"""The weekly recap: what last week's signals did, which ones to tell, first drafts.

Pure: alert rows in, plain dicts out. The bot turns this into a draft every
Monday; the admin edits and approves it; nothing here posts anything.

A *signal* is one message: every alert that fired on the same match minute is
posted together, so they are counted together. It found a goal when any of
its alerts was Confirmed and came to nothing when all of them Expired. Anything
else (still open, cancelled, the other side scored first) is left out.
"""

from __future__ import annotations

import json
from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta, tzinfo
from typing import Any

WEEKDAYS: tuple[str, ...] = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
DAY_NAMES: tuple[str, ...] = (
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
)
WAIT_BUCKETS: tuple[tuple[str, int, int | None], ...] = (
    ("Within 5 min", 0, 5),
    ("5–10 min", 5, 10),
    ("10–20 min", 10, 20),
    ("20+ min", 20, None),
)
# The story quotes the stat the flagged side led by most, in this order of interest.
STORY_STATS: tuple[tuple[str, str, bool], ...] = (
    ("da", "dangerous attacks", False),
    ("sot", "shots on target", False),
    ("corners", "corners", False),
    ("sofft", "shots off target", False),
)
CARD_STATS: tuple[tuple[str, str, bool], ...] = (
    ("possession", "Possession", True),
    ("sot", "Shots on target", False),
    ("sofft", "Shots off target", False),
    ("da", "Dangerous attacks", False),
    ("corners", "Corners", False),
)
_WINDOWS: dict[str, tuple[str, str]] = {
    "delta_5min": ("last_5min", " in the last five minutes"),
    "pressure_index": ("last_10min", " in the last ten minutes"),
}
_CUP_WORDS = ("cup", "beker", "copa", "pokal", "coupe", "coppa", "taça", "taca", "trophy")
_NUMBER_WORDS = ("No", "One", "Two", "Three", "Four", "Five")
SITE = "kalchas.live"


@dataclass
class Signal:
    match_id: str
    minute: int
    home: str
    away: str
    league: str
    created_at: datetime
    rows: list[Mapping[str, Any]] = field(default_factory=list)

    @property
    def states(self) -> set[str]:
        return {str(row.get("state") or "") for row in self.rows}

    @property
    def result(self) -> str | None:
        if "Confirmed" in self.states:
            return "goal"
        if self.states == {"Expired"}:
            return "miss"
        return None


def week_bounds(today: date) -> tuple[date, date]:
    """Monday and Sunday of the last full week before `today`."""
    this_monday = today - timedelta(days=today.weekday())
    first = this_monday - timedelta(days=7)
    return first, first + timedelta(days=6)


def build_recap(
    rows: Iterable[Mapping[str, Any]],
    *,
    week_start: date,
    thresholds: Mapping[str, float] | None = None,
    zone: tzinfo = UTC,
) -> dict[str, Any]:
    """Stats, picks and first-draft text for the week starting `week_start`."""
    return _build(rows, kind="week", start=week_start, days=7, thresholds=thresholds, zone=zone)


def build_daily(
    rows: Iterable[Mapping[str, Any]],
    *,
    day: date,
    thresholds: Mapping[str, float] | None = None,
    zone: tzinfo = UTC,
    strategies: Collection[str] | None = None,
) -> dict[str, Any]:
    """The same for one day, posted only when the admin chooses to: no miss, up to four calls.

    `strategies` keeps only alerts fired by those strategy keys; None or empty keeps all.
    """
    return _build(
        rows,
        kind="day",
        start=day,
        days=1,
        thresholds=thresholds,
        zone=zone,
        strategies=strategies,
    )


def _build(
    rows: Iterable[Mapping[str, Any]],
    *,
    kind: str,
    start: date,
    days: int,
    thresholds: Mapping[str, float] | None,
    zone: tzinfo,
    strategies: Collection[str] | None = None,
) -> dict[str, Any]:
    thresholds = thresholds or {}
    only = sorted({str(k) for k in strategies or () if k})
    if only:
        rows = [row for row in rows if str(row.get("strategy_key") or "") in only]
    signals = [s for s in group_signals(rows) if s.result is not None]
    goals = [s for s in signals if s.result == "goal"]
    misses = [s for s in signals if s.result == "miss"]
    gaps = [g for g in (_gap(s) for s in goals) if g is not None]

    by_day = []
    for index in range(days):
        day = start + timedelta(days=index)
        mine = [s for s in signals if s.created_at.astimezone(zone).date() == day]
        by_day.append(
            {
                "day": WEEKDAYS[day.weekday()],
                "date": day.isoformat(),
                "goals": sum(1 for s in mine if s.result == "goal"),
                "total": len(mine),
            }
        )

    calls, honourable = _pick_calls(goals, 4 if kind == "day" else 3)
    miss = None
    if kind == "week":
        miss = max(misses, key=lambda s: _confidence(s, thresholds), default=None)
    best_day, worst_day = (
        (_best_day(by_day), _worst_day(by_day)) if kind == "week" else (None, None)
    )
    if best_day and worst_day and best_day["day"] == worst_day["day"]:
        worst_day = None  # one busy day is not a best *and* a worst

    def summary(signal: Signal, why: str) -> dict[str, Any]:
        flags = sorted(
            s.minute for s in signals if s.match_id == signal.match_id and _side(s) == _side(signal)
        )
        return _summary(signal, thresholds, why=why, flags=flags)

    end = start + timedelta(days=days - 1)
    data: dict[str, Any] = {
        "kind": kind,
        # `week_start`/`week_end` name the period for both kinds (a day starts and ends on itself).
        "week_start": start.isoformat(),
        "week_end": end.isoformat(),
        "total": len(signals),
        "goals": len(goals),
        "misses": len(misses),
        "waits": [
            {
                "label": label,
                "count": sum(1 for g in gaps if g >= low and (high is None or g < high)),
            }
            for label, low, high in WAIT_BUCKETS
        ],
        "days": by_day if kind == "week" else [],
        "fastest": min(gaps) if gaps else None,
        "average_wait": round(sum(gaps) / len(gaps)) if gaps else None,
        "within_10": sum(1 for g in gaps if g < 10),
        "best_day": best_day,
        "worst_day": worst_day,
        "calls": [summary(s, _call_why(s)) for s in calls],
        "honourable": summary(honourable, "next best call") if honourable else None,
        "miss": summary(miss, _miss_why(misses)) if miss else None,
        "strategy_filter": only,
    }
    data["texts"] = draft_texts(data)
    return data


def group_signals(rows: Iterable[Mapping[str, Any]]) -> list[Signal]:
    grouped: dict[tuple[str, int], Signal] = {}
    for row in rows:
        try:
            key = (str(row["match_id"]), int(row["minute"]))
        except (KeyError, TypeError, ValueError):
            continue
        signal = grouped.get(key)
        if signal is None:
            payload = _obj(row.get("payload"))
            signal = grouped[key] = Signal(
                match_id=key[0],
                minute=key[1],
                home=str(row.get("home_team") or ""),
                away=str(row.get("away_team") or ""),
                league=str(payload.get("league") or _obj(row.get("detail")).get("league") or ""),
                created_at=_when(row.get("created_at")),
            )
        signal.rows.append(row)
    return sorted(grouped.values(), key=lambda s: s.created_at)


# ---------------------------------------------------------------- picks


def _pick_calls(goals: Sequence[Signal], count: int) -> tuple[list[Signal], Signal | None]:
    """The flagged side scored, soonest first; the other side's goals only fill gaps.

    One call per match: three signals before one late equaliser are one story.
    """
    timed = [s for s in goals if _gap(s) is not None]
    own = sorted(
        (s for s in timed if _scorer(s) and _scorer(s) == _side(s)),
        key=lambda s: (_gap(s), -_dominance(s)),
    )
    rest = sorted((s for s in timed if s not in own), key=lambda s: (_gap(s), -_dominance(s)))
    ranked: list[Signal] = []
    seen: set[str] = set()
    for signal in own + rest:
        if signal.match_id not in seen:
            seen.add(signal.match_id)
            ranked.append(signal)
    return ranked[:count], (ranked[count] if len(ranked) > count else None)


def _confidence(signal: Signal, thresholds: Mapping[str, float]) -> float:
    """How far past its own fire threshold the strongest alert was."""
    best = 0.0
    for row in signal.rows:
        try:
            value = float(row.get("value") or 0)
        except (TypeError, ValueError):
            continue
        bar = thresholds.get(str(row.get("strategy_key") or ""))
        best = max(best, value / bar if bar and bar > 0 else value)
    return best


def _call_why(signal: Signal) -> str:
    gap = _gap(signal)
    side = "the side we flagged scored" if _scorer(signal) == _side(signal) else "a goal came"
    return f"{side}, {gap} min after the signal"


def _miss_why(misses: Sequence[Signal]) -> str:
    return f"our most confident call that didn't land ({len(misses)} misses this week)"


def _best_day(days: Sequence[Mapping[str, Any]]) -> dict[str, Any] | None:
    busy = [d for d in days if d["total"] >= 3]
    if not busy:
        return None
    return dict(max(busy, key=lambda d: (d["goals"] / d["total"], d["total"])))


def _worst_day(days: Sequence[Mapping[str, Any]]) -> dict[str, Any] | None:
    busy = [d for d in days if d["total"] >= 3]
    if not busy:
        return None
    return dict(min(busy, key=lambda d: (d["goals"] / d["total"], -d["total"])))


# ---------------------------------------------------------------- one signal


def _lead_row(signal: Signal) -> Mapping[str, Any]:
    """The alert that speaks for the signal: the one with a side, highest value."""
    with_side = [row for row in signal.rows if _row_side(row)] or signal.rows

    def value(row: Mapping[str, Any]) -> float:
        try:
            return float(row.get("value") or 0)
        except (TypeError, ValueError):
            return 0.0

    return max(with_side, key=value)


def _row_side(row: Mapping[str, Any]) -> str:
    side = str(row.get("team") or _obj(row.get("payload")).get("team") or "").lower()
    return side if side in ("home", "away") else ""


def _side(signal: Signal) -> str:
    return _row_side(_lead_row(signal))


def _team(signal: Signal, side: str) -> str:
    return signal.home if side == "home" else signal.away if side == "away" else ""


def _detail(signal: Signal) -> Mapping[str, Any]:
    for row in signal.rows:
        if row.get("state") == "Confirmed":
            return _obj(row.get("detail"))
    return _obj(signal.rows[0].get("detail")) if signal.rows else {}


def _gap(signal: Signal) -> int | None:
    goal = goal_minute(signal)
    if goal is None:
        return None
    gap = goal - signal.minute
    return gap if gap >= 0 else None


def goal_minute(signal: Signal) -> int | None:
    detail = _detail(signal)
    for key in ("goal_minute", "settle_minute"):
        value = _int(detail.get(key))
        if value is not None:
            return value
    return None


def _scores(signal: Signal) -> tuple[tuple[int, int] | None, tuple[int, int] | None]:
    detail = _detail(signal)
    fire = _parse_score(detail.get("fire_score") or _lead_row(signal).get("score"))
    return fire, _parse_score(detail.get("settle_score"))


def _scorer(signal: Signal) -> str:
    fire, settle = _scores(signal)
    if fire is None or settle is None:
        return ""
    if settle[0] > fire[0] and settle[1] == fire[1]:
        return "home"
    if settle[1] > fire[1] and settle[0] == fire[0]:
        return "away"
    return ""


def _stat_block(signal: Signal) -> tuple[Mapping[str, Any], str]:
    row = _lead_row(signal)
    payload = _obj(row.get("payload"))
    window_key, phrase = _WINDOWS.get(str(row.get("strategy_key") or ""), ("", ""))
    block = payload.get(window_key) if window_key else None
    if isinstance(block, Mapping) and any(
        isinstance(block.get(k), Mapping) for k, *_ in STORY_STATS
    ):
        return block, phrase
    return payload, ""


def _pair(block: Mapping[str, Any], key: str, side: str) -> tuple[int, int] | None:
    raw = block.get(key)
    if not isinstance(raw, Mapping):
        return None
    home, away = _int(raw.get("home")), _int(raw.get("away"))
    if home is None or away is None or (home == 0 and away == 0):
        return None
    return (away, home) if side == "away" else (home, away)


def _dominance(signal: Signal) -> int:
    block, _ = _stat_block(signal)
    side = _side(signal) or "home"
    best = 0
    for key, *_ in STORY_STATS:
        pair = _pair(block, key, side)
        if pair:
            best = max(best, pair[0] - pair[1])
    return best


def _story_stat(signal: Signal) -> tuple[int, int, str, str] | None:
    """(own, other, label, window phrase) for the stat the flagged side led by most.

    Shots off target only speak when nothing better does: "11 shots off target
    to 3" says pressure, but also says wasteful.
    """
    block, phrase = _stat_block(signal)
    side = _side(signal) or "home"
    best: tuple[int, int, str, str] | None = None
    fallback: tuple[int, int, str, str] | None = None
    for key, label, _percent in STORY_STATS:
        pair = _pair(block, key, side)
        if not pair or pair[0] <= pair[1]:
            continue
        found = (pair[0], pair[1], label, phrase)
        if key == "sofft":
            fallback = found
        elif best is None or pair[0] - pair[1] > best[0] - best[1]:
            best = found
    return best or fallback


def _card_stats(signal: Signal) -> list[dict[str, Any]]:
    payload = _obj(_lead_row(signal).get("payload"))
    if not any(isinstance(payload.get(key), Mapping) for key, *_ in CARD_STATS):
        payload, _ = _stat_block(signal)
    side = _side(signal) or "home"
    out = []
    for key, label, percent in CARD_STATS:
        pair = _pair(payload, key, side)
        if pair:
            out.append({"label": label, "own": pair[0], "other": pair[1], "percent": percent})
    return out


def _summary(
    signal: Signal, thresholds: Mapping[str, float], *, why: str, flags: Sequence[int] = ()
) -> dict[str, Any]:
    side = _side(signal)
    fire, settle = _scores(signal)
    detail = _detail(signal)
    payload = _obj(_lead_row(signal).get("payload"))
    return {
        "home_logo": str(payload.get("home_logo") or "") or None,
        "away_logo": str(payload.get("away_logo") or "") or None,
        "flags": list(flags) or [signal.minute],
        "match_id": signal.match_id,
        "home": signal.home,
        "away": signal.away,
        "league": signal.league,
        "team": side or None,
        "team_name": _team(signal, side) or None,
        "other_name": _team(signal, "away" if side == "home" else "home") if side else None,
        "minute": signal.minute,
        "goal_minute": goal_minute(signal) if signal.result == "goal" else None,
        "gap": _gap(signal) if signal.result == "goal" else None,
        "scorer": _scorer(signal) or None,
        "fire_score": _fmt_score(fire),
        "settle_score": _fmt_score(settle),
        "window": _int(detail.get("success_window_minutes"))
        if not detail.get("infinite_ttl")
        else None,
        "strategies": sorted({str(row.get("strategy_key") or "") for row in signal.rows}),
        "value": _float(_lead_row(signal).get("value")),
        "confidence": round(_confidence(signal, thresholds), 2),
        "stats": _card_stats(signal),
        "story_stat": _story_stat(signal),
        "cup": any(word in signal.league.lower() for word in _CUP_WORDS),
        "why": why,
    }


# ---------------------------------------------------------------- drafts


# Every word on a card is one of these fields, so the admin has the last say on
# all of it. (key, label in admin, where it shows, rows of textarea)
WEEK_FIELDS: tuple[tuple[str, str, str, int], ...] = (
    ("period_label", "Card header", "every card", 1),
    ("period_dates", "Dates in the header", "every card", 1),
    ("kicker", "Small line above the headline", "card 1", 1),
    ("headline_number", "Headline, big part", "card 1", 1),
    ("headline_rest", "Headline, small part", "card 1", 1),
    ("cover_line", "Line under the headline", "card 1", 2),
    ("feature_label", "Feature box title", "card 1", 1),
    ("feature_tag", "Feature box tag", "card 1", 1),
    ("feature_line", "Feature box line", "card 1", 2),
    ("waits_title", "Chart title: time to goal", "card 1", 1),
    ("waits_note", "Sentence under that chart", "card 1", 2),
    ("days_title", "Chart title: day by day", "card 1", 1),
    ("cover_footer", "Footer", "card 1", 1),
    ("calls_title", "Title", "card 2", 1),
    ("calls_sub", "Line beside the title", "card 2", 1),
    ("call_1", "Call 1", "card 2", 4),
    ("call_2", "Call 2", "card 2", 4),
    ("call_3", "Call 3", "card 2", 4),
    ("calls_footer", "Footer", "card 2", 1),
    ("miss_kicker", "Small line above the match", "card 3", 1),
    ("miss", "The miss", "card 3", 4),
    ("readout_note", "Line beside the big number", "card 3", 2),
    ("lesson_label", "Lesson box title", "card 3", 1),
    ("lesson", "What we learned", "card 3", 2),
    ("miss_footer", "Footer", "card 3", 1),
    ("x", "X post", "posts", 5),
    ("caption", "Telegram and Discord caption", "posts", 8),
)
DAY_FIELDS: tuple[tuple[str, str, str, int], ...] = (
    ("period_label", "Card header", "card", 1),
    ("period_dates", "Date in the header", "card", 1),
    ("kicker", "Small line above the headline", "card", 1),
    ("headline_number", "Headline, big part", "card", 1),
    ("headline_rest", "Headline, small part", "card", 1),
    ("cover_line", "Line under the headline", "card", 2),
    ("fastest_title", "Beside the ring, bold", "card", 1),
    ("fastest_line", "Beside the ring", "card", 2),
    ("call_1", "Call 1", "card", 2),
    ("call_2", "Call 2", "card", 2),
    ("call_3", "Call 3", "card", 2),
    ("call_4", "Call 4", "card", 2),
    ("day_footer", "Footer", "card", 1),
    ("x", "X post", "posts", 5),
    ("caption", "Telegram and Discord caption", "posts", 8),
)
FOOTER = "Every signal is posted live, before the goal."


def text_fields(kind: str) -> tuple[tuple[str, str, str, int], ...]:
    return DAY_FIELDS if kind == "day" else WEEK_FIELDS


def draft_texts(data: Mapping[str, Any]) -> dict[str, str]:
    """First drafts of every word on the cards. The lesson is always left empty."""
    if data.get("kind") == "day":
        return _draft_day(data)
    calls = data["calls"]
    miss = data.get("miss")
    feature = calls[0] if calls else None
    texts = {
        "period_label": "The week in signals",
        "period_dates": period_dates(data),
        "kicker": "Every signal we sent",
        "headline_number": headline_number(data),
        "headline_rest": "signals found a goal",
        "cover_line": cover_line(data),
        "feature_label": "Call of the week",
        "feature_tag": _after_signal(feature["gap"]) if feature else "",
        "feature_line": feature_line(feature) if feature else "",
        "waits_title": "How long until the goal",
        "waits_note": waits_note(data),
        "days_title": "Day by day",
        "cover_footer": FOOTER,
        "calls_title": "Three we got right" if len(calls) == 3 else "What we got right",
        "calls_sub": "The side we flagged scored, soon after the signal.",
        "calls_footer": honourable_line(data["honourable"]) if data.get("honourable") else FOOTER,
        "miss_kicker": "The one that got away",
        "miss": miss_story(miss) if miss else "",
        "readout_note": readout_note(miss) if miss else "",
        "lesson_label": "What we learned",
        "lesson": "",
        "miss_footer": "We post the misses too.",
        "x": x_text(data),
        "caption": caption_text(data, lesson=""),
    }
    for index in range(3):
        texts[f"call_{index + 1}"] = call_story(calls[index]) if index < len(calls) else ""
    return texts


def _draft_day(data: Mapping[str, Any]) -> dict[str, str]:
    calls = data["calls"]
    fastest = min(calls, key=lambda c: c.get("gap") or 0) if calls else None
    texts = {
        "period_label": "The day in signals",
        "period_dates": period_dates(data),
        "kicker": "A good day",
        "headline_number": headline_number(data),
        "headline_rest": "signals found a goal",
        "cover_line": day_line(data),
        "fastest_title": f"Fastest: {_short_gap(fastest['gap'])}" if fastest else "",
        "fastest_line": fastest_line(fastest) if fastest else "",
        "day_footer": FOOTER,
        "x": x_text(data),
        "caption": caption_text(data, lesson=""),
    }
    for index in range(4):
        texts[f"call_{index + 1}"] = daily_line(calls[index]) if index < len(calls) else ""
    return texts


def normalize_texts(texts: Mapping[str, Any], data: Mapping[str, Any]) -> dict[str, str]:
    """Saved texts over fresh drafts, so a field added later still has words.

    Recaps drafted before every word was a field kept the calls as a list.
    """
    out = dict(draft_texts(data))
    saved = dict(texts)
    for index, story in enumerate(saved.pop("calls", None) or []):
        saved.setdefault(f"call_{index + 1}", story)
    if "honourable" in saved:
        saved.setdefault("calls_footer", saved.pop("honourable") or FOOTER)
    out.update({key: str(value) for key, value in saved.items() if value is not None})
    return out


def headline_number(data: Mapping[str, Any]) -> str:
    return f"{data['goals']} of {int(data['goals']) + int(data['misses'])}"


def period_dates(data: Mapping[str, Any]) -> str:
    first = date.fromisoformat(str(data["week_start"]))
    if data.get("kind") == "day":
        return f"{DAY_NAMES[first.weekday()]} {first.day} {first:%b}"
    last = date.fromisoformat(str(data["week_end"]))
    return f"{first:%a} {first.day} {first:%b} – {last:%a} {last.day} {last:%b}"


def waits_note(data: Mapping[str, Any]) -> str:
    if not data["goals"]:
        return ""
    return f"{data['within_10']} of the {data['goals']} goals came within 10 minutes of the signal."


def feature_line(call: Mapping[str, Any]) -> str:
    return (
        f"Flagged at {_flag_minutes(call)}{_score_state(call)}. Goal at {call.get('goal_minute')}′."
    )


def readout_note(miss: Mapping[str, Any]) -> str:
    labels = {
        "delta_goal": "goals behind their usual pace",
        "delta_5min": "5-minute pressure, out of 12",
        "pressure_index": "sustained pressure, out of 100",
        "rule_of_three": "unrealised goals",
        "kscore": "K-Score, out of 100",
    }
    label = next((labels[k] for k in miss.get("strategies") or [] if k in labels), "")
    head = f"{_cap(label)} at {miss['minute']}′. " if label else ""
    return f"{head}Our most confident signal this week."


def day_line(data: Mapping[str, Any]) -> str:
    late = [c for c in data["calls"] if (c.get("goal_minute") or 0) >= 85]
    if len(late) >= 2:
        count = _NUMBER_WORDS[len(late)].lower() if len(late) < len(_NUMBER_WORDS) else len(late)
        return f"Late goals everywhere: {count} of our best calls landed after the 85th minute."
    if data.get("fastest") is not None:
        return cover_line({**data, "best_day": None, "worst_day": None})
    return ""


def fastest_line(call: Mapping[str, Any]) -> str:
    team = call.get("team_name") or "They"
    gap = int(call.get("gap") or 0)
    if gap == 0:
        return f"{team} scored in the minute we posted."
    return f"{team} scored {_minutes(gap)} after we posted."


def daily_line(call: Mapping[str, Any]) -> str:
    opener = _score_opener(call, "").split(",")[0]
    if len(call.get("flags") or []) > 1:
        return f"{opener}. We flagged them at {_flag_minutes(call)}. Goal at {call.get('goal_minute')}′."
    gap = int(call.get("gap") or 0)
    when = "in the same minute" if gap == 0 else f"{_minutes(gap)} later"
    return f"{opener}. We posted at {call['minute']}′; they scored {when}."


def _flag_minutes(call: Mapping[str, Any]) -> str:
    minutes = [f"{m}′" for m in call.get("flags") or [call["minute"]]]
    if len(minutes) == 1:
        return minutes[0]
    return ", ".join(minutes[:-1]) + " and " + minutes[-1]


def _score_state(call: Mapping[str, Any]) -> str:
    fire = _parse_score(call.get("fire_score"))
    if fire is None or not call.get("team"):
        return ""
    own, other = (fire[1], fire[0]) if call["team"] == "away" else fire
    if own < other:
        return f" while {other}–{own} down"
    if own == other == 0:
        return " at 0–0"
    if own == other:
        return " with the score level"
    return " while already ahead"


def _after_signal(gap: Any) -> str:
    n = int(gap or 0)
    return "Same minute as the signal" if n == 0 else f"{n} min after the signal"


def _short_gap(gap: Any) -> str:
    n = int(gap or 0)
    return "same minute" if n == 0 else f"{n} min"


def headline(data: Mapping[str, Any]) -> str:
    settled = int(data["goals"]) + int(data["misses"])
    return f"{data['goals']} of {settled} signals found a goal"


def cover_line(data: Mapping[str, Any]) -> str:
    best, worst = data.get("best_day"), data.get("worst_day")
    if best and worst and best["day"] != worst["day"]:
        return (
            f"{_day_name(best['day'])} was the best day ({best['goals']} of {best['total']}). "
            f"{_day_name(worst['day'])} was the hardest ({worst['goals']} of {worst['total']})."
        )
    if data.get("fastest") is not None:
        if int(data["fastest"]) == 0:
            return "The quickest goal came the same minute as the signal."
        return f"The quickest goal came {_minutes(data['fastest'])} after the signal."
    return ""


def call_story(call: Mapping[str, Any]) -> str:
    team = call.get("team_name") or "They"
    opener = _score_opener(call, team)
    stat = call.get("story_stat")
    lead = f"{opener}: {stat[0]} {stat[2]} to {stat[1]}{stat[3]}." if stat else f"{opener}."
    gap = int(call.get("gap") or 0)
    own_goal = call.get("scorer") and call.get("scorer") == call.get("team")
    when = "that same minute" if gap == 0 else f"{_minutes(gap)} later"
    end = f"They scored {when}." if own_goal else f"The goal came {when}."
    if len(call.get("flags") or []) > 1:
        return f"{lead} We flagged them at {_flag_minutes(call)}. The goal came at {call.get('goal_minute')}′."
    return f"{lead} We posted at {call['minute']}′. {end}"


def honourable_line(call: Mapping[str, Any]) -> str:
    team = call.get("team_name")
    flagged = f"{team}, flagged at {call['minute']}′" if team else f"flagged at {call['minute']}′"
    return f"Honourable mention: {flagged}, goal at {call.get('goal_minute')}′."


def miss_story(miss: Mapping[str, Any]) -> str:
    team = miss.get("team_name") or "the side we flagged"
    parts = ["Our most confident call of the week."]
    stat = miss.get("story_stat")
    if stat:
        parts.append(
            f"{_cap(team)} had {stat[0]} {stat[2]} to {stat[1]}{stat[3]} when we posted at {miss['minute']}′."
        )
    else:
        parts.append(f"We flagged {team} at {miss['minute']}′.")
    possession = next((s for s in miss.get("stats") or [] if s["label"] == "Possession"), None)
    if possession and possession["own"] <= 35:
        parts.append(f"But they had just {possession['own']}% of the ball.")
    window = miss.get("window")
    parts.append(f"No goal came in the next {window} minutes." if window else "No goal came.")
    return " ".join(parts)


def miss_notes(miss: Mapping[str, Any]) -> list[str]:
    """Things worth knowing before writing the lesson. Shown to the admin only."""
    notes = []
    if miss.get("cup"):
        notes.append(f"Cup tie ({miss.get('league')}): form from different leagues can mislead.")
    for stat in miss.get("stats") or []:
        if stat["label"] == "Possession" and stat["own"] <= 35:
            notes.append(f"{miss.get('team_name')} had only {stat['own']}% of the ball.")
        if stat["label"] == "Shots off target" and stat["own"] >= 2 * max(1, _shots_on(miss)):
            notes.append(f"{stat['own']} shots off target against {_shots_on(miss)} on it.")
    if miss.get("minute", 0) >= 80:
        notes.append(f"Late signal ({miss['minute']}′): little time left for a goal.")
    return notes


def x_text(data: Mapping[str, Any]) -> str:
    when = "yesterday" if data.get("kind") == "day" else "last week"
    lines = [f"{headline(data)} {when}."]
    if data["calls"]:
        best = data["calls"][0]
        lines += [
            "",
            f"Best call: {best['home']} v {best['away']}, {_goal_after(best['gap'])}.",
        ]
    if data.get("miss"):
        miss = data["miss"]
        lines.append(f"The miss: {miss['home']} v {miss['away']}, our surest call of the week.")
    lines += ["", "The full story 👇"]
    return "\n".join(lines)


def caption_text(data: Mapping[str, Any], *, lesson: str) -> str:
    title = "The day in signals" if data.get("kind") == "day" else "The week in signals"
    lines = [f"{title} · {_span(data)}", "", f"{headline(data)}."]
    if data["calls"]:
        best = data["calls"][0]
        lines += [
            "",
            f"Best call: {best['home']} v {best['away']}. Signal at {best['minute']}′, goal at {best['goal_minute']}′.",
        ]
    if data.get("miss"):
        miss = data["miss"]
        lines += [
            "",
            f"The miss: {miss['home']} v {miss['away']}. Our most confident call of the week.",
        ]
    if lesson.strip():
        lines += ["", lesson.strip()]
    lines += ["", f"Every signal goes out live, before the goal. {SITE}"]
    return "\n".join(lines)


def final_caption(texts: Mapping[str, Any]) -> str:
    """The approved caption, with the lesson worked in above the sign-off if it isn't already."""
    caption = str(texts.get("caption") or "").strip()
    lesson = str(texts.get("lesson") or "").strip()
    if not lesson or lesson in caption:
        return caption
    head, sep, tail = caption.rpartition("\n\n")
    if not sep:
        return f"{caption}\n\n{lesson}"
    return f"{head}\n\n{lesson}\n\n{tail}"


def lesson_missing(texts: Mapping[str, Any]) -> bool:
    return not str(texts.get("lesson") or "").strip()


def week_label(data: Mapping[str, Any]) -> str:
    return _span(data)


def _span(data: Mapping[str, Any]) -> str:
    first = date.fromisoformat(str(data["week_start"]))
    last = date.fromisoformat(str(data["week_end"]))
    if first == last:
        return f"{first.day} {first:%b}"
    if first.month == last.month:
        return f"{first.day}–{last.day} {last:%b}"
    return f"{first.day} {first:%b} – {last.day} {last:%b}"


def _score_opener(call: Mapping[str, Any], team: str) -> str:
    fire = _parse_score(call.get("fire_score"))
    if fire is None or not call.get("team"):
        return f"{team} were pushing"
    own, other = (fire[1], fire[0]) if call["team"] == "away" else fire
    if own < other:
        behind = other - own
        count = _NUMBER_WORDS[behind] if behind < len(_NUMBER_WORDS) else str(behind)
        noun = "goal" if behind == 1 else "goals"
        return f"{'A goal' if behind == 1 else f'{count} {noun}'} down, but {team} were the side pushing"
    if own == other == 0:
        return f"Still 0–0, and {team} were all over it"
    if own == other:
        return f"Level at {own}–{other}, and {team} were the side pushing"
    return f"Already ahead, and {team} kept coming"


def _shots_on(miss: Mapping[str, Any]) -> int:
    for stat in miss.get("stats") or []:
        if stat["label"] == "Shots on target":
            return int(stat["own"])
    return 0


def _day_name(short: str) -> str:
    return DAY_NAMES[WEEKDAYS.index(short)] if short in WEEKDAYS else short


def _goal_after(gap: Any) -> str:
    n = int(gap or 0)
    return (
        "goal the same minute as the signal" if n == 0 else f"goal {_minutes(n)} after the signal"
    )


def _minutes(gap: Any) -> str:
    n = int(gap or 0)
    return "a minute" if n == 1 else f"{n} minutes"


def _cap(text: str) -> str:
    return text[:1].upper() + text[1:]


# ---------------------------------------------------------------- parsing


def _obj(raw: object) -> Mapping[str, Any]:
    if isinstance(raw, str) and raw.strip():
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return {}
    return raw if isinstance(raw, Mapping) else {}


def _int(raw: object) -> int | None:
    if raw is None or raw == "":
        return None
    try:
        return int(raw)  # type: ignore[call-overload]
    except (TypeError, ValueError):
        return None


def _float(raw: object) -> float | None:
    try:
        return float(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _when(raw: object) -> datetime:
    if isinstance(raw, datetime):
        at = raw
    else:
        try:
            at = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        except ValueError:
            at = datetime.min
    return at if at.tzinfo else at.replace(tzinfo=UTC)


def _parse_score(raw: object) -> tuple[int, int] | None:
    text = str(raw or "").replace("–", "-").replace(" ", "")
    home, sep, away = text.partition("-")
    if not sep:
        return None
    a, b = _int(home), _int(away)
    return (a, b) if a is not None and b is not None else None


def _fmt_score(score: tuple[int, int] | None) -> str | None:
    return f"{score[0]}–{score[1]}" if score else None
