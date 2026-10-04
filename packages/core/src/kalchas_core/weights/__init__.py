"""Effective strategy coefficients, resolved without touching a database.

In Kalchas 2.2 a formula that needed a coefficient called
`utils.strategy_weights.resolve(strategy, key)`, which opened a Postgres
connection, read `strategy_thresholds`, and fell back to a default if the read
failed. Three things followed from that:

* No formula could be evaluated without a database, so most were never
  unit-tested.
* A single strategy evaluation issued one query per coefficient.
* A silent `except Exception` around the read meant a database outage
  downgraded every coefficient to its default without anyone noticing.

`WeightSet` inverts it. Services load overrides once -- from Postgres, a
config file, or a test fixture -- and hand the resulting immutable object to
the formulas. Resolution order is unchanged: **override -> registry default**.

    >>> weights = WeightSet.defaults()
    >>> weights.get("npei", "w2_shot_accuracy")
    0.4
    >>> tuned = WeightSet.from_overrides({"npei": {"w2_shot_accuracy": 0.55}})
    >>> tuned.get("npei", "w2_shot_accuracy")
    0.55
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any

from kalchas_core.weights.registry import (
    BUILTIN_PRESETS,
    REGISTRY,
    STRATEGY_INFO,
    StrategyInfo,
    WeightSpec,
    display_name_for,
    short_label_for,
    spec_for,
    strategy_names,
)

__all__ = [
    "BUILTIN_PRESETS",
    "REGISTRY",
    "STRATEGY_INFO",
    "StrategyInfo",
    "UnknownCoefficientError",
    "WeightSet",
    "WeightSpec",
    "display_name_for",
    "short_label_for",
    "spec_for",
    "strategy_names",
]


class UnknownCoefficientError(KeyError):
    """Raised when asking for a coefficient that is not in the registry."""


def _drop_stale_omega_scale(
    overrides: Mapping[str, Mapping[str, float]],
) -> Mapping[str, Mapping[str, float]]:
    """Ignore the pre-recalibration display scale (k=0.5).

    Admin rows saved under k=0.5 printed 50°+ on ordinary busy spells. Drop
    that scale and its companion min_accel so new defaults apply (k=1.5,
    fire at 30°). Other Omega gates (baseline, PI, windows) stay.
    """
    omega = overrides.get("omega")
    if not isinstance(omega, Mapping):
        return overrides
    try:
        scale = float(omega["k_scale"]) if "k_scale" in omega else None
    except (TypeError, ValueError):
        return overrides
    if scale is None or abs(scale - 0.5) > 1e-6:
        return overrides
    cleaned = dict(overrides)
    omega_clean = {
        key: value for key, value in omega.items() if key not in {"k_scale", "min_accel"}
    }
    if omega_clean:
        cleaned["omega"] = omega_clean
    else:
        cleaned.pop("omega", None)
    return cleaned


def _freeze(overrides: Mapping[str, Mapping[str, float]]) -> Mapping[str, Mapping[str, float]]:
    """Validate, clamp, and deep-freeze a set of overrides.

    Unknown strategies and unknown keys are dropped rather than raising: the
    overrides usually come from a database table that outlives any given
    release, so a coefficient retired in code should not break startup.
    Out-of-range values are clamped to the registered bounds.
    """
    overrides = _drop_stale_omega_scale(overrides)
    frozen: dict[str, Mapping[str, float]] = {}
    for strategy, values in overrides.items():
        if strategy not in REGISTRY or not isinstance(values, Mapping):
            continue
        kept: dict[str, float] = {}
        for key, raw in values.items():
            spec = spec_for(strategy, key)
            if spec is None:
                continue
            try:
                kept[key] = spec.clamp(float(raw))
            except (TypeError, ValueError):
                continue
        if kept:
            frozen[strategy] = MappingProxyType(kept)
    return MappingProxyType(frozen)


@dataclass(frozen=True, slots=True)
class WeightSet:
    """An immutable snapshot of effective coefficient values.

    Build one per evaluation cycle and pass it down. Never construct this
    directly from untrusted input -- use `from_overrides`, which clamps.
    """

    overrides: Mapping[str, Mapping[str, float]] = field(
        default_factory=lambda: MappingProxyType({})
    )

    @classmethod
    def defaults(cls) -> WeightSet:
        """Every coefficient at its registry default."""
        return cls()

    @classmethod
    def from_overrides(cls, overrides: Mapping[str, Mapping[str, float]] | None) -> WeightSet:
        """Build from a `{strategy: {key: value}}` mapping, clamped to bounds."""
        return cls(_freeze(overrides or {}))

    @classmethod
    def from_preset(cls, strategy: str, preset_name: str) -> WeightSet:
        """Build from one of the built-in presets."""
        presets = BUILTIN_PRESETS.get(strategy)
        if presets is None or preset_name not in presets:
            raise UnknownCoefficientError(f"no preset {preset_name!r} for strategy {strategy!r}")
        return cls.from_overrides({strategy: presets[preset_name]})

    def get(self, strategy: str, key: str) -> float:
        """Effective value for one coefficient: override, else registry default.

        Raises `UnknownCoefficientError` for an unregistered coefficient. 2.2
        logged a warning and returned 0.0 here, which silently zeroed a term in
        whichever formula had the typo.
        """
        override = self.overrides.get(strategy, {}).get(key)
        if override is not None:
            return override

        spec = spec_for(strategy, key)
        if spec is None:
            raise UnknownCoefficientError(f"{strategy}.{key} is not a registered coefficient")
        return spec.default

    def for_strategy(self, strategy: str) -> Mapping[str, float]:
        """Every registered coefficient for one strategy at its effective value."""
        if strategy not in REGISTRY:
            raise UnknownCoefficientError(f"{strategy!r} is not a registered strategy")
        return MappingProxyType(
            {spec.key: self.get(strategy, spec.key) for spec in REGISTRY[strategy]}
        )

    def describe(self, strategy: str) -> list[dict[str, Any]]:
        """Specs plus current values, shaped for the admin settings UI."""
        if strategy not in REGISTRY:
            raise UnknownCoefficientError(f"{strategy!r} is not a registered strategy")
        return [
            {
                "key": spec.key,
                "label": spec.label,
                "default": spec.default,
                "current": self.get(strategy, spec.key),
                "min": spec.min_val,
                "max": spec.max_val,
                "step": spec.step,
                "description": spec.description,
                "suggested": spec.suggested or str(spec.default),
            }
            for spec in REGISTRY[strategy]
        ]

    def with_overrides(self, overrides: Mapping[str, Mapping[str, float]]) -> WeightSet:
        """A new WeightSet with `overrides` layered on top of this one."""
        merged: dict[str, dict[str, float]] = {
            strategy: dict(values) for strategy, values in self.overrides.items()
        }
        for strategy, values in overrides.items():
            merged.setdefault(strategy, {}).update(values)
        return WeightSet.from_overrides(merged)
