"""Score parsing helpers for outcome evaluation."""

from __future__ import annotations


def parse_score(score_str: str | None) -> tuple[int, int]:
    """Return `(home, away)` ints from a `'H-A'` string. On error return `(0, 0)`."""
    if not score_str:
        return 0, 0
    try:
        parts = str(score_str).strip().split("-")
        if len(parts) != 2:
            return 0, 0
        return int(parts[0].strip()), int(parts[1].strip())
    except (ValueError, AttributeError, TypeError):
        return 0, 0
