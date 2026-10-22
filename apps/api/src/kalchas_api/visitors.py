"""Visitor log: request-side recording plus the read-side bot filter.

Recording is best-effort -- a visitor's page or poll must never fail because
the log did. Bot/human is decided here at read time from what was stored, so
tightening a rule reclassifies the whole 30-day log at once.

There is no data-centre lookup: Cloudflare's free headers carry the country
but not the ASN. The masked IP is shown instead so a hosting range is easy
to spot by eye.
"""

from __future__ import annotations

import ipaddress
import logging
import os
import re
from collections import defaultdict
from datetime import date, datetime, timedelta, tzinfo
from typing import Any
from urllib.parse import urlsplit

from fastapi import APIRouter, Request
from pydantic import BaseModel

log = logging.getLogger(__name__)

public_router = APIRouter(prefix="/api/visit", tags=["visitors"])

MAX_USER_AGENT = 400
MAX_ID = 64

OWN_HOSTS = {"kalchas.live", "www.kalchas.live"}

# Tokens that only automated clients put in a user agent. Kept deliberately
# broad: a false "bot" only hides a row from the default view, it's still
# there under "everything".
_BOT_UA = re.compile(
    r"[\w.-]*(?:bot|crawl|spider|slurp)[\w.-]*"
    r"|headless\w*|phantomjs|selenium|puppeteer|playwright|lighthouse"
    r"|python[\w.-]*|curl|wget|httpclient|http-client|go-http-client|java/|okhttp|axios"
    r"|node-fetch|undici|scrapy|libwww|guzzle|postman"
    r"|facebookexternalhit|facebookcatalog|embedly|preview|pingdom|uptime|statuscake"
    r"|ahrefs|semrush|mj12|bytespider|yandex(?!browser)|baidu|petalsearch"
    r"|whatsapp|discord|skypeuripreview|vkshare|gptbot|chatgpt|claude-|anthropic|perplexity"
    r"|ccbot|google-inspectiontool|feedfetcher|validator",
    re.IGNORECASE,
)


class VisitEventIn(BaseModel):
    vid: str
    kind: str


def _dsn() -> str | None:
    return os.environ.get("DATABASE_URL") or os.environ.get("POSTGRES_URL")


def client_ip(request: Request) -> str | None:
    """The caller's address: Cloudflare's header, then the proxy chain, then the socket."""
    for header in ("CF-Connecting-IP", "X-Real-IP"):
        value = (request.headers.get(header) or "").strip()
        if value:
            return value
    forwarded = (request.headers.get("X-Forwarded-For") or "").split(",")[0].strip()
    if forwarded:
        return forwarded
    return request.client.host if request.client else None


def mask_ip(ip: str | None) -> str | None:
    """Drop the host part: IPv4 keeps /24 (``203.0.113.x``), IPv6 keeps /48."""
    if not ip:
        return None
    try:
        addr = ipaddress.ip_address(ip.strip())
    except ValueError:
        return None
    if addr.version == 4:
        head = str(addr).rsplit(".", 1)[0]
        return f"{head}.x"
    net = ipaddress.ip_network(f"{addr}/48", strict=False)
    return f"{net.network_address}/48"


def referrer_host(url: str | None, own_host: str | None = None) -> str | None:
    """Referring host only (``t.me``, ``google.com``); internal hops return None."""
    if not url:
        return None
    try:
        host = (urlsplit(url.strip()).hostname or "").lower()
    except ValueError:
        return None
    if host.startswith("www."):
        host = host[4:]
    own = {h.removeprefix("www.") for h in OWN_HOSTS}
    if own_host:
        own.add(own_host.split(":", 1)[0].lower().removeprefix("www."))
    if not host or host in own or host in {"localhost", "127.0.0.1"}:
        return None
    return host[:120]


def _country(request: Request) -> str | None:
    value = (request.headers.get("CF-IPCountry") or "").strip().upper()
    return value or None


def _user_agent(request: Request) -> str | None:
    value = (request.headers.get("user-agent") or "").strip()
    return value[:MAX_USER_AGENT] or None


def record_page_load(request: Request, path: str) -> None:
    """Log an HTML page load (no JS needed); skipped for the admin pages."""
    dsn = _dsn()
    if not dsn or path.strip("/").split("/", 1)[0] == "admin":
        return
    try:
        from kalchas_db.visits import record_page_load as store

        store(
            dsn,
            ip_masked=mask_ip(client_ip(request)),
            country=_country(request),
            user_agent=_user_agent(request),
            referrer=referrer_host(request.headers.get("referer"), request.headers.get("host")),
            landing_path=("/" + path.lstrip("/"))[:200],
        )
    except Exception:
        log.debug("visit page-load log failed", exc_info=True)


def record_heartbeat(
    request: Request, visitor_id: str, match_id: str | None, referrer: str | None
) -> None:
    """Extend the caller's visit from the board poll they already make."""
    dsn = _dsn()
    if not dsn or not visitor_id:
        return
    try:
        from kalchas_db.visits import record_heartbeat as store

        store(
            dsn,
            visitor_id[:MAX_ID],
            ip_masked=mask_ip(client_ip(request)),
            country=_country(request),
            user_agent=_user_agent(request),
            referrer=referrer_host(referrer, request.headers.get("host")),
            match_id=(match_id or "")[:MAX_ID] or None,
        )
    except Exception:
        log.debug("visit heartbeat log failed", exc_info=True)


@public_router.post("/event")
def visit_event(body: VisitEventIn) -> dict[str, bool]:
    """Join-button clicks, sent as a beacon. Unknown kinds are ignored."""
    dsn = _dsn()
    kind = {"tg_free": "telegram_free", "tg_paid": "telegram_paid"}.get(body.kind)
    if not dsn or not kind or not body.vid:
        return {"ok": False}
    try:
        from kalchas_db.visits import record_telegram_click

        record_telegram_click(dsn, body.vid[:MAX_ID], kind)
    except Exception:
        log.debug("visit event log failed", exc_info=True)
        return {"ok": False}
    return {"ok": True}


def bot_reason(user_agent: str | None) -> str | None:
    """Why this user agent looks automated, or None if it looks like a browser."""
    ua = (user_agent or "").strip()
    if not ua:
        return "no user agent"
    hit = _BOT_UA.search(ua)
    if hit:
        return f"bot UA: {hit.group(0)}"
    if not ua.startswith("Mozilla/"):
        return "non-browser UA"
    return None


def classify(row: dict[str, Any]) -> tuple[bool, list[str]]:
    """(likely human, reasons it isn't) for one stored visit."""
    reasons: list[str] = []
    ua_reason = bot_reason(row.get("user_agent"))
    if ua_reason:
        reasons.append(ua_reason)
    if not row.get("visitor_id") or int(row.get("heartbeats") or 0) <= 0:
        reasons.append("no JS heartbeat")
    return not reasons, reasons


def summarize_user_agent(user_agent: str | None) -> dict[str, str]:
    """Browser / OS / device from a user agent, by cheap substring checks."""
    ua = user_agent or ""
    if re.search(r"iPad|Tablet", ua) or ("Android" in ua and "Mobile" not in ua):
        device = "tablet"
    elif re.search(r"Mobi|iPhone|iPod|Android", ua):
        device = "mobile"
    else:
        device = "desktop"

    if re.search(r"iPhone|iPad|iPod", ua):
        os_name = "iOS"
    elif "Android" in ua:
        os_name = "Android"
    elif "Windows" in ua:
        os_name = "Windows"
    elif "CrOS" in ua:
        os_name = "ChromeOS"
    elif "Mac OS X" in ua or "Macintosh" in ua:
        os_name = "macOS"
    elif "Linux" in ua:
        os_name = "Linux"
    else:
        os_name = "Other"

    browsers = (
        (r"FBAN|FBAV", "Facebook app"),
        (r"Instagram", "Instagram app"),
        (r"Telegram", "Telegram app"),
        (r"Edg(?:e|A|iOS)?/", "Edge"),
        (r"OPR/|Opera", "Opera"),
        (r"SamsungBrowser", "Samsung"),
        (r"YaBrowser", "Yandex"),
        (r"Firefox/|FxiOS", "Firefox"),
        (r"CriOS|Chrome/", "Chrome"),
        (r"Version/[\d.]+.*Safari/", "Safari"),
    )
    browser = next((name for pattern, name in browsers if re.search(pattern, ua)), "Other")
    if not ua:
        browser, os_name, device = "Unknown", "Unknown", "unknown"
    return {"browser": browser, "os": os_name, "device": device}


def _iso(value: Any) -> str | None:
    return value.isoformat() if hasattr(value, "isoformat") else (str(value) if value else None)


def visit_item(row: dict[str, Any]) -> dict[str, Any]:
    """One stored visit, shaped for the admin table."""
    human, reasons = classify(row)
    first, last = row["first_seen"], row["last_seen"]
    first_ever = row.get("first_ever")
    return {
        "id": int(row["id"]),
        "visitor_id": row.get("visitor_id"),
        "ip": row.get("ip_masked"),
        "country": row.get("country") or "",
        "first_seen": _iso(first),
        "last_seen": _iso(last),
        "duration_seconds": max(0, int((last - first).total_seconds())),
        "page_loads": int(row.get("page_loads") or 0),
        "heartbeats": int(row.get("heartbeats") or 0),
        "referrer": row.get("referrer"),
        "landing_path": row.get("landing_path"),
        "matches": list(row.get("matches_viewed") or []),
        "telegram_free": bool(row.get("telegram_free")),
        "telegram_paid": bool(row.get("telegram_paid")),
        "visit_count": int(row.get("visit_count") or 1),
        "returning": bool(first_ever is not None and first_ever < first),
        "user_agent": row.get("user_agent") or "",
        **summarize_user_agent(row.get("user_agent")),
        "likely_human": human,
        "reasons": reasons,
    }


def _visitor_key(item: dict[str, Any]) -> str:
    # Anonymous rows have no id; masked IP + UA is the best stand-in.
    return item["visitor_id"] or f"anon:{item['ip']}:{item['user_agent']}"


def daily_summary(
    items: list[dict[str, Any]],
    *,
    tz: tzinfo,
    start: date,
    end: date,
    humans_only: bool,
) -> list[dict[str, Any]]:
    """One row per local day from `start` to `end` inclusive, newest first.

    A visit counts on the day it started. A visitor is "new" on a day when
    that day holds their first visit in the retained log; everyone else seen
    that day is "returning". Filtered-out (bot) visits are always counted in
    ``filtered`` so the humans view still shows how much was hidden.
    """
    days: dict[date, dict[str, Any]] = {}
    cursor = end
    while cursor >= start:
        days[cursor] = {
            "date": cursor.isoformat(),
            "visits": 0,
            "visitors": set(),
            "new": set(),
            "seconds": 0,
            "telegram": 0,
            "filtered": 0,
            "countries": defaultdict(set),
        }
        cursor -= timedelta(days=1)
    for item in items:
        started = datetime.fromisoformat(item["first_seen"]).astimezone(tz).date()
        day = days.get(started)
        if day is None:
            continue
        if humans_only and not item["likely_human"]:
            day["filtered"] += 1
            continue
        key = _visitor_key(item)
        day["visits"] += 1
        day["visitors"].add(key)
        if not item["returning"]:
            day["new"].add(key)
        day["seconds"] += item["duration_seconds"]
        if item["telegram_free"] or item["telegram_paid"]:
            day["telegram"] += 1
        day["countries"][item["country"]].add(key)
    out = []
    for day in days.values():
        visitors = len(day["visitors"])
        new = len(day["new"])
        countries = sorted(day["countries"].items(), key=lambda kv: (-len(kv[1]), kv[0]))
        out.append(
            {
                "date": day["date"],
                "visitors": visitors,
                "new": new,
                "returning": visitors - new,
                "visits": day["visits"],
                "total_seconds": day["seconds"],
                "avg_seconds": round(day["seconds"] / day["visits"]) if day["visits"] else 0,
                "telegram_clicks": day["telegram"],
                "filtered": day["filtered"],
                "countries": [{"code": c, "count": len(v)} for c, v in countries[:6]],
            }
        )
    return out
