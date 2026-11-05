"""Browser goal alerts: spotting goals from score marks and sending to followers."""

from __future__ import annotations

from typing import Any

import pytest
from kalchas_bot import push_goals
from kalchas_bot.push_goals import Goal, detect_goals, goal_message


def _row(**kw: Any) -> dict[str, Any]:
    base = {
        "match_id": "100",
        "home_team": "PSV",
        "away_team": "Club Brugge",
        "home_score": 0,
        "away_score": 0,
        "minute": 10,
        "minute_display": None,
        "status_short": "1H",
        "mark_home": 0,
        "mark_away": 0,
    }
    base.update(kw)
    return base


def test_first_sighting_only_marks() -> None:
    goals, marks = detect_goals([_row(home_score=2, mark_home=None, mark_away=None)])
    assert goals == []
    assert marks == [{"match_id": "100", "home_score": 2, "away_score": 0}]


def test_unchanged_score_writes_nothing() -> None:
    assert detect_goals([_row()]) == ([], [])


def test_goal_for_each_side_that_went_up() -> None:
    goals, marks = detect_goals([_row(home_score=1, away_score=1, minute=54)])
    assert [g.side for g in goals] == ["home", "away"]
    assert goals[0].minute == "54'"
    assert marks == [{"match_id": "100", "home_score": 1, "away_score": 1}]


def test_goal_taken_back_is_quiet() -> None:
    goals, marks = detect_goals([_row(home_score=0, mark_home=1)])
    assert goals == []
    assert marks == [{"match_id": "100", "home_score": 0, "away_score": 0}]


def test_message_uses_stoppage_display_and_scorer() -> None:
    goal = Goal("100", "away", "PSV", "Club Brugge", 1, 2, "90+3'")
    msg = goal_message(goal, {"player_name": "H. Vetlesen", "minute": 90})
    assert msg["title"] == "⚽ Goal for Club Brugge"
    assert msg["body"] == "PSV 1–2 Club Brugge · H. Vetlesen 90+3'"
    assert msg["tag"] == "goal-100"
    assert msg["url"] == "/?match=100"


def test_minute_display_without_apostrophe_gets_one() -> None:
    goals, _ = detect_goals([_row(away_score=1, minute=47, minute_display="45+2")])
    assert goals[0].minute == "45+2'"


class _Store:
    def __init__(self, rows: list[dict[str, Any]], subs: list[dict[str, Any]]) -> None:
        self.rows = rows
        self.subs = subs
        self.marks: list[dict[str, Any]] = []
        self.results: dict[str, list[int]] = {}

    def live_scores_with_marks(self, dsn: str) -> list[dict[str, Any]]:
        return self.rows

    def save_marks(self, dsn: str, marks: list[dict[str, Any]]) -> None:
        self.marks.extend(marks)

    def followers(self, dsn: str, match_id: str) -> list[dict[str, Any]]:
        return self.subs

    def latest_goal(self, dsn: str, match_id: str, side: str) -> dict[str, Any] | None:
        return {"player_name": "Old Scorer", "minute": 20}  # earlier goal: not named

    def record_results(self, dsn: str, **kw: list[int]) -> None:
        self.results = {k: list(v) for k, v in kw.items()}


@pytest.fixture
def store(monkeypatch: pytest.MonkeyPatch) -> _Store:
    fake = _Store(
        [_row(home_score=1, minute=61)],
        [
            {"id": 1, "endpoint": "a", "p256dh": "k", "auth": "x"},
            {"id": 2, "endpoint": "b", "p256dh": "k", "auth": "x"},
            {"id": 3, "endpoint": "c", "p256dh": "k", "auth": "x"},
        ],
    )
    import kalchas_db.push as real

    for name in ("live_scores_with_marks", "save_marks", "followers", "latest_goal"):
        monkeypatch.setattr(real, name, getattr(fake, name))
    monkeypatch.setattr(real, "record_results", fake.record_results)
    return fake


def test_tick_sends_and_sorts_results(store: _Store) -> None:
    seen: list[dict[str, Any]] = []
    statuses = {"a": 201, "b": 410, "c": 500}

    def send(sub: dict[str, Any], message: dict[str, Any]) -> int:
        seen.append(message)
        return statuses[sub["endpoint"]]

    assert push_goals.tick("dsn", send) == 1
    assert store.marks == [{"match_id": "100", "home_score": 1, "away_score": 0}]
    assert store.results == {"sent": [1], "failed": [3], "gone": [2]}
    assert seen[0]["body"] == "PSV 1–0 Club Brugge · 61'"


def test_quiet_tick_marks_without_sending(store: _Store) -> None:
    def send(sub: dict[str, Any], message: dict[str, Any]) -> int:
        raise AssertionError("must not send")

    assert push_goals.tick("dsn", send, notify=False) == 0
    assert store.marks == [{"match_id": "100", "home_score": 1, "away_score": 0}]
