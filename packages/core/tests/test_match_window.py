"""Rolling window resolution, including the half-boundary clamps.

New in 3.0. The clamping rules existed in 2.2 -- duplicated between
`delta_calculator` and `npei_calculator` -- but were never tested, so nothing
would have caught the two copies drifting apart.
"""

from __future__ import annotations

import pytest
from conftest import timeline_from
from kalchas_core.match import (
    FIRST_PERIOD_START,
    PERIOD_STARTS,
    Side,
    TeamDeltas,
    TeamStats,
    WindowClamp,
    period_start_for,
    resolve_window,
)
from kalchas_core.match import earliest_allowed_start as earliest


class TestDeltas:
    def test_activity_is_the_difference_between_snapshots(self) -> None:
        deltas = TeamDeltas.between(
            TeamStats(attacks=30, dangerous_attacks=10, shots_on_target=2, shots_off_target=3),
            TeamStats(attacks=45, dangerous_attacks=18, shots_on_target=4, shots_off_target=6),
        )
        assert deltas.attacks == 15
        assert deltas.dangerous_attacks == 8
        assert deltas.shots_on_target == 2
        assert deltas.shots == 5

    def test_a_counter_correction_does_not_produce_negative_activity(self) -> None:
        """Providers sometimes revise a counter downward mid-match."""
        deltas = TeamDeltas.between(TeamStats(attacks=40), TeamStats(attacks=35))
        assert deltas.attacks == 0


class TestWindowResolution:
    def test_resolves_the_last_five_minutes(self) -> None:
        timeline = timeline_from({m: {} for m in range(10, 21)}, current_minute=20)
        window = resolve_window(timeline)

        assert window is not None
        assert window.start_minute == 15
        assert window.end_minute == 20
        assert window.span == 5

    def test_falls_back_to_the_oldest_minute_inside_the_range(self) -> None:
        """A gap in recording shortens the window rather than voiding it."""
        timeline = timeline_from({10: {}, 17: {}, 20: {}}, current_minute=20)
        window = resolve_window(timeline)

        assert window is not None
        assert window.start_minute == 17

    def test_deltas_are_scoped_per_team(self) -> None:
        timeline = timeline_from(
            {
                15: {"home": {"attacks": 20}, "away": {"attacks": 30}},
                20: {"home": {"attacks": 35}, "away": {"attacks": 33}},
            },
            current_minute=20,
        )
        window = resolve_window(timeline)

        assert window is not None
        assert window.deltas(Side.HOME).attacks == 15
        assert window.deltas(Side.AWAY).attacks == 3


class TestNoReading:
    """None means no reading, which callers must not treat as a reading of zero."""

    def test_match_too_young_for_a_full_window(self) -> None:
        timeline = timeline_from({m: {} for m in range(0, 4)}, current_minute=3)
        assert resolve_window(timeline) is None

    def test_current_minute_was_never_recorded(self) -> None:
        timeline = timeline_from({10: {}, 11: {}}, current_minute=20)
        assert resolve_window(timeline) is None

    def test_no_recorded_minute_falls_inside_the_range(self) -> None:
        timeline = timeline_from({2: {}, 20: {}}, current_minute=20)
        assert resolve_window(timeline) is None

    def test_empty_timeline(self) -> None:
        assert resolve_window(timeline_from({}, current_minute=20)) is None


class TestHalfBoundaryClamp:
    """A window must not span an interval: counters carry over, play does not."""

    def test_mid_half_is_a_plain_five_minute_lookback(self) -> None:
        assert earliest(70) == 65

    @pytest.mark.parametrize("period_start", PERIOD_STARTS)
    def test_window_never_reaches_before_a_period_start(self, period_start: int) -> None:
        for minute in range(period_start, period_start + 5):
            assert earliest(minute) >= period_start

    def test_clamp_lifts_once_the_period_is_underway(self) -> None:
        assert earliest(56) == 51
        assert earliest(60) == 55

    def test_lookback_is_shortened_while_clamped(self) -> None:
        """Three minutes, not five, for the first stretch of a new period."""
        assert earliest(54) == 51
        assert earliest(55) == 52

    def test_a_window_after_the_break_excludes_first_half_stoppage(self) -> None:
        timeline = timeline_from({48: {}, 49: {}, 51: {}, 52: {}, 53: {}}, current_minute=53)
        window = resolve_window(timeline)

        assert window is not None
        assert window.start_minute == 51, "window reached back across half-time"


class TestPeriodStart:
    @pytest.mark.parametrize(
        ("minute", "expected"),
        [(1, 1), (45, 1), (50, 1), (51, 51), (96, 51), (97, 97), (110, 97), (111, 111), (120, 111)],
    )
    def test_locates_the_containing_period(self, minute: int, expected: int) -> None:
        assert period_start_for(minute) == expected

    def test_the_first_period_includes_its_stoppage_time(self) -> None:
        """Minutes 46-50 are first-half stoppage, not the second half."""
        assert period_start_for(48) == FIRST_PERIOD_START


class TestClampPolicies:
    """The two rules 2.2 used are kept apart because they genuinely disagree."""

    def test_period_start_clamp_holds_for_the_whole_period(self) -> None:
        assert earliest(58, 10, WindowClamp.PERIOD_START) == 51
        assert earliest(70, 10, WindowClamp.PERIOD_START) == 60

    def test_short_after_break_imposes_nothing_once_underway(self) -> None:
        """Safe for a five-minute window, but a ten-minute one crosses the break."""
        assert earliest(58, 10, WindowClamp.SHORT_AFTER_BREAK) == 48

    def test_the_two_policies_disagree_at_minute_55(self) -> None:
        assert earliest(55, 5, WindowClamp.SHORT_AFTER_BREAK) == 52
        assert earliest(55, 5, WindowClamp.PERIOD_START) == 51

    @pytest.mark.parametrize("period_start", PERIOD_STARTS)
    def test_neither_policy_reaches_before_a_period_start(self, period_start: int) -> None:
        for minute in range(period_start, period_start + 10):
            for clamp in WindowClamp:
                if clamp is WindowClamp.SHORT_AFTER_BREAK and minute >= period_start + 5:
                    continue  # documented gap: see test above
                assert earliest(minute, 10, clamp) >= period_start


class TestPartialWindows:
    def test_a_full_span_is_required_by_default(self) -> None:
        timeline = timeline_from({1: {}, 2: {}, 3: {}}, current_minute=3)
        assert resolve_window(timeline, 5) is None

    def test_a_partial_window_can_be_accepted(self) -> None:
        timeline = timeline_from({1: {}, 2: {}, 3: {}}, current_minute=3)
        window = resolve_window(timeline, 5, require_full_span=False)

        assert window is not None
        assert window.start_minute == 1


class TestFallbackLookback:
    def test_a_stale_snapshot_is_accepted_within_the_fallback(self) -> None:
        timeline = timeline_from({28: {}, 40: {}}, current_minute=40)

        assert resolve_window(timeline, 10) is None
        window = resolve_window(timeline, 10, fallback_lookback=15)
        assert window is not None
        assert window.start_minute == 28

    def test_the_nearest_snapshot_to_the_fallback_target_wins(self) -> None:
        timeline = timeline_from({5: {}, 27: {}, 40: {}}, current_minute=40)
        window = resolve_window(timeline, 10, fallback_lookback=15)

        assert window is not None
        assert window.start_minute == 27, "a very old snapshot would read as one long surge"
