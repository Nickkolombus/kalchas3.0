"""Telegram HTML caption from outbox rows."""

from __future__ import annotations

from kalchas_bot.format import (
    format_alert_html,
    format_joint_html,
    format_outcome_html,
    joint_window_span,
)


def _delta5_row(**overrides):
    row = {
        "home_team": "Patriotas",
        "away_team": "Boca Juniors",
        "minute": 45,
        "score": "1-2",
        "strategy_key": "delta_5min",
        "team": "home",
        "value": 7.0,
        "payload": {
            "league": "Primera B",
            "status_short": "1H",
            "last_5min": {
                "start": 40,
                "end": 45,
                "sot": {"home": 2, "away": 0},
                "sofft": {"home": 1, "away": 0},
                "da": {"home": 6, "away": 1},
                "corners": {"home": 2, "away": 0},
                "possession": {"home": 58, "away": 42},
            },
            "h2h": {
                "sample": 8,
                "home_avg": 1.3,
                "away_avg": 0.3,
                "home_wins": 5,
                "draws": 1,
                "away_wins": 2,
            },
        },
    }
    row.update(overrides)
    return row


def test_delta_5min_caption():
    text = format_alert_html(_delta5_row())
    assert text.index("<b>Patriotas</b> vs Boca Juniors") < text.index("<b>Δ5′</b>")
    assert "<b>Patriotas</b> vs Boca Juniors · 45′" in text
    assert "<i>Primera B</i>" in text
    assert "<b>Δ5′</b> (5-minute pressure): 7.0 / 12.0 for <b>Patriotas</b>" in text
    assert "[Patriotas]" not in text
    assert "<b>Last 5 mins (40′-45′):</b>" in text
    assert "SOT: <b>2</b> - 0" in text
    assert "SOFFT: <b>1</b> - 0" in text
    assert "DA: <b>6</b> - 1" in text
    assert "Corners: <b>2</b> - 0" in text
    assert "Possession: <b>58%</b> - 42%" in text
    assert "· Patriotas average 1.3 goals per meeting vs Boca Juniors 0.3, last 8." in text
    assert "· 5W-1D-2L for Patriotas." in text
    assert "KO " not in text
    assert "TSLG" not in text
    assert "1-2" not in text


def test_h2h_and_title_use_away_triggerer():
    text = format_alert_html(
        _delta5_row(
            home_team="Sittard",
            away_team="Twente",
            team="away",
            value=9.0,
        )
    )
    assert "Sittard vs <b>Twente</b> · 45′" in text
    assert "<b>Δ5′</b> (5-minute pressure): 9.0 / 12.0 for <b>Twente</b>" in text
    assert "· Twente average 0.3 goals per meeting vs Sittard 1.3, last 8." in text
    assert "· 2W-1D-5L for Twente." in text
    assert "for Sittard" not in text
    assert "for Patriotas" not in text


def test_photo_fallback_includes_score():
    text = format_alert_html(_delta5_row(), with_score=True)
    assert "<b>Patriotas</b> vs Boca Juniors · 1-2 · 45′" in text


def test_skips_zero_zero_rows():
    row = _delta5_row()
    row["payload"]["last_5min"]["corners"] = {"home": 0, "away": 0}
    row["payload"]["last_5min"]["sofft"] = {"home": 0, "away": 0}
    text = format_alert_html(row)
    assert "Corners:" not in text
    assert "SOFFT:" not in text
    assert "SOT:" in text


def test_bolds_the_bigger_number_not_the_firing_side():
    row = _delta5_row()
    row["payload"]["last_5min"]["possession"] = {"home": 40, "away": 60}
    text = format_alert_html(row)
    assert "Possession: 40% - <b>60%</b>" in text
    assert "<b>40%</b>" not in text


def test_equal_numbers_are_not_bold():
    row = _delta5_row()
    row["payload"]["last_5min"]["sot"] = {"home": 1, "away": 1}
    text = format_alert_html(row)
    assert "SOT: 1 - 1" in text
    assert "<b>1</b>" not in text.split("SOT:", 1)[1].split("\n", 1)[0]


def test_skips_h2h_under_five_meetings():
    row = _delta5_row()
    row["payload"]["h2h"] = {"sample": 4, "home_avg": 1.0, "away_avg": 0.5}
    text = format_alert_html(row)
    assert "goals per meeting" not in text


def test_skips_h2h_when_missing():
    row = _delta5_row()
    del row["payload"]["h2h"]
    text = format_alert_html(row)
    assert "goals per meeting" not in text


def test_h2h_goals_line_without_record_if_wins_missing():
    row = _delta5_row()
    row["payload"]["h2h"] = {"sample": 8, "home_avg": 1.3, "away_avg": 0.3}
    text = format_alert_html(row)
    assert "· Patriotas average 1.3 goals per meeting vs Boca Juniors 0.3, last 8." in text
    assert "W-" not in text


def test_html_escapes_team_names():
    text = format_alert_html(
        {
            "home_team": "A <B> & C",
            "away_team": 'D "E"',
            "minute": 1,
            "score": "1-0",
            "strategy_key": "kscore",
            "team": "home",
            "value": 55,
            "payload": None,
        }
    )
    assert "A &lt;B&gt; &amp; C" in text
    assert "D &quot;E&quot;" in text
    assert "<b>K</b> (K-Score): 55 / 100 for <b>A &lt;B&gt; &amp; C</b>" in text
    assert "<b>A &lt;B&gt; &amp; C</b> vs D &quot;E&quot; · 1′" in text


def test_omega_uses_degrees_over_ceiling():
    text = format_alert_html(
        {
            "home_team": "Home",
            "away_team": "Away",
            "minute": 20,
            "score": "1-0",
            "strategy_key": "omega",
            "team": "home",
            "value": 0.5,
            "payload": {"theta": 22.0, "k_scale": 0.5, "league": "Test"},
        }
    )
    assert "<b>Ω</b> (Omega): 22° for <b>Home</b>" in text
    assert "/ 40" not in text
    assert "<b>Home</b> vs Away · 20′" in text


def test_omega_caption_uses_last_10min():
    text = format_alert_html(
        {
            "home_team": "Home",
            "away_team": "Away",
            "minute": 84,
            "score": "1-1",
            "strategy_key": "omega",
            "team": "home",
            "value": 0.5,
            "payload": {
                "league": "Test",
                "theta": 22.0,
                "k_scale": 0.5,
                "sot": {"home": 10, "away": 2},
                "sofft": {"home": 6, "away": 5},
                "da": {"home": 82, "away": 44},
                "corners": {"home": 13, "away": 4},
                "possession": {"home": 57, "away": 43},
                "last_10min": {
                    "start": 74,
                    "end": 84,
                    "sot": {"home": 3, "away": 1},
                    "sofft": {"home": 2, "away": 1},
                    "da": {"home": 12, "away": 4},
                    "corners": {"home": 3, "away": 1},
                    "possession": {"home": 57, "away": 43},
                },
            },
        }
    )
    assert "<b>Ω</b> (Omega): 22° for <b>Home</b>" in text
    assert "<b>Last 10 mins (74′-84′):</b>" in text
    assert "SOT: <b>3</b> - 1" in text
    assert "DA: <b>12</b> - 4" in text
    assert "SOT: <b>10</b>" not in text
    assert "DA: <b>82</b>" not in text


def test_pressure_index_caption_uses_last_10min():
    text = format_alert_html(
        {
            "home_team": "Gimnastica Segoviana",
            "away_team": "Valladolid Promesas",
            "minute": 84,
            "score": "1-1",
            "strategy_key": "pressure_index",
            "team": "home",
            "value": 82,
            "payload": {
                "league": "Segunda División RFEF - Group 5",
                "sot": {"home": 10, "away": 2},
                "sofft": {"home": 6, "away": 5},
                "da": {"home": 82, "away": 44},
                "corners": {"home": 13, "away": 4},
                "possession": {"home": 57, "away": 43},
                "last_10min": {
                    "start": 74,
                    "end": 84,
                    "sot": {"home": 3, "away": 1},
                    "sofft": {"home": 2, "away": 1},
                    "da": {"home": 12, "away": 4},
                    "corners": {"home": 3, "away": 1},
                    "possession": {"home": 57, "away": 43},
                },
            },
        }
    )
    assert "<b>Δ10′</b> (Sustained pressure): 82 / 100 for <b>Gimnastica Segoviana</b>" in text
    assert "<b>Last 10 mins (74′-84′):</b>" in text
    assert "SOT: <b>3</b> - 1" in text
    assert "SOFFT: <b>2</b> - 1" in text
    assert "DA: <b>12</b> - 4" in text
    assert "Corners: <b>3</b> - 1" in text
    assert "SOT: <b>10</b>" not in text
    assert "DA: <b>82</b>" not in text


def test_pressure_index_falls_back_to_match_totals_without_window():
    text = format_alert_html(
        {
            "home_team": "Home",
            "away_team": "Away",
            "minute": 64,
            "score": "0-0",
            "strategy_key": "pressure_index",
            "team": "home",
            "value": 70,
            "payload": {
                "sot": {"home": 10, "away": 2},
                "da": {"home": 82, "away": 44},
            },
        }
    )
    assert "Last 10 mins" not in text
    assert "SOT: <b>10</b> - 2" in text


def test_match_totals_for_other_strategies():
    text = format_alert_html(
        {
            "home_team": "Lesotho",
            "away_team": "Morocco",
            "minute": 64,
            "score": "0-0",
            "strategy_key": "rule_of_three",
            "team": "away",
            "value": 1.4,
            "payload": {
                "league": "Africa Cup",
                "sot": {"home": 2, "away": 1},
                "sofft": {"home": 0, "away": 0},
                "corners": {"home": 5, "away": 1},
                "da": {"home": 18, "away": 9},
                "possession": {"home": 61, "away": 39},
            },
        }
    )
    assert "<b>UrG</b> (Unrealised goals): 1.4 for <b>Morocco</b>" in text
    assert "/ 3" not in text
    assert "Lesotho vs <b>Morocco</b> · 64′" in text
    assert "Last 5 mins" not in text
    assert "SOT: <b>2</b> - 1" in text
    assert "SOFFT:" not in text
    assert "Corners: <b>5</b> - 1" in text


def test_confirmed_outcome_reply():
    text = format_outcome_html(
        {
            "strategy_key": "rule_of_three",
            "team": "home",
            "home_team": "Al Ittihad",
            "away_team": "Shabab Al Ahli Dubai",
            "minute": 67,
            "value": 1.3,
            "state": "Confirmed",
            "payload": {"league": "AFC Champions League Elite - League Phase"},
            "detail": {
                "fire_score": "0-2",
                "settle_score": "1-2",
                "settle_minute": 96,
                "goal_minute": 96,
            },
        }
    )
    assert text == (
        "<b>Al Ittihad</b> vs Shabab Al Ahli Dubai · 67′\n"
        "<i>AFC Champions League Elite - League Phase</i>\n"
        "<b>UrG</b> (Unrealised goals): 1.3 for <b>Al Ittihad</b>\n"
        "\n"
        "⚽ GOAL at 96′ · 0-2 → 1-2"
    )


def test_expired_outcome_reply():
    text = format_outcome_html(
        {
            "strategy_key": "delta_5min",
            "team": "away",
            "home_team": "Home",
            "away_team": "Away",
            "state": "Expired",
            "detail": {
                "fire_score": "0-0",
                "settle_score": "0-0",
                "settle_minute": 74,
                "success_window_minutes": 20,
            },
        }
    )
    assert text == "No goal arrived within 20′\n<b>Δ5′</b> for <b>Away</b>"


def test_expired_infinite_ttl_has_no_window():
    text = format_outcome_html(
        {
            "strategy_key": "rule_of_three",
            "team": "away",
            "home_team": "Home",
            "away_team": "Away",
            "state": "Expired",
            "detail": {"infinite_ttl": True, "success_window_minutes": 999},
        }
    )
    assert text == "No goal arrived\n<b>UrG</b> for <b>Away</b>"


def test_outcome_reply_escapes_team_names():
    text = format_outcome_html(
        {
            "strategy_key": "kscore",
            "team": "home",
            "home_team": "A <B>",
            "away_team": "C",
            "state": "Confirmed",
            "detail": {"goal_minute": 20, "fire_score": "0-0", "settle_score": "1-0"},
        }
    )
    assert "A &lt;B&gt;" in text
    assert "<b>K</b> (K-Score) for <b>A &lt;B&gt;</b>" in text
    assert "⚽ GOAL at 20′ · 0-0 → 1-0" in text


def _window(span_start: int, end: int, sot: tuple[int, int]) -> dict:
    return {
        "start": span_start,
        "end": end,
        "sot": {"home": sot[0], "away": sot[1]},
        "sofft": {"home": 1, "away": 0},
        "da": {"home": 4, "away": 2},
        "corners": {"home": 1, "away": 0},
        "possession": {"home": 49, "away": 51},
    }


def test_joint_omega_and_urg_uses_last_10_minutes():
    text = format_joint_html(
        [
            {
                "id": 2,
                "strategy_slot": 1,
                "strategy_key": "rule_of_three",
                "team": "away",
                "home_team": "Bolivar",
                "away_team": "Mineros",
                "minute": 82,
                "value": 1.3,
                "payload": {
                    "league": "Copa Venezuela",
                    "sot": {"home": 4, "away": 5},
                    "h2h": {
                        "sample": 10,
                        "home_avg": 1.0,
                        "away_avg": 1.7,
                        "home_wins": 3,
                        "draws": 3,
                        "away_wins": 4,
                    },
                },
            },
            {
                "id": 1,
                "strategy_slot": 6,
                "strategy_key": "omega",
                "team": "away",
                "home_team": "Bolivar",
                "away_team": "Mineros",
                "minute": 82,
                "value": 0.7,
                "payload": {
                    "league": "Copa Venezuela",
                    "theta": 36.0,
                    "k_scale": 0.5,
                    "last_10min": _window(72, 82, (0, 1)),
                    "last_5min": _window(77, 82, (0, 1)),
                },
            },
        ]
    )
    assert text.index("<b>UrG</b>") < text.index("<b>Ω</b>")
    assert "Bolivar vs <b>Mineros</b> · 82′" in text
    assert text.count("Copa Venezuela") == 1
    assert "<b>Last 10 mins (72′-82′):</b>" in text
    assert "Last 5 mins" not in text
    assert "SOT: 0 - <b>1</b>" in text
    assert "SOT: <b>4</b>" not in text
    assert text.count("average 1.7 goals") == 1


def test_joint_delta5_and_urg_uses_last_5_minutes():
    assert joint_window_span(["delta_5min", "rule_of_three"]) == 5
    text = format_joint_html(
        [
            {
                "strategy_slot": 4,
                "strategy_key": "delta_5min",
                "team": "home",
                "home_team": "Home",
                "away_team": "Away",
                "minute": 40,
                "value": 8.0,
                "payload": {
                    "last_5min": _window(35, 40, (3, 0)),
                    "last_10min": _window(30, 40, (1, 1)),
                },
            },
            {
                "strategy_slot": 1,
                "strategy_key": "rule_of_three",
                "team": "home",
                "home_team": "Home",
                "away_team": "Away",
                "minute": 40,
                "value": 1.2,
                "payload": {"sot": {"home": 9, "away": 1}},
            },
        ]
    )
    assert "<b>Last 5 mins (35′-40′):</b>" in text
    assert "Last 10 mins" not in text
    assert "SOT: <b>3</b> - 0" in text


def test_joint_with_a_third_strategy_stays_on_10_minutes():
    assert joint_window_span(["delta_5min", "rule_of_three", "omega"]) == 10
