"""Strategy runner smoke test."""

from conftest import timeline_from
from kalchas_core.runner import evaluate_match


def test_quiet_match_yields_no_candidates() -> None:
    timeline = timeline_from(
        {m: {"home": {}, "away": {}} for m in range(10, 21)}, current_minute=20
    )
    assert evaluate_match(timeline, slots=(1, 2, 4, 6)) == []


def test_busy_home_can_produce_pressure_candidate() -> None:
    timeline = timeline_from(
        {
            10: {"home": {}, "away": {}},
            20: {
                "home": {
                    "shots_on_target": 8,
                    "shots_off_target": 6,
                    "corners": 5,
                    "dangerous_attacks": 20,
                },
                "away": {},
            },
        },
        current_minute=20,
    )
    cands = evaluate_match(timeline, slots=(2,), thresholds={2: 10.0})
    assert any(c.strategy_slot == 2 for c in cands)
