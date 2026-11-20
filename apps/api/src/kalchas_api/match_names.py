"""Names for matches our own tables no longer know, from the football provider.

The visitor log keeps viewed match ids for 30 days, but a match is only named
in our tables if it is still live, was archived, was on a watchlist or got an
alert. For the few left over, the admin's "Most-watched matches" card asks the
provider, one match at a time, and caches the answer in ``panel_cache`` so a
match is fetched at most once (a miss is retried after a day).
"""

from __future__ import annotations

import logging
from collections.abc import Callable, MutableMapping, Sequence
from datetime import UTC, datetime, timedelta, tzinfo
from typing import Any

logger = logging.getLogger(__name__)

CACHE_PREFIX = "match_name:"
CACHE_DAYS = 30
RETRY_MISS_AFTER = timedelta(days=1)
FETCH_TIMEOUT_SECONDS = 4.0

Fetch = Callable[[str], dict[str, Any]]


def name_from_event(row: dict[str, Any]) -> dict[str, Any] | None:
    """Provider ``get_events`` row (times asked for in UTC) to our name fields."""
    home = str(row.get("match_hometeam_name") or "").strip()
    away = str(row.get("match_awayteam_name") or "").strip()
    if not home or not away:
        return None
    day = str(row.get("match_date") or "").strip()
    clock = str(row.get("match_time") or "").strip() or "00:00"
    kickoff = None
    if day:
        try:
            kickoff = datetime.fromisoformat(f"{day}T{clock}").replace(tzinfo=UTC).isoformat()
        except ValueError:
            kickoff = None
    return {
        "home_team": home,
        "away_team": away,
        "league": str(row.get("league_name") or "").strip() or None,
        "kickoff": kickoff,
    }


def provider_fetch() -> tuple[Fetch, Callable[[], None]] | None:
    """A fetcher on the shared provider client, or None without an API key."""
    try:
        from kalchas_football import FootballAPIClient

        client = FootballAPIClient(timeout=FETCH_TIMEOUT_SECONDS)
    except Exception:  # noqa: BLE001 — no key, no lookups; the card shows ids
        return None

    def fetch(match_id: str) -> dict[str, Any]:
        return client.get_fixture_events(match_id, timezone="+00:00")

    return fetch, client.close


def fill_missing_names(
    rows: Sequence[MutableMapping[str, Any]],
    zone: tzinfo,
    *,
    dsn: str,
    now: datetime | None = None,
    fetcher: Callable[[], tuple[Fetch, Callable[[], None]] | None] = provider_fetch,
) -> None:
    """Fill ``home_team``/``away_team``/``league``/``date`` in place on the
    top-matches rows that have no names. Never raises."""
    from kalchas_db.panel_cache import load_panel_cache, save_panel_cache

    from kalchas_api.insights import parse_time

    now = now or datetime.now(UTC)
    missing = [row for row in rows if not (row.get("home_team") and row.get("away_team"))]
    if not missing:
        return
    opened: tuple[Fetch, Callable[[], None]] | None = None
    tried_provider = False
    try:
        for row in missing:
            mid = str(row["match_id"])
            key = f"{CACHE_PREFIX}{mid}"
            try:
                cached = load_panel_cache(dsn, key, ttl_days=CACHE_DAYS)
            except Exception:  # noqa: BLE001 — cache is optional
                cached = None
            name = (cached or {}).get("name")
            checked = parse_time((cached or {}).get("checked_at"))
            fresh_miss = (
                cached is not None and not name and checked and now - checked < RETRY_MISS_AFTER
            )
            if not name and not fresh_miss:
                if not tried_provider:
                    tried_provider = True
                    opened = fetcher()
                if opened is None:
                    continue
                try:
                    name = name_from_event(opened[0](mid) or {})
                except Exception as exc:  # noqa: BLE001 — stop asking a failing provider
                    logger.warning("match name lookup failed for %s: %s", mid, exc)
                    break
                try:
                    save_panel_cache(dsn, key, {"name": name, "checked_at": now.isoformat()})
                except Exception:  # noqa: BLE001,S110 — cache write is best effort
                    pass
            if not name:
                continue
            row["home_team"] = name.get("home_team")
            row["away_team"] = name.get("away_team")
            row["league"] = row.get("league") or name.get("league")
            kickoff = parse_time(name.get("kickoff"))
            if not row.get("date") and kickoff:
                row["date"] = kickoff.astimezone(zone).date().isoformat()
    finally:
        if opened is not None:
            try:
                opened[1]()
            except Exception:  # noqa: BLE001,S110
                pass
