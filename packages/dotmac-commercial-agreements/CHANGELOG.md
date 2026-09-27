# Changelog — dotmac-commercial-agreements

All notable changes to the `dotmac-commercial-agreements` distribution. This
package follows [Semantic Versioning](https://semver.org). Pre-1.0 (`0.x`, incl.
this alpha) the surface is still settling — a `0.MINOR` bump may carry breaking
changes, each called out here.

## Release state — read this before pinning

`0.1.0a1` is published. Its peeled tag
`dotmac-commercial-agreements-v0.1.0a1` resolves to exact revision
`fead57bc93d6551450f5e6ae1c9de1296e27b0ae`.

`0.1.0a2` is also published. Its peeled tag
`dotmac-commercial-agreements-v0.1.0a2` resolves to exact revision
`42acc8b30f1bcaed1580d312fd33d7b5ef358817`. (This section previously read
"`0.1.0a2` is declared and unreleased" — that was stale; the tag above already
existed on `main`.)

`0.1.0a3` is also published. Its annotated tag
`dotmac-commercial-agreements-v0.1.0a3` (written by the release workflow, whose
tag message reads "verified on the Forgejo registry (installed and registered
alone)") peels to exact revision `5005e998a4cac9b4f7e3ba91f371967b0ee8b2a2`. (This section
previously read "`0.1.0a3` is declared and unreleased" — stale in the same way
the a2 note once was. Its oracle-backed release record is not yet in
`docs/inventories/module-release-verifications.json`.)

`0.1.0a4` is declared and unreleased. Source presence is not registry evidence;
Vendor stays on its exact a2 pin until a4 has passed the protected release
workflow and Vendor deliberately adopts that immutable artifact.

## 0.1.0a4 — 2026-09-27 — prepared, unreleased (no tag, not on the index)

**An approval withdrawal is recorded as approval STANDING, never as a lifecycle
transition** (Gate-0 C2 S4, Michael 2026-09-27).

- `record_approval_withdrawal(db, RecordApprovalWithdrawalCommand) ->
  ApprovalWithdrawalResult` binds the withdrawal to the evidence this module
  froze — request, decision reference, policy code/version, subject and content
  digest — and records the withdrawal reference, reason and time in the new
  append-only `mod_agreements.agreement_approval_withdrawals` table
  (`cg_0002_approval_withdrawals`, rewrite-refusing trigger, `platform_api`/
  `app_admin` SELECT+INSERT only; UPDATE, DELETE and TRUNCATE are refused by
  trigger). It appends one history row with
  `from_status == to_status`, one audit event under the NEW action
  `commercial_agreement.approval_withdrawal_recorded`, and one
  `agreement.approval_withdrawn.v1` platform-outbox fact, in one transaction and
  through the kernel's at-most-once owner.
- The closed `ApprovalWithdrawalOutcome` vocabulary: `recorded`,
  `already_recorded` (identical replay), `decision_not_carried` (the agreement
  is bound to a different decision), `content_not_bound` (no decision bound and
  the digest no longer matches), `evidence_conflict` (subject, policy or a
  same-reference/same-decision contradiction, or a digest contradicting the
  one frozen on the agreement). Only `recorded` writes; every refusal is
  decided under the row lock and writes nothing, not even an idempotency entry,
  so a refusal that depends on current state is re-decided on redelivery.
- Recorded standing BLOCKS `approve`, `activate` and `reinstate`, which now take
  the agreement row `FOR UPDATE` and consult the table under that lock, so a
  transition can never slip past a withdrawal committing concurrently.
  `permitted_actions` drops the three actions and views carry
  `approval_withdrawn`. Nothing is ever cancelled, suspended or terminated:
  approved and active remain historical facts, and re-approval happens only on
  an amended successor.
- **Fix:** `activate` now refuses approval evidence whose `decision_ref` differs
  from the decision that carried approval. Previously only the digest and policy
  were compared.
- No change to existing tables. The manifest declares the new platform table,
  its audit action, lineage head `cg_0002_approval_withdrawals`, and a catalog
  entry drafted from the migration and verified by the live catalog test.

## 0.1.0a3 — 2026-09-19 — published (tag `dotmac-commercial-agreements-v0.1.0a3`)

**Public typed READ contracts.** `detail()` returns an `AgreementDetail` — the
agreement and its lines, the lifecycle timeline, the owner-derived
`permitted_actions`, and the `expected_version` / `expected_status` a surface
hands straight back on the next command. Carrying the expected version with the
thing being looked at is what turns a concurrent edit into an
`ExpectedStateError` refusal rather than a lost update.

**`AgreementFilter` gives the EXISTING keyset reader a closed shape**, and bounds
`limit` in the type rather than in one function body. It is not a second list
implementation: `list_agreements(db, filter)` and the a1
`list_agreements(db, after=..., limit=...)` name the same page through the same
reader, and passing both is refused. A parallel reader would be a second read
authority over `mod_agreements` with its own drift.

**One lifecycle table.** `service._PERMITTED_FROM` states which statuses each
command may be issued from, and every write guard now reads it instead of an
inline `frozenset`. The permitted-actions read comes from that same table, so a
screen cannot offer an action the write path would refuse — a second copy in a
template would disagree the moment a status moved between the render and the
click.

`DEFAULT_AGREEMENT_PAGE_SIZE` and `MAX_AGREEMENT_PAGE_SIZE` moved to `ports` so
`facts` can bound the filter without importing `service`. Both modules still
re-export them; no caller's import changes.

**The manifest now carries a `database_catalog=` contribution**
(`ModuleDatabaseCatalogContributionV1`, lineage head `cg_0001_agreements`,
covering all three platform tables in sorted order). Every column, ordinal,
PostgreSQL type and generation fact was transcribed verbatim from
`observe_postgres_tables_columns` against a disposable PostgreSQL 16 database
composed from the kernel lineage, this assembly and `cg_0001_agreements` at
that exact head — never hand-typed from the migration source — and
self-verified against a fresh observation of the same database with
`compare_module_database_catalog(...).matched is True` and zero drifts before
teardown.

The `dotmac-kernel` floor moves to `>=0.1.0a100` for this: the contribution
type and `dotmac_kernel.product_database_catalog` were first published in
a100, above the a74 allocation floor this module previously declared.

## 0.1.0a2 — 2026-08-25

Published; peeled tag `dotmac-commercial-agreements-v0.1.0a2` resolves to
`42acc8b30f1bcaed1580d312fd33d7b5ef358817`. (Previously marked "unreleased" in
this file — stale; see "Release state" above.)

### Added

- `AgreementPeriod.end_exclusive` and `AgreementView.end_exclusive`, both
  derived from the stored inclusive `expiry_date` by the one public
  `derive_end_exclusive` rule. No date column or lifecycle transition changed.
- `list_agreements`, a read-only, bounded UUID-keyset reader over the complete
  platform agreement estate. It returns frozen `AgreementPage` and
  `AgreementView` values with eagerly materialized promised lines, never ORM
  rows or lazy loaders.

### Compatibility

- `expiry_date` remains inclusive exactly as it was in a1: the agreement is in
  term through that date and becomes expiry-eligible on `end_exclusive`.
- `date.max` remains a valid stored inclusive expiry. Asking for an exclusive
  boundary beyond it raises typed `AgreementBoundaryError`; it does not wrap or
  silently become open-ended.
- There is no schema or migration change in this release.

## 0.1.0a1 — 2026-08-19

First release. Product-first extraction of the vendor control plane's
`contracts/` service (ADR-0057 § 1).

### Added

- `mod_agreements` — `agreements`, `agreement_lines`, `agreement_events` on the
  platform plane. Lineage root `cg_0001_agreements`, which verifies
  `idempotency_ledger.v1` and `platform_audit_log.v1` before any DDL of its own.
- The full lifecycle as named, guarded, idempotent commands: `open_draft`,
  `propose`, `approve`, `reject`, `activate`, `suspend`, `reinstate`,
  `terminate`, `expire`, `cancel`, `amend`.
- Evidence binding — `ApprovalEvidence.content_digest` must equal the digest
  frozen at `propose()`, checked at both `approve()` and `activate()`.
- Optimistic concurrency on every transition (`expected_status`,
  `expected_version`).
- Append-only history, enforced by the `refuse_history_rewrite` trigger against
  every role including `app_admin`.
- Ten versioned facts, enumerated in `PUBLISHED_EVENT_TYPES`.

### Changed from the source implementation

- `pending_approval` is renamed `proposed` (ADR-0057's vocabulary). Safe here
  because this is a greenfield lineage: no deployment has stored the old value
  under `mod_agreements`.
- Approval is EVIDENCE, not a sibling import. The source called
  `vendor_cp.approvals.evaluate(...)` inside `approve()`; a module may not
  import a sibling (ADR-0024) and approvals may not perform the domain's
  transition (ADR-0026 § 6).
- Lines carry opaque `release_ref`/`offer_ref` and caller-frozen terms instead
  of a foreign key to `offer_versions`. Ruling A2(b) detached the offer
  catalogue; ADR-0006 D1 forbids the cross-lineage foreign key.
- `customer_ref` becomes an opaque `counterparty_ref`. ADR-0019 § 1 and ruling
  A3: `vendor_accounts` must not retire into kernel `Party`.
- Amendment and supersession are implemented rather than reserved. The source
  left `superseded_by_id` unset with a note naming it a separable follow-up.
- The append-only history table is new. The source recorded transitions only as
  platform audit events, which a product may purge under its own retention
  policy — an evidence chain that a retention sweep can shorten is not evidence.
