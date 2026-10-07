# dotmac-integration

The external connector control plane (ADR-0024): installations, immutable
configuration revisions, capability bindings, secret references, and a versioned
connector SPI.

The module holds no provider knowledge. It contains no provider enum, no import
list and no `if provider == ...` branch (ADR-0024 § 7) — a connector is an
independently released distribution the module discovers through entry points,
and everything the module knows about one it learned from a declaration it
verified.

## Release state

**Released: `0.1.0a1` through `0.1.0a17`; `0.1.0a18` is declared and
unreleased.** Releases a2–a4 implement SPI 1.1;
a5–a9 implement SPI 1.2; a10 adds SPI 1.3's
manifest-owned secret-binding and egress declarations. See `CHANGELOG.md`,
which is the authority on what has and has not shipped. a8 adds indexed,
revisioned shadow-comparison evidence; a9 adds finite replay-evidence retention
and durable legal-hold history. a11 makes the existing POLL protocol executable
through a session-free provider phase followed by atomic receipt/cursor commit.
a12 projects one authenticated product-port descriptor onto every binding that
carries its capability, without putting a binding list in the assembly.
a13 accepts the product-owned v2 descriptor and projects a generic
ProductObservation v1 document with engine-derived installation provenance;
connector SPI remains 1.3.
a14 adds typed outbound provider evidence, delivered-payload retention and SPI
1.4's explicit capability-to-mode mapping.
a15 refuses changed-effect reuse of an outbound idempotency key and contains
concurrent enqueue uniqueness failures behind typed, material-safe outcomes.
a16 adds the domain-owned capability payload contract, durably stores its
validated command result, and gives polling one module-owned lifecycle,
due-job selector, retry state and bounded failure-history sweep; raw provider
response bodies remain unrepresentable. The module chooses no polling cadence
and no failure-retention period.
a17 accepts product-port descriptor v3: the owning product now carries its
capability payload contract (or dated schema grace) and independently names the
wire the assembly must render. The module persists and revalidates both without
authoring either contract.

**Declared, unpublished `0.1.0a18`:** its source adds additive SPI 1.5's
provider-neutral plan/apply/observe/cancel contract and SPI 1.6's bounded,
provider-neutral synchronous REQUEST contract. It adds no
persistence, migration or assembly wiring. `0.1.0a17` remains the latest
release; no consumer may exact-pin a18 until the protected release tags it.

Capability `config_schema` declarations are executable contracts, not catalog
metadata. A revision is accepted only when it matches every capability bound to
the installation; a new revision or changed binding invalidates activation
until static and live connection validation succeed again. Configuration
identity includes both content and `schema_version`.

## Where to read what

| | |
|---|---|
| The SPI, and what it promises | `COMPATIBILITY.md` |
| What has shipped | `CHANGELOG.md` |
| The as-built module | the docstring in `src/dotmac_integration/__init__.py` |
| Extraction provenance | `EXTRACTION.toml` |

## The SPI in one page

A connector distribution registers one entry point in the
`dotmac_integration.connectors` group, resolving to a plugin that satisfies
`ConnectorPlugin` — identity, metadata, `validate_connection` — plus one
protocol per mode it declares:

| Mode | Protocol | Factory | Returns |
|---|---|---|---|
| `DELIVERY` | `DeliveryPlugin` | `handler_for` | `CapabilityHandler` |
| `INGRESS` | `IngressPlugin` | `ingress_handler_for` | `IngressHandler` |
| `POLL` | `PollPlugin` | `poll_handler_for` | `PollHandler` |
| `PROVISION` | `ProvisionPlugin` | `provisioning_handler_for` | `ProvisioningHandler` |
| `REQUEST` | `RequestPlugin` | `request_handler_for` | `RequestHandler` |

A declared mode is a promise the module verifies at discovery, in both
directions and including the shape of the handler that comes back. A mode
declared and not implemented fails at the first dispatch; one implemented and
not declared never gets its workers started. Both used to pass.

For `PROVISION`, the owning product supplies an ordered plan and its canonical
hash. The connector may validate and execute that plan but the Integrator
refuses any returned plan that inserts, removes, reorders or rewrites a step.
The current slice deliberately stops at that call boundary.

For `REQUEST`, a domain-owned capability id selects one operation. Its existing
`command_schema` bounds input and `observation_schema` bounds normalized output;
there is no raw URL, path, method or header passthrough. The module performs at
most two attempts by default, retries only `provider_unavailable` and `timeout`,
and caps configurable attempts at five. A connector may perform one internal
401/403 re-authentication-and-replay inside one module attempt. `prepare_query`
pins an enabled binding, installation, compatible manifest and immutable config
revision under the shared runtime/quarantine admission authority; only after the
database session closes does `execute_prepared_query` materialize secret refs.

Ingress connectors receive one immutable `IngressRequest` — the raw bytes, the
headers and the query params, preserved exactly and handed to all three hooks as
the same object, so what was authenticated and what was interpreted are provably
the same bytes. They hand back an `Acknowledgement`, which carries the response
**body** and **media type** and deliberately cannot carry a **status code**: a
connector must be able to satisfy a provider's exact handshake format without
being able to lie about whether the engine accepted the request.

SPI 1.2 lets `verify` return a `VerificationResult`: acceptance plus positions
in an ordered active-secret set, with no field capable of carrying a secret
name, reference or value. The assembly may observe that provider-neutral result
for rotation metrics. SPI 1.1 boolean results remain valid.

The module also carries product delivery provenance without owning product
meaning. A destination application publishes one authenticated
`ProductPortDescriptorSnapshot`;
`reconcile_product_port_descriptor_for_capability` verifies and appends the
snapshot to every matching binding's destination revision history. Claimed receipts
carry their durable `provider_event_id` and module-derived installation source
into `ProductRequest`; `product_observation_document` then serializes the
provider-neutral envelope without interpreting the product-owned observation. And
`InboundDisposition.RECORD_ONLY` closes transport evidence that must never
enter the product consequence worker. These are engine contracts, not provider
branches.

## Operating the outbound runtime

**This module ships no HTTP routes, no login flow and no operator UI.** Its
manifest declares no `permissions` and no `capabilities` for exactly that
reason: both exist to gate a route, and there is none here. Every control below
is a Python call made inside the composing assembly's own transaction.

That matters because it is the thing a runbook gets wrong. **There is no
`/platform/auth/login` step for operating this queue.** That route is real — it
is `dotmac_kernel.platform_auth.platform_auth_router`, mounted by the kernel's
`create_app`, host-gated to `PLATFORM_ROOT_DOMAIN`, and it authenticates a
`PlatformAdmin` against the STARTER assembly's control plane (see the starter's
`README.md` and `docs/inventories/starter-surfaces.md`). It is not this module's
operator flow, and it does not reach this module's tables: the starter assembly
does not compose `dotmac-integration` at all (`docs/MODULE_CATALOG.md` — "not
installed here"). Authenticating there and expecting to reach an outbound queue
authenticates against a deployment that has none.

The real operator surface belongs to the `dotmac_integrator` assembly, which
composes this module and owns whatever authentication, routes and guards it
exposes over the calls below. Anything else is that assembly's documentation to
write, not this package's to assume.

| Operator intent | The one call |
|---|---|
| Stop ONE connector consuming the queue | `lifecycle.quarantine(db, installation, reason=…)` |
| Let it back in | `lifecycle.release_quarantine(db, installation, reason=…)`, then `lifecycle.enable(…)` |
| Stop the WHOLE deployment dispatching | `ExecutionPolicy(dispatch_enabled=False)` |
| Bound concurrent provider calls | `ExecutionPolicy(max_in_flight_per_installation=N)` |
| See what is stuck | `operations.health_report(db)` |
| See how the queue is behaving | `operations.dispatch_metrics(db)` |
| Requeue a dead letter | `operations.replay_delivery(db, delivery, reason=…)` |
| Recover a dead worker's rows | `operations.release_expired_leases(db)` |

Three properties worth knowing before using any of them:

* **quarantine is per INSTALLATION, and it deletes nothing.** It stops every
  capability that installation serves — a binding is a route into it and a
  capability is a contract many installations implement, so neither is the unit
  of distrust. Queued deliveries, leases and retry schedules are left exactly
  as they were, and both entering and leaving quarantine write a platform audit
  event. `admission`'s module docstring carries the full reasoning.
* **the kill switch halts, it does not purge.** `dispatch_enabled=False` refuses
  admission before anything is claimed; the outbox is untouched and resumes on
  its own schedule when the switch goes back.
* **a provider 429 is retryable, never terminal**, and its `Retry-After` wins
  over the backoff curve. A throttle also delays that installation's other
  queued deliveries, in the database — the pause is a `next_attempt_at`, never a
  sleep, so no session is ever held waiting on a provider.

`operations.dispatch_metrics` returns numbers under stable, language-neutral
names (`operations.METRIC_NAMES`); it does not export them. There is no metrics
client in this package, deliberately: the exporter belongs to the assembly, the
same way the HTTP surface does.

## Certifying a connector

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

The conformance kit is shipped as library code rather than left in this repo's
test tree, because a kit that lives in the host's tests cannot be imported by the
distribution it is meant to certify. It reaches no network and needs no
credentials.
