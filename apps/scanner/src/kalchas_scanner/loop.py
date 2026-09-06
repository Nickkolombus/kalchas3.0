"""Scanner poll loop."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

from kalchas_core.cooldown import CooldownBook
from kalchas_core.events import compute_tslg_status, convert_ssot_events, tally_red_cards
from kalchas_core.runner import evaluate_match
from kalchas_core.weights import WeightSet
from kalchas_football import FootballAPIClient, LiveMatch

from kalchas_scanner.enrich import api_events_to_ssot, api_statistics_to_list
from kalchas_scanner.outbox import AlertSink, default_sink
from kalchas_scanner.persist import MatchPersist, default_persist
from kalchas_scanner.store import MinuteStore

logger = logging.getLogger("kalchas.scanner")


@dataclass
class ScannerConfig:
    interval_sec: int = 60
    min_minute: int = 5
    slots: tuple[int, ...] = (1, 2, 3, 4, 6, 7)
    max_matches_per_cycle: int = 40
    stale_cleanup_minutes: int = 360
    cleanup_every_cycles: int = 30


@dataclass
class Scanner:
    client: FootballAPIClient
    store: MinuteStore = field(default_factory=MinuteStore)
    cooldown: CooldownBook = field(default_factory=CooldownBook)
    weights: WeightSet = field(default_factory=WeightSet.defaults)
    config: ScannerConfig = field(default_factory=ScannerConfig)
    sink: AlertSink = field(default_factory=default_sink)
    persist: MatchPersist = field(default_factory=default_persist)
    _cycles: int = 0

    def _hydrate_if_needed(self, match_id: str) -> None:
        if self.store.has(match_id):
            return
        try:
            history = self.persist.load_history(match_id)
        except Exception:
            logger.exception("failed loading history for %s", match_id)
            return
        if history:
            self.store.seed_history(match_id, history)
            logger.info("hydrated %s with %s minutes from postgres", match_id, len(history))

    def process_match(self, match: LiveMatch) -> list[dict]:
        if match.minute < self.config.min_minute:
            return []
        self._hydrate_if_needed(match.match_id)
        stats_raw = self.client.get_fixture_statistics(match.match_id)
        stats_list = api_statistics_to_list(stats_raw)
        timeline = self.store.merge_snapshot(
            match.match_id,
            match.minute,
            stats_list,
            home_goals=match.home_score,
            away_goals=match.away_score,
        )
        block = self.store.latest_block(match.match_id, match.minute)
        if block is not None:
            try:
                self.persist.save_minute(
                    match_id=match.match_id,
                    home_team=match.home_team,
                    away_team=match.away_team,
                    home_team_id=match.home_team_id,
                    away_team_id=match.away_team_id,
                    league_name=match.league_name or None,
                    status_short=match.status_short,
                    home_score=match.home_score,
                    away_score=match.away_score,
                    minute=match.minute,
                    minute_block=block,
                )
            except Exception:
                logger.exception("failed persisting minute for %s", match.match_id)

        # Prefer events embedded in the live get_events row (saves a free-tier call).
        events_raw = match.raw if match.raw else self.client.get_fixture_events(match.match_id)
        ssot_events = api_events_to_ssot(
            events_raw,
            match.home_team_id,
            match.away_team_id,
            home_team=match.home_team,
            away_team=match.away_team,
        )
        goals, cards = convert_ssot_events(
            ssot_events, home_team=match.home_team, away_team=match.away_team
        )
        reds = tally_red_cards(cards, match.home_team, match.away_team)
        tslg = compute_tslg_status(
            {
                "home_team": match.home_team,
                "away_team": match.away_team,
                "home_score": match.home_score,
                "away_score": match.away_score,
                "goal_events": goals,
                "current_minute": match.minute,
            },
            minute=match.minute,
        )

        candidates = evaluate_match(
            timeline,
            home_goals=match.home_score,
            away_goals=match.away_score,
            weights=self.weights,
            slots=self.config.slots,
        )
        emitted: list[dict] = []
        for cand in candidates:
            team = cand.side.value if cand.side else None
            decision = self.cooldown.decide(
                match.match_id,
                cand.strategy_slot,
                match.minute,
                cand.value,
                team=team,
                goal_events=goals,
                last_goal=tslg.get("last_goal") or None,
                red_cards=reds,
            )
            if not decision.can_send:
                logger.debug(
                    "blocked %s S%s: %s",
                    match.match_id,
                    cand.strategy_slot,
                    decision.blocked_by,
                )
                continue
            payload = {
                "event": "alert",
                "match_id": match.match_id,
                "home": match.home_team,
                "away": match.away_team,
                "minute": match.minute,
                "score": f"{match.home_score}-{match.away_score}",
                "strategy_slot": cand.strategy_slot,
                "strategy": cand.strategy_key,
                "team": team,
                "value": cand.value,
                "tslg": tslg.get("display"),
            }
            self.sink.emit(payload)
            self.cooldown.confirm(decision.cooldown_key)
            emitted.append(payload)
        return emitted

    def run_once(self) -> int:
        matches = self.client.get_live_fixtures()
        matches = matches[: self.config.max_matches_per_cycle]
        logger.info("cycle: %s live matches", len(matches))
        n = 0
        for match in matches:
            try:
                n += len(self.process_match(match))
            except Exception:
                logger.exception("failed processing match %s", match.match_id)
        self._cycles += 1
        if self._cycles % self.config.cleanup_every_cycles == 0:
            self._maybe_cleanup()
        return n

    def _maybe_cleanup(self) -> None:
        dsn = getattr(self.persist, "dsn", None)
        if not dsn:
            return
        try:
            from kalchas_db.matches import delete_stale_matches_sync

            deleted = delete_stale_matches_sync(
                dsn, max_age_minutes=self.config.stale_cleanup_minutes
            )
            if deleted:
                logger.info("cleaned %s stale matches", deleted)
        except Exception:
            logger.exception("stale match cleanup failed")

    def run_forever(self) -> None:
        while True:
            started = time.monotonic()
            try:
                self.run_once()
            except Exception:
                logger.exception("scanner cycle failed")
            elapsed = time.monotonic() - started
            sleep_for = max(1.0, self.config.interval_sec - elapsed)
            time.sleep(sleep_for)
