"""Admin insights: period windows, results maths, visitor maths and the routes."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient
from kalchas_api import insights
from kalchas_api.app import app
from kalchas_api.insights import (
    Window,
    alert_stats,
    best_slice,
    daily_visitors,
    results_insights,
    sources,
    strategy_drift,
    tips_health,
    visit_stats,
    visitors_insights,
    window_from_params,
)

ATHENS = ZoneInfo("Europe/Athens")
TODAY = date(2026, 10, 31)


def alert(
    day: date,
    state: str,
    *,
    strategy: str = "kscore",
    minute: int = 70,
    settle_minute: int | None = None,
    hour: int = 18,
    clock: str = "61-75",
    team: str = "home",
) -> dict:
    return {
        "strategy": strategy,
        "state": state,
        "minute": minute,
        "settle_minute": settle_minute,
        "team": team,
        "league": "Super League",
        "created_at": datetime(day.year, day.month, day.day, hour, tzinfo=ATHENS).isoformat(),
        "factors": {
            "clock_bucket": clock,
            "half": "2H",
            "score_state": "level",
            "sweet_spot": True,
        },
    }


def visit(
    day: date,
    visitor: str,
    *,
    seconds: int = 120,
    returning: bool = False,
    referrer: str | None = None,
    tg: bool = False,
    human: bool = True,
    hour: int = 20,
) -> dict:
    start = datetime(day.year, day.month, day.day, hour, tzinfo=ATHENS)
    return {
        "visitor_id": visitor,
        "ip": "1.2.3.x",
        "user_agent": "Mozilla/5.0",
        "first_seen": start.isoformat(),
        "last_seen": (start + timedelta(seconds=seconds)).isoformat(),
        "duration_seconds": seconds,
        "returning": returning,
        "referrer": referrer,
        "telegram_free": tg,
        "telegram_paid": False,
        "matches": [{"match_id": "m1", "home_team": "PAOK", "away_team": "Aris"}]
        if seconds > 60
        else [],
        "country": "GR",
        "device": "mobile",
        "browser": "Chrome",
        "os": "Android",
        "likely_human": human,
    }


def test_window_presets_and_custom_range() -> None:
    week = window_from_params(days=7, since=None, until=None, zone=ATHENS, today=TODAY)
    assert (week.first, week.last, week.days) == (date(2026, 10, 25), TODAY, 7)
    assert week.previous().last == date(2026, 10, 24)
    assert week.previous().days == 7
    custom = window_from_params(
        days=None, since="2026-10-20", until="2026-11-05", zone=ATHENS, today=TODAY
    )
    assert (custom.first, custom.last) == (date(2026, 10, 20), TODAY)
    swapped = window_from_params(
        days=None, since="2026-10-12", until="2026-10-02", zone=ATHENS, today=TODAY
    )
    assert swapped.first == date(2026, 10, 2)
    assert Window(TODAY, TODAY, ATHENS).widen_to(14).first == date(2026, 10, 18)


def test_window_uses_local_midnight() -> None:
    day = Window(TODAY, TODAY, ATHENS)
    # 23:30 UTC on the 30th is already 01:30 on the 31st in Athens.
    assert day.contains(datetime(2026, 10, 30, 23, 30, tzinfo=UTC))
    assert not day.contains(datetime(2026, 10, 30, 20, 0, tzinfo=UTC))


def test_alert_stats_counts_open_and_minutes_to_goal() -> None:
    rows = [
        alert(TODAY, "Confirmed", minute=70, settle_minute=74),
        alert(TODAY, "Confirmed", minute=60, settle_minute=70),
        alert(TODAY, "Expired"),
        alert(TODAY, "Monitoring"),
    ]
    stats = alert_stats(rows)
    assert stats["total"] == 4
    assert stats["open"] == 1
    assert stats["settled"] == 3
    assert abs(stats["hit_rate"] - 2 / 3) < 1e-9
    assert stats["median_to_goal"] == 7


def test_results_insights_compares_periods_and_filters_strategy() -> None:
    rows = [alert(TODAY - timedelta(days=d), "Confirmed") for d in range(3)]
    rows += [alert(TODAY - timedelta(days=d), "Expired", strategy="npei") for d in range(2)]
    rows += [alert(TODAY - timedelta(days=9), "Expired")]
    window = Window(TODAY - timedelta(days=6), TODAY, ATHENS)
    body = results_insights(rows, window=window, known_keys=["kscore", "npei"], selected=["kscore"])
    assert body["summary"]["total"] == 3
    assert body["summary"]["hit_rate"] == 1.0
    assert body["previous"]["hit_rate"] == 0.0
    scorecard = {row["strategy"]: row for row in body["by_strategy"]}
    assert scorecard["npei"]["current"]["expired"] == 2
    assert len(scorecard["kscore"]["trend"]) == 14
    assert body["overall_hit_rate"] == 3 / 5
    assert [day["date"] for day in body["daily"]][-1] == TODAY.isoformat()
    cells = body["matrix"]["rows"][0]["cells"]
    assert cells[4] == {"confirmed": 3, "settled": 3}
    minute_slice = next(s for s in body["slices"] if s["dim"] == "Minute")
    assert minute_slice["label"] == "61-75'" and minute_slice["n"] == 3


def test_today_window_charts_two_weeks_of_context() -> None:
    body = results_insights([], window=Window(TODAY, TODAY, ATHENS), known_keys=["kscore"])
    assert body["chart_window"]["days"] == 14
    assert len(body["daily"]) == 14


def test_retired_strategy_with_rows_still_gets_a_row() -> None:
    rows = [alert(TODAY, "Confirmed", strategy="omega")]
    body = results_insights(rows, window=Window(TODAY, TODAY, ATHENS), known_keys=["kscore"])
    assert [row["strategy"] for row in body["by_strategy"]] == ["kscore", "omega"]


def test_best_slice_needs_enough_alerts_and_must_beat_the_rate() -> None:
    rows = [alert(TODAY, "Confirmed", team="home") for _ in range(8)]
    rows += [alert(TODAY, "Expired", team="away") for _ in range(8)]
    best = best_slice(rows, ATHENS)
    assert best is None or best["hit_rate"] > 0.5
    assert best_slice(rows[:5], ATHENS) is None
    rows += [alert(TODAY, "Confirmed", team="home") for _ in range(4)]
    best = best_slice(rows, ATHENS)
    assert best is not None and best["label"] == "Home team"


def test_visit_stats_funnel_and_rates() -> None:
    items = [
        visit(TODAY, "a", seconds=5),
        visit(TODAY, "b", seconds=300, tg=True),
        visit(TODAY, "b", seconds=200, returning=True),
        visit(TODAY, "c", seconds=90, returning=True),
    ]
    stats = visit_stats(items)
    assert stats["visitors"] == 3
    assert stats["visits"] == 4
    assert stats["bounce_rate"] == 0.25
    assert stats["engaged"] == 2
    assert stats["match_viewers"] == 2
    assert stats["telegram_visitors"] == 1
    assert abs(stats["returning_share"] - 2 / 3) < 1e-9


def test_daily_visitors_splits_new_and_returning() -> None:
    items = [
        visit(TODAY, "a"),
        visit(TODAY, "a", returning=True),
        visit(TODAY, "b", returning=True),
    ]
    days = daily_visitors(items, Window(TODAY, TODAY, ATHENS))
    assert days == [{"date": TODAY.isoformat(), "new": 1, "returning": 1}]


def test_sources_rank_and_compare() -> None:
    cur = [
        visit(TODAY, "a", referrer="t.me", tg=True),
        visit(TODAY, "b", referrer="t.me"),
        visit(TODAY, "c"),
    ]
    prev = [visit(TODAY, "z", referrer="t.me")]
    rows = sources(cur, prev)
    assert rows[0]["source"] == "t.me"
    assert rows[0]["visitors"] == 2 and rows[0]["previous"] == 1
    assert rows[0]["telegram_rate"] == 0.5
    assert rows[1]["source"] == "Direct" and rows[1]["previous"] == 0
    assert sources(cur, None)[0]["previous"] is None


def test_visitors_insights_hides_bots_and_drops_unretained_previous() -> None:
    items = [
        visit(TODAY, "a"),
        visit(TODAY, "bot", human=False),
        visit(TODAY - timedelta(days=8), "a"),
    ]
    window = Window(TODAY - timedelta(days=6), TODAY, ATHENS)
    retained = datetime(2026, 10, 1, tzinfo=UTC)
    body = visitors_insights(items, window=window, retained_since=retained, live_now=4)
    assert body["summary"]["visitors"] == 1
    assert body["filtered"] == 1
    assert body["previous"]["visitors"] == 1
    assert body["live_now"] == 4
    assert sum(sum(row) for row in body["heatmap"]) == 1
    late = visitors_insights(
        items, window=window, retained_since=datetime(2026, 10, 30, tzinfo=UTC)
    )
    assert late["previous"] is None
    assert late["previous_window"] is None


def test_strategy_drift_flags_a_slump() -> None:
    rows = [alert(TODAY - timedelta(days=d), "Expired") for d in range(10)]
    rows += [alert(TODAY - timedelta(days=d), "Confirmed") for d in range(3)]
    rows += [alert(TODAY - timedelta(days=d), "Confirmed") for d in range(8, 30)]
    items = strategy_drift(rows, today=TODAY, zone=ATHENS, keys=["kscore"], names={"kscore": "K"})
    assert len(items) == 1
    assert items[0]["title"].startswith("K is running")
    assert items[0]["go"] == "results:kscore"


def test_tips_health_levels() -> None:
    now = datetime(2026, 10, 31, 12, tzinfo=UTC)
    assert tips_health({"last_polled_at": None}, now=now)["level"] == "warn"
    fresh = tips_health(
        {"last_polled_at": (now - timedelta(minutes=2)).isoformat(), "poll_count": 10}, now=now
    )
    assert fresh["level"] == "ok"
    stale = tips_health({"last_polled_at": (now - timedelta(hours=3)).isoformat()}, now=now)
    assert stale["level"] == "warn"


def _login(monkeypatch) -> TestClient:
    monkeypatch.setenv("ADMIN_PASSWORD", "s3cret")
    monkeypatch.setenv("DATABASE_URL", "postgresql://unused")
    client = TestClient(app)
    client.post("/api/admin/login", json={"password": "s3cret"})
    return client


def test_insight_routes_require_session(monkeypatch) -> None:
    monkeypatch.setenv("ADMIN_PASSWORD", "s3cret")
    client = TestClient(app)
    for path in (
        "/api/admin/insights/results",
        "/api/admin/insights/visitors",
        "/api/admin/insights/overview",
    ):
        assert client.get(path).status_code == 401


def test_results_insights_route(monkeypatch) -> None:
    import kalchas_api.admin as admin

    today = datetime.now(ATHENS).date()
    monkeypatch.setattr(
        admin, "_load_insight_alerts", lambda start, end: [alert(today, "Confirmed")]
    )
    client = _login(monkeypatch)
    res = client.get("/api/admin/insights/results", params={"days": 7, "tz": "Europe/Athens"})
    assert res.status_code == 200
    body = res.json()
    assert body["tz"] == "Europe/Athens"
    assert body["summary"]["confirmed"] == 1
    assert body["names"]["kscore"]
    bad = client.get("/api/admin/insights/results", params={"since": "nope", "until": "2026-10-01"})
    assert bad.status_code == 422


def test_visitors_and_overview_routes(monkeypatch) -> None:
    import kalchas_api.admin as admin

    today = datetime.now(ATHENS).date()
    monkeypatch.setattr(
        admin, "_load_insight_visits", lambda start, end: [visit(today, "a", tg=True)]
    )
    monkeypatch.setattr(admin, "_load_insight_alerts", lambda start, end: [alert(today, "Expired")])
    monkeypatch.setattr(admin, "_live_now", lambda: 3)
    monkeypatch.setattr(insights, "tips_health", lambda settings, now: {"level": "ok"})
    client = _login(monkeypatch)
    res = client.get("/api/admin/insights/visitors", params={"days": 1, "tz": "Europe/Athens"})
    assert res.status_code == 200
    body = res.json()
    assert body["summary"]["telegram_visitors"] == 1
    assert body["live_now"] == 3
    assert len(body["log"]) == 1
    over = client.get("/api/admin/insights/overview", params={"tz": "Europe/Athens"})
    assert over.status_code == 200
    data = over.json()
    assert data["results"]["today"]["expired"] == 1
    assert data["visitors"]["today"]["visitors"] == 1
    assert len(data["hit_daily"]) == 14
    assert {row["strategy"] for row in data["strategies"]} >= {"kscore"}
