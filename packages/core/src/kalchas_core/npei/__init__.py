"""NPEI -- Net Pressure Efficiency Index (Strategy 5).

Measures how efficiently a team converts pressure, rather than how much
pressure it generates. Three ratios over a rolling window, blended into a
0-100 score and labelled with an efficiency zone.
"""

from kalchas_core.npei.calculator import (
    NPEI_CAP,
    NpeiSnapshot,
    TeamEfficiency,
    cap_signal,
    compute_npei,
)
from kalchas_core.npei.zones import (
    CSS_BY_TIER,
    EMPTY_ZONE,
    TIER_ORDER,
    ZONE_KEYS,
    ZONE_LABELS,
    EfficiencyZone,
    classify_efficiency,
    efficiency_zone_label,
    load_bounds,
    normalize_bounds,
    zone_scale_hint,
)

__all__ = [
    "CSS_BY_TIER",
    "EMPTY_ZONE",
    "NPEI_CAP",
    "TIER_ORDER",
    "ZONE_KEYS",
    "ZONE_LABELS",
    "EfficiencyZone",
    "NpeiSnapshot",
    "TeamEfficiency",
    "cap_signal",
    "classify_efficiency",
    "compute_npei",
    "efficiency_zone_label",
    "load_bounds",
    "normalize_bounds",
    "zone_scale_hint",
]
