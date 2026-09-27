"""The versioned facts this module publishes, as values.

An adopting assembly reads these off the platform outbox and reacts —
`dotmac-entitlement-allocation` stages an allocation when an agreement
activates, `dotmac-licensing` issues against that allocation, billing raises the
first invoice. **This module calls none of them.** It records a decision and
emits the fact; the assembly routes it. ADR-0026 § 6 states the rule for
approvals and ADR-0024 states it generally: an owner emits, a consumer's own
authoritative service acts.

## Why the version is in the event type

`agreement.activated.v1`, not `agreement.activated`. A consumer pins a shape.
When the shape changes incompatibly, `v2` is emitted ALONGSIDE `v1` for a
migration window, and a consumer that never migrated keeps working instead of
silently mis-parsing. An unversioned type makes that impossible to do safely,
because there is no way to emit both.

The `v` is part of the string rather than a separate field for the same reason a
routing key is: a relay filters on the type, and a consumer that has to parse a
payload to discover it cannot subscribe to only what it understands.

## The payload carries references, never resolved documents

Every fact names `agreement_id`, `counterparty_ref` and `content_hash`, and
stops. It does not embed the counterparty's name, the release's manifest, or the
approval's policy document — those belong to their owners, and copying them into
an event makes this module a stale second source of each. A consumer that needs
the name asks the owner.

`content_hash` is in every payload deliberately: it is what lets a consumer
prove the fact it is acting on describes the same terms it last saw.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from typing import ClassVar, Final
from uuid import UUID

from dotmac_commercial_agreements.ports import (
    DEFAULT_AGREEMENT_PAGE_SIZE,
    MAX_AGREEMENT_PAGE_SIZE,
    AgreementError,
    derive_end_exclusive,
)

# ── Event types ─────────────────────────────────────────────────────────────

AGREEMENT_PROPOSED_V1: Final[str] = "agreement.proposed.v1"
AGREEMENT_APPROVED_V1: Final[str] = "agreement.approved.v1"
AGREEMENT_ACTIVATED_V1: Final[str] = "agreement.activated.v1"
AGREEMENT_AMENDED_V1: Final[str] = "agreement.amended.v1"
AGREEMENT_SUSPENDED_V1: Final[str] = "agreement.suspended.v1"
AGREEMENT_REINSTATED_V1: Final[str] = "agreement.reinstated.v1"
AGREEMENT_TERMINATED_V1: Final[str] = "agreement.terminated.v1"
AGREEMENT_EXPIRED_V1: Final[str] = "agreement.expired.v1"
AGREEMENT_REJECTED_V1: Final[str] = "agreement.rejected.v1"
AGREEMENT_CANCELLED_V1: Final[str] = "agreement.cancelled.v1"
#: Recording a withdrawal is NOT a lifecycle transition — `from_status` and
#: `to_status` on the emitted history row are equal, and `agreements.status`
#: never changes. The fact still needs its own type because a consumer of
#: `agreement.approved.v1` must be told the approval it saw no longer stands.
AGREEMENT_APPROVAL_WITHDRAWN_V1: Final[str] = "agreement.approval_withdrawn.v1"

#: Every type this module can emit. A consumer building a subscription set reads
#: this rather than a hand-kept list that drifts, and the module's own test
#: asserts the set matches what the service actually emits — a published
#: vocabulary nobody checks is the same defect ADR-0008 names for declarations.
PUBLISHED_EVENT_TYPES: Final[frozenset[str]] = frozenset(
    {
        AGREEMENT_PROPOSED_V1,
        AGREEMENT_APPROVED_V1,
        AGREEMENT_ACTIVATED_V1,
        AGREEMENT_AMENDED_V1,
        AGREEMENT_SUSPENDED_V1,
        AGREEMENT_REINSTATED_V1,
        AGREEMENT_TERMINATED_V1,
        AGREEMENT_EXPIRED_V1,
        AGREEMENT_REJECTED_V1,
        AGREEMENT_CANCELLED_V1,
        AGREEMENT_APPROVAL_WITHDRAWN_V1,
    }
)


# ── Views ───────────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class PromisedLine:
    """One line of what an agreement promises, as a value.

    This is the shape `dotmac-entitlement-allocation` reads to build its
    `ContractSnapshot`. It carries `product_code` beside `capability_code` for
    the reason that module records: a capability code is only meaningful against
    the product that declares it.
    """

    line_no: int
    product_code: str
    capability_code: str
    quantity: int
    unit_amount: str
    unit_currency_code: str
    release_ref: str | None = None
    offer_ref: str | None = None


@dataclass(frozen=True, slots=True)
class AgreementView:
    """The agreement as a caller sees it. No ORM object leaves this module.

    Returning a detached ORM row would let a caller lazy-load into a session it
    does not own, and would make every column a public contract by accident.
    ``expiry_date`` preserves a1's inclusive end; ``end_exclusive`` is the
    explicit derived boundary for consumers that work with half-open ranges.
    """

    id: UUID
    reference: str
    agreement_family_id: UUID
    agreement_version: int
    counterparty_ref: str
    agreement_type: str
    status: str
    effective_date: date
    expiry_date: date
    content_hash: str | None
    record_version: int
    approval_policy_code: str | None = None
    approval_policy_version: int | None = None
    approval_decision_ref: str | None = None
    approved_at: datetime | None = None
    activation_rule: str | None = None
    activated_at: datetime | None = None
    supersedes_id: UUID | None = None
    superseded_by_id: UUID | None = None
    lines: tuple[PromisedLine, ...] = ()
    #: True once ANY approval withdrawal has been recorded for this agreement.
    #: Blocks approve, activate and reinstate — never a lifecycle status.
    approval_withdrawn: bool = False

    @property
    def end_exclusive(self) -> date:
        """The first date outside the inclusive agreement period."""
        return derive_end_exclusive(self.expiry_date)


@dataclass(frozen=True, slots=True)
class AgreementPage:
    """A bounded keyset page of detached agreement views.

    ``next_after`` is the last id in ``items`` only when another row exists.
    Pass it back unchanged; it is a stable UUID keyset, not an offset or a row
    count that moves when the estate changes.
    """

    items: tuple[AgreementView, ...]
    next_after: UUID | None


@dataclass(frozen=True, slots=True)
class TransitionRecord:
    """One entry of the append-only history, as a value."""

    sequence: int
    event_type: str
    from_status: str | None
    to_status: str
    occurred_at: datetime
    actor_ref: str | None
    reason: str | None
    command_id: str


# ── Read contracts ──────────────────────────────────────────────────────────


class AgreementAction(StrEnum):
    """A lifecycle command that may legally be issued against an agreement.

    Owner-derived, always. Which of these is available is a function of the
    current status, whether a snapshot has been frozen, and whether the
    agreement has already been superseded — and the module answers it from the
    SAME table its write guards enforce (`service._PERMITTED_FROM`). A row
    action that decided its own eligibility downstream would be a second, weaker
    copy of the lifecycle, and the two would disagree the moment a status moved
    between the render and the click.
    """

    PROPOSE = "propose"
    APPROVE = "approve"
    REJECT = "reject"
    ACTIVATE = "activate"
    SUSPEND = "suspend"
    REINSTATE = "reinstate"
    CANCEL = "cancel"
    TERMINATE = "terminate"
    EXPIRE = "expire"
    AMEND = "amend"


@dataclass(frozen=True, slots=True)
class AgreementDetail:
    """One agreement, its lifecycle timeline, and what may be done to it next.

    ## Expected-version conflict handling is part of the READ

    `expected_version` and `expected_status` are what a surface hands straight
    back on the command it issues. Every lifecycle command already carries them
    and `service._require_expected` refuses on a mismatch with
    `ExpectedStateError` — but only if the caller actually has the values, and a
    screen that had to dig them out of a view would eventually forget on one
    form. Carrying them on the detail makes the round trip the obvious thing to
    do, and makes a lost update a refusal rather than an overwrite.

    They are deliberately the module's own reading of the row at read time, not
    something a caller may compose: the point of an expected version is that it
    was OBSERVED.
    """

    agreement: AgreementView
    timeline: tuple[TransitionRecord, ...]
    permitted_actions: tuple[AgreementAction, ...]
    expected_version: int
    expected_status: str
    #: Mirrors `agreement.approval_withdrawn` — carried here too so a surface
    #: reading only the detail's own fields still sees it.
    approval_withdrawn: bool = False


@dataclass(frozen=True, slots=True)
class AgreementFilter:
    """What a caller may narrow the agreement estate by, and how far it may read.

    A closed set of typed fields. No predicate, no sort column, no raw `where`:
    a consumer that could pass one would own every future query over
    `mod_agreements`, and the module could no longer say what its own read
    surface is.

    There is deliberately nowhere here to state a permitted action or an
    expected version. Both are the module's to derive from rows it owns.

    ## It narrows the KEYSET reader; it does not add a second one

    `after`/`limit` are the same cursor and bound `list_agreements` has always
    taken — agreement id as a stable total key, a `limit + 1` probe instead of a
    count query. This type gives that reader a closed shape and bounds `limit`
    in the TYPE rather than in one function body; it does not introduce a
    parallel list implementation, which would be a second read authority over
    the same tables with its own drift.
    """

    status: str | None = None
    agreement_type: str | None = None
    counterparty_ref: str | None = None
    agreement_family_id: UUID | None = None
    #: Keyset cursor: the `next_after` of the previous page, unchanged. Not an
    #: offset — an offset over a moving estate skips and repeats rows.
    after: UUID | None = None
    limit: int = DEFAULT_AGREEMENT_PAGE_SIZE

    MAX_LIMIT: ClassVar[int] = MAX_AGREEMENT_PAGE_SIZE

    def __post_init__(self) -> None:
        # `AgreementError` rather than a bare `ValueError`, because this is the
        # refusal `list_agreements` has raised for these exact inputs since a1
        # and a caller catching it must keep catching it. It IS a `ValueError`
        # subclass, so nothing that caught the broader type stops working.
        if not isinstance(self.limit, int) or isinstance(self.limit, bool):
            raise AgreementError("agreement page limit must be a whole number")
        if not 1 <= self.limit <= self.MAX_LIMIT:
            raise AgreementError(
                f"agreement page limit must be between 1 and {self.MAX_LIMIT}"
            )
        if self.after is not None and not isinstance(self.after, UUID):
            raise AgreementError("agreement page cursor must be a UUID or None")


# ── Approval withdrawal: recorded as standing, never as a transition ────────


@dataclass(frozen=True, slots=True)
class RecordApprovalWithdrawalCommand:
    """Record that an approval decision no longer stands.

    Idempotently binds `approval_request_ref`, `approval_decision_ref`,
    `policy_code`/`policy_version`, `subject_ref` and `content_hash` — every
    field `service.record_approval_withdrawal` checks the evidence against
    before writing anything. There is no `expected_version`: the command takes
    the agreement row FOR UPDATE and decides from the evidence bound to it, not
    from a version the caller last saw. It never changes `agreements.status`;
    when it records, it bumps `record_version` once so a stale form holding the
    old version is refused by the next transition.
    """

    command_id: str
    agreement_id: UUID
    approval_request_ref: str
    approval_decision_ref: str
    policy_code: str
    policy_version: int
    subject_ref: str
    content_hash: str
    withdrawal_ref: str
    reason: str
    withdrawn_at: datetime
    actor_admin_id: UUID | None = None

    def __post_init__(self) -> None:
        for field, value in (
            ("approval_request_ref", self.approval_request_ref),
            ("approval_decision_ref", self.approval_decision_ref),
            ("policy_code", self.policy_code),
            ("subject_ref", self.subject_ref),
            ("content_hash", self.content_hash),
            ("withdrawal_ref", self.withdrawal_ref),
            ("reason", self.reason),
        ):
            if not value or not value.strip():
                raise AgreementError(f"approval withdrawal {field} must not be blank")
        if self.withdrawn_at.tzinfo is None:
            raise AgreementError(
                "approval withdrawal withdrawn_at must be timezone-aware"
            )
        # The column bounds, checked here so an over-long value is a typed
        # refusal at construction rather than a DataError at flush that would
        # fail identically on every redelivery.
        for field, value, limit in (
            ("command_id", self.command_id, 200),
            ("approval_request_ref", self.approval_request_ref, 200),
            ("approval_decision_ref", self.approval_decision_ref, 200),
            ("policy_code", self.policy_code, 120),
            ("subject_ref", self.subject_ref, 200),
            ("content_hash", self.content_hash, 64),
            ("withdrawal_ref", self.withdrawal_ref, 200),
        ):
            if len(value) > limit:
                raise AgreementError(
                    f"approval withdrawal {field} exceeds {limit} characters"
                )


class ApprovalWithdrawalOutcome(StrEnum):
    """A closed vocabulary of what recording a withdrawal actually did.

    Only `RECORDED` and `ALREADY_RECORDED` write anything. The other three are
    refusals: the command's own binding does not match what this module froze,
    and no partial write happens on the way to reporting that.
    """

    RECORDED = "recorded"
    ALREADY_RECORDED = "already_recorded"
    DECISION_NOT_CARRIED = "decision_not_carried"
    CONTENT_NOT_BOUND = "content_not_bound"
    EVIDENCE_CONFLICT = "evidence_conflict"


@dataclass(frozen=True, slots=True)
class ApprovalWithdrawalResult:
    """What `record_approval_withdrawal` decided, and whether it wrote."""

    outcome: ApprovalWithdrawalOutcome
    agreement_id: UUID
    status: str
    approval_carried: bool
    withdrawal_id: UUID | None


__all__ = [
    "AGREEMENT_ACTIVATED_V1",
    "AGREEMENT_AMENDED_V1",
    "AGREEMENT_APPROVAL_WITHDRAWN_V1",
    "AGREEMENT_APPROVED_V1",
    "AGREEMENT_CANCELLED_V1",
    "AGREEMENT_EXPIRED_V1",
    "AGREEMENT_PROPOSED_V1",
    "AGREEMENT_REINSTATED_V1",
    "AGREEMENT_REJECTED_V1",
    "AGREEMENT_SUSPENDED_V1",
    "AGREEMENT_TERMINATED_V1",
    "PUBLISHED_EVENT_TYPES",
    "AgreementAction",
    "AgreementDetail",
    "AgreementFilter",
    "AgreementPage",
    "AgreementView",
    "ApprovalWithdrawalOutcome",
    "ApprovalWithdrawalResult",
    "PromisedLine",
    "RecordApprovalWithdrawalCommand",
    "TransitionRecord",
]
