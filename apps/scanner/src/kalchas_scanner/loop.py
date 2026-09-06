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
from kalchas_scanner.store import MinuteStore

logger = logging.getLogger("kalchas.scanner")


@dataclass
class ScannerConfig:
    interval_sec: int = 60
    min_minute: int = 5
    slots: tuple[int, ...] = (1, 2, 3, 4, 6, 7)
    max_matches_per_cycle: int = 40


@dataclass
class Scanner:
    client: FootballAPIClient
    store: MinuteStore = field(default_factory=MinuteStore)
    cooldown: CooldownBook = field(default_factory=CooldownBook)
    weights: WeightSet = field(default_factory=WeightSet.defaults)
    config: ScannerConfig = field(default_factory=ScannerConfig)
    sink: AlertSink = field(default_factory=default_sink)

    def process_match(self, match: LiveMatch) -> list[dict]:
        if match.minute < self.config.min_minute:
            return []
        stats_raw = self.client.get_fixture_statistics(match.match_id)
        stats_list = api_statistics_to_list(stats_raw)
        timeline = self.store.merge_snapshot(
            match.match_id,
            match.minute,
            stats_list,
            home_goals=match.home_score,
            away_goals=match.away_score,
        )
        events_raw = self.client.get_fixture_events(match.match_id)
        ssot_events = api_events_to_ssot(events_raw, match.home_team_id, match.away_team_id)
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
        return n

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
