"""Scoring chance: kickoff prices, the clock and the score on one scale."""

from __future__ import annotations

from itertools import pairwise

import pytest
from conftest import timeline_from
from kalchas_core.alert_factors import (
    CHANCE_BUCKETS,
    CSV_COLUMNS,
    csv_row,
    factors_from_payload,
    pattern_summary,
)
from kalchas_core.chance import (
    ALERT_UPLIFT,
    DEFAULT_TOTAL_GOALS,
    MAX_TOTAL_GOALS,
    _result_probabilities,
    chance_for_alert,
    chance_record,
    goal_rates,
    remaining_goal_share,
    score_tilt,
    scoring_chance,
)
from kalchas_core.conditions import condition_catalog
from kalchas_core.match import Side
from kalchas_core.runner import board_snapshot, evaluate_match, kickoff_draw_odds

PRICES = {"home_odds": 1.85, "draw_odds": 3.6, "away_odds": 4.2}


# ---------------------------------------------------------------- goal rates


@pytest.mark.parametrize(
    ("home", "draw", "away"),
    [(1.85, 3.6, 4.2), (2.5, 3.2, 2.5), (1.25, 6.0, 11.0), (5.2, 3.9, 1.62), (3.1, 2.9, 2.6)],
)
def test_goal_rates_reproduce_the_prices_they_came_from(
    home: float, draw: float, away: float
) -> None:
    rates = goal_rates(home, draw, away)
    assert rates is not None
    margin = 1 / home + 1 / draw + 1 / away
    home_win, drawn, away_win = _result_probabilities(*rates)
    assert home_win == pytest.approx((1 / home) / margin, abs=2e-3)
    assert drawn == pytest.approx((1 / draw) / margin, abs=2e-3)
    assert away_win == pytest.approx((1 / away) / margin, abs=2e-3)


def test_favourite_gets_the_higher_rate_and_even_prices_split_evenly() -> None:
    home, away = goal_rates(1.85, 3.6, 4.2)  # type: ignore[misc]
    assert home > away
    level_home, level_away = goal_rates(2.5, 3.2, 2.5)  # type: ignore[misc]
    assert level_home == pytest.approx(level_away, abs=1e-4)


def test_without_a_draw_price_the_total_is_the_default() -> None:
    home, away = goal_rates(1.85, None, 4.2)  # type: ignore[misc]
    assert home + away == pytest.approx(DEFAULT_TOTAL_GOALS)
    assert home > away


def test_a_freak_draw_price_cannot_push_the_total_past_its_bounds() -> None:
    home, away = goal_rates(1.01, 41.0, 41.0)  # type: ignore[misc]
    assert home + away <= MAX_TOTAL_GOALS + 1e-6


@pytest.mark.parametrize(
    ("home", "away"), [(None, 4.2), (1.85, None), (1.0, 4.2), ("x", 4.2), (float("nan"), 2.0)]
)
def test_unusable_prices_give_no_rates(home: object, away: object) -> None:
    assert goal_rates(home, 3.6, away) is None


# --------------------------------------------------------------------- clock


def test_all_of_the_goals_are_ahead_at_kickoff_and_fewer_every_minute() -> None:
    assert remaining_goal_share(0, first_half=True) == pytest.approx(1.0)
    first = [remaining_goal_share(minute, first_half=True) for minute in range(0, 51)]
    second = [remaining_goal_share(minute, first_half=False) for minute in range(45, 101)]
    assert all(later <= earlier for earlier, later in pairwise(first))
    assert all(later <= earlier for earlier, later in pairwise(second))
    # Past first-half stoppage only the second half is left.
    assert first[-1] == pytest.approx(second[0])


def test_stoppage_time_reads_by_the_period_not_the_minute() -> None:
    """45+3 arrives as 48. In the first half there is a whole second half to come."""
    assert remaining_goal_share(48, first_half=True) == pytest.approx(0.575)
    assert remaining_goal_share(48, first_half=False) < 0.56
    # Without the period the minute decides; the two readings are close.
    assert remaining_goal_share(47) == pytest.approx(
        remaining_goal_share(47, first_half=True), abs=0.04
    )


def test_a_live_match_always_has_a_little_time_left() -> None:
    assert remaining_goal_share(90, first_half=False) == pytest.approx(0.0729, abs=1e-4)
    assert 0 < remaining_goal_share(104, first_half=False) < 0.01


def test_score_tilt_favours_the_team_chasing() -> None:
    assert score_tilt(0) == 1.0
    assert score_tilt(-1) > 1.0 > score_tilt(1) > score_tilt(3)


# -------------------------------------------------------------------- chance


def test_known_reading() -> None:
    reading = scoring_chance(
        Side.HOME, minute=67, home_goals=1, away_goals=0, first_half=False, **PRICES
    )
    assert reading is not None
    assert reading.percent == 51
    assert reading.baseline_percent == 38
    assert chance_record(reading) == {"chance": 0.509, "baseline": 0.378}


def test_uplift_only_separates_chance_from_baseline() -> None:
    plain = scoring_chance(
        Side.HOME, minute=67, home_goals=1, away_goals=0, first_half=False, uplift=1.0, **PRICES
    )
    lifted = scoring_chance(
        Side.HOME, minute=67, home_goals=1, away_goals=0, first_half=False, **PRICES
    )
    assert plain is not None and lifted is not None
    assert plain.chance == pytest.approx(plain.baseline)
    assert lifted.baseline == pytest.approx(plain.baseline)
    assert lifted.chance > lifted.baseline
    assert lifted.expected_goals == pytest.approx(plain.expected_goals * ALERT_UPLIFT)


def test_same_team_same_score_is_a_smaller_chance_later() -> None:
    readings = [
        scoring_chance(
            Side.HOME, minute=minute, home_goals=0, away_goals=0, first_half=minute <= 45, **PRICES
        )
        for minute in (20, 40, 60, 75, 85, 92)
    ]
    chances = [reading.chance for reading in readings if reading is not None]
    assert len(chances) == 6
    assert chances == sorted(chances, reverse=True)
    assert chances[0] > 0.8
    assert chances[-1] < 0.15


def test_favourite_and_chasing_team_read_higher() -> None:
    def chance(side: Side, home_goals: int, away_goals: int) -> float:
        reading = scoring_chance(
            side,
            minute=60,
            home_goals=home_goals,
            away_goals=away_goals,
            first_half=False,
            **PRICES,
        )
        assert reading is not None
        return reading.chance

    assert chance(Side.HOME, 0, 0) > chance(Side.AWAY, 0, 0)
    assert chance(Side.HOME, 0, 1) > chance(Side.HOME, 0, 0) > chance(Side.HOME, 1, 0)


def test_no_kickoff_prices_no_chance() -> None:
    assert (
        scoring_chance(
            Side.HOME,
            minute=60,
            home_goals=0,
            away_goals=0,
            home_odds=None,
            draw_odds=None,
            away_odds=None,
        )
        is None
    )
    assert chance_record(None) is None


# ------------------------------------------------------------ alert payloads

OLD_PAYLOAD = {
    "status_short": "1H",
    "odds": {
        "home": 9.9,
        "draw": 9.9,
        "away": 9.9,
        "kickoff": {"home": 1.7, "draw": 3.6, "away": 5.2},
    },
}


def test_alert_without_a_stamp_is_worked_out_from_what_it_stored() -> None:
    reading = chance_for_alert(OLD_PAYLOAD, team="home", minute=38, score="0-0")
    assert reading is not None
    assert reading.percent == 78
    assert reading.baseline_percent == 63
    # Payload's own team / minute / score are used when the caller has none.
    same = chance_for_alert({**OLD_PAYLOAD, "team": "home", "minute": 38, "score": "0–0"})
    assert same is not None and same.percent == 78


def test_stamped_reading_wins_over_recomputing() -> None:
    payload = {**OLD_PAYLOAD, "chance": {"chance": 0.41, "baseline": 0.3}}
    reading = chance_for_alert(payload, team="home", minute=38, score="0-0")
    assert reading is not None
    assert (reading.percent, reading.baseline_percent) == (41, 30)


@pytest.mark.parametrize(
    ("payload", "team", "score"),
    [
        (OLD_PAYLOAD, None, "0-0"),
        (OLD_PAYLOAD, "both", "0-0"),
        (OLD_PAYLOAD, "home", "abc"),
        ({"status_short": "1H"}, "home", "0-0"),
        (None, "home", "0-0"),
    ],
)
def test_alert_with_no_team_score_or_prices_has_no_chance(
    payload: dict | None, team: str | None, score: str
) -> None:
    assert chance_for_alert(payload, team=team, minute=38, score=score) is None


def test_factors_carry_the_chance_and_its_band() -> None:
    factors = factors_from_payload(
        OLD_PAYLOAD, strategy="rule_of_three", team="home", minute=38, score="0-0"
    )
    assert factors["chance"] == 78
    assert factors["chance_baseline"] == 63
    assert factors["chance_bucket"] == "70%+"
    row = csv_row({"factors": factors})
    assert row["chance"] == 78
    assert {"chance", "chance_baseline"} <= set(CSV_COLUMNS)

    none = factors_from_payload({}, strategy="rule_of_three", team="home", minute=38, score="0-0")
    assert none["chance"] is None and none["chance_bucket"] is None


@pytest.mark.parametrize(
    ("percent", "band"),
    [
        (4, "under 30%"),
        (29, "under 30%"),
        (30, "30-39%"),
        (49, "40-49%"),
        (50, "50-59%"),
        (69, "60-69%"),
        (70, "70%+"),
        (96, "70%+"),
    ],
)
def test_chance_bands(percent: int, band: str) -> None:
    payload = {"chance": {"chance": percent / 100, "baseline": 0.1}}
    factors = factors_from_payload(payload, team="home", minute=60, score="0-0")
    assert factors["chance_bucket"] == band
    assert band in CHANCE_BUCKETS


def test_pattern_summary_groups_hit_rate_by_chance_band() -> None:
    def row(percent: int, state: str) -> dict:
        payload = {"chance": {"chance": percent / 100, "baseline": 0.1}}
        factors = factors_from_payload(payload, team="home", minute=60, score="0-0")
        return {"state": state, "factors": factors, "value": 2.0}

    rows = [row(72, "Confirmed"), row(75, "Confirmed"), row(71, "Expired"), row(25, "Expired")]
    groups = {block["title"]: block["rows"] for block in pattern_summary(rows)}
    bands = {line["label"]: line for line in groups["Scoring chance (alerted team)"]}
    assert bands["70%+"]["n"] == 3
    assert bands["70%+"]["confirmed"] == 2
    assert bands["under 30%"]["hit_rate"] == 0.0


# ------------------------------------------------------- runner / conditions


def _gated_delta5_timeline(minute: int):
    """Home Δ5' = 1×2 + 4×0.5 = 4.0 and the corroboration gate passes."""
    return timeline_from(
        {
            minute - 5: {"home": {}, "away": {}},
            minute: {
                "home": {"shots_on_target": 1, "dangerous_attacks": 4},
                "away": {"shots_on_target": 1},
            },
        },
        current_minute=minute,
    )


def _chance_at_least(percent: float) -> dict[int, list]:
    return {
        4: [
            {
                "left_scope": "triggering",
                "left_metric": "chance",
                "operator": ">=",
                "right_kind": "value",
                "right_value": percent,
            }
        ]
    }


def test_chance_is_offered_as_a_condition_metric() -> None:
    metrics = {item["key"]: item["label"] for item in condition_catalog()["metrics"]}
    assert metrics["chance"] == "Chance %"


def test_a_chance_condition_lets_the_early_alert_through_and_blocks_the_late_one() -> None:
    kwargs = dict(
        slots=(4,),
        thresholds={4: 3.0},
        conditions=_chance_at_least(50),
        home_odds=1.85,
        away_odds=4.2,
        draw_odds=3.6,
    )
    early = evaluate_match(_gated_delta5_timeline(20), first_half=True, **kwargs)
    assert [cand.strategy_slot for cand in early] == [4]
    # Same reading at 85': about a 20% chance, so the gate holds it back.
    late = evaluate_match(_gated_delta5_timeline(85), first_half=False, **kwargs)
    assert late == []
    board = board_snapshot(
        _gated_delta5_timeline(85),
        thresholds={4: 3.0},
        conditions=_chance_at_least(50),
        home_odds=1.85,
        away_odds=4.2,
        draw_odds=3.6,
        first_half=False,
    )
    home = board["strategy_status"]["delta_5min"]["teams"]["home"]
    assert home["value"] == 4.0
    assert "triggered" not in home


def test_a_chance_condition_blocks_when_there_are_no_kickoff_prices() -> None:
    blocked = evaluate_match(
        _gated_delta5_timeline(20),
        slots=(4,),
        thresholds={4: 3.0},
        conditions=_chance_at_least(1),
        first_half=True,
    )
    assert blocked == []


def test_kickoff_draw_odds_reads_the_same_block_as_home_and_away() -> None:
    nested = {
        "home": 9.9,
        "draw": 9.9,
        "away": 9.9,
        "kickoff": {"home": 1.9, "draw": 3.4, "away": 4.2},
    }
    assert kickoff_draw_odds(nested) == 3.4
    assert kickoff_draw_odds({"home": 2.1, "draw": 3.2, "away": 3.4}) == 3.2
    assert (
        kickoff_draw_odds({"kickoff": {"home": 1.8}, "home": 2.0, "draw": 3.3, "away": 3.9}) == 3.3
    )
    assert kickoff_draw_odds({"home": 2.1, "away": 3.4}) is None
    assert kickoff_draw_odds(None) is None
