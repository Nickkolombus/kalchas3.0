"""Browser goal alerts: push a notification when a pinned match scores.

Every few seconds the worker reads the live scores the scanner keeps in
``matches`` and compares each with the last score it saw (``push_goal_marks``).
A higher score is a goal: every browser following that match gets a push.
The first sighting of a match only records its score, so turning alerts on
mid-match never replays old goals, and marks survive restarts.

Env (on the `bot` service):
  VAPID_PRIVATE_KEY  -- base64url raw P-256 private key (pair of the site's
                        VAPID_PUBLIC_KEY); without it the worker stays off.
  VAPID_SUBJECT      -- contact the push services see, default
                        mailto:info@kalchas.live
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger("kalchas.bot.push")

POLL_SEC = 8.0
PRUNE_EVERY_SEC = 3600.0
PUSH_TTL_SEC = 600
"""A goal alert that cannot be delivered within ten minutes is old news."""
SEND_WORKERS = 8
DEFAULT_SUBJECT = "mailto:info@kalchas.live"


def vapid_private_key() -> str:
    return (os.environ.get("VAPID_PRIVATE_KEY") or "").strip()


def vapid_subject() -> str:
    return (os.environ.get("VAPID_SUBJECT") or "").strip() or DEFAULT_SUBJECT


@dataclass(frozen=True)
class Goal:
    match_id: str
    side: str
    home_team: str
    away_team: str
    home_score: int
    away_score: int
    minute: str

    @property
    def team(self) -> str:
        return self.home_team if self.side == "home" else self.away_team


def _int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _minute_label(row: dict[str, Any]) -> str:
    shown = str(row.get("minute_display") or "").strip()
    if shown:
        return shown if shown.endswith("'") else f"{shown}'"
    minute = _int(row.get("minute"))
    return f"{minute}'" if minute else ""


def detect_goals(rows: Sequence[dict[str, Any]]) -> tuple[list[Goal], list[dict[str, Any]]]:
    """Goals since the last look, plus the marks to store.

    A match seen for the first time is only marked. A score that went down
    (a goal taken back) is re-marked quietly, so the next real goal still
    counts once.
    """
    goals: list[Goal] = []
    marks: list[dict[str, Any]] = []
    for row in rows:
        home, away = _int(row.get("home_score")), _int(row.get("away_score"))
        if home is None or away is None:
            continue
        mark_home, mark_away = _int(row.get("mark_home")), _int(row.get("mark_away"))
        match_id = str(row["match_id"])
        if (home, away) != (mark_home, mark_away):
            marks.append({"match_id": match_id, "home_score": home, "away_score": away})
        if mark_home is None or mark_away is None:
            continue
        for side, now, before in (("home", home, mark_home), ("away", away, mark_away)):
            if now > before:
                goals.append(
                    Goal(
                        match_id=match_id,
                        side=side,
                        home_team=str(row.get("home_team") or "Home"),
                        away_team=str(row.get("away_team") or "Away"),
                        home_score=home,
                        away_score=away,
                        minute=_minute_label(row),
                    )
                )
    return goals, marks


def goal_message(goal: Goal, scorer: dict[str, Any] | None = None) -> dict[str, Any]:
    """Notification payload the site's service worker shows as-is."""
    score = f"{goal.home_team} {goal.home_score}–{goal.away_score} {goal.away_team}"
    detail = goal.minute
    name = str((scorer or {}).get("player_name") or "").strip()
    if name:
        detail = f"{name} {goal.minute}".strip()
    body = f"{score} · {detail}" if detail else score
    return {
        "title": f"⚽ Goal for {goal.team}",
        "body": body,
        "tag": f"goal-{goal.match_id}",
        "url": f"/?match={goal.match_id}",
        "match_id": goal.match_id,
    }


Sender = Callable[[dict[str, Any], dict[str, Any]], int]
"""(subscription row, message) -> HTTP status from the push service (0 = no reply)."""


def webpush_sender(private_key: str, subject: str) -> Sender:
    import requests
    from pywebpush import WebPushException, webpush

    session = requests.Session()

    def send(sub: dict[str, Any], message: dict[str, Any]) -> int:
        try:
            resp = webpush(
                subscription_info={
                    "endpoint": sub["endpoint"],
                    "keys": {"p256dh": sub["p256dh"], "auth": sub["auth"]},
                },
                data=json.dumps(message, ensure_ascii=False),
                vapid_private_key=private_key,
                # webpush adds aud/exp to the dict it gets, so hand it a fresh one.
                vapid_claims={"sub": subject},
                ttl=PUSH_TTL_SEC,
                headers={"Urgency": "high"},
                timeout=10,
                requests_session=session,
            )
            return int(getattr(resp, "status_code", 201) or 201)
        except WebPushException as exc:
            status = getattr(exc.response, "status_code", None)
            return int(status) if status else 0
        except Exception:
            logger.exception("push send failed")
            return 0

    return send


def deliver(
    dsn: str,
    goals: Sequence[Goal],
    send: Sender,
    *,
    pool: ThreadPoolExecutor | None = None,
) -> int:
    """Push each goal to its followers; returns how many pushes were accepted."""
    from kalchas_db import push as store

    accepted = 0
    for goal in goals:
        subs = store.followers(dsn, goal.match_id)
        if not subs:
            continue
        try:
            scorer = store.latest_goal(dsn, goal.match_id, goal.side)
        except Exception:  # noqa: BLE001 -- the scorer's name is a nice-to-have
            scorer = None
        if scorer and _int(scorer.get("minute")) is not None:
            # Only name a scorer from an event close to now, never an earlier goal.
            current = _int(goal.minute.rstrip("'").split("+")[0]) or 0
            if abs(current - (_int(scorer.get("minute")) or 0)) > 5:
                scorer = None
        message = goal_message(goal, scorer)
        if pool is not None:
            statuses = list(pool.map(send, subs, [message] * len(subs)))
        else:
            statuses = [send(s, message) for s in subs]
        sent, failed, gone = [], [], []
        for sub, status in zip(subs, statuses, strict=True):
            if 200 <= status < 300:
                sent.append(sub["id"])
            elif status in (404, 410):
                gone.append(sub["id"])  # the browser unsubscribed or the key expired
            else:
                failed.append(sub["id"])
        store.record_results(dsn, sent=sent, failed=failed, gone=gone)
        accepted += len(sent)
        logger.info(
            "goal push %s %s: %s sent, %s failed, %s gone",
            goal.match_id,
            goal.side,
            len(sent),
            len(failed),
            len(gone),
        )
    return accepted


def tick(
    dsn: str,
    send: Sender,
    *,
    pool: ThreadPoolExecutor | None = None,
    notify: bool = True,
) -> int:
    """One look at the scores. ``notify=False`` only records them: the first
    look after a restart, so goals scored while the bot was down stay quiet."""
    from kalchas_db import push as store

    goals, marks = detect_goals(store.live_scores_with_marks(dsn))
    # Mark first: a crash mid-send then skips a push instead of repeating it.
    store.save_marks(dsn, marks)
    if not notify or not goals:
        return 0
    return deliver(dsn, goals, send, pool=pool)


async def push_goals_loop(dsn: str, private_key: str, subject: str | None = None) -> None:
    send = webpush_sender(private_key, subject or vapid_subject())
    pool = ThreadPoolExecutor(max_workers=SEND_WORKERS, thread_name_prefix="push")
    last_prune = 0.0
    first = True
    logger.info("goal push worker on (every %.0fs)", POLL_SEC)
    while True:
        try:
            await asyncio.to_thread(tick, dsn, send, pool=pool, notify=not first)
            first = False
            if time.monotonic() - last_prune > PRUNE_EVERY_SEC:
                from kalchas_db import push as store

                await asyncio.to_thread(store.prune, dsn)
                last_prune = time.monotonic()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("goal push tick failed")
        await asyncio.sleep(POLL_SEC)
