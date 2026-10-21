"""Live visitor presence: who's on the board right now, and from where.

One row per visitor, keyed by a client-generated id (no account, no PII
beyond the Cloudflare-reported country). Every `/api/live` poll upserts the
caller's own row and reads back a fresh aggregate -- there is no separate
heartbeat endpoint, the same trick Kalchas 2.2 used.

Rows older than `STALE_AFTER_SECONDS` are pruned on each ping so the table
stays small; "active now" is a narrower window applied at read time.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import text

from kalchas_db.sync import sync_engine

STALE_AFTER_SECONDS = 600
"""Rows older than this are dead weight (tab closed without a clean signal,
not just a slow poll) and get deleted rather than merely excluded."""

DEFAULT_ACTIVE_SECONDS = 60
"""A visitor counts as "live" if seen within this many seconds -- a few
multiples of the 15s board poll, enough to absorb a missed tick."""

UPSERT_PING = text(
    """
    INSERT INTO live_visitors (visitor_id, country, last_seen)
    VALUES (:visitor_id, :country, NOW())
    ON CONFLICT (visitor_id) DO UPDATE SET
        country = EXCLUDED.country,
        last_seen = NOW()
    """
)

PRUNE_STALE = text(
    """
    DELETE FROM live_visitors
    WHERE last_seen < NOW() - (:stale_seconds || ' seconds')::INTERVAL
    """
)

SELECT_ACTIVE_BY_COUNTRY = text(
    """
    SELECT COALESCE(country, '') AS country, COUNT(*)::int AS n
    FROM live_visitors
    WHERE last_seen >= NOW() - (:active_seconds || ' seconds')::INTERVAL
    GROUP BY COALESCE(country, '')
    ORDER BY n DESC, country ASC
    """
)


def record_visitor_ping(dsn: str, visitor_id: str, country: str | None) -> None:
    """Upsert one visitor's presence, then sweep anything long stale."""
    if not visitor_id:
        return
    eng = sync_engine(dsn)
    with eng.begin() as conn:
        conn.execute(
            UPSERT_PING,
            {"visitor_id": visitor_id, "country": (country or None)},
        )
        conn.execute(PRUNE_STALE, {"stale_seconds": STALE_AFTER_SECONDS})


def get_live_presence(dsn: str, *, active_seconds: int = DEFAULT_ACTIVE_SECONDS) -> dict[str, Any]:
    """Active visitor count plus a by-country breakdown, most-populous first.

    Blank/unknown country (no `CF-IPCountry` on the request -- e.g. a direct
    Railway hit bypassing Cloudflare) is folded into one `""` row rather than
    dropped, so the total still reconciles with `count`.
    """
    eng = sync_engine(dsn)
    with eng.connect() as conn:
        rows = (
            conn.execute(SELECT_ACTIVE_BY_COUNTRY, {"active_seconds": active_seconds})
            .mappings()
            .all()
        )
    countries = [{"code": str(r["country"]), "count": int(r["n"])} for r in rows]
    return {"count": sum(c["count"] for c in countries), "countries": countries}
