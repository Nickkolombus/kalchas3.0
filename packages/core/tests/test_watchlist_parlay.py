"""The day's parlay: one priced leg per strong match, three orders."""

from __future__ import annotations

from typing import Any

from kalchas_core.watchlist.parlay import MAX_LEGS, build, leg_for, order


def page(
    match_id: str,
    *,
    watch: str = "strong",
    patterns: list[tuple[str, float]] | None = None,
    odds: dict[str, float] | None = None,
    btts: tuple[int, int, int, int] = (8, 10, 7, 10),
    over: tuple[int, int, int, int] = (9, 10, 8, 10),
    wins: tuple[int, int] = (9, 10),
    kickoff: str = "2026-11-06T20:00:00+03:00",
) -> dict[str, Any]:
    def row(key: str, c: tuple[int, int, int, int]) -> dict[str, Any]:
        return {"key": key, "home": {"count": c[0], "n": c[1]}, "away": {"count": c[2], "n": c[3]}}

    return {
        "match_id": match_id,
        "kickoff": kickoff,
        "league": {"name": "Eredivisie", "country": "Netherlands"},
        "home": {"name": f"Home {match_id}", "badge": None, "position": 2},
        "away": {"name": f"Away {match_id}", "badge": None, "position": 9},
        "watch": watch,
        "score": 0.6,
        "odds": odds
        if odds is not None
        else {
            "home": 1.3,
            "away": 9.0,
            "over_2_5": 1.5,
            "under_2_5": 2.6,
            "btts_yes": 1.7,
            "btts_no": 2.1,
        },
        "patterns": [
            {
                "key": k,
                "tag": k,
                "score": s,
                "brief": f"{k} brief",
                "outcome": None,
                "outcome_note": "",
            }
            for k, s in (patterns if patterns is not None else [("over_2_5", 0.5)])
        ],
        "pattern_table": [row("btts", btts), row("over_2_5", over)],
        "form": {"home": {"games": wins[1], "wins": wins[0]}, "away": {"games": 10, "wins": 2}},
        "result": None,
    }


def test_the_strongest_priced_pattern_makes_the_leg() -> None:
    leg = leg_for(page("1", patterns=[("red_card", 0.8), ("over_2_5", 0.4), ("btts_yes", 0.3)]))
    assert leg is not None
    assert (leg["market"], leg["label"], leg["price"]) == ("over_2_5", "Over 2.5 goals", 1.5)
    assert (leg["hit"], leg["n"]) == (17, 20)
    assert leg["brief"] == "over_2_5 brief"


def test_unders_and_btts_no_count_the_games_where_it_did_not_happen() -> None:
    under = leg_for(page("1", patterns=[("under_2_5", 0.5)], over=(3, 10, 4, 10)))
    assert under is not None and (under["hit"], under["n"]) == (13, 20)
    no = leg_for(page("2", patterns=[("btts_no", 0.5)], btts=(5, 10, 4, 9)))
    assert no is not None and (no["hit"], no["n"], no["label"]) == (10, 19, "Both teams score: No")


def test_a_favourite_is_priced_from_the_match_odds_and_its_wins() -> None:
    leg = leg_for(page("1", patterns=[("favourite_home", 0.4)], wins=(8, 10)))
    assert leg is not None
    assert (leg["label"], leg["price"], leg["hit"], leg["n"]) == ("Home 1 to win", 1.3, 8, 10)


def test_no_leg_without_a_price_a_strong_enough_pattern_or_a_strong_list_spot() -> None:
    assert leg_for(page("1", patterns=[("late_goal", 0.7), ("red_card", 0.5)])) is None
    assert leg_for(page("2", patterns=[("over_2_5", 0.1)])) is None
    assert leg_for(page("3", odds={"home": 1.3})) is None
    assert leg_for(page("4", watch="quiet")) is None


def test_strong_legs_always_come_before_worth_a_look() -> None:
    legs = [
        leg_for(page("1", watch="look", patterns=[("over_2_5", 0.9)])),
        leg_for(page("2", patterns=[("over_2_5", 0.2)])),
    ]
    for style in ("safer", "balanced", "bolder"):
        assert order([x for x in legs if x], style)[0] == "2"


def test_safer_takes_short_prices_and_only_reliable_legs() -> None:
    short = leg_for(page("1", patterns=[("favourite_home", 0.3)], wins=(9, 10)))
    long_ = leg_for(
        page("2", patterns=[("btts_no", 0.6)], odds={"btts_no": 3.2}, btts=(5, 10, 4, 10))
    )
    legs = [x for x in (short, long_) if x]
    assert order(legs, "safer") == ["1"]  # 11 of 20 is below the safer bar
    assert order(legs, "balanced") == ["2", "1"]  # by pattern strength
    assert order(legs, "bolder")[0] == "2"  # its record beats a 3.20 price by the most


def test_build_lists_legs_by_kickoff_and_names_strong_matches_left_out() -> None:
    pages = [page(str(i), kickoff=f"2026-11-06T{10 + i % 12:02d}:00:00+03:00") for i in range(25)]
    pages.append(page("99", patterns=[("late_goal", 0.6)]))
    built = build(pages)
    assert len(built["legs"]) == 25
    assert [leg["kickoff"] for leg in built["legs"]] == sorted(
        leg["kickoff"] for leg in built["legs"]
    )
    assert all(len(ids) == MAX_LEGS for ids in built["order"].values())
    assert built["unpriced"] == [
        {"match_id": "99", "home": "Home 99", "away": "Away 99", "tags": ["late_goal"]}
    ]


def test_a_settled_leg_keeps_its_outcome() -> None:
    p = page("1")
    p["patterns"][0].update(outcome="landed", outcome_note="4 goals.")
    p["result"] = {"status": "finished", "label": "FT", "home": 3, "away": 1}
    leg = leg_for(p)
    assert leg is not None
    assert (leg["outcome"], leg["outcome_note"], leg["result"]["home"]) == ("landed", "4 goals.", 3)
