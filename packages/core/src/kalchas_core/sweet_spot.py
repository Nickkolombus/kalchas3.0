"""Sweet-spot clock windows for the live board filter."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

DEFAULT_HT1_START = 28
DEFAULT_HT1_END = 44
DEFAULT_HT2_START = 72
DEFAULT_HT2_END = 88
MINUTE_BOUNDS = (0, 130)


@dataclass(frozen=True, slots=True)
class SweetSpotWindows:
    ht1_start: int = DEFAULT_HT1_START
    ht1_end: int = DEFAULT_HT1_END
    ht2_start: int = DEFAULT_HT2_START
    ht2_end: int = DEFAULT_HT2_END
    include_injury_time: bool = False

    @classmethod
    def from_mapping(cls, raw: dict[str, Any] | None = None) -> SweetSpotWindows:
        data = raw or {}
        return normalize_windows(
            ht1_start=data.get("ht1_start", DEFAULT_HT1_START),
            ht1_end=data.get("ht1_end", DEFAULT_HT1_END),
            ht2_start=data.get("ht2_start", DEFAULT_HT2_START),
            ht2_end=data.get("ht2_end", DEFAULT_HT2_END),
            include_injury_time=bool(data.get("include_injury_time", False)),
        )

    def as_dict(self) -> dict[str, int | bool]:
        return {
            "ht1_start": self.ht1_start,
            "ht1_end": self.ht1_end,
            "ht2_start": self.ht2_start,
            "ht2_end": self.ht2_end,
            "include_injury_time": self.include_injury_time,
        }


def _clamp_minute(value: Any, default: int) -> int:
    try:
        minute = int(value)
    except (TypeError, ValueError):
        minute = default
    return max(MINUTE_BOUNDS[0], min(MINUTE_BOUNDS[1], minute))


def normalize_windows(
    *,
    ht1_start: Any,
    ht1_end: Any,
    ht2_start: Any,
    ht2_end: Any,
    include_injury_time: bool,
) -> SweetSpotWindows:
    first = sorted(
        (
            _clamp_minute(ht1_start, DEFAULT_HT1_START),
            _clamp_minute(ht1_end, DEFAULT_HT1_END),
        )
    )
    second = sorted(
        (
            _clamp_minute(ht2_start, DEFAULT_HT2_START),
            _clamp_minute(ht2_end, DEFAULT_HT2_END),
        )
    )
    return SweetSpotWindows(
        ht1_start=first[0],
        ht1_end=first[1],
        ht2_start=second[0],
        ht2_end=second[1],
        include_injury_time=bool(include_injury_time),
    )


def _display_token(minute_display: str | None) -> str:
    return (minute_display or "").replace("′", "'").replace(" ", "").rstrip("'")


def is_first_half_injury(
    minute: int,
    status_short: str | None = None,
    minute_display: str | None = None,
) -> bool:
    token = _display_token(minute_display)
    if token.startswith("45+"):
        return True
    return (status_short or "").upper() == "1H" and minute > 45


def is_second_half_injury(
    minute: int,
    status_short: str | None = None,
    minute_display: str | None = None,
) -> bool:
    token = _display_token(minute_display)
    if token.startswith("90+"):
        return True
    return (status_short or "").upper() == "2H" and minute > 90


def in_sweet_spot(
    minute: int,
    *,
    status_short: str | None = None,
    minute_display: str | None = None,
    windows: SweetSpotWindows | None = None,
) -> bool:
    """True when the live clock sits in a configured half window.

    Injury time (45+x / 90+x) is outside the numeric windows unless
    ``include_injury_time`` is on. Extra time is never a sweet-spot minute.
    """
    settings = windows or SweetSpotWindows()
    if (status_short or "").upper() == "ET":
        return False
    first_injury = is_first_half_injury(minute, status_short, minute_display)
    second_injury = is_second_half_injury(minute, status_short, minute_display)
    if first_injury or second_injury:
        return settings.include_injury_time
    return (settings.ht1_start <= minute <= settings.ht1_end) or (
        settings.ht2_start <= minute <= settings.ht2_end
    )
