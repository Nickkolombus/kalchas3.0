"""Contact form messages: stored first, then delivered by email and Telegram.

The table doubles as the rate limiter -- only real (non-spam) messages are
written, so counting a sender's recent rows is exactly "how many have they
sent".
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import text

from kalchas_db.sync import sync_engine

INSERT_MESSAGE = text(
    """
    INSERT INTO contact_messages (
        name, email, message, ip_hash, ip_masked, country, user_agent
    ) VALUES (
        :name, :email, :message, :ip_hash, :ip_masked, :country, :user_agent
    )
    RETURNING id
    """
)

COUNT_RECENT = text(
    """
    SELECT
        COUNT(*) FILTER (WHERE ip_hash IS NOT DISTINCT FROM :ip_hash) AS sender,
        COUNT(*) AS everyone
    FROM contact_messages
    WHERE created_at >= NOW() - (:seconds || ' seconds')::INTERVAL
    """
)

MARK_DELIVERED = text(
    """
    UPDATE contact_messages
    SET emailed = emailed OR :emailed, telegram_sent = telegram_sent OR :telegram_sent
    WHERE id = :id
    """
)

LIST_MESSAGES = text(
    """
    SELECT id, created_at, name, email, message, ip_masked, country,
           emailed, telegram_sent
    FROM contact_messages
    ORDER BY created_at DESC
    LIMIT :limit
    """
)


def recent_counts(dsn: str, ip_hash: str | None, seconds: int) -> tuple[int, int]:
    """(messages from this sender, messages from everyone) in the last `seconds`."""
    with sync_engine(dsn).connect() as conn:
        row = conn.execute(COUNT_RECENT, {"ip_hash": ip_hash, "seconds": seconds}).one()
    return int(row.sender or 0), int(row.everyone or 0)


def insert_message(
    dsn: str,
    *,
    name: str,
    email: str,
    message: str,
    ip_hash: str | None,
    ip_masked: str | None,
    country: str | None,
    user_agent: str | None,
) -> int:
    with sync_engine(dsn).begin() as conn:
        row = conn.execute(
            INSERT_MESSAGE,
            {
                "name": name,
                "email": email,
                "message": message,
                "ip_hash": ip_hash,
                "ip_masked": ip_masked,
                "country": country,
                "user_agent": user_agent,
            },
        ).one()
    return int(row[0])


def mark_delivered(dsn: str, message_id: int, *, emailed: bool, telegram_sent: bool) -> None:
    with sync_engine(dsn).begin() as conn:
        conn.execute(
            MARK_DELIVERED,
            {"id": message_id, "emailed": emailed, "telegram_sent": telegram_sent},
        )


def list_messages(dsn: str, limit: int = 200) -> list[dict[str, Any]]:
    with sync_engine(dsn).connect() as conn:
        rows = conn.execute(LIST_MESSAGES, {"limit": limit}).mappings().all()
    return [dict(row) for row in rows]
