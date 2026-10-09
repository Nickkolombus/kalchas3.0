"""Scanner poll loop."""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field, replace

from kalchas_core.alert_outcomes import AlertOutcomeEvaluator, evaluator_from_rule_rows
from kalchas_core.cooldown import (
    DEFAULT_BASE_COOLDOWN,
    DEFAULT_BYPASS_DELTA,
    DEFAULT_OMEGA_COOLDOWN,
    CooldownBook,
    CooldownRules,
)
from kalchas_core.events import (
    compute_tslg_status,
    convert_ssot_events,
    count_cards_by_side,
    tally_red_cards,
)
from kalchas_core.h2h import DEFAULT_LAST, compute_h2h_stats, h2h_meeting_averages
from kalchas_core.runner import (
    DEFAULT_THRESHOLDS,
    evaluate_match,
    home_away_odds,
    live_home_away_odds,
)
from kalchas_core.strategies.delta_5min import last_5min_block
from kalchas_core.weights import WeightSet
from kalchas_football import (
    FootballAPIClient,
    LiveMatch,
    RateLimitBudgetExceeded,
    advance_stoppage_clock,
    compose_odds_record,
    hold_playing_period,
    https_asset_url,
    lineup_from_event,
    statistics_from_event,
    substitutions_from_event,
)

from kalchas_scanner.enrich import (
    api_events_to_ssot,
    api_statistics_to_list,
    possession_from_stats,
)
from kalchas_scanner.outbox import AlertSink, default_sink
from kalchas_scanner.persist import MatchPersist, default_persist
from kalchas_scanner.store import MinuteStore

logger = logging.getLogger("kalchas.scanner")

TERMINAL_STATUS = frozenset({"FT", "AET", "PEN", "CANC", "PST", "AWD"})


def _side_counts(block: dict | None, key: str) -> dict[str, int]:
    row = (block or {}).get(key) or {}
    try:
        return {"home": int(row.get("home") or 0), "away": int(row.get("away") or 0)}
    except (TypeError, ValueError):
        return {"home": 0, "away": 0}


def _tally_yellow(
    card_events: list[dict],
    home_team: str,
    away_team: str,
) -> dict[str, int]:
    home_yc = 0
    away_yc = 0
    for card in card_events or []:
        detail = str(card.get("detail", "")).lower()
        if "yellow" not in detail:
            continue
        team_name = card.get("team", "")
        if team_name == home_team:
            home_yc += 1
        elif team_name == away_team:
            away_yc += 1
        else:
            side = str(card.get("side") or "").lower()
            if side == "home":
                home_yc += 1
            elif side == "away":
                away_yc += 1
    return {"home": home_yc, "away": away_yc}


@dataclass
class ScannerConfig:
    interval_sec: int = 60
    min_minute: int = 5
    slots: tuple[int, ...] = (1, 2, 3, 4, 6, 7)
    max_matches_per_cycle: int = 400
    max_stats_http_per_cycle: int = 15
    stale_cleanup_minutes: int = 360
    cleanup_every_cycles: int = 30
    odds_refresh_sec: int = 600
    live_odds_refresh_sec: int = 45


@dataclass
class Scanner:
    client: FootballAPIClient
    store: MinuteStore = field(default_factory=MinuteStore)
    cooldown: CooldownBook = field(default_factory=CooldownBook)
    weights: WeightSet = field(default_factory=WeightSet.defaults)
    config: ScannerConfig = field(default_factory=ScannerConfig)
    sink: AlertSink = field(default_factory=default_sink)
    persist: MatchPersist = field(default_factory=default_persist)
    thresholds: dict[int, float] = field(default_factory=lambda: dict(DEFAULT_THRESHOLDS))
    conditions: dict[int, list] = field(default_factory=dict)
    _cycles: int = 0
    _tuning_at: float = 0.0
    _odds_by_match: dict[str, dict[str, float]] = field(default_factory=dict)
    _odds_fetched_at: float = 0.0
    _live_odds_by_match: dict[str, dict[str, float]] = field(default_factory=dict)
    _live_odds_fetched_at: float = 0.0
    _comment_elapsed_by_match: dict[str, int] = field(default_factory=dict)
    _status_by_match: dict[str, str] = field(default_factory=dict)
    _stats_http_used: int = 0
    _stats_http_window_at: float = 0.0
    _outcome_evaluator: AlertOutcomeEvaluator = field(default_factory=AlertOutcomeEvaluator)
    _h2h_alert_by_pair: dict[tuple[int, int], dict | None] = field(default_factory=dict)

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

    def _refresh_odds_cache(self) -> None:
        self._refresh_kickoff_odds_cache()
        self._refresh_live_odds_cache()

    def _refresh_kickoff_odds_cache(self) -> None:
        now = time.monotonic()
        if self._odds_fetched_at and now - self._odds_fetched_at < self.config.odds_refresh_sec:
            return
        fetch = getattr(self.client, "get_odds_1x2_today", None)
        if callable(fetch):
            try:
                fresh = fetch() or {}
                added = 0
                for match_id, odds in fresh.items():
                    key = str(match_id)
                    if key in self._odds_by_match:
                        continue
                    self._odds_by_match[key] = dict(odds)
                    added += 1
                logger.info(
                    "kickoff odds cache: %s matches (%s new)",
                    len(self._odds_by_match),
                    added,
                )
            except Exception:
                logger.exception("kickoff odds cache refresh failed")
        self._odds_fetched_at = now

    def _refresh_live_odds_cache(self) -> None:
        now = time.monotonic()
        if (
            self._live_odds_fetched_at
            and now - self._live_odds_fetched_at < self.config.live_odds_refresh_sec
        ):
            return
        bundle = getattr(self.client, "get_live_odds_comments_bundle", None)
        fetch = getattr(self.client, "get_live_odds_1x2", None)
        if callable(bundle) or callable(fetch):
            try:
                clocks: dict[str, int] = {}
                if callable(bundle):
                    packed = bundle() or ({}, {})
                    fresh, clocks = packed[0] or {}, packed[1] or {}
                else:
                    fresh = fetch() or {}
                if fresh:
                    for match_id, odds in fresh.items():
                        self._live_odds_by_match[str(match_id)] = dict(odds)
                    logger.info("live odds cache: %s matches", len(self._live_odds_by_match))
                if clocks:
                    self._comment_elapsed_by_match = {
                        str(match_id): int(elapsed) for match_id, elapsed in clocks.items()
                    }
            except Exception:
                logger.exception("live odds cache refresh failed")
        self._live_odds_fetched_at = now

    def _previous_status(self, match_id: str) -> str | None:
        cached = self._status_by_match.get(match_id)
        if cached:
            return cached
        try:
            header = self.persist.load_header(match_id)
        except Exception:  # noqa: BLE001 — header lookup must not take down the cycle
            return None
        status = str((header or {}).get("status_short") or "").strip().upper()
        if status:
            self._status_by_match[match_id] = status
            return status
        return None

    def _with_comment_clock(self, match: LiveMatch) -> LiveMatch:
        comment = self._comment_elapsed_by_match.get(match.match_id)
        if comment is None:
            return match
        elapsed, short, display = advance_stoppage_clock(
            match.minute,
            match.status_short,
            match.minute_display,
            comment_elapsed=comment,
        )
        if elapsed == match.minute and display == match.minute_display:
            return match
        return replace(
            match,
            minute=elapsed,
            status_short=short,
            minute_display=display,
        )

    def _with_event_stoppage(self, match: LiveMatch, events: list[dict]) -> LiveMatch:
        display = match.minute_display or ""
        if "+" not in display:
            return match
        base_s = display.split("+", 1)[0]
        if not base_s.isdigit():
            return match
        base = int(base_s)
        added = 0
        for event in events:
            try:
                minute = int(event.get("minute") or 0)
            except (TypeError, ValueError):
                continue
            if base < minute <= base + 15:
                added = max(added, minute - base)
        elapsed, short, filled = advance_stoppage_clock(
            match.minute,
            match.status_short,
            match.minute_display,
            event_added=added,
        )
        if elapsed == match.minute and filled == match.minute_display:
            return match
        return replace(
            match,
            minute=elapsed,
            status_short=short,
            minute_display=filled,
        )

    def _odds_payload(self, match_id: str) -> dict | None:
        return compose_odds_record(
            kickoff=self._odds_by_match.get(match_id),
            live=self._live_odds_by_match.get(match_id),
        )

    def _h2h_for_alert(self, match: LiveMatch) -> dict | None:
        """Goals-per-meeting for Telegram. Skips samples under 5. Cache first."""
        try:
            home_id = int(match.home_team_id or 0)
            away_id = int(match.away_team_id or 0)
        except (TypeError, ValueError):
            return None
        if home_id <= 0 or away_id <= 0 or home_id == away_id:
            return None
        pair = (min(home_id, away_id), max(home_id, away_id))
        overlay = self._h2h_from_panel_cache(home_id, away_id)
        if overlay is not None:
            self._h2h_alert_by_pair[pair] = overlay
            return overlay
        if pair in self._h2h_alert_by_pair:
            return self._h2h_alert_by_pair[pair]
        fetch = getattr(self.client, "get_head_to_head", None)
        if not callable(fetch):
            self._h2h_alert_by_pair[pair] = None
            return None
        try:
            fixtures = fetch(home_id, away_id, last=DEFAULT_LAST)
        except RateLimitBudgetExceeded:
            return None
        except Exception:
            logger.exception("h2h fetch failed for %s", match.match_id)
            return None
        stats = compute_h2h_stats(
            fixtures or [],
            team1_id=home_id,
            team2_id=away_id,
            team1_name=match.home_team,
            team2_name=match.away_team,
        )
        snippet = h2h_meeting_averages(stats)
        self._h2h_alert_by_pair[pair] = snippet
        return snippet

    def _h2h_from_panel_cache(self, home_id: int, away_id: int) -> dict | None:
        dsn = os.environ.get("DATABASE_URL") or os.environ.get("POSTGRES_URL")
        if not dsn:
            return None
        try:
            from kalchas_db.panel_cache import load_panel_cache, pair_cache_key

            cached = load_panel_cache(dsn, pair_cache_key("h2h", home_id, away_id))
        except Exception:  # noqa: BLE001 - missing table must not block alerts
            return None
        if not isinstance(cached, dict):
            return None
        try:
            sample = int((cached.get("summary") or {}).get("sample") or 0)
            patterns = cached.get("patterns") or {}
            home_goals = float(patterns.get("home_goals"))
            away_goals = float(patterns.get("away_goals"))
        except (TypeError, ValueError):
            return None
        if sample < 5:
            return None
        return {
            "sample": sample,
            "home_avg": round(home_goals / sample, 1),
            "away_avg": round(away_goals / sample, 1),
        }

    def _claim_stats_http(self) -> bool:
        now = time.monotonic()
        window = 60.0
        if now - self._stats_http_window_at >= window:
            self._stats_http_window_at = now
            self._stats_http_used = 0
        if self._stats_http_used >= self.config.max_stats_http_per_cycle:
            return False
        self._stats_http_used += 1
        return True

    def _ingest_stats(self, match: LiveMatch, stats_raw: dict) -> tuple[object, dict | None]:
        stats_list = api_statistics_to_list(stats_raw)
        home_poss, away_poss = possession_from_stats(stats_list)
        timeline = self.store.merge_snapshot(
            match.match_id,
            match.minute,
            stats_list,
            home_possession=home_poss,
            away_possession=away_poss,
            home_goals=match.home_score,
            away_goals=match.away_score,
        )
        return timeline, self.store.latest_block(match.match_id, match.minute)

    def _persist_minute(self, match: LiveMatch, block: dict | None) -> None:
        try:
            self.persist.save_minute(
                match_id=match.match_id,
                home_team=match.home_team,
                away_team=match.away_team,
                home_team_id=match.home_team_id,
                away_team_id=match.away_team_id,
                league_name=match.league_name or None,
                league_id=match.league_id or None,
                status_short=match.status_short,
                home_score=match.home_score,
                away_score=match.away_score,
                minute=match.minute,
                minute_display=match.minute_display or None,
                minute_block=block or {},
                lineup=lineup_from_event(match.raw),
                substitutions=substitutions_from_event(match.raw),
                country_name=match.country_name or None,
                country_logo=https_asset_url(match.country_logo) or None,
                home_team_logo=https_asset_url(match.home_team_logo) or None,
                away_team_logo=https_asset_url(match.away_team_logo) or None,
                odds=self._odds_payload(match.match_id),
            )
        except Exception:
            logger.exception("failed persisting minute for %s", match.match_id)

    def _prior_stored_minute(self, match_id: str) -> int:
        header: dict | None = None
        loader = getattr(self.persist, "load_header", None)
        if callable(loader):
            try:
                header = loader(match_id)
            except Exception:
                logger.exception("failed loading header for %s", match_id)
        if header:
            try:
                prior = int(header.get("minute") or 0)
            except (TypeError, ValueError):
                prior = 0
            if prior > 0:
                return prior
        try:
            history = self.persist.load_history(match_id)
            minutes = [int(key) for key in history]
            if minutes:
                return max(minutes)
        except Exception:
            logger.exception("failed loading history clock for %s", match_id)
        return 0

    def process_match(self, match: LiveMatch) -> list[dict]:
        self._refresh_tuning()
        self._refresh_odds_cache()
        self._hydrate_if_needed(match.match_id)
        match = self._with_comment_clock(match)
        match = hold_playing_period(match, previous_status=self._previous_status(match.match_id))
        self._status_by_match[match.match_id] = (match.status_short or "").strip().upper()
        if match.raw:
            match = self._with_event_stoppage(
                match,
                api_events_to_ssot(
                    match.raw,
                    match.home_team_id,
                    match.away_team_id,
                    home_team=match.home_team,
                    away_team=match.away_team,
                ),
            )
        status = (match.status_short or "").strip().upper()
        if status in TERMINAL_STATUS:
            clock = match.minute if match.minute > 0 else self._prior_stored_minute(match.match_id)
            ended = replace(match, minute=clock)
            self._persist_minute(ended, None)
            events = api_events_to_ssot(
                match.raw or {},
                match.home_team_id,
                match.away_team_id,
                home_team=match.home_team,
                away_team=match.away_team,
            )
            self._settle_open_alerts(ended, events)
            return []
        # Live get_events / WS rows already carry statistics, lineup, substitutions,
        # goalscorer, cards, and country. Extra get_statistics / get_lineups /
        # get_events calls are fallbacks only. 1X2 comes from a cached get_odds
        # window, not a per-match request. H2H stays off this cycle.
        stats_raw = statistics_from_event(match.raw)
        timeline = None
        block: dict | None = None
        if stats_raw is not None:
            timeline, block = self._ingest_stats(match, stats_raw)
        # Persist the clock before any stats HTTP. An hour-long rate-limit
        # sleep used to freeze this method and starve /api/live's 15-minute window.
        self._persist_minute(match, block)
        if (
            stats_raw is None
            and match.minute >= self.config.min_minute
            and self._claim_stats_http()
        ):
            try:
                stats_raw = self.client.get_fixture_statistics(match.match_id)
            except RateLimitBudgetExceeded:
                stats_raw = None
            if stats_raw is not None:
                timeline, block = self._ingest_stats(match, stats_raw)
                self._persist_minute(match, block)

        # Prefer events embedded in the live get_events row (saves a free-tier call).
        events_raw: object
        if match.raw:
            events_raw = match.raw
        elif match.minute >= self.config.min_minute:
            try:
                events_raw = self.client.get_fixture_events(match.match_id)
            except RateLimitBudgetExceeded:
                events_raw = {}
        else:
            events_raw = {}
        ssot_events = api_events_to_ssot(
            events_raw,
            match.home_team_id,
            match.away_team_id,
            home_team=match.home_team,
            away_team=match.away_team,
        )
        try:
            self.persist.save_events(match.match_id, ssot_events)
        except Exception:
            logger.exception("failed persisting events for %s", match.match_id)
        self._settle_open_alerts(match, ssot_events)
        if match.minute < self.config.min_minute or timeline is None:
            return []
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

        odds_payload = self._odds_payload(match.match_id)
        home_odds, away_odds = home_away_odds(odds_payload)
        live_home, live_away = live_home_away_odds(odds_payload)
        yellow, red = count_cards_by_side(ssot_events)
        candidates = evaluate_match(
            timeline,
            home_goals=match.home_score,
            away_goals=match.away_score,
            weights=self.weights,
            thresholds=self.thresholds,
            slots=self.config.slots,
            league_id=match.league_id,
            league_name=match.league_name or None,
            country_name=match.country_name or None,
            home_odds=home_odds,
            away_odds=away_odds,
            live_home_odds=live_home,
            live_away_odds=live_away,
            yellow_cards=yellow,
            red_cards=red,
            conditions=self.conditions,
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
            detail = cand.detail or {}
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
                "league": match.league_name or None,
                "sot": _side_counts(block, "shots_on_target"),
                "sofft": _side_counts(block, "shots_off_target"),
                "corners": _side_counts(block, "corners"),
                "attacks": _side_counts(block, "attacks"),
                "da": _side_counts(block, "dangerous_attacks"),
                "possession": _side_counts(block, "possession"),
                "yc": _tally_yellow(cards, match.home_team, match.away_team),
                "rc": {"home": reds.get("home", 0), "away": reds.get("away", 0)},
                "odds": odds_payload,
            }
            if cand.strategy_key == "omega":
                payload["theta"] = detail.get("theta")
                payload["k_scale"] = detail.get("k_scale")
            if cand.strategy_key == "delta_5min":
                last_5 = last_5min_block(timeline)
                if last_5:
                    payload["last_5min"] = last_5
            h2h = self._h2h_for_alert(match)
            if h2h:
                payload["h2h"] = h2h
            payload["home_logo"] = https_asset_url(match.home_team_logo) or None
            payload["away_logo"] = https_asset_url(match.away_team_logo) or None
            payload["status_short"] = match.status_short
            self.sink.emit(payload)
            self.cooldown.confirm(decision.cooldown_key)
            emitted.append(payload)
        return emitted

    def run_once(self) -> int:
        self._refresh_odds_cache()
        self._refresh_tuning()
        matches = self.client.get_live_fixtures()
        matches.sort(
            key=lambda item: (
                0 if statistics_from_event(item.raw) is not None else 1,
                -int(item.minute or 0),
            )
        )
        total_live = len(matches)
        if total_live > self.config.max_matches_per_cycle:
            logger.warning(
                "live list %s exceeds %s; processing sorted prefix",
                total_live,
                self.config.max_matches_per_cycle,
            )
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

    def _refresh_tuning(self) -> None:
        now = time.monotonic()
        if self._tuning_at and now - self._tuning_at < 15:
            return
        dsn = os.environ.get("DATABASE_URL") or os.environ.get("POSTGRES_URL")
        if not dsn:
            self._tuning_at = now
            return
        try:
            from kalchas_db.settings import KEY_BY_SLOT, load_runtime_bundle

            bundle = load_runtime_bundle(dsn)
            stored_w = bundle.get("weights") or {}
            if stored_w:
                self.weights = WeightSet.from_overrides(stored_w)
            stored_th = bundle.get("thresholds") or {}
            self.thresholds = {**DEFAULT_THRESHOLDS, **stored_th}
            self.conditions = bundle.get("conditions") or {}
            enabled = tuple(
                int(row["strategy_slot"])
                for row in bundle.get("rules") or []
                if row.get("enabled") and int(row["strategy_slot"]) in KEY_BY_SLOT
            )
            if enabled:
                self.config.slots = enabled
            self._outcome_evaluator = evaluator_from_rule_rows(bundle.get("rules") or [])
            rules: dict[int, CooldownRules] = {}
            for row in bundle.get("rules") or []:
                slot = int(row["strategy_slot"])
                bypass = row.get("cooldown_bypass_delta")
                default_cd = DEFAULT_OMEGA_COOLDOWN if slot == 6 else DEFAULT_BASE_COOLDOWN
                if slot == 6:
                    bypass = None
                elif slot == 4 and bypass is not None and float(bypass) <= 1.0:
                    bypass = None
                elif bypass is not None:
                    bypass = float(bypass)
                else:
                    bypass = DEFAULT_BYPASS_DELTA.get(slot)
                rules[slot] = CooldownRules(
                    strategy_slot=slot,
                    base_cooldown_minutes=int(row.get("cooldown_minutes") or default_cd),
                    value_delta_threshold=bypass,
                    rearm_after_drop=slot in {4, 6},
                )
            if rules:
                self.cooldown.rules = rules
        except Exception:
            logger.exception("failed loading admin settings")
        self._tuning_at = now

    def _settle_open_alerts(self, match: LiveMatch, events: list[dict]) -> None:
        dsn = getattr(self.persist, "dsn", None)
        if not dsn:
            return
        try:
            from kalchas_scanner.settle import persist_settled_alerts

            persist_settled_alerts(
                dsn,
                match_id=match.match_id,
                current_minute=int(match.minute),
                current_score=f"{match.home_score}-{match.away_score}",
                status_short=match.status_short,
                events=events,
                evaluator=self._outcome_evaluator,
            )
        except Exception:
            logger.exception("failed settling alerts for %s", match.match_id)

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
