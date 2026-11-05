"""Browser push subscriptions and the goal marks the sender keeps.

The API writes subscriptions (one row per browser, with the match ids it has
pinned). The bot reads live scores, compares them with ``push_goal_marks`` and
pushes a notification to every browser following a match that just scored.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any

from sqlalchemy import bindparam, text

from kalchas_db.sync import sync_engine

UPSERT_SUBSCRIPTION = text(
    """
    INSERT INTO push_subscriptions (endpoint, p256dh, auth, match_ids, user_agent)
    VALUES (:endpoint, :p256dh, :auth, :match_ids, :user_agent)
    ON CONFLICT (endpoint) DO UPDATE SET
        p256dh = EXCLUDED.p256dh,
        auth = EXCLUDED.auth,
        match_ids = EXCLUDED.match_ids,
        user_agent = COALESCE(EXCLUDED.user_agent, push_subscriptions.user_agent),
        updated_at = NOW(),
        fail_count = 0
    """
)

DELETE_SUBSCRIPTION = text("DELETE FROM push_subscriptions WHERE endpoint = :endpoint")

LIVE_SCORES = text(
    """
    SELECT m.match_id, m.home_team, m.away_team, m.home_score, m.away_score,
           m.minute, m.minute_display, m.status_short,
           g.home_score AS mark_home, g.away_score AS mark_away
    FROM matches m
    LEFT JOIN push_goal_marks g ON g.match_id = m.match_id
    WHERE m.updated_at >= NOW() - INTERVAL '30 minutes'
    """
)

UPSERT_MARK = text(
    """
    INSERT INTO push_goal_marks (match_id, home_score, away_score, updated_at)
    VALUES (:match_id, :home_score, :away_score, NOW())
    ON CONFLICT (match_id) DO UPDATE SET
        home_score = EXCLUDED.home_score,
        away_score = EXCLUDED.away_score,
        updated_at = NOW()
    """
)

FOLLOWERS = text(
    """
    SELECT id, endpoint, p256dh, auth
    FROM push_subscriptions
    WHERE :match_id = ANY(match_ids)
    """
)

LATEST_GOAL = text(
    """
    SELECT minute, player_name
    FROM match_events
    WHERE match_id = :match_id AND event_type = 'goal' AND side = :side
    ORDER BY minute DESC, recorded_at DESC
    LIMIT 1
    """
)

MARK_SENT = text(
    """
    UPDATE push_subscriptions SET last_sent_at = NOW(), fail_count = 0
    WHERE id IN :ids
    """
).bindparams(bindparam("ids", expanding=True))

MARK_FAILED = text(
    """
    UPDATE push_subscriptions SET fail_count = fail_count + 1
    WHERE id IN :ids
    """
).bindparams(bindparam("ids", expanding=True))

DELETE_BY_ID = text("DELETE FROM push_subscriptions WHERE id IN :ids").bindparams(
    bindparam("ids", expanding=True)
)

PRUNE = (
    # Finished matches leave the board; drop them from every follow list.
    text(
        """
        UPDATE push_subscriptions s
        SET match_ids = ARRAY(
            SELECT id FROM unnest(s.match_ids) AS id
            WHERE id IN (SELECT match_id FROM matches)
        )
        WHERE EXISTS (
            SELECT 1 FROM unnest(s.match_ids) AS id
            WHERE id NOT IN (SELECT match_id FROM matches)
        )
        """
    ),
    text("DELETE FROM push_goal_marks WHERE updated_at < NOW() - INTERVAL '2 days'"),
    # Browsers that keep failing, or that nobody has opened in three months.
    text(
        """
        DELETE FROM push_subscriptions
        WHERE fail_count >= :max_failures
           OR updated_at < NOW() - INTERVAL '90 days'
        """
    ),
)

MAX_FOLLOWS = 60


def clean_match_ids(raw: Iterable[Any]) -> list[str]:
    """Unique, digit-only match ids in the order given, capped at MAX_FOLLOWS."""
    out: list[str] = []
    seen: set[str] = set()
    for value in raw:
        mid = str(value or "").strip()
        if not mid.isdigit() or len(mid) > 20 or mid in seen:
            continue
        seen.add(mid)
        out.append(mid)
        if len(out) >= MAX_FOLLOWS:
            break
    return out


def upsert_subscription(
    dsn: str,
    *,
    endpoint: str,
    p256dh: str,
    auth: str,
    match_ids: Sequence[str],
    user_agent: str | None = None,
) -> None:
    with sync_engine(dsn).begin() as conn:
        conn.execute(
            UPSERT_SUBSCRIPTION,
            {
                "endpoint": endpoint,
                "p256dh": p256dh,
                "auth": auth,
                "match_ids": clean_match_ids(match_ids),
                "user_agent": user_agent,
            },
        )


def delete_subscription(dsn: str, endpoint: str) -> None:
    with sync_engine(dsn).begin() as conn:
        conn.execute(DELETE_SUBSCRIPTION, {"endpoint": endpoint})


def live_scores_with_marks(dsn: str) -> list[dict[str, Any]]:
    """Recently updated matches, each with the last score the sender saw (or None)."""
    with sync_engine(dsn).connect() as conn:
        return [dict(row) for row in conn.execute(LIVE_SCORES).mappings()]


def save_marks(dsn: str, marks: Sequence[dict[str, Any]]) -> None:
    if not marks:
        return
    with sync_engine(dsn).begin() as conn:
        conn.execute(UPSERT_MARK, [dict(m) for m in marks])


def followers(dsn: str, match_id: str) -> list[dict[str, Any]]:
    with sync_engine(dsn).connect() as conn:
        return [dict(row) for row in conn.execute(FOLLOWERS, {"match_id": match_id}).mappings()]


def latest_goal(dsn: str, match_id: str, side: str) -> dict[str, Any] | None:
    with sync_engine(dsn).connect() as conn:
        row = conn.execute(LATEST_GOAL, {"match_id": match_id, "side": side}).mappings().first()
    return dict(row) if row else None


def record_results(
    dsn: str,
    *,
    sent: Sequence[int] = (),
    failed: Sequence[int] = (),
    gone: Sequence[int] = (),
) -> None:
    with sync_engine(dsn).begin() as conn:
        if sent:
            conn.execute(MARK_SENT, {"ids": list(sent)})
        if failed:
            conn.execute(MARK_FAILED, {"ids": list(failed)})
        if gone:
            conn.execute(DELETE_BY_ID, {"ids": list(gone)})


def prune(dsn: str, *, max_failures: int = 20) -> None:
    with sync_engine(dsn).begin() as conn:
        strip_finished, old_marks, dead_browsers = PRUNE
        conn.execute(strip_finished)
        conn.execute(old_marks)
        conn.execute(dead_browsers, {"max_failures": max_failures})
