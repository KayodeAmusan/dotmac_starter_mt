# Exposure rehearsal — Lane 3, the plan and its prerequisites

> **Addresses redacted 2026-10-05** at the owner's direction: this is a public
> repository and these were live production estate addresses. Each redaction
> names the address's ROLE. The role → address mapping, which keeps this record
> checkable as evidence, is held privately in the Dotmac Knowledge record
> `dotmac-estate-address-redaction-map-2026-10-05`. The original values remain
> in this repository's public Git history; redaction does not withdraw them.


**The status table moved.** It is now GENERATED at
`docs/inventories/deployment-exposure-rehearsal-status.md`, from
`RehearsalReceipt.v1` when a run exists and from
`deployment-exposure-rehearsal-baseline.json` before one does. `make
rehearsal-status-check` fails if the committed file drifts from its source.

This file keeps the PLAN, the role definitions and the prerequisites. It no
longer keeps a tally, and that is the fix rather than a tidy-up.

## Why the tally had to stop being written by hand

The 2026-08-29 revision opened with *"RUN. 14 of 16 items CLOSED."* Its own
result table, three lines below, recorded four items **partial** and one
**n/a**. Fourteen was reached by counting those as closed.

Both halves were written by hand into one file, so nothing could catch the
contradiction. The generated document computes its heading, its rows and its
tally from one list, and `verify_publication` reads the receipt rather than the
document — so a hand-edited table can no longer make a release pass, and a
summary can no longer disagree with its own evidence.

**Only `executed_passed` satisfies publication.** `hand_measured` and `vacuous`
exist as their own statuses precisely because the old count folded them in: a
hand-driven step proves the operator can do it, not that the controller can, and
a check whose fixture derives nothing observed nothing.

## The Foundation bytes under rehearsal

Lane 3 resolves the candidate repository, Actions run, artifact ID and SHA-256
only from the committed `CandidateArtifact.v1`. It fetches and verifies both
recorded distribution files, installs the wheel into an isolated environment,
and runs the controller through that interpreter. The artifact digest written
to `RehearsalReceipt.v1` is the digest from that same receipt; no dispatch input
can supply it. The publication oracle parses the rehearsal receipt with the
same candidate wheel before those bytes become reachable by the publisher.

This is the binding between "the code passed Lane 3" and "these are the bytes
being published." A rehearsal that imports
`packages/dotmac-deployment-foundation/src` from its checkout is a source
rehearsal, even if it carries a
candidate digest in its output, and does not satisfy the lane.

## Historical result — superseded by the generated status document

| Item | Result |
|---|---|
| 1 apply under the product deployment lock | **closable only by hand** — the 2026-08-29 run applied with `up -d --force-recreate` from a shell. The controller path now exists (`cmd_exposure_apply --execute` → `ComposeHostExposureEffects` → `ExposureTransaction`) but has never been run against a host |
| 2 pre-change snapshot (`HostObservation`) | **closable only by hand** — a pre-state was captured by shell, not by `ExposureTransaction.run` |
| 3 non-recreating apply REFUSED | **closable only by hand** — `refuse_non_recreating_apply` has unit coverage; it has never refused a real invocation |
| 4 socket re-observation | **CLOSED** — 18443 on `127.0.0.1` AND `[::1]`; 18445 on `127.0.0.1` only; no `0.0.0.0:`, no `[::]:` |
| 5 `docker-proxy` PIDs new, one per family | **CLOSED** — 1136702 / 1136709 / 1136725 |
| 6 firewall re-observation | **VACUOUS under this fixture** — every publication is `loopback` or `none`, so the derived plan is empty by construction. Not a pass: nothing was observed because nothing was derived |
| 7 inert v6 chain fixture | **BLOCKED** — needs a `private` publication (see the prerequisite below) |
| 8 rollback, provoked | **closable only by hand** — teardown restored the pre-state, but no PROVOKED transactional rollback was driven |
| 9 digest equality | **NOT CLOSED — two of three terms.** The gate is `descriptor == authorized plan == VerificationReport.descriptor_digest`. `sha256:9b748af9…` was shown identical across the descriptor's canonical document and the verification report; there was no authorized plan, because nothing can issue one (prerequisite 2). The 2026-08-29 entry recorded this as CLOSED, which is the same over-count as the header |
| 10 `exposure = "none"` emits no socket | **CLOSED** — 18444 absent from `ss` |
| 11 target closed-port behaviour | **CLOSED** — Role A **RSTs**; re-measured 2026-08-30 at 5-8 ms per refusal |
| 12 privileged-vantage refusal on a real probe | **CLOSED** — see below |
| 13 IPv6 external negative | **CLOSED for the 2026-08-29 fixture only** — and NOT re-closable today: the containers are gone, so a refusal now measures an absent service rather than a loopback bind. It re-opens with the fixture |
| 14 IPv6 external positive control | **CLOSED** — re-measured 2026-08-30, `tcp/22` over IPv6 to Role A: OPEN |
| 15 IPv4 external negative + positive control | **positive control CLOSED** (re-measured 2026-08-30, `tcp/22` over IPv4: OPEN); **negative re-opens with the fixture**, same reason as item 13 |
| 16 `private` reachable from inside its source set | **BLOCKED** — same prerequisite |

**Closed: 4, 5, 10, 11, 12, 14, and the positive-control halves of 13-15 — 8
items.** **Closable only by hand today: 1, 2, 3, 8** — the four a controller
must originate, named as a distinct category deliberately. **Blocked: 7, 9,
16.** **Vacuous: 6.**

Item 9 moved out of the closed column while this was being written, and the
reason is worth keeping: the digest-equality gate has three terms and the
recorded evidence had two. Two thirds of an identity check is not a weaker pass,
it is a different check.

## 2026-08-30 re-measurement, and the three prerequisites that remain human-only

Everything in this section was measured on 2026-08-30, read-only, and the
commands are named so the next reader re-runs rather than trusts.

### Role B is now a materially BETTER vantage than the retraction described

The 2026-08-29 retraction rested on a second NIC (`eth1 10.0.0.4/22`) routing
into the `idp-ha` private network. **That NIC is gone.** Measured with
`ip -br addr`, `ip rule show` and `ip route show table all`:

```
lo    UNKNOWN  127.0.0.1/8 ::1/128
eth0  UP       [redacted 2026-10-05: probe vantage IPv4]/20 [redacted 2026-10-05: probe vantage IPv6]/64 [redacted 2026-10-05: probe vantage link-local, MAC-derived]/64
```

No `eth1`. No tunnel, wireguard, tun, tap, gre, vti or ipip device. Policy
routing is the stock three rules (local/main/default) with no extra table. No
Docker. No `/opt/openbao` and zero `BAO`/`VAULT` environment variables.

Both paths to Role A leave via `eth0`, checked per family.

> **SUPERSEDED 2026-09-04 — these measurements name the retired target.** They
> were taken against `[redacted 2026-10-05: shared rehearsal host IPv4]`, which is no longer Role A. They are kept
> as the RECORD OF WHAT WAS DONE and must not be read as current: the new
> target's public IPv4 is `[redacted 2026-10-05: rehearsal target public IPv4]` and its IPv6 is
> `[redacted 2026-10-05: rehearsal target IPv6]`, and neither has been routed from this vantage. The
> replacement numbers are deliberately absent rather than transcribed from the
> new addresses — a routing result is a measurement, and writing one that
> nobody took is the failure this whole document exists against. Re-run both
> queries from the outside vantage and replace this block with what they
> return.

```
ip route get [redacted 2026-10-05: shared rehearsal host IPv4]          -> via [redacted 2026-10-05: probe vantage gateway] dev eth0 src [redacted 2026-10-05: probe vantage IPv4]
ip -6 route get [redacted 2026-10-05: shared rehearsal host IPv6] -> via fe80::1 dev eth0 src [redacted 2026-10-05: probe vantage IPv6]
```

**One caveat, recorded rather than glossed.** The old third line —
`ip route get 10.0.0.2 -> dev eth1` — was the control proving the routing query
DISCRIMINATES rather than always answering `eth0`. With the NIC detached that
query now answers `eth0` like everything else, so that particular control no
longer discriminates. The interface enumeration above replaces it: with exactly
one non-loopback interface and no policy routing, there is no other path for a
query to select. That is a weaker form of the same assurance and is stated as
such.

### The probe pass, with both positive controls

From Role B to Role A, one run, 2026-08-30:

```
v4 22     OPEN               12ms      <- IPv4 POSITIVE CONTROL
v4 18443  refused/filtered    7ms
v4 18445  refused/filtered    8ms
v4 18444  refused/filtered    8ms
v6 22     OPEN                7ms      <- IPv6 POSITIVE CONTROL
v6 18443  refused/filtered    7ms
v6 18445  refused/filtered    5ms
v6 18444  refused/filtered    7ms
```

Both positive controls fired, so the probe fired. Sub-10 ms refusals confirm
Role A **RSTs** rather than DROPs, which re-closes item 11 independently of the
2026-08-29 measurement.

**The six refusals are NOT evidence for items 13 and 15, and counting them would
be the error this lane exists to prevent.** The 2026-08-29 fixture containers no
longer exist: all four containers on Role A are `Exited (255)` and no Compose
project is up. A refusal on a port where nothing is listening measures an absent
service, not a loopback bind. Items 13 and 15's negative halves re-open with the
fixture and can only be closed in the same run that applies it.

### Prerequisite 1 — there is no exclusive-lease mechanism to obtain

`"Exclusive lease and no concurrent host mutations"` is the first clause of the
clean-target definition, and **no mechanism implements it.** `/var/lock` on Role
A holds only `lvm/` and `subsys/` — no lease file, no convention, nothing to
take. Meanwhile the host carries eleven other agents' worktrees under `/root`
(`dotmac-erp-foundation-*`, `dotmac-sub-money-*`, `dotmac-starter-money-*`,
`codex/`, and others) and four other agents' stopped containers.

A lease cannot be self-granted, and "no concurrent mutations" cannot be verified
from inside: `who` was empty at the moment of measurement, which says nothing
about the next minute. **Only a human can quiesce the other lanes and declare
the window.** This is a human-only prerequisite, not a task.

### Prerequisite 2 — nothing can issue the authorization the rehearsal binds to

This is the substantive finding, and it is a design gap rather than a missing
feature.

`dotmac-deployment-control` is a LIBRARY module. Its own `EXTRACTION.toml`
records composition into `dotmac_vendor_control_plane` but states that
production adoption is explicitly not claimed, and **no Control instance is
deployed anywhere that can propose or approve a plan.** Three consequences:

1. There is no authorization/run ID, so a controller identity has nothing to be
   BOUND to. The binding is the whole point of the requirement — an unbound
   short-lived key is just another shared key with a shorter life.
2. **Item 9 has no middle term.** The gate is
   `descriptor == authorized plan == VerificationReport.descriptor_digest`. With
   no issued plan there are only two terms, and the 2026-08-29 entry closed it
   on `descriptor == report`. That is a real equality and it is not this one.
3. `AuthorizationReceipt` (added in this change) is therefore a contract with no
   producer yet. That is the correct shape — Foundation must never mint its own
   authorization — but it means the receipt leg of the binding is *declarable*
   and not yet *satisfiable*.

Foundation must not close this by generating its own receipt. Per ADR-0070 the
authorization state belongs to Control, and a facility that manufactures the
approval it then checks has verified nothing.

#### 2026-09-05 — the prose above was true and the CODE contradicted it

This prerequisite has read "nothing can issue the authorization" since
2026-08-30. `scripts/exposure_rehearsal_runner.py` shipped anyway with
`--authorization-run` and `--authorization-doc-digest` as `workflow_dispatch`
TEXT, and executed on them. The only comparison ever made was
`lease.covers(authorization_run_id=...)` — a string equality against a lease
record the same operator writes. The digest was compared to nothing at all until
`build_receipt` asserted it equalled the descriptor digest, which is a value any
caller computes locally from a file in this repository. Nothing imported
`provenance.py` or `authorization.py`; no `VerifiedAuthorization` and no
`ExecutionGrant` were ever constructed.

So the two matching strings LOOKED like a binding while no authorization existed
anywhere, and the lane could be driven green on a fabricated run id. A document
that says "blocked" beside code that says "green" is worse than either, because
the reader who checks the run believes the code.

`scripts/lane3_authorization.py` is now the single owner of the question, asked
before the lease is taken and before the host is contacted, with the same three
statuses the repository's other gates use: **0 attested / 1 refused / 2 the
question could not be answered.** It answers 2 today, and the workflow refuses on
it. The lane is now EXPLICITLY BLOCKED rather than unmonitored, which is the
whole of what this change claims — no verification chain was built and none
could be.

`--authorization-doc-digest` is gone from the runner and from the dispatch
inputs rather than deprecated: an argument that names proof and supplies none is
the defect itself. The signed DOCUMENT replaces it (`--authorization-document`),
resolved on the control runner beside the controller key so no dispatcher hands
the lane its own proof.

**The preconditions for real verification, enumerated.** The list lives in code
as `PRECONDITIONS` in that module — a refusal is built from it, so an entry
cannot rot into decoration — and each was measured rather than assumed:

| # | Precondition | Owner | Measured 2026-09-05 |
|---|---|---|---|
| 1 | An implementation of `provenance.AuthorizationVerifier` (`attest(material) -> Mapping`) carrying Platform CP's trust roots. The Foundation ships none by design (zero runtime dependencies, ADR-0070); a weak substitute would read as coverage | the assembly — the only party legitimately depending on both Control and the Foundation | none exists in any repository under `management/` |
| 2 | It is declared as ONE `dotmac_deployment_foundation.execution_bindings` entry point, installed into the candidate venv the runner executes in | the assembly's bindings distribution | zero declarations of that group fleet-wide |
| 3 | The signed authorization DOCUMENT reaches the runner, not only a digest of it — a verifier attests BYTES, and a digest of bytes nobody holds can only be compared against a digest the same caller chose | Platform CP, and the workflow that carries it | the dispatch supplied a digest as free text; the document never reached the runner |
| 4 | A translator between the issuer type and the verifier type. Control issues `AuthorizationStatementV2` (schema `dotmac.deployment-authorization` v2); `AuthorizationReceipt.from_document` requires 14 named keys and REFUSES unknown ones | the assembly; neither side may normalize the other's document | against `dotmac-deployment-control` at the peeled `a11` tag: ~18 keys the receipt rejects as unknown, 5 required keys the statement does not carry, and `control_plan_digest` has no producer on either side |
| 5 | A published Foundation carrying the verifying code — `verify_authorization`, `authorize`, `discover_bindings` — inside the wheel Lane 3 installs, not in the checkout beside it | the Foundation's release pipeline | that code reached the one `0.4.0a1` candidate (run `33920058598`, artifact `9954731961`, source `753a004e7f8dbab034d5d6ca565c680d931a5309`), but its receipt was never committed and the facility source later drifted; the candidate is inadmissible and Foundation remains unpublished beyond `0.2.0a2` |
| 6 | Gate item 9's middle term is `ExecutionPlanDigestV1` (`AGENTS.md` rule 49), explicitly NOT the descriptor digest and NOT the authorization-envelope digest | the Foundation's `rehearsal.py` with this lane's runner — **not repaired here** | `build_receipt(require_same_digest)` forces all three terms equal, so the middle term can only ever be the descriptor digest — the degenerate two-term shape its own docstring warns about |

Entries 1, 2, 3 and 5 are observable from the runner's own environment and a
refusal cites them by code. Entries 4 and 6 are STATED and not enforced, and the
list says so: a stated requirement is not an enforced one, and conflating the two
is the checklist-as-coverage failure ADR-0018 names.

Item 9 is therefore still not closable, and the reason has changed shape rather
than gone away. The authorized-plan term now comes out of an attested receipt
instead of off the command line — provenance, not a new fact — and it is still
not the middle term rule 49 defines. Precondition 6 is where that is recorded.

### Prerequisite 3 — the controller identity is a credential act on a shared host

Attribution today is impossible and measurably so: `/root/.ssh/authorized_keys`
on Role A holds exactly **two** keys, `seabone@hp-server` and
`michaelayoade@macboos-MacBook-Pro.local`. Every agent authenticates as one of
them, so no artifact on that host can be attributed to any actor — which is
precisely why a rehearsal run under a shared key cannot prove the CONTROLLER did
it, only that somebody did.

The access path to the registered control runner was verified 2026-08-30 and is
**indirect**: `[redacted 2026-10-05: control runner public IPv4]:22` is source-restricted and is NOT reachable from
the workstation (connect times out). It IS reachable from `seabone`
(`[redacted 2026-10-05: seabone jump host IPv4]`, explicitly in the runner's allow set), which authenticates
successfully as `dotmac@dotmac-control-runner`. So the runner is usable, via
seabone, once an identity exists to use.

Creating, installing and later removing a dedicated credential on a shared
multi-agent host is a provisioning act, and it was placed under review. It stays
there.

### Proposed deletions: the set is EMPTY

The rule is *"remove only exact, labelled rehearsal-owned objects"*. Measured
against every Docker object on Role A:

| Object class | Count | Labelled as Foundation-rehearsal-owned |
|---|---|---|
| containers (all stopped) | 4 | **0** — and their label maps are EMPTY, lost in the 2026-08-29 reboot, so they cannot be attributed by label at all |
| volumes | 24 (20 dangling) | **0** — every one carries only `com.docker.volume.anonymous` |
| networks | 1 non-default (`erp-fin-perms-0778-net`) | **0** |
| images | 12 | **0** by label |

`docker ps -aq --filter label=dotmac-exposure`, and the equivalent volume and
network filters for `com.dotmac.rehearsal`, all return zero.

**Nothing qualifies for deletion. No deletion is proposed and none is needed.**
The four containers and the stray network are ERP/codex work belonging to other
lanes; `dotmac-df-image-audit-a2-test:6a8fdb03` is identifiable as a Foundation
artifact by NAME but not by LABEL, and a name is not the stated criterion.

This is the right outcome rather than a shortfall. Under the amended definition
foreign state is the INSTRUMENT: the requirement *"prove apply and rollback
without replacing unrelated host state"* is only falsifiable if unrelated state
is present. **Nominated preservation canaries**, to be captured byte-identical
before, after apply and after rollback:

- the 4 stopped containers, by ID and status;
- `erp-fin-perms-0778-net` and its subnet;
- the 24 volume names;
- host `postgres` on `127.0.0.1:5432` / `[::1]:5432` and `redis` on
  `127.0.0.1:6379` / `[::1]:6379` — real foreign sockets, and the two the
  verifier should also flag as `undeclared_socket`;
- `iptables-save` and `ip6tables-save` in full.

Both shared chains were measured **empty** on 2026-08-30 (`DOCKER-USER` v4 and
v6 hold zero rules; `INPUT` v6 policy `ACCEPT`, zero rules; zero rules carry a
`dotmac-exposure` comment). Firewall canaries therefore have to be *introduced*
to be meaningful, which is a decision for the run rather than an observation.

### The controller-identity bootstrap plan — for review, not executed

**Why it is needed, measured.** `/root/.ssh/authorized_keys` on Role A holds
exactly two keys, `seabone@hp-server` and
`michaelayoade@macboos-MacBook-Pro.local`. Every agent authenticates as one of
them, so no artifact on that host can be attributed to any actor. A rehearsal
run under a shared key cannot prove the CONTROLLER did it — only that somebody
did — which is the difference between a procedurally and an evidentially
controller-driven run.

**Access path, verified 2026-08-30.** `[redacted 2026-10-05: control runner public IPv4]:22` is source-restricted
and NOT reachable from the workstation (connect times out). It IS reachable from
`seabone` (`[redacted 2026-10-05: seabone jump host IPv4]`, explicitly in the runner's allow set), where
`ssh dotmac@[redacted 2026-10-05: control runner public IPv4]` succeeds as `dotmac-control-runner`. So the runner
is usable indirectly; what is missing is an identity, not a route.

**The bootstrap, in order. Every step is a proposal.**

1. **Obtain the authorization/run ID first.** The credential is bound to it, so
   it cannot be minted before the thing it binds to exists. This is blocked by
   prerequisite 2 — no deployed Control issues one. Nothing below should run
   until that is resolved, because an unbound short-lived key is just another
   shared key with a shorter life.
2. **Generate on the runner, never on the workstation.** `ssh-keygen -t ed25519`
   in a `root`-owned `0700` directory on `dotmac-control-runner`, comment
   `dotmac-foundation-rehearsal:<run-id>`. The private half never leaves the
   runner and is never read by an agent. Per the secrets rule the key is named
   by POINTER only; no path here is a value.
3. **Record the fingerprint before use.** `ssh-keygen -lf <pub>` — SHA256, into
   the rehearsal record, alongside the run ID. A fingerprint recorded after the
   run proves nothing about what ran.
4. **Install restricted, not bare.** Append to Role A's `authorized_keys` with
   `restrict,from="<runner address>",command="<the single rehearsal entry
   point>"`. `restrict` is the deny-all default; `from=` scopes it to the
   runner; `command=` makes it incapable of an interactive shell. A key that can
   do anything proves only that a key was used.
5. **Prefer WireGuard for the transport.** The runner already reaches Observer
   as `[redacted 2026-10-05: WireGuard peer address]` over CGNAT space chosen so the tunnel does not inherit a
   broad `10.0.0.0/8` accept. Extending that shape to Role A keeps the
   `from=` restriction meaningful against a stable inside address. Note the
   runner's egress output chain is `policy drop` with `ip protocol icmp accept`,
   so a successful ping there proves nothing about TCP — the reachability check
   must be a TCP connect.
6. **Remove it at the end, and prove removal.** Delete the line, re-read
   `authorized_keys`, and record the resulting fingerprint set. "Removed" is a
   claim; the post-removal key list is the evidence.

**What this does not solve.** It makes the rehearsal's own actions attributable.
It does not make the two pre-existing shared keys attributable, and it does not
retroactively attribute anything already on the host — including the four
stopped containers, whose label maps were emptied by the 2026-08-29 reboot.

### What this changes about items 7 and 16

The 2026-08-29 rationale for BLOCKING them was specific: *"a snapshot-restoring
rollback replays the chain state captured before the run, so a rule another
agent added during it is deleted by the rollback"*.

**That mechanism no longer exists.** `ComposeHostExposureEffects` never flushes
and deletes only rules bearing its own ownership comment, and as of this change
`ExposureTransaction` independently measures the foreign rules before and after
and refuses if any vanished. The data-loss path the block was protecting against
is gone in code.

Items 7 and 16 therefore remain blocked on prerequisites 1-3 — the lease, the
authorization issuer, and the controller identity — and **no longer on the
rollback mechanism**. That is a narrowing, and it is a decision for Michael
whether the narrowed set is satisfiable in one authorized window.

### The external proof, item 13-15

From Role B, all in one run:

```
IPv4 POSITIVE CONTROL  ssh/22 over IPv4            OPEN
  18443 / 18445 / 18444 over IPv4                  refused
IPv6 POSITIVE CONTROL  ssh/22 over IPv6            OPEN
  18443 / 18445 / 18444 over IPv6                  refused
```

Both positive controls fired, so the six refusals mean "not reachable" rather
than "the path is broken". This is the release's central claim, measured: an
IPv6 socket declared loopback refusing the internet.

### The trap, reproduced live — item 12

Same port, same minute, two vantages:

```
workstation (inside [redacted 2026-10-05: estate public /22]) -> ERP 9001 : OPEN
Role B      (outside every allowlist) -> ERP 9001 : refused
```

`accept_public_exposure_evidence` then **refused** the workstation result,
refused an unenumerated vantage, and **accepted** Role B — the negative control
that stops the refusal being a blanket ban. Unit coverage proves the function
refuses a constructed vantage; this proves it refuses the actual connection
that produced two false P0 escalations.

### What the run also found

**The verifier fired `undeclared_socket` on two sockets belonging to other work
on the shared host** (`127.0.0.1:55439`, `127.0.0.1:5434`). Correct behaviour,
and the other-direction sweep earning its place: a verifier that only walks the
descriptor cannot see the port the descriptor does not mention.

**Role A is not a clean host, and this is now a PREREQUISITE rather than a
preference.** It carries four containers from other agents' work, which the
plan below asks it not to. That cost nothing in this run only because the
fixture derives no firewall rules at all — every publication is `loopback` or
`none`.

Items 7 and 16 need a `private` publication, and a `private` publication writes
port-scoped rules into **shared** chains. Two consequences, and the second is
the one that bites: a snapshot-restoring rollback replays the chain state
captured before the run, so a rule another agent added *during* it is deleted
by the rollback rather than by anything anyone reviewed. **Do not attempt items
7 or 16 on the current Role A.** They need a host carrying nothing else.

**nginx cannot start under the facility's `read_only: true`** without a tmpfs
for `/var/cache/nginx`. Correct hardening, and the reason the fixture uses a
server that writes nothing.

---

The rest of this document is the plan the run followed.

`deployment-foundation-rehearsal.md` describes Lanes 1 and 2 and remains the
record for them. This is a third lane because it proves a different thing:

| Lane | Proves |
|---|---|
| 1 — the written suites | the code does what its own tests say |
| 2 — the disposable host | a real engine, database, ingress handoff, restore and observability loop |
| **3 — exposure** | **that the declared exposure semantics hold against a real socket, from a vantage that can actually falsify them** |

## Why Lane 1 cannot close this gate

`IngressPolicy.v1` and the `exposure` verifier are complete and tested, and
every one of those tests supplies its own observation. `ProbeResult` and
`ProbeVantage` are typed INPUTS a caller provides; the facility performs no
network I/O and holds zero runtime dependencies, which is correct for a build
runner and is also the whole limitation. **Nothing has yet compared the
semantics against a socket that a kernel opened.**

The specific claims that unit tests cannot settle:

- that a rendered `host_ip` produces the socket the renderer believes it does,
  on both families;
- that `docker-proxy` binds what the long-syntax entry says, and that the
  process is a NEW one rather than a survivor of the previous container;
- that an `ip6tables DOCKER-USER` rule is inert in the way measured, rather
  than in the way described;
- that a rollback restores an observed state on a host, not in a fake;
- that a probe from outside every applicable allowlist reaches, or does not
  reach, what the plan says.

## The two roles

**Authorization for one does not imply authorization for the other, and the
plan is invalid if they are the same host.** Each is requested separately
below, with its own status.

### Why the vantage cannot be the target

This is not bureaucracy. Both failures happened on this fleet on 2026-08-29.

- **A probe originating on the machine under test proves nothing about
  external reachability.** It never leaves the host's own stack, so it cannot
  distinguish a loopback bind from a routable one — which is the single fact
  the whole lane exists to establish.
- **A probe from inside an allowlist proves nothing about public
  reachability.** The workstation sits inside `[redacted 2026-10-05: estate public /22]`, which several
  of this fleet's `DOCKER-USER` allowlists ACCEPT. Two agents independently
  connected to "public" ports from it and each escalated a P0 that did not
  exist. The connections were real; the conclusion was not.

`ProbeVantage.membership_established` encodes the second one: a vantage that
has not been enumerated against the target's rule set cannot conclude anything,
and the verifier refuses rather than assuming it is outside.

### Role A — disposable execution target — **AUTHORIZED: `lane3-rehearsal-target`**

**Status: retargeted by Michael, 2026-09-04.** VM 102 was rebuilt as a
genuinely disposable target, with a verified safety backup taken beforehand:

| | |
|---|---|
| name | `lane3-rehearsal-target` |
| size | 4 GiB memory, 40 GiB disk |
| private IPv4 | `[redacted 2026-10-05: rehearsal target private IPv4]` |
| public IPv4 | `[redacted 2026-10-05: rehearsal target public IPv4]` |
| IPv6 | `[redacted 2026-10-05: rehearsal target IPv6]` |

**The previous authorization named `[redacted 2026-10-05: shared rehearsal host IPv4]` and is withdrawn.** That
address is the shared dedicated test server — `CONTRIBUTING.md` and `AGENTS.md`
both name it in that role, and they are correct to. A lane that induces a
genuine apply-path failure and an automatic rollback cannot run on a host other
agents are working on, and "disposable" and "shared workspace" cannot both be
true of one machine. Any surviving `[redacted 2026-10-05: shared rehearsal host IPv4]` in a Role A sentence is
stale and must not be read as authorization.

**PRECONDITION — SLAAC suppression, and it is not incidental.**
`/etc/netplan/99-lane3-no-slaac.yaml` (`accept-ra: false`) is what makes the
target egress IPv6 from the declared `[redacted 2026-10-05: rehearsal target IPv6]`. Without it the target
egresses from a SLAAC address, and then the far-end observation — the one that
replaces the `__TARGET_OBSERVED_V6__` sentinel — **passes while measuring the
wrong thing**: it reports an address nobody declared, and reports it
confidently. That is the exact failure the sentinel repair exists to close, so
this file is a precondition of an existing gate rather than a note about setup.

**The sysctl approach looked correct and did not survive a reboot**, and the
next person to hit this will reach for sysctl first. Netplan owns the interface,
so a sysctl drop-in is reverted the moment netplan re-applies. The netplan file
was proved across a second reboot with the static default route intact. A
rehearsal that re-images the target or re-runs cloud-init must re-establish it
before the far-end observation means anything.

**HAZARD — the private address is three away from production ns1.**
`[redacted 2026-10-05: production ns1 private IPv4]` is production ns1 and `[redacted 2026-10-05: rehearsal target private IPv4]` is this target: the same
/24. A static assignment typo or a DHCP collision lands the rehearsal on a
production nameserver, and this lane rewrites firewall chains. The rebuilt VM
must never boot with `[redacted 2026-10-05: production ns1 private IPv4]`. Measured 2026-09-04: no file in this
repository contains `[redacted 2026-10-05: production ns1 private IPv4]`, or any `[redacted 2026-10-05: production private /24]` address at all,
and nothing here can supply one — `--target` is `required=True` with no default
and the Lane 3 descriptor deliberately holds no address. So the repository is
not a source of that mistake; the machine build is where it has to be prevented.

**What is still missing is an ACCESS PATH, not an authorization.** This
repository carries no SSH configuration entry and no reference to that address,
so the connection user and the key's location have to be supplied before
anything runs. Guessing either is the "never infer a target" mistake with an
extra step. Per the secrets rule the key is named by POINTER, never by value.

Where the plan is applied, snapshotted, re-observed and rolled back.

| Requirement | Why |
|---|---|
| disposable, and not carrying any other Dotmac service | the lane deliberately opens and closes real sockets and rewrites firewall chains |
| Docker with the Compose v2 plugin | long-syntax publication and `up -d --force-recreate` |
| **IPv6 enabled on the daemon and on the host** | the entire IPv6 half of the contract is unfalsifiable without it, and this is the half that was actually open in production |
| root, for `iptables`/`ip6tables`/`ss` | the derived rules and the re-observation |
| out-of-band recovery (console or equivalent) | the lane writes INPUT rules; a mistake that locks SSH out must be recoverable without SSH |
| a recorded pre-state | `iptables-save`, `ip6tables-save`, `ss -tlnp` and `docker ps` captured before anything runs |

**What the target must be able to do:** apply the authorized plan under the
deployment lock, hold a pre-change snapshot, re-observe its own sockets,
`docker-proxy` processes and firewall chains, and roll back to the snapshot.

### Role B — independent IPv6-capable external probe vantage — **`[redacted 2026-10-05: probe vantage IPv4]`**

**Status: usable for Role A, and NOT yet a general external vantage.**
Sources: v4 `[redacted 2026-10-05: probe vantage IPv4]`, v6 `[redacted 2026-10-05: probe vantage IPv6]`.

The general claim "outside every Dotmac allowlist" is **RETRACTED**. It was
established by refusals measured only over public transport, and the host holds
a **second NIC** — `eth1 10.0.0.4/22`, routing into the `idp-ha` private
network and reaching both nodes there. A vantage that is untrusted publicly and
inside the perimeter privately is the more dangerous shape, not a lesser one:
its refusals read as proof of isolation that the private path never had to
satisfy.

**Standing rule until that NIC is detached: probe from this host only where
`ip route get <target>` shows the path leaving via `eth0`.**

For Role A that was established, measured rather than assumed — **against the
retired target, and therefore superseded on 2026-09-04.** The queries below
name `[redacted 2026-10-05: shared rehearsal host IPv4]`; the new Role A is `[redacted 2026-10-05: rehearsal target public IPv4]` /
`[redacted 2026-10-05: rehearsal target IPv6]` and has not been routed from this vantage. Re-run and
replace rather than editing the addresses in place, because the arrow's
right-hand side is a result and not a restatement of its left.

```
ip route get [redacted 2026-10-05: shared rehearsal host IPv4]        -> via [redacted 2026-10-05: probe vantage gateway] dev eth0 src [redacted 2026-10-05: probe vantage IPv4]
ip -6 route get [redacted 2026-10-05: shared rehearsal host IPv6] -> dev eth0 src [redacted 2026-10-05: probe vantage IPv6]
ip route get 10.0.0.2              -> dev eth1 src 10.0.0.4
```

The retired Role A was not in `10.0.0.0/22`, so the private NIC was not in the
path and contaminated nothing measured against it. **The new target needs that
re-established and the question is not identical:** it carries a private
address of its own, `[redacted 2026-10-05: rehearsal target private IPv4]`, which the retired one did not. That is
outside `10.0.0.0/22` so the same conclusion is likely, but likely is not
measured. The third line is the control: it
shows the routing query discriminates rather than always answering `eth0`.

#### The verification step this was missing

The original qualification probed *targets* and never enumerated the
*vantage*. Refusals over one transport were read as refusals over all
transports — which is the privileged-vantage trap inverted, and it was walked
into while writing the guard against it.

**Enumerate a vantage's interfaces and routes BEFORE trusting its refusals.**
`ip -br addr` and `ip route get` for each intended target, recorded alongside
the probe output. A refusal is scoped to the transport that carried it, and a
probe whose shape does not match the claim it is testing tells you about the
probe.

The target may still not stand in for it. A probe originating on the machine
under test never leaves that host's own stack, so it cannot distinguish a
loopback bind from a routable one — the single fact the external half exists to
establish. Using the target as its own vantage converts a two-role rehearsal
into a one-role one that looks complete, which is worse than not running it.

#### What was verified, and why the last line is the load-bearing one

| Condition | Evidence |
|---|---|
| global IPv6 with a default route | `[redacted 2026-10-05: probe vantage IPv6]/64`, default via `fe80::1` dev eth0 |
| IPv6 egress actually works | `[2606:4700:4700::1111]:443` and `[2001:4860:4860::8888]:53` both OPEN |
| **outside every Dotmac allowlist** | OpenBao `8200`, ERP `9001`, ERP `6391` all **refused** |
| **the refusals mean something** | **ERP `443` is OPEN from the same vantage** |
| holds no fleet credentials | no `/opt/openbao`, zero `BAO`/`VAULT` environment variables |
| can reach Role A | ~~`[redacted 2026-10-05: shared rehearsal host IPv4]:22` reachable~~ — **retired target; unmeasured against `[redacted 2026-10-05: rehearsal target public IPv4]`** |

**The fourth row is why the third can be believed.** Three refusals on their own
are equally consistent with a vantage that cannot reach anything — a broken
probe and a working allowlist produce identical output. One reachable Dotmac
port from the same source at the same time separates them. This is the same
target-specific positive control the probe plan demands, applied to the
vantage itself before the vantage is trusted to say anything.

That is what makes `membership_established` true for this host rather than
assumed: it was checked against the actual rule sets, in both directions.

**Status: not named, and it cannot be inferred from the target.** This is a
separate authorization request and, on present evidence, probably a
provisioning request.

**What the vantage must be able to do:** reach Role A's global IPv6 address
from outside every source set that could apply to it, and prove it did so
against Role A specifically rather than against the internet in general.

A **different machine**, and genuinely outside every source set that could
apply to Role A.

| Requirement | Why |
|---|---|
| **not** the workstation | its public IPv4 sits inside `[redacted 2026-10-05: estate public /22]`, which several of this fleet's allowlists ACCEPT — this is the exact vantage that produced two false P0s on 2026-08-29 |
| **not** `observe`, `s3` or `db-primary` | none has IPv6 egress, so none can run the IPv6 half at all |
| IPv6 egress, verified against Role A specifically | a vantage's own egress check does not prove the path to one target |
| its source address **enumerated against Role A's rule set before any probe** | `ProbeVantage.membership_established` is `False` until this is done, and the verifier refuses to conclude from an unestablished vantage |
| `nc` available | bash `/dev/tcp` does not exist in this shell and reads every port closed — a silent all-green |

### Why one had to be provisioned — kept as the record

Measured on 2026-08-29: **neither the workstation nor `observe`, `s3` nor
`db-primary` has IPv6 egress.** Only the product hosts do, and using production
as a probe source for a rehearsal is its own authorization rather than a
freebie — and a product host inside the fleet's own ranges is not a neutral
vantage anyway.

So Role B needed a host that did not exist, and one was provisioned:
`[redacted 2026-10-05: probe vantage IPv4]`, verified above. The requirement it was provisioned against —
**any disposable VM with IPv6 egress in address space outside every Dotmac
allowlist** — is kept here because it is the requirement any REPLACEMENT vantage
must also meet, and because "we already have a host with IPv6" is the shortcut
that would put a product host in this role.

The on-host `ss -tlnp` evidence remains valid and remains insufficient on its
own: it shows what the host bound, not what the internet can reach.

## The five artifacts publication is gated on

Distinct artifacts, produced by **the controller executing the exact signed
plan** — not by a script standing in for it. The proof is of the real path.

### 1. Apply

The controller applies the authorized plan under the product deployment lock.
Recorded: the plan identifier, the descriptor digest, the exact command, and
the pre-change snapshot (`HostObservation`) taken before anything mutated.

Refusals that must be exercised, not merely present: an apply whose command
cannot change a binding is refused (`docker compose restart` reuses the
container it has; a plain `up -d` does not recreate an unchanged image).

### 2. Re-observation

After apply, on Role A:

- `ss -tlnp` shows `127.0.0.1:<port>` and `[::1]:<port>` for a loopback
  dual-stack publication, and shows **neither** `0.0.0.0:<port>` nor
  `[::]:<port>`;
- the `docker-proxy` PID for the port is **new** — a surviving PID means the
  container was not recreated and the apply proved nothing;
- `iptables-save` and `ip6tables-save` are captured and parsed by
  `parse_iptables_save`, and the derived rules land in `DOCKER-USER` on IPv4
  and `INPUT` on IPv6.

### 3. Negative AND positive probes

From Role B, per family:

| Probe | Expected | What it establishes |
|---|---|---|
| **positive control** to Role A `tcp/22` on IPv4 | reachable | the v4 path from this vantage to THIS target works |
| **positive control** to Role A `tcp/22` on IPv6 | reachable | the v6 path to THIS target works — a vantage-egress check does not substitute |
| **negative** to the loopback-bound port, IPv4 | not reachable | the bind is what the render said |
| **negative** to the loopback-bound port, IPv6 | not reachable | the half that was actually open in production |
| **negative** to an `exposure = "none"` port | not reachable | no socket exists at all |
| **inside-vantage** probe from a host within a declared source set to a `private` port | reachable | the allowlist admits what it should |

The target-specific positive control is mandatory. Once the port under test is
closed, an unreachable result is indistinguishable from a broken path, and only
a control against the **same target** separates them. `tcp/22` served this
purpose on 2026-08-29.

Two fail-closed handling rules, both exercised:

- a probe whose vantage is inside an accepted source set, or whose membership
  was never established, must raise `PrivilegedVantageError` and must NOT be
  recorded as public-exposure evidence;
- silence from a host that DROPs closed ports yields `inconclusive`, never
  `absent`. Role A's closed-port behaviour is recorded before the lane runs —
  ERP silently DROPs and the SON host RSTs, so identical probe output means
  different things per host.

### 4. Rollback

Deliberately provoked, not simulated: apply a plan whose verification must
fail, and show the transaction restores the pre-change snapshot. Recorded: the
refusal, the restored chains, and a re-observation matching the snapshot.

### 5. Digest equality

The artifact that ties the other four together, and the one that fails most
quietly if it is skipped.

```
descriptor digest  ==  the digest inside the authorized plan
                   ==  the digest the post-apply verification report cites
```

`ProductDeploymentSpec.to_canonical_document().sha256_digest()`, the plan's
bound digest, and `VerificationReport.descriptor_digest` must be **byte-identical
strings**, recorded side by side. If they cannot be shown equal, the execution
proves nothing about the thing that was authorized: it proves something about
whatever happened to be on the host.

## The sixteen gate items, and which host closes each

Sixteen items, three groups, and **every one of them must close** before
`0.3.0a1` may be published. The grouping is by which host produces the
evidence, not by which items are optional — none is.

The workstation group is worth reading rather than skimming: a vantage that may
NOT claim reachability is still the correct instrument for the two items that
are not reachability claims.

### CLOSES with Role A alone — on-host evidence, no external vantage

On-host `ss -tlnp` is the AUTHORITY for what the host bound, not a probe. That
is not a convenience: hosts differ in closed-port behaviour, so identical probe
output means different things on different hosts, while `ss` reads the socket
table directly.

| # | Gate item | Why Role A suffices |
|---|---|---|
| 1 | Apply under the product deployment lock | entirely on-host |
| 2 | Pre-change snapshot (`HostObservation`) | captured before mutation, on-host |
| 3 | Non-recreating apply is REFUSED | exercised against the real controller path; `restart` reuses the container it has |
| 4 | Socket re-observation: `127.0.0.1:` and `[::1]:`, never `0.0.0.0:` / `[::]:` | `ss -tlnp` is the authority |
| 5 | `docker-proxy` re-observation: PID is NEW, `-host-ip` correct per family | a surviving PID means the container was never recreated |
| 6 | Firewall re-observation: v4 rules in `DOCKER-USER`, v6 in `INPUT`, terminal DROP present, `--ctorigdstport` on the remapped publish | chain dumps are on-host |
| 7 | The inert-chain fact captured as a fixture: a v6 `DOCKER-USER` rule with a ZERO packet counter | `ip6tables -L -v -n`, on-host |
| 8 | Rollback, provoked rather than simulated | restores the observed snapshot; re-observation matches |
| 9 | Digest equality: descriptor == authorized plan == `VerificationReport.descriptor_digest` | computation plus the applied plan |
| 10 | `exposure = "none"` emits no socket at all | absence in `ss` |

### CLOSES with the WORKSTATION vantage — the two things that are not reachability claims

The workstation sits inside `[redacted 2026-10-05: estate public /22]` and may not be used to claim
reachability. It is still the right instrument for exactly two items, because
neither is a claim about reachability:

| # | Gate item | Why a privileged vantage is admissible here |
|---|---|---|
| 11 | The target's closed-port behaviour (DROP vs RST), recorded | a property of the TARGET's response style, not of who can reach it — and it is required to interpret any later probe |
| 12 | The privileged-vantage refusal FIRES on a real probe | the point is that the verdict is refused; a genuinely inside vantage is the only way to demonstrate it |

Item 12 is worth running deliberately. `accept_public_exposure_evidence` has
unit coverage, but a real connection from a real inside vantage being refused
is the demonstration that the two false P0 escalations of 2026-08-29 would now
be caught rather than repeated.

### CLOSES with Role B — 4 items, no longer unmonitored

These four are REQUIRED to close rather than recorded as gaps. Each result
below is scoped to the transport that carried it: `ip route get` confirmed both
paths to Role A leave via `eth0`, so these are statements about **public-transport
reachability to Role A**, which is exactly what items 13-15 ask for. They are
not statements about Role B's isolation in general, and this document does not
make one.

| # | Gate item | Expected |
|---|---|---|
| 13 | IPv6 external negative: the loopback-bound v6 socket | not reachable |
| 14 | IPv6 external positive control: `tcp/22` over v6 to THIS target | reachable |
| 15 | IPv4 external negative + its `tcp/22` positive control | not reachable / reachable |
| 16 | a `private` exposure reached from inside its declared source set | reachable |

**Why these stopped being optional.** The earlier reading — that on-host `ss`
already covers the underlying defect, so the external half is confirmation —
was rejected on its premise rather than its logic. For a release whose entire
subject is ADDRESS-FAMILY ENFORCEMENT, the IPv6 external proof is not
corroboration of something already established; it is the release's central
claim. A facility that exists to make IPv6 exposure declarable, and ships
without once watching an IPv6 socket refuse the internet, has not been tested
against the thing it was built for.

Item 15 was conditional on a vantage outside the applicable allowlists rather
than impossible. That vantage now exists, so the condition is met and the item
opens with the rest.

**Publication of `0.3.0a1` is gated on all sixteen.** An UNMONITORED region is
an acceptable answer for a peripheral property and is not one for the property
a release is named after.

## Fixtures this lane produces

Real observations, checked in as parser and verifier fixtures so the next
change is tested against measured bytes rather than invented ones:

- `ss -tlnp` output for loopback dual-stack, and for a `private` bind;
- `docker-proxy` process lines including a remapped publish;
- `iptables-save` and `ip6tables-save` before and after apply;
- an `ip6tables DOCKER-USER` rule with its zero packet counter, which is the
  measured form of "inert";
- a remapped publish's `--ctorigdstport` rule, and the `--dport` rule that
  matches nothing;
- an allowlist with its terminal DROP, and the same allowlist without it.

## Not in scope

No production host. The emergency ERP and SON edits of 2026-08-29 are
product-first evidence and parity fixtures; they are neither the mechanism nor
the target design, and this lane does not touch either host.

Publication of `0.3.0a1` stays HELD regardless of the outcome:
`docs/inventories/declared-publication-baseline.json` records it as
`declared-unpublished` while OpenBao containment and credential rotation
settle. A green Lane 3 removes one blocker; it does not remove that one.

## The publication gates are three separate things

Easy to conflate, and conflating them is how a green preflight comes to read as
"the release is attested".

| Gate | Establishes | Does NOT establish |
| --- | --- | --- |
| **Publisher authentication** | that the identity doing the publishing is the intended one | anything about what was published |
| **Artifact signing** | that this artifact was signed, by which certificate | that the signature was recorded anywhere durable |
| **Provenance** | what built the artifact, from which source, on which runner | who published it |

**Publisher authentication does not close signing or provenance.** A green
preflight establishes who is publishing and nothing about what.

`AGENTS.md` rule 39 binds the signing gate specifically: a signed release
pipeline verifies **the produced artifact's** application identity and its
**actual signing certificate**, never secret or file existence — and a step is
renamed if it does not test the property it is named for. A step called
"verify signing" that checks a keystore file exists is testing the presence of
a file and must be called that.

Lane 3 establishes none of the three. It is about exposure semantics against a
real socket, and it is listed here only so the two are not mistaken for one
gate when publication is finally considered.
