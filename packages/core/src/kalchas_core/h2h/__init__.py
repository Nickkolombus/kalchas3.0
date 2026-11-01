"""Head-to-head enrichment (Strategy 10) — pure stats and timing counts."""

from kalchas_core.h2h.payload import build_h2h_payload, empty_h2h_payload, orient_h2h_payload
from kalchas_core.h2h.stats import (
    DEFAULT_LAST,
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
    h2h_meeting_averages,
    normalize_fixture,
)

__all__ = [
    "DEFAULT_LAST",
    "DEFAULT_MIN_SAMPLE",
    "CountPct",
    "H2HFixture",
    "H2HStats",
    "TeamH2H",
    "TimingCounts",
    "build_h2h_payload",
    "compute_h2h_stats",
    "compute_timing_counts",
    "dedup_fixtures",
    "empty_h2h",
    "empty_h2h_payload",
    "h2h_meeting_averages",
    "normalize_fixture",
    "orient_h2h_payload",
]
