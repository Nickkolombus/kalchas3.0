"""Resolution of tunable strategy coefficients.

New in 3.0. Kalchas 2.2 had no tests for `utils/strategy_weights.py` because
`resolve()` required a live Postgres connection to exercise -- which is the
same reason a database outage could silently downgrade every coefficient to
its default in production.
"""

from __future__ import annotations

import pytest
from kalchas_core.weights import (
    BUILTIN_PRESETS,
    REGISTRY,
    STRATEGY_INFO,
    UnknownCoefficientError,
    WeightSet,
    spec_for,
    strategy_names,
)


class TestResolution:
    def test_default_comes_from_the_registry(self) -> None:
        assert WeightSet.defaults().get("npei", "w2_shot_accuracy") == 0.40

    def test_override_wins_over_default(self) -> None:
        tuned = WeightSet.from_overrides({"npei": {"w2_shot_accuracy": 0.55}})
        assert tuned.get("npei", "w2_shot_accuracy") == 0.55

    def test_unlisted_keys_fall_back_to_default(self) -> None:
        tuned = WeightSet.from_overrides({"npei": {"w2_shot_accuracy": 0.55}})
        assert tuned.get("npei", "w1_attack_conv") == 0.35

    def test_unknown_coefficient_raises_rather_than_returning_zero(self) -> None:
        """2.2 logged a warning and returned 0.0, silently zeroing a term."""
        with pytest.raises(UnknownCoefficientError):
            WeightSet.defaults().get("npei", "no_such_key")

    def test_unknown_strategy_raises(self) -> None:
        with pytest.raises(UnknownCoefficientError):
            WeightSet.defaults().for_strategy("no_such_strategy")


class TestOverrideHygiene:
    """Overrides come from a database table that outlives any given release."""

    def test_values_are_clamped_to_registered_bounds(self) -> None:
        spec = spec_for("npei", "w2_shot_accuracy")
        assert spec is not None

        too_high = WeightSet.from_overrides({"npei": {"w2_shot_accuracy": 99.0}})
        assert too_high.get("npei", "w2_shot_accuracy") == spec.max_val

        too_low = WeightSet.from_overrides({"npei": {"w2_shot_accuracy": -5.0}})
        assert too_low.get("npei", "w2_shot_accuracy") == spec.min_val

    def test_retired_coefficients_are_dropped_not_fatal(self) -> None:
        weights = WeightSet.from_overrides({"npei": {"coefficient_removed_in_v2": 1.0}})
        assert weights.get("npei", "w2_shot_accuracy") == 0.40

    def test_unknown_strategy_in_overrides_is_dropped(self) -> None:
        assert WeightSet.from_overrides({"retired_strategy": {"k": 1.0}}).overrides == {}

    @pytest.mark.parametrize("bad", ["abc", None, [1, 2]])
    def test_non_numeric_values_are_dropped(self, bad: object) -> None:
        weights = WeightSet.from_overrides({"npei": {"w2_shot_accuracy": bad}})  # type: ignore[dict-item]
        assert weights.get("npei", "w2_shot_accuracy") == 0.40

    def test_none_overrides_is_the_same_as_defaults(self) -> None:
        assert WeightSet.from_overrides(None).overrides == WeightSet.defaults().overrides


class TestImmutability:
    def test_a_weight_set_cannot_be_mutated_in_place(self) -> None:
        weights = WeightSet.from_overrides({"npei": {"w1_attack_conv": 0.5}})
        with pytest.raises(TypeError):
            weights.overrides["npei"]["w1_attack_conv"] = 0.9  # type: ignore[index]

    def test_layering_returns_a_new_object(self) -> None:
        base = WeightSet.from_overrides({"npei": {"w1_attack_conv": 0.5}})
        layered = base.with_overrides({"npei": {"w2_shot_accuracy": 0.6}})

        assert layered.get("npei", "w1_attack_conv") == 0.5
        assert layered.get("npei", "w2_shot_accuracy") == 0.6
        assert base.get("npei", "w2_shot_accuracy") == 0.40


class TestPresets:
    def test_every_preset_key_is_registered(self) -> None:
        """A typo in a preset would silently do nothing at runtime."""
        for strategy, presets in BUILTIN_PRESETS.items():
            for name, values in presets.items():
                for key in values:
                    assert spec_for(strategy, key) is not None, (
                        f"preset {strategy}/{name} sets unregistered key {key!r}"
                    )

    def test_preset_values_are_within_bounds(self) -> None:
        for strategy, presets in BUILTIN_PRESETS.items():
            for name, values in presets.items():
                for key, value in values.items():
                    spec = spec_for(strategy, key)
                    assert spec is not None
                    assert spec.min_val <= value <= spec.max_val, (
                        f"preset {strategy}/{name} sets {key}={value} outside bounds"
                    )

    def test_building_from_a_preset(self) -> None:
        weights = WeightSet.from_preset("npei", "Accuracy-biased")
        assert weights.get("npei", "w2_shot_accuracy") == 0.55

    def test_pressure_index_defaults_are_the_doubled_scale(self) -> None:
        weights = WeightSet.defaults()
        assert weights.get("pressure_index", "sot_points") == 26.0
        assert weights.get("pressure_index", "sofft_points") == 16.0
        assert weights.get("pressure_index", "corner_points") == 10.0
        assert weights.get("pressure_index", "da_points") == 4.0

    def test_stale_pressure_index_factory_points_are_dropped(self) -> None:
        weights = WeightSet.from_overrides(
            {
                "pressure_index": {
                    "sot_points": 13.0,
                    "sofft_points": 8.0,
                    "corner_points": 5.0,
                    "da_points": 2.0,
                    "time_mult_0_30": 0.85,
                }
            }
        )
        assert weights.get("pressure_index", "sot_points") == 26.0
        assert weights.get("pressure_index", "sofft_points") == 16.0
        assert weights.get("pressure_index", "corner_points") == 10.0
        assert weights.get("pressure_index", "da_points") == 4.0
        assert weights.get("pressure_index", "time_mult_0_30") == 0.85

    def test_custom_pressure_index_points_are_kept(self) -> None:
        weights = WeightSet.from_overrides(
            {"pressure_index": {"sot_points": 20.0, "da_points": 3.0}}
        )
        assert weights.get("pressure_index", "sot_points") == 20.0
        assert weights.get("pressure_index", "da_points") == 3.0
        assert weights.get("pressure_index", "sofft_points") == 16.0

    def test_omega_presets_cover_the_operator_named_sets(self) -> None:
        names = set(BUILTIN_PRESETS["omega"])
        assert names == {
            "Default (~30°)",
            "Sensitive",
            "Confirmed surges only",
            "Quiet / picky",
        }
        confirmed = WeightSet.from_preset("omega", "Confirmed surges only")
        assert confirmed.get("omega", "min_accel") == 0.866
        assert confirmed.get("omega", "min_baseline_slope") == 0.05
        assert confirmed.get("omega", "pi_level_min") == 45.0
        assert confirmed.get("omega", "min_shots") == 1.0

    def test_stale_omega_scale_pair_is_dropped(self) -> None:
        weights = WeightSet.from_overrides(
            {"omega": {"k_scale": 0.5, "min_accel": 0.363, "pi_level_min": 40.0}}
        )
        assert weights.get("omega", "k_scale") == 1.5
        assert weights.get("omega", "min_accel") == 0.866
        assert weights.get("omega", "pi_level_min") == 40.0

    def test_stale_k_scale_drops_old_min_accel_too(self) -> None:
        weights = WeightSet.from_overrides({"omega": {"k_scale": 0.5, "min_accel": 0.42}})
        assert weights.get("omega", "k_scale") == 1.5
        assert weights.get("omega", "min_accel") == 0.866

    def test_custom_omega_scale_is_kept(self) -> None:
        weights = WeightSet.from_overrides({"omega": {"k_scale": 2.0, "min_accel": 0.9}})
        assert weights.get("omega", "k_scale") == 2.0
        assert weights.get("omega", "min_accel") == 0.9

    def test_unknown_preset_raises(self) -> None:
        with pytest.raises(UnknownCoefficientError):
            WeightSet.from_preset("npei", "no such preset")


class TestRegistryIntegrity:
    @pytest.mark.parametrize("strategy", strategy_names())
    def test_defaults_sit_inside_their_own_bounds(self, strategy: str) -> None:
        for spec in REGISTRY[strategy]:
            assert spec.min_val <= spec.default <= spec.max_val, (
                f"{strategy}.{spec.key} default {spec.default} is outside "
                f"[{spec.min_val}, {spec.max_val}]"
            )

    @pytest.mark.parametrize("strategy", strategy_names())
    def test_keys_are_unique_within_a_strategy(self, strategy: str) -> None:
        keys = [spec.key for spec in REGISTRY[strategy]]
        assert len(keys) == len(set(keys))

    @pytest.mark.parametrize("strategy", strategy_names())
    def test_every_strategy_has_display_copy(self, strategy: str) -> None:
        info = STRATEGY_INFO[strategy]
        assert info.name
        assert info.short

    def test_rule_of_three_public_name_is_unrealised_goals(self) -> None:
        info = STRATEGY_INFO["rule_of_three"]
        assert info.name == "Unrealised goals"
        assert info.short == "UrG"

    def test_describe_shapes_a_row_per_coefficient(self) -> None:
        rows = WeightSet.defaults().describe("npei")
        assert len(rows) == len(REGISTRY["npei"])
        assert set(rows[0]) == {
            "key",
            "label",
            "default",
            "current",
            "min",
            "max",
            "step",
            "description",
            "suggested",
        }
