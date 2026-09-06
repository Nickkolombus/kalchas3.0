"""Delta Goal (Strategy 3).

New in 3.0. Kalchas 2.2 had no tests for this strategy at all, despite it
being the most intricate of them: the calculation sat in a 380-line method
that opened a database connection, ran a second model in shadow mode and
appended to a JSON learning store as it went.

The port was verified against 2.2 by differential comparison over 1,248
matches, agreeing on the trigger decision, tier, team and every intermediate
value in the chain (`scripts/verify_delta_goal_port.py`).
"""

from __future__ import annotations

import math

import pytest
from conftest import timeline_from
from kalchas_core.match import MatchTimeline, Side
from kalchas_core.strategies.delta_goal import (
    DEFAULT_BASELINE,
    GLOBAL_AVERAGE_GOALS_PER_GAME,
    LEAGUE_BASELINES,
    LEAGUE_GOALS_PER_GAME,
    MAX_THREAT_SCORE,
    MINIMUM_MINUTE,
    AttackingPatterns,
    EventBaseline,
    MatchContext,
    Tier,
    WindowEvents,
    baseline_for,
    detect_patterns,
    evaluate,
    league_prior,
    sigmoid,
    threat_score,
    tier_for,
    window_events,
)
from kalchas_core.weights import WeightSet

DEFAULTS = WeightSet.defaults()


def busy(minute: int, *, per_minute: int = 2, span: int = 30) -> MatchTimeline:
    """A timeline where the home team attacks steadily and the away team does not."""
    minutes = {}
    for m in range(max(1, minute - span), minute + 1):
        step = m - max(1, minute - span) + 1
        minutes[m] = {
            "home": {
                "shots_on_target": step * per_minute,
                "shots_off_target": step * per_minute,
                "corners": step,
                "dangerous_attacks": step * 3,
            },
            "away": {},
        }
    return timeline_from(minutes, current_minute=minute)


class TestSigmoid:
    def test_midpoint(self) -> None:
        assert sigmoid(0.0) == pytest.approx(0.5)

    def test_saturates_rather_than_overflowing(self) -> None:
        assert sigmoid(1e6) == 1.0
        assert sigmoid(-1e6) == 0.0

    def test_is_monotonic(self) -> None:
        assert sigmoid(-1) < sigmoid(0) < sigmoid(1)


class TestLeaguePrior:
    def test_a_known_league_uses_its_own_scoring_rate(self) -> None:
        bundesliga = league_prior("175")
        serie_a = league_prior("207")
        assert bundesliga > serie_a, "the higher-scoring league should have a higher prior"

    def test_an_unknown_league_falls_back_to_the_global_average(self) -> None:
        assert (
            league_prior("nonexistent")
            == pytest.approx(league_prior(None))
            == pytest.approx((GLOBAL_AVERAGE_GOALS_PER_GAME / 2) / 18)
        )

    def test_the_prior_is_a_plausible_five_minute_probability(self) -> None:
        for league in LEAGUE_GOALS_PER_GAME:
            assert 0.0 < league_prior(league) < 0.12

    def test_integer_league_ids_resolve(self) -> None:
        assert league_prior(175) == league_prior("175")


class TestBaselines:
    def test_a_known_league_gets_its_own_baseline(self) -> None:
        assert baseline_for("152") != DEFAULT_BASELINE

    def test_an_unknown_league_gets_the_default(self) -> None:
        assert baseline_for("nonexistent") == DEFAULT_BASELINE
        assert baseline_for(None) == DEFAULT_BASELINE

    def test_every_baseline_is_positive(self) -> None:
        """They are divisors, so a zero would be a problem."""
        for baseline in (DEFAULT_BASELINE, *LEAGUE_BASELINES.values()):
            assert baseline.shots_on_target > 0
            assert baseline.shots_off_target > 0
            assert baseline.corners > 0
            assert baseline.dangerous_attacks > 0

    def test_a_cagey_league_makes_the_same_activity_score_higher(self) -> None:
        """Normalising by a lower baseline raises the score for equal events."""
        timeline = busy(30)
        cagey = evaluate(timeline, league_id="207")
        open_league = evaluate(timeline, league_id="302")
        assert cagey.home.pressure_score > open_league.home.pressure_score


class TestMatchContext:
    def test_urgency_rises_through_the_match(self) -> None:
        early = MatchContext.build(10, 0, 0)
        late = MatchContext.build(85, 0, 0)
        assert late.urgency > early.urgency

    def test_urgency_falls_as_the_scoreline_opens_up(self) -> None:
        tied = MatchContext.build(80, 1, 1)
        rout = MatchContext.build(80, 4, 0)
        assert tied.urgency > rout.urgency

    def test_urgency_is_bounded(self) -> None:
        for minute, home, away in ((0, 0, 0), (90, 0, 0), (120, 9, 0), (45, 2, 2)):
            assert 0.0 <= MatchContext.build(minute, home, away).urgency <= 1.0

    def test_phase_flags(self) -> None:
        assert MatchContext.build(80, 0, 0).is_late_game
        assert MatchContext.build(20, 0, 0).is_early_game
        assert MatchContext.build(50, 0, 0).is_tied
        assert not MatchContext.build(50, 1, 0).is_tied

    def test_the_clock_beyond_ninety_does_not_push_urgency_over_one(self) -> None:
        assert MatchContext.build(120, 0, 0).urgency == pytest.approx(1.0)


class TestWindowEvents:
    def test_events_are_differenced_across_the_window(self) -> None:
        timeline = timeline_from(
            {
                15: {"home": {"shots_on_target": 2, "corners": 1}},
                20: {"home": {"shots_on_target": 5, "corners": 4}},
            },
            current_minute=20,
        )
        events = window_events(timeline, Side.HOME, 20)
        assert events.shots_on_target == 3
        assert events.corners == 3

    def test_a_single_snapshot_yields_nothing(self) -> None:
        """2.2 refused to work from one snapshot rather than inventing a delta."""
        timeline = timeline_from({20: {"home": {"shots_on_target": 5}}}, current_minute=20)
        assert window_events(timeline, Side.HOME, 20) == WindowEvents()

    def test_a_missing_minute_falls_back_to_a_recent_one(self) -> None:
        timeline = timeline_from(
            {
                14: {"home": {"shots_on_target": 2}},
                19: {"home": {"shots_on_target": 6}},
            },
            current_minute=20,
        )
        assert window_events(timeline, Side.HOME, 20).shots_on_target == 4

    def test_a_gap_wider_than_the_lookback_reads_as_zero(self) -> None:
        timeline = timeline_from(
            {
                1: {"home": {"shots_on_target": 2}},
                2: {"home": {"shots_on_target": 3}},
            },
            current_minute=40,
        )
        assert window_events(timeline, Side.HOME, 40) == WindowEvents()

    def test_deltas_are_clamped_at_zero(self) -> None:
        timeline = timeline_from(
            {
                15: {"home": {"shots_on_target": 6}},
                20: {"home": {"shots_on_target": 2}},
            },
            current_minute=20,
        )
        assert window_events(timeline, Side.HOME, 20).shots_on_target == 0

    def test_the_window_is_not_clamped_at_half_time(self) -> None:
        """Unlike every other strategy, this one measures straight through the break.

        The window from minute 42 to 47 spans the interval, and the events on
        either side are differenced as though play never stopped.
        """
        timeline = timeline_from(
            {
                42: {"home": {"shots_on_target": 1}},
                47: {"home": {"shots_on_target": 4}},
            },
            current_minute=47,
        )
        assert window_events(timeline, Side.HOME, 47).shots_on_target == 3

    def test_the_attacking_total_excludes_fouls(self) -> None:
        events = WindowEvents(
            shots_on_target=1, shots_off_target=1, corners=1, dangerous_attacks=1, fouls=5
        )
        assert events.attacking_total == 4
        assert events.total_including_fouls == 9


class TestPatternDetection:
    def test_too_little_history_detects_nothing(self) -> None:
        timeline = timeline_from({19: {}, 20: {}}, current_minute=20)
        assert detect_patterns(timeline, Side.HOME, 20) == AttackingPatterns()

    def test_a_corner_sequence_is_detected(self) -> None:
        timeline = timeline_from(
            {
                20: {"home": {"corners": 0}},
                25: {"home": {"corners": 1}},
                30: {"home": {"corners": 4}},
            },
            current_minute=30,
        )
        assert detect_patterns(timeline, Side.HOME, 30).corner_sequence

    def test_a_shot_burst_is_detected(self) -> None:
        timeline = timeline_from(
            {
                20: {"home": {}},
                25: {"home": {"shots_on_target": 1}},
                30: {"home": {"shots_on_target": 3, "shots_off_target": 2}},
            },
            current_minute=30,
        )
        assert detect_patterns(timeline, Side.HOME, 30).shot_burst

    def test_sustained_attack_needs_activity_in_both_recent_windows(self) -> None:
        timeline = busy(30)
        assert detect_patterns(timeline, Side.HOME, 30).sustained_attack
        assert not detect_patterns(timeline, Side.AWAY, 30).sustained_attack


class TestFoulsCountAsSustainedAttack:
    """A preserved defect, pinned so it cannot be silently tidied away.

    2.2 summed the whole event dict when testing for a sustained attack, which
    pulled fouls in alongside shots and corners. Because a sustained attack
    satisfies the evidence gate on its own, a scrappy passage of play with no
    shots at all can clear a gate written to require attacking intent.
    """

    def _fouls_only(self, minute: int = 30) -> MatchTimeline:
        minutes = {}
        for index, m in enumerate(range(minute - 15, minute + 1)):
            minutes[m] = {"home": {"fouls": index * 2}, "away": {}}
        return timeline_from(minutes, current_minute=minute)

    def test_fouls_alone_register_as_a_sustained_attack(self) -> None:
        patterns = detect_patterns(self._fouls_only(), Side.HOME, 30)
        assert patterns.sustained_attack
        assert not patterns.shot_burst
        assert not patterns.corner_sequence

    def test_and_therefore_satisfy_the_evidence_gate(self) -> None:
        result = evaluate(self._fouls_only(), league_id="152")
        assert result.home.events.shots_on_target == 0
        assert result.home.events.attacking_total == 0
        assert result.home.has_evidence, "no shots, no corners, yet the gate passes"


class TestTiers:
    def test_tiers_step_up_with_the_margin_over_the_threshold(self) -> None:
        assert tier_for(17.9, 18.0) is None
        assert tier_for(18.0, 18.0) is Tier.YELLOW
        assert tier_for(20.0, 18.0) is Tier.ORANGE
        assert tier_for(22.0, 18.0) is Tier.RED

    def test_tiers_rank_in_severity_order(self) -> None:
        assert Tier.RED.rank > Tier.ORANGE.rank > Tier.YELLOW.rank


class TestThreatScore:
    def _context(self, minute: int = 50, difference: int = 1) -> MatchContext:
        return MatchContext.build(minute, difference, 0)

    def test_a_stronger_signal_scores_higher(self) -> None:
        weak = threat_score(0.02, 1.2, 20.0, self._context(), AttackingPatterns(), DEFAULTS)
        strong = threat_score(0.11, 2.4, 90.0, self._context(), AttackingPatterns(), DEFAULTS)
        assert strong > weak

    def test_patterns_add_a_bonus(self) -> None:
        plain = threat_score(0.08, 2.0, 70.0, self._context(), AttackingPatterns(), DEFAULTS)
        with_patterns = threat_score(
            0.08,
            2.0,
            70.0,
            self._context(),
            AttackingPatterns(sustained_attack=True, shot_burst=True),
            DEFAULTS,
        )
        assert with_patterns > plain

    def test_a_late_level_match_scores_the_same_signal_higher(self) -> None:
        mid = threat_score(
            0.08, 2.0, 70.0, MatchContext.build(50, 1, 0), AttackingPatterns(), DEFAULTS
        )
        late = threat_score(
            0.08, 2.0, 70.0, MatchContext.build(85, 1, 1), AttackingPatterns(), DEFAULTS
        )
        assert late > mid

    def test_the_probability_term_is_capped(self) -> None:
        """Beyond the ceiling, more probability adds nothing."""
        at_ceiling = threat_score(0.12, 1.0, 50.0, self._context(), AttackingPatterns(), DEFAULTS)
        far_beyond = threat_score(0.95, 1.0, 50.0, self._context(), AttackingPatterns(), DEFAULTS)
        assert at_ceiling == far_beyond

    def test_the_score_can_exceed_its_nominal_ceiling(self) -> None:
        """Preserved from 2.2, which applied no clamp.

        Every term maxed in a late, level match with all three patterns pushes
        the composite past 1.0. The differential harness found this in the
        majority of triggering cases, so it is the common path, not an edge.
        """
        maxed = threat_score(
            0.5,
            5.0,
            100.0,
            MatchContext.build(90, 0, 0),
            AttackingPatterns(sustained_attack=True, corner_sequence=True, shot_burst=True),
            DEFAULTS,
        )
        assert maxed > MAX_THREAT_SCORE

    def test_a_floor_applies_when_something_is_happening(self) -> None:
        """So the dashboard shows a reading rather than a bare zero."""
        scored = threat_score(
            0.0, 0.0, 0.0, MatchContext.build(89, 0, 0), AttackingPatterns(), DEFAULTS
        )
        assert scored > 0

    def test_the_weights_are_tunable(self) -> None:
        heavy = WeightSet.from_overrides({"delta_goal": {"threat_w_ps": 0.6}})
        args = (0.05, 1.5, 95.0, self._context(), AttackingPatterns())
        assert threat_score(*args, heavy) > threat_score(*args, DEFAULTS)


class TestEvaluate:
    def test_an_early_match_is_flagged_and_does_not_trigger(self) -> None:
        result = evaluate(busy(MINIMUM_MINUTE - 1, span=8))
        assert result.is_early_match
        assert result.triggering_team is None
        assert result.trigger_value == 0.0
        assert result.home.threat == 0.0

    def test_a_quiet_match_does_not_trigger(self) -> None:
        timeline = timeline_from({m: {} for m in range(10, 41)}, current_minute=40)
        result = evaluate(timeline)
        assert result.triggering_team is None

    def test_a_dominant_team_triggers(self) -> None:
        result = evaluate(busy(70), league_id="152", threshold=10.0)
        assert result.triggering_team is Side.HOME
        assert result.trigger_value > 0

    def test_the_quiet_team_does_not_trigger(self) -> None:
        result = evaluate(busy(70), league_id="152", threshold=10.0)
        assert not result.away.qualifies

    def test_the_full_chain_is_reported(self) -> None:
        team = evaluate(busy(70), league_id="152", threshold=10.0).home
        assert team.pressure_index > 0
        assert 0 < team.pressure_score < 100
        assert 0 < team.confidence <= 1
        assert team.probability > team.prior, "live pressure should lift the prior"
        assert team.lift > 1

    def test_confidence_rises_with_activity(self) -> None:
        quiet = evaluate(busy(40, per_minute=0), league_id="152")
        loud = evaluate(busy(40, per_minute=3), league_id="152")
        assert loud.home.confidence > quiet.home.confidence

    def test_a_high_threshold_suppresses_the_alert(self) -> None:
        timeline = busy(70)
        assert evaluate(timeline, threshold=10.0).triggering_team is Side.HOME
        assert evaluate(timeline, threshold=100.0).triggering_team is None

    def test_the_strongest_team_is_reported_even_without_a_trigger(self) -> None:
        """The dashboard needs a reading when nothing alerts."""
        result = evaluate(busy(70), threshold=100.0)
        assert result.triggering_team is None
        assert result.strongest_team is Side.HOME

    def test_the_higher_tier_wins_over_the_higher_score(self) -> None:
        result = evaluate(busy(70), threshold=10.0)
        side = result.triggering_team
        assert side is not None
        assert result.team(side).tier is not None


class TestEvidenceGate:
    def _dangerous_attacks_only(self, per_minute: int, minute: int = 30) -> MatchTimeline:
        minutes = {
            m: {"home": {"dangerous_attacks": (m - 20) * per_minute}, "away": {}}
            for m in range(20, minute + 1)
        }
        return timeline_from(minutes, current_minute=minute)

    def test_a_trickle_of_dangerous_attacks_does_not_qualify(self) -> None:
        """The gate exists to stop alerts built on the noisiest feed signal."""
        result = evaluate(self._dangerous_attacks_only(per_minute=0), threshold=0.0)
        assert result.home.events.shots_on_target == 0
        assert not result.home.patterns.sustained_attack
        assert not result.home.has_evidence

    def test_two_shots_on_target_qualify(self) -> None:
        minutes = {
            25: {"home": {"shots_on_target": 1}},
            30: {"home": {"shots_on_target": 3}},
        }
        result = evaluate(timeline_from(minutes, current_minute=30), threshold=0.0)
        assert result.home.has_evidence

    def test_one_shot_with_supporting_corners_qualifies(self) -> None:
        minutes = {
            25: {"home": {"shots_on_target": 0, "corners": 0}},
            30: {"home": {"shots_on_target": 1, "corners": 2}},
        }
        result = evaluate(timeline_from(minutes, current_minute=30), threshold=0.0)
        assert result.home.has_evidence

    def test_one_unsupported_shot_does_not_qualify(self) -> None:
        minutes = {
            25: {"home": {"shots_on_target": 0}},
            30: {"home": {"shots_on_target": 1}},
        }
        result = evaluate(timeline_from(minutes, current_minute=30), threshold=0.0)
        assert not result.home.has_evidence

    def test_a_tier_without_evidence_does_not_qualify(self) -> None:
        result = evaluate(self._dangerous_attacks_only(per_minute=0), threshold=0.0)
        assert result.home.tier is not None, "the score clears the threshold"
        assert not result.home.qualifies, "but the evidence gate blocks it"
        assert result.triggering_team is None


class TestDangerousAttacksDefeatTheEvidenceGate:
    """A second, larger instance of the `sustained_attack` defect.

    The gate's first two clauses both require a shot on target, which is what
    makes it a gate against alerting on dangerous attacks -- the noisiest
    signal the feed carries. But its third clause accepts a sustained attack,
    and that pattern is computed by summing *all* events, dangerous attacks
    included. Three or more of them in each of the last two windows is enough.

    So the gate does not do the job it was written for. Since dangerous
    attacks are the highest-frequency stat in the feed, and the competition
    baseline is only about 1.2 per five minutes, this is not a rare path.

    Preserved because changing it would change which alerts subscribers
    receive, which is a product decision rather than a porting one.
    """

    def _dangerous_attacks_only(self, per_minute: int) -> MatchTimeline:
        minutes = {
            m: {"home": {"dangerous_attacks": (m - 20) * per_minute}, "away": {}}
            for m in range(20, 31)
        }
        return timeline_from(minutes, current_minute=30)

    def test_dangerous_attacks_alone_register_as_a_sustained_attack(self) -> None:
        result = evaluate(self._dangerous_attacks_only(per_minute=2), threshold=0.0)
        assert result.home.events.shots_on_target == 0
        assert result.home.events.dangerous_attacks > 0
        assert result.home.patterns.sustained_attack

    def test_and_therefore_pass_the_gate_with_no_shots_at_all(self) -> None:
        result = evaluate(self._dangerous_attacks_only(per_minute=2), threshold=0.0)
        assert result.home.events.shots_on_target == 0
        assert result.home.has_evidence
        assert result.home.qualifies
        assert result.triggering_team is Side.HOME


class TestOddsPrior:
    def test_odds_replace_the_competition_prior(self) -> None:
        timeline = busy(60)
        from_league = evaluate(timeline, league_id="152")
        from_odds = evaluate(timeline, league_id="152", home_odds=1.4, away_odds=7.0)
        assert from_odds.home.prior != from_league.home.prior

    def test_the_favourite_starts_from_a_higher_prior(self) -> None:
        result = evaluate(busy(60), home_odds=1.4, away_odds=7.0)
        assert result.home.prior > result.away.prior

    def test_even_odds_give_both_teams_the_same_prior(self) -> None:
        result = evaluate(busy(60), home_odds=2.5, away_odds=2.5)
        assert result.home.prior == pytest.approx(result.away.prior)

    def test_one_missing_side_of_the_market_falls_back_to_the_league(self) -> None:
        timeline = busy(60)
        partial = evaluate(timeline, league_id="152", home_odds=1.4)
        assert partial.home.prior == pytest.approx(league_prior("152"))


class TestWeightTuning:
    def test_the_event_weights_change_the_pressure_score(self) -> None:
        timeline = busy(50)
        heavy = WeightSet.from_overrides({"delta_goal": {"weight_sot": 3.0}})
        assert (
            evaluate(timeline, weights=heavy).home.pressure_score
            > evaluate(timeline).home.pressure_score
        )

    def test_a_preset_applies(self) -> None:
        preset = WeightSet.from_preset("delta_goal", "SOT-driven")
        assert evaluate(busy(50), weights=preset).home.pressure_score > 0

    def test_the_possession_weight_is_not_wired_in(self) -> None:
        """A dead control inherited from 2.2, left dead rather than reinterpreted.

        The registry carries `weight_possession` and 2.2 resolved it on
        startup, but it was never multiplied into anything. Changing it must
        not move the score, or the port has invented behaviour.
        """
        timeline = busy(50)
        tweaked = WeightSet.from_overrides({"delta_goal": {"weight_possession": 0.5}})
        assert evaluate(timeline, weights=tweaked).home.threat == evaluate(timeline).home.threat


class TestScoreline:
    def test_the_scoreline_reaches_the_threat_score(self) -> None:
        timeline = busy(85)
        level = evaluate(timeline, home_score=1, away_score=1, threshold=10.0)
        rout = evaluate(timeline, home_score=4, away_score=0, threshold=10.0)
        assert level.home.threat > rout.home.threat

    def test_a_string_scoreline_is_not_this_layer_s_problem(self) -> None:
        """Scores arrive as integers here; parsing feed formats belongs upstream."""
        result = evaluate(busy(50), home_score=2, away_score=1)
        assert result.home.events is not None


class TestNumericSafety:
    def test_extreme_activity_stays_finite(self) -> None:
        minutes = {
            m: {"home": {stat: (m - 10) * 500 for stat in ("shots_on_target", "corners")}}
            for m in range(10, 61)
        }
        team = evaluate(timeline_from(minutes, current_minute=60)).home
        for value in (team.pressure_index, team.pressure_score, team.probability, team.lift):
            assert math.isfinite(value)

    def test_a_zero_baseline_does_not_divide_by_zero(self) -> None:
        from kalchas_core.strategies import delta_goal

        events = WindowEvents(shots_on_target=3)
        score = delta_goal._event_score(events, EventBaseline(0.0, 0.0, 0.0, 0.0), DEFAULTS)
        assert math.isfinite(score)

    def test_an_empty_timeline_does_not_raise(self) -> None:
        result = evaluate(MatchTimeline.from_raw({}, 60))
        assert result.triggering_team is None
