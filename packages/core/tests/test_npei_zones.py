"""Efficiency zone classification for the NPEI score.

Ported from Kalchas 2.2 `tests/test_npei_efficiency_zones.py`. The band
boundary cases are carried over verbatim -- they pin the exact score at which
each label changes, which is the behaviour subscribers see on the dashboard.
Added here: the empty-score cases and the injected-bounds case, neither of
which 2.2 covered.
"""

from __future__ import annotations

import pytest
from kalchas_core.npei import (
    EMPTY_ZONE,
    classify_efficiency,
    efficiency_zone_label,
    load_bounds,
    normalize_bounds,
    zone_scale_hint,
)
from kalchas_core.weights import WeightSet


@pytest.mark.parametrize(
    ("score", "expected"),
    [
        (0, "Totally Inefficient"),
        (5, "Totally Inefficient"),
        (6, "Inefficient"),
        (20, "Inefficient"),
        (21, "Moderately Efficient"),
        (40, "Moderately Efficient"),
        (41, "Efficient"),
        (55, "Efficient"),
        (56, "Highly Efficient"),
        (100, "Highly Efficient"),
    ],
)
def test_default_band_boundaries(score: float, expected: str) -> None:
    assert classify_efficiency(score).label == expected


def test_normalize_bounds_enforces_increasing_order() -> None:
    """Sliders dragged out of order must still yield reachable bands."""
    out = normalize_bounds(
        {
            "zone_max_totally": 30,
            "zone_max_inefficient": 10,
            "zone_max_moderate": 5,
            "zone_max_efficient": 4,
        }
    )
    assert out["zone_max_totally"] < out["zone_max_inefficient"]
    assert out["zone_max_inefficient"] < out["zone_max_moderate"]
    assert out["zone_max_moderate"] < out["zone_max_efficient"]


def test_bounds_are_clamped_into_range() -> None:
    out = normalize_bounds({"zone_max_totally": -50, "zone_max_efficient": 900})
    assert out["zone_max_totally"] >= 0.0
    assert out["zone_max_efficient"] <= 100.0


def test_scale_hint_names_every_band() -> None:
    hint = zone_scale_hint()
    for label in (
        "Totally Inefficient",
        "Inefficient",
        "Moderately Efficient",
        "Efficient",
        "Highly Efficient",
    ):
        assert label in hint


@pytest.mark.parametrize("score", [None, float("nan"), "not a number"])
def test_unscoreable_windows_are_empty_not_zero(score: object) -> None:
    """Too little activity to score is distinct from scoring zero."""
    zone = classify_efficiency(score)  # type: ignore[arg-type]
    assert zone == EMPTY_ZONE
    assert zone.is_empty
    assert zone.label == "—"


def test_zone_label_shortcut_matches_classification() -> None:
    assert efficiency_zone_label(42) == classify_efficiency(42).label


class TestInjectedBounds:
    """Admin-tuned ceilings arrive in a WeightSet, never from a database read."""

    def test_tuned_ceilings_move_the_bands(self) -> None:
        strict = WeightSet.from_overrides({"npei": {"zone_max_totally": 30.0}})

        assert classify_efficiency(20, weights=strict).label == "Totally Inefficient"
        assert classify_efficiency(20).label == "Inefficient"

    def test_load_bounds_reflects_the_weight_set(self) -> None:
        tuned = WeightSet.from_overrides({"npei": {"zone_max_moderate": 44.0}})
        assert load_bounds(tuned)["zone_max_moderate"] == 44.0

    def test_explicit_bounds_win_over_weights(self) -> None:
        weights = WeightSet.from_overrides({"npei": {"zone_max_totally": 30.0}})
        zone = classify_efficiency(20, bounds={"zone_max_totally": 5.0}, weights=weights)
        assert zone.label == "Inefficient"
