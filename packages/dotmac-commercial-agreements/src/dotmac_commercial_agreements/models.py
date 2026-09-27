"""The agreement tables, bound to the `mod_agreements` schema (ADR-0006 D1).

Platform catalog tables: no `tenant_id`, no RLS, `app_user` REVOKEd. A
vendor↔operator commercial agreement is a control-plane fact about the fleet;
no product data plane holds one, and ADR-0057 § 7 declares the plane from that
consumer rather than discovering it from a missing column.

## Three tables, because three things have different lifetimes

- `agreements` — the header and its lifecycle. Mutable in exactly the ways the
  lifecycle allows, and versioned so a stale caller cannot overwrite a decision.
- `agreement_lines` — what is promised. Frozen at proposal and never rewritten;
  an amendment creates a NEW agreement version rather than editing these.
- `agreement_events` — the append-only transition and evidence history. Written
  once per transition, never updated, never deleted, enforced by a trigger
  rather than only by the service.

## No foreign key leaves this schema

`counterparty_ref`, `release_ref`, `offer_ref` and `approval_decision_ref` are
all bare strings with no constraint. That is deliberate three times over:

1. ADR-0006 D1 — a cross-lineage FK splices two independently released
   migration lineages and makes either un-releasable without the other.
2. ADR-0019 § 1 and ruling A3 — `vendor_accounts` must not retire into kernel
   `Party`, so this module holds an opaque counterparty reference and never
   resolves it.
3. An agreement is a legal record that must outlive the rows it references. A
   release superseded, an approval policy retired, or a counterparty record
   merged must not be able to delete or invalidate an executed agreement.

## `accepted_snapshot` is the immutable copy, and `content_hash` is its digest

The snapshot is stored as JSONB rather than reconstructed from the lines on
demand, because reconstruction reads TODAY's lines and the whole point is to
record what was accepted THEN. `content_hash` is the digest of exactly that
document, and it is what approval evidence must bind to — so a change to terms
after approval makes the prior approval stale rather than transferable
(ADR-0026 § 2).

## `record_version` exists because two screens are the ordinary case

Every transition command carries the version the caller believed it was acting
on, and the service refuses a mismatch. Without it, two operators suspending and
reinstating one agreement from two tabs produces a last-writer-wins outcome in
which one operator's decision is silently discarded and the append-only history
records both as successful.

## Status is text with no CHECK

ADR-0008's reason, applied here: adding a lifecycle member should cost a module
release, not an `ALTER TYPE` on every deployment. The legality of a transition
is proven by the service's guard and by the append-only history, both of which
are testable; a CHECK would restate the value set without restating a single
transition rule.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from dotmac_kernel.models import Base, TimestampMixin, uuid_pk
from dotmac_kernel.namespaces import module_schema, schema_table_args
from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

#: JSONB in production, portable `JSON` everywhere else. The variant is not a
#: convenience: the module's logic tests run on in-memory SQLite (the repo's
#: testing model — `tests/unit` is SQLite-fast, tenancy and grants are proven on
#: real Postgres), and a bare `JSONB` column makes the whole model layer
#: unimportable there. The MIGRATION names `JSONB` unconditionally, because the
#: production dialect is not in question — only the test dialect is.
_JSON_DOC = JSON().with_variant(JSONB(), "postgresql")

#: Derived from the allocated short code — never a literal here. The migration
#: uses a literal on purpose (a frozen historical artifact); runtime models
#: resolve through the ledger so drift between the two is a boot failure.
SCHEMA: str = module_schema("agreements")

_AGREEMENTS = "agreements"
_LINES = "agreement_lines"
_EVENTS = "agreement_events"
_APPROVAL_WITHDRAWALS = "agreement_approval_withdrawals"


class AgreementStatus(StrEnum):
    """The commercial-agreement lifecycle, as a value object.

    ONE definition, shared by persistence and by every owner that reads the
    contract — the typed-contracts standard's requirement, and the reason this
    is not two constants that drift.

    `PROPOSED` is the source implementation's `pending_approval`, renamed to the
    vocabulary ADR-0057 records. The rename is safe precisely because this is a
    greenfield lineage with no rows to migrate: no deployment has ever stored
    `pending_approval` under `mod_agreements`.

    **Commercial approval and operational activation are different decisions and
    different states.** That separation is the source's, and it is the single
    most load-bearing thing in this enum: `APPROVED` means the required people
    said yes; `ACTIVE` means the contracted activation rule was satisfied. An
    implementation that collapses them cannot express "signed but not yet
    countersigned", which is where most commercial disputes live.
    """

    DRAFT = "draft"
    PROPOSED = "proposed"
    APPROVED = "approved"
    ACTIVE = "active"
    SUSPENDED = "suspended"
    TERMINATED = "terminated"
    EXPIRED = "expired"
    CANCELLED = "cancelled"
    SUPERSEDED = "superseded"


#: Statuses from which no further transition is legal. Named once so the guard
#: and the tests cannot disagree about which they are.
TERMINAL_STATUSES: frozenset[str] = frozenset(
    {
        AgreementStatus.TERMINATED.value,
        AgreementStatus.EXPIRED.value,
        AgreementStatus.CANCELLED.value,
        AgreementStatus.SUPERSEDED.value,
    }
)


class Agreement(Base, TimestampMixin):
    """A commercial agreement header, its accepted snapshot and its lifecycle."""

    __tablename__ = _AGREEMENTS
    __table_args__ = (
        UniqueConstraint("reference", name="uq_agreements_reference"),
        UniqueConstraint(
            "agreement_family_id",
            "agreement_version",
            name="uq_agreements_family_version",
        ),
        CheckConstraint("agreement_version >= 1", name="ck_agreements_version"),
        CheckConstraint("record_version >= 1", name="ck_agreements_record_version"),
        CheckConstraint("expiry_date >= effective_date", name="ck_agreements_period"),
        schema_table_args(SCHEMA),
    )

    id: Mapped[UUID] = uuid_pk()

    #: The human-readable reference an operator quotes on a call. Unique, and
    #: supplied by the caller rather than generated here — `dotmac-numbering`
    #: owns allocation of numbered series, and generating one here would make
    #: this module a second numbering authority.
    reference: Mapped[str] = mapped_column(String(120), nullable=False)

    #: Stable across amendments: every version of one commercial relationship
    #: shares this id, so "show me this agreement's history" is one query and
    #: not a recursive walk of `supersedes_id`.
    agreement_family_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    agreement_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    #: Opaque. Never resolved, dereferenced or joined — ADR-0019 § 1, ruling A3.
    counterparty_ref: Mapped[str] = mapped_column(
        String(200), nullable=False, index=True
    )

    #: An open registered string, not an enum (ADR-0008). A product names its own
    #: agreement types — reseller, OEM, direct, pilot — without a kernel change.
    agreement_type: Mapped[str] = mapped_column(String(120), nullable=False)

    status: Mapped[str] = mapped_column(
        String(24), nullable=False, default=AgreementStatus.DRAFT.value, index=True
    )

    effective_date: Mapped[date] = mapped_column(Date, nullable=False)
    expiry_date: Mapped[date] = mapped_column(Date, nullable=False)

    #: The immutable accepted commercial snapshot, frozen at proposal. NULL only
    #: while `DRAFT` — a proposed agreement always has one.
    accepted_snapshot: Mapped[dict[str, Any] | None] = mapped_column(_JSON_DOC)
    #: The digest of exactly that document. Approval evidence binds to it.
    content_hash: Mapped[str | None] = mapped_column(String(64))

    #: Recorded at proposal so the decision stays explainable after the policy
    #: changes. This module never evaluates a policy — `dotmac-approvals` does.
    approval_policy_code: Mapped[str | None] = mapped_column(String(120))
    approval_policy_version: Mapped[int | None] = mapped_column(Integer)
    #: An opaque handle into the deciding owner's record. Stored so an auditor
    #: can dereference it; never dereferenced here.
    approval_decision_ref: Mapped[str | None] = mapped_column(String(200))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    activation_rule: Mapped[str | None] = mapped_column(String(120))
    activation_reference: Mapped[str | None] = mapped_column(String(200))
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    suspension_reason: Mapped[str | None] = mapped_column(Text)
    termination_reason: Mapped[str | None] = mapped_column(Text)
    #: The reason for whichever transition happened most recently, kept for the
    #: header view. The AUTHORITATIVE per-transition reason is in the events
    #: table — this column is a convenience that a reader must not treat as
    #: history, which is why the docstring says so and the events are append-only.
    last_reason: Mapped[str | None] = mapped_column(Text)

    #: Amendment / supersession. Both bare UUIDs within this schema's own table,
    #: so they ARE constrained — unlike every reference that leaves it.
    supersedes_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(f"{SCHEMA}.{_AGREEMENTS}.id", ondelete="RESTRICT")
    )
    superseded_by_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(f"{SCHEMA}.{_AGREEMENTS}.id", ondelete="RESTRICT")
    )

    #: Optimistic concurrency. Incremented by the service on every transition.
    record_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    lines: Mapped[list[AgreementLine]] = relationship(
        lambda: AgreementLine,
        back_populates="agreement",
        cascade="all, delete-orphan",
        order_by=lambda: AgreementLine.line_no,
    )
    events: Mapped[list[AgreementEvent]] = relationship(
        lambda: AgreementEvent,
        back_populates="agreement",
        order_by=lambda: AgreementEvent.sequence,
    )
    #: Deliberately NO `approval_withdrawals` relationship. Every read of "does
    #: a withdrawal exist" goes through `service._has_withdrawal`'s explicit
    #: `EXISTS`-shaped query in the CALLER's own session, taken after the row's
    #: FOR-UPDATE lock — an ORM collection populated before that lock can be a
    #: stale cached list, and a guard that trusted it could approve a row a
    #: concurrent withdrawal had just recorded.


class AgreementLine(Base, TimestampMixin):
    """One promised line: an opaque product/release/offer reference, the
    capability it entitles, a quantity, and the terms frozen at proposal."""

    __tablename__ = _LINES
    __table_args__ = (
        UniqueConstraint("agreement_id", "line_no", name="uq_agreement_lines_no"),
        CheckConstraint("quantity > 0", name="ck_agreement_lines_quantity"),
        schema_table_args(SCHEMA),
    )

    id: Mapped[UUID] = uuid_pk()
    agreement_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{SCHEMA}.{_AGREEMENTS}.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    line_no: Mapped[int] = mapped_column(Integer, nullable=False)

    #: The product whose declared catalogue `capability_code` was validated
    #: against. Persisted for the reason `dotmac-entitlement-allocation` records:
    #: a capability code is only meaningful against the product that declares it,
    #: so without this column a promise validated for product A could be read as
    #: a promise for product B — every code still resolves, in the wrong
    #: catalogue.
    product_code: Mapped[str] = mapped_column(String(120), nullable=False)

    #: Opaque references. `dotmac-release-catalog` owns release definitions;
    #: ruling A2(b) detached the offer catalogue. No FK — see the module
    #: docstring.
    release_ref: Mapped[str | None] = mapped_column(String(200))
    offer_ref: Mapped[str | None] = mapped_column(String(200))

    #: A plain string, not an enum: the vocabulary belongs to the products, and
    #: this module is deliberately not where new codes are invented.
    capability_code: Mapped[str] = mapped_column(String(120), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    #: Exact money as text, never float (ADR-0003). Frozen at proposal. This
    #: module performs no arithmetic on it — totals belong to billing.
    unit_amount: Mapped[str] = mapped_column(String(40), nullable=False)
    unit_currency_code: Mapped[str] = mapped_column(String(3), nullable=False)

    agreement: Mapped[Agreement] = relationship(
        lambda: Agreement, back_populates="lines"
    )


class AgreementEvent(Base, TimestampMixin):
    """One append-only transition record with the evidence that justified it.

    Append-only is enforced by a trigger, not only by this module refusing to
    write an UPDATE. A service rule cannot police a path that never calls the
    service, and an evidence history that raw SQL can rewrite is not evidence.
    """

    __tablename__ = _EVENTS
    __table_args__ = (
        UniqueConstraint(
            "agreement_id", "sequence", name="uq_agreement_events_sequence"
        ),
        CheckConstraint("sequence >= 1", name="ck_agreement_events_sequence"),
        schema_table_args(SCHEMA),
    )

    id: Mapped[UUID] = uuid_pk()
    agreement_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{SCHEMA}.{_AGREEMENTS}.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    #: Dense and per-agreement, so a gap is detectable. `created_at` alone would
    #: not be: two transitions in one transaction share a timestamp.
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)

    event_type: Mapped[str] = mapped_column(String(60), nullable=False)
    from_status: Mapped[str | None] = mapped_column(String(24))
    to_status: Mapped[str] = mapped_column(String(24), nullable=False)

    #: The actor as the CALLER identifies them — opaque, like every other
    #: cross-boundary reference here. This module owns no identity.
    actor_ref: Mapped[str | None] = mapped_column(String(200))
    reason: Mapped[str | None] = mapped_column(Text)

    #: The evidence document for this transition: approval evidence, activation
    #: evidence, the impact acknowledgement, or the amendment linkage. Never a
    #: secret and never bytes — `dotmac-files` owns bytes (ADR-0022).
    evidence: Mapped[dict[str, Any] | None] = mapped_column(_JSON_DOC)

    #: The idempotency key of the command that produced this event, so a replay
    #: is explainable rather than merely silent.
    command_id: Mapped[str] = mapped_column(String(200), nullable=False)

    agreement: Mapped[Agreement] = relationship(
        lambda: Agreement, back_populates="events"
    )


class AgreementApprovalWithdrawal(Base, TimestampMixin):
    """One recorded withdrawal of an approval decision, as STANDING — never a
    lifecycle transition.

    Distinct from `AgreementEvent` on purpose: an approval withdrawal is a fact
    about the APPROVAL, not a transition of the agreement's own status, and it
    must never appear in the append-only history that records what the
    agreement's status did. Recording one here BLOCKS a later approve, activate
    or reinstate (`service._require_no_withdrawal`); it never cancels,
    suspends or terminates, and it never rewrites `agreements.status`.

    Append-only, enforced by its own trigger with its own message
    (`refuse_withdrawal_rewrite`) — reusing `agreement_events`'s trigger would
    raise an exception naming the wrong table.
    """

    __tablename__ = _APPROVAL_WITHDRAWALS
    __table_args__ = (
        UniqueConstraint(
            "withdrawal_ref", name="uq_agreement_approval_withdrawals_ref"
        ),
        UniqueConstraint(
            "agreement_id",
            "approval_decision_ref",
            name="uq_agreement_approval_withdrawals_decision",
        ),
        CheckConstraint(
            "reason <> ''", name="ck_agreement_approval_withdrawals_reason"
        ),
        schema_table_args(SCHEMA),
    )

    id: Mapped[UUID] = uuid_pk()
    agreement_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{SCHEMA}.{_AGREEMENTS}.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    #: The idempotency binding this command locks to. Every field here is
    #: checked, in order, before a withdrawal is recorded (`service.
    #: record_approval_withdrawal`).
    approval_request_ref: Mapped[str] = mapped_column(String(200), nullable=False)
    approval_decision_ref: Mapped[str] = mapped_column(String(200), nullable=False)
    approval_policy_code: Mapped[str] = mapped_column(String(120), nullable=False)
    approval_policy_version: Mapped[int] = mapped_column(Integer, nullable=False)
    subject_ref: Mapped[str] = mapped_column(String(200), nullable=False)
    #: Bare hex, the form CA already stores on `Agreement.content_hash`.
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    withdrawal_ref: Mapped[str] = mapped_column(String(200), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    withdrawn_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    #: The agreement's status at the moment this was recorded. Historical
    #: colour only — recording never changes `agreements.status`.
    status_at_record: Mapped[str] = mapped_column(String(24), nullable=False)
    #: True when the withdrawn decision matched the agreement's OWN
    #: `approval_decision_ref` — the case where the decision this withdrawal
    #: names actually carried the agreement's approval.
    approval_carried: Mapped[bool] = mapped_column(Boolean, nullable=False)

    command_id: Mapped[str] = mapped_column(String(200), nullable=False)
    actor_ref: Mapped[str | None] = mapped_column(String(200))

    #: Deliberately no `agreement` relationship. Nothing joins from a
    #: withdrawal row back to its agreement in this module — the check runs
    #: the other direction, `service._has_withdrawal(session, agreement_id)`.


__all__ = [
    "SCHEMA",
    "TERMINAL_STATUSES",
    "Agreement",
    "AgreementApprovalWithdrawal",
    "AgreementEvent",
    "AgreementLine",
    "AgreementStatus",
]
