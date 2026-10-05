# ADR-0005: Forgejo private artifact registry (supersedes the public-PyPI R0 decision)

- **Status:** Accepted (2026-07-30). Supersedes the registry choice in the R0
  release plan (`docs/superpowers/plans/2026-07-30-kernel-release-preparation.md`).
- **Deciders:** Michael.
- **Scope:** Cross-Dotmac artifact distribution (Python wheels now; OCI, npm, and
  other formats later).

## Context

R0 ratified publishing `dotmac-kernel` to **public PyPI** via OIDC trusted
publishing. Before the first publish, the strategy was revised: Dotmac's kernel,
vendor control plane, and product packages are proprietary and should not be
world-visible, and Dotmac wants one self-hosted control plane for all artifact
formats (Python, OCI, npm) with scoped access and its own retention/backup.

## Decision

**Forgejo becomes Dotmac's authoritative private artifact registry.** GitHub
remains authoritative for source, pull requests, and CI during phase 1. **No
repository mirroring and no parallel CI authority.**

Authority split (phase 1):

| Authority | System |
|---|---|
| Source, PRs, rulesets, CI | GitHub |
| Private Python / OCI / npm / future packages | Forgejo |
| Credentials & signing material | OpenBao |
| Vendor/product lifecycle | Vendor control plane |

- **Deployment:** Forgejo runs on **dotmac-s3 ([redacted 2026-10-05: dotmac-s3 address; see Fleet])** at
  `https://registry.dotmac.io`, co-located with the existing (idle) MinIO — a
  dedicated registry host, deliberately NOT the production database tier. Package
  **blobs** live in a MinIO bucket (`dotmac-packages`); Forgejo **metadata** in a
  dedicated Postgres. Config + runbook: `deploy/forgejo/`. Forgejo compute is
  intended to migrate to a dedicated VM later (a clean repoint, since blobs are in
  MinIO and metadata in Postgres).
- **Ownership:** business owner Dotmac; initial Forgejo admin is a Dotmac-controlled
  account; a second named maintainer is added after the first release.
- **Publishing:** GitHub Actions publishes with a **narrowly-scoped
  `write:package` credential** whose canonical source is OpenBao
  (`secret/dotmac/forgejo/ci-publisher-token`). Phase 1 mirrors it into the
  protected `registry-release` GitHub environment (Michael-gated, main-only)
  because GitHub-hosted runners cannot reach the internal OpenBao; the hardening
  target is a self-hosted runner using GitHub OIDC → OpenBao JWT auth so no token
  is stored in GitHub. **PyPI trusted publishing is not used.**
- **Release gates preserved** from R0: protected `workflow_dispatch`, exact
  current-`main`-SHA gate, explicit `version` input matched to metadata,
  build-once → inspect → publish-the-same-bytes → install-and-verify from the
  registry → tag `dotmac-kernel-v<version>` only after verification. Every
  publishing-workflow action is pinned to a full commit SHA; container images are
  pinned to digests.

## Consequences / controls

- **Immutability** (compensating for Forgejo admins being able to delete/republish
  a version): the MinIO artifact bucket has **versioning + object-lock (WORM
  retention)**, so prior bytes + digests are retained tamper-evidently beneath
  Forgejo. Restrict Forgejo admin accounts; treat delete/republish as audited.
  Keep off-host/versioned backups (MinIO replication + the Forgejo-metadata
  Postgres dump).
- **Dependency confusion:** consumers (Vendor CP, Sub) resolve `dotmac-kernel`
  explicitly from the Forgejo index and must avoid an uncontrolled public
  extra-index fallback for Dotmac names (pin with hashes and/or a controlled index
  priority). Public transitive deps still come from PyPI.
- **Forgejo package-permission granularity** is currently org-oriented (finer team
  permissions are still upstream-planned); compensate with restricted
  administration + the scoped publisher token + the MinIO immutability controls.
- **Availability:** the registry is now on the critical path for every Dotmac CI
  install; monitoring, backup, and a restore rehearsal are standup prerequisites.

## Decision amendment — 2026-08-23 (release authority and record closure)

The publisher, the human gate reviewer and the post-release recorder are three
different authorities:

1. An automation identity may dispatch and observe a release, but is not a
   `registry-release` reviewer and must report
   `current_user_can_approve=false` while a run is pending. A human reviewer
   approves in the protected-environment UI; chat authorization never transfers
   that action to an agent or API client.
2. A dedicated recorder GitHub App may read metadata, write the mechanical
   release-record branch and open its pull request. It has no Actions or
   deployment-approval, environment or repository-administration permission.
   GitHub does not offer a create-only pull-request permission: pull-request
   write also reaches the review API. The separation therefore rests on two
   enforced facts rather than an overclaim about the token: the App authors and
   last-pushes its own record PR, whose author cannot approve it, and protected
   `main` requires a fresh approval from someone other than the last pusher with
   no bypass. The repository-wide Actions switch that couples PR creation to PR
   approval stays disabled. Each tag-writing job mints one short-lived,
   current-repository installation token through
   `.github/actions/release-recorder-token`, then rebinds Git before the record
   branch is written so both the push and PR belong to that App. It uses
   `RELEASE_RECORDER_CLIENT_ID` and `RELEASE_RECORDER_PRIVATE_KEY` from the
   protected environment; only contents and pull-request write are requested.
   The tag-writing job's ordinary workflow token has exactly contents write and
   no pull-request authority. It can provide the loud fallback branch when the
   App is unavailable, but cannot silently become a second automatic recorder
   if repository settings change.
   The private key's canonical OpenBao path must be recorded when the App is
   provisioned, and no key value enters source or logs.
3. Protected `main` requires one approving review, approval of the most recent
   reviewable push, dismissal of stale approvals, no bypass, and every emitted
   acceptance check: the ten `quality (...)` matrix checks,
   `allocation-gate`, `unit`, `integration`, `docker-build`, `consumer-boot`,
   both `kernel-floors` checks and `Dotmac engineering standards`. Because the
   recorder App authors and last-pushes its PR, the approval must come from a
   different actor. A required-check subset is not release evidence merely
   because the unrequired checks happened to be green on one PR.

One release captain freezes every non-record merge from dispatch until the tag
is verified, the generated record PR is reviewed and green, and the resulting
protected-main revision is both truthful and green. A tag is the opening of the
record gap, not the end of the release. If recorder automation fails after
tagging, the release stays failed and frozen while a human opens the
already-pushed branch; publication is never re-run to repair bookkeeping.

This is the accepted end state. The loud/manual branch bridge remains the
fail-closed operational path until the two restricted identities and ruleset
settings are installed and verified. The a91/a93 approval exceptions and the
a92/a93 record evidence are retained in `docs/CONTROL_EXCEPTIONS.md`.

### Provisioning record — 2026-08-24

As observed at 2026-08-24 22:35 UTC, private App
`dotmac-release-recorder-328160` has selected-repository access to
`michaelayoade/dotmac_starter_mt` only and declares metadata read, contents
write and pull-requests write. A direct proof authenticated a newly generated
key, minted an unrestricted installation token, enumerated exactly Starter and
revoked the token.

The key's canonical pointer is
`bao://secret/dotmac/github/release-recorder#private_key`. Its GitHub
projection is protected environment `registry-release`: variable
`RELEASE_RECORDER_CLIENT_ID` and secret `RELEASE_RECORDER_PRIVATE_KEY`.
Repository-level inputs and the previous App key remain a temporary rollback,
not a second authority; the release captain removes both only after one
legitimate release opens its App-authored record PR and triggers required CI
without manual intervention. Because GitHub settings are mutable external
state, the release captain refreshes this observation before that dispatch.

## Decision amendment — 2026-08-26 (automated package publication)

Michael retired the human-review queue for **package publication**. This
amendment supersedes only the human-approval and independent record-PR review
requirements in the 2026-08-23 amendment; it preserves the authority split,
credential scopes, build-once rule, exact-main guard, registry install-back,
tag-after-verification order, durable record, strict required CI and no-bypass
branch protection.

`registry-release` and the retained `pypi-release` environment are now
main-only credential boundaries with zero required reviewers and zero wait
timer. An explicit dispatch does not publish merely because it was requested:
the workflow must still prove the run is the exact protected-main revision,
resolve a closed allowlist entry, match the exact declared version, inspect and
smoke the immutable artifact, re-check current main immediately before the
registry write, install the published bytes back, and verify them before
tagging. A failure at any seam remains closed and visible.

The recorder App opens the mechanical release-record pull request and enables
squash auto-merge. It cannot waive branch protection; the record lands only
after the complete required-check set succeeds. The App retains contents and
pull-request write only and receives no Actions, deployment, environment or
administration permission. The ordinary tag-writing workflow token remains
exactly contents-write. The repository-wide Actions PR switch is enabled, but
cannot expand that job's explicit token permissions.

The checked-in mutable-settings contract is
`.github/release-environments.json`. Repository tests validate that contract
and release-workflow coverage; they do not claim to inspect GitHub's live
settings. The release captain reads the live settings back after each change
and whenever a package release unexpectedly waits.

This decision does **not** authorize unattended production deployment.
Production remains behind a named human approval until the owning product
accepts a separate, dated deployment decision with deployment-specific
evidence and rollback controls.

## Decision amendment — 2026-09-01 (publisher and verifier are separate)

The kernel publisher owns **build and publish only**. It builds one wheel and
one sdist, retains those exact bytes, and uploads them under a scoped registry
writer. It has contents-read authority, cannot tag, cannot open or write the
release record, and does not verify its own upload.

An independently dispatched verifier binds the original first-attempt
publisher run, retained-artifact id, exact protected-main source and the
historical release authorization whose immediate child allocated that source.
Its read-only job retrieves the retained bytes through GitHub and the named
registry bytes through the non-admin `ci-reader` identity, compares every byte,
and clean-installs the wheel and sdist separately with only their declared
dependencies. The same workflow's subsequent tag job independently re-derives
the historical authorization, reasserts current protected main immediately
before mutation, and is the sole owner of the annotated tag and mechanical
record PR. It holds contents-write but no registry writer.

Both jobs emit closed canonical receipts. Actions retains retrieval copies,
but the record PR projects their non-secret coordinates, receipt digests,
canonical provider identities and both filename/size/sha256 tuples into one
immutable checked-in `KernelReleaseEvidence.v1` file per version. From a101,
the annotated tag set and this record set are bijective and CI validates each
record against the live tag oracle. The release freeze continues until that
record reaches protected main.

After the publisher has created the retained artifact, that version's bytes
must never be rebuilt by rerunning the publisher. A pre-artifact failure burns
the alpha and starts a newly authorized successor. A post-artifact failure is
resumed only from those retained bytes through a separately reviewed no-build
publication path. Kernel a100 predates this corrected facility: it is
published and tagged but remains unadoptable because the clean artifact import
fails. Kernel a101 is the first release eligible to traverse the separated
facility end to end.

## Decision amendment — 2026-09-16 (bind the publisher to built bytes)

The uncredentialed kernel build job records the SHA-256 of its exact wheel and
sdist **after** distribution inspection and the wheel smoke. The credentialed
publish job accepts only those two filenames and recomputes both hashes from
the downloaded Actions artifact before using the Forgejo writer. A missing,
malformed, extra or changed artifact fails before the upload; the publisher
never repairs a mismatch by rebuilding. This closes the
build-job-to-publish-job handoff, not the separate question of what the registry
ultimately serves.

The independently dispatched verifier remains the sole registry read-back
decision: it compares both retained build files with the named registry files,
clean-installs them, and supplies the immutable per-version release record.
Neither a green publisher job nor a matching build-job output substitutes for
that verifier, and this new handoff check does not retroactively establish
provenance or token identity for earlier releases.

## Follow-ups

1. Stand up per `deploy/forgejo/RUNBOOK.md`; publish + verify `dotmac-kernel
   0.1.0a1`.
2. Pin Vendor CP and Sub to `dotmac-kernel==0.1.0a1` from the Forgejo index.
3. Decide the self-hosted-runner + OIDC→OpenBao hardening (removes the GitHub
   environment secret).
4. A future ADR governs any move of Git/CI authority off GitHub — out of scope here.
