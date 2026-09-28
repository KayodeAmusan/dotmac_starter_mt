# Changelog — dotmac-deployment-foundation

## Unreleased — successor not allocated

### Added: `transition_receipt` — the Foundation's half of D16's two-sided recovery receipt

New module, `DeploymentTransitionReceipt.v1`: a closed schema
(`TransitionReceiptV1`, `TransitionSide`, `TargetSide`, `TransitionBackup`)
and a pure verifier, `verify_transition_receipt`, for the receipt that binds
a source-to-target deployment hop — descriptor, migration heads, the image
running on the target, the backup taken of the source before migration, and
the run that performed it. The receipt claims no restore. `dotmac-deployment-control` produces the receipt in a later
change; this package verifies it independently.

`verify_transition_receipt(receipt, *, spec, observed_target_heads,
previous_receipt, backup_record, bundle_manifest, observed_image_digest,
expected_run_id, expected_target, genesis_source=None)` never raises: every
disagreement becomes one of the closed `TransitionFinding` codes rather than an
exception, including `INPUT_NOT_CANONICALIZABLE` for an input that cannot
itself be canonicalized. `genesis_source` and `previous_receipt` are
mutually exclusive and one is required (`CHAIN_ANCHOR_AMBIGUOUS` otherwise),
anchoring a chain's first receipt to a caller-named source instead of
trusting the receipt's own claim. A chain is scoped to one product,
environment and target (`CHAIN_SCOPE_MISMATCH`); the run that produced a
receipt must match what the caller actually launched and must not repeat a
predecessor's run id (`RUN_ID_MISMATCH`/`RUN_ID_REUSED`).

The target image must match the descriptor (`IMAGE_DESCRIPTOR_MISMATCH`),
the caller's own observation (`IMAGE_DIGEST_MISMATCH`), and the caller's
observation must itself already be canonical (`OBSERVED_IMAGE_MALFORMED` for
a bare-hex, uppercase or padded spelling — never normalized). The image's
source revision must be well-formed 40-lowercase-hex (`IMAGE_REVISION_INVALID`)
AND match the descriptor's own `source_revision` (`IMAGE_REVISION_DESCRIPTOR_MISMATCH`)
— a receipt is not evidence about which commit is running unless both hold.

A backup must be a `RECOVERY_BUNDLE` at assurance `VERIFIED` or higher
(`BACKUP_ASSURANCE_TOO_LOW`). Completeness — that the artefact is a whole
recovery bundle, not merely intact bytes — is established separately, by
BINDING the receipt to the bundle's own manifest: the verifier calls
`recovery.load_manifest(bundle_manifest)` (a new required keyword; pure, no
I/O — `SpecError` becomes `BACKUP_MANIFEST_NOT_A_BUNDLE`).

**Michael's 2026-09-28 correction of an earlier ruling here:** `bundle_digest`
stays exactly what it always was — the artefact's own write-time checksum,
bound to `BackupRecord.checksum` (`BACKUP_DIGEST_MISMATCH`) — and is NOT
compared with the manifest's identity. The prior ruling bound `bundle_digest`
to the manifest digest, which made a real backup (whose recorded checksum is
the artefact checksum, never a manifest digest) unverifiable. A `sha512`
dataset still cannot verify a bundle-backed receipt: the manifest's component
digests are `sha256`-only, so such a record is refused by name
(`BACKUP_ALGORITHM_NOT_BUNDLE_COMPATIBLE`). A new field, `TransitionBackup.manifest_digest` — a canonical
`sha256:` digest, validated like every other canonical digest on this
receipt, and now REQUIRED by `parse` — carries the manifest's own identity,
compared against `RecoveryBundleManifestV1.sha256_digest()`
(`BACKUP_MANIFEST_DIGEST_MISMATCH`). The artefact is linked to that manifest
through the manifest's own `database_dump` component digest:
`BackupRecord.checksum` must equal
`manifest.component_digest(BundleComponent.DATABASE_DUMP).hex`
(`BACKUP_ARTEFACT_NOT_IN_MANIFEST`). For a RECOVERY_BUNDLE, the record's
`path` and `checksum` therefore name the `database_dump` archive file. No
producer in this package writes such a record yet. Every component digest this Foundation
can express is `sha256` (`digest.ALGORITHMS` has exactly one entry), so that
link can only hold when the record's own `checksum_algorithm` is `sha256`; a
`sha512` (or any other) dataset is refused outright and by name
(`BACKUP_ALGORITHM_NOT_BUNDLE_COMPATIBLE`) rather than compared and silently
never matching. The manifest's `product` and sorted, de-duplicated
`migration_heads` must still agree with `receipt.product` and
`receipt.source.migration_heads` (the backup is of the SOURCE database,
before migration — `BACKUP_MANIFEST_SCOPE_MISMATCH`). `VERIFIED` is then
exactly the remaining claim that level is for: the bytes are intact. A
disposable restore (`RESTORABLE` and above) is a separate, stronger proof
this receipt does not claim, and this receipt makes no restore-rehearsal
claim at all.
A backup's `bundle_id` binds to `BackupRecord.path` (`BACKUP_ID_MISMATCH`);
its `checksum_algorithm` is restricted to `BackupDataset.CHECKSUMS`
(`{sha256, sha512}`, imported directly from `spec.py` — `BACKUP_ALGORITHM_UNSUPPORTED`
for anything else) and its `bundle_digest` must be lowercase hex of the
length that algorithm implies, 64 or 128 (`BACKUP_DIGEST_MALFORMED`) — bare
hex, unprefixed, matching the spelling every existing producer already uses.
A record shaped like one built by `external_recovery
.backup_record_from_receipt` (an executor identifier and a restore duration
standing in for a real artefact id and byte count) is refused outright
(`BACKUP_RECORD_NOT_ARTEFACT_BOUND`) rather than accepted on those stand-in
values — and `backup_record_from_receipt` itself now refuses (`SpecError`) a
`path` that does not carry the shared `EXTERNAL_BACKUP_PATH_PREFIX`, so its
one caller (`engine/run.py`) cannot emit a record this detection would miss.

A backup's `dataset` must name a dataset the descriptor's own
`backup_datasets` actually declares (`BACKUP_DATASET_NOT_DECLARED`), and its
`checksum_algorithm` must match that specific dataset's declared `checksum`
— not merely the global allow-list — or `BACKUP_ALGORITHM_NOT_DECLARED`.

Every digest-shaped field (`descriptor_sha256`, `image_digest`,
`previous_receipt_digest`, `manifest_digest`) and every migration head — DECLARED and OBSERVED
alike — must already be canonical: `sha256:` plus 64 lowercase hex for a
digest, no leading/trailing whitespace and non-empty for a head. `parse()`
refuses rather than normalizes a differently-spelled input, and the verifier
also attempts the RECEIPT's own canonicalization (`receipt.canonical_bytes()`)
so a receipt built directly rather than through `parse()` cannot carry an
undetected secret-shaped field.

Never raises, made concrete: every `BackupRecord` field the verifier reads
(`path`, `checksum`, `dataset` as strings; `assurance` as an `Assurance`;
`artefact_class` as an `ArtefactClass`; `size_bytes` as a non-bool `int`) is
type-checked before use, and a malformed one is `INPUT_NOT_CANONICALIZABLE`
rather than an `AttributeError`/`TypeError` — the same rule
`observed_target_heads` and a receipt/spec that cannot itself be hashed were
already held to. A check that does not need the malformed field keeps
running rather than an early return silencing every finding after it: an
operator sees every way a receipt is wrong in one pass, not one refusal per
re-run.

### Gate-3 successor execution authority (candidate; not released)

`FoundationExecutionPlanV3` binds the candidate wheel, exact target,
controller SSH fingerprint and Control/Fleet host incarnation/enrolment to the
existing `ExecutionPlanDigestV1`. The sole new grant issuer consumes the
unchanged Control V2 authorization+dispatch pair through a startup-fixed
assembly provider and rechecks independent local/Control facts before effects.
That recheck now exact-binds F2's authenticated installed host identity,
installed signer fingerprint and installed root-version UUID to the V3 plan
and fresh provider observation for both deploy and rollback. `Effects` cannot
claim an authenticated target on its own; trusted CP composition owns the
provider/admission/effects bundle.
The fixed provider now also owns an explicit pre-effect Control transaction:
Foundation checks F2 trace, fresh context, sequence/attempt and expiry before
passing the frozen original V2 pair and exact V3 coordinates. The provider
must refuse before commit or atomically spend the exact dispatch and return
`None` after commit; Foundation performs no fallible post-commit check. Replay,
revoked standing and failed consumption refuse before effects. The deterministic
`control-dispatch:<dispatch_id>` key is stored in Control's committed ledger
for crash recovery and in successful local `DeploymentEvidence.v2`; V1 evidence
bytes remain unchanged. The external CP
implementation and its conformance evidence remain outstanding.
The public V2 attestation function remains non-admitting alone. Historical V1
`authorize()` now refuses; CLI, Lane 3 and release probes cannot promote a
single V1 receipt. Lane 3 remains non-admitting until trusted CP provider and
V3 plan composition exist. Standalone installed-wheel release smoke can pass
by proving V3 render/digest behavior and CLI refusal without that provider;
publication is not adoption or authorization. This is a
candidate source contract, not evidence of a passed hosted test or release.

### ADR-0073 redesign step 1 + step 2: `verify_attestation_pair` returns typed, non-authorizing evidence, widened to report everything verified

**Breaking**: `verify_attestation_pair()` now returns `AttestationPairVerificationResultV1`
on success instead of bare `None`, and requires one new keyword-only parameter,
`verification_context_digest: str`. This is step 1 of a 3-step cross-repo
redesign (Foundation → Control → CP adapter) closing an availability hazard in
the merged ADR-0073 host-admission protocol: the current design holds Control
locks across this out-of-process verification call, which can block emergency
root revocation if the call stalls. The redesign moves to a resolve →
transaction-free-verify → revalidate/consume shape; this typed result is what
lets Control's later revalidation step bind Foundation's actual verification
outcome without either package importing the other's types.

`verification_context_digest` is Foundation's **opaque**: it is Control's own
digest over its resolved admission context, carried through this function
unread and unvalidated beyond a non-empty check, and returned unchanged in the
result only on success. Foundation does not compute, interpret, or reproduce
it — digest ownership stays singular per repository (Foundation owns the two
attestation-envelope digests it already computes; Control owns the context
digest). `admit_host_source()` carries the same new parameter through
unchanged in spirit, for nine keyword-only parameters total, still discarding
`verify_attestation_pair`'s return value since it only needs pass/fail.

**Step 2 (result widening)**: `AttestationPairVerificationResultV1` gained
seven more fields — `expected_host_identity`, `expected_observation_id`,
`expected_package`, `candidate_audience`, `installed_audience`,
`candidate_root`, `installed_root` (the last two a new small frozen
dataclass, `AttestationVerifiedRootV1`) — closing half of a real
security-boundary gap an independent review found on
`dotmac_platform_control_plane`#192: today, Control's CP adapter caller
supplies `expected_host_identity`/`expected_observation_id`/
`expected_package`/`trust_policy` with NO downstream comparison against what
Control itself resolved. Foundation now reports EVERYTHING it actually
verified — the caller-supplied expectations that were checked, the audiences
the trust policy declared, and the specific root that matched each half —
so a later Control change can compare its own resolution against what
Foundation actually verified against, instead of trusting a caller-supplied
echo of its own input back at it unchanged. `AttestationPairVerificationResultV1`
has never been published in any real release (`0.4.0a1`, which introduced it,
was never tagged), so this widens the type in place rather than adding a V2.
Control's comparison and the CP adapter's simplification are separate,
later, cross-repository tasks.

The successor remains unallocated and this is source-only, unreleased
Foundation contract work. No Control implementation or CP adapter exists yet.

### ADR-0073: admission coordinates and full attestation-envelope digest

`AttestationEnvelopeV2.canonical_document()` now exposes the exact parsed full
envelope mapping, including `signature`; `attestation_envelope_digest()` hashes
that mapping with the package's canonical JSON rules. This is additive to the
existing `signed_bytes()` method: it does not change that method's return type
or wire meaning.

`verify_attestation_pair()` now requires the Control-derived
`expected_observation_id` (the signed dispatch coordinate) and
`expected_package`, refusing mismatches with the distinct public constants
`OBSERVATION_ID_MISMATCH` and `PACKAGE_MISMATCH`. `admit_host_source()` carries
the same two keyword-only inputs, for eight keyword-only parameters total, and
checks them before reading the installed artifact from the host.

The successor remains unallocated and this is source-only, unreleased
Foundation contract work. No Control implementation, signer, or positive
executor admission path is claimed here.

### Both mutating executors accept a host-source admission provider, handed over at construction

`host_source_admission.py` adds `HostSourceAdmissionProvider` (a Protocol
with one argument-free method, `admit_host_source() -> tuple[HostSource,
HostSourceAdmissionTrace]`) and `RefusingHostSourceAdmissionProvider`, the
reference implementation that delegates to
`require_host_source(receipt=None)` and therefore always refuses.
`engine/run.py`'s `Executor` and `recovery_execution.py`'s
`RecoveryExecutor` each gain a keyword-only `admission_provider` constructor
parameter defaulting to `RefusingHostSourceAdmissionProvider()`, so a caller
that supplies nothing observes exactly today's refusal behavior. Both
executors' `_verify_host_source` now delegates to
`self._admission_provider.admit_host_source()` — called fresh on every
`run`/`rollback` invocation, never cached across calls on the same instance —
and a supplied provider's `PreconditionFailed`/`SpecError` propagates
unchanged.

This is additive API under the current unreleased version; no successor is
allocated by this change. A provider that actually reaches Control's
trust-root/revocation/replay-consumption state to admit a real `HostSource`
is later, separate, cross-repo work — this change only wires the seam. The
protocol is not proof of that future provider: the shipped CLI supplies none,
and its three executor callsites remain refusal-only.

### `admit_host_source()` composes the v2 attestation seams into a `HostSource` — synthetic and UNWIRED

`host_source_admission.py` adds `admit_host_source()` and
`HostSourceAdmissionTrace`: the first function that turns a verified pair of
`AttestationEnvelopeV2` values into a real, checked `HostSource`. It calls
`verify_attestation_pair()` first (letting every existing refusal propagate
unchanged), then `verify_candidate_attestation()` again against the same
`candidate` object to obtain the authenticated subject, reads the
interpreter's own installed artifact only after the pair check succeeds, and
refuses with `host_source.DISAGREES` if that real reading disagrees with the
authenticated installed-host subject. `trusted_host_source.py` remains
zero-I/O; its additive canonical mapping and digest surface are preserved by
doing the one host I/O read here instead, and `require_host_source`'s
signature and behavior are untouched.

This is exercised today only against SYNTHETIC, non-secret attestation
envelopes built in the unit test suite. No executor calls this function:
`engine/run.py`'s `Executor` and `recovery_execution.py`'s `RecoveryExecutor`
are unmodified, and `HostSourceAdmissionTrace` is consumed by nothing in this
package. Wiring either executor to this function is later, separate work,
blocked on a delivery-seam decision that has not been made.

### A trusted host workload authenticates a candidate instead of trusting a parsed value

`verify_candidate_attestation()` is the one seam that turns a signed
`AttestationEnvelopeV2` into an authenticated `CandidateAttestationSubjectV2`,
checked against Control-resolved candidate trust roots. Its signature carries
no parameter for a subject, receipt, digest, or ad hoc root, so a caller
cannot hand in the fact it is supposed to prove. `verify_attestation_pair`
now calls this exact function for its candidate half rather than repeating
the check inline — there is exactly one candidate-verification code path in
this module. `CandidateReceipt` (`host_source.py`) is unchanged and remains a
plain parser value with no authority; this seam is what a host uses instead
of trusting it.

### Correction — 2026-09-08: verifier same-key refusal and recovery coverage gap

The v2 verifier retained the split-roots construction check but had lost the
independent verifier-level refusal for candidate and installed attestations
signed by the same key. `verify_attestation_pair` now refuses that pair before
trust-policy, root, or signature evaluation, using `public_key_fingerprint`
(`trusted-host-source-same-key-signed-both`), never the `key_id` label. Distinct
fingerprints carrying the same label remain an admitted near-miss under the
supplied policy.

The recorded 73-entry skip inventory is explicitly Executor tests only. It is
not RecoveryExecutor behavioral coverage: the real `RecoveryExecutor.run` ten-
step sequence remains separately UNMONITORED while the executor is
non-admitting. That named gap retires only with genuine trusted-provenance
admission AND coverage of the real `RecoveryExecutor.run` sequence; no skip is
retired here.

### Authorization receipt successor remains non-admitting

`AuthorizationReceiptV2` is a minimal Foundation consumer value consumed
through the typed `attest_authorization_receipt_v2()` composition seam after an
injected attester has checked both Control documents. The raw value has no
public execution-input gate; opaque `AttestedAuthorizationReceiptV2` owns the
combined liveness and equality check and exposes neither its parsed receipt nor
a reusable witness. It retains the two original
signed-document digests, distinct positional signer identities, authorization
and dispatch identifiers, decision reference, authorization/dispatch timing,
Control product code, environment, target, operation, Control `plan_digest`, descriptor
digest, Foundation execution-plan digest, execution sequence and
dispatch-owned attempt number. It has strict schema-tagged canonical bytes. The old
`AuthorizationReceipt` remains readable unchanged. Platform constructs this
plain value only after Control verifies standing and signatures; Foundation
does not re-decide standing. It is not authority, and post-issuance revocation
needs a future online or signed observation. Foundation compares the successor
against separately supplied execution inputs, including the approval
decision reference, and refuses before the signed dispatch issue time as well
as after authorization expiry. It does not import Control,
make a second canonicalizer, or introduce a positive executor admission path.
The injected attester is explicitly not an authority selector: no executor
accepts the returned type until trusted Platform composition and host
enrolment exist. Product-vocabulary mapping stays in that later Platform
adapter, avoiding a rewrite of the existing v2 wire schema here.

No version is allocated by this heading. `0.4.0a1` was built once from older
bytes and is spent; the successor coordinate is allocated only after the trust
composition freezes.

## 0.4.0a1 — unreleased, BUILT ONCE; UNRECORDED AND DRIFTED

### Correction: the v1 sidecar was held before freeze; v2 is a contract, not admission

The earlier `TrustedAttestationBinding` sidecar is removed.  It let key-id
labels stand in for public key material and did not bind custody, audience,
replay identity, root validity or the complete candidate subject.  That shape
is not extended across an artifact boundary.

`trusted_host_source.py` now defines `TrustedHostAttestation.v2`.  Each signed
envelope binds schema/purpose, issuer, key id, algorithm, public-key
fingerprint, custody domain, trust-root version, issued/expiry times,
role-specific audience, observation identity and a complete immutable subject.
Candidate subjects bind package/version/final wheel digest/source revision plus
the CandidateArtifact.v1 `repository`/`run_id`/`artifact_id` coordinates. Host
subjects bind the expected host identity supplied by Control, installed
package/version/digest and the digest of that complete candidate subject. The
authoritative owner and grammar for that host identity remain unresolved;
caller-selected paths convey no authority. Trust is over immutable
fingerprints, purposes and distinct custody domains, never labels. The pure
verifier refuses aliases of the same material, shared custody,
revocation/invalid roots, wrong purpose/audience, stale/future evidence, bad
signatures and subject mismatch.

This is only a typed parsing/testing contract. Observation identity is signed,
but atomic replay consumption belongs to future Control/admission ownership,
not this stateless verifier. The protected Starter release
workflow must author candidate evidence and a distinct target-local workload
must author host evidence; Platform transports only. Foundation holds neither
private keys nor a network client. Control has not yet installed those bindings.
There is consequently no positive executor admission before 0.4.0a2, no
preverified authority result, and both executors retain their unconditional,
zero-effect refusal. A successful verifier call proves agreement only relative
to the supplied policy and verifier; trusted composition must source both from
Control before that result can participate in authority. The 73 skip inventory
is unchanged.

### A caller who cannot produce two independently authored signatures cannot pass the host-source gate — the fail-closed verifier and sidecar contract, not yet admission

The entry below this one found no reachable trust root for either half of
trusted host-source provenance and, correctly, changed nothing about
`Executor`/`RecoveryExecutor`. Michael's sequencing correction that followed:
land the fail-closed verifier and the exact sidecar contract NOW, so the two
attestation producers and the rehearsal that composes them (future work —
Foundation frozen at a new version, Control V3, Platform CP's translator) have
something fixed to build against; admission itself waits until those exist and
is proved once, at that point, not claimed here.

`trusted_host_source.py` (new module) adds `verify_trusted_host_source()`,
which admits a `TrustedAttestationBinding` only when:

* a `CandidateArtifactAttestation` (envelope around the existing
  `CandidateArtifact.v1` document) and an `InstalledHostObservation.v1`
  envelope are BOTH present;
* each envelope's signature verifies against its OWN `SignatureVerifier`,
  using a `key_id` its OWN `AttestationTrustRoot` accepts;
* the two roots are STRUCTURALLY disjoint — `DistinctTrustRoots` refuses at
  CONSTRUCTION if `candidate.accepted_key_ids` and `installed.accepted_key_ids`
  share any key, so "two roots that happen to accept the same signer" cannot
  be built, not merely cannot be exploited;
* the two envelopes were not signed by the SAME `key_id` — checked first,
  before either key is matched against a trust root, so this refusal does not
  depend on `DistinctTrustRoots` having been configured correctly elsewhere;
* the authenticated candidate and installed contents agree (facility,
  version, artifact digest).

**This directly targets what sank both prior admission attempts**: a single
caller supplying both halves of the comparison from data it authored itself.
`tests/unit/test_deployment_foundation_trusted_host_source.py` proves it with
a REAL keyed-MAC `SignatureVerifier` (`hmac.new(secret, message, sha256)`,
`hmac.compare_digest` — not the codebase's own `"probe-valid"` magic string),
over two distinct secrets: a genuine two-authority pair admits; the identical
pair signed by ONE key instead is refused (`SAME_KEY_SIGNED_BOTH`) even though
each individual signature verifies; two trust roots sharing an accepted key
refuse at construction (`TRUST_ROOTS_NOT_DISTINCT`); a tampered document with
a stale-but-real signature, a genuinely valid signature from an untrusted key,
and two authentically-signed-but-disagreeing attestations each refuse with
their own named code.

**Not wired into `Executor` or `RecoveryExecutor`.** No production signer for
either half exists anywhere reachable in this repository (unchanged from the
entry below — re-measured: neither `foundation-candidate.yml` nor
`release-facility.yml` gained a sign/attest/cosign/sigstore/gpg step). Wiring
an unpopulated verifier field into `ExecutionBindings` now would repeat the
exact failure mode `execution_bindings.py`'s own docstring names for the seams
that already exist ("real for an embedder and decorative for the CLI"), so
this is deliberately not done. `_verify_host_source` on both executors is
unchanged and still calls `require_host_source(receipt=None)` unconditionally.

**Skip inventory: unchanged, 73 before and 73 after** (recomputed and diffed
against the recorded set — see `host_source_skip_inventory.py`).
`RETIRE_WHEN = "trusted-provenance-admission"` is met only when a real
admission path exists for either executor; this PR delivers the verifier and
the contract two future attestation producers can build against, not
admission, so nothing here retires.

### Trusted provenance was investigated (step 3) and found to have no reachable trust root today; nothing here admits, and nothing was wired to pretend otherwise

Michael's ruling for this step named the required shape precisely: an
externally committed/signed candidate attestation, an independently signed
installed-host observation, verified inside the executor against DISTINCT
trust roots, and no public "already verified" dataclass an arbitrary caller
can construct. This entry records what was actually found reachable in this
repository against that shape, MEASURED rather than assumed, and why neither
`Executor` nor `RecoveryExecutor` changed as a result.

**Candidate half.** `scripts/foundation_candidate.py` writes an unsigned
`CandidateArtifact.v1` JSON document from a GitHub Actions run; the only
document that ever reaches this repository is a plain file, committed by a
human-reviewed PR (`docs/inventories/foundation-candidate-*.json`). Nothing
signs it — `.github/workflows/foundation-candidate.yml` and
`release-facility.yml` were read in full; neither contains a `sign`, `attest`,
`cosign`, `sigstore`, or `gpg` step, and publication is a plain `twine upload`
to a private Forgejo index (`registry.dotmac.io`) with no build-provenance
attestation attached. So the ONLY assurance behind a committed candidate
receipt is git history and branch-protected review — a real trust root, but
not the "signed" one the ruling names, and not one `require_host_source` can
verify cryptographically today because it has nothing to verify it WITH.
Independently, the coverage gap the second failed attempt already measured
still holds: `docs/inventories/` carries receipts through `0.3.0a5`, the
declared version is `0.4.0a1` (`version.py`), and no
`foundation-candidate-0.4.0a1.json` exists — there is no candidate receipt for
the version this package would actually ship as.

**Installed-host half.** `read_installed_artifact` reads PEP 610
`direct_url.json`, written by pip itself at install time with no signature of
any kind — it is the installer's own unauthenticated bookkeeping, not an
"independently signed" observation by any party distinct from whoever ran
`pip install`. No mechanism anywhere in this repository produces a signed
statement about what is installed on a host; `evidence.py`'s
`SignatureVerifier`/`TrustPolicy` pair is the one place this facility already
knows how to verify a signed document without holding a crypto dependency
itself (ADR-0070, zero runtime deps — the assembly supplies the verifier and
carries the trust root), but it exists today for `ReleaseEvidence.v1` (a
revision had a green CI run) — a different subject from "this installed
artifact is the one a release process built" — and `ExecutionBindings`
(`execution_bindings.py`) has no host-source-purpose verifier field. Even
where that pattern IS wired (`evidence_verifier`, `recovery_verifier`), no
production caller supplies real key material anywhere reachable from this
repository — `scripts/release_facility.py`'s own probe uses a literal
`"probe-signer"`/`"probe-valid"` stub, and no assembly in this repository
declares the `dotmac_deployment_foundation.execution_bindings` entry point
with real bindings. `execution_bindings.py`'s own docstring names exactly this
failure mode for the seams that already exist ("real for an embedder and
decorative for the CLI") — adding an unpopulated host-source verifier field to
`ExecutionBindings` now would be that same shape again, not a step past it.

**Conclusion.** Both trust-root positions the ruling requires are open
architecture decisions, not implementation gaps: what signs a candidate
attestation and with what key custody; how that attestation reaches a
`pip install`ed consumer that by design carries no source checkout (`launcher.py`
already refuses to run from one); what independently signs an installed-host
observation, and who holds that second key. None of these is a choice this
change makes. `Executor.__init__`/`RecoveryExecutor.__init__` therefore accept
no new parameter, `_verify_host_source` still calls
`require_host_source(receipt=None)` unconditionally, and both executors keep
refusing in every environment — the identical SAFETY-ONLY posture the prior
entry established, now with the "what would have to exist" question answered
rather than left open. `tests/architecture/host_source_skip_inventory.py`'s
73 recorded entries are unchanged (73 before, 73 after): `RETIRE_WHEN =
"trusted-provenance-admission"` is not met by an investigation that found no
admissible path, and retiring any of them here would misrepresent what was
proven.

### The host-source seam was respelled, not closed, and is now GONE entirely — SAFETY-ONLY until trusted provenance exists

An independent review at exact head `541cee5d` found that the entries below
this one — which removed `host_source_installed`/`host_source_probe` and
resolved the receipt from a committed, version-derived path — repeated the
defect they claimed to close, twice over:

1. `Executor.__init__`/`RecoveryExecutor.__init__` still took BOTH halves of
   the admission decision. `host_source_receipt` (a plain frozen
   `CandidateReceipt`, constructible by anyone, carrying `artifact_digest`
   directly) paired with `host_source_metadata` (an `InstalledMetadata`
   Protocol whose `read_text("direct_url.json")` returns a caller-chosen
   string that becomes the offered digest) let a caller state the SAME
   digest on both sides of `require_host_source`'s one comparison —
   byte-for-byte the admission `host_source_installed=` originally produced,
   with a `json.dumps` in between. `valid_host_source_kwargs()`
   (`tests/unit/host_source_stance.py`) WAS that exploit, shipped as a
   convenience fixture every "admitted executor" test used.
2. Receipt resolution moved the caller's choice rather than narrowing it out
   of existence: "name a file" became "name a directory containing a file
   whose name you can derive", and the recovery test's `tempfile.mkdtemp()`
   with a self-authored receipt exercised that same shape as a "genuine
   admit".
3. The committed-directory default was measured UNREACHABLE even in this
   repository: `docs/inventories/` held `0.3.0a1`–`0.3.0a5`, the declared
   version was `0.4.0a1`, and the existing tests globbed `0.3.0a*` /
   hardcoded `"0.3.0a5"`, so nothing noticed the gap.
4. `DEFAULT_CANDIDATE_RECEIPTS_DIR` was CWD-relative with no flag on
   `restore-rehearsal` to redirect it — the lowest-risk mutating path got a
   permanently unsatisfiable gate, silently.

**Michael's ruling: reshape into a SAFETY-ONLY change.**
`Executor.__init__`/`RecoveryExecutor.__init__` now accept **no host-source
parameter of any kind** — no receipt, no metadata, no directory.
`_verify_host_source` always calls `require_host_source(receipt=None)`,
which always refuses — a typed refusal (`ABSENT`/`WRONG_KIND`/`NO_RECEIPT`)
with zero effects, in EVERY environment, including this repository's own
unit-test job. `resolve_committed_candidate_receipt`,
`installed_distribution_version` and `DEFAULT_CANDIDATE_RECEIPTS_DIR` are
removed from `host_source.py` entirely, along with the CLI's
`--host-source-receipts-dir` option — there is nothing left to configure.
`CandidateReceipt` and `InstalledMetadata` remain useful PARSING interfaces
(and `require_host_source` itself remains a general-purpose function, still
taking `receipt=`/`installed=`/`metadata=`/`source_tree_digest=` for its OWN
direct unit tests) — they are simply never treated as authority-bearing
evidence by either mutating executor again.

**Justification for the strong form** (Michael, verbatim): *"An unusable
production path is currently safe because no production caller exists."*
`scripts/deploy.sh` drives `docker compose` directly; `deploy --execute` has
no caller in this repository. A gate that refuses everything costs nothing
today and stops a forgeable one shipping.

**Coverage lost, named rather than hidden.** Every test that built an
"admitted" `Executor`/`RecoveryExecutor` to reach past the gate and exercise
something downstream of it (the authorization cross-matrix, failure
injection, principal bootstrap, deployment evidence, lock capability,
external recovery, the ten restore steps) can no longer do so through this
seam. `valid_host_source_kwargs()` now calls `pytest.skip(...)` rather than
returning admitting kwargs, naming every remaining caller's lost coverage
explicitly rather than crashing or silently passing.
`test_deployment_foundation_recovery_execution.py`'s ten-step behaviour tests
were reduced to individual step-handler tests rather than copied into a
second dispatch loop. The complete sequence is therefore UNMONITORED through
the executor itself until trusted provenance lands; no test-only loop or
constructor hook recreates reachability merely to keep those tests green.

**Trusted provenance is separate, future work, and nothing here starts it or
leaves a hook for it:** an externally committed/signed candidate attestation,
an independently signed installed-host observation, verification inside the
executor against DISTINCT trust roots, and no public "already verified"
dataclass an arbitrary caller can construct.

### `host_source_installed`/`host_source_probe` were not test-only — they were a live bypass, and are removed

**SUPERSEDED by the entry above** — the repair this entry describes (keeping
`host_source_receipt`/`host_source_metadata`) was itself the next round of
the same defect. Left below for the historical record of what was tried and
why it was insufficient.

Calling them "test-only override hooks" (see the entry below) never made them
one: `Executor.__init__` accepted `host_source_installed` (a pre-built
`InstalledArtifact`) and `host_source_probe` (a callable standing in for the
launcher digest) from ANY caller, and `_verify_host_source` forwarded both
straight into `require_host_source` as `installed=`/`source_tree_digest=`.
A caller passing `installed=InstalledArtifact(artifact_digest=X, ...)`
alongside a receipt naming `sha256=X` was admitted without a single byte of
either claim ever being read from the running interpreter or the launcher.
The architecture coverage guard
(`test_deployment_foundation_host_source_coverage.py`) only ever asserted
`_verify_host_source` was CALLED, never what it was fed, so nothing caught
this.

Both parameters are removed from `Executor.__init__`. `host_source_metadata`
(typed to the `InstalledMetadata` Protocol) is the ONE remaining seam — it
still drives the real `RECORD`/`direct_url.json` parse through
`read_installed_artifact`, never a digest handed over directly. A new
`tests/architecture/test_deployment_foundation_host_source_constructor_seam.py`
proves, by AST, that neither forbidden parameter exists on `Executor.__init__`
or on the new `RecoveryExecutor.__init__` (see below), with a sensitivity
proof (a planted regrowth of both parameters is named; the repaired shape
stays silent).

### The committed candidate receipt is resolved by installed version, not a caller-chosen path

**SUPERSEDED by the entry at the top of this section** — the mechanism this
entry describes (`resolve_committed_candidate_receipt`,
`DEFAULT_CANDIDATE_RECEIPTS_DIR`) is REMOVED, not merely no longer wired to
the executors; it narrowed a caller's choice without closing the underlying
admission. Left below for the historical record.

`--host-source-receipt PATH` took an arbitrary file. `candidate_receipt_from_
mapping` only checks schema and 40-hex `source_sha`; nothing checked the
receipt was committed, signed, or named a real commit. Anyone who could read
a host's own `direct_url.json` could author a document naming the same
`sha256` and pass `require_host_source`'s transitive-link check with a
receipt describing bytes nobody built.

`host_source.resolve_committed_candidate_receipt(version, receipts_dir=...)`
derives the filename itself — `foundation-candidate-<version>.json` — from
the installed version (the same fact `require_host_source` already reads),
never from a caller. `--host-source-receipt` is replaced by
`--host-source-receipts-dir` (default `docs/inventories`, the committed
directory this repository already uses for `dotmac-deployment-foundation`'s
own candidates): a NARROWER capability than the path it replaces, since it
names only WHERE to look, never WHICH file — admitting a receipt for version
V still requires `foundation-candidate-V.json` to be a committed document.

**Reachability, stated plainly rather than assumed:** the default resolves
correctly when `dotmac-deploy` is invoked with its working directory inside a
checkout that carries `docs/inventories/foundation-candidate-<version>.json`
for the INSTALLED `dotmac-deployment-foundation` version — which is true of
this repository (`scripts/deploy.sh`'s own `DEPLOY_DIR` defaults to its
checkout root), but is **not** the general shape this facility documents
itself as serving ("the one command every product's CI and host runs").
A different product that only `pip install`s this package as a dependency has
no reason to carry `dotmac_starter_mt`'s `docs/inventories/` at all — that
directory holds the FOUNDATION's own candidate records, committed in the
FOUNDATION's own source repository, not the consuming product's. Such a
consumer would need its own pipeline to fetch or vendor the matching receipt
onto the host and point `--host-source-receipts-dir` at it. No search path
across multiple locations was added to paper over this — a search path is a
caller-influenceable choice by another name, which is exactly the shape this
change removes. This is an open operational gap for any consumer other than
this repository, not something resolved by this change, and it is not fixed
here: the fix (attaching the matching receipt to the published artifact
itself, e.g. as package data or a release asset) is a packaging/release
decision outside this task's boundary.

Separately, and also measured rather than assumed: `dotmac-deploy deploy
--execute`/`rollback --execute` have no caller anywhere in THIS repository
today — `scripts/deploy.sh` (this repository's own production deploy path)
uses `docker compose` directly and never invokes this facility's CLI, and
`--host-source-receipt`/`--host-source-receipts-dir` appear in no workflow or
script. The mechanism this and the prior entry describe is exercised by its
own unit tests; it has no production caller in this repository to observe.

### `RecoveryExecutor` gets the same mandatory prerequisite, through the same seam, never by caller injection

**UPDATED by the entry at the top of this section** — the "same seam" this
entry built (`host_source_metadata`/`host_source_receipts_dir`, resolving
internally) is REMOVED; `RecoveryExecutor` now takes no host-source
parameter at all, exactly like `Executor`. The prerequisite itself (called
before `_do_fresh_target`) is unchanged and still correct. Left below for
the historical record of the seam's shape before the second round of repair.

`_do_fresh_target` — this class's first effect, creating a cluster — ran with
no host-source check at all, and `cli.py`'s `restore-rehearsal --execute`
constructed it with nothing that could supply one. Boundary 4's ruling ("the
same prerequisite covers every mutating executor path") applies to it exactly
as it applies to `Executor.run`/`rollback`.

The naive repair — adding `host_source_receipt`/`host_source_probe`
constructor parameters a caller fills in directly — would reproduce the exact
bypass shape the entry above removes. Instead `RecoveryExecutor` accepts
`host_source_metadata` (the identical test seam `Executor` keeps) and
`host_source_receipts_dir`, and resolves its OWN receipt internally, from the
installed version, via the same `resolve_committed_candidate_receipt` the CLI
uses for `Executor`. There is no `host_source_receipt` constructor parameter
on this class at all — the receipt is never a caller-supplied value.
`_verify_host_source()` runs before the plan-drift check and before the
dispatch loop, so a wrong-artifact host cannot reach `create_fresh_target`.

### `CandidateReceipt`/`HostSource` now carry the candidate's location coordinate

Every committed `docs/inventories/foundation-candidate-*.json` already
records `repository`/`run_id`/`artifact_id` — the `(repository, run_id,
artifact_id)` triple that LOCATES the workflow evidence for a candidate, as
distinct from `sha256`, which IDENTIFIES the wheel it produced. Nothing read
them. `candidate_receipt_from_mapping` now requires all three (a receipt
missing them previously parsed cleanly with no way to trace which workflow
run produced it), and `require_host_source` binds them onto the resulting
`HostSource` alongside `source_revision`.

This is the scope achievable from this facility alone. The product/target/
environment/lease/approval-status subject terms Control signs are NOT bound
here and cannot be: `rehearsal_grant.py`, the module that bound them
(`product_code`/`target_id`/`environment`/candidate triple/execution-plan
digest), was reverted from `main` in #661 (`2879b57c`, reverting #655) before
this change landed, and is deliberately not restored or reimplemented by this
change. `authorization.py`'s `ExecutionGrant`/`AuthorizationReceipt` binds
`operation`/`descriptor_digest`/`target`/`execution_plan_digest` plus an
approval window (`policy_code`/`decision_ref`/`expires_at`) through a wholly
separate mechanism, and carries no `product` or `environment` field at all —
so "product" and "environment" are not currently bindable ANYWHERE in this
facility, by any mechanism, pending that module's repair and Michael's ruling
on what replaces it.

### `HostSource` binds facility, VERSION, digest and a full source revision — not two of the four

`require_host_source` compared facility and artifact digest but never the
receipt's `version` against the installed distribution's, and
`candidate_receipt_from_mapping` accepted any nonempty `source_sha`. A
candidate receipt for `version="9.9.9"` with `source_sha="not-a-commit"`
therefore bound cleanly against a matching digest — a receipt for a build
that never happened, naming a tree that does not exist, admitted because the
two checked terms happened to agree.

`require_host_source` now refuses a version disagreement under the same
`DISAGREES` code the facility check already uses, naming both versions.
`candidate_receipt_from_mapping` now requires `source_sha` to be a full
40-character lowercase-hex commit, under a new `MALFORMED_SOURCE_REVISION`
code — the identical shape `scripts/release_facility.py
::candidate_source_revision` already enforces on the same field, so a receipt
is refused by one rule whether it is read there or here.

Two further corrections, same module, same review:

* `Digest.parse` raised an uncoded `SpecError` straight through
  `read_installed_artifact` for an unparsable installer-recorded hash (e.g.
  `archive_info.hashes.sha256="not-a-digest"`), despite this module's stated
  contract of `PreconditionFailed` refusals with unreadable provenance
  classified `ABSENT`. Converted deliberately, at the one call site, into the
  same coded refusal every other malformed-metadata case already raises.
* `InstalledArtifact.read_from` unconditionally named
  `archive_info.hashes.sha256` even when the digest was read from the legacy
  `archive_info.hash` spelling PEP 610 also permits — a small reporting lie
  that would send an operator to the wrong line of a real `direct_url.json`
  mid-incident. It now names whichever key was actually read.

No version is allocated; `0.4.0a1` was built once, but is unrecorded and
drifted, so it remains unpublished and spent; see the candidate-state
correction below.

### The executor calls `require_host_source` itself — a handed-in `HostSource` proves nothing

`host_source.require_host_source` existed and nothing mutating a host ever
called it. `HostSource` is a plain frozen dataclass; a caller handing one to
`Executor` would prove only that the caller could construct a dataclass, not
that the installed artifact was verified. Boundary 4's ruling: the executor
must perform the call itself, against inputs it cannot forge.

`Executor.run` and `Executor.rollback` now call a new `_verify_host_source`
prerequisite immediately after the caller's deployment-lock hold is proven and
before everything else — grant revalidation, execution-plan digest
recomputation, the `deployment.start`/`deployment.rollback` annotation,
principal bootstrap, every step. `Executor` accepts the RAW ingredients
`require_host_source` itself checks (`host_source_receipt`, plus
`host_source_installed`/`host_source_metadata`/`host_source_probe` test-only
override hooks) rather than a `HostSource`, so there is no parameter that
satisfies the gate without going through the call. `cli.py`'s `deploy` and
`rollback` subcommands gained `--host-source-receipt`, loading the committed
`CandidateArtifact.v1` and handing it to the executor; the executor is still
what verifies it.

Measured, not assumed: this package is a Poetry path dependency with
`develop = true` (`pyproject.toml`), which installs it EDITABLE in this
repository's own `poetry install` unit-test job — the shape `host_source.py`
already documents as unable to answer either question it asks. The mandatory
gate therefore refuses under that install, by design: a release only ever
executes against a wheel-installed artifact (`.foundation-candidate`,
`.lane3-foundation`, or the equivalent CI venv), and refusing a dev checkout is
the property being enforced, not a defect. No bypass, environment flag, or
degraded-start path was added for this; unit tests that need to reach past the
gate inject `host_source_receipt`/`host_source_metadata` fakes, the same
pattern `host_source.py`'s own tests already use for `InstalledMetadata`.

### Candidate-state correction — 2026-09-05

Run `33920058598` built `0.4.0a1` once from protected-main source
`753a004e7f8dbab034d5d6ca565c680d931a5309` as artifact `9954731961`.
Its `CandidateArtifact.v1` receipt remained in the workflow artifact and never
entered this repository. Commits `#628` and `#631` then changed the facility's
importable source under the unchanged version. The build oracle records both
facts as `unrecorded` and `drifted` in
`tests/architecture/candidate_window_baseline.json`.

Consequently these bytes are not an admissible rehearsal or publication
coordinate, and `0.4.0a1` must not be rebuilt or published. The latest
published Foundation remains `0.2.0a2`. Closing the candidate window and
allocating any successor are separate authorized lifecycle acts; this
changelog does neither.

### `version_binding_guard.py` now refuses this coordinate offline — 2026-09-06

The freeze-oracle gap: `scripts/version_binding_guard.py` read tags,
`CandidateArtifact.v1` receipts and `CandidateDisposition.v1` entries, and none
of the three had anything to point at for `0.4.0a1` — its receipt never
reached this repository, so the guard ADMITTED it for both a candidate build
and a release, exactly the coordinate the paragraph above says must never be
rebuilt or published.

A fourth typed binding source, `spent_identity_bindings`, reads
`SpentIdentity.v1` rows from `docs/inventories/spent-version-identities.json`
by schema, the same way the guard already reads a disposition log. Two rows
seed it: `0.4.0a1` (built once, unrecorded, drifted — the coordinate above,
by run `33920058598` and artifact `9954731961`) and `0.3.0a6` (declared,
never built, retired unbuilt — a separate, older gap this facility's ledger
already carried). Both are now refused for `--purpose candidate` and
`--purpose release`, offline, with no GitHub access. Neither row authorizes
committing the drifted receipt, appending a disposition, or allocating a
successor — those remain Michael's decisions.

### An absence proof can only prove the concern its inventory belongs to

`IntegrationSurfaceAbsenceProofV1` validated `families` against
`INTEGRATION_SURFACE_FAMILIES` while its `concern` field accepted **any of the
thirteen**. A proof with `concern=WORKER_EXECUTION` carrying integration
families therefore constructed cleanly — and then **passed the profile's
misfiling guard**, because that guard compares the slot key with this same
`concern` field. The two things that agree were the two things checked; the
inventory, the only thing that would have disagreed, was never consulted.

The misfiling guard is not vacuous — it catches a correctly built proof filed
under the wrong key. It cannot catch a proof **built against the wrong
inventory**, which is the earlier and quieter defect.

Construction now refuses a concern other than `INTEGRATION`, under a **new**
code `absence_proof.unsupported_concern`. Deliberately not
`ABSENCE_WRONG_CONCERN`, which already means two things — "not a
`FoundationConcern`" at construction and "wrong slot key" at the profile level.
A third meaning would make three different repairs indistinguishable in a log.

Both halves are exercised: the refusal fires for three non-integration concerns,
and `INTEGRATION` still constructs — a guard that refused everything would
satisfy the first test completely while making the type unusable.

### `HostLeaseRelease.v1` says which ARTIFACT ran, and separately which RUNNER

`source_revision`'s own docstring said *"WHICH artifact ran — a release from
another candidate's run is evidence about another run"*, and the Lane 3 runner
populated it with its own head SHA. The field said one thing and carried
another, so a destroyer reading it attributed the bytes to the wrong commit.

- `source_revision` is renamed **`candidate_source_revision`** and is populated
  from the committed `CandidateArtifact.v1`, through the runner's
  `--candidate-source-revision` argument;
- **`runner_revision`** is added, populated from `--foundation-revision`.

Both are required and both reach `as_document`, the parser and the digest, so
the writer and the reader cannot drift apart on the rename.

**No publication revision, and this is the deciding reason rather than an
omission: the Lane 3 runner cannot observe it.** A release is sealed before any
commit has been chosen to publish. Any value would be a guess, a default, or a
copy of one of the other two, and each reads to a destroyer as an established
fact. A field its only producer cannot fill truthfully must not exist.

That statement was true only against the two candidates checked at authoring
time (`0.3.0a1` and `0.3.0a5`). The file later crossed the `0.4.0a1` candidate
boundary before this change; the change is therefore part of a1's recorded
source drift and cannot be published under that identity.

### `IntegrationSurfaceAbsenceProofV1.image_digest` → `artifact_digest`

Not cosmetic. It follows a ruling about **what the proof binds: the Platform
application wheel, not the OCI image the proof travels inside.** A proof
embedded in an image cannot carry that image's own digest — the digest is over
the finished image, and the image is not finished until the proof is in it. The
old name asked a producer for a value that does not exist yet, and every way out
of that is worse than the rename.

The field, the `satisfies` keyword, the emitted document key and the prose all
move together; `satisfies` is keyword-only, so a caller still passing an OCI
image digest gets a `TypeError` rather than a proof that quietly never
satisfies. Every other `image_digest` in this package is a real OCI image digest
and keeps its name.

The earlier shape of this type also crossed the `0.4.0a1` candidate boundary.
The rename is part of a1's recorded source drift and cannot be published under
that identity.

### Ruling 4 — the three revisions stand in a stated RELATIONSHIP

Neither equality nor nothing.

Equality recreates the bootstrap loop `foundation-candidate.yml` exists to
break: a candidate must be buildable BEFORE the commit that rehearses it, so
every later commit would invalidate it and the release could never be satisfied.
All five recorded candidates were built at commits that are ancestors of `main`
and not its head. Requiring nothing is the opposite failure: a candidate built on
a divergent branch, rehearsed and published by a protected-main run, with
nothing saying the bytes came from code that was never on main.

`release_facility.require_revision_relationships` enforces **ancestry**, against
BOTH protected revisions — checking only one leaves the other open. Equality
satisfies ancestry, so a candidate built at the tip is still allowed.

An unknown commit refuses as a FETCH problem and names `fetch-depth`, separately
from a known non-ancestor, because a shallow clone answers "not an ancestor" for
two commits that are related — which reads exactly like the defect and is how a
real guard gets disabled.

`require_tag_peels_to` enforces that **the version tag peels to the candidate
source commit**, in the strict sense: `rev-list -n 1`, the peeled commit, never
`rev-parse`, which returns an annotated tag's own object sha. The release lane
now tags the commit the bytes were built from rather than the release run's SHA
— a tag pointing at a tree that was never built sends a consumer inspecting what
they installed to code that is not what they installed — and records the
release-adapter revision separately in the annotation.

The exact-digest half is unchanged and deliberately not re-derived:
`verify-candidate` compares the bytes with the receipt and `require_rehearsal.py
--artifact-digest` compares the receipt with the bytes.

### Three revisions, three bindings — and one of them was bound to nothing

The build/rehearse/publish sequence involves three commits and they answer three
different questions:

- the **candidate source** revision — what the artifact was built from. It lives
  in the committed `CandidateArtifact.v1` as `source_sha`;
- the **Lane 3 runner** revision — whose runner drove the rehearsal. The
  rehearsal run's own head SHA, recorded as
  `RehearsalReceipt.v1.foundation_revision`;
- the **release/tag** revision — what publishes.

Two of them were already bound: `verify_publication` refuses unless the
receipt's revision equals the release revision. The candidate source revision
was bound to nothing at all — `resolve-candidate` never emitted it, so no
downstream step could refer to it, let alone compare it.

`release_facility.candidate_source_revision` emits it, refusing an absent, empty
or abbreviated value rather than passing on something that can only ever compare
unequal. Lane 3 now receives it as `--candidate-source-revision`, separate from
`--foundation-revision`, and records all three facts it can establish in its
terminal evidence.

### `require_rehearsed_artifact` — publication binds the receipt to the BYTES

New, and additive: `RehearsalReceipt.v1` is unchanged and no document changes
shape. `RehearsalReceiptV1.foundation_artifact_digest` exposes a field
`build_receipt` has always written unconditionally.

Nothing previously compared the receipt with the artifact, so a rehearsal of
candidate A satisfied a publication of candidate B whenever both ran at the same
commit — and `candidate_version` is a dispatch input on `exposure-rehearsal.yml`
precisely so that two candidates CAN be rehearsed from one SHA.

This is also what makes the candidate source revision real without widening a
shipped record: the digest identifies exactly one `CandidateArtifact.v1`, and
that record names exactly one `source_sha`. `RehearsalReceipt.v1` has crossed an
artifact boundary in five built candidate wheels, so adding a field to it would
make one schema name identify two contracts — the defect this package has
already paid for. The revision is therefore bound transitively and provably
rather than by amendment.

It is a separate function rather than a keyword on `verify_publication`: a
keyword with a default is a check the caller may omit and nobody notices; a
second function the gate must CALL is a check whose absence is visible in the
gate's own source. `require_rehearsal.py` takes `--artifact-digest` as a
REQUIRED argument, so a lane that forgets it does not run.

### Import isolation needs `-E -P`, not just a venv

Lane 3 and the publication gate both install the digest-verified candidate into
a venv and drive their scripts with that interpreter. A venv does not make the
wheel the only importable copy: `PYTHONPATH` is honoured by every interpreter,
so a step that exported it — or a runner image that ships it — puts the
checkout's `packages/dotmac-deployment-foundation/src` back on the path. The
rehearsal would exercise the SOURCE and pass identically whether or not the
wheel is correct, which is the one outcome the whole sequence exists to prevent.

Both invocations are now `-E -P`: `-E` makes `PYTHONPATH` inert, `-P` keeps the
script's own directory off `sys.path`. `-P` costs the runner nothing because it
re-adds that directory itself, from an absolute path derived from `__file__`.

The isolation is PROVED rather than asserted: one control shows a plain
interpreter really does import a decoy `PYTHONPATH` names, and its pair shows
`-E -P` makes the same path unreachable. A flag string in a YAML file that
nobody has watched work is exactly as good as no flag at all.

### A refusal after mutation has a member: `host_state_uncertified`

`TerminalRefusal.PROVOCATION_UNESTABLISHED` is RENAMED and GENERALIZED to
`HOST_STATE_UNCERTIFIED` (value `host_state_uncertified`). The member count is
unchanged at six; nothing was added.

The old member named ONE instance of a condition — a foreign-rule provocation
that could not be established — and therefore left every other instance of the
same condition with no member at all. The live one: a `StepFailed` from a
compose apply on the host had no vocabulary member anywhere, so a failed apply
left the host MUTATED with no release record and no closure, on any run where
the apply fails. The generalized member covers both, because both need the same
operator action: `inspection_required` or `destroy_only`, and never `reusable`.

Note the modality — mutation **may** have begun, not did. The member exists for
the case where nobody can say. Constraining the closure does not excuse the
cleanup axis: `cleanup` is still required and reusability is still the
intersection of the two constraints.

`exposure_rehearsal_runner.classify_refusal` answers by TYPE first and then by
whether an exact lease was in hand. Type alone is not enough: `errors.py`
documents `PreconditionFailed` as "a gate refused before anything was mutated"
and `ExposureTransaction.run` raises it after applying the stack and rewriting
both filter chains, while `SpecError` is raised both by
`ProductDeploymentSpec.load` before host contact and by `build_receipt` after the
whole transaction. One type, opposite operator actions.

### Three terminal cases, so the classifier answers on TWO facts

`classify_refusal` took `host_mutated` alone, and a single boolean has two values
for three cases — so the third case borrowed one of the others' answers. It takes
`lease_in_hand` as well:

- **no exact `HostLease.v2` in hand** — a descriptor that will not parse, a lease
  that is missing, expired, or issued for another authorization run: NO member
  and no release. A release discharges a lease, and there is none. An expired
  lease stays `EXPIRED_HELD`, which is `HostStanding`'s answer for a holder
  nobody can ask anything of;
- **the lease in hand, and an invocation defect the lane PROVED before host
  contact or mutation** — `precondition_unfit`;
- **the lease in hand, and a generic failure that prevented host state from being
  established** — `host_state_uncertified`, EVEN WITH
  `host_mutation_attempted=false`. Holding the lease means the run owned the
  host; a refusal it cannot name means it could not establish what state that
  host is in. "Nothing was attempted" and "nobody can say" are different claims.
  `_PERMITTED_CLOSURES` already bounds the member to `inspection_required` or
  `destroy_only`.

`host_mutated` is no longer the discriminator; it is the CHECK on the second
case's premise. `precondition_unfit` is the only member whose meaning is a claim
about the machine, so a refusal of that kind arriving past first mutation
degrades to `host_state_uncertified` rather than asserting an untouched host —
the site-134 drift, caught by the classifier instead of only by a position test
over an arrangement of lines.

The terminal-evidence sidecar records `lease_in_hand` beside
`host_mutation_attempted`, so a reader can tell the three cases apart without
re-deriving them from the notes.

One consequence, stated rather than left to be found: `run` parses
`--controller-identity` before it loads the lease, so a malformed fingerprint
records no member. `TerminalRefusal`'s table still maps that refusal to
`precondition_unfit` and the mapping is right; whether the parse should move
behind `load_lease` so the case becomes recordable is OPEN.

### The `TerminalRefusal` mapping table is keyed semantically, not by line

It filed sites by line number and the numbers went stale: three
`precondition_unfit` sites were recorded as "host untouched, safely releasable"
while sitting after the compose stack had been applied. The table is now keyed by
the question each refusal answers and by its position relative to first mutation,
and the position is checked against the code by
`tests/unit/test_lane3_terminal_release.py`.

The inside-vantage probe no longer appears under two members at once:

- a missing harness, argument or jump key, detected BEFORE host contact, is
  `precondition_unfit`;
- the probe subprocess exiting non-zero, AFTER mutation, is `evidence_unreadable`;
- `probe_refused` applies only where a probe actually ran and refused.

### `ControllerSshFingerprintV1`, on both planes, and a rename before the build

The controller key fingerprint was a bare string on `HostLease` (checked only for
being non-empty) and on the release plane was validated against
`^sha256:[0-9a-f]{64}$` — the shape of a CONTENT DIGEST, not of an OpenSSH
fingerprint. `ssh-keygen -lf` emits `SHA256:` followed by 43 characters of
unpadded base64, so the documented way of producing the value could not produce
an accepted one, and the accepted shape was not a key fingerprint at all.

`ControllerSshFingerprintV1` establishes the value by DECODING it — the exact
`SHA256:` label, strict standard base64, exactly 32 bytes, and the canonical
spelling — rather than by widening a pattern, because a wider pattern accepts
more strings without establishing what any of them is. Equality is over the
decoded digest, so the destroy gate's comparison answers about the KEY: a
well-formed fingerprint of the wrong key is refused where it is compared.

`HostLeaseReleaseV1.host_mutation_evidence` is RENAMED to
`controller_identity_fingerprint`, the name `HostLease` already used for the same
fact. One thing with two names across a boundary where the two are compared
invites a reader to conclude they are different facts. The rename is present
in the `0.4.0a1` candidate bytes, but those bytes are
unrecorded, drifted and inadmissible. No published Foundation artifact has
carried `HostLeaseRelease.v1`; a published schema would have had to carry both.

`HistoricalLeaseV1` keeps a bare `str`, deliberately: it reads `HostLease.v1`
records written by five shipped candidate wheels under a validator that required
only non-emptiness, and parsing them strictly would make a real historical record
unreadable. It reports what a record says; it grants nothing on the strength of
it.

Allocated 2026-09-04. A MINOR bump rather than a seventh alpha of the `0.3.0`
line, and the reason is a new CAPABILITY rather than a size judgement:
authorized recovery of a FAILED PRODUCTION SYSTEM — an act that mutates
something already existing, with its own `RecoveryExecutionPlanV1` (a
deployment-shaped plan is not a recovery plan), an authorization binding, the
replay coordinate echoed, a signed and settleable result, and the three
bindings a rehearsal does not take: a captured prestate, the failed system's
own observed state, and a desired poststate.

### `recover` is NOT added to `authorization.OPERATIONS` by this release

An earlier draft of the paragraph above said it was. That was a commitment this
changelog had no standing to make, and it is withdrawn before it ever reached
`main`.

Michael's withdrawal of `recover` stands. The annotation at that constant —
*"WAS a member for one commit and is WITHDRAWN; that reversal is the record"* —
exists precisely to stop the member being re-added in order to close a gap, and
a version-allocation note is exactly the kind of place that repair would get
made quietly. Which authorization vocabulary carries the recovery act is an open
decision, not a consequence of the bump.

### The counterparty divergence, measured

Read 2026-09-04 against `dotmac_deployment_control` at the peeled `a11` tag
`98b2a257f4185ee134b54a0349ad09d76f05286b`:

- **Control's vocabulary is `{deploy, rollback, recover}`; this facility's is
  two.** Control's own module docstring says its vocabulary is closed so that it
  cannot *"freeze, sign and dispatch an authorization the executor is
  structurally unable to honour"* — and at `a11` it can. `recover` went in at
  `a10` on the stated premise that this facility's `a5` was being built against
  the same three members; the Shape B ruling falsified that premise, and nothing
  on Control's side refuses it.
- **There is no recover-specific settlement contract to implement against.**
  Control's `settle_attempt` is operation-agnostic: it settles on OUTCOME
  (succeeded / failed / timed out / cancelled) and never reads `operation`.
  There is no recover-specific receipt shape and no recover-specific
  verification. So what `0.4.0a1` must produce is a result Control's existing
  operation-agnostic settlement path can consume — not conformance to a shape
  that does not exist.
- **On this side the divergence fails LOUDLY, which is the one reassuring fact
  in it.** `AuthorizationReceipt.__post_init__` reads `OPERATIONS` rather than
  respelling it (the #603 repair) and raises `SpecError` on `recover` at
  construction — before a grant exists, before a plan is rendered, before any
  effect. A dispatched `recover` authorization is unusable here, not silently
  admitted. That is the correct failure and it is still a failure, which is why
  the repair belongs on Control's side rather than in a quiet widening here.

**Why the allocation happened before the work rather than after it.** The rule
this package enforces — *a tree that diverges from a built artifact allocates a
new version* — does not apply here, because `0.3.0a6` was never built and its
name covers no bytes. What applies instead is the precedent set by #602 and
#597: allocate in its own change, then build the contract under the new name,
so a reviewer sees the identity move as a diff of its own rather than buried in
the change that motivated it.

### What retiring an UNBUILT name costs, and why it is not free

`0.3.0a6` is the first name in this package's ledger retired without an
artifact, and the shape is new:

- **A spent NAME without a spent artifact.** Every earlier retirement was spent
  by bytes — a wheel existed, so a second build would have made one name mean
  two artifacts. `0.3.0a6` has no wheel and no `CandidateArtifact.v1` receipt.
  What it has is publication in DOCUMENTS: while it was the declared identity,
  `main` advertised it in this file, in `docs/MODULE_CATALOG.md`, in the
  `poetry.lock` path-package line, in
  `docs/inventories/declared-publication-baseline.json`, and inside the
  rendered `deploy/rendered/docker-compose.yml` labels by way of
  `io.dotmac.deployment.configuration.digest`. Re-declaring it would recreate
  `0.3.0a2`'s two-contracts defect **with the documents rather than the bytes**
  — the same failure arriving through a different door.
- **No `CandidateDisposition.v1`, and symmetry would be WRONG rather than
  merely unnecessary.** The log dispositions built artifacts, anchored by
  `receipt_path`, `receipt_digest` and an `artifact` block, hash-chained from
  the receipt's own digest. There is no a6 receipt to anchor to. The proof is
  mechanical: adding `"0.3.0a6"` to `SUPERSEDED` in
  `tests/architecture/test_version_binding_guard.py` FAILS
  `test_a_superseded_candidate_is_still_refused_for_a_second_build`, because
  the guard reads records, finds none for a version never built, and has
  nothing to refuse with. `EXPECTED_ENTRIES` stays 4; `SUPERSEDED` and
  `BUILT_CANDIDATES` are unchanged;
  `tests/architecture/candidate_source_binding_baseline.json` stays empty,
  which is still the healthy state.
- **The spent-identity oracle refuses `0.3.0a6`.** The guard reads four
  binding sources — tags, candidate receipts, dispositions and `SpentIdentity.v1`
  records — and this name is recorded in the fourth. Both candidate and release
  checks refuse it, while the inventory row preserves the historical reason
  without pretending that an artifact or disposition exists.

### `RecoveryExecutionPlanV1` — the distinct plan type, deliberately unreachable

A deployment-shaped plan is not a recovery plan. That sentence has been true in
this package's documentation for three releases and nothing expressed it as a
type; now something does.

It carries the three bindings a rehearsal does not take — `CapturedPrestateV1`
(what the source system was when the bundle was taken), `FailedSystemObservationV1`
(the failed system's own observed state at recovery start) and `DesiredPoststateV1`
(what the recovered system must present) — plus its own document schema and its
own digest name, `RecoveryExecutionPlanDigestV1`.

**Digests and NAMES, never parsed catalogue facts.** The poststate is a
descriptor digest, a bundle-manifest digest, and the verification names that must
report passed. It is not a catalogue assertion, for the reason that refused a
fourteenth `BundleComponent`: `recovery.py` runs with no database precisely
because the manifest carries digests and counts rather than facts. The names are
READ from `spec.BackupDataset.VERIFICATIONS` rather than respelled, so the
vocabulary widens on its own when `recovery.UNDECLARED_COMPARISONS` retires a
member into it, and a poststate demanding an undeclarable proof is refused —
unfalsifiable requirements get removed rather than met.

**No `operation` field.** The deployment plan needs one because a single
descriptor yields two otherwise-identical documents and the field is what tells
them apart. A recovery plan has no sibling, so the field would carry no
information — and a field carrying no information is one a later author finds
something to put in.

That drops a job the deployment plan's `operation` check was silently doing:
making the document self-identifying. The schema now owns it, at five acceptance
points, each with its own stable code, each proven by driving a REAL document or
object of the wrong kind through it in BOTH directions. One of the five was a
genuine hole: every plan kind has a `digest()`, so a recovery plan handed to
`require_execution_plan_digest` used to compute a good recovery digest, compare
it with a deploy authorization, and report *"something changed between
authorization and execution"* — a refusal that is actionable in the wrong
direction. `Executor` now refuses a non-deployment plan at CONSTRUCTION rather
than dying on `AttributeError` later.

**The ten canonicalization rules moved to `canonical_plan.py` and are owned
once.** A parallel copy for the second plan kind would be a second authority over
one question, and copies agree right up until they don't — the defect this
package has already paid for at `AuthorizationReceipt`, at `discover_bindings`,
and between Control's `plan_digest` and the Foundation's. The extraction is
byte-neutral, proved against an independently written encoder rather than against
the function itself.

The guard over it was NARROWED after CI showed the first version was wrong, and
the correction is worth reading. It asserted that no module outside the core
canonicalized with `json.dumps(sort_keys=...)` — and found sixteen sites, every
one of them correct. Canonical JSON is not a plan concept: `evidence.py`
canonicalizes a signed envelope, `lease.py` a host lease, `recovery.py` a bundle
manifest, `document.py` the descriptor. A detector whose extent is "anything that
looks like the thing I care about" reports every neighbour, and the honest repair
is to narrow the CLAIM rather than the scan. It is now a two-directional
population ratchet — the set of canonicalizing modules is known and cannot move
silently, in either direction — plus a direct assertion of the property that
actually matters: neither plan module canonicalizes for itself.

**A real import cycle was removed rather than routed around.** Adding the module
broke the package on import: `execution_plan` imported `engine.plan` at module
scope while `engine/__init__` imported `engine.run` which imported
`execution_plan` back, and that resolved only through the order `__init__`
happened to use. The import was for an annotation, and
`from __future__ import annotations` made it unnecessary at runtime — so the
cycle was load-bearing for nothing.

**Nothing constructs one of these.** `recover` is not in
`authorization.OPERATIONS`, there is no `recover` subcommand, and no grant covers
the act. The staging is the one `ApplicationFoundationProfile.v1` used — the type
refuses first, reachability comes later — because a grant, a replay coordinate
and a signed result wrapped around a plan nobody can execute is a chain whose
every link is correct and whose subject does not exist, and it would review as
finished. An AST test derives the unreachability from the package source, so the
change that wires it up is told to come and read the argument first.

### `DeploymentEvidence.v1` — the record is closed by structure

**This is a behaviour change to shipped deploy-path evidence**, authorized
deliberately. A reader comparing an old and a new record will find three fields
gone; this entry is where that is announced rather than inferred.

The previous record was a free-form mapping with three open text channels, and
raw exception text reached all three: `failure` (assigned from `str(exc)`),
`steps[].detail` (prose — twelve of the seventeen handlers built it with an
f-string over live values), and `notes` (including, literally,
`f"evidence could not be written: {exc}"`). A fourth channel left the host
entirely: `Executor` filled `Annotation.detail` with `outcome.failure` on the
failure path, sending exception text to the observability platform.

**A filter over a free-form dict is a convention; a closed type is a structure.**
The property is that there is no key the forbidden value could be written under
— not that a guard rejects it afterwards. `require_no_secrets` could never have
been the whole answer: it is a SHAPE detector, and stderr is not secret-shaped,
a DSN inside an exception message is not secret-shaped, and neither is a
fragment of SQL. It is retained as the belt, for a permitted field carrying an
impermissible value.

`failure` and `detail` become a CLOSED standing vocabulary; `notes` is gone from
the document. `installed` and `reconciled_after_commit` are separate members and
must stay so: same end state, different histories, and the crash path is exactly
when someone needs to tell them apart. `refused` and `failed` are likewise
separate, derived from the exception type, because "nothing was mutated, re-run
the identical command" and "state may have changed" decide different next
actions.

**Diagnostics did not disappear; they stopped being persisted.** `StepRecord`
still carries `detail`, the outcome still carries `failure` and `notes`, and the
CLI still prints all three. Evidence is a durable record that travels and is read
back; a diagnostic is ephemeral operator output. Putting the second inside the
first is how stderr comes to live in a signed record.

**`default=str` is removed** from the success-path read-back comparison. A
stringify-anything escape hatch defeats a closed type by turning an unexpected
object into text rather than refusing it — the precise mechanism by which an
exception instance becomes an exception message inside a record.

What is deliberately NOT narrowed: the four fields the publication gate reads
(`succeeded`, `execution_plan_digest`, `descriptor_digest`,
`control_plan_digest`) and Control's replay coordinate
(`execution_sequence`, `attempt_no`). Narrowing the document to a single step's
four fields would have broken the gate that publishes this facility and Control's
settlement at the same time.
### `FoundationExecutionPlanV2` — the plan that can express a principal bootstrap

**V1 is not touched.** Two other repositories compute or compare its digest, and
a version that grows a field is a version whose digest moves for documents nobody
edited. V2 is a new document; the two are told apart by `schema` at every
acceptance point.

**Not `Step.command`, and that is the load-bearing constraint.** The cheap way to
express "bootstrap this principal's credential" is a step whose command is an
`ALTER ROLE` string — which puts SQL inside a reviewed, signed plan, after which
`require_no_secrets` is the only thing between a plan and a credential, and it is
a shape detector that cannot tell an `ALTER ROLE ... PASSWORD` from any other
sentence. A typed member cannot carry a command by construction.

`PostgresPrincipalCredentialBootstrapV1` holds a service identity, a principal,
an OpenBao path and field, an expected version, and the declared transition.
There is no field for a password, a DSN, SQL or a command — not "those are
rejected", but *there is nowhere to put them*.

**`expected_version = 1` is what makes it a transition rather than a write.**
With `absent_to_present` it is a compare-and-set against "no record exists", so a
second run against a store that already holds the record refuses rather than
rotating a credential other systems now hold. `True` is refused explicitly,
because `bool` is an `int` in Python and would sail through as the version 1.

**The digest keeps the V1 NAME.** A V2 document produces an
`ExecutionPlanDigestV1`. The value schema and the document schema are separate
names on purpose: Control freezes the value and never parses the document, so a
second document version does not make a second value type and Control needs no
change. The reason is in the module, not only here, because the edit it guards
against looks like a tidy-up.

**The substitution matrix is now 3x3.** Nine ordered pairs across three plan
kinds; three admit, six refuse, each with the refusing side's own code. One
shared "wrong plan kind" code would let a direction be proven twice while another
was never proven at all — likelier the bigger the matrix gets.

**Half a change, deliberately.** There is no `StepKind` for the act and no
`Effects` method to invoke it. Widening that protocol makes
`_PROBE_BINDINGS_SOURCE` in `scripts/release_facility.py` — the probe wheel the
publication gate installs — non-conforming until updated, so it is held pending a
ruling. Same staging as `RecoveryExecutionPlanV1`: the type refuses first,
reachability later, so a half-built chain cannot read as done.

### The bootstrap invocation — `Effects` widened, every implementation updated

The half `FoundationExecutionPlanV2` was landed without. `Effects` gains
`bootstrap_principal_credential(bootstrap) -> StepStanding`, and the executor
performs each bootstrap the authorized plan carries.

**The seam is shaped so this facility cannot do the work.** It receives the TYPED
plan member — there is no parameter SQL, a DSN or a command could arrive through
— it resolves nothing, and the implementation reads the OpenBao reference on the
target. PostgreSQL mechanics stay in the product (ADR-0070).

**It returns a STANDING, not a boolean.** Any answer other than `installed` or
`reconciled_after_commit` is refused: "it is present now" is true of both an
install and a reconciliation after a crash, and a provider that will not say
which has not answered.

**The step is NOT emitted by `build_plan`, and that is a constraint rather than a
shortcut.** A step in the built plan lands in `FoundationExecutionPlanV1.steps`,
which is inside the V1 digest — so emitting one would move every existing V1
digest, including ones Control has already frozen, for deployments that
bootstrap nothing. The act is driven from `principal_bootstraps` on the
authorized V2 plan, which is itself inside the digest, and the ordering (before
the step loop, so a migration can rely on the role) is a constant of this
facility version. Asserted, not commented.

**Every implementation is updated in the same change** — the compose-host
provider, both test doubles, and `_PROBE_BINDINGS_SOURCE` in
`scripts/release_facility.py`, which is the probe wheel the publication gate
installs. A protocol widened without that last one makes the gate that publishes
this facility non-conforming. The test that proves it DERIVES the implementer
list rather than listing one, and names the probe separately because it is a
string of Python inside a script that every sweep over `.py` files misses.

The in-package provider conforms by REFUSING rather than by lacking the method:
a missing method fails as an `AttributeError` mid-deployment, a present one that
refuses fails as a `PreconditionFailed` before any effect, naming what to
install.

`Executor` now accepts V1 or V2 and still refuses a recovery plan, which
completes the 3x3 substitution matrix at its third acceptance point.

### The fifth signing identity becomes a TYPE

Five signing identities exist in this estate — authorization, dispatch,
observation, recovery and release evidence. Four were types that refuse a wrong
purpose at construction. The fifth was a dict literal and a JSON field, and
Platform's own source said so: *"`deployment_dispatch` and
`platform_release_evidence` do not exist as types yet, so they are named here as
literals until they do."*

The measured cost was **4 typed diagonals and 16 typed refusals** where five
identities' worth of enrolled material supports 5 and 20. The shortfall was never
a skipped test — **data does not refuse anything.**

This adds, beside `ReleaseEvidence.v1`'s verifier: the canonical
`RELEASE_EVIDENCE_PURPOSE`, a `ReleaseEvidenceVerificationIdentity` that refuses
any other purpose AT CONSTRUCTION, and a machine-readable `PURPOSE_MISMATCH`
code. A caller deciding what to do about a wrong-purpose key branches on the
code; a caller matching on a sentence is coupled to the wording, which is the
thing most likely to be improved.

It mirrors the shape Control's four identities use rather than importing one —
this facility declares zero runtime dependencies, the line
`provenance.AuthorizationReceipt` already draws. It validates the fingerprint's
SHAPE and never the key: no crypto library enters this package.

`from_document` is the one door from the installed
`PlatformCpPublicVerificationIdentity.v1` to the type, and an ABSENT purpose is
refused rather than defaulted — a document that says nothing must not be read as
saying the right thing. `require_release_evidence_key` binds the identity to the
key the envelope actually nominated, because a correct identity sitting beside a
signature made by some other trusted key proves nothing about that signature.

The suite carries the control that makes the four refusals mean something: **a
verifier broken shut produces four perfect refusals and reads as success**, so
the positive control asserts the identity accepts its OWN purpose. The five
enrolled fingerprints are asserted physically distinct rather than assumed.

NOT included, deliberately: wiring the identity into `accept_release_evidence`.
That is the composition step, and it needs Platform's typed
`ReleaseEvidenceSignerPointer` and its producer to exist first — a pointer that
cannot be constructed from what this publishes is two halves that do not meet.

### `IncumbentPrestateDigestV1` — the value with no producer

Control's `RecoveryGrantStatementV1` carries `incumbent_prestate_digest` as a
SIGNED term and its `RecoverySubject` requires a caller to state one. Measured at
the peeled `0.1.0a12` tag, **Control never computes it**: no canonicalizer, no
hash, only storage and comparison.

So the value existed in the contract with **no authority computing it on either
side** — the exact asymmetry `ExecutionPlanDigestV1` was created to fix. Two
sides computing it independently would diverge for the reason `plan_digest` did,
and the failure would be a `PRESTATE_MISMATCH` that told nobody anything.

Foundation now defines the canonical bytes and the typed digest function;
Platform's INSTALLED ADAPTER computes it, so the producer is the artifact rather
than a source tree; Control stores, signs and compares and implements no second
canonicalizer. `FailedSystemObservationV1` carries its own document schema so it
can be canonicalized alone — Control signs a digest of the observation, never of
the plan containing it, and a fragment has no kind for the shared guard to check.

**Foundation also publishes the DISCRIMINATOR Control stores beside the digest.**
A digest alone is 64 hex characters and cannot say which encoding produced it, so
`incumbent_prestate_digest NOT NULL` proves only that a string exists. The
discriminator names the observation schema AND the rules that turned it into
bytes; Control stores and REQUIRES it without owning it, and neither its
migration nor a `RecoveryGrantV1` version may redefine the encoding — that would
be the second canonicalizer this binding exists to prevent, arriving as a schema
change rather than as code.

**An undiscriminated row is HISTORICAL AND UNEXECUTABLE and is never backfilled
by assumption.** It predates the term, so nobody produced its digest under rules
anyone can name, and assuming the current one would manufacture provenance for a
value whose provenance is exactly what is missing. An unknown discriminator
refuses separately, because the repair is a version rather than a re-observation:
comparing under rules this facility does not have is not comparing.

The earlier "missing digest" refusal is WITHDRAWN. Control's column is NOT NULL,
so the case has no subject — and a refusal for a condition that cannot arise is
the false coverage this lane has removed twice already.

The tests do the two distinct jobs the ruling names. **Mutating every bound
field** proves each is genuinely inside the canonical bytes rather than merely
present in the document, with the field list asserted to be the whole document so
a new one cannot go unmutated. **Exchanging document and digest independently in
both directions** proves the comparison is not passing on identity — and a third
case moves both together and requires the pair to still refuse against the
ORIGINAL authorization, which is the half a same-direction test cannot reach.

### The release is PERSISTED, in the same store the lease already lives in

`HostLeaseRelease.v1` was a type nothing wrote down. It could describe a
terminal outcome perfectly and still leave the next run with exactly the evidence
it had before: no running process, and a timestamp going by. A record that
exists only in memory answers no question a later reader can ask.

`write_release`, `load_release`, `require_release_for_destruction` and
`require_release_for_reuse` close that, and the choice worth naming is WHERE they
write: **the same authoritative store `load_lease` already reads**,
`release_path()` beside the lease, not a second ledger. A separate release store
would create two places a host's standing could be answered from — and two
answers that can disagree is the failure this type exists to prevent, since a
host would then be destroyable according to one file and held according to
another.

**`require_release_for_destruction` is the whole call a destroyer makes.** It
loads the lease AND the release from one directory and then applies every
existing refusal. A caller assembling those pieces itself would be free to load
the lease from one place and the release from another; this function exists to
make that shape unavailable, not merely discouraged. A `HostLease.v1` refuses
here by refusing to LOAD at all — it names no workload principal, so nothing it
says can be bound to a releasing party.

**The refusal that matters most is `RELEASE_MISSING`.** Absence of a release is
not "released" — it is UNKNOWN, and a destruction gate reading it as clearance is
precisely the shape that lets a crashed run's silence authorise wiping a host
another lane is still using. `RELEASE_DUPLICATE` refuses a second write, because
a terminal record that can be overwritten is not terminal.

**The release is published ATOMICALLY, and the difference is not academic.**
`write_store_record_once` uses an `O_EXCL` temp plus `os.link`, so creating the
name and failing on a taken name are ONE syscall. The first draft refused with a
`path.exists()` check before writing, which reads correctly and protects nothing
under the only conditions that matter: the store is a shared host whose premise
is that agents contend for the target, and the driving workflow does not cancel a
run in progress, so two dispatches overlap by design. Under an interleaving, both
runs see no file, both write, and the second silently overwrites the record of
how the first ended.

Measured rather than argued — the same harness, twenty races each: `os.link`
gives one publish and one refusal every time; stat-then-write gives two publishes
and no refusal every time. The rejected implementation is KEPT in the test file
as a negative control, because sequentially the two are indistinguishable, which
is exactly how a stat-then-write survives a suite full of create-only tests.

**Two writers, one bytes mechanism.** A lease may be rewritten — it is renewed,
and the current row is the answer. A release may not. `_store_bytes` is the
single answer to "how does a record in this store become bytes";
`write_store_record` overwrites and `write_store_record_once` does not. The
semantics differ for a real reason, so they are separate functions rather than a
convenient merge.

**`write_release` raises `PreconditionFailed`, deliberately, and takes no path
override.** Not `OSError`: the meaning of a duplicate release belongs to this
module, so a caller must catch it by name. And a workspace copy for artifact
upload is a copy taken AFTER a successful store write — never a second write
path, which would be the second-ledger defect wearing an evidence costume.

**Reuse and destruction are separate gates over the same record.** "May this host
be destroyed?" and "may a next lease take it as it stands?" have different
answers, and a host may legitimately answer yes to one and no to the other.
`require_release_for_reuse` refuses any closure that is not `REUSABLE` with
`RELEASE_NOT_DESTROYABLE` — which is also the member that keeps "the lease timed
out" from reading as "the host may be wiped".

### `HostLeaseRelease.v1` — the other end of the lease contract

`load_lease` refuses to BEGIN without a lease record. Nothing recorded the END,
so the only evidence a shared host was finished with was the absence of a running
process and a timestamp going by. Both are inferences.

**Expiry and release are separate members, not two readings of one field.** An
expired lease means *this run may not continue*; only a release means *the host
may be destroyed*. Collapsing them is what lets a crashed run's timeout authorise
a wipe: a run that dies at 03:00 leaves no release, its lease expires at 06:00,
and a destroyer reading "is the lease live?" finds "no" and takes it as
permission. `HostStanding.EXPIRED_HELD` is that third case, and the destroy gate
refuses on it by name. **A crash before release leaves the VM held** — the repair
is a human releasing deliberately, which leaves a record.

**A refused run is terminal and may release.** A schema accepting only receipts
would hold a host forever after any legitimate refusal, and somebody would then
release it by hand — the mechanism this record exists to remove.

**The refusal vocabulary is closed and owned here**, DERIVED from all THIRTEEN
terminal refusals rather than invented: a schema validating a code against a set
the writer invents is not a validation.

Thirteen, and the count is the lesson. The first derivation found eight by
scanning one file for `raise DeploymentFoundationError` — a grep's answer. Three
more raise `ProvocationError`, which SUBCLASSES it, and two live in a file
neither side had scanned. The writing lane's independent count was ten and was
wrong the same way, in its own words: *"my own count was made by the shape of a
grep rather than by the shape of the class hierarchy."* The final scan is by AST
over every raise of a `DeploymentFoundationError` subclass across three files,
and the site-to-member table is in the enum's docstring, because a vocabulary
whose derivation is not written down is one the next person re-derives
differently.

SIX members, not seven. `descriptor_unfit` and `provocation_unestablished` are
genuine additions with opposite operator actions — the first means *do not touch
the machine, fix the input*; the second is the only refusal where the host was
MUTATED and the mutation FAILED, so it means *inspect the machine before
re-running*. And `vantage_unavailable` is gone: it was derived from one site that
was then correctly remapped, leaving a member nobody raises — a code for
something that cannot happen and a test that can never fail. It is not retained
against a refusal that does not exist.

Every terminal refusal maps to exactly one member, and an unmapped one is an
amendment rather than a free-text escape.

**VM identity is the SLOT, not the address.** The addresses are exactly what a
destroy-and-restore can change, so an address would bind by coincidence and could
name a different machine afterwards. `vm_slot` is `node/vmid`;
`vm_installation_id` is the machine-id and may be `""` as a STATED value — the
same rule `application_profile_digest` follows — because a field only some paths
can produce pushes a writer toward the broad handler that produces it. When
present it catches the one case the slot alone cannot: a slot re-provisioned
between release and destroy.

**No change to `load_lease` was needed.** The digest is a pure function of the
PARSED lease through the shared ten-rule core, so the runner digests the lease it
already loaded and there is no second opinion about where a lease lives.

### The stage-two effects caller — Foundation owns the transition

`build_platform_cp_effects` could not be reached through the published binding
contract at all. Foundation's contract is `build_effects(spec, deploy_dir)` — two
positionals — and the factory required `target` and `incumbent_roles` as
keyword-only, so every real invocation raised `TypeError` before any deployment
logic ran. There was **no production caller anywhere**: only tests, each calling
the factory the way the factory wanted to be called, never the way this facility
calls it.

The circularity is genuine. Effects are built from `(spec, deploy_dir)`; the plan
is rendered by reading `observe_roles()` on those effects; the plan carries the
target and frozen prestate the provider needs. Neither can be known at
construction, so the seam is two stages and Foundation owns the transition —
`bind_authorized_effects(effects, plan)`, called after `render_execution_plan`
and before `Executor`.

**The three prohibitions are structural rather than remembered.** There is no
`observe_roles()` call in the function, derived from the AST rather than trusted
— a prestate read there would be a second authority over a fact the plan already
fixed. There is no `attempt_no` parameter, so nothing can assert what the
envelope should carry. And the plan is type-checked before anything is read off
it, so a mapping with the right keys cannot stand in for the frozen document.

**The projection is the identity.** `HostPrestateV1.roles` is already sorted
`(role, digest)` pairs and the provider applies the same rules, refusing an
unsorted sequence rather than repairing it — so the frozen tuple passes through
unchanged. A sort or a rebuild here would be a second opinion about a fact the
plan froze. An empty prestate stays the positive "first deployment" claim, and
`host_prestate` is required with no default, so `None` has no path.

### `IntegrationSurfaceAbsenceProofV1` — a proven absence SATISFIES a concern

Michael's decision, and the reason it is forced rather than preferred. A
candidate build requires all thirteen concerns bound. If a proven absence could
NOT satisfy a concern, then a product with genuinely no integration surface
could never reach 13/13 — and a gate nobody can meet is a gate that gets waived,
not a gate that gets met. The bar that stays load-bearing is a different one:

**It satisfies only when ESTABLISHED, never when merely well-formed.**

That is stated in the type rather than in this note. `__post_init__` answers
"is this well-formed"; `satisfies(concern, *, image_digest, inventory_digest)`
answers "did this establish anything about THIS artifact", and it answers by
COMPARING the proof's recorded inventory digest against one the caller computed
independently. A caller can write any string into `observed_inventory_digest`;
it cannot make that string equal a digest another party derived from the image
without having examined the image. Constructing the type grants nothing, which
is the whole difference between a proof and a placeholder wearing a type.

**Four states stay distinct**, and none of them is the absence of the others:
`bound` (a provider answers), not-yet-implemented (owed and missing),
`inapplicable` (refused by ruling, the existing `InapplicableConcern`), and
`absent_proven` (this type). The document NAMES its state, so a reader never
infers "proven absent" from a missing binding — that inference is exactly how
not-yet-implemented gets laundered into satisfied.

**The inventory is closed and enumerated FIRST.** Five families written
longhand — `outbound_connector`, `inbound_webhook`, `scheduled_sync`,
`message_consumer`, `external_api_client` — enumerated before any proof runs and
never derived from a proof's own findings. Three refusals follow from that:
a family never looked at refuses (`ABSENCE_INVENTORY_INCOMPLETE`) rather than
reporting a subset as "none"; a surface outside the inventory refuses
(`ABSENCE_UNREGISTERED_SURFACE`) rather than silently not counting, which is the
failure absence proofs actually have; and one surface FOUND refuses
(`ABSENCE_NOT_ABSENT`) because a live connector makes the concern UNBOUND — a
state that needs a provider, not a proof.

ADR-0033 § 3 is carried whole: no positive control, no proof
(`ABSENCE_UNESTABLISHED`), because a prover that never finds anything and an
artifact that has nothing are otherwise the same colour. Provenance —
`source_revision`, `method`, `established_at`, `established_by` — is required by
the same code, and the concern must be a `FoundationConcern` rather than a
string (`ABSENCE_WRONG_CONCERN`), so one proof can never certify thirteen.

**The scope is exactly `integration`.** It is not widened to
`request_evidence_context` or `data_governance`; those are owed, and a type
built to prove emptiness must not become the way an owed concern is closed.

**No release/pin sequencing applies here, and that is worth stating.** Platform's
`profile_readback.py` imports no Foundation type — it is stdlib-only and reads
the profile as a DOCUMENT, already refusing a proof whose `source_revision` does
not match the artifact under readback. So this type does not have to be
released, pinned and then consumed before Platform can verify it; the seam
between the two sides is the emitted document, and `as_document()` carries the
two fields Platform's existing check reads.

### Also in this release

**The facility's own maturity claim about the thirteen concerns is withdrawn.**
`application_profile.py` and `cli.py` asserted that four of the thirteen
concerns have mature fleet owners and nine do not. The CODE never depended on
it — bindability comes entirely from an assembly's own declaration, and the
absence of a hardcoded list of "the bindable ones" is a deliberate design
recorded in that module. But the prose stated a fleet-wide maturity
determination this facility does not own and cannot check, in a package whose
whole discipline is that a claim names its oracle. It is replaced by what is
true here: the verification is report-only because ADR 0039 stages it that way,
and which concerns any assembly can bind is that assembly's declaration to
make.

A wheel for `0.4.0a1` was built exactly once by `foundation-candidate.yml` in
run `33920058598`, but its receipt was not committed and the importable source
later drifted. It is therefore not the candidate the later Lane 3 exposure
rehearsal may use and must never be rebuilt or published. A successor, if
authorized after the composition changes, must be built once from its own exact
protected-main SHA; Lane 3 must fetch, digest-verify, install and execute those
recorded bytes rather than importing Foundation from checkout or accepting an
operator-supplied artifact digest. Publication must parse the rehearsal receipt
with that same installed candidate wheel.

## 0.3.0a6 — unreleased, NEVER BUILT, RETIRED UNBUILT 2026-09-04

Allocated 2026-09-03, the third application of *a tree that diverges from a
built artifact allocates a new version* — and the first one caught LATE.
`0.3.0a5` was built once (artifact `9903418260`, run `33780438726`, from
`27bee8fc`); PR #600 then added 405 lines and removed 9 across
`authorization.py`, `provenance.py` and `recovery_execution.py` while
`version.py` and `pyproject.toml` still declared `0.3.0a5`. The facility
`src/` tree moved from `ff508afd` to `44f3c4d6`, so one version name covered
two contracts — and the second contradicted the first in writing, because the
a5 receipt's `item_scope` records `items_absent: [10]` and argues in a
committed field that `("deploy", "rollback")` is the correct vocabulary.

**Nothing mechanical caught it, and that is the durable part.**
`version_binding_guard.py` runs only when a build is requested;
`test_declared_version_matches_published_tree.py` compares against a git tag
an untagged candidate does not have. Two real guards, one blind spot between
them. `scripts/candidate_source_binding.py` now closes it and fails CI on
every merge, so a fourth application of this rule is a red build rather than
an audit finding.

This release also withdraws `recover` from `authorization.OPERATIONS` and
makes the restore executor reachable under the act it actually performs. See
the entry for that change below when it lands.

No wheel for `0.3.0a6` exists. It must be built exactly once, by
`foundation-candidate.yml`, after these changes merge.

> **Amended 2026-09-04.** The paragraph above was written at allocation and its
> second sentence is now false, which is why it is amended rather than edited:
> `0.3.0a6` was NEVER BUILT and must never be. It is superseded by `0.4.0a1`
> without an artifact — no wheel, no `CandidateArtifact.v1` receipt, and
> therefore no `CandidateDisposition.v1`, which is a first for this ledger and
> is reasoned through in the `0.4.0a1` entry above. Nothing else below is
> withdrawn: the divergence reasoning is still correct and
> `scripts/candidate_source_binding.py` is still the guard it motivated. The
> work the paragraph beginning "This release also withdraws" promised did land,
> in #603 through #606 — `recover` is out of `authorization.OPERATIONS` and the
> restore executor is reachable as `restore-rehearsal --execute` — and those
> bytes are now `0.4.0a1`'s, because a version that was never built carries
> nothing away with it. Read the `0.4.0a1` entry for why an unbuilt name is
> nonetheless SPENT, and for the machine-oracle gap that retirement leaves.

> **Amended 2026-09-07.** The paragraph above was written at allocation and
> its machine-oracle gap was accurate at that time. The later `SpentIdentity.v1`
> source now closes that gap for offline candidate and release checks: the
> guard reads the recorded spent identity for `0.3.0a6` and refuses both
> purposes. This amendment records the later control without rewriting the
> historical account as though it had always existed.

## 0.3.0a5 — built once, SUPERSEDED and unpublishable (2026-09-03); heading below written at allocation

Allocated 2026-09-03, when Michael's audit ruled `0.3.0a4` not
cutover-admissible and its candidate (artifact `9880868637`, built once from
`14f7d9fe`) was recorded superseded and unpublishable in
`docs/inventories/foundation-candidate-dispositions.json`. Two defects, both in
the a4 bytes and both structural:

- **The installed CLI could not load an assembly's effects or verifiers.**
  `authorization_verifier` was an argparse-namespace attribute nothing ever
  set, and `_build_effects` a closed switch over the one in-package provider —
  so the installed `dotmac-deploy` could refuse honestly but never ADMIT.
- **The release-evidence reader corrupted signed envelopes.** The
  `Effects.release_evidence` seam was typed `Mapping[str, str]`, so every
  conforming provider had to stringify the envelope's nested `document` — the
  very thing the signature covers — and the verifier judged a Python repr.

This release types the seam (`SignedEvidenceEnvelope`, refusing a stringified
document at construction, passed through parsed and never restated) and will
add provider-neutral execution-bindings discovery, injection for effects and
all verifiers, replay coordinates, observed prestate, candidate-image
injection, real readiness, immutable evidence read-back, executable authorized
recovery, and an installed end-to-end ADMIT proof.

No wheel for `0.3.0a5` exists. It must be built exactly once, by
`foundation-candidate.yml`, after these changes merge.

> **Amended 2026-09-03.** The paragraph above was written at allocation and
> is now false in its first sentence, which is why it is amended rather than
> edited: `0.3.0a5` WAS built, exactly once, as candidate artifact
> `9903418260` (run `33780438726`) from `27bee8fc`. Those bytes are preserved,
> are never rebuilt and are never relabelled. They are recorded **superseded**
> and `publishable: false` at `CandidateDisposition.v1` sequence 4 — superseded
> is not invalidated, and this candidate was never wrong: it is a coherent
> contract carrying nine of the eleven a5-audit items plus item 4 from #597,
> with item 10 absent by decision and its own receipt saying so. The successor
> is `0.3.0a6`. The list of what this release "will add" above also stands as
> written at allocation: executable authorized recovery is NOT in these bytes.

## 0.3.0a4 — built once, SUPERSEDED and unpublishable (2026-09-03); heading below written at allocation

The successor identity, allocated 2026-09-02 because this release adds
`observability_promotion.py` to `src/` and `0.3.0a3` had already been built
once (`docs/inventories/foundation-candidate-0.3.0a3.json`, artifact
`9830633429`, from `005490b2`, with the package tree byte-identical to it).
A tree that diverges from a built artifact allocates a new version — the rule
that came out of the `0.3.0a2` incident, applied here BEFORE the divergence
shipped rather than after somebody found it.

No wheel for `0.3.0a4` exists. It is not tagged, it is on no index, and it is
recorded as unpublished in `docs/inventories/declared-publication-baseline.json`.
The next authorized step is ONE candidate build.

**`0.3.0a3` is not superseded as an artifact and must not be rebuilt.** Its
wheel remains the Platform CP cutover's bootstrap input, and nothing about this
bump reaches it: a consumer resolves those bytes by RUN AND ARTIFACT ID out of
the committed `CandidateArtifact.v1`, never by the version this tree declares.
The version-binding guard still admits `0.3.0a3` for `--purpose release` while
refusing it for a second build, and
`tests/architecture/test_version_binding_guard.py` asserts both.

`VERSION` sits inside the canonical descriptor, so this bump moved
`io.dotmac.deployment.configuration.digest`
(`sha256:eff30b30…` → `sha256:d1d736c0…`) and `deploy/rendered/docker-compose.yml`
with it, re-rendered in this same change. That digest is re-derived from the
tree; the one recorded in a candidate receipt is a historical fact about that
build and is not touched.

### `observability_promotion` — the host half of an Observability promotion

Observability ADR-0010 owns the promotion DECISION and no host effect: every
host effect is a method on `promote.PromotionFacility`, a Protocol it declares
and does not implement. `dotmac_deployment_foundation.observability_promotion`
is that implementation.

None of it existed. The shipped executor's "switch" is `docker compose up -d
--force-recreate` against a re-rendered Compose file
(`providers/compose_host.py`); nothing staged a directory, nothing swapped a
pointer, `previous_image` was supplied by the caller rather than read off the
host, there was no transport of any kind, the only reload primitive was
`nginx -s reload` and nothing anywhere queried Prometheus or Alertmanager.

What is here, and the failure each part prevents:

- **Immutable release-directory staging.** The whole tree is written to a new
  release directory, made unwritable, and refused outright if that directory
  already exists. Never file by file: a single-file bind mount is bound to an
  inode, which is how the Observer host became append-only by hand (ADR-0002).
- **A previous-pointer READER, and preservation.** `read_previous_pointer`
  reads the symlink off the host before anything changes, and the value it read
  is carried into every later read-back on that facility. Reading it is only
  half the capability: the control plane's `ObservationRequest` has no field
  for it, and a null `release.previous` on a promotion that is not the first is
  `RECEIPT-NO-ROLLBACK-TARGET` — the receipt is refused. Letting the caller
  re-supply it would reintroduce `previous_image`'s defect one layer up. Three broken shapes that used to be
  indistinguishable from a fresh host are now refusals: a regular file where
  the pointer belongs (activation here was never atomic), a symlink into
  nothing (the rollback target is already gone), and an unreadable link. `None`
  means one thing — no pointer at all.
- **Exact-byte transport.** Files go out over an injectable `HostTransport`
  (`LocalTransport`, and `SshTransport`, which quotes with `shlex.join` because
  ssh's far end is a shell). Every staged file is then read BACK and compared,
  byte for byte, against what was sent, and the path set is compared in both
  directions. A mismatch refuses with the staging directory removed and the
  pointer untouched — a corrupt release can never be activated. The comparison
  is over bytes fetched from the host and hashed here, never over a digest the
  host computed: the host cannot be the authority on whether the host received
  the right file.
- **Atomic activation.** `ln -s` into a temporary name then `mv -T` over the
  pointer — a `rename(2)`. `ln -sfn` is an unlink followed by a symlink and has
  a window with no pointer at all. The pointer is then RE-READ, and a swap that
  does not read back is `ActivationNotObserved`.
- **Prometheus and Alertmanager reloads, each checked.** Each is reloaded over
  its lifecycle endpoint rather than by recreating the container, which would
  discard the scrape window the verification is about to read. A `200` from
  `/-/reload` is the request being accepted; the evaluator's own
  `*_config_last_reload_successful` and
  `*_config_last_reload_success_timestamp_seconds`, read straight after, are
  the process saying it adopted a configuration — and only a success timestamp
  later than the moment we posted says it adopted THIS one. Otherwise
  `ReloadNotObserved`, which fails the promotion at `RELOADED` and rolls back.
  An evaluator that does not export the metric at all is also a refusal: an
  unexported metric is not a successful reload.
- **A complete read-back**, as an `observability-live-observation.v1` document:
  the whole active tree by path and sha256, targets, rules, resolved routes,
  the named ingestion counter and `process_start_time_seconds` in ONE read,
  the canary, and one probe per surface per address family with its positive
  control nested inside it.
- **Exact rollback, and a read-back of the restored host.** `rollback` restores
  the pointer and returns the observation, carrying a `rollback` block whose
  `restored_release` is RE-READ from the pointer rather than echoed from the
  argument, and whose `restored_digest` is computed from bytes fetched back off
  the host. A rollback whose evaluators never took the restored configuration
  reports `succeeded: false` rather than raising, because the read-back is the
  most useful thing an operator can be handed at that point.

Everything it cannot obtain itself arrives through a seam and defaults to an
honest absence. No `ReceiverWitness` means `delivered: false` with no evidence
reference, which the verifier refuses — rather than reporting Alertmanager's
outbound `200` as a human having been reached. No `SurfaceProber` means
`inconclusive`, not `refused`, because an unplugged cable and a shut port look
identical from here. A required contract block the facility was given nothing
for — an unnamed ingestion counter, an unplanned canary, a probe slot with no
declared expectation — is a refusal, never a fabricated one.

Nothing here judges whether a promotion succeeded. Health thresholds, target
expectations, the verdict and the six conditions stay in the control plane.

### Five places ADR-0010 cannot be implemented exactly as written

1. **`observe`/`rollback` cannot return `LiveState`.** That is a dataclass in
   `dotmac_observability`, and this facility must not import the product it
   serves (ADR-0070; the zero-runtime-dependency and forbidden-import gates
   both bite). They return the `observability-live-observation.v1` DOCUMENT —
   the actual contract — and the control plane's own `live_verify.live_state`
   types it. One call, on the side that owns the type.
2. **`restored_digest` is order-dependent and a read-back has no order.**
   `render.tree_digest` hashes `path\0contents\0` in the RENDERER'S order,
   which is not alphabetical, and condition 6 compares `restored_digest`
   against `previous_digest` with `!=`. A directory walk cannot recover that
   order. `stage` therefore writes a `ReleaseTreeManifest.v1` recording it,
   stored OUTSIDE the release directory because a file inside would read back
   as a path the renderer does not produce. The manifest supplies ORDER only:
   every path and byte is still read off the host, the manifest's path list is
   compared with the walk in both directions, and a missing manifest yields a
   `None` digest rather than a guessed one.
3. **`ObservationRequest` does not carry what the schema requires.** It has
   `release`, `paths`, `integrity_counters` and `probe_slots` — and the schema
   needs a per-probe `expectation` "derived from the desired state", a route
   list by declared id, a canary plan with its receiver, an `environment` and a
   `host_target_id`. None of those are things the facility holds. They arrive
   here on a `PromotionContext` supplied at construction; the alternative is
   the facility inventing them, and a guessed expectation manufactures a pass.
4. **`rollback(target, release)` is handed no observation request.** The
   facility therefore keeps the standing `PromotionContext` and substitutes the
   restored release, which is why that context is a constructor argument rather
   than a per-call one.
5. **`integrity_counters` is a LIST and the `integrity` block holds ONE.**
   `live_verify.integrity_counters` returns every `*_total` token found across
   every declared gate's integrity predicate, in declaration order, so a control
   plane with two gates naming different counters legitimately produces two.
   `observability-live-observation.v1`'s `integrity` block has a single
   `counter`/`value`/`process_start_time`. Reading the first and filing the
   document would verify one counter while the read-back reported as complete —
   a subset presented as the whole. The facility therefore REFUSES a request
   naming more than one, and the repair is a contract carrying a list, which is
   not this facility's to make.

## 0.3.0a3 — unreleased, BUILT ONCE (artifact 9830633429), never to be rebuilt

The successor identity, allocated 2026-09-01 because `0.3.0a2` had come to name
two different contracts and one of them was an artifact nobody could change.

The wheel exists and must never be rebuilt. Corrected 2026-09-02: this
paragraph previously read "No wheel for `0.3.0a3` exists", which was true when
written and stopped being true on the day of the build. It was built exactly
once as candidate artifact `9830633429` (run `33587629491`) from merged
protected main at `005490b278be73112fa9600bffb6e00a37c77a59`, wheel sha256
`11978d919f1e910ae16d9b8262ffd3c473b074b4815067ab210fbe88e009d990`, expiring
2026-12-01. It is not tagged and is on no index, and it is the Platform CP
cutover's bootstrap input — resolved by run and artifact id out of
`docs/inventories/foundation-candidate-0.3.0a3.json`, never by the version this
tree declares, which is why the later move to `0.3.0a4` does not reach it. A
second build under this name would produce different bytes with the same
identity; publishing these exact bytes is the only remaining step.

The previous section here declined to allocate a successor, on the reasoning
that the tree could keep declaring `0.3.0a2` while diverging from the frozen
bytes. That reasoning is withdrawn. It is the exact mechanism by which one
version name covers two contracts (`AGENTS.md` rule 34), and no equivalent
permission replaces it: a tree that diverges from a built artifact allocates a
new version. Everything below this heading that was previously filed as
"unreleased, version unallocated" is `0.3.0a3` work.

### `FoundationExecutionPlanV1` — the middle term of the receipt binding

Control's `plan_digest` hashed the spec **wrapped in six sibling keys**; the
Foundation hashed the **descriptor alone**. Same serialization rules, different
payload — so the two values could never be equal, for any input, and nothing
said so. Both sides were internally consistent, both computed "the plan digest",
and the comparison was dead on arrival while reading as correct.

Patching either end would leave the shape intact: whoever normalizes decides
what was authorized and the other party trusts a reconstruction. So the middle
term is now a document the **Foundation renders** and Control merely **freezes**.

`ExecutionPlanDigestV1 = sha256(canonical FoundationExecutionPlanV1 bytes)`. It
is **not** the descriptor digest, the authorization-envelope digest, or Control's
internal snapshot digest — each is a real value a reader could reach for, and
reaching for the third is how the divergence happened.

The flow: Foundation renders the target-bound plan from the immutable artifact
and the authorized environment inventory and computes the digest
(`dotmac-deploy execution-plan --target ... --operation ...`); Platform CP
submits that exact digest and an explicit operation to Control; Control freezes
and signs and **never reconstructs or normalizes** the document; Foundation
**recomputes the digest before execution** (`require_execution_plan_digest`);
and the execution report carries the same digest and operation.

Canonicalization is stated byte level, because two repositories bind to it:
UTF-8 of `json.dumps(sort_keys=True, separators=(",", ":"), ensure_ascii=True)`;
ASCII-only and refused otherwise, so NFC/NFD never arises; keys sorted at every
depth; every declared key always present and `null` never appearing; integers
only; `steps` in plan order and every other array sorted and deduplicated; **no
prose**, so an edit to a step's description cannot change a signed digest; the
digest covering the document ALONE with no wrapper; and `foundation_version`
inside the document.

The environment inventory carries material NAMES only, never a resolved value
(ADR-0009), and the finished document is run through `require_no_secrets`.

### External recovery: a proof from another party, bound so it cannot be claimed

A read-only measurement of the frozen `0.3.0a2` wheel found it could not bind an
externally executed recovery contract. Two independent gaps, and neither fixes
the other:

* `BackupDataset.VERIFICATIONS` was byte-identical to the published 0.2 line, so
  a descriptor naming `roles`, `ownership`, `memberships` or
  `effective_privileges` was refused AT PARSE — while `recovery.py` had modelled
  every one of them since the bundle contract landed. Plumbing, not design.
* `backup.assess()` computed the `restore_proof_max_age_days` window correctly
  and had **zero callers**, and `BackupRecord.restore_proved_at_epoch` was
  written by nothing in the package. The window was inert because nothing
  supplied the records.

`recovery_identity.ExternalExecutorV1` types WHO executed the recovery — closed
kind, machine-shaped identifier, a required version and the signing key its
receipts must carry. Never a free-text owner: `owner = "the DBA team"` cannot be
compared with anything, so a receipt from the wrong party reads identically to
one from the right party.

`recovery_identity.DatasetIdentityV1` names WHICH data, independently of host
and executor — the two things that change while the data does not. A host-shaped
lineage and one containing the executor's identifier are both refused, because a
failover or a change of supplier is exactly when the old proofs matter most.

`external_recovery.accept_external_recovery_receipt` accepts a signed
`RecoveryReceipt.v1` bound to the dataset identity, the descriptor digest, the
snapshot checksum, the executor identity AND version, and the exact verification
set. The signature is checked BEFORE any content check, so an attacker cannot
probe accepted values with documents they never had to sign. **No verifier means
refuse**, never "skip signature checking".

`backup_record_from_receipt` is the writer `restore_proved_at_epoch` never had,
and `require_restore_proof` is the caller `assess()` never had. Together they
close receipt → record → assessment → refusal, and it is a REFUSAL: a window
producing a warning nobody blocks on is the same artefact as no window.

`StepKind.VERIFY_EXTERNAL_RECOVERY_RECEIPT` is a **GATE**, before any DDL. When
a dataset declares an external executor the plan emits it and emits NO `backup`
or `verify_backup` step for that dataset — a backup step there would attribute
to the consuming product an act it does not perform, which is the artefact that
read as green while nothing in the fleet had ever been restored.

Receipts are **passed in, never discovered**: `Executor(recovery_receipts=...)`
and `dotmac-deploy deploy --recovery-receipt DATASET=PATH`, following
`--authorization`. There is no directory scan, because a search cannot tell "no
proof exists" from "no proof was offered" and will happily find last quarter's.

`expected_backup_interval_seconds` is now a descriptor field and the name
`assess()` uses (it was `expected_interval_seconds`, a second name for a control
the descriptor could not state at all). It stays SEPARATE from
`restore_proof_max_age_days`: cadence decides staleness, the window decides
whether recovery has ever been demonstrated, and a product taking hourly backups
nobody has restored passes the first and fails the second.

`DatabaseDescriptorTransition.v1` pre-authorizes the descriptor state a
database operation produces, binds the result to its plan and target, and
requires the live starting descriptor as a compare-and-swap precondition. An
operation either commits in one transaction or declares every ordered durable
checkpoint; a lone final candidate cannot describe partial progress.

`DatabaseDescriptorPromotionPending.v1` names the honest gap between the
database commit and descriptor promotion. Recovery re-drives one idempotent
compare-and-swap keyed by transition id, and the terminal
`DatabaseDescriptorTransitionReceipt.v1` binds both descriptors, the observed
database postcondition and the durable promotion event.

`compare_database_contract()` adds a descriptor-digest-bound, read-only,
two-way catalogue comparison with phase-specific refusal classifications,
exact schema/head/role/isolation comparisons, an independently derived
effective-privilege audit-universe requirement and typed exclusions. The
independent sidecar can bind canonical database catalogues by schema, contained
path, digest and explicit MODULE or PRODUCT scope to a v1 descriptor digest.
It deliberately cannot make those coordinates v1 descriptor facts.
`ProductDeploymentSpec.v2` is the explicit successor: its `[database]` requires
and digest-covers the coordinates while the v1 reader keeps refusing the key.
Foundation does not copy their grammar. A separate
typed comparator result becomes a witness only after an integrated verifier
runs over held catalogue and observation bytes with complete
schema/table/column observation. Contract identifiers alone are not provenance:
Foundation invokes the injected verifier over both held payloads and rechecks
the returned comparator id, scope, digests and PostgreSQL major. Coordinates
are then checked against the verified declaration schema, MODULE/PRODUCT scope,
complete schemas and product code/version; product coordinates
also bind catalogue product code/version through an explicit descriptor-product
mapping. Changed structural attributes remain reportable in both set-difference
directions, while partial scope and the v1 sidecar both withhold a
whole-descriptor match.

## 0.3.0a2 — INVALIDATED. Never published, never to be rebuilt

Built ONCE as candidate artifact 9740182233 from
`e930f878ce400b766b4a50feb0369021a28ab2fa`, never tagged and never uploaded.
Commit `0f390a9aa93b0bb1cb78621ab1e9febc90bc48d2` (#551) then changed the
facility source under this same declared version, so a consumer resolving
`0.3.0a2` from the repository and a consumer holding the frozen bytes hold
different code.

The bytes remain historically real and re-fetchable by the coordinates in
`docs/inventories/foundation-candidate-0.3.0a2.json`, which is preserved
byte-for-byte as `CandidateArtifact.v1`. The judgement about them is a separate,
appended `CandidateDisposition.v1` record in
`docs/inventories/foundation-candidate-dispositions.json`: **invalidated**,
`publishable: false`, with the invalidating commit and the reason. This version
must never be rebuilt, republished, tagged or re-declared.

The section below is what that candidate contained, kept as the historical
record of what those bytes are.

The eight property clusters an audit of the closed PR #507 found missing, each
restored fresh against current main rather than revived from that branch.

**a1 must never be published or adopted.** It was built once, before any of
this landed, as a bootstrap input only, and is authorized for exactly two
supervised uses: an isolated recovery proof and the Platform CP bootstrap. It
cannot close Lane 3, because it predates the execution seam it would be
certifying.

`authorization.py` — Platform CP authorization at the execution seam.
`Executor` cannot be CONSTRUCTED without an `ExecutionGrant`, and a grant
cannot be built outside `authorize()`. `--execute` alone refuses; a caller who
skips authorization has nothing to pass. Deploy and rollback are separately
authorized, so one approval can no longer both make a change and erase it.

`launcher.py` — refuses a controller loaded from inside the tree it is
deploying, and a staged directory on `sys.path`. That directory is the INPUT,
and an input that supplies its own validator is not an input that was
validated. It does not claim to verify a compromised interpreter; the strong
form is the launcher digest compared from outside the process.

`evidence.py` — release evidence must be signed, and must be OURS. The previous
gate accepted any non-empty file. `repository_id != head_repository_id` refuses
a fork run, which `all_external_contributors` does not cover: that stops fork
code EXECUTING, not fork evidence being ADMITTED. No verifier, no policy or an
empty signer set each refuse rather than degrade.

`toolchain.py` — host binaries are named, not searched for. `docker` and `git`
are absolute and integrity-checked, including the parent directory, because
`rename(2)` needs write permission on the directory rather than the file.
`pg_dump` is deliberately excluded: it runs inside the db container, where the
host's PATH has no say and the image digest owns its identity.

`ancestry.py` — a deploy that is not provably forward refuses. UNKNOWN and
UNRELATED refuse alongside ANCESTOR, because an unmeasured ancestry is not a
forward deploy. `DowngradeOverride` is typed, single-use and names the exact
revision pair, a reason and a decision; it cannot excuse an UNKNOWN ordering.

`render/compose.py` — `DeploymentIdentity.v1` on every rendered service. A
controller reads a release's identity off the running object instead of
inferring it from a mutable tag or project name. The configuration digest is
the same value deployment control binds an approval to, so the comparison is
`==` rather than a translation.

`release-facility.yml` — publication is create-only and cannot race itself.
Keyed on facility AND version, never cancelled in flight, and `--skip-existing`
is absent and asserted absent: it turns a duplicate into a green no-op.

**The version bump itself changes rendered bytes.** `VERSION` is inside the
canonical descriptor document, so the configuration digest moves and every
`DeploymentIdentity.v1` label with it. The rendered assets are re-rendered in
this change, never hand-edited.

## 0.3.0a1 — unreleased, and HELD

`PostgresRecoveryBundle.v1` — the artefact a database can actually come back
from, and the reason `Assurance.PROVED` is now reachable at all.

`pg_dump --dbname` captures GRANTs and RLS policies and never captures the roles
they name. A `pg_restore` of Vendor CP's newest production backup into a
disposable PostgreSQL 16 container exited 1 with 114 missing-role errors from a
TOC holding 55 ACL entries, 26 POLICY entries and zero role objects — and left
45 tables, 23 of 26 policies and 16 RLS-enabled tables behind. Under ADR-0023
the revocation IS the plane isolation, so that database reads as recovered and
is not.

`recovery.py` adds the bundle: thirteen required components, each with a digest
and a statement of what it covers — dump, role and membership closure DERIVED
from the source catalog, role attributes and PostgreSQL 16 per-membership
INHERIT, ownership, default/schema/object privileges, row- and column-level ACL
evidence, RLS ENABLE and FORCE, extensions, an explicit tablespace decision,
migration heads. `load_manifest` refuses a database-only dump on the artefact's
shape, before a target exists; that refusal catches a plausible WHOLE, which is
the shape that fools an operator.

No passwords, no hashes, no superusers: `RoleFact` has no field a verifier could
occupy and refuses `superuser`. `pg_dumpall --globals-only` is named as the
wrong flag — it emits SCRAM verifiers — and `--no-role-passwords` as the right
one.

`[database]` in the descriptor declares typed roles, expected schemas and
isolation invariants. A declaration is a CLAIM: nothing turns it into role DDL,
`restore_plan` refuses a bundle with no role closure even when the descriptor
names every role, and an AST guard proves the package contains no role DDL
anywhere.

`EffectivePrivilegeFact` — isolation is proven with `has_table_privilege` OR
`has_any_column_privilege` across all seven table privileges, in both
directions. `information_schema.table_privileges` sees only direct grants and
reports "fully revoked" for a role holding the privilege through PUBLIC, an
inherited membership, or a column.

`classify_invariant_breaches` — a rehearsal is a DRIFT DETECTOR as well as a
recovery proof. A restored copy violating a declared invariant has either been
restored unfaithfully or restored perfectly from a production database that is
already wrong, and those have opposite remedies. Comparing the restored copy
against the source catalogue separates them, which is nearly free because a
verification already holds both: a breach in the restored copy only is a
RESTORE DEFECT, a breach in both is SOURCE DRIFT. Both still fail the proof —
the label changes where the operator looks, never whether the receipt is PROVED,
because otherwise the cheap repair is to relax the bundle until it passes.
Measured instance: a Platform CP rehearsal found `platform_api` holding DELETE
on a delivery-target table, and production had the same permission — real drift,
a required revocation whose migration has never run.

Counts (`roles`, `privileges`, `policies`, `rls_tables`, …) are recorded in the
manifest as OBSERVATIONS and gated on by nothing. A grant matrix is a good
invariant and a poor assertion: `app_admin 315 / app_user 62 / platform_api 164`
changes with every migration, so the gate is the property, not the total.

`RESTORE_PROCEDURE` — ten ordered steps. `adjudicate_restore` DESTROYS a target
after any non-zero restore, and after a zero exit carrying missing-role errors.
`RecoveryReceiptV1` is value-free and carries the restore wall clock.

**Behaviour change.** `providers/compose_host.py` refuses its own historical
`("--no-owner", "--no-privileges")` default for any product declaring
`[database]`; that default gave every adopting product a dump with no ownership
and no grants in it. `BackupRecord` gains `artefact_class`, defaulting to
`data_export`, and a `data_export` may not claim RESTORABLE or PROVED.
`retention_keep` now also keeps an aged data export until a newer PROVED bundle
exists.

### Also in 0.3.0a1

`DeploymentIdentity.v1` — every rendered Compose service now carries
`io.dotmac.deployment.*` labels: the product, the environment, the compose
service name and its KIND (`release` | `migration` | `dependency` |
`telemetry`), plus — on the services that run the product's own image — the
manifest digest, the configuration digest and the source revision.

A controller that cannot read a release's identity off the running object has
to infer it, and the two things available to infer from are both wrong. An
image TAG is mutable, which is the reason every other reference in this
facility is a digest. A compose PROJECT name is an operator's `-p` flag or the
directory the file happens to sit in. Neither is an authorized identity, and a
controller that reconciles against an inferred one reconciles the wrong release
confidently.

The configuration digest is the CANONICAL DESCRIPTOR DOCUMENT's digest — the
same value `dotmac-deployment-control` binds an approval to — so a controller
compares the label to an approved plan digest with `==` rather than translating
between two spellings of one value. It is taken over the descriptor as actually
rendered, image override included, so a rollback restamps it and a rollback to
a previously approved image reproduces that image's approved digest exactly. It
deliberately is NOT a digest of the rendered compose file: the label lives
inside the file it would describe.

Consequence worth knowing: the canonical document carries the exact facility
version, so a Foundation upgrade changes the configuration digest and therefore
the rendered bytes, and `render --check` fails until the assets are
re-rendered. That is intended — the version is in the digest precisely because
a renderer upgrade can change what a descriptor word MEANS.

`build_canonical_document` gains `refuse_resolved_material=False` for that one
caller. The flag changes no byte of the document — the refusal only ever
raises — but the refusal is a boundary check about what may be SENT to Control
rather than a canonicalization rule, and a descriptor it trips (an in-container
`uvicorn --host 0.0.0.0` is enough) must still be renderable. A container with
no identity is strictly worse than a descriptor Control would want edited.

Auxiliary services are labelled but NOT stamped with the release: a Redis or a
vendor collector is recreated on its own schedule and takes no part in the
release, so making one answer "yes" to "are you running release X" would be a
confident wrong answer rather than a missing one. The migration service IS
stamped — it runs the product image at this revision and is the release's first
effect on the database.

`IngressPolicy.v1` — the typed exposure contract, and the non-mutating
projection that makes an exposure authorizable.

`PortPublication` gains mandatory `exposure` (`none` | `loopback` | `private` |
`public`) and mandatory `address_family` (`ipv4` | `ipv6` | `dual_stack`). The
free-form `bind` is REMOVED and declaring it is fatal; the bind address is
DERIVED from the two declarations, so a loopback publication renders an explicit
`127.0.0.1` and/or `::1` while anything routable renders a required, no-default
promotion-time variable. `none` emits no publication at all. Compose renders in
LONG SYNTAX for roles and managed dependencies alike, one entry per declared
family, so `host_ip` is a field that cannot be omitted rather than a string
position that can.

`[ingress]` declares its own `exposure` and `address_family`, because an edge is
where a `public` exposure legitimately lives; a role may no longer also publish
a port its edge already routes to. Source policy is a NAMED source set that
`dotmac-deployment-control` resolves at authorization — no product IP literal is
accepted anywhere, `trusted_proxies` included. A provider capability matrix
fails a publication closed when it claims a control no available provider
enforces.

`ProductDeploymentSpec.to_canonical_document()` returns
`DeploymentDescriptorDocument.v1`, and `canonical_bytes()` / `sha256_digest()`
belong to that DOCUMENT rather than to the spec or a renderer — so there is one
answer to "what was signed" and a caller cannot reach the digest without
holding the bytes it was taken over. It is the missing hop between a parsed
descriptor and `dotmac-deployment-control`'s desired specification: the facility
previously had no canonical document at all, only digests of rendered bytes, so
no descriptor fact was inside any plan digest.

The document carries schema identity, the exact facility version, every default
materialized, the service roster and roles, exact image references, the ingress
and exposure policy, and the migration, backup, handoff and rollback
requirements. It EXCLUDES resolved endpoints, IP addresses, credential bindings
and secret values — Control binds this digest into an independently signed
authorization and resolves the private material separately, so a resolved
address reaching the digest would collapse the two owners into one. The
exclusion is enforced over the finished document, with a planted-address proof.

The descriptor half is derived by walking `dataclasses.fields` rather than by a
hand-written serializer, because a hand-written one is a field allow-list: the
next field somebody adds stays out of the digest silently. `build_edge_plan()`
and `build_firewall_plan()` are provider-neutral; the firewall plan is derived
defense-in-depth and never a substitute for a correct socket binding.
`dotmac-deploy ingress-policy` prints all of it and mutates nothing.

Three measured facts are encoded rather than described. An `ip6tables`
`DOCKER-USER` rule for a published port is INERT — that chain is jumped only
from `FORWARD` while an IPv6 publish terminates on `INPUT` in `docker-proxy` —
so rules derive into `INPUT` on IPv6 and `DOCKER-USER` on IPv4, and emitting v6
into `DOCKER-USER` is refused. The IPv4 rule matches `--ctorigdstport` because
the packet there is already DNATed and its `--dport` is the container port. And
every allowlist ends in a terminal DROP, because one whose last rule is an
ACCEPT enforces nothing.

### Lane 3 is a runner and a receipt, not a fixture and a table

`scripts/exposure-rehearsal/` held a descriptor and some recorded bytes that no
test and no workflow consumed, and the sixteen gate items lived in a
hand-maintained markdown table whose header once read "14 of 16 CLOSED" while
its own rows recorded four `partial` and one `n/a`.

`scripts/exposure_rehearsal_runner.py` executes the lane through
`ExposureTransaction` over `ComposeHostExposureEffects` — snapshot, plan, apply,
re-observation, external probes, rollback, exact restoration comparison — and
emits `RehearsalReceipt.v1`. Every input is required and none has a default: the
protected-main revision, the wheel candidate digest, the Platform CP
authorization run, the signed authorization document, the controller identity,
the lease, the probe identity and the exact fixture. A rehearsal missing one is
not a partial rehearsal, it is a different activity.

`require_rehearsal.py` now reads **Lane 3**, not Lane 2. Lane 2 proves a real
engine, database, handoff and restore loop; it never watches an IPv6 socket
refuse the internet, which is what this release is named after. Two oracles,
because they fail differently: the Actions API says a run succeeded on this
exact SHA, and the receipt says what it established. A green run whose receipt
is full of `blocked` rows is exactly what the pair catches.

**Only `executed_passed` satisfies publication.** `hand_measured` and `vacuous`
are their own statuses because the old count folded them into "closed". The
status document is now GENERATED (`make rehearsal-status-check`), so a heading
cannot contradict its own table.

### The fixture can now fail the checks it feeds

The old one published only `loopback` and `none`, so `build_firewall_plan`
returned EMPTY and gate item 6 passed without observing anything. The new one
adds a `private`, dual-stack, source-scoped publication REMAPPED from 19001 to
8080 — the only shape that proves original-destination matching, because with
host == container a wrong `--dport` rule and a correct `--ctorigdstport` rule are
indistinguishable. It derives four rules: `--ctorigdstport` in `DOCKER-USER` on
IPv4, `--dport` in `INPUT` on IPv6, each ending in a terminal DROP.

### `ObservedProxy` carries the pid

Gate item 5 is "the `docker-proxy` pid is NEW" — a surviving pid means the
container was never recreated and the apply proved nothing. The parser discarded
the pid entirely, so that item could only ever be closed by a human reading `ps`
output. It is now captured (both `ps -eo pid,args` and `ps aux` shapes), and
`None` when the listing carried no pid column, so a caller must refuse rather
than compare sentinels.

### A typed `Digest`, and `HostLease.v1`

`Digest` replaces raw string comparison: bare and prefixed spellings parse to one
value, uppercase is accepted on input and lowercased on output, and unknown
algorithms, wrong lengths and malformed values are refused.
`require_same_digest` takes a NAMED mapping so a refusal says which term
disagreed, and refuses fewer than two terms so a three-term gate cannot be
weakened by passing fewer.

`HostLease.v1` records exclusive use of a shared target. Measured 2026-08-30,
the rehearsal host had no lease mechanism at all while eleven agents' worktrees
shared it. A lease **cannot be self-granted**: `authorization_run_id` is
mandatory, and a holder that writes its own lease has proved only that it can
write a file.

### `VantageQualification` — positive proofs, not an absent NIC

The external vantage's second NIC is gone, which removed the risk AND removed
the discrimination control that depended on it. A check that stops
discriminating because the thing it discriminated against was removed has been
lost, not passed. Qualification is now seven positive proofs, and the last —
that the TARGET observed the expected source address — is the only one a vantage
cannot fake about itself.

### `DeploymentProvenance.v1` — binding what ran to what was authorized

`build_provenance()` binds six facts into one canonical, digest-bearing record:
the descriptor digest, one sha256 per rendered asset (the Compose hashes among
them), the per-role image digest, the source revision, the service roster, and
the authorization receipt.

**Digests, never tags.** An image reference with no `@sha256:` is refused: a tag
is a mutable pointer that can be moved to different bytes after the approval and
before the deploy, and the record would still read as true. A branch name or an
abbreviated commit is refused for the same reason — neither identifies the
source months later.

**The receipt is bound by VALUE, never by import.** `dotmac-deployment-control`
owns plans, approvals, attempts and receipts; this facility owns rendering and
execution and declares ZERO runtime dependencies. So `AuthorizationReceipt` is a
typed input the caller constructs from Control — the same shape as `ProbeResult`
and `ProbeVantage` — and `provenance.py` imports nothing outside the standard
library, which is asserted from its own AST.

What the module does with it is a pure equality check: the digest the receipt
cites must equal the digest of the descriptor in hand. That is deliberately NOT
an authorization decision. Foundation never judges whether an approval should
have been granted; it refuses to execute something OTHER than what was
authorized, which is its own business. A structurally incomplete receipt is
refused as a malformed input; an unfavourable one is not evaluated at all.

`normalize_digest()` resolves a real trap between the two owners: Control's
`plan_digest` is BARE hex and this facility emits the `sha256:`-prefixed form,
compared with a raw `!=`. Unnormalized, a mismatch reads as a security refusal
while actually being a formatting bug — the kind of alarm that gets suppressed
rather than investigated. Both sides are normalized before comparison.

### The preservation property moved to the TRANSACTION

`OWNERSHIP_PREFIX` and `ownership_comment()` moved from
`providers/exposure_host` to `exposure`, and `ExposureTransaction` now MEASURES
what the provider previously only promised. Before applying it records the rules
in the shared chains it does not own; after the apply, and again after any
rollback, it looks and refuses if one of them has vanished.

The asymmetry is deliberate. A foreign rule that VANISHED was deleted by us —
the data-loss bug wearing the word *restore*, and exactly what replaying a
captured chain does. A foreign rule that APPEARED was written by somebody else
while we held the lock, and refusing on it would reject the correct behaviour of
preserving a rule that arrived mid-transaction. An unlabelled rule on a port we
publish is treated as ours rather than as unrelated host state, because calling
it foreign would make a correct rollback of our own leftover look like data loss.

This is a guarantee of the SEAM, not of one implementation: a second provider,
or a regression in this one, cannot quietly lose it.

### A real `ExposureEffects`, and the preservation property

`providers/exposure_host.ComposeHostExposureEffects` implements
`ExposureEffects` against a host, so apply, snapshot, re-observation and
rollback run through `ExposureTransaction` rather than through an operator's
hands. `dotmac-deploy exposure-apply` is the entry point, DRY RUN unless
`--execute`.

**A rollback restores what that transaction changed and nothing else.** The
obvious implementation — snapshot the chain, flush it, replay the snapshot —
destroys any rule another process added while the transaction was running, and
both chains this facility writes into (`DOCKER-USER` on IPv4, `INPUT` on IPv6)
are shared with everything else on the host. On a host carrying other work
that is a data-loss bug wearing the word *restore*.

So nothing is ever flushed. Every inserted rule carries
`-m comment --comment dotmac-exposure:<product>`, every removal is a targeted
`-D` of a rule bearing it, and a rule without it is never touched — whenever it
appeared. Ownership lives in the rule rather than in a diff against a snapshot,
because a diff cannot tell "someone else added this" from "we failed to record
adding this", and those need opposite handling. Deletes replay the rule's own
arguments, never an index, because an index shifts the moment anything else in
the chain changes.

The port match is re-derived from `FirewallRule.render()` rather than
re-implemented, so the rule the provider inserts cannot drift from the rule the
plan describes — the drift that put a `--dport` on a remapped publish.

Proven, not intended: a foreign rule is planted and asserted to survive,
including one that appears MID-TRANSACTION, and the suite is checked against
two sabotaged implementations (flush-and-replay, and index-based deletes) to
confirm it goes red for both.

### Execution and proof

`exposure.py` applies the plan and then goes and looks. `ExposureTransaction`
takes the product's exclusive deployment lock, SNAPSHOTS the host, applies,
RE-OBSERVES and verifies — rolling back to the observed snapshot on any
refusal, because a rollback that restores only what it thinks it changed cannot
repair what it did not notice changing.

`verify_exposure()` compares declared bindings against real sockets,
`docker-proxy` processes and firewall chains, in both directions: a declared
family that is not bound is `socket_missing`, and a bound port the descriptor
never mentions is `undeclared_socket` — the port that stays open is the one
nothing declares. `dotmac-deploy exposure-verify` runs the same verifier over
RECORDED command output, so an incident's pasted `ss` and `iptables-save` can be
replayed months later with no host present.

Three refusals encode what a naive check misses. `refuse_non_recreating_apply`
refuses an apply that cannot change a binding, because `docker compose restart`
reuses the container it already has and a plain `up -d` will not recreate an
unchanged image — a correct Compose diff plus a restart leaves the OLD binding
live and the NEW one believed. `conclude_binding` returns INCONCLUSIVE rather
than "closed" when the only evidence is an external probe against a host that
silently DROPs, because loopback-bound and wildcard-bound-and-dropped are
indistinguishable from outside. And `accept_public_exposure_evidence` refuses a
probe whose vantage is inside — or is not KNOWN to be outside — a source set
the plan accepts: on 2026-08-29 two agents independently connected to "public"
ports from a workstation sitting inside this fleet's own allowlisted range, and
each escalated a P0 that did not exist.

MAJOR-shaped, released as a pre-release, and the warning-phase deviation is
recorded with its four premises in `COMPATIBILITY.md`. **Publication is HELD**
while OpenBao containment and credential rotation settle — see
`docs/inventories/declared-publication-baseline.json`.

## 0.2.0a2 — unreleased

Make the strict image-audit filesystem collector run as an inspection-only
uid/gid 0 while continuing to validate the image's configured runtime
`Config.User` as numeric and non-root. A failed filesystem walk now refuses
the gate explicitly and preserves its partial output and diagnostics instead
of truncating the listing to empty evidence. Add executable negative controls
and one planted failure for every hardened-image rule.

## 0.2.0a1 — 2026-08-28

Normalize the Nginx renderer to exactly one trailing newline. The first ERP
adopter proved that `end-of-file-fixer` rewrites the 0.1 output while
`render --check` requires those original bytes, making the consumer's two gates
mutually exclusive. This is a minor release because rendered bytes are public
contract even when the behavioral configuration is unchanged.

## 0.1.0a1 — 2026-08-28

First cut. `ProductDeploymentSpec.v1`, the deterministic renderers, the
hardened image contract and its audit, the deployment state machine as data
with its executor, backup/restore assurance levels, drift comparison, the
64-alert common catalogue, the telemetry resource-attribute stamp, the
conformance kit, and the `dotmac-deploy` CLI.

Extracted product-first from three qualifying sources — `dotmac_sub`'s
deployment state machine, `dotmac_integrator`'s image and migration-ordering
contract, `dotmac_erp`'s migration-role preflight and backup-before-migrate —
with eighteen defects recorded as deliberate non-goals in `EXTRACTION.toml` and
the inventory.

Published through the protected facility lane after an exact-main disposable
host rehearsal completed with 34 passes, zero failures and zero skips.
