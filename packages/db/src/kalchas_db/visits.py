"""Visitor log: one row per visit, for the admin Visitors tab.

Two writers feed it:

* every HTML page load (server side, no JS needed) -- recorded as an
  anonymous row keyed by masked IP + user agent, ``visitor_id`` NULL;
* every board poll that carries a visitor id (the JS heartbeat the live
  count already uses).

When a heartbeat arrives, any anonymous page-load rows from the same masked
IP and user agent inside the visit gap are folded into that visitor's visit,
so a human shows up once with their referrer and landing path, and the rows
that stay anonymous are the clients that never ran JS.

A visit ends after `VISIT_GAP_SECONDS` of silence; rows older than
`RETENTION_DAYS` are deleted whenever a new visit starts.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import text

from kalchas_db.sync import sync_engine

VISIT_GAP_SECONDS = 1800
"""Silence longer than this starts a new visit (the usual 30-minute rule)."""

RETENTION_DAYS = 30

MAX_MATCHES_PER_VISIT = 50

FIND_ANON_PAGE_LOAD = text(
    """
    SELECT id FROM visitor_sessions
    WHERE visitor_id IS NULL
      AND ip_masked IS NOT DISTINCT FROM :ip_masked
      AND user_agent IS NOT DISTINCT FROM :user_agent
      AND last_seen >= NOW() - (:gap_seconds || ' seconds')::INTERVAL
    ORDER BY last_seen DESC
    LIMIT 1
    """
)

TOUCH_PAGE_LOAD = text(
    """
    UPDATE visitor_sessions SET
        last_seen = NOW(),
        page_loads = page_loads + 1,
        country = COALESCE(:country, country),
        referrer = COALESCE(referrer, :referrer)
    WHERE id = :id
    """
)

INSERT_PAGE_LOAD = text(
    """
    INSERT INTO visitor_sessions (
        visitor_id, ip_masked, country, user_agent, referrer, landing_path, page_loads
    ) VALUES (NULL, :ip_masked, :country, :user_agent, :referrer, :landing_path, 1)
    """
)

FIND_FOR_HEARTBEAT = text(
    """
    SELECT id, visitor_id, page_loads, referrer, landing_path, first_seen
    FROM visitor_sessions
    WHERE last_seen >= NOW() - (:gap_seconds || ' seconds')::INTERVAL
      AND (
        visitor_id = :visitor_id
        OR (
          visitor_id IS NULL
          AND ip_masked IS NOT DISTINCT FROM :ip_masked
          AND user_agent IS NOT DISTINCT FROM :user_agent
        )
      )
    ORDER BY (visitor_id IS NULL), last_seen DESC
    """
)

TOUCH_HEARTBEAT = text(
    """
    UPDATE visitor_sessions SET
        visitor_id = :visitor_id,
        last_seen = NOW(),
        first_seen = LEAST(first_seen, :first_seen),
        heartbeats = heartbeats + 1,
        page_loads = page_loads + :absorbed_loads,
        ip_masked = COALESCE(:ip_masked, ip_masked),
        country = COALESCE(:country, country),
        user_agent = COALESCE(:user_agent, user_agent),
        referrer = COALESCE(referrer, :referrer),
        landing_path = COALESCE(landing_path, :landing_path),
        matches_viewed = CASE
            WHEN CAST(:match_id AS TEXT) IS NULL
              OR CAST(:match_id AS TEXT) = ANY(matches_viewed)
              OR cardinality(matches_viewed) >= :max_matches
            THEN matches_viewed
            ELSE array_append(matches_viewed, CAST(:match_id AS TEXT))
        END
    WHERE id = :id
    """
)

INSERT_HEARTBEAT = text(
    """
    INSERT INTO visitor_sessions (
        visitor_id, ip_masked, country, user_agent, referrer, heartbeats, matches_viewed
    ) VALUES (
        :visitor_id, :ip_masked, :country, :user_agent, :referrer, 1,
        CASE WHEN CAST(:match_id AS TEXT) IS NULL THEN '{}'::TEXT[]
             ELSE ARRAY[CAST(:match_id AS TEXT)] END
    )
    """
)

DELETE_IDS = text("DELETE FROM visitor_sessions WHERE id = ANY(:ids)")

MARK_TELEGRAM = {
    "telegram_free": text(
        """
        UPDATE visitor_sessions SET telegram_free = TRUE
        WHERE id = (
            SELECT id FROM visitor_sessions WHERE visitor_id = :visitor_id
            ORDER BY last_seen DESC LIMIT 1
        )
        """
    ),
    "telegram_paid": text(
        """
        UPDATE visitor_sessions SET telegram_paid = TRUE
        WHERE id = (
            SELECT id FROM visitor_sessions WHERE visitor_id = :visitor_id
            ORDER BY last_seen DESC LIMIT 1
        )
        """
    ),
}

PRUNE_OLD = text(
    """
    DELETE FROM visitor_sessions
    WHERE last_seen < NOW() - (:retention_days || ' days')::INTERVAL
    """
)

SELECT_VISITS = text(
    """
    SELECT s.id, s.visitor_id, s.ip_masked, s.country, s.user_agent, s.referrer,
           s.landing_path, s.first_seen, s.last_seen, s.page_loads, s.heartbeats,
           s.matches_viewed, s.telegram_free, s.telegram_paid,
           v.first_ever, v.visit_count
    FROM visitor_sessions s
    LEFT JOIN LATERAL (
        SELECT MIN(first_seen) AS first_ever, COUNT(*)::int AS visit_count
        FROM visitor_sessions s2
        WHERE s2.visitor_id = s.visitor_id
    ) v ON s.visitor_id IS NOT NULL
    WHERE s.last_seen >= :since AND s.first_seen < :until
    ORDER BY s.last_seen DESC
    LIMIT :limit
    """
)

SELECT_MATCH_NAMES = text(
    """
    SELECT match_id, home_team, away_team FROM matches WHERE match_id = ANY(:ids)
    """
)


def record_page_load(
    dsn: str,
    *,
    ip_masked: str | None,
    country: str | None,
    user_agent: str | None,
    referrer: str | None,
    landing_path: str | None,
) -> None:
    """Log one HTML page load; repeat loads inside the gap extend the same row."""
    params = {
        "ip_masked": ip_masked,
        "country": country or None,
        "user_agent": user_agent or None,
        "referrer": referrer,
        "landing_path": landing_path,
        "gap_seconds": VISIT_GAP_SECONDS,
    }
    eng = sync_engine(dsn)
    with eng.begin() as conn:
        found = conn.execute(FIND_ANON_PAGE_LOAD, params).scalar()
        if found is not None:
            conn.execute(TOUCH_PAGE_LOAD, {**params, "id": found})
            return
        conn.execute(INSERT_PAGE_LOAD, params)
        conn.execute(PRUNE_OLD, {"retention_days": RETENTION_DAYS})


def record_heartbeat(
    dsn: str,
    visitor_id: str,
    *,
    ip_masked: str | None,
    country: str | None,
    user_agent: str | None,
    referrer: str | None,
    match_id: str | None,
) -> None:
    """Extend this visitor's open visit, adopting their anonymous page loads.

    The visitor's own open visit wins; failing that, the newest anonymous page
    load from the same masked IP and user agent becomes their visit. Any other
    matching anonymous rows are merged in and deleted, so a refresh doesn't
    leave a "no JS" ghost behind.
    """
    if not visitor_id:
        return
    params = {
        "visitor_id": visitor_id,
        "ip_masked": ip_masked,
        "country": country or None,
        "user_agent": user_agent or None,
        "referrer": referrer,
        "match_id": match_id or None,
        "max_matches": MAX_MATCHES_PER_VISIT,
        "gap_seconds": VISIT_GAP_SECONDS,
    }
    eng = sync_engine(dsn)
    with eng.begin() as conn:
        rows = conn.execute(FIND_FOR_HEARTBEAT, params).mappings().all()
        if not rows:
            conn.execute(INSERT_HEARTBEAT, params)
            conn.execute(PRUNE_OLD, {"retention_days": RETENTION_DAYS})
            return
        keep, absorbed = rows[0], [r for r in rows[1:] if r["visitor_id"] is None]
        # The kept row's own values win; absorbed page loads only fill gaps.
        donors = [keep, *absorbed]
        conn.execute(
            TOUCH_HEARTBEAT,
            {
                **params,
                "id": keep["id"],
                "first_seen": min(r["first_seen"] for r in donors),
                "absorbed_loads": sum(int(r["page_loads"]) for r in absorbed),
                "referrer": next((r["referrer"] for r in donors if r["referrer"]), referrer),
                "landing_path": next(
                    (r["landing_path"] for r in donors if r["landing_path"]), None
                ),
            },
        )
        if absorbed:
            conn.execute(DELETE_IDS, {"ids": [int(r["id"]) for r in absorbed]})


def record_telegram_click(dsn: str, visitor_id: str, kind: str) -> None:
    """Flag the visitor's latest visit; `kind` is telegram_free or telegram_paid."""
    query = MARK_TELEGRAM.get(kind)
    if not visitor_id or query is None:
        return
    eng = sync_engine(dsn)
    with eng.begin() as conn:
        conn.execute(query, {"visitor_id": visitor_id})


def list_visits(
    dsn: str, *, since: datetime, until: datetime, limit: int = 5000
) -> list[dict[str, Any]]:
    """Visits overlapping [since, until), newest first, with per-visitor totals.

    ``first_ever`` and ``visit_count`` look across the whole retained log, not
    just the window, so "returning" means returning within the last 30 days.
    Viewed matches come back as ``{match_id, home_team, away_team}`` dicts.
    """
    eng = sync_engine(dsn)
    with eng.connect() as conn:
        rows = [
            dict(r)
            for r in conn.execute(
                SELECT_VISITS, {"since": since, "until": until, "limit": limit}
            ).mappings()
        ]
        ids = sorted({m for r in rows for m in (r.get("matches_viewed") or [])})
        names: dict[str, dict[str, Any]] = {}
        if ids:
            for m in conn.execute(SELECT_MATCH_NAMES, {"ids": ids}).mappings():
                names[str(m["match_id"])] = dict(m)
    for row in rows:
        row["matches_viewed"] = [
            names.get(m) or {"match_id": m, "home_team": None, "away_team": None}
            for m in (row.get("matches_viewed") or [])
        ]
    return rows
