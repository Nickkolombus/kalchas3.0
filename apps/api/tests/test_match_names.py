"""Most-watched matches: names from our own tables, then the provider."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import kalchas_db.panel_cache as panel_cache
from kalchas_api.match_names import fill_missing_names, name_from_event
from kalchas_db.visits import match_names

ATHENS = ZoneInfo("Europe/Athens")
NOW = datetime(2026, 11, 21, 12, tzinfo=UTC)


class _Result:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    def mappings(self) -> list[dict[str, Any]]:
        return self._rows


class _Conn:
    """Answers the name sources in order: matches, history, watchlist, alerts."""

    def __init__(self, *answers: list[dict[str, Any]]) -> None:
        self.answers = list(answers)
        self.ids: list[list[str]] = []

    def execute(self, _query: Any, params: dict[str, Any]) -> _Result:
        self.ids.append(params["ids"])
        return _Result(self.answers.pop(0))


def test_match_names_takes_each_field_from_the_best_source() -> None:
    alert_time = datetime(2026, 11, 2, 20, 10, tzinfo=UTC)
    conn = _Conn(
        [],  # live matches: long gone
        [
            {
                "match_id": "1",
                "home_team": "Ajax",
                "away_team": "PSV",
                "league": None,
                "kickoff": datetime(2026, 11, 2, 19, tzinfo=UTC),
            }
        ],
        [
            {
                "match_id": "2",
                "home_team": "Motagua",
                "away_team": "Marathon",
                "league": "Liga Nacional",
                "kickoff": "2026-11-02T02:15:00+03:00",
            }
        ],
        [
            {
                "match_id": "1",
                "home_team": "Ajax A",
                "away_team": "PSV E",
                "league": "Eredivisie",
                "kickoff": alert_time,
            },
            {
                "match_id": "3",
                "home_team": "Ath Bilbao",
                "away_team": "Espanyol",
                "league": "La Liga",
                "kickoff": alert_time,
            },
        ],
    )
    names = match_names(conn, ["1", "2", "3", "4"])
    assert len(conn.ids) == 4
    assert names["1"] == {
        "match_id": "1",
        "home_team": "Ajax",
        "away_team": "PSV",
        "league": "Eredivisie",
        "kickoff": "2026-11-02T19:00:00+00:00",
    }
    assert names["2"]["kickoff"] == "2026-11-02T02:15:00+03:00"
    assert names["3"]["home_team"] == "Ath Bilbao"
    assert "4" not in names
    assert match_names(conn, []) == {}


def test_name_from_event() -> None:
    row = {
        "match_hometeam_name": "Inter",
        "match_awayteam_name": "Milan",
        "league_name": "Serie A",
        "match_date": "2026-11-01",
        "match_time": "23:30",
    }
    assert name_from_event(row) == {
        "home_team": "Inter",
        "away_team": "Milan",
        "league": "Serie A",
        "kickoff": "2026-11-01T23:30:00+00:00",
    }
    assert name_from_event({"match_hometeam_name": "Inter"}) is None


def _cache(monkeypatch, store: dict[str, dict[str, Any]]) -> None:
    monkeypatch.setattr(panel_cache, "load_panel_cache", lambda dsn, key, **kw: store.get(key))
    monkeypatch.setattr(
        panel_cache, "save_panel_cache", lambda dsn, key, payload: store.__setitem__(key, payload)
    )


def test_fill_missing_names_asks_the_provider_once_and_caches(monkeypatch) -> None:
    store: dict[str, dict[str, Any]] = {}
    _cache(monkeypatch, store)
    asked: list[str] = []
    closed: list[bool] = []

    def fetch(mid: str) -> dict[str, Any]:
        asked.append(mid)
        if mid == "7":
            return {
                "match_hometeam_name": "Inter",
                "match_awayteam_name": "Milan",
                "league_name": "Serie A",
                "match_date": "2026-11-01",
                "match_time": "23:30",
            }
        return {}

    def fetcher():
        return fetch, lambda: closed.append(True)

    rows = [
        {"match_id": "1", "home_team": "Ajax", "away_team": "PSV", "date": "2026-11-02"},
        {"match_id": "7", "home_team": None, "away_team": None, "league": None, "date": None},
        {"match_id": "8", "home_team": None, "away_team": None, "league": None, "date": None},
    ]
    fill_missing_names(rows, ATHENS, dsn="x", now=NOW, fetcher=fetcher)
    assert asked == ["7", "8"] and closed == [True]
    assert rows[1] == {
        "match_id": "7",
        "home_team": "Inter",
        "away_team": "Milan",
        "league": "Serie A",
        "date": "2026-11-02",
    }
    assert rows[2]["home_team"] is None
    assert store["match_name:8"]["name"] is None

    # Next load: the hit comes from the cache; the fresh miss is not retried.
    again = [
        {"match_id": "7", "home_team": None, "away_team": None},
        {"match_id": "8", "home_team": None, "away_team": None},
    ]
    fill_missing_names(again, ATHENS, dsn="x", now=NOW, fetcher=fetcher)
    assert asked == ["7", "8"]
    assert again[0]["home_team"] == "Inter"

    # A day later the miss is tried again.
    later = [{"match_id": "8", "home_team": None, "away_team": None}]
    fill_missing_names(later, ATHENS, dsn="x", now=NOW + timedelta(days=2), fetcher=fetcher)
    assert asked == ["7", "8", "8"]


def test_fill_missing_names_without_a_provider_leaves_ids(monkeypatch) -> None:
    _cache(monkeypatch, {})
    rows = [{"match_id": "9", "home_team": None, "away_team": None}]
    fill_missing_names(rows, ATHENS, dsn="x", now=NOW, fetcher=lambda: None)
    assert rows[0]["home_team"] is None


def test_fill_missing_names_stops_on_provider_errors(monkeypatch) -> None:
    _cache(monkeypatch, {})
    calls: list[str] = []

    def fetch(mid: str) -> dict[str, Any]:
        calls.append(mid)
        raise TimeoutError("slow")

    rows = [{"match_id": m, "home_team": None, "away_team": None} for m in ("1", "2")]
    fill_missing_names(rows, ATHENS, dsn="x", now=NOW, fetcher=lambda: (fetch, lambda: None))
    assert calls == ["1"]
