"""Alert outbox writers — scanner emits, bot claims."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Protocol


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
