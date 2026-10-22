"""Form Bar becomes goals-behind-expected-pace: reset slot 3's settings.

The bar's scale changed from a -10..+10 lift score to goals behind pace, so
the stored slot-3 settings no longer mean anything:

* threshold 6.0 (score) -> 1.0 (goal behind pace);
* cooldown bypass 4.0 -> NULL (the gap rises too slowly to ever bypass);
* every ``strategy_weights`` row for ``delta_goal`` is dropped -- the
  coefficients they tuned no longer exist;
* the strategy is switched off until an admin turns it on.

Also seeds four switched-off extra conditions for slot 3 -- triggering team's
Δ10′, Δ5′, UrG and Omega -- so an admin can require pressure alongside the
pace gap by ticking a box and setting a value, rather than building each row.
Values start at each strategy's own default fire level. Skipped per metric
where a slot-3 row for it already exists.

Revision ID: 0022_form_bar_pace
Revises: 0021_form_bar_rename
Create Date: 2026-10-23
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0022_form_bar_pace"
down_revision: str | None = "0021_form_bar_rename"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# (metric, starting value, sort order)
_CONDITIONS = (
    ("pressure_index", 75.0, 0),
    ("delta_5min", 7.0, 1),
    ("rule_of_three", 1.5, 2),
    ("omega", 30.0, 3),
)


def upgrade() -> None:
    op.execute(
        """
        UPDATE strategy_rules
        SET enabled = FALSE, cooldown_bypass_delta = NULL
        WHERE strategy_slot = 3;

        INSERT INTO strategy_thresholds (strategy_slot, threshold, updated_at)
        VALUES (3, 1.0, NOW())
        ON CONFLICT (strategy_slot) DO UPDATE SET
            threshold = EXCLUDED.threshold,
            updated_at = NOW();

        DELETE FROM strategy_weights WHERE strategy_key = 'delta_goal';
        """
    )
    insert = sa.text(
        """
        INSERT INTO strategy_conditions (
            strategy_slot, enabled, left_scope, left_metric, operator,
            right_kind, right_scope, right_metric, right_value, multiplier, sort_order
        )
        SELECT 3, FALSE, 'triggering', :metric, '>=',
               'value', 'opponent', :metric, :value, 1, :sort_order
        WHERE NOT EXISTS (
            SELECT 1 FROM strategy_conditions
            WHERE strategy_slot = 3 AND left_metric = :metric
        );
        """
    )
    for metric, value, order in _CONDITIONS:
        op.execute(insert.bindparams(metric=metric, value=value, sort_order=order))


def downgrade() -> None:
    op.execute(
        """
        DELETE FROM strategy_conditions
        WHERE strategy_slot = 3 AND enabled = FALSE
          AND left_scope = 'triggering' AND right_kind = 'value'
          AND left_metric IN ('pressure_index', 'delta_5min', 'rule_of_three', 'omega');

        UPDATE strategy_thresholds SET threshold = 6.0, updated_at = NOW()
        WHERE strategy_slot = 3;

        UPDATE strategy_rules SET enabled = TRUE, cooldown_bypass_delta = 4.0
        WHERE strategy_slot = 3;
        """
    )
