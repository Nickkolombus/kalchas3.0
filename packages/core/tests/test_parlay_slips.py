"""A posted slip's legs judged from match results, and the slip's verdict."""

from __future__ import annotations

from typing import Any

from kalchas_core.watchlist.parlay_slips import judge, marks, result_caption, snapshot, verdict


def leg(mid: str, market: str = "over_2_5", price: float = 1.5) -> dict[str, Any]:
    return {
        "match_id": mid,
        "market": market,
        "label": market,
        "price": price,
        "home": {"name": "Home", "badge": None},
        "away": {"name": "Away", "badge": None},
    }


def finished(h: int, a: int) -> dict[str, Any]:
    return {
        "result": {
            "status": "finished",
            "label": "FT",
            "home": h,
            "away": a,
            "home_90": h,
            "away_90": a,
        }
    }


def test_judge_waits_for_a_result() -> None:
    assert judge(leg("1"), None)["state"] == "pending"
    assert judge(leg("1"), {"result": None})["state"] == "pending"


def test_judge_settles_the_posted_market() -> None:
    assert judge(leg("1", "over_2_5"), finished(2, 1))["state"] == "landed"
    assert judge(leg("1", "under_2_5"), finished(2, 1))["state"] == "missed"
    assert judge(leg("1", "btts_yes"), finished(2, 1))["score"] == "2–1"


def test_called_off_goes_to_the_admin() -> None:
    seen = judge(leg("1"), {"result": {"status": "off", "label": "Postponed"}})
    assert seen == {"state": "off", "note": "Postponed"}


def test_a_result_that_cant_settle_is_not_guessed() -> None:
    page = {"result": {"status": "finished", "label": "FT", "home": 1, "away": 0}}  # no 90' score
    assert judge(leg("1"), page)["state"] == "unjudged"
    page["result"].update(home_90=1, away_90=0)
    assert judge(leg("1", "late_goal"), page)["state"] == "unjudged"
    assert judge(leg("1", "under_2_5"), page)["state"] == "landed"


def test_verdict_waits_for_every_leg() -> None:
    legs = [leg("1"), leg("2"), leg("3")]
    v = verdict(legs, {"1": {"outcome": "missed"}, "2": {"outcome": "landed"}})
    assert v["done"] is False
    assert v["result"] is None


def test_verdict_came_in_with_a_void_leg_at_evens() -> None:
    legs = [leg("1", price=2.0), leg("2", price=1.5), leg("3", price=3.0)]
    v = verdict(
        legs,
        {"1": {"outcome": "landed"}, "2": {"outcome": "void"}, "3": {"outcome": "landed"}},
    )
    assert v["result"] == "came_in"
    assert v["combined"] == 6.0
    assert v["returns"] == 60.0


def test_verdict_lost_names_the_legs() -> None:
    legs = [leg("1"), leg("2"), leg("3")]
    outs = {"1": "landed", "2": "missed", "3": "missed"}
    v = verdict(legs, {k: {"outcome": o} for k, o in outs.items()})
    assert v["result"] == "lost"
    assert v["missed_legs"] == [2, 3]
    assert "missed on legs 2, 3" in result_caption({}, v)


def test_open_questions_draw_no_marks() -> None:
    outcomes = {"1": {"outcome": "landed"}, "2": {"state": "off", "note": "Postponed"}}
    assert marks(outcomes) == {"1": "landed"}


def test_snapshot_keeps_what_the_slip_needs() -> None:
    full = leg("9") | {"kickoff": "2026-11-08T20:00:00+02:00", "brief": "long text", "score": 0.4}
    snap = snapshot(full)
    assert snap["price"] == 1.5
    assert snap["home"] == {"name": "Home", "badge": None}
    assert "brief" not in snap
