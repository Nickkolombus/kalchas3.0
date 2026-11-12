"""The scanner stamps each alert with the alerted team's scoring chance."""

from __future__ import annotations

from typing import Any

from kalchas_core.match import Side
from kalchas_core.runner import AlertCandidate
from kalchas_football import LiveMatch
from kalchas_scanner.loop import Scanner
from kalchas_scanner.outbox import MemoryAlertSink
from kalchas_scanner.persist import MemoryMatchPersist


class _Client:
    def get_fixture_statistics(self, match_id: str):
        raise AssertionError("embedded stats present; get_statistics must not be called")

    def get_fixture_events(self, match_id: str):
        return {}

    def get_live_fixtures(self):
        return []


def _match(minute: int, status_short: str) -> LiveMatch:
    raw = {
        "match_id": "8",
        "match_hometeam_name": "A",
        "match_awayteam_name": "B",
        "statistics": [
            {"type": "Attacks", "home": "40", "away": "30"},
            {"type": "Dangerous Attacks", "home": "18", "away": "9"},
            {"type": "On Target", "home": "3", "away": "1"},
            {"type": "Off Target", "home": "4", "away": "2"},
            {"type": "Corners", "home": "5", "away": "1"},
            {"type": "Ball Possession", "home": "61%", "away": "39%"},
        ],
    }
    return LiveMatch(
        match_id="8",
        home_team="A",
        away_team="B",
        home_team_id=1,
        away_team_id=2,
        minute=minute,
        home_score=0,
        away_score=0,
        status_short=status_short,
        league_name="L",
        raw=raw,
    )


def _fire(monkeypatch, *, odds: dict | None, minute: int = 30, status_short: str = "1H") -> dict:
    seen: dict[str, Any] = {}

    def fake_evaluate(*args: Any, **kwargs: Any) -> list[AlertCandidate]:
        seen.update(kwargs)
        return [AlertCandidate(4, "delta_5min", Side.HOME, 5.5, {})]

    monkeypatch.setattr("kalchas_scanner.loop.evaluate_match", fake_evaluate)
    scanner = Scanner(
        client=_Client(),  # type: ignore[arg-type]
        sink=MemoryAlertSink(),
        persist=MemoryMatchPersist(),
    )
    if odds is not None:
        scanner._odds_by_match["8"] = odds
    emitted = scanner.process_match(_match(minute, status_short))
    assert len(emitted) == 1
    return {"payload": emitted[0], "kwargs": seen}


def test_alert_carries_the_alerted_teams_chance(monkeypatch) -> None:
    fired = _fire(monkeypatch, odds={"home": 2.1, "draw": 3.2, "away": 3.4})
    assert fired["payload"]["chance"] == {"chance": 0.755, "baseline": 0.608}
    # The runner gets what it needs to gate on the same number.
    assert fired["kwargs"]["draw_odds"] == 3.2
    assert fired["kwargs"]["first_half"] is True


def test_first_half_stoppage_is_not_read_as_the_second_half(monkeypatch) -> None:
    first = _fire(monkeypatch, odds={"home": 2.1, "draw": 3.2, "away": 3.4}, minute=47)
    second = _fire(
        monkeypatch,
        odds={"home": 2.1, "draw": 3.2, "away": 3.4},
        minute=47,
        status_short="2H",
    )
    assert first["kwargs"]["first_half"] is True
    assert second["kwargs"]["first_half"] is False
    assert first["payload"]["chance"]["chance"] > second["payload"]["chance"]["chance"]


def test_no_kickoff_odds_means_no_chance_on_the_alert(monkeypatch) -> None:
    fired = _fire(monkeypatch, odds=None)
    assert "chance" not in fired["payload"]
