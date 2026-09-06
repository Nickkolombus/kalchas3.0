"""Scanner persistence + hydrate smoke tests."""

from __future__ import annotations

from kalchas_football import LiveMatch
from kalchas_scanner.persist import MemoryMatchPersist
from kalchas_scanner.store import MinuteStore


def test_store_seeds_history_and_reports_has() -> None:
    store = MinuteStore()
    assert not store.has("m1")
    store.seed_history(
        "m1",
        {
            "10": {
                "shots_on_target": {"home": 1, "away": 0},
                "goals": {"home": 0, "away": 0},
            }
        },
    )
    assert store.has("m1")
    tl = store.timeline("m1", 10)
    assert tl is not None
    assert 10 in tl.minutes


def test_memory_persist_round_trip() -> None:
    persist = MemoryMatchPersist()
    block = {
        "shots_on_target": {"home": 2, "away": 1},
        "goals": {"home": 1, "away": 0},
    }
    persist.save_minute(
        match_id="99",
        home_team="Home",
        away_team="Away",
        home_team_id=1,
        away_team_id=2,
        league_name="Test",
        status_short="1H",
        home_score=1,
        away_score=0,
        minute=22,
        minute_block=block,
    )
    history = persist.load_history("99")
    assert history["22"]["shots_on_target"]["home"] == 2
    assert persist.matches["99"]["minute"] == 22


def test_process_match_persists_and_hydrates(monkeypatch) -> None:
    from kalchas_scanner.loop import Scanner
    from kalchas_scanner.outbox import MemoryAlertSink

    class FakeClient:
        def get_fixture_statistics(self, match_id: str):
            return {
                "home_team": {
                    "on_target": 2,
                    "off_target": 3,
                    "corners": 1,
                    "attacks": 10,
                    "dangerous_attacks": 4,
                },
                "away_team": {
                    "on_target": 0,
                    "off_target": 1,
                    "corners": 0,
                    "attacks": 3,
                    "dangerous_attacks": 1,
                },
            }

        def get_fixture_events(self, match_id: str):
            return {}

        def get_live_fixtures(self):
            return []

    persist = MemoryMatchPersist()
    # Pre-seed so hydrate path is exercised on a fresh store
    persist.save_minute(
        match_id="42",
        home_team="A",
        away_team="B",
        home_team_id=1,
        away_team_id=2,
        league_name="L",
        status_short="1H",
        home_score=0,
        away_score=0,
        minute=20,
        minute_block={
            "shots_on_target": {"home": 1, "away": 0},
            "goals": {"home": 0, "away": 0},
        },
    )

    scanner = Scanner(
        client=FakeClient(),  # type: ignore[arg-type]
        sink=MemoryAlertSink(),
        persist=persist,
    )
    monkeypatch.setattr(
        "kalchas_scanner.loop.evaluate_match",
        lambda *args, **kwargs: [],
    )

    match = LiveMatch(
        match_id="42",
        home_team="A",
        away_team="B",
        home_team_id=1,
        away_team_id=2,
        minute=25,
        home_score=1,
        away_score=0,
        status_short="1H",
        league_name="L",
    )
    scanner.process_match(match)
    assert scanner.store.has("42")
    assert "20" in scanner.store._histories["42"]  # hydrated
    assert "25" in persist.histories["42"]  # new minute written
