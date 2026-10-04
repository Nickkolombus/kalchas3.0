"""Scanner persistence + hydrate smoke tests."""

from __future__ import annotations

import time

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
        league_id=152,
    )
    history = persist.load_history("99")
    assert history["22"]["shots_on_target"]["home"] == 2
    assert persist.matches["99"]["minute"] == 22
    assert persist.matches["99"]["league_id"] == 152


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


def test_process_match_uses_embedded_stats_without_extra_request(monkeypatch) -> None:
    from kalchas_scanner.loop import Scanner
    from kalchas_scanner.outbox import MemoryAlertSink

    class NoStatsCallClient:
        def get_fixture_statistics(self, match_id: str):
            raise AssertionError("embedded stats present; get_statistics must not be called")

        def get_fixture_events(self, match_id: str):
            return {}

        def get_live_fixtures(self):
            return []

    persist = MemoryMatchPersist()
    scanner = Scanner(
        client=NoStatsCallClient(),  # type: ignore[arg-type]
        sink=MemoryAlertSink(),
        persist=persist,
    )
    monkeypatch.setattr("kalchas_scanner.loop.evaluate_match", lambda *a, **k: [])

    raw = {
        "match_id": "7",
        "match_hometeam_name": "A",
        "match_awayteam_name": "B",
        "goalscorer": [{"time": "12", "home_scorer": "Scorer", "away_scorer": ""}],
        "cards": [{"time": "25", "home_fault": "", "away_fault": "Booked", "card": "yellow card"}],
        "statistics": [
            {"type": "Attacks", "home": "40", "away": "30"},
            {"type": "Dangerous Attacks", "home": "18", "away": "9"},
            {"type": "On Target", "home": "3", "away": "1"},
            {"type": "Off Target", "home": "4", "away": "2"},
            {"type": "Shots Off Goal", "home": "2", "away": "1"},
            {"type": "Corners", "home": "5", "away": "1"},
            {"type": "Ball Possession", "home": "61%", "away": "39%"},
        ],
    }
    match = LiveMatch(
        match_id="7",
        home_team="A",
        away_team="B",
        home_team_id=1,
        away_team_id=2,
        minute=30,
        home_score=0,
        away_score=0,
        status_short="1H",
        league_name="L",
        raw=raw,
    )
    scanner.process_match(match)
    block = persist.histories["7"]["30"]
    assert block["dangerous_attacks"] == {"home": 18, "away": 9}
    assert block["shots_off_target"] == {"home": 4, "away": 2}
    assert block["possession"] == {"home": 61, "away": 39}
    assert [event["event_type"] for event in persist.events["7"]] == ["goal", "card"]


def test_alert_payload_includes_live_stats(monkeypatch) -> None:
    from kalchas_core.match import Side
    from kalchas_core.runner import AlertCandidate
    from kalchas_scanner.loop import Scanner
    from kalchas_scanner.outbox import MemoryAlertSink

    class NoStatsCallClient:
        def get_fixture_statistics(self, match_id: str):
            raise AssertionError("embedded stats present; get_statistics must not be called")

        def get_fixture_events(self, match_id: str):
            return {}

        def get_live_fixtures(self):
            return []

    persist = MemoryMatchPersist()
    sink = MemoryAlertSink()
    scanner = Scanner(
        client=NoStatsCallClient(),  # type: ignore[arg-type]
        sink=sink,
        persist=persist,
    )
    scanner._odds_by_match["8"] = {"home": 2.1, "draw": 3.2, "away": 3.4}
    monkeypatch.setattr(
        "kalchas_scanner.loop.evaluate_match",
        lambda *a, **k: [AlertCandidate(4, "delta_5min", Side.HOME, 5.5, {})],
    )
    raw = {
        "match_id": "8",
        "match_hometeam_name": "A",
        "match_awayteam_name": "B",
        "cards": [{"time": "25", "home_fault": "", "away_fault": "Booked", "card": "yellow card"}],
        "statistics": [
            {"type": "Attacks", "home": "40", "away": "30"},
            {"type": "Dangerous Attacks", "home": "18", "away": "9"},
            {"type": "On Target", "home": "3", "away": "1"},
            {"type": "Off Target", "home": "4", "away": "2"},
            {"type": "Corners", "home": "5", "away": "1"},
            {"type": "Ball Possession", "home": "61%", "away": "39%"},
        ],
    }
    match = LiveMatch(
        match_id="8",
        home_team="A",
        away_team="B",
        home_team_id=1,
        away_team_id=2,
        minute=30,
        home_score=0,
        away_score=0,
        status_short="1H",
        league_name="L",
        raw=raw,
    )
    emitted = scanner.process_match(match)
    assert len(emitted) == 1
    payload = emitted[0]
    assert payload["league"] == "L"
    assert payload["sot"] == {"home": 3, "away": 1}
    assert payload["sofft"] == {"home": 4, "away": 2}
    assert payload["corners"] == {"home": 5, "away": 1}
    assert payload["attacks"] == {"home": 40, "away": 30}
    assert payload["da"] == {"home": 18, "away": 9}
    assert payload["possession"] == {"home": 61, "away": 39}
    assert payload["yc"] == {"home": 0, "away": 1}
    assert payload["rc"] == {"home": 0, "away": 0}
    assert payload["odds"]["home"] == 2.1
    assert payload["odds"]["kickoff"]["away"] == 3.4
    assert sink.items[0]["sot"] == payload["sot"]


def test_process_match_persists_lineup_before_min_minute_without_extra_http() -> None:
    from kalchas_scanner.loop import Scanner
    from kalchas_scanner.outbox import MemoryAlertSink

    class NoExtraClient:
        def get_fixture_statistics(self, match_id: str):
            raise AssertionError("live row has stats; get_statistics must not be called")

        def get_fixture_events(self, match_id: str):
            raise AssertionError("live row has events; get_events must not be called")

        def get_live_fixtures(self):
            return []

    persist = MemoryMatchPersist()
    scanner = Scanner(
        client=NoExtraClient(),  # type: ignore[arg-type]
        sink=MemoryAlertSink(),
        persist=persist,
    )
    raw = {
        "match_id": "3",
        "lineup": {
            "home": {
                "starting_lineups": [
                    {"lineup_player": "Home GK", "lineup_number": "1", "lineup_position": "1"}
                ],
                "coach": [{"lineup_player": "Home Coach"}],
            },
            "away": {"starting_lineups": [], "substitutes": []},
        },
        "substitutions": {
            "home": [{"time": "1", "substitution": "Out | In"}],
        },
        "statistics": [
            {"type": "Attacks", "home": "8", "away": "4"},
            {"type": "Dangerous Attacks", "home": "3", "away": "1"},
            {"type": "On Target", "home": "1", "away": "0"},
        ],
        "goalscorer": [],
        "cards": [],
    }
    match = LiveMatch(
        match_id="3",
        home_team="A",
        away_team="B",
        home_team_id=1,
        away_team_id=2,
        minute=3,
        home_score=0,
        away_score=0,
        status_short="1H",
        league_name="L",
        raw=raw,
    )
    assert scanner.process_match(match) == []
    assert (
        persist.matches["3"]["lineup"]["home"]["starting_lineups"][0]["lineup_player"] == "Home GK"
    )
    assert persist.histories["3"]["3"]["dangerous_attacks"] == {"home": 3, "away": 1}


def test_process_match_persists_country_and_cached_odds_without_get_odds() -> None:
    from kalchas_scanner.loop import Scanner
    from kalchas_scanner.outbox import MemoryAlertSink

    class NoOddsCallClient:
        def get_fixture_statistics(self, match_id: str):
            return {"home_team": {}, "away_team": {}}

        def get_fixture_events(self, match_id: str):
            return {}

        def get_live_fixtures(self):
            return []

        def get_odds_1x2_today(self):
            raise AssertionError("per-match path must use the cache, not get_odds")

    persist = MemoryMatchPersist()
    scanner = Scanner(
        client=NoOddsCallClient(),  # type: ignore[arg-type]
        sink=MemoryAlertSink(),
        persist=persist,
    )
    scanner._odds_by_match = {"9": {"home": 2.1, "draw": 3.2, "away": 3.4}}
    now = time.monotonic()
    scanner._odds_fetched_at = now
    scanner._live_odds_fetched_at = now
    match = LiveMatch(
        match_id="9",
        home_team="A",
        away_team="B",
        home_team_id=1,
        away_team_id=2,
        minute=20,
        home_score=0,
        away_score=0,
        status_short="1H",
        league_name="J-League Cup",
        country_name="Japan",
        country_logo="https://apiv3.apifootball.com/badges/logo_country/3_japan.png",
        raw={"statistics": [{"type": "On Target", "home": "1", "away": "0"}]},
    )
    scanner.process_match(match)
    stored = persist.matches["9"]
    assert stored["country_name"] == "Japan"
    assert stored["odds"]["home"] == 2.1
    assert stored["odds"]["kickoff"]["draw"] == 3.2
    assert "live" not in stored["odds"]


def test_process_match_keeps_team_badges_on_clock_persist(monkeypatch) -> None:
    from kalchas_scanner.loop import Scanner, ScannerConfig
    from kalchas_scanner.outbox import MemoryAlertSink

    class NoStatsCallClient:
        def get_fixture_statistics(self, match_id: str):
            raise AssertionError("stats HTTP budget spent; get_statistics must not be called")

        def get_fixture_events(self, match_id: str):
            return {}

        def get_live_fixtures(self):
            return []

    persist = MemoryMatchPersist()
    scanner = Scanner(
        client=NoStatsCallClient(),  # type: ignore[arg-type]
        sink=MemoryAlertSink(),
        persist=persist,
        config=ScannerConfig(max_stats_http_per_cycle=0),
    )
    monkeypatch.setattr("kalchas_scanner.loop.evaluate_match", lambda *a, **k: [])
    badge_home = "https://apiv3.apifootball.com/badges//2222_puerto-montt.jpg"
    badge_away = "https://apiv3.apifootball.com/badges/553_colo-colo.jpg"
    first = LiveMatch(
        match_id="860018",
        home_team="D. Puerto Montt",
        away_team="Colo Colo",
        home_team_id=2222,
        away_team_id=553,
        minute=12,
        home_score=0,
        away_score=0,
        status_short="1H",
        home_team_logo=badge_home,
        away_team_logo=badge_away,
        raw={
            "team_home_badge": badge_home,
            "team_away_badge": badge_away,
        },
    )
    scanner.process_match(first)
    later = LiveMatch(
        match_id="860018",
        home_team="D. Puerto Montt",
        away_team="Colo Colo",
        home_team_id=2222,
        away_team_id=553,
        minute=13,
        home_score=0,
        away_score=0,
        status_short="1H",
    )
    scanner.process_match(later)
    stored = persist.matches["860018"]
    assert stored["home_team_logo"] == "https://apiv3.apifootball.com/badges/2222_puerto-montt.jpg"
    assert stored["away_team_logo"] == badge_away
    assert stored["minute"] == 13


def test_run_once_refreshes_odds_cache_once() -> None:
    from kalchas_scanner.loop import Scanner, ScannerConfig
    from kalchas_scanner.outbox import MemoryAlertSink

    calls = {"odds": 0}

    class EmptyLiveClient:
        def get_odds_1x2_today(self):
            calls["odds"] += 1
            return {"1": {"home": 1.9, "away": 4.0}}

        def get_live_fixtures(self):
            return []

    scanner = Scanner(
        client=EmptyLiveClient(),  # type: ignore[arg-type]
        sink=MemoryAlertSink(),
        persist=MemoryMatchPersist(),
        config=ScannerConfig(odds_refresh_sec=600),
    )
    scanner.run_once()
    scanner.run_once()
    assert calls["odds"] == 1
    assert scanner._odds_by_match["1"]["home"] == 1.9


def test_odds_cache_keeps_kickoff_when_refresh_returns_empty() -> None:
    from kalchas_scanner.loop import Scanner, ScannerConfig
    from kalchas_scanner.outbox import MemoryAlertSink

    calls = {"odds": 0}

    class EmptyThenGone:
        def get_odds_1x2_today(self):
            calls["odds"] += 1
            if calls["odds"] == 1:
                return {"1": {"home": 1.9, "away": 4.0}}
            return {}

        def get_live_fixtures(self):
            return []

    scanner = Scanner(
        client=EmptyThenGone(),  # type: ignore[arg-type]
        sink=MemoryAlertSink(),
        persist=MemoryMatchPersist(),
        config=ScannerConfig(odds_refresh_sec=0),
    )
    scanner.run_once()
    scanner.run_once()
    assert calls["odds"] == 2
    assert scanner._odds_by_match["1"]["home"] == 1.9


def test_process_match_refreshes_odds_and_persists_live_1x2() -> None:
    from kalchas_scanner.loop import Scanner
    from kalchas_scanner.outbox import MemoryAlertSink

    class OddsClient:
        def get_odds_1x2_today(self):
            return {"12": {"home": 2.2, "draw": 3.1, "away": 3.4}}

        def get_live_odds_1x2(self):
            return {"12": {"home": 1.7, "draw": 3.6, "away": 5.0}}

        def get_live_fixtures(self):
            return []

        def get_fixture_statistics(self, match_id: str):
            return {"home_team": {}, "away_team": {}}

        def get_fixture_events(self, match_id: str):
            return {}

    persist = MemoryMatchPersist()
    scanner = Scanner(
        client=OddsClient(),  # type: ignore[arg-type]
        sink=MemoryAlertSink(),
        persist=persist,
    )
    match = LiveMatch(
        match_id="12",
        home_team="A",
        away_team="B",
        home_team_id=1,
        away_team_id=2,
        minute=20,
        home_score=0,
        away_score=0,
        status_short="1H",
        league_name="L",
        raw={"statistics": [{"type": "On Target", "home": "1", "away": "0"}]},
    )
    scanner.process_match(match)
    stored = persist.matches["12"]["odds"]
    assert stored["home"] == 2.2
    assert stored["kickoff"]["away"] == 3.4
    assert stored["live"] == {"home": 1.7, "draw": 3.6, "away": 5.0}


def test_process_match_fills_stoppage_from_comment_clock() -> None:
    from kalchas_scanner.loop import Scanner
    from kalchas_scanner.outbox import MemoryAlertSink

    class ClockClient:
        def get_odds_1x2_today(self):
            return {}

        def get_live_odds_comments_bundle(self):
            return {}, {"12": 92}

        def get_live_fixtures(self):
            return []

        def get_fixture_statistics(self, match_id: str):
            return {"home_team": {}, "away_team": {}}

        def get_fixture_events(self, match_id: str):
            return {}

    persist = MemoryMatchPersist()
    scanner = Scanner(
        client=ClockClient(),  # type: ignore[arg-type]
        sink=MemoryAlertSink(),
        persist=persist,
    )
    match = LiveMatch(
        match_id="12",
        home_team="A",
        away_team="B",
        home_team_id=1,
        away_team_id=2,
        minute=90,
        home_score=1,
        away_score=0,
        status_short="2H",
        minute_display="90+",
        league_name="L",
        raw={},
    )
    scanner.process_match(match)
    stored = persist.matches["12"]
    assert stored["minute"] == 92
    assert stored["minute_display"] == "90+2"


def test_process_match_updates_clock_when_stats_http_budget_is_spent(monkeypatch) -> None:
    from kalchas_scanner.loop import Scanner, ScannerConfig
    from kalchas_scanner.outbox import MemoryAlertSink

    class NoStatsCallClient:
        def get_fixture_statistics(self, match_id: str):
            raise AssertionError("stats HTTP budget spent; get_statistics must not be called")

        def get_fixture_events(self, match_id: str):
            return {}

        def get_live_fixtures(self):
            return []

    persist = MemoryMatchPersist()
    scanner = Scanner(
        client=NoStatsCallClient(),  # type: ignore[arg-type]
        sink=MemoryAlertSink(),
        persist=persist,
        config=ScannerConfig(max_stats_http_per_cycle=0),
    )
    monkeypatch.setattr("kalchas_scanner.loop.evaluate_match", lambda *a, **k: [])
    match = LiveMatch(
        match_id="786889",
        home_team="Somalia",
        away_team="Ivory Coast",
        home_team_id=630,
        away_team_id=738,
        minute=58,
        home_score=0,
        away_score=0,
        status_short="2H",
        minute_display="90+",
        league_name="Africa Cup of Nations Qualification - Qualification",
    )
    assert scanner.process_match(match) == []
    header = persist.matches["786889"]
    assert header["minute"] == 58
    assert header["status_short"] == "2H"
    assert header["minute_display"] == "90+"


def test_process_match_persists_when_stats_http_hits_hourly_budget(monkeypatch) -> None:
    from kalchas_football import RateLimitBudgetExceeded
    from kalchas_scanner.loop import Scanner
    from kalchas_scanner.outbox import MemoryAlertSink

    class RateLimitedStatsClient:
        def get_fixture_statistics(self, match_id: str):
            raise RateLimitBudgetExceeded(3497.6)

        def get_fixture_events(self, match_id: str):
            return {}

        def get_live_fixtures(self):
            return []

    persist = MemoryMatchPersist()
    scanner = Scanner(
        client=RateLimitedStatsClient(),  # type: ignore[arg-type]
        sink=MemoryAlertSink(),
        persist=persist,
    )
    monkeypatch.setattr("kalchas_scanner.loop.evaluate_match", lambda *a, **k: [])
    match = LiveMatch(
        match_id="786889",
        home_team="Somalia",
        away_team="Ivory Coast",
        home_team_id=630,
        away_team_id=738,
        minute=75,
        home_score=0,
        away_score=0,
        status_short="2H",
        league_name="Africa Cup of Nations Qualification - Qualification",
    )
    assert scanner.process_match(match) == []
    header = persist.matches["786889"]
    assert header["minute"] == 75
    assert header["status_short"] == "2H"


def test_process_match_persists_finished_as_ft_without_zeroing_minute(monkeypatch) -> None:
    from kalchas_scanner.loop import Scanner
    from kalchas_scanner.outbox import MemoryAlertSink

    class MustNotCallClient:
        def get_fixture_statistics(self, match_id: str):
            raise AssertionError("Finished matches must not call get_statistics")

        def get_fixture_events(self, match_id: str):
            raise AssertionError("Finished matches must not call get_events")

        def get_live_fixtures(self):
            return []

    persist = MemoryMatchPersist()
    persist.save_minute(
        match_id="uxbridge",
        home_team="Uxbridge",
        away_team="Away",
        home_team_id=1,
        away_team_id=2,
        league_name="National League",
        status_short="2H",
        home_score=1,
        away_score=0,
        minute=90,
        minute_block={"shots_on_target": {"home": 3, "away": 1}},
    )
    scanner = Scanner(
        client=MustNotCallClient(),  # type: ignore[arg-type]
        sink=MemoryAlertSink(),
        persist=persist,
    )
    called = {"eval": 0}

    def _boom(*args: object, **kwargs: object) -> list:
        called["eval"] += 1
        raise AssertionError("Finished matches must not evaluate alerts")

    monkeypatch.setattr("kalchas_scanner.loop.evaluate_match", _boom)
    finished = LiveMatch(
        match_id="uxbridge",
        home_team="Uxbridge",
        away_team="Away",
        home_team_id=1,
        away_team_id=2,
        minute=0,
        home_score=1,
        away_score=0,
        status_short="FT",
        league_name="National League",
    )
    assert scanner.process_match(finished) == []
    header = persist.matches["uxbridge"]
    assert header["status_short"] == "FT"
    assert header["minute"] == 90
    assert called["eval"] == 0


def test_run_once_processes_every_live_match(monkeypatch) -> None:
    from kalchas_scanner.loop import Scanner, ScannerConfig
    from kalchas_scanner.outbox import MemoryAlertSink

    matches = [
        LiveMatch(
            match_id=str(i),
            home_team=f"H{i}",
            away_team=f"A{i}",
            home_team_id=i,
            away_team_id=i + 10,
            minute=10 + i,
            home_score=0,
            away_score=0,
            status_short="1H",
            league_name="L",
        )
        for i in range(3)
    ]

    class LiveClient:
        def get_odds_1x2_today(self):
            return {}

        def get_live_fixtures(self):
            return list(matches)

        def get_fixture_statistics(self, match_id: str):
            return {"home_team": {}, "away_team": {}}

        def get_fixture_events(self, match_id: str):
            return {}

    persist = MemoryMatchPersist()
    scanner = Scanner(
        client=LiveClient(),  # type: ignore[arg-type]
        sink=MemoryAlertSink(),
        persist=persist,
        config=ScannerConfig(max_stats_http_per_cycle=0),
    )
    monkeypatch.setattr("kalchas_scanner.loop.evaluate_match", lambda *a, **k: [])
    scanner.run_once()
    assert set(persist.matches) == {"0", "1", "2"}
    assert persist.matches["2"]["minute"] == 12
