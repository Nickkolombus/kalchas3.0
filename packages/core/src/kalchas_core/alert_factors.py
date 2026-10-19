"""Fire-time board snapshot and pattern buckets for alert results.

Keeps a compact copy of the live board on the alert payload so later
Confirmed / Expired rows can be grouped by clock, score, odds, TSLG, weekday,
hour, league, and country -- 3.0's version of 2.2's `alerts-history.html`
admin page, which grouped `alerts_history` by the same dimensions via
`EXTRACT(DOW/HOUR FROM alert_time)` and `league_name`/`country_name`.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

from kalchas_core.alert_outcomes.score import parse_score
from kalchas_core.sweet_spot import SweetSpotWindows, in_sweet_spot

BOARD_KEYS: tuple[str, ...] = (
    "rule_of_three",
    "pressure_index",
    "delta_5min",
    "delta_goal",
    "npei",
    "omega",
    "kscore",
)

CSV_COLUMNS: tuple[str, ...] = (
    "result",
    "strategy",
    "side",
    "value",
    "minute",
    "status",
    "half",
    "score",
    "home",
    "away",
    "league",
    "country",
    "sweet_spot",
    "tslg_home",
    "tslg_away",
    "odds_home",
    "odds_draw",
    "odds_away",
    "live_home",
    "live_away",
    "sot_home",
    "sot_away",
    "sofft_home",
    "sofft_away",
    "da_home",
    "da_away",
    "att_home",
    "att_away",
    "crn_home",
    "crn_away",
    "pos_home",
    "pos_away",
    "urg_home",
    "urg_away",
    "d5_home",
    "d5_away",
    "d10_home",
    "d10_away",
    "lbar_home",
    "lbar_away",
    "phi_home",
    "phi_away",
    "omega_home",
    "omega_away",
    "k_home",
    "k_away",
    "k_match",
    "also_firing",
    "settle_score",
    "settle_minute",
)


def _finite(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number:
        return None
    return number


def _int(value: Any) -> int | None:
    number = _finite(value)
    if number is None:
        return None
    return int(number)


def _pair(raw: Any) -> dict[str, float | None]:
    if not isinstance(raw, Mapping):
        return {"home": None, "away": None}
    return {"home": _finite(raw.get("home")), "away": _finite(raw.get("away"))}


def _team_cell(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, Mapping):
        return {"home": None, "away": None, "home_fired": False, "away_fired": False}
    return {
        "home": _finite(raw.get("home")),
        "away": _finite(raw.get("away")),
        "home_fired": bool(raw.get("home_fired") or raw.get("ht")),
        "away_fired": bool(raw.get("away_fired") or raw.get("at")),
        **(
            {"match": _finite(raw.get("match"))}
            if raw.get("match") is not None or raw.get("m") is not None
            else {}
        ),
    }


def compact_board(snapshot: Mapping[str, Any] | None) -> dict[str, Any]:
    """Shrink board_snapshot strategy_status to home/away values + fire flags."""
    status = (snapshot or {}).get("strategy_status") or {}
    out: dict[str, Any] = {}
    for key in BOARD_KEYS:
        block = status.get(key) if isinstance(status, Mapping) else None
        if not isinstance(block, Mapping):
            continue
        teams = block.get("teams") if isinstance(block.get("teams"), Mapping) else {}
        home = teams.get("home") if isinstance(teams.get("home"), Mapping) else {}
        away = teams.get("away") if isinstance(teams.get("away"), Mapping) else {}
        row: dict[str, Any] = {
            "home": _finite(home.get("value")),
            "away": _finite(away.get("value")),
            "home_fired": bool(home.get("triggered")),
            "away_fired": bool(away.get("triggered")),
        }
        if block.get("match") is not None:
            row["match"] = _finite(block.get("match"))
        out[key] = row
    return out


def _kickoff_odds(raw: Any) -> dict[str, float | None]:
    if not isinstance(raw, Mapping):
        return {"home": None, "draw": None, "away": None}
    kick = raw.get("kickoff") if isinstance(raw.get("kickoff"), Mapping) else raw
    return {
        "home": _finite(kick.get("home") if isinstance(kick, Mapping) else None),
        "draw": _finite(kick.get("draw") if isinstance(kick, Mapping) else None),
        "away": _finite(kick.get("away") if isinstance(kick, Mapping) else None),
    }


def _live_odds(raw: Any) -> dict[str, float | None]:
    if not isinstance(raw, Mapping):
        return {"home": None, "away": None}
    live = raw.get("live") if isinstance(raw.get("live"), Mapping) else {}
    return {
        "home": _finite(live.get("home")),
        "away": _finite(live.get("away")),
    }


def _half(status: str | None, minute: int | None) -> str | None:
    token = (status or "").upper()
    if token in {"1H", "HT"}:
        return "1H"
    if token in {"2H", "ET", "P", "PEN", "FT", "AET"}:
        return "2H"
    if minute is None:
        return None
    return "1H" if minute <= 45 else "2H"


def _score_state(score: str | None, team: str | None) -> str | None:
    if not score:
        return None
    home, away = parse_score(score)
    if home == 0 and away == 0:
        return "0-0"
    if team == "home":
        if home > away:
            return "leading"
        if home < away:
            return "trailing"
        return "level"
    if team == "away":
        if away > home:
            return "leading"
        if away < home:
            return "trailing"
        return "level"
    if home == away:
        return "level"
    return "uneven"


def _clock_bucket(minute: int | None) -> str | None:
    if minute is None:
        return None
    if minute <= 15:
        return "1-15"
    if minute <= 30:
        return "16-30"
    if minute <= 45:
        return "31-45"
    if minute <= 60:
        return "46-60"
    if minute <= 75:
        return "61-75"
    return "76+"


def _tslg_bucket(tslg_min: int | None, no_goal: bool) -> str:
    if no_goal:
        return "no goal yet"
    if tslg_min is None:
        return "unknown"
    if tslg_min < 10:
        return "0-9'"
    if tslg_min < 20:
        return "10-19'"
    return "20'+"


def _odds_bucket(price: float | None) -> str:
    if price is None:
        return "unknown"
    if price < 2:
        return "favourite <2"
    if price <= 3.5:
        return "mid 2-3.5"
    return "dog >3.5"


_WEEKDAY_LABELS: tuple[str, ...] = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
_HOUR_LABELS: tuple[str, ...] = tuple(f"{hour:02d}:00" for hour in range(24))


def _parse_created_at(created_at: Any) -> datetime | None:
    if not created_at:
        return None
    try:
        return datetime.fromisoformat(str(created_at).replace("Z", "+00:00"))
    except ValueError:
        return None


def _weekday_bucket(created_at: Any) -> str | None:
    """Mon-Sun in the timezone the timestamp carries (created_at is stored UTC)."""
    at = _parse_created_at(created_at)
    return _WEEKDAY_LABELS[at.weekday()] if at else None


def _hour_bucket(created_at: Any) -> str | None:
    at = _parse_created_at(created_at)
    return f"{at.hour:02d}:00" if at else None


def _tslg_min(home: int | None, away: int | None) -> int | None:
    values = [item for item in (home, away) if item is not None]
    if not values:
        return None
    return min(values)


def _board_side(board: Mapping[str, Any], key: str) -> dict[str, float | None]:
    row = board.get(key) if isinstance(board.get(key), Mapping) else {}
    if not isinstance(row, Mapping):
        return {"home": None, "away": None}
    return {"home": _finite(row.get("home")), "away": _finite(row.get("away"))}


def also_firing(board: Mapping[str, Any], strategy: str | None, team: str | None) -> list[str]:
    extra: list[str] = []
    flag = "home_fired" if team == "home" else "away_fired" if team == "away" else None
    for key in BOARD_KEYS:
        if key == strategy:
            continue
        row = board.get(key)
        if not isinstance(row, Mapping):
            continue
        if flag and row.get(flag):
            extra.append(key)
        elif flag is None and (row.get("home_fired") or row.get("away_fired")):
            extra.append(key)
    return extra


def factors_from_payload(
    payload: Mapping[str, Any] | None,
    *,
    strategy: str | None = None,
    team: str | None = None,
    minute: int | None = None,
    score: str | None = None,
) -> dict[str, Any]:
    """Normalize stored payload (old stats-only or new board snapshot)."""
    raw = payload if isinstance(payload, Mapping) else {}
    board = raw.get("board") if isinstance(raw.get("board"), Mapping) else {}
    tslg_home = _int(raw.get("tslg_home"))
    tslg_away = _int(raw.get("tslg_away"))
    tslg_min = _tslg_min(tslg_home, tslg_away)
    no_goal = tslg_home is None and tslg_away is None
    status = str(raw.get("status_short") or raw.get("status") or "") or None
    clock = minute if minute is not None else _int(raw.get("minute"))
    kick = _kickoff_odds(raw.get("odds"))
    live = _live_odds(raw.get("odds"))
    side = (team or str(raw.get("team") or "") or None) or None
    if side:
        side = side.lower()
    trigger_odds = kick.get("home") if side == "home" else kick.get("away") if side == "away" else None
    sweet = raw.get("sweet_spot")
    sweet_spot = None if sweet is None else bool(sweet)
    urg = _board_side(board, "rule_of_three")
    d5 = _board_side(board, "delta_5min")
    d10 = _board_side(board, "pressure_index")
    lbar = _board_side(board, "delta_goal")
    phi = _board_side(board, "npei")
    omega = _board_side(board, "omega")
    k = _board_side(board, "kscore")
    k_match = None
    k_row = board.get("kscore") if isinstance(board.get("kscore"), Mapping) else {}
    if isinstance(k_row, Mapping):
        k_match = _finite(k_row.get("match"))
    return {
        "status": status,
        "country": str(raw.get("country") or "") or None,
        "sweet_spot": sweet_spot,
        "half": _half(status, clock),
        "tslg": str(raw.get("tslg") or "") or None,
        "tslg_home": tslg_home,
        "tslg_away": tslg_away,
        "tslg_min": tslg_min,
        "odds_home": kick["home"],
        "odds_draw": kick["draw"],
        "odds_away": kick["away"],
        "live_home": live["home"],
        "live_away": live["away"],
        "trigger_odds": trigger_odds,
        "sot": _pair(raw.get("sot")),
        "sofft": _pair(raw.get("sofft")),
        "da": _pair(raw.get("da")),
        "attacks": _pair(raw.get("attacks")),
        "corners": _pair(raw.get("corners")),
        "possession": _pair(raw.get("possession")),
        "yc": _pair(raw.get("yc")),
        "rc": _pair(raw.get("rc")),
        "urg": urg,
        "d5": d5,
        "d10": d10,
        "lbar": lbar,
        "phi": phi,
        "omega": omega,
        "k": k,
        "k_match": k_match,
        "also_firing": also_firing(board, strategy, side),
        "score_state": _score_state(score or str(raw.get("score") or "") or None, side),
        "clock_bucket": _clock_bucket(clock),
        "tslg_bucket": _tslg_bucket(tslg_min, no_goal),
        "odds_bucket": _odds_bucket(trigger_odds),
        "h2h": raw.get("h2h") if isinstance(raw.get("h2h"), Mapping) else None,
        "last_5min": raw.get("last_5min") if isinstance(raw.get("last_5min"), Mapping) else None,
        "last_10min": raw.get("last_10min") if isinstance(raw.get("last_10min"), Mapping) else None,
        "has_board": bool(board),
    }


def sweet_spot_flag(
    minute: int,
    *,
    status_short: str | None,
    minute_display: str | None = None,
    windows: SweetSpotWindows | None = None,
) -> bool:
    return in_sweet_spot(
        minute,
        status_short=status_short,
        minute_display=minute_display,
        windows=windows,
    )


def pattern_summary(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Hit rate by clock / score / TSLG / odds / sweet spot / weekday / hour /
    league / country. Settled rows only (Confirmed or Expired).

    Weekday and hour come from `created_at`, not `factors`, so -- unlike the
    board-snapshot groups -- they cover every row, including alerts fired
    before full board snapshots started landing on the payload.
    """
    settled = [row for row in rows if str(row.get("state") or "") in {"Confirmed", "Expired"}]
    fixed_groups = (
        ("Clock", "clock_bucket", ("1-15", "16-30", "31-45", "46-60", "61-75", "76+")),
        ("Half", "half", ("1H", "2H")),
        ("Score", "score_state", ("0-0", "level", "leading", "trailing")),
        ("TSLG", "tslg_bucket", ("no goal yet", "0-9'", "10-19'", "20'+")),
        ("Sweet spot", "sweet_spot", ("yes", "no")),
        ("Kickoff odds (trigger side)", "odds_bucket", ("favourite <2", "mid 2-3.5", "dog >3.5")),
        ("Weekday (UTC)", "weekday_bucket", _WEEKDAY_LABELS),
        ("Hour (UTC)", "hour_bucket", _HOUR_LABELS),
    )
    out: list[dict[str, Any]] = []
    for title, field, labels in fixed_groups:
        buckets: dict[str, list[int]] = {label: [0, 0] for label in labels}
        for row in settled:
            factors = row.get("factors") if isinstance(row.get("factors"), Mapping) else {}
            if field == "weekday_bucket":
                key = _weekday_bucket(row.get("created_at")) or ""
            elif field == "hour_bucket":
                key = _hour_bucket(row.get("created_at")) or ""
            else:
                raw = factors.get(field) if isinstance(factors, Mapping) else None
                if field == "sweet_spot":
                    if raw is True:
                        key = "yes"
                    elif raw is False:
                        key = "no"
                    else:
                        continue
                else:
                    key = str(raw or "")
            if key not in buckets:
                continue
            buckets[key][1] += 1
            if str(row.get("state")) == "Confirmed":
                buckets[key][0] += 1
        lines = []
        for label in labels:
            confirmed, total = buckets[label]
            if total == 0:
                continue
            lines.append(
                {
                    "label": label,
                    "n": total,
                    "confirmed": confirmed,
                    "hit_rate": confirmed / total,
                }
            )
        if lines:
            out.append({"title": title, "rows": lines})
    out.extend(_open_vocabulary_groups(settled))
    return out


def _open_vocabulary_groups(
    settled: Sequence[Mapping[str, Any]], *, top_n: int = 12
) -> list[dict[str, Any]]:
    """League / Country hit rate, ranked by volume.

    Unlike the fixed groups above, the label set is open-ended (dozens of
    leagues), so this ranks by alert count instead of a known tuple, and
    folds anything past `top_n` into one "Other" row.
    """
    specs: tuple[tuple[str, Any], ...] = (
        ("League", lambda row: row.get("league")),
        (
            "Country",
            lambda row: (row.get("factors") or {}).get("country")
            if isinstance(row.get("factors"), Mapping)
            else None,
        ),
    )
    out: list[dict[str, Any]] = []
    for title, getter in specs:
        buckets: dict[str, list[int]] = {}
        for row in settled:
            raw = getter(row)
            key = str(raw).strip() if raw else "Unknown"
            bucket = buckets.setdefault(key, [0, 0])
            bucket[1] += 1
            if str(row.get("state")) == "Confirmed":
                bucket[0] += 1
        if not buckets:
            continue
        ranked = sorted(buckets.items(), key=lambda item: item[1][1], reverse=True)
        lines = [
            {"label": label, "n": total, "confirmed": confirmed, "hit_rate": confirmed / total}
            for label, (confirmed, total) in ranked[:top_n]
        ]
        if len(ranked) > top_n:
            rest = ranked[top_n:]
            rest_confirmed = sum(confirmed for _, (confirmed, _) in rest)
            rest_total = sum(total for _, (_, total) in rest)
            lines.append(
                {
                    "label": f"Other ({len(rest)})",
                    "n": rest_total,
                    "confirmed": rest_confirmed,
                    "hit_rate": (rest_confirmed / rest_total) if rest_total else 0.0,
                }
            )
        out.append({"title": title, "rows": lines})
    return out


def csv_row(item: Mapping[str, Any]) -> dict[str, Any]:
    factors = item.get("factors") if isinstance(item.get("factors"), Mapping) else {}
    def side(block: Any, which: str) -> Any:
        if not isinstance(block, Mapping):
            return ""
        value = block.get(which)
        return "" if value is None else value

    return {
        "result": item.get("state") or "",
        "strategy": item.get("strategy") or "",
        "side": item.get("team") or "",
        "value": item.get("value"),
        "minute": item.get("minute"),
        "status": factors.get("status") or "",
        "half": factors.get("half") or "",
        "score": item.get("score") or "",
        "home": item.get("home_team") or "",
        "away": item.get("away_team") or "",
        "league": item.get("league") or "",
        "country": factors.get("country") or "",
        "sweet_spot": factors.get("sweet_spot"),
        "tslg_home": factors.get("tslg_home"),
        "tslg_away": factors.get("tslg_away"),
        "odds_home": factors.get("odds_home"),
        "odds_draw": factors.get("odds_draw"),
        "odds_away": factors.get("odds_away"),
        "live_home": factors.get("live_home"),
        "live_away": factors.get("live_away"),
        "sot_home": side(factors.get("sot"), "home"),
        "sot_away": side(factors.get("sot"), "away"),
        "sofft_home": side(factors.get("sofft"), "home"),
        "sofft_away": side(factors.get("sofft"), "away"),
        "da_home": side(factors.get("da"), "home"),
        "da_away": side(factors.get("da"), "away"),
        "att_home": side(factors.get("attacks"), "home"),
        "att_away": side(factors.get("attacks"), "away"),
        "crn_home": side(factors.get("corners"), "home"),
        "crn_away": side(factors.get("corners"), "away"),
        "pos_home": side(factors.get("possession"), "home"),
        "pos_away": side(factors.get("possession"), "away"),
        "urg_home": side(factors.get("urg"), "home"),
        "urg_away": side(factors.get("urg"), "away"),
        "d5_home": side(factors.get("d5"), "home"),
        "d5_away": side(factors.get("d5"), "away"),
        "d10_home": side(factors.get("d10"), "home"),
        "d10_away": side(factors.get("d10"), "away"),
        "lbar_home": side(factors.get("lbar"), "home"),
        "lbar_away": side(factors.get("lbar"), "away"),
        "phi_home": side(factors.get("phi"), "home"),
        "phi_away": side(factors.get("phi"), "away"),
        "omega_home": side(factors.get("omega"), "home"),
        "omega_away": side(factors.get("omega"), "away"),
        "k_home": side(factors.get("k"), "home"),
        "k_away": side(factors.get("k"), "away"),
        "k_match": factors.get("k_match"),
        "also_firing": ",".join(str(s) for s in (factors.get("also_firing") or [])),
        "settle_score": item.get("settle_score") or "",
        "settle_minute": item.get("settle_minute"),
    }
