"""Pre-match watchlist: profiles, league norms, patterns and payloads."""

from __future__ import annotations

from typing import Any

from kalchas_core.watchlist import (
    build_match_research,
    build_team_profile,
    league_norms,
    list_row,
    match_patterns,
    shortlist,
    table_slice,
    timing_bucket,
    watch_level,
)
from kalchas_core.watchlist.profile import DEFAULT_NORMS, LeagueNorms

HOME, AWAY = 1, 2


def fixture(
    match_id: str,
    home_id: int,
    away_id: int,
    hs: int,
    as_: int,
    *,
    day: int = 1,
    goals: list[tuple[str, str, str]] | None = None,
    ht: tuple[int, int] | None = None,
    status: str = "FT",
) -> dict[str, Any]:
    """`goals` are (time, side, half) as the provider sends them."""
    events = []
    for time, side, half in goals or []:
        base, _, added = time.partition("+")
        minute = int(base) + (int(added) if added else 0)
        events.append({"minute": minute, "side": side, "team": side, "half": half})
    return {
        "match_id": match_id,
        "match_date": f"2026-10-{day:02d}",
        "status_short": status,
        "home_team_id": home_id,
        "away_team_id": away_id,
        "home_team": f"Team {home_id}",
        "away_team": f"Team {away_id}",
        "home_score": hs,
        "away_score": as_,
        "home_ht_score": ht[0] if ht else None,
        "away_ht_score": ht[1] if ht else None,
        "goal_events": events,
    }


def norms(**overrides: float) -> LeagueNorms:
    return LeagueNorms(games=200, rates={**DEFAULT_NORMS, **overrides}, card_games=200)


def season(team: int, scores: list[tuple[int, int]], *, start: int = 0) -> list[dict[str, Any]]:
    """Games for `team` against fresh opponents, alternating home and away."""
    rows = []
    for i, (gf, ga) in enumerate(scores):
        opp = 100 + start + i
        day = 28 - i
        if i % 2 == 0:
            rows.append(fixture(f"{team}-{i}", team, opp, gf, ga, day=day))
        else:
            rows.append(fixture(f"{team}-{i}", opp, team, ga, gf, day=day))
    return rows


# --------------------------------------------------------------- profiles


def test_stoppage_time_stays_in_its_half() -> None:
    assert timing_bucket({"minute": 48, "half": "1H"}) == 2
    assert timing_bucket({"minute": 94, "half": "2H"}) == 5
    assert timing_bucket({"minute": 46, "half": "2H"}) == 3
    assert timing_bucket({"minute": 105, "half": "ET"}) is None
    assert timing_bucket({"minute": 12}) == 0


def test_profile_counts_goals_by_bucket_from_the_teams_side() -> None:
    rows = [
        fixture(
            "1",
            HOME,
            9,
            2,
            1,
            goals=[("12", "home", "1H"), ("45+3", "away", "1H"), ("90+4", "home", "2H")],
            ht=(1, 1),
        ),
        fixture("2", 9, HOME, 0, 1, goals=[("80", "away", "2H")], ht=(0, 0), day=2),
    ]
    profile = build_team_profile(rows, HOME, name="Home")
    assert profile.n == 2
    newest, older = profile.games
    assert newest.venue == "A" and newest.goals_for == 1
    assert newest.for_by_bucket == (0, 0, 0, 0, 0, 1)
    assert older.for_by_bucket == (1, 0, 0, 0, 0, 1)
    assert older.against_by_bucket == (0, 0, 1, 0, 0, 0)
    assert profile.count("late_goal") == 2
    assert profile.count("first_half_goal") == 1


def test_untimed_scoring_match_is_left_out_of_timing_not_read_as_goalless() -> None:
    rows = [
        fixture("1", HOME, 9, 2, 0, goals=[]),
        fixture("2", HOME, 8, 0, 0, day=2),
    ]
    profile = build_team_profile(rows, HOME)
    assert [g.timed for g in profile.games] == [True, False]
    assert len(profile.timed_games) == 1
    assert profile.games[1].first_half_goal is None


def test_unplayed_rows_are_ignored() -> None:
    rows = [fixture("1", HOME, 9, 0, 0, status="PST"), fixture("2", HOME, 8, 1, 0, day=2)]
    assert build_team_profile(rows, HOME).n == 1


def test_scoring_run_counts_one_venue_newest_first() -> None:
    rows = season(HOME, [(1, 0), (0, 2), (2, 2), (1, 1), (0, 0)])
    profile = build_team_profile(rows, HOME)
    # Home games (even indexes, newest first): 1-0, 2-2, 0-0.
    assert profile.home_scoring_run == 2
    assert profile.away_scoring_run == 0


def test_small_league_uses_general_norms() -> None:
    rows = season(HOME, [(3, 3)] * 10)
    small = league_norms(rows)
    assert small.rate("btts") == DEFAULT_NORMS["btts"]


def test_league_norms_lean_on_the_league_once_it_has_games() -> None:
    rows = season(HOME, [(2, 1)] * 60)
    big = league_norms(rows)
    assert big.games == 60
    assert big.rate("btts") > 0.8


# --------------------------------------------------------------- patterns


def both_score_teams() -> tuple[Any, Any]:
    home = build_team_profile(
        season(HOME, [(2, 1), (1, 1), (2, 2), (3, 1), (1, 2)] * 2), HOME, name="Norwich"
    )
    away = build_team_profile(
        season(AWAY, [(1, 2), (1, 1), (2, 3), (1, 1), (0, 1)] * 2, start=50), AWAY, name="Hull"
    )
    return home, away


def test_both_teams_to_score_is_found_and_leads_when_it_is_the_story() -> None:
    home, away = both_score_teams()
    patterns = match_patterns(home, away, norms(btts=0.5), league="Championship")
    assert patterns[0].key == "btts_yes"
    assert "the Championship average of 50%" in patterns[0].detail
    assert "btts_no" not in {p.key for p in patterns}


def test_h2h_meetings_back_up_btts() -> None:
    home, away = both_score_teams()
    without = match_patterns(home, away, norms(btts=0.5), league="Championship")
    with_h2h = match_patterns(
        home,
        away,
        norms(btts=0.5),
        league="Championship",
        h2h={"sample": 5, "btts": {"count": 5}, "over_2_5": {"count": 3}},
    )
    score = {p.key: p.score for p in without}["btts_yes"]
    top = next(p for p in with_h2h if p.key == "btts_yes")
    assert top.score > score
    assert "all 5 of their last meetings" in top.detail


def test_low_scoring_teams_get_the_opposite_patterns() -> None:
    home = build_team_profile(
        season(HOME, [(1, 0), (0, 0), (0, 1), (1, 0), (0, 0)] * 2), HOME, name="A"
    )
    away = build_team_profile(
        season(AWAY, [(0, 0), (1, 0), (0, 1), (0, 0), (1, 1)] * 2, start=50), AWAY, name="B"
    )
    keys = [p.key for p in match_patterns(home, away, norms(), league="")]
    assert {"under_2_5", "btts_no"} <= set(keys)
    assert "over_2_5" not in keys and "btts_yes" not in keys


def test_too_few_games_says_nothing_rather_than_guessing() -> None:
    home = build_team_profile(season(HOME, [(3, 3)] * 3), HOME, name="A")
    away = build_team_profile(season(AWAY, [(3, 3)] * 10, start=50), AWAY, name="B")
    keys = {p.key for p in match_patterns(home, away, norms(), league="")}
    assert not keys & {"btts_yes", "over_2_5", "late_goal"}


def test_general_norms_are_worded_without_a_league() -> None:
    home, away = both_score_teams()
    top = match_patterns(home, away, norms(btts=0.5), league="")[0]
    assert "a typical 50%" in top.detail


def test_possessive_for_names_ending_in_s() -> None:
    home = build_team_profile(season(HOME, [(2, 1), (1, 1), (2, 2)] * 3), HOME, name="Spartans")
    away = build_team_profile(
        season(AWAY, [(2, 1), (1, 1), (2, 2)] * 3, start=50), AWAY, name="Hull"
    )
    detail = match_patterns(home, away, norms(btts=0.5), league="")[0].detail
    assert "Spartans' " in detail and "Spartans's" not in detail


def test_watch_level_reads_from_pattern_strength() -> None:
    home, away = both_score_teams()
    assert watch_level(match_patterns(home, away, norms(btts=0.5), league="")) == "strong"
    assert watch_level([]) == "quiet"


# ---------------------------------------------------------------- payloads


def test_research_page_and_list_row() -> None:
    home, away = both_score_teams()
    fx = {
        "match_id": "77",
        "league_id": 153,
        "league_name": "Championship",
        "country_name": "England",
        "round": "15",
        "home_badge": "https://x/h.png",
        "away_badge": None,
    }
    table = [
        {
            "position": p,
            "team_id": t,
            "team": f"T{t}",
            "played": 14,
            "goal_difference": 0,
            "points": 30 - p,
        }
        for p, t in [(3, 30), (4, HOME), (5, 31), (16, 32), (17, AWAY), (18, 33)]
    ]
    page = build_match_research(
        fx,
        kickoff="2026-11-03T22:45:00+03:00",
        home=home,
        away=away,
        home_source="competition",
        away_source="competition",
        norms=norms(btts=0.5),
        odds={"home": 1.95, "draw": 3.6, "away": 3.9, "btts_yes": 1.7},
        h2h=None,
        table=table,
        league_record={"confirmed": 38, "settled": 57},
        overall_record={"confirmed": 500, "settled": 860},
    )
    assert page["points"][0]["key"] == "btts_yes"
    assert page["home"]["position"] == 4 and page["away"]["points"] == 13
    assert page["pattern_table"][0]["key"] == "btts"
    assert page["pattern_table"][0]["flagged"] is True
    assert page["pattern_table"][0]["home"] == {"count": 10, "n": 10}
    assert len(page["form"]["home"]["results"]) == 6
    assert page["record"]["league"] == {"confirmed": 38, "settled": 57}
    assert page["h2h"] is None

    row = list_row(page, "153:Championship")
    assert row["headline"] == "Both teams to score looks likely."
    assert row["reason"].startswith("Both teams scored in all 10")
    assert row["odds"] == {"home": 1.95, "draw": 3.6, "away": 3.9}
    assert {"label": "Both score: Yes", "outcome": None} in row["tags"]
    assert row["result"] is None and row["outcome"] is None and row["outcome_note"] == ""


def test_cup_tie_from_all_competitions_uses_general_norms() -> None:
    home, away = both_score_teams()
    fx = {"match_id": "1", "league_name": "Challenge Cup - 1/16-finals"}
    page = build_match_research(
        fx,
        kickoff="",
        home=home,
        away=away,
        home_source="all",
        away_source="competition",
        norms=norms(btts=0.95),
        odds=None,
        h2h=None,
        table=[],
        league_record=None,
        overall_record=None,
    )
    assert page["points"][0]["key"] == "btts_yes"
    assert "a typical" in page["points"][0]["detail"]


def test_table_slice_keeps_rows_around_both_teams() -> None:
    rows = [{"position": p, "team_id": p * 10} for p in range(1, 21)]
    out = table_slice(rows, [40, 170])
    assert [r["position"] for r in out] == [3, 4, 5, 16, 17, 18]


def test_shortlist_skips_quiet_and_caps_each_league() -> None:
    rows = [
        {"match_id": "a", "score": 0.9, "watch": "strong", "league_key": "L1"},
        {"match_id": "b", "score": 0.8, "watch": "strong", "league_key": "L1"},
        {"match_id": "c", "score": 0.7, "watch": "strong", "league_key": "L1"},
        {"match_id": "d", "score": 0.6, "watch": "look", "league_key": "L2"},
        {"match_id": "e", "score": 0.1, "watch": "quiet", "league_key": "L3"},
    ]
    assert shortlist(rows) == ["a", "b", "d"]


# ------------------------------------------------------------ new patterns


def with_cards(rows: list[dict[str, Any]], cards: int, red: bool = False) -> list[dict[str, Any]]:
    return [{**r, "cards": cards, "red_card": red} for r in rows]


def test_big_scoring_teams_bring_over_3_5_and_team_goals() -> None:
    home = build_team_profile(
        season(HOME, [(3, 2), (4, 1), (2, 2), (3, 1), (2, 3)] * 2), HOME, name="A"
    )
    away = build_team_profile(
        season(AWAY, [(1, 3), (2, 2), (0, 4), (1, 3), (2, 3)] * 2, start=50), AWAY, name="B"
    )
    keys = {p.key for p in match_patterns(home, away, norms(), league="")}
    assert {"over_2_5", "over_3_5", "team_over_1_5_home"} <= keys


def test_card_patterns_need_card_data_and_settle_on_it() -> None:
    rows_h = with_cards(season(HOME, [(1, 1)] * 10), 7, red=True)
    rows_a = with_cards(season(AWAY, [(1, 1)] * 10, start=50), 6, red=True)
    home = build_team_profile(rows_h, HOME, name="A")
    away = build_team_profile(rows_a, AWAY, name="B")
    found = {p.key: p for p in match_patterns(home, away, norms(), league="")}
    assert {"cards_over_4_5", "red_card"} <= set(found)
    assert found["cards_over_4_5"].tag == "Over 4.5 cards"

    # Same teams without card data: nothing is said about cards.
    bare_h = build_team_profile(season(HOME, [(1, 1)] * 10), HOME, name="A")
    bare_a = build_team_profile(season(AWAY, [(1, 1)] * 10, start=50), AWAY, name="B")
    keys = {p.key for p in match_patterns(bare_h, bare_a, norms(), league="")}
    assert not keys & {"cards_over_4_5", "red_card"}


def test_league_without_card_data_keeps_card_patterns_quiet() -> None:
    home = build_team_profile(with_cards(season(HOME, [(1, 1)] * 10), 7, True), HOME, name="A")
    away = build_team_profile(
        with_cards(season(AWAY, [(1, 1)] * 10, start=50), 7, True), AWAY, name="B"
    )
    no_cards = LeagueNorms(games=200, rates=dict(DEFAULT_NORMS), card_games=3)
    keys = {p.key for p in match_patterns(home, away, no_cards, league="L")}
    assert not keys & {"cards_over_4_5", "red_card"}


def test_new_wording() -> None:
    home = build_team_profile(
        season(HOME, [(1, 0), (0, 0), (0, 1), (1, 0), (0, 0)] * 2), HOME, name="A"
    )
    away = build_team_profile(
        season(AWAY, [(0, 0), (1, 0), (0, 1), (0, 0), (1, 1)] * 2, start=50), AWAY, name="B"
    )
    found = {p.key: p for p in match_patterns(home, away, norms(), league="")}
    assert found["btts_no"].tag == "Both score: No"
    assert found["btts_no"].title == "Both teams to score looks unlikely."
    assert found["under_2_5"].tag == "Under 2.5"


def test_over_3_5_follows_over_2_5_and_never_outranks_it() -> None:
    home = build_team_profile(
        season(HOME, [(3, 2), (4, 1), (2, 2), (3, 1), (2, 3)] * 2), HOME, name="A"
    )
    away = build_team_profile(
        season(AWAY, [(1, 3), (2, 2), (0, 4), (1, 3), (2, 3)] * 2, start=50), AWAY, name="B"
    )
    found = {p.key: p for p in match_patterns(home, away, norms(), league="")}
    assert found["over_3_5"].score <= found["over_2_5"].score

    low = build_team_profile(season(HOME, [(1, 0), (0, 0), (0, 1)] * 4), HOME, name="C")
    low_away = build_team_profile(
        season(AWAY, [(0, 0), (1, 0), (0, 1)] * 4, start=50), AWAY, name="D"
    )
    assert "over_3_5" not in {p.key for p in match_patterns(low, low_away, norms(), league="")}


def test_watch_score_ignores_a_second_pattern_from_the_same_family() -> None:
    from kalchas_core.watchlist.patterns import Pattern, watch_score

    def p(key: str, score: float) -> Pattern:
        return Pattern(key=key, tag="", title="", detail="", brief="", score=score)

    assert watch_score([p("over_2_5", 0.5), p("over_3_5", 0.45)]) == 0.5
    assert watch_score([p("over_2_5", 0.5), p("over_3_5", 0.45), p("late_goal", 0.2)]) == 0.56


# ------------------------------------------------------- meetings and caps

from kalchas_core.watchlist import cap_levels, day_cap  # noqa: E402
from kalchas_core.watchlist.profile import PlayedGame  # noqa: E402


def meeting(*, corners: int | None = None, penalty: bool | None = False) -> PlayedGame:
    return PlayedGame(
        match_id="m",
        match_date="2026-01-01",
        opponent="B",
        venue="H",
        goals_for=1,
        goals_against=1,
        first_half_goal=True,
        timed=True,
        for_by_bucket=(0,) * 6,
        against_by_bucket=(0,) * 6,
        corners=corners,
        penalty_goal=penalty,
    )


def quiet_teams() -> tuple[Any, Any]:
    return (
        build_team_profile(
            season(HOME, [(1, 1), (1, 0), (0, 1), (2, 1), (1, 1)] * 2), HOME, name="A"
        ),
        build_team_profile(
            season(AWAY, [(1, 1), (0, 1), (1, 0), (1, 2), (1, 1)] * 2, start=50), AWAY, name="B"
        ),
    )


def test_penalties_need_a_habit_across_the_meetings() -> None:
    home, away = quiet_teams()
    habit = [meeting(penalty=True)] * 4 + [meeting()] * 6
    found = {p.key: p for p in match_patterns(home, away, norms(), league="", meetings=habit)}
    assert "penalty_h2h" in found
    assert "4 of 10" in found["penalty_h2h"].detail
    rare = [meeting(penalty=True)] * 2 + [meeting()] * 8
    assert "penalty_h2h" not in {
        p.key for p in match_patterns(home, away, norms(), league="", meetings=rare)
    }


def test_corners_take_the_highest_line_most_meetings_cleared() -> None:
    home, away = quiet_teams()
    meets = [meeting(corners=c) for c in (14, 13, 15, 13, 9, 13, 8, 16, 13, 10)]
    league = LeagueNorms(
        games=200, rates=dict(DEFAULT_NORMS), card_games=200, corner_totals=(9,) * 70 + (13,) * 30
    )
    keys = {p.key for p in match_patterns(home, away, league, league="L", meetings=meets)}
    assert "corners_over_12_5" in keys
    ordinary = [meeting(corners=c) for c in (8, 9, 10, 7, 9, 8)]
    keys = {p.key for p in match_patterns(home, away, league, league="L", meetings=ordinary)}
    assert not any(k.startswith("corners_over") for k in keys)


def test_day_cap_is_bigger_at_the_weekend() -> None:
    assert day_cap("2026-11-06") == 20  # Friday
    assert day_cap("2026-11-08") == 20  # Sunday
    assert day_cap("2026-11-03") == 10  # Tuesday


def test_cap_keeps_started_matches_and_demotes_the_rest_by_score() -> None:
    pages = [{"match_id": str(i), "score": 0.9 - i * 0.01, "watch": "strong"} for i in range(14)]
    pages.append({"match_id": "late", "score": 0.95, "watch": "strong"})
    changed = {
        p["match_id"]: p["watch"] for p in cap_levels(pages, day="2026-11-03", keep={"0", "1"})
    }
    # 0 and 1 kept and counted; "late" (best score) and 2-9 take the other 8 places.
    assert "late" not in changed and "0" not in changed
    assert all(k not in changed for k in ("2", "8"))
    assert changed["9"] == "look" and changed["13"] == "look"


def test_meeting_patterns_never_lead_or_make_a_match_alone() -> None:
    home, away = quiet_teams()
    habit = [meeting(penalty=True)] * 6 + [meeting()] * 4
    found = match_patterns(home, away, norms(), league="", meetings=habit)
    pen = next(p for p in found if p.key == "penalty_h2h")
    others = [p for p in found if p.key != "penalty_h2h"]
    assert found[0].key != "penalty_h2h"
    if others:
        assert pen.score < others[0].score
    alone = match_patterns(
        build_team_profile(season(HOME, [(1, 1)] * 3), HOME),
        build_team_profile(season(AWAY, [(1, 1)] * 3, start=50), AWAY),
        norms(),
        league="",
        meetings=habit,
    )
    assert watch_level(alone) == "quiet"
