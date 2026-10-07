# Changelog — dotmac-integration

## Release state — read this before pinning

**Seventeen versions have been released. Pin `0.1.0a17`.** Tags
`dotmac-integration-v0.1.0a1` … `-v0.1.0a17`; a17 was published, installed back
from the private index, registered and tagged from exact revision
`2cab76b442e6cc6c8ed81a409d943ba250351c3d` by release run `33043793199`, whose
build, publish and verify jobs all succeeded. a16's is `32929018760`, from exact
revision `dcab4559b6dcc2c38737dd65ce6bb2f5ba59df0e`. a17's released migration
digests are recorded in `tests/architecture/test_released_migrations.py`'s
`RELEASED_TAGS`.

`0.1.0a17` is the latest published version. `0.1.0a16` adds domain-owned
payload contracts and durably stores a validated normalized result in
`ig_0013`, and adds durable polling attempt/failure/backoff evidence with a
bounded keyset selection in `ig_0014`.

`0.1.0a17` is RELEASED — tagged `dotmac-integration-v0.1.0a17` on 2026-08-27,
peeling to `2cab76b442e6cc6c8ed81a409d943ba250351c3d`. It adds authenticated
product-port descriptor v3, which carries the owning domain's exact payload
contract or dated grace separately from the product wire, persisted by
`ig_0015`.

`0.1.0a11` keeps SPI 1.3 and makes the declared POLL mode executable through a
three-phase engine; it was published and tagged from `f25df1ad`.

**Do not pin `0.1.0a1` or `0.1.0a2`.** Their discovery path renders a
connector's own exception message into `ModeContractError` and chains it as
`__cause__`, so any secret a connector interpolates into its error reaches the
operator's boot log, the traceback and any handler using `exc_info`. `0.1.0a3`
fixes it.

**`0.1.0a3` still carries the persisted-exception-text defect**, which `a4`
fixes: `dispatch.invoke` wrote a connector's exception message into
`error_detail`, a column `execution` persists — so a connector that
interpolated a materialized credential into its own exception stored it, where
it outlives the request, the process and the credential's rotation. Prefer a4.

`0.1.0a5` was published, installed back from the private index, composed and
tagged on 2026-08-17 from `7828697`. Its publication-ledger row was retired in
the immediately following release-record change.

`0.1.0a6` was published, installed back from the private index and tagged on
2026-08-17 from `7e05430`. It keeps SPI 1.2, makes the platform-audit storage
dependency explicit and restores installation/configuration lifecycle parity.

`0.1.0a7` was published, installed back from the private index and tagged on
2026-08-17 from `c669b24` while the independent a8 branch was being rebased.

`0.1.0a8` was published, installed back from the private index, registered and
tagged on 2026-08-17 from `4b1e867` by release run `32050382156`.

`0.1.0a9` was published, installed back from the private index, registered and
tagged on 2026-08-18 from `92ae7a6` by release run `32102257979`.

`0.1.0a10` was published, installed back from the private index, registered and
tagged on 2026-08-19 from `7a59864` by release run `32230755284`.

`0.1.0a11` was published, installed back from the private index and tagged on
2026-08-22 from `f25df1ad`.

This section exists because the `0.1.0a2` heading previously carried a date and
read exactly like a release entry while being unreleased — and a changelog that
misdescribes what is installable is how a consumer comes to pin something that
does not exist, or something it should not. It has since been wrong in the other
direction four times: a2, a3, a12 and now a17 were each tagged while this
preamble still called them unreleased — a12 for long enough that it told readers
to pin a11 while `dotmac_integrator` was already composing a12, and a17 for long
enough that an allocation change for a18 had to correct it. Four recurrences of
one defect is a counting problem, not an attention problem: nothing fails when
this preamble disagrees with the tag namespace, so it drifts every time and is
found by a human reading it. The table of tags and
commits above is what a reader should trust, because `git ls-remote --tags`
checks it.

Check it with `sort -V`. `git ls-remote --tags | tail` sorts lexicographically,
where `a12` falls between `a11` and `a2` rather than after `a11` — which is how
a published a12 came to be read as absent while this preamble agreed with the
mistake.

Everything under a `## 0.1.0a2` heading below shipped in that tag. There are
four such headings because a2's content landed across four merges (SPI 1.1,
receipt delivery, retention, the type gate) and each wrote its own section
before the version was cut. They are not four releases.

Nothing in this file is a publication claim except this section.

## 0.1.0a18 — unreleased

a17 is published (tag `dotmac-integration-v0.1.0a17`); a18 was allocated
ahead of source so the durable provisioning-runtime work could not share a
version number with a17's published contract. That work has now landed:

- Adds **SPI 1.5**: a fourth closed `ConnectorMode`, `PROVISION`, with one
  `ProvisioningHandler` implementing `plan` / `apply` / `observe` / `cancel`.
- `provision_plan_hash` is the canonical plan identity; `plan_provisioning`
  raises `ProvisionPlanRewritten` on any step drift — a connector may
  validate a plan, never rewrite it.
- `ProvisionResultStatus` is closed: `SUCCEEDED` is not "provisioned",
  `ACCEPTED`/`PENDING` means the provider took the command and the caller
  must observe, and a `NOT_FOUND` from `cancel` does not establish whether an
  effect never existed or was already removed.
- Carries no execution owner: no table, no lease, no retry, no idempotency
  claim, and no `a18` persistence migration. The durable runtime that makes
  these calls survivable is a separate, later change.

- Adds **SPI 1.6**: a fifth closed `ConnectorMode`, `REQUEST`, with immutable,
  repr-hidden `QueryRequest`/`QueryResult` values and one `RequestHandler`.
- Reuses the domain-owned `command_schema` for bounded request input and
  `observation_schema` for normalized output, preserving all existing contract
  digests and product-port descriptor v3 documents.
- Adds a persistence-free invocation boundary with a module-owned immutable
  retry policy: two attempts by default, five maximum, exponential capped
  backoff, and retries only for `provider_unavailable` or `timeout`.
- Adds `prepare_query`/`PreparedQuery`, reusing enabled binding/installation,
  manifest pin, capability digest/mode and runtime/quarantine admission checks.
  Invalid input is refused before the assembly materializes secret references.
- Gives a process-global connector a stable opaque installation key for session
  isolation. Provider credentials/config remain repr-hidden connector material;
  products receive neither. One 401/403 re-authentication replay remains inside
  a connector attempt and an exhausted unauthorized session is not retried.
- Accepts strict lower-case single-label DNS egress destinations such as a
  private Compose service alias, while continuing to reject URLs, paths,
  wildcards, IP literals, the reserved `localhost` name and trailing root dots.

Still unreleased. See `docs/inventories/declared-publication-baseline.json`
for the recorded declared-unpublished state.

## 0.1.0a17 — 2026-08-27 — RELEASED

### The product descriptor now carries the product's payload contract

- Accepts `dotmac.io/product-port-descriptor/v3`. Its nested capability
  contract carries the domain-owned command, result and observation schemas or
  an explicit dated `SchemaGrace`, plus the canonical contract digest.
- Parses the exact field set, re-derives the domain contract and refuses a
  changed schema behind a stale digest or disagreement with the installed
  registry. The module validates and stores the product declaration; it never
  invents compatibility in the Integrator assembly.
- Adds an independent `wire_schema_version`. Descriptor version is metadata
  protocol, not product payload protocol: messaging's established envelope and
  settlement's ProductObservation wire remain distinct without a capability or
  provider branch in the assembly.
- Adds `ig_0015_descriptor_contract`, persisting both v3 fields on the immutable
  destination revision and constraining legacy v1/v2 rows to carry neither.
- Connector SPI stays 1.4. This is the serial prerequisite for a thin assembly
  to accept product-owned a16 contracts without constructing silent registry
  entries.

## 0.1.0a16 — 2026-08-26 — RELEASED

### One capability id now means one PAYLOAD, and the domain owns it

ADR-0024 §§ 10-12 and ADR-0061 A2. A capability id was already one contract with
one owner; its payload was not. `CapabilityDeclaration` carried a config schema
and `DispatchRequest.payload` was an unvalidated `dict[str, object]` — so
configuration had a declared contract and commands did not, which is how one id
grew two disjoint command vocabularies with nothing able to see it.

- `CapabilityContract` — the declaration the owning BUSINESS application
  publishes — gains `command_schema`, `result_schema`, `observation_schema`, a
  canonical `contract_digest` over those three plus the id, and
  `ContractDeprecation` (`replaced_by`, `retire_after`). Schemas are validated
  at construction, exactly as `config_schema` already was.
- `CapabilityDeclaration` gains `claims_contract_digest` and NOTHING else. A
  connector never publishes a schema for a capability it merely implements: if
  every connector published one, drift would become machine-readable rather than
  prevented, because two connectors serving one id would declare two
  individually valid schemas and nothing could prefer either.
- **Four seams enforce it.** `execution.enqueue_delivery` validates the command
  before a row exists; `capability_registry.require_implements_only_declared`
  and `require_declared_for_binding` both check digest agreement — composition
  and binding, because a distribution can be installed after composition ran;
  `dispatch.settle` validates the result before the claim-guarded UPDATE; and
  `ingress.record_batch` validates every observation before the batch commits,
  which is also the polling path's gate because `record_poll_batch` calls it.
- **A published version is SUCCEEDED, never redefined.**
  `install_capability_registry` refuses a reload that gives an already published
  id a different digest, or that walks a published contract back into a grace; a
  deprecation must name a successor declared in the same registry; and a
  contract may not name itself as its own replacement.
- **Adoption is a declared, dated grace — not an optional field.** A contract
  that declares neither a schema nor a `SchemaGrace(reason=…, retire_after=…)`
  is refused at construction. `schema_grace_register` enumerates every ungated
  capability with its owner and deadline, and `require_no_expired_grace` (run by
  `require_governable`) refuses once a window has closed.
- `Outcome` gains `result` — the normalized outcome body ADR-0024 § 12.2 says a
  provider customer id, recipient code or transfer reference must arrive as. It
  is validated against the domain's `result_schema` before settlement, which is
  what distinguishes it from the unstructured evidence mapping
  `provider_status_code` exists to refuse.
- New refusal `ingress.ObservationRejected` (503, constant message) answers a
  provider; the detailed `CapabilityPayloadRejected` reaches every caller that
  is not answering one. Neither ever repeats the offending value — the summary
  is a JSON pointer and a failing keyword, because `error_detail` is persisted.
- `spi.canonical_digest` is now the ONE canonical-JSON hashing rule;
  `execution.payload_digest` delegates to it and keeps its meaning.
- Adds `ig_0013_delivery_result`. A validated `Outcome.result` is persisted
  atomically with settlement rather than discarded after validation, and ages
  out with the command payload under the same legal hold.
- **Not repaired here, and deliberately visible:** `messaging.send.v1` still has
  two connectors with disjoint command vocabularies. ADR-0024 § 11.2 repairs it
  by SUCCESSION rather than redefinition, so it stays in grace until Sub
  migrates. `tests/architecture/test_capability_contract_divergence.py` holds
  that and the four other shared-and-ungated capability ids in a
  two-directional ratchet.

### A failed poll now leaves durable evidence, and the engine backs it off

The three-phase POLL engine recorded a SUCCESS — receipts plus an advanced
cursor — and recorded nothing at all about a FAILURE. The durable state could
not say how many times in a row a job had failed, when it might safely be tried
again, or what kind of failure it was, so every assembly running a poll worker
answered those three questions itself. That is a parallel retry ledger and a
second writer of a decision this module already owned half of (the checkpoint's
optimistic `version`).

- New module `poll_schedule`, exported from the top-level namespace. It owns the
  retry state, the failure history and the selection query; the assembly gains
  no scheduler and no counter of its own.
- `PollingCheckpoint` gains `attempt_count`, `next_attempt_at` (NOT NULL),
  `last_attempt_at`, `last_success_at`, `last_failure_at` and
  `last_failure_code`. `attempt_count` counts CONSECUTIVE failures since the
  last success, not lifetime attempts.
- **Failure bookkeeping never touches `version`.** The version is a claim about
  the CURSOR, and a failed attempt moved no cursor; bumping it would make a
  concurrent in-flight settle lose a race that did not happen.
- New never-rewritten platform table `polling_attempt_failures`: attempt number,
  the checkpoint version the attempt worked against, the failure code, a
  sanitized connector exception TYPE NAME, the backoff actually applied and the
  resulting floor. **It has no free-text column at all** — the guarantee that
  connector or provider text never reaches a column is enforced here by the
  absence of anywhere to put it, rather than by a source scan.
- `POLL_FAILURE_CODES` is a CLOSED vocabulary of eight codes derived from this
  package's own exception types, enforced by a database check constraint. An
  unrecognised error is recorded as `settlement_failed` rather than given a new
  code. No connector `error_code` and no provider status reaches it.
- `poll_backoff_seconds` DELEGATES to `retry.retry_delay_seconds`. The curve,
  its ceiling and its overflow guard stay defined once.
- **A poll job is never dead-lettered.** A failing delivery eventually is; a
  failing poll must not be, because a provider stream nobody reads fails
  silently. The curve saturates at `ExecutionPolicy.max_backoff_seconds` and the
  job stays selectable. Suppressing a poll keeps its one existing owner:
  disable the binding or the installation.
- `due_polling_jobs` is a bounded KEYSET selection (`PollPageKey`, page size
  `INTEGRATION_POLL_PAGE_SIZE`, capped at 1000). It claims nothing — the
  checkpoint's optimistic `version` is already the stronger claim, and a lease
  here would be a second one over the same row. Ordering by
  `(next_attempt_at, id)` makes healthy jobs round-robin (a success stamps the
  floor with the moment of the success) and pushes failing ones behind their own
  backoff, so a permanently broken early checkpoint cannot starve the rows
  created after it. `poll_failure_history` pages the same way, newest first.
- `ensure_polling_checkpoint` is the one public declaration lifecycle for a
  `(binding, job_key)`. It validates the pinned POLL capability, contains an
  insert race with the kernel savepoint, returns detached state and never
  rewinds. It deliberately offers no listing method: `due_polling_jobs` remains
  the sole scheduling selector.
- The engine owns the FLOOR ("not before"), never the CADENCE ("every N
  seconds"). A polling interval is a deployment's decision about one provider.
- `poll_once` records every failing path before re-raising, in a FRESH unit of
  work so the evidence is not rolled back with the attempt it describes. There
  is no opt-out keyword: one would be a supported way to keep a private attempt
  counter instead. The write is best-effort — a broken recorder never replaces
  the operator's exception, and a lost record degrades toward MORE polling,
  never toward a job that silently stops.
- `PollConnectorRaised` gains a public `exception_type` attribute carrying the
  already-sanitized type name, so a persisting caller never has to parse the
  message.
- Adds `ig_0014_polling_evidence`. `next_attempt_at` is backfilled from
  `COALESCE(advanced_at, created_at)` before being made NOT NULL, so a
  deployment with an existing polling backlog keeps its ordering instead of
  having every job tied at the moment of the migration.
- `prune_poll_failure_history` owns the bounded oldest-first deletion mechanic.
  Its timezone-aware cutoff is mandatory and product-supplied: the package has
  no default age, environment read or hidden TTL. Failure rows are never
  updated, but they are not falsely described as immortal append-only facts.

### Declaring a binding no longer erases how it is selected

- `add_binding` is idempotent by contract, so every activation and reconcile
  sequence re-declares a binding that already exists. It wrote `scope_json` and
  `policy_json` unconditionally from parameters that defaulted to `None`, so a
  re-declaration naming only the capability reset both columns. `policy_json`
  is what `selection` reads to choose between several bindings enabled for one
  capability, so losing it stopped outbound dispatch with an ambiguity refusal
  while every control-plane state column still read `enabled`.
- Omitting `scope` or `policy` now PRESERVES the stored value; an explicit
  value — `None` included — is still a write, because "declares no scope" and
  "is not the selection default" have to stay expressible. The omission marker
  is `lifecycle.KEEP`, exported so an assembly forwarding an optional field can
  name it.
- Adds `set_binding_selection_policy` and `set_binding_scope` as the named
  owners of those two columns. Neither invalidates activation: selection is
  read live per dispatch and scope is display-only, so neither was ever
  validated by the connection check, and returning the installation to `draft`
  to change one would make relabelling a binding an outage.
- Enabling stays a lifecycle transition that writes no binding column. That is
  now asserted statically rather than merely intended
  (`tests/architecture/test_integration_lifecycle_writers.py`), including that
  the lifecycle owner cannot name `CapabilityDestinationRevision` at all — a
  destination is `establish_destination`'s decision and its own append-only
  table.
- No schema change: both columns already exist, and no migration slot is
  consumed.

## 0.1.0a15 — released 2026-08-24

Published, installed back from the private index, registered and tagged from
exact revision `bd8d2262c26f62041cc22a813916066b9af85c7f`.

### Outbound enqueue identity and race safety

- Refuses an idempotency key reused for a different event type, capability
  binding or payload digest instead of silently replaying the first row.
- Contains the expected uniqueness race inside a savepoint. A READ COMMITTED
  caller replays the winning row; a stale snapshot receives a typed retry
  instruction whose message cannot carry payload-bound driver parameters.

### Outbound replay, dead-letter repair and ambiguous-outcome reconciliation

- Adds `outbound_repair`, the single owner of whether a stored outbound command
  may become a live effect again. Every entry point routes through one
  `classify_repair` decision, so an inspection report can never show a row as
  repairable that the repair command then refuses.
- Replays a command by the `(installation, idempotency_key)` a product
  addressed it with. The re-dispatched request is the row's own stored payload,
  verified against the digest recorded at enqueue; neither entry point accepts
  a content parameter, so a replay cannot carry anything the recorded evidence
  does not describe.
- A replay of a command that already landed returns the recorded outcome —
  delivered-at, attempt count and typed provider evidence — and re-dispatches
  nothing. A command whose stored request was redacted by the retention sweep,
  lost, or no longer digests to what was recorded is refused by name rather
  than retried into a live effect.
- Adds oldest-first, page-bounded dead-letter and ambiguous inspection carrying
  what was attempted, the binding and installation it was attempted against,
  the typed provider evidence, the connector's classification, the legal-hold
  state and whether the request is still verifiable. Derived at read time;
  no status column and no new table.
- Resolves an INDETERMINATE attempt against provider evidence in three phases
  with no session held across the probe. A `landed` verdict closes the command
  as delivered without re-dispatching it, only a provider-proven `not_landed`
  returns it to the queue (and still only with verifiable request evidence),
  and `unknown` leaves it ambiguous with a module-owned marker rather than
  blindly retrying or blindly failing it. Replaying an ambiguous command
  through the operator path is refused and pointed at reconciliation.
- Declares one new audit action, `integration.delivery.reconciled`, carrying
  the verdict, the previous and resulting state and typed provider evidence.
  Connector-authored probe text is returned to the caller and persisted
  nowhere. Requeueing keeps its existing single writer,
  `integration.delivery.replayed`.
- `INTEGRATION_DEAD_LETTER_PAGE_SIZE` is the new configuration knob (default
  100, bounded at 1000). No schema change: the reconciliation trail is the
  fleet's one platform audit ledger, and the four-state outcome vocabulary
  stays `retry.OutcomeStatus`.
### Connector quarantine, a dispatch kill switch and one admission owner

- Adds `admission`, the single authority for "may this worker dispatch right
  now?". It carries a closed set of reasons, and `dispatch.prepare` consults it
  BEFORE claiming, so a refusal never strands a leased row.
- `dispatch.DispatchNotAdmitted` is a third, distinct answer beside `None` (no
  claim, contention) and `DispatchUnavailable` (a misconfiguration, alert).
  A deliberate halt no longer reads as a broken configuration.
- Quarantine is scoped to the INSTALLATION and enforced at dispatch: every
  capability it serves stops, other installations of the same connector and the
  same capability are untouched. It removes no queued delivery, breaks no lease
  and rewrites no retry schedule.
- Adds `lifecycle.release_quarantine`, the explicit exit. It lands in
  `disabled`, never `enabled`, so leaving containment cannot skip `enable`'s
  live connection check. Both directions write a declared platform audit event
  recording the previous state, the reason and the actor.
- Adds `ExecutionPolicy.dispatch_enabled`, the deployment-wide kill switch. It
  refuses admission with no database access at all and leaves every durable row
  exactly as it found it.

### Provider rate limits and backpressure

- A TERMINAL outcome carrying a configured transient HTTP status (429, 503,
  502, 504, 500, 408, 425) is reclassified RETRYABLE. The engine branches on the
  typed `provider_status_code` only, never on a connector's `error_code`, and
  never promotes `RECONCILIATION_REQUIRED`. Attempt exhaustion still applies.
- Adds `retry.parse_retry_after`, which reads both RFC 7231 forms
  (delta-seconds and HTTP-date) so every connector does not reimplement it.
  An unusable header falls back to the curve instead of failing the outcome.
- An observed throttle delays that installation's other queued deliveries
  through one bounded UPDATE in the settle transaction — it only ever moves
  `next_attempt_at` forward, never touches in-flight or settled rows, and never
  reaches another installation. The pause is a schedule, never a sleep, so no
  session is held across provider I/O.
- Adds `ExecutionPolicy.max_in_flight_per_installation`, the backpressure that
  applies before a provider complains.

### Operational metrics

- Adds `operations.dispatch_metrics`: queue depth, oldest queued age, end-to-end
  dispatch latency over a configured window, retry counts, failure counts,
  expired leases, unprocessed receipts and quarantined installations.
- Derived at read time beside `health_report`, for the same reason — a stored
  gauge is a second writer over facts the ledgers already hold.
- `operations.METRIC_NAMES` is the stable, language-neutral naming contract.
  The module produces the numbers and introduces no metrics client: the
  exporter stays with the composing assembly.

### Configuration

- Every threshold added here is a validated `ExecutionPolicy` field with a
  documented default that reproduces the previous behaviour. Construction
  refuses a zero concurrency ceiling and refuses a throttling status that is not
  also retryable — which would delay the queue while dead-lettering the delivery
  that discovered the limit.

## 0.1.0a14 — released 2026-08-24

Published, installed back from the private index, registered and tagged from
exact protected-main revision `70459efd` by release run `32693378851`.

### Outbound delivery evidence and content retention

- Adds typed `provider_reference` and `provider_status_code` outcome fields and
  persists them atomically with the claimed attempt. Arbitrary provider response
  bodies remain unrepresentable.
- Adds `delivery_legal_holds` and a bounded, oldest-first redaction sweep for
  delivered outbox payloads. Deduplication keys, payload digests, state and
  provider evidence survive redaction; replayable and reconciliation-required
  deliveries are refused by name.
- Adds migration `ig_0012_delivery_evidence` on the platform plane.
- Adds SPI 1.4's optional per-capability mode mapping. Legacy declarations keep
  the 1.0–1.3 meaning; multi-mode connectors no longer have to pretend every
  factory serves every capability.

## 0.1.0a13 — unreleased

### Generic product-observation delivery

- Adds `ProductObservationSource`, derived during the claim transaction from
  the module-owned installation and binding rather than from connector payload.
- Exposes that one derivation through `resolve_product_observation_source`, so
  read-only shadow projection does not reimplement module persistence in its
  composing assembly.
- Adds `product_observation_document`, a provider- and product-neutral
  ProductObservation v1 projection whose addressing comes only from the
  authenticated product descriptor and whose observation remains product-owned.
- Covers source provenance in the request fingerprint, so the same delivery
  identity cannot silently move between installations or connector packages.
- Accepts product-port descriptor v2 alongside v1. Unknown descriptor versions
  still fail closed; connector SPI remains 1.3.

## 0.1.0a12 — released 2026-08-22

Published, installed back from the private index, registered and tagged from
exact protected-main revision `9f59d02b` by release run `32587960069`.

### Capability-wide product-port reconciliation

- Adds a module-owned query for every durable binding carrying one capability;
  it deliberately includes configured and disabled bindings because routing is
  a prerequisite for activation, not a consequence of it.
- Projects one authenticated product-port descriptor onto that complete set in
  the caller's transaction, so independently installed connectors implementing
  the same capability cannot leave one binding addressable and another
  accumulating undeliverable receipts.
- Refuses an empty binding set instead of reporting a vacuous successful
  reconciliation. The operation remains digest-idempotent for the whole set.

## 0.1.0a11 — released 2026-08-22

### Executable polling engine

- Adds a three-phase POLL seam: short configuration/checkpoint prepare,
  session-free provider invocation, then one atomic receipt-and-checkpoint
  transaction.
- Refuses a stale checkpoint with the existing optimistic version guard, so a
  losing worker cannot commit receipts past a cursor it did not advance.
- Carries connector exceptions and secret-resolver failures only through typed,
  material-free errors. The handler receives materialized held secrets and no
  database/session by signature.
- Extends the shipped conformance fake with explicit poll exception and
  wrong-return-shape controls.

## 0.1.0a10 — released 2026-08-19

### Manifest-owned runtime boundaries (SPI 1.3)

- Adds immutable secret-binding and exact-host egress declarations to
  `ConnectorManifest`; an empty egress declaration is explicit deny-all.
- Refuses URL, path, wildcard, IP-literal, mixed-case, local and duplicate
  egress entries before discovery can trust them.
- Covers secret names, requiredness and egress hosts in the manifest digest.
  Pre-1.3 manifests remain readable and keep their historical digest so an
  upgrade does not invalidate persisted installation pins.
- Adds `derive_runtime_policy`, the deterministic projection of the installed
  manifest set. It refuses a legacy omission and exposes the exact egress union,
  named secret bindings and a stable policy digest to the composing runtime.
- Carries no provider list and performs no network I/O. The independently
  deployed Integrator projects the declarations into its runtime policy.

## 0.1.0a9 — released 2026-08-18

### Finite replay evidence and durable legal-hold history

- Adds a separately required replay-evidence period to `RetentionPolicy`; it
  must outlive the content period and neither period has a library default.
- Adds `purge_expired_replay_evidence`, which deletes only closed receipts whose
  content was already redacted, whose evidence period elapsed and which have no
  active legal hold. The conditional delete repeats those predicates so a
  concurrent hold still wins.
- Adds additive revision `ig_0011`. Released migrations remain byte-frozen.
  The old cascading hold FK is replaced by PostgreSQL triggers that reject an
  invented hold and reject deletion under an active hold, while allowing a
  released hold row and its exact receipt UUID to outlive the receipt.
- Records purged internal receipt UUIDs in the module's existing platform audit
  facility. Provider event ids, payloads and header values never enter it.

## 0.1.0a8 — released 2026-08-17

### Indexed, revisioned product-port shadow evidence

- Adds append-only `shadow_comparison_evidence` in the module's platform plane
  through additive revision `ig_0010`; released migration bytes stay frozen.
- Stores only the Integrator receipt UUID, an explicit comparison revision,
  closed verdict/blocker codes and bounded field names. Provider identities,
  payloads, headers, values and exception text are not representable.
- Selects due receipts without claiming or mutating them. Terminal evidence is
  observed once per revision; transient outcomes retry only after an explicit
  interval; a new deployment revision deliberately re-drives the population.
- Aggregates only the latest result per receipt and refuses to call an empty or
  blocked sample cutover-safe. The final cutover remains a product decision.
- Keeps transaction authority with the assembly: services accept a session,
  mutate and flush; they never create sessions, commit or roll back.
- Does not use the kernel operator-audit ledger as a high-volume polling index,
  and does not put reusable state in the thin assembly.

## 0.1.0a7 — released 2026-08-17

### Product-owned destination provenance and complete receipt identity

- Adds append-only `ig_0009_product_port_desc` columns on destination
  revisions. A named reconciler accepts one already-authenticated product
  descriptor, verifies its digest, owner, capability, version and same-origin
  paths, and appends only when the digest changes.
- Carries `provider_event_id` from the claimed receipt into `ProductRequest`
  and its fingerprint. The engine-owned durable identity no longer has to be
  reconstructed from connector payload content.
- Adds `InboundDisposition.RECORD_ONLY`, defaulting to `DELIVER`. Malformed,
  provider-error and unsupported-wire evidence can remain durable and
  deduplicated while being closed without entering a product delivery worker.
- Keeps SPI 1.2 and its verification-evidence observer unchanged; the new
  disposition is additive and existing connector events retain their delivery
  behaviour.

## 0.1.0a6 — released 2026-08-17

### Configuration declarations are executable contracts

- Refuses a connector whose capability carries malformed Draft 2020-12 JSON
  Schema, without rendering the connector-owned schema or chaining the
  validator exception.
- Validates a revision against every currently bound capability before it can
  be written, and validates an existing revision before a new capability is
  bound. Activation repeats the check so a row created by an older module
  cannot bypass it.
- Includes `schema_version` in revision identity. Equal values under different
  schemas no longer collapse into one immutable revision.
- Restores Sub's lifecycle semantics: a new revision starts `pending`, a
  configuration or binding change returns the installation to `draft` and
  disables its bindings, and rebinding the same installation/capability updates
  the one existing binding rather than surfacing a uniqueness error.
- Treats connector validation text as secret-bearing. Only bounded
  lowercase-snake-case diagnostic codes may reach state or exceptions;
  free-text detail is hidden from `repr` and never persisted or rendered by
  the lifecycle owner. A raising connector becomes the generic
  `connection_validation_failed` code with no chained exception.
- Adds `jsonschema >=4.23,<5.0` as a runtime dependency. This makes the JSON
  Schema surface already declared by SPI 1.2 real; no provider or connector
  import enters the module.

### `platform_audit_log.v1` is declared and verified at deploy

- Declares the append-only platform audit effect used by repair and retention
  operations at request time.
- Adds DDL-free `ig_0008_platform_audit_log` after the released `ig_0007`
  ledger verifier. Published migration bytes remain untouched.
- Raises the kernel floor to `>=0.1.0a68`, the first release that publishes
  the audit prerequisite and its live-catalog verifier.
- Requires all eight migrations in the release wheel.
- Converts `write_platform_audit_event` from frozen caller debt into a mapped
  facility enforced against every module caller.

## 0.1.0a5 — released 2026-08-17

### SPI 1.2 — provider-neutral verification evidence

- Adds `VerificationResult`, containing only an acceptance bit and zero or more
  positions in a connector's ordered active-secret set. No secret name,
  reference or value is representable on the type.
- Adds a provider-neutral verification observer to the ingress engine so an
  assembly can count secret-rotation traffic without importing a connector or
  branching on a provider. Observer failure is non-fatal telemetry failure.
- Keeps SPI 1.0/1.1 ingress plugins source-compatible: a boolean verification
  result is adapted to `VerificationResult` with no secret positions.
- Refuses any other truthy object. Before this release, a plugin accidentally
  returning an object instead of `bool` authenticated the request because the
  engine relied on Python truthiness.
- Raises `CURRENT_SPI_VERSION` from 1.1 to 1.2. No persistence or migration
  changes are included.

## 0.1.0a4 — released 2026-08-16

Written against a declared-but-unreleased `0.1.0a3`, which was cut from
`b14f66e` while this change was open. The ledger work moved up to a4 rather than
being back-dated into a release it was never in — and `ig_0007` stayed unreleased
rather than joining a3's digest entry in
`tests/architecture/test_released_migrations.py`.

### `idempotency_ledger.v1` is declared, and verified at deploy

Declares the kernel prerequisite this module has consumed since `0.1.0a1`.

`dotmac_integration.idempotency.run_effect_once` delegates at-most-once
execution to `dotmac_kernel.idempotency.execute_once_platform` (hard rule 21,
ADR-0014 — the ledger has exactly one owner and it is not this module), so
`public.platform_idempotency_records` is written at REQUEST time. Nothing in
`ig_0001`..`ig_0006` creates it, so the dependency existed only inside a
function body: an adopter running its own lineage that never ran the kernel's
— ERP hosts `public.tenants` itself and structurally cannot run kernel `0001` —
installs this module, passes every gate it has, migrates cleanly, and raises
`UndefinedTable` on the first guarded delivery. No test could have caught it
before kernel `0.1.0a66`, because there was no name to declare. Same defect,
same week, as `dotmac-numbering` `0.1.0a1`.

#### Changed

- `ModuleManifest.requires` gains `idempotency_ledger.v1`. COMMON rather than
  `platform_requires`: this module owns one plane, installed atomically, so
  there is no selection under which the requirement lapses — and a plane list
  is unresolvable for an atomic module anyway, since `resolve_depends_on` reads
  one only via `module=`, which needs a `ModulePlaneSelection` such a module may
  not have.
- Kernel floor raised to `>=0.1.0a66`, the release that published the name.
  a58..a65 HAVE the tables — kernel `0018` created them — but do not know the
  name, so `validate_prerequisites` refuses the manifest at import. **This is a
  visible break for a consumer pinned to a released a1, a2 or a3 on an older
  kernel**, and deliberately so: every one of those installs against a kernel
  whose ledger it silently requires and cannot state.
- Every migration is now a required wheel content in
  `.github/release-modules.json`, not just the first two. `ig_0007` creates
  nothing, so a wheel that dropped it would ship a declared-but-never-verified
  prerequisite.

#### Added

- **`ig_0007_idempotency_ledger`** — a DDL-free revision whose whole body is
  `require_prerequisites`. Deploy is the last moment at which a missing ledger
  is a failed migration rather than a failed delivery.
- A NEW revision rather than an edit to `ig_0001`, which shipped in three
  published tags and whose bytes are therefore history.
  `tests/architecture/test_released_migrations.py` records the SHA-256 of every
  migration file in every released tag, cross-checks each digest against the
  blob git holds at that tag, and fails if one changes or disappears — the guard
  numbering did not need, because its `0.1.0a1` was never published.

## 0.1.0a3 — released 2026-08-15

### `ModeContractError` no longer repeats what a connector threw

`verify_plugin_modes` calls each declared mode's handler factory at DISCOVERY,
which happens after configuration has been resolved — so a plugin that
interpolates a resolved credential into its own exception (an ordinary connector
bug) handed that credential to this module, which put it in the error message
and chained the original as `__cause__`.

The type name now travels and nothing else, and the raise is `from None`.
Dropping `{exc}` alone would not have been enough: the chained cause renders in
every traceback and every `logging` call with `exc_info`, which is where an
operator would actually have read it.

This is the invariant `ingress.HandlerUnavailable` already held one layer down
for the REQUEST path. Discovery held the inverse. Proven on all four surfaces —
message, `repr`, rendered traceback and a log record — with a sensitivity proof
that the same value DOES reach all four when interpolated and chained the way
the defect did it.

An operator keeps what they need to act: the connector key, the capability, the
mode, the failing hook and the exception TYPE.

## 0.1.0a2 — released 2026-08-15 (see the warning above)

### SPI 1.1 — one frozen contract, mode-specific protocols

**SPI 1.1 ships in `0.1.0a2`**, and is published because that version is (this
paragraph said "not published either" while a2 was still unreleased; the tag was
cut on 2026-08-15). It is the ONLY SPI version after 1.0: two unpublished drafts existed
on an abandoned branch — one adding the mode protocols, one replacing the
ingress hooks' loose parameters with a single immutable envelope — and they are
collapsed into this one. Shipping them as two consecutive breaking SPI versions
inside one unreleased alpha would have been a fiction, because no consumer could
ever have pinned the intermediate one. Any note elsewhere describing "SPI 1.1"
and "SPI 1.2" as separate published contracts describes something that never
existed.

`CURRENT_SPI_VERSION` is therefore `1.1`, and 1.2 is unused and available.

#### Modes became obligations

`ConnectorMode` shipped in SPI 1.0 with three members and nothing consulting
them: `INGRESS` and `POLL` had no executable protocol at all, and `DELIVERY` was
invoked without checking the declaration, so a binding pointed at an
ingress-only connector reached `handler_for` and failed with an `AttributeError`
from inside a lookup.

- `ConnectorPlugin` is now the BASE — identity, metadata, `validate_connection`.
  `handler_for` moved to `DeliveryPlugin`, joined by `IngressPlugin`
  (`ingress_handler_for`) and `PollPlugin` (`poll_handler_for`). A base
  demanding `handler_for` is what made `modes` decorative: if every plugin must
  supply a delivery handler, declaring `DELIVERY` says nothing.
- `MODE_PROTOCOLS` binds each mode to its plugin protocol, its factory name and
  the protocol the factory's RETURN VALUE must satisfy — one frozen
  (`MappingProxyType`) table, asserted exhaustive at import, so a new mode
  cannot be added without deciding what makes it runnable.
- `verify_plugin_modes` checks the implication in BOTH directions and runs at
  DISCOVERY. One direction alone is not enough: declaring without implementing
  fails at the first dispatch, implementing without declaring never gets workers
  started and the connector looks installed and inert.
- It also checks the SHAPE of the handler, not merely that one came back. A
  factory returning a delivery handler where an ingress handler was promised
  satisfies "not None" perfectly and then fails on a provider's request.
- `discovery.discover` and `conformance.assert_plugin_conforms` both call that
  one function, so an author's suite and the host's boot cannot reach different
  verdicts.
- `dispatch.invoke` calls `require_mode(plugin, DELIVERY)` BEFORE the handler
  lookup, so a misconfigured binding says "this connector does not deliver".

#### An immutable raw request envelope

- `IngressRequest` carries the raw body, headers and query params, and the SAME
  object is handed to all three ingress hooks — so what was authenticated and
  what was interpreted are provably the same bytes.
- Nothing is normalised: names and values are preserved exactly as given, the
  mappings are copied and then wrapped in `MappingProxyType`, and the dataclass
  is `frozen`/`slots` so no hook can mutate what a later hook sees or smuggle a
  session on as an ad-hoc attribute.
- `repr=False`: it is a frame local in every traceback leaving the plugin phase
  and it holds the raw body, the signature header and any cookie a misconfigured
  proxy passed through.
- Known limit, stated rather than discovered later: `headers` and `params` are
  single-valued. A multi-valued view is purely additive and needs no break.

#### A constrained acknowledgement

- `Acknowledgement` gives the connector the response BODY (as `bytes`) and the
  media type, and nothing else. The engine keeps the status code.
- That split is the point: a connector must be able to satisfy a provider's
  exact handshake format without being able to lie about whether the engine
  accepted the request. A status code is a retry instruction, and only the
  engine knows whether the batch committed.
- `media_type` is validated against a strict `type/subtype` — it is a response
  header value, and an unvalidated one carrying CRLF is header injection.

#### SPI 1.0 compatibility

Minor rather than major, and held by a test rather than by prose:
`tests/unit/test_integration_spi_modes.py` carries a hand-written SPI 1.0
delivery-only connector — `handler_for` on the plugin, `modes` naming `DELIVERY`
only, `>=1.0,<2.0`, no knowledge of ingress or poll — and proves it still
discovers, still conforms, and is still actually dispatched to. A major bump
would have excluded every honest `>=1.0,<2.0` delivery connector in order to
protect a compatibility promise nothing ever consumed.

### Fixed (the type gate)
## 0.1.0a2 (continued) — RELEASED — receipt-to-product delivery

Receipt-to-product delivery: the half that turns a recorded observation into a
delivered one. **No version bump** — the persistence this slice specifies is
still blocked on a staged handoff (below), so nothing here is releasable yet.

### Added

- **`dotmac_integration.receipt_delivery`** — the typed, deeply immutable
  boundary contracts for landing a receipt on the product that owns it, plus
  `deliver_receipt`, the three-phase orchestrator: claim transaction → product
  call with **no session held** → conditional settlement guarded by the claim's
  attempt/lease identity. A network call inside a transaction holds a row lock
  for the duration of someone else's outage, so phase 2 touches no database at
  all, and the fake store in the unit suite checks that rather than trusting it.
- `ProductAcceptance` — five typed product answers, each mapped to an existing
  `retry.OutcomeStatus` through a table rather than an `if` chain, so a new
  member without a retry decision is a `KeyError` at the boundary instead of a
  silent fall-through to "retryable" (the default that duplicates consequences).
- `idempotency_key_for` — derived from the receipt and its DESTINATION, and
  deliberately **not** from the attempt number. That absence is the whole
  at-most-once property: a timeout on attempt 1 followed by a successful attempt
  2 presents the product with the same key, so it deduplicates and the
  consequence happens once. Had the key carried the attempt, the retry curve
  would be a duplication machine.
- `request_fingerprint_for` / `require_stable_fingerprint` — same identity plus
  same fingerprint is a safe replay; a changed fingerprint is a
  `FingerprintConflict`, raised BEFORE the product is contacted rather than
  silently overwriting a recorded consequence.

### Changed

- **`LostClaim` moved to `execution`, which owns claiming.** It was defined in
  `dispatch` for the outbox; the inbox now needs the same concept, and two
  classes sharing the name would have made `except LostClaim` catch a delivery's
  lost claim but not a receipt's, decided by nothing more than which module the
  caller imported from. `dispatch.LostClaim` still resolves and the package
  surface is unchanged.

### Blocked (deliberately, and ratcheted)

`inbox_receipts` needs a lease, due scheduling, a fingerprint and typed product
outcome columns. Those are receipt-state model changes, and ownership is staged
behind Team 2 (`models.py` / `ig_0003`) and Team 3's trusted destination
(PR #184). Writing them now would collide with `models.py` mid-edit.

So `tests/test_integration_receipt_delivery_isolation.py` specifies the
behaviour FIRST, as 11 PostgreSQL canaries carrying
`xfail(strict=True, raises=ProgrammingError)` — they must fail, and must fail
*because the column is missing*. A twelfth test asserts those columns are still
absent, so the moment the handoff lands the suite goes red and names the markers
that must come off. The trusted destination is consumed through structural
protocols (`TrustedDestination`, `TrustedScope`) that Team 3's frozen
`DestinationBinding` already satisfies, so adopting it is a one-line import.
## 0.1.0a2 (continued) — RELEASED — payload retention

Payload retention. No version bump here on purpose: the release lane decides
when this ships, and a bump in the same change as the behaviour makes the two
decisions one.

### Added

- **`dotmac_integration.retention`** — a receipt's CONTENT ages out; its
  identity never does. Redaction rewrites `payload_json`, `headers_json` and
  the values inside `consequence_json`, and touches no column deduplication,
  ordering or outcome comparison reads. A provider redelivering a
  months-old event still gets "already received" rather than being processed a
  second time, and one event id arriving with different content is still a
  `ProviderEventIdentityCollision`.
- **No default retention period and no default legal-policy owner.**
  `resolve_retention_policy` refuses until `INTEGRATION_PAYLOAD_RETENTION_DAYS`
  and `INTEGRATION_RETENTION_LEGAL_POLICY_OWNER` are both set, in every
  environment. A period baked into a library becomes the deployment's
  data-retention posture without anyone deciding it.
- **`receipt_legal_holds`** (migration `ig_0006_retention`) — a held receipt is
  never redacted, and the refusal is named and counted. Platform plane, with a
  PARTIAL unique index enforcing at most one ACTIVE hold per receipt while
  keeping released holds as the record that they existed.
- **Four refusals, four ways to destroy in-flight work**: `legal_hold`,
  `leased` (a worker's claim), `unresolved` (including `dead_letter` and
  `retryable`, which `replay_receipt` may still move) and
  `reconciliation_required`. Enforced twice — a named Python refusal, and a
  conditional UPDATE that repeats every condition so a hold or a claim arriving
  mid-sweep still wins.
- `retention_backlog`, counted from the ledger at read time. No stored status
  column, for the same reason `health_report` has none.

## 0.1.0a2 (continued) — RELEASED — the type gate

Fixes a public function that could never have run, and the gate gap that let it
ship. `pyproject.toml` declares `dotmac_integration.*` under mypy's strict
settings, but the Makefile never passed the package to `mypy` or `bandit` — so
the strictness was declared and unenforced, and `0.1.0a1` published with 42 type
errors and one broken export.

### Fixed

- **`run_effect_once` raised `TypeError` on its first call.** It passed a
  `payload=` keyword `dotmac_kernel.idempotency.execute_once_platform` does not
  accept, and an `operation` taking no arguments where the kernel calls
  `operation(db)`. It is exported from `__init__` and had no caller and no test,
  which is why nothing noticed. Now a faithful adapter: every parameter is the
  kernel's, and the only addition is `mechanism` → `scope`. The old `payload`
  becomes `fingerprint`, the kernel's own column (ADR-0014).
- `assert_connector_conforms` used `try/except/pass` carrying a `# noqa: S110` —
  ruff's code, not bandit's `B110`, so the suppression named the wrong tool.
  Rewritten as a positive assertion with no swallowed exception.

### Changed

- Every JSON-shaped payload is annotated `dict[str, object]` in house style
  (32 sites). `secret_refs` is `dict[str, str]` downstream of validation and
  `dict[str, object]` in the validator itself, which exists to reject
  non-strings.
- `resolve_binding`'s rows are typed once, so its three returns stop escaping as
  `Any` from a declared `CapabilityBinding` return type.
- `_is_reference` narrows with `is not None` rather than `bool(match)`. The old
  form was safe at runtime — `and` short-circuits — but unprovable to a checker.

## 0.1.0a1 — 2026-08-14 — RELEASED (tag `dotmac-integration-v0.1.0a1`)

The connector control plane, as a Starter module (ADR-0024). Implements SPI 1.0.
(It was the only released version when this was written; `0.1.0a2` followed on
2026-08-15. See "Release state" at the top for the current list.)
