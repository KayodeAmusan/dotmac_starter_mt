# ADR-0070: Deployment is a stateless versioned foundation, not a module

- Status: Accepted
- Date: 2026-08-26
- Deciders: Michael
- Supersedes: none
- Extends: ADR-0003 (composable deployment profiles — this ADR supplies the
  concrete facility ADR-0003 § "Infrastructure provisioning and deployment
  execution" declared but never built), ADR-0006 (module/assembly ownership and
  the product-first extraction amendment), ADR-0024 (applications are
  independent), ADR-0062 (modules own definitions, assemblies own exporters)
- Related: ADR-0007 (authenticated applied state), ADR-0009 (a secret is held,
  never dereferenced), ADR-0018 (a guard exemption states an enforceable
  premise), ADR-0023 (dual-plane modules), `packages/dotmac-deployment-control`
  (desired deployment state), `packages/dotmac-platform-health`

## Context

Four Dotmac repositories each carry their own deployment infrastructure, and
the same seven mechanisms are implemented four times with four different sets
of defects.

`dotmac_sub` has the most mature engine: an exclusive deployment lock, exact
OCI digest and source-revision verification, backup before DDL, a migration
lock with bounded retries, a warm candidate that is readiness-gated before
Nginx hands traffic over, per-worker verification and a bounded stability
window before the rollback decision. It also carries a 22-service Compose
topology with genuinely privileged network roles, a second divergent copy of
its Nginx configuration, and host-side script drift that has caused two
recorded staging incidents.

`dotmac_integrator` has the best image and migration-ordering contract: a
non-root, read-only, capability-dropped runtime; a one-shot migration service
that must COMPLETE before any runtime container starts; an owner role that is
absent from the runtime roles; an audited image (`scripts/audit_image.sh`) that
carries its own sensitivity proof; and deployment thresholds that live in
`deploy/alerts/` rather than in the process. It has no host deployment engine,
no backup, and no ingress at all, and its Compose file and runbook disagree
about whether a digest or a mutable tag is deployed.

`dotmac_erp` has production-used migration-role preflight, backup-before-
migrate and static-asset synchronization — and, in the same files, production
source/template/static bind mounts, a `/health` gate that cannot fail, one
credential used for both migration and online access, and development OpenBao
and CSP defaults that reach production.

`dotmac_starter_mt` is the reference assembly and has the thinnest of all four.

Copying the best of these into the other three would not establish a standard.
It would establish four forks of one standard, and the next security fix would
have to be applied four times by four people who would each apply it slightly
differently. That is the failure ADR-0006's build-once rule exists to prevent,
applied to a surface — build and deployment — that ADR-0006 never named because
it is not a business capability and has no rows.

## Decision

### 1. A fourth destination exists, and it is stateless

`dotmac-build-once-reusable-belongs-in-kernel` resolves reusable code to the
kernel, `dotmac-ui`, or a `dotmac-<domain>` module. Deployment infrastructure
fits none of them, and forcing it into one is what has kept it unbuilt:

- It is not kernel. The kernel is imported by a running application process.
  A build runner that renders a Compose file has no database, no ORM, no web
  framework and no tenant, and must not acquire them in order to validate a
  descriptor.
- It is not a module. A module has a `ModuleManifest`, a `mod_<code>` schema, a
  migration lineage and rows. This facility has none of those and must never
  gain them: the thing that decides how a deployment is built cannot be a
  tenant-scoped table inside one of the deployments it builds.
- It is not an assembly overlay. That is precisely the copying this ADR ends.

`dotmac-deployment-foundation` is therefore created as a **universal facility**
— the classification `packages/dotmac-kernel/EXTRACTION.toml` already uses, and
the one `scripts/check_allocation_serialized.py` already exempts from the
migration-ledger gate because such a package legitimately owns no lineage.

It is housed in the Starter's `packages/` tree, for the same reason
`dotmac-application-directory` is: the Starter is where distributions are built
and released, and housing is not composition. The assembly does not install it
into the application image, `alembic.ini` gains no lineage, and no application
process imports it.

Concretely, and enforced:

- no `ModuleManifest`, no models, no migrations, no `short_code`, no
  `migration_prefix`, no tenant or business state;
- zero runtime dependencies — not `dotmac-kernel`, not SQLAlchemy, not FastAPI,
  not Jinja, not a YAML library, not a templating engine. Standard library
  only, exactly as `dotmac-ui` is dependency-free and for the same reason: a
  build runner adopts the facility without adopting a runtime;
- rendering is explicit Python that emits text, not a template engine, so
  `render --check` compares bytes and a reviewer reads a diff;
- consumed by CI, build runners, provisioning workers and deployment hosts —
  never by an application domain service. Two import-linter contracts say so in
  both directions.

Any concrete Python implementation of a kernel provider protocol — a
`ProvisioningProvider` for a dedicated VM, for instance — is a **stateless
protocol adapter** and is classified as one. It is not an optional module.

### 2. The boundary, in four lines

- **`dotmac-kernel`** owns universal in-process contracts and mechanics:
  session factories and transaction boundaries, tenant/organization priming,
  conflict savepoints and public error contracts, product/module manifest
  contracts, migration graph orchestration, the standard liveness/readiness and
  telemetry *interfaces*, and the provisioning/profile protocols and their
  reusable conformance kits. It never renders infrastructure.
- **`dotmac-deployment-foundation`** owns build- and deploy-time execution:
  the versioned deployment descriptor, the renderer, the hardened image
  contract and its audit, the Compose baseline, the deployment state machine,
  backup/restore and their evidence, ingress providers, the telemetry
  collector profile and resource attributes, and the common infrastructure
  alert catalogue. It decides HOW, on one host, for one release.
- **`dotmac-deployment-control`** owns durable fleet intent: desired state,
  immutable plans, approvals, rollout decisions and attempts, authenticated
  acknowledgements and drift. It decides WHAT to deploy and to which target.
  It gains no Docker, Nginx, SSH, cloud-provider, migration, backup or
  monitoring implementation — its `EXTRACTION.toml` contract already says so
  and this ADR does not widen it.
- **The product assembly** owns declarative, product-specific input only:
  identity, manifest reference, process roles and commands, worker and queue
  topology, image-specific system packages, migration command, readiness
  dependencies, exposed domain ports, product preflight/postflight commands,
  product metrics and domain alert rules, and explicitly justified capability
  or resource exceptions.

`dotmac-platform-health` is untouched by this ADR. It may own authenticated,
normalized health *observations* and their projection. It owns no raw logs,
metrics or traces, no deployment decision, and no monitoring infrastructure.

### 3. Variation enters through a typed descriptor, never a branch

No shared execution path in the foundation contains `if product == "erp"`, a
product enum, a product-keyed behaviour dict, or a provider conditional. Every
difference between ERP, Sub, Integrator and Starter is a value in
`ProductDeploymentSpec.v1` or a declared extension point. This is ADR-0024 § 4
applied to infrastructure, and it is checked the same way: a static guard over
the foundation's own source, with a sensitivity proof.

### 4. The descriptor holds names, never secrets

`ProductDeploymentSpec.v1` declares *material names* and approved OpenBao
pointers. It may not contain a credential, token, DSN with embedded
credentials, private key or any other secret value — ADR-0009's rule, restated
for a file that is checked into a product repository and rendered into
configuration a host reads. The loader refuses such a value at parse time
rather than at review time, and that refusal carries a sensitivity proof.

### 5. Nginx is the first dedicated-VM ingress provider, not the architecture

Ingress is a replaceable provider. Nginx is the first one implemented because
Sub's warm-candidate handoff is the proven production behaviour and it is
Nginx-shaped. It owns no tenant, domain, TLS or business lifecycle decision:
it renders an upstream pair, a candidate handoff and the timeout/size envelope
the descriptor declares, installs the result atomically, verifies with
`nginx -t`, rolls back on failure and reports a config-digest drift.

Static Nginx serves a *known* set of hosts. Dynamic customer domains are a
different problem and are explicitly out of scope here: they need a
domain/DNS/TLS reconciler, and Caddy, Traefik, cert-manager or a managed load
balancer remain available as later providers for that profile. Host bootstrap
is a typed provider (Ansible or cloud-init); an imperative "apt install and
hand-edit" script is never retained as the authority.

### 6. Build once, promote a digest

One image is built once and the exact same OCI digest is promoted through
test, staging and production. No environment rebuilds. The deployment engine
verifies the digest and the source revision it was built from before it mutates
anything, and refuses a dirty or source-mounted production state outright.

### 7. The standard is enforced at three levels, or it is not a standard

A template that is copied is not a standard; it is a fork with good intentions.
Enforcement is:

1. **Build time** — one renderer, one image contract, one release workflow.
2. **CI time** — a reusable cross-repository conformance workflow pinned by
   immutable commit, required by the Governance profile in every product, plus
   sensitivity tests proving each detector fails when a temporary violation is
   introduced (ADR-0018), and two-directional ratchets for temporary
   deviations.
3. **Runtime** — `render --check` against the committed assets, image audits,
   disposable migration and boot tests, and a running drift check comparing the
   image digest, configuration digest and product-manifest digest with the
   approved deployment plan.

## Consequences

- ERP is the first full adopter and the highest-value one, because it holds the
  most defects. Starter becomes the minimal reference adopter. Integrator
  adopts the same descriptor and its Compose/runbook contradiction is corrected
  in the same change. Sub adopts last: its 22-service topology and privileged
  network roles need explicit, justified overlays, and its duplicated
  deployment and Nginx scripts are retired only after parity is proven, never
  before.
- Four repositories gain a `deploy/product.toml` and lose an engine. The
  engine's behaviour is extracted product-first from Sub, Integrator and ERP as
  rule 24 requires, with the defect list recorded in the dossier so that a
  reader can see what was deliberately not copied.
- A deployment defect is now fixed once and propagates through an exact version
  pin and an update pull request, exactly as ADR-0003 § "Cross-project reuse
  and release model" already requires for the kernel.
- **Observability is definition-only.** The facility renders a collector
  configuration and a 64-alert catalogue, and nothing consumes either: no
  collector is deployed, no metric is scraped, no rule is loaded, no annotation
  is emitted, and several catalogue alerts name metrics no Dotmac process
  produces. The catalogue is a SPECIFICATION of what must be emitted, not a
  monitoring system, and it must not be described as one — a directory of 64
  well-formed rules reads as 64 alerts to anyone who does not check. The
  sequence for making it real is in
  `docs/inventories/deployment-foundation-rehearsal.md`.
- The facility is unadopted until a product exact-pins a released version and
  its rendered assets pass `render --check` in that product's CI. Until then it
  is built and validated, and must not be described as in production
  (`AGENTS.md` rule 30).

### Amendment — 2026-08-31: database changes promote a declared result

A database-advancing operation carries a pre-authored descriptor transition:
target, plan digest, starting descriptor digest and result descriptor digest.
Authorization binds the result, plan and target; the starting digest is the
independently observed live-state and compare-and-swap precondition. A running
database is never used to author its descriptor.

The operation either commits in one database transaction or declares an
ordered descriptor for every durable checkpoint, including the final state. A
partially committing operation with only a final candidate is refused because
it leaves recovery with an undeclared intermediate state.

PostgreSQL and the accepted descriptor registry are separate transaction
domains, so their movement is not described as literally atomic. After the
database result is observed and before the accepted descriptor is promoted,
the transition is explicitly `promotion_pending`. Promotion is an idempotent,
durably recorded compare-and-swap from the starting digest to the result digest
keyed by transition id. Recovery re-drives that same operation and must recover
the original promotion event; observing that the pointer already equals the
result is not itself promotion evidence. A terminal receipt binds both
descriptors, the plan and target, the database postcondition, and the promotion
event.

The corresponding drift comparison runs in both directions at preflight,
postflight and recovery. A live fact missing from the descriptor is as much a
failure as a declared fact missing from the catalogue. Effective-privilege
coverage comes from an independently selected audit universe rather than from
the descriptor's invariants, because the omitted invariant is the Platform CP
incident shape. A report cannot expose a matched descriptor digest until the
whole selected universe was answered.

This amendment also records a boundary rather than hiding it.
`ProductDeploymentSpec.v1` is already published and is not redefined to accept
a new key. An independent `DatabaseDescriptorCatalogBindingV1` sidecar can bind
canonical database-catalogue schema/path/digest coordinates to its descriptor
digest. Each coordinate names either one complete MODULE schema or every
expected schema as a PRODUCT catalogue. A sidecar is not a descriptor fact and
can never enable v1's whole-descriptor matched digest.

The kernel module and product v1 schema identifiers are paired exactly with
MODULE and PRODUCT scope respectively; a future schema needs a new explicit
registration. A product coordinate binds catalogue product code and version to
the exact descriptor product and requires a decision reference when those codes
are intentionally aliases.

`ProductDeploymentSpec.v2` is the explicit successor rather than a silent v1
expansion. The v1 parser still refuses `database.catalogs` and its canonical
bytes omit the version-gated field. V2 requires at least one coordinate whenever
`[database]` exists, embeds it in the canonical descriptor, and may reach a
whole-descriptor match only after recognized witnesses cover every expected
schema.

Foundation owns neither catalogue grammar nor live collection. Structural
acceptance must invoke an integrated verifier over the held catalogue and
observation bytes, not trust a freely constructed result because its comparator
and observer strings look known. The result and `ObservedDatabaseState` bind
the same immutable observation identity and PostgreSQL major, report changed
attributes as both set-difference directions, and require explicit complete
schema, table and column extent. Foundation invokes that dependency-inverted
verifier with the held payloads and rechecks its factory-only result's contract
id, fact scope, digests, PostgreSQL major, declaration schema/scope/complete
schemas and product code/version before normalizing its typed facts.

Scoped evidence stays scoped. The Deployment Control catalogue can prove the
seven tables and 95 columns in `mod_deploy` without waiting for every module,
but that witness cannot expose the whole descriptor's matched digest while
`public` or another declared schema lacks structural coverage. Current
`CatalogEvidence` cannot create the witness because it carries no table or
column inventory. A product must compose the kernel-owned observer and pass the
matching module or product verifier into Foundation; a schema name or contract
id alone is not an adapter and proves nothing. Neither a schema name nor an
Alembic head is substituted for structural proof.

### Amendment — 2026-09-07: Platform Health authors signed evidence; Control freezes authorization

On 2026-09-07, Michael explicitly approves this two-document authority chain.
It is an architecture contract only: implementation and adoption remain zero
until the Platform Health producer, Control extension, Platform CP composition,
Foundation verifier and a production run land. No prior text is treated as
having declared this producer or provenance chain.

**Canonical health evidence.** Platform Health is the sole durable-health owner
and authors `DeploymentHealthEvidence.v1`. Its canonical bytes contain exactly
the requested component roster, each component's observation identity,
observation time, state and freshness, the evaluation time, and an owner-derived
`valid_until`. The evidence contains no deployment coordinates. Platform Health
signs those exact canonical bytes with Ed25519. Its private key is held only in
the Platform Health service composition through an approved `SecretSource` /
OpenBao pointer; it is never held by the Platform CP deployment runner or any
repository. Control owns the versioned public-key eligibility/revocation
registry and verifies the signature through the existing Kernel verification
pattern. Foundation adds no cryptography.

Integrator authenticates and transports bounded raw observations into Platform
Health through `HealthObservationInput`; it authors neither canonical health
evidence nor either signature, and decides no state or freshness.

Platform CP only orchestrates, submits and translates. It authors and signs
neither document. It submits the signed health evidence together with the exact
`ExecutionPlanDigestV1` to Control. Control verifies the inner signature, binds
its digest to target, environment, operation, plan, descriptor, image and the
exact required-component roster, then freezes and signs the outer authorization.
Adding the health-evidence digest and roster to that signed authorization
requires an explicit successor/versioned authorization schema; it must not
silently widen or redefine the existing published statement. Control does not
recompute health. The binding logic is Control-owned; Platform CP owns
exhaustive adapter and runner composition.

**The Foundation boundary.** Foundation receives the inner evidence as an
offline supplied document; a caller-chosen path is transport, never authority.
It accepts only after the evidence digest and every coordinate and roster entry
match a `VerifiedAuthorization` / `ExecutionGrant` produced through the
existing signed Control path. Foundation makes no network call and imports
neither Platform Health, Control nor Integrator. The import-linter must forbid
those dependencies explicitly; dependency absence alone is unmonitored.

The required component set is a product-owned declarative input and must enter
a successor/versioned descriptor and plan contract. Platform Health signs
exactly that requested roster and represents missing entries explicitly.
Foundation evaluates every entry and emits a deterministic, sorted set of
findings. Admission requires an exact roster, every state `healthy`, every
freshness `fresh`, and both the evidence and outer authorization to be live.
Aggregation is therefore neither worst-of nor first-refusing.

**Refusal vocabulary.** The contract requires seven health/receipt refusals:
`missing`, `incomplete`, `expired`, `unknown`, `degraded`, `stale` and
`unhealthy`; Foundation refuses each. They are not the complete integrity
vocabulary. Malformed evidence,
an unknown or revoked signer, an invalid signature, evidence-digest mismatch,
wrong deployment subject or roster, and future-dated evidence remain distinct
refusals. A missing required component is `incomplete`; evidence whose signed
evaluation or observation time is future-dated relative to Foundation's
injected execution time is also refused. Outer Control expiry must not extend
Platform Health's `valid_until`.

**What stays separate.** Local readiness, liveness, worker and scheduler gates
remain separate static or runtime gates; a health evidence admission does not
satisfy them, and they do not satisfy this chain. The role-level readiness/
liveness gate already in
`_validate_cross_field` (`spec.py` lines 2706–2721: a role with `replicas > 0`
must declare an HTTP `live`/`ready` probe, a `WorkerContract.ping_command`, or a
`scheduler_tick_max_age_seconds` budget, or the descriptor is refused as
unmonitored) is unchanged and is not this receipt. It is a static, per-role
declaration check at descriptor-validation time; the health receipt is a
per-deployment-attempt, cross-service artifact checked at a different point in
the pipeline. Passing one does not satisfy the other, and this amendment adds
no exception to either.

This producer/verifier separation is construction and pending Governance
ratification, not a claim that a local independent-provenance rule already
exists. Rule 49 is valid on the current branch and supplies the exact-plan
digest precedent. Rule 24's product-first and adoption requirements, and rule
30's authoritative-external-oracle boundary, remain accurate: a passing receipt
is composition evidence, not adoption evidence. Until the implementation and
production run land, `dotmac-platform-health` remains unadopted.

## Amendment, 2026-09-07: trusted host provenance v2 custody contract is held, not admitted

Foundation's discarded sidecar allowed a `TrustedAttestationBinding` result and
trusted key-id labels. It is replaced before freeze by
`TrustedHostAttestation.v2`: signed candidate and installed-host envelopes bind
the signer public-key fingerprint, declared custody domain, root version,
purpose/schema, issuer, algorithm, validity interval, role-specific audience,
observation identity and complete immutable subject. Atomic replay consumption
is future Control/admission ownership, not this stateless verifier. Candidate
evidence belongs to the protected Starter release-workflow signer and binds
package, version, final wheel digest, source revision, repository, run id and
artifact id. Installed-host evidence belongs to a distinct target-local
host-attestation workload and binds the Control-supplied expected host identity,
installed package/version/digest and the candidate-subject digest. The
authoritative owner and grammar of that host identity remain unresolved;
caller-selected paths convey no authority. Platform is transport only; this
package contains no private key or network client.

Control must later bind fingerprint/purpose/domain roots. Until it does, and
until independently produced v2 evidence exists for 0.4.0a2, the verifier is
only a typed parsing/testing seam and no executor may accept evidence, a
verifier, roots, paths or a preverified result from a caller. Both mutating
executors continue their explicit no-evidence refusal before effects. This
amendment implements a contract and does not claim adoption or positive
admission. Its successful return establishes agreement only relative to the
supplied policy and verifier; those inputs become authority only when a trusted
composition sources them from Control.

### Amendment, 2026-09-25: Gate-3 execution authority successor and host ownership correction

This amendment supersedes the 2026-09-07 claim above that host identity's
authoritative owner and grammar are unresolved, and the 2026-09-08 statement
below that Fleet has no usable incarnation coordinate. Accepted ADR-0073 now
assigns canonical `host_id` grammar to Fleet; Control owns authenticated
presenter → target → current host association, enrolled-root standing and
atomic dispatch consumption; Foundation verifies supplied evidence; CP fixes
the provider, clock and commit-before-launch composition at startup. Neither
a request field nor an environment-only mode chooses the verifier, observer or
clock. Python objects/private witnesses do not constitute an unforgeable trust
boundary: installed, reviewed in-process assembly code is trusted as code.

`FoundationExecutionPlanV3` is the successor document whose digest remains
`ExecutionPlanDigestV1`. It binds the exact candidate Foundation wheel digest,
target ID and reference, controller SSH fingerprint, Fleet host ID, immutable
host-key incarnation and enrolment coordinate, in addition to V2's complete
acts and host prestate. Control signs precisely this digest in its unchanged
`AuthorizationReceiptV2` authorization+dispatch pair. Foundation's sole grant
issuer checks that pair with the startup-fixed provider, compares fresh
Control/Fleet-resolved facts and installed artifact metadata independently of
the pair, and rechecks before effects. F2 host-source admission remains the
separate installed-source verification owner; this amendment does not pretend
that PEP 610's recorded wheel hash verifies current installed file bytes.

Gate-3 host binding is exact, not an inferred translation: ADR-0073 defines
F2's authenticated installed `host_identity` as the Fleet `host_id`, the
installed signer fingerprint as the host-key incarnation, and the installed
trust-root version as the immutable enrolment UUID. After F2 admission and
before any effect, Foundation compares all three to the V3 plan and fresh
provider observation. The `Effects` protocol exposes no authenticated target
identity; therefore only trusted CP assembly code may construct the matching
V3 provider, F2 admission provider and Effects bundle. Separately injecting
those components from request fields is not an authority path, and Foundation
does not claim an Effects object proves which remote host it can mutate.

The historical V1 `authorize()` and V1/V2 plan parsing remain non-authorizing.
CLI, Lane 3 and release probes must not convert a single V1 document into an
execution grant. Lane 3 has no ratified CP provider/typed V3 plan coordinate
today, so its workflow refuses rather than deriving host facts from its
request fields. Publication's installed-wheel smoke may pass by proving V3
render/digest behavior and the standalone CLI's honest refusal; that is not
Gate-3 adoption or authorization. The external CP execution composition
remains a visible held prerequisite, not an invented local provider.

### Amendment, 2026-09-25: current standing and dispatch consumption are pre-effect

The V3 grant freezes canonical copies of the exact Control V2 authorization
and dispatch documents it attested. After F2 admission and independent
plan/host rechecks, but before any deploy or rollback effect, Foundation calls
the same startup-fixed provider with those documents and exact expected
receipt, context and plan digest. CP owns the external transaction: it must
revalidate current approval standing, atomically consume the dispatch and
commit before `consume_dispatch(...) -> None` returns normally. A replay,
withdrawn standing, failed transaction, changed host/attempt or expired pair
must refuse before commit. Foundation checks every receipt, V3 plan, fresh
provider observation and F2 host trace fact before that call; no fallible
Foundation check follows it. The request carries a deterministic
`control-dispatch:<dispatch_id>` coordinate. Control's committed consumption
ledger is the recovery source if the process crashes on the next instruction;
local `DeploymentEvidence.v2` carries the same coordinate only when execution
continues and evidence is written. V1 evidence bytes remain unchanged. Python
values cannot independently prove CP's commit; the trusted in-process provider implementation and its conformance evidence are
therefore part of the composition gate. This slice defines and uses that
provider contract; the real CP adapter and conformance proof are external and
not claimed here.

Correction, 2026-09-25: the Control-facing request does not carry the receipt
or observed execution context as separately trusted claims. Foundation checks
both before the call, then passes exact signed-pair bytes, the F2 trace
(including its actual pair-verification result and transient opaque CP
continuation), the execution-plan digest and deterministic recovery coordinate.
CP submits these to one Control host-admission-and-execution finalizer, which
freshly rederives both standings and stages one dispatch consumption in its
caller-owned transaction. Foundation neither interprets nor persists the
continuation.

## What this ADR does not decide

### Amendment — 2026-09-07: successor Control receipt is a Foundation value, not admission

Foundation may retain one minimal, import-free consumer receipt after Platform's
verified-pair adapter has parsed, verified and cross-validated Control's
separately signed documents, including their standing and signer purposes. It
preserves each original envelope digest and
signer identity, requires distinct fingerprints, encodes the two consumer roles
structurally rather than copying Control's purpose vocabulary, and compares the
Foundation execution subject independently. Control's `plan_digest` maps to
Foundation's explicitly named `control_plan_digest`; `attempt_no` remains
dispatch-owned. Foundation does not parse or canonicalize Control documents,
replace either signer, or admit an executor in this amendment. The 73-item
trusted-provenance skip inventory and executor `receipt=None` seam remain a
paired non-admission ratchet.

### Amendment, 2026-09-08: restore the independent v2 same-key refusal

The v2 contract retained its split-roots construction check but had lost the
independent verifier check. `verify_attestation_pair` now refuses candidate
and installed envelopes with the same `public_key_fingerprint` before any
trust-policy, root, or signature evaluation (`trusted-host-source-same-key-
signed-both`). `key_id` is only a bound label: distinct fingerprints using the
same label remain a deliberately admitted near-miss under a supplied policy.

The 73-entry host-source skip inventory is Executor tests only. It never
represented behavioral coverage of the real `RecoveryExecutor.run` ten-step
sequence, which remains separately UNMONITORED while that executor is
non-admitting. This recovery behavior gap has an exact named inventory and
retires only when genuine trusted-provenance admission exists and the real
`RecoveryExecutor.run` sequence is covered; no skip retirement occurs here.

### Amendment, 2026-09-08: pair attestation precedes future admission

The plain v2 receipt remains parseable evidence but no longer exposes the
execution-input gate. Platform supplies both opaque Control documents to
Foundation's `attest_authorization_receipt_v2()` composition seam; an injected
`AuthorizationReceiptV2Attester` attests the pair, and only the resulting
opaque `AttestedAuthorizationReceiptV2` may compare execution inputs. It
exposes neither its parsed receipt nor a reusable witness, and its public
constructor refuses. This is a Python convention boundary, not protection from
malicious code in the same process.

The attester parameter is not an authority selector. A request-selected
implementation can attest invented material, so no Foundation executor accepts
the resulting type in this contract revision. Trusted Platform composition
must eventually own which implementation is installed and prove that a
request cannot replace it before this value may participate in admission.

`approval_decision_ref` is now an independent execution input, and the combined
gate always checks liveness first. Liveness includes `dispatch_issued_at`: a
future-dated dispatch refuses even when its authorization interval and every
equality term otherwise agree. Product vocabulary mapping remains Platform's
future adapter responsibility; this amendment does not rewrite the existing
`AuthorizationReceipt.v2` wire schema under the spent `0.4.0a1` identity.

This amendment deliberately does not invent host enrollment, key material,
replay consumption or an executor admission path. Fleet currently owns only a
string `host_id` and no provisioning epoch. Incarnation will be the enrolled
host-attester key identity: a rebuild must issue a new key and revoke the old
one. That contract lands only with its custody/enrollment owner and Control's
atomic dispatch consumption; a formatted incarnation field alone would close
nothing.

### Amendment, 2026-09-08: six admission decisions, none of them implemented yet

Michael rules six decisions that shape how genuine trusted-provenance
admission is eventually built. None of the six is implemented by this
amendment: no version is allocated, no artifact is built or signed, no
executor stops refusing, and the 73-entry skip inventory is untouched.

**1. Evidence subject is Foundation's own `CandidateArtifact.v1`, never a
kernel record.** Admission for `dotmac-deployment-foundation` binds against a
`CandidateArtifact.v1` receipt authored for the Foundation's own future
`0.4.0a2`, never against the kernel's `0.1.0a103` release record. `0.1.0a103`
is the PATTERN to copy — a committed, CI-authored, branch-protected record
binding version, tag object, peeled commit, artifact digests and publisher
run coordinates (`docs/inventories/kernel-release-verifications/0.1.0a103.json`)
— not the record to bind against. The Foundation's own subject is the
distribution `dotmac-deployment-foundation` (`host_source.py`'s `DISTRIBUTION`
constant), it declares zero runtime dependencies, and an import-linter
contract ("The deployment foundation must not import the kernel, the UI or
the assembly") forbids it from importing the kernel at all. Admitting the
Foundation on a kernel record would let a Foundation whose own bytes nobody
vouched for mutate a host on the strength of a different package's provenance.

**2. Ordering is fixed: freeze source, allocate, build once, sign the exact
bytes, commit the receipt, rehearse, then publish.** Freeze the source
revision first. Allocate `0.4.0a2` only against that frozen revision. Build
the artifact once from it. Sign the exact resulting wheel bytes — not a
recomputed hash, not a rebuild. Commit the `CandidateArtifact.v1` receipt
before any rehearsal consumes it. Rehearse the full admission path against
the committed receipt. Publish only after rehearsal passes. Reordering any
step (for example, signing before the build is final, or publishing before
the receipt is committed) reopens the exact gap this ADR's `NO_RECEIPT`
refusal exists to close.

**3. Installation must fetch and verify the exact artifact, never resolve by
name.** The installer must download the specific wheel file, verify its
digest against the committed `CandidateArtifact.v1`, and install that exact
file. A plain `pip install dotmac-deployment-foundation==0.4.0a2` is
explicitly NOT identity evidence: resolving by name retains no wheel identity,
writing no PEP 610 `direct_url.json` `archive_info`, so
`read_installed_artifact` (`host_source.py`) has nothing to read a digest out
of and refuses by the same `ABSENT` path an editable install already hits.
This is a statement about that INSTALL SHAPE, not about registries: the
approved replacement still obtains the wheel from the registry, but downloads
and verifies the exact file against the committed receipt FIRST, installs that
local file, and only then lets the trusted host workload attest what it
installed.

**4. Editable CI remains refusal-only.** This repository installs
`dotmac-deployment-foundation` with `develop = true`
(root `pyproject.toml`), which is precisely the EDITABLE branch
`read_installed_artifact` refuses (`host_source.py`, the `dir_info.editable`
check) before a receipt is ever consulted — `require_host_source` reads the
installed artifact first and only reaches the `receipt is None` check
afterward. That refusal is correct and this amendment does not soften it,
special-case it, or let a receipt or preverified result bypass it for an
editable checkout. CI here continues to prove refusal, not admission.

**5. First positive admission occurs only inside the protected
artifact-rehearsal workflow.** No admission is exercised on `main`'s ordinary
CI, on a developer's editable checkout, or on any workflow lacking branch
protection and the artifact-install shape decision 3 requires. The first time
`require_host_source` is expected to return a `HostSource` rather than raise
`PreconditionFailed` is inside a dedicated, protected rehearsal workflow that
has built, signed and installed the exact artifact per decisions 2 and 3.
Both mutating executors (`recovery_execution.py` and `engine/run.py`, each
calling `require_host_source(receipt=None)` today) keep refusing everywhere
else.

**6. Platform's dependency on this seam stays in a thin deployment adapter.**
Whatever component in Platform CP eventually supplies a receipt, a verifier
or an installed-artifact reading to Foundation stays confined to a
deployment-specific adapter, outside Platform's core application runtime.
This restates, for Platform's own composition, the same shape the 2026-09-07
"trusted host provenance v2" amendment already requires of Foundation itself:
Platform is transport, never authority, and the adapter that carries evidence
across the boundary must not become a second copy of the decision logic on
either side of it.

**Refusal ownership.** The four documented v2 refusal families are not
interchangeable and are not all Foundation's to fix. A same-author or
mismatched-artifact refusal belongs to the Foundation verifier itself. A
wrong-host refusal belongs to the Foundation verifier operating on
Control-resolved host identity — Foundation never resolves host identity on
its own. A revoked-key refusal belongs to Control's enrolment/trust-root
state, not to anything Foundation holds. A replay refusal belongs to
Control's atomic challenge consumption. Foundation's verifier is
INTENTIONALLY stateless (this ADR's amendment of 2026-09-07,
"trusted host provenance v2 custody contract is held, not admitted" — atomic
replay consumption is future Control/admission ownership, not this stateless
verifier), so it must never be expected to refuse a replay on a second call:
a verifier that held consumption state would become a second, weaker copy of
the cut-off that Control alone owns.

**Attestations are verifier inputs; the resulting admission trace is output
only.** The candidate and host attestations are INPUTS to verification — that
is what they are for. What must never become a second authorization input is
the verified admission TRACE: a successful admission adds non-secret
coordinates to the deployment outcome —
the candidate-subject digest, the host observation identity, the host
identity, and signer fingerprints/root versions — without that report
becoming another authorization input for a later admission. Today
`self._host_source` is written by both executors and read by nothing
(`recovery_execution.py`, `engine/run.py`), so the gate currently leaves no
trace of its own decision. Closing that gap — wiring the admission report
into whatever consumes deployment evidence — is a separate obligation this
amendment records and does not implement.

- It does not authorize a production deployment, a host, or an SSH session.
- It does not name a target for any environment.
- It does not retire any product's existing deployment path. Retirement is a
  separate change per product, gated on proven parity.

## Amendment — 2026-09-17: typed Compose topology for deployment assets

Platform CP's production Compose topology requires separate front/back
networks, profile-gated support jobs, named volumes, a repository-sourced
initialization script, and a host-held signing-material mount. A generic
single-network render silently drops those facts; a hand-written Compose file
beside it would preserve a second deployment writer. `ProductDeploymentSpec.v3`
therefore makes topology an explicit, digest-covered descriptor field. It
requires a placement for every rendered runtime role, managed dependency,
migration service and collector; it names networks and mounts through typed
fields rather than accepting arbitrary Compose YAML. Host and repository bind
mounts carry justification and a named approver. The host provider rechecks
repository confinement, descriptor-bound repository file hashes, and
host-material paths immediately before mutation. Repository-source binds are
read-only; a container cannot rewrite the file whose digest was admitted.

A deploy-time support job is profile-gated, uses an exact dependency image,
has a bounded timeout, executes under the normal deployment lock, and has an
explicit command and exact-output postcondition. Its output is not included
in deployment failure records. A support job cannot receive the migration
owner material through either its environment or a mount. Runtime roles may
omit an implicit Compose
dependency on `migrate` only when the migration service is profile-gated;
Foundation's migration plan remains the DDL authority. V1 and V2 canonical
documents and rendering are unchanged by an absent V3 field. V3 inherits V2's
database-catalog binding, not V1's sidecar-only limitation.

This amendment describes an implementation path, not proof of adoption.
For V3, the host provider requires a retained Compose file and its recorded
SHA-256, checks those bytes against the descriptor's deterministic render, and
installs the retained bytes. Candidate operations use a short-lived private
copy of those verified bytes, not the previous release's on-disk Compose file.
This local path-and-digest pair is not itself a release receipt or proof that
CI retained the bytes; the Platform CP release producer and Control binding
must supply that provenance before adoption.
It refuses to synthesize rollback configuration
from the candidate descriptor; a previous-release asset and separate
authorization are still needed for a proven rollback.
The V3 plan itself therefore reports rollback as unavailable even when the
migration is online and a previous image digest is known. The old image is
insufficient to reconstruct the old topology; this refusal must be lifted only
with a typed, release-receipted old asset and its own rollback authorization.
Platform CP's accepted descriptor, source/render hashes, host asset,
authorization binding, rehearsed rollback, and old-writer retirement require
separate evidence before any full cutover can be claimed. No deployment or
release is authorized by the V3 schema alone.

## Amendment — 2026-09-19: Platform CP topology admission boundary

The CP-shaped V3 diagnostic fixture models structural features observed at
`dotmac_platform_control_plane` commit
`1524580f43549a5804134131d4d9ed3b2237edef`: separate app, platform and
relay-dispatcher credentials; a backend-only relay without a misleading
container healthcheck; both first-cluster PostgreSQL init mounts; the
network-isolated manifest initializer with exact owner and mode verification;
read-only app/relay and read-write ops manifest mounts; and the one-shot
Foundation migration owner. Its image and mounted-source bytes are synthetic;
it is not a render of CP's accepted descriptor. V3's explicit `command = []`
on a role inherits the exact-digest image's default CMD and omits Compose's
`command`; an absent key still refuses, and V1/V2 still require a nonempty
array. This keeps CP's container-local bind address in its pinned image, not
as a host-address literal in the signed deployment descriptor. Existing
nonempty-command V3 canonical documents gain no field or changed bytes. CP
still uses one `ops` service with the migration credential, whereas V3 renders
a separate migration service that alone holds the owner material. That split
remains an adoption decision, not a proven equivalence.
The relay's existing `dotmac-platform relay health`
CLI exits successfully even for an unhealthy verdict, so a Foundation worker
ping must check its machine-readable `data.verdict` for `relay_draining` rather
than trust the CLI exit status alone. A fixture demonstrates that contract; CP's
accepted product descriptor has not yet adopted it.

Foundation runs deploy-time support jobs **after a verified backup and before
migration preflight**. CP's current script runs `manifest-init` before backup.
The existing Foundation order remains the safety boundary: no generic job is
authorized to mutate a volume before the snapshot. CP must reconcile this
order in its adoption workflow, or a separate narrowly typed volume-init
contract with its own containment proof must be reviewed before changing the
Foundation plan. A render test is not evidence that CP's workflow consumes the
retained bytes, that its descriptor is accepted, or that a release/cutover has
occurred.

Michael approved the adoption direction on 2026-09-19: Platform CP will move
manifest initialization after the verified backup and use Foundation's
separate one-shot migration service as the sole DDL owner. This is a contract
for the subsequent CP adoption change, not a claim that CP's current script or
descriptor has already changed. A pre-backup mutation path is not part of this
Foundation source slice.

## Amendment — 2026-09-20: the admission-provider seam is wired, real admission is not

`host_source_admission.py` adds `HostSourceAdmissionProvider`, a Protocol
with one argument-free method, `admit_host_source()`, and
`RefusingHostSourceAdmissionProvider`, the shipped reference implementation
that delegates to `require_host_source(receipt=None)` and therefore always
refuses. `engine/run.py`'s `Executor` and `recovery_execution.py`'s
`RecoveryExecutor` each now accept the provider as a keyword-only
constructor parameter, defaulting to `RefusingHostSourceAdmissionProvider`,
and each class's `_verify_host_source` calls
`self._admission_provider.admit_host_source()` fresh on every `run`/
`rollback` invocation rather than caching a result across calls on the same
instance.

The provider is HANDED OVER at construction, the same rule this ADR and
`host_source_admission.py` already apply to every other host-source
ingredient (`recovery_receipts`, `evidence_policy`, `evidence_verifier`):
Foundation owns no installation mechanism of its own, and there is no
ambient registry, module-level global, or discovery path either executor
consults instead. An executor that went looking for a provider could not
distinguish "no provider was installed" from "the wrong provider was
installed", and a mutating executor is exactly where that distinction has
to stay visible at the call site. Argument-free is deliberate on the
Protocol method itself: a real provider implementation reaches Control and
evidence entirely inside its own method body, so this amendment does not
invent a request/context parameter schema for Control before Control has
one.

The one implementation this package ships, `RefusingHostSourceAdmissionProvider`,
reproduces the prior unconditional refusal byte-for-byte — same typed
codes (`ABSENT`/`WRONG_KIND`/`NO_RECEIPT`), zero effects — so a caller
supplying no provider observes no behavior change from before this seam
existed. A REAL provider, one that actually reaches Control's trust-root,
revocation, and replay-consumption state and Foundation's own
attestation-verification seam (`admit_host_source()`, `verify_attestation_pair()`,
`verify_candidate_attestation()`) to produce a genuinely admitted
`HostSource`, remains separate, later, cross-repo work. This amendment
records the seam a provider is handed through, not a claim that real
admission works end-to-end.

### Correction, 2026-09-20: a provider protocol does not prove its provider

The constructor parameter is a trusted-composition extension point, not a
new security boundary. An in-process caller can supply a structurally valid
provider that returns invented `HostSource` and trace values without ever
calling `admit_host_source()` or Control. The synthetic accepting provider in
unit tests demonstrates this reachability; those tests prove executor and
recovery sequencing only, not trusted provenance. This corrects the preceding
amendment wherever "provider" could be read as "verified provider".

The installed `dotmac-deploy` CLI currently passes no admission provider to
any of its three direct mutating executor construction sites. A
sensitivity-tested architecture guard checks those sites and rejects explicit
`admission_provider=` or dynamic keyword expansion anywhere in that CLI; it
does not prove a future indirect factory safe. It also does not cover an
external embedder or Platform CP. Before either may pass a positive provider,
the assembly must fix its selection at trusted installation/startup, prove
that requests and operators cannot replace it, and obtain fresh authenticated
Control trust-root/revocation, enrolled-host identity and replay-consumption
state for each invocation. Absence or failure refuses before effects. A
real positive admission still belongs first in the protected exact-wheel
artifact rehearsal; neither a passing unit test nor this PR retires that gate.

## Amendment — 2026-09-22: three distinct immutable candidate-provenance artifacts, and the record/signing order they fix

Decision 2 of the 2026-09-08 amendment ("six admission decisions") states the
ordering as "build once, sign the exact bytes, commit the receipt, rehearse,
then publish" — one word, "receipt", carrying two different meanings across
that sentence and the paragraph following it: `CandidateArtifact.v1`
(decision 1's committed, non-authorizing binding of source revision,
wheel/sdist digest, build run and artifact IDs) and whatever record binds a
SIGNED envelope back to that artifact. Read literally, the sentence orders
signing before any commit — which, followed literally, would let a signer
produce a signed envelope against bytes nobody has yet durably recorded,
reopening exactly the non-repudiation gap `CandidateArtifact.v1` exists to
close: a record built or adjusted AFTER signing can always be made to agree
with whatever was signed. `scripts/candidate_attestation_signer.py` already
implements the correct order in practice — it "reads an already-committed-shape
`CandidateArtifact.v1` receipt" and signs from it, never the reverse — but the
ADR text never stated that as a rule, and never named the POST-sign record as
its own distinct type. This amendment corrects both omissions.

**Three artifacts, not two, each immutable and append-only, each with a
single writer:**

1. **`CandidateArtifact.v1`** — committed FIRST, before any signature exists.
   Non-authorizing (decision 1: it shapes how admission is eventually built,
   it does not itself admit anything). Binds source revision, the final
   wheel/sdist digest(s), the build run ID and artifact ID, and an expiry.
   Written once, by the build workflow, from the exact bytes the build
   produced — never recomputed by a later re-hash, re-read, or a fresh API
   call (already decision 2's own rule; restated here because it is the
   property the ordering fix depends on). A `CandidateArtifact.v1` record is
   never edited after it is committed.

2. **The signed candidate-attestation envelope** (`TrustedHostAttestation.v2`,
   already specified by the 2026-09-07 "trusted host provenance v2" amendment)
   — produced only AFTER verifying that a committed `CandidateArtifact.v1`
   record exists and that the artifact being signed matches it exactly (same
   digest, same run and artifact IDs). The signer never signs from a fresh
   build, a fresh hash, or an unrecorded artifact; it signs from the committed
   record and nothing else. This is decision 2's "sign the exact bytes"
   restated with its precondition made explicit: the bytes being signed are
   the bytes the ALREADY-COMMITTED record names, not bytes the signer
   independently trusts.

3. **`CandidateAttestationReceipt.v1`** — committed AFTER the signed envelope
   exists, in the SAME reviewed commit that lands the envelope itself (the
   shape `scripts/candidate_attestation_signer.py`'s own docstring already
   describes: "A human commits the signed envelope (and the bound receipt)
   under `docs/inventories/` in a follow-up, reviewed change" — this
   amendment names the vocabulary that docstring already assumed). It binds,
   BY VALUE, never by path alone:
   - the committed `CandidateArtifact.v1` record's revision identifier and
     the canonical SHA-256 of the record's OWN bytes (not the wheel digest
     the record itself names);
   - the signed envelope's own canonical SHA-256 and the immutable artifact
     coordinate (`CandidateArtifact.v1`'s build run ID and artifact ID) it
     was produced from;
   - the candidate's facility name and version;
   - the identity of the one process that wrote it — the protected Starter
     release-workflow signing step, the same identity decision 1 names as
     the signer, and the ONLY writer this record ever has.

   A record naming a FILE PATH to the artifact record or the envelope,
   without also carrying that record's or envelope's own canonical digest,
   is not a binding: a path can be repointed at a different file without
   changing the receipt, a digest cannot. Duplicating the envelope's own
   already-signed fields (package, version, wheel digest) without ALSO
   carrying `CandidateArtifact.v1`'s OWN canonical digest closes nothing
   either — that leaves no verifiable link back to the specific committed
   record the signer actually read, only to facts the envelope already
   separately asserts about itself. Without both digests present, a reader
   cannot distinguish "this envelope was signed from this exact committed
   record" from "this envelope happens to name the same package and version
   as some record." This is the type the ADR text previously left unnamed.
   It exists so a reader (or a later admission decision) can answer "which
   committed artifact record does this signed envelope attest to" from a
   durable, append-only pointer, rather than from the signer's own
   now-unverifiable claim or from re-deriving the binding out-of-band.
   Foundation's existing 2026-09-07 "successor Control receipt is a
   Foundation value, not admission" amendment already establishes the
   pattern of Foundation retaining a minimal, import-free consumer receipt
   after cross-validating separately signed documents;
   `CandidateAttestationReceipt.v1` is the SAME shape of thing, one step
   earlier in the pipeline, for the candidate's own signed envelope rather
   than for Control's authorization pair.

**The fixed order, restated precisely**: freeze source → allocate → build once
→ commit `CandidateArtifact.v1` → sign the exact recorded bytes → commit
`CandidateAttestationReceipt.v1` → rehearse → publish. Reordering any step —
signing before the artifact record is committed, committing the receipt before
the envelope is actually signed, or rehearsing/publishing against anything
other than the exact bytes both records name — reopens the same gap decision
2 already named and this amendment now makes unambiguous.

**Three distinct revisions, not one.** "Freeze source" — the first step of
the fixed order — fixes the CANDIDATE SOURCE REVISION: the exact commit of
`packages/dotmac-deployment-foundation` the build was taken from. Neither the
`CandidateArtifact.v1` record's own commit, nor the
`CandidateAttestationReceipt.v1` commit that lands afterward, IS that source
revision, and neither is required to be — they are evidence ABOUT a frozen
source revision, committed later, in the starter monorepo's own history, not
inside the facility's source tree itself. A later evidence commit (fixing a
typo in the receipt, recording a rehearsal result, or any change that does
not touch `packages/dotmac-deployment-foundation` itself) does NOT by itself
spend the candidate. What spends it is a change to the FACILITY SOURCE TREE
or its declared version under the same candidate identity: if
`packages/dotmac-deployment-foundation`'s tree, or its `pyproject.toml`
version, no longer matches the frozen source revision `CandidateArtifact.v1`
names, the candidate is spent — full stop, regardless of how many or how few
evidence commits followed it. Unrelated evidence, runner, or documentation
commits elsewhere in the monorepo never spend a candidate on their own.

**A failed or drifted candidate is spent.** If a build fails, if the recorded
digest does not match what actually got produced, or if a `CandidateArtifact.v1`
record is found to disagree with the bytes it names at any later check, that
candidate identity is spent: no `CandidateAttestationReceipt.v1` may bind to
it, and the version it was allocated against is never reused (the existing
rule that `0.4.0a1` remains "spent/drifted" and must never be reused for a
real release is this same rule, applied once already, ahead of it being
written down as a general one here). A fresh attempt allocates a fresh
version and starts a fresh `CandidateArtifact.v1`, never resurrects a spent
one.

**Records are append-only, and a correction is never a same-identity
replacement.** None of the three artifacts is ever edited in place once
committed. A DEFECT discovered in a committed record — the build failed, a
digest was wrong, rehearsal found a mismatch — is recorded as an APPENDED
DISPOSITION: a new, separate record marking the existing
`CandidateArtifact.v1` (and any `CandidateAttestationReceipt.v1` bound to it)
spent, stating why. It is never a corrected `CandidateArtifact.v1` committed
under the same candidate version — that would be exactly the same-identity
edit this rule forbids, only routed through a second record instead of an
in-place rewrite. A REPLACEMENT candidate — one meant to actually supersede
the defective one and proceed to rehearsal and publication — requires a
NEWLY ALLOCATED version and starts its own fresh `CandidateArtifact.v1`, per
"a failed or drifted candidate is spent" above; it does not reference the
spent record as something it supersedes, because a provenance record is
never superseded under its own identity, only disposed of and left in place.
The general append-only discipline this restates is the same one
`AGENTS.md` rule 34 already requires of a published connector manifest,
applied here to a candidate's own provenance chain before it ever reaches
publication.

**Publication may use only the exact rehearsed bytes.** The artifact that is
eventually published must be bit-for-bit the same artifact the committed
`CandidateArtifact.v1` names, the same artifact the signed envelope attests to,
and the same artifact the protected rehearsal workflow (decision 5) actually
exercised — never a rebuild, even an ostensibly-identical one. This restates
decision 2's ordering as an invariant that holds continuously from commit
through publication, not only at the moment each record is written.

This amendment resolves the record/signing ordering conflict only. It does
not allocate a Foundation successor version, does not build or sign a real
`0.4.0a2` candidate, does not activate a production rehearsal issuer, and does
not change `dotmac-deployment-control`'s pin. Those remain separately gated —
Gate 0 (the protected disposable rehearsal-issuer contract, including
ADR-0013 A6.4 immutable-reference derivation, signer custody, lease and
controller identity) and Gate 1 (real CP `build_trust_policy` binding,
applicable follow-ups closed before that binding becomes reachable,
replay/refusal proof, Lane 3 runner capability, and the real ten-step recovery
and roles-fail/objects-succeed adjudication test) must both be reviewed and
green before a successor is allocated at all, and `0.4.0a1` remains spent and
is never reused.

## Amendment — 2026-09-25: first executor cutover is Control Plane bootstrap

The original Consequences section names ERP as the first full adopter. For
executor cutover, that sequence is narrowed: `dotmac_platform_control_plane`
is the first Foundation executor cutover and control-plane bootstrap. It must
compose Control's authenticated host admission, current execution standing,
single-use dispatch consumption and commit-before-effect boundary before a
data-plane product can depend on that authority. ERP remains the first **full
data-plane adopter**, after that bootstrap; its existing exact pin, descriptor
inputs and CI conformance are not proof that its deployment executor has been
replaced. This amendment records ordering only. It does not claim either
product has completed executor cutover, production adoption or retirement of
its prior execution path.

## Amendment — 2026-10-05: Lane 3 executes from organization-owned, workflow-restricted, ephemeral runners

**Decision (Michael Ayoade, 2026-10-05).** Lane 3 leaves the personal-account
Starter repository's self-hosted runner. It runs from an organization-owned
execution repository, through a runner group restricted to that repository and
to one ref-pinned workflow, behind a protected Environment, on ephemeral
just-in-time runners. Topology and credentials are delivered privately at run
time. Static Lane 3 credentials and the personal runner are retired. The
rehearsal oracle that `release-facility.yml` reads is amended to match. The
design, its proposed coordinates and its admission evidence are in
[`docs/LANE3_EXECUTION_TOPOLOGY.md`](../LANE3_EXECUTION_TOPOLOGY.md).

**Why.** Starter is a public, personal-account repository. A runner label
routes a job but does not restrict which workflow may use the runner, and
workflow-restricted runner groups exist only for organizations. A public
repository's variables, dispatch inputs, logs and artifacts are public. The
current lane therefore cannot hold private vantage topology or static keys on
its runner, which is the unresolved private-delivery row that Platform CP's
Gate-0 D spec (§ 8) assigns to Starter/Foundation infrastructure under CP
ADR-0013 § A7.6. The public GitHub Free topology that CP adopted for Gate 0
(spec § 11) is the precedent. Lane 3 mirrors it with a **separate** group, CA
and base image, because Gate 0 is forbidden to connect to a target and Lane 3
exists to do so.

**What does not change.** Lane 3 still executes the digest-verified candidate
wheel resolved from the committed `CandidateArtifact.v1` (rule 44). The
launcher runs an exact Starter protected-`main` revision's own runner, never a
copy. Publication still requires two oracles, newest-then-check selection,
sixteen `executed_passed` rows and the existing three-revision ancestry
ruling. No `ExecutionGrant` is created, widened or substituted by this
topology (rule 51).

**What changes when D-S2 lands, and not before.**
- The run population becomes the pinned execution workflow's
  `workflow_dispatch` runs on `main`, identified by an immutable repository ID
  checked into Starter.
- The Starter revision is tied to a run through a dispatch grammar that the
  launcher refuses before checkout, and bound by the receipt's
  `foundation_revision` from the launcher's verified checkout.
- The selected run's launcher revision, runner group and Environment approval
  are checked.
- The receipt is fetched from exactly that run and must bind that run's
  identity.

Until the admission evidence exists, the amended oracle refuses. `AGENTS.md`
rule 44's statement that the Starter run's `head_sha` is the protected-main
oracle is amended in that same change.

**A Foundation prerequisite this creates.** Receipts must carry opaque
identifiers instead of target and probe addresses, and must bind the
producing run. That is a change to Foundation's receipt contract, so it must
land in Foundation source **before the Gate-2 freeze** (rule 48). Foundation
chooses an additive v1 field or a v2 schema.

**Not decided here.** Provisioning values and their approval, Gate-3
controller-fingerprint issuance, binding certificate issuance to a Control
lease, and the four Lane 3 runner fixes (D4) are not decided here. This
amendment closes neither Packet D nor any gate.
