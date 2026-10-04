"""Shared scanner runtime status for the API dashboard."""

from __future__ import annotations

from typing import Any

from sqlalchemy import text

from kalchas_db.sync import sync_engine

UPSERT_STATUS = text(
    """
    INSERT INTO scanner_status (
        singleton, mode, connected, messages_received, reconnects,
        last_message_at, last_http_poll_at, last_error, updated_at
    ) VALUES (
        TRUE, :mode, :connected, COALESCE(:messages_received, 0), COALESCE(:reconnects, 0),
        CASE WHEN :last_message THEN NOW() ELSE NULL END,
        CASE WHEN :last_http_poll THEN NOW() ELSE NULL END,
        :last_error, NOW()
    )
    ON CONFLICT (singleton) DO UPDATE SET
        mode = EXCLUDED.mode,
        connected = EXCLUDED.connected,
        messages_received = COALESCE(:messages_received, scanner_status.messages_received),
        reconnects = COALESCE(:reconnects, scanner_status.reconnects),
        last_message_at = CASE
            WHEN :last_message THEN NOW() ELSE scanner_status.last_message_at END,
        last_http_poll_at = CASE
            WHEN :last_http_poll THEN NOW() ELSE scanner_status.last_http_poll_at END,
        last_error = :last_error,
        updated_at = NOW()
    """
)

GET_STATUS = text(
    """
    SELECT mode, connected, messages_received, reconnects,
           last_message_at, last_http_poll_at, last_error, updated_at
    FROM scanner_status
    WHERE singleton = TRUE
    """
)


def update_scanner_status_sync(
    dsn: str,
    *,
    mode: str,
    connected: bool,
    messages_received: int | None = None,
    reconnects: int | None = None,
    last_message: bool = False,
    last_http_poll: bool = False,
    last_error: str | None = None,
) -> None:
    eng = sync_engine(dsn)
    with eng.begin() as conn:
        conn.execute(
            UPSERT_STATUS,
            {
                "mode": mode,
                "connected": connected,
                "messages_received": messages_received,
                "reconnects": reconnects,
                "last_message": last_message,
                "last_http_poll": last_http_poll,
                "last_error": last_error,
            },
        )


def get_scanner_status_sync(dsn: str) -> dict[str, Any] | None:
    eng = sync_engine(dsn)
    with eng.connect() as conn:
        row = conn.execute(GET_STATUS).mappings().first()
    return dict(row) if row is not None else None
