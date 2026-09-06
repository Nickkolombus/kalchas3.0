"""Alert outbox writers — scanner emits, bot claims."""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any, Protocol

logger = logging.getLogger("kalchas.scanner.outbox")


class AlertSink(Protocol):
    def emit(self, alert: dict[str, Any]) -> None: ...


@dataclass
class StdoutAlertSink:
    """MVP sink used when Postgres is not configured."""

    def emit(self, alert: dict[str, Any]) -> None:
        print(json.dumps(alert), flush=True)


@dataclass
class MemoryAlertSink:
    """In-process queue for tests and local bot handoff."""

    items: list[dict[str, Any]] = field(default_factory=list)

    def emit(self, alert: dict[str, Any]) -> None:
        self.items.append(dict(alert))


@dataclass
class PostgresAlertSink:
    """Write pending alerts for the bot delivery worker."""

    dsn: str
    also_stdout: bool = True

    def emit(self, alert: dict[str, Any]) -> None:
        from kalchas_db.sync import insert_pending_sync

        insert_pending_sync(self.dsn, alert)
        if self.also_stdout:
            print(json.dumps(alert), flush=True)


def default_sink() -> AlertSink:
    dsn = os.environ.get("DATABASE_URL") or os.environ.get("POSTGRES_URL")
    if dsn:
        logger.info("alert sink: postgres outbox")
        return PostgresAlertSink(dsn=dsn)
    logger.info("alert sink: stdout (set DATABASE_URL for outbox)")
    return StdoutAlertSink()
