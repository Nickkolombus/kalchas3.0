"""Board odds output only shows a live 1X2 line while it is fresh."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from kalchas_api.app import _odds_out


def _record(fetched_at: str | None) -> dict:
    live: dict = {"home": 11.0, "draw": 1.055, "away": 17.0}
    if fetched_at is not None:
        live["fetched_at"] = fetched_at
    return {
        "home": 1.7,
        "draw": 3.9,
        "away": 4.2,
        "kickoff": {"home": 1.7, "draw": 3.9, "away": 4.2},
        "live": live,
    }


def test_board_odds_hide_unstamped_and_stale_live_lines() -> None:
    old = (datetime.now(UTC) - timedelta(minutes=20)).isoformat()
    for record in (_record(None), _record(old)):
        out = _odds_out(record)
        assert out is not None
        assert out.kickoff is not None and out.kickoff.home == 1.7
        assert out.live is None


def test_board_odds_show_a_fresh_live_line() -> None:
    out = _odds_out(_record(datetime.now(UTC).isoformat()))
    assert out is not None
    assert out.live is not None
    assert out.live.draw == 1.055
