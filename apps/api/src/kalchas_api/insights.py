"""The numbers behind the admin Overview, Results and Visitors pages.

Everything here is a pure function over rows the routes already loaded --
alert results shaped by ``admin._result_item`` and visits shaped by
``visitors.visit_item`` -- so the maths is testable without a database.

Days are the admin's own calendar days (`tz` from the browser), and every
period is compared with the period of the same length right before it.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta, tzinfo
from statistics import median
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

WEEKDAYS: tuple[str, ...] = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
CLOCKS: tuple[str, ...] = ("1-15", "16-30", "31-45", "46-60", "61-75", "76+")
SETTLED = frozenset({"Confirmed", "Expired"})
BOUNCE_SECONDS = 15
ENGAGED_SECONDS = 60
DURATION_BUCKETS: tuple[tuple[str, int, int | None], ...] = (
    ("<15s", 0, 15),
    ("15-60s", 15, 60),
    ("1-3 min", 60, 180),
    ("3-10 min", 180, 600),
    ("10-30 min", 600, 1800),
    ("30 min+", 1800, None),
)


def resolve_zone(name: str | None) -> tuple[tzinfo, str]:
    try:
        return ZoneInfo(name or "UTC"), name or "UTC"
    except (ZoneInfoNotFoundError, ValueError):
        return UTC, "UTC"


@dataclass(frozen=True)
class Window:
    """Inclusive run of local calendar days."""

    first: date
    last: date
    tz: tzinfo

    @property
    def days(self) -> int:
        return (self.last - self.first).days + 1

    @property
    def start(self) -> datetime:
        return datetime.combine(self.first, time.min, tzinfo=self.tz)

    @property
    def end(self) -> datetime:
        return datetime.combine(self.last + timedelta(days=1), time.min, tzinfo=self.tz)

    def previous(self) -> Window:
        return Window(
            self.first - timedelta(days=self.days), self.first - timedelta(days=1), self.tz
        )

    def widen_to(self, days: int) -> Window:
        """Same last day, at least `days` long (charts keep 14 days of context)."""
        if self.days >= days:
            return self
        return Window(self.last - timedelta(days=days - 1), self.last, self.tz)

    def contains(self, at: datetime | None) -> bool:
        return at is not None and self.start <= at < self.end

    def each_day(self) -> list[date]:
        return [self.first + timedelta(days=i) for i in range(self.days)]

    def as_dict(self) -> dict[str, Any]:
        return {"first": self.first.isoformat(), "last": self.last.isoformat(), "days": self.days}


def window_from_params(
    *,
    days: int | None,
    since: str | None,
    until: str | None,
    zone: tzinfo,
    today: date | None = None,
    max_days: int = 400,
) -> Window:
    """`since`/`until` (YYYY-MM-DD, inclusive) win over `days`; never past today."""
    today = today or datetime.now(zone).date()
    if since and until:
        first, last = date.fromisoformat(since[:10]), date.fromisoformat(until[:10])
        if last < first:
            first, last = last, first
        last = min(last, today)
        first = max(min(first, last), last - timedelta(days=max_days - 1))
        return Window(first, last, zone)
    n = max(1, min(int(days or 7), max_days))
    return Window(today - timedelta(days=n - 1), today, zone)


def parse_time(value: Any) -> datetime | None:
    """ISO string or datetime to an aware datetime (naive means UTC)."""
    if not value:
        return None
    if isinstance(value, datetime):
        at = value
    else:
        try:
            at = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
    return at if at.tzinfo else at.replace(tzinfo=UTC)


def _rate(confirmed: int, settled: int) -> float | None:
    return confirmed / settled if settled else None


# ---------------------------------------------------------------- results


def _factors(row: Mapping[str, Any]) -> Mapping[str, Any]:
    raw = row.get("factors")
    return raw if isinstance(raw, Mapping) else {}


def _minutes_to_goal(row: Mapping[str, Any]) -> int | None:
    if row.get("state") != "Confirmed":
        return None
    try:
        gap = int(row["settle_minute"]) - int(row["minute"])
    except (KeyError, TypeError, ValueError):
        return None
    return gap if gap >= 0 else None


def alert_stats(rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    total = confirmed = expired = 0
    gaps: list[int] = []
    for row in rows:
        total += 1
        state = row.get("state")
        if state == "Confirmed":
            confirmed += 1
            gap = _minutes_to_goal(row)
            if gap is not None:
                gaps.append(gap)
        elif state == "Expired":
            expired += 1
    settled = confirmed + expired
    return {
        "total": total,
        "confirmed": confirmed,
        "expired": expired,
        "open": total - settled,
        "settled": settled,
        "hit_rate": _rate(confirmed, settled),
        "median_to_goal": median(gaps) if gaps else None,
    }


def _day_of(row: Mapping[str, Any], zone: tzinfo) -> date | None:
    at = parse_time(row.get("created_at"))
    return at.astimezone(zone).date() if at else None


def daily_hits(rows: Sequence[Mapping[str, Any]], window: Window) -> list[dict[str, Any]]:
    by_day: dict[date, list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        day = _day_of(row, window.tz)
        if day is not None:
            by_day[day].append(row)
    out = []
    for day in window.each_day():
        stats = alert_stats(by_day.get(day, []))
        out.append(
            {
                "date": day.isoformat(),
                "total": stats["total"],
                "confirmed": stats["confirmed"],
                "settled": stats["settled"],
                "hit_rate": stats["hit_rate"],
            }
        )
    return out


_SCORE_LABELS = {
    "0-0": "0-0",
    "level": "Level, not 0-0",
    "leading": "Trigger side leading",
    "trailing": "Trigger side trailing",
}


def _slice_dims(zone: tzinfo) -> tuple[tuple[str, Callable[[Mapping[str, Any]], Any]], ...]:
    def clock(row: Mapping[str, Any]) -> str | None:
        bucket = _factors(row).get("clock_bucket")
        return f"{bucket}'" if bucket else None

    def half(row: Mapping[str, Any]) -> str | None:
        return {"1H": "1st half", "2H": "2nd half"}.get(str(_factors(row).get("half") or ""))

    def sweet(row: Mapping[str, Any]) -> str | None:
        flag = _factors(row).get("sweet_spot")
        if flag is None:
            return None
        return "Inside sweet spot" if flag else "Outside sweet spot"

    def weekday(row: Mapping[str, Any]) -> str | None:
        at = parse_time(row.get("created_at"))
        return WEEKDAYS[at.astimezone(zone).weekday()] if at else None

    def known(value: Any) -> str | None:
        text = str(value or "").strip()
        return text if text and text != "unknown" else None

    return (
        ("Minute", clock),
        ("Half", half),
        ("Score", lambda row: _SCORE_LABELS.get(str(_factors(row).get("score_state") or ""))),
        ("Kickoff odds", lambda row: known(_factors(row).get("odds_bucket"))),
        ("Side", lambda row: {"home": "Home team", "away": "Away team"}.get(row.get("team") or "")),
        ("Sweet spot", sweet),
        ("Time since last goal", lambda row: known(_factors(row).get("tslg_bucket"))),
        ("League", lambda row: known(row.get("league"))),
        ("Country", lambda row: known(_factors(row).get("country"))),
        ("Weekday", weekday),
    )


def slices(rows: Sequence[Mapping[str, Any]], zone: tzinfo) -> list[dict[str, Any]]:
    """Hit rate of every value of every dimension, settled alerts only."""
    out: list[dict[str, Any]] = []
    settled = [row for row in rows if row.get("state") in SETTLED]
    for dim, getter in _slice_dims(zone):
        buckets: dict[str, list[int]] = {}
        for row in settled:
            label = getter(row)
            if not label:
                continue
            bucket = buckets.setdefault(str(label), [0, 0])
            bucket[1] += 1
            if row.get("state") == "Confirmed":
                bucket[0] += 1
        for label, (confirmed, n) in buckets.items():
            out.append(
                {
                    "dim": dim,
                    "label": label,
                    "n": n,
                    "confirmed": confirmed,
                    "hit_rate": confirmed / n,
                }
            )
    return out


def best_slice(rows: Sequence[Mapping[str, Any]], zone: tzinfo) -> dict[str, Any] | None:
    """The slice that beats this strategy's own rate by the most, on enough alerts."""
    stats = alert_stats(rows)
    if stats["settled"] < 10 or stats["hit_rate"] is None:
        return None
    floor = max(10, int(stats["settled"] * 0.15))
    better = [
        item
        for item in slices(rows, zone)
        if item["n"] >= floor and item["hit_rate"] > stats["hit_rate"]
    ]
    if not better:
        return None
    return max(better, key=lambda item: (item["hit_rate"], item["n"]))


def clock_matrix(rows: Sequence[Mapping[str, Any]], keys: Sequence[str]) -> dict[str, Any]:
    cells: dict[tuple[str, str], list[int]] = defaultdict(lambda: [0, 0])
    for row in rows:
        if row.get("state") not in SETTLED:
            continue
        bucket = _factors(row).get("clock_bucket")
        if bucket not in CLOCKS:
            continue
        cell = cells[(str(row.get("strategy")), str(bucket))]
        cell[1] += 1
        if row.get("state") == "Confirmed":
            cell[0] += 1
    return {
        "columns": list(CLOCKS),
        "rows": [
            {
                "strategy": key,
                "cells": [
                    {"confirmed": cells[(key, c)][0], "settled": cells[(key, c)][1]} for c in CLOCKS
                ],
            }
            for key in keys
        ],
    }


def strategy_order(rows: Iterable[Mapping[str, Any]], known: Sequence[str]) -> list[str]:
    """Current strategies in slot order, then any retired key that still has rows."""
    seen = {str(row.get("strategy")) for row in rows if row.get("strategy")}
    return list(known) + sorted(seen - set(known))


def results_insights(
    rows: Sequence[Mapping[str, Any]],
    *,
    window: Window,
    known_keys: Sequence[str],
    selected: Sequence[str] = (),
) -> dict[str, Any]:
    """Everything the Results page draws. `rows` must cover the previous window
    and 14 days of trend before `window.last`."""
    zone = window.tz
    prev = window.previous()
    trend = window.widen_to(14)
    chart = trend if window.days == 1 else window

    def within(w: Window, items: Iterable[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
        return [row for row in items if w.contains(parse_time(row.get("created_at")))]

    picked = [row for row in rows if not selected or row.get("strategy") in selected]
    cur_all, prev_all = within(window, rows), within(prev, rows)
    cur, previous = within(window, picked), within(prev, picked)
    trend_window = Window(window.last - timedelta(days=13), window.last, zone)
    keys = strategy_order(cur_all, known_keys)

    by_strategy = []
    for key in keys:
        mine = [row for row in cur_all if row.get("strategy") == key]
        theirs_prev = [row for row in prev_all if row.get("strategy") == key]
        trend_rows = within(trend_window, (row for row in rows if row.get("strategy") == key))
        by_strategy.append(
            {
                "strategy": key,
                "current": alert_stats(mine),
                "previous": alert_stats(theirs_prev),
                "trend": [day["hit_rate"] for day in daily_hits(trend_rows, trend_window)],
                "best_slice": best_slice(mine, zone),
            }
        )
    return {
        "window": window.as_dict(),
        "previous_window": prev.as_dict(),
        "chart_window": chart.as_dict(),
        "summary": alert_stats(cur),
        "previous": alert_stats(previous),
        "daily": daily_hits(within(chart, picked), chart),
        "by_strategy": by_strategy,
        "overall_hit_rate": alert_stats(cur_all)["hit_rate"],
        "matrix": clock_matrix(cur_all, keys),
        "slices": slices(cur, zone),
    }


# ---------------------------------------------------------------- visitors


def visitor_key(item: Mapping[str, Any]) -> str:
    # Anonymous rows have no id; masked IP + UA is the best stand-in.
    return item.get("visitor_id") or f"anon:{item.get('ip')}:{item.get('user_agent')}"


def _started(item: Mapping[str, Any], zone: tzinfo) -> datetime | None:
    at = parse_time(item.get("first_seen"))
    return at.astimezone(zone) if at else None


def visit_stats(items: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    people: dict[str, dict[str, bool]] = {}
    for item in items:
        p = people.setdefault(
            visitor_key(item),
            {"returning": False, "engaged": False, "match": False, "tg": False, "paid": False},
        )
        p["returning"] |= bool(item.get("returning"))
        p["engaged"] |= int(item.get("duration_seconds") or 0) >= ENGAGED_SECONDS
        p["match"] |= bool(item.get("matches"))
        p["tg"] |= bool(item.get("telegram_free") or item.get("telegram_paid"))
        p["paid"] |= bool(item.get("telegram_paid"))
    n = len(people)
    visits = len(items)

    def count(flag: str) -> int:
        return sum(1 for p in people.values() if p[flag])

    durations = [int(item.get("duration_seconds") or 0) for item in items]
    return {
        "visitors": n,
        "visits": visits,
        "median_seconds": median(durations) if durations else None,
        "returning_share": count("returning") / n if n else None,
        "bounce_rate": sum(1 for d in durations if d < BOUNCE_SECONDS) / visits if visits else None,
        "engaged": count("engaged"),
        "match_viewers": count("match"),
        "telegram_visitors": count("tg"),
        "paid_visitors": count("paid"),
        "telegram_rate": count("tg") / n if n else None,
    }


def _unique_by(
    items: Sequence[Mapping[str, Any]], getter: Callable[[Mapping[str, Any]], str], top: int
) -> list[dict[str, Any]]:
    groups: dict[str, set[str]] = defaultdict(set)
    for item in items:
        groups[getter(item)].add(visitor_key(item))
    ranked = sorted(groups.items(), key=lambda kv: (-len(kv[1]), kv[0]))
    out = [{"label": label, "visitors": len(ids)} for label, ids in ranked[:top]]
    if len(ranked) > top:
        rest: set[str] = set().union(*(ids for _, ids in ranked[top:]))
        out.append({"label": f"Other ({len(ranked) - top})", "visitors": len(rest), "other": True})
    return out


def _source(item: Mapping[str, Any]) -> str:
    return str(item.get("referrer") or "Direct")


def sources(
    items: Sequence[Mapping[str, Any]], prev_items: Sequence[Mapping[str, Any]] | None
) -> list[dict[str, Any]]:
    groups: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for item in items:
        groups[_source(item)].append(item)
    before: dict[str, set[str]] = defaultdict(set)
    for item in prev_items or []:
        before[_source(item)].add(visitor_key(item))
    out = []
    for name, rows in groups.items():
        stats = visit_stats(rows)
        out.append(
            {
                "source": name,
                "visitors": stats["visitors"],
                "previous": len(before.get(name, ())) if prev_items is not None else None,
                "median_seconds": stats["median_seconds"],
                "telegram_rate": stats["telegram_rate"],
            }
        )
    return sorted(out, key=lambda row: -row["visitors"])


def hourly(items: Sequence[Mapping[str, Any]], zone: tzinfo) -> list[dict[str, int]]:
    hours = [{"hour": h, "new": 0, "returning": 0} for h in range(24)]
    for item in items:
        at = _started(item, zone)
        if at is not None:
            hours[at.hour]["returning" if item.get("returning") else "new"] += 1
    return hours


def week_heatmap(items: Sequence[Mapping[str, Any]], zone: tzinfo) -> list[list[int]]:
    grid = [[0] * 24 for _ in WEEKDAYS]
    for item in items:
        at = _started(item, zone)
        if at is not None:
            grid[at.weekday()][at.hour] += 1
    return grid


def duration_histogram(items: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for label, low, high in DURATION_BUCKETS:
        n = sum(
            1
            for item in items
            if int(item.get("duration_seconds") or 0) >= low
            and (high is None or int(item.get("duration_seconds") or 0) < high)
        )
        out.append({"label": label, "visits": n})
    return out


def top_matches(items: Sequence[Mapping[str, Any]], top: int = 8) -> list[dict[str, Any]]:
    viewers: dict[str, set[str]] = defaultdict(set)
    names: dict[str, Mapping[str, Any]] = {}
    for item in items:
        for match in item.get("matches") or []:
            mid = str(match.get("match_id") if isinstance(match, Mapping) else match)
            viewers[mid].add(visitor_key(item))
            if isinstance(match, Mapping):
                names[mid] = match
    ranked = sorted(viewers.items(), key=lambda kv: -len(kv[1]))[:top]
    return [
        {
            "match_id": mid,
            "home_team": (names.get(mid) or {}).get("home_team"),
            "away_team": (names.get(mid) or {}).get("away_team"),
            "viewers": len(ids),
        }
        for mid, ids in ranked
    ]


def daily_visitors(items: Sequence[Mapping[str, Any]], window: Window) -> list[dict[str, Any]]:
    """Unique visitors per local day, split by whether that visitor was new that day."""
    days: dict[date, dict[str, bool]] = {day: {} for day in window.each_day()}
    for item in items:
        at = _started(item, window.tz)
        if at is None or at.date() not in days:
            continue
        seen = days[at.date()]
        key = visitor_key(item)
        # New on a day = at least one of their visits that day was their first ever.
        seen[key] = seen.get(key, False) or not item.get("returning")
    out = []
    for day, seen in days.items():
        new = sum(1 for is_new in seen.values() if is_new)
        out.append({"date": day.isoformat(), "new": new, "returning": len(seen) - new})
    return out


def visitors_insights(
    items: Sequence[Mapping[str, Any]],
    *,
    window: Window,
    retained_since: datetime,
    live_now: int | None = None,
) -> dict[str, Any]:
    """Everything the Visitors page draws, likely humans only.

    `items` must cover the previous window and 14 days of chart context.
    The previous period only counts when the visit log still holds all of it.
    """
    zone = window.tz
    humans = [item for item in items if item.get("likely_human")]
    prev = window.previous()
    chart = window.widen_to(14)

    def within(w: Window) -> list[Mapping[str, Any]]:
        return [item for item in humans if w.contains(parse_time(item.get("first_seen")))]

    cur = within(window)
    prev_items = within(prev) if prev.start >= retained_since else None
    countries = _unique_by(cur, lambda item: str(item.get("country") or ""), 7)
    return {
        "window": window.as_dict(),
        "previous_window": prev.as_dict() if prev_items is not None else None,
        "chart_window": chart.as_dict(),
        "live_now": live_now,
        "summary": visit_stats(cur),
        "previous": visit_stats(prev_items) if prev_items is not None else None,
        "daily": daily_visitors(within(chart), chart),
        "hourly": hourly(cur, zone),
        "heatmap": week_heatmap(cur, zone),
        "durations": duration_histogram(cur),
        "sources": sources(cur, prev_items),
        "countries": countries,
        "devices": _unique_by(
            cur, lambda item: str(item.get("device") or "unknown").capitalize(), 3
        ),
        "browsers": _unique_by(cur, lambda item: str(item.get("browser") or "Other"), 5),
        "os": _unique_by(cur, lambda item: str(item.get("os") or "Other"), 5),
        "matches": top_matches(cur),
        "filtered": sum(
            1
            for item in items
            if not item.get("likely_human") and window.contains(parse_time(item.get("first_seen")))
        ),
    }


# ---------------------------------------------------------------- overview


def strategy_drift(
    rows: Sequence[Mapping[str, Any]],
    *,
    today: date,
    zone: tzinfo,
    keys: Sequence[str],
    names: Mapping[str, str],
    min_settled: int = 10,
    drop: float = 0.10,
) -> list[dict[str, Any]]:
    """Strategies whose last 7 days run `drop` or more below their 30 days before."""
    week = Window(today - timedelta(days=6), today, zone)
    base = Window(week.first - timedelta(days=30), week.first - timedelta(days=1), zone)
    out = []
    for key in keys:
        mine = [row for row in rows if row.get("strategy") == key]
        now = alert_stats(row for row in mine if week.contains(parse_time(row.get("created_at"))))
        before = alert_stats(
            row for row in mine if base.contains(parse_time(row.get("created_at")))
        )
        if now["settled"] < min_settled or before["settled"] < min_settled:
            continue
        if now["hit_rate"] is None or before["hit_rate"] is None:
            continue
        if now["hit_rate"] <= before["hit_rate"] - drop:
            gap = round((before["hit_rate"] - now["hit_rate"]) * 100)
            out.append(
                {
                    "level": "warn",
                    "title": f"{names.get(key, key)} is running {gap} pts below its usual rate",
                    "detail": (
                        f"{round(now['hit_rate'] * 100)}% over the last 7 days on "
                        f"{now['settled']} settled vs {round(before['hit_rate'] * 100)}% "
                        "over the 30 days before."
                    ),
                    "go": f"results:{key}",
                }
            )
    return out


def source_spikes(
    items: Sequence[Mapping[str, Any]], *, today: date, zone: tzinfo, min_before: int = 10
) -> list[dict[str, Any]]:
    """Referrers whose visitors this week moved 40%+ either way vs last week."""
    week = Window(today - timedelta(days=6), today, zone)
    last = week.previous()
    humans = [item for item in items if item.get("likely_human")]
    now = {
        row["source"]: row["visitors"]
        for row in sources(
            [i for i in humans if week.contains(parse_time(i.get("first_seen")))], None
        )
    }
    before = {
        row["source"]: row["visitors"]
        for row in sources(
            [i for i in humans if last.contains(parse_time(i.get("first_seen")))], None
        )
    }
    out = []
    for name, prev_n in before.items():
        cur_n = now.get(name, 0)
        if prev_n < min_before:
            continue
        change = (cur_n - prev_n) / prev_n
        if abs(change) >= 0.4:
            out.append(
                {
                    "level": "info",
                    "title": f"{name} traffic is {'up' if change > 0 else 'down'} {abs(round(change * 100))}% this week",
                    "detail": f"{cur_n} visitors over the last 7 days vs {prev_n} the 7 days before.",
                    "go": "visitors",
                }
            )
    return sorted(out, key=lambda item: item["title"])[:3]


def tips_health(
    settings: Mapping[str, Any], *, now: datetime, stale_minutes: int = 60
) -> dict[str, Any]:
    last = parse_time(settings.get("last_polled_at"))
    if last is None:
        return {
            "level": "warn",
            "title": "Tips feed has never been polled",
            "detail": "No poll recorded for /tips.csv.",
            "go": "tips",
        }
    age = (now - last).total_seconds() / 60
    when = f"{round(age)} min ago" if age < 120 else f"{round(age / 60)} h ago"
    if age > stale_minutes:
        return {
            "level": "warn",
            "title": "Tips feed has gone quiet",
            "detail": f"Last polled {when}.",
            "go": "tips",
        }
    return {
        "level": "ok",
        "title": "Tips feed healthy",
        "detail": f"Last polled {when if age >= 1 else 'under a minute ago'}, {int(settings.get('poll_count') or 0):,} polls in total.",
        "go": "tips",
    }
