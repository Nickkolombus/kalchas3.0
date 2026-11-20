"""Admin Results: each alert's Over bet, graded or as stamped at fire."""

from __future__ import annotations

from kalchas_api.admin import _over_csv, _over_item

STAMPED = {
    "primary": "ft_o15",
    "bets": {
        "ft_o15": {"period": "ft", "line": 1.5, "label": "Over 1.5 FT", "price": 2.4},
        "ht_o05": {"period": "h1", "line": 0.5, "label": "Over 0.5 HT", "price": 3.1},
    },
}


def test_graded_row_wins_over_the_stamped_bet() -> None:
    graded = {
        "ft_o15": {**STAMPED["bets"]["ft_o15"], "won": True},
        "ht_o05": {**STAMPED["bets"]["ht_o05"], "won": False},
    }
    item = _over_item({"over_bets": graded, "over_primary": "ft_o15"}, {"over_bet": STAMPED})
    assert item is not None
    assert item["graded"] is True
    assert item["label"] == "Over 1.5 FT" and item["won"] is True
    assert abs(item["return"] - 1.4) < 1e-9
    assert item["bets"]["ht_o05"]["return"] == -1.0
    assert item["bets"]["ht_o05"]["name"] == "HT Over +0.5"
    csv = _over_csv(item)
    assert csv["over_bet"] == "Over 1.5 FT" and csv["over_won"] == "1"
    assert csv["ht_o05_won"] == "0" and csv["ft_o15_price"] == 2.4


def test_open_alert_shows_the_stamped_bet_and_none_shows_nothing() -> None:
    item = _over_item({}, {"over_bet": STAMPED})
    assert item is not None
    assert item["graded"] is False and item["won"] is None and item["return"] is None
    assert _over_item({}, {}) is None
    assert _over_csv(None) == {}
