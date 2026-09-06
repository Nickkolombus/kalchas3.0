"""Efficiency zone labels for the NPEI (ΦI) score.

Five bands, each with an admin-tunable ceiling:

    0 .. zone_max_totally      -> Totally Inefficient
      .. zone_max_inefficient  -> Inefficient
      .. zone_max_moderate     -> Moderately Efficient
      .. zone_max_efficient    -> Efficient
    above zone_max_efficient   -> Highly Efficient

Ported from Kalchas 2.2 `utils/npei_efficiency_zones.py`. The banding logic is
unchanged. What changed is where the ceilings come from: 2.2's `_resolve_bound`
reached into `strategy_weights.resolve`, and therefore Postgres, on every call.
Here they arrive in a `WeightSet`.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from kalchas_core.weights import WeightSet

ZONE_KEYS: tuple[str, ...] = (
    "zone_max_totally",
    "zone_max_inefficient",
    "zone_max_moderate",
    "zone_max_efficient",
)

TIER_ORDER: tuple[str, ...] = ("totally", "inefficient", "moderate", "efficient", "highly")

ZONE_LABELS: Mapping[str, str] = MappingProxyType(
    {
        "totally": "Totally Inefficient",
        "inefficient": "Inefficient",
        "moderate": "Moderately Efficient",
        "efficient": "Efficient",
        "highly": "Highly Efficient",
    }
)

CSS_BY_TIER: Mapping[str, str] = MappingProxyType(
    {
        "totally": "npei-val--zero",
        "inefficient": "npei-val--low",
        "moderate": "npei-val--mild",
        "efficient": "npei-val--strong",
        "highly": "npei-val--extreme",
    }
)

EMPTY_TIER = "empty"
EMPTY_LABEL = "—"
EMPTY_CSS = "npei-val--empty"


@dataclass(frozen=True, slots=True)
class EfficiencyZone:
    """Where a ΦI score falls on the five-band scale."""

    tier: str
    label: str
    css_class: str

    @property
    def is_empty(self) -> bool:
        return self.tier == EMPTY_TIER


EMPTY_ZONE = EfficiencyZone(tier=EMPTY_TIER, label=EMPTY_LABEL, css_class=EMPTY_CSS)


def load_bounds(weights: WeightSet | None = None) -> Mapping[str, float]:
    """Read the four zone ceilings and guarantee each band has room."""
    w = weights or WeightSet.defaults()
    return normalize_bounds({key: w.get("npei", key) for key in ZONE_KEYS})


def normalize_bounds(raw: Mapping[str, float]) -> Mapping[str, float]:
    """Force strictly increasing ceilings inside [0, 100].

    An admin can drag sliders into a nonsensical order (a Moderate ceiling
    below the Inefficient one). Rather than reject it, nudge each ceiling to at
    least one point above its predecessor so every band stays reachable.
    """
    out: dict[str, float] = {}
    previous = -1.0
    defaults = {key: _default_bound(key) for key in ZONE_KEYS}

    for key in ZONE_KEYS:
        try:
            value = float(raw.get(key, defaults[key]))
        except (TypeError, ValueError):
            value = defaults[key]
        if math.isnan(value):
            value = defaults[key]

        value = max(0.0, min(100.0, value))
        if value <= previous:
            value = min(100.0, previous + 1.0)

        out[key] = value
        previous = value

    return MappingProxyType(out)


def _default_bound(key: str) -> float:
    from kalchas_core.weights import spec_for

    spec = spec_for("npei", key)
    # Every ZONE_KEYS entry is registered, so spec is never None in practice.
    return spec.default if spec else 0.0


def classify_efficiency(
    score: float | None,
    *,
    bounds: Mapping[str, float] | None = None,
    weights: WeightSet | None = None,
) -> EfficiencyZone:
    """Map a ΦI score (0-100) to its tier, label, and dashboard CSS class.

    A `None` or NaN score is not an error -- it means the window had too little
    activity to score -- and yields `EMPTY_ZONE`.
    """
    resolved = normalize_bounds(bounds) if bounds is not None else load_bounds(weights)

    if score is None:
        return EMPTY_ZONE
    try:
        value = float(score)
    except (TypeError, ValueError):
        return EMPTY_ZONE
    if math.isnan(value):
        return EMPTY_ZONE

    if value <= resolved["zone_max_totally"]:
        tier = "totally"
    elif value <= resolved["zone_max_inefficient"]:
        tier = "inefficient"
    elif value <= resolved["zone_max_moderate"]:
        tier = "moderate"
    elif value <= resolved["zone_max_efficient"]:
        tier = "efficient"
    else:
        tier = "highly"

    return EfficiencyZone(tier=tier, label=ZONE_LABELS[tier], css_class=CSS_BY_TIER[tier])


def efficiency_zone_label(score: float | None, *, weights: WeightSet | None = None) -> str:
    """Short label stored on NPEI snapshots as `home_zone` / `away_zone`."""
    return classify_efficiency(score, weights=weights).label


def zone_scale_hint(bounds: Mapping[str, float] | None = None) -> str:
    """One-line legend of the current bands, shown under the dashboard scale."""
    b = normalize_bounds(bounds) if bounds is not None else load_bounds()
    totally = int(b["zone_max_totally"])
    inefficient = int(b["zone_max_inefficient"])
    moderate = int(b["zone_max_moderate"])
    efficient = int(b["zone_max_efficient"])

    return (
        f"0–{totally} {ZONE_LABELS['totally']} · "
        f"{totally + 1}–{inefficient} {ZONE_LABELS['inefficient']} · "
        f"{inefficient + 1}–{moderate} {ZONE_LABELS['moderate']} · "
        f"{moderate + 1}–{efficient} {ZONE_LABELS['efficient']} · "
        f"{efficient + 1}+ {ZONE_LABELS['highly']}"
    )
