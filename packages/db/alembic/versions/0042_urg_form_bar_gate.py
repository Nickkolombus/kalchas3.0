"""UrG (slot 1) alerts only when the team is at least 0.8 goals behind its Form Bar pace.

Adds one extra condition to Rule of 3: triggering ``delta_goal`` >= 0.8. A team
with no Form Bar reading (fewer than 5 recent games) is then blocked, and so is
one already ahead of its pace or done.

Motivation (review 2026-11-24, UrG alerts 12-23 Nov against the stamped
``payload.chance``): UrG alerts where the team was 1+ goal behind its form
scored 5% above the price (80 alerts), the rest 20% below (129 alerts); same
direction in both halves of the period. Neither beats the price clearly, so
segment later reviews at this migration's run time (the config history row).

Same row and history entry as an admin save, so the admin page shows it and
can remove it.

Revision ID: 0042_urg_form_bar_gate
Revises: 0041_once_per_half
Create Date: 2026-11-24
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
from sqlalchemy import text

revision: str = "0042_urg_form_bar_gate"
down_revision: str | None = "0041_once_per_half"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SLOT = 1
GAP = 0.8

_MATCH = """
    strategy_slot = :slot AND left_scope = 'triggering' AND left_metric = 'delta_goal'
    AND operator = '>=' AND right_kind = 'value' AND right_value = :gap
"""


def upgrade() -> None:
    from kalchas_db.settings import _slot_conditions, record_config_change

    conn = op.get_bind()
    params = {"slot": SLOT, "gap": GAP}
    if conn.execute(text(f"SELECT 1 FROM strategy_conditions WHERE {_MATCH}"), params).first():
        return
    before = _slot_conditions(conn, SLOT)
    conn.execute(
        text(
            """
            INSERT INTO strategy_conditions (
                strategy_slot, enabled, left_scope, left_metric, operator,
                right_kind, right_scope, right_metric, right_value, multiplier, sort_order
            )
            SELECT :slot, TRUE, 'triggering', 'delta_goal', '>=',
                   'value', 'opponent', 'delta_goal', :gap, 1.0,
                   COALESCE(MAX(sort_order) + 1, 0)
            FROM strategy_conditions WHERE strategy_slot = :slot
            """
        ),
        params,
    )
    after = _slot_conditions(conn, SLOT)
    record_config_change(conn, kind="conditions", slot=SLOT, before=before, after=after)


def downgrade() -> None:
    op.execute(
        text(f"DELETE FROM strategy_conditions WHERE {_MATCH}").bindparams(slot=SLOT, gap=GAP)
    )
