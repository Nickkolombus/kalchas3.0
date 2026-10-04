"""Sweet-spot window membership."""

from __future__ import annotations

from kalchas_core.sweet_spot import SweetSpotWindows, in_sweet_spot, normalize_windows


def test_defaults_keep_late_first_half_and_late_second_half() -> None:
    windows = SweetSpotWindows()
    assert in_sweet_spot(28, windows=windows)
    assert in_sweet_spot(44, windows=windows)
    assert in_sweet_spot(72, windows=windows)
    assert in_sweet_spot(88, windows=windows)
    assert not in_sweet_spot(12, windows=windows)
    assert not in_sweet_spot(45, windows=windows)
    assert not in_sweet_spot(60, windows=windows)
    assert not in_sweet_spot(90, windows=windows)


def test_injury_time_stays_out_until_the_checkbox_is_on() -> None:
    off = SweetSpotWindows()
    on = SweetSpotWindows(include_injury_time=True)
    assert not in_sweet_spot(47, status_short="1H", minute_display="45+2", windows=off)
    assert in_sweet_spot(47, status_short="1H", minute_display="45+2", windows=on)
    assert not in_sweet_spot(92, status_short="2H", minute_display="90+2", windows=off)
    assert in_sweet_spot(92, status_short="2H", minute_display="90+2", windows=on)


def test_bare_stoppage_mark_counts_as_injury() -> None:
    on = SweetSpotWindows(include_injury_time=True)
    assert in_sweet_spot(45, status_short="1H", minute_display="45+", windows=on)
    assert in_sweet_spot(90, status_short="2H", minute_display="90+", windows=on)


def test_extra_time_is_never_a_sweet_spot() -> None:
    on = SweetSpotWindows(include_injury_time=True)
    assert not in_sweet_spot(91, status_short="ET", minute_display="90+1", windows=on)


def test_normalize_swaps_reversed_bounds() -> None:
    windows = normalize_windows(
        ht1_start=44,
        ht1_end=28,
        ht2_start=88,
        ht2_end=72,
        include_injury_time=True,
    )
    assert windows.ht1_start == 28
    assert windows.ht1_end == 44
    assert windows.ht2_start == 72
    assert windows.ht2_end == 88
    assert windows.include_injury_time is True
