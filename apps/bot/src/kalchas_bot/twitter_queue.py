"""Serial background queue for X posts.

Delivery hands a tweet to the queue and moves on, so a slow or hung X can never
hold up Telegram or Discord. One worker runs the jobs in order, which keeps an
alert's tweet ahead of its outcome reply.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Sequence
from typing import Any

from kalchas_bot.twitter_channel import TwitterCredentials, post_alert_tweet, reply_tweet

logger = logging.getLogger("kalchas.bot.twitter")

Job = Callable[[], Awaitable[None]]


class TwitterQueue:
    def __init__(self, creds: TwitterCredentials, pool: Any, *, maxsize: int = 100) -> None:
        self.creds = creds
        self.pool = pool
        self._jobs: asyncio.Queue[Job] = asyncio.Queue(maxsize=maxsize)
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self.run())

    def submit_alert(
        self,
        *,
        alert_ids: Sequence[int],
        caption: str,
        match_id: object,
        photo_bytes: bytes | None,
    ) -> None:
        ids = [int(alert_id) for alert_id in alert_ids]
        self._put(lambda: self._post_alert(ids, caption, match_id, photo_bytes), "alert tweet")

    def submit_outcome(self, *, alert_ids: Sequence[int], text: str) -> None:
        ids = [int(alert_id) for alert_id in alert_ids]
        self._put(lambda: self._post_outcome(ids, text), "outcome reply")

    def _put(self, job: Job, label: str) -> None:
        try:
            self._jobs.put_nowait(job)
        except asyncio.QueueFull:
            logger.warning("twitter queue full, dropping %s", label)

    async def _post_alert(
        self,
        alert_ids: list[int],
        caption: str,
        match_id: object,
        photo_bytes: bytes | None,
    ) -> None:
        from kalchas_db.alerts import mark_twitter_sent

        tweet_id = await post_alert_tweet(
            self.creds, caption=caption, match_id=match_id, photo_bytes=photo_bytes
        )
        if tweet_id is None:
            return
        async with self.pool.acquire() as conn:
            for alert_id in alert_ids:
                await mark_twitter_sent(conn, alert_id, tweet_id)

    async def _post_outcome(self, alert_ids: list[int], text: str) -> None:
        from kalchas_db.alerts import find_tweet_id

        # Looked up now, not at claim time: the alert tweet may only just have landed.
        async with self.pool.acquire() as conn:
            tweet_id = await find_tweet_id(conn, alert_ids)
        if tweet_id is None:
            return
        await reply_tweet(self.creds, text, tweet_id)

    async def _run_job(self, job: Job) -> None:
        try:
            await job()
        except Exception:
            logger.exception("twitter job failed")
        finally:
            self._jobs.task_done()

    async def run(self) -> None:
        while True:
            await self._run_job(await self._jobs.get())

    async def drain(self) -> None:
        """Run whatever is queued, inline. For tests; production uses ``run``."""
        while not self._jobs.empty():
            await self._run_job(self._jobs.get_nowait())
