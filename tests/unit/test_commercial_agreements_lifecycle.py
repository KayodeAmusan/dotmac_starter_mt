"""The lifecycle refuses more than it permits, and every refusal is proven.

The invariant this file protects: **an agreement reaches a status only through a
command whose precondition held, and the append-only history says so.** A suite
that only walked the happy path would pass against an implementation with no
guards at all — every status is reachable if nothing checks.

So the shape here is: for each transition, one test that it works from the
legal status, and one that it is refused from an illegal one. Plus the three
properties that are easy to implement and easy to get subtly wrong —
idempotency, optimistic concurrency, and amendment-as-new-version.

In-memory SQLite — logic only. Grants, the append-only trigger, the raw-SQL
constraints and migration-from-empty are proven against real Postgres in
`tests/test_commercial_agreements_platform_isolation.py`. Do not add a tenancy
or privilege assertion here; SQLite cannot enforce either, so it would pass for
the wrong reason.
"""

from __future__ import annotations

import uuid
from collections.abc import Generator
from datetime import UTC, date, datetime

import pytest
from dotmac_commercial_agreements import (
    AGREEMENT_APPROVAL_WITHDRAWN_V1,
    AUDIT_ACTION_APPROVAL_WITHDRAWAL_RECORDED,
    MAX_AGREEMENT_PAGE_SIZE,
    ActivateCommand,
    ActivationEvidence,
    AgreementAction,
    AgreementApprovalWithdrawal,
    AgreementBoundaryError,
    AgreementError,
    AgreementPage,
    AgreementPeriod,
    AgreementStatus,
    AgreementView,
    AmendCommand,
    ApprovalEvidence,
    ApprovalWithdrawalOutcome,
    ApproveCommand,
    CommercialTerms,
    DraftCommand,
    EmptyAgreementError,
    EvidenceRefusedError,
    ExpectedStateError,
    LineInput,
    ProposeCommand,
    RecordApprovalWithdrawalCommand,
    TerminateCommand,
    TransitionCommand,
    TransitionRefusedError,
    UndeclaredCapabilityError,
    UnknownProductError,
    activate,
    amend,
    approve,
    cancel,
    detail,
    expire,
    family,
    get,
    history,
    list_agreements,
    module,
    open_draft,
    propose,
    record_approval_withdrawal,
    reinstate,
    reject,
    suspend,
    terminate,
)
from dotmac_kernel.audit import PlatformAuditEvent
from dotmac_kernel.audit_actions import AuditActionRegistry, install_audit_actions
from dotmac_kernel.models import Base
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

_TODAY = date(2026, 9, 1)
_END = date(2027, 8, 31)


class FakeCatalogue:
    """A catalogue reader over a `{product: {codes}}` map.

    Deliberately NOT a stub that always says yes: the failing paths are the
    point, and a permissive fake would make the validation tests vacuous.
    """

    def __init__(self, declared: dict[str, set[str]]) -> None:
        self.declared = declared
        self.calls: list[tuple[str, tuple[str, ...]]] = []

    def require_declared(self, product_code: str, codes: tuple[str, ...]) -> None:
        self.calls.append((product_code, codes))
        if product_code not in self.declared:
            raise UnknownProductError(product_code)
        missing = tuple(sorted(set(codes) - self.declared[product_code]))
        if missing:
            raise UndeclaredCapabilityError(product_code, missing)


@pytest.fixture(autouse=True)
def _installed_module_audit_actions() -> None:
    """Exercise the module as an adopter does: its manifest is installed."""
    install_audit_actions(AuditActionRegistry.from_manifests([module]))


@pytest.fixture
def db() -> Generator[Session, None, None]:
    engine = create_engine("sqlite://", future=True)

    @event.listens_for(engine, "connect")
    def _attach(dbapi_connection, _record):  # type: ignore[no-untyped-def]
        # pysqlite does not emit BEGIN on its own, which leaves SAVEPOINT
        # semantics broken — and every command runs inside one, via the kernel's
        # at-most-once owner. Without SQLAlchemy's documented workaround a
        # rollback silently keeps the row and the flush-only test below would
        # fail against CORRECT code.
        dbapi_connection.isolation_level = None
        dbapi_connection.execute("ATTACH DATABASE ':memory:' AS mod_agreements")

    @event.listens_for(engine, "begin")
    def _emit_begin(connection):  # type: ignore[no-untyped-def]
        connection.exec_driver_sql("BEGIN")

    # A module that reuses a kernel facility inherits its storage: every command
    # writes the platform idempotency ledger and the platform audit log.
    Base.metadata.create_all(
        engine,
        tables=[
            table
            for table in Base.metadata.tables.values()
            if table.schema == "mod_agreements"
            or table.name
            in {
                "platform_idempotency_records",
                "platform_audit_events",
                "platform_admins",
                "platform_outbox_events",
            }
        ],
    )
    session = sessionmaker(bind=engine, autocommit=False, autoflush=False)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture
def catalogue() -> FakeCatalogue:
    return FakeCatalogue(
        {
            "dotmac_sub": {"subscriber.manage", "billing.invoicing"},
            "dotmac_erp": {"finance.ledger"},
        }
    )


def _lines(*, product: str = "dotmac_sub") -> tuple[LineInput, ...]:
    return (
        LineInput(
            product_code=product,
            capability_code="subscriber.manage",
            quantity=500,
            terms=CommercialTerms(unit_amount="12.50", currency_code="NGN"),
            release_ref="dotmac_sub@7.187.1",
        ),
    )


def _draft(db: Session, catalogue: FakeCatalogue, *, reference: str | None = None):
    return open_draft(
        db,
        DraftCommand(
            command_id=f"cmd-{uuid.uuid4().hex[:12]}",
            reference=reference or f"AGR-{uuid.uuid4().hex[:8]}",
            counterparty_ref="acme-operator",
            agreement_type="oem_reseller",
            period=AgreementPeriod(_TODAY, _END),
            lines=_lines(),
        ),
        catalogue=catalogue,
    )


def _propose(db: Session, catalogue: FakeCatalogue, agreement_id: uuid.UUID):
    return propose(
        db,
        ProposeCommand(
            command_id=f"cmd-{uuid.uuid4().hex[:12]}",
            agreement_id=agreement_id,
            approval_policy_code="commercial.oem",
            approval_policy_version=3,
        ),
        catalogue=catalogue,
    )


def _evidence(
    digest: str,
    *,
    policy: str = "commercial.oem",
    version: int = 3,
    decision_ref: str | None = None,
):
    return ApprovalEvidence(
        policy_code=policy,
        policy_version=version,
        decision_ref=decision_ref or f"apr-{uuid.uuid4().hex[:10]}",
        content_digest=digest,
        decided_at=datetime(2026, 8, 20, 9, 0, tzinfo=UTC),
    )


def _approve(db: Session, view):
    return approve(
        db,
        ApproveCommand(
            command_id=f"cmd-{uuid.uuid4().hex[:12]}",
            agreement_id=view.id,
            evidence=_evidence(view.content_hash or ""),
        ),
    )


def _activate(db: Session, view):
    return activate(
        db,
        ActivateCommand(
            command_id=f"cmd-{uuid.uuid4().hex[:12]}",
            agreement_id=view.id,
            # Activation must present the SAME decision that carried approval.
            approval_evidence=_evidence(
                view.content_hash or "", decision_ref=view.approval_decision_ref
            ),
            activation_evidence=ActivationEvidence(
                rule="countersignature",
                reference="doc-4471",
                satisfied_at=datetime(2026, 8, 21, 10, 0, tzinfo=UTC),
            ),
        ),
    )


def _to_active(db: Session, catalogue: FakeCatalogue):
    view = _draft(db, catalogue)
    view = _propose(db, catalogue, view.id)
    view = _approve(db, view)
    return _activate(db, view)


def _approved_with_decision(db: Session, catalogue: FakeCatalogue, decision_ref: str):
    """A `proposed` agreement approved under a CALLER-CHOSEN `decision_ref`.

    The generic `_approve` helper mints a random one, which is fine for the
    lifecycle tests above but useless here: a withdrawal command has to name
    the exact decision it is withdrawing, so the tests need to know it in
    advance.
    """
    view = _propose(db, catalogue, _draft(db, catalogue).id)
    return approve(
        db,
        ApproveCommand(
            command_id=f"cmd-{uuid.uuid4().hex[:12]}",
            agreement_id=view.id,
            evidence=ApprovalEvidence(
                policy_code="commercial.oem",
                policy_version=3,
                decision_ref=decision_ref,
                content_digest=view.content_hash or "",
                decided_at=datetime(2026, 8, 20, 9, 0, tzinfo=UTC),
            ),
        ),
    )


def _activate_under_decision(db: Session, view, decision_ref: str):
    """Activate an agreement approved under `decision_ref`, re-supplying the
    same decision — the property `activate` itself now requires."""
    return activate(
        db,
        ActivateCommand(
            command_id=f"cmd-{uuid.uuid4().hex[:12]}",
            agreement_id=view.id,
            approval_evidence=ApprovalEvidence(
                policy_code="commercial.oem",
                policy_version=3,
                decision_ref=decision_ref,
                content_digest=view.content_hash or "",
                decided_at=datetime(2026, 8, 20, 9, 0, tzinfo=UTC),
            ),
            activation_evidence=ActivationEvidence(
                rule="countersignature",
                reference="doc-4471",
                satisfied_at=datetime(2026, 8, 21, 10, 0, tzinfo=UTC),
            ),
        ),
    )


def _withdrawal_command(
    view,
    *,
    decision_ref: str,
    policy_code: str = "commercial.oem",
    policy_version: int = 3,
    subject_ref: str | None = None,
    content_hash: str | None = None,
    withdrawal_ref: str | None = None,
) -> RecordApprovalWithdrawalCommand:
    return RecordApprovalWithdrawalCommand(
        command_id=f"cmd-{uuid.uuid4().hex[:12]}",
        agreement_id=view.id,
        approval_request_ref=f"req-{uuid.uuid4().hex[:8]}",
        approval_decision_ref=decision_ref,
        policy_code=policy_code,
        policy_version=policy_version,
        subject_ref=subject_ref if subject_ref is not None else str(view.id),
        content_hash=(
            content_hash if content_hash is not None else (view.content_hash or "")
        ),
        withdrawal_ref=withdrawal_ref or f"wd-{uuid.uuid4().hex[:10]}",
        reason="policy compliance issue",
        withdrawn_at=datetime(2026, 9, 5, 12, 0, tzinfo=UTC),
    )


def _replay(command: RecordApprovalWithdrawalCommand, **overrides: object):
    """The same withdrawal, restated under a NEW command id — the shape a
    genuine retry has, as opposed to a conflicting second command."""
    fields = {
        "command_id": f"cmd-{uuid.uuid4().hex[:12]}",
        "agreement_id": command.agreement_id,
        "approval_request_ref": command.approval_request_ref,
        "approval_decision_ref": command.approval_decision_ref,
        "policy_code": command.policy_code,
        "policy_version": command.policy_version,
        "subject_ref": command.subject_ref,
        "content_hash": command.content_hash,
        "withdrawal_ref": command.withdrawal_ref,
        "reason": command.reason,
        "withdrawn_at": command.withdrawn_at,
    }
    fields.update(overrides)
    return RecordApprovalWithdrawalCommand(**fields)  # type: ignore[arg-type]


# ── The forward path ────────────────────────────────────────────────────────


class TestTheForwardPath:
    def test_a_draft_starts_unfrozen_and_at_version_one(self, db, catalogue) -> None:
        view = _draft(db, catalogue)
        assert view.status == AgreementStatus.DRAFT.value
        assert view.content_hash is None, "a draft has nothing frozen to approve"
        assert view.agreement_version == 1
        assert view.record_version == 1
        assert len(view.lines) == 1

    def test_proposing_freezes_a_snapshot_and_its_digest(self, db, catalogue) -> None:
        view = _propose(db, catalogue, _draft(db, catalogue).id)
        assert view.status == AgreementStatus.PROPOSED.value
        assert view.content_hash and len(view.content_hash) == 64
        assert view.approval_policy_code == "commercial.oem"
        assert view.approval_policy_version == 3

    def test_approval_is_not_activation(self, db, catalogue) -> None:
        """The separation the source implementation got right, kept.

        Collapsing them would make "signed but not yet countersigned"
        inexpressible, which is where most commercial disputes live.
        """
        view = _approve(db, _propose(db, catalogue, _draft(db, catalogue).id))
        assert view.status == AgreementStatus.APPROVED.value
        assert view.approved_at is not None
        assert view.activated_at is None, "approval must not imply activation"

    def test_activation_records_the_rule_that_was_satisfied(
        self, db, catalogue
    ) -> None:
        view = _to_active(db, catalogue)
        assert view.status == AgreementStatus.ACTIVE.value
        assert view.activation_rule == "countersignature"
        # Naive comparison: SQLite has no tz-aware type. See the note in
        # test_commercial_agreements_evidence.py — the property under test is
        # that the EVIDENCE's clock is stored, not this module's.
        assert view.activated_at is not None
        assert view.activated_at.replace(tzinfo=None) == datetime(2026, 8, 21, 10, 0)

    def test_the_full_path_appends_one_history_row_per_transition(
        self, db, catalogue
    ) -> None:
        view = _to_active(db, catalogue)
        rows = history(db, view.id)
        assert [r.to_status for r in rows] == ["proposed", "approved", "active"]
        assert [r.sequence for r in rows] == [1, 2, 3], "sequence is dense"
        assert rows[0].from_status == "draft"
        # `open_draft` appends nothing: creating a draft is not a transition,
        # and a history row claiming one would make the first sequence number
        # mean something different from every later one.
        assert all(r.command_id for r in rows)


# ── Refusals ────────────────────────────────────────────────────────────────


class TestIllegalTransitionsAreRefused:
    """Every guard, driven from a status it must reject.

    This is the half a happy-path suite misses entirely: without these, an
    implementation whose guards were deleted would still pass every test above.
    """

    def test_a_draft_cannot_be_approved(self, db, catalogue) -> None:
        view = _draft(db, catalogue)
        with pytest.raises(ExpectedStateError):
            approve(
                db,
                ApproveCommand(
                    command_id="cmd-x",
                    agreement_id=view.id,
                    evidence=_evidence("0" * 64),
                ),
            )

    def test_a_proposed_agreement_cannot_be_activated(self, db, catalogue) -> None:
        view = _propose(db, catalogue, _draft(db, catalogue).id)
        with pytest.raises(ExpectedStateError):
            _activate(db, view)

    def test_a_draft_cannot_be_suspended(self, db, catalogue) -> None:
        view = _draft(db, catalogue)
        with pytest.raises(TransitionRefusedError):
            suspend(db, TransitionCommand("cmd-x", view.id))

    def test_an_active_agreement_cannot_be_cancelled(self, db, catalogue) -> None:
        """Cancellation exists only before anything downstream can have been
        created. An active agreement is terminated, which is evidenced."""
        view = _to_active(db, catalogue)
        with pytest.raises(TransitionRefusedError):
            cancel(db, TransitionCommand("cmd-x", view.id))

    def test_a_terminated_agreement_refuses_every_further_transition(
        self, db, catalogue
    ) -> None:
        view = _to_active(db, catalogue)
        view = terminate(
            db,
            TerminateCommand(
                command_id="cmd-t",
                agreement_id=view.id,
                effective_date=date(2026, 12, 31),
                impact_acknowledged=True,
                reason="counterparty exit",
            ),
        )
        assert view.status == AgreementStatus.TERMINATED.value
        for call in (
            lambda: suspend(db, TransitionCommand("c1", view.id)),
            lambda: reinstate(db, TransitionCommand("c2", view.id)),
            lambda: cancel(db, TransitionCommand("c3", view.id)),
        ):
            with pytest.raises(TransitionRefusedError):
                call()

    def test_an_agreement_with_no_lines_cannot_be_drafted(self, db, catalogue) -> None:
        with pytest.raises(EmptyAgreementError):
            open_draft(
                db,
                DraftCommand(
                    command_id="cmd-x",
                    reference="AGR-EMPTY",
                    counterparty_ref="acme-operator",
                    agreement_type="oem_reseller",
                    period=AgreementPeriod(_TODAY, _END),
                    lines=(),
                ),
                catalogue=catalogue,
            )

    def test_expiry_is_refused_while_the_term_is_still_running(
        self, db, catalogue
    ) -> None:
        """The guard that stops a mis-scheduled job expiring a live agreement."""
        view = _to_active(db, catalogue)
        with pytest.raises(TransitionRefusedError):
            expire(db, TransitionCommand("cmd-x", view.id), as_of=date(2027, 1, 1))

    def test_expiry_date_itself_is_still_inside_the_term(self, db, catalogue) -> None:
        """a1's expiry date remains inclusive; a2 does not move the boundary."""
        view = _to_active(db, catalogue)
        with pytest.raises(TransitionRefusedError):
            expire(db, TransitionCommand("cmd-x", view.id), as_of=_END)

    def test_expiry_succeeds_once_the_term_has_ended(self, db, catalogue) -> None:
        view = _to_active(db, catalogue)
        view = expire(db, TransitionCommand("cmd-e", view.id), as_of=date(2027, 9, 1))
        assert view.status == AgreementStatus.EXPIRED.value

    def test_termination_without_an_acknowledged_impact_preview_is_refused(
        self, db, catalogue
    ) -> None:
        view = _to_active(db, catalogue)
        with pytest.raises(EvidenceRefusedError):
            terminate(
                db,
                TerminateCommand(
                    command_id="cmd-x",
                    agreement_id=view.id,
                    effective_date=date(2026, 12, 31),
                    impact_acknowledged=False,
                    reason="no preview shown",
                ),
            )

    def test_a_period_that_ends_before_it_starts_is_refused_at_construction(
        self,
    ) -> None:
        """The type refuses it, so no call site has to.

        `AgreementError` specifically, not a bare `Exception`: a broad catch
        would also pass if the constructor raised `TypeError` on a signature
        change, which is the opposite of the property under test.
        """
        with pytest.raises(AgreementError):
            AgreementPeriod(date(2027, 1, 1), date(2026, 1, 1))

    def test_the_exclusive_end_is_derived_from_the_inclusive_expiry(self) -> None:
        period = AgreementPeriod(_TODAY, _END)
        assert period.expiry_date == date(2027, 8, 31)
        assert period.end_exclusive == date(2027, 9, 1)

    def test_an_unrepresentable_exclusive_end_is_a_typed_refusal(self) -> None:
        period = AgreementPeriod(date.max, date.max)
        assert period.expiry_date == date.max, "the inclusive a1 value is preserved"
        with pytest.raises(AgreementBoundaryError, match="no representable"):
            _ = period.end_exclusive


# ── Catalogue validation ────────────────────────────────────────────────────


class TestPromisedCapabilitiesAreValidated:
    def test_an_undeclared_capability_is_refused_before_anything_is_written(
        self, db, catalogue
    ) -> None:
        with pytest.raises(UndeclaredCapabilityError) as excinfo:
            open_draft(
                db,
                DraftCommand(
                    command_id="cmd-x",
                    reference="AGR-BAD",
                    counterparty_ref="acme-operator",
                    agreement_type="oem_reseller",
                    period=AgreementPeriod(_TODAY, _END),
                    lines=(
                        LineInput(
                            product_code="dotmac_sub",
                            capability_code="not.declared",
                            quantity=1,
                            terms=CommercialTerms("1.00", "NGN"),
                        ),
                    ),
                ),
                catalogue=catalogue,
            )
        assert excinfo.value.codes == ("not.declared",)
        assert get(db, uuid.uuid4()) is None

    def test_an_unknown_product_fails_closed(self, db, catalogue) -> None:
        """An unknown product is not an empty catalogue.

        Treating the two alike would let a typo in `product_code` promise
        arbitrary capabilities against a product nobody has declared.
        """
        with pytest.raises(UnknownProductError):
            open_draft(
                db,
                DraftCommand(
                    command_id="cmd-x",
                    reference="AGR-BAD2",
                    counterparty_ref="acme-operator",
                    agreement_type="oem_reseller",
                    period=AgreementPeriod(_TODAY, _END),
                    lines=(
                        LineInput(
                            product_code="dotmac_typo",
                            capability_code="subscriber.manage",
                            quantity=1,
                            terms=CommercialTerms("1.00", "NGN"),
                        ),
                    ),
                ),
                catalogue=catalogue,
            )

    def test_codes_are_grouped_by_product_not_checked_one_at_a_time(
        self, db, catalogue
    ) -> None:
        """A caller fixing a manifest wants every missing code at once."""
        with pytest.raises(UndeclaredCapabilityError) as excinfo:
            open_draft(
                db,
                DraftCommand(
                    command_id="cmd-x",
                    reference="AGR-BAD3",
                    counterparty_ref="acme-operator",
                    agreement_type="oem_reseller",
                    period=AgreementPeriod(_TODAY, _END),
                    lines=(
                        LineInput(
                            "dotmac_sub", "nope.one", 1, CommercialTerms("1", "NGN")
                        ),
                        LineInput(
                            "dotmac_sub", "nope.two", 1, CommercialTerms("1", "NGN")
                        ),
                    ),
                ),
                catalogue=catalogue,
            )
        assert excinfo.value.codes == ("nope.one", "nope.two")


# ── Concurrency ─────────────────────────────────────────────────────────────


class TestExpectedStateConcurrency:
    """Two operators on two screens is the ordinary case, not the exotic one."""

    def test_a_stale_record_version_is_refused(self, db, catalogue) -> None:
        view = _to_active(db, catalogue)
        stale_version = view.record_version
        suspend(db, TransitionCommand("cmd-s", view.id, reason="billing hold"))
        with pytest.raises(ExpectedStateError) as excinfo:
            reinstate(
                db,
                TransitionCommand(
                    "cmd-r",
                    view.id,
                    expected_status=AgreementStatus.ACTIVE.value,
                    expected_version=stale_version,
                ),
            )
        assert excinfo.value.expected_version == stale_version
        assert excinfo.value.actual_status == AgreementStatus.SUSPENDED.value

    def test_the_version_advances_on_every_transition(self, db, catalogue) -> None:
        view = _draft(db, catalogue)
        assert view.record_version == 1
        view = _propose(db, catalogue, view.id)
        assert view.record_version == 2
        view = _approve(db, view)
        assert view.record_version == 3

    def test_omitting_the_version_still_checks_the_status(self, db, catalogue) -> None:
        """Opting out of the version check is not opting out of the guard.

        An outbox consumer reacting to a fact has no prior read to compare
        against; it must still be unable to activate a draft.
        """
        view = _draft(db, catalogue)
        with pytest.raises(ExpectedStateError):
            _activate(db, view)


# ── Idempotency ─────────────────────────────────────────────────────────────


class TestCommandsAreIdempotent:
    def test_replaying_a_command_id_does_not_transition_twice(
        self, db, catalogue
    ) -> None:
        view = _propose(db, catalogue, _draft(db, catalogue).id)
        command = ApproveCommand(
            command_id="cmd-fixed",
            agreement_id=view.id,
            evidence=_evidence(view.content_hash or ""),
        )
        first = approve(db, command)
        second = approve(db, command)
        assert first.status == second.status == AgreementStatus.APPROVED.value
        assert (
            first.record_version == second.record_version
        ), "a replay must not advance the record version"
        assert (
            len(history(db, view.id)) == 2
        ), "a replay must not append a second history row"


# ── Amendment ───────────────────────────────────────────────────────────────


class TestAmendmentIsANewVersion:
    def test_amending_supersedes_the_predecessor_and_returns_the_successor(
        self, db, catalogue
    ) -> None:
        original = _to_active(db, catalogue)
        successor = amend(
            db,
            AmendCommand(
                command_id="cmd-a",
                agreement_id=original.id,
                reference="AGR-2026-0001-A2",
                lines=(
                    LineInput(
                        product_code="dotmac_sub",
                        capability_code="billing.invoicing",
                        quantity=900,
                        terms=CommercialTerms("11.00", "NGN"),
                    ),
                ),
                reason="volume increase",
            ),
            catalogue=catalogue,
        )
        assert successor.agreement_version == 2
        assert successor.status == AgreementStatus.DRAFT.value
        assert successor.supersedes_id == original.id
        assert successor.agreement_family_id == original.agreement_family_id

        predecessor = get(db, original.id)
        assert predecessor is not None
        assert predecessor.status == AgreementStatus.SUPERSEDED.value
        assert predecessor.superseded_by_id == successor.id

    def test_the_predecessor_keeps_its_lines_and_its_history(
        self, db, catalogue
    ) -> None:
        """An amendment is a new version, never an edit — which is what makes
        "what did we agree, and when" answerable years later."""
        original = _to_active(db, catalogue)
        before = len(history(db, original.id))
        amend(
            db,
            AmendCommand(
                command_id="cmd-a",
                agreement_id=original.id,
                reference="AGR-A2",
                lines=_lines(),
            ),
            catalogue=catalogue,
        )
        predecessor = get(db, original.id)
        assert predecessor is not None
        assert predecessor.lines[0].quantity == 500, "original lines are untouched"
        assert len(history(db, original.id)) == before + 1

    def test_a_terminal_agreement_cannot_be_amended(self, db, catalogue) -> None:
        view = _to_active(db, catalogue)
        view = expire(db, TransitionCommand("cmd-e", view.id), as_of=date(2027, 9, 1))
        with pytest.raises(TransitionRefusedError):
            amend(
                db,
                AmendCommand(
                    command_id="cmd-a",
                    agreement_id=view.id,
                    reference="AGR-A2",
                    lines=_lines(),
                ),
                catalogue=catalogue,
            )

    def test_amending_twice_from_the_same_predecessor_is_refused(
        self, db, catalogue
    ) -> None:
        """Otherwise one agreement would have two successors and the family
        would stop being a chain."""
        original = _to_active(db, catalogue)
        amend(
            db,
            AmendCommand("cmd-a1", original.id, "AGR-A2", _lines()),
            catalogue=catalogue,
        )
        with pytest.raises(TransitionRefusedError):
            amend(
                db,
                AmendCommand("cmd-a2", original.id, "AGR-A3", _lines()),
                catalogue=catalogue,
            )

    def test_the_family_reads_back_in_version_order(self, db, catalogue) -> None:
        original = _to_active(db, catalogue)
        amend(
            db,
            AmendCommand("cmd-a", original.id, "AGR-A2", _lines()),
            catalogue=catalogue,
        )
        versions = family(db, original.agreement_family_id)
        assert [v.agreement_version for v in versions] == [1, 2]


# ── Bounded estate inspection ───────────────────────────────────────────────


class TestAgreementEstateListing:
    def test_pages_every_agreement_once_in_stable_id_order(self, db, catalogue) -> None:
        created = tuple(_draft(db, catalogue) for _ in range(5))
        expected_ids = sorted(view.id for view in created)

        first = list_agreements(db, limit=2)
        assert isinstance(first, AgreementPage)
        assert [view.id for view in first.items] == expected_ids[:2]
        assert first.next_after == expected_ids[1]

        second = list_agreements(db, after=first.next_after, limit=2)
        assert [view.id for view in second.items] == expected_ids[2:4]
        assert second.next_after == expected_ids[3]

        final = list_agreements(db, after=second.next_after, limit=2)
        assert [view.id for view in final.items] == expected_ids[4:]
        assert final.next_after is None

    def test_a_full_final_page_does_not_invent_a_continuation(
        self, db, catalogue
    ) -> None:
        created = tuple(_draft(db, catalogue) for _ in range(2))
        page = list_agreements(db, limit=2)
        assert {view.id for view in page.items} == {view.id for view in created}
        assert page.next_after is None

    def test_views_and_lines_remain_usable_after_the_orm_is_detached(
        self, db, catalogue
    ) -> None:
        created = _draft(db, catalogue)
        page = list_agreements(db, limit=1)
        db.expunge_all()

        assert isinstance(page.items[0], AgreementView)
        assert not hasattr(page.items[0], "_sa_instance_state")
        assert page.items[0].id == created.id
        assert page.items[0].lines[0].capability_code == "subscriber.manage"
        assert page.items[0].end_exclusive == date(2027, 9, 1)

    @pytest.mark.parametrize("limit", [False, 0, MAX_AGREEMENT_PAGE_SIZE + 1])
    def test_invalid_page_limits_are_refused(self, db, limit) -> None:
        with pytest.raises(AgreementError, match="page limit"):
            list_agreements(db, limit=limit)

    def test_a_non_uuid_cursor_is_refused_at_the_public_boundary(self, db) -> None:
        with pytest.raises(AgreementError, match="cursor"):
            list_agreements(db, after="not-a-uuid")  # type: ignore[arg-type]


# ── Rejection clears the frozen snapshot ────────────────────────────────────


class TestRejectionInvalidatesApprovals:
    def test_rejecting_clears_the_digest_so_no_approval_can_bind(
        self, db, catalogue
    ) -> None:
        view = _propose(db, catalogue, _draft(db, catalogue).id)
        frozen = view.content_hash
        view = reject(db, TransitionCommand("cmd-j", view.id, reason="terms"))
        assert view.status == AgreementStatus.DRAFT.value
        assert view.content_hash is None
        assert view.approval_policy_code is None
        # The approval collected against the old digest is now unusable, because
        # there is no digest for it to bind to.
        with pytest.raises(ExpectedStateError):
            approve(
                db,
                ApproveCommand("cmd-k", view.id, _evidence(frozen or "")),
            )


# ── Approval withdrawal: recorded as standing, never as a transition ────────


class TestApprovalWithdrawalOutcomes:
    """Every outcome `record_approval_withdrawal` can report, driven from the
    exact binding that produces it — the closed vocabulary this module commits
    to (`ApprovalWithdrawalOutcome`)."""

    def test_a_withdrawal_naming_the_approving_decision_is_recorded_as_carried(
        self, db, catalogue
    ) -> None:
        view = _approved_with_decision(db, catalogue, "apr-carried")
        result = record_approval_withdrawal(
            db, _withdrawal_command(view, decision_ref="apr-carried")
        )
        assert result.outcome == ApprovalWithdrawalOutcome.RECORDED
        assert result.approval_carried is True
        assert result.status == "approved"
        assert result.withdrawal_id is not None

    def test_a_withdrawal_against_a_still_proposed_agreement_is_recorded_uncarried(
        self, db, catalogue
    ) -> None:
        """No decision is bound yet — this is what blocks the FIRST approval
        from ever landing on this row."""
        view = _propose(db, catalogue, _draft(db, catalogue).id)
        result = record_approval_withdrawal(
            db,
            _withdrawal_command(
                view, decision_ref="apr-never-approved", content_hash=view.content_hash
            ),
        )
        assert result.outcome == ApprovalWithdrawalOutcome.RECORDED
        assert result.approval_carried is False
        assert result.status == "proposed"

    def test_an_identical_replay_of_the_same_withdrawal_ref_is_already_recorded(
        self, db, catalogue
    ) -> None:
        view = _approved_with_decision(db, catalogue, "apr-replay")
        command = _withdrawal_command(view, decision_ref="apr-replay")
        first = record_approval_withdrawal(db, command)
        # Identical payload under a new command id. (A different reason under the
        # same reference is a conflict — see the replay-identity tests below.)
        second = record_approval_withdrawal(db, _replay(command))
        assert second.outcome == ApprovalWithdrawalOutcome.ALREADY_RECORDED
        assert second.withdrawal_id == first.withdrawal_id
        assert second.approval_carried == first.approval_carried

    def test_the_same_withdrawal_ref_with_a_different_binding_is_an_evidence_conflict(
        self, db, catalogue
    ) -> None:
        view = _approved_with_decision(db, catalogue, "apr-conflict")
        command = _withdrawal_command(view, decision_ref="apr-conflict")
        record_approval_withdrawal(db, command)
        result = record_approval_withdrawal(
            db, _replay(command, approval_request_ref="a-different-request-ref")
        )
        assert result.outcome == ApprovalWithdrawalOutcome.EVIDENCE_CONFLICT
        assert result.withdrawal_id is None

    def test_a_second_withdrawal_ref_for_an_already_withdrawn_decision_is_a_conflict(
        self, db, catalogue
    ) -> None:
        """The a4 deviation: a second DISTINCT `withdrawal_ref` naming the same
        (agreement, decision) is refused as `evidence_conflict` rather than left
        to the unique constraint as an `IntegrityError` a caller would retry
        forever."""
        view = _approved_with_decision(db, catalogue, "apr-twice")
        record_approval_withdrawal(
            db, _withdrawal_command(view, decision_ref="apr-twice")
        )
        result = record_approval_withdrawal(
            db, _withdrawal_command(view, decision_ref="apr-twice")
        )
        assert result.outcome == ApprovalWithdrawalOutcome.EVIDENCE_CONFLICT
        assert result.withdrawal_id is None

    def test_a_withdrawal_naming_the_wrong_subject_is_an_evidence_conflict(
        self, db, catalogue
    ) -> None:
        view = _approved_with_decision(db, catalogue, "apr-subject")
        result = record_approval_withdrawal(
            db,
            _withdrawal_command(
                view, decision_ref="apr-subject", subject_ref=str(uuid.uuid4())
            ),
        )
        assert result.outcome == ApprovalWithdrawalOutcome.EVIDENCE_CONFLICT
        assert result.withdrawal_id is None

    def test_a_withdrawal_naming_a_different_frozen_policy_is_an_evidence_conflict(
        self, db, catalogue
    ) -> None:
        view = _approved_with_decision(db, catalogue, "apr-policy")
        result = record_approval_withdrawal(
            db,
            _withdrawal_command(
                view, decision_ref="apr-policy", policy_code="commercial.direct"
            ),
        )
        assert result.outcome == ApprovalWithdrawalOutcome.EVIDENCE_CONFLICT
        assert result.withdrawal_id is None

    def test_a_mismatched_content_hash_on_an_unapproved_row_is_content_not_bound(
        self, db, catalogue
    ) -> None:
        view = _propose(db, catalogue, _draft(db, catalogue).id)
        result = record_approval_withdrawal(
            db,
            _withdrawal_command(
                view, decision_ref="apr-never-approved", content_hash="0" * 64
            ),
        )
        assert result.outcome == ApprovalWithdrawalOutcome.CONTENT_NOT_BOUND
        assert result.withdrawal_id is None

    def test_a_decision_ref_that_is_neither_bound_nor_unset_is_decision_not_carried(
        self, db, catalogue
    ) -> None:
        view = _approved_with_decision(db, catalogue, "apr-actual")
        result = record_approval_withdrawal(
            db,
            _withdrawal_command(view, decision_ref="apr-someone-elses-decision"),
        )
        assert result.outcome == ApprovalWithdrawalOutcome.DECISION_NOT_CARRIED
        assert result.withdrawal_id is None


class TestApprovalWithdrawalIsRecordedAsStandingNotAsATransition:
    def test_recording_never_changes_status_and_bumps_the_version_exactly_once(
        self, db, catalogue
    ) -> None:
        view = _approved_with_decision(db, catalogue, "apr-version")
        before_version = view.record_version
        record_approval_withdrawal(
            db, _withdrawal_command(view, decision_ref="apr-version")
        )
        after = get(db, view.id)
        assert after is not None
        assert after.status == "approved"
        assert after.record_version == before_version + 1

    def test_a_replay_of_an_already_recorded_withdrawal_does_not_bump_it_again(
        self, db, catalogue
    ) -> None:
        view = _approved_with_decision(db, catalogue, "apr-replay-version")
        command = _withdrawal_command(view, decision_ref="apr-replay-version")
        record_approval_withdrawal(db, command)
        after_first = get(db, view.id)
        assert after_first is not None
        record_approval_withdrawal(db, _replay(command))
        after_second = get(db, view.id)
        assert after_second is not None
        assert after_second.record_version == after_first.record_version

    def test_recording_writes_exactly_one_history_row_with_equal_from_and_to_status(
        self, db, catalogue
    ) -> None:
        view = _approved_with_decision(db, catalogue, "apr-hist")
        before = len(history(db, view.id))
        record_approval_withdrawal(
            db, _withdrawal_command(view, decision_ref="apr-hist")
        )
        rows = history(db, view.id)
        assert len(rows) == before + 1
        new_row = rows[-1]
        assert new_row.from_status == new_row.to_status == "approved"
        assert new_row.event_type == AGREEMENT_APPROVAL_WITHDRAWN_V1

    def test_recording_writes_the_withdrawal_audit_action_not_the_transition_one(
        self, db, catalogue
    ) -> None:
        view = _approved_with_decision(db, catalogue, "apr-audit")
        record_approval_withdrawal(
            db, _withdrawal_command(view, decision_ref="apr-audit")
        )
        rows = (
            db.query(PlatformAuditEvent)
            .filter(PlatformAuditEvent.entity_id == str(view.id))
            .all()
        )
        # Not ordered by `created_at`: SQLite's `CURRENT_TIMESTAMP` has
        # second-level resolution, and propose/approve/withdrawal can land in
        # the same second — an ordering assumption would be flaky for a reason
        # that has nothing to do with the property under test. Exactly one row
        # carries the withdrawal action; the rest (propose, approve) carry the
        # transition action, never this one.
        withdrawal_rows = [
            row
            for row in rows
            if row.action == AUDIT_ACTION_APPROVAL_WITHDRAWAL_RECORDED
        ]
        assert len(withdrawal_rows) == 1

    def test_non_record_outcomes_write_no_withdrawal_row_and_no_history_row(
        self, db, catalogue
    ) -> None:
        view = _approved_with_decision(db, catalogue, "apr-clean")
        before_history = len(history(db, view.id))
        before_version = view.record_version
        result = record_approval_withdrawal(
            db,
            _withdrawal_command(
                view, decision_ref="apr-clean", subject_ref=str(uuid.uuid4())
            ),
        )
        assert result.outcome == ApprovalWithdrawalOutcome.EVIDENCE_CONFLICT
        after = get(db, view.id)
        assert after is not None
        assert after.record_version == before_version
        assert len(history(db, view.id)) == before_history
        rows = (
            db.query(AgreementApprovalWithdrawal)
            .filter(AgreementApprovalWithdrawal.agreement_id == view.id)
            .all()
        )
        assert rows == []


class TestWithdrawalRefusalsAreDecidedFreshUnderTheLock:
    """Review of #759: a refusal is decided under the row lock, on every
    delivery — it writes nothing, so it cannot be memoized under the command
    id the way a `RECORDED` outcome is. These pin the decisions the fix in
    HEAD makes, each one a case the pre-fix code got wrong."""

    def test_a_refusal_is_not_memoized_and_the_same_command_id_later_records(
        self, db, catalogue
    ) -> None:
        """The exact bug in review #759: `content_not_bound` while the row was
        a draft, replayed forever by the ledger once the row was proposed with
        a matching digest. If the refusal were still memoized under
        `process_once_platform`, this second call would report
        `content_not_bound` again instead of `recorded`."""
        view = _draft(db, catalogue)
        first_command = _withdrawal_command(
            view, decision_ref="apr-never-approved", content_hash="0" * 64
        )
        first = record_approval_withdrawal(db, first_command)
        assert first.outcome == ApprovalWithdrawalOutcome.CONTENT_NOT_BOUND

        proposed = _propose(db, catalogue, view.id)
        second_command = _replay(
            first_command,
            command_id=first_command.command_id,
            content_hash=proposed.content_hash,
        )
        second = record_approval_withdrawal(db, second_command)
        assert second.outcome == ApprovalWithdrawalOutcome.RECORDED
        assert second.approval_carried is False

    def test_a_carried_withdrawal_with_a_contradicting_digest_is_an_evidence_conflict(
        self, db, catalogue
    ) -> None:
        """Check 3's digest guard: the decision matches the row's own, but the
        command's digest contradicts the one this module froze — refused
        rather than written into append-only evidence."""
        view = _approved_with_decision(db, catalogue, "apr-digest-conflict")
        result = record_approval_withdrawal(
            db,
            _withdrawal_command(
                view, decision_ref="apr-digest-conflict", content_hash="f" * 64
            ),
        )
        assert result.outcome == ApprovalWithdrawalOutcome.EVIDENCE_CONFLICT
        assert result.withdrawal_id is None
        rows = (
            db.query(AgreementApprovalWithdrawal)
            .filter(AgreementApprovalWithdrawal.agreement_id == view.id)
            .all()
        )
        assert rows == []

    def test_a_withdrawal_recorded_on_a_terminated_agreement_is_carried(
        self, db, catalogue
    ) -> None:
        """Never a transition: a terminal agreement is recorded historically,
        never refused, and its status does not move."""
        view = _approved_with_decision(db, catalogue, "apr-terminal")
        activated = _activate_under_decision(db, view, "apr-terminal")
        terminated = terminate(
            db,
            TerminateCommand(
                command_id="cmd-t",
                agreement_id=activated.id,
                effective_date=date(2026, 12, 31),
                impact_acknowledged=True,
                reason="counterparty exit",
            ),
        )
        result = record_approval_withdrawal(
            db, _withdrawal_command(terminated, decision_ref="apr-terminal")
        )
        assert result.outcome == ApprovalWithdrawalOutcome.RECORDED
        assert result.approval_carried is True
        assert result.status == AgreementStatus.TERMINATED.value

    def test_a_suspended_agreement_with_a_withdrawal_excludes_reinstate(
        self, db, catalogue
    ) -> None:
        view = _approved_with_decision(db, catalogue, "apr-suspended-reinstate")
        activated = _activate_under_decision(db, view, "apr-suspended-reinstate")
        suspended = suspend(
            db, TransitionCommand("cmd-s", activated.id, reason="billing hold")
        )
        record_approval_withdrawal(
            db,
            _withdrawal_command(suspended, decision_ref="apr-suspended-reinstate"),
        )
        agreement_detail = detail(db, suspended.id)
        assert agreement_detail is not None
        assert AgreementAction.REINSTATE not in agreement_detail.permitted_actions
        with pytest.raises(TransitionRefusedError):
            reinstate(db, TransitionCommand("cmd-r", suspended.id))

    def test_a_command_id_reused_from_another_command_is_refused(
        self, db, catalogue
    ) -> None:
        """The kernel's platform ledger keys on `command_id` alone, across
        every command type — a `suspend` and a `record_approval_withdrawal`
        sharing one id collide in the SAME ledger row. A replay is trusted
        only when it is THIS command's own record; the `suspend` record
        `process_once_platform` finds instead names neither an `outcome` nor a
        `withdrawal_ref`, so this raises rather than reporting `recorded`."""
        view = _approved_with_decision(db, catalogue, "apr-shared-command")
        activated = _activate_under_decision(db, view, "apr-shared-command")
        suspend(
            db, TransitionCommand("cmd-shared", activated.id, reason="billing hold")
        )

        withdrawal_command = _replay(
            _withdrawal_command(activated, decision_ref="apr-shared-command"),
            command_id="cmd-shared",
        )
        with pytest.raises(TransitionRefusedError, match="already used"):
            record_approval_withdrawal(db, withdrawal_command)

        rows = (
            db.query(AgreementApprovalWithdrawal)
            .filter(AgreementApprovalWithdrawal.agreement_id == activated.id)
            .all()
        )
        assert rows == [], "the collision must not be reported as a record"


class TestAWithdrawalBlocksReapprovalNeverOtherTransitions:
    def test_approve_is_refused_once_a_withdrawal_is_recorded(
        self, db, catalogue
    ) -> None:
        view = _propose(db, catalogue, _draft(db, catalogue).id)
        record_approval_withdrawal(
            db,
            _withdrawal_command(
                view, decision_ref="apr-blocks-approval", content_hash=view.content_hash
            ),
        )
        with pytest.raises(TransitionRefusedError):
            approve(
                db,
                ApproveCommand(
                    command_id="cmd-x",
                    agreement_id=view.id,
                    evidence=_evidence(view.content_hash or ""),
                ),
            )

    def test_activate_is_refused_once_a_withdrawal_is_recorded_on_the_approved_row(
        self, db, catalogue
    ) -> None:
        view = _approved_with_decision(db, catalogue, "apr-blocks-activation")
        record_approval_withdrawal(
            db, _withdrawal_command(view, decision_ref="apr-blocks-activation")
        )
        with pytest.raises(TransitionRefusedError):
            _activate_under_decision(db, view, "apr-blocks-activation")

    def test_reinstate_is_refused_once_a_withdrawal_is_recorded_on_a_suspended_row(
        self, db, catalogue
    ) -> None:
        view = _approved_with_decision(db, catalogue, "apr-blocks-reinstate")
        activated = _activate_under_decision(db, view, "apr-blocks-reinstate")
        suspended = suspend(
            db, TransitionCommand("cmd-s", activated.id, reason="billing hold")
        )
        record_approval_withdrawal(
            db,
            _withdrawal_command(suspended, decision_ref="apr-blocks-reinstate"),
        )
        with pytest.raises(TransitionRefusedError):
            reinstate(db, TransitionCommand("cmd-r", suspended.id))

    def test_permitted_actions_excludes_approve_activate_and_reinstate(
        self, db, catalogue
    ) -> None:
        view = _propose(db, catalogue, _draft(db, catalogue).id)
        record_approval_withdrawal(
            db,
            _withdrawal_command(
                view, decision_ref="apr-permitted", content_hash=view.content_hash
            ),
        )
        agreement_detail = detail(db, view.id)
        assert agreement_detail is not None
        assert AgreementAction.APPROVE not in agreement_detail.permitted_actions
        assert AgreementAction.ACTIVATE not in agreement_detail.permitted_actions
        assert AgreementAction.REINSTATE not in agreement_detail.permitted_actions

    def test_the_view_and_detail_report_approval_withdrawn(self, db, catalogue) -> None:
        view = _approved_with_decision(db, catalogue, "apr-view-flag")
        before = get(db, view.id)
        assert before is not None
        assert before.approval_withdrawn is False
        record_approval_withdrawal(
            db, _withdrawal_command(view, decision_ref="apr-view-flag")
        )
        after = get(db, view.id)
        assert after is not None
        assert after.approval_withdrawn is True
        agreement_detail = detail(db, view.id)
        assert agreement_detail is not None
        assert agreement_detail.agreement.approval_withdrawn is True
        assert agreement_detail.approval_withdrawn is True

    def test_suspend_still_works_after_a_withdrawal_is_recorded(
        self, db, catalogue
    ) -> None:
        view = _approved_with_decision(db, catalogue, "apr-suspend-ok")
        activated = _activate_under_decision(db, view, "apr-suspend-ok")
        record_approval_withdrawal(
            db, _withdrawal_command(activated, decision_ref="apr-suspend-ok")
        )
        suspended = suspend(
            db, TransitionCommand("cmd-s", activated.id, reason="billing hold")
        )
        assert suspended.status == AgreementStatus.SUSPENDED.value

    def test_cancel_still_works_after_a_withdrawal_is_recorded(
        self, db, catalogue
    ) -> None:
        view = _propose(db, catalogue, _draft(db, catalogue).id)
        record_approval_withdrawal(
            db,
            _withdrawal_command(
                view, decision_ref="apr-cancel-ok", content_hash=view.content_hash
            ),
        )
        cancelled = cancel(db, TransitionCommand("cmd-c", view.id))
        assert cancelled.status == AgreementStatus.CANCELLED.value

    def test_terminate_still_works_after_a_withdrawal_is_recorded(
        self, db, catalogue
    ) -> None:
        view = _approved_with_decision(db, catalogue, "apr-terminate-ok")
        activated = _activate_under_decision(db, view, "apr-terminate-ok")
        record_approval_withdrawal(
            db, _withdrawal_command(activated, decision_ref="apr-terminate-ok")
        )
        terminated = terminate(
            db,
            TerminateCommand(
                command_id="cmd-t",
                agreement_id=activated.id,
                effective_date=date(2026, 12, 31),
                impact_acknowledged=True,
                reason="counterparty exit",
            ),
        )
        assert terminated.status == AgreementStatus.TERMINATED.value


class TestActivationRequiresTheSameDecisionThatCarriedApproval:
    def test_activation_naming_a_different_decision_than_the_approval_is_refused(
        self, db, catalogue
    ) -> None:
        view = _approved_with_decision(db, catalogue, "apr-original-decision")
        with pytest.raises(EvidenceRefusedError, match="SAME decision"):
            activate(
                db,
                ActivateCommand(
                    command_id="cmd-act",
                    agreement_id=view.id,
                    approval_evidence=ApprovalEvidence(
                        policy_code="commercial.oem",
                        policy_version=3,
                        decision_ref="apr-a-different-decision",
                        content_digest=view.content_hash or "",
                        decided_at=datetime(2026, 8, 20, 9, 0, tzinfo=UTC),
                    ),
                    activation_evidence=ActivationEvidence(
                        rule="countersignature",
                        reference="doc-1",
                        satisfied_at=datetime(2026, 8, 21, 10, 0, tzinfo=UTC),
                    ),
                ),
            )


# ── Transaction authority ───────────────────────────────────────────────────


class TestTheModuleOwnsNoTransaction:
    def test_nothing_is_committed_so_a_rollback_discards_it(
        self, db, catalogue
    ) -> None:
        """Hard rule 8: the module only adds and flushes; the boundary commits.

        If the service committed, the rollback below would not remove the row —
        which is exactly the failure this asserts against.
        """
        view = _draft(db, catalogue)
        db.rollback()
        assert get(db, view.id) is None


class TestWithdrawalReplayNeverDependsOnMutableRowState:
    """Opus acceptance of #759: the replay lookup runs FIRST, against the stored
    withdrawal only, so an identical redelivery replays even after the row's
    frozen policy has changed; reason and time are part of the identity."""

    def test_replay_after_reject_and_repropose_under_a_new_policy(
        self, db: Session, catalogue: FakeCatalogue
    ) -> None:
        view = _propose(db, catalogue, _draft(db, catalogue).id)
        command = _withdrawal_command(view, decision_ref="apr-before-reject")
        first = record_approval_withdrawal(db, command)
        assert first.outcome is ApprovalWithdrawalOutcome.RECORDED

        drafted = reject(db, TransitionCommand("cmd-r1", view.id, reason="terms"))
        propose(
            db,
            ProposeCommand(
                command_id="cmd-p2",
                agreement_id=drafted.id,
                approval_policy_code="commercial.direct",
                approval_policy_version=9,
            ),
            catalogue=catalogue,
        )

        again = record_approval_withdrawal(db, _replay(command))
        assert again.outcome is ApprovalWithdrawalOutcome.ALREADY_RECORDED
        assert again.withdrawal_id == first.withdrawal_id

    def test_the_same_reference_with_a_different_reason_is_a_conflict(
        self, db: Session, catalogue: FakeCatalogue
    ) -> None:
        view = _propose(db, catalogue, _draft(db, catalogue).id)
        command = _withdrawal_command(view, decision_ref="apr-reason")
        record_approval_withdrawal(db, command)
        changed = record_approval_withdrawal(
            db, _replay(command, reason="a different reason")
        )
        assert changed.outcome is ApprovalWithdrawalOutcome.EVIDENCE_CONFLICT

    def test_an_over_long_reference_is_refused_at_construction(self) -> None:
        with pytest.raises(AgreementError, match="withdrawal_ref exceeds 200"):
            RecordApprovalWithdrawalCommand(
                command_id="cmd-long",
                agreement_id=uuid.uuid4(),
                approval_request_ref="req",
                approval_decision_ref="apr",
                policy_code="commercial.oem",
                policy_version=3,
                subject_ref="subject",
                content_hash="a" * 64,
                withdrawal_ref="w" * 201,
                reason="reason",
                withdrawn_at=datetime(2026, 9, 5, 12, 0, tzinfo=UTC),
            )
