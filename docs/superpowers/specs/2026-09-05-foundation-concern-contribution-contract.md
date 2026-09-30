# The Foundation concern-contribution contract — DESIGN FOR REVIEW

**Status: CONTRACT DESIGN ONLY — revision 8.**
This contract is **not implemented**. No implementation is accepted by this
document; this is not profile admission, a Platform cutover, or deletion
authority. Governance ADR 0039
remains Proposed and unenforced.

**Revision 8 changes**: Michael approved the cutover standard: applications
become thin slices that directly compose the owning Foundation contracts; there
is no compatibility adapter. The only adapters that remain are transport, protocol, and host-I/O adapters, and none translates admission meaning. The
semantic-evaluator seam is now a closed, immutable verifier-artifact-owned
registry keyed by `FoundationConcern + contract_id + contract_version`, with
typed generators, schemas, injection sites, output codecs, semantic evaluators,
absence scanners and registration digests. The candidate fixed inventory and
the installed inventory are collected independently before the fresh seed is
drawn. `SeedCommitmentV1`, `ChallengeSetDigestV1`, and
`EvaluatorRegistrationDigestV1` make the receipt's five-part join explicit.
No evaluator is registered from reviewed facts in this design; every concern is
therefore `unregistered-blocks-admission`. The parity gate remains false and now
requires retained-artifact cross-repository evidence plus proof that no shim or
local writer survives. This is still **not implemented**, does not reserve an
entry point, does not claim 13/13, and does not accept a candidate.

**Revision 7 changes**: candidate implementation review found the required
semantic evaluator seam is not yet specified. A generic Foundation verifier
cannot judge typed provider observations without the per-concern contract
evaluator, challenge schema, output schema, and semantic relation that §3.3b
assigns to each concern contract. The candidate was withdrawn rather than leave
a caller-controlled verifier capable of returning `admitted`. The parity map
remains a hard block: Platform deletion requires a pinned retained-artifact,
cross-repository admission result and row mapping, none of which this repository
can produce or claim locally.

**Revision 6 changes**: the **cross-repository parity join** (§ 11A) — Platform's
map is fetched at its pinned commit, anchored by the **sha256 of its bytes**, and
joined by ROW ID; it fails closed when the counterpart cannot be fetched, because
an unavailable oracle is not a pass. On its first run the join found a claim of
this document's that was too coarse: Platform classifies `uninjected` as
`approximated`, a boolean could not carry that, and the honest count of genuine
additions drops from 8 to **7**. § 12A's *no semantic translator* constraint and
the atomic-removal condition are recorded (§ 11B).

**Revision 5 changes** (third review): the F2 ruling **reaches § 4.3, § 12A and
§ 3.1** — the verification record is rebuilt in the ruled vocabulary, the receipt
is specified once rather than twice, and § 3.1 is marked SUPERSEDED instead of
standing as normative text asserting the design § 3.3b defeats (§ 13.1 is the
rule adopted against this recurring class); the seed commitment **gains an
opener** (§ 4.3b) — a commitment nobody re-derives was this document's own inert
shape, one surface over; the expected relation must be **semantic**, with
`shape-discriminator` as an eighth mutant (F3); clause 6 is bounded as a claim
about the published record, not process isolation; "unrepresentable" now **names
the type** — an admission outcome is a SUM TYPE; N25's refusal column is `—`
because the broken verifier is what would emit a code; the mutants are
**required, not built**; and § 3B's swallowed bullet, a stray rule pair and the
matrix ordering are repaired.

**Revision 4 changes**: **F2 is RULED** — the Foundation-owned challenge space,
with the seed drawn AFTER the candidate bytes are fixed and the provider
returning typed outputs rather than its own verdict, which defeats the lookup
table and both boundary attacks (§ 3.3b); the **seven required mutants**,
including `broken-shut-verifier`, which turns the rule on the tool (§ 3.4b);
§ 3.4's residual restated in Michael's terms as an **inertness AND correctness**
limit; and — from Platform's merged row map — an **ENVELOPE admission stage**
(§ 3A.1), because none of its five unmapped rows had a successor code and
`document_absent` is the only verdict this programme has ever observed against a
real image.

**Revision 3 changes** (second review): the five-identity repair reaches the
SCHEMAS — the provider carries only what a module build can know, the binding
carries the assembly-scoped half, and the verification carries all five and is
the fact that binds them (§ 1.1, § 4.1, § 4.2, § 4.2b); § 8's canonicalizer claim
was **false** and is ruled — one canonicalizer, the schema check widens to a
closed accepted set (§ 8.0); the successor names are ruled, in two families, with
admission outcomes kept OUT of the profile (§ 3B.1); "right site, wrong
provenance" gets the refusal it never had (§ 3.3 row 5b); § 0's claim is
qualified where it is made and § 7's refusal citation corrected (F7); a live
merged-code defect is logged (§ 6.0); and **F2 — the battery does not close the
inert class — is stated as an OPEN decision with both options** (§ 3.3b), which
is Michael's to rule.

**Revision 2 changes** (independent review + Michael's nine-point gate): the
nonce echo was **defeated** and is replaced by a Foundation-owned versioned
scenario battery with negative scenarios (§ 3); the join key grows from four
module-scoped components to **five**, two of them assembly-scoped (§ 1.1); the
probe goes through the assembly's **composition root** rather than the entry
point (§ 3.2); the successor is a **new versioned contract**, not a widening
(§ 3B); documents close on **decode** as well as encode and carry no free text
(§ 4.4–4.5); `InventoryDigest.v1` becomes Foundation-owned (§ 5A); absence
inventories become **per concern** (§ 6.1); displacement and retirement are
canonical, and V1 now **rejects** retirement (§ 6B, landed); admission joins the
**retained-artifact release path** (§ 12A); and the parity map is committed and
two-directional (§ 11).
This document is the review package Michael asked for before nine consumers bind
to a shape. It contains no implementation: no build tool, no module declarations,
no entry-point scanning. Two things in this repository are real today and are
cited rather than proposed — `ApplicationFoundationProfile` and its canonical
encoding, and `IntegrationSurfaceAbsenceProofV1` as a slot value (landed
2026-09-05).

Everything under "PROPOSED" below is a shape to argue with.

---

## 0. The rule this whole design exists to serve

> **Applications supply declarations. Foundation supplies meaning.**

Stated as an obligation rather than a slogan, because it is checkable:

An application assembly MAY declare its identity, the modules and versions it
selects, its migration and plane selections, its profile selection, its product
descriptor, and thin adapters into owning services.

An application MUST NOT implement profile canonicalization, profile
verification, deployment execution, or settlement translation. **There is no
compatibility adapter for these.** At cutover an application becomes a thin
slice directly composing the owner contracts; only transport, protocol, and
host-I/O adapters remain, and those adapters may not translate an admission
verdict, receipt, registry entry, or profile value. Producing or translating the
Foundation contract through an application-local adapter preserves two competing contracts, and two contracts
that agree today are two contracts that diverge on the day one is improved. That
is compatibility plumbing, not composition.

The test of the rule is mechanical: **if a value could differ between two
correct deployments of the same artifacts, it is not profile material** — it
belongs to settings, the deployment descriptor, or the entitlement surface.
`ConcernBinding`'s closed field set states this, and `_binding_from_document`
**would** refuse an extra key — **but nothing in production calls that parser
today; see § 6C, which is part of this claim and not a footnote to it.** The
contract below inherits the discipline; § 12A is what gives it a caller.

---

## 1. Three independently supplied facts, and the joining rule

A provider satisfies a concern only when **three separately produced facts join
on the same typed contract identity and the same artifact coordinates.**

| fact | answers | produced by | produced when |
| --- | --- | --- | --- |
| `ConcernProvider` | *what capability exists, and in which implementation* | the **module** | at module build |
| `ConsumerBinding` | *that the assembly actually injects and uses it* | the **assembly** | at assembly build |
| `ConcernVerification` | *that the composed path was exercised, with evidence* | the **generic tool** | at candidate build |

Each of the three looks complete on its own, and that is exactly the hazard.

* A provider alone is a **declaration**. A module can ship a perfect provider
  into an assembly that never wires it.
* A provider plus a consumer binding is a **wiring claim**. Both can name the
  same capability and the code path can still never execute — the binding is a
  statement about intent, made by the party with the least interest in
  discovering it is wrong.
* A verification alone is **an exercise of something**, and without the other
  two nothing says what.

### 1.1 The join key — FIVE identities, not four

**Revised after review.** The first revision's four-part key was entirely
**module-scoped**, so a verification produced against assembly A joined cleanly
to assembly B's binding whenever both pinned the same wheel. Two assembly-scoped
identities close that, and a typed injection site closes the wiring hole:

```
JOIN = (
  assembly_artifact,        # the exact assembly / candidate artifact
  composition_digest,       # Foundation-canonical digest of the composition
  concern_contract,         # (concern, contract_id, contract_version)
  provider_artifact,        # resolved provider artifact + entry point
  injection_site,           # TYPED, not a string path
)
```

Each component MUST be **identical** wherever it appears — not compatible,
identical. It does **not** follow that every fact carries every component:
`ConcernProvider` is produced at module build, when no assembly exists, so it
cannot name `assembly_artifact`, `composition_digest` or `injection_site`. § 4.2b
states which fact carries which, and the **verification carries all five and is
the fact that binds them.** Each omission from the KEY is exploitable:

| omit | what becomes joinable |
| --- | --- |
| `assembly_artifact` | assembly A's verification certifies assembly B |
| `composition_digest` | a re-composed assembly reuses an old verification |
| `concern_contract` | one contract's evidence answers another's question |
| `provider_artifact` | yesterday's wheel certifies today's |
| `injection_site` | an object wired somewhere else satisfies this slot |

`assembly_artifact` and `provider_artifact` are **immutable** references —
`<name>@sha256:<64 hex>`, `sha256:<64 hex>`, or a peeled 40-character commit.
`_require_coordinate` applies unchanged: an installation adopts by digest, so a
claim measured against a reference that can move is not a claim about any
particular bytes.

`injection_site` is **typed**, not a dotted string. A string is a name two
parties can spell differently while meaning the same site, or spell identically
while meaning different ones; a typed site is compared by identity.

### 1.2 Why the tool produces the verification, and the module does not

A module verifying itself is the shape this programme has already paid for: a
binding whose only consumer is a test, a verifier with no caller outside its own
module. The module supplies the **provider**; Foundation supplies the
**question**; the generic tool asks it against the composed assembly and records
what came back. That is what makes the third fact independent, and it is why
`ConcernVerification` is not something a module may declare.

---

## 2. The lifecycle is closed. Only `admitted` fills a slot.

```
declared → resolved → injected → exercised → admitted
```

| state | established by | what it does NOT mean |
| --- | --- | --- |
| `declared` | an entry-point row exists | that the row imports |
| `resolved` | the row imports and yields the typed object | that anything uses it |
| `injected` | a `ConsumerBinding` joins it on the full JOIN key | that the path executes |
| `exercised` | a `ConcernVerification` reports at least one positive outcome | that the answer is correct |
| `admitted` | all three facts join AND the verification is non-vacuous | — |

**Only `admitted` fills a profile slot.** Every earlier state is a refusal with
its own name, and the names matter: an operator repairing "declared but
unresolvable" edits a package, one repairing "no consumer binding" edits an
assembly, and one repairing "broken-shut" edits a provider. Collapsing them into
"not admitted" would send all three to the same place.

Note the final row's second column carefully. `exercised` does **not** mean the
provider's answer is correct. Nothing generic can establish that; correctness is
the concern's own contract test and lives with the module. What the generic tool
establishes is that the composed path is **live and responsive** rather than
declared and dead. Overclaiming here would itself be the defect — a check that
is believed to prove more than it does is worse than an absent one.

---

## 3. Inertness — REVISED after independent review

### 3.0 The previous revision was defeated, and here is the defeat

The first revision of this document proposed a Foundation-issued **nonce** that
a `ProbeOutcome` must echo, and claimed it distinguished a live provider from a
declared-and-dead one. The reviewer produced this:

```python
def probe(self, nonce):
    return ProbeOutcome(positive=True, nonce_echo=nonce, detail="ok")
```

It resolves, it echoes, it reports positive, and it fills a slot while
implementing nothing. **The inert surface did not close; it moved from a
manifest row to a five-line method** — and § 3.3 then forbade the tool from
holding the one opinion that could have told the difference.

Two further defects, both structural:

* **the probe resolved the provider from the ENTRY POINT, not through the
  assembly's composed graph.** A nonce echo was therefore compatible with a
  module installed and never wired. Refusal 2 caught a forgotten *row*, and the
  author of a forgotten row is the same person as the author of forgotten
  wiring;
* **every component of the join key was module-scoped**, so a verification
  produced against assembly A joined cleanly to assembly B's binding whenever
  both pinned the same wheel.

§ 2 conceded that `exercised` ≠ correct and said correctness lives with the
module. Nothing required that test to exist, run, or be evidence — and § 1.2's
own argument is that a module cannot be trusted to verify itself. The concession
was load-bearing and unfunded.

This section is the repair. It is recorded rather than replaced silently,
because the defeated design is the reason the new one has the shape it has.

### 3.1 SUPERSEDED by § 3.3b — the versioned scenario battery

> **This section is superseded and is retained as history, not as normative
> text.** § 3.3b's challenge space replaces it. Revision 4 ruled that and left
> this section asserting the defeated design as current — including *"no
> constant satisfies both"*, which is true and insufficient, and a
> `battery_version` in the join key that § 1.1 and § 4.2b do not carry. **Two
> statements of one key is the defect this document is built to refuse**, and it
> had one.
>
> What survives into § 3.3b: Foundation owns the questions and judges the
> answers; the two halves are both required; the batteries are per concern
> contract and never per product. What does not: fixed inputs, `scenario_id`,
> `expected` in any record, and the claim that the pairing closes the inert
> class.


> *"A provider-supplied boolean or nonce proves only reachability; Foundation's
> versioned battery must independently judge positive and negative scenarios."*

Per concern contract, Foundation defines a **versioned battery**: a set of
scenarios, each with an input Foundation constructs and an **expected outcome
Foundation knows**. The provider does not report whether it succeeded. It
returns an answer; **Foundation compares.**

The battery has two halves, and both are required:

| half | scenario expects | catches |
| --- | --- | --- |
| **positive** | the provider ACCEPTS and answers | a provider that refuses everything (`broken_shut`) |
| **negative** | the provider REFUSES | a provider that accepts everything — **the five-line stub** |

That pairing is the repair. `return positive=True` passes every positive
scenario and **fails every negative one**, because it says yes to inputs the
contract requires it to refuse. A stub inverted to refuse everything passes the
negatives and fails the positives. **A provider must pass both halves**, and no
constant satisfies both.

The battery is **versioned** and its version is part of the join key, so
"which questions were asked" is a fact about the record rather than about
whichever Foundation happened to run.

**Foundation writes the batteries.** They are per *concern contract*, not per
product — a battery that needed to know about ERP would be the adapter this
whole redirection removes.

### 3.2 The probe goes through the ASSEMBLY'S COMPOSITION ROOT

The tool does not resolve the provider from its entry point and call it. It asks
the **assembly's composition root** for the object it injected at the declared
**typed injection site**, and runs the battery against *that*.

Consequences, each of which was a hole before:

* a module installed but never wired has **nothing at the injection site**, so
  the battery cannot run — `uninjected`, distinguishable from a missing row;
* an object present at a **different** site than declared is `wrong_site`;
* the object obtained must have the **same artifact identity** as the resolved
  provider, or the assembly wired something else with the right shape. **This is
  a refusal — `foreign_provenance`** (§ 3.3, row 5b), not merely a consequence.
  Revision 2 stated it as an implication and gave it no code and no row, which
  left "right site, wrong provenance" nameless: an assembly wiring a look-alike
  from another distribution is not `wrong_site` (the site is right) and not
  `contract_mismatch` (the declarations agree). It had no refusal at all.

  **ARTIFACT identity, not object identity**, and the distinction is load-bearing:
  requiring the obtained object to *be* the resolved provider object would refuse
  every factory-based composition, which is most of them. What must match is
  which distribution the object came from.

### 3.3 The refusals

| # | shape | refusal |
| --- | --- | --- |
| 1 | declared, import-unresolvable | `unresolvable` |
| 2 | provider present, no consumer binding | `uninjected` |
| 3 | consumer names another contract/version/artifact | `contract_mismatch` |
| 4 | nothing at the declared injection site | `unexercised` |
| 5 | object present at a site other than the declared one | `wrong_site` |
| 5b | right site, object from another distribution | `foreign_provenance` |
| 6 | battery run, **every** outcome negative | `broken_shut` |
| 7 | **positive scenarios pass and negative scenarios also "pass"** | `answers_everything` |
| 8 | verification joins a different assembly | `wrong_assembly` |
| 9 | inventory digest not Foundation-computed over the typed inventory | `foreign_inventory` |
| 10 | any document carries an unknown key | `unknown_key` |
| 11 | runtime readback ≠ admitted artifact | `readback_drift` |

Refusal 7 is the one this revision exists to add, and refusals 6 and 7 are
**duals**: a provider that refuses everything and a provider that accepts
everything are both non-providers, and each is invisible to the check that
catches the other.

### 3.3b RULED — the Foundation-owned CHALLENGE SPACE (F2)

Revision 3 stated this as open. **Michael has ruled: the challenge space, with a
construction stronger than recording a seed.**

The hole it closes, restated so the ruling is read against it: *"no constant
satisfies both halves"* is true, but *"the inert class is closed"* does not
follow. A versioned battery has **fixed inputs by definition**, and fixed inputs
are a key —

```python
_TABLE = {digest(inp): verdict}
def answer(self, inp):
    return _TABLE.get(digest(inp), refuse)
```

— which passes both halves, discriminates perfectly and implements nothing. It
needs no bad intent: *"special-case the battery inputs until CI is green"*
produces it one scenario at a time, each step looking like progress.

**The ruled construction:**

1. the verifier generates a **fresh unpredictable seed AFTER the candidate bytes
   are fixed**;
2. Foundation creates **typed challenges and expected relations independently**;
3. the provider is reached **through the assembly's real injection site**;
4. the provider returns **typed OUTPUTS — never its own pass/fail verdict**;
5. the **public receipt** records: challenge-space version, **seed commitment**,
   challenge-set digest, case count, verifier artifact digest;
6. the **raw seed stays in restricted verifier evidence**.

#### Why clauses 1 and 4 are the ones doing the work

**Clause 1 defeats the table.** The seed is drawn *after* the candidate bytes are
fixed, so the challenges cannot have been known when the artifact was built. A
table cannot be baked into bytes that predate the seed that selects the inputs.
This is why "record `(space_version, seed)`" was not enough on its own: recording
a seed makes a run reproducible, but if the seed is chosen before or during the
build, the inputs are still knowable in advance.

**Clause 4 defeats the two cheap attacks directly.** Revision 2 put `expected`
beside `observed` in one record and forbade nothing about the boundary. Now the
provider never sees `expected`, never sees a scenario identity, and never gets to
say whether it passed. It returns outputs; **Foundation judges.** A provider that
cannot see the question's answer cannot special-case it, and one that cannot
report a verdict cannot assert one.

Clauses 5 and 6 split the record: the receipt is **public** and carries a **seed
commitment** rather than the seed, so a later run can be checked against it
without publishing the material that would let the next candidate be built
against it. Publishing the raw seed would reintroduce clause 1's hole for every
subsequent build.

#### The expected relation must be SEMANTIC (F3)

Clause 1 makes the challenge VALUES unpredictable and says nothing about their
TYPES. That leaves a shape fresh seeds do not touch:

```python
def answer(self, challenge):
    if isinstance(challenge, WellFormedFoo):
        return some_output
    return REFUSE
```

It passes both halves, is not a lookup table, and clause 1 is irrelevant to it —
the provider is discriminating on the challenge's *shape*, which Foundation
handed it, rather than on anything the contract means.

**The obligation, on the battery author:** a challenge's expected relation MUST
be **semantic** — determinable only by applying the contract's own logic to the
challenge's CONTENT. It may never be determinable from the challenge's type,
class, structure or any other property visible without applying that logic.

Concretely: positive and negative challenges must be **type-indistinguishable**.
If every accepted challenge is a `WellFormedFoo` and every refused one is not,
the battery has told the provider the answer in the argument.

The bound is honest: this needs a badly constructed battery, and *"Foundation
writes the batteries"* already puts it in the right hands. But the contract gave
the first battery author **no rule to violate**, and a rule that exists only as
the author's good judgement is not a rule. `shape-discriminator` (§ 3.4b) is the
mutant that must be refused.

#### What clause 6 does and does not claim

Clause 6 is a claim about the **published record** — the raw seed is not in the
receipt — and **not** a claim of process isolation. The provider runs in-process
with the verifier and could read the seed if it tried. That is the Python plugin
trust boundary this repository already accepts by standing rule: plugins are
trusted in-process code, installed and verified by the supply chain.

Stated so nobody over-reads clause 6 later. It closes the *published* path, which
is the one that would let the NEXT candidate be built against these challenges.

#### Consequences for § 4.3

`ConcernVerification` changes shape: no `expected` beside `observed` in anything
the provider can reach, and the recorded fields become the six of clause 5. The
provider-facing surface carries **typed challenge inputs only**.

### 3.3c Revision 8: the immutable evaluator registry is the only question owner

The words "Foundation creates typed challenges" are insufficient until the
artifact that owns each typed operation is named. The verifier owns one immutable
registry, keyed exactly by:

```
(FoundationConcern, contract_id, contract_version)
```

There are no caller callbacks, default evaluators, wildcard registrations,
fallback lookups, or dynamically supplied relations. A missing key is
`unregistered-blocks-admission`; it is not a reason to use a nearby contract.
Each registered value is owned by the verifier artifact and contains this closed
set of typed members:

| member | required property |
| --- | --- |
| challenge generator and challenge schema | generates only the selected contract's closed challenge type |
| private witness | keeps expected relation material out of the provider boundary |
| output encoder, decoder, and output schema | rejects unknown/ill-typed output before evaluation |
| independent semantic evaluator/relation | judges content, not challenge shape or a provider verdict |
| real typed injection site | resolves the object from the assembly composition root |
| challenge-space version | participates in the challenge commitment and digest |
| absence scanner | has a closed inventory and a same-scope positive control |
| canonical registration digest | identifies this complete registry entry byte-for-byte |

The verifier selects an entry only after it independently collects the fixed candidate artifact inventory and the installed-distribution inventory, compares them, and records their independently derived digests. Only then may it draw a
fresh seed. This ordering prevents a caller from seeding a challenge set against
a source checkout, a partial installation, or an inventory it computed itself.

**No evaluator rows are populated by this document.** A row needs reviewed,
artifact-bound facts for its typed generator, evaluator, scanner, injection
site, and positive control. Until those facts are reviewed and installed, all
thirteen concerns are deliberately `unregistered-blocks-admission`; this is a
block, not a 13/13 claim or an acceptance result.

### 3.4 The residual, stated honestly — an INERTNESS limit and a correctness one

> **"This defeats the cheap memorisation paths. It still cannot prove arbitrary
> business correctness; a concern without an independent oracle remains
> unproven."**

Both halves of that are load-bearing and revision 2 recorded only the second.

**Inertness.** The challenge space defeats the *cheap* memorisation paths — the
constant, the nonce echo, the pre-built lookup table, and the two boundary
attacks clause 4 closes. It does not make inertness impossible in principle: a
provider that reimplements enough of the contract to answer unpredictable
challenges is no longer cheap to write, but "expensive" is not "excluded", and
this section does not claim otherwise.

**Correctness.** A concern **without an independent oracle remains unproven.**
The challenges establish that the composed path answers Foundation's questions
in the expected relation; where Foundation has no oracle for a concern, there is
no question to ask that the provider is not also the only authority on.

The honest summary is that the battery's strength is bounded by two things
neither of which is the battery's own design: whether the inputs could have been
known in advance (clause 1) and whether Foundation has an independent oracle for
the concern at all.

### 3.4b The EIGHT required mutants

A refusal nobody has watched fire is a refusal nobody should trust, and a design
that names refusals without naming the artefacts that provoke them leaves the
proving to whoever implements it.

**All eight are REQUIRED and none is built** — nothing in this repository builds
a mutant, and nothing in this PR implements the contract. Revision 4 said "all
seven are built", which was a present-tense claim about an artefact that does not
exist. They are owed by the implementation step.

Each must be **refused**, and refused **for its own reason** rather than by
whichever check happens to trip first.

| mutant | what it is | must be caught by |
| --- | --- | --- |
| `constant-positive` | answers positively to everything | `answers_everything` (negative challenges) |
| `nonce-echo` | revision 1's five-line stub, echoing and asserting success | `answers_everything`; it also cannot report a verdict at all under clause 4 |
| `lookup-table` | the memorising table of § 3.3b | the seed drawn AFTER candidate bytes are fixed (clause 1) |
| `missing-injection` | provider installed, never wired | `uninjected` |
| `swapped-binding` | a binding joined to another assembly's verification | `wrong_assembly` |
| `stale-provider` | a binding naming a provider artifact the assembly no longer carries | `contract_mismatch` |
| `shape-discriminator` | answers on the challenge's TYPE, never its content | the semantic-relation rule: positive and negative challenges are type-indistinguishable |
| `broken-shut-verifier` | **the VERIFIER refuses everything** | see below |

**`broken-shut-verifier` is the one nobody asked for, and it is the reason this
list is not six.** Every other mutant is a defective *provider*,
and every check in this document points at providers. A verifier that refuses
everything makes **every** provider look inert — the whole fleet fails admission,
each failure individually plausible, and nothing in the matrix would say the
instrument was the broken part.

It is `broken_shut` turned on the tool itself, and it needs its own control: the
verifier must be shown **admitting a known-good provider** in the same run that
it refuses the six mutants. A verifier that only ever refuses has not been shown
to work; it has been shown to fail uniformly — which is precisely the argument
§ 3.3 makes about providers, and there is no reason the tool should be exempt
from its own rule.

### 3.5 Still NOT inertness signals

Coverage, answer content beyond the battery's own expectations, and timing.
Each would make the generic tool product-aware, which is the property the whole
design protects. The battery is not an exception: Foundation defines it **per
concern contract**, so it is generic by construction.

## 3A. ANSWERED: the refusal is discriminated per lifecycle stage

Raised against Platform's inventory: its dialect made admission all-or-nothing,
so `CONCERNS_INCOMPLETE` is a single verdict naming the missing set. Under a
five-state lifecycle a slot can fail at four distinct points and one verdict
loses which. **My answer is yes — the refusal is discriminated, and the verdict
carries the stage.** Three reasons, in the order they bite.

**1. The stages have different owners, so one verdict routes to the wrong desk.**

| stage reached | what failed | who repairs it |
| --- | --- | --- |
| `declared` | the row will not import | the **module** — a packaging defect |
| `resolved` | nothing injects it | the **assembly** — a wiring omission |
| `injected` | the probe never reached it | the **assembly or the tool** — composition |
| `exercised` | every outcome negative | the **module** — a broken provider |

`CONCERNS_INCOMPLETE` naming a set of concerns tells four different people the
same sentence, and three of them will look in the wrong repository first. This
programme already pays that tax elsewhere: an unfetched commit and a divergent
branch produce the same `merge-base` answer, and separating them was worth doing
precisely because the repairs are `fetch-depth: 0` versus a rebase.

**2. Uniform failure is a MEANING, not a count.** Thirteen concerns all failing
at `declared` is a broken install. Thirteen all failing at `exercised` is a dead
dependency or a misconfigured environment — the composition is right and the
world is wrong. An incomplete-set verdict renders those identically, and they
are the two most common real outcomes.

**3. Without the stage, `broken_shut` cannot be reported at all.** It is not a
missing concern; it is a present, resolved, injected, exercised concern whose
answers were all negative. Folded into "incomplete", the subtlest refusal in
this design becomes invisible in the one artifact an operator reads.

### The shape

```
ContributionRefusal = (concern, stage_reached, code, detail)
```

* `stage_reached` is the **last stage the slot actually attained** — not the one
  it failed to reach. "Reached `resolved`" is a fact established by evidence;
  "failed to reach `injected`" is the same fact stated as an absence, and this
  design prefers the positive form everywhere else for the same reason.
* `code` stays the closed vocabulary of § 3 — the stage does not replace it.
  Stage says *how far it got*, code says *what was wrong*, and one does not
  determine the other: `contract_mismatch` can arise at `resolved` or at
  `injected` and the repair differs.
* The profile-level verdict becomes the **set of discriminated refusals**, not a
  set of concern names. `CONCERNS_INCOMPLETE` survives only as a summary that
  must be derivable from the refusals — never a value stored beside them, or
  the two can disagree.

### What this obligates

Adds two rows to § 10: **N17** — every refusal names a stage, and the stage is
the highest actually attained; **N18** — the summary verdict is derived from the
refusals and cannot be set independently. Both need a planted defect: a refusal
with no stage, and a summary that disagrees with the refusals it summarises.

---

## 3B. A NEW versioned admission contract, not a widening of V1

**Point 1 of the gate, and it is a constraint on how this lands rather than on
what it says.**

`ApplicationFoundationProfile.v1` is not widened to carry any of this. The
successor is a **new schema with its own name and version**, and V1 remains
readable exactly as it is.

The reason is one this repository has already paid for twice: a contract that
has crossed an artifact boundary cannot be widened, because a wheel already in
circulation writes documents the new reader refuses under the same schema name —
one name identifying two contracts. `HostLease.v2` alongside a read-only
`HistoricalLeaseV1` is the pattern in-tree, and it is the pattern here.

Two immediate consequences:

* **V1 REJECTS what it cannot bind.** Landed 2026-09-05: `retirement` was in
  `BINDING_FIELDS`, never read by the parser, never emitted by `as_document`, so
  the profile digest did not cover displacement evidence — and a document
  supplying `displaces` with its retirement rows was refused for carrying none,
  a message false about its own input. V1 now refuses at the parse (point 7's
  "until V2 supports this");
* **no number was allocated when this section was written.** Naming the successor
  is part of accepting the design, not part of proposing it — and § 3B.1 below is
  that acceptance, recorded after Michael ruled the names. The bullet is restored
  because it carries the transition: revision 4's § 3A.1 insertion swallowed it,
  leaving "two immediate consequences" followed by one.
### 3A.1 The ENVELOPE — what Platform's row map found missing

Platform's merged row map (`74dab8a8`, `docs/inventories/platform-parity-row-map.json`)
leaves **five rows unmapped, and all five are envelope-level**:

`document_absent` · `document_not_utf8` · `document_not_json` ·
`document_not_an_object` · `contract_unknown`

**No successor code covers an artifact carrying no profile at all**, and the gap
is structural rather than an omission from a list:

* `missing` is **per-concern** — it says *this concern has no admitted
  contribution*;
* N17 requires every refusal to name **the highest stage actually attained**;
* for a document that was never read, no concern attained any stage, so
  13 × `missing` is not merely noisy — it is **unrepresentable**, because there
  is no stage to name for any of them.

So the contract discriminates *contributions* superbly and says almost nothing
about the **envelope they arrive in**. That asymmetry is not a small hole:
`document_absent` is **the only verdict this programme has ever observed against
a real image.**

**The repair: envelope admission is its own stage, before any concern is
considered.**

| refusal | shape |
| --- | --- |
| `envelope_absent` | the retained artifact carries no profile document |
| `envelope_not_utf8` | the bytes are not UTF-8 |
| `envelope_not_json` | the bytes are not JSON |
| `envelope_not_an_object` | the JSON is not an object |
| `envelope_contract_unknown` | the `schema` is not in the accepted set (§ 8.0) |
| `envelope_digest_stale` | the declared self-digest does not cover the content |

These are **profile-scoped, not concern-scoped**, and they terminate admission:
no per-concern refusal is emitted alongside one, because no concern was reached.
The lifecycle gains a stage before `declared`:

```
envelope → declared → resolved → injected → exercised → admitted
```

`envelope_digest_stale` is Platform's other finding and had no case either: a
document that declares a digest which does not cover its own content is
well-formed, parses, and is wrong about itself. It belongs here rather than with
the concerns, because it is a property of the document and not of any slot.

### 3B.1 RULED: the names, and TWO families rather than one

| | Python type | wire schema |
| --- | --- | --- |
| the composition an assembly declares | `ApplicationFoundationProfileV2` | `ApplicationFoundationProfile.v2` |
| Foundation's proof it exercised that composition | `ApplicationFoundationAdmissionReceiptV1` | `ApplicationFoundationAdmissionReceipt.v1` |

> **"The profile declares the exact composition. The receipt proves Foundation
> exercised that composition from the retained artifact. Do not place admission
> outcomes inside the profile; that would collapse assertion and independent
> proof."**

Two families, and the separation is the same one § 1 is built on. A profile is
what the assembly **asserts**; a receipt is what Foundation **observed**. Folding
the outcomes into the profile would make the asserting party the author of its
own proof — § 1.2's rule, arriving one level up.

It also keeps the digests apart, which matters mechanically: the profile digest
must be computable **before** admission runs, because admission is *about* that
digest. A profile carrying its own admission outcome could not be hashed until
the thing that hashes it had finished.

The receipt is the immutable artifact § 12A's release path consumes.

**Note the version numbers are independent**: the profile is at v2 because v1
shipped; the receipt is at v1 because it is new. They are not a matched pair and
must not be renumbered to look like one.

---

## 4. Canonical schemas, and who owns every field

### 4.1 `ConcernProvider.v1` — owned by the MODULE

**Carries the module-scoped subset of the join key, and only that.** § 1.1 said
all three facts carry all five identities; that is **impossible here** and the
first revision of this section did not notice. A provider document is produced
**at module build**, when no assembly exists — it cannot name
`assembly_artifact`, `composition_digest` or `injection_site` without inventing
them, and a field a producer must invent is the defect § 12A's build-once rules
name.

| field | owner | join component |
| --- | --- | --- |
| `schema` | Foundation | — |
| `concern` | Foundation vocabulary | `concern_contract` |
| `contract_id` | Foundation | `concern_contract` |
| `contract_version` | Foundation | `concern_contract` |
| `implementation` | module | `provider_artifact` |
| `version` | module | `provider_artifact` |
| `artifact_coordinates` | module | `provider_artifact` (immutable) |
| `entry_point` | module | `provider_artifact` |
| `displaces` | module | — (see § 6B) |

### 4.2 `ConsumerBinding.v1` — owned by the ASSEMBLY

**Carries the assembly-scoped identities the provider cannot know, and restates
the module-scoped ones so they can disagree.**

| field | owner | join component |
| --- | --- | --- |
| `schema` | Foundation | — |
| `assembly_artifact` | assembly | `assembly_artifact` (immutable) |
| `composition_digest` | Foundation computes over the assembly's composition | `composition_digest` |
| `injection_site` | assembly, **typed** | `injection_site` |
| `concern` / `contract_id` / `contract_version` | restated by the assembly | `concern_contract` |
| `provider_artifact` | restated by the assembly | `provider_artifact` |
| `declared_by` | assembly | — |

The assembly **restates** the module-scoped components rather than referencing
the provider's copy. A reference cannot disagree, and disagreement is the signal.

### 4.2b The join, stated as who carries what

| component | provider | binding | verification |
| --- | --- | --- | --- |
| `concern_contract` | ✓ | ✓ | ✓ |
| `provider_artifact` | ✓ | ✓ | ✓ |
| `assembly_artifact` | — | ✓ | ✓ |
| `composition_digest` | — | ✓ | ✓ |
| `injection_site` | — | ✓ | ✓ |

**The join is over each component by the facts that can carry it**, and the
**verification is the fact that binds them** — it is the only document holding
all five, because it is the only one produced when all five exist. That is not a
weakening of § 1.1: two independent statements of a component must still be
identical, and a component with only one carrier is still bound, by the
verification, to the assembly it was observed in.

A verification is therefore not a third opinion to be reconciled with two
others. It is the join itself, written down.

### 4.3 `ConcernVerification` — owned by the GENERIC TOOL

**Rebuilt in § 3.3b's ruled vocabulary.** Revision 4 ruled the challenge space
and left this table carrying the defeated battery's fields — `scenario_id` and
`expected` beside `observed`, and none of clause 5's six. An implementer building
from § 4 would have built the shape § 3.3b defeats. That is the third
consecutive recurrence of the same class, and § 13.1 is the rule adopted against
it.

| field | owner | notes |
| --- | --- | --- |
| `schema` | Foundation | fixed literal |
| join key (**five** identities) | tool, **copied from what it observed** | not from either declaration |
| `challenge_space_version` | Foundation | clause 5 |
| `seed_commitment` | verifier | clause 5 — the commitment, **never the seed** |
| `challenge_set_digest` | Foundation | clause 5 |
| `evaluator_registration_digest` | Foundation | `EvaluatorRegistrationDigestV1` for the exact immutable registry entry (§ 3.3c) |
| `case_count` | Foundation | clause 5 — a bounded count |
| `fixed_candidate_inventory_digest` | Foundation | independently collected fixed-candidate artifact inventory |
| `installed_distribution_inventory_digest` | Foundation | independently collected installed-distribution inventory |
| `verifier_artifact_digest` | verifier | exact immutable verifier artifact digest, never a caller coordinate |
| `outcome` | **Foundation judges** | a closed verdict over the whole run |
| `observed_at` / `observed_by` | tool | provenance |

**`expected` appears nowhere in this document, and no per-scenario record
reaches the provider.** The provider returns typed OUTPUTS (clause 4); Foundation
applies the expected relation and records only the judged `outcome`. A record
that carried `expected` beside `observed` would put the answer in the same
structure as the question — the cheap attack revision 4 closed — and a
`scenario_id` would hand the provider a scenario identity to key on.

There is no `detail`, no `nonce_echo`, no exception text and no free text (§ 4.4).

**The raw seed and the challenge set are NOT here.** They live in restricted
verifier evidence (clause 6, § 4.3b).

#### Closed receipt identities (revision 8)

The named digest values are typed documents, not strings supplied by the caller:

* `SeedCommitmentV1` commits canonical `(challenge_space_version, seed)` bytes;
* `ChallengeSetDigestV1` is Foundation's digest of challenges generated from
  that committed seed and the selected registry entry;
* `EvaluatorRegistrationDigestV1` identifies the immutable complete registry
  entry of § 3.3c.

`ApplicationFoundationAdmissionReceiptV1` closes its fields and joins five independent parts: **(1)** the five-identity contribution join from § 1.1,
**(2)** fixed candidate artifact inventory digest, **(3)** installed
distribution inventory digest, **(4)** the three typed challenge/evaluator
digests above, and **(5)** the closed judged outcome. It carries no callback,
provider verdict, raw seed, challenge values, witness, exception text, secret,
or fallback marker. An unavailable evaluator, inventory collector, decoder,
semantic evaluator, or absence scanner blocks admission rather than minting a
partial receipt.

### 4.3b Restricted verifier evidence, and the OPENER

Clause 5 records a commitment and clause 6 keeps the raw seed restricted.
Revision 4 stopped there, and that was a hole: it never said what the commitment
**is**, **who opens it**, **when**, **against what**, or **that opening is ever
required**. § 12A then says publication and authorization do not re-derive
anything — so **no party would ever check that the committed seed is the seed
that was used.** A verifier that fabricated the entire challenge set could write
any commitment and every consumer would accept it.

**A commitment with no opener is a value nobody re-derives** — this document's
own definition of the inert shape, one surface over. It would have shipped an
inertness contract with an inert field in it.

| | |
| --- | --- |
| **commitment construction** | `sha256` over the canonical bytes of `(challenge_space_version, seed)`, per § 8 |
| **restricted evidence holds** | the raw seed **and the challenge set** |
| **opener** | an auditor, or any party holding the restricted evidence — never the verifier that produced it |
| **when** | on audit, and on any dispute about an admission. **Not per release.** |
| **the check** | re-derive the commitment from the raw seed; regenerate the challenge set from `(space_version, seed)`; re-derive `challenge_set_digest` and compare with the receipt |

This is an **audit path, not a per-release step**, so build-once is undisturbed:
publication still consumes the receipt without re-deriving it (§ 12A). What
changes is that the receipt is now **openable** — the commitment can be shown to
be about the seed that was actually used, by someone who is not the party that
wrote it.

The verifier may not be its own opener, for § 1.2's reason exactly: a party
verifying its own claim is not an independent witness of it.

### 4.4 Every document is closed on ENCODING and DECODING

Point 5, and it is a rule about both directions because closing only one is how
a closed set quietly opens.

**Permitted value kinds, exhaustively:** typed codes from a closed vocabulary ·
bounded counts · immutable references · known digests · enumerated identifiers.

**Refused, by construction rather than by policy:** free-text `detail` ·
exception text · captured stderr · arbitrary maps · `default=str` serialisation
· any string not drawn from a declared vocabulary.

An unknown key on decode is `unknown_key`, never ignored.

### 4.5 The scope boundary this closes for free

> **"Host inventory, environment policy and secret pointers are deployment-time
> bindings and do not belong in the build-time composition join."**

These are not build-time facts, so the documents have **nowhere to put them** —
and that is a better answer than adding secret classification to the contract.
With `detail` removed and only typed codes retained, `ProbeOutcome` has no
carrier for a resolved secret, so the leak path into retained evidence closes
**by construction rather than by policing**. Nothing has to remember to redact.

This is ADR 0009's held-never-dereferenced rule reaching a fourth surface: a
value that cannot be represented cannot be leaked.

### 4.6 The profile — owned by FOUNDATION

Unchanged by this design except that a slot may now hold a proven absence. The
application supplies **selection**; Foundation supplies **structure, admission
and meaning**.

---

## 5. Compatibility and duplicates

**Incompatibility.** `contract_version` is compared by exact identity, not by
range. A running Foundation declares the set of contract versions it accepts; a
contribution outside that set is refused (`contract_mismatch`) rather than
coerced. A range would make "which contract is this" a computation rather than a
fact, and two parties computing it is how one name comes to identify two
contracts — the `0.3.0a2` defect this repository has already paid for.

**Duplicates.** Two admitted contributions for one concern is a **refusal**
(`contribution.duplicate`), naming every declarer. Which one wins must never be
an iteration-order accident. This mirrors `discovery.discover_one`'s first
refusal and must NOT be resolved through `displaces`: that field names local
writers a provider retires, not rival contributions, and overloading it would
turn a refusal into a race the loser cannot see.

**Missing.** A concern with no admitted contribution and no proven absence is a
refusal. That is the 13/13 gate, and it is why `not-yet-implemented` has no
constructible slot member.

---

## 6. Absence-proof integration (item 2, folded in)

Landed 2026-09-05, and cited here as the shape the contract must preserve.

A concern slot may hold a **proven absence**. Three constructible slot members
for four states; `not-yet-implemented` deliberately has none.

Two properties bind on the contract:

1. **It satisfies only when ESTABLISHED, never when merely well-formed.**
   Construction settles well-formedness alone; the proof is re-asked at
   verification against an independently derived artifact digest and inventory
   digest. **A slot whose evidence was not supplied is a finding, not a pass.**
2. **The proof binds the application wheel, not a self-referential image.** A
   proof embedded in an image cannot carry that image's own digest. Hence
   `artifact_digest`, and hence two distinct inputs to verification: the image
   digest a BINDING is checked against, and the artifact digest a PROVEN ABSENCE
   is checked against. Comparing a proof against the image digest could never
   match and would make the gate unsatisfiable — the failure that looks like
   strictness.

A proven absence is **not** an inertness escape hatch. `broken_shut` is a
provider that does not work and `answers_everything` is one that does not
discriminate; absent-proven is a subject that is not there. A contribution that
fails § 3 may not be re-filed as an absence.

### 6.0 LOGGED AND NARROWLY REPAIRED: the former misfiling defect

Before the 2026-09-05 interim repair, `IntegrationSurfaceAbsenceProofV1`
validated `families` against the integration inventory while its `concern` field
accepted **any of the thirteen**. A proof with `concern=WORKER_EXECUTION`
carrying INTEGRATION families therefore constructed cleanly — and then passed
the profile's misfiling guard, because that guard compared the slot key against
the proof's own `concern` field. *The two things that agreed were the two things
checked.* The inventory, the only thing that would have disagreed, was never
consulted.

That historical construction no longer succeeds: `application_profile.py:583`
refuses every concern other than `INTEGRATION` for this integration-shaped proof
type. The defect remains relevant as the reason § 6.1 requires per-concern
inventories; it is not a claim that a non-integration proof constructs today.

The misfiling guard landed 2026-09-05 and is not vacuous in general — it catches
a correctly-built proof filed under the wrong key. It cannot catch a proof
**built against the wrong inventory**, which is the earlier and quieter defect.

Revision 2 presented the defect as motivation for a future generalisation. Its
historical mechanism is recorded here rather than described as a live
construction path.

**The narrow interim repair is landed.** `application_profile.py:583` now
refuses a `concern` other than `INTEGRATION`, because this proof type carries
only `INTEGRATION_SURFACE_FAMILIES`. The control establishes that this is a
real refusal, not a comment. It does not generalize the type: § 6.1's
per-concern closed inventories, scanners, and positive controls remain proposed
and belong to the revision-8 registry. This design neither claims that those
other inventories exist nor treats the interim fix as admission.

### 6.1 THIRTEEN closed inventories, not one (point 6)

> **"A worker-absence proof cannot certify integration, recovery or identity."**

Today one closed inventory exists — `INTEGRATION_SURFACE_FAMILIES` — and
`IntegrationSurfaceAbsenceProofV1` validates its `families` against it while
the landed line-583 guard accepts only `INTEGRATION`. A proof for
`worker_execution` is now refused before it can enumerate anything; before the
interim repair it would have had to enumerate *integration* families. The type
remains integration-shaped and cannot establish absence for another concern.

**Each concern gets its own discriminated, closed absence inventory, each with
its own positive control.** The generalisation is of a shape that is already
real and mechanically enforced — the review confirmed the integration separation
holds, with a correct non-vacuity control — so this is extension, not invention.

Three properties carry over unchanged and one is added:

1. the inventory is **closed** and enumerated before the proof, never from its
   own results;
2. **complete enumeration** — a family never visited is distinguishable from one
   visited and found empty;
3. a **positive control**: the instrument shown finding something known to
   exist, with the same scan and scope;
4. **new** — the inventory is selected by the concern, so a proof cannot be
   built against another concern's families. The misfiling refusal landed
   2026-09-05 catches a proof filed under the wrong key; this catches one
   *built* against the wrong inventory, which is the earlier and quieter defect.

---

## 5A. `InventoryDigest.v1` — Foundation-owned (point 4)

Today `observed_inventory_digest` is compared against **a string the caller
supplies**, and the caller computes it however it likes. Two implementations
computing "the inventory digest" differently is the permanently-unequal-values
failure the canonical byte rules exist to prevent, one surface over.

So the digest becomes a **Foundation-owned document**:

| field | owner | notes |
| --- | --- | --- |
| `schema` | Foundation | `InventoryDigest.v1` |
| `subject` | Foundation vocabulary | WHAT was inventoried — the artifact identity, typed |
| `entries` | supplier (typed) | closed shape: distribution identity → version |
| `digest` | **Foundation computes** | over canonical bytes of `subject` + `entries` |

> **Platform supplies typed inventory, never a locally computed digest.**

That inverts today's relationship. A supplier that hands over a digest is asking
to be believed; a supplier that hands over the typed inventory is handing over
something Foundation can compute from and therefore check. The digest stops
being a claim and becomes a derivation.

`subject` is required and typed because a digest with no stated subject is a
number, and two parties can agree on a number about different things.

Canonical bytes: the § 8 rules, unchanged and not restated. **A committed golden
fixture** with a re-derivation test and a sensitivity pair — the same treatment
the profile fixture already has, which the review called out as done right.

---

## 6A. The fleet lifecycle this contract sits inside

```
retained artifact → artifact admission → target-bound plan → signed authorization
→ controlled execution → verified evidence → durable settlement
```

The contract in this document occupies **artifact admission** and produces the
profile digest that **target-bound plan** and **signed authorization** bind. It
does not reach further, and the boundary is stated because a contract that
drifted into planning or settlement would be a second authority over them.

| owner | owns | must not own |
| --- | --- | --- |
| **Foundation** | canonical profile, admission, planning, execution, recovery, evidence contracts | durable intent, approval state, operator UI |
| **Application** | thin typed declarations: roles, migrations, ports, readiness, resource needs, product-specific preconditions | profile canonicalization, profile verification, deployment execution, settlement translation |
| **Control** | durable intent, approval, authorization, rollout state, settlement | artifact meaning |
| **Platform CP** | operator UI and orchestration wiring | any profile dialect |
| **Runtime providers** | generic Compose / PostgreSQL / Nginx / Kubernetes effects | anything ERP-, Sub- or Platform-specific |
| **Kernel** | in-process mechanics | deployment orchestration |

### Build-once, as checkable rules

Each is a property this contract must not make unrepresentable:

1. the artifact is built **exactly once**; verification and retention are of
   **those exact bytes**;
2. the **same digest** is promoted through rehearsal and production —
   `artifact_coordinates` is in the join key precisely so this is checkable
   rather than asserted;
3. **host inventory, environment policy and secret pointers bind AFTER build.**
   None of them may appear in a `ConcernProvider`, a `ConsumerBinding` or the
   profile. This is the closed-field-set rule stated as a lifecycle property: if
   a value could differ between two correct deployments of the same artifacts,
   it is not profile material;
4. an artifact is **never rebuilt to change environment configuration** — a
   rebuild produces new bytes, and every digest bound to the old ones becomes a
   claim about something that no longer exists;
5. **no secret value** in an artifact, plan, receipt or log. The contract's
   documents carry **pointers and names only**, which is ADR 0009's held-never-
   dereferenced rule applied to a fourth surface.

Per release only the deployment transaction repeats — select artifact, derive
plan, approve, execute, settle. **No reminting identities, recreating targets,
redesigning adapters, or rebuilding environment-specific images.** A contract
that required any of those per release would have moved a build-time fact into
the release loop, which is the defect rule 4 names.

---

## 6B. Displacement and retirement, canonically (point 7)

The successor contract represents both, and the profile digest **covers** them —
which is the property V1 lacks and why V1 now refuses rather than discards.

| binds | to |
| --- | --- |
| a **displacement** | the specific legacy responsibility displaced, and an evidence reference |
| a **terminal retirement** | back to the replacing assembly AND provider |

Two directions, deliberately. A displacement that named only "something was
retired" is the free-text shape point 5 removes; a terminal retirement that did
not bind back to its replacement leaves a retired responsibility with no
successor of record, which is how a capability comes to be owned by nobody.

**Until the successor exists, V1 REJECTS retirement.** Landed 2026-09-05 —
`_binding_from_document` refuses a document carrying it, with a message true
about that document, and the premise (that `as_document` omits it) is asserted
so the refusal cannot outlive its reason.

### 6C. A defect in this document's own cited premise

The review found that `_binding_from_document` — cited in § 0 as the enforcement
of the closed-field rule — **has no production caller.** Its only callers are
two tests.

By § 1.2's own standard that is *a provider whose only consumer is a test*,
sitting inside this design's cited premise. It is recorded here rather than
repaired here, because the repair is to wire admission into the release path,
which is point 9 and is implementation.

Until then § 0's claim is precise about what it is: the parser **would** refuse a
policy value, and nothing in production currently asks it to.

---

## 7. Artifact / build / runtime boundary

| stage | subject | may read | may NOT read |
| --- | --- | --- | --- |
| **module build** | the module's own wheel | its own source | any assembly |
| **assembly build** | the assembly's declaration | selected module identities | provider internals |
| **candidate build** | the **installed distributions** | the installed inventory of the exact artifact | any source checkout |
| **runtime** | the running system | its own admitted digest | nothing it may edit |

The candidate-build row is the one with a history. A profile in
`deploy/product.toml` would be **a checkout fact describing an image**: a source
tree states what an assembly intends to compose, an image holds what it will
run, and the two differ routinely and innocently — an uncommitted pin, a build
argument, a dependency resolved to a newer compatible release, a wheel that
never reached the registry.

At runtime the readback **compares and never derives** (§ 3.3 refusal 11,
`readback_drift` — revision 2 cited "refusal 6", which the renumbering had made
`broken_shut`). Editing an
accepted profile to match what a deployed image turned out to contain inverts
the relationship, and from that moment drift and correction arrive as the same
commit.

---

## 8. Canonical bytes and digest

### 8.0 RULED: one canonicalizer, and the schema check widens to an accepted set

**Revision 2 asserted this section was reusable verbatim. That was false, and
revision 2 made it larger.** `canonical_profile_bytes`
(`application_profile.py:961-968`, pinned by
`test_the_canonicalizer_still_refuses_a_wrapper`) hard-refuses any document
whose `schema` is not `ApplicationFoundationProfile.v1`. Under revision 2, FOUR
documents claimed these rules and **none of them could be canonicalised by the
shipped function**: the three contribution documents and `InventoryDigest.v1`.

Left unruled, the default outcome is a **second canonicalizer** — which is
precisely what that function's own error message warns about: *"two parties come
to compute permanently unequal values while both look correct."* A design whose
unstated default is the defect it cites is not neutral.

**The ruling: ONE canonicalizer. The schema check widens from a single literal to
a CLOSED ACCEPTED SET of Foundation-owned schemas.**

* the check stays a **membership test against a closed set**, never a prefix
  match, a regex or "starts with a Foundation name" — an open predicate is how
  a wrapper eventually passes, and the wrapper refusal is the whole point;
* the accepted set is **enumerated longhand**, so adding a document to it is a
  reviewed diff;
* the rules themselves do **not** change, so every digest already computed stays
  valid — this widens *what may be hashed*, never *how*;
* the wrapper refusal survives unchanged: a document whose schema is not in the
  set is refused, and a wrapper's schema never is.

**The alternative was considered and refused.** A `canonical_contribution_bytes`
beside `canonical_profile_bytes` would be two functions implementing one
specification. They would agree on the day they were written, and this
repository has paid for that shape repeatedly — `discovery.py`'s own docstring
exists because of it. Two canonicalizers is not a smaller change than one
widened check; it is the same change with a second authority attached.

**This is a change to shipped behaviour and is NOT in this PR.** It lands with
the implementation, and its own guard is the near miss: a wrapper containing an
accepted schema must still be refused.

### 8.1 The rules

Reused from `canonical_profile_bytes`, not re-specified — a restatement of a
rule is a copy of it:

* sorted keys at **every** depth;
* separators `(",", ":")` — no spaces;
* `ensure_ascii=True`;
* UTF-8 encoded;
* **no wrapper**: the digest covers the document alone. Hashing a wrapper that
  merely contains one is how two parties compute permanently unequal values
  while both look correct;
* the document's `schema` is checked before hashing, so a non-profile cannot be
  hashed as one.

`profile_digest` = `sha256:` + hex over those bytes.

Every document in this contract uses the **same** rules through the **same**
function, per § 8.0. One canonicalizer, one answer.

---

## 9. Golden byte fixtures

Computed from the shipped canonicalizer at this commit, not written by hand. The
committed fixture is `docs/inventories/foundation-profile-golden.json`.

Bound slot (`identity_session`):

```json
{"coordinates":"acme-foundation@sha256:bbbb…bbbb","displaces":[],"implementation":"acme-foundation","state":"bound","version":"1.0.0"}
```

Absent-proven slot (`integration`) carries, sorted: `artifact_digest`,
`concern`, `established_at`, `established_by`, `families`, `method`,
`observed_inventory_digest`, `positive_control`, `schema`, `source_revision`,
`state`.

Canonical form begins:

```
{"application":"acme-app","concerns":{"api_web_interaction":{"coordinates":…
```

* canonical length: **3320 bytes**
* profile digest: **`sha256:aa4e0f9334c57d089efc3b85debfa49f5103a0bbf2cf59d756948b4d3c906b4a`**

A golden fixture nobody re-derives is the inert shape this document is about, so
one architecture test re-derives the digest from the committed fixture through
the shipped canonicalizer. That test guards the FIXTURE; it does not implement
the contract.

---

## 10. Negative and non-vacuity matrix

Every row is an obligation on the implementation (item 7), not a claim that it
exists. "Non-vacuity" is the column that fails in practice.

| # | negative case | must refuse with | non-vacuity partner |
| --- | --- | --- | --- |
| N1 | entry-point row that will not import | `unresolvable` | a row that imports is admitted |
| N2 | provider, no consumer binding | `uninjected` | provider + binding proceeds |
| N3 | consumer names another `contract_id` | `contract_mismatch` | identical ids join |
| N4 | consumer names another `contract_version` | `contract_mismatch` | identical versions join |
| N5 | consumer names another `provider_artifact` | `contract_mismatch` | identical provider artifacts join |
| N5b | verification names another `composition_digest` | `wrong_composition` | same composition joins |
| N5c | verification names another `injection_site` | `wrong_site` | the declared site joins |
| N5d | a provider document carrying `assembly_artifact`, `composition_digest` or `injection_site` | refused — a producer inventing a fact it cannot know | a module-scoped provider document admits |
| N6 | nothing at the declared injection site | `unexercised` | an object at the declared site admits |
| N7 | all battery outcomes negative | `broken_shut` | a battery passing both halves admits |
| N7b | **negative scenarios "pass" too** — the five-line stub | `answers_everything` | a provider that refuses what it must admits |
| N7c | object present at a site other than the declared one | `wrong_site` | the declared site admits |
| N7d | right site, object from another distribution | `foreign_provenance` | matching artifact identity admits |
| N8 | two providers for one concern | `duplicate` | one provider admits |
| N9 | concern with nothing at all | `missing` | 13/13 admits |
| N10 | runtime digest ≠ admitted digest | `readback_drift` | equal digests pass |
| N11 | join on a SUBSET of the key | must be unrepresentable | the join takes all FIVE identities |
| N11b | verification joins another assembly | `wrong_assembly` | same assembly artifact joins |
| N11c | caller-supplied inventory digest | `foreign_inventory` | Foundation-computed over typed entries admits |
| N11d | unknown key on **decode** | `unknown_key` | a closed document decodes |
| N11e | a V1 document carrying `retirement` | refusal at the parse | a document without it parses |
| N11f | a wrapper CONTAINING an accepted schema | refused by the canonicalizer | each accepted schema canonicalises (§ 8.0) |
| N12 | absence proof, no observed inventory | finding | supplied inventory verifies |
| N13 | absence proof for another artifact | finding | matching artifact verifies |
| N14 | absence proof misfiled under another concern | `absence_proof.wrong_concern` | correctly filed admits |
| N15 | a moving `artifact_coordinates` | coordinate refusal | an immutable one admits |
| N16 | **the tool admits everything** | — | every refusal above must be shown FIRING |
| N17 | a refusal carrying no lifecycle stage | must be unrepresentable | every refusal names the highest stage ACTUALLY attained |
| N18 | a summary verdict disagreeing with its refusals | must be unrepresentable | the summary is derived, never stored beside them |
| N19 | the generic path reproduces 53 and produces no new refusal | acceptance failure | `uninjected`, `unexercised` and `broken_shut` each shown firing |
| N20 | the artifact carries **no profile at all** | `envelope_absent` | an artifact carrying one proceeds |
| N21 | bytes not UTF-8 / not JSON / not an object | the matching `envelope_*` | well-formed bytes proceed |
| N22 | `schema` outside the accepted set | `envelope_contract_unknown` | an accepted schema proceeds |
| N23 | declared self-digest does not cover the content | `envelope_digest_stale` | a covering digest proceeds |
| N24 | an envelope refusal emitted **alongside** per-concern refusals | **unrepresentable — the admission outcome is a SUM TYPE** (see below) | an envelope refusal terminates admission |
| N25 | the **verifier** refuses everything | — (see below) | the verifier admits a known-good provider in the same run |
| N26 | a provider that memorises the challenge set | defeated by clause 1 | the seed is drawn AFTER candidate bytes are fixed |
| N27 | the expected relation reachable by the provider | **unrepresentable — no `expected` field exists in any record** (§ 4.3) | the provider returns typed outputs only |
| N28 | a provider discriminating on the challenge's TYPE | `shape-discriminator` mutant, refused by the semantic-relation rule | positive and negative challenges are type-indistinguishable |
| N29 | a seed commitment nobody can open | must be openable | restricted evidence holds the raw seed AND the challenge set; the digest re-derives (§ 4.3b) |
| N30 | evaluator key absent or unavailable | `unregistered-blocks-admission` | a reviewed immutable registry entry resolves exactly |
| N31 | caller supplies a callback, default, wildcard, or fallback relation | must be unrepresentable | only the verifier-artifact registry can select the evaluator |
| N32 | fixed candidate inventory and installed inventory differ | admission blocks | independently collected equal inventories proceed |
| N33 | a shim translates Platform/local verdicts or a local writer emits a receipt | parity gate remains false | retained-artifact evidence proves direct owner-contract composition and no shim/writer |

**N16 is the one that must not be skipped.** A verifier that has never refused
anything and a composition that is correct are the same colour. Rows N1–N15 each
need a planted defect and a near miss, and the suite must fail if the detector
is removed.

**N11e and N12–N14 exist today** and are exercised
(`test_deployment_foundation_application_profile.py`). The rest are owed by the
implementation step.

**N30–N33 are revision 8's named mutants and positive controls.** The mutants
are `unregistered-evaluator`, `caller-callback`, `inventory-split`, and
`platform-semantic-shim`; the positive controls are respectively a reviewed
exact registry key, a registry-only invocation, two independently collected
equal inventories, and retained-artifact cross-repository evidence of direct
composition with no local receipt writer. They are required implementation
tests, not tests this design claims to ship. This document's architecture guard
asserts these names and rows remain present so a future prose edit cannot quietly
drop the conditions.

**"Unrepresentable" now names the type that makes it so, everywhere it is
claimed.** The word was asserted four times without one, and an invariant is not
a type: *a record with an optional envelope refusal plus a rule that the concern
list must then be empty is a checked rule wearing the stronger word, and it will
drift.*

> **An admission outcome is a SUM TYPE: either an `EnvelopeRefusal`, or a set of
> concern outcomes. Never a record with fields for both.**

The structure already pointed at it — `ContributionRefusal` carries a `concern`
and envelope refusals are profile-scoped, so an envelope refusal **cannot be
one**. N27 is the same one-line fix: there is no `expected` field in any record,
so "reachable by the provider" has nothing to reach.

**N20–N24 are the envelope stage** (§ 3A.1), and N20 is the only verdict this
programme has ever observed against a real image — it had no code until
revision 4. **N24 is the one that keeps the stage honest**: an envelope refusal
must terminate admission, or a reader gets an envelope failure and thirteen
concern failures describing a document nobody read.

**N25–N28 come from the F2 ruling.** N25 turns `broken_shut` on the tool itself:
a verifier that refuses everything makes every provider look inert, and nothing
else in the matrix would say the instrument was the broken part.

**N25's refusal column is `—`, as N16's is, and that is not an omission.** There
can be no code: the broken verifier is the thing that would emit one. It is
caught by its non-vacuity partner — the same-run admission of a known-good
provider — and printing a code there would send a reader hunting for something
that must not exist.

**N5d, N7d and N11f are revision 3's rows.** N5d is the F1 repair made
falsifiable: the previous revision's claim that every fact carries every identity
was not merely imprecise, it demanded that a module-build document name an
assembly. N7d gives "right site, wrong provenance" the refusal it never had.
N11f is § 8.0's near miss — widening the accepted schema set must not weaken the
wrapper refusal, which is the whole reason the check exists.

**N7b is the row revision 2 existed to add.** Its absence is what the
independent review defeated: the previous design's nonce echo made N7b
unrepresentable, so a five-line stub filled a slot. N7 and N7b are duals — a
provider that refuses everything and one that accepts everything are both
non-providers, and each is invisible to the check that catches the other.

**N19 is the migration's acceptance criterion**, and it is deliberately not
satisfiable by parity alone: reproducing all 53 of Platform's rows while adding
no refusal would mean the generic path had reproduced the dialect rather than
replaced it. See § 11 step 3.

---

## 11. Migration from Platform's #166 / #168 — an EXTRACTION, not a deletion

Michael's framing, which is the standard this programme already applies to
product-first extraction: those PRs were **sound under the former direction.
They become superseded implementation — not bad implementation, and not
programme progress.**

> **Updated 2026-09-05.** The parity inventory is merged (`d7b8ca6a`): **53
> driven rows.** The sequence below is the obligation; the row-by-row contents
> live in Platform's inventory and are not restated here.

1. **Preserve** their behaviour and negative cases as **parity fixtures**. The
   inventory is merged: **53 driven rows — 33 verifier, 14 builder, 6
   type-boundary.**

   One of those rows is *a proof carrying only a concern name, a revision and
   free text must not be admitted.* **Correction, 2026-09-05:** an earlier
   revision of this document said Platform had a MERGED TEST admitting that
   shape. **That was false and is retracted** — the repair landed inside #166.
   What survives is the REQUIREMENT, as a bar in the parity matrix, and it is
   precisely the "well-formed proves nothing" shape § 6 turns on. The false
   version is left visible here rather than quietly deleted, because a wrong
   claim about another team's code is the kind of thing that gets repeated once
   it has been written down.
2. **Land** the canonical Foundation contract and the generic verifier.
3. **Prove** the generic path produces **at least the same refusals**, against
   **real artifact bytes**. Not equivalent-looking output: the same refusals,
   from the same inputs. This is the measurable gate, and it is mine.

   **53 is a FLOOR, not the bar, and the gap is the point.** Platform's dialect
   collapses provider, binding and verification into one declaration plus an
   import probe. A shape that cannot be *stated* cannot be *tested*, so the
   inventory structurally cannot contain a case for:

   * a provider that **resolves but is never injected** (`uninjected`);
   * a provider **injected but never exercised** (`unexercised`);
   * a verification whose outcomes are **all negative** (`broken_shut`).

   Those are three of the six inertness refusals, and they are exactly what the
   three-fact separation exists to catch. So "at least the same refusals" is
   necessary and not sufficient: passing all 53 while producing no new refusal
   would mean the generic path had reproduced the dialect rather than replaced
   it. **The acceptance criterion is 53 reproduced AND the inertness refusals
   Platform could not express, each shown firing.**

   The map is committed: `docs/inventories/foundation-admission-parity-map.json`
   (point 8). It is **two-directional** — `legacy_total` and the length of
   `added` are both fixed, so a case cannot appear or vanish as a side effect;
   a shrinking count would otherwise read as cleanup and a growing one as
   progress. **Ten** added cases (**seven** of them genuinely new — see below):
   `uninjected`, `wrong_site`,
   `foreign_provenance`, `all_negative`, `answers_everything`, `wrong_assembly`,
   `wrong_composition`, `foreign_inventory`, `unknown_key`,
   `retirement_round_trip`.

   **`parity_gate_passed` is FALSE, and deleting Platform's dialect requires it
   TRUE.** Revision 2 recorded the debt and gated nothing: it asserted
   `legacy_rows_supplied_here` stays false, and nothing failed if deletion
   proceeded while it was. A field that records an obligation without blocking
   on it is a note, not a gate. Flipping it requires the per-row mapping of all
   53, which the Platform lane owns.

   **`nonce_only` was dropped in revision 3.** It was a case under revision 1,
   where the nonce was the liveness signal; revision 3 removes the nonce
   entirely, so the shape cannot be represented and the row could never fire.
   A provider that answers positively while implementing nothing is
   `answers_everything`, which is real and fireable. Keeping both would have been
   one defect wearing two names — and the ratchet would have frozen the
   duplicate in place, which is why it is resolved now rather than later. The
   historical defeat lives in § 3.0, where a defeated design belongs, not as a
   test case that cannot fail.

   **Platform's row map is MERGED and is now the join partner** —
   `platform-cp#170`, `74dab8a8`, `docs/inventories/platform-parity-row-map.json`,
   schema `platform-parity-row-map/1`. Row identity is `PCP-<surface>-<ordinal>`,
   **allocated once and never reused**: a retired row *spends* its ordinal,
   because reuse would silently re-point a foreign reference at a different
   property.

   | state | rows |
   | --- | ---: |
   | mapped | 33 |
   | migrates | 13 |
   | retires | 2 |
   | **unmapped — blocks deletion** | **5** |

   Those sum to 53, so the two halves reconcile arithmetically rather than by
   assertion. The rows themselves are still not restated here — a copy would be
   a second authority that drifts.

   **The five unmapped rows are all envelope-level, and § 3A.1 is their
   resolution.** They had no successor code at all, which is a structural gap
   rather than an omission: `missing` is per-concern and N17 makes 13 × `missing`
   unrepresentable for a document that was never read.

   **Two of the added cases are NOT new**, and the map records it:
   `foreign_inventory` and `unknown_key` have legacy counterparts. They are still
   required — a case with a counterpart still has to be reproduced — but counting
   them as gains would overstate what the successor adds. Ten obligations, seven
   genuine additions.
4. **Replace** Platform's acceptance invocation.
5. **Delete** Platform's builder, canonicalizer and verifier **atomically, when
   the generic path ADMITS THE RETAINED PLATFORM ARTIFACT** — not when the
   contract merely exists, and **with NO Platform-to-Foundation semantic
   translator.** A shim mapping Platform's verdicts onto Foundation's would be
   the two-competing-contracts shape this redirection rejected at the outset,
   arriving as a migration aid and staying as an architecture. Removal is in that
   same composed change — never a separate one, because that produces a temporary
   state with neither verifier.
6. **Ratchet** so the local dialect cannot return: a two-directional guard that
   fails when a product-local canonicalizer or profile verifier reappears, and
   also fails if the count is lowered without the row being removed.

Steps 4–6 are Platform's file set, not mine. Step 3 is mine and gates them.

---

## 12. Reviewed against three consumers, implemented for one

Michael: *"Review the shape against Platform, ERP and Sub, but implement Platform
as the first reference assembly before enrolling the other consumers."*

| consumer | what the shape must survive | open question for review |
| --- | --- | --- |
| **Platform CP** | a concern with genuinely no surface (integration) → the absence slot | does Platform hold any concern where the provider is in-process rather than a distribution? |
| **ERP** | many modules contributing to one assembly; several concerns per module | does one distribution contributing to two concerns need two providers, or one with two rows? **Proposed: two rows** — one provider answers one concern, so the join key stays total. |
| **Sub** | the largest existing writer surface; `displaces` will carry real weight | does Sub have a concern satisfied by two implementations today, which § 5 would refuse as a duplicate? If so the refusal is correct and the repair is Sub's, but it must be found before enrolment, not during. |

Those three questions are the ones I would most like answered in review. Each is
a place where the design could be right in the abstract and unbuildable for a
real assembly.

### 12.1 The composability proof: ERP with NO ERP adapter

> **"Compose ERP as the second consumer without adding an ERP adapter."**

This is the real test of the design and it is worth stating as a falsifiable
claim rather than an aspiration:

**If enrolling ERP requires anything ERP-shaped in Foundation, the contract has
failed.** Not "needs work" — failed, because an adapter per consumer is the
two-competing-contracts shape this whole redirection exists to remove, arriving
one consumer at a time instead of all at once.

Concretely, none of these may be required to enrol ERP:

* an ERP branch, flag or `if product ==` anywhere in Foundation;
* an ERP-specific concern, or a fourteenth concern added to carry an ERP need;
* an ERP-specific provider base class, mixin or registration helper;
* a Foundation-side translation of an ERP-local profile dialect;
* a widened `contract_version` range to admit ERP's build.

What ERP MAY supply is exactly what any module supplies: typed
`ConcernProvider` rows, and — as an assembly — `ConsumerBinding` rows and thin
typed declarations. If ERP cannot be expressed that way, the missing expressive
power is a **generic** gap in the contract and the repair is generic.

The design's known pressure point for ERP is in the table above: one
distribution contributing to two concerns. The answer proposed there — **two
provider rows, one per concern, so the join key stays total** — is what keeps
this generic. A single row with two concerns would make the join key partial for
one of them, and a partial join is the defect § 1.1 exists to prevent.

**This proof is scheduled, not assumed.** It belongs to the enrolment step and
must be run before ERP is composed, not after — the cheapest moment to discover
an ERP-shaped requirement is while the contract is still a document.

---

## 11A. The CROSS-REPOSITORY parity join

> **"Independently green suites are insufficient."**

`parity_gate_passed` cannot flip on Foundation asserting that it covers
Platform's rows. Two teams each asserting 53 is exactly what the arithmetic
reconciliation replaced one level up, and asserting coverage of five envelope
rows is the same shape one level down. **Something must join the two
repositories' artifacts and fail if they disagree.**

### 11A.1 The anchor

| | |
| --- | --- |
| repository | `michaelayoade/dotmac_platform_control_plane` |
| commit | `74dab8a8ec97bd8492d4eec5bde4edab74d4c957` |
| path | `docs/inventories/platform-parity-row-map.json` |
| schema | `platform-parity-row-map/1` |
| **sha256 of the counterpart bytes** | `5d69b4a5…6aa` |

The digest is the join's anchor and the reason it is a join rather than a
citation. A pinned commit says *which* artifact; the digest says the bytes
compared were the bytes pinned.

### 11A.2 What the join checks, and that it FAILS CLOSED

1. fetch the counterpart at the pinned commit; **re-derive its sha256 and
   compare.** If it cannot be fetched, the join **REFUSES** — an unavailable
   oracle is not a pass, which is this repository's standing rule and the one
   most likely to be quietly inverted for a cross-repository dependency;
2. every Platform row in state `unmapped` has a Foundation code
   (`envelope_join`);
3. Platform's four `map_states` sum to `legacy_total`;
4. every case present in **both** `added` lists agrees on its
   `legacy_relation`;
5. the revision Platform measured against is recorded, and every difference is
   either agreement or **classified version skew**.

**Only then may `parity_gate_passed` flip.** It is false today.

### 11A.3 What the join found — verified, not inherited

Fetched and checked rather than taken from a summary, because the numbers had
already been relayed to me once with an error.

* Platform's map: **53 rows, `mapped 33 / migrates 13 / retires 2 / unmapped 5`**
  — confirmed against the artifact;
* **unmoved since the pin**: head and pinned bytes hash identically;
* **all five unmapped rows close** against § 3A.1's envelope codes, joined by row
  id — `PCP-V-01`…`04` and `PCP-V-11`. `PCP-V-11` is recorded by Platform as
  PARTIAL (`contract_mismatch` covers a *consumer* naming another contract, not
  an unknown contract in the envelope), and the envelope code closes the
  remainder;
* Platform measured against **revision 2**; this is revision 8.

**One genuine disagreement, and Platform is right.** Platform classifies
`uninjected` as **`approximated`** — it carries a legacy row
(`concern_spec_bound_without_a_consumer`) because Platform asserted the
requirement at construction and could not OBSERVE it, so the runtime refusal is
new and the intent is not. This map called it simply new. **A boolean cannot say
that**, so `new_to_the_successor` is replaced by Platform's three-value
`legacy_relation` — `has_counterpart` / `approximated` / `no_counterpart`. The
honest count of genuine additions drops from 8 to **7**.

That is the join earning its place on its first run: it found a claim of this
document's that was too coarse, in the direction of overstating what the
successor adds.

**Three one-sided cases are VERSION SKEW, not disagreement**, and the join must
be able to tell those apart or it reports progress as a defect: `nonce_only`
exists only in Platform's list (dropped in revision 3 — the nonce no longer
exists, so the row could never fire), and `foreign_provenance` and
`wrong_composition` exist only here (added in revisions 5 and 4, after Platform
measured).

### 11A.4 What this does NOT do

It does not run either suite. It compares two committed artifacts. Independently
green suites remain insufficient by construction, because the join never consults
them.

---

## 12A. Admission on the retained-artifact release path (point 9)

Admission is not a build-time side activity whose result is recomputed later.

* the generic tool runs admission against the **retained artifact** — the exact
  bytes already built and verified, never a rebuild;
* admission emits an **immutable receipt** carrying the five identities, the
  composition digest and clause 5's six fields (§ 4.3) — **specified once, in
  § 4.3, and referenced here.** Revision 4 restated it in the defeated battery's
  vocabulary, which is two specifications of one record;
* **publication and authorization consume that receipt.** They do not re-derive
  it, re-run the battery, or rebuild anything.

This is build-once (§ 6A) applied to admission itself. A publication step that
recomputed admission would be a second authority over it, and the two would
agree until the day one changed — the same failure the whole redirection removes
at the profile level.

It also closes the § 6C gap by construction rather than by discipline: the
parser acquires a production caller because the release path calls it, so the
enforcement premise stops being a claim about code nothing runs.

**This section is design. The wiring is implementation** and is not in this PR.

---

## 13.1 THE RULE adopted against this document's own recurring defect

Three consecutive review passes found the same class: **a ruling landed in the
narrative and did not reach the schema table or the negative matrix.**

* revision 2 → 3: the five-identity repair reached § 1.1 and not § 4.1 / § 4.2;
* revision 3 → 4: —
* revision 4 → 5: the challenge-space ruling reached § 3.3b and not § 4.3,
  § 12A or § 3.1, which still asserted the design it defeats.

Each time the prose was right and **an implementer building from § 4 would have
built the defeated shape.** That is worse than an unmade decision, because the
document reads as though the decision was made.

> **When a ruling lands, the schema table and the negative matrix are edited in
> the SAME change as the narrative — and any superseded section is marked
> superseded, not left standing.**

The failure mode has a name in this document already: two statements of one
thing, agreeing until one is improved. § 3.1 carried a `battery_version` in the
join key that § 1.1 and § 4.2b did not, which is exactly that.

**A design document is not exempt from the rule it is written to impose.**

---

## 13. What this document deliberately does NOT do

* no Platform build tool or semantic translator;
* no Platform module declarations or entry-point group is claimed or reserved;
* no ADR number is allocated — this is a proposal in
  `docs/superpowers/specs/`, which the repository defines as
  **non-authoritative intent**. It becomes authoritative by an accepted ADR, not
  by being merged.
