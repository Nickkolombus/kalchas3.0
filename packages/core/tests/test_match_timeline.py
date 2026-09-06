"""Parsing the scanner's minute-by-minute feed into a typed timeline.

New in 3.0. Kalchas 2.2 had no tests here because there was no such type --
each consumer dug through the raw nested dictionaries with its own coercion
helper, so a malformed feed became a silent zero deep inside a formula.
"""

from __future__ import annotations

import pytest
from conftest import raw_minute, timeline_from
from kalchas_core.match import MatchTimeline, Side, TeamStats


class TestSide:
    def test_opponent_flips(self) -> None:
        assert Side.HOME.opponent is Side.AWAY
        assert Side.AWAY.opponent is Side.HOME

    def test_value_matches_the_feed_key(self) -> None:
        assert Side.HOME.value == "home"
        assert Side.AWAY.value == "away"


class TestTeamStats:
    def test_total_shots_sums_on_and_off_target(self) -> None:
        assert TeamStats(shots_on_target=3, shots_off_target=4).total_shots == 7

    def test_defaults_to_an_empty_stat_line(self) -> None:
        assert TeamStats().total_shots == 0


class TestParsing:
    def test_reads_counters_for_both_teams(self) -> None:
        timeline = timeline_from(
            {10: {"home": {"attacks": 40, "shots_on_target": 3}, "away": {"attacks": 25}}}
        )
        snapshot = timeline.snapshot_at(10)

        assert snapshot is not None
        assert snapshot.home.attacks == 40
        assert snapshot.home.shots_on_target == 3
        assert snapshot.away.attacks == 25

    def test_minutes_are_ordered_regardless_of_input_order(self) -> None:
        timeline = timeline_from({30: {}, 10: {}, 20: {}})
        assert timeline.available_minutes == (10, 20, 30)

    def test_current_returns_the_snapshot_at_the_clock(self) -> None:
        timeline = timeline_from({10: {}, 20: {}}, current_minute=20)
        assert timeline.current is not None
        assert timeline.current.minute == 20

    def test_current_is_none_when_that_minute_was_never_recorded(self) -> None:
        timeline = timeline_from({10: {}}, current_minute=35)
        assert timeline.current is None

    def test_empty_timeline_is_falsy(self) -> None:
        assert not MatchTimeline.from_raw({}, 0)
        assert MatchTimeline.from_raw(None, 0).available_minutes == ()


class TestMalformedFeed:
    """The feed is a third-party product; it sends surprises."""

    @pytest.mark.parametrize("key", ["HT", "", "forty", None])
    def test_non_numeric_minute_keys_are_skipped(self, key: object) -> None:
        timeline = MatchTimeline.from_raw({key: raw_minute(), "10": raw_minute()}, 10)  # type: ignore[dict-item]
        assert timeline.available_minutes == (10,)

    def test_non_mapping_minute_bodies_are_skipped(self) -> None:
        timeline = MatchTimeline.from_raw({"9": "unavailable", "10": raw_minute()}, 10)
        assert timeline.available_minutes == (10,)

    @pytest.mark.parametrize(
        ("sent", "expected"),
        [(None, 0), ("7", 7), (7.9, 7), (-3, 0), ("nonsense", 0), ([1], 0)],
    )
    def test_counters_are_coerced_and_never_negative(self, sent: object, expected: int) -> None:
        timeline = timeline_from({10: {"home": {"attacks": sent}}})
        snapshot = timeline.snapshot_at(10)
        assert snapshot is not None
        assert snapshot.home.attacks == expected

    def test_missing_stat_block_reads_as_zero(self) -> None:
        timeline = MatchTimeline.from_raw({"10": {"attacks": "not a mapping"}}, 10)
        snapshot = timeline.snapshot_at(10)
        assert snapshot is not None
        assert snapshot.home.attacks == 0

    @pytest.mark.parametrize(
        ("sent", "expected"),
        [("62%", 62.0), (62, 62.0), (150, 100.0), (-5, 0.0), (None, 0.0), ("", 0.0)],
    )
    def test_possession_is_clamped_to_a_percentage(self, sent: object, expected: float) -> None:
        timeline = timeline_from({10: {"home": {"possession": sent}}})
        snapshot = timeline.snapshot_at(10)
        assert snapshot is not None
        assert snapshot.home.possession == expected


class TestImmutability:
    def test_snapshots_cannot_be_mutated(self) -> None:
        timeline = timeline_from({10: {"home": {"attacks": 5}}})
        snapshot = timeline.snapshot_at(10)
        assert snapshot is not None
        with pytest.raises(AttributeError):
            snapshot.home.attacks = 99  # type: ignore[misc]

    def test_the_minute_mapping_cannot_be_mutated(self) -> None:
        timeline = timeline_from({10: {}})
        with pytest.raises(TypeError):
            timeline.minutes[11] = None  # type: ignore[index]
