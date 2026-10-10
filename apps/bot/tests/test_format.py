"""Telegram HTML caption from outbox rows."""

from __future__ import annotations

from kalchas_bot.format import format_alert_html


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
    assert (
        "· Patriotas average 1.3 goals per meeting vs Boca Juniors 0.3, last 8." in text
    )
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
