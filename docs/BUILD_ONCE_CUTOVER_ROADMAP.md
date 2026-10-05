# Build-once cutover roadmap: Foundation → Platform CP → ERP → Sub

- **Status:** Draft execution roadmap, 2026-09-20. Michael Ayoade owns go/no-go
  decisions. This document grants no release, host, secret, migration, production
  deployment, or risk-acceptance authority.
- **Baseline:** `dotmac_starter_mt` `d346d94f474088bdaf8b860809a3c425e9410543`;
  Platform CP PR #187 `a514c41c8552301b69a486ef231273e38719ed76`;
  local CP ADR-0017 amendment `2fead5f` (not pushed). Refresh these coordinates
  before acting. Repository documents do not establish current host state.
- **Owning contracts:** Starter [ADR-0070](adr/0070-deployment-is-a-stateless-versioned-foundation.md),
  `AGENTS.md` rules 24, 30, 31, 32 and 41; Platform CP ADR-0013 and ADR-0017;
  Governance ADR-0014 § 6. This roadmap orders work; it does not amend those
  contracts. A conflict is a stop requiring an owning ADR amendment.

**Execution decision:** close the issuer contract and source/runner readiness
(gates 0–1) now, then build one successor and rehearse it before publication.
Do not deploy the currently refusing CP issuer, repin #187 for appearance, or
allocate another candidate while its proof path is not ready. The next review
should ask which gate's refusal was removed and where its evidence lives.

## Outcome, not activity

The first programme cutover is **not** a Foundation pin, a green render, an
issuer deployment, a published wheel, or one signed receipt. It is Platform CP
executing a deployment and a redeployment through the admitted Foundation path,
proving recovery and the authorized read-backs, then retiring or positively
fencing its former deployment executor with a product retirement receipt. The
two runs must be controller-owned and distinguishable; a rehearsal against a
disposable target is a publication gate, not that production adoption.

After the CP control-plane path is proved, ERP takes the first full data-plane
adoption slice, then Sub. Each product owns its own exact pin, retained assets,
rehearsal, switch and old-writer retirement. No neighbour's receipt proves its
adoption. ERP and Sub do not wait to inventory their sources, but neither may
claim a cutover from CP's evidence.

The original ADR-0070 consequence calls **ERP the first full adopter**. The
current programme queues CP first. This roadmap interprets CP as the required
control-plane bootstrap and first executor cutover, and ERP as the first full
data-plane adopter. Before anyone describes CP as the first *full* adopter,
Michael must settle that wording in ADR-0070; this roadmap cannot silently
reverse an accepted ADR.

## Measured starting line

| Surface | Evidence at the baseline | Consequence |
| --- | --- | --- |
| Foundation candidate | `pyproject.toml` declares `0.4.0a1`; `tests/architecture/candidate_window_baseline.json` records artifact `9954731961` as `unrecorded` and `drifted`. No successor is allocated. | `0.4.0a1` is spent. Never relabel, rebuild, publish, or rehearse it as a fresh candidate. |
| CP topology | Starter PR #723 merged a CP-shaped V3 diagnostic fixture, not an accepted CP descriptor or consuming deploy workflow. CP #188 merged backup-first ordering. | Finish the production input/consumer separately; source parity is not adoption. |
| CP PR #187 | Draft at `a514c41`: `check`, `kernel-pin`, `image`, `postgres` and Governance-pin succeed; Engineering Standards fails on schema-11 `deployment_artefact_surfaces`. Five module pins are validation only; kernel a101 remains admitted. | Do not merge, declare adoption, or bump to a104 for appearance. |
| CP issuer | The generated Lane 3 status records no authorization run ID and **0/16** `executed_passed`. PR #187's `deployment propose` and `deployment authorize` deliberately refuse pending an immutable Foundation candidate and custody-approved signer; current production workflow only format-checks `authorization_ref`. | Deploying these source bytes cannot issue the needed authorization. Source composition and live issuer admission are separate gates. |
| CP bootstrap | CP's checked-in descriptor-reconciliation evidence says the single-use persistence bootstrap already ran; ADR-0013 prohibits replacing the application during bootstrap and requires later bootstrap-call-site retirement. | Reconcile that receipt and define the production issuer's in-place activation; do not assume the one-time operation can be replayed. |
| Foundation admission/recovery | `IntegrationSurfaceAbsenceProofV1` and 13 concern slots exist. Starter #735 (`8404473c`) proves the generic verifier for every slot with distinct **synthetic** positive, missing-implementation and wrong-version cases; concrete assembly bindings are not proven. Starter #737 (`d346d94f`) adds `admit_host_source` for a verified candidate/installed-host attestation pair and interpreter reading, but its trace has no consumer and neither mutating executor calls it. `RecoveryExecutor.run::real-ten-step-sequence` remains open; both executors still call `require_host_source(receipt=None)`. | Generic slot verification and the pure admission seam are real progress, not evidence of a trusted mutating execution or real recovery. |
| Lane 3 | `docs/inventories/deployment-exposure-rehearsal-status.md` says 0/16, with hand measurements, blocked, unexecuted and vacuous rows. | Publication requires a real receipt with **16/16 `executed_passed`**, not a converted tally or a shell transcript. |

The status row is a dated repository observation. Before a production action,
the responsible operator re-reads the live source revision, CI, release
coordinates and named host; the table is not a substitute for those oracles.

## The one critical path

Each gate below has an owner, an artifact and a refusal. **A gate advances only
when its evidence is addressable by immutable coordinates and the owning check
accepts it.** Source PRs may run in parallel; the irreversible candidate and
production steps stay serial.

| Gate | Owner and next deliverable | Pass evidence | Stop / authority boundary |
| --- | --- | --- | --- |
| **0. Settle the bootstrap contracts** | CP + Control + Foundation: review the pre-publication rehearsal issuer, immutable candidate reference, custody-approved signer, lease and controller identity. Specify how the five ADR-0013 A6.4 plan inputs are derived without an operator-supplied image. Reconcile the existing single-use persistence-bootstrap receipt with the no-application-replacement rule. | Accepted design and source-level refusal tests for wrong candidate, signer, target, profile, image and plan; protected rehearsal workflow prepared. The issuer path must be implementable once a candidate exists, but cannot produce a candidate-bound authorization yet. | PR #187's current refusal is honest. Do not patch around it with flags, a free-text `authorization_ref` or a fake receipt. Recommend a protected disposable issuer for rehearsal only; production issuer activation remains a separate gate. Any departure from ADR-0013 needs its owner's amendment, not just host approval. |
| **1. Make source and runner ready** | Foundation wires trusted candidate + installed-host admission through both executors; prepares concrete assembly binding and absence-evidence collection for the declared concerns beyond #735's synthetic verifier tests; fixes recovery's per-step adjudication; prepares a protected, real ten-step recovery and Lane 3 runner. Control prepares enrolment/revocation, challenge and signed authorization/grant semantics. | Source-level negative tests for same-author, wrong-artifact, wrong-host, revoked-key, replay and `receipt=None`; a `Lane3RunnerCapability.v1` check proves the runner can produce the required evidence before allocation. Positive candidate admission and live ten-step recovery are **not** claimed at this gate. | `_do_restore_objects` currently overwrites `outcome.attempt` from `_do_restore_roles` before adjudication: add roles-fail/objects-succeed refusal. No second CP renderer or Control decision engine. Do not require a candidate-bound proof before the candidate exists. |
| **2. Freeze and build one successor** | Starter release captain freezes an exact protected-main source revision, disposes of spent `0.4.0a1`, allocates fresh `0.4.0a2`, and builds wheel and sdist once. Follow the record/signing order fixed by ADR-0070's 2026-09-22 amendment ("three distinct immutable candidate-provenance artifacts, and the record/signing order they fix"), which resolved the earlier conflict between ADR-0070's “sign, then commit receipt” wording and `foundation-candidate-attestation.yml`'s requirement for an **already committed** `CandidateArtifact.v1`; keep that artifact record distinct from the later signed attestation. | Protected candidate run; committed artifact record with source, wheel/sdist digests, run/artifact IDs and observed expiry; exact bytes re-fetched and verified with the required 30-day retention margin; independent signed envelope and its reviewed record at the sequence the reconciled contract requires. | **Not published or tagged yet.** Missing/expired artifacts or source-tree drift under the same version spend the candidate; disposition and a new version are required. An evidence-only main commit does not automatically void the window. Release-ancestry and freeze guards must still pass. Do not allocate before issuer design and runner readiness are reviewed. |
| **3. Authorize and rehearse exact bytes before publication** | After gate 2 has produced the one exact artifact, CP/Control activate the gate-0 **rehearsal** issuer on a specifically authorized disposable target. Foundation issues and validates its candidate-bound `ExecutionGrant`, binding the exact gate-2 artifact bytes, rendered plan, target/host and controller identity before any executor or Lane-3 action. Foundation installs that wheel as an exact verified file, never a name-only resolution, then exercises candidate/host admission, real ten-step recovery and Lane 3 with the lease, controller identity and actual source-set probes. Retain the Lane 3 receipt as its workflow artifact; do not move the release revision after that run. | The accepted Foundation `ExecutionGrant` coordinate and issuer authorization run ID; signed candidate/host and recovery receipts; Lane 3 `RehearsalReceipt.v1` with **16/16 `executed_passed`**, including provoked rollback and non-vacuous running-service negatives. The grant and rehearsal run bind the **later release revision** that contains the committed candidate record; that revision separately binds the candidate source tree and artifact digest. | Human names the exact SSH endpoint and action before host work. `vendor-cp-prod` is a logical host ID, not an inferred SSH target. A rehearsal issuer's identity and Control's authorization to operate it are not Foundation execution authority; no executor starts until the `ExecutionGrant` is accepted. No positive admission on editable CI or ordinary main. |
| **4. Publish the rehearsed candidate** | Starter release captain publishes the **same wheel and sdist bytes** from the rehearsed candidate, reads them back from the registry, verifies digests, tags and merges the truthful release record under the short named freeze. | Protected release run, immutable tag/peeled candidate-source commit, registry read-back, install-back of exact files and green release-record main. The release workflow separately checks candidate source, release revision and rehearsal-runner revision. | No rebuild, mutable tag, name-only install, skipped gate, or use of the spent a1 artifact. Publication still does not transfer a product executor. |
| **5. Land CP's consuming source** | CP implements ADR-0017's concrete design only with Michael's separate implementation go-ahead and the topology-complete published Foundation pin. First, pre-merge CI renders and byte-compares the effective `docker-compose.production.yml` **without authorization or an independent image slot**. Reconcile #187 and schema 11. After merge, publish a CP image and verify its release receipt and registry read-back; only then derive `admit_candidate_image` and let Control bind that image, retained render, private inventory, target and approval. | Required hosted checks green at the final PR head; retained asset hash and consuming workflow; negative tests for edited bytes, `COMPOSE_FILE` diversion, image injection, wrong authorized inputs and missing receipted rollback asset. Accepted descriptors remain until their specified successful migration/runtime promotion. | A green render is neither image admission nor Control authorization. #187 stays draft until its real Governance gate is green. Do not let a pre-merge candidate authorize production or retroactively mutate `deploy/product.toml` or its ledger. |
| **6. Activate production issuer; execute and retire CP** | On Michael's exact production-host authorization, activate the **production** issuer with approved invocation, signer custody, persistence and authorization path **without application replacement**. CP then performs an authorized Foundation deployment **and redeployment**, verifies image/profile/catalog/asset and runtime read-backs, proves recovery and observes the displacement window. Retire direct-Compose **and** the bootstrap mutation path. | Production issuer admission; two distinct controller-owned deploy-run IDs and signed receipts, including the CP-authorized second-deployment oracle and image digest; bootstrap receipt supersession, checked-in launcher/call-site deletion to zero, old-executor zero-surface proof and product retirement receipt. | Reconcile the already-run single-use bootstrap; never replay it by assumption. A rollback needs a separately receipted previous asset and authorization; V3 currently reports it unavailable. If either ordinary or bootstrap legacy path can still write, cutover is not complete. |
| **7. Repeat by product** | ERP, then Sub: each chooses a coherent legacy-executor slice, makes its own descriptor/asset/authorization binding, rehearses its topology, executes and retires its writer. | Product-local deploy/redeploy, recovery, observation and retirement receipts. | CP evidence cannot close ERP or Sub debt. ERP's finance/data cutover obligations remain separately gated. |

### Parallel work that starts now

1. **CP/Control authority PRs:** prepare `propose` and `authorize` for
   immutable-candidate derivation and custody-approved signing; implement A6.4
   reference resolution and its negative tests. Candidate-bound success is
   proven at gate 3, after a real artifact exists. Do not merge a
   raw-image or operator-shaped authorization escape. CP ADR-0017's accepted
   *concept* should be pushed as a docs-only PR when GitHub write is authorized.
2. **Foundation PRs:** trusted-provenance consumption in both executors;
   concrete assembly binding/evidence beyond #735's synthetic slot tests;
   restore-attempt overwrite repair and real ten-step recovery runner; Lane 3 capability and runner fixes
   whose retained evidence, not merely a pass counter, proves all sixteen
   subjects at gate 3.
3. **Evidence and operations:** reconcile the CP bootstrap runbook with ADR-0013
   (already-run one-time in-place operation; no app replacement during
   bootstrap); inventory egress, PostgreSQL, verified backup/restore, signing custody, lease,
   controller and host-engine versions. This is read-only preparation until
   Michael names and authorizes an exact host. Prepare the old-executor
   retirement diff before, not after, the production switch.

These lanes meet at gate 2. A ninth unrelated merge or another pin-only PR
does not move this roadmap. Every work item must name the gate, its before/after
evidence and the refusal it removes.

## Decision and evidence discipline

- **Now:** Michael decides whether the pre-publication rehearsal uses a
  protected disposable CP issuer (recommended) or whether a production
  in-place issuer is contractually necessary. That decision must identify the
  signer/trust domain and the distinction between rehearsal and production
  authorization. Michael ratified the complete CP ADR-0013 A6 amendment,
  including A6.4's replacement immutable-reference rule, on 2026-09-25. The
  ADR-0070 versus
  attestation-workflow ordering conflict has since been resolved by ADR-0070's
  2026-09-22 amendment. None of these decisions authorizes SSH or deployment.
- **Before host work:** Michael supplies the exact SSH endpoint, environment,
  action and scope. ADR-0013 names `vendor-cp-prod` as a logical target; a
  historical address in a runbook is not current permission. No broad Docker
  run is inferred from approval of a read-only preflight.
- **Before allocation/publication:** Starter's release captain records the
  exact source, candidate coordinates, disposition, freeze and normal release
  checks. The release policy in `AGENTS.md` rule 31 is machine-authorized on
  protected `main`; production deployment remains a separate human gate.
- **Before calling any gate closed:** update this roadmap with an immutable
  receipt/run/commit coordinate and the owning check that accepted it. Do not
  replace `blocked` with `passed` on a prose assertion, a local green test,
  or an agent's risk acceptance. Reconcile the canonical debt register and
  product cutover record in the same change.

The immediate executable package is therefore **gates 0–1's contract and
source-readiness PRs** (the signing-order conflict has since been resolved by
ADR-0070's 2026-09-22 amendment)—not an issuer deployment or a new Foundation
build. The next joint checkpoint is a
reviewed rehearsal-issuer design, a capable Lane 3 runner and a protected
Foundation source tree whose admission and recovery paths can be exercised
against one exact built candidate. Only then does the short, irreversible
candidate window begin.

## Update, 2026-09-24 — Gate 0/1's mechanism half is proven; the authority
## contract (Work Packet A) is ratified

**This section is a dated observation, not a rewrite of the plan above** —
the gate table and its evidence discipline stand. This records what actually
closed since the 2026-09-20 baseline and reconciles this roadmap's 0–7 gate
numbering with the simpler three-gate framing Michael has since used when
directing this exact work, so nobody mistakes two numbering schemes for two
plans.

### Refreshed baseline

Superseding the § "Baseline" coordinates above (re-verify before acting, per
that section's own instruction): Platform CP `main`
`c80415fa6837b2f2c9ebb4755d5a0b3f9fbf55f3`; Starter `main`
`96780a9fd30f33b468bdcc1af3a5001d2026beec`; `dotmac_deployment_control` `main`
`a3b7f9d64f92529e2f3ce7f77da12af38165c602`, publishing `dotmac-deployment-control`
`0.1.0a14` — independently verified published, tagged, and pinnable, not
merely declared. CP PR #187 is superseded by this baseline; #193 (the full
Control-a14/Kernel-a101 application rewrite) remains HELD, uncommitted,
locally at `/private/tmp/cp1-rehearsal-issuer-composition-20260923`.

### Reconciling the two gate numberings

Michael's own recent framing (Gate 0 → Gate 2 → Gate 3) is the SAME sequence
this roadmap's Gates 0–3 describe, at coarser grain — it folds this roadmap's
Gates 0 and 1 into one "protected issuer readiness" gate, and keeps this
roadmap's Gates 2 and 3 as-is:

| Michael's gate | This roadmap's gate(s) | Status as of this update |
| --- | --- | --- |
| **Gate 0** — protected issuer readiness | Gates 0 ("Settle the bootstrap contracts") + 1 ("Make source and runner ready") | MECHANISM half proven (below); PROTECTED-COMPOSITION half open (Work Packets A–E) |
| **Gate 2** — allocate/build/sign one successor | Gate 2 ("Freeze and build one successor") | Not started; blocked on Gate 0 closing in full; produces no execution authority and performs no rehearsal |
| **Gate 3** — authorize and rehearse exact bytes | Gate 3 ("Authorize and rehearse exact bytes before publication") | Not started; issues and validates Foundation's candidate-bound `ExecutionGrant` before any executor or Lane-3 action |

Nothing below changes gates 4–7 or their owners.

### What closed: the mechanism half of gates 0–1

Platform CP #194 (a dependency-light, stdlib-only source seam translating a
caller's three fields into Control's exact accepted request shape) and #195
(a disposable, candidate-independent harness proving the real, published
Control `0.1.0a14` wheel — paired with `dotmac-kernel` `0.1.0a100` — genuinely
issues, holds committed standing on, revokes, and single-use-consumes
rehearsal-issuer authority) are both merged. #195's final CI run is real
evidence, not a claim: 16 of 16 tests passed against real migrated
PostgreSQL, with `platform_api` (not the migrator) performing every issuer
operation, matching `docs/ARCHITECTURE.md`'s real production role contract
exactly (`app_admin` stayed `NOCREATEROLE` throughout).

This proves the MECHANISM — Control's real issuance/standing/revocation/
consumption code, called with the real published artifacts, under a
production-shaped privilege model — is sound. It does not close gate 0/1's
protected-composition half: no protected GitHub Environment, no real key
custody, no genuine `dotmac-approvals` decision, and no real per-run
controller identity exist yet (confirmed absent below). Reaching a "16/16"
mechanism proof and reaching "the protected rehearsal issuer may act for a
real approval, under real custody, on a real runner" are different claims,
and this roadmap's own gate-0 pass evidence ("Accepted design and
source-level refusal tests… protected rehearsal workflow prepared") already
named the second, not the first, as what closes the gate.

### What remains: five work packets closing gate 0/1's protected-composition half

Platform CP's `docs/adr/0013-operator-authorization-issuer-and-its-bootstrap.md`
§ A7 is the ratified document-purpose/identity/ownership matrix for these.
It merged as CP PR #196 (`c8ead5a`) with this section as Starter PR #747
(`ead3b8a`), and Michael Ayoade ratified it separately afterwards, on
2026-09-24 ("a is ratified"); the ratification is recorded at the head of
§ A7. That 2026-09-24 record covers § A7 only. Michael separately ratified the
complete CP ADR-0013 A6 amendment, including replacement A6.4, on 2026-09-25;
CP records that later decision at the head of A6. Summary, including Starter's
own stake in each:

| Packet | Owner | Starter's stake |
| --- | --- | --- |
| **A. Authority contract** | CP + Starter docs (this section, plus CP ADR-0013 § A7) | Proposes gate sequencing, the five-document purpose matrix (rehearsal-issuer authorization vs. Foundation `ExecutionGrant` vs. harness evidence vs. `ApprovalEvidence` vs. Lane-3 receipt — never conflate the first two), and ownership. **Closed:** ratified by Michael on 2026-09-24, after merge, which is what froze these rules — merging proposed prose alone would not have. |
| **B. Protected issuer composition** | Platform CP | Real approvals via `dotmac-approvals` (not rollout-coupled) and real signer/verifier providers — no rollout, no deployment |
| **C1. Execution semantics** | Deployment Foundation | Selects Foundation's real `ExecutionGrant` path and fixes its digest semantics — this is what the rehearsal-issuer envelope must NEVER be mistaken for |
| **C2. Assembly binding** | Starter/CP binding package | Installs B's genuine (non-ephemeral) verifier into the candidate-independent protected rehearsal-issuer composition. It requires no Foundation candidate and creates no candidate environment. |
| **D. Protected workflow** | Starter protected-workflow owner | Creates the protected GitHub Environment, OIDC and real per-run controller-key custody, and configures the Lane-3 observer/jump/inside vantage this roadmap's own gate 1 already named. It emits protected workflow evidence for E; it does not write the Gate-0 readiness receipt. |
| **E. Operational Gate-0 acceptance** | Platform CP, as the single writer of the readiness receipt | After B, C1, C2 and D are accepted, consumes D's protected-workflow evidence and records one immutable, candidate-independent issuer-readiness receipt proving genuine approval, signer custody, controller identity, issuance and standing, revocation, single-use consumption and the required refusal cases. It allocates, builds, signs and rehearses no Foundation candidate; issues no candidate-bound `ExecutionGrant`; and authorizes no deployment. |

A had to be ratified and merged before B/C1/C2/D/E could begin
implementation; merge alone was insufficient. Both are now done, so B and C1
may run in parallel; C2 and D follow
their respective contracts; E runs only after B, C1, C2 and D are accepted
and is the sole operational closeout of gate 0/1. **This ordering exists
specifically to avoid recreating the circularity #194/#195 just broke**: a
pre-allocation, candidate-bound Lane-3 authorization would be exactly that
regression, so gate 2 (successor allocation/build/sign only) still does not
start until gate 0/1 is reviewed closed in full — mechanism, protected
composition and E's immutable candidate-independent readiness receipt,
together. Candidate-specific execution authority is issued and validated
only at gate 3, after gate 2 has produced the exact bytes it binds.

### Confirmed absent, read-only, 2026-09-24

Independently verified against live GitHub state (no host action, workflow
dispatch, key creation, OpenBao read, or secret value observed):

- No protected rehearsal GitHub Environment exists — `pypi-release` and
  `registry-release` are the only two environments on this repository.
- `control-runner-starter-mt` is online and idle, carrying exactly
  `self-hosted, Linux, X64, dotmac-control-runner, dotmac-foundation-control`.
  Its only observed diagnostic run was cancelled 2026-08-31; none has
  succeeded.
- Repository variables are exactly `LANE3_PROBE_HOST` and
  `RELEASE_RECORDER_CLIENT_ID` — no observer-user, jump-key, or
  inside-vantage variable exists yet, so `docs/inventories/lane3-acceptance-
  criteria.md`'s own vantage requirements (§§ 2a–2c: far-end source
  addresses, `privileged_vantage_refused`, `private_inside`) remain
  unconfigurable until Work Packet D lands.

These are gate-1 preconditions this roadmap already listed as open ("prepares
a protected, real ten-step recovery and Lane 3 runner"); this update dates
and confirms them rather than changing what gate 1 requires.

## Update, 2026-10-05 — Packet D moved out of Starter; Starter's share is Lane 3 private delivery

**This is a dated observation, not a rewrite of the plan.** The gate table,
the 2026-09-24 numbering reconciliation and the packet ownership above stand,
except where this section names a correction. Re-verify every coordinate
before acting.

### Refreshed baseline

| Repository | `main` at this observation |
| --- | --- |
| Starter | `e066dd07671a96e5adf1740e8073e90573f3963e` |
| Platform CP | `bf1d16265be638eac2fc63583d60f5e1f3248529` (#234) |
| `dotmac_deployment_control` | `ad95f4e1ef2bc454450ffc1f59a8d6f090b32431` (release record #74) |
| `dotmac-tech/gate0-issuer-execution` | `453ad4db44d0fe9ddf94748cd1fa124cdcc2d680` |

### Correction: Packet D's protected workflow is not Starter's

The 2026-09-24 table above assigns **D. Protected workflow** to the "Starter
protected-workflow owner". Michael's 2026-09-30 ruling on public GitHub Free
superseded that placement. It is recorded as § 11 of CP
`docs/design/gate0-d-implementation-spec.md` (CP #229, merged
`6f5efe2176e25477816f24e6762d5ce9e9fb34ed`). The protected Gate-0 workflow,
Environment and runner group live in the public, organization-owned
`dotmac-tech/gate0-issuer-execution` (repository ID `1397614140`, organization
ID `335992433`). Platform CP keeps the operator-workflow and readiness-receipt
ownership (§ A7.6–A7.7).

**The one D item that remains Starter's** is the spec's § 8 row "design and
verify private delivery of observer, jump and inside-vantage configuration
through Starter/Foundation infrastructure" (ADR-0013 § A7.6). On 2026-10-05
Michael chose organization-owned Lane 3 execution for it: a dedicated
workflow-restricted runner group, a protected Environment, ephemeral runners,
an amended rehearsal oracle, and retirement of `control-runner-starter-mt` and
its static credentials. The design is
[`docs/LANE3_EXECUTION_TOPOLOGY.md`](LANE3_EXECUTION_TOPOLOGY.md), recorded by
the ADR-0070 amendment of 2026-10-05. Its source work (D-S2 workflow and
oracle, D-S3 guards) stays fail-closed until provisioning and the negative
proofs are recorded. The four Lane 3 runner fixes in
`docs/inventories/lane3-acceptance-criteria.md` are tracked separately (D4)
and are not part of D.

### What closed since 2026-09-24

Positive coordinates only. Each is a merge, run or peeled tag, not a status
claim.

- **Packet A and CP ADR-0013 A6.** § A7 was ratified 2026-09-24; the full A6
  amendment, including A6.4, was ratified 2026-09-25 (recorded in Starter
  #748, #749).
- **Packet C1, source.** Starter #753 merged as
  `cb2d9f8983f7bb40141540a0490731320bca0fe3` (V3 execution authority and
  unified host admission). Starter #761 merged as
  `adf8632d1a09d6bd1c430e0e4069bb6c48d5d81b` (Foundation transition-receipt
  verifier). **Both are unreleased**: no Foundation successor exists.
- **Packet D public topology.** Execution repository refusal-only PR #1 was
  merged as `f218660b6ff7c3a01b877e6ab080efcd31672805`. The bounded
  scheduling-and-teardown subgate completed 2026-10-01: in protected run
  `36858977107`, Michael approved the Environment, the job was assigned to the
  `gate0-issuer-protected` group, and the intended refusal step executed. The
  six historical negative fixtures were re-run first and their eleven jobs
  never received a runner. The disposable canary was removed afterwards.
  **No privileged runner was attached.**
- **Control and CP source composition.** `dotmac-deployment-control`
  `0.1.0a17` is tagged `dotmac-deployment-control-v0.1.0a17`, peeling to
  `574418944d35ddf3559d17e59e9184b5f545ebe4`. CP #233 adopted it at source
  level (`40e9fddf6a586b511bb73116696b463423448ef1`). CP #217 (`d598aa0e`),
  #231 (`6e9166d7`), #232 (`a88d9ff3`) and #234 (`bf1d1626`) also merged. These
  are source composition, not production adoption.

**Two baseline rows above are stale at this observation.**

- The 2026-09-20 table and gate 1 say `_do_restore_objects` overwrites the
  roles attempt before adjudication. Starter #740
  (`b0273cee`) fixed that: roles and objects now carry separate attempts, and
  adjudication walks both.
- Both executors no longer call `require_host_source(receipt=None)`. Since
  #753 they take a required `admission_provider`. The only provider shipped is
  `RefusingHostSourceAdmissionProvider`, and every CLI call site wires it, so
  positive admission still needs an external assembly provider. That is a
  repair of the call shape, not admission.

The real ten-step recovery run and Lane 3's 16/16 remain open.

### Still open, as of 2026-10-05

These are absences: dated, with a named refresh owner.

| Item | State | Refresh owner |
| --- | --- | --- |
| Gate-0 D credential-bearing provisioning (OpenBao JWT role, issuer and attester signers, trust state, SSH CA, privileged runner) | Not provisioned | Michael |
| Gate-0 E readiness receipt | Not started | Platform CP |
| Gate 2 (allocate `0.4.0a2`) | Not started. `packages/dotmac-deployment-foundation/pyproject.toml` still declares spent `0.4.0a1` | Starter release captain |
| Lane 3 | 0/16 `executed_passed`. No receipt has ever been produced | Foundation / Lane 3 runner owner (D4) |
| Starter Lane 3 vantage | Environments are still only `pypi-release` and `registry-release`. Variables are still only `LANE3_PROBE_HOST` and `RELEASE_RECORDER_CLIENT_ID`. `control-runner-starter-mt` is online and idle | Starter (this design), then Michael (provisioning) |
| `retired_total` | 0 | Each product |

**A Gate-2 ordering constraint, in Foundation's receipt contract.** Any
change below must land in Foundation source before the Gate-2 freeze, or the
candidate it ships in is spent. `RehearsalReceipt.v1` cannot carry any of them:
its schema is frozen against new fields because it has crossed five built
wheels, so they need a `RehearsalReceipt.v2`.

1. Gate item 9's middle term must be `ExecutionPlanDigestV1` (rule 49).
   `build_receipt` currently forces the descriptor, authorization-document and
   report digests to be equal, and `scripts/lane3_authorization.py` lists this
   as an unrepaired Foundation precondition.
2. Lane 3 receipts must carry opaque identifiers instead of target and probe
   addresses, from the Lane 3 design.
3. Lane 3 receipts must bind the GitHub run that produced them, also from the
   Lane 3 design.
