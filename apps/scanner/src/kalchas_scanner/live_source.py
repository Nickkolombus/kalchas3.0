"""API-Football WebSocket source with HTTP polling fallback."""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol
from urllib.parse import urlencode

from kalchas_football import FootballAPIClient, LiveMatch, live_match_from_event
from websockets.exceptions import WebSocketException
from websockets.sync.client import connect

from kalchas_scanner.loop import Scanner

logger = logging.getLogger("kalchas.scanner.live_source")

DEFAULT_WS_URL = "wss://wss.apifootball.com/livescore"


class StatusReporter(Protocol):
    def report(self, **fields: Any) -> None: ...


@dataclass
class NullStatusReporter:
    def report(self, **fields: Any) -> None:
        return None


def parse_websocket_message(message: str | bytes) -> list[LiveMatch]:
    """Normalize one provider frame, including Finished rows so the scanner can persist FT."""
    try:
        data = json.loads(message)
    except (json.JSONDecodeError, UnicodeDecodeError):
        logger.debug("ignoring non-JSON WebSocket frame (%s bytes)", len(message))
        return []
    rows = data if isinstance(data, list) else [data]
    matches: list[LiveMatch] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        match = live_match_from_event(row)
        if match is None:
            continue
        matches.append(match)
    return matches


@dataclass
class WebSocketLiveSource:
    scanner: Scanner
    client: FootballAPIClient
    reporter: StatusReporter = field(default_factory=NullStatusReporter)
    timezone: str = "+03:00"
    ws_url: str = DEFAULT_WS_URL
    reconnect_min_sec: float = 2.0
    reconnect_max_sec: float = 60.0
    http_refresh_sec: float = 90.0
    connect_fn: Callable[..., Any] = connect
    sleep_fn: Callable[[float], None] = time.sleep
    monotonic_fn: Callable[[], float] = time.monotonic
    _last_http_at: float = 0.0

    def _url(self) -> str:
        query = urlencode({"APIkey": self.client.api_key, "timezone": self.timezone})
        return f"{self.ws_url}?{query}"

    def _http_poll(self, *, connected: bool) -> None:
        """One get_events cycle. Used as reconnect fallback and WS catch-up."""
        mode = "websocket" if connected else "http_fallback"
        try:
            emitted = self.scanner.run_once()
            self.reporter.report(
                mode=mode,
                connected=connected,
                last_http_poll=True,
                last_error=None,
            )
            logger.info(
                "HTTP %s cycle completed: %s alerts",
                "catch-up" if connected else "fallback",
                emitted,
            )
        except Exception as exc:
            self.reporter.report(
                mode=mode,
                connected=connected,
                last_http_poll=True,
                last_error=str(exc),
            )
            logger.exception("HTTP poll cycle failed")

    def _http_fallback(self) -> None:
        """Run one normal polling cycle while the socket is unavailable."""
        self._http_poll(connected=False)

    def run_forever(self) -> None:
        """Consume WebSocket frames forever, reconnecting with HTTP fallback."""
        delay = self.reconnect_min_sec
        messages = 0
        reconnects = 0
        while True:
            self.reporter.report(mode="connecting", connected=False, last_error=None)
            try:
                logger.info("connecting to API-Football WebSocket")
                with self.connect_fn(
                    self._url(),
                    open_timeout=15,
                    ping_interval=20,
                    ping_timeout=20,
                    close_timeout=10,
                    user_agent_header="Kalchas-3.0",
                ) as websocket:
                    self.reporter.report(mode="websocket", connected=True, last_error=None)
                    logger.info("API-Football WebSocket connected")
                    self._last_http_at = self.monotonic_fn()
                    for message in websocket:
                        matches = parse_websocket_message(message)
                        if not matches:
                            continue
                        delay = self.reconnect_min_sec
                        messages += 1
                        for match in matches:
                            try:
                                self.scanner.process_match(match)
                            except Exception:
                                logger.exception(
                                    "failed processing WebSocket match %s", match.match_id
                                )
                        self.reporter.report(
                            mode="websocket",
                            connected=True,
                            last_message=True,
                            messages_received=messages,
                            last_error=None,
                        )
                        now = self.monotonic_fn()
                        if now - self._last_http_at >= self.http_refresh_sec:
                            self._http_poll(connected=True)
                            self._last_http_at = now
                    reconnects += 1
                    self.reporter.report(
                        mode="http_fallback",
                        connected=False,
                        reconnects=reconnects,
                        last_error="WebSocket closed",
                    )
            except KeyboardInterrupt:
                raise
            except (OSError, TimeoutError, WebSocketException) as exc:
                reconnects += 1
                self.reporter.report(
                    mode="http_fallback",
                    connected=False,
                    reconnects=reconnects,
                    last_error=str(exc),
                )
                logger.warning("WebSocket unavailable: %s", exc)

            self._http_fallback()
            logger.info("reconnecting WebSocket in %.1fs", delay)
            self.sleep_fn(delay)
            delay = min(delay * 2, self.reconnect_max_sec)
