"""Telegram HTML card from outbox rows."""

from __future__ import annotations

from kalchas_bot.format import format_alert_html


def test_unrealised_goals_card() -> None:
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
                "tslg": "12 - —",
                "sot": {"home": 2, "away": 1},
                "sofft": {"home": 4, "away": 2},
                "corners": {"home": 5, "away": 1},
                "attacks": {"home": 40, "away": 28},
                "da": {"home": 18, "away": 9},
                "possession": {"home": 61, "away": 39},
                "yc": {"home": 1, "away": 0},
                "rc": {"home": 0, "away": 0},
                "odds": {"home": 2.1, "draw": 3.2, "away": 3.4},
            },
        }
    )
    assert "<b>UrG</b> · Unrealised goals" in text
    assert "<i>Africa Cup</i>" in text
    assert "<b>Lesotho</b>" not in text
    assert "<b>Morocco</b>" not in text
    assert "Lesotho  0–0  Morocco" in text
    assert "0–0" in text
    assert "64′" in text
    assert "<code>1.4</code>" in text
    assert "SOT: 2–1" in text
    assert "SoffT: 4–2" in text
    assert "D.Atk.: 18–9" in text
    assert "Possession: 61%–39%" in text
    assert "YC: 1–0" in text
    assert "RC:" not in text
    assert "KO 2.10 / 3.20 / 3.40" in text
    assert "TSLG: 12 - —" in text
    assert "rule_of_three" not in text


def test_odds_include_live_1x2() -> None:
    text = format_alert_html(
        {
            "home_team": "Home",
            "away_team": "Away",
            "minute": 40,
            "score": "1-0",
            "strategy_key": "delta_5min",
            "team": "home",
            "value": 3.2,
            "payload": {
                "odds": {
                    "home": 2.1,
                    "draw": 3.2,
                    "away": 3.4,
                    "kickoff": {"home": 2.1, "draw": 3.2, "away": 3.4},
                    "live": {"home": 1.7, "draw": 3.8, "away": 5.1},
                }
            },
        }
    )
    assert "KO 2.10 / 3.20 / 3.40" in text
    assert "Live 1.70 / 3.80 / 5.10" in text


def test_html_escapes_team_names() -> None:
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
    assert "<b>K</b> · K-Score" in text
    assert "TSLG" not in text
    assert "SOT:" not in text


def test_payload_json_string() -> None:
    text = format_alert_html(
        {
            "home_team": "Home",
            "away_team": "Away",
            "minute": 12,
            "score": "2-1",
            "strategy_key": "omega",
            "team": "match",
            "value": 0.5,
            "payload": '{"tslg": "5 - 9"}',
        }
    )
    assert "TSLG: 5 - 9" in text
    assert "match" in text
    assert "<code>18°</code>" in text
    assert "<code>0.5</code>" not in text


def test_omega_prefers_payload_theta() -> None:
    text = format_alert_html(
        {
            "home_team": "Home",
            "away_team": "Away",
            "minute": 20,
            "score": "1-0",
            "strategy_key": "omega",
            "team": "home",
            "value": 0.5,
            "payload": {"theta": 22.0, "k_scale": 0.5},
        }
    )
    assert "<code>22°</code>" in text
    assert "<code>45°</code>" not in text


def test_scanner_outbox_payload_shape() -> None:
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
                "event": "alert",
                "home": "Lesotho",
                "away": "Morocco",
                "league": "Africa Cup",
                "tslg": "12 - —",
                "sot": {"home": 2, "away": 1},
                "sofft": {"home": 4, "away": 2},
                "corners": {"home": 5, "away": 1},
                "attacks": {"home": 40, "away": 28},
                "da": {"home": 18, "away": 9},
                "possession": {"home": 61, "away": 39},
                "yc": {"home": 1, "away": 0},
                "rc": {"home": 0, "away": 0},
                "odds": {"home": 2.1, "draw": 3.2, "away": 3.4},
            },
        }
    )
    assert "SOT: 2–1" in text
    assert "KO 2.10 / 3.20 / 3.40" in text
    assert "Possession: 61%–39%" in text
    assert "<b>Lesotho</b>" not in text
    assert "<b>Morocco</b>" not in text


def test_short_ko_home_is_bold() -> None:
    text = format_alert_html(
        {
            "home_team": "ADR Jicaral",
            "away_team": "Cofutpa",
            "minute": 49,
            "score": "2-0",
            "strategy_key": "delta_5min",
            "team": "home",
            "value": 7.5,
            "payload": {
                "odds": {
                    "kickoff": {"home": 1.29, "draw": 6.0, "away": 11.0},
                    "home": 1.29,
                    "draw": 6.0,
                    "away": 11.0,
                }
            },
        }
    )
    assert "<b>ADR Jicaral</b>  2–0  Cofutpa" in text
    assert "<b>Cofutpa</b>" not in text


def test_short_ko_away_is_bold() -> None:
    text = format_alert_html(
        {
            "home_team": "Home",
            "away_team": "Away",
            "minute": 20,
            "score": "0-1",
            "strategy_key": "delta_5min",
            "team": "away",
            "value": 3.1,
            "payload": {"odds": {"home": 5.5, "draw": 4.0, "away": 1.50}},
        }
    )
    assert "Home  0–1  <b>Away</b>" in text
    assert "<b>Home</b>" not in text
