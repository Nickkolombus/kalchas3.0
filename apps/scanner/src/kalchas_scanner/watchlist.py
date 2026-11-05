"""Builds today's and tomorrow's pre-match watchlist, then settles it.

Runs on its own thread with its own API client and hourly budget, so a slow
build never holds up the live scan. Covers the matches bookmakers price (one
``get_odds`` call says which). Team history comes one call per league rather
than per team, which is what keeps a busy Saturday inside the budget; teams
with too few games in that competition (cup ties, European nights) fall back
to their own fixtures across all competitions.

Every provider read is cached in ``panel_cache``, so a rebuild every few
hours mostly reuses what the last one fetched and refreshes odds.

Pages go to the permanent archive (``kalchas_db.watchlist``), which the API
reads. A match's page is frozen at kick-off: later rebuilds leave it alone,
so the list a visitor saw before the game is the one it is judged on. After
full time one ``get_events`` call per day brings the scores, and each
pattern is marked landed or missed (``kalchas_core.watchlist.results``).

Dry run against the real provider, no database:
``uv run --env-file .env python -m kalchas_scanner.watchlist --day tomorrow``
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import threading
import time
from collections.abc import Callable, Mapping
from datetime import UTC, date, datetime, timedelta, timezone
from typing import Any, Protocol

from kalchas_core.h2h import DEFAULT_LAST, build_h2h_payload, orient_h2h_payload
from kalchas_core.watchlist import (
    NO_RESULT,
    PlayedGame,
    TeamProfile,
    assemble_day,
    build_match_research,
    build_team_profile,
    cap_levels,
    has_covered_games,
    is_settled,
    league_norms,
    match_result,
    played_game,
    settle_page,
    team_shots,
)
from kalchas_football import FootballAPIClient, RateLimitBudgetExceeded

logger = logging.getLogger("kalchas.scanner.watchlist")

REBUILD_SEC = 3 * 3600
SETTLE_SEC = 15 * 60
SETTLE_AFTER = timedelta(minutes=110)
"""Kick-off plus this and a match should be over; only then is it looked up."""
FAST_RETRY_SEC = 120
BOARD_ENDED = frozenset({"FT", "AET", "PEN", "PST", "CANC", "AWD"})
"""Statuses the live scanner writes when a match is over or called off."""
SETTLE_DAYS = 3
"""Days back still checked for results (late finishes, slow provider data)."""
GIVE_UP_AFTER = timedelta(hours=48)
"""Still no result this long after kick-off: the match is marked "No result"."""
LEAGUE_HISTORY_HOURS = 12
TEAM_HISTORY_HOURS = 12
TABLE_HOURS = 6
SHORT_H2H_HOURS = 24
KEEP_HOURS = 72
HISTORY_DAYS = 120
RECORD_DAYS = 180
MEETINGS_LOOKED_AT = 10
MEETING_CALLS_PER_BUILD = 100
"""Past meetings fetched one by one for their penalties and corners. Each is
kept for good (a played match doesn't change), so a pair costs its calls
once; this caps a heavy first build and the rest come at the next one."""
MEETING_HOURS = 365 * 24
MIN_COMPETITION_GAMES = 6
"""Fewer league/cup games than this and a team's profile uses all competitions."""
SHOT_COMPETITION_GAMES = 10
"""Covered games in the competition before player shots stop reaching for
the team's games in all competitions."""

SKIP_STATUS = frozenset({"FT", "AET", "PEN", "PST", "CANC", "AWD"})
DEFAULT_TIMEZONE = "+03:00"
LEGACY_MATCH_PREFIX = "watchlist_match_"
"""Pages from before the archive, held in ``panel_cache`` for 72 hours."""


def tz_from_offset(offset: str) -> timezone:
    match = re.fullmatch(r"([+-])(\d{2}):(\d{2})", offset.strip())
    if not match:
        return UTC
    sign = 1 if match.group(1) == "+" else -1
    return timezone(sign * timedelta(hours=int(match.group(2)), minutes=int(match.group(3))))


def kickoff_iso(fixture: Mapping[str, Any], offset: str) -> str:
    day = str(fixture.get("match_date") or "")
    clock = str(fixture.get("match_time") or "")
    if not re.fullmatch(r"\d{2}:\d{2}", clock):
        clock = "00:00"
    return f"{day}T{clock}:00{offset}"


def kickoff_at(page: Mapping[str, Any]) -> datetime | None:
    try:
        return datetime.fromisoformat(str(page.get("kickoff") or ""))
    except ValueError:
        return None


def has_started(page: Mapping[str, Any], now: datetime) -> bool:
    at = kickoff_at(page)
    return at is not None and at <= now


class Cache(Protocol):
    def load(self, key: str, *, ttl_hours: int) -> dict[str, Any] | None: ...

    def save(self, key: str, payload: dict[str, Any]) -> None: ...


class PanelCache:
    def __init__(self, dsn: str) -> None:
        self.dsn = dsn

    def load(self, key: str, *, ttl_hours: int) -> dict[str, Any] | None:
        from kalchas_db.panel_cache import load_panel_cache

        return load_panel_cache(self.dsn, key, ttl_hours=ttl_hours)

    def save(self, key: str, payload: dict[str, Any]) -> None:
        from kalchas_db.panel_cache import save_panel_cache

        save_panel_cache(self.dsn, key, payload)


class MemoryCache:
    """For dry runs and tests."""

    def __init__(self, rows: dict[str, dict[str, Any]] | None = None) -> None:
        self.rows: dict[str, dict[str, Any]] = dict(rows or {})

    def load(self, key: str, *, ttl_hours: int) -> dict[str, Any] | None:
        return self.rows.get(key)

    def save(self, key: str, payload: dict[str, Any]) -> None:
        self.rows[key] = payload


class Store(Protocol):
    """Where match pages and day lists are kept for good."""

    def pages_on(self, day: str) -> list[dict[str, Any]]: ...

    def save_page(self, day: str, page: dict[str, Any]) -> None: ...

    def drop_page(self, match_id: str) -> None: ...

    def save_day(self, day: str, doc: dict[str, Any]) -> None: ...


class ArchiveStore:
    def __init__(self, dsn: str) -> None:
        self.dsn = dsn

    def pages_on(self, day: str) -> list[dict[str, Any]]:
        from kalchas_db.watchlist import load_watchlist_matches_on

        return load_watchlist_matches_on(self.dsn, day)

    def save_page(self, day: str, page: dict[str, Any]) -> None:
        from kalchas_db.watchlist import save_watchlist_match

        save_watchlist_match(self.dsn, day, page, settled=is_settled(page))

    def drop_page(self, match_id: str) -> None:
        from kalchas_db.watchlist import delete_watchlist_match

        delete_watchlist_match(self.dsn, match_id)

    def save_day(self, day: str, doc: dict[str, Any]) -> None:
        from kalchas_db.watchlist import save_watchlist_day

        save_watchlist_day(self.dsn, day, doc)


class MemoryStore:
    """For dry runs and tests."""

    def __init__(self) -> None:
        self.pages: dict[str, tuple[str, dict[str, Any]]] = {}
        self.days: dict[str, dict[str, Any]] = {}

    def pages_on(self, day: str) -> list[dict[str, Any]]:
        return [page for d, page in self.pages.values() if d == day]

    def save_page(self, day: str, page: dict[str, Any]) -> None:
        self.pages[str(page["match_id"])] = (day, page)

    def drop_page(self, match_id: str) -> None:
        self.pages.pop(match_id, None)

    def save_day(self, day: str, doc: dict[str, Any]) -> None:
        self.days[day] = doc


Records = tuple[dict[tuple[str, str], dict[str, int]], dict[str, int] | None]


def load_records(dsn: str, now: datetime | None = None) -> Records:
    """Our settled alerts per (country, league) and overall, last `RECORD_DAYS`.
    Kept on each page for internal use; the public API leaves them out."""
    from kalchas_db.alerts import alert_record_by_league_sync

    since = (now or datetime.now(UTC)) - timedelta(days=RECORD_DAYS)
    rows = alert_record_by_league_sync(dsn, since=since)
    by_league: dict[tuple[str, str], dict[str, int]] = {}
    confirmed = settled = 0
    for row in rows:
        c, s = int(row.get("confirmed") or 0), int(row.get("settled") or 0)
        confirmed += c
        settled += s
        key = (str(row.get("country") or ""), str(row.get("league") or ""))
        by_league[key] = {"confirmed": c, "settled": s}
    overall = {"confirmed": confirmed, "settled": settled} if settled else None
    return by_league, overall


def _latest_build(pages: list[dict[str, Any]]) -> str:
    return max((str(p.get("built_at") or "") for p in pages), default="")


class WatchlistBuilder:
    def __init__(
        self,
        client: FootballAPIClient,
        cache: Cache,
        store: Store,
        *,
        offset: str = DEFAULT_TIMEZONE,
        records: Callable[[], Records] | None = None,
    ) -> None:
        self.client = client
        self.cache = cache
        self.store = store
        self.offset = offset
        self.records = records
        self._meeting_calls = MEETING_CALLS_PER_BUILD

    # -------------------------------------------------------------- reads

    def _cached(
        self,
        key: str,
        ttl_hours: int,
        fetch: Callable[[], dict[str, Any]],
    ) -> dict[str, Any] | None:
        """Cache-then-fetch. `None` when the fetch failed or ran out of budget;
        a successful empty fetch is cached like any other."""
        try:
            cached = self.cache.load(key, ttl_hours=ttl_hours)
        except Exception:
            logger.exception("watchlist cache read failed for %s", key)
            cached = None
        if cached is not None:
            return cached
        try:
            payload = fetch()
        except RateLimitBudgetExceeded:
            logger.warning("watchlist: budget spent, skipping %s", key)
            return None
        except Exception:
            logger.exception("watchlist fetch failed for %s", key)
            return None
        try:
            self.cache.save(key, payload)
        except Exception:
            logger.exception("watchlist cache write failed for %s", key)
        return payload

    def _league_history(self, league_id: int) -> list[dict[str, Any]] | None:
        block = self._cached(
            f"wl_league_{league_id}",
            LEAGUE_HISTORY_HOURS,
            lambda: {
                "fixtures": self.client.get_league_fixtures(
                    league_id, days_back=HISTORY_DAYS, player_stats=True
                )
            },
        )
        return None if block is None else list(block.get("fixtures") or [])

    def _team_history(self, team_id: int) -> list[dict[str, Any]] | None:
        block = self._cached(
            f"wl_team_{team_id}",
            TEAM_HISTORY_HOURS,
            lambda: {
                "fixtures": self.client.get_team_fixtures(
                    team_id, days_back=HISTORY_DAYS, player_stats=True
                )
            },
        )
        return None if block is None else list(block.get("fixtures") or [])

    def _shots(
        self, history: list[dict[str, Any]], team_id: int, source: str
    ) -> dict[str, Any] | None:
        """The team's shooters. From the competition when it has enough
        covered games; otherwise from all competitions, fetched only if the
        profile already did or the provider covers this competition at all
        (most competitions it doesn't, and a call per team there would be
        wasted budget)."""
        here = team_shots(history, team_id) if source != "all" else None
        if source != "all" and (
            (here and here["games"] >= SHOT_COMPETITION_GAMES) or not has_covered_games(history)
        ):
            return here
        wider = self._team_history(team_id)
        found = team_shots(wider, team_id, source="all") if wider else None
        if found is None or (here and here["games"] >= found["games"]):
            return here
        return found

    def _table(self, league_id: int) -> list[dict[str, Any]]:
        block = self._cached(
            f"wl_table_{league_id}",
            TABLE_HOURS,
            lambda: {"rows": self.client.get_standings_table(league_id)},
        )
        return list((block or {}).get("rows") or [])

    def _h2h(self, fixture: Mapping[str, Any]) -> dict[str, Any] | None:
        """Oriented H2H payload. Shares the ``h2h_<lo>_<hi>`` row the match
        panel uses; thin pairs (under 5 meetings) go in a shorter-lived row
        of their own, so they are not refetched every build."""
        from kalchas_db.panel_cache import pair_cache_key

        home_id, away_id = int(fixture["home_team_id"]), int(fixture["away_team_id"])
        home, away = str(fixture["home_team"]), str(fixture["away_team"])
        shared = pair_cache_key("h2h", home_id, away_id)
        thin = pair_cache_key("wl_h2h", home_id, away_id)
        cached = None
        for key, ttl in ((shared, 7 * 24), (thin, SHORT_H2H_HOURS)):
            try:
                cached = self.cache.load(key, ttl_hours=ttl)
            except Exception:  # noqa: BLE001
                cached = None
            if cached:
                break
        if not cached:
            try:
                meetings = self.client.get_head_to_head(home_id, away_id, last=DEFAULT_LAST)
            except RateLimitBudgetExceeded:
                return None
            except Exception:
                logger.exception("watchlist H2H failed for %s", fixture.get("match_id"))
                return None
            cached = build_h2h_payload(
                meetings,
                home_team_id=home_id,
                away_team_id=away_id,
                home_team=home,
                away_team=away,
            )
            try:
                self.cache.save(shared if cached["summary"]["sample"] >= 5 else thin, cached)
            except Exception:
                logger.exception("watchlist H2H cache write failed")
        return orient_h2h_payload(
            cached, home_team_id=home_id, away_team_id=away_id, home_team=home, away_team=away
        )

    def _meetings(self, h2h: Mapping[str, Any] | None, home_id: int) -> list[PlayedGame]:
        """The last meetings with their detail (goal times, corners), from
        the home side's point of view. Only for matches already standing
        out: these back a match up, they don't make one."""
        out: list[PlayedGame] = []
        for meeting in ((h2h or {}).get("fixtures") or [])[:MEETINGS_LOOKED_AT]:
            match_id = str(meeting.get("match_id") or "")
            if not match_id:
                continue
            key = f"meeting_{match_id}"  # outside the 72-hour "wl_" cleanup
            try:
                block = self.cache.load(key, ttl_hours=MEETING_HOURS)
            except Exception:  # noqa: BLE001
                block = None
            if block is None:
                if self._meeting_calls <= 0:
                    continue
                self._meeting_calls -= 1
                try:
                    block = {"row": self.client.get_match(match_id)}
                except RateLimitBudgetExceeded:
                    self._meeting_calls = 0
                    continue
                except Exception:
                    logger.exception("watchlist: meeting %s unavailable", match_id)
                    continue
                try:
                    self.cache.save(key, block)
                except Exception:
                    logger.exception("watchlist cache write failed for %s", key)
            row = block.get("row")
            game = played_game(row, home_id) if row else None
            if game is not None:
                out.append(game)
        return out

    def _profile(
        self, history: list[dict[str, Any]], team_id: int, name: str
    ) -> tuple[TeamProfile, str]:
        profile = build_team_profile(history, team_id, name=name)
        if profile.n >= MIN_COMPETITION_GAMES:
            return profile, "competition"
        wider = self._team_history(team_id)
        if wider:
            fuller = build_team_profile(wider, team_id, name=name)
            if fuller.n > profile.n:
                return fuller, "all"
        return profile, "competition"

    # -------------------------------------------------------------- build

    def build_day(self, day: date, *, now: datetime | None = None) -> dict[str, Any] | None:
        """(Re)build the pages of matches still to kick off, keep the ones
        that have started exactly as they were, and write the day's list."""
        day_str = day.isoformat()
        now = now or datetime.now(UTC)
        built_at = now.isoformat()
        try:
            fixtures = self.client.get_fixtures_on(day_str, timezone=self.offset)
            odds_by_match = self.client.get_odds_markets_on(day_str)
        except RateLimitBudgetExceeded:
            logger.warning("watchlist %s: budget spent before fixtures", day_str)
            return None

        stored = {str(p["match_id"]): p for p in self.store.pages_on(day_str)}
        frozen = {mid for mid, page in stored.items() if has_started(page, now)}
        priced = {
            fx["match_id"]: fx
            for fx in fixtures
            if fx["match_id"] in odds_by_match and fx.get("status_short") not in SKIP_STATUS
        }
        for mid in set(stored) - frozen - set(priced):
            # Lost its price, or moved to another day, before kick-off.
            try:
                self.store.drop_page(mid)
            except Exception:
                logger.exception("watchlist: could not drop %s", mid)
            stored.pop(mid, None)
        # Only matches still to kick off are (re)built: a pick made after
        # kick-off is not a pick, and a frozen page is what gets judged.
        upcoming = [
            fx
            for mid, fx in priced.items()
            if mid not in frozen and not has_started({"kickoff": kickoff_iso(fx, self.offset)}, now)
        ]

        records: Records = ({}, None)
        if self.records is not None:
            try:
                records = self.records()
            except Exception:
                logger.exception("watchlist: alert record unavailable")
        by_league_record, overall = records

        histories: dict[int, list[dict[str, Any]] | None] = {}
        tables: dict[int, list[dict[str, Any]]] = {}
        partial = False
        self._meeting_calls = MEETING_CALLS_PER_BUILD

        for fx in sorted(upcoming, key=lambda f: (f["match_time"], f["match_id"])):
            league_id = int(fx.get("league_id") or 0)
            if league_id not in histories:
                histories[league_id] = self._league_history(league_id)
                tables[league_id] = self._table(league_id)
            history = histories[league_id]
            if history is None:
                partial = True  # the last good page, if there is one, stays
                continue

            home, home_source = self._profile(history, fx["home_team_id"], fx["home_team"])
            away, away_source = self._profile(history, fx["away_team_id"], fx["away_team"])
            h2h = self._h2h(fx)
            inputs: dict[str, Any] = {
                "kickoff": kickoff_iso(fx, self.offset),
                "home": home,
                "away": away,
                "home_source": home_source,
                "away_source": away_source,
                "norms": league_norms(history),
                "odds": odds_by_match.get(fx["match_id"]),
                "h2h": h2h,
                "table": tables[league_id],
                "league_record": by_league_record.get((fx["country_name"], fx["league_name"])),
                "overall_record": overall,
                "shots": {
                    "home": self._shots(history, int(fx["home_team_id"]), home_source),
                    "away": self._shots(history, int(fx["away_team_id"]), away_source),
                },
            }
            research = build_match_research(fx, **inputs)
            if research["watch"] != "quiet":
                meetings = self._meetings(h2h, int(fx["home_team_id"]))
                if meetings:
                    research = build_match_research(fx, **inputs, meetings=meetings)
            research["day"] = day_str
            research["built_at"] = built_at
            research["result"] = None
            try:
                self.store.save_page(day_str, research)
            except Exception:
                logger.exception("watchlist: could not store %s", fx["match_id"])
                partial = True
                continue
            stored[fx["match_id"]] = research

        # A short list on purpose: at most `day_cap` strong watches (and as
        # many worth a look); matches already under way keep their rating.
        for page in cap_levels(list(stored.values()), day=day_str, keep=frozen):
            try:
                self.store.save_page(day_str, page)
            except Exception:
                logger.exception("watchlist: could not store %s", page["match_id"])
                continue
            stored[str(page["match_id"])] = page

        doc = assemble_day(
            day_str, list(stored.values()), built_at=built_at, timezone=self.offset, partial=partial
        )
        self.store.save_day(day_str, doc)
        logger.info(
            "watchlist %s: %s matches in %s leagues, %s already started%s",
            day_str,
            len(doc["matches"]),
            len(doc["leagues"]),
            len(frozen),
            " (partial)" if partial else "",
        )
        return doc

    # ------------------------------------------------------------- settle

    def settle_day(
        self,
        day: date,
        *,
        now: datetime | None = None,
        finished: set[str] | frozenset[str] = frozenset(),
    ) -> int:
        """Give finished matches their score and each pattern its outcome.

        One provider call, made only when a listed match should be over and
        is not settled yet. Returns how many pages it settled."""
        day_str = day.isoformat()
        now = now or datetime.now(UTC)
        pages = self.store.pages_on(day_str)
        due = [
            p
            for p in pages
            if not is_settled(p)
            and (
                str(p["match_id"]) in finished
                or ((at := kickoff_at(p)) is not None and at + SETTLE_AFTER <= now)
            )
        ]
        if not due:
            return 0
        try:
            rows = self.client.get_results_on(day_str, timezone=self.offset)
        except RateLimitBudgetExceeded:
            logger.warning("watchlist %s: budget spent before results", day_str)
            return 0
        results = {str(r["match_id"]): r for r in rows}

        by_id = {str(p["match_id"]): p for p in pages}
        settled = 0
        for page in due:
            row = results.get(str(page["match_id"]))
            result = match_result(row) if row else None
            if result is None and (at := kickoff_at(page)) and at + GIVE_UP_AFTER <= now:
                result = dict(NO_RESULT)
            if result is None:
                continue
            done = settle_page(page, result)
            try:
                self.store.save_page(day_str, done)
            except Exception:
                logger.exception("watchlist: could not settle %s", page["match_id"])
                continue
            by_id[str(page["match_id"])] = done
            settled += 1
        if settled:
            pages = list(by_id.values())
            doc = assemble_day(day_str, pages, built_at=_latest_build(pages), timezone=self.offset)
            self.store.save_day(day_str, doc)
            logger.info("watchlist %s: settled %s matches", day_str, settled)
        return settled

    def adopt(self, pages: list[dict[str, Any]]) -> list[str]:
        """Copy pages built before the archive into it, for days the archive
        has nothing on yet. Returns the days it filled."""
        by_day: dict[str, list[dict[str, Any]]] = {}
        for page in pages:
            if page.get("day") and page.get("match_id"):
                by_day.setdefault(str(page["day"]), []).append({"result": None, **page})
        filled: list[str] = []
        for day_str, day_pages in sorted(by_day.items()):
            if self.store.pages_on(day_str):
                continue
            for page in day_pages:
                self.store.save_page(day_str, page)
            doc = assemble_day(
                day_str, day_pages, built_at=_latest_build(day_pages), timezone=self.offset
            )
            self.store.save_day(day_str, doc)
            filled.append(day_str)
        return filled


class WatchlistJob:
    """Rebuilds today and tomorrow every `REBUILD_SEC`, and as soon as the
    date rolls over in the board's time zone. Settles results every
    `SETTLE_SEC`."""

    def __init__(self, builder: WatchlistBuilder, *, dsn: str | None) -> None:
        self.builder = builder
        self.dsn = dsn
        self.zone = tz_from_offset(builder.offset)
        self._fast_tried: dict[date, float] = {}

    def adopt_legacy(self) -> None:
        """Days built before the archive existed keep their list."""
        if not self.dsn:
            return
        try:
            from kalchas_db.panel_cache import load_panel_cache_prefix

            pages = load_panel_cache_prefix(self.dsn, LEGACY_MATCH_PREFIX, hours=KEEP_HOURS)
            filled = self.builder.adopt(pages)
            if filled:
                logger.info("watchlist: archived earlier days %s", ", ".join(filled))
        except Exception:
            logger.exception("watchlist: adopting earlier pages failed")

    def run_once(self) -> None:
        today = datetime.now(self.zone).date()
        for day in (today, today + timedelta(days=1)):
            try:
                self.builder.build_day(day)
            except Exception:
                logger.exception("watchlist build failed for %s", day)
        if self.dsn:
            try:
                from kalchas_db.panel_cache import delete_panel_cache_older

                for prefix in ("watchlist_", "wl_"):
                    delete_panel_cache_older(self.dsn, prefix, hours=KEEP_HOURS)
                delete_panel_cache_older(self.dsn, "meeting_", hours=MEETING_HOURS)
            except Exception:
                logger.exception("watchlist cleanup failed")

    def ended_on_the_board(self, day: date) -> set[str]:
        """Listed, unsettled matches the live scanner has seen end: their
        results can be fetched now instead of at the next settle round."""
        if not self.dsn:
            return set()
        now = datetime.now(UTC)
        pages = self.builder.store.pages_on(day.isoformat())
        ids = [
            str(p["match_id"])
            for p in pages
            if not is_settled(p) and (at := kickoff_at(p)) is not None and at <= now
        ]
        if not ids:
            return set()
        from kalchas_db.matches import get_matches_sync

        rows = get_matches_sync(self.dsn, ids)
        return {
            mid
            for mid, row in rows.items()
            if str(row.get("status_short") or "").upper() in BOARD_ENDED
        }

    def settle_ended(self) -> None:
        """Settle right after full time. Retries a day at most every
        `FAST_RETRY_SEC`, as the provider's results can lag the live feed."""
        today = datetime.now(self.zone).date()
        for day in (today - timedelta(days=1), today):
            try:
                ended = self.ended_on_the_board(day)
                if not ended:
                    continue
                if time.monotonic() - self._fast_tried.get(day, float("-inf")) < FAST_RETRY_SEC:
                    continue
                self._fast_tried[day] = time.monotonic()
                self.builder.settle_day(day, finished=ended)
            except Exception:
                logger.exception("watchlist quick settle failed for %s", day)

    def settle_once(self) -> None:
        today = datetime.now(self.zone).date()
        for back in range(SETTLE_DAYS, -1, -1):
            day = today - timedelta(days=back)
            try:
                self.builder.settle_day(day)
            except Exception:
                logger.exception("watchlist settle failed for %s", day)

    def run_forever(self) -> None:
        self.adopt_legacy()
        last_day: date | None = None
        last_run = last_settle = float("-inf")
        while True:
            today = datetime.now(self.zone).date()
            if today != last_day or time.monotonic() - last_run >= REBUILD_SEC:
                self.run_once()
                last_day, last_run = today, time.monotonic()
            if time.monotonic() - last_settle >= SETTLE_SEC:
                self.settle_once()
                last_settle = time.monotonic()
            self.settle_ended()
            time.sleep(60)

    def start(self) -> threading.Thread:
        thread = threading.Thread(target=self.run_forever, name="watchlist", daemon=True)
        thread.start()
        return thread


def start_watchlist_thread() -> threading.Thread | None:
    """Started by the scanner entry point. Off with ``WATCHLIST_ENABLED=0``."""
    if os.environ.get("WATCHLIST_ENABLED", "1").lower() in {"0", "false", "no"}:
        return None
    dsn = os.environ.get("DATABASE_URL") or os.environ.get("POSTGRES_URL")
    if not dsn:
        logger.info("watchlist off: no DATABASE_URL")
        return None
    budget = int(os.environ.get("WATCHLIST_REQUESTS_PER_HOUR") or 200)
    client = FootballAPIClient(requests_per_hour=budget)
    builder = WatchlistBuilder(
        client,
        PanelCache(dsn),
        ArchiveStore(dsn),
        offset=os.environ.get("FOOTBALL_TIMEZONE", DEFAULT_TIMEZONE),
        records=lambda: load_records(dsn),
    )
    return WatchlistJob(builder, dsn=dsn).start()


def main() -> None:
    parser = argparse.ArgumentParser(description="Dry-run the watchlist, no database.")
    parser.add_argument("--day", default="tomorrow", help="today | tomorrow | YYYY-MM-DD")
    parser.add_argument("--match", help="print the full research page for this match_id")
    parser.add_argument("--cache-file", help="JSON file to reuse provider reads between runs")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    offset = os.environ.get("FOOTBALL_TIMEZONE", DEFAULT_TIMEZONE)
    today = datetime.now(tz_from_offset(offset)).date()
    day = {"today": today, "tomorrow": today + timedelta(days=1)}.get(args.day)
    day = day or date.fromisoformat(args.day)
    stored: dict[str, dict[str, Any]] = {}
    if args.cache_file and os.path.exists(args.cache_file):
        with open(args.cache_file, encoding="utf-8") as fh:
            stored = json.load(fh)
    cache = MemoryCache(stored)
    store = MemoryStore()
    with FootballAPIClient() as client:
        doc = WatchlistBuilder(client, cache, store, offset=offset).build_day(day)
    if args.cache_file:
        with open(args.cache_file, "w", encoding="utf-8") as fh:
            json.dump(cache.rows, fh)
    if not doc:
        return
    if args.match:
        page = store.pages.get(args.match)
        print(json.dumps(page[1] if page else None, indent=2))
        return
    by_id = {r["match_id"]: r for r in doc["matches"]}
    print(f"\n{doc['day']}: {len(doc['matches'])} matches. Shortlist:")
    for match_id in doc["shortlist"]:
        row = by_id[match_id]
        print(f"  {row['score']:.2f} {row['home']['name']} v {row['away']['name']}")
        print(f"       {row['headline']} {row['reason']}")
    levels: dict[str, int] = {}
    for row in doc["matches"]:
        levels[row["watch"]] = levels.get(row["watch"], 0) + 1
    print("\nlevels:", levels)
    print("\nall, best first:")
    for row in sorted(doc["matches"], key=lambda r: -r["score"]):
        tags = ", ".join(t["label"] for t in row["tags"])
        print(
            f"  {row['score']:.2f} {row['watch']:<6} {row['home']['name']} v "
            f"{row['away']['name']} | {tags}"
        )


if __name__ == "__main__":
    main()
