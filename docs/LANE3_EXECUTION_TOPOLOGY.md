# Lane 3 execution topology: organization-owned, workflow-restricted, ephemeral

- **Status:** Proposed design, 2026-10-05. On 2026-10-05 Michael Ayoade chose
  this direction (organization-owned Lane 3 execution, a dedicated
  workflow-restricted runner group with a protected Environment, ephemeral
  runners, an amended rehearsal oracle, and retirement of the personal runner
  and its static credentials). The concrete coordinates, paths and defaults
  below are **proposals awaiting review**, not provisioned facts. This
  document grants no provisioning, host, secret, release, deployment or
  risk-acceptance authority.
- **Owning contracts:** ADR-0070 (amendment 2026-10-05 records this decision);
  `AGENTS.md` rules 30, 44 and 51; Platform CP ADR-0013 § A7.6 (Lane 3 vantage
  configuration belongs to Starter/Foundation infrastructure); CP
  `docs/design/gate0-d-implementation-spec.md` § 8 (the unresolved
  private-vantage-delivery row this document answers) and § 11 (the public
  GitHub Free topology this document mirrors).
- **Coordinates, as of 2026-10-05 (re-read before acting):** Starter `main`
  `e066dd07671a96e5adf1740e8073e90573f3963e`; Platform CP `main`
  `bf1d16265be638eac2fc63583d60f5e1f3248529`; `dotmac-tech/gate0-issuer-execution`
  `main` `453ad4db44d0fe9ddf94748cd1fa124cdcc2d680` (repository ID
  `1397614140`, organization ID `335992433`).

## 0. What this closes, and what it does not

This is the Starter share of Gate-0 Work Packet D: a design for delivering the
Lane 3 observer, jump and inside-vantage configuration privately, and the
execution topology that makes that possible. It defines what D-S2 (workflow
and oracle source) and D-S3 (guards and tests) must implement, and the
evidence D's acceptance requires from Starter.

It does **not** close Packet D. D closes on live evidence: the provisioning
and refusal proofs in § 7, plus CP's own D items (JWT role, signers, trust
state, SSH CA, privileged Gate-0 runner). It does not close Work Packet E,
allocate or rehearse a Foundation candidate (Gates 2 and 3), or change the
four Lane 3 runner fixes in `docs/inventories/lane3-acceptance-criteria.md`.
Those fixes are tracked separately as D4 and are deliberately out of scope
here.

## 1. Why the current topology cannot be admitted

Measured read-only on 2026-10-05:

- **The repository is public and personal-account owned.**
  `control-runner-starter-mt` is registered to `michaelayoade/dotmac_starter_mt`
  (online, idle, labels `self-hosted, Linux, X64, dotmac-control-runner,
  dotmac-foundation-control`). A label routes a job; it does not restrict
  which workflow may use the runner. Workflow-restricted runner groups are an
  organization control, unavailable on a personal account. Anyone with write
  access can push a branch whose workflow selects
  `[self-hosted, dotmac-control-runner]`. The three self-hosted workflows on
  `main` use `workflow_dispatch` only, but nothing enforces that the next one
  will. The fork-PR approval policy (`all_external_contributors`) does not
  cover collaborators.
- **The topology is public.** `exposure-rehearsal.yml` reads
  `vars.LANE3_PROBE_HOST`, `vars.LANE3_INSIDE_VANTAGE`,
  `vars.LANE3_OBSERVER_USER` and the key-path variables, and passes them, along
  with the `target` and `vm_slot` dispatch inputs, as runner arguments.
  Repository variables are not masked. Dispatch inputs, logs and artifacts of a
  public repository are public.
- **The credentials are static and sit on a shared runner.** The controller
  key (`~/.dotmac/controller-<authorization_run>`), the observer key, the
  inside-vantage jump key and the probe-host key are long-lived files on the
  runner, readable by any step any workflow runs there. `RUNNER_QUERY_TOKEN`
  (`administration: read`) is a long-lived repository secret.
- **The evidence carries topology.** `RehearsalReceipt.v1` records `target`
  and `probe_identity`. `render_status_document` writes both into
  `deployment-exposure-rehearsal-status.md`. `probe-evidence.json` carries
  observed source addresses. All three are uploaded as artifacts.
  `collect_probe_evidence.sh` defaulted `LANE3_FORMER_PRIVATE_PATHS` to private
  addresses in tracked source (removed by R6, 2026-10-06).

Each of these is a refusal reason for § 7's admission, not a style nit.

## 2. Target topology

All names are proposals. Provisioning records the final exact coordinates and
updates this document and `.github/lane3-execution.json` (§ 6) in the same
change, before any runner registration.

| Element | Proposed coordinate | Required properties |
| --- | --- | --- |
| Execution repository | `dotmac-tech/lane3-exposure-execution` (public) | Holds the launcher workflow and nothing private. Protected `main`: PR required, zero required approvals (solo owner), required non-privileged checks, admin enforcement, no bypass actors, deletion and force-push refused. Read back the effective ruleset. Public because GitHub offers required Environment reviewers on Free only for public repositories, the same reason as CP § 11. |
| Workflow | `dotmac-tech/lane3-exposure-execution/.github/workflows/lane3-exposure-rehearsal.yml@refs/heads/main` | `workflow_dispatch` only. No `pull_request`, `pull_request_target`, `workflow_call` or `push` trigger on the privileged job. Job-level condition requiring `workflow_dispatch` and `refs/heads/main`. Minimum `GITHUB_TOKEN` permissions plus `id-token: write` on the protected job only. No third-party action on the privileged runner. |
| Environment | `lane3-rehearsal-protected` | Michael is the required reviewer. `main` only. Admin bypass disabled and read back. This is a one-person human gate, not two-person approval. |
| Runner group | `lane3-exposure-protected` | The full § 11 tuple: `allows_public_repositories=true`, `visibility=selected`, `selected_repository_ids=[<execution repository ID>]`, `restricted_to_workflows=true`, `selected_workflows=[<the ref-pinned workflow above>]`. Nothing else in the group. **Distinct from `gate0-issuer-protected`.** The two never share a group, a runner, a base image or an SSH CA, because Gate 0 is forbidden to connect to a target and Lane 3 exists to do exactly that. |
| Runners | Ephemeral, one job per runner | Registered just in time (`generate-jitconfig`) by a provisioner outside the public repository, on a VM recreated from a verified base image for every run. No persistent home directory, no credentials at rest, nothing carried between runs. Ephemerality is hygiene, not the selection control: selection comes from the group's repository and workflow restriction. |

**The launcher is thin.** It holds the dispatch grammar, the ordering in § 3,
and the evidence publication in § 5. Lane 3's behaviour stays in Starter: the
launcher checks out an exact Starter protected-`main` revision and runs that
revision's `exposure_rehearsal_runner.py` against the digest-verified
candidate wheel. Two copies of the runner would mean two contracts.

## 3. What one run does, in order

1. **Validate the dispatch inputs before anything else.** The inputs are
   `starter_revision` (exactly 40 lowercase hex characters),
   `candidate_version`, and an opaque Gate-3 grant reference. Anything else is
   refused. The grammar lives in one module that the launcher and the oracle
   (§ 6) both import, and a test proves it. `run-name` renders
   `lane3 starter=<starter_revision> candidate=<candidate_version>` from these
   inputs.
2. **Require the revision to be on Starter's protected `main`.** The compare
   API must report `main...<starter_revision>` as `identical` or `behind`. Any
   other answer, or no answer, refuses.
3. **Check out exactly that revision** and require `git rev-parse HEAD` to
   equal it. This verified checkout, not the launcher's own `GITHUB_SHA`, is
   the runner revision the receipt records as `foundation_revision`.
4. **Resolve, fetch and verify the candidate** from that checkout's committed
   `CandidateArtifact.v1`, and install the wheel in an isolated `-E -P`
   environment. This is unchanged from rule 44. The credential used to fetch
   the Starter artifact must be read-only and scoped to Starter. Whether a
   credential is needed at all for a public repository's artifact is
   **unmeasured**, and is measured during § 7.
5. **Verify the Gate-3 authorization** through `lane3_authorization.py` and
   Foundation's `ExecutionGrant`. If it does not verify, refuse before any
   OpenBao call.
6. **Fetch topology and credentials only now** (§ 4). Write each value to a
   `0600` file in a per-run tmpfs, pass file paths and never values on any
   command line, and add `::add-mask::` as defence in depth only.
7. **Execute, publish the redacted evidence (§ 5), and destroy** the keys,
   certificates and tmpfs. The runner then exits and its VM is destroyed.

**Honesty about step 5 → 6.** That order is enforced by reviewed workflow
code on protected `main`, not by a credential boundary. OpenBao sees the OIDC
claims of the workflow; it cannot see whether a Foundation grant verified.
Binding certificate issuance to a Control lease would turn this ordering into
a credential boundary. That is an **open item for Gate 3**, not a property
this design claims.

**Dispatch carries no topology.** The current `target`, `vm_slot`,
`controller_identity` and `authorization_run` free-text inputs go away.
`FoundationExecutionPlanV3` (ADR-0070, 2026-09-25) already binds the target
reference, Fleet `host_id` and controller fingerprint. The Proxmox slot is
topology, so it comes from the private record keyed by that `host_id`.

## 4. Private delivery

**Topology record.** One OpenBao KV v2 record, proposed path
`secret/dotmac/starter/lane3/vantage-topology`. It holds the probe vantage,
the inside vantage, the observer principal, the target → far-end mapping keyed
by Fleet `host_id`, the former private paths, and the slot map. Only Michael's
provisioning identity writes it. The workflow identity reads it and never
writes it. Receipts cite the record **version**, never its values.

**Workflow identity.** One OpenBao JWT role, proposed name
`lane3-exposure-rehearsal`, with `bound_claims` on `repository`,
`repository_id` and `repository_owner_id` (immutable IDs read at repository
creation), `environment`, `ref=refs/heads/main`, `workflow_ref` (the exact
coordinate in § 2) and `event_name=workflow_dispatch`, plus an exact
`bound_audiences` value (proposed `urn:dotmac:lane3:exposure-rehearsal`). The
token is short-lived and non-renewable. Non-renewability is checked on the
provisioned role, because a max TTL does not prove it. The policy permits only
reading the topology record and signing at the two Lane 3 roles below. It
explicitly denies `gate0-ssh/`, CP's issuer and attester signer paths, their
trust-state records, and everything else.

**Lane 3 SSH CA.** A dedicated mount, proposed `lane3-ssh/`, disjoint from
`gate0-ssh/` and holding a separate CA key. A Gate-0 certificate must never
authenticate to a Lane 3 host, and a Lane 3 certificate must never
authenticate to anything else. Key pairs are generated inside the run, and
private keys never leave the run's tmpfs.

| Role | Principal | Certificate constraints |
| --- | --- | --- |
| `lane3-ssh/sign/observer` | `lane3obs` (target-side, no sudo, no docker group, as today) | No PTY, no agent, X11 or port forwarding. TTL at most the job timeout, and the actual TTL is measured. |
| `lane3-ssh/sign/inside-jump` | the inside-vantage jump account | `force-command=/bin/false` and `permit-port-forwarding` only (`ssh -W` needs direct-tcpip and nothing else). Server-side `PermitOpen` limited to the declared probe ports. Same TTL rule. |

Each target and vantage trusts the Lane 3 CA through `TrustedUserCAKeys` and
an `AuthorizedPrincipalsFile`. The static `authorized_keys` entries are
removed in § 8.

**Controller identity** follows the per-run OpenSSH key pattern in CP spec § 5,
and the fingerprint is bound into the V3 plan. How the fingerprint is
presented to Control before the grant is issued is Gate-3 composition, owned
by CP, Control and Foundation. This document does not decide it. It only
retires the static `~/.dotmac/controller-*` file.

## 5. Public evidence without topology

**Rule:** no address, hostname, slot, jump detail or vantage value appears in
the execution repository's tracked files, variables, secrets, logs or
artifacts, or in a receipt. Masking is not the control, because it fails on
any transformed value. The control is that the value is never written to
public output.

- **Receipt identifiers become opaque.** `target` becomes the Fleet `host_id`,
  and `probe_identity` becomes the topology-record key and version. Every
  receipt also binds the run that produced it (execution `repository_id`,
  `run_id`, `run_attempt`), so a receipt cannot be moved from one run to
  another. **This is a Foundation contract change, and it must land in
  Foundation source before the Gate-2 freeze**, because the receipt contract
  ships inside the candidate bytes. Landing it later would spend the candidate
  (rule 48). Foundation owns the schema decision: an additive v1 field, or
  `RehearsalReceipt.v2`.
- **Raw probe evidence is encrypted.** It is bundled, encrypted to a recipient
  whose private key Michael holds outside every runner (proposed: `age`, with
  an offline key), and uploaded as the only raw-evidence artifact. The receipt
  binds the ciphertext's SHA-256, and each row's `evidence` points into bundle
  member paths. Item 16's requirement that a reader can confirm the vantage
  was inside the source set is met by a reader with record access resolving
  the record key and version. It is not met by publishing the address.
- **The generated status document** renders only opaque identifiers.

## 6. Oracle amendment (normative for D-S2)

The current oracle reads `exposure-rehearsal.yml` runs in the Starter
repository and treats the run's `head_sha` as the runner revision. Under this
topology, the run lives in another repository and its `head_sha` is the
launcher's commit. The amended oracle keeps every existing property: two
oracles, newest-then-check, fail closed on every ambiguity, no escape hatch.
It changes only where runs come from and how a run is tied to a Starter
revision.

**Pinned identity.** A checked-in `.github/lane3-execution.json` in Starter
holds:
- the execution repository name, `repository_id` and `owner_id`;
- the workflow path;
- the Environment name and ID, and the expected reviewer;
- the runner group name and ID;
- the admitted launcher revisions.

Changing any of these is a reviewed Starter PR. Placeholder values make the
oracle refuse (§ 9).

**Selection.** This replaces `gh run list --workflow exposure-rehearsal.yml
--commit <sha>` and `_fetch` against Starter.

1. List every run of the pinned workflow in the pinned repository with
   `event=workflow_dispatch` and `branch=main`, paginating to the end. An
   incomplete listing refuses.
2. Refuse if any listed run's `repository.id`, `path`, `event` or
   `head_branch` differs from the pinned values.
3. Parse each run's `display_title` with the shared grammar from § 3 step 1.
   A run whose title does not parse is excluded, and **only for this reason**:
   the launcher's first step refuses exactly that grammar before checkout, so
   such a run cannot have rehearsed any revision. D-S3 proves the grammar is
   shared and that the refusal is the launcher's first step. Without that
   proof, exclusion would be a masking path, and the oracle must refuse
   instead.
4. Keep the runs whose parsed `starter` equals the SHA under release. If none
   remain, refuse.
5. Select the newest by `(run_started_at, id)`, then require it to be
   `completed`/`success`. This is unchanged `decide` semantics.
6. **New checks.** The selected run's `head_sha` must be an admitted launcher
   revision. Its protected job's `runner_group_id` must equal the pinned group
   (jobs API). Its Environment approval must come from the expected reviewer
   on the pinned Environment ID (approvals API). Any read failure refuses.
7. Download the receipt from **exactly that run ID**, and apply
   `verify_publication` with the wanted revision set to the SHA under release.
   Require the receipt's run binding to equal the selected run's
   `(repository_id, run_id, run_attempt)`. Require the artifact digest as
   today.

The three-revision ancestry ruling in `release-facility.yml` is unchanged; its
runner revision is the receipt's `foundation_revision`. The read credential
for the execution repository's runs, jobs, approvals and artifacts must be
read-only. Whether the release job's own token can read them is measured in
§ 7. If it cannot, a read-only App installation scoped to the execution
repository is used, with no write permission.

**Rejected alternative.** An App posting a check run onto the Starter SHA from
the execution side. It would put a write credential with `checks: write` where
privileged code runs, and the receipt already binds the revision.

**Rule text follows code.** `AGENTS.md` rule 44's sentence "The workflow run's
`head_sha` remains the protected-main oracle" is amended in the same PR that
changes the oracle (D-S2), not before. Rules describe enforced behaviour.

## 7. Admission evidence before a privileged runner or credential

The [2026-10-06 B5 scheduling record](inventories/lane3-b5-scheduling-evidence-2026-10-06.md)
contains the canonical run/job references and expected positive-launcher refusal.
N3 was not executed, and later credential/admission evidence remains incomplete;
this record does not admit the topology. `admission_evidence` remains null.

This mirrors CP § 11. A positive dispatch alone is never sufficient. On the
single ephemeral runner the order is fixed: the runner is shown idle, the
negative cases are queued and stay unassigned for the stated bound, and only
then does the protected positive dispatch run and get picked up.

| Check | Required evidence |
| --- | --- |
| Public controls | Read back visibility, organization ownership, the ruleset, the Environment reviewer, branch policy and admin-bypass refusal, and the full runner-group tuple including the resolved repository ID. |
| Authorized scheduling | A Michael-approved dispatch from `main` reaches only the pinned group and protected job. The observed OIDC claims match the role. |
| PR exclusion | Same-repository and fork `pull_request` **and** `pull_request_target` probes, including probes that name the group or labels, never schedule on the group. |
| Ref and workflow failure | A non-`main` dispatch, a different workflow, a different ref and a reusable call never schedule and never obtain a token. A missing reviewer blocks the job. |
| Credential failure | Each wrong bound claim (name, immutable IDs, environment, ref, workflow, event, audience, expiry) is denied by the live role. The token cannot read Gate-0 or CP signer paths. |
| No-grant refusal | A dispatch without a verified grant makes no OpenBao request, which is observed on the OpenBao audit side. A log line saying so is not enough. |
| Isolation and disclosure | A failed or cancelled canary run leaves no key, certificate or workspace state, and the next run sees none. A private-side scan of the public logs and artifacts, using the topology record's actual values, finds none. The scan runs outside the public repository, because a public scan would need the values. |
| Oracle reachability | The amended oracle's reads (§ 6) succeed with the intended read credential and refuse with a wrong one. |

Scheduling probes use a disposable canary in the same group, on a separately
named and authorized isolated VM. The canary is neither the existing control
runner nor the shared testing server. Record repository IDs, read-backs, run
and job IDs, refusal outcomes and source revisions in the roadmap and the
canonical debt register.

## 8. Retiring the personal runner and static credentials

Lane 3 has never produced a receipt: qualification refuses before
`build_receipt`. The old path therefore has no working capability to preserve,
and retirement does not wait for org admission. It waits only for D-S2 to stop
any Starter workflow from targeting the label. Each step is evidenced by a
read-back, not by the change that was meant to cause it.

| Step | Action | Evidence |
| --- | --- | --- |
| R1 | **Split, 2026-10-06.** (a) `exposure-rehearsal.yml` is retired only after its rehearse-job steps move into a Starter-owned script that the launcher calls (D-S2c). About 40 Starter guard tests encode its Lane 3 properties (candidate-bytes execution, `-E -P` isolation, authorization before probe, capability preflight). Deleting it first would leave those properties unguarded, because the launcher lives in another repository. (b) `control-runner-diagnostic.yml` is **held**: `packages/dotmac-runner-transport/EXTRACTION.toml` names VMID 124 (the control runner) as that programme's first adopter, and its cutover needs both repository diagnostics. Retiring it needs an owner decision on which plan wins. When R1 lands, it updates the executor inventory and lowers the `vars.LANE3_` ratchet to empty | Merge SHA. Executor-retirement ratchet green. |
| R2 | Deregister `control-runner-starter-mt`. **Held** with R1(b): same VMID 124 conflict | Starter runner listing reads zero runners, with a timestamp. |
| R3 | Destroy the runner VM and its disk, including the controller, observer, jump and probe keys at rest, and retire its Fleet declaration. **Held** with R1(b). The Lane 3 static keys can still be removed from the VM and from `authorized_keys` (R4) without destroying the VM | Hypervisor read-back of absence. Fleet record change. |
| R4 | Remove the static `lane3obs`, jump and probe-host keys from every `authorized_keys` they were installed in | Per-host read-back naming the host. "Unobserved" is recorded as unobserved, never as absent. |
| R5 | **Split:** deleting `LANE3_PROBE_HOST` can proceed; deleting and revoking `RUNNER_QUERY_TOKEN` is **held** with R1(b), because `control-runner-diagnostic.yml` uses it. Delete repository variable `LANE3_PROBE_HOST` and secret `RUNNER_QUERY_TOKEN`, and **revoke the underlying token at its issuer**, because deleting a repository secret revokes nothing | Variable and secret listings. Issuer-side revocation read-back. |
| R6 | **Done (source), 2026-10-06:** the private-address default is removed from `collect_probe_evidence.sh` (the value is now required from the private topology record), and the address ratchet is lowered to empty. Refreshing `lane3-acceptance-criteria.md`'s vantage references follows with the launcher | Merge SHA. |

## 9. Fail-closed contract for D-S2 and D-S3

Until § 7's evidence is recorded and `.github/lane3-execution.json` carries
non-placeholder IDs:
- the release oracle refuses with a named reason;
- the launcher workflow in the execution repository is refusal-only, like
  Gate-0's PR #1 (`f218660b`);
- no topology value is configured anywhere public.

D-S3 adds static guards with sensitivity proofs (planted violations turning
them red):
- no Starter or launcher workflow lets `pull_request*` select a self-hosted
  runner;
- no `vars.LANE3_*` topology and no topology literal in tracked files;
- the dispatch grammar is shared and its refusal is the launcher's first step;
- `Lane3RunnerCapability.v1` requires the private-delivery seam.

## 10. Who does what

| Work | Owner |
| --- | --- |
| Create the organization repository, ruleset, Environment, runner group and JIT provisioner. Run the canary and its negative proofs | Michael |
| OpenBao JWT role and policy, `lane3-ssh/` CA and roles, the topology record, sshd CA trust on targets and vantages | Michael (provisioning identity only) |
| D-S2 launcher (refusal-only first) and oracle source. D-S3 guards. Retirement steps R1 and R6 | Starter |
| Receipt opaque identifiers and run binding, before the Gate-2 freeze | Foundation |
| How the controller fingerprint is presented to Control and the grant issued; binding certificate issuance to a lease | CP, Control and Foundation (Gate 3) |
| Lane 3 runner fixes (items 8, 12, 13–16 and far-end addresses) | D4, separate |

## 11. Decisions this document leaves to Michael

1. The final names of the repository, workflow, Environment, group, JWT role,
   SSH mount and topology record path.
2. The evidence encryption recipient and where its private key is held.
3. The oracle's read credential, if § 7 shows the release job's token cannot
   read the execution repository.
4. Where the JIT provisioner runs, and its owner.
5. Certificate and token TTLs, after measurement.

## 12. Proposed amendment — Lane 3 N3 structural exclusion (2026-10-06)

**Status: PROPOSED, NOT ADOPTED.** Michael requested a draft proposing
structural coverage on 2026-10-06. That request authorizes preparation, not
acceptance of this substitution. Until the contract owners accept matching
Starter and CP amendments through reviewed, fully green protected merges,
the existing live PR-target requirement applies. `admission_evidence` remains
null. This is a documentation proposal, not an implemented admission check.

### Scope and precise proposed substitution

For Lane 3 repository `dotmac-tech/lane3-exposure-execution` only (repository
ID 1406738001, owner ID 335992433), permit N3 to be recorded as
`structural exclusion; live probe not executed` for a reviewed exact source
revision whose entire workflow set declares no `pull_request_target` trigger.
Replace only the otherwise required same-repository and fork-origin N3 live
probe with the complete source/control evidence below. Same-repository and
fork `pull_request` negatives, non-main/different-file/reusable-call negatives,
and the protected positive scheduling proof remain live requirements.

This proposal does not apply to `dotmac-tech/gate0-issuer-execution`, does not
replace any OIDC/credential/audit/disclosure/oracle check, and does not certify
that a runner group rejects every PR-target event. No Foundation allocation,
publication, privileged attachment or provisioning authority follows from it.

### Required structural evidence before accepting N3

1. Independently retrieve the live repository ID/owner, default branch `main`,
   exact full source SHA, and Git tree. Enumerate every workflow file from that
   tree, archive its content digest and parse its complete trigger/job selection
   structure. Fail closed on unreadable files, unsupported YAML, aliases or
   indirection. Every workflow must lack `pull_request_target`, not only the
   selected launcher. Record the policy implementation/test SHAs too.
2. Verify the selected launcher has only `workflow_dispatch`; its privileged
   job checks both event and `refs/heads/main`, uses the exact group and protected
   Environment, and cannot derive its runner selection or workflow code from
   PR input. Record the workflow blob digest. No PR-target opt-in or source
   policy exception is permitted under this substitution.
3. Live API read-backs must bind the group to that immutable repository ID and
   exact selected workflow at `@refs/heads/main`, with no alternate repository
   or workflow entry. Read back the main ruleset's required PR/source-policy
   check, enforcement and absence of bypass actors; Environment reviewer,
   main-only branch rule and disabled admin bypass. Show the latest required
   source-policy checks passed for the exact head/base. A label is insufficient.
4. Link the live N1/N2/N4b/N5/N6 and P1 evidence, including the contemporaneous
   queued observation bound with an online idle canary, positive approval and
   assignment, and teardown. Terminal `runner_id: 0` alone does not reconstruct
   the historical waiting interval. Identify which evidence is API-verified,
   contemporaneously observed, or reported; do not promote one into another.
5. The contract owners must record acceptance of this precise residual:
   source policy is editable in the same repository as workflows. A privileged
   source change that adds PR-target behavior can invalidate this evidence;
   this is reliance on reviewed protected source, not a measured event-level
   scheduler denial. No credential-bearing runtime may rely on a stale source
   snapshot. A later admission owner must re-read the bound source and controls
   before privileged attachment; if that revalidation is absent, refuse.

### What the reasoning establishes

GitHub documents that PR-target workflow code is taken from the base
repository's default branch. A same-repository or fork PR workflow edit does
not create a PR-target entry point in an independently inspected default-branch
workflow tree containing no such trigger. This is the narrow proposed
exclusion argument. See [GitHub's PR-target security documentation](https://docs.github.com/en/actions/reference/security/securely-using-pull_request_target)
and the [default-branch semantics change](https://github.blog/changelog/2025-11-07-actions-pull_request_target-and-environment-branch-protections-changes/).

**Do not infer event isolation from `@refs/heads/main`.** PR-target can itself
resolve to the default branch; a selected ref does not, by itself, distinguish
that event from an admitted main dispatch. The proposal relies on absence of
an entry point in the full protected source and the dispatch-only job shape.
It does not prove how GitHub would schedule a newly added malicious default-
branch PR-target workflow.

### Invalidation, labels and acceptance

Any change to the default-branch workflow tree, policy implementation/tests,
repository/default-branch identity, group tuple, ruleset or Environment
invalidates the structural evidence. Before further credential-bearing runs,
re-establish every structural condition against the new exact source/control
snapshot, or perform the live N3 probes under a separately authorized reviewed
probe procedure. If a PR-target trigger appears anywhere, this substitution
is unavailable. Missing evidence remains indeterminate and refuses admission.

The accepted record must retain `live N3 not executed`; never label it a live
pass. Adoption requires CP and Starter contract-owner review plus Michael's
explicit acceptance of the residual above and corresponding checked-in
amendments. Source-policy green alone is not that acceptance. The October6
scheduling record is evidence input, not a completed structural dossier; no
full workflow-tree digest/revalidation mechanism is supplied by this change.
All other programme gates remain unchanged.
