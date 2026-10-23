"""Form Bar (Strategy 3, key ``delta_goal``): goals scored vs goals expected by now."""

from __future__ import annotations

import pytest
from kalchas_core.form import TeamForm
from kalchas_core.match import Side
from kalchas_core.strategies.delta_goal import (
    DEFAULT_ALERT_THRESHOLD,
    DELIVERED_LABEL,
    FORM_BAR_MIN_GAMES,
    evaluate,
    expected_goals,
)


def form(scored: list[int], conceded: list[int] | None = None) -> TeamForm:
    """A form with these per-game goals (newest first)."""
    against = conceded if conceded is not None else [1] * len(scored)
    return TeamForm(
        games_played=len(scored),
        goals_for=sum(scored),
        goals_against=sum(against),
        scored_by_game=tuple(scored),
        conceded_by_game=tuple(against),
    )


# Median scored 2, median conceded 1.
STRONG = form([2, 2, 3, 1, 2, 0, 2, 4, 2, 1], [1, 0, 1, 2, 1, 1, 0, 1, 2, 1])
# Median scored 1, median conceded 2.
LEAKY = form([1, 0, 1, 2, 1, 1, 0, 1, 2, 1], [2, 2, 3, 1, 2, 0, 2, 4, 2, 1])
SHORT = form([3, 3, 3, 3])
assert SHORT.games_played < FORM_BAR_MIN_GAMES, "fixture must sit below the floor"


class TestExpectedGoals:
    def test_averages_own_attack_and_opponent_defence(self) -> None:
        # STRONG scores a median 2; LEAKY concedes a median 2.
        assert expected_goals(STRONG, LEAKY) == (2.0, True)
        # LEAKY scores a median 1; STRONG concedes a median 1.
        assert expected_goals(LEAKY, STRONG) == (1.0, True)

    def test_uses_the_median_so_one_rout_does_not_drag_it(self) -> None:
        rout = form([6, 1, 1, 0, 1, 1, 2, 1, 0, 1])
        assert rout.goals_for / rout.games_played == 1.4  # the mean would say 1.4
        assert expected_goals(rout, None) == (1.0, False)

    def test_falls_back_to_own_attack_when_the_opponent_is_short(self) -> None:
        assert expected_goals(STRONG, SHORT) == (2.0, False)
        assert expected_goals(STRONG, None) == (2.0, False)

    def test_no_reading_when_the_team_itself_is_short(self) -> None:
        assert expected_goals(SHORT, STRONG) == (None, False)
        assert expected_goals(None, STRONG) == (None, False)

    def test_five_games_is_enough(self) -> None:
        assert expected_goals(form([1, 2, 1, 2, 1]), None) == (1.0, False)


class TestPace:
    def test_expected_by_now_spreads_evenly_over_ninety_minutes(self) -> None:
        home = evaluate(45, home_recent_form=STRONG, away_recent_form=LEAKY).home
        assert home.expected_goals == 2.0
        assert home.expected_by_now == pytest.approx(1.0)

    def test_stoppage_and_extra_time_count_as_minute_ninety(self) -> None:
        home = evaluate(97, home_recent_form=STRONG, away_recent_form=LEAKY).home
        assert home.expected_by_now == pytest.approx(2.0)

    def test_gap_is_positive_when_behind_and_negative_when_ahead(self) -> None:
        behind = evaluate(60, home_score=0, home_recent_form=STRONG, away_recent_form=LEAKY)
        ahead = evaluate(60, home_score=2, home_recent_form=STRONG, away_recent_form=LEAKY)
        assert behind.home.gap == pytest.approx(1.33, abs=0.01)
        assert ahead.home.gap == pytest.approx(-0.67, abs=0.01)

    def test_no_form_is_no_reading_not_zero(self) -> None:
        result = evaluate(60, home_recent_form=SHORT, away_recent_form=None)
        assert not result.home.has_form
        assert result.home.gap is None
        assert not result.home.qualifies
        assert result.away.gap is None


class TestDelivered:
    def test_scoring_the_full_expectation_is_delivered(self) -> None:
        home = evaluate(30, home_score=2, home_recent_form=STRONG, away_recent_form=LEAKY).home
        assert home.delivered
        assert not home.qualifies

    def test_one_short_of_the_expectation_is_not(self) -> None:
        home = evaluate(30, home_score=1, home_recent_form=STRONG, away_recent_form=LEAKY).home
        assert not home.delivered

    def test_zero_expected_and_zero_scored_is_not_delivered(self) -> None:
        blank = form([0, 0, 0, 1, 0], [0, 0, 1, 0, 0])
        home = evaluate(80, home_score=0, home_recent_form=blank, away_recent_form=blank).home
        assert home.expected_goals == 0.0
        assert not home.delivered
        assert home.gap == 0.0


class TestAlerting:
    def test_fires_at_one_goal_behind_by_default(self) -> None:
        assert DEFAULT_ALERT_THRESHOLD == 1.0
        # Expected 2.0 for the match: 1.0 by 45', so 0 scored is exactly one behind.
        at_45 = evaluate(45, home_recent_form=STRONG, away_recent_form=LEAKY)
        at_40 = evaluate(40, home_recent_form=STRONG, away_recent_form=LEAKY)
        assert at_45.triggering_team is Side.HOME
        assert at_45.trigger_value == pytest.approx(1.0)
        assert at_40.triggering_team is None
        assert at_40.trigger_value == 0.0

    def test_threshold_is_respected(self) -> None:
        result = evaluate(60, home_recent_form=STRONG, away_recent_form=LEAKY, threshold=1.5)
        assert result.home.gap == pytest.approx(1.33, abs=0.01)
        assert result.triggering_team is None

    def test_the_team_furthest_behind_triggers(self) -> None:
        # Home expects 2.0, away 1.0; at 90' with 0-0, home is 2 behind, away 1.
        result = evaluate(90, home_recent_form=STRONG, away_recent_form=LEAKY)
        assert result.home.qualifies and result.away.qualifies
        assert result.triggering_team is Side.HOME

    def test_ties_go_to_home(self) -> None:
        result = evaluate(90, home_recent_form=STRONG, away_recent_form=STRONG)
        assert result.home.gap == result.away.gap
        assert result.triggering_team is Side.HOME


class TestReadings:
    def test_note_while_behind(self) -> None:
        home = evaluate(60, home_score=0, home_recent_form=STRONG, away_recent_form=LEAKY).home
        assert home.note(60) == "0 of 2 expected · 1.3 by 60′"

    def test_note_once_delivered(self) -> None:
        home = evaluate(70, home_score=2, home_recent_form=STRONG, away_recent_form=LEAKY).home
        assert home.note(70) == f"{DELIVERED_LABEL} · 2 of 2 expected"

    def test_note_with_quarter_goal_expectation(self) -> None:
        odd = form([1, 2, 1, 2, 1, 2], [1, 1, 1, 1, 1, 1])  # median scored 1.5
        home = evaluate(90, home_recent_form=odd, away_recent_form=odd).home
        assert home.expected_goals == 1.25
        assert home.note(90) == "0 of 1.25 expected · 1.2 by 90′"

    def test_note_while_ahead(self) -> None:
        # Expects 2.0; one goal by 30' is 1 against 0.67 expected by now.
        home = evaluate(30, home_score=1, home_recent_form=STRONG, away_recent_form=LEAKY).home
        assert home.gap == -0.33
        assert not home.delivered
        assert home.note(30) == "1 of 2 expected · 0.7 by 30′ · 0.3 ahead"

    def test_note_without_form(self) -> None:
        assert evaluate(60).home.note(60) == "Not enough recent games"

    def test_detail_carries_the_reading_for_telegram(self) -> None:
        home = evaluate(60, home_recent_form=STRONG, away_recent_form=LEAKY).home
        detail = home.detail(60)
        assert detail["scored"] == 0
        assert detail["expected_goals"] == 2.0
        assert detail["expected_by_now"] == pytest.approx(1.33, abs=0.01)
        assert detail["opponent_used"] is True
        assert detail["note"] == home.note(60)
