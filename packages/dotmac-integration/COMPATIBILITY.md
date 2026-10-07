# dotmac-integration — the connector SPI, and what it promises

This is the prose companion to `dotmac_integration.spi`. The module is
authoritative; where this document and the code disagree, the code wins and this
document is the bug.

## Release state

| | |
|---|---|
| Released | `0.1.0a1` through **`0.1.0a17`**; a2–a4 implement **SPI 1.1**, a5–a9 implement **SPI 1.2**, a10 implements **SPI 1.3**, a11 adds executable polling, a12 adds capability-wide product-port reconciliation, a13 adds ProductObservation v1 projection, a14 adds additive **SPI 1.4** capability modes plus outbound evidence/retention, a15 adds typed outbound repair and runtime safety, and a16 adds the domain-owned payload gate plus durable polling evidence, and a17 adds product-port descriptor v3, carrying the domain's payload contract or dated grace separately from the product wire without changing SPI 1.4 |
| Declared, unpublished | `0.1.0a18` contains additive **SPI 1.5** provisioning and **SPI 1.6** bounded synchronous `REQUEST` source, with no persistence migration. It is not a release, and nothing may exact-pin it until the protected release tags exact `0.1.0a18` |

SPI 1.2 is additive. It accepts the same closed `>=1.0,<2.0` ranges and adapts
SPI 1.1's boolean ingress-verification result to the evidence-free form of the
new result. That obligation is discharged by tests, not by this sentence — see
"SPI 1.0 still works" and "Verification evidence" below.

SPI 1.3 is additive at the executable seam and explicit at the deployment
seam. A current manifest declares named secret bindings and an exact external
host allowlist; exact private single-label DNS service names are valid, while
the reserved `localhost` name, URLs, wildcards, IP literals and trailing-root-
dot forms remain invalid. The
empty allowlist means deny-all. Pre-1.3 manifests remain
readable during adoption and keep their digest. A connector whose declared
minimum is 1.3 cannot omit either runtime declaration.

SPI 1.4 adds an optional mode set to each capability declaration. Omission
retains the published 1.0–1.3 meaning: all plugin modes serve the capability.
When present, the mapping is exact, included in the manifest digest and checked
at discovery and invocation. This lets one plugin expose an ingress-only
receive capability and a delivery-only send capability without either factory
lying about the other.

SPI 1.5 adds the `PROVISION` mode and one handler with typed `plan`, `apply`,
`observe` and `cancel` operations. It does not move payload ownership into the
connector: the product still owns the capability contract and exact plan, and
the connector still claims only that contract's digest. The Integrator refuses
a rewritten plan before any later persistence layer could accept it.

SPI 1.6 adds the `REQUEST` mode for bounded caller-initiated reads. The existing
domain-owned `command_schema` validates request input and `observation_schema`
validates normalized success output, so existing contract digests and descriptor
v3 documents do not change shape. `QueryRequest` carries a stable opaque
Integrator installation key for connector session isolation and cannot express
an arbitrary URL, path, method or header. General retries are module-owned,
bounded to five attempts, and limited to unavailable/timeout results; connector
session recovery is limited to one internal 401/403 re-authentication replay.

The `InboundEvent.disposition` field declared for a7 defaults to `deliver`.
Existing connectors therefore keep their behaviour; connectors may explicitly
mark transport-only evidence `record_only` so the engine persists and closes it
without scheduling a product consequence.

## Two version axes, and only one of them is this package's version

| Axis | Constant | What it gates |
|---|---|---|
| Package version | `pyproject.toml`, `__version__` | which wheel you installed |
| **SPI version** | **`CURRENT_SPI_VERSION`** | **what a connector may assume about the contract** |

They move independently. A package release that fixes a type annotation does not
touch the SPI; an SPI change is what a connector's `spi_range` is checked
against.

`SpiVersion` is `major.minor` with no patch component — a patch that changes
nothing a plugin can observe does not belong in a compatibility decision. Major
is the break; minor is additive-or-safe. A connector declares a CLOSED range
(`>=1.0,<2.0`); an open-ended range is refused rather than defaulted, because
"works with any future SPI" is a claim no author can honestly make.

The range is checked at **discovery**, again at **startup**, and again at
**activation**. That looks redundant and is not: a distribution can be installed
after discovery ran, and a binding activated long after startup.

## What a connector implements

### The base

Every plugin satisfies `ConnectorPlugin`: `manifest`, `historical_manifests`,
`modes`, `validate_connection`. Identity and metadata only — nothing on the base
moves data.

Each capability's `config_schema` is Draft 2020-12 JSON Schema and is enforced
by the module. Malformed schemas fail at declaration; configuration is checked
before revision write, binding, and activation. An empty schema remains the
explicit "no capability-specific constraint" declaration. A connector's
validation `detail` is diagnostic material and may contain resolved values, so
the module never persists or renders it; only a bounded machine `code` crosses
that boundary.

### One protocol per mode

`ConnectorMode` is a **closed** union of five members. Each adds exactly one
factory:

| Mode | Plugin protocol | Factory | Returns |
|---|---|---|---|
| `DELIVERY` | `DeliveryPlugin` | `handler_for` | `CapabilityHandler` |
| `INGRESS` | `IngressPlugin` | `ingress_handler_for` | `IngressHandler` |
| `POLL` | `PollPlugin` | `poll_handler_for` | `PollHandler` |
| `PROVISION` | `ProvisionPlugin` | `provisioning_handler_for` | `ProvisioningHandler` |
| `REQUEST` | `RequestPlugin` | `request_handler_for` | `RequestHandler` |

That table is `MODE_PROTOCOLS`, a read-only mapping asserted exhaustive at
import. A mode cannot be added without deciding what makes it runnable — the
omission that left `POLL` a label with no machinery behind it throughout SPI 1.0.

**Why an enum here, when ADR-0008 says a new vocabulary is a declaration
registry and never an enum.** This module obeys that rule for the vocabulary
that is genuinely open: a capability id is a regex-validated `domain.noun.vN`
string, declared by the connector, with no enum anywhere — because the module
never has to *implement* a capability, it routes one. A mode is the opposite
kind of name. Every member obliges the **engine** to run machinery only the
engine can supply: `DELIVERY` a dispatch worker, `INGRESS` a mounted route and a
verify/normalize pipeline, `POLL` a scheduler and the cursor it persists. A
product cannot bring that machinery with it, so a product-declared mode would be
a label with nothing behind it. The union is closed three ways — an `Enum` with
members cannot be subclassed, `ConnectorMode("invented")` raises, and
`MODE_PROTOCOLS` cannot be written to — and each is proved to bite in
`tests/unit/test_integration_spi_modes.py`.

### A declared mode is verified, both ways, at discovery

`spi.verify_plugin_modes` runs inside `discovery.discover` and inside
`conformance.assert_plugin_conforms` — the same function, so an author's suite
and the host's boot cannot reach different verdicts. It refuses:

1. a mode **declared and not implemented** — otherwise it fails at the first
   dispatch;
2. a mode **implemented and not declared** — otherwise the runtime never starts
   the workers that would call it, and the connector looks installed and inert;
3. a factory returning a handler of the **wrong shape** — checked against the
   mode's handler protocol, not merely for non-null. A factory handing back a
   delivery handler where an ingress handler was promised satisfies "not None"
   perfectly and then fails on a provider's request;
4. a connector declaring **no modes at all**.

This calls plugin code at boot. That is intended: a factory is an in-process
lookup returning a callable — it materializes no secrets and contacts no
provider — and a factory that cannot survive being called at boot would not have
survived a request either.

`dispatch.invoke` additionally calls `require_mode(plugin, DELIVERY)` before the
handler lookup, so a binding pointed at a connector that cannot deliver produces
a stated refusal naming the connector and what it *does* declare.

The POLL mode is executed by `prepare_poll` -> `invoke_poll` ->
`record_poll_batch`. Provider I/O runs after the prepare unit of work has closed;
the normalized batch and next cursor then commit together. This is package
machinery rather than a new SPI shape in a11. The source in declared,
unpublished a18 now sets `CURRENT_SPI_VERSION` to 1.6 for the additive
provisioning and synchronous request contracts; a17 remains the latest release.

## The ingress contract

### `IngressRequest` — one immutable envelope

The raw body, the headers and the query params, handed **unchanged and as the
same object** to `challenge`, `verify` and `normalize`.

- **Nothing is normalised on the way in.** The engine's obligation is to hand
  over what it received: the body as the exact bytes off the wire, and header
  and query names and values exactly as they arrived — not lowercased, not
  trimmed, not decoded, not re-encoded. This type preserves whatever it is
  given and adds nothing. **An engine that normalises before constructing the
  envelope has already broken the contract, and no check inside the SPI can see
  that it did.**
- **The same object, not an equal one.** What `verify` authenticated and what
  `normalize` interpreted are then provably the same bytes. An engine that
  re-read or re-decoded between the calls would authenticate one thing and
  normalize another, and a signature check that guards a different byte string
  guards nothing.
- **Immutable for real.** `frozen`, `slots`, and the mappings copied and then
  wrapped in `MappingProxyType` — a plugin can neither edit the engine's view
  nor watch the engine edit it afterwards.
- **`repr=False`.** It is a frame local in every traceback leaving the plugin
  phase and it holds the raw body, the signature header, and any authorization
  header or cookie a misconfigured proxy passed through. The values are still
  there; this is a rendering rule, not a removal.

**Stated limit of 1.1:** `headers` and `params` are `Mapping[str, str]`, so a
repeated header or query key is not expressible and an engine handing one over
must pick a value. No provider handshake or signature scheme in the requirement
record repeats a key. The escape hatch is purely additive — a later minor may
add multi-valued views beside these without breaking a single connector — which
is why freezing the scalar view now costs nothing later.

### `Acknowledgement` — the connector owns the body, the engine owns the meaning

| | Owner |
|---|---|
| response **body** (`bytes`) | the **connector** |
| response **media type** | the **connector** |
| response **status code** | the **engine** |
| response **headers** | nobody — not expressible |

This split is the whole point of the type. A connector must be able to satisfy a
provider's exact handshake format — a raw echo, a `{"status":"ok"}`, an empty
200 — without being able to lie about whether the engine accepted the request.

- The body is `bytes`, not `str`, for the same reason `verify` takes bytes: a
  provider comparing an exact response body is comparing bytes, and an
  engine-chosen encoding would be a guess.
- A **status code is a retry instruction**. 200 means "never send this again",
  5xx means "send it again", 4xx means "stop and page someone". A connector
  choosing it could discard events the engine believes are safely persisted, and
  only the engine knows whether the batch committed.
- **Arbitrary headers** are a response-splitting surface and a place for request
  material to be echoed back out of the module's sight. Not needed by any
  handshake in the requirement record, so withheld rather than granted and
  policed.
- `media_type` is validated against a strict `type/subtype` (optional charset)
  because it IS a header value; an unvalidated one carrying CRLF is header
  injection with extra steps. `None` means "the engine picks", and
  `Acknowledgement.resolved(default)` is how the engine fills it.

### The three hooks

- `challenge` answers a provider's subscription handshake, and is an **explicit
  operation** the engine reaches through its own handshake entry point — never
  inferred from the shape of a request. A bodyless POST is still a DELIVERY, and
  a provider that confirms a subscription with a bodied request must still be
  able to handshake. Returning `None` is a refusal.
- `verify` decides authenticity from `request.raw_body`. It may return SPI
  1.1's `bool` or SPI 1.2's `VerificationResult`.
- `normalize` shapes a verified request into `(events, acknowledgement)` and is
  never called on an unverified body. It builds the acknowledgement because it
  is the last connector code that runs: the engine records the batch after
  `normalize` returns and emits the acknowledgement only once that batch has
  committed, so calling back into the plugin afterwards would put plugin
  exceptions on the far side of a durable write.

`config` reaches `normalize`; `secrets` deliberately does not — normalization
that needs a secret is doing verification in the wrong place.

### Verification evidence — positions, never material

`VerificationResult` contains an acceptance bit and an increasing tuple of
positions in the connector's ordered active-secret set. It cannot carry a
secret name, secret-store reference or value. This is enough for an assembly to
count how often an old or new signing secret matched during rotation while
remaining provider-neutral.

The ingress engine reports the result through an optional observer before
normalization. A failing observer is ignored: metrics are evidence, not an
availability dependency. A legacy boolean becomes the same result with an empty
position tuple. Any other object is a connector-contract refusal rather than an
implicit authentication through Python truthiness.

## SPI 1.0 still works

`tests/unit/test_integration_spi_modes.py` carries a hand-written SPI 1.0
delivery-only connector: `handler_for` directly on the plugin, `modes` naming
`DELIVERY` and nothing else, `>=1.0,<2.0`, and no knowledge of ingress, poll,
`IngressRequest` or `Acknowledgement`. It is deliberately not built from the
conformance kit — a compatibility claim proved with the current release's own
helper proves the helper, not the compatibility.

It is proved to **discover**, to **conform**, and to actually be **dispatched
to**. The range check is separately proved live, so "`>=1.0,<2.0` is admitted"
is a fact about the range rather than about nothing being checked.

This is why SPI 1.1 and 1.2 are minors. A major would have excluded every honest
`>=1.0,<2.0` delivery connector in order to protect a compatibility promise
nothing ever consumed.

## Polling evidence is an ENGINE contract, not an SPI one

`0.1.0a16` gives the poll loop durable retry state, a never-rewritten failure
history and a bounded keyset selection (`dotmac_integration.poll_schedule`). A
connector sees none of it. `PollHandler.poll` is unchanged — same parameters,
same return shape, same "raise to signal failure" — so no connector needs
recompiling, re-certifying or re-pinning, and the SPI version does not move.

What changed is what the ENGINE does around that call, and the three properties
a consumer may rely on:

* **the vocabulary is closed and it is the engine's.** Every persisted failure
  is one of eight `POLL_FAILURE_CODES` derived from this package's own exception
  types. A connector's `error_code` never reaches it, and neither does an
  exception message: the evidence table has no free-text column, which is the
  strongest form of that promise available — a rule enforced by the absence of a
  place to break it. The single bounded exception is a connector exception's
  TYPE NAME, sanitized to a bare Python identifier at the raise site and
  re-checked at the write;
* **the engine owns the FLOOR, never the CADENCE.** `next_attempt_at` means
  *not before*. This package will not grow a polling interval: that is a
  deployment's decision about one provider, and a library that chose it would be
  shipping a schedule. A worker wakes on its own cadence and asks
  `due_polling_jobs` what is eligible;
* **a poll job is never dead-lettered.** A failing outbound delivery eventually
  is. A failing poll must not be, because a provider stream nobody is reading
  has no symptom but missing facts. The backoff curve saturates at
  `ExecutionPolicy.max_backoff_seconds` and the job stays selectable forever.
  Stopping a poll stays a lifecycle gesture with an audit trail: disable the
  binding or the installation.

`due_polling_jobs` selects and claims nothing. Two workers may see the same
page; the checkpoint's optimistic `version` decides which one settles, and the
loser records a `checkpoint_conflict` rather than losing a batch. Adding a lease
would be a second claim over a row that already has a stronger one.

Backoff is not redefined here — `poll_backoff_seconds` delegates to
`retry.retry_delay_seconds`, which stays the one owner of the curve for the
outbox and the poll loop alike.

## Product-port descriptor v3 carries the domain contract

`0.1.0a17` closes the assembly gap exposed by a16's fail-closed payload gate.
The authenticated product-port descriptor carries the owning domain's exact
`CapabilityContract` document: command, result and observation schemas or one
dated `SchemaGrace`, plus its canonical digest. The module parses and persists
that declaration and refuses disagreement with the installed registry; it does
not create a schema for the product.

Descriptor protocol version and `wire_schema_version` are separate. Messaging
may still require its established envelope while settlement renders the generic
ProductObservation wire; adding payload-contract metadata must not collapse
those two product protocols into one ambiguous assembly branch. This is an
engine/storage addition only. Connector SPI remains 1.4.

`ensure_polling_checkpoint` is the declaration lifecycle; it does not list
work. `due_polling_jobs` is the sole scheduling selector. Failure-history
deletion is likewise one typed bounded operation,
`prune_poll_failure_history`, and requires a timezone-aware cutoff supplied by
the adopting product. Neither a cadence nor a retention duration is part of
this package's compatibility contract.

## What would force a major (2.0)

- removing or renaming a member of `ConnectorMode`, or a factory on a mode
  protocol;
- changing the parameters or return type of `handler_for`, an `IngressHandler`
  hook, or `PollHandler.poll`;
- moving a member onto `ConnectorPlugin` that every connector must then supply;
- narrowing what `IngressRequest` preserves, or granting the connector any part
  of the response the engine currently owns.

Additive and **not** a major: a new mode with a full `MODE_PROTOCOLS` entry, a
new optional field on `IngressRequest` (multi-valued header/param views), a new
field on `ConnectorManifest` with a default, a new `Diagnostic` code.

## Conformance

A connector distribution certifies itself from its own test suite:

```python
from dotmac_integration.conformance import (
    assert_connector_conforms,
    assert_plugin_conforms,
)
from my_connector import MANIFEST, PLUGIN


def test_manifest_conforms() -> None:
    assert_connector_conforms(MANIFEST)


def test_plugin_conforms() -> None:
    assert_plugin_conforms(PLUGIN)
```

The kit reaches no network and needs no credentials: the whole
installation/configuration/binding/dispatch slice must be provable without a
provider, and a kit that needed credentials would make every author's first
encounter with the SPI a secrets problem.

The kit **owns no rules**. Every mode refusal is `spi.verify_plugin_modes`,
which `discovery.discover` also runs; the kit only translates it into an
`AssertionError` an author's suite can read.

## What the module may never contain

ADR-0024 § 7: no fixed provider enum, no import list, no `if provider == ...`
branch. Which part of a request identifies a handshake, which header carries a
signature, and what a provider wants echoed back are all connector knowledge —
which is why the whole envelope is handed over and the whole acknowledgement
body comes back, rather than the module selecting either.
