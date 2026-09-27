"""Approval withdrawals — recorded as STANDING, never as a lifecycle transition.

Withdrawing an approval is not suspension, cancellation or termination. It is a
fact about the APPROVAL: the decision that was recorded no longer stands. This
table exists precisely so that fact can be recorded, checked and blocked on
without ever writing to `agreements.status`. The service appends ONE history row
to `agreement_events` for it, with `from_status == to_status`, so the history
shows the withdrawal without it ever looking like a lifecycle transition.

## Platform catalog grants, not RLS — same reasoning as `cg_0001`

A withdrawal of a vendor↔operator approval decision is a control-plane fact
with no `tenant_id` to scope by. `platform_api` and `app_admin` get SELECT and
INSERT; `app_user` is REVOKEd everywhere (hard rule 27).

## Append-only, enforced by its own trigger and its own message

`agreement_events` already has `refuse_history_rewrite`, but its exception
message names `agreement_events` by name — reusing it here would raise an
exception about the wrong table. This migration defines a SECOND function,
`refuse_withdrawal_rewrite`, so the message an administrator sees always names
the table that actually refused the write.

## `UNIQUE(agreement_id, approval_decision_ref)`

One withdrawal per decision. A caller that tries to record a second withdrawal
against a decision already withdrawn hits this constraint before the service
even needs to check for one — the same defence in depth `uq_agreement_events_
sequence` gives the history table in `cg_0001`.

Revision ID: cg_0002_approval_withdrawals
Revises: cg_0001_agreements
Create Date: 2026-09-27
"""

from __future__ import annotations

import sqlalchemy as sa
from dotmac_kernel.migrations.verify import require_prerequisites
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "cg_0002_approval_withdrawals"
down_revision = "cg_0001_agreements"
branch_labels = None
depends_on = None

# Same two request-time effects `cg_0001` verified, verified again here for the
# same reason: this is DDL that runs at deploy time, and deploy is the last
# moment at which a missing ledger is a failed migration rather than a failed
# transition in production. No new prerequisite is added — this table uses
# neither effect differently than the tables `cg_0001` already created.
COMMON_REQUIRES = ("idempotency_ledger.v1", "platform_audit_log.v1")
REQUIRES = COMMON_REQUIRES

# A literal, not `module_schema("agreements")` — see `cg_0001`'s docstring: a
# migration is a frozen historical artifact, and the static gate reads this
# file without importing it.
_SCHEMA = "mod_agreements"


def upgrade() -> None:
    require_prerequisites(op.get_bind(), REQUIRES)

    op.create_table(
        "agreement_approval_withdrawals",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False
        ),
        sa.Column("agreement_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("approval_request_ref", sa.String(length=200), nullable=False),
        sa.Column("approval_decision_ref", sa.String(length=200), nullable=False),
        sa.Column("approval_policy_code", sa.String(length=120), nullable=False),
        sa.Column("approval_policy_version", sa.Integer(), nullable=False),
        sa.Column("subject_ref", sa.String(length=200), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("withdrawal_ref", sa.String(length=200), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("withdrawn_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status_at_record", sa.String(length=24), nullable=False),
        sa.Column("approval_carried", sa.Boolean(), nullable=False),
        sa.Column("command_id", sa.String(length=200), nullable=False),
        sa.Column("actor_ref", sa.String(length=200), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["agreement_id"],
            ["mod_agreements.agreements.id"],
            name="fk_agreement_approval_withdrawals_agreement_id",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "withdrawal_ref", name="uq_agreement_approval_withdrawals_ref"
        ),
        sa.UniqueConstraint(
            "agreement_id",
            "approval_decision_ref",
            name="uq_agreement_approval_withdrawals_decision",
        ),
        sa.CheckConstraint(
            "reason <> ''", name="ck_agreement_approval_withdrawals_reason"
        ),
        schema="mod_agreements",
    )
    op.create_index(
        "ix_agreement_approval_withdrawals_agreement_id",
        "agreement_approval_withdrawals",
        ["agreement_id"],
        schema="mod_agreements",
    )

    # ── Append-only, its own function so the message names this table ───────
    op.execute(
        """
        CREATE FUNCTION mod_agreements.refuse_withdrawal_rewrite() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION
                'agreement_approval_withdrawals is append-only; a withdrawal is '
                'never edited or removed once recorded'
                USING ERRCODE = '23514';
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER refuse_withdrawal_rewrite
        BEFORE UPDATE OR DELETE ON mod_agreements.agreement_approval_withdrawals
        FOR EACH ROW EXECUTE FUNCTION mod_agreements.refuse_withdrawal_rewrite();
        """
    )
    # TRUNCATE bypasses row triggers; a statement trigger closes that path for
    # every role that could otherwise empty the table in one statement.
    op.execute(
        """
        CREATE TRIGGER refuse_withdrawal_truncate
        BEFORE TRUNCATE ON mod_agreements.agreement_approval_withdrawals
        FOR EACH STATEMENT EXECUTE FUNCTION mod_agreements.refuse_withdrawal_rewrite();
        """
    )

    op.execute(
        "GRANT SELECT, INSERT ON mod_agreements.agreement_approval_withdrawals "
        "TO platform_api;"
    )
    op.execute(
        "GRANT SELECT, INSERT ON mod_agreements.agreement_approval_withdrawals "
        "TO app_admin;"
    )
    op.execute(
        "REVOKE ALL ON mod_agreements.agreement_approval_withdrawals " "FROM app_user;"
    )


def downgrade() -> None:
    # Withdrawal rows are immutable evidence that BLOCKS approve, activate and
    # reinstate. Dropping them would silently make every withdrawn agreement
    # approvable again, so the downgrade refuses while any exist (the same
    # guard as `ap_0003`'s). Lock first so no row can be inserted between the
    # check and the drop.
    op.execute(
        "LOCK TABLE mod_agreements.agreement_approval_withdrawals "
        "IN ACCESS EXCLUSIVE MODE;"
    )
    has_evidence = (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT EXISTS "
                "(SELECT 1 FROM mod_agreements.agreement_approval_withdrawals)"
            )
        )
        .scalar_one()
    )
    if has_evidence:
        raise RuntimeError(
            "cannot downgrade cg_0002: mod_agreements.agreement_approval_withdrawals "
            "contains immutable withdrawal evidence"
        )
    op.execute(
        "DROP TRIGGER IF EXISTS refuse_withdrawal_truncate "
        "ON mod_agreements.agreement_approval_withdrawals;"
    )
    op.execute(
        "DROP TRIGGER IF EXISTS refuse_withdrawal_rewrite "
        "ON mod_agreements.agreement_approval_withdrawals;"
    )
    op.execute("DROP FUNCTION IF EXISTS mod_agreements.refuse_withdrawal_rewrite();")
    op.drop_index(
        "ix_agreement_approval_withdrawals_agreement_id",
        "agreement_approval_withdrawals",
        schema="mod_agreements",
    )
    op.drop_table("agreement_approval_withdrawals", schema="mod_agreements")
