"""After full time: scores, pattern outcomes and the day's tally."""

from __future__ import annotations

from typing import Any

from kalchas_core.watchlist import (
    assemble_day,
    day_summary,
    is_settled,
    match_result,
    settle,
    settle_page,
)


def row(
    status: str = "FT",
    h: int | None = 2,
    a: int | None = 1,
    *,
    final: tuple[int, int] | None = None,
    ht: tuple[int, int] | None = (1, 0),
    goals: list[tuple[str, int, str, str]] | None = None,
    pens: tuple[int, int] | None = None,
) -> dict[str, Any]:
    """`goals` are (display, minute, half, side)."""
    fh, fa = final or (h, a)
    return {
        "match_id": "1",
        "status_short": status,
        "home_90": h,
        "away_90": a,
        "home_final": fh,
        "away_final": fa,
        "home_ht": ht[0] if ht else None,
        "away_ht": ht[1] if ht else None,
        "home_pens": pens[0] if pens else None,
        "away_pens": pens[1] if pens else None,
        "goals": [
            {"display": d, "minute": m, "half": half, "side": side}
            for d, m, half, side in goals or []
        ],
    }


def judge(key: str, result: dict[str, Any] | None) -> tuple[str | None, str]:
    return settle(key, result, home="Norwich", away="Hull")


def test_unfinished_matches_have_no_result_and_called_off_ones_say_so() -> None:
    assert match_result(row("2H")) is None
    assert match_result(row("PST", None, None)) == {"status": "off", "label": "Postponed"}
    assert judge("btts_yes", match_result(row("PST", None, None))) == (None, "")


def test_goal_markets_and_team_patterns() -> None:
    result = match_result(row("FT", 2, 1))
    assert judge("btts_yes", result) == ("landed", "Both teams scored.")
    assert judge("btts_no", result) == ("missed", "Both teams scored.")
    assert judge("over_2_5", result) == ("landed", "3 goals.")
    assert judge("under_2_5", result) == ("missed", "3 goals.")
    assert judge("favourite_home", result) == ("landed", "Norwich won.")
    assert judge("favourite_away", result) == ("missed", "Hull lost.")
    assert judge("leaky_away", result) == ("landed", "Hull conceded.")
    assert judge("blanks_away", result) == ("missed", "Hull scored.")
    assert judge("home_scoring_run", result) == ("landed", "Norwich scored.")
    assert judge("first_half_goal", result) == ("landed", "1–0 at half-time.")

    nil = match_result(row("FT", 0, 0, ht=(0, 0)))
    assert judge("btts_no", nil) == ("landed", "Neither side scored.")
    assert judge("blanks_home", nil) == ("landed", "Norwich failed to score.")
    assert judge("leaky_home", nil) == ("missed", "Norwich kept a clean sheet.")
    assert judge("late_goal", nil) == ("missed", "No goals.")

    one = match_result(row("FT", 0, 1))
    assert judge("btts_yes", one) == ("missed", "Only Hull scored.")
    assert judge("over_2_5", one) == ("missed", "1 goal.")


def test_late_goals_need_goal_times() -> None:
    timed = match_result(
        row(
            "FT",
            2,
            1,
            goals=[
                ("12", 12, "1H", "home"),
                ("45+3", 48, "1H", "away"),
                ("90+2", 92, "2H", "home"),
            ],
        )
    )
    assert timed is not None and timed["timed"]
    assert judge("late_goal", timed) == ("landed", "Goal at 90+2'.")
    early = match_result(
        row("FT", 1, 1, goals=[("12", 12, "1H", "home"), ("45+3", 48, "1H", "away")])
    )
    assert judge("late_goal", early) == ("missed", "No goal after 75'.")
    untimed = match_result(row("FT", 2, 1))
    assert judge("late_goal", untimed) == (None, "")


def test_extra_time_counts_for_the_score_not_the_patterns() -> None:
    result = match_result(
        row(
            "PEN",
            1,
            1,
            final=(1, 1),
            pens=(5, 4),
            goals=[("63", 63, "2H", "away"), ("90", 90, "2H", "home")],
        )
    )
    assert result is not None
    assert result["label"] == "Pens" and result["pens"] == [5, 4]
    assert judge("under_2_5", result) == ("landed", "2 goals.")
    assert judge("late_goal", result) == ("landed", "Goal at 90'.")

    aet = match_result(row("AET", 1, 1, final=(1, 2)))
    assert aet is not None and (aet["home"], aet["away"]) == (1, 2)
    assert judge("favourite_away", aet) == ("missed", "Hull drew.")
    unknown = match_result(row("AET", None, None, final=(1, 2)))
    assert judge("btts_yes", unknown) == (None, "")


def page(key: str = "btts_yes", watch: str = "strong") -> dict[str, Any]:
    pattern = {
        "key": key,
        "tag": "Both score",
        "title": "T",
        "detail": "D",
        "brief": "B",
        "score": 0.6,
    }
    return {
        "match_id": "1",
        "kickoff": "2026-11-03T20:00:00+03:00",
        "league": {"id": 3, "name": "Championship", "country": "England", "logo": None},
        "home": {"name": "Norwich", "badge": None, "position": 4},
        "away": {"name": "Hull", "badge": None, "position": 17},
        "odds": {"home": 2.0, "draw": 3.4, "away": 3.6},
        "watch": watch,
        "score": 0.6,
        "points": [pattern],
        "patterns": [pattern],
        "result": None,
    }


def test_settled_page_feeds_the_list_row_and_tally() -> None:
    done = settle_page(page(), match_result(row("FT", 2, 1)))
    assert is_settled(done) and not is_settled(page())
    assert done["points"][0]["outcome"] == "landed"

    other = settle_page(
        {**page("over_2_5", "look"), "match_id": "2"}, match_result(row("FT", 1, 0))
    )
    doc = assemble_day("2026-11-03", [done, other], built_at="x", timezone="+03:00")
    first = doc["matches"][0]
    assert first["result"] == {
        "status": "finished",
        "label": "FT",
        "home": 2,
        "away": 1,
        "pens": None,
    }
    assert first["outcome"] == "landed" and first["tags"][0]["outcome"] == "landed"
    assert doc["summary"]["top"] == {"landed": 1, "settled": 2}
    assert doc["summary"]["strong_tally"] == {"landed": 1, "settled": 1}
    assert doc["summary"]["look_tally"] == {"landed": 0, "settled": 1}
    assert doc["leagues"][0]["match_ids"] == ["1", "2"]


def test_quiet_matches_do_not_count_in_the_tally() -> None:
    quiet = settle_page(page(watch="quiet"), match_result(row("FT", 2, 1)))
    doc = assemble_day("2026-11-03", [quiet], built_at="x", timezone="+03:00")
    assert doc["matches"][0]["outcome"] is None
    assert day_summary(doc["matches"], doc["shortlist"])["top"] == {"landed": 0, "settled": 0}


def test_new_patterns_settle() -> None:
    result = match_result({**row("FT", 3, 1), "cards": 6, "red_card": False})
    assert judge("over_3_5", result) == ("landed", "4 goals.")
    assert judge("team_over_1_5_home", result) == ("landed", "Norwich scored 3.")
    assert judge("team_over_1_5_away", result) == ("missed", "Hull scored 1.")
    assert judge("cards_over_4_5", result) == ("landed", "6 cards.")
    assert judge("red_card", result) == ("missed", "No red card.")
    unknown = match_result(row("FT", 3, 1))
    assert judge("cards_over_4_5", unknown) == (None, "")


def test_list_row_shows_one_chip_per_label() -> None:
    twin = {
        "key": "blanks_home",
        "tag": "Struggles to score",
        "title": "T",
        "detail": "D",
        "brief": "B",
        "score": 0.5,
    }
    other = {**twin, "key": "blanks_away"}
    pg = {**page(), "patterns": [twin, other, {**twin, "key": "btts_no", "tag": "Both score: No"}]}
    doc = assemble_day("2026-11-03", [pg], built_at="x", timezone="+03:00")
    assert [t["label"] for t in doc["matches"][0]["tags"]] == [
        "Struggles to score",
        "Both score: No",
    ]


def test_penalty_and_corner_patterns_settle() -> None:
    result = match_result(
        {
            **row(
                "FT",
                2,
                1,
                goals=[
                    ("12", 12, "1H", "home"),
                    ("55", 55, "2H", "away"),
                    ("80", 80, "2H", "home"),
                ],
            ),
            "corners": 13,
        }
    )
    assert result is not None
    result["goals"][1]["penalty"] = True
    assert judge("penalty_h2h", result) == ("landed", "Penalty scored at 55'.")
    assert judge("corners_over_12_5", result) == ("landed", "13 corners.")
    assert judge("corners_over_13_5", result) == ("missed", "13 corners.")
    no_stats = match_result(row("FT", 2, 1))
    assert judge("corners_over_12_5", no_stats) == (None, "")


def test_lead_side_is_none_for_pages_built_before_sides() -> None:
    old = page("team_over_1_5_away")  # its patterns have no "side"
    doc = assemble_day("2026-11-03", [old], built_at="x", timezone="+03:00")
    assert doc["matches"][0]["lead_side"] is None
    new = {**page(), "patterns": [{**page()["patterns"][0], "side": "away"}]}
    doc = assemble_day("2026-11-03", [new], built_at="x", timezone="+03:00")
    assert doc["matches"][0]["lead_side"] == "away"
