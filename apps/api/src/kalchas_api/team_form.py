"""Form Bar's team form for the API's own board paths (live board, match panel,
admin preview), read-through ``panel_cache``.

Independent of the scanner's ``_team_form_for`` -- same pattern as the H2H
endpoint having its own cache-then-fetch path rather than sharing one with the
scanner's alert-time H2H lookup.
"""

from __future__ import annotations

import logging
from typing import Any

from kalchas_core.form import TeamForm

logger = logging.getLogger("kalchas.api")

TEAM_FORM_CACHE_HOURS = 12
"""Matches the scanner's TEAM_FORM_CACHE_HOURS -- a team's form only changes
when it plays a new finished fixture, so this just bounds staleness."""


def team_form_for_board(dsn: str, team_id: Any, *, fetch: bool = True) -> TeamForm | None:
    """Recent goals scored/conceded for Form Bar. `None` when nothing could be
    read or fetched; Form Bar decides whether the history is long enough.

    ``fetch=False`` reads the cache only, for paths that promise no provider
    calls (the match panel). The live board fetches, so the cache is normally
    warm by the time anyone opens a panel.
    """
    from kalchas_core.form import (
        calculate_team_form,
        form_cache_key,
        form_cache_payload,
        form_from_cache_payload,
        played_fixtures,
    )
    from kalchas_core.strategies.delta_goal import FORM_WINDOW

    try:
        tid = int(team_id)
    except (TypeError, ValueError):
        return None
    if tid <= 0:
        return None

    from kalchas_db.panel_cache import load_panel_cache, save_panel_cache

    cache_key = form_cache_key(tid)
    try:
        cached = load_panel_cache(dsn, cache_key, ttl_hours=TEAM_FORM_CACHE_HOURS)
    except Exception:  # noqa: BLE001 - missing table must not block the board
        cached = None
    form = form_from_cache_payload(cached)
    if form is not None or not fetch:
        return form

    from kalchas_football import FootballAPIClient, RateLimitBudgetExceeded

    try:
        client = FootballAPIClient()
        try:
            raw_fixtures = client.get_team_fixtures(tid)
        finally:
            client.close()
    except RateLimitBudgetExceeded:
        return None
    except Exception:
        logger.exception("team fixtures fetch failed for %s", tid)
        return None

    form = calculate_team_form(played_fixtures(raw_fixtures or []), tid, window=FORM_WINDOW)
    try:
        save_panel_cache(dsn, cache_key, form_cache_payload(form))
    except Exception:
        logger.exception("failed caching team form for %s", tid)
    return form
