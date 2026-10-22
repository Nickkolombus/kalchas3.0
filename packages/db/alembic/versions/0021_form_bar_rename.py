"""Rename the seeded strategy_rules row for slot 3: League Bar -> Form Bar.

The code-level default (``DEFAULT_RULES`` in
``kalchas_core.alert_outcomes.rules``) only takes effect where no DB row
exists. Slot 3 was seeded by 0001_baseline and has had a live row ever
since, so the rename needs its own migration to actually reach it -- same
reason the admin-tuned ``strategy_thresholds``/``strategy_weights`` rows
don't pick up new code defaults on their own.

Revision ID: 0021_form_bar_rename
Revises: 0020_live_visitors
Create Date: 2026-10-22
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0021_form_bar_rename"
down_revision: str | None = "0020_live_visitors"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE strategy_rules
        SET strategy_name = 'Form Bar'
        WHERE strategy_slot = 3 AND strategy_name = 'League Bar';
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE strategy_rules
        SET strategy_name = 'League Bar'
        WHERE strategy_slot = 3 AND strategy_name = 'Form Bar';
        """
    )
