"""Team form metrics and insight strings (Strategy 9 enrichment)."""

from __future__ import annotations

from kalchas_core.form import (
    FinishedFixture,
    build_form_insights,
    calculate_team_form,
    comparative_insights,
    goal_form_insights,
    prioritize_insights,
    streak_insights,
)


def fx(
    home_id: int,
    away_id: int,
    hs: int,
    aws: int,
    *,
    date: str = "2026-01-01",
) -> FinishedFixture:
    return FinishedFixture(home_id, away_id, hs, aws, match_date=date)


class TestCalculateTeamForm:
    def test_empty(self) -> None:
        form = calculate_team_form([], team_id=1)
        assert form.games_played == 0
        assert form.form_string == "No recent data"

    def test_window_of_wins(self) -> None:
        fixtures = [fx(1, 2, 2, 0), fx(3, 1, 0, 1), fx(1, 4, 3, 1), fx(5, 1, 1, 2)]
        form = calculate_team_form(fixtures, team_id=1, window=4)
        assert form.wins == 4
        assert form.losses == 0
        assert form.results_last5 == ("W", "W", "W", "W")
        assert form.current_streak.type == "W"
        assert form.current_streak.count == 4
        assert form.goals_per_game == 2.0

    def test_streak_stops_at_the_first_break(self) -> None:
        """Current streak is the unbroken run from the most recent match.

        Sequence newest-first W, D, W → type=W and count=1 (not 2).
        """
        fixtures = [fx(1, 2, 1, 0), fx(1, 2, 0, 0), fx(1, 2, 2, 0)]
        form = calculate_team_form(fixtures, team_id=1, window=3)
        assert form.current_streak.type == "W"
        assert form.current_streak.count == 1
        assert form.draws == 1

    def test_unbroken_streak_still_counts_through(self) -> None:
        fixtures = [fx(1, 2, 1, 0), fx(1, 2, 2, 0), fx(1, 2, 3, 1)]
        form = calculate_team_form(fixtures, team_id=1, window=3)
        assert form.current_streak.type == "W"
        assert form.current_streak.count == 3

    def test_accepts_legacy_dict_keys(self) -> None:
        raw = [
            {
                "match_hometeam_id": 10,
                "match_awayteam_id": 20,
                "match_hometeam_score": 0,
                "match_awayteam_score": 2,
            }
        ]
        form = calculate_team_form(raw, team_id=20, window=5)
        assert form.wins == 1
        assert form.home_record.games == 0
        assert form.away_record.games == 1


class TestInsights:
    def test_winning_streak(self) -> None:
        fixtures = [fx(1, 2, 1, 0) for _ in range(4)]
        form = calculate_team_form(fixtures, team_id=1)
        assert streak_insights("Alpha", form) == ["Alpha on 4-game winning streak"]

    def test_high_scoring(self) -> None:
        fixtures = [fx(1, 2, 3, 0), fx(1, 2, 2, 1), fx(1, 2, 2, 0)]
        form = calculate_team_form(fixtures, team_id=1)
        lines = goal_form_insights("Alpha", form)
        assert any("averaging" in line for line in lines)

    def test_comparative_form_gap(self) -> None:
        strong = calculate_team_form([fx(1, 2, 2, 0) for _ in range(5)], team_id=1)
        weak = calculate_team_form([fx(3, 4, 0, 2) for _ in range(5)], team_id=3)
        lines = comparative_insights("Home", "Away", strong, weak)
        assert any("much better recent form" in line for line in lines)

    def test_prioritize_caps_at_three(self) -> None:
        many = [
            "Alpha on 5-game winning streak",
            "Beta averaging 2.5 goals in recent form",
            "Table clash: 1th vs 10th place",
            "Gamma conceding 2.0 goals per game recently",
            "Delta: +8 goal difference in recent games",
        ]
        top = prioritize_insights(many, limit=3)
        assert len(top) == 3
        assert "winning streak" in top[0]

    def test_build_pipeline(self) -> None:
        home = calculate_team_form([fx(1, 2, 3, 0) for _ in range(5)], team_id=1)
        away = calculate_team_form([fx(3, 4, 0, 2) for _ in range(5)], team_id=3)
        lines = build_form_insights("Home", "Away", home, away)
        assert 1 <= len(lines) <= 3


class TestPositionInsights:
    def test_table_clash_when_gap_is_large(self) -> None:
        from kalchas_core.form import position_insights

        standings = [
            {"team_id": 1, "position": 2},
            {"team_id": 2, "position": 14},
        ]
        lines = position_insights(standings, 1, 2, "Home", "Away")
        assert lines == ["Table clash: 2th vs 14th place"]

    def test_top_table_clash(self) -> None:
        from kalchas_core.form import position_insights

        standings = [
            {"team": {"id": 1}, "position": 1},
            {"team": {"id": 2}, "position": 3},
        ]
        lines = position_insights(standings, 1, 2, "Home", "Away")
        assert lines == ["Top-table clash: 1nd vs 3rd place"]

    def test_missing_team_returns_empty(self) -> None:
        from kalchas_core.form import position_insights

        assert position_insights([{"team_id": 1, "position": 1}], 1, 99, "H", "A") == []


class TestFormBarHelpers:
    """The pieces the scanner and API share to feed Form Bar's prior."""

    def _row(self, status_short: str, hs: int | None, aws: int | None) -> dict:
        return {
            "match_id": "1",
            "status_short": status_short,
            "match_status": "whatever the provider said",
            "home_team_id": 1,
            "away_team_id": 2,
            "home_score": hs,
            "away_score": aws,
        }

    def test_only_played_fixtures_with_both_scores_survive(self) -> None:
        from kalchas_core.form import played_fixtures

        rows = [
            self._row("FT", 2, 1),
            self._row("AET", 1, 1),
            self._row("PEN", 0, 0),
            self._row("PST", None, None),
            self._row("CANC", 0, 0),
            self._row("AWD", 3, 0),
            self._row("FT", 2, None),
            self._row("", None, None),
        ]
        kept = played_fixtures(rows)
        assert [(f.home_score, f.away_score) for f in kept] == [(2, 1), (1, 1), (0, 0)]

    def test_per_game_goals_and_medians(self) -> None:
        # Team 1: home 1-0, home 3-0, away 0-0, away 1-2 (scored 1 as away side).
        fixtures = [fx(1, 2, 1, 0), fx(1, 3, 3, 0), fx(4, 1, 0, 0), fx(5, 1, 2, 1)]
        form = calculate_team_form(fixtures, team_id=1, window=10)
        assert form.scored_by_game == (1, 3, 0, 1)
        assert form.conceded_by_game == (0, 0, 0, 2)
        assert form.median_scored == 1.0
        assert form.median_conceded == 0.0

    def test_cache_payload_round_trips(self) -> None:
        from kalchas_core.form import form_cache_payload, form_from_cache_payload

        form = calculate_team_form([fx(1, 2, 1, 0), fx(1, 3, 3, 0), fx(4, 1, 0, 2)], team_id=1)
        payload = form_cache_payload(form)
        assert payload == {"scored": [1, 3, 2], "conceded": [0, 0, 0]}
        back = form_from_cache_payload(payload)
        assert back is not None
        assert back.games_played == 3
        assert back.median_scored == form.median_scored
        assert back.median_conceded == form.median_conceded

    def test_unreadable_or_legacy_cache_payloads_are_a_miss(self) -> None:
        from kalchas_core.form import form_from_cache_payload

        assert form_from_cache_payload(None) is None
        assert form_from_cache_payload({"games_played": 10, "goals_for": 14}) is None  # v2
        assert form_from_cache_payload({"scored": [1, 2], "conceded": [1]}) is None
        assert form_from_cache_payload({"scored": ["x"], "conceded": [1]}) is None
        assert form_from_cache_payload({"scored": [], "conceded": []}).games_played == 0
