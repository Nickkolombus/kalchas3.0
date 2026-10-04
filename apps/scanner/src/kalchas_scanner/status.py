"""Scanner status reporters."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger("kalchas.scanner.status")


@dataclass
class PostgresStatusReporter:
    dsn: str

    def report(self, **fields: Any) -> None:
        from kalchas_db.scanner_status import update_scanner_status_sync

        try:
            update_scanner_status_sync(self.dsn, **fields)
        except Exception:
            logger.exception("failed updating scanner status")


def default_status_reporter() -> PostgresStatusReporter | None:
    dsn = os.environ.get("DATABASE_URL") or os.environ.get("POSTGRES_URL")
    return PostgresStatusReporter(dsn) if dsn else None
