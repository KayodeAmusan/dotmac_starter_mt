# Public surface and stability — dotmac-deployment-foundation

## What is public

- `ProductDeploymentSpec` and every type it exposes, plus the `SCHEMA` string.
- `ProductDeploymentSpec.to_canonical_document()` and
  `DeploymentDescriptorDocumentV1` — its `canonical_bytes()`,
  `sha256_digest()` and the `DESCRIPTOR_DOCUMENT_SCHEMA` string. The BYTES
  are public contract exactly as the rendered assets are: a change to the
  document's shape changes every consumer's digest at once, which is the
  intended behaviour and makes it a MINOR bump at least.
- `FoundationExecutionPlanV1` and `ExecutionPlanDigestV1` — the historical document, its
  ten canonicalization rules, and the digest over it. The BYTES are the
  contract and two other systems bind to them: Platform CP submits the digest
  and Control freezes it, so a change to the document's shape, key set, key
  names, or any of the ten rules invalidates every frozen digest at once and is
  a MINOR bump at least. V1 remains readable but is non-authorizing.
- `FoundationExecutionPlanV3` and `authorize_v3()` — the active execution
  authority contract. The V3 document binds the exact recorded candidate
  wheel digest, target ID/ref, controller SSH fingerprint, Fleet/Control host
  ID, host-key incarnation fingerprint and immutable enrolment/root-version
  reference. Its canonical digest is still `ExecutionPlanDigestV1` and must
  equal Control's signed V2 pair value. `dotmac-deploy execution-plan` renders
  it only with a startup-installed provider; a V1/V2 plan cannot issue a grant.
  The Control V2 receipt schema is unchanged. The trusted in-process assembly
  fixes the attester, clock and host observer; request material cannot choose
  them. Host-source admission remains the separate F2 owner of installed-source
  integrity, not a claim made by the recorded wheel digest. Its authenticated
  `host_identity` equals the V3 Fleet `host_id`; installed signer fingerprint
  and installed trust-root version equal the V3 host incarnation and canonical
  enrolment UUID. The executor compares all three before effects. `Effects`
  carries no authenticated target identity, so the trusted CP composition must
  construct the V3 provider, F2 admission provider and Effects as one bundle.
  `ExecutionAuthorityV3Provider.consume_dispatch()` receives immutable
  canonical copies of the exact attested authorization+dispatch material, the
  exact F2 admission trace, the execution-plan digest and deterministic
  `control-dispatch:<dispatch_id>` recovery key. The trace retains Foundation's
  actual pair-verification result and a transient opaque CP continuation;
  Foundation checks its presence and pair/host coordinates but neither
  interprets nor persists the continuation. CP passes both to Control's one
  host-admission-and-execution finalizer, which freshly rederives both standings
  and stages one dispatch marker. The provider returns `None` only after CP
  commits; otherwise it raises before commit. Foundation checks the live
  receipt and independently observed context before calling it, with no
  fallible post-commit gate. Successful local run
  evidence uses `DeploymentEvidence.v2` to carry the recovery key; V1 bytes
  remain unchanged. Control's committed ledger is authoritative if Foundation
  crashes before that local evidence can be written. This is a required trust contract for the external CP adapter, not
  a claim that the adapter is already implemented or conformance-proven.
  Installed-wheel release smoke proves V3 rendering and honest standalone CLI
  refusal only; publication never grants deployment authority.
- `IngressPolicy.v1`: the exposure vocabulary, the provider capability
  matrix, the derived endpoint-token format and the firewall rule shape.
- The `dotmac-deploy` CLI: its subcommands, its flags, and its **exit codes**
  (`0` ok, `1` refused, `2` usage). CI wires the exit codes, so they are part
  of the contract rather than an implementation detail.
- The rendered output of every renderer, treated as bytes: `render --check` is
  a byte comparison, so a whitespace change is a breaking change for every
  consumer that has committed the previous output.
- `DeploymentProvenance.v1`: `AuthorizationReceipt`, `AuthorizationReceiptV2`,
  `AuthorizationReceiptV2Attester`, `AttestedAuthorizationReceiptV2`,
  `attest_authorization_receipt_v2()`, `DeploymentProvenanceV1`,
  `build_provenance()`, `normalize_digest()` and the `PROVENANCE_SCHEMA`
  string. The canonical BYTES are public contract on the same terms as the
  descriptor document's. `AuthorizationReceipt` is a typed INPUT this facility
  never produces: `dotmac-deployment-control` owns authorization, and the
  receipt is bound by VALUE so a zero-dependency build runner never acquires a
  stateful module and never reaches into another owner's state.
  The successor is a minimal Foundation consumer value: Platform's verified-pair
  adapter attests both Control documents through the typed attester port, while
  Foundation alone constructs the opaque wrapper. Only that wrapper exposes
  the combined liveness/execution-input gate. Foundation preserves envelope
  digests, distinct signer identities and Control's product code without
  parsing, mirroring or re-canonicalizing either Control document. No executor
  accepts the wrapper in this contract revision: a caller-selected attester is
  not production authority, and product-vocabulary mapping remains a later
  Platform adapter responsibility.
- `TrustedHostAttestation.v2`: `AttestationEnvelopeV2`,
  `AttestationTrustPolicy`, `AttestationTrustRootV2`, `AttestationVerifiedRootV1`,
  `CandidateAttestationSubjectV2`, `InstalledHostAttestationSubjectV2`,
  `AttestationVerifier`, `attestation_envelope_digest()`,
  `verify_attestation_pair()`,
  `verify_candidate_attestation()` and the exported schema, purpose and
  refusal-code constants, including `SAME_KEY_SIGNED_BOTH`,
  `OBSERVATION_ID_MISMATCH` and `PACKAGE_MISMATCH`. The parsed envelope's
  complete mapping is public through `AttestationEnvelopeV2.canonical_document()`;
  `attestation_envelope_digest()` hashes its exact canonical JSON mapping,
  including `signature`. The signed canonical bytes and refusal codes are
  public contract. The verifier
  identifies a signing key by `public_key_fingerprint`, never by the reusable
  `key_id` label, and remains a non-admitting composition seam: neither
  executor accepts these values in this contract revision.
  `verify_candidate_attestation()` is the single candidate-authentication
  code path — a trusted host workload calls it to obtain an authenticated
  `CandidateAttestationSubjectV2` instead of trusting a parsed value, and
  `verify_attestation_pair()` calls this exact function for its candidate
  half rather than a parallel implementation. Its signature accepts only the
  envelope to authenticate plus Control-resolved trust configuration
  (`verifier`, `trust_policy`, `now`); there is no parameter for a
  preconstructed subject, receipt, digest, or ad hoc root.
- **Breaking (ADR-0073 redesign step 1)**: `verify_attestation_pair()` now
  returns `AttestationPairVerificationResultV1` on success instead of bare
  `None`, and requires one new keyword-only parameter,
  `verification_context_digest: str`. That parameter is Foundation's opaque —
  Control's own digest over its resolved admission context, validated only for
  non-emptiness and echoed back unchanged in the result on success; Foundation
  never computes, interprets, or reproduces it. This result is explicitly
  non-authorizing: never a `HostSource` or execution token; only Control
  decides consequence from it.
- **Breaking (ADR-0073 redesign step 2, result widening)**:
  `AttestationPairVerificationResultV1` now carries ten fields —
  `candidate_attestation_envelope_digest`, `installed_attestation_envelope_digest`,
  `verification_context_digest`, `expected_host_identity`,
  `expected_observation_id`, `expected_package`, `candidate_audience`,
  `installed_audience`, `candidate_root`, `installed_root` — reporting
  EVERYTHING actually verified, not only digests. The two envelope digests
  are computed from the actual parsed `candidate`/`installed` objects this
  call verified, identically to `attestation_envelope_digest()` — never
  copied from a caller-supplied value. `expected_host_identity`,
  `expected_observation_id` and `expected_package` are this call's own
  validated local values (the exact strings checked against the
  authenticated subjects), not an unchecked echo of caller input.
  `candidate_audience`/`installed_audience` are `trust_policy`'s own
  declared audiences. `candidate_root`/`installed_root` are a new frozen
  dataclass, `AttestationVerifiedRootV1` (`public_key_fingerprint`,
  `trust_root_version`, `key_id`, `algorithm`, `purpose`, `custody_domain`,
  `issuer`) — the specific trust root from `trust_policy` that actually
  matched and authenticated each half, not the whole `AttestationTrustRootV2`
  (which also carries `public_key_base64`/`not_before`/`not_after`/`revoked`,
  policy configuration Control already has from its own resolution). This is
  what lets a later Control change compare its own resolution against what
  Foundation actually verified against, instead of trusting a caller-supplied
  echo of its own input back at it unchanged.
  `AttestationPairVerificationResultV1` has never appeared in a published
  release, so this widens the type in place; there is no V2.
- `admit_host_source()` and `HostSourceAdmissionTrace`
  (`host_source_admission.py`). `admit_host_source(*, candidate, installed,
  verifier, trust_policy, expected_host_identity, expected_observation_id,
  expected_package, verification_context_digest, now)` returns
  `tuple[HostSource, HostSourceAdmissionTrace]` or raises: every existing
  `SpecError`/`PreconditionFailed` from `verify_attestation_pair()` /
  `verify_candidate_attestation()` propagates unchanged, plus distinct
  coordinate refusals for a mismatched Control dispatch observation or
  expected package, and one disagreement refusal using `host_source.DISAGREES`
  when the interpreter's
  own installed-artifact reading (taken only after the attestation pair is
  verified) disagrees with the authenticated installed-host subject's
  `package`/`version`/`wheel_sha256`. The nine-parameter signature has no
  parameter for a receipt, a pre-parsed subject, an installed artifact, a
  metadata reader, a distribution selector, or any preverified result — the
  same inexpressible-bypass shape as `verify_candidate_attestation()`.
  `verification_context_digest` is threaded through to `verify_attestation_pair()`
  unread; `admit_host_source()` retains that call's actual typed
  `AttestationPairVerificationResultV1` in the trace, without treating it as
  caller-constructible authority.
  `HostSourceAdmissionTrace` is a frozen, slotted record populated from
  authenticated fields by `admit_host_source()` (`candidate_subject_digest`,
  `host_observation_id`, `host_identity`, both signer fingerprints, both
  trust-root versions, and the actual pair-verification result). A trusted CP
  F2 provider may attach a transient `opaque_finalization` continuation;
  Foundation checks only its presence, excludes it from repr/equality and
  never persists or interprets it. The publicly constructible trace type
  alone proves no authentication. The V3 pre-effect check is its only
  consumption path: it compares the trace and pair-result host, signed
  dispatch-observation and root coordinates against independently observed V3
  facts, then passes the exact trace to the startup-fixed provider for one
  Control host-admission-and-execution finalizer. Non-V3 callers retain the
  historical host-source behavior without making this trace a grant.
  `trusted_host_source.py` remains zero-I/O; `require_host_source()`'s
  signature and behavior are unchanged and it remains the constructor a
  receipt-only caller uses. Neither executor accepts a directly supplied
  `HostSource` or trace; each accepts the return of a handed-over provider,
  whose trust must be established by the composing assembly.
- `HostSourceAdmissionProvider` and `RefusingHostSourceAdmissionProvider`
  (`host_source_admission.py`), plus the keyword-only `admission_provider`
  parameter on `engine/run.py`'s `Executor` and `recovery_execution.py`'s
  `RecoveryExecutor` constructors. `HostSourceAdmissionProvider` is a
  `runtime_checkable` Protocol with one argument-free method,
  `admit_host_source() -> tuple[HostSource, HostSourceAdmissionTrace]` — no
  parameter for a receipt, an envelope, a subject, a trust policy, a
  verifier, or any preverified result. This shape does not force an
  implementation to reach Control: an arbitrary constructor caller can hand
  over a provider returning invented values. Positive use therefore requires
  trusted, startup-fixed, non-request-selectable assembly composition and
  current Control verification. `admission_provider` is keyword-only and
  **required** on both executor constructors, with no implicit fallback. The
  shipped CLI explicitly passes `RefusingHostSourceAdmissionProvider()`,
  which calls exactly `require_host_source(receipt=None)` and preserves the
  historical refusal-only behavior and typed codes
  (`ABSENT`/`WRONG_KIND`/`NO_RECEIPT`) with zero effects; it cannot authorize
  V3. Both
  executors' `_verify_host_source` calls
  `self._admission_provider.admit_host_source()` fresh on every `run`/
  `rollback` invocation — never cached, never memoized across calls on the
  same instance — and a supplied provider's own
  `PreconditionFailed`/`SpecError` propagates unchanged. Neither executor
  discovers a provider from an ambient registry or module-level global; the
  provider is HANDED OVER at construction only. A provider that composes
  `admit_host_source()` above against real Control-resolved attestations to
  genuinely admit a `HostSource` is later, separate, cross-repo work.
- `ExposureEffects`, plus `OWNERSHIP_PREFIX`, `ownership_comment()`,
  `foreign_rules()`, `foreign_rule_arguments()`, `managed_ports()` and
  `require_preserved_foreign_rules()`. Ownership is part of the CONTRACT rather
  than of one provider, because the preservation property is measured against
  it: a shared filter chain is never restored wholesale, and an implementation
  that replays one is refused rather than trusted not to. The measurement is a
  FUNCTION taking a before and an after observation, so a caller that never
  mutates can still make it.
- `ExposureReconciliationV1` and `FoundationExecutionPlanV2`'s
  `exposure_reconciliations` field — the typed authority to reconcile one
  address family's exposure. The member carries no rule, port, chain position
  or command: the rules are derived from the descriptor, whose digest is
  already in the plan and in the grant. Adding the field CHANGES the V2
  document's key set and therefore every V2 digest, which would be a MINOR bump
  at least — it is free here only because V2 has existed solely under the spent
  `0.4.0a1` and has never been published.
- `Digest`, `require_same_digest()`, `ALGORITHMS` and `CANONICAL_ALGORITHM`.
  The canonical serialization is `sha256:<64 lowercase hex>`; the bare form is
  accepted on INPUT as a compatibility affordance for
  `dotmac-deployment-control`'s `String(64)` column and is not a second
  canonical form.
- `RehearsalReceipt.v1`: `RehearsalReceiptV1`, `RequirementResult`,
  `RequirementStatus`, `REQUIRED_ITEMS`, `build_receipt()`,
  `verify_publication()`, `render_status_document()` and
  `render_pending_document()`. The sixteen item CODES are contract — a release
  gate reads them — and only `executed_passed` satisfies publication.
- `RehearsalReceipt.v2`: `RehearsalReceiptV2`, `ExecutionRunBindingV1`,
  `build_receipt_v2()`, `require_execution_run()` and
  `REHEARSAL_RECEIPT_V2_SCHEMA`. It is the receipt the release gate reads; v1
  stays readable as history. Its key set is CLOSED, and its reader refuses a
  missing or unknown field.
  - **Gate item 9 is a chain** over the authorized `ExecutionPlanDigestV1`, the
    plan's descriptor digest and the executed `DeploymentOutcome`'s copies of
    both. The builder takes the `FoundationExecutionPlanV3` itself, and takes
    the authorized digest only from the `ExecutionGrant` that `authorize_v3()`
    issued, never from a string.
  - **The receipt binds its Control dispatch.** `control_dispatch` records the
    dispatch ID, execution sequence and attempt, and the outcome must report
    the grant's sequence and attempt.
  - **The plan names the bytes and the controller.** Its candidate wheel digest
    and controller fingerprint must equal the rehearsed artifact and the
    controller identity.
  - **Target and host come from the plan.** `target_id` and `host_id` are taken
    from the plan, and an IP literal is refused. Fleet owns the `host_id`
    grammar, so hostnames are not policed here.
  - **The vantage is a reference.** `probe_vantage_ref` is
    `<record-key>@<version>`.
  - **The receipt binds its run.** It carries the producing run's immutable
    repository ID, run ID and attempt.
  - **Adding a field means v3.** v1 could not be widened for the same reason.
- `HostLease.v2`: `HostLease`, `load_lease()`, `write_lease()`. A lease is
  never self-granted; `authorization_run_id` is mandatory, and so is the
  `workload_principal` that holds and releases it. `HostLease.v1` is READABLE AS
  HISTORY through `HistoricalLeaseV1`, which has no `covers()` and no principal:
  legibility is not authority. This bullet said `.v1` until 0.4.0a1 and was
  stale by one schema.
- `HostLeaseRelease.v1`: `HostLeaseReleaseV1`, `TerminalOutcome`,
  `TerminalRefusal`, `HostClosure`, `CleanupDisposition`, `ReleasingPrincipal`,
  `write_release()`, `load_release()`, `require_release_for_destruction()`,
  `require_release_for_reuse()`. The refusal, closure and cleanup vocabularies
  are CLOSED and are contract — a destroy gate branches on them. Expiry is not
  release: a crashed run leaves `expired_held`, which does not authorize a wipe.
- `ControllerSshFingerprintV1`. The controller key's OpenSSH SHA-256
  fingerprint, on BOTH the lease and the release. Parsed by DECODING the
  canonical `SHA256:<43 base64>` that `ssh-keygen -lf` emits and requiring 32
  bytes; equality is over those bytes, so comparison answers about the KEY.
  There is exactly one accepted spelling per key.
- `VantageQualification` and `qualify_vantage()`. Typed observations in, a
  verdict out; this package performs no network I/O.
- `Effects`, `Executor`, `DeploymentPlan`, `Step`, `StepKind`, `Strategy`.
- `conformance.*` — the functions a product calls in its own CI.
- `RESOURCE_ATTRIBUTES` and the alert `code` of every entry in `COMMON_ALERTS`.
- `PostgresRecoveryBundle.v1`: `BundleComponent` (the thirteen component CODES
  are contract - a bundle is identified by them), `COMPONENTS` and each
  `ComponentSpec.covers`, `RecoveryBundleManifestV1`, `build_manifest()`,
  `load_manifest()`, `derive_role_closure()`, `RoleClosure`, and the typed
  evidence: `RoleFact`, `MembershipFact`, `OwnershipFact`, `PrivilegeFact`,
  `EffectivePrivilegeFact`, `DefaultPrivilegeFact`, `FunctionSecurityFact`,
  `PolicyFact`, `RlsFact`, `ExtensionFact`, `TablespaceDecision`,
  `CatalogEvidence`. `RoleFact` having NO password field is part of the
  contract, not an omission: adding one would be a breaking change in the
  direction that matters.
- `RESTORE_PROCEDURE` and `RestoreStep` - the ten step CODES and their ORDER
  are contract. `restore_plan()`, `adjudicate_restore()`, `Disposition`,
  `RestoreAttempt`, `verify_recovery()`, `verify_plane_isolation()`,
  `invariant_breaches()`, `classify_invariant_breaches()` and
  `InvariantBreach`. The `RESTORE DEFECT` / `SOURCE DRIFT` prefixes are
  contract - an operator and a dashboard both branch on which side is
  wrong. Manifest `counts` are observations and are gated on by nothing.
- `RecoveryReceipt.v1`: `RecoveryReceiptV1` and `build_recovery_receipt()`.
  `restore_duration_seconds` is mandatory and stays mandatory.
- `refuse_identity_stripping()` and `IDENTITY_STRIPPING_ARGS`.
- `ArtefactClass` - `data_export` vs `recovery_bundle`, and the rule that a
  `data_export` may not reach `RESTORABLE` or `PROVED`.
- `[database]` in `ProductDeploymentSpec.v1`: `DatabaseContract`,
  `DatabaseRole`, `IsolationInvariant`. There is deliberately no `superuser`
  key on a declared role; adding one would be breaking. V1 remains immutable
  and has no catalogue coordinate.
- `[database]` in `ProductDeploymentSpec.v2`: the v1 fields plus mandatory
  `[[database.catalogs]]` whenever `[database]` exists. Coordinates are typed,
  contained and digest-covered. The kernel module schema is valid only at
  MODULE scope (one complete schema), and the kernel product schema only at
  PRODUCT scope (all expected schemas); future schemas need an explicit typed
  registration. Product coordinates also bind catalogue product code/version
  to the descriptor product, with a decision reference required for aliases.
  V1 refuses this key rather than partially reading it.
- Database contract drift: `ObservedDatabaseState`,
  `EffectivePrivilegeAuditUniverse`, `PrivilegeUniverseDerivation`,
  `DatabaseDriftExclusions`, `DatabaseDriftPhase`,
  `DatabaseContractDriftReport`, `DatabaseDriftFinding`,
  `DatabaseContractGap`, `DatabaseContractGapCode`,
  `DatabaseCatalogScope`, `DatabaseCatalogCoordinateV1`,
  `DatabaseCatalogProductIdentityV1`,
  `DatabaseDescriptorCatalogBindingV1`,
  `DatabaseStructureComparisonResultV1`, `DatabaseStructureCoverageV1`,
  `DatabaseStructureFactAttribute`, `DatabaseStructureFactKeyV1`,
  `DatabaseStructureFindingV1`, `DatabaseStructureObservationEvidenceV1`,
  `DatabaseStructureWitnessV1`,
  `accept_database_structure_comparison()` and `compare_database_contract()`.
  The sidecar binds catalogue coordinates to a v1 descriptor digest without
  pretending they are inside v1; `ProductDeploymentSpec.v2` embeds the same
  coordinates. Contract-id allowlists are not an evidence path: acceptance
  requires an injected typed verifier and invokes it over the held catalogue
  and observation bytes. The verifier result's exact contract id, fact scope,
  digests, PostgreSQL major, declaration schema/scope/complete schemas and
  product code/version are rechecked before normalization. The
  structural result and `ObservedDatabaseState` must bind the same observation
  digest and PostgreSQL major. A report exposes `matched_descriptor_digest`
  only for v2 after complete accepted structural evidence covers every schema;
  a module-scoped witness is useful evidence but can never masquerade as a
  whole-product match.
- `DatabaseDescriptorTransition.v1`,
  `DatabaseDescriptorPromotionPending.v1` and
  `DatabaseDescriptorTransitionReceipt.v1`: the `from`/`to`, plan and target
  bindings; the one-transaction versus declared-checkpoint durability shape;
  `promotion_pending`; the idempotent compare-and-swap promotion port; and the
  terminal postcondition and promotion evidence. Authorization binds the
  result descriptor; the starting descriptor is the live/CAS precondition.

## Retired before any tagged release

These two entries were declared under "What is public" and have been withdrawn.
**They are NOT breaking changes**, and the distinction is the point of this
section rather than a softening of it: a breaking change removes something a
consumer could have depended on, and nothing could depend on these.

What was measured, and how:

- `ExposureTransaction` and `apply_exposure()` have **never appeared in a
  tagged version**. `exposure.py` does not exist at
  `dotmac-deployment-foundation-v0.2.0a2`, the newest of this facility's three
  tags — the module was introduced after it.
- `dotmac-deploy exposure-apply` likewise. `cli.py` DOES exist at that tag and
  the subcommand is absent from it, so this is a subcommand added after the
  last tag rather than a tagged surface withdrawn.
- `0.2.0a2` **was published and tagged** by release run `33171027470`.
  The `## 0.2.0a2 — unreleased` changelog heading at that tag is stale release
  prose, not evidence that publication failed. Neither retired API appears in
  the published tag, so this correction does not make its withdrawal breaking.

So the accurate record is a **declared surface retired before it ever shipped**.
It was written down here, in this document, as something consumers would be
able to rely on; that promise is withdrawn before anyone could take it up, and
withdrawing it is exactly why it is recorded rather than quietly deleted.

**An in-tree consumer still has to migrate**, and that is real work regardless
of what shipped. The migration boundary is below.

### `ExposureTransaction` and `apply_exposure()` — withdrawn

No shim, no alias, no re-export;
`test_the_retired_surface_is_UNAVAILABLE_not_merely_unmentioned` asserts that
`from dotmac_deployment_foundation.exposure import ExposureTransaction` raises
`ImportError`.

They were a second executor. They took the product's deployment lock
themselves, ordered apply / re-observe / verify / compensate, and no
`ExecutionGrant`, frozen execution plan or Control receipt reached any of it.
A compatibility alias was considered and refused: it is a fork with a friendly
name, keeping the removed ordering callable while reading in a diff as a
courtesy.

**Replacement: `Executor`, holding an `ExecutionGrant`.** The exposure act is
`Executor._reconcile_exposure`, performed from the authorized plan.

**The migration boundary** — what a caller must now supply, and why none of it
can be defaulted:

| was | is | why it cannot be defaulted |
|---|---|---|
| `ExposureTransaction(spec=..., effects=...)` | `Executor(spec, effects, grant, execution_plan=..., exposure_effects=...)` | the grant is positional and only `authorize_v3()` can issue one, from the exact Control V2 authorization-and-dispatch pair through the startup-fixed V3 provider; historical `authorize()` always refuses |
| `.run()` | `Executor.run(plan, lock=held)` | `lock` is a `DeploymentLockHeld`, obtainable only inside `deployment_lock`'s `with` block |
| implicit — any transaction could apply | `FoundationExecutionPlanV3.exposure_reconciliations` must name the address families | V1/V2 plans are historical and non-authorizing; the act is inside the V3 frozen plan digest, so Control authorizes THIS deployment's exposure and not exposure in general |
| `.rolled_back` | the `restore_exposure` record on `DeploymentOutcome` | compensation is evidence on the run, not state on a caller's object |

A caller that constructed the transaction has **no in-package direct
replacement**, and that is the change rather than a gap in it: performing this
act without an authorization is what was withdrawn, not an API. Callers that
only MEASURED are unaffected and better served —
`require_preserved_foreign_rules()`, `foreign_rule_arguments()` and
`managed_ports()` are public functions taking observations, so a caller that
mutates nothing can still make the measurement that used to require
constructing a transaction.

**Known consequence, recorded rather than deferred:** Lane 3's
`apply_under_lock` and `provoked_rollback` items are `blocked`. Control issues
no V2 plan carrying an exposure reconciliation yet, so no grant in existence
names the act, and Foundation must not mint one. `verify_publication` refuses a
receipt with a blocked item, so this is loud at the publication gate rather
than silent.

### `dotmac-deploy exposure-apply --execute` — withdrawn

The subcommand survives and still observes, verifies and reports; it can no
longer change a shared firewall chain. It never accepted `--authorization`, so
there was no way to hand it a Control decision and nothing in it looked for one
— the flag was permission supplied by whoever typed it.

The CLI's subcommands and flags ARE public contract (see "What is public"), so
this would be breaking had the flag ever been tagged. It was not, per the
measurement above.

## What is not

Anything underscore-prefixed, the internal layout of the renderers, and the
`Finding`/`Comparison` message TEXT (the `rule` and `verdict` values are
stable; the prose explaining them is not).

## The version rule

**A change to rendered bytes is a MINOR bump at least**, even when the change
is cosmetic, because every consumer has committed the previous bytes and
`render --check` will fail for all of them at once. That is the intended
behaviour — the alternative is a renderer that can change what a host runs
without anyone reviewing a diff — but it means a whitespace tidy-up is a
release, not a patch.

**A new REFUSAL in `spec.py` is a MAJOR bump.** A descriptor that parsed
yesterday and does not parse today breaks a consumer's build, and calling that
a patch is how a facility loses the trust it needs to be adopted. The right
shape for a new rule is: add it warning-only in a minor release, name the
version it becomes fatal in, then make it fatal in the next major.

### Deviation, 0.3.0a1: the exposure contract is fatal without a warning release

`IngressPolicy.v1` makes four descriptor changes fatal in this release,
skipping the warning-only minor the rule above requires:

- `PortPublication.bind` is REMOVED, and declaring it raises rather than being
  ignored;
- `exposure` and `address_family` are MANDATORY on every publication;
- `[ingress]` must declare its own `exposure` and `address_family`, and a
  public edge must carry `approval_ref` and `rationale_url`;
- `trusted_proxies` entries are source-set NAMES; a CIDR is refused.

The deviation is recorded here rather than taken silently, and it rests on four
premises a reader can check rather than on judgement:

1. **The consumer census is exactly one.** `EXTRACTION.toml` records one
   contract consumer, and the product-first gate derives the dossier's status
   from that count exactly. The warning phase exists to protect consumers who
   would otherwise break without notice; here there is one, and it is known.
2. **That consumer migrates in the same train.** Its descriptor changes
   alongside this release, so the notice a warning phase would have provided is
   provided by the change itself.
3. **A changed consumer set fails the migration gate.** If a second consumer
   appears, the recorded count no longer supports the dossier's status and the
   gate fails before this reasoning can be reused on a fleet it no longer
   describes. The premise is enforced, not asserted.
4. **Warning-only would still render the unsafe condition.** A release that
   accepts `bind` keeps emitting a publication whose address family is
   undeclared — and an undeclared family is not a tidiness problem. A
   short-form publish spawns one `docker-proxy` per family, so a descriptor
   silent about IPv6 gets IPv6 anyway, and the `ip6tables DOCKER-USER` rules
   written to cover it cannot fire. That is not hypothetical: two production
   DROP rules were measured with zero packet counters while the ports they
   named were open from the internet. A deprecation window is affordable when
   the old behaviour is merely untidy; it is not when the old behaviour is the
   defect.

This deviation authorises exactly these four changes. It is not a precedent for
skipping the warning phase generally, and a future removal without these four
premises holding is an ordinary rule violation.

**A new schema version is a new string.** `ProductDeploymentSpec.v2` is a
different `schema` value, and a v1 reader REFUSES a v2 document rather than
reading the subset it understands — a field an older reader cannot see may be
the one that disables a control.

### 0.3.0a4: `observability_promotion`, and why it is ADDITIVE

A new module, `dotmac_deployment_foundation.observability_promotion`, implementing
the host half of Observability ADR-0010's promotion facility: immutable
release-directory staging, a previous-release-pointer reader, an exact-byte
transport, `rename(2)` activation, per-evaluator reload with a read-back that
proves the process took the bytes, a complete live read-back, and a rollback that
returns one.

**Nothing existing changed.** No signature, no refusal and no rendered byte of any
prior surface moved. `providers/compose_host.py`'s `Runner` in particular is
untouched: a file transport needs to feed a command bytes on stdin and that
`Runner` cannot, so this module declares its own `HostTransport` Protocol rather
than widening the shipped one. Widening it would have been a MINOR-at-best change
to a seam every existing provider implements.

**The declared version moved for a reason unrelated to compatibility.**
`0.3.0a3` had already been built, so adding source under it would have made one
version name two contracts. The bump is the version rule above being applied, not
a signal that anything broke.

**Zero runtime dependencies still.** The module is stdlib-only — `urllib` rather
than `requests`/`httpx`, `subprocess` with an argv list — so the facility remains
something a build runner can adopt without adopting a runtime.

### 0.3.0a3: the external-recovery contract, measured against the version rule

Stated rather than assumed, because the rule above is strict and this change
touches every clause of it.

**New refusals in `spec.py`, and why this is not the MAJOR case.** Declaring an
`external_executor` without a `lineage` is refused, and so is a lineage that is
host-shaped or that repeats the executor's identifier. Both fire only on keys
that did not exist in any previous version, so **no descriptor that parsed
yesterday fails today** — the premise of the major-bump rule ("a consumer's
build breaks") is absent. A refusal reachable only from new syntax is a
constraint on new syntax, not a retraction of old.

**The verification vocabulary WIDENED.** `roles`, `ownership`, `memberships`
and `effective_privileges` are now accepted where they were refused at parse.
That direction cannot break a consumer, and an unknown verification is still
refused, so the vocabulary is wider and not open.

**One breaking signature change**, named plainly: `backup.assess()`'s
`expected_interval_seconds` parameter is now `expected_backup_interval_seconds`,
matching the descriptor field that supplies it. It was a second name for one
control, and one the descriptor could not state at all — so every caller
silently took the daily default whatever the product's real cadence was. There
were **no callers**: `assess()` had none in this package or in any consuming
product, which is the same fact that made `restore_proof_max_age_days` inert.
A rename with no callers is recorded here rather than deferred to a major
release nobody is waiting for.

**`SECONDS_PER_DAY` moved** from `backup` to `spec`, which now declares a
cadence in seconds and would otherwise hold a second definition of it. `backup`
re-exports it, so no import moves.

**Rendered bytes changed.** The descriptor gained fields, so
`io.dotmac.deployment.configuration.digest` moves and `docker-compose.yml` with
it — the MINOR case. `0.2.0a2` is the newest published version, so the published
line moves `0.2` → `0.3`, which satisfies it. No consumer has committed
`0.3.0a2`'s bytes: that candidate was never published and is recorded
invalidated.

## Consuming this package

Exact-pin it. A conformance gate resolving to "whatever is newest" cannot
distinguish a product that drifted from a foundation that changed, and the
reusable workflow refuses a range for that reason.
