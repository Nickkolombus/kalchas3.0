"""Match block conversion helpers (no Postgres required)."""

from __future__ import annotations

from kalchas_db.matches import (
    block_to_side_stats,
    get_matches_sync,
    load_match_events_for_ids_sync,
    load_match_histories_sync,
    side_stats_to_block,
)


def test_block_round_trips_through_side_stats() -> None:
    block = {
        "shots_on_target": {"home": 3, "away": 1},
        "dangerous_attacks": {"home": 20, "away": 8},
        "possession": {"home": 58, "away": 42},
        "goals": {"home": 1, "away": 0},
    }
    home, away = block_to_side_stats(block)
    assert home["shots_on_target"] == 3
    assert away["dangerous_attacks"] == 8
    rebuilt = side_stats_to_block(home, away, home_goals=1, away_goals=0)
    assert rebuilt["shots_on_target"] == {"home": 3, "away": 1}
    assert rebuilt["goals"] == {"home": 1, "away": 0}


def test_batch_loaders_short_circuit_empty_ids() -> None:
    assert load_match_histories_sync("postgresql://unused", []) == {}
    assert load_match_events_for_ids_sync("postgresql://unused", []) == {}
    assert get_matches_sync("postgresql://unused", []) == {}
