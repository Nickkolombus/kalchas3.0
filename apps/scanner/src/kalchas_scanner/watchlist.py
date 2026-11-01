"""Builds today's and tomorrow's pre-match watchlist into ``panel_cache``.

Runs on its own thread with its own API client and hourly budget, so a slow
build never holds up the live scan. Covers the matches bookmakers price (one
``get_odds`` call says which). Team history comes one call per league rather
than per team, which is what keeps a busy Saturday inside the budget; teams
with too few games in that competition (cup ties, European nights) fall back
to their own fixtures across all competitions.

Every provider read is cached, so a rebuild every few hours mostly reuses
what the last one fetched and refreshes odds. The API only reads the rows
this writes: ``watchlist_day_<date>`` and ``watchlist_match_<id>``.

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
    TeamProfile,
    build_match_research,
    build_team_profile,
    league_norms,
    list_row,
    shortlist,
)
from kalchas_football import FootballAPIClient, RateLimitBudgetExceeded

logger = logging.getLogger("kalchas.scanner.watchlist")

REBUILD_SEC = 3 * 3600
LEAGUE_HISTORY_HOURS = 12
TEAM_HISTORY_HOURS = 12
TABLE_HOURS = 6
SHORT_H2H_HOURS = 24
PAGE_TTL_HOURS = 48
KEEP_HOURS = 72
HISTORY_DAYS = 120
RECORD_DAYS = 180
MIN_COMPETITION_GAMES = 6
"""Fewer league/cup games than this and a team's profile uses all competitions."""

SKIP_STATUS = frozenset({"FT", "AET", "PEN", "PST", "CANC", "AWD"})
DEFAULT_TIMEZONE = "+03:00"


def day_cache_key(day: str) -> str:
    return f"watchlist_day_{day}"


def match_cache_key(match_id: str) -> str:
    return f"watchlist_match_{match_id}"


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


Records = tuple[dict[tuple[str, str], dict[str, int]], dict[str, int] | None]


def load_records(dsn: str, now: datetime | None = None) -> Records:
    """Our settled alerts per (country, league) and overall, last `RECORD_DAYS`."""
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


class WatchlistBuilder:
    def __init__(
        self,
        client: FootballAPIClient,
        cache: Cache,
        *,
        offset: str = DEFAULT_TIMEZONE,
        records: Callable[[], Records] | None = None,
    ) -> None:
        self.client = client
        self.cache = cache
        self.offset = offset
        self.records = records

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
                "fixtures": self.client.get_league_fixtures(league_id, days_back=HISTORY_DAYS)
            },
        )
        return None if block is None else list(block.get("fixtures") or [])

    def _team_history(self, team_id: int) -> list[dict[str, Any]] | None:
        block = self._cached(
            f"wl_team_{team_id}",
            TEAM_HISTORY_HOURS,
            lambda: {"fixtures": self.client.get_team_fixtures(team_id, days_back=HISTORY_DAYS)},
        )
        return None if block is None else list(block.get("fixtures") or [])

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
        day_str = day.isoformat()
        built_at = (now or datetime.now(UTC)).isoformat()
        try:
            fixtures = self.client.get_fixtures_on(day_str, timezone=self.offset)
            odds_by_match = self.client.get_odds_markets_on(day_str)
        except RateLimitBudgetExceeded:
            logger.warning("watchlist %s: budget spent before fixtures", day_str)
            return None
        fixtures = [
            fx
            for fx in fixtures
            if fx["match_id"] in odds_by_match and fx.get("status_short") not in SKIP_STATUS
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
        rows: list[dict[str, Any]] = []
        leagues: dict[str, dict[str, Any]] = {}
        partial = False

        for fx in sorted(fixtures, key=lambda f: (f["match_time"], f["match_id"])):
            league_id = int(fx.get("league_id") or 0)
            if league_id not in histories:
                histories[league_id] = self._league_history(league_id)
                tables[league_id] = self._table(league_id)
            history = histories[league_id]
            if history is None:
                partial = True
                continue

            home, home_source = self._profile(history, fx["home_team_id"], fx["home_team"])
            away, away_source = self._profile(history, fx["away_team_id"], fx["away_team"])
            league_key = f"{league_id}:{fx['league_name']}"
            record = by_league_record.get((fx["country_name"], fx["league_name"]))

            research = build_match_research(
                fx,
                kickoff=kickoff_iso(fx, self.offset),
                home=home,
                away=away,
                home_source=home_source,
                away_source=away_source,
                norms=league_norms(history),
                odds=odds_by_match.get(fx["match_id"]),
                h2h=self._h2h(fx),
                table=tables[league_id],
                league_record=record,
                overall_record=overall,
            )
            research["day"] = day_str
            research["built_at"] = built_at
            try:
                self.cache.save(match_cache_key(fx["match_id"]), research)
            except Exception:
                logger.exception("watchlist: could not store %s", fx["match_id"])
                partial = True
                continue

            rows.append(list_row(research, league_key))
            league = leagues.setdefault(
                league_key,
                {
                    "key": league_key,
                    "name": fx["league_name"],
                    "country": fx["country_name"],
                    "logo": fx.get("league_logo") or None,
                    "record": research["record"]["league"],
                    "match_ids": [],
                },
            )
            league["match_ids"].append(fx["match_id"])

        rows.sort(key=lambda r: (r["kickoff"], r["match_id"]))
        ordered = sorted(
            leagues.values(),
            key=lambda lg: (
                -max((r["score"] for r in rows if r["league_key"] == lg["key"]), default=0)
            ),
        )
        doc = {
            "day": day_str,
            "built_at": built_at,
            "timezone": self.offset,
            "partial": partial,
            "matches": rows,
            "leagues": ordered,
            "shortlist": shortlist(rows),
            "overall_record": overall,
        }
        self.cache.save(day_cache_key(day_str), doc)
        logger.info(
            "watchlist %s: %s matches in %s leagues%s",
            day_str,
            len(rows),
            len(ordered),
            " (partial)" if partial else "",
        )
        return doc


class WatchlistJob:
    """Rebuilds today and tomorrow every `REBUILD_SEC`, and as soon as the
    date rolls over in the board's time zone."""

    def __init__(self, builder: WatchlistBuilder, *, dsn: str | None) -> None:
        self.builder = builder
        self.dsn = dsn
        self.zone = tz_from_offset(builder.offset)

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
            except Exception:
                logger.exception("watchlist cleanup failed")

    def run_forever(self) -> None:
        last_day: date | None = None
        last_run = 0.0
        while True:
            today = datetime.now(self.zone).date()
            if today != last_day or time.monotonic() - last_run >= REBUILD_SEC:
                self.run_once()
                last_day, last_run = today, time.monotonic()
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
    with FootballAPIClient() as client:
        doc = WatchlistBuilder(client, cache, offset=offset).build_day(day)
    if args.cache_file:
        with open(args.cache_file, "w", encoding="utf-8") as fh:
            json.dump(cache.rows, fh)
    if not doc:
        return
    if args.match:
        print(json.dumps(cache.rows.get(match_cache_key(args.match)), indent=2))
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
        print(
            f"  {row['score']:.2f} {row['watch']:<6} {row['home']['name']} v "
            f"{row['away']['name']} | {', '.join(row['tags'])}"
        )


if __name__ == "__main__":
    main()
