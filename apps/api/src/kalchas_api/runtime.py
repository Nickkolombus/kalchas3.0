"""Load persisted weights / thresholds / extra conditions for the live board."""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any

from kalchas_core.runner import DEFAULT_THRESHOLDS
from kalchas_core.weights import WeightSet
from kalchas_db.settings import KEY_BY_SLOT

logger = logging.getLogger("kalchas.api")

_CACHE_TTL = 15.0
_cached_at = 0.0
_cached: BoardTuning | None = None


@dataclass(frozen=True, slots=True)
class BoardTuning:
    weights: WeightSet
    thresholds: dict[int, float]
    conditions: dict[int, list[dict[str, Any]]] = field(default_factory=dict)


def load_board_tuning() -> BoardTuning:
    """WeightSet + fire thresholds + extra conditions. Falls back to core defaults."""
    global _cached_at, _cached
    now = time.monotonic()
    if _cached is not None and now - _cached_at < _CACHE_TTL:
        return _cached
    dsn = os.environ.get("DATABASE_URL") or os.environ.get("POSTGRES_URL")
    weights = WeightSet.defaults()
    thresholds = dict(DEFAULT_THRESHOLDS)
    conditions: dict[int, list[dict[str, Any]]] = {}
    if dsn:
        try:
            from kalchas_db.settings import (
                list_strategy_conditions,
                list_thresholds,
                list_weight_overrides,
            )

            stored = list_weight_overrides(dsn)
            if stored:
                weights = WeightSet.from_overrides(stored)
            stored_th = list_thresholds(dsn)
            thresholds.update(
                {slot: value for slot, value in stored_th.items() if slot in KEY_BY_SLOT}
            )
            conditions = list_strategy_conditions(dsn)
        except Exception:
            logger.debug("board tuning unavailable", exc_info=True)
    _cached = BoardTuning(weights=weights, thresholds=thresholds, conditions=conditions)
    _cached_at = now
    return _cached


def clear_board_tuning_cache() -> None:
    global _cached_at, _cached
    _cached = None
    _cached_at = 0.0
