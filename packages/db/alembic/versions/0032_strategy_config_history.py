"""Strategy config history (placeholder).

The original migration was deployed to production without being committed.
0033 revises it, so this keeps the chain whole. It changes nothing: production
already ran the original, and no code in this repository reads its table.

Revision ID: 0032_strategy_config_history
Revises: 0031_visit_watchlist
Create Date: 2026-11-04
"""

from __future__ import annotations

from collections.abc import Sequence

revision: str = "0032_strategy_config_history"
down_revision: str | None = "0031_visit_watchlist"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
