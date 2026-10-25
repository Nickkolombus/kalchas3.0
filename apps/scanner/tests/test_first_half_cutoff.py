"""The scanner's "is it the first half" for the first-half cut-off.

Decided from the status the feed parser produces, because first-half stoppage
arrives with a second-half-looking minute (45+3 is 48).
"""

from __future__ import annotations

from kalchas_football.client import _parse_elapsed
from kalchas_scanner.loop import _in_first_half


def test_first_half_stoppage_is_still_the_first_half() -> None:
    minute, status, display = _parse_elapsed("45+3")
    assert (minute, display) == (48, "45+3")
    assert _in_first_half(status)


def test_half_time_counts_as_first_half() -> None:
    assert _in_first_half(_parse_elapsed("Half Time")[1])


def test_second_half_does_not() -> None:
    assert not _in_first_half(_parse_elapsed("48")[1])
    assert not _in_first_half(_parse_elapsed("90+4")[1])
    assert not _in_first_half(None)
