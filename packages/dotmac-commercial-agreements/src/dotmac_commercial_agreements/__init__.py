"""DotMac Commercial Agreements — what was agreed, with whom, and on what proof.

The one owner of the **durable commercial agreement between the platform
operator and a counterparty**: its identity, its accepted commercial snapshot,
its lifecycle, and the append-only evidence for every transition.

Extracted product-first from `dotmac_vendor_control_plane:src/vendor_cp/
contracts/` (658-line service, two tables, migration `v004_contracts`) under
ADR-0057 § 1. See `docs/inventories/vendor-cp-gap-sources.md` § 1 for the source
inventory and `EXTRACTION.toml` for the ownership record.

## The one rule to know

**This module is handed evidence; it never infers that something happened
elsewhere.**

`approve()` takes an `ApprovalEvidence` whose `content_digest` must equal the
digest this module froze at `propose()`. There is no `approved: bool` parameter
and no settable status. Change the terms after approval and the digests differ,
which makes the prior approval **stale rather than transferable** — ADR-0026
§ 2's binding, enforced at the boundary where it is checkable.

`activate()` requires that evidence AGAIN, alongside separate activation
evidence naming the satisfied rule. Not because the module distrusts its own
`approved` column, but so an auditor reading one history row can verify the
activation without trusting that an earlier row was written correctly.

## What it owns

Agreement identity and human-readable reference; an opaque counterparty
reference; type and version; the draft → proposed → approved → active →
suspended → terminated → expired lifecycle; effective and expiry dates; the
immutable accepted commercial snapshot and its digest; opaque product/release
references; commercial terms and entitlement promises; approval evidence;
activation, suspension and termination reasons; amendments and supersession;
append-only transition history; optimistic concurrency; idempotent commands;
and the versioned facts an assembly routes.

## What it does NOT own

Product or release definitions (`dotmac-release-catalog`); entitlement balances
or allocations (`dotmac-entitlement-allocation`); licences (`dotmac-licensing`);
deployment state (`dotmac-deployment-control`); invoices, settlements or
collections decisions (`dotmac-billing`, `dotmac-collections`); approval workflow
internals (`dotmac-approvals`); counterparty master data (nobody in this
programme — ADR-0057 § 6); documents or stored bytes (`dotmac-files`, ADR-0022).

## It imports no sibling module

`dotmac-approvals` and `dotmac-entitlement-allocation` are consumed and produced
as VALUES through the assembly, never imported (ADR-0024, and the import-linter
contract `Modules are independent of each other`). The three couplings the
source had — an approvals import, an offer-catalogue FK, and a `vendor_accounts`
id — are each cut at a port described in `ports.py`.

## Transaction authority

Receives a `Session`; only `add` and `flush`. Never commits, never rolls back,
never constructs a session (hard rule 8). The boundary owns the transaction.

## Public surface

Everything importable from this top-level namespace is stable. Submodules are
not: import from here.

`get`, `detail`, `history`, `family` and `list_agreements` are the whole read
surface, and they answer in the typed values of `facts` — never in ORM rows.
`list_agreements` is ONE keyset reader: the closed `AgreementFilter` and the a1
``after=``/``limit=`` keywords name the same page in two ways, and there is
deliberately no second list implementation to drift from it.
"""

from __future__ import annotations

from dotmac_commercial_agreements.facts import (
    AGREEMENT_ACTIVATED_V1,
    AGREEMENT_AMENDED_V1,
    AGREEMENT_APPROVAL_WITHDRAWN_V1,
    AGREEMENT_APPROVED_V1,
    AGREEMENT_CANCELLED_V1,
    AGREEMENT_EXPIRED_V1,
    AGREEMENT_PROPOSED_V1,
    AGREEMENT_REINSTATED_V1,
    AGREEMENT_REJECTED_V1,
    AGREEMENT_SUSPENDED_V1,
    AGREEMENT_TERMINATED_V1,
    PUBLISHED_EVENT_TYPES,
    AgreementAction,
    AgreementDetail,
    AgreementFilter,
    AgreementPage,
    AgreementView,
    ApprovalWithdrawalOutcome,
    ApprovalWithdrawalResult,
    PromisedLine,
    RecordApprovalWithdrawalCommand,
    TransitionRecord,
)
from dotmac_commercial_agreements.manifest import module
from dotmac_commercial_agreements.migrations import versions_dir
from dotmac_commercial_agreements.models import (
    SCHEMA,
    TERMINAL_STATUSES,
    Agreement,
    AgreementApprovalWithdrawal,
    AgreementEvent,
    AgreementLine,
    AgreementStatus,
)
from dotmac_commercial_agreements.ports import (
    ActivationEvidence,
    AgreementBoundaryError,
    AgreementError,
    AgreementPeriod,
    ApprovalEvidence,
    CapabilityCatalogueReader,
    CommercialTerms,
    EmptyAgreementError,
    EvidenceRefusedError,
    ExpectedStateError,
    LineInput,
    TransitionRefusedError,
    UndeclaredCapabilityError,
    UnknownProductError,
    derive_end_exclusive,
)
from dotmac_commercial_agreements.service import (
    AUDIT_ACTION_APPROVAL_WITHDRAWAL_RECORDED,
    AUDIT_ACTION_TRANSITIONED,
    DEFAULT_AGREEMENT_PAGE_SIZE,
    MAX_AGREEMENT_PAGE_SIZE,
    ActivateCommand,
    AmendCommand,
    ApproveCommand,
    DraftCommand,
    ProposeCommand,
    TerminateCommand,
    TransitionCommand,
    accepted_snapshot,
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
    open_draft,
    propose,
    record_approval_withdrawal,
    reinstate,
    reject,
    snapshot_digest,
    suspend,
    terminate,
)

__version__ = "0.1.0a4"

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
    "AUDIT_ACTION_APPROVAL_WITHDRAWAL_RECORDED",
    "AUDIT_ACTION_TRANSITIONED",
    "ActivateCommand",
    "ActivationEvidence",
    "Agreement",
    "AgreementAction",
    "AgreementApprovalWithdrawal",
    "AgreementBoundaryError",
    "AgreementDetail",
    "AgreementError",
    "AgreementEvent",
    "AgreementFilter",
    "AgreementLine",
    "AgreementPage",
    "AgreementPeriod",
    "AgreementStatus",
    "AgreementView",
    "AmendCommand",
    "ApprovalEvidence",
    "ApprovalWithdrawalOutcome",
    "ApprovalWithdrawalResult",
    "ApproveCommand",
    "CapabilityCatalogueReader",
    "CommercialTerms",
    "DEFAULT_AGREEMENT_PAGE_SIZE",
    "DraftCommand",
    "EmptyAgreementError",
    "EvidenceRefusedError",
    "ExpectedStateError",
    "LineInput",
    "MAX_AGREEMENT_PAGE_SIZE",
    "PUBLISHED_EVENT_TYPES",
    "PromisedLine",
    "ProposeCommand",
    "RecordApprovalWithdrawalCommand",
    "SCHEMA",
    "TERMINAL_STATUSES",
    "TerminateCommand",
    "TransitionCommand",
    "TransitionRecord",
    "TransitionRefusedError",
    "UndeclaredCapabilityError",
    "UnknownProductError",
    "__version__",
    "accepted_snapshot",
    "activate",
    "amend",
    "approve",
    "cancel",
    "derive_end_exclusive",
    "detail",
    "expire",
    "family",
    "get",
    "history",
    "list_agreements",
    "module",
    "open_draft",
    "propose",
    "record_approval_withdrawal",
    "reinstate",
    "reject",
    "snapshot_digest",
    "suspend",
    "terminate",
    "versions_dir",
]
