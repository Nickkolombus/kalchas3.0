"""Head-to-head enrichment (Strategy 10) — pure stats and timing counts."""

from kalchas_core.h2h.stats import (
    DEFAULT_MIN_SAMPLE,
    CountPct,
    H2HFixture,
    H2HStats,
    TeamH2H,
    TimingCounts,
    compute_h2h_stats,
    compute_timing_counts,
    dedup_fixtures,
    empty_h2h,
    normalize_fixture,
)

__all__ = [
    "DEFAULT_MIN_SAMPLE",
    "CountPct",
    "H2HFixture",
    "H2HStats",
    "TeamH2H",
    "TimingCounts",
    "compute_h2h_stats",
    "compute_timing_counts",
    "dedup_fixtures",
    "empty_h2h",
    "normalize_fixture",
]
