"""WebSocket live source tests using recorded provider-shaped frames."""

from __future__ import annotations

import json
from typing import Any

import pytest
from kalchas_scanner.live_source import WebSocketLiveSource, parse_websocket_message


def _row(*, match_id: str = "902316", status: str = "67") -> dict[str, Any]:
    return {
        "match_id": match_id,
        "match_status": status,
        "match_hometeam_id": "3",
        "match_hometeam_name": "Italy",
        "match_hometeam_score": "1",
        "match_awayteam_id": "16",
        "match_awayteam_name": "England",
        "match_awayteam_score": "1",
        "league_name": "European Championship",
        "team_home_badge": "https://apiv3.apifootball.com/badges//3_italy.jpg",
        "team_away_badge": "https://apiv3.apifootball.com/badges/16_england.jpg",
        "goalscorer": [],
        "cards": [],
        "statistics": [
            {"type": "Attacks", "home": "80", "away": "73"},
            {"type": "Dangerous Attacks", "home": "31", "away": "29"},
            {"type": "On Target", "home": "4", "away": "3"},
            {"type": "Off Target", "home": "5", "away": "4"},
            {"type": "Corners", "home": "5", "away": "2"},
            {"type": "Ball Possession", "home": "52%", "away": "48%"},
        ],
    }


def test_parse_websocket_list_frame() -> None:
    matches = parse_websocket_message(json.dumps([_row(), _row(match_id="2", status="Finished")]))
    assert len(matches) == 2
    by_id = {row.match_id: row for row in matches}
    assert by_id["902316"].minute == 67
    assert by_id["902316"].home_team_logo == "https://apiv3.apifootball.com/badges/3_italy.jpg"
    assert by_id["902316"].raw["statistics"][1]["type"] == "Dangerous Attacks"
    assert by_id["2"].status_short == "FT"
    assert by_id["2"].minute == 0


def test_parse_websocket_preserves_stoppage_display() -> None:
    match = parse_websocket_message(json.dumps(_row(status="90+")))[0]
    assert match.minute == 90
    assert match.status_short == "2H"
    assert match.minute_display == "90+"
    added = parse_websocket_message(json.dumps(_row(status="45+2")))[0]
    assert added.minute == 47
    assert added.status_short == "1H"
    assert added.minute_display == "45+2"


def test_parse_websocket_fills_stoppage_from_goal_time() -> None:
    row = _row(status="90+")
    row["goalscorer"] = [
        {"time": "90+3", "home_scorer": "Scorer", "away_scorer": ""},
    ]
    match = parse_websocket_message(json.dumps(row))[0]
    assert match.minute == 93
    assert match.minute_display == "90+3"


def test_parse_websocket_single_frame_and_invalid_rows() -> None:
    assert parse_websocket_message(json.dumps(_row()))[0].home_team == "Italy"
    assert parse_websocket_message(json.dumps({"match_status": "10"})) == []
    assert parse_websocket_message(json.dumps(["bad", 4, None])) == []
    assert parse_websocket_message("Connected") == []
    assert parse_websocket_message(b"") == []


class _Scanner:
    def __init__(self) -> None:
        self.processed: list[str] = []
        self.polls = 0

    def process_match(self, match: Any) -> list[dict]:
        self.processed.append(match.match_id)
        return []

    def run_once(self) -> int:
        self.polls += 1
        return 0


class _Client:
    api_key = "secret"


class _Reporter:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    def report(self, **fields: Any) -> None:
        self.events.append(fields)


class _Socket:
    def __enter__(self) -> _Socket:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def __iter__(self):
        yield json.dumps([_row()])
        raise ConnectionError("socket closed")


def test_source_processes_frame_then_falls_back_and_reconnects() -> None:
    scanner = _Scanner()
    reporter = _Reporter()
    urls: list[str] = []

    def connect_fn(url: str, **kwargs: Any) -> _Socket:
        urls.append(url)
        return _Socket()

    def stop_after_backoff(delay: float) -> None:
        raise KeyboardInterrupt

    source = WebSocketLiveSource(
        scanner=scanner,  # type: ignore[arg-type]
        client=_Client(),  # type: ignore[arg-type]
        reporter=reporter,
        connect_fn=connect_fn,
        sleep_fn=stop_after_backoff,
    )
    with pytest.raises(KeyboardInterrupt):
        source.run_forever()

    assert scanner.processed == ["902316"]
    assert scanner.polls == 1
    assert "APIkey=secret" in urls[0]
    assert any(e.get("connected") is True for e in reporter.events)
    assert any(e.get("last_message") is True for e in reporter.events)
    assert any(e.get("mode") == "http_fallback" for e in reporter.events)


class _GreetingSocket(_Socket):
    def __iter__(self):
        yield "Connected"


def test_greeting_only_connection_does_not_reset_backoff() -> None:
    scanner = _Scanner()
    delays: list[float] = []

    def sleep_fn(delay: float) -> None:
        delays.append(delay)
        if len(delays) == 2:
            raise KeyboardInterrupt

    source = WebSocketLiveSource(
        scanner=scanner,  # type: ignore[arg-type]
        client=_Client(),  # type: ignore[arg-type]
        connect_fn=lambda *args, **kwargs: _GreetingSocket(),
        sleep_fn=sleep_fn,
    )
    with pytest.raises(KeyboardInterrupt):
        source.run_forever()

    assert delays == [2.0, 4.0]
    assert scanner.processed == []
    assert scanner.polls == 2


class _Clock:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t


class _CatchupSocket(_Socket):
    def __init__(self, clock: _Clock) -> None:
        self._clock = clock

    def __iter__(self):
        self._clock.t = 21.0
        yield json.dumps([_row()])
        raise ConnectionError("socket closed")


def test_source_http_catchup_while_websocket_stays_connected() -> None:
    scanner = _Scanner()
    clock = _Clock()

    def stop_after_backoff(delay: float) -> None:
        raise KeyboardInterrupt

    source = WebSocketLiveSource(
        scanner=scanner,  # type: ignore[arg-type]
        client=_Client(),  # type: ignore[arg-type]
        connect_fn=lambda *args, **kwargs: _CatchupSocket(clock),
        sleep_fn=stop_after_backoff,
        monotonic_fn=clock,
        http_refresh_sec=20.0,
    )
    with pytest.raises(KeyboardInterrupt):
        source.run_forever()

    assert scanner.processed == ["902316"]
    assert scanner.polls == 2
