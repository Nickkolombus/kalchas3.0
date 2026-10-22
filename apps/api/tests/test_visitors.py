"""Visitor log: bot filter, UA summary, daily rollup and the admin endpoint."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient
from kalchas_api.app import app
from kalchas_api.visitors import (
    bot_reason,
    classify,
    daily_summary,
    mask_ip,
    record_page_load,
    referrer_host,
    summarize_user_agent,
    visit_item,
)
from starlette.requests import Request

CHROME_WIN = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36"
)
SAFARI_IPHONE = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 18_5 like Mac OS X) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/18.5 Mobile/15E148 Safari/604.1"
)
SAMSUNG_ANDROID = (
    "Mozilla/5.0 (Linux; Android 14; SM-S918B) AppleWebKit/537.36 (KHTML, like Gecko) "
    "SamsungBrowser/27.0 Chrome/125.0.0.0 Mobile Safari/537.36"
)
YANDEX_BROWSER = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/138.0.0.0 YaBrowser/25.8.0.0 Safari/537.36"
)
GOOGLEBOT = "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"
HEADLESS = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "HeadlessChrome/141.0.0.0 Safari/537.36"
)


def _row(**fields) -> dict:
    now = datetime(2026, 10, 22, 18, 0, tzinfo=UTC)
    base = {
        "id": 1,
        "visitor_id": "v-1",
        "ip_masked": "203.0.113.x",
        "country": "GR",
        "user_agent": CHROME_WIN,
        "referrer": None,
        "landing_path": "/",
        "first_seen": now,
        "last_seen": now + timedelta(minutes=5),
        "page_loads": 1,
        "heartbeats": 20,
        "matches_viewed": [],
        "telegram_free": False,
        "telegram_paid": False,
        "first_ever": now,
        "visit_count": 1,
    }
    base.update(fields)
    return base


def test_bot_reason_flags_crawlers_and_tools() -> None:
    assert bot_reason(GOOGLEBOT) == "bot UA: Googlebot"
    assert bot_reason(HEADLESS) == "bot UA: HeadlessChrome"
    assert bot_reason("curl/8.4.0") is not None
    assert bot_reason("python-requests/2.32") is not None
    assert bot_reason("facebookexternalhit/1.1") is not None
    assert bot_reason("TelegramBot (like TwitterBot)") is not None
    assert bot_reason("") == "no user agent"
    assert bot_reason(None) == "no user agent"


def test_bot_reason_passes_real_browsers() -> None:
    for ua in (CHROME_WIN, SAFARI_IPHONE, SAMSUNG_ANDROID, YANDEX_BROWSER):
        assert bot_reason(ua) is None, ua


def test_classify_requires_js_heartbeat() -> None:
    assert classify(_row()) == (True, [])
    human, reasons = classify(_row(visitor_id=None, heartbeats=0))
    assert human is False
    assert reasons == ["no JS heartbeat"]
    human, reasons = classify(_row(user_agent=HEADLESS))
    assert human is False
    assert reasons == ["bot UA: HeadlessChrome"]


def test_summarize_user_agent() -> None:
    assert summarize_user_agent(CHROME_WIN) == {
        "browser": "Chrome",
        "os": "Windows",
        "device": "desktop",
    }
    assert summarize_user_agent(SAFARI_IPHONE) == {
        "browser": "Safari",
        "os": "iOS",
        "device": "mobile",
    }
    assert summarize_user_agent(SAMSUNG_ANDROID)["browser"] == "Samsung"
    assert summarize_user_agent(SAMSUNG_ANDROID)["device"] == "mobile"
    assert summarize_user_agent(None)["browser"] == "Unknown"


def test_mask_ip_drops_host_part() -> None:
    assert mask_ip("203.0.113.57") == "203.0.113.x"
    assert mask_ip("2001:db8:abcd:12:1:2:3:4") == "2001:db8:abcd::/48"
    assert mask_ip("not-an-ip") is None
    assert mask_ip(None) is None


def test_referrer_host_keeps_external_host_only() -> None:
    assert referrer_host("https://www.google.com/search?q=kalchas") == "google.com"
    assert referrer_host("https://t.me/Kalchas_Tips_Free") == "t.me"
    assert referrer_host("https://kalchas.live/?match=1") is None
    assert (
        referrer_host(
            "https://kalchas-production.up.railway.app/", "kalchas-production.up.railway.app"
        )
        is None
    )
    assert referrer_host("") is None


def test_visit_item_marks_returning_and_duration() -> None:
    earlier = datetime(2026, 10, 20, 9, 0, tzinfo=UTC)
    item = visit_item(_row(first_ever=earlier, visit_count=3))
    assert item["returning"] is True
    assert item["visit_count"] == 3
    assert item["duration_seconds"] == 300
    assert item["likely_human"] is True
    assert visit_item(_row())["returning"] is False


def test_daily_summary_counts_by_local_day() -> None:
    athens = ZoneInfo("Europe/Athens")
    # 22:30 UTC on the 21st is already the 22nd in Athens (UTC+3).
    late = datetime(2026, 10, 21, 22, 30, tzinfo=UTC)
    earlier = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)
    items = [
        visit_item(_row(id=1, visitor_id="a", first_seen=late, last_seen=late, first_ever=late)),
        visit_item(_row(id=2, visitor_id="b", first_ever=earlier, telegram_free=True)),
        visit_item(_row(id=3, visitor_id="b", first_ever=earlier)),
        visit_item(_row(id=4, visitor_id=None, heartbeats=0, user_agent=GOOGLEBOT)),
    ]
    days = daily_summary(
        items, tz=athens, start=date(2026, 10, 21), end=date(2026, 10, 22), humans_only=True
    )
    assert [d["date"] for d in days] == ["2026-10-22", "2026-10-21"]
    today = days[0]
    assert today["visitors"] == 2
    assert today["new"] == 1
    assert today["returning"] == 1
    assert today["visits"] == 3
    assert today["telegram_clicks"] == 1
    assert today["filtered"] == 1
    assert today["countries"] == [{"code": "GR", "count": 2}]
    assert days[1]["visits"] == 0

    everything = daily_summary(
        items, tz=athens, start=date(2026, 10, 22), end=date(2026, 10, 22), humans_only=False
    )
    assert everything[0]["visits"] == 4
    assert everything[0]["filtered"] == 0


def _request(path: str) -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": path,
            "headers": [
                (b"user-agent", CHROME_WIN.encode()),
                (b"cf-connecting-ip", b"198.51.100.23"),
                (b"cf-ipcountry", b"GR"),
                (b"referer", b"https://www.google.com/"),
            ],
            "client": ("10.0.0.1", 1234),
        }
    )


def test_record_page_load_masks_ip_and_skips_admin(monkeypatch) -> None:
    import kalchas_db.visits

    calls: list[dict] = []
    monkeypatch.setenv("DATABASE_URL", "postgresql://unused")
    monkeypatch.setattr(
        kalchas_db.visits, "record_page_load", lambda dsn, **kwargs: calls.append(kwargs)
    )
    record_page_load(_request("/admin"), "admin")
    assert calls == []
    record_page_load(_request("/"), "/")
    assert calls == [
        {
            "ip_masked": "198.51.100.x",
            "country": "GR",
            "user_agent": CHROME_WIN,
            "referrer": "google.com",
            "landing_path": "/",
        }
    ]


def test_visit_event_ignores_unknown_kinds(monkeypatch) -> None:
    import kalchas_db.visits

    calls: list[tuple] = []
    monkeypatch.setenv("DATABASE_URL", "postgresql://unused")
    monkeypatch.setattr(
        kalchas_db.visits,
        "record_telegram_click",
        lambda dsn, vid, kind: calls.append((vid, kind)),
    )
    client = TestClient(app)
    assert client.post("/api/visit/event", json={"vid": "v-1", "kind": "nope"}).json() == {
        "ok": False
    }
    assert client.post("/api/visit/event", json={"vid": "v-1", "kind": "tg_paid"}).json() == {
        "ok": True
    }
    assert calls == [("v-1", "telegram_paid")]


def test_admin_visitors_requires_session(monkeypatch) -> None:
    monkeypatch.setenv("ADMIN_PASSWORD", "s3cret")
    assert TestClient(app).get("/api/admin/visitors").status_code == 401


def test_admin_visitors_filters_bots_by_default(monkeypatch) -> None:
    import kalchas_db.visits

    now = datetime.now(UTC) - timedelta(minutes=10)
    rows = [
        _row(
            id=1,
            visitor_id="human",
            first_seen=now,
            last_seen=now + timedelta(minutes=4),
            first_ever=now,
            matches_viewed=[{"match_id": "m1", "home_team": "Home", "away_team": "Away"}],
        ),
        _row(
            id=2,
            visitor_id=None,
            heartbeats=0,
            user_agent=GOOGLEBOT,
            first_seen=now,
            last_seen=now,
            first_ever=None,
        ),
        _row(
            id=3,
            visitor_id="headless",
            user_agent=HEADLESS,
            first_seen=now,
            last_seen=now,
            first_ever=now,
        ),
    ]
    seen: dict = {}

    def _list(dsn, *, since, until, limit=5000):
        seen.update(since=since, until=until)
        return rows

    monkeypatch.setenv("ADMIN_PASSWORD", "s3cret")
    monkeypatch.setenv("DATABASE_URL", "postgresql://unused")
    monkeypatch.setattr(kalchas_db.visits, "list_visits", _list)
    client = TestClient(app)
    client.post("/api/admin/login", json={"password": "s3cret"})

    res = client.get("/api/admin/visitors", params={"days": 7, "tz": "Europe/Athens"})
    assert res.status_code == 200
    body = res.json()
    assert body["tz"] == "Europe/Athens"
    assert body["humans_only"] is True
    assert [item["id"] for item in body["items"]] == [1]
    assert body["items"][0]["matches"][0]["home_team"] == "Home"
    assert body["items"][0]["browser"] == "Chrome"
    assert body["summary"] == {
        "visits": 3,
        "human_visits": 1,
        "human_visitors": 1,
        "filtered": 2,
    }
    assert len(body["daily"]) == 7
    assert sum(d["visitors"] for d in body["daily"]) == 1
    assert sum(d["filtered"] for d in body["daily"]) == 2
    assert seen["since"].tzinfo is not None

    everything = client.get("/api/admin/visitors", params={"humans": "false", "tz": "Nowhere/X"})
    body = everything.json()
    assert body["tz"] == "UTC"
    assert {item["id"] for item in body["items"]} == {1, 2, 3}
    bots = {item["id"]: item["reasons"] for item in body["items"] if not item["likely_human"]}
    assert bots == {2: ["bot UA: Googlebot", "no JS heartbeat"], 3: ["bot UA: HeadlessChrome"]}


def test_admin_visitors_rejects_out_of_range_days(monkeypatch) -> None:
    monkeypatch.setenv("ADMIN_PASSWORD", "s3cret")
    client = TestClient(app)
    client.post("/api/admin/login", json={"password": "s3cret"})
    assert client.get("/api/admin/visitors", params={"days": 90}).status_code == 422
