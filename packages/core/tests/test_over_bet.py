"""The Over bet each alert stands for, and its grading."""

from __future__ import annotations

from kalchas_core.over_bet import (
    FT_O05,
    FT_O15,
    HT_O05,
    bet_return,
    grade_over_bets,
    over_bets_for_alert,
    primary_bet,
)

ODDS = {
    "ft": {
        "1.5": {"over": 1.7, "under": 2.1},
        "2.5": {"over": 3.4, "under": 1.3},
    },
    "h1": {"1.5": {"over": 4.5, "under": 1.18}},
}


def test_second_half_alert_is_ft_over_goals_plus_half() -> None:
    bet = over_bets_for_alert(score="1-0", first_half=False, goal_odds=ODDS)
    assert bet == {
        "primary": FT_O05,
        "bets": {FT_O05: {"period": "ft", "line": 1.5, "label": "Over 1.5 FT", "price": 1.7}},
    }


def test_first_half_alert_tracks_both_bets_and_shows_the_admin_choice() -> None:
    bet = over_bets_for_alert(score="1-0", first_half=True, goal_odds=ODDS)
    assert bet is not None
    assert bet["primary"] == FT_O15
    assert bet["bets"][FT_O15] == {
        "period": "ft",
        "line": 2.5,
        "label": "Over 2.5 FT",
        "price": 3.4,
    }
    assert bet["bets"][HT_O05] == {
        "period": "h1",
        "line": 1.5,
        "label": "Over 1.5 HT",
        "price": 4.5,
    }
    switched = over_bets_for_alert(
        score="1-0", first_half=True, goal_odds=ODDS, first_half_mode="ht_o05"
    )
    chosen = primary_bet(switched)
    assert chosen is not None and chosen["label"] == "Over 1.5 HT"
    # An unknown mode falls back to the default.
    odd = over_bets_for_alert(score="0-0", first_half=True, goal_odds=None, first_half_mode="x")
    assert odd is not None and odd["primary"] == FT_O15


def test_missing_line_or_bad_score() -> None:
    bet = over_bets_for_alert(score="3-2", first_half=False, goal_odds=ODDS)
    assert bet is not None
    assert bet["bets"][FT_O05]["price"] is None
    assert bet["bets"][FT_O05]["line"] == 5.5
    assert over_bets_for_alert(score="?", first_half=False, goal_odds=ODDS) is None


def test_grading_uses_half_time_and_ninety_minute_totals() -> None:
    bet = over_bets_for_alert(score="1-0", first_half=True, goal_odds=ODDS)
    graded = grade_over_bets(bet, ht_total=1, ft_total=3)
    assert graded is not None
    assert graded["bets"][FT_O15]["won"] is True  # 3 > 2.5
    assert graded["bets"][HT_O05]["won"] is False  # 1 not > 1.5
    unknown_ht = grade_over_bets(bet, ht_total=None, ft_total=2)
    assert unknown_ht is not None
    assert unknown_ht["bets"][HT_O05]["won"] is None
    assert unknown_ht["bets"][FT_O15]["won"] is False


def test_bet_return() -> None:
    assert abs((bet_return(1.7, True) or 0) - 0.7) < 1e-9
    assert bet_return(1.7, False) == -1.0
    assert bet_return(None, True) is None
    assert bet_return(1.7, None) is None
