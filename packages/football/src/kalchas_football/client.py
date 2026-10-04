"""APIFootball.com client (apiv3.apifootball.com).

Kalchas has always used this provider — not RapidAPI API-Football.
Auth is ``APIkey`` query param; endpoints are ``action=get_events`` /
``action=get_statistics`` / ``action=get_odds``. The Worldwide plan
allows 1000 calls per hour **per endpoint**.
"""

from __future__ import annotations

import logging
import os
import re
import time
import unicodedata
from dataclasses import dataclass, field, replace
from typing import Any

import httpx

logger = logging.getLogger("kalchas.football")

DEFAULT_BASE_URL = "https://apiv3.apifootball.com/"
# Worldwide plan: 1000 calls/hour/endpoint. Limiters are keyed by ``action``.
DEFAULT_REQUESTS_PER_HOUR = 1000


class RateLimitBudgetExceeded(RuntimeError):
    """Hourly HTTP budget is exhausted; the caller must skip this request."""

    def __init__(self, sleep_for: float) -> None:
        super().__init__(f"hourly HTTP budget exhausted; would block {sleep_for:.1f}s")
        self.sleep_for = sleep_for


@dataclass
class RateLimiter:
    """Sliding-window limiter (requests per hour). Never sleeps; callers skip."""

    requests_per_hour: int = DEFAULT_REQUESTS_PER_HOUR
    _times: list[float] = field(default_factory=list)

    def wait(self) -> None:
        now = time.monotonic()
        self._times = [t for t in self._times if now - t < 3600]
        if len(self._times) >= self.requests_per_hour:
            oldest = min(self._times) if self._times else now
            sleep_for = 3600 - (now - oldest) + 0.05
            logger.warning(
                "rate limit: skipping request (would sleep %.1fs)",
                sleep_for,
            )
            raise RateLimitBudgetExceeded(max(sleep_for, 0.0))
        self._times.append(time.monotonic())


@dataclass
class LiveMatch:
    match_id: str
    home_team: str
    away_team: str
    home_team_id: int
    away_team_id: int
    minute: int
    home_score: int
    away_score: int
    status_short: str
    minute_display: str = ""
    league_name: str = ""
    league_id: int | None = None
    country_name: str = ""
    country_logo: str = ""
    home_team_logo: str = ""
    away_team_logo: str = ""
    raw: dict[str, Any] = field(default_factory=dict)


def https_asset_url(value: Any) -> str:
    """Keep the live-row badge URL. https + collapse ``badges//``."""
    text = str(value or "").strip()
    if text.startswith("http://"):
        text = "https://" + text[len("http://") :]
    if not text.startswith("https://"):
        return ""
    while "/badges//" in text:
        text = text.replace("/badges//", "/badges/")
    return text


def apifootball_badge_slug(team_name: str) -> str:
    """Badge filename slug. Leading ``D.`` / ``C.D.`` initials are not in the file."""
    slug = unicodedata.normalize("NFD", (team_name or "").lower())
    slug = "".join(c for c in slug if unicodedata.category(c) != "Mn")
    while True:
        stripped = re.sub(r"^[a-z]\.\s*", "", slug)
        if stripped == slug:
            break
        slug = stripped
    return re.sub(r"[^a-z0-9]+", "-", slug).strip("-")


def apifootball_badge_url(team_id: int | None, team_name: str) -> str | None:
    """Same badge URL shape 2.2 used, with abbreviated initials stripped."""
    if team_id is None or int(team_id) <= 0:
        return None
    slug = apifootball_badge_slug(team_name)
    if not slug:
        return None
    return f"https://apiv3.apifootball.com/badges/{int(team_id)}_{slug}.jpg"


def _coerce_int(value: Any, default: int = 0) -> int:
    if value is None:
        return default
    text = str(value).strip().replace("%", "")
    if not text or text.lower() in {"none", "null", "-"}:
        return default
    try:
        return int(float(text))
    except (TypeError, ValueError):
        return default


_COMMENT_END = re.compile(
    r"^(full time|half time|finished|end of|penalt|\s*ht\s*|\s*ft\s*)$",
    re.I,
)


def _added_from_event_time(time_str: Any, base: int) -> int:
    """``90+3`` or integer ``93`` → 3 when ``base`` is 90. Caps added at 15."""
    text = str(time_str or "").strip().replace("′", "'").rstrip("'")
    if "+" in text:
        left, right = text.split("+", 1)
        try:
            token_base = int(left.strip())
        except ValueError:
            return 0
        if token_base != base:
            return 0
        added_part = right.strip()
        added = int(added_part) if added_part.isdigit() else 0
        return added if 0 < added <= 15 else 0
    if text.isdigit():
        minute = int(text)
        if base < minute <= base + 15:
            return minute - base
    return 0


def _event_times(row: dict[str, Any]) -> list[Any]:
    times: list[Any] = []
    for goal in row.get("goalscorer") or []:
        if isinstance(goal, dict):
            times.append(goal.get("time"))
    for card in row.get("cards") or []:
        if isinstance(card, dict):
            times.append(card.get("time"))
    subs = row.get("substitutions")
    if isinstance(subs, dict):
        for side in ("home", "away"):
            for item in subs.get(side) or []:
                if isinstance(item, dict):
                    times.append(item.get("time"))
    elif isinstance(subs, list):
        for item in subs:
            if isinstance(item, dict):
                times.append(item.get("time"))
    return times


def event_stoppage_added(row: dict[str, Any], base: int) -> int:
    """Largest ``base+n`` attached to a goal, card, or substitution on this row."""
    added = 0
    for token in _event_times(row):
        added = max(added, _added_from_event_time(token, base))
    return added


def advance_stoppage_clock(
    elapsed: int,
    status_short: str,
    display: str,
    *,
    event_added: int = 0,
    comment_elapsed: int | None = None,
) -> tuple[int, str, str]:
    """Fill a bare ``90+`` / ``45+`` clock from events or comment MM:SS.

    Does not invent the referee's announced total. A status that already has
    a digit (``90+3``) is kept unless a later source is strictly ahead.
    """
    text = (display or "").strip()
    short = (status_short or "").strip().upper()
    if "+" not in text:
        if comment_elapsed is None:
            return elapsed, status_short, display
        if short == "1H" and comment_elapsed > 45:
            added = comment_elapsed - 45
            return max(elapsed, comment_elapsed), status_short, f"45+{added}"
        if short == "2H" and comment_elapsed > 90:
            added = comment_elapsed - 90
            return max(elapsed, comment_elapsed), status_short, f"90+{added}"
        return elapsed, status_short, display
    base_s, _, added_s = text.partition("+")
    if not base_s.isdigit():
        return elapsed, status_short, display
    base = int(base_s)
    best = elapsed if elapsed >= base else base
    if added_s.strip().isdigit():
        best = max(best, base + int(added_s.strip()))
    if event_added > 0:
        best = max(best, base + event_added)
    if comment_elapsed is not None and comment_elapsed >= base:
        best = max(best, comment_elapsed)
    added = best - base
    return best, status_short, f"{base}+{added}" if added else f"{base}+"


_FIRST_HALF_LIVE = frozenset({"1H", "LIVE", "INP"})
_PERIOD_BREAKS = frozenset({"HT", "BT"})
_MAX_FIRST_HALF_ADDED = 15


def hold_playing_period(match: LiveMatch, *, previous_status: str | None) -> LiveMatch:
    """Keep 1H added time in the first half until the feed actually sends HT.

    A bare ``47`` from the provider is elapsed clock, not 2H. Flipping status
    at 46' expires ``expire_at_half_end`` alerts while 45+n is still running.
    """
    prev = (previous_status or "").strip().upper()
    short = (match.status_short or "").strip().upper()
    minute = int(match.minute or 0)
    if short in _PERIOD_BREAKS or (prev in _PERIOD_BREAKS and short == "2H"):
        return match
    if prev in _FIRST_HALF_LIVE and short == "2H" and minute <= 45 + _MAX_FIRST_HALF_ADDED:
        added = max(0, minute - 45)
        display = f"45+{added}" if added else (match.minute_display or "45+")
        return replace(match, status_short="1H", minute_display=display)
    if prev == "2H" and short == "ET" and minute <= 105:
        added = max(0, minute - 90)
        display = f"90+{added}" if added else (match.minute_display or "90+")
        return replace(match, status_short="2H", minute_display=display)
    return match


def comment_elapsed_from_live_comments(payload: Any) -> dict[str, int]:
    """Index ``match_id`` → elapsed minute from the last in-play comment ``MM:SS``.

    Skips ``Full time`` / ``Half time`` rows so a trailing ``90:00`` end marker
    does not rewind the clock. There is no announced-added-minutes field.
    """
    rows: list[Any]
    if isinstance(payload, dict):
        rows = list(payload.values())
    elif isinstance(payload, list):
        rows = payload
    else:
        return {}
    out: dict[str, int] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        match_id = str(row.get("match_id") or "")
        comments = row.get("live_comments")
        if not match_id or not isinstance(comments, list):
            continue
        elapsed: int | None = None
        for item in comments:
            if not isinstance(item, dict):
                continue
            text = str(item.get("text") or "").strip()
            if _COMMENT_END.match(text):
                continue
            stamp = str(item.get("time") or "").strip()
            if ":" not in stamp:
                continue
            minute_s = stamp.split(":", 1)[0].strip()
            if not minute_s.isdigit():
                continue
            elapsed = int(minute_s)
        if elapsed is not None:
            out[match_id] = elapsed
    return out


def _parse_elapsed(match_status: Any) -> tuple[int, str, str]:
    """Return (elapsed_minute, status_short, display) from apifootball match_status.

    Display keeps stoppage as ``45+2`` / ``90+``. Elapsed is still the integer
    strategies use (47 / 90).
    """
    status = str(match_status or "").strip().replace("′", "'")
    if status.endswith("'"):
        status = status[:-1].strip()
    mapping = {
        "Finished": "FT",
        "After ET": "AET",
        "After Pen.": "PEN",
        "Half Time": "HT",
        "Postponed": "PST",
        "Cancelled": "CANC",
        "Awarded": "AWD",
    }
    if status in mapping:
        return 0, mapping[status], ""
    if "+" in status:
        try:
            parts = status.split("+", 1)
            base = int(parts[0].strip())
            added_part = parts[1].strip() if len(parts) > 1 else ""
            added = int(added_part) if added_part.isdigit() else 0
            elapsed = base + added
            display = f"{base}+{added}" if added else f"{base}+"
            short = "1H" if base <= 45 else "2H" if base <= 90 else "ET"
            return elapsed, short, display
        except ValueError:
            return 0, status or "UNK", ""
    if status.isdigit():
        elapsed = int(status)
        short = "1H" if elapsed <= 45 else "2H" if elapsed <= 90 else "ET"
        return elapsed, short, str(elapsed)
    return 0, status or "UNK", ""


def live_match_from_event(row: dict[str, Any]) -> LiveMatch | None:
    match_id = str(row.get("match_id") or "")
    if not match_id:
        return None
    elapsed, status_short, minute_display = _parse_elapsed(row.get("match_status"))
    if "+" in (minute_display or ""):
        base_s = minute_display.split("+", 1)[0]
        event_added = event_stoppage_added(row, int(base_s)) if base_s.isdigit() else 0
        elapsed, status_short, minute_display = advance_stoppage_clock(
            elapsed,
            status_short,
            minute_display,
            event_added=event_added,
        )
    parsed_league_id = _coerce_int(row.get("league_id"))
    return LiveMatch(
        match_id=match_id,
        home_team=str(row.get("match_hometeam_name") or ""),
        away_team=str(row.get("match_awayteam_name") or ""),
        home_team_id=_coerce_int(row.get("match_hometeam_id")),
        away_team_id=_coerce_int(row.get("match_awayteam_id")),
        minute=elapsed,
        home_score=_coerce_int(row.get("match_hometeam_score")),
        away_score=_coerce_int(row.get("match_awayteam_score")),
        status_short=status_short,
        minute_display=minute_display,
        league_name=str(row.get("league_name") or ""),
        league_id=parsed_league_id if parsed_league_id else None,
        country_name=str(row.get("country_name") or ""),
        country_logo=str(row.get("country_logo") or ""),
        home_team_logo=https_asset_url(row.get("team_home_badge") or row.get("home_team_logo")),
        away_team_logo=https_asset_url(row.get("team_away_badge") or row.get("away_team_logo")),
        raw=row,
    )


# Labels in priority order. "Off Target" includes blocked shots while
# "Shots Off Goal" does not, so they are not interchangeable; 2.2 calibrated
# on "On Target"/"Off Target" and only fell back to the others when absent.
_STAT_LABELS: dict[str, tuple[str, ...]] = {
    "on_target": ("on_target", "shots_on_target", "shots_on_goal"),
    "off_target": ("off_target", "shots_off_target", "shots_off_goal"),
    "corners": ("corners", "corner_kicks"),
    "attacks": ("attacks",),
    "dangerous_attacks": ("dangerous_attacks",),
    "ball_possession": ("ball_possession", "possession"),
}


def statistics_to_team_dict(raw_stats: list[Any]) -> dict[str, Any]:
    """Map apifootball statistics[] into the home_team/away_team shape core parses."""
    by_label: dict[str, dict[str, Any]] = {}
    for stat in raw_stats or []:
        if not isinstance(stat, dict):
            continue
        label = "_".join(str(stat.get("type") or "").lower().split())
        if label and label not in by_label:
            by_label[label] = stat
    home: dict[str, Any] = {}
    away: dict[str, Any] = {}
    for target, labels in _STAT_LABELS.items():
        found = next((lbl for lbl in labels if lbl in by_label), None)
        if found is None:
            continue
        home[target] = _coerce_int(by_label[found].get("home"))
        away[target] = _coerce_int(by_label[found].get("away"))
    return {"home_team": home, "away_team": away}


def statistics_from_event(row: Any) -> dict[str, Any] | None:
    """Stats embedded in a ``get_events`` row, or None when the row carries none.

    Live ``get_events`` rows include full-match ``statistics`` (with Attacks and
    Dangerous Attacks, which ``get_statistics`` omits), so a separate
    per-match request is only needed as a fallback.
    """
    stats = row.get("statistics") if isinstance(row, dict) else None
    if not isinstance(stats, list) or not stats:
        return None
    processed = statistics_to_team_dict(stats)
    processed["match_id"] = str(row.get("match_id") or "")
    return processed


def lineup_from_event(row: Any) -> dict[str, Any]:
    """Starting XI / bench / coach as carried by ``get_events`` and the live WS.

    Same object as ``action=get_lineups``. Calling that endpoint per match is
    redundant when the live row already includes ``lineup``.
    """
    lineup = row.get("lineup") if isinstance(row, dict) else None
    return dict(lineup) if isinstance(lineup, dict) else {}


def substitutions_from_event(row: Any) -> dict[str, Any]:
    """Home/away substitution lists from a live ``get_events`` / WS row."""
    substitutions = row.get("substitutions") if isinstance(row, dict) else None
    return dict(substitutions) if isinstance(substitutions, dict) else {}


def _odd_float(value: Any) -> float | None:
    text = str(value or "").strip()
    if not text or text in {"-", "null", "None"}:
        return None
    try:
        parsed = float(text)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


_FT_1X2_MARKETS = frozenset(
    {
        "match winner",
        "1x2",
        "1 x 2",
        "full time result",
        "fulltime result",
        "ft result",
        "match result",
        "home/draw/away",
        "home / draw / away",
        "home-draw-away",
        "3way result",
        "3-way",
        "to win match",
        "win-draw-win",
    }
)


def _triple_1x2(block: Any) -> dict[str, float] | None:
    if not isinstance(block, dict):
        return None
    home = _odd_float(block.get("home"))
    away = _odd_float(block.get("away"))
    if home is None or away is None:
        return None
    parsed: dict[str, float] = {"home": home, "away": away}
    draw = _odd_float(block.get("draw"))
    if draw is not None:
        parsed["draw"] = draw
    return parsed


def _kickoff_from_record(record: Any) -> dict[str, float] | None:
    if not isinstance(record, dict):
        return None
    nested = _triple_1x2(record.get("kickoff"))
    if nested:
        return nested
    return _triple_1x2(record)


def compose_odds_record(
    *,
    kickoff: dict[str, float] | None = None,
    live: dict[str, float] | None = None,
) -> dict[str, Any] | None:
    """Persist shape: frozen kickoff 1X2 at top level, plus ``kickoff`` / ``live``."""
    kick = _triple_1x2(kickoff)
    inplay = _triple_1x2(live)
    if not kick and not inplay:
        return None
    out: dict[str, Any] = {}
    if kick:
        out.update(kick)
        out["kickoff"] = dict(kick)
    if inplay:
        out["live"] = dict(inplay)
    return out


def merge_odds_records(previous: Any, incoming: Any) -> dict[str, Any]:
    """Keep the first kickoff 1X2; replace live 1X2 when a new complete line arrives."""
    prev = dict(previous) if isinstance(previous, dict) else {}
    inc = dict(incoming) if isinstance(incoming, dict) else {}
    kickoff = _kickoff_from_record(prev) or _kickoff_from_record(inc)
    live = _triple_1x2(inc.get("live")) or _triple_1x2(prev.get("live"))
    return compose_odds_record(kickoff=kickoff, live=live) or {}


def odds_1x2_from_provider_rows(rows: Any) -> dict[str, dict[str, float]]:
    """Index ``match_id`` → ``{home, draw, away}`` from ``action=get_odds``.

    Provider rows use ``odd_1`` / ``odd_x`` / ``odd_2``. Several bookmakers can
    share a match_id; the first complete 1X2 is kept so this stays one call
    per refresh, not one call per match.
    """
    out: dict[str, dict[str, float]] = {}
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        match_id = str(row.get("match_id") or "")
        if not match_id or match_id in out:
            continue
        parsed = _triple_1x2(
            {
                "home": row.get("odd_1"),
                "draw": row.get("odd_x"),
                "away": row.get("odd_2"),
            }
        )
        if parsed is None:
            continue
        out[match_id] = parsed
    return out


def _is_ft_1x2_market(name: str) -> bool:
    n = " ".join(name.lower().replace("/", " ").replace("-", " ").split())
    compact = n.replace(" ", "")
    if any(
        token in n
        for token in (
            "half",
            "next goal",
            "which team",
            "correct score",
            "double chance",
            "draw no bet",
            "to qualify",
            "how many",
        )
    ):
        return False
    if n in _FT_1X2_MARKETS or compact in {"1x2", "matchwinner"}:
        return True
    return "1x2" in compact


def _1x2_slot(label: str, home_name: str, away_name: str) -> str | None:
    text = " ".join(label.lower().split())
    if text in {"home", "1", "h", "home team"}:
        return "home"
    if text in {"draw", "x", "d", "tie"}:
        return "draw"
    if text in {"away", "2", "a", "away team"}:
        return "away"
    if home_name and text == home_name:
        return "home"
    if away_name and text == away_name:
        return "away"
    return None


def _1x2_from_live_odds_list(
    live_odds: Any,
    *,
    home_name: str,
    away_name: str,
) -> dict[str, float] | None:
    if not isinstance(live_odds, list):
        return None
    collected: dict[str, float] = {}
    for item in live_odds:
        if not isinstance(item, dict):
            continue
        if str(item.get("suspended") or "").strip().lower() in {"yes", "true", "1"}:
            continue
        if not _is_ft_1x2_market(str(item.get("odd_name") or "")):
            continue
        slot = _1x2_slot(str(item.get("type") or ""), home_name, away_name)
        value = _odd_float(item.get("value"))
        if slot is None or value is None or slot in collected:
            continue
        collected[slot] = value
    return _triple_1x2(collected)


def odds_1x2_from_live_comments(payload: Any) -> dict[str, dict[str, float]]:
    """Index ``match_id`` → live 1X2 from ``action=get_live_odds_commnets``."""
    rows: list[Any]
    if isinstance(payload, dict):
        rows = list(payload.values())
    elif isinstance(payload, list):
        rows = payload
    else:
        return {}
    out: dict[str, dict[str, float]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        match_id = str(row.get("match_id") or "")
        if not match_id or match_id in out:
            continue
        direct = _triple_1x2(
            {
                "home": row.get("odd_1"),
                "draw": row.get("odd_x"),
                "away": row.get("odd_2"),
            }
        )
        if direct is not None:
            out[match_id] = direct
            continue
        parsed = _1x2_from_live_odds_list(
            row.get("live_odds"),
            home_name=str(row.get("match_hometeam_name") or "").strip().lower(),
            away_name=str(row.get("match_awayteam_name") or "").strip().lower(),
        )
        if parsed is not None:
            out[match_id] = parsed
    return out


def parse_h2h_meetings(data: Any) -> list[dict[str, Any]]:
    """Flatten ``get_H2H`` into canonical meeting dicts.

    Provider shape is ``{firstTeam_VS_secondTeam: [...]}``. A list of match
    rows is also accepted. Goal minutes are copied when the row already
    carries ``goalscorer`` so timing can be computed without extra HTTP.
    """
    rows: list[Any] = []
    if isinstance(data, dict):
        if data.get("error"):
            return []
        block = data.get("firstTeam_VS_secondTeam")
        if isinstance(block, list):
            rows = block
        elif isinstance(data.get("response"), dict):
            inner = data["response"].get("firstTeam_VS_secondTeam")
            if isinstance(inner, list):
                rows = inner
    elif isinstance(data, list):
        rows = data

    out: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        match_id = str(row.get("match_id") or "").strip()
        home_id = _coerce_int(row.get("match_hometeam_id") or row.get("home_team_id"))
        away_id = _coerce_int(row.get("match_awayteam_id") or row.get("away_team_id"))
        if not match_id and not home_id and not away_id:
            continue
        goals = _h2h_goal_events(row)
        out.append(
            {
                "match_id": match_id,
                "home_team": str(row.get("match_hometeam_name") or row.get("home_team") or ""),
                "away_team": str(row.get("match_awayteam_name") or row.get("away_team") or ""),
                "home_team_id": home_id,
                "away_team_id": away_id,
                "home_score": _coerce_int(row.get("match_hometeam_score", row.get("home_score"))),
                "away_score": _coerce_int(row.get("match_awayteam_score", row.get("away_score"))),
                "match_date": str(row.get("match_date") or ""),
                "league_name": str(row.get("league_name") or ""),
                "league_id": _coerce_int(row.get("league_id")),
                "goal_events": goals,
            }
        )
    return out


def _h2h_goal_events(row: dict[str, Any]) -> list[dict[str, Any]]:
    raw = row.get("goalscorer") or row.get("goal_events") or []
    if not isinstance(raw, list):
        return []
    events: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        minute, _status, _display = _parse_elapsed(item.get("time") or item.get("minute"))
        if minute <= 0:
            continue
        home_scorer = str(item.get("home_scorer") or "").strip()
        away_scorer = str(item.get("away_scorer") or "").strip()
        side = "home" if home_scorer else "away" if away_scorer else str(item.get("team") or "")
        events.append({"minute": minute, "team": side, "side": side})
    return events


class FootballAPIClient:
    """Thin httpx client for apiv3.apifootball.com."""

    def __init__(
        self,
        api_key: str | None = None,
        *,
        base_url: str | None = None,
        requests_per_hour: int | None = None,
        timeout: float = 30.0,
    ) -> None:
        self.api_key = (
            api_key or os.environ.get("API_FOOTBALL_KEY") or os.environ.get("FOOTBALL_API_KEY", "")
        )
        if not self.api_key:
            raise ValueError("API_FOOTBALL_KEY (or FOOTBALL_API_KEY) is required")
        self.base_url = (
            base_url or os.environ.get("FOOTBALL_API_BASE") or DEFAULT_BASE_URL
        ).rstrip("/") + "/"
        per_hour = requests_per_hour
        if per_hour is None:
            per_hour = int(
                os.environ.get("FOOTBALL_REQUESTS_PER_HOUR") or DEFAULT_REQUESTS_PER_HOUR
            )
        # Provider quota is per action (get_events / get_statistics / get_odds).
        self._per_hour = per_hour
        self._limiters: dict[str, RateLimiter] = {}
        self._client = httpx.Client(
            base_url=self.base_url,
            headers={
                "User-Agent": "Kalchas-3.0",
                "Accept": "application/json",
            },
            timeout=timeout,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> FootballAPIClient:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def limiter_for(self, action: str) -> RateLimiter:
        key = action or "_"
        bucket = self._limiters.get(key)
        if bucket is None:
            bucket = RateLimiter(requests_per_hour=self._per_hour)
            self._limiters[key] = bucket
        return bucket

    @property
    def limiter(self) -> RateLimiter:
        """get_events bucket — tests and callers that still use ``.limiter``."""
        return self.limiter_for("get_events")

    def _get(self, action: str, params: dict[str, Any] | None = None) -> Any:
        self.limiter_for(action).wait()
        query = {"action": action, "APIkey": self.api_key}
        if params:
            query.update(params)
        response = self._client.get("", params=query)
        if response.status_code == 403:
            raise PermissionError("apifootball.com returned 403 — check API_FOOTBALL_KEY")
        response.raise_for_status()
        data = response.json()
        # Error payloads are objects with an error field, not a match list.
        if isinstance(data, dict) and data.get("error"):
            message = str(data.get("message") or data.get("error") or "")
            lowered = message.lower()
            # Quiet windows: provider returns this instead of [].
            if "no event found" in lowered or "no odds" in lowered:
                return []
            raise RuntimeError(f"apifootball.com error: {data.get('message') or data}")
        return data

    def get_live_fixtures(self) -> list[LiveMatch]:
        """Live matches via ``action=get_events&match_live=1``.

        apifootball sometimes still returns freshly finished rows under
        ``match_live=1``. Keep them so the scanner can persist ``FT`` and
        the live API can drop them from the board.
        """
        try:
            data = self._get("get_events", {"match_live": "1"})
        except RateLimitBudgetExceeded:
            logger.warning("skipping get_events; hourly HTTP budget exhausted")
            return []
        rows = data if isinstance(data, list) else []
        out: list[LiveMatch] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            match = live_match_from_event(row)
            if match is None:
                continue
            out.append(match)
        return out

    def get_fixture_statistics(self, match_id: str | int) -> dict[str, Any]:
        """``action=get_statistics`` → ``{home_team, away_team}`` for core parse."""
        mid = str(match_id)
        data = self._get("get_statistics", {"match_id": mid})
        block: Any = {}
        if isinstance(data, dict):
            block = data.get(mid) or data.get(int(mid) if mid.isdigit() else mid) or {}
            if not block and "statistics" in data:
                block = data
        elif isinstance(data, list) and data:
            # Some responses wrap oddly; tolerate a single-element list of dicts.
            first = data[0]
            if isinstance(first, dict):
                block = first.get(mid) or first
        stats = block.get("statistics") if isinstance(block, dict) else None
        if not isinstance(stats, list):
            return {"home_team": {}, "away_team": {}, "match_id": mid}
        processed = statistics_to_team_dict(stats)
        processed["match_id"] = mid
        return processed

    def get_fixture_events(self, match_id: str | int) -> dict[str, Any]:
        """``action=get_events&match_id=`` — raw match row (goalscorer + cards)."""
        try:
            data = self._get("get_events", {"match_id": str(match_id)})
        except RateLimitBudgetExceeded:
            logger.warning("skipping get_events for %s; hourly HTTP budget exhausted", match_id)
            return {}
        if isinstance(data, list) and data:
            first = data[0]
            return first if isinstance(first, dict) else {}
        if isinstance(data, dict) and "match_id" in data:
            return data
        return {}

    def get_odds_1x2_today(self) -> dict[str, dict[str, float]]:
        """One ``get_odds`` call for yesterday–tomorrow, keyed by match_id.

        Live/WS rows do not include 1X2. Date-range fetch is the documented
        path; per-match ``match_id`` queries would burn the hourly budget.
        Tomorrow is included so UTC hosts still see evening kickoffs in UTC+3.
        """
        from datetime import date, timedelta

        today = date.today()
        start = today - timedelta(days=1)
        end = today + timedelta(days=1)
        try:
            data = self._get("get_odds", {"from": start.isoformat(), "to": end.isoformat()})
        except RateLimitBudgetExceeded:
            logger.warning("skipping get_odds; hourly HTTP budget exhausted")
            return {}
        return odds_1x2_from_provider_rows(data)

    def get_live_odds_comments_bundle(
        self,
    ) -> tuple[dict[str, dict[str, float]], dict[str, int]]:
        """One ``get_live_odds_commnets`` call: 1X2 plus comment elapsed clocks."""
        try:
            data = self._get("get_live_odds_commnets")
        except RateLimitBudgetExceeded:
            logger.warning("skipping get_live_odds_commnets; hourly HTTP budget exhausted")
            return {}, {}
        return odds_1x2_from_live_comments(data), comment_elapsed_from_live_comments(data)

    def get_live_odds_1x2(self) -> dict[str, dict[str, float]]:
        """One ``get_live_odds_commnets`` call; keep only full-time 1X2 lines."""
        odds, _clocks = self.get_live_odds_comments_bundle()
        return odds

    def get_head_to_head(
        self,
        team1_id: int,
        team2_id: int,
        *,
        last: int = 10,
    ) -> list[dict[str, Any]]:
        """``action=get_H2H`` for a pair of team IDs. Newest ``last`` meetings."""
        try:
            t1 = int(team1_id)
            t2 = int(team2_id)
        except (TypeError, ValueError):
            return []
        if t1 <= 0 or t2 <= 0 or t1 == t2:
            return []
        data = self._get("get_H2H", {"firstTeamId": t1, "secondTeamId": t2})
        meetings = parse_h2h_meetings(data)
        meetings.sort(key=lambda row: str(row.get("match_date") or ""), reverse=True)
        if last > 0:
            return meetings[:last]
        return meetings
