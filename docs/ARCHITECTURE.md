# Architecture

This expands the `CLAUDE.md` summary. See `docs/adr/0001-multi-tenant-architecture.md`
for the founding tenancy design and `docs/adr/0002-starter-consolidation.md`
for how this repo came to be the org's one starter. ADR-0003 defines the
accepted, not-yet-implemented profile-driven direction for SaaS, dedicated,
self-hosted/on-premise, OEM, and single-tenant deployments. ADR-0006 fixes the
package/module/theme/brand/facet ownership boundaries and extraction rule for
that target.

## Application and module composition boundary (accepted)

ADR-0024 makes the fleet boundary explicit: every application owns its own
runtime, database, migrations, authorization and domain decisions. Applications
exchange data through versioned APIs and webhooks; they never query or import
one another's persistence. An Integrator connector plugin converts provider
wire data into a typed, idempotent observation. A local resolver then updates a rebuildable
projection or submits a command to the local owning service. The importer does
not assign authoritative lifecycle state.

Installable modules are independent distributions composed *inside* an
application. Each adopter pins the package, runs its own module lineage and owns
its own module rows. Sharing `dotmac-ticketing` or `dotmac-files` therefore
shares a contract and implementation, never a cross-application database.
Modules import neither the assembly nor sibling modules; the assembly connects
published contracts and owns product relations.

Shared execution paths have no product/provider switch. The reusable engine is
Starter's stateful `dotmac-integration` module; the independently deployed
`dotmac_integrator` repository is a thin assembly that pins kernel, that module
and connector packages and runs them. Provider connectors are installed into
that runtime through ADR-0024's versioned plugin SPI, while products expose
provider-neutral capability ports. Products do not each compose the engine
module. Endpoints and credentials are configuration, but business authority is
an accepted ownership contract, not a configurable default. Outbound
synchronization is delivered after commit through a durable outbox so a local
transaction never depends on another application's uptime.

Connector distributions register by package metadata and declare versioned
capabilities; `dotmac-integration` contains no provider catalogue. The module
owns installations, immutable configuration revisions, one active binding per
installation/capability, secret materialization, inbox/outbox, retry,
checkpoints, health, repair evidence and its own `mod_*` lineage. Plugins own
only provider wire translation and I/O. The thin assembly adds no competing
engine or persistence. Products therefore add no provider client or conditional
when an external system changes.

Application-to-application synchronization does not pass through provider
plugins. The stateless `dotmac-app-sync` contract package gives independently
deployed products one versioned envelope and authenticated hand-off shape while
leaving the durable outbox, peer authentication, atomic deduplication, local
observation row, resolver and every consequence with the participating
products. Capability declarations are destination-owned; adding a flow does not
add a source/destination branch to the package or make Integrator a domain
owner.

The first concrete plugin follows that split exactly:

| Contract surface | Owner | Non-owner boundary |
|---|---|---|
| Versioned inter-application envelope, authenticated peer/source binding, schema validation, idempotency identity and payload fingerprint | `dotmac-app-sync` | Owns no transport, peer authentication, row, session, application route, domain resolver or consequence; each destination declares the capability schema and implements the atomic receiver |
| Meta WhatsApp ingress authentication, batch traversal, raw provider identities and acknowledgement bytes; the WABA message-template catalogue read as typed provider observations; outbound text/template/media sends that refuse before the wire what the provider would reject anyway (unapproved template, variable arity the catalogue does not describe, unsupported MIME type, oversize attachment, a caption or filename the media type cannot carry) | `dotmac-connector-whatsapp` (`meta_whatsapp`, `messaging.receive.v1` INGRESS + `messaging.send.v1` DELIVERY + `messaging.templates.read.v1` POLL) | Owns no installation row, retry/checkpoint, destination, subscriber, conversation, customer-window decision, template selection or product consequence. The template catalogue is an in-process memo under a configured freshness policy, never persisted and never a second authority on approval |
| Meta Social ingress authentication, Facebook/Instagram message and comment traversal, raw provider identities and acknowledgement bytes; outbound Messenger/Instagram Direct sends and Facebook/Instagram comment replies, one Graph call per product-decided command, with Graph error codes classified into typed outcomes | `dotmac-connector-meta-social` (`meta_social`, `messaging.receive.v1` INGRESS + `messaging.send.v1` DELIVERY) | Owns no messaging-window decision, no permission to respond, no profile lookup, installation row, retry/checkpoint, destination, contact, conversation or product consequence |
| Flutterwave API v4 exact-byte ingress authentication, OAuth-authenticated paged charge reconciliation, provider-event identity, exact amount/currency translation, and outbound payment-initialization and refund commands | `dotmac-connector-flutterwave` (`flutterwave`, INGRESS+POLL on `payments.settlement.observation.v1`, DELIVERY on `payments.intent.v1` and `payments.refund.v1`) | Owns no v3 fallback, transfer/payout surface, provider-fee inference, installation row, retry/checkpoint, destination, tenant, allocation, coverage, receivable, ledger or product consequence. Outbound classifies only: a decline is terminal, a timeout after send is reconciliation-required, and the engine's idempotency key rides the provider's own header |
| Paystack ingress authentication plus authenticated paged transaction reconciliation, provider-event identity and exact amount/fee/currency translation; and outbound payment-initialization/charge, refund, payout and customer commands, each behind its own bound capability so an observation binding never carries command authority | `dotmac-connector-paystack` (`paystack`, INGRESS+POLL on `payments.settlement.observation.v1`; DELIVERY on `payments.intent.v1`, `payments.refund.v1`, `payments.payout.v1` and `payments.customer.v1`) | Owns no installation row, retry/checkpoint, destination, tenant, allocation, coverage, receivable, ledger, refund warrant, payout decision or product consequence. Outbound derives the provider reference from the engine's idempotency key and never reads one from the payload; a send whose answer never arrived is reported AMBIGUOUS with its reference as evidence, never retried. **Today the only `payments.payout.v1` binding in the fleet — see ADR-0061 § 4 D1.** It also still declares `payments.customer.v1` (`create_customer | update_customer | read_customer`) — as built, and RULED OUT: ADR-0061 Amendment A5 REMOVES that capability from the public manifest (no independent Dotmac business lifecycle; it is Paystack's `/customer` REST surface). The code removal is part of the payout refactor, gated behind the capability-schema and result seams; A5 holds the artifact-by-artifact list |
| Mono Financial Data v2 authenticated account-transaction polling, same-origin pagination and provider-neutral transaction translation | `dotmac-connector-mono` (`mono`, POLL-only, `banking.transaction.observation.v1`) | Owns no account-link intent, bank statement, reconciliation, product identity, installation row, retry/checkpoint, ledger or accounting consequence |
| Connector polling preparation, provider invocation and atomic inbox-plus-checkpoint settlement | `dotmac-integration.polling` | Pins config and cursor before I/O, passes no session to plugins, and advances the checkpoint in the same transaction as the complete received batch; owns no provider schedule or domain consequence |
| Whether a polling job may be attempted now, how far into the backoff curve it is, and what its attempts have done — declaration lifecycle, retry state, never-rewritten per-attempt failure evidence, bounded retention sweep and the sole bounded keyset selection a worker loops over | `dotmac-integration.poll_schedule` plus the `polling.ensure_polling_checkpoint` lifecycle seam | Owns the FLOOR (`next_attempt_at` = not before), never the CADENCE — a polling interval stays a deployment's decision. Never dead-letters a poll job (the curve saturates and the job stays selectable; stopping one is `lifecycle.disable`). Never touches the checkpoint's optimistic `version`, which remains `execution.advance_checkpoint`'s claim about the cursor. Owns no backoff formula (`retry.retry_delay_seconds`), no lease (the selection claims nothing), no connector vocabulary (eight engine-owned failure codes, and the evidence table has no free-text column), and no retention period; the product supplies the cutoff to the typed sweep |
| Remita authenticated RRR status polling, provider-neutral response translation, and outbound RRR issuance under the provider SHA-512 request contract | `dotmac-connector-remita` (`remita`, POLL on `payments.reference.status.observation.v1`, DELIVERY on `payments.reference.issuance.v1`) | Carries provider status verbatim; owns no RRR lifecycle, status mapping, biller decision, source linkage, installation row, retry/checkpoint, ledger, journal or accounting consequence. Issuance carries the PRODUCT's stable `orderId` and mints none of its own, because Remita accepts no idempotency header and `orderId` is its only natural key |
| LinkedIn challenge-response, exact-byte webhook authentication and organization-social/lead notification translation | `dotmac-connector-linkedin` (`linkedin`, INGRESS-only, `social.activity.observation.v1` + `marketing.lead.observation.v1`) | Owns no contact, campaign, qualification, assignment, ticket, publication, destination or product consequence; declares deny-all provider egress |
| Connector installation, binding, product-port descriptor projection, engine-derived ProductObservation source, materialized secret lifetime, receipt identity, retry/repair, verification evidence and revisioned shadow evidence | `dotmac-integration` inside `dotmac_integrator` | Contains no provider header, signature, payload or acknowledgement rule; fetches no product descriptor itself, and a destination owns each typed observation and comparison and returns only closed safe outcomes |
| Whether a stored outbound command may become a live effect again — replay by product idempotency key, dead-letter inspection and operator repair, and resolution of an INDETERMINATE attempt from provider evidence | `dotmac-integration.outbound_repair` | One decision (`classify_repair`) behind every entry point, so inspection and repair cannot disagree; re-dispatches only the row's own stored request checked against its enqueue digest, never a rebuilt payload; returns the recorded outcome for a landed effect instead of re-sending it; refuses to replay an ambiguous attempt; and owns no queue reset (`operations.replay_delivery`), no at-most-once ledger (`dotmac_kernel.idempotency`), no audit ledger (`dotmac_kernel.audit`), no outcome vocabulary (`retry.OutcomeStatus`) and no table of its own |
| Product-port declaration: capability meaning and payload schema (or dated grace), product wire, local binding identity, delivery/mirror paths, stream scope and activation state | the receiving product (Sub for cutover 1) | The thin assembly authenticates and freezes descriptor v3; `dotmac-integration.reconcile_product_port_descriptor` validates it against the installed domain registry and is the sole writer of its append-only Integrator projection |
| Meaning and consequences of a received messaging observation | the receiving product's typed port and local owning service (Sub for cutover 1) | Imports neither the connector nor Integrator persistence |
| Whether a payout happens, to whom, for how much, and whether an ambiguous attempt may be tried again | **`PaymentService`** (`dotmac_erp:app/services/finance/payments/payment_service.py` — `initiate_expense_transfer`, `_recover_transfer_initiation`, `process_successful_transfer`, `mark_transfer_failed`, `poll_transfer_status`, `process_transfer_reversal`) — the SOLE interim owner. `BatchTransferService` is dead code (zero callers, not exported, zero tests) and is NOT an owner. ADR-0061 § 1 + Amendment A1 — the owner ADR-0042 § 3 left unnamed, named as services rather than as a role. **Implemented and tested; production enablement unconfirmed** (ADR-0061 A7 — the path is gated by `paystack_transfers_enabled`, which is runtime data, and no deployment target has been named). `BatchTransferService` is to be DELETED as security-sensitive dead code (A7). No `dotmac-treasury` package or namespace exists or may be allocated: ADR-0063 scopes a narrow `PaymentInstruction` owner and gates its construction on ERP's `PaymentIntent.status` three-writer fix | No connector, no `dotmac-integration` path, no `dotmac_integrator` configuration and no operator gesture inside the Integrator originates, alters, batches, suppresses or re-sends a payout. `outbound_repair.classify_repair`'s refusal to replay an ambiguous money attempt IS this boundary in code |

External advertising and social-media observations use the same application
boundary with a separate domain owner. The tenant-only
`dotmac-media-observations` package owns immutable normalized entity,
hierarchy, declaration and aggregate period-metric facts plus rebuildable
projections. It imports neither Integration nor a provider package and stores
only opaque installation and transport-receipt references. Integrator and its
plugins retain credentials, wire payloads, endpoints, polling/webhooks,
checkpoints and retry evidence. Provider conversion claims remain explicitly
`provider_reported`; Lead origin, customer identity, attribution, authoritative
revenue and business consequences remain outside the module (ADR-0034). The
package is published and registry-verified at `0.1.0a1` against kernel
`0.1.0a81`, but no product composes it; Michael's 2026-08-18 adoption pause
remains active because release is not adoption.

First-party website measurement follows the same application boundary without
becoming a connector concern (ADR-0055):

| Contract surface | Owner | Non-owner boundary |
|---|---|---|
| Property/stream identity, accepted first-party events, property-scoped visitor/session evidence, filter evidence, deterministic aggregates/funnels, retention rebuild and drift repair | each application's installed `dotmac-web-analytics` tenant plane | Contains no website hostname, content, form value, customer identity, provider API, official attribution or dashboard policy |
| Origin verification and rate limiting for a collection request | the adopting application's thin local or remote collection adapter | Both local and Integrator-delivered commands enter the same versioned analytics service; remote transport is not a bypass |
| Remote delivery and replay evidence | `dotmac-integration` inside `dotmac_integrator` plus a website connector plugin | Transports a typed observation and records delivery; never classifies, sessionises or attributes it |
| Website routes/content and form submission | `dotmac-sites` and the adopting product's Forms owner | May emit a declared anonymous event after its own decision; analytics receives no form or customer fields |
| Provider analytics aggregates | `dotmac-media-observations` through Integrator connectors | Cannot write or masquerade as first-party events |
| Consent eligibility and official acquisition/commercial consequences | product consent owner; future attribution owner; Sales/Orders/Billing | Analytics records the effective policy evidence and anonymous sequence only |

For ticketing this means separate local installations: Sub owns operational
customer/service tickets, ERP owns only its internal back-office tickets, and
the vendor control plane owns vendor-support tickets. A remotely owned ticket
does not become a compatibility projection merely to preserve a foreign key or
dropdown. Correlation-only needs store an opaque Integrator reference on the
local owning record; a separate locally owned ticket may be created only by the
local ticket owner. Synchronization never makes either application a writer of
the other's lifecycle.

ADR-0040 accepts the next Sub vNext parity cohort without claiming it is
installed today. The product-first inventory and extraction dossiers are
complete. Forms and Workflow Runtime now have audit-complete implementation
candidates on the a86 integration branch; publication and adoption remain
separate gates. The
accepted owners are `dotmac-referrals`, `dotmac-reseller-management`,
`dotmac-ai-operations`, `dotmac-remote-access`,
`dotmac-compliance-reporting`, `dotmac-workflow-runtime`,
`dotmac-support-access`, `dotmac-platform-health`, and the independently
qualified `dotmac-forms`. Fleet Control adopts the already implemented
`dotmac-deployment-control`; there is no `dotmac-fleet-control` owner.

The tenant plane is accepted for Referrals, Reseller Management, AI Operations,
Remote Access, Compliance Reporting, Workflow Runtime and Forms. Support Access
and Platform Health are platform-plane capabilities with the Vendor control
plane as their first candidate assembly. The seven newly constructed owners now
have manifests, independent lineages, catalogue entries and live isolation
canaries on this integration branch; this is construction, not composition,
publication or adoption.

### Outbound commands: one capability id, two payload dialects (as built, 2026-08-24)

The connector contract-surface table at the top of this section is the
ownership register, and it holds on the receiving side. On the SENDING side
there is a gap, recorded here because `docs/ARCHITECTURE.md` is as-built truth
and ADR-0061 and ADR-0024 § 8 are decisions the code has not yet reached.

A capability id is supposed to be a contract (ADR-0024 § 8.1). Mechanically it
is currently only a name: `dotmac_integration.spi.CapabilityDeclaration`
carries `capability_id`, `config_schema` and `modes`, and
`DispatchRequest.payload` is an unvalidated `dict[str, object]`. Configuration
has a declared schema; commands do not. So each connector settled the command
shape locally, and two shipped ids have two dialects each:

| | `dotmac-connector-paystack` | `dotmac-connector-flutterwave` / `-remita` |
|---|---|---|
| envelope | `{"action": <verb>, "params": {…}}`; the verb is checked against `delivery.ACTIONS_BY_CAPABILITY`, so a binding granted intents cannot be talked into a payout | flat, typed per capability; no action verb |
| provider reference | DERIVED: `operations.provider_reference` = `dmi` + SHA-256 of `DispatchRequest.idempotency_key`. Reading one from the payload is refused | PRODUCT-minted: Flutterwave requires `intent_reference`; Remita carries the product's `orderId` verbatim and mints none |
| minor units | product sends an exact MAJOR-unit decimal string plus `currency`; the connector applies `PAYSTACK_WIRE_SCALE = 2` itself and accepts no `currency_minor_units` | product MUST send `currency_minor_units`; absence is `currency_minor_units_required` |
| provider idempotency | the derived value in the provider's own `reference` field, which the provider refuses on reuse | Flutterwave: engine key on `X-Idempotency-Key`. Remita: none exists; `orderId` is the only natural key |

Each refusal is locally explicable. Paystack's wire multiplies by 100 for every
supported currency **including zero-exponent XOF**, so a product-supplied
exponent would be a second, contradictory authority on that provider's scale;
and deriving the reference from the engine key is what makes every attempt of
one delivery present an identical, provider-refusable key. Flutterwave and
Remita cannot derive, because their natural key is the product's own and their
exponent is genuinely currency-dependent.

That is where this section originally stopped, and stopping there was the
mistake: "both are locally correct" is a description of a stand-off, not a
resolution, and it quietly licenses the divergence to continue. ADR-0061
Amendment A3 supersedes it. The payload question is answered **once**, by the
capability's owning domain, and each connector adapts to that answer
**internally** — Paystack keeps deriving its provider reference and applying
its own wire scale, from the contract's stable reference and exact money,
because those are provider protocol performed inside the connector, and it
ignores a field it cannot use instead of refusing the command that carries it.
Neither connector is asked to look like the other.

The declaration surface that makes this possible is the DOMAIN's, not the
connector's. As built, `dotmac_integration.capability_registry
.CapabilityContract` — the business owner's declaration, one per capability id,
which the Integrator validates and never mints — carries `capability_id`,
`owner` and `summary`, and no schema of any kind. ADR-0024 § 10 extends it with
`command_schema`, `result_schema`, `observation_schema`, a canonical contract
digest, and deprecation/replacement metadata; `CapabilityDeclaration` keeps
config and modes and may only CLAIM that digest. Putting the schema on the
connector declaration instead would make drift machine-readable rather than
prevent it — two connectors would publish two individually valid schemas for
one id and nothing could prefer either.

None of that gate exists today. It comprises command validation before
`execution.enqueue_delivery`, digest agreement in
`capability_registry.require_implements_only_declared` (composition) and
`require_declared_for_binding` (binding), result validation before
`dispatch.settle`, observation validation before `ingress.record_batch`, and a
schema change taking a new `.vN` id rather than redefining a published one —
with planted sensitivity failures for digest mismatch, missing schema, invalid
payload and invalid result (ADR-0024 §§ 10.4–10.5).

`messaging.send.v1` has the same shape of divergence: `meta_whatsapp` accepts
`send_text | send_template | send_media` with a `recipient` param, while
`meta_social` accepts `send_direct_message | reply_to_comment` with
`recipient_id` plus `channel`. Both declare the same id deliberately — the
outbound name is not minted per connector — and a product bound to one still
cannot be re-bound to the other without changing its command.

`messaging.send.v1` is published, so it is repaired by SUCCESSION rather than
redefined in place (ADR-0024 § 11, ADR-0061 Amendment A4). The canonical
successors are `messaging.direct.send.v2` (provider-neutral direct delivery
with a discriminated text/template/media content shape, replacing both
vocabularies at once), `social.comment.reply.v1` (public Facebook/Instagram
comment consequences — a different business act) and `social.profile.read.v1`
(caller-initiated profile observation through a REQUEST mode). Sub migrates to
them; v1 is kept for a bounded compatibility window and then retired. The
declared, unpublished `dotmac-integration` a18 source now supplies SPI 1.6's
provider-neutral REQUEST machinery; the three named capability contracts and
their connector/product cutovers still do not exist.

Consequence, stated plainly: **payout traffic cannot be switched between
providers by changing a binding today.** `payments.payout.v1` has exactly one
implementation (Paystack), and even with a second one the command shapes
differ. ADR-0061 § 5 is the ordered list of what must become true before
interchangeability may be claimed; ADR-0024 § 8.4 records the same gap from the
contract side.

### Disbursement has six owners, and none of them is a department (2026-08-24)

As built, this repository holds no disbursement code at all: the payout decision
lives in ERP and the transport lives in `dotmac-integration` plus a connector.
What it does hold is the ownership register above, and until 2026-08-24 two
accepted records disagreed about one row of it.

ADR-0047 § Context (2026-08-18) said *"Finance/Payables owns obligations,
journals, disbursement and settlement"*. ADR-0042 (2026-08-19, one day later,
and devoted specifically to separating liabilities from payment execution) said
in its § 3 that Payables *"does not choose a bank account, payment rail,
provider, batch or execution time and does not perform network I/O"* and that a
**Treasury/payment owner performs disbursement**. **ADR-0042 controls.**
ADR-0047's sentence was written to say "not Expenses" and is narrowed to that by
its own dated Amendment A1; "Finance/Payables" is a department, and a department
cannot be pointed at in a review — the same error ADR-0061 A1 corrected when it
replaced "ERP's Treasury/payment owner" with a named service.

| Owner | Decision | Record |
|---|---|---|
| Expenses | whether a claim is eligible for reimbursement | ADR-0047 |
| Payables | what is owed, to whom, in what currency and when | ADR-0042 §§ 1, 3 |
| Treasury | the authorized payment instruction, rail submission and resolution | ADR-0042 § 3's unnamed owner; named for payouts by ADR-0061 § 1 + A1; scoped by ADR-0063 |
| Integrator | provider authentication, transport and evidence | ADR-0024 §§ 6–7, ADR-0061 § 1 |
| Banking | statement/cash observations and reconciliation evidence | ADR-0044 |
| Accounting | journal and ledger consequences | ADR-0041 |

Six owners, six failure modes, six sets of controls — which is why the compound
sentence had to be broken up rather than reworded.

**Treasury's scope, and why nothing is being built.** ADR-0063 authorizes a
narrow shared owner of `PaymentInstruction`
(`authorized → submitting → ambiguous | submitted → settled | failed |
reversed`), grouped by `PaymentRun` rather than by a provider batch, over two
rails from the beginning: an API rail through the Integrator bindable to
Paystack or Flutterwave v4, and a manual bank-file rail for AP and payroll.
Three of its invariants are worth restating here because they are the ones a
future implementer is most likely to violate by accident:

- **Exporting a spreadsheet must not mark an instruction paid.** An export
  proves a file was produced. `submitted` needs operator submission evidence;
  `settled` needs Banking's settlement observation.
- **Run progress is derived from instruction outcomes, never from a batch-level
  response.** Provider calls are not atomic: ten transfers can return seven
  successes, two failures and one ambiguous result, and a batch aggregate that
  believes the batch response marks the unknown one paid.
- **Rail routing is pre-submission only.** A Paystack timeout may have
  succeeded; a router that retries it through Flutterwave pays the beneficiary
  twice. The rail is stamped immutably at authorization, an ambiguous result
  reconciles against the ORIGINAL provider, and rerouting needs a conclusively
  unsubmitted or terminally failed instruction plus a new authorization.
  Paystack ↔ Flutterwave interchangeability is safe CONFIGURATION, not
  cross-provider retry.

**The gate:** none of it is constructed before ERP's `PaymentIntent.status`
three-writer violation is fixed in the ERP repository. Extraction copies a
lifecycle; a lifecycle with three writers has no owner, and porting it would
make one product's defect a shared module's contract. No `dotmac-treasury`
distribution, namespace, `mod_*` short code or migration lineage may be
allocated until then (ADR-0063 § 7, extending ADR-0061 A1).

**Evidentiary wording for ERP payout, required verbatim:
"Implemented and tested; production enablement unconfirmed."** The path is
gated by `paystack_transfers_enabled`, which is runtime data; confirming it
needs an explicitly named deployment target and a `deployment_run` oracle
(`AGENTS.md` rule 30), and no target has been named. This blocks no
construction — it blocks any claim of production parity, adoption or
retirement, in both directions. `BatchTransferService` is to be DELETED as
security-sensitive dead code now that the product-first dossier
`docs/inventories/treasury-payment-execution-sources.md` § 1.3 preserves its
disposition (ADR-0061 A7). That dossier is produced on the sibling branch
`docs/treasury-product-first-dossier` and is the evidence base for ADR-0063;
its own § 12.3 G5 asks for that record.

### The money-out leg: what is decided, in what order, and what blocks it (2026-08-24)

Four accepted rulings extend the six-owner split above. None of them is as-built
in this repository — it holds no disbursement code — so each is marked for what
it is: a decision recorded where it can be cited, with the as-built facts it
rests on named.

**`payments.refund.v1` is KEPT, and the reason it survives is the reason
`payments.customer.v1` did not.** ADR-0061 A5 removed the customer capability
because it named provider workflow; A8 runs the same test on refund and it
passes. The discriminating question:

> If the provider vanished tomorrow, would the thing still exist and still need
> an owner?

A provider-side customer record would not — there was never a Dotmac object,
only a mirror of `POST/PUT/GET /customer`. A refund obligation would: someone
with authority decided money goes back, for how much, against which original
payment, and it would be paid another way. **A provider-side customer record is
a by-product of an act; a refund IS the act.** So the capability is retained
while its provider-shaped OPERATIONS are removed: one command, `request_refund`,
carrying exact money, the original-payment correlation, the authorization
reference and idempotency identity — and Paystack's transaction handle and
Flutterwave's charge id become connector internals.

The as-built fact that shapes the refund rule: **Paystack's `/refund` accepts no
client reference.** There is no field for the engine's idempotency key, so the
connector stamps a derived key into `merchant_note`
(`packages/dotmac-connector-paystack/src/dotmac_connector_paystack/
operations.py:626-630`) and classifies an unanswered send as `AMBIGUOUS`
(`:368`), resolving it by reading the provider's refund list and matching the
note (`:68-73`). **That makes an ambiguous refund DECIDABLE; it does not make a
second refund REFUSED.** A duplicated payout is refusable at the provider
because its derived reference rides Paystack's own `reference` field; a
duplicated refund is not. The reconciliation read is therefore mandatory before
any re-request, no transport ever makes one, and a re-request is a new
authorized decision. **Treasury is not automatically the refund owner** — a
refund reverses a receivable rather than discharging a payable, it is not one of
ADR-0063 § 6's twelve closed items, and extending that list needs its own record
(ADR-0061 A8, A9).

**ERP splits `PROCESSING` before anything is extracted, and an unprobed row is
`ambiguous`.** ADR-0063 A1. `PROCESSING` today means both "the provider call is
running" and "a worker has picked this row up" — the second meaning is why
`poll_stuck_expense_transfers` writes the column at all — and carrying a state
that means both into a shared module under a better name would launder the
ambiguity into a contract. The vocabulary becomes `submission_requested` (a
durable intent, no provider outcome attempted), `submitted` (conclusively
accepted), `ambiguous` (may have landed, reconciliation required), and the
terminal `settled` / `failed` / `reversed`. **Worker claim/lease state moves to
the execution engine** (ADR-0014's at-most-once owner), which is most of why the
third writer exists. The migration rule carries the weight: existing
`PROCESSING` rows are **PROBED**, the probe is read-only, the **worker is
quiesced** for the duration, and **without conclusive provider evidence a row
maps to `ambiguous`, never `submitted`** — assuming success on migration is how
a double payment or a silently lost disbursement enters the new module, because
a row wrongly marked `submitted` is never looked at again.

**Payroll produces `PaymentInstruction` rows, and Treasury never sees a salary
component.** ADR-0063 A2 with ADR-0046 A1. One authorized net-pay obligation
produces one instruction; a run may group them into a `PaymentRun` without
conferring authorization; Treasury's manual rail produces the bank-upload
artifact; **exporting the file does not mark payroll paid** (ERP's payroll
export writes no status today, which is correct and must survive the port); and
settlement evidence returns to Payroll as a typed observation. Treasury receives
**net amount, currency, payee/destination reference and payroll obligation
reference — and nothing else.** Never gross, allowances, deductions, tax,
pension, garnishments or grade, including in a narration field. That is a
privacy boundary as much as an ownership one: the bank-file rail means the
artifact LEAVES, its audience is payments operations rather than HR, and
ADR-0063 § 2 requires Treasury to retain it immutably — so a component that
reaches Treasury is digested and archived beyond HR's reach to redact.

**The order, and the one thing that blocks release regardless of it**
(ADR-0063 A3):

| # | Step | Where |
|---|---|---|
| 1 | ERP execute-permission containment | ERP |
| 2 | ERP authorization-log audit on a named target | ERP |
| 3 | Delete dead `BatchTransferService` | ERP |
| 4 | Reduce `PaymentIntent.status` to one writer | ERP |
| 5 | Split `PROCESSING` from `ambiguous` | ERP |
| 6 | Add capability request/result schemas | `dotmac-integration` + connectors |
| 7 | Build Treasury `PaymentInstruction` and `PaymentRun` | new module |
| 8 | Add expense, AP and payroll producers | ERP → Treasury |
| 9 | Complete Paystack and Flutterwave payout bindings | connectors |
| 10 | Build refund through its named owner | Billing / the named owner |
| 11 | Provider sandbox proof, CI and cutover | all |

Steps 1–3 come first because they reduce blast radius and depend on no design
decision. Step 4's digest/version work may continue in parallel — it is internal
to ERP and touches no rail. But:

> **No payout release and no payout enablement passes the authorization
> blocker.**

The blocker is an as-built ERP fact, not a design concern: **ERP's broad
module-access scope `finance:access` currently satisfies the guard on
`POST /transfers/{intent_id}/initiate`, which executes a real transfer.** The
old helper also names `payments:read`, but that permission is absent from the
normal token allowlist and seeder, so it is not the live reachability mechanism.
The
weakest admitted credential is the one that defines a path's real authorization,
which makes every other control on that path decorative. A dedicated ERP
security change is implemented on `fix/payout-execute-permission-containment`.
This is a gate on RELEASE and ENABLEMENT and is independent of ADR-0063 § 7's
gate on CONSTRUCTION; satisfying either does not satisfy the other. It changes
no evidentiary claim in either direction — *"Implemented and tested; production
enablement unconfirmed"* remains the required wording (ADR-0061 A7), and the
blocker is a reason enablement must not be sought rather than evidence about
whether it has happened.

### Durable polling evidence: the module owns the retry loop, not the assembly

`dotmac-integration`'s POLL engine always recorded a success — receipts plus an
advanced cursor. It recorded nothing about a failure, so three questions a poll
worker must answer every cycle had no durable answer: how many times in a row
has this job failed, when may it be tried again, and what kind of failure was
it? An assembly answers them regardless. Answering them in the assembly means an
attempt counter in a worker's memory, a backoff constant in its loop, sometimes
a retry table in its own schema — a parallel retry ledger, and a second writer
of a decision the module already owned half of through the checkpoint's
optimistic `version`.

`dotmac_integration.poll_schedule` is the named owner. `PollingCheckpoint`
carries the current retry state (`attempt_count`, `next_attempt_at`,
`last_success_at`, `last_failure_at`, `last_failure_code`);
`mod_intg.polling_attempt_failures` is the never-rewritten per-attempt history;
`ensure_polling_checkpoint` owns declaration without rewind; and
`due_polling_jobs` is the sole bounded keyset selection a worker loops over.
The assembly gains a wake-up cadence and supplies an approved retention cutoff,
but it gains no second selector, retry ledger or deletion mechanism.

Five boundaries make it a shared engine rather than one deployment's scheduler:

- **floor, not cadence.** `next_attempt_at` means *not before*. A polling
  interval is a deployment's decision about one provider — a nightly bulk export
  and a live tail do not share one — so the module refuses to hold it.
- **no dead-letter.** A failing outbound delivery is eventually dead-lettered;
  a failing poll is not. A poll job that stops has no symptom but facts that
  stop arriving. The curve saturates at `ExecutionPolicy.max_backoff_seconds`
  and the job stays selectable; suppressing one keeps its existing owner
  (`lifecycle.disable` on the binding or installation, with its audit trail).
- **the cursor's version is untouched by failure bookkeeping.** `version` is a
  claim about the CURSOR; a failed attempt moved no cursor, and bumping it would
  make a concurrent in-flight settle lose a race that never happened.
- **one backoff owner.** `poll_backoff_seconds` delegates to
  `retry.retry_delay_seconds`, the same curve the outbox uses.
- **no provider or connector vocabulary reaches storage.** Eight engine-owned
  failure codes, closed by a database check constraint, and an evidence table
  with no free-text column at all — the same rule `test_integration_error_text`
  has to enforce by scanning elsewhere, enforced here by there being nowhere to
  break it.

Selection claims nothing on purpose. Two workers may read the same page; the
checkpoint's optimistic `version` decides which settles and the loser records a
`checkpoint_conflict`. A lease would be a second claim over a row that already
has a stronger one. Ordering by `(next_attempt_at, id)` makes healthy jobs
round-robin — a success stamps the floor with the moment of the success — and
pushes failing ones behind their own backoff, so an early permanently broken
checkpoint cannot starve the ones created after it. Keyset rather than offset
paging is what keeps that true across a multi-page walk, because the rows a
worker polls are the rows whose offsets would shift under it.

Failure evidence is finite only through
`poll_schedule.prune_poll_failure_history`. The module owns that bounded,
oldest-first deletion path, while the adopting product supplies the mandatory
timezone-aware cutoff. There is no module default, environment read or hidden
TTL, so installing the package cannot silently choose a retention posture.

### Runtime metrics: the module names them, the assembly exports them (ADR-0062)

`dotmac-integration` derives two kinds of runtime number from its own ledgers,
both at read time and neither stored: `operations.health_report` answers "is
anything silently stuck?" (in-flight leases expired, retryable overdue,
dead-letter, reconciliation-required, receipts unprocessed, checkpoints stale)
and `operations.dispatch_metrics` answers "how is the queue behaving?" (depth,
oldest-queued age, end-to-end latency, retries, failures, quarantined
installations).

The module ships **no** metrics client, counter registry or `/metrics` route,
and none of the other 80-odd distributions does either — verified by grep over
`packages/*/src`. What the module owns is the NAMES:
`operations.METRIC_NAMES` is a thirteen-entry tuple of stable,
`integration_`-prefixed, unit-suffixed identifiers that
`DispatchMetrics.as_metrics()` returns verbatim, pinned as literals by
`tests/unit/test_integration_runtime_safety.py`. The exporter belongs to the
deploying assembly (`dotmac_integrator`), which is why one module can be
composed by several assemblies exporting to different systems without a fork.

Two as-built qualifications:

- `HealthReport.as_dict()` returns bare dataclass field names —
  `dead_letter`, `checkpoints_stale` and so on — with no declared tuple and no
  `integration_` prefix. An assembly exporting the health signals therefore
  exports six unprefixed, undeclared names. ADR-0062 § 5 D2.
- `dotmac-analytics` and `dotmac-media-observations` also speak of "metrics";
  those are DOMAIN metrics — persisted, provenance-carrying, repairable facts
  under ADR-0043 and ADR-0034 — and are a different subject from the runtime
  numbers above. ADR-0062 § 4.

## Target deployment profiles and commercial authorities (accepted; partially implemented)

The current application implements `FeatureManifest`, `DISABLED_FEATURES`, and
`WEB_ENABLED`; the kernel also ships a validating
`ModuleManifest`/`ModuleRegistry`, manifest-owned permission and audit-action
catalogues with request/write-time enforcement, the capability catalogue, a
pure typed deployment-profile registry, tenant-local WS2 entitlement
grants/evaluation, and WS8 licence verification, revocation, and authenticated
applied-state contracts. The reference assembly owns the durable
licence/revocation receiver state and thin apply/import adapters. It does
**not** yet implement runtime profile/provider selection, the complete
effective-capability availability lifecycle, or an adopted subscriptions,
billing, collections or metering authority. Billing and Collections exist here
as independently releasable optional-package candidates but are not composed
into this reference assembly. The target architecture is authoritative in
[`ADR-0003`](adr/0003-unified-deployment-profiles.md); ADR-0006 owns its package
and presentation boundaries, with delivery gates in the
[`deployment profiles and commercial platform plan`](superpowers/plans/2026-07-18-deployment-profiles-commercial-platform.md).

New deployment types compose modules and providers across independent axes
(topology, operator, connectivity, commercial authority, identity, branding,
domains, locale, currency, legal/tax authority, residency, UI surface, updates,
and telemetry). Feature code must not branch on deployment-mode or plan-name
strings. A one-tenant deployment still provisions a tenant row and retains
tenant context, composite constraints, and RLS.

The planned request-time decision is:

```text
installed + deployment-enabled + migrated + dependencies + healthy
  + tenant entitlement + actor permission + applicable quota
  = effective capability
```

These authorities must remain distinct:

| Concern | Question answered | Required? |
|---|---|---|
| Permission | May this actor perform this action? | Yes for protected actions |
| Entitlement | May this tenant use this capability/limit? | Common commercial/access core |
| Feature flag | Should eligible traffic receive this rollout? | Optional; never authorization |
| Setting | How should enabled behavior operate? | As declared by a module |
| Subscription | What recurring plan/lifecycle applies? | Optional |
| Billing | What payment/invoice settlement occurred? | Optional |
| Collections | Which delinquency policy/case applies, and what consequence should be requested? | Optional |
| Metering | How much usage occurred and against which limit? | Optional |
| Signed licensing | Which offline/delegated grant is valid? | Optional; typical on-prem/OEM |

Contract grants, subscription state, or verified license claims project into
entitlement grants. Billing may update subscription state, and metering may
feed quota and/or billing, but request handlers consult local entitlement and
quota decisions—not payment providers or raw license payloads.

### Build and deployment execution: `dotmac-deployment-foundation` (as built, 2026-08-28)

ADR-0003 § "Infrastructure provisioning and deployment execution" declared
profile-specific deployment assets and reusable providers. It was never built,
and in the meantime four repositories implemented the same seven mechanisms four
times with four different sets of defects — one of them, this repository's own
`scripts/deploy.sh`, a self-declared hand-port that dropped the deployment lock,
the digest and evidence gates, the dirty-tree refusal, the migration preflight
and the warm candidate.

`packages/dotmac-deployment-foundation` is the concrete facility. It is
classified `universal-facility`, which is a real classification with
consequences rather than a label: `check_allocation_serialized.py` exempts it
from the migration-ledger gate because it legitimately owns no lineage, and
`tests/architecture/test_deployment_foundation_facility.py` holds it to five
properties with a planted-defect proof for each.

**Ownership, and where each line's boundary is drawn.**

| Owner | Owns | Explicitly does not own |
|---|---|---|
| `dotmac-kernel` | in-process contracts and mechanics: sessions and transaction boundaries, tenant priming, conflict savepoints, public error contracts, manifest contracts, migration-graph orchestration, the liveness/readiness and telemetry *interfaces*, the provisioning protocols | anything that renders infrastructure |
| `dotmac-deployment-foundation` | one release on one host: the descriptor and its refusals, the deterministic renderers, the hardened image contract and its audit, the ordered plan and its gates, the typed database descriptor-transition/CAS protocol and terminal receipt construction, backup/restore assurance, ingress providers, resource attributes and deployment annotations, the common alert catalogue, the conformance kit | the accepted descriptor pointer, a `DescriptorPromoter` implementation or its durable promotion events, durable fleet records, health status, signal storage, any in-process runtime contract |
| `dotmac-deployment-control` | durable fleet intent: desired state, immutable plans, approvals, rollout decisions and attempts, authenticated acknowledgements, drift-as-authority | Docker, Nginx, SSH, cloud providers, migrations, backup, monitoring — its own `EXTRACTION.toml` contract already says so, and ADR-0070 does not widen it |
| the product assembly | declarative input: identity, manifest reference, process roles and commands, worker/queue topology, image system packages, migration command, readiness dependencies, exposed ports, product hooks, domain alert rules, justified capability exceptions | the deployment engine, the renderers, any infrastructure alert |
| `dotmac-platform-health` | authenticated normalized health *observations* and their projection | raw logs, metrics, traces, deployment decisions, monitoring infrastructure |
| the external Observability platform | storage, queries, dashboards, alert delivery, operator access | alert *definitions*, which are the foundation's and the product's |

**Zero runtime dependencies is the load-bearing property.** Not the kernel, not
SQLAlchemy, not FastAPI, not Jinja, not a YAML library — rendering is explicit
Python emitting text. Two consequences: a build runner adopts the facility
without adopting a runtime, and `dotmac-deploy render --check` is a byte
comparison a reviewer reads as an ordinary diff. This is `dotmac-ui`'s shape and
it is here for the same reason.

**The plan is data.** `engine/plan.py` builds an ordered tuple of typed steps
whose first seven mutate nothing, and `engine/run.py` executes it against an
injected `Effects` protocol. That is what makes the twenty-case
failure-injection matrix a unit-test file rather than a disposable-VM exercise —
and a gate that has never been shown to fire is a gate nobody should trust. Two
of the source engine's gates were in fact found to be wrong only in production.

Every host MUTATION is now routed through `engine/run.py`'s `Executor`. The
`dotmac-deploy exposure-apply --execute` CLI and the Lane 3 rehearsal used to
invoke a second transaction class directly over the composed host effects,
outside `Executor`'s grant and execution-plan checks; that class is deleted.
Exposure is a typed effect the executor performs from an authorized
`FoundationExecutionPlanV3`, and `exposure-apply` observes without applying.
The V3 plan fixes the candidate's recorded wheel digest, target ID/ref,
controller SSH fingerprint, Fleet/Control host ID, host-key incarnation and
immutable enrolment/root-version reference. Foundation alone issues an
`ExecutionGrant` after a startup-fixed trusted assembly provider attests
Control's V2 authorization+dispatch pair and reobserves those independent
facts. V1 authority is retired; V1/V2 documents remain historical only.
The CLI/Lane 3/release path has no concrete CP provider composition yet and
therefore refuses execution; a request-selected verifier cannot bridge that
gap. F2 host-source admission remains the independent installed-source gate
before effects; the PEP610 wheel digest is source-artifact evidence, not a
fresh byte-integrity attestation.
F2's authenticated installed host ID, signer fingerprint and root-version
UUID are compared exactly to the V3 plan and fresh provider observation before
either deploy or rollback effects. `Effects` exposes no authenticated target
identity, so the CP adapter must compose its Effects, F2 admission provider
and V3 provider as one trusted in-process bundle; request fields cannot select
those independently. The V3 provider's pre-effect Control seam takes the
frozen original authorization+dispatch pair and a deterministic
`control-dispatch:<dispatch_id>` ledger key. Foundation compares the receipt,
V3 plan, fresh context, F2 trace, sequence/attempt and expiry before the call.
CP atomically revalidates current approval standing and consumes the exact
dispatch, refusing before commit or returning `None` only after commit.
Foundation performs no fallible post-commit check before effects. Control's
committed ledger is the recovery source if Foundation crashes before local
`DeploymentEvidence.v2` can record the same key; V1 evidence bytes are
unchanged. This source defines the seam; an external CP implementation
and its conformance proof are not present here. Installed-wheel release smoke
checks V3 render/digest bytes and an honest standalone CLI refusal; it may
pass without CP adoption, while the actual execution path still cannot.
Lane 3's two exposure items remain
`blocked` until the trusted pair and V3 plan name their act. The
`ApplicationFoundationProfile.v1` verifier is likewise report-only: this
assembly does not compose it into boot or deploy. No Foundation `HostSource`
provider is composed here, and failed-production recovery is deliberately
unreachable until its authorization and settlement bindings exist.

**A database result is declared before execution and promoted honestly.** The
transition binds target, plan, starting descriptor and result descriptor.
Authorization binds the result; the live starting state is its independent
precondition. One transaction has no intermediate durable state, while a
partially committing operation declares every ordered checkpoint. PostgreSQL
and Control's accepted pointer are separate transaction domains, so the gap
after the database commit is named `promotion_pending`, recovered by an
idempotent compare-and-swap, and closed only by a receipt carrying the observed
postcondition and Control's durable promotion event. Foundation owns this typed
mechanic. No accepted-pointer registry or `DescriptorPromoter` implementation
is composed in this tree yet. Platform CP's Git descriptor and promotion ledger
own its current accepted pointer and event; moving that authority into
Deployment Control requires an explicit migration rather than an as-built claim
written ahead of the code.

**Database drift is a pure two-way comparison, not a catalogue-to-descriptor
generator.** `database_drift.py` compares the accepted descriptor with a frozen
`CatalogEvidence` snapshot and reports declared-but-absent and
present-but-undeclared facts separately. Effective privilege comparison is
unmeasurable without a typed audit universe derived independently from the
descriptor. An independent `DatabaseDescriptorCatalogBindingV1` sidecar can
bind one or more release-contained catalogues by schema/path/digest to the
existing descriptor digest. A catalogue is explicitly module-scoped over one
complete schema or product-scoped over every expected schema. The two kernel v1
schema identifiers have exact, non-interchangeable scopes; an unknown future
schema is refused until its reader and scope are explicitly registered. A
product coordinate binds the catalogue product code and version to the exact
descriptor product, and any code alias requires a declared decision reference.
The sidecar is a
typed migration seam, not a v1 descriptor fact. `ProductDeploymentSpec.v2` is
the explicit successor: when it declares `[database]`, it requires and
digest-covers those coordinates while the v1 reader continues to refuse them.
`ProductDeploymentSpec.v3` retains that v2 database binding and adds a
digest-covered `compose_topology` for multi-network placement, typed mounts,
and profile-gated support jobs. The renderer derives the Compose services
from this field; the host provider validates descriptor-bound bind-source
hashes before mutating,
requires a byte-checked retained Compose asset, and requires an exact-output
postcondition for a deploy-time support job. A V3 plan does not promise
rollback from a previous image digest alone, even after an online migration;
the provider also refuses switching without a separately retained, authorized
old asset. This
schema is an implementation surface, not evidence that a product has adopted
it or retired its handwritten deployment asset.

Foundation does not parse those bytes or redefine their grammar. A separately
owned typed comparator and live observer must be invoked by an integrated
verifier over the held catalogue and observation bytes. A caller-supplied
result plus recognizable contract strings is not provenance and cannot mint a
witness. The result binds the exact observation identity also held by
`ObservedDatabaseState`, including PostgreSQL major, and carries typed
schema/table/column facts plus explicit completeness. Foundation invokes the
injected kernel verifier over both held payloads, then rechecks its factory-only
result's comparator id, fact scope, digests, PostgreSQL major, declaration
schema/scope/complete schemas and product code/version. Verified witnesses compose
by covered schema and carry drift findings in both directions. A
`mod_deploy` witness can prove its
seven-table/95-column slice, but it cannot expose `matched_descriptor_digest`
while `public` or another expected schema remains uncovered—and no sidecar can
expose it for v1 at all. V2 may expose it only after recognized witnesses cover
every expected schema. The current `CatalogEvidence` has no table/column
inventory and cannot produce such a witness.

**The provider seam is where a host lives, and there is exactly one provider.**
`engine/run.py` defines `Effects` — nineteen methods, no implementation — and
`providers/compose_host.py` is the dedicated-VM Docker Compose implementation of
it. Everything the facility can do to a host goes through one `subprocess.run`
seam with `shell=False` and an argv list, so a descriptor value containing `;`
or `$(…)` reaches the child as one literal argument. Forty constructor knobs,
each with a documented default, so no binary name, path, port, timeout or
service name is unoverridable.

The seam is what makes the failure matrix testable without infrastructure, and
it is also what stops the copying: a product that had to write its own provider
would write a slightly different one, which is the fork this facility exists to
prevent. A Kubernetes or cloud-runner provider is a second implementation of the
same protocol and changes no step of the plan.

**Nginx is a provider, not the architecture.** It is first because Sub's
warm-candidate handoff is the proven production behaviour and is Nginx-shaped.
It renders an upstream pair and a candidate handoff, and decides no tenant,
domain, TLS or business lifecycle. Static Nginx serves a KNOWN host set; dynamic
customer domains are explicitly out of scope and need a domain/DNS/TLS
reconciler, for which Caddy, Traefik, cert-manager or a managed load balancer
remain available.

**Filesystem inspection is not the runtime identity.** The reusable strict
image gate enumerates image files in a one-shot uid/gid 0 container so a
configured non-root user cannot make root-owned base-image paths invisible.
The audit independently reads `Config.User` from `docker image inspect` and
still refuses a missing, named, root or system-range runtime user. A failed
filesystem walk is a failed evidence collection: the gate preserves its
partial listing and diagnostics, then refuses instead of truncating the input
and auditing an empty file.

**Adoption status (repository baseline, 2026-09-20).** The latest published
Foundation version is `0.2.0a2`; `0.4.0a1` was built once, then its candidate
artifact was left unrecorded and its source drifted, so it is not an eligible
publication or rehearsal coordinate. No product has completed the Foundation
executor cutover or retired its previous writer. Platform CP is the current
control-plane bootstrap and first executor-cutover target; ERP remains the first
full data-plane adopter, followed by Sub. That distinction reconciles the
programme sequence with ADR-0070's original "ERP first full adopter" wording;
it does not amend the ADR. The measured gates and next work are in
`docs/BUILD_ONCE_CUTOVER_ROADMAP.md`; the publication baseline is
`docs/inventories/declared-publication-baseline.json`. Decision: ADR-0070.
Sources and the eighteen defects deliberately not extracted:
`docs/inventories/deployment-foundation-sources.md`.

### Target tenant lifecycle and global commercial foundations

The application currently has tenant creation and `Tenant.is_active`/
`suspended_at`/`deleted_at` fields, but no canonical tenant transition service,
cross-module lifecycle orchestrator, outbox/inbox, onboarding workflow,
subscription/billing/rating lifecycle, implemented support-access workflow, or
coordinated offboarding/purge path. The target uses separate tenant, subscription,
entitlement, provider-job, domain, and license state machines. Versioned policy
maps commercial events to restriction/suspension; payment failure never directly
deletes data.

The existing display settings provide timezone and date/datetime presentation
formats only. They are not internationalization, multi-currency, or
multi-jurisdiction support. The target keeps locale/language, timezone,
transaction and functional currencies, legal entity, tax jurisdiction, and
data residency independent. It adds stable message IDs/catalogs, exact Money,
immutable FX/price/rating/tax snapshots, and versioned jurisdiction policy while
keeping API facts and codes language-neutral.

Cross-module lifecycle mutations use idempotent commands, one local transaction
owner, transactional outbox/idempotent inbox, retryable provider jobs,
compensation, audit history, and reconcile/repair. Offboarding explicitly covers
final settlement, read-only/export, credential/integration/domain cleanup,
retention/legal hold, backup expiry, and purge.

### Target infrastructure provisioning and fleet operations

The existing Docker Compose and `scripts/deploy.sh` are a deployment primitive,
not an end-to-end fleet provisioner. The target platform control plane records a
pending `Deployment` and durable `ProvisioningRequest`; a restricted worker then
uses a selected infrastructure provider to plan, approve, create, bootstrap,
deploy, verify, activate, reconcile, and eventually retire it. Signup never runs
OpenTofu, Ansible, Helm, migrations, or cloud APIs synchronously.

The recommended first provider for dedicated ISPs is an isolated VM or cloud
project/account, managed PostgreSQL where available, object storage, external
secrets, DNS/TLS, and the existing immutable-image Compose release. Reusable
OpenTofu modules own cloud desired state with encrypted/locked remote state per
deployment; cloud-init/Ansible owns repeatable host bootstrap. The deployment
worker retains external resource IDs and evidence, not raw provider credentials,
and obtains least-privilege credentials from the configured secret/identity
authority.

Kubernetes is optional. A later managed-Kubernetes provider uses Helm/GitOps when
regional fleet size, HA, or multi-service scheduling justifies it, while keeping
separate ISP database and secret boundaries. A namespace alone is not treated as
equivalent to account/project/cluster isolation. On-prem starts with Compose and
can select K3s/conformant Kubernetes when the customer requires HA or already
operates it.

```text
verified signup/contract -> commercial order -> pending deployment
  -> IaC plan/approval/apply -> runtime bootstrap -> image deploy/migrate
  -> one tenant + owner -> entitlement/license projection -> DNS/TLS
  -> health/security/backup checks -> activation -> billing-start event
```

Every step is idempotent, serialized per deployment, resumable, audited, and
records desired versus observed state plus compensation/repair. Day-two
reconciliation handles drift, upgrades, renewals, backup verification, capacity,
disaster recovery, suspension, export, retention, and termination. Artifact CI
publishes signed images/SBOM/provenance; unrestricted fleet credentials remain in
the provisioning environment rather than application CI or tenant deployments.

Customer-controlled on-premise cannot provide an absolute source-confidentiality
guarantee: a privileged host/container operator can inspect image files and layers,
observe running code, and patch local license checks. The standard profile ships a
minimal signed runtime image/offline bundle—not a repository—built in multiple
stages with no Git history, tests, build secrets, or unnecessary source inputs in
any final layer. It runs non-root/read-only, pins by digest, verifies signature and
provenance, and contains only public licence/artifact verification material.

Native compilation or obfuscation of selected modules raises reverse-engineering
cost but is not treated as secrecy. Source-critical customers should select
vendor-managed dedicated hosting, where they do not control the host/image. A
separate attested-appliance profile may later use measured boot, confidential
computing, remote attestation, and conditional key release on supported hardware;
it still requires an explicit threat model and residual-risk statement. Contracts,
OEM/source licences, and escrow address legal/commercial rights, not technical
confidentiality.

### Target support, observability, and maintenance operations

Today the starter has correlated JSON request logs and a public liveness endpoint;
it does not yet provide readiness, metrics/traces, central telemetry, fleet heartbeat,
SLOs/alerts, support cases/access, diagnostic bundles, maintenance rings, or incident
management. The target uses vendor-neutral OpenTelemetry instrumentation and a local
collector, preserving request IDs while correlating logs, metrics, and traces.

Connected deployments export outbound over mTLS to a regional gateway; restricted
deployments can send signed aggregate health only; air-gapped deployments retain data
locally and generate customer-approved redacted/encrypted diagnostic bundles. The
gateway assigns canonical deployment/tenant scope from authenticated identity. Telemetry
uses attribute allowlists, redaction, sampling, bounded buffering, contractual retention
and residency, and excludes secrets, subscriber/business payloads, and high-cardinality
identifiers by default. Telemetry failure never blocks application requests.

The health surface separates public liveness, protected readiness, authenticated
diagnostics, and external synthetic journeys. Central storage and dashboards isolate
deployment/tenant data at ingest, query, alert, export, retention, and deletion. Alerts
focus on actionable symptoms/SLOs, backups, certificate/licence expiry, capacity, job lag,
drift, security exposure, and telemetry deadman signals; maintenance windows, grouping and
inhibition prevent alert storms.

Support requires a case, severity/SLA, consent or policy-approved break-glass, a
time-bounded least-privilege grant, an outbound customer-controlled channel for on-prem,
session/action/command recording, revocation, and customer-visible closure. Application
impersonation and host access are separate. Shared passwords, permanent vendor SSH keys,
hidden accounts, inbound-by-default tunnels, and invisible global impersonation are
forbidden.

Fleet maintenance inventories exact product/artifact/config/schema/module versions,
support/EOL state, drift and backup/restore proof. Releases move through internal, canary,
early-adopter and general rings with customer windows/approvals, preflight, backup,
migration compatibility, readiness/synthetic observation, automatic wave halt and
rollback evidence. The kernel defines common web/job/database/deployment signals;
assemblies add domain signals such as ISP RADIUS, provisioning, usage and subscriber-
service health. Incident management owns detection through recovery communication and
post-incident corrective work.

### Target cross-project reuse and frontend surfaces

Cloning this repository still creates an independent source snapshot; later
fixes do not propagate automatically. The repository now separates a versioned,
publishable `dotmac-kernel` from this thin reference assembly and proves the
built wheel in a clean consumer environment. The remaining target adds
versioned optional modules and `dotmac-ui`, resolved deployment profiles, and
product adoption through exact released pins. Maintained products use automated
update PRs to rebuild and run profile/lifecycle/migration tests before rollout.
A fix is implemented once but deployed deliberately—never injected silently
into running systems. ADR-0006 owns the package direction and forbids extraction
based on similarity alone. Its 2026-08-08 amendment also forbids a second
greenfield implementation once the contract gate passes and a qualifying,
tested product implementation exists: that product code and its behaviour tests
are the extraction source, product-specific dependencies become typed seams,
and the first product cutover retires the local owner.

As built, every distribution under `packages/` now carries a machine-checked
`EXTRACTION.toml` dossier. The non-growing debt map is explicit: the kernel and
UI package predate the dossier rule, while `dotmac-template-studio` remains
`audit-required`. Its audit RAN on 2026-08-10
([`template-studio-source-audit.md`](inventories/template-studio-source-audit.md))
and found that ERP's document-template stack and Sub's notification-template
stack are not one contract: the package's `kind` merge was disqualified, Sub was
selected as the source for the notification half, and the capability was mapped
to six owners of which this package is one (ADR-0006 § 5a–5c). The status stays
`audit-required` because approval needs two contract consumers, which an audit
cannot produce. The evidence index is
[`module-extraction-sources.md`](inventories/module-extraction-sources.md), and
`tests/architecture/test_product_first_extraction.py` prevents a new package
from entering with the same unresolved status.

The generated [`MODULE_CATALOG.md`](MODULE_CATALOG.md) is the as-built discovery
view over those independent owners; it owns no facts of its own. Package
`pyproject.toml` files own declared versions and kernel requirements,
`EXTRACTION.toml` owns contract/evidence/consumer state, `ModuleManifest` owns
runtime persistence-plane and schema declarations, and
`.github/release-modules.json` owns eligibility for the general module release
workflow. It covers both persistence shapes of an installable
`ModuleManifest`: every row carries a mandatory `db_schema`, either a `mod_*`
string for a stateful module or explicit JSON `null` for a stateless one. The
resolver proves that shape against the manifest's `short_code` and
`migration_prefix` before build; the installed-wheel smoke proves it again
through `ModuleRegistry`, and a stateless wheel containing migrations is
refused. This keeps a missing stateful schema a failure rather than turning
schema ownership into an optional check. `.github/release-adapters.json` owns
the separate question for `stateless-protocol-adapter` distributions, which
have no `ModuleManifest` or kernel floor and are gated, built and verified by
`release-adapter.yml` instead (ADR-0006's 2026-08-14 amendment).
`dotmac-auth-oidc` is one such server-side protocol adapter. Its confidential
web client and public-native ID-token verifier are separate public roles over
one private discovery/JWKS and token-verification core; it owns no mobile PKCE
verifier, product ceremony, local identity mapping, authorization decision or
product session. The native surface is declared in unreleased `0.1.0a2`, so
Sub remains a candidate until the protected adapter release exists, Sub pins
that exact artifact and its local verifier is deleted with exchange-path proof.
`.github/release-contracts.json` owns the fourth lane, for
`stateless-contract-catalogue` distributions — a product owner's capability
contracts as canonical schema bytes and digests. It shares the adapter's four
properties and adds a fifth the adapter lane cannot assert: a catalogue reaches
nothing, so `release_contract.py` refuses `httpx`, `requests`, `socket`,
`urllib` and `subprocess`, where an adapter is expected to declare a provider
client. That difference is why the connector lane's "a release profile, not a
new classification" ruling does not extend here (ADR-0006's 2026-08-26
amendment). The lane is CLOSED and currently empty: the seven candidate
catalogues live only on an archive ref and floor on a kernel capability grammar
that is not yet published, and absence from the allowlist is the lock.
The module lane's pre-publish smoke builds the target and kernel wheels plus
every repository-local distribution named by that module's reviewed
`wheel_contents.allowed_requires`; this is how the permitted
`module -> dotmac-ui` direction stays installable without giving the build job a
registry credential. The post-publish smoke separately installs from the
registry, so local dependency artifacts cannot substitute for publication.
The verify job also downloads the same immutable build artifact that the
publish job uploaded and invokes `compare-published` against the private index
before any tag. After registry verification and annotated tagging, the
post-release recorder hashes that exact wheel and appends its filename,
SHA-256, annotated tag object and peeled source commit to
`docs/inventories/module-release-verifications.json`. The row is producer-owned,
append-only and refuses coordinate rewrites; source work never predicts a
future release hash. The CI architecture gate validates every row and compares
the disjoint verification and legacy-unverified inventories with the complete
local annotated-tag oracle. Deleting a post-cutover verification row, changing
a tag object or peeled commit, or leaving a new tag unrecorded fails. The 120
pre-cutover governed tags in `module-release-legacy-unverified.json` retain
only real tag coordinates as of accepted source base
`7281adb1620ae5b5942518a9a01290330e198ec3`, because their registry-byte
proof was not retained;
they are debt/history, never verified or pinnable evidence. A consumer may pin
a checked-in verification row and independently recheck registry bytes, but
the legacy baseline cannot satisfy that check.

The annotated tag itself carries the canonical evidence, not free text: its
message is exactly one line of `ModuleReleaseTagEvidence.v1` JSON —
`distribution`, `version`, `wheel_filename`, `wheel_sha256` and
`verification_run_id` — produced by the single renderer
`render_module_release_tag_evidence` and read back only by its paired
`parse_module_release_tag_evidence` (both in `scripts/write_release_record.py`).
`scripts/tag_module_release.py` is the one fail-closed writer of that tag:
it refuses an already-existing tag, local or remote, and never force-tags,
deletes or recreates one — a release that needs a new tag ships a new
version instead. The recorder's validator proves a row against the tag
object it names by re-deriving `ModuleReleaseTagEvidence.v1` from the tag
message and checking the row's wheel filename, SHA-256 and
`verification_run_id` against it field-for-field; a row whose
`verification_run_id` disagrees with its own tag's embedded run id fails
the gate. The legacy `module-release-legacy-unverified.json` inventory is
frozen byte-identical to its accepted source base and carries no
`verification_run_id` — it is bootstrap history, not evidence, and the
gate never asks it to prove anything. `recover-module-release.yml`'s
artifacts (the downloaded original build and the record-PR's manual-fallback
guidance) live under the runner's own temp directory for the duration of
that run only; nothing persists there past the job, and the manual fallback
in `scripts/open_release_record_pr.sh` never prints that path to an
operator — it tells them to `gh run download` a fresh copy instead, which
`write_release_record.py` will refuse unless its digest matches the one
already embedded in the tag.

Separately, hosted CI compares the complete verification ledger at each PR's
immutable `pull_request.base.sha` (and each main push's `before` SHA) with the
new tree: accepted rows must remain identical and in order; only append is
allowed. A shallow checkout, unresolved base, or missing base ledger is a
refusal, not an implicit empty ledger. The initial inventory therefore needs
its own reviewed bootstrap commit before the append-only implementation gate
can run against it.
A row's `verification_run_id` and `source_run_id` name Actions runs, and the
Actions runs API exposes no dispatch inputs — so a real, successful run for
one module at a given commit is otherwise indistinguishable from a forged
ledger row naming that same run for a different module or version.
`scripts/module_release_provenance.py` is the single CI-invoked prover of
that binding, over only the rows a PR/push newly appended (an older row was
already proven when it was appended, and its run may since have expired or
been deleted from GitHub's retention window). For every new row it requires:
the named run belongs to an approved workflow (`release-module.yml` or
`recover-module-release.yml`), re-derived independently from its
`workflow_id`; was triggered by `workflow_dispatch`; reports `head_branch`
`main` AND its head commit is on the first-parent line of
`refs/remotes/origin/main` (a ref merely NAMED `main` or `origin/main`, such
as a tag, cannot satisfy this, and neither can a commit that only entered
main inside a merged branch); `repository` and
`head_repository` are this repository; the run id matches exactly; its
`display_title`
(rendered from the workflow's top-level `run-name`) equals exactly `Release
module <distribution> <version>` or `Recover module <distribution>
<version>`, binding the run to the specific module and version the row
claims; its "Tag the ..." step succeeded inside the job that owns tag
creation (`verify` or `recover`); the tag's peeled commit is itself on that
same first-parent line; and the run itself completed
successfully within a bounded wait. A release additionally requires
`source_run_id == verification_run_id` and that run's `head_sha` to equal the
tagged commit. A recovery additionally requires a `source_run_id` naming a
DIFFERENT run passing the same identity checks against `release-module.yml`
(including the first-parent check on its head commit), titled `Release module <distribution> <version>`, built at the tagged
commit, that did NOT succeed — recovery only ever applies to a release that
failed after publishing but before tagging. Runs dispatched before the
`run-name` binding existed carry no provable title and cannot be checked this
way; this is acceptable because no governed module has a verified row yet.
`ModuleReleaseTagEvidence.v1` gained `source_run_id` in place because no
tag carrying the earlier shape was ever emitted (no governed module release
ran between the two changes). Residuals, stated rather than implied: (a) the
check runs the pull request's own copy of the script, the same class as the
append-only checker, so a weakening made in the same diff is caught only by
review; (b) replacing a tag after a legitimate run (delete and re-push with a
different digest while keeping real run ids) is not bound to anything the run
itself produced — an availability risk to the record, not to registry
integrity, since publication is environment-protected; (c) restricting tag
creation to a dedicated release App ruleset is pending Michael, and no
blanket GitHub Actions bypass is granted in its place.
**Release authority at execution time (`ReleaseAuthority.v1`).**
`scripts/release_authority.py` derives the module release control surface
mechanically — both release workflows, every local composite action and
script they reach (run bodies, shell references, Python imports and string
references inside `scripts/`), the release allowlist, the row-deciding
checkers (`module_release_provenance.py`,
`check_module_release_verification_append_only.py`) and itself — plus every
third-party action as an `action:<owner/repo@40-hex>` coordinate (a mutable
reference is refused). Its canonical digest is the active authority in
`docs/inventories/release-authority.json`, whose `history` is append-only; a
test fails whenever the surface changes without the ledger moving. The tag
step computes the digest from its own checkout, refuses a stale ledger, and
records it in the tag evidence and the verification row. A new row is
authorized only when its digest is already in the BASE branch's history, the
ledger at the exact commit of the run that wrote the tag marked it active,
that commit's bytes (with the surface re-derived there) reconstruct it, and
the commit is on main's first-parent line — so a later authority change
cannot invalidate an authorized release, and a release PR cannot invent
authority. A pull request that changes the authority ledger and adds a
release row is refused, as is any row over a base without a ledger.
Dependency source is tested input, not release control: the smoke installs
the target, kernel and first-party dependencies only as the exact wheels the
run built, proves in an isolated interpreter that each installed
distribution came from exactly that file and has no files under the
checkout, and records every kernel/dependency wheel's filename and SHA-256
as `smoke_dependency_wheels` in the tag evidence and row. A rerun of the
same run may accept an existing tag only when its canonical bytes, tag
object, peeled commit, run ids, authority digest, smoke wheels and wheel
digest all match exactly; a recovery never replaces a tag — it adopts one
only after matching it to the original run and the recovered artifact, and
the row records the adopting run as `adopting_run_id`, which provenance
checks as a separate successful, authorized recovery run. Rebase-merge
configuration is optional hardening and is not part of this proof.

`scripts/module_catalog.py` joins those inputs deterministically, and
`tests/architecture/test_module_catalog.py` plus `make module-catalog-check`
refuse drift or an undiscoverable new distribution. An application still owns
its exact installed pins: `ModuleRegistry.inventory_payload()` reports that
deployment-local composition, while the repository catalogue only answers what
reusable distributions exist here and what their evidence currently proves.

ERP and ISP subscriber management remain separate product assemblies/data planes
even when they consume the same kernel. ERP `Organization` is the natural tenant
mapping candidate; in the ISP product, the ISP operator—not each subscriber—is
the tenant. Dedicated one-tenant deployments are the safe initial adoption path
for additional ISPs. The detailed strangler/adapter and later shared multi-ISP
tenant-safety program is in the
[`existing product adoption plan`](superpowers/plans/2026-07-18-existing-product-adoption.md).

The current architecture already points toward an API-first, not API-only,
surface model: feature `router.py` files expose JSON while `web.py` files and the
optional `web` manifest expose the Jinja/HTMX portal over shared services. The
target formalizes versioned OpenAPI contracts, generated-client tests, and a
capability/bootstrap response for separate SPA/mobile/partner frontends. The
built-in portal remains supported; `WEB_ENABLED=false` remains the API-only
composition. Cookie/CSRF rules apply to the same-origin portal, while external
frontends use explicitly configured bearer/OAuth/OIDC and CORS/origin contracts.

### Target domain, DNS, TLS, and ingress control plane

As built, `PLATFORM_ROOT_DOMAIN` serves both as the root host/platform context
and the suffix for `{tenant-slug}.{root}`. `TenantResolverMiddleware` also
accepts an exact `TenantDomain.domain` match only when `verified_at` is set.
There is currently no mutation API for `TenantDomain`, DNS ownership
verification, ingress reconciler, certificate lifecycle, or dynamic production
`TRUSTED_HOSTS` policy. ADR-0001's ingress examples are design intent, not a
completed custom-domain control plane.

The target profile separates these concerns:

- **Platform host:** the exact control-plane host, such as
  `console.example.com`; tenant traffic must not reach platform routes.
- **Tenant base domain(s):** wildcard tenant hosts such as
  `{slug}.app.example.com`, normally served by wildcard DNS and TLS.
- **Custom-domain target:** a stable CNAME/ALIAS target and ownership TXT
  challenge used before a customer domain becomes routable.
- **Ingress provider:** Nginx, Caddy, Traefik, Kubernetes ingress/cert-manager,
  or a managed load balancer implementation of one provider contract.
- **TLS provider:** ACME/DNS-01/HTTP-01, managed certificates, or manually
  supplied/customer-PKI certificates according to deployment profile.

`TenantDomain` is the desired application routing authority only after a
normalized domain passes ownership verification and reaches `active` state.
DNS and certificate systems remain external authorities; an idempotent
reconciler records their observed state, last error, certificate expiry, and
next retry. The planned lifecycle is:

```text
requested -> pending_dns -> verified -> pending_tls -> active
                                      \-> failed/retry
active -> suspended | removing -> removed
```

Domain input is lower-cased, IDNA-normalized, stripped of port/trailing dot,
globally unique, and checked against reserved/platform domains. A random DNS
TXT challenge—not CNAME presence alone—proves control. TLS is issued only after
verification; certificates renew before expiry and are revoked/removed when a
binding is retired. Wildcard certificates cover only the configured tenant
suffix, not arbitrary custom domains.

At the HTTP boundary, the selected proxy must preserve the validated `Host`,
set `X-Forwarded-Proto`, replace rather than append untrusted forwarding
headers, and be the only network peer whose forwarded headers the app trusts.
Unknown/unverified hosts fail closed. On-prem/air-gapped profiles can use local
DNS and customer PKI/manual certificates without any public ACME dependency.

## Layout

The kernel was extracted into an installable package (kernel-boundary Task 1);
`app/` is the reference **assembly** that consumes it as `dotmac_kernel.*` via an
editable path dependency — no copied modules, no import-path shims.

```
packages/dotmac-kernel/          the kernel package (distribution dotmac-kernel,
  pyproject.toml                 import dotmac_kernel, editable path dep)
  src/dotmac_kernel/   config, db, models base (+ cross-cutting identity models incl.
                 UserCredential), models_platform (PlatformAdmin/PlatformSession),
                 platform_auth (platform guard + auth routes), security,
                 deps (route guards), middleware/, logging, errors, crud,
                 features (manifest registry), modules (versioned ModuleManifest
                 + validating ModuleRegistry), permissions (PermissionSpec +
                 PermissionCatalogue), audit_actions (AuditActionRegistry), audit,
                 settings_models (DomainSetting), settings_resolver (spec
                 registry + tenant->platform->default resolver), templating
                 (Jinja env + render()), branding (static + per-tenant DB
                 override), identity (Party invariant helpers), web_deps
                 (cookie auth guard, shared with the bearer seam in deps.py)
packages/dotmac-ui/              the design-system package (distribution
  pyproject.toml                 dotmac-ui, import dotmac_ui, editable path dep,
  src/dotmac_ui/                 ZERO runtime dependencies)
                 contract (UI_CONTRACT_VERSION + namespaces + theme selectors),
                 tokens (191 role-named semantic design tokens),
                 assets (packaged static dir, stylesheet path/URL, digests),
                 a11y (WCAG 2.2 AA contrast contract + checker),
                 build (INTERNAL — the deterministic asset generator),
                 static/dotmac-ui/  the COMMITTED compiled stylesheet + manifest
packages/dotmac-template-studio/ the first optional stateful module (distribution
  pyproject.toml                 dotmac-template-studio; audit-required until
  EXTRACTION.toml                two contract consumers exist — ADR-0006 § 5b)
  src/dotmac_template_studio/    module manifest, service, API/web adapters,
                 package templates, models, and its own `ts` Alembic lineage;
                 `rendering` is pure single-brace substitution and `composition`
                 joins already-rendered email parts without delivery decisions
packages/dotmac-application-directory/ a tenant's connected-application
  pyproject.toml                 portfolio, and the permanent owner of the
  EXTRACTION.toml                `ApplicationDescriptor` contract (ADR-0021 §4).
  src/dotmac_application_directory/  manifest, descriptor, lifecycle, models,
                 service, and its own `ad` lineage in schema `mod_appdir`.
                 BUILT AND TESTED HERE, COMPOSED ELSEWHERE: this assembly does
                 NOT list it in `app/assembly.py` and `alembic.ini` does NOT
                 carry its lineage — the starter is a target application, not a
                 workspace, and composing it would create `mod_appdir` in every
                 starter deployment. Its consumer is `dotmac_workspace`. The
                 Postgres proof therefore provisions its own scratch database
                 (`tests/test_application_directory_isolation.py`) and the
                 composed migration gate runs over the same composition from
                 `tests/architecture/test_application_directory_module.py`,
                 since `make migration-gate` reads the shipped `alembic.ini`.
packages/dotmac-ticketing/       optional dual-plane ticket lifecycle
  pyproject.toml                 distribution dotmac-ticketing; audit-complete,
  EXTRACTION.toml                with ERP then Vendor CP as candidate cutovers
  src/dotmac_ticketing/          persistence-free lifecycle/vocabulary engine,
                 explicit tenant/platform models, per-plane link helpers,
                 manifest, and independent `tk` lineage in schema `mod_tkt`.
                 COMPOSED by this reference assembly for catalog proof, but it
                 has no surface or production contract consumer yet. Each real
                 adopter installs and owns separate rows (ADR-0024).
packages/dotmac-files/           optional dual-plane stored-byte lifecycle
  pyproject.toml                 distribution dotmac-files; audit-complete,
  EXTRACTION.toml                with ERP, Academy, then Vendor CP as candidate
                                 cutovers (ADR-0022/0023); ERP E8 is a
                                 prerequisite and none is counted yet
  src/dotmac_files/              admission contracts, provider seam, metadata,
                 shared persistence-free physical engine, scoped lifecycle,
                 manifest, and independent `fi` lineage in schema `mod_files`.
                 Tenant rows use forced RLS; platform rows are tenant-free and
                 revoked from app_user. BUILT AND TESTED HERE, NOT COMPOSED by
                 this reference assembly. Domains retain attachment meaning,
                 authorization and retention; import parsing is separate.
packages/dotmac-imports/         optional bulk-import run ledger
  pyproject.toml                 distribution dotmac-imports; audit-complete,
  EXTRACTION.toml                with ERP then Sub as candidate cutovers and
                                 CRM as source evidence (ADR-0025); the release
                                 lane is authorized, but no cutover is counted
  src/dotmac_imports/            run/row contract, CSV decoding, alias-based
                 column mapping and preview, the validate/promote/apply
                 service, manifest, and independent `im` lineage in schema
                 `mod_imports`. Tenant plane only — the audit found no
                 control-plane import capability in the fleet. BUILT AND
                 TESTED HERE, NOT COMPOSED by this reference assembly. The
                 domain owns the field vocabulary, validation and mutation;
                 `dotmac-files` owns the bytes the run reads.
packages/dotmac-people/          optional tenant employment directory
  pyproject.toml                 distribution dotmac-people; audit-complete,
  EXTRACTION.toml                with ERP as the qualifying source and clean
                                 Backoffice as the first exact-pin consumer
  src/dotmac_people/             narrow employee lifecycle, organization
                 catalogues, positions, temporal assignments and date-aware
                 reporting resolution; manifest plus independent `pe` lineage
                 in schema `mod_people`. Tenant plane only, forced RLS, and
                 linked to kernel Party through `party_person_catalog.v1`.
                 BUILT AND TESTED HERE, NOT COMPOSED by this reference
                 assembly. No ERP identity, payroll, attendance, finance,
                 integration, notification or persisted vacancy cache ports.
packages/dotmac-content/         optional tenant editorial content owner
  pyproject.toml                 distribution dotmac-content; audit-complete,
  EXTRACTION.toml                with Mkt as the qualifying source and
                                 Backoffice as the first candidate cutover
  src/dotmac_content/            guarded plan/item lifecycle, canonical text,
                 provider-neutral authored variants, ordered opaque creative
                 references and immutable ORM-free snapshots; manifest plus
                 independent `ct` lineage in schema `mod_content`. Tenant
                 plane only and forced RLS. BUILT AND TESTED HERE, NOT
                 COMPOSED by this reference assembly. Publishing, outbound
                 campaigns, stored bytes, authorization, people, tasks and
                 provider transport remain separate owners.
packages/dotmac-publishing/      optional tenant publication lifecycle owner
  pyproject.toml                 distribution dotmac-publishing; audit-complete,
  EXTRACTION.toml                with Mkt as the qualifying source and
                                 Backoffice as the first candidate cutover
  src/dotmac_publishing/         immutable publication snapshots, requested
                 delivery time, opaque target deliveries, monotonic attempts,
                 deduplicated observations and derived aggregate state;
                 manifest plus independent `pb` lineage in schema
                 `mod_publishing`. Tenant plane only and forced RLS. BUILT AND
                 TESTED HERE, NOT COMPOSED by this reference assembly.
                 Content, target-selection policy, durable timer storage,
                 provider identity, credentials and transport remain separate
                 owners.
packages/dotmac-sites/           optional tenant website-composition owner
  pyproject.toml                 distribution dotmac-sites; audit-complete,
  EXTRACTION.toml                greenfield after the exact six-repository
                                 census; Backoffice is candidate cutover 1
  src/dotmac_sites/              stable site/page identity, append-only page
                 revisions, immutable composed site revisions, typed
                 navigation/SEO/redirects and deterministic SiteReleaseV1;
                 manifest plus independent `si` lineage in schema `mod_sites`.
                 Tenant plane only and forced RLS. BUILT AND TESTED HERE, NOT
                 COMPOSED by this reference assembly. Files, forms,
                 publication intent/outcomes and Integrator hosting transport
                 remain separate owners.
packages/dotmac-inventory/       optional tenant stock-ledger owner
  pyproject.toml                 distribution dotmac-inventory; audit-complete,
  EXTRACTION.toml                product-first from ERP; ERP is candidate
                                 cutover 1 (ADR-0036)
  src/dotmac_inventory/          items, warehouses, immutable movements,
                 balances, reservations, lot/serial traceability and moving-
                 average valuation; manifest plus independent `iv` lineage in
                 schema `mod_inventory`. Tenant plane only and forced RLS.
                 BUILT AND TESTED HERE, NOT COMPOSED by this reference
                 assembly. Procurement authorisation, payables, GL posting and
                 durable-asset lifecycle remain separate owners.
packages/dotmac-assets/          optional tenant durable-unit owner
  pyproject.toml                 distribution dotmac-assets; audit-complete,
  EXTRACTION.toml                product-first from ERP; ERP is candidate
                                 cutover 1 (ADR-0037)
  src/dotmac_assets/             durable-unit identity, physical lifecycle,
                 opaque location, custody/assignment history, maintenance and
                 disposal with append-only evidence; manifest plus independent
                 `as` lineage in schema `mod_assets`. Tenant plane only and
                 forced RLS. BUILT AND TESTED HERE, NOT COMPOSED by this
                 reference assembly. Capitalization, depreciation, stock,
                 position observations and product extensions remain separate
                 owners.
packages/dotmac-customers/       optional tenant customer-account owner
  pyproject.toml                 distribution dotmac-customers; audit-complete,
  EXTRACTION.toml                with Sub as the qualifying source and first
                                 candidate consumer
  src/dotmac_customers/          account identity/lifecycle, narrow profiles,
                 and typed opaque Party references; manifest plus independent
                 `cu` lineage in `mod_customers`. Tenant plane only, forced
                 RLS, built and tested here but not composed. Authentication,
                 reachability, addresses, qualification, commercial terms,
                 services, billing and network state remain outside.
packages/dotmac-service-catalog/ optional technical service catalogue
  pyproject.toml                 distribution dotmac-service-catalog;
                                 audit-complete with Sub as qualifying source
  src/dotmac_service_catalog/    specifications, plan families,
                 characteristics and eligibility-input declarations; `sc`
                 lineage in `mod_svc_cat`, tenant-only forced RLS, built and
                 tested here but uncomposed. Offers, prices, contracts,
                 subscriptions and fixed recurrence are excluded.
packages/dotmac-qualification/   optional qualification-decision owner
  src/dotmac_qualification/      time-bounded observation evidence and
                 expiring decisions; `qu` lineage in `mod_qual`, tenant-only
                 forced RLS, uncomposed. Positioning/network systems supply
                 facts but never write the authoritative decision.
packages/dotmac-services/        optional service-instance lifecycle owner
  src/dotmac_services/           current status plus immutable transition
                 history; `se` lineage in `mod_services`, tenant-only forced
                 RLS, uncomposed. Customer, catalogue and qualification
                 identities remain opaque; enforcement and billing stay out.
packages/dotmac-usage/           optional normalized usage-fact owner
  src/dotmac_usage/              immutable observations, append-only corrections
                 and rebuildable aggregates; `us` lineage in `mod_usage`,
                 tenant-only forced RLS, uncomposed. Raw AAA and rating stay out.
packages/dotmac-usage-rating/    optional pre-tax usage-rating owner
  src/dotmac_usage_rating/       effective rules and immutable obligations;
                 `ur` lineage in `mod_usage_rate`, tenant-only forced RLS,
                 uncomposed. Invoices, tax, payments and accounting stay out.
packages/dotmac-service-access-policy/ optional desired-access decision owner
  src/dotmac_service_access_policy/ per-service policy inputs and desired state;
                 `sap` lineage in `mod_serviceaccess`, tenant-only forced RLS,
                 uncomposed. Network Access remains the only enforcer.
packages/dotmac-inbox-operations/ optional staffed-inbox operation owner
  src/dotmac_inbox_operations/   executable routing and decision evidence,
                 durable FIFO queues, four-state chosen availability with a
                 state-free heartbeat and derived busy, eligible-agent
                 assignment, and claim/transfer/requeue/escalate as separate
                 commands; `io` lineage in `mod_inbox_ops`, tenant-only forced
                 RLS, uncomposed.
packages/dotmac-response-obligations/ optional response-time clock owner
  src/dotmac_response_obligations/ named policies per product-declared subject
                 type, priority-resolved first-response/next-response/
                 queue-wait/resolution targets, a running clock whose stored
                 due instant a resume moves, itemised paused intervals each
                 carrying a required reason, and append-only warning/breach
                 observations; `ro` lineage in `mod_sla`, tenant-only forced
                 RLS, uncomposed. Durable Timers schedules, Operational
                 Escalations decides the consequence, Messaging delivers.
packages/dotmac-workforce/       optional workforce scheduling/dispatch owner
  src/dotmac_workforce/          teams, skills, memberships, shifts,
                 availability and opaque-work dispatch decisions; `wf`
                 lineage in `mod_workforce`, tenant-only forced RLS,
                 uncomposed. People and Work Order lifecycles stay out.
packages/dotmac-fx-policy/       optional FX observation/selection owner
  src/dotmac_fx_policy/          rate types, sources, effective policy,
                 observations and determination evidence; `fx` lineage in
                 `mod_fx_policy`, tenant-only forced RLS, uncomposed. Money,
                 invoice snapshots, tax, provider I/O and GL stay out.
packages/dotmac-ipam/            network-suite-v1: tenant address-space owner
packages/dotmac-network-inventory/    network-suite-v1: managed sites, nodes,
                                 interfaces, ports, VLANs and admission
packages/dotmac-network-observability/ network-suite-v1: observations,
                                 measurements, availability and alert evidence
packages/dotmac-network-topology/     network-suite-v1: declared/observed
                                 links, paths and reachability projections
packages/dotmac-network-assurance/    network-suite-v1: incidents, impact,
                                 maintenance and SLA evidence
packages/dotmac-network-control/      network-suite-v1: provider-neutral
                                 commands, dispatch and execution evidence
packages/dotmac-fiber-plant/     network-suite-v1: outside-plant structures,
                                 strands, splices, terminations, continuity
packages/dotmac-network-access/  network-suite-v1: access projections,
                                 authentication/accounting facts and sessions
packages/dotmac-pon-access/      network-suite-v1: OLT/ONT commissioning,
                                 desired state and optical evidence
                 The nine network-suite-v1 candidates each own one independent
                 lineage (`ip`, `ni`, `no`, `nt`, `na`, `nc`, `fp`, `nac`,
                 `pn`) in its own schema, tenant plane only and forced RLS.
                 They import no sibling module and hold cross-owner references
                 opaquely. BUILT AND TESTED HERE AS ONE COHORT, NOT COMPOSED
                 by this reference assembly and not released before Sub's
                 first-authority cutover (ADR-0038).
packages/dotmac-positioning/     optional tenant position-evidence owner
  pyproject.toml                 distribution dotmac-positioning;
  EXTRACTION.toml                audit-complete, no adopter yet (ADR-0039)
  src/dotmac_positioning/        provider-neutral position observations,
                 tracked-unit identity and derived motion/stop facts; manifest
                 plus independent `po` lineage in schema `mod_pos`. Tenant
                 plane only and forced RLS. BUILT AND TESTED HERE, NOT COMPOSED
                 by this reference assembly. Deliberately NOT part of the
                 network suite: Assets owns a durable unit's AUTHORITATIVE
                 location, positioning only observes, and the adopting product
                 keeps every geofence, SLA, dispatch and billing consequence.
app/                             the reference assembly
  features/
    tenants/       platform-level tenant provisioning (no tenant context)
    auth/          JWT login, sessions, /auth/me; owns /admin/login+logout (web)
    parties/       person + organization CRUD (/parties/people, /parties/organizations)
                   + /admin/parties/* web screens (list/detail/create/edit)
    rbac/          roles, role grants, audit-event read endpoint
                   + /admin/roles, /admin/role-grants, /admin/audit web screens
    settings/      tenant settings admin API (spec declarations, seed, router)
                   + /admin/settings web screens (generic editor + branding editor)
    presentation/  stateless assembly adapter: resolved kernel brand data ->
                   dotmac-ui token CSS at GET /branding/theme.css
    custom_fields/ field definitions CRUD + values on a registered entity's
                   custom_fields JSONB column (zero migrations per field)
                   + /admin/custom-fields web screens, incl. the
                   values-panel fragment other features' pages embed
    web/           core=False, deletable — owns only the /admin dashboard shell
  main.py        app assembly: middleware stack, error handlers, /health,
                 feature mounting
templates/       Jinja templates for the admin portal (see "Admin portal" below)
static/          Tailwind v4 CSS + vendored htmx/Alpine JS for the portal
```

### Position evidence stops at the observation (ADR-0039)

`dotmac-positioning` is deliberately NOT part of the network suite, and the
boundary is the reason it exists as its own owner: an observation is not a
decision, and a coordinate is not a consequence. Products own consequences.

| Contract surface | Owner | Non-owner boundary |
|---|---|---|
| Position observations and projections | `dotmac-positioning` (`mod_pos`, tenant plane only) | Owns no vehicle lifecycle, work-order lifecycle, attendance consequence, provider transport or map presentation |
| A durable unit's AUTHORITATIVE location | `dotmac-assets` | Reads no observation; positioning never overwrites it — a product asks the asset owner to move it when policy permits |
| Subject links, applicability, policy and every business consequence — geofence action, SLA, dispatch, billing | the adopting product (Sub is cutover 1, ERP cutover 2) | Imports no positioning persistence; links a local subject to an opaque tracked-unit id |
| Static plant, GIS and map coordinates | `dotmac-fiber-plant`, `dotmac-network-inventory`, `dotmac-network-topology` | Carrying a coordinate does not make state position evidence; these are fixed infrastructure, not tracked units |

Consent is part of the evidence, not the product: `collection_grants` carries
purpose, expiry and revocation, so a tracked unit whose grant lapsed stops
being observable without the product having to remember.

### ERP / Backoffice / general publication-prep ownership map

The following tenant-only packages are as-built in this repository at
`0.1.0a1`, allocated by published kernel `0.1.0a85`, and deliberately not
composed or release-allowlisted. Each row names the package's decision owner;
products retain their current authority until the dossier's sealed cutover and
writer-retirement gate completes. The cohort validation and adopter dependency
map is
[`erp-backoffice-general-publication-readiness.md`](inventories/erp-backoffice-general-publication-readiness.md).

| Package | Sole owned decision/state surface | Qualifying provenance |
|---|---|---|
| `dotmac-accounting` | Tenant chart, fiscal periods/dimensions, balanced posting, reversal and immutable ledger evidence | ERP GL behavior and tests |
| `dotmac-analytics` | Declared aggregate observations and deterministic rebuildable current-point projections | ERP metric storage/computers; fleet projection requirements |
| `dotmac-banking` | Bank-account masters, statement/cash observations, matching decisions and reconciliation evidence | ERP banking behavior |
| `dotmac-documents` | Controlled document identity, immutable exact-content versions, lifecycle, collaboration and acknowledgements | ERP handbook base plus Sub immutable quote delta |
| `dotmac-expenses` | Requests, claims, receipt meaning, policy evaluation, lifecycle and reimbursement eligibility | ERP expenses behavior |
| `dotmac-finance` | Fixed-asset accounting books, valuations and immutable balanced consequences | ERP fixed-assets behavior |
| `dotmac-inbox` | Conversation/message identity and lifecycle, ordering/threading, per-operator read cursors and typed identity-preserving history adoption | Sub Team Inbox behavior |
| `dotmac-response-obligations` | Response-time targets, running clocks, itemised paused time and breach observations against an opaque subject | Sub SLA clock behavior; ERP read-time targets and CRM copy are demand |
| `dotmac-party` | Party business capacities, capacity relationships, memberships, reachability evidence and external-reference provenance | Sub Party-context behavior; kernel Party retains identity |
| `dotmac-payables` | Supplier invoices/credits, recognized liabilities and payment-obligation lifecycle | ERP AP behavior |
| `dotmac-payroll` | Component policy, immutable structures, calculation evidence and employee/external liabilities | ERP payroll behavior |
| `dotmac-procurement` | Requisitions, sourcing, supplier offers, awards and purchase commitments | ERP procurement behavior |
| `dotmac-projects` | Project/task identity and lifecycle, hierarchy, dependencies, templates, schedule constraints and assignments | Sub project/task behavior |
| `dotmac-records` | Record declarations, retention schedules/triggers, legal holds, preservation/custody and disposition authority | Greenfield after the exact fleet inventory |
| `dotmac-surveys` | Survey definitions/invitations, response evidence, answer validation and rebuildable feedback aggregates | Sub communications-surveys behavior |
| `dotmac-tax` | Tenant tax policy, determinations, statutory report snapshots, filing obligations and return lifecycle | ERP tax behavior; Sub supplies billing facts only |
| `dotmac-work-orders` | Physical-work execution lifecycle and evidence | Sub internal-crew WorkOrder behavior |

Every persisted class in this cohort has an explicit owner. Table names below
are relative to the package's declared `mod_*` schema; every adopter owns its
local copy and no cross-application or sibling-module foreign key is implied.

| Package | Persisted model classes | Owned tables | Decision source |
|---|---|---|---|
| `dotmac-approvals` | `ApprovalPolicy`, `ApprovalRequest`, `ApprovalDecision`, `ApprovalWithdrawal`, `PlatformApprovalPolicy`, `PlatformApprovalRequest`, `PlatformApprovalDecision`, `PlatformApprovalWithdrawal` | `approval_policies`, `approval_requests`, `approval_decisions`, `approval_withdrawals`, `platform_approval_policies`, `platform_approval_requests`, `platform_approval_decisions`, `platform_approval_withdrawals` | ERP product-first plus Vendor CP control-plane delta; ADR-0026. Withdrawal evidence is append-only; request standing moves to `withdrawn` while the original APPROVE decision and completion time remain. The DB-owned withdrawal operation pairs approved parent, exact `completed_at` evidence and terminal standing; the standing-transition trigger writes one complete `approval.withdrawn` outbox row for every valid transition, even paired raw owner DML. Direct online-role table DML cannot forge either side. Public withdrawal commands use that operation in the caller transaction through the required `outbox_relay.v1` prerequisite. Downgrade refuses any selected plane holding withdrawal evidence before dropping either plane. Generic approval event delivery remains an adapter. |
| `dotmac-accounting` | `AccountCategory`, `Account`, `FiscalYear`, `FiscalPeriod`, `AccountingDimension`, `AccountingDimensionValue`, `JournalEntry`, `JournalLine`, `JournalLineDimension`, `PostedLedgerLine`, `PostedLedgerDimension`, `PeriodEvent` | `account_categories`, `accounts`, `fiscal_years`, `fiscal_periods`, `accounting_dimensions`, `accounting_dimension_values`, `journal_entries`, `journal_lines`, `journal_line_dimensions`, `posted_ledger_lines`, `posted_ledger_dimensions`, `period_events` | ERP product-first; ADR-0041 |
| `dotmac-analytics` | `MetricCatalogEntry`, `MetricIngestReceipt`, `MetricObservation`, `MetricPoint`, `MetricProjectionRebuild` | `metric_catalog_entries`, `metric_ingest_receipts`, `metric_observations`, `metric_points`, `metric_projection_rebuilds` | ERP product-first; ADR-0043 |
| `dotmac-banking` | `BankInstitution`, `BankAccount`, `BankStatement`, `BankStatementLine`, `CashAccountObservation`, `MatchPolicy`, `MatchDecision`, `MatchAllocation`, `Reconciliation` | `bank_institutions`, `bank_accounts`, `bank_statements`, `bank_statement_lines`, `cash_account_observations`, `match_policies`, `match_decisions`, `match_allocations`, `reconciliations` | ERP product-first; ADR-0044 |
| `dotmac-documents` | `DocumentLibrary`, `DocumentTypeVersion`, `Document`, `DocumentVersion`, `DocumentRendition`, `DocumentClassification`, `DocumentRelation`, `DocumentCheckout`, `DocumentAnnotation`, `DocumentAccessGrant`, `DocumentAcknowledgement`, `DocumentEvent` | `document_libraries`, `document_type_versions`, `documents`, `document_versions`, `document_renditions`, `document_classifications`, `document_relations`, `document_checkouts`, `document_annotations`, `document_access_grants`, `document_acknowledgements`, `document_events` | ERP base plus Sub delta; ADR-0049 |
| `dotmac-expenses` | `ExpenseCategory`, `ExpensePolicy`, `ExpensePolicyRule`, `ExpenseRequest`, `ExpenseRequestLine`, `ExpenseClaim`, `ExpenseClaimLine`, `ExpenseReceipt`, `ExpensePolicyEvaluation`, `ExpenseLifecycleEvent` | `expense_categories`, `expense_policies`, `expense_policy_rules`, `expense_requests`, `expense_request_lines`, `expense_claims`, `expense_claim_lines`, `expense_receipts`, `expense_policy_evaluations`, `expense_lifecycle_events` | ERP product-first; ADR-0047 |
| `dotmac-finance` | `AssetBook`, `DepreciationRun`, `DepreciationLine`, `AccountingEvent`, `AccountingConsequence`, `AccountingConsequenceLine` | `asset_books`, `depreciation_runs`, `depreciation_lines`, `accounting_events`, `accounting_consequences`, `accounting_consequence_lines` | ERP product-first; ADR-0048 |
| `dotmac-inbox` | `Conversation`, `Message`, `ConversationReadState` | `conversations`, `messages`, `conversation_read_states` | Sub product-first; ADR-0052 |
| `dotmac-party` | `PartyRole`, `PartyRelationship`, `PartyMembership`, `PartyContactPoint`, `PartyExternalReference` | `party_roles`, `party_relationships`, `party_memberships`, `party_contact_points`, `party_external_references` | Sub product-first; kernel Party retains identity; ADR-0019 |
| `dotmac-payables` | `SupplierInvoice`, `SupplierInvoiceLine`, `CreditNote`, `CreditNoteLine`, `PaymentObligation`, `LiabilityEvent`, `CreditApplication`, `SettlementObservation`, `AccountingReceipt` | `supplier_invoices`, `supplier_invoice_lines`, `credit_notes`, `credit_note_lines`, `payment_obligations`, `liability_events`, `credit_applications`, `settlement_observations`, `accounting_receipts` | ERP product-first; ADR-0042 |
| `dotmac-payroll` | `PayComponent`, `PayStructure`, `PayStructureRevision`, `PayStructureRule`, `PayRuleBasis`, `EmployeePayAssignment`, `PayrollRun`, `PayrollCalculation`, `PayrollCalculationLine`, `PayrollLiability`, `PayrollLiabilitySettlement` | `pay_components`, `pay_structures`, `pay_structure_revisions`, `pay_structure_rules`, `pay_rule_bases`, `employee_pay_assignments`, `payroll_runs`, `payroll_calculations`, `payroll_calculation_lines`, `payroll_liabilities`, `payroll_liability_settlements` | ERP product-first; ADR-0046 |
| `dotmac-procurement` | `PurchaseRequisition`, `PurchaseRequisitionLine`, `SourcingEvent`, `SourcingEventLine`, `SourcingInvitation`, `BidSubmission`, `BidLine`, `BidEvaluation`, `PurchaseOrder`, `PurchaseOrderLine`, `ReceiptObservationRecord`, `ProcurementEvidence` | `purchase_requisitions`, `purchase_requisition_lines`, `sourcing_events`, `sourcing_event_lines`, `sourcing_invitations`, `bid_submissions`, `bid_lines`, `bid_evaluations`, `purchase_orders`, `purchase_order_lines`, `receipt_observations`, `procurement_evidence` | ERP product-first; ADR-0050 |
| `dotmac-projects` | `Project`, `ProjectTemplate`, `ProjectTemplateTask`, `ProjectTemplateTaskDependency`, `ProjectTask`, `ProjectTaskDependency`, `ProjectTaskAssignee` | `projects`, `project_templates`, `project_template_tasks`, `project_template_task_dependencies`, `project_tasks`, `project_task_dependencies`, `project_task_assignees` | Sub product-first; ADR-0051 |
| `dotmac-records` | `RetentionScheduleVersion`, `RecordSeriesVersion`, `Record`, `RecordTriggerObservation`, `LegalHoldCase`, `LegalHoldTarget`, `DispositionBatch`, `DispositionItem`, `CustodyTransfer`, `PreservationCheck`, `RecordEvent` | `retention_schedule_versions`, `record_series_versions`, `records`, `record_trigger_observations`, `legal_hold_cases`, `legal_hold_targets`, `disposition_batches`, `disposition_items`, `custody_transfers`, `preservation_checks`, `record_events` | Greenfield after exact fleet inventory; ADR-0049 |
| `dotmac-surveys` | `Survey`, `SurveyInvitation`, `SurveyResponse` | `surveys`, `survey_invitations`, `survey_responses` | Sub product-first; ADR-0053 |
| `dotmac-tax` | `TaxAuthority`, `TaxJurisdiction`, `TaxCode`, `TaxRule`, `TaxRuleBand`, `TaxDeterminationSet`, `TaxDetermination`, `TaxDeterminationLine`, `StatutoryReportDefinition`, `StatutoryReportBox`, `TaxFilingObligation`, `StatutoryReport`, `StatutoryReportValue`, `TaxReturn`, `TaxReturnEvent` | `tax_authorities`, `tax_jurisdictions`, `tax_codes`, `tax_rules`, `tax_rule_bands`, `tax_determination_sets`, `tax_determinations`, `tax_determination_lines`, `statutory_report_definitions`, `statutory_report_boxes`, `tax_filing_obligations`, `statutory_reports`, `statutory_report_values`, `tax_returns`, `tax_return_events` | ERP product-first; ADR-0045 |
| `dotmac-work-orders` | `WorkOrder`, `WorkOrderAssignment`, `WorkOrderEvent`, `WorkOrderWorkLog`, `WorkOrderNote`, `WorkOrderEvidence` | `work_orders`, `work_order_assignments`, `work_order_events`, `work_order_worklogs`, `work_order_notes`, `work_order_evidence` | Sub product-first; ADR-0054 |

Canonical writers are equally explicit. These services accept the caller's
session, mutate and flush; they do not commit or roll back. Product adapters
authorize and translate typed facts but never maintain a parallel writer.

| State surface | Canonical writer and non-owner boundary |
|---|---|
| Approval policy revisions, votes and effective standing | `dotmac_approvals.service` is the single writer on each selected plane. A caller's guarded adapter authorizes a withdrawal and supplies actor, authority, reason and external reference; Approvals records one immutable withdrawal, generates the effective UTC time, and emits a typed event. The subject owner projects a revocation through its own guarded transition. |
| Accounting chart, periods, dimensions, journals and ledger evidence | `dotmac_accounting.service`; producers submit typed facts, while Approvals, Numbering and each subledger retain their separate decisions. |
| Analytical declaration snapshots, receipts, observations and winning points | `dotmac_analytics.service.record_batch`; `rebuild_projection` is the sole repair writer for `metric_points`; domain owners retain calculations. |
| Banking masters, observations, match allocations and reconciliations | `dotmac_banking.service`; Integrator owns provider transport and Accounting owns cash-ledger projection. |
| Controlled document identity, exact versions and document lifecycle | `dotmac_documents.service`; Files owns bytes, Approvals owns verdicts and Durable Timers owns wake-up identity. |
| Expense requests, claims, receipts, policy evidence and eligibility | `dotmac_expenses.service`; Party owns identity, Approvals owns quorum, Files owns bytes and Finance owns payable/payment state. |
| Fixed-asset books, valuation decisions and balanced consequences | `dotmac_finance.service`; the physical Assets owner and the Accounting projection remain separate typed seams. |
| Conversations, messages and read cursors | `dotmac_inbox.service`; products own subject/workforce links and consequences, while Integrator owns transport evidence. |
| Party capacities, relationships, memberships, contact evidence and external references | `dotmac_party.service`; kernel Party remains the identity owner and authorization consumes facts without treating them as grants. |
| Supplier documents, credits, liabilities and obligations | `dotmac_payables.service`; Procurement, suppliers, Approvals, Tax, Accounting and Treasury remain independent owners. |
| Payroll components, structures, calculations, liabilities and settlement coverage | `dotmac_payroll.service`; People, Tax, Banking and Accounting are ports, not imported models or alternate writers. |
| Requisitions, sourcing, bids, awards, commitments and receipt projection | `dotmac_procurement.service`; Approvals decides quorum, Inventory owns stock/receipts and Payables consumes approved commitment facts. |
| Project/task/template/dependency/assignment structure and lifecycle | `dotmac_projects.service`; products own project subjects plus finance, workforce, work-order and customer consequences. |
| Record declarations, schedules, holds, preservation, custody and disposition | `dotmac_records.service`; source domains retain meaning, Files performs physical deletion, Approvals decides verdicts and Timers schedules review. |
| Survey definitions, invitations, responses and aggregates | `dotmac_surveys.service`; products own eligibility, delivery and every subject consequence. |
| Tax policy, determinations, report snapshots, obligations and returns | `dotmac_tax.service`; `determine_tax_set` returns the ORM-free exact-Money `TaxDeterminationSetV1`/component/line contract while persistence models remain internal. Every a3 set moves once from transaction-local `building` to `sealed`, closes child insertion at that transition, and is verified by an `rv1` full-result fingerprint before replay or statutory aggregation. Immutable unsealed a2/legacy evidence fails closed rather than being backfilled or summed. Products own taxable source facts, Integrator owns authority transport and Accounting owns postings. |
| Physical-work execution rows and evidence | `dotmac_work_orders.service`; products own subjects, workforce eligibility, inventory, topology and downstream consequences. |
Core never imports `app/features` (import-linter contract). Features never
import each other (import-linter contract). Cross-feature references are
FK/UUID columns, never a Python import — e.g. `rbac`'s `PartyRoleGrant` refers
to `parties` via a composite FK, not by importing `app.features.parties`.

The package dependency graph is one-way and enforced (ADR-0006 § 2, corrected
2026-08-25): the assembly independently imports the kernel, selected modules and
`dotmac-ui`; a module may import the kernel; `dotmac-ui` imports none of them and
has only Python as a runtime dependency. The kernel imports neither `app` nor
`dotmac_ui`. This is what lets `dotmac_erp` consume the design system without
adopting the kernel. Three import-linter contracts hold it, and
`tests/architecture/test_ui_public_surface.py` additionally forbids `dotmac_ui`
importing a web framework, ORM, or templating engine.

### Model placement: core vs. feature

`Tenant`, `TenantDomain`, `Party` (+ subtype tables `PartyPerson`/
`PartyOrganization`), `Role`, `PartyRoleGrant`, `AuthSession` live in
`dotmac_kernel/models.py`; `AuditEvent` + `write_audit_event` live in
`dotmac_kernel/audit.py`. These are the models `dotmac_kernel.deps` (route guards) and
`dotmac_kernel.middleware.tenant` (the resolver) query directly — and since core
cannot import features, anything core needs to query at runtime must live in
core. `Party` (spec amendment 2026-07-17) replaced the bare `Person` model —
it's the fleet-wide identity source of truth (`party_type` person|
organization), with profile data on the subtype tables. `DomainSetting`
(`dotmac_kernel/settings_models.py`) and the spec registry + resolver
(`dotmac_kernel/settings_resolver.py`) live in core for the same reason, one
level removed: the `custom_fields` feature must call `resolve_value`
directly (the per-entity field limit), and features may never import each
other, so the shared mechanics sit in core while the `settings` feature
keeps only what nothing else needs (spec declarations, seed, router,
schemas). `CustomFieldDefinition` stays feature-local
(`app/features/custom_fields/models.py`) — nothing outside `custom_fields`
touches it. Everything not needed outside its own feature stays
feature-local: `UserCredential` (password hashes) lives in
`app/features/auth/models.py`, referencing `parties`/`tenants` by
string-form `ForeignKey`/`ForeignKeyConstraint` only. See ADR-0002 for the
full rationale — this is a deliberate deviation from "one model per feature
package." The complete model-by-model list — owner and port source-of-truth
for every model class in the repo — is the **Model provenance table** below.

## Settings resolution order + platform-row RLS design

`domain_settings` (`dotmac_kernel/settings_models.py::DomainSetting`) is keyed by
`(tenant_id, scope_kind, scope_id, domain, key)` where `tenant_id` is
**nullable**: a
`tenant_id IS NULL` row is a platform-level default, readable by every
tenant but writable only by the `platform_api` role. This is the one
tenant-scoped-ish table that deliberately does not follow the standard
"NOT NULL + single RLS policy" template (see the hard-rules exception noted
in `CLAUDE.md`):

- One expression index, `uq_domain_settings_scope`, coalesces nullable
  `tenant_id`/`scope_id` to a UUID sentinel. Postgres otherwise treats every
  `NULL` as distinct, so a conventional composite unique constraint would
  admit duplicate platform or tenant-wide rows.
- `tenant_id` and `scope_kind` form one database invariant:
  platform requires a NULL tenant; every other scope requires a tenant. The
  context-aware ORM default derives that pair. Raw SQL cannot inspect another
  column, so its server default is the safe platform/NULL shape and a tenant
  raw write must name both values. Migration `0021_setting_scope_alignment`
  repairs the legacy tenant/NULL default shape and installs
  `ck_domain_settings_scope_alignment`.
- RLS is a **split read/write policy pair**, not the single
  `USING/WITH CHECK` policy every other tenant-scoped table gets: `app_user`
  may `SELECT` a row where `tenant_id = app_current_tenant_id() OR
  tenant_id IS NULL` (own rows + platform defaults), but may only
  `INSERT/UPDATE/DELETE` where `tenant_id = app_current_tenant_id()` — never
  `NULL`. Only `platform_api` (no `BYPASSRLS`, but its own broader grants)
  writes `tenant_id IS NULL` rows. See
  `tests/test_settings_isolation.py` for the three load-bearing properties
  this buys: (a) a tenant-owned row is invisible cross-tenant, (b) a
  platform-default row is visible to every tenant, (c) a tenant session
  cannot smuggle a `tenant_id IS NULL`/other-tenant write past the policy.

**Resolution order** (`dotmac_kernel.settings_resolver.resolve_with_source`,
`resolve_value` is a thin wrapper that drops the `source`): the declared scope
chain, most specific row first (tenant row if `tenant_id` is not `None` →
platform row, `tenant_id IS NULL`) → the assembly's **profile default**
(`ProductAssemblySpec.setting_defaults`, keyed `"<domain>/<key>"`, ADR-0013) →
the `SettingSpec`'s own `default`. The environment is not in this list and is
not a source at all — ADR-0011; `env_var` is a bootstrap that produces a row
before anything resolves. A stored value that fails coercion to the spec's
`value_type`, or violates `allowed`/`min_value`/`max_value`, degrades all the
way to the spec default (not to "ignore this row", and *not* to the profile
default either) — a corrupted row can never break every caller. `source` is the
level that actually answered: the scope kind (`"tenant"`, `"platform"`, …),
`"profile"`, or `"default"`. It tells the settings admin API whether to mask a
secret's value (masked whenever a real row exists; never for the built-in
default — there's nothing to hide there).

Finer levels than `tenant` are possible — a spec resolves through the
declared scope chain (`dotmac_kernel.setting_scopes`), most specific first,
always ending at the platform row. `tenant_id` carries isolation and only
isolation; `scope_kind`/`scope_id` carry precedence.

**Environment variables are a bootstrap, never a fallback.** A spec's
`env_var` is read once, at startup, by `seed_settings_from_env` (called from
the `create_app` lifespan just before `validate_required_settings`, so a
required setting configured by environment counts as configured). It creates
the platform row when none exists and never touches one that does — so an
operator who later edits the value in the admin screen does not have it
reverted on the next restart by a stale variable in a unit file. Nothing
reads the environment at resolution time: a live env fallback would make the
answer depend on which process asked, leave the value with no history and no
owner, and make a database restore fail to reproduce it. (`dotmac_sub`
reached this rule first; the kernel has been brought to it.)

**Spec registration**: `SettingSpec` instances are declared in a feature's
own module (today only `app/features/settings/spec.py`) and registered into
the core registry via `register_specs([...])` as an import-time side
effect — importing the `settings` feature package registers them. Nothing
enforces *where* a spec is declared beyond "some feature module, at import
time" — this is the extension point other features use to add their own
settings (see `CLAUDE.md`'s Extension points section). The
no-orphan-settings architecture test (`tests/architecture/
test_no_orphan_settings.py`) fails the build if a registered key's `key`
string never appears as a literal anywhere under `app/` outside the
`settings` package and the resolver module — a spec with no reader is a
dead control an admin could "change" with zero effect.

**Extension point for feature authors**: a module declares each settings domain
on its manifest. `SettingDomainRegistry` validates writes, the database column
remains an open string, and the manifest declaration tests require every member
to be both unique and consumed. Adding a product-owned domain therefore needs
no kernel enum or CHECK migration (ADR-0008).

Write path: `PUT /settings/{domain}/{key}` → `settings/service.py::
update_setting` → `validate_spec_value` (raises `BadRequestError` on any
violation, never silently coerces on write — unlike the read-path
degradation above) → `settings_resolver.upsert_by_key` (always writes the
TENANT row; only a platform-role session can pass `tenant_id=None`) → an
audit event (`settings.update`, domain/key only — never the value, in case
it's a secret) written by the router, not the service.

## Party family + subtype RLS

`Party` (`dotmac_kernel/models.py`) is the fleet-wide identity source of truth —
`party_type` discriminates `person`/`organization`. It carries the standard
tenant-scoped template (`tenant_id NOT NULL`, composite unique
`(tenant_id, id)`, a case-insensitive partial unique index
`(tenant_id, lower(email)) WHERE email IS NOT NULL`, single `USING/WITH
CHECK (tenant_id = app_current_tenant_id())` RLS policy) plus a
`custom_fields` JSONB column (default `{}`) that custom-fields values ride
on top of.

`PartyPerson`/`PartyOrganization` (1:1 subtype profile tables, PK = FK =
`party_id`) carry **no `tenant_id` column of their own** — isolation is
inherited entirely through the FK to `parties`, enforced by an
`EXISTS`-based RLS policy of the shape:

```sql
USING (EXISTS (
  SELECT 1 FROM parties p
  WHERE p.id = party_persons.party_id
    AND p.tenant_id = app_current_tenant_id()
))
```

(see `alembic/versions/20260717_0003_party_identity.py` for the literal
policy on both subtype tables). `tests/test_party_isolation.py` is the
load-bearing proof this pattern actually holds — it's the pattern any
future subtype/detail table hanging off `parties` (or off any other
identity-shaped entity) should copy rather than adding its own `tenant_id`.

Auth credentials (`UserCredential`), RBAC grants (`PartyRoleGrant`), audit actors
(`AuditEvent.actor_party_id`), and auth sessions (`AuthSession`) all bind to
`party_id` — there is exactly one identity table for every feature to peg
to, replacing the old bare `Person` model (spec amendment 2026-07-17).

## Custom-fields value flow

Field **shape** (type, validation rules, display) is defined per-tenant in
`CustomFieldDefinition` (`app/features/custom_fields/models.py`) — a
standard tenant-scoped table (single RLS policy, same shape as `parties`).
Field **values** live on the entity's own row, in a `custom_fields` JSONB
column (e.g. `Party.custom_fields`) — riding on that row's *existing* RLS
policy rather than a separate values table with its own isolation to get
right.

The write path (`PUT /custom-fields/{entity_type}/{entity_id}/values` →
`service.py::set_values`) is **validate → merge → flag_modified**:

1. **Resolve** the entity row via `registry.resolve_entity(entity_type)` +
   `db.get(model, entity_id)` — `None` (including a cross-tenant row RLS
   hides) raises `NotFoundError`.
2. **Validate** (`validate_values`) every submitted key against that
   `entity_type`'s active `CustomFieldDefinition`s: required fields present,
   known field codes only (an unrecognized code is a caller-side error, not
   a silent drop — a deliberate gap-closure over the ERP port, see
   `service.py`'s module docstring), each value passing
   `CustomFieldDefinition.validate_value` (type-specific checks — BOOLEAN/
   DATE/DATETIME are strict, URL/PHONE/CURRENCY are documented passthrough
   pending a project-specific `validation_regex`). Any violation raises one
   `BadRequestError` joining every message — nothing is written on a
   partial failure.
3. **Merge** (partial-update semantics): `dict(row.custom_fields or {})`,
   then for each submitted key — `None` deletes the key, any other value
   overwrites it. Keys not present in the request are left untouched.
4. **`flag_modified(row, "custom_fields")`** — SQLAlchemy cannot detect an
   in-place mutation of a JSON/JSONB column's Python `dict` on its own;
   without this call the `UPDATE` never fires and the merged value is
   silently lost on flush. This is the load-bearing line in `set_values`.

This is also the **runtime-field / zero-migration** proof point: creating a
new field (`POST /custom-fields/definitions`) is a plain row insert against
an already-existing table — no Alembic migration, no deploy, no app
restart. `tests/test_custom_fields_isolation.py` plus the eye-color e2e
canary (`tests/unit/test_custom_fields_api.py`) demonstrate a field being
defined and used in the same test run with zero schema changes in between.

### Visibility flags are consumed, query-level (2b.1-T5, finding F6)

`CustomFieldDefinition` has always declared `show_in_form`/`show_in_detail`/
`show_in_list` (defaults `True`/`True`/`False`), but until this task nothing
read them — every consumer listed every active definition regardless. The
fix is a single query-level owner: `custom_fields_service.list_for_entity`
gained an optional `visible_in: Literal["form", "detail", "list"] | None`
filter that maps directly to the matching `show_in_*` column
(`visible_in="form"` → `show_in_form == True`, etc.); `None` (every
pre-existing caller) is unchanged — every definition, unfiltered. No
consumer re-implements this filtering itself; each just asks for the slice
it needs:

- The values-panel **edit form**
  (`app.features.custom_fields.web.party_values_panel`) requests
  `visible_in="form"` — only `show_in_form` fields get an input.
- The same panel's read-only **"Details" section** requests
  `visible_in="detail"`, then layers one more in-Python condition,
  `not show_in_form`, via the panel's own `_detail_only_definitions`
  helper — a field that is BOTH `show_in_form` and `show_in_detail` (the
  default for both flags, so the common case) renders its value exactly
  ONCE, in the editable form input, not a second time as a duplicate
  read-only row. This narrower "detail-only" combination is scoped to this
  one consumer, in-Python, rather than overloading `list_for_entity`'s
  established single-flag `visible_in="detail"` semantics, which other
  future callers may still want unfiltered by `show_in_form`.
- The definitions **table** (`templates/admin/custom_fields/_table.html`)
  reads `show_in_list` per-row directly, to render a "visible in lists"
  badge — a list-VIEW consumer that picks actual columns from
  `visible_in="list"` is still future work (no entity-list admin screen
  exists yet), but the flag is no longer a dead control now that this badge
  reads it.

Tests: one per flag/consumer (`tests/unit/test_custom_fields_service.py`,
`tests/unit/test_custom_fields_web.py`) plus the detail/form
non-double-render pin.

## Capability model: manifest-driven surfaces (ADR-0006 web-facet runtime)

There are two explicit module-contract generations during the migration window:

- Contract 1 is `FeatureManifest.web_routers` / `ModuleManifest.web_routers`
  plus path-based `nav`. `ModuleManifest.from_feature` selects this generation
  for every legacy feature that still declares either field. An omitted
  `ModuleManifest.contract_version` makes the same inference, so an existing
  downstream legacy manifest does not become generation 2 merely by upgrading
  the kernel. The compatibility adapter preserves absolute paths but synthesizes
  no facet or authorization policy: the assembly must explicitly declare a
  `staff_admin` facet with authentication and admission permission, or startup
  fails.
- Contract 2 is `ModuleManifest.web_surfaces: Sequence[WebSurfaceContribution]`.
  A contribution owns facet-relative named routers, route-derived navigation,
  namespaced templates/static data, supported UI contract generations and
  required browser capabilities. A contract-2 manifest cannot also author the
  legacy fields.

The assembly owns `WebFacetMount`: audience code, URL prefix, shell, named
authentication profile, optional admission permission, navigation regions,
approved pre-auth entry routes and the named login route. `WebSurfaceRegistry`
validates the complete graph before mounting: unknown facets/profiles,
incompatible UI versions, browser capabilities, overlapping prefixes, cookie
scope, route/nav/namespace collisions and unresolved entry/login routes all stop
startup.

Facet admission is a TENANT-plane decision. `mount_web_surfaces` evaluates
`WebFacetMount.admission_permission` through `authorize_party(db, tenant,
party, code)`, which needs a tenant-scoped `Party`, so only a facet whose
authentication profile declares `BrowserSecurityPlane.TENANT` ever reaches that
call. A platform profile resolves a `PlatformAdmin` and a public profile
resolves no principal at all; both take the non-tenant context dependency,
which never reads the permission. A facet declaring admission against either
plane was therefore enforcing nothing while reading as guarded — the permission
sat on the facet, `create_app` confirmed it was declared, and every request was
admitted anyway. `WebSurfaceRegistry` refuses that binding at startup. A
platform or public facet WITHOUT admission stays valid and authorizes inside
its own routes against its own principal, which is where a non-`Party`
principal's authorization belongs (ADR-0006 § 5 amendment, 2026-08-26).

The kernel's contract-v2 platform contribution uses an assembly-declared
`platform_admin` facet when one exists. During the migration window only, an
assembly with `platform_surface_enabled=True` and no such declaration receives
a kernel-owned compatibility facet bound to the existing platform-admin cookie
provider. That reproduces the pre-facet platform UI and its exact identity
boundary; it does not infer tenant permissions or provide a general facet
default. `platform_surface_enabled=False` still removes both platform auth and
UI routes.

Browser capabilities also carry their security consequences. The assembly's
provider may declare only the closed `BrowserSecurityRequirement` vocabulary;
the registry unions requirements from capabilities actually used by enabled
surfaces, and the security-header owner deterministically composes those into
the baseline CSP. Raw module directives/origins are not a contract surface, and
a raw assembly/operator CSP cannot replace an active typed requirement. Even
when the active requirement set is empty, a raw compatibility policy must retain
every strict-baseline directive and may only remove sources; a partial or wider
policy fails application construction. The baseline uses the vendored Alpine
CSP build and therefore grants neither `script-src 'unsafe-inline'` nor
`'unsafe-eval'`.

Template security governance consumes the same composition declaration: the
architecture sweep derives roots from `ProductAssemblySpec`, its installed
presentation-package directories and every v2 surface's `TemplatePackage`.
Hidden native-form CSRF proof and `| safe` discipline therefore apply to every
composed template, while every non-fragment v2 surface template must extend a
facet shell. A new audience or module cannot escape by choosing a directory
name outside `admin/**`.

The contract-v2 Template Studio canary projects SQLAlchemy rows into its
existing Pydantic `TemplateRead` / `VersionRead` contracts before rendering.
Templates therefore traverse detached scalar read models rather than a live ORM
graph. Contract-v1 screens have not yet been migrated and remain explicitly
unmonitored for this requirement.

The shared tenant and platform shells expose a skip link and focusable main
landmark. Tenant navigation publishes active-page state; its small-screen drawer
publishes expanded state, traps focus while open, restores focus when dismissed
and renders a separate visible sidebar copy. Platform navigation publishes
active-page state and wraps on narrow screens. These are reusable shell
behaviours, not a WCAG conformance claim: page-level keyboard, reflow, contrast
and assistive-technology evidence still belongs to composed browser journeys.

`mount_features` now mounts enabled API routers only. `mount_web_surfaces` mounts
both contract generations through one adapter, qualifies every route name as
`web:<facet>:<module>:<surface>:<local>`, attaches CSRF, authenticates through the
facet profile, applies tenant facet admission through `authorize_party`, and
then leaves every route's granular permission/capability dependencies intact.
Navigation reads those same stamped decisions; hiding a link never authorizes a
request.

Every composed request receives an immutable `SurfaceContext` with its facet,
surface, URL prefix, enabled-module set, filtered navigation, stylesheets and
selected UI contract. `render()` injects it per request. `install_surface_globals` and
`install_stylesheets` remain contract-1 helpers, but `create_app` resets their
fallbacks instead of installing an assembly as mutable process-global UI state.
Login `next` values are same-origin and, for a composed request, confined to
that context's facet prefix; one portal cannot use another as an arbitrary
post-login destination.

**Two independent on/off switches — do not conflate them:**

- `DISABLED_FEATURES` (`Settings.disabled_feature_set`) turns off ONE named
  feature entirely — both its `routers` and `web_routers` together, one
  feature, one switch. `DISABLED_FEATURES=web` disables the `web` package
  specifically (the admin DASHBOARD SHELL, `GET /admin`, and nothing else);
  every other feature's own `/admin/*` screens and JSON routes are
  unaffected.
- `WEB_ENABLED` (`Settings.web_enabled`, env var, default `true`) is the
  SURFACE switch: `WEB_ENABLED=false` mounts NO feature's `web_routers` at
  all (zero `/admin` routes across every feature) and also drops the
  `/static` `StaticFiles` mount (`app/main.py`) — there is no HTML UI left
  to serve assets to. Every feature's `routers` (JSON API) keeps working
  unchanged. This is the real API-only deployment mode, independent of
  which individual features are enabled/disabled via `DISABLED_FEATURES`.

**The optional-slot pattern (F5):** a feature's nav entry or an embedded
fragment must never point at a route that might not be mounted. Two
enforcement mechanisms:

1. **Nav↔routes coherence** — contract 2 validates named GET routes and their
   regions at startup. The contract-1
   `tests/architecture/test_feature_manifests.py
   ::test_nav_items_paths_exist_in_web_routers` fails the build if any
   manifest's `NavItem.path` doesn't correspond to a route actually mounted
   in that SAME manifest's `web_routers` — a stale/dead sidebar link is a
   build failure, not a 404 a user finds later.
   `test_nav_paths_coherence_detects_bogus_entry` is the sensitivity check:
   it injects a bogus nav entry and asserts the coherence test actually
   catches it (a green coherence test that can't go red proves nothing).
2. **`enabled_features`-gated fragment embeds** —
   `templates/admin/parties/detail.html` wraps its custom-fields
   values-panel embed in `{% if 'custom_fields' in enabled_features %}`;
   with `DISABLED_FEATURES=custom_fields`, the party detail page renders
   200 without the panel div (and without an htmx call to a route that no
   longer exists) instead of a broken fragment. This is THE pattern for any
   template that conditionally embeds another feature's optional UI: guard
   on `enabled_features`, never assume a feature is mounted.

Every feature that has portal pages puts them in that feature's own
`web.py` (never `router.py`). Contract-1 routers retain `/admin/...`; contract-2
routers are facet-relative and the assembly supplies the prefix. Every `web.py`
route calls the SAME `service.py` functions its JSON sibling calls (e.g.
`parties/web.py`'s edit form and `PATCH`-equivalent both call
`parties_service.update_person_party`) — one write-owner per resource, two
presentation surfaces, never a second implementation of the write.

## Admin portal (web UI)

Phase 2b added an HTML/HTMX admin portal alongside the existing JSON API —
same tenants, same services, a second thin presentation surface (see
"Capability model" above for how a feature's admin screens get mounted and
how they reach the sidebar). The deletable `web` feature package
(`app/features/web/`, `core=False`) owns only the dashboard shell
(`GET /admin`) — `DISABLED_FEATURES=web` drops that one route and nothing
else, since login/logout (`GET`/`POST /admin/login`, `POST /admin/logout`)
are owned by `auth` (a core feature) and every other feature's `/admin/*`
routes mount independently.

### Template / asset layout

```
templates/
  base.html                 <html> shell: brand-aware <title>, static asset links,
                            and the `extra_stylesheets` slot (see "Design system")
  layouts/admin.html         {% extends "base.html" %} + sidebar/topbar chrome
  components/                sidebar, topbar, form_macros, table_macros (Jinja macros)
  auth/login.html             standalone (does not extend layouts/admin.html — pre-auth)
  admin/
    dashboard.html
    parties/  rbac/  settings/  custom_fields/   one dir per feature's pages
    <feature>/_*.html          "_"-prefixed = htmx fragment, not a full page
  errors/{400,401,403,404,409,422,500,csrf}.html   branded error pages
static/
  css/src/main.css           Tailwind v4 CSS-first source (@theme/@source/@custom-variant)
  css/main.css                compiled output — gitignored, build-only (`make css-build`)
  js/{htmx,alpine}.min.js     vendored (no CDN, no node_modules at runtime)
  js/csrf.js                  CSRF header bridge (see below)
  js/components.js            small Alpine component glue

(served under the same /static mount, from the dotmac-ui package:)
  dotmac-ui/dotmac-ui-1.css   design-system tokens — COMMITTED, npm-free
  dotmac-ui/manifest.json     asset digests for non-Python consumers
```

Every `templates/admin/**/*.html` and `templates/auth/*.html` file either
`{% extends %}` a layout or is `_`-prefixed (a fragment meant to be
`{% include %}`d or returned directly to an htmx swap) —
`tests/architecture/test_web_conventions.py::test_every_admin_or_auth_template_extends_a_layout_or_is_a_fragment`.
A `GET` route that serves both a full page and an htmx fragment (e.g.
`GET /admin/parties`) branches on the `HX-Request` header: present → render
just the `_table.html` fragment; absent → render the full `index.html`,
which itself `{% include %}`s that same fragment once, so there is exactly
one template that knows how to draw the table.

Tailwind v4 is CSS-first — `static/css/src/main.css`'s `@theme` (design
tokens) and `@source` (an explicit safelist of class-name patterns the
compiler must not tree-shake away, since Jinja templates aren't a build-time
scannable source the default content-detection understands) replace the old
`tailwind.config.js` entirely. `npm run css:build` (`make css-build`, or the
Dockerfile's `css-builder` stage) compiles it; `static/css/main.css` is
gitignored — never commit it, always rebuild.

### Design system: `dotmac-ui` (ADR-0006 U1)

The portal loads a **second** stylesheet, from the `dotmac-ui` package. The two
are not variants of each other and must not be conflated:

| | `static/css/main.css` | `dotmac-ui/dotmac-ui-1.css` |
|---|---|---|
| Owner | this assembly (kernel package data) | the `dotmac-ui` package |
| Built by | Tailwind v4 CLI, via npm | pure Python, `make ui-build` |
| In git | **no** — gitignored, rebuilt | **yes** — it IS the published contract |
| Contains | compiled utility classes | role-named CSS custom properties, one `:focus-visible` rule, and published component CSS |
| Consumer needs | the v4 toolchain | nothing at all |

It loads **after** `main.css`, so its tokens and its focus-indicator rule win on
equal specificity. The package wiring is two fields in `app/assembly.py`:
`packaged_static_dirs=(dotmac_ui.static_dir(),)` layers the package's assets into
the existing `/static` mount (under any assembly file, over the kernel's), and
the first `stylesheets` entry puts the package `<link>` in `base.html` via the
`extra_stylesheets` Jinja global. The assembly-owned runtime brand URL is the
second entry, so the cascade is product CSS -> dotmac-ui defaults -> resolved
brand overrides. All entries are ignored when `WEB_ENABLED=false`.

**The kernel does not know what fills those slots.** They are anonymous
`ProductAssemblySpec` fields (kernel 0.1.0a13) — the dependency direction
forbids the kernel reaching forward to a presentation package, so the assembly
owns the composition and the kernel owns only the slot. `stylesheets` takes URLs
rather than paths for the same reason: the URL mapping is the assembly's.

**Why the artifact is committed and npm-free** (ADR-0006 D3): the published
contract is *compiled, versioned, self-hosted CSS*, so a consumer never runs the
package through its own compiler and never has to match a Tailwind major — ERP
is on v3.4, this repo and Sub are on v4, and all three link the identical file.
Committing it means a token change shows up as a CSS diff in review and an
air-gapped consumer gets working assets from a checkout. `make ui-check` (in
`make check`) and `test_committed_stylesheet_matches_a_fresh_build` fail if the
committed copy drifts from `packages/dotmac-ui/src/dotmac_ui/tokens.py`.

Tokens are named by ROLE (`--dmui-surface-primary`,
`--dmui-action-destructive-hover`), never by value; the `--dmui-` prefix exists
because Tailwind v4's `@theme` emits unprefixed `--color-*`/`--font-*` into the
same `:root`. Dark values are emitted under both `.dark` (what this portal's
Alpine store already toggles) and `[data-dmui-theme="dark"]`. The published
component surface contains the reuse-proven `empty_state` and the
audit-complete, deliberately unadopted `map_frame`; every emitted `.dmui-*`
class is derived from its typed component contract. `map_frame` owns only an
accessible canvas frame and generic ready/loading/empty/error presentation.
Provider runtime, tiles, viewport, endpoints, polling, layers, fallback lists
and domain vocabulary remain host-owned, as recorded in
`docs/inventories/map-ui-sources.md`. ADR-0006 § 5 still forbids adding a
component because markup merely looks similar, and a guard fails the build if a
selector appears without a declaration. Full contract:
`packages/dotmac-ui/COMPATIBILITY.md`.

The first product-facing cutover is the shared document canvas, tenant login,
admin layout, sidebar, topbar and toast/status layer. Those five templates use
the same semantic variables in both modes; `.dark` changes the token values,
not a parallel set of element classes, and `/branding/theme.css` moves their
primary actions through the same variables. The two-directional palette debt
therefore falls from 970 to 851. The remaining 851 occurrences are still
frozen per file and token; neighbouring forms, tables and pages retire in later
coherent slices rather than being hidden by this shell migration.

### Auth flow: cookie + bearer share one seam

`dotmac_kernel.deps.authenticate_request` is the ONE function that validates a
token (signature, expiry, session-revocation, tenant-claim match) and
resolves it to a `Party` — both the JSON API's bearer `Authorization`
header and the portal's cookie flow call it, so a security fix to token
validation lands once and covers both surfaces:

1. **Login** (`POST /admin/login`, `app.features.auth.web`) — a plain HTML
   form POST (via `hx-post`, see the CSRF section below), calling
   `auth_service.web_login` (same credential-check path `POST /auth/login`
   uses for the JSON API) and, on success, setting an `access_token` cookie
   (`HttpOnly`, `SameSite=Lax`, `Secure` iff `is_secure_request()`) instead
   of returning the token in a JSON body.
2. **Every composed portal page** receives the facet's declared authentication
   profile. The tenant profile binds `require_web_party`, which reads the
   `access_token` cookie and calls the shared `authenticate_request` seam but
   decides no authorization. `staff_admin` then requires the declared
   `web.portal.staff.access` admission permission; each v2 module route keeps
   its own granular permission guard. Contract-v1 `require_web_auth` remains a
   party/roles mapping adapter and no longer hardcodes `"admin"`.
3. **Logout** (`POST /admin/logout` — was `GET /admin/logout` until 2b.1-T5,
   finding F7: a bare `<a href="/admin/logout">` is a CSRF-exempt safe
   method, so a third-party page could force a victim's logout just by
   loading `<img src="/admin/logout">`; the topbar's logout control is now
   an `hx-post` button, routed through the same CSRF header-bridge as every
   other mutation) revokes the `AuthSession` server-side (not just clearing
   the cookie) and redirects to the login page — verified by the e2e canary
   re-submitting the revoked cookie value and getting redirected again, not
   authenticated.

### CSRF browser-route contract

`CSRFMiddleware` issues and rotates a signed, expiring double-submit token bound
to the current declared browser-session cookies. It does not infer protection
from a path or from whether a request happens to contain cookies.
`mount_web_surfaces` explicitly adds `require_csrf` to every composed browser
route; that dependency validates every unsafe method, including pre-auth login
and logout, while bearer-only API routes receive no CSRF dependency. Proof may
arrive through `X-CSRF-Token` (the htmx/`fetch` bridge in `static/js/csrf.js`)
or a native form's hidden `csrf_token` field. Both must match the signed cookie
and are compared in constant time. A protected route reached without
`CSRFMiddleware` fails loudly on safe and unsafe methods; absence of middleware
state is a configuration error, never an implicit CSRF disable switch.

Development uses the host-only `csrf_token` cookie. Production fails startup if
CSRF is disabled or `CSRF_SECRET` is a sentinel, shorter than 32 bytes, or reused
as the JWT/session-hash secret, and emits the
`Secure; Path=/; SameSite=Lax` `__Host-csrf_token` cookie. A change to an
`access_token` or `platform_access_token` session binding invalidates the old
proof and the next safe request rotates it. An explicitly cross-site
`Origin`/`Referer` or `Sec-Fetch-Site` is rejected as defence in depth; absence
of those optional headers is not treated as proof, so the signed token remains
the authority. The cookie also carries `Max-Age` equal to the signed token TTL.

### Branding pipeline: static config + per-tenant DB override

Two layers, kept deliberately separate (`dotmac_kernel.branding`'s module
docstring):

- **`get_brand()`** — deployment-STATIC identity (name, tagline, colors,
  support email, app URL). Resolution order, lowest to highest precedence:
  built-in generic defaults < `brand.json` (repo root; path overridable via
  `BRAND_CONFIG_PATH`) < same-named `BRAND_*` environment variable
  (`BRAND_NAME`, `BRAND_TAGLINE`, `BRAND_PRIMARY_COLOR`,
  `BRAND_ACCENT_COLOR`, `BRAND_SUPPORT_EMAIL`, `BRAND_APP_URL`). Cached for
  the process lifetime (`lru_cache`) and installed as a Jinja global
  (`dotmac_kernel.templating`), so every template reads `brand.name` etc.
  without a route passing it explicitly — a restart is required to pick up
  a `brand.json`/env change.
- **`load_branding(db, tenant_id)`** — the static brand above, with any
  keys present in the tenant's `ui_branding` domain setting
  (`SettingDomain.branding`, resolved via the same
  tenant→platform→spec-default resolver every other setting uses) overlaid
  on top. Per-request, not cached — a tenant admin's branding edit is live
  on the next page load, no restart. Only keys in `_KNOWN_BRAND_KEYS`
  (`name`, `tagline`, `logo_url`, `primary_color`, `accent_color` — the
  branding editor's own form fields) are merged from the stored override;
  anything else in that dict is ignored (2b final-review follow-up, resolved
  2b.1-T4/F4 — previously any key merged unchecked).
  `primary_color`/`accent_color` overrides are validated as `#RRGGBB` hex,
  falling back to the static color on a bad value.

  **A tenant cannot contribute CSS (2026-08-13, ADR-0006 D8).** `custom_css`
  was accepted, regex-sanitized on read, and rendered `| safe` into a `<style>`
  block. The field and `sanitize_branding_css` are both gone. A write naming a
  retired key is REFUSED by the shared `settings_service.update_setting`
  write owner. The generic JSON editor and settings API pass their raw values
  to it; the friendly form preserves any injected retired key when it composes
  the declared fields so the same owner can refuse it. A legacy stored value is
  inert, because `custom_css` is outside
  `_KNOWN_BRAND_KEYS` and `load_branding` therefore cannot see it. The stored
  bytes are deliberately NOT erased, and stay readable through the EXISTING
  authorized surface: the generic settings editor and `GET
  /settings/branding/ui_branding` return the stored `ui_branding` dict as-is,
  legacy keys included. So a legitimate intent can be mapped onto tokens before
  the data is deleted as a separate act, without a bespoke export API for a
  consumer that does not exist. A denylist was the wrong shape — it had to enumerate every
  dangerous CSS construct while an attacker needed one it had missed.

**Portal-wide resolution (2b.1-T4, finding F4):** `load_branding` used to
have exactly one caller (the branding editor's own preview) — every other
portal page and the login page rendered the deployment-static brand only,
so saving a tenant's branding changed nothing outside the editor. Fixed by
`dotmac_kernel.branding.get_request_branding(request, db)`: resolves
`load_branding(db, tenant.id)` (or the static `get_brand()` fallback when
`request.state.tenant` is `None` — platform hosts, unresolved-tenant error
contexts) exactly ONCE per request, memoized on `request.state.branding`.
`dotmac_kernel.templating.render()` is the single place that reads it back into
the template context — it sets `context["brand"]` from
`request.state.branding` unless the caller's own context already defines
`brand` (route-level override still wins; see that module's docstring for
the full precedence: explicit context > per-request tenant override >
static global). No route changed to pick this up.

Three call sites populate `request.state.branding` for the whole app,
independent of how many features/routers exist (seam decision documented in
`dotmac_kernel.branding`'s module docstring, including the two rejected
per-router/per-route shapes): `dotmac_kernel.web_deps.require_web_auth` (covers
every authenticated `/admin/*` page — one seam, since every such route
already depends on it) and the two pre-auth `GET`/`POST /admin/login`
routes (`app.features.auth.web`), which never reach `require_web_auth`.

Cost: one extra DB read (`resolve_value` inside `load_branding`) per
authenticated web request that didn't already need one — mitigated to
"one per request" (not one per render) by the memoization above; fully
removing it is the phase-3 settings-cache ticket
(`docs/superpowers/phase2-backlog.md`'s "Added during phase 2a execution"
section) — not needed to ship this fix.

`GET`/`POST /admin/settings/branding` (`app.features.settings.web`) still
calls `load_branding` directly for its own live-preview render (its context
explicitly sets `brand`, which is why the precedence rule above lets a
route override the per-request value) — it renders the CURRENT effective
branding, and its own render context's `brand` key SHADOWS both the
per-request tenant override and the process-global static `brand` template
global for that one response only (the static global stays available to
every other template unchanged). That route used to carry the app's ONLY
`| safe` — the `custom_css` preview — and it went away with tenant CSS.
There are now **zero** `| safe` usages in the tree; the guard stays, backed by
`test_the_safe_filter_guard_still_bites`, because the rule is about the next
one rather than the last one.

Write path: `POST /admin/settings/branding` composes the submitted
sub-fields (`name`/`tagline`/`logo_url`/`primary_color`/`accent_color`) back
into the `ui_branding` dict, preserving the presence of any injected retired
key solely so it cannot be silently dropped, and calls the SAME
`settings_service.update_setting(db, tenant, "branding", "ui_branding",
raw)` the generic per-key editor (`POST /admin/settings/{domain}/{key}/edit`)
and the JSON `PUT /settings/{domain}/{key}` API all call — one write path,
three presentation surfaces (generic web editor, friendly branding editor,
JSON API), each ending in the same audit event
(`settings.update`, domain/key only, never the value).

### Runtime brand projection: assembly adapter, generated CSS

`GET /branding/theme.css` is the Train-3 presentation seam. The stateless
`app.features.presentation` feature owns it because this is assembly
composition, not a kernel facility and not notification content:

1. `dotmac_kernel.branding.load_branding` resolves deployment and tenant data;
2. `app.features.presentation.service.project_brand_stylesheet` constructs the
   public `dotmac_ui.BrandOverride` value;
3. `dotmac_ui.render_brand_css` generates both whole-colour and `-rgb` channel
   variables for the brand and accent ramps, then re-points every dependent
   semantic role channel in light and dark mode so opacity utilities cannot
   retain the package palette while solid fills use the tenant palette;
4. the thin web adapter returns `text/css` with `Cache-Control: private,
   no-store` and non-sensitive `X-Dotmac-Brand-Projection` attribution.

The route is intentionally pre-auth so the tenant login page can load it.
`require_brand_scope` accepts a resolved tenant or the exact platform root;
unknown hosts fail closed. The platform scope receives an empty stylesheet
because the platform pages share `base.html` but have no tenant brand. It is
linked after dotmac-ui's compiled defaults, so that empty response leaves the
package palette in force rather than inventing a second default. Every response
is `private, no-store` and `Vary: Host`. Resolver/generator exceptions and
contrast warnings return the same empty fallback at 200; logs contain only the
error type or warning count, never colour inputs or a rendered brand payload.
The route emits no raw tenant CSS, URL, selector input, inline `<style>`, or
cross-origin allowance.

`logo_url` is not emitted by this CSS route and still has no render consumer.
A future logo slice must establish the managed, same-origin asset contract
before making that stored field visible; accepting an arbitrary external image
URL here would conflate token projection with asset authority.

Template Studio is a downstream content authoring/rendering module. It may
eventually receive a resolved brand as typed render context, but it does not own
brand precedence, token generation, stylesheet delivery, theme selection,
consent, channel choice, delivery, or document generation.

### Display settings: tenant timezone + date/datetime formats

Three specs registered on a new `SettingDomain.display`
(`app/features/settings/spec.py`), resolved through the same
tenant→platform→spec-default resolver every other setting uses — no
dedicated screen or bespoke storage; they auto-appear in the registry-driven
`/admin/settings` index like any other spec:

- `timezone` (string, default `"UTC"`) — an IANA zone name.
- `date_format` (string, default `"%Y-%m-%d"`) — a strftime pattern.
- `datetime_format` (string, default `"%Y-%m-%d %H:%M"`) — a strftime
  pattern.

**Write-loud / read-degrade validator split.** `SettingSpec` gained a new
field, `validator: Callable[[object], None] | None`, run after
type-coercion/`allowed`/range checks. The two call sites that consult it
behave in deliberately OPPOSITE ways for the SAME check:

- **Write path** — `settings_resolver.validate_spec_value` runs the
  validator LAST and lets its `ValueError` propagate as a `BadRequestError`
  (a clean 400, whether the write came from the JSON `PUT
  /settings/{domain}/{key}` API or the generic admin editor). An admin
  typing `Foo/Bar` into `date_format` (no `%` directive, so
  `_validate_strftime` raises before even calling `strftime`) or an unknown
  zone name into `timezone` (`_validate_timezone` — `ZoneInfo(...)` raising
  `ZoneInfoNotFoundError`) gets rejected before anything is written.
- **Read path** — `settings_resolver.resolve_with_source` (which
  `resolve_value` delegates to) catches the SAME `ValueError` and silently
  degrades to the spec default, `source="default"` — same fallback
  treatment as a coercion failure or an `allowed`-set miss. A row that
  passed validation at write time but is later corrupted (a raw DB edit, a
  future migration that reuses the column) or a zone whose tzdata went
  missing from the runtime image can never surface as a validation error
  mid-render; it just silently reverts to UTC / the default format string.

This asymmetry is intentional, not an inconsistency: a write is a single
request the caller can retry with better input, so it fails loud; a read
happens on every page render for every user of that tenant, so it must
never be the thing that turns a stored-data problem into a 500.

**Per-request seam (mirrors branding).** `dotmac_kernel.display.DisplaySettings`
(`timezone: ZoneInfo`, `date_format`, `datetime_format`) is resolved by
`get_request_display(request, db)` at most once per request and memoized on
`request.state.display` — the identical shape to
`request.state.branding`/`get_request_branding` above, including the same
single warming call site: `dotmac_kernel.web_deps.require_web_auth` (every
authenticated `/admin/*` page). `load_display` additionally wraps the
resolved timezone string in `ZoneInfo(...)` with its own
try/except-to-`_UTC` fallback — belt-and-braces alongside the resolver's own
validator-driven degrade, covering the case where a value that validated
fine at write time (tzdata present then) can't be loaded at read time
(tzdata missing now).

**Filter fallback invariant.** Templates never read `request.state.display`
directly; they consume it ONLY through the two Jinja filters registered in
`dotmac_kernel.templating` — `local_datetime` and `local_date` (`@pass_context`,
so they can reach `request.state` without the caller threading it through).
Both call a shared `_context_display(context)` helper that returns
`request.state.display` if the current render already warmed it, or
`default_display()` (spec defaults, UTC) if not — a render that never went
through `require_web_auth` (an error page, a pre-auth page) still gets a
formatted timestamp, never an `AttributeError`/`UndefinedError`. This is the
one and only consumption point: `tests/architecture/test_web_conventions.py
::test_timestamp_renders_go_through_local_filters` fails the build on any
Jinja expression referencing a `*_at`-named attribute that doesn't also
apply one of these two filters — see CLAUDE.md's hard-rules entry.

**Migration note (data loss on downgrade).** `alembic/versions/
20260718_0006_display_setting_domain.py` widens the
`ck_domain_settings_domain` CHECK constraint from `('auth', 'audit',
'branding', 'custom_fields')` to add `'display'`. Its `downgrade()` DELETES
every `domain_settings` row with `domain = 'display'` before restoring the
narrower constraint (any surviving row would violate it) — a real,
documented data-loss-on-downgrade: rolling back this migration on a
database with tenant-customized timezones/formats permanently discards
those overrides, silently reverting every tenant to UTC/spec-default
formatting with no way to recover the deleted rows short of a backup
restore.

**API boundary.** The JSON API is deliberately untouched: every response
stays ISO-8601 UTC, unchanged before and after this feature. Display
formatting is a web-portal presentation concern only; API consumers do
their own localization.

### Cross-feature UI composition (values-panel pattern)

See CLAUDE.md's Extension points entry for the rule; concretely: the party
detail page needs to show/edit a party's custom-field values, but `parties`
may never import `custom_fields`. `custom_fields/web.py` owns
`GET`/`POST /admin/custom-fields/party/{party_id}/values-panel` and the
partial they render (`templates/admin/custom_fields/_values_panel.html`);
`templates/admin/parties/detail.html` references only the URL
(`hx-get=".../values-panel" hx-trigger="load"`) — composition happens
entirely in the browser via htmx's lazy-load-on-render, zero Python import.
The panel's own form posts back to the SAME web route (not the JSON API's
`PUT /custom-fields/{entity_type}/{entity_id}/values` — an htmx form always
sends `Accept: text/html`, and the JSON route would still return
`application/json` regardless, which htmx would swap in as literal text),
which calls the same `custom_fields_service.set_values` the JSON API uses.

### Error negotiation: branded HTML with a JSON fallback

`dotmac_kernel.errors._negotiate` is the single JSON-vs-HTML decision point for
every error response (FastAPI exception handlers and the CSRF/tenant/
rate-limit ASGI middleware all route through it). Rule: a request "prefers
HTML" iff `"text/html" in request.headers["accept"]` — htmx sends
`Accept: text/html, */*`, so htmx error responses get the branded page too
(a valid swap target), while a JSON API client (`Accept: application/json`)
always gets the byte-identical envelope
(`{"code", "message", "details", "request_id"}`) unchanged from the
API-only phase. Every status this app has a dedicated template for
(400/401/403/404/409/422/500, plus a special `csrf_failed` page regardless
of its 403 status) renders that template with exactly the envelope's
`code`/`message`/`request_id` fields; a status outside that map still gets
a branded page via the `>=500`/else fallback — never a raw stack trace or
blank page. **Fallback**: if `render_error` itself raises (a broken
template, a missing asset during render), `_negotiate` catches it, logs
`"Error-page render failed; falling back to JSON envelope"`, and returns
the plain JSON envelope instead — an error page can never itself 500 an
error response into an unhandled crash.

### `/static` and `/health` bypass (recap)

Both bypass `TenantResolverMiddleware` entirely before any DB query — see
"Static-asset bypass" and "Health bypass" above (unchanged by the portal
work, listed here for the reader looking for portal-adjacent behavior in
one place).

## Web-portal module provenance

Same convention as the model provenance table below — owner and port
source-of-truth for the modules phase 2b introduced. "ST" = `dotmac_starter`
(the pre-consolidation single-tenant starter), "SUB" = `dotmac_sub`,
"native" = no upstream port.

| Module | Purpose | Port SoT |
|---|---|---|
| `dotmac_kernel/templating.py` | Jinja2 environment + `render()`, `static_asset_url` cache-busting | ST (`app/templates.py::_asset_version`/`_static_asset_url`); the `brand`/branding-DB-override wiring is native to this phase |
| `dotmac_kernel/branding.py` | `get_brand()` (static) + `load_branding()` (DB overlay) + `reject_retired_brand_keys` | SUB (`app/services/branding_config.py::get_brand`) for the static layer; ST (`app/services/branding.py::get_branding`) for the DB overlay, adapted from ST's single-tenant "one row, no tenant_id" model to this app's tenant-scoped resolver. ST's `sanitize_branding_css` was ported and then RETIRED 2026-08-13 with the `custom_css` field it existed for (ADR-0006 D8) |
| `dotmac_kernel/web_deps.py` | `require_web_auth`, `WebAuthRedirect`, `safe_next_url`, `is_secure_request` | ST (`app/web/deps.py`), routed through this app's `authenticate_request` shared seam (native adaptation — ST had no bearer/cookie seam to share) |
| `dotmac_kernel/identity.py` | `normalize_email`, `person_display_name` — the single-owner Party-invariant helpers | native (closes the SOT gap tracked from 2a-T6/T7; no upstream port — see "Known dual-writer: Parties" below) |

## Model provenance table

Every model class in `app/` (ORM `Base` subclasses — `grep -rn "class .*Base"
app/` to re-enumerate; excludes Pydantic `BaseModel`/`BaseSettings` schema
classes, which aren't persisted tables), its owner (`core` | the feature
package name), and its port source-of-truth. "native" means designed for
this repo, no upstream port. This is criterion 1 of the SOT-complete
criteria (`docs/superpowers/specs/2026-07-17-starter-consolidation-design.md`)
made concrete — every model has exactly one declared owner.

| Model | Table | Owner | Port SoT |
|---|---|---|---|
| `Tenant` | `tenants` | core | native (dotmac_starter_mt, ADR-0001) |
| `TenantDomain` | `tenant_domains` | core | native (dotmac_starter_mt, ADR-0001) |
| `Party` | `parties` | core | native (spec amendment 2026-07-17; supersedes the earlier bare `Person`, which was `dotmac_starter`-derived) |
| `PartyPerson` | `party_persons` | core | native (spec amendment 2026-07-17) |
| `PartyOrganization` | `party_organizations` | core | native (spec amendment 2026-07-17) |
| `Role` | `roles` | core | dotmac_sub (`app/models/rbac.py`, tenant-adapted) |
| `PartyRoleGrant` | `party_role_grants` | core | dotmac_sub (`app/models/rbac.py::PersonRole`, tenant-adapted + renamed for Party) |
| `AuthSession` | `auth_sessions` | core | dotmac_sub (`app/models/auth.py`, tenant-adapted) |
| `AuditEvent` | `audit_events` | core | dotmac_sub (`app/models/audit.py`, tenant-adapted) |
| `DomainSetting` | `domain_settings` | core | dotmac_starter (`app/models/domain_settings.py`, tenant-adapted), with `CheckConstraint` restored from dotmac_sub |
| `CommunicationSuppression` | `communication_suppressions` | core | dotmac_sub (`app/models/notification.py::CommunicationSuppression`, tenant-adapted with RLS; canonical channel identity and conflict-safe idempotency added by the kernel) |
| `CommunicationDelivery` | `communication_deliveries` | core | dotmac_sub (`app/models/notification.py::NotificationDelivery`) for the receipt shape; stable dispatch identity and the bounce/complaint→consent feedback loop are native kernel behavior |
| `UserCredential` | `user_credentials` | core | dotmac_sub (`app/models/auth.py`, tenant-adapted; `email` column dropped 2b.1-T3 — see "Auth credentials" ownership row and the F2 resolution note below). PORT-DELTA (control-plane security Task 2): moved from the `auth` feature to core — atomic tenant provisioning (`tenants` feature) must create the owner credential and features never import each other, so the model joined the other identity models under ADR-0002's placement rule; hashing/verification stays in `dotmac_kernel.security` |
| `ExternalIdentityBinding` | `external_identity_bindings` | core | dotmac_erp (`app/models/auth.py::FederatedIdentity` — the `issuer`/`subject`/`is_active`/`last_authenticated_at` shape, its written contract and its no-auto-provision refusal) with named dotmac_sub deltas (`app/models/auth.py::AuthenticationBinding`'s binding-as-discriminator → `provider_binding`; its CHECK-forced evidence pair → `bound_by`/`bind_reason`). PORT-DELTA: `tenant_id` + composite uniques + FORCEd RLS, which NEITHER source has — ERP's table has no tenant column so its `(issuer, subject)` uniqueness is global across every organization, and Sub's migration 527 declares `- no NOT NULL, no RLS`. Core under ADR-0002's placement rule: the same cross-feature identity family as `UserCredential`. Sources: `docs/inventories/external-identity-sources.md` |
| `PlatformAdmin` | `platform_admins` | core | native (control-plane security Task 1, ADR-0004) — platform catalog table: no `tenant_id`, no RLS, GRANT `platform_api`/`app_admin` only, REVOKEd from `app_user` |
| `PlatformSession` | `platform_sessions` | core | same grant model as `platform_admins` (control-plane security Task 1, ADR-0004) |
| `PlatformAuditEvent` | `platform_audit_events` | core | native kernel platform-plane audit trail (`platform_audit_log.v1`): no tenant column/RLS, `app_user` fully revoked, online `platform_api` limited to `SELECT`+`INSERT`; offline `app_admin` retains migration/retention authority. The nullable `actor_admin_id` FK uses `ON DELETE SET NULL`, so durable actor attribution is not yet equivalent to tenant audit's snapshot contract. |
| `CustomFieldDefinition` | `custom_field_definitions` | custom_fields | dotmac_erp (`app/models/finance/automation/custom_field.py`, generalized: string `entity_type` registry instead of a finance-only enum, `tenant_id` instead of `organization_id`) |
| `TenantAppliedLicence` | `tenant_applied_licences` | licensing | native (WS8 reference receiver, assembly migration `a002`) — the receiver-owned durable replay record the kernel verifier deliberately does not store; one row per `(tenant_id, licence_id)` lineage, upserted on each applied version |
| `TenantRevocationList` | `tenant_revocation_lists` | licensing | native (WS8 revocation import, assembly migration `a003`) — the last imported list version + the revoked set, one row per tenant. Persisted (not just applied) because the set is fed into every subsequent `verify_licence` offline; accepted imports must be a SUPERSET of the stored set, since a well-ordered newer list that omits an id is silent un-revocation |
| `Offer` / `PlatformOffer` | `mod_subscriptions.offers` / `platform_offers` | `dotmac-subscriptions` optional module | Stable recurring-commercial offer identity. The tenant and platform planes share behavior but never rows; product capability, service and provider semantics remain in adopter-owned links. |
| `OfferVersion` / `PlatformOfferVersion` | `mod_subscriptions.offer_versions` / `platform_offer_versions` | `dotmac-subscriptions` optional module | Immutable effective-dated published offer snapshot with source and command provenance; withdrawal is terminal evidence, never an in-place rewrite. |
| `OfferVersionPrice` / `PlatformOfferVersionPrice` | `mod_subscriptions.offer_version_prices` / `platform_offer_version_prices` | `dotmac-subscriptions` optional module | Exact declared-scale pre-tax price component beneath one immutable offer version. Charge-model codes come from the assembly's declaration registry. |
| `SubscriptionContract` / `PlatformSubscriptionContract` | `mod_subscriptions.subscription_contracts` / `platform_subscription_contracts` | `dotmac-subscriptions` optional module | Stable contract identity keyed to an opaque adopter source. It owns recurring-commercial agreement identity, not customer, service, invoice or access state. |
| `SubscriptionContractVersion` / `PlatformSubscriptionContractVersion` | `mod_subscriptions.subscription_contract_versions` / `platform_subscription_contract_versions` | `dotmac-subscriptions` optional module | Immutable effective-dated cadence, collection timing, proration and rating-policy evidence. Supersession and ending are explicit terminal transitions. |
| `SubscriptionContractLine` / `PlatformSubscriptionContractLine` | `mod_subscriptions.subscription_contract_lines` / `platform_subscription_contract_lines` | `dotmac-subscriptions` optional module | Stable line lineage with exact price, product-link reference, declared charge/source vocabulary and money-free entitlement intent. |
| `RecurringChargeOccurrence` / `PlatformRecurringChargeOccurrence` | `mod_subscriptions.recurring_charge_occurrences` / `platform_recurring_charge_occurrences` | `dotmac-subscriptions` optional module | One replayable natural-identity occurrence with exact pre-tax amount, period/coverage and complete rating provenance. It transactionally stages `RatedObligationOutputV1`; an assembly translates that fact to Billing and separately correlates the occurrence ID to Billing's returned ID. Timer generation is provenance, not Billing identity. |
| `SubscriptionBillingArrangement` / `PlatformSubscriptionBillingArrangement` | `mod_subscriptions.subscription_billing_arrangements` / `platform_subscription_billing_arrangements` | `dotmac-subscriptions` optional module | Effective-dated approval NOT to collect a strictly positive contracted line price. Mandatory end date, positive approved ceiling, snapshotted approval policy, open declared reason code, sponsor/cost-centre evidence and approval/revocation command provenance. Terms are frozen by trigger; `active -> revoked` is the only permitted update, and a new contract version for a contract with an open arrangement is refused. |
| `SubscriptionBillingGrant` / `PlatformSubscriptionBillingGrant` | `mod_subscriptions.subscription_billing_grants` / `platform_subscription_billing_grants` | `dotmac-subscriptions` optional module | Append-only exact non-cash evidence for one approved service period, bound to one recurring occurrence. One CHECK relates the contracted amount, the approved ceiling and the foregone amount, so a zero-price concealment and an over-cap grant are both unrepresentable. It stages `NonCashGrantOutputV1`; entitlement, billing anchor, invoice suppression and sponsor/expense posting stay with their owners. |
| `BillingAccount` / `PlatformBillingAccount` | `mod_billing.billing_accounts` / `platform_billing_accounts` | `dotmac-billing` optional module | Per-currency serialization identity only; contains no mutable balance. Tenant/platform counterparts share behavior, never rows. |
| `RatedObligation` / `PlatformRatedObligation` | `mod_billing.rated_obligations` / `platform_rated_obligations` | `dotmac-billing` optional module | Immutable accepted rated occurrence with opaque subject/service and verified service-period evidence; changed input under one natural key conflicts. A pre-document correction appends exactly one same-account successor; documented obligations use credit notes. Database relationships enforce the account and correction boundary. |
| `BillingDocument` / `PlatformBillingDocument` | `mod_billing.documents` / `platform_documents` | `dotmac-billing` optional module | Draft/issued invoice and credit-note meaning; issuance freezes number, due-date basis, parties, payment instructions, profile, locale and presentation-asset reference. Coverage is not lifecycle. |
| `DocumentLine` / `PlatformDocumentLine` | `mod_billing.document_lines` / `platform_document_lines` | `dotmac-billing` optional module | Exact line amounts and price provenance; frozen structurally with the issued document. |
| `DocumentEvent` / `PlatformDocumentEvent` | `mod_billing.document_events` / `platform_document_events` | `dotmac-billing` optional module | Append-only issuance/void evidence; corrections append and never rewrite the issued document. |
| `ConfirmedSettlement` / `PlatformConfirmedSettlement` | `mod_billing.confirmed_settlements` / `platform_confirmed_settlements` | `dotmac-billing` optional module | Independently confirmed, provider-neutral kernel-Money evidence keyed by source settlement identity and fingerprint. |
| `PostingGroup` / `PlatformPostingGroup` | `mod_billing.posting_groups` / `platform_posting_groups` | `dotmac-billing` optional module | Immutable operational-receivable mutation group and monotonic per-account source version. Refund, chargeback and reversal are movements that append and may reopen; none is a position state. |
| `PostingEffect` / `PlatformPostingEffect` | `mod_billing.posting_effects` / `platform_posting_effects` | `dotmac-billing` optional module | Exact signed effect in one of three distinct lanes: receivable, available credit or prepaid funding. |
| `AllocationEffect` / `PlatformAllocationEffect` | `mod_billing.allocation_effects` / `platform_allocation_effects` | `dotmac-billing` optional module | Internal immutable settlement→document allocation/correction detail; intentionally not a published peer contract. |
| `AppliedTaxSnapshot` / `PlatformAppliedTaxSnapshot` | `mod_billing.applied_tax_snapshots` / `platform_applied_tax_snapshots` | `dotmac-billing` optional module | Immutable source-supplied tax treatment, jurisdiction, policy version, rate and exact basis/amount; no hardcoded jurisdiction or return ownership. |
| `AppliedFxSnapshot` / `PlatformAppliedFxSnapshot` | `mod_billing.applied_fx_snapshots` / `platform_applied_fx_snapshots` | `dotmac-billing` optional module | Immutable observation identity/version, exact rate, purpose, instants, rounding and provenance; no FX provider client. |
| `PartyTaxIdentitySnapshot` / `PlatformPartyTaxIdentitySnapshot` | `mod_billing.party_tax_identity_snapshots` / `platform_party_tax_identity_snapshots` | `dotmac-billing` optional module | Seller/customer tax identity frozen for one document; an imported value never mutates a party owner. |
| `InvoiceDocumentFact` / `PlatformInvoiceDocumentFact` | `mod_billing.invoice_document_facts` / `platform_invoice_document_facts` | `dotmac-billing` optional module | Immutable typed invoice presentation fact and semantic digest emitted to the separate rendering owner. |
| `DocumentArtifact` / `PlatformDocumentArtifact` | `mod_billing.document_artifacts` / `platform_document_artifacts` | `dotmac-billing` optional module | Append-only official relation from fact version/media type to opaque Files UUID plus renderer/byte provenance. Initial record is structurally idempotent by fact/version/medium; physical repair names the exact current row, appends its replacement and preserves supersession evidence. Billing stores no bytes. |
| `AccountingFact` / `PlatformAccountingFact` | `mod_billing.accounting_facts` / `platform_accounting_facts` | `dotmac-billing` optional module | Immutable typed operational effects for ERP intake; no account code, journal, period or GL state. |
| `ReceivablePositionFact` / `PlatformReceivablePositionFact` | `mod_billing.receivable_position_facts` / `platform_receivable_position_facts` | `dotmac-billing` optional module | Immutable account/currency `ReceivablePositionV1`: kernel Money, three separate financial lanes, source authority distinct from projection mode, completeness and Billing-owned aggregate financial state. It never borrows one invoice's service/due identity. |
| `ReceivableExposureFact` / `PlatformReceivableExposureFact` | `mod_billing.receivable_exposure_facts` / `platform_receivable_exposure_facts` | `dotmac-billing` optional module | Immutable invoice-grained `ReceivableExposureV1`: one exposure identity with subject/service, collection timing, service period, due-date evidence, collectible amount and Billing-owned financial state. This is the sole Billing fact an assembly may translate to Collections' observation. |
| Collections policy rows | `mod_coll.collection_policies`, `collection_policy_versions`, `collection_policy_steps` and their `platform_*` mirrors | `dotmac-collections` optional module | Immutable policy/version/step evidence on independently selectable tenant and platform planes. Each step owns its notice purpose or action/effect scope, receipt gate and retry offsets. Collections consumes `ReceivableObservationV1`, never owns or imports Billing's position. |
| Collections case and attempt rows | `mod_coll.collection_cases`, `collection_case_exposures`, `collection_case_transitions`, `collection_step_attempts`, `collection_reconciliations` and their `platform_*` mirrors | `dotmac-collections` optional module | One case lifecycle over tenant FORCE-RLS rows or platform rows with no tenant column/RLS and complete `app_user` revocation. `CollectionCaseService` alone schedules/cancels the exact timer identity and turns a current neutral wake into a freshly reread policy decision. Unknown due dates, incomplete or shadow observations fail closed; no FK crosses planes. |
| Collections arrangement/grace/notice/action rows | `mod_coll.payment_arrangements`, `payment_arrangement_exposures`, `payment_arrangement_installments`, `payment_arrangement_settlement_receipts`, `collection_grace_grants`, `collection_notice_requests`, `collection_notice_receipts`, `collection_action_requests`, `collection_action_receipts` and their `platform_*` mirrors | `dotmac-collections` optional module | Scope-explicit decision evidence only; no settlement, allocation, delivery, financial-resolution or product-access authority. The selectable platform path resolves ADR-0020 A2's former implementation conflict without claiming a product cutover. |
| `TenantTicket` | `mod_tkt.tickets` | `dotmac-ticketing` optional module | Tenant-plane product-neutral lifecycle record, product-first from Sub's authoritative support lifecycle after the fleet inventory separated standard status from product reason. Forced RLS; each adopter owns a separate installation and only local workflow rows (ADR-0023/0024). |
| `TenantTicketComment` | `mod_tkt.ticket_comments` | `dotmac-ticketing` optional module | Tenant-plane comment trail owned with its local ticket; never a cross-application conversation store. |
| `PlatformTicket` | `mod_tkt.platform_tickets` | `dotmac-ticketing` optional module | Platform-plane form of the same persistence-free lifecycle for a control-plane installation: no tenant column/RLS, platform grants, `app_user` revoked (ADR-0023). |
| `PlatformTicketComment` | `mod_tkt.platform_ticket_comments` | `dotmac-ticketing` optional module | Platform-plane comment trail owned with its vendor-support ticket; no cross-plane or cross-application FK. |
| `TenantStoredFile` | `mod_files.stored_files` | `dotmac-files` optional module | Tenant plane: product-first port of Sub's provider/staged lifecycle, ERP's document/image policy coverage and CRM's content-spoofing canaries; forced RLS and required `TenantScope` (ADR-0022/0023; [`files-sources.md`](inventories/files-sources.md)). The a3 lineage supports explicit TENANT and TENANT+PLATFORM installations; ERP then Academy are the first tenant cutovers, and ERP E8 plus the deferred six-module cohort still gate source-product retirement. |
| `PlatformStoredFile` | `mod_files.platform_stored_files` | `dotmac-files` optional module | Platform plane over the same persistence-free physical engine: no tenant column or RLS, platform grants, and `app_user` revoked. Vendor CP is candidate cutover 3 through a licensing-owned exact-bundle relation; no product tenant is created and no consumer is claimed yet (ADR-0023). |
| `ImportRun` | `mod_imports.import_runs` | `dotmac-imports` optional module | Tenant plane: product-first port of Sub's run lifecycle and one-shot dry-run→apply promotion, joined to ERP's decoding/alias/preview mechanism; forced RLS and a tenant-composite identity neither source had (ADR-0025; [`imports-sources.md`](inventories/imports-sources.md)). The input is an opaque `dotmac-files` id plus its SHA-256, not an inline payload. Validation and apply independently verify immutable bytes and advance either the ordinary run checkpoint or the bounded partition ledger. ERP then Sub are the candidate cutovers; CRM is inventory evidence only and is not revived. ERP E8 still gates source-product retirement. |
| `ImportRunRow` | `mod_imports.import_run_rows` | `dotmac-imports` optional module | One minimised outcome per input line — `ok | error | skipped`, a canonical row fingerprint, bounded typed safe error detail, and the domain applier's opaque result. Mapped row values and raw exception text are not retained. Carries NO foreign key into a domain table: Sub's shared row table welded `payment_id` into the ledger, and the reference runs the other way here (ADR-0025 § 3). |
| `ImportPartition` | `mod_imports.import_partitions` | `dotmac-imports` optional module | One immutable `dotmac-files` partition identity, contiguous source-row range, byte size and SHA-256 plus an expiring opaque worker claim and completion checkpoint. A worker verifies the entire bounded artifact before any domain call; a stale token cannot settle, and promotion clones the exact validated plan. It stores no row values and has no cross-module FK. |
| `ContentPlan` | `mod_content.content_plans` | `dotmac-content` optional module | Tenant editorial planning identity, text, guarded lifecycle and optional date range, product-first from Mkt `Campaign` and deliberately renamed to keep outbound campaign execution with `dotmac-campaigns`. Backoffice owns actor authorization; `created_by_ref` is opaque ([content dossier](inventories/content-extraction-dossier.md)). |
| `ContentItem` / `ContentVariant` | `mod_content.content_items`, `content_variants` | `dotmac-content` optional module | Canonical title/body, editorial `draft`/`ready`/`archived` state, calendar placement and open provider-neutral authored variants. Publication requests, targets and outcomes are not content state and move through immutable `ContentSnapshotV1` values to the publishing owner. |
| `ContentPlanCreative` / `ContentItemCreative` | `mod_content.content_plan_creatives`, `content_item_creatives` | `dotmac-content` optional module | Ordered role/caption/alt metadata around opaque `file_ref` UUIDs. `dotmac-files` owns stored bytes and lifecycle; no sibling import or foreign key crosses that ownership boundary. |
| `PublicationRelease` | `mod_publishing.publication_releases` | `dotmac-publishing` optional module | One tenant publication intent with an immutable, digested snapshot, requested delivery time and actor/source provenance held as opaque references. Editorial content and site revisions remain with their source owners; Backoffice owns authorization and target-selection policy ([publishing dossier](inventories/publishing-extraction-dossier.md)). |
| `PublicationDelivery` | `mod_publishing.publication_deliveries` | `dotmac-publishing` optional module | One selected opaque target per release and its normalized local delivery state. A target reference identifies an Integrator binding without importing its registry or storing provider, credential, endpoint or channel vocabulary. |
| `PublicationAttempt` / `PublicationObservation` | `mod_publishing.publication_attempts`, `publication_observations` | `dotmac-publishing` optional module | Monotonic attempt evidence joined to one transactional outbox intent, plus immutable receipt-deduplicated normalized outcomes. Integrator owns connector execution, raw transport evidence, retry/checkpoints and remote systems; publishing derives explicit partial, published, failed or cancelled aggregate state from local observations. |
| `Site` / `Page` | `mod_sites.sites`, `pages` | `dotmac-sites` optional module | Tenant site and stable page identity. Site archive is terminal; Backoffice owns actor authorization. Landing routes and product templates are consumers or separate application presentation, not competing site owners ([sites dossier](inventories/sites-extraction-dossier.md)). |
| `PageRevision` | `mod_sites.page_revisions` | `dotmac-sites` optional module | Append-only page title/body, SEO and opaque ordered file/form references. Files and forms retain their independent lifecycles and no sibling-module foreign key or import crosses the boundary. |
| `SiteRevision` / `SiteRevisionPage` | `mod_sites.site_revisions`, `site_revision_pages` | `dotmac-sites` optional module | Immutable complete local website snapshot plus exact page-revision membership, routes, navigation, redirects and one guarded ready revision. `SiteReleaseV1` is usable locally; publishing owns later remote intent/outcomes and Integrator owns hosting transport (ADR-0035). |
| `NodeDefinition` | `mod_mediaobs.node_definitions` | `dotmac-media-observations` optional module | Tenant-scoped versioned external-node vocabulary, product-first from Mkt's hierarchy shape but open to connector declarations rather than a provider enum (ADR-0034). |
| `MetricDefinition` | `mod_mediaobs.metric_definitions` | `dotmac-media-observations` optional module | Tenant-scoped versioned metric code with explicit value type, unit, semantic and `provider_reported` origin. |
| `ObservationEnvelope` | `mod_mediaobs.observations` | `dotmac-media-observations` optional module | Append-only domain identity, normalized fingerprint, source instant, first receipt instant, normalization revision and optional restatement link. Identity is global across fact kinds within its tenant/installation/source scope. |
| `ObservationReceipt` | `mod_mediaobs.observation_receipts` | `dotmac-media-observations` optional module | Append-only opaque transport-receipt provenance with its distinct receipt instant; reusing one receipt identity with a changed instant or observation is a conflict. The module never dereferences or replaces Integrator evidence. |
| `EntityFact` | `mod_mediaobs.entity_observations` | `dotmac-media-observations` optional module | Append-only provider-reported entity name/state/disposition and aggregate properties. Exact Decimal configuration values use a private type-preserving JSON encoding and are restored on public reads. Archive/deletion is observed state, not destructive local deletion. |
| `HierarchyFact` | `mod_mediaobs.hierarchy_observations` | `dotmac-media-observations` optional module | Append-only reported parent edge. Missing parents and cycles remain visible drift rather than silently re-rooting the child. |
| `MetricPeriod` | `mod_mediaobs.metric_periods` | `dotmac-media-observations` optional module | Canonical append-only half-open period, non-overlapping for one installation/source/account/entity/versioned metric series. |
| `MetricFact` | `mod_mediaobs.metric_observations` | `dotmac-media-observations` optional module | Append-only typed provider claim. Counts remain integer; exact money retains decimal amount, currency, minor-unit scale and integer minor units; conversion claims are never authoritative attribution or revenue. |
| `CurrentEntity` | `mod_mediaobs.current_entities` | `dotmac-media-observations` optional module | Disposable deterministic effective-entity projection rebuilt from immutable source time/restatement ordering. |
| `CurrentHierarchy` | `mod_mediaobs.current_hierarchy` | `dotmac-media-observations` optional module | Disposable effective-edge projection with explicit missing-child, missing-parent or cycle drift code. |
| `CurrentMetric` | `mod_mediaobs.current_metrics` | `dotmac-media-observations` optional module | Disposable effective metric-period pointer; the full value and provenance remain in immutable rows. |
| `ReconciliationEvidence` | `mod_mediaobs.reconciliation_evidence` | `dotmac-media-observations` optional module | Append-only preview/repair evidence recording actor, reason, drift count and before/expected digests. |
| `Campaign` / `CampaignRevision` / `CampaignStep` | `mod_campaigns.campaigns`, `campaign_revisions`, `campaign_steps` | `dotmac-campaigns` optional module | Tenant-only provider-neutral campaign identity and its immutable active execution plan. Product audience, financial and sender business rules are typed inputs; Template Studio and Durable Timers remain assembly-bound owners (ADR-0056; [`campaigns-sources.md`](inventories/campaigns-sources.md)). |
| `CampaignAudience` / `CampaignRecipient` / `CampaignConsentReceipt` | `mod_campaigns.campaign_audiences`, `campaign_recipients`, `campaign_consent_receipts` | `dotmac-campaigns` optional module | Immutable source-versioned audience and delivery snapshots plus observations of the kernel consent owner's decision at audience, delayed-step and final-delivery gates. They do not become Party/customer or consent-policy records. PII carries an explicit deadline and can only move to the database-enforced scrubbed form after sending begins. |
| `CampaignRecipientStep` / `CampaignDeliveryIntent` | `mod_campaigns.campaign_recipient_steps`, `campaign_delivery_intents` | `dotmac-campaigns` optional module | One unique recipient/step progression fact and one provider-neutral intent. The package emits deterministic timer identities through a port and writes the kernel outbox atomically; it owns no scheduler, relay, provider credentials, I/O or retry. |
| `CampaignObservation` / `CampaignResponse` | `mod_campaigns.campaign_observations`, `campaign_responses` | `dotmac-campaigns` optional module | Append-only deduplicated delivery/open/click/reply observations and response/conversion-correlation facts. Delivery projection is precedence-checked; the assembly asks Sales about a Lead and Inbox remains the message/conversation owner. |
| `CampaignUnsubscribeRequest` / `CampaignCounter` | `mod_campaigns.campaign_unsubscribe_requests`, `campaign_counters` | `dotmac-campaigns` optional module | Request evidence around a kernel-consent write, plus rebuildable aggregate projection. The counter is never authoritative and the drift/rebuild service derives it from recipient facts. |
| `Employee` | `mod_people.employees` | `dotmac-people` optional module | Product-first port of ERP's narrow employment relationship: one kernel Party person per tenant, stable code, lifecycle state/dates, and optional catalogue references. Personal identity, auth, reporting caches, compensation, payroll, attendance, finance and integrations are excluded ([`people-directory-sources.md`](inventories/people-directory-sources.md)). |
| `Department` | `mod_people.departments` | `dotmac-people` optional module | Tenant department identity and hierarchy. ERP's competing `head_id` employee pointer and cost-centre FK do not port; department head is derived through one declared head position and its dated incumbent. |
| `Designation` | `mod_people.designations` | `dotmac-people` optional module | Tenant job-title catalogue. ERP's NCC reporting category remains with its regulatory consumer rather than widening the directory contract. |
| `EmploymentType` | `mod_people.employment_types` | `dotmac-people` optional module | Tenant employment-arrangement catalogue with no payroll or product-integration fields. |
| `Position` | `mod_people.positions` | `dotmac-people` optional module | Canonical reporting hierarchy and vacancy-routing policy. Vacancy is derived from dated assignments; ERP's persisted `is_vacant` cache is deliberately not ported. |
| `PositionAssignment` | `mod_people.position_assignments` | `dotmac-people` optional module | Historical PRIMARY/ACTING/INTERIM occupancy. Service checks preserve ERP behavior and a PostgreSQL trigger serializes and rejects all overlapping primary intervals, including the finite intervals ERP's open-ended partial indexes missed. |
| `ReferralProgramme` / `ReferralProgrammeVersion` | `mod_referrals.referral_programmes`, `referral_programme_versions` | `dotmac-referrals` optional module | Tenant referral policy identity and immutable active-policy snapshot, product-first from Sub. Party, Customer, Sales and Billing remain opaque collaborators (ADR-0040). |
| `ReferralCode` / `Referral` / `ReferralConversion` | `mod_referrals.referral_codes`, `referrals`, `referral_conversions` | `dotmac-referrals` optional module | Finite invitation identity, idempotent source attribution and evidence-bound conversion. The conversion writes a provider-neutral reward request to the kernel outbox; it never creates a lead/customer or applies a credit. |
| `ResellerAccount` / `ResellerAuthorityRevision` | `mod_reseller.reseller_accounts`, `reseller_authority_revisions` | `dotmac-reseller-management` optional module | Product-first from Sub: tenant reseller identity, cycle-safe hierarchy, active/suspended/retired lifecycle and immutable least-privilege delegated authority. Party roles are opaque references; Commercial Agreements and Entitlement Allocation remain independent owners (ADR-0040). |
| `ResellerMemberBinding` / `ResellerCustomerAccountBinding` | `mod_reseller.reseller_member_bindings`, `reseller_customer_account_bindings` | `dotmac-reseller-management` optional module | Tenant-scoped bindings to opaque member and customer-account identities. They authorize no login and copy no Party or Customer state; commissions, payouts, invoices and customer lifecycle do not enter this namespace. |
| `Form` / `FormVersion` / `FormSection` / `FormField` / `FormFieldOption` | `mod_forms.forms`, `form_versions`, `form_sections`, `form_fields`, `form_field_options` | `dotmac-forms` optional module | Product-first port of ERP's seven-table reusable form definition owner. Published versions freeze an exact digest; subject meaning and file bytes remain opaque external references (ADR-0040). |
| `FormSubmission` / `FormAnswer` | `mod_forms.form_submissions`, `form_answers` | `dotmac-forms` optional module | One idempotent submission against an exact published version plus immutable typed value, display and field-definition snapshots. The module validates capture but decides no subject consequence. |
| `WorkflowExecution` / `WorkflowCheckpoint` / `WorkflowRepair` | `mod_workflow.workflow_executions`, `workflow_checkpoints`, `workflow_repairs` | `dotmac-workflow-runtime` optional module | Product-first runtime-only port from ERP: ordered finite claims, bounded retry and evidence-bound repair over opaque definition/subject/output references. Assemblies execute every external/domain effect (ADR-0040). |
| `HealthComponent` / `HealthObservation` / `HealthProjection` | `mod_health.health_components`, `health_observations`, `health_projections` | `dotmac-platform-health` optional module | Platform-only provider-neutral component policy, immutable bounded health evidence and a disposable deterministic latest-state projection. Fresh/stale/missing is derived at read time; no health fact mutates deployment state (ADR-0040). |
| `SupportAccessRequest` / `SupportAccessGrant` / `SupportAccessEvent` | `mod_supportaccess.support_access_requests`, `support_access_grants`, `support_access_events` | `dotmac-support-access` optional module | Platform-only purpose/case-bound request and exact Approval evidence, credential-free finite descriptor, revocation/expiry state and append-only workflow evidence. Kernel/adopter enforcement remains independent (ADR-0040). |
| `RemoteAccessRequest` / `RemoteAccessGrant` / `RemoteAccessObservation` | `mod_remoteaccess.remote_access_requests`, `remote_access_grants`, `remote_access_observations` | `dotmac-remote-access` optional module | Tenant purpose/opaque-target/least-privilege request, exact Approval binding, finite grant and immutable execution outcome. Network Control executes only the provider-neutral intent and remains the device desired-state owner (ADR-0040). |
| `ReportingObligation` / `ClassificationRevision` / `EvidencePack` / `EvidenceSection` | `mod_compliance.reporting_obligations`, `classification_revisions`, `evidence_packs`, `evidence_sections` | `dotmac-compliance-reporting` optional module | Product-first from Sub's NCC pack: immutable section vocabulary and exact period snapshot with explicit missing evidence. Source domains remain authoritative and a missing source never fabricates a value (ADR-0040). |
| `FilingSubmission` / `RegulatorAcknowledgement` | `mod_compliance.filing_submissions`, `regulator_acknowledgements` | `dotmac-compliance-reporting` optional module | Submission is bound to the exact pack digest; regulator acceptance/rejection is immutable evidence. Rendering, scheduling and transport remain separate owners. |
| `AIPolicy` / `AIPolicyVersion` / `AIOperation` / `AIExecutionAttempt` / `AIInsight` | `mod_aiops.ai_policies`, `ai_policy_versions`, `ai_operations`, `ai_execution_attempts`, `ai_insights` | `dotmac-ai-operations` optional module | Product-first from Sub: immutable allowed-operation/input-contract policy, provider-neutral intents, opaque provider/model/request observation strings and advisory insights. Integrator owns provider I/O; products alone own prompts and consequences (ADR-0040). |
| `CustomerAccount` | `mod_customers.customer_accounts` | `dotmac-customers` optional module | Stable tenant customer account number, display label, and account lifecycle extracted Sub-first. It is not a login, subscription, billing account, or network-access record. |
| `CustomerProfile` | `mod_customers.customer_profiles` | `dotmac-customers` optional module | One narrow segment/notes profile per customer account. Contact reachability, addresses, location evidence and arbitrary identity fields remain with their owning systems. |
| `CustomerPartyReference` | `mod_customers.customer_party_references` | `dotmac-customers` optional module | Typed opaque association to a Party identity owned elsewhere. The module never copies person/organization identity or dereferences a foreign application's database. |
| `ServiceSpecification` / `PlanFamily` | `mod_svc_cat.service_specifications`, `mod_svc_cat.plan_families` | `dotmac-service-catalog` optional module | Provider-neutral technical catalogue identity and grouping extracted Sub-first. No offer, price, contract, subscription, billing cycle or fixed recurrence is stored. |
| `CharacteristicDefinition` / `EligibilityInputDefinition` | `mod_svc_cat.characteristic_definitions`, `mod_svc_cat.eligibility_input_definitions` | `dotmac-service-catalog` optional module | Typed technical characteristic vocabulary and declared facts a Qualification owner may consume. They do not decide eligibility or provision network state. |
| `QualificationCase` / `QualificationEvidence` / `QualificationDecision` | `mod_qual.qualification_cases`, `mod_qual.qualification_evidence`, `mod_qual.qualification_decisions` | `dotmac-qualification` optional module | Time-bounded observation evidence and the one expiring service-eligibility decision. Positioning and Network Access contribute facts; they do not assign the outcome or service lifecycle. |
| `ServiceInstance` / `ServiceLifecycleEvent` | `mod_services.service_instances`, `mod_services.service_lifecycle_events` | `dotmac-services` optional module | One tenant service identity, current lifecycle state and immutable transition history. Customer/catalogue/qualification identifiers are opaque; fulfillment, access enforcement, subscriptions, rating and billing remain outside. |
| `UsageObservation` / `UsageCorrection` / `UsageAggregate` | `mod_usage.usage_observations`, `mod_usage.usage_corrections`, `mod_usage.usage_aggregates` | `dotmac-usage` optional module | Normalized immutable meter facts, append-only corrections and rebuildable projections. Raw AAA remains an upstream collector concern; tariff selection, monetary rating, invoices and ledgers remain outside. |
| `RatingRule` / `RatedUsageObligation` | `mod_usage_rate.rating_rules`, `mod_usage_rate.rated_usage_obligations` | `dotmac-usage-rating` optional module | Effective meter pricing and immutable pre-tax rated obligations from opaque usage references. Invoice lifecycle, tax, payments, revenue recognition and GL posting remain outside. |
| `ServiceAccessInput` / `DesiredAccessDecision` | `mod_serviceaccess.service_access_inputs`, `mod_serviceaccess.desired_access_decisions` | `dotmac-service-access-policy` optional module | Per-service FUP/prepaid/collections/admin observations and one desired ALLOW/RESTRICT/DENY projection. It owns no subscriber/account status and performs no AAA or device mutation; Network Access reconciles enforcement. |
| `InboxQueue` / `InboxRoutingRule` / `InboxRoutingDecision` / `InboxAgentPresence` / `InboxPresenceEvent` / `ConversationAssignment` / `InboxWorkflowEvent` / `InboxQueueEntry` / `InboxRoundRobinCursor` / `InboxTransferRequest` / `InboxEscalationRequest` / `InboxOfflineDisposition` | `mod_inbox_ops.*` declared tables | `dotmac-inbox-operations` optional module | Staffed inbox operation state adjudicated from Sub and CRM. Conversation/message content remains with Inbox, providers remain transports, and teams/skills/shifts/field availability remain with Workforce. The owner executes and records routing, accepts only caller-supplied opaque eligibility, serializes FIFO position and agent capacity decisions, selects the queue winner itself, attempts each queue in a fair cohort, and keeps released assignments plus settled queue entries as history through active-only unique indexes. Separate typed adoption commands preserve historical operation UUIDs and timestamps without executing live workflow consequences. Availability is a four-state agent choice with a state-free heartbeat and a derived (never stored) busy answer; only AVAILABLE is dispatchable, and claim, cold transfer, warm transfer, requeue and escalation are separate commands whose evidence records the previous and new holder (ADR-0059). |
| `ResponsePolicy` / `ResponseTarget` / `ResponseClock` / `ResponseClockPause` / `ResponseObservation` | `mod_sla.*` declared tables | `dotmac-response-obligations` optional module | One promise about time on one opaque subject, extracted product-first from Sub's already entity-generic SLA policy/target/clock/breach tables. The stored `due_at` is moved by a resume rather than derived at read time, so the sweep reads the front of an index instead of rescanning, and a PAUSED clock is never swept. Late completion settles as BREACHED, not MET. A breach carries no status: `dotmac-operational-escalations` owns whether it should escalate and who answered, `dotmac-durable-timers` owns scheduling, Messaging owns delivery, and business hours arrive as an `OUTSIDE_BUSINESS_HOURS` pause rather than a second calendar engine (ADR-0060). |
| `WorkforceTeam` / `WorkforceSkill` / `TeamMembership` / `WorkerSkill` / `WorkforceShift` / `WorkforceAvailability` / `DispatchDecision` | `mod_workforce.*` declared tables | `dotmac-workforce` optional module | Workforce scheduling and dispatch adjudicated from Sub, ERP and CRM. Workers and work are opaque references; People, payroll, attendance consequences, Inbox presence, Work Order lifecycle and route execution remain with their owning systems. |
| `FXRateType` / `FXRateSource` / `FXSelectionPolicy` / `FXRateObservation` / `FXRateDetermination` | `mod_fx_policy.*` declared tables | `dotmac-fx-policy` optional module | Effective FX observations, source provenance, selection policy and determination evidence extracted ERP-first. Kernel owns Money/ExchangeRate values; Billing, Tax, Accounting and provider adapters retain their distinct decisions and consequences. |
| `ServiceOrder` | `mod_serviceorders.service_orders` | `dotmac-service-orders` optional module | Product-first from Sub: the service-delivery order between a sold commercial order and a usable service. Customer, commercial-order, specification and service identifiers are opaque references; the commercial order, fulfillment saga, field work and realized service keep their own owners. |
| `ServiceOrderReadinessDecision` / `ServiceOrderReadinessCheck` | `mod_serviceorders.service_order_readiness_decisions`, `mod_serviceorders.service_order_readiness_checks` | `dotmac-service-orders` optional module | Append-only activation-readiness decision and the normalized checks it was made from, at most one per kind. Sub's rule is kept — a failed delivery run is terminal, any other failure blocks — while its direct reads of Projects, Tasks, Work Orders and IP Assignments become caller-supplied observations. |
| `PaymentIntent` | `mod_payments.payment_intents` | `dotmac-payments` optional module | Product-first from Sub's `topup_intents`: an intent to pay, idempotent on its own reference, with exact `Numeric` money and a required ISO-4217 code. It owns no receivable — Billing decides what a confirmed payment settles. |
| `PaymentTransferProof` / `PaymentConfirmation` | `mod_payments.payment_transfer_proofs`, `mod_payments.payment_confirmations` | `dotmac-payments` optional module | Bank-transfer evidence with its review, and the append-only correlation between an intent and one external settlement fact. Uniqueness on (tenant, provider type, external reference) is unconditional, closing the partial-index gap that left Sub's CRM-origin payments needing a second index. |
| `ServiceChangeRequest` / `ServiceChangeCheckpoint` | `mod_servicechanges.service_change_requests`, `mod_servicechanges.service_change_checkpoints` | `dotmac-service-changes` optional module | Product-first from Sub's `SubscriptionChangeRequest`: the durable plan-change/relocation/vacation request and typed append-only evidence that each crossed owner reached a named point. Sub's per-collaborator nullable FK columns become rows; execution advances one declared step at a time. |
| `EscalationPolicy` / `EscalationPolicyVersion` / `EscalationInstance` | `mod_escalations.escalation_policies`, `mod_escalations.escalation_policy_versions`, `mod_escalations.escalation_instances` | `dotmac-operational-escalations` optional module | Product-first from Sub: policy identity, IMMUTABLE versions with exactly one ACTIVE per policy (partial unique index, not writer-only), and instances bound to the exact version they were raised under. Delivery is deliberately absent — Messaging/Integrator owns it and Durable Timers owns scheduling. |

`Party.custom_fields` and `DomainSetting`'s split-policy shape are
columns/behavior on the rows above, not separate tables, so they don't get
their own provenance row — they're called out in the sections above instead.

## Mutable-resource ownership list

SOT-complete criterion 1 ("every mutable resource, decision, and state
transition has one named owner") applied at the *resource* level, not just
the model level — one service-layer function (or, where two legitimately
exist, both named with the invariant that keeps them consistent) owns every
write:

| Resource | Owning write path(s) |
|---|---|
| Tenants | `app.features.tenants.service.provision_tenant` (platform-only, control-plane security Task 2 — one transaction creating tenant + owner party/person/credential + `admin` role grant + two audit events; no update/delete service yet) |
| Platform admins | `scripts/create_platform_admin.py::upsert_admin` (CLI-only, platform/migration DB credentials — the same trust boundary as migrations; deliberately NO HTTP write path, see ADR-0004) |
| Platform sessions | `dotmac_kernel.platform_auth.login` (issues, via `POST /platform/auth/login`) **and** `logout` (revokes, via `POST /platform/auth/logout`) |
| Platform runtime-health evidence and projections | `dotmac_platform_health.service.record_observation` is the sole immutable fact writer; `register_component` owns bounded freshness policy; `rebuild_projections` is the sole repair writer and `summarize_health` derives explicit fresh/stale/missing state. Observability owns raw telemetry, Ticketing owns incidents and Deployment Control alone owns desired-state mutation. |
| Temporary support-access requests and finite grants | `dotmac_support_access.service.create_request`, `admit_request`, `revoke_grant` and `expire_grants` own the platform workflow. Approval is accepted only as exact-content evidence; the returned descriptor contains no credential and the adopter/kernel remains the enforcement owner. There is no renewal path. |
| Tenant domains | none — no write path exists yet (rows would be inserted by a future custom-domain feature) |
| Parties (person/org identity + profile) | **Dual writer**, see below: `app.features.parties.service.create_person_party` / `create_organization_party` / `update_person_party` / `update_organization_party` (the `/parties` API + `/admin/parties/{id}/edit` web flow), **and** `app.features.auth.service.register` (the `/auth/register` flow) |
| `Party.display_name` projection | owner: parties+auth services via `core/identity` helpers (recompute-on-write) — `app.features.parties.service.create_person_party`/`update_person_party` and `app.features.auth.service.register` all call `dotmac_kernel.identity.person_display_name`; `update_organization_party`/`create_organization_party` reassign `legal_name` directly (no helper needed — `legal_name` IS the display name). Recomputed on every create AND update, never write-once again (Task 5 closed the SOT gap; see below). Repair: re-save (call the relevant update function — it recomputes from the current subtype fields, no separate repair script needed) |
| `Party.email` (the login identity) | **Single column, single authority as of 2b.1-T3 (finding F2, resolved)**: owner is parties+auth writers via `dotmac_kernel.identity.normalize_email` — same dual-writer/shared-invariant shape as `display_name` above (`create_person_party`/`update_person_party`/`create_organization_party`/`update_organization_party` and `auth/service.py::register` all call it). `app.features.auth.service.login` READS this column directly (join by `party_id` to find the credential row) instead of a second `UserCredential.email` copy, which is GONE — see the F2 resolution note under "Known dual-writer: Parties" below. No repair path needed: there is only ever one column now, so there is nothing to drift or re-sync. |
| Party role grants | `app.features.rbac.service.assign_role` (the `POST /rbac/role-grants` JSON API **and** the `POST /admin/role-grants` web form both call this same function) **and** `app.features.tenants.service.provision_tenant` (grants the provisioned owner the `admin` role inside the provisioning transaction). The race-prone `_assign_first_user_admin` first-registrant bootstrap is DELETED (control-plane security Task 2) — registration never grants a role |
| Roles | `app.features.rbac.service.create_role` (`POST /rbac/roles` API **and** `POST /admin/roles` web form), and `app.features.tenants.service.provision_tenant` (creates the new tenant's `admin` role during provisioning) |
| Auth credentials | `app.features.auth.service.register` (policy-gated self-registration, `auth.registration_policy` default `closed`) **and** `app.features.tenants.service.provision_tenant` (the owner credential, inside the provisioning transaction) — no credential-update/password-reset path yet, phase 2c. `Party.email` is a SEPARATE resource with its own row above (Parties) — `UserCredential` carries no email of its own as of 2b.1-T3 (F2): `login()` resolves `Party` by email first, then `UserCredential` by `party_id` only. |
| Human credential lifecycle decisions (kernel CONTRACT; not composed by this assembly) | `dotmac_kernel.credential_lifecycle.CredentialLifecycle` — `provision` (no parameter can carry caller-supplied material), `verify` (one typed verdict, never a boolean, never a session), `complete_reset` (behind a single-use proven recovery authorization) and `plan_force_reset`/`apply_force_reset` (a canonically sorted cohort, a typed `CredentialResetPlanDigestV1`, a separate authorization carrying no `approved_by`, and all targets or none). Stateless: the product supplies five typed ports and OWNS the transaction, so the kernel writes nothing itself. The assembly's own `auth`/`tenants` writers above are unchanged and remain the as-built path; `dotmac_sub` is the named first adopter and its cutover has not started. See "Human credential lifecycle" below and `docs/inventories/credential-lifecycle-sources.md`. |
| Auth sessions | `app.features.auth.service.login` (issues, via `POST /auth/login` and `POST /admin/login`'s `web_login`) **and** `web_logout` (revokes — sets `revoked_at`, via `POST /admin/logout`, CSRF-protected as of 2b.1-T5/F7; the JSON API has no logout/revoke route of its own yet) |
| Audit events | `dotmac_kernel.audit.write_audit_event` — the only function that constructs an `AuditEvent`. It enforces two distinct contracts before anything reaches the session: the open ACTION VOCABULARY is declared by installed modules through `AuditActionRegistry`, while the actor is the closed kernel-owned `(actor_type, actor_id)` identity pair (`system` may omit an id; `user`/`service`/`api_key` may not). Both members are explicit at every applicable caller; `actor_party_id` is optional accountability enrichment and never supplies the pair, while `actor_label` is a display snapshot. A production-source AST census covers all 20 writers across the assembly and shipped packages. `dotmac_workspace` PR #10 retired the final known external fallback callers before kernel a69 removed the derivation. `occurred_at` is domain time (database `now()` by default, caller-supplied for reconstruction), distinct from server-assigned persistence `created_at`. Tenant audit actor columns have no FK so attribution survives deletion. |
| Platform audit events | `dotmac_kernel.audit.write_platform_audit_event` is the sole constructor/writer. Kernel owns the storage contract as `platform_audit_log.v1`; migration `0026_platform_audit_log` makes online history append-only, and the live verifier proves shape, FK/index, no RLS, tenant-role isolation, and `platform_api` `SELECT`+`INSERT` only. Consumer declarations and DDL-free verification revisions follow only after kernel a68 is published, so their declared floor is resolvable. Current limitation: deleting a `PlatformAdmin` nulls actor attribution, so immutable actor snapshotting remains a separate unresolved hardening slice. |
| Integrator shadow-comparison evidence | `dotmac_integration.shadow.record_shadow_observation` is the sole writer; it appends and flushes a closed, privacy-safe outcome keyed by the module receipt UUID and explicit comparison revision. `due_shadow_receipt_ids` and `shadow_report` are the only scheduling/report readers. The destination product owns the comparison and its domain reads; the thin `dotmac_integrator` assembly owns only transaction boundaries and transport. This high-volume worker state is not projected from the kernel operator-audit ledger. |
| External media observation facts and projections | `dotmac_media_observations.service` is the only package writer: declaration and `record_*` functions append normalized facts/receipts/restatements; `_refresh_projections` and `reconcile_projections` alone replace disposable current rows. A connector emits typed commands but never writes these tables. No product composes the module while adoption is paused (ADR-0034). |
| Communication suppressions | `dotmac_kernel.consent.suppress`, `unsuppress`, and `unsuppress_marketing`; delivery never writes the table directly — a suppressing provider receipt delegates to `consent.suppress` in the same transaction |
| Communication delivery receipts | `dotmac_kernel.delivery.record_receipt` — the only constructor/writer; it preserves each provider status transition, deduplicates repeated callbacks, and delegates suppressing consequences to the consent owner |
| Domain settings rows | `dotmac_kernel.settings_resolver.upsert_by_key` (tenant writes, via `settings/service.py::update_setting` — called by the JSON `PUT /settings/{domain}/{key}` API, the generic web editor `POST /admin/settings/{domain}/{key}/edit`, **and** the friendly branding editor `POST /admin/settings/branding`, all three ending in the same function and the same `settings.update` audit event) and `ensure_by_key` (platform-default seeding only, via `settings/seed.py::seed_platform_defaults`, idempotent — never overwrites an existing row) |
| Notification channel-policy setting | Same canonical `DomainSetting` writers as above; `dotmac_kernel.channel_policy.resolve_channels` is the typed reader and the legacy per-event shadow setting is not supported |
| `ui_branding` setting specifically | same writer as above (`update_setting`, domain=`branding`, key=`ui_branding`) — no separate write path; read by `dotmac_kernel.branding.load_branding`, whose resolved colour fields are projected by `app.features.presentation.service.project_brand_stylesheet` through `dotmac_ui.render_brand_css`. Template Studio is not an owner or writer |
| Runtime brand stylesheet projection | `app.features.presentation.service.project_brand_stylesheet` is the sole composer: kernel-resolved brand data in, public `dotmac_ui` generator out. `web.py` only guards scope and applies response policy; templates only link the route. No stored CSS, parallel renderer, or Template Studio writer exists |
| Reusable map-frame presentation | `dotmac_ui.components.MAP_FRAME` owns only the inert canvas/state markup, token-native CSS and accessibility contract. A composing product owns the state transition and every provider, tile, viewport, endpoint, poll, location datum, layer, popup, control, fallback and domain decision. The contract is audit-complete with zero product adopters; no product-local owner is retired yet. |
| Custom field definitions | `app.features.custom_fields.service.create_field` / `update_field` / `deactivate_field` (soft-delete only — no hard delete); each has a JSON API route (`custom_fields/router.py`) and an `/admin/custom-fields` web route (`custom_fields/web.py`) calling the same function |
| Custom field values | `app.features.custom_fields.service.set_values` (the only writer of any entity's `custom_fields` JSONB column) — called by the JSON `PUT /custom-fields/{entity_type}/{entity_id}/values` API **and** the web values-panel (`POST /admin/custom-fields/party/{party_id}/values-panel`, see the composition pattern above) |
| Subscription complimentary/sponsored arrangements and non-cash grants | `dotmac_subscriptions.treatments` is the sole writer on both declared planes through `approve_billing_arrangement`, `revoke_billing_arrangement` and `record_non_cash_grant`. Approval is fingerprint-bound to a preview, replay is resolved before the preview runs, and `resolve_billing_arrangement` answers `standard`, `effective` or `protected_drift` — the last suppresses customer charging while refusing a grant rather than fabricating coverage. Sub keeps its own arrangement writer until ledger items G5/G6 complete the backfill, shadow and cutover; no product is claimed as cut over. |
| Subscription offers, versions, prices, contracts, lines and recurring occurrences | `dotmac_subscriptions.service` is the sole writer on both declared planes through its typed publish/withdraw, record/end, resolve, generate and acknowledge operations. It uses the caller's session and flushes only. The occurrence and Subscriptions-owned `RatedObligationOutputV1` stage atomically; Billing owns only its distinct `AcceptRatedObligationV1` input, and access/Billing owners are assembly-wired consumers, never sibling imports. No product is claimed as cut over. |
| Billing obligations, documents, settlements, posting effects, account positions, invoice exposures, official artifact relations and accounting facts | `dotmac_billing.service` is the sole writer on both declared planes through its typed accept/issue/void/credit/allocation/correction/rebuild/artifact-record/artifact-repair operations. It uses the caller's session and flushes only, and every emitted kernel-outbox routing code is declared by its module manifest. Billing owns both aggregate and exposure financial state; Collections receives only an assembly-translated `ReceivableExposureV1`, and ERP receives immutable accounting facts. |
| Collections policy, cases, arrangements, grace, notice/action request evidence and receipts | `dotmac_collections.service` is the sole writer on both declared planes. A typed `Scope` selects mirrored models and the matching kernel idempotency ledger; `CollectionCaseService.assess` and `process_step_due` reread `ReceivableObservationV1` and fail closed before action. Case transitions stage exact timer schedule/cancel operations through the caller-owned `CollectionsTimer` port. Accepted requests and manifest-declared kernel outbox intents flush atomically; accepted or retryable owner receipts schedule only the next immutable policy step/retry. Replay emits no duplicate. Collections never writes Billing financial state or the owning product's service state, and neither candidate adopter is claimed as cut over. |
| Ticket lifecycle rows | none in this reference assembly — it composes `mod_tkt` only for migration/catalog proof and has no ticket surface. A real adopter's local ticket service is the sole writer. Independently owned tickets stay in their owning application/Integrator evidence; correlation alone uses an opaque reference rather than a local projection (ADR-0024). |
| Stored-file metadata and physical state | `dotmac_files.service.stage_file` / `request_deletion`, then the explicit target→external-action→record-result phases (`deletion_target` → `delete_object` → `finalize_purge`; `reconciliation_target` → `observe_object` → `record_presence`). DB phases filter explicit `TenantScope` and flush without commit/rollback; provider phases accept no `Session`, so no network call or download stream holds a DB transaction. The owner covers only provider/byte state. Domain attachment relations, read authorization, retention permission, document meaning, and import outcomes remain with the domain that references the opaque file UUID (ADR-0022). |
| First-party website observations and analytical projections | `dotmac_web_analytics.service.record_event` is the sole raw-observation writer; `record_classification` appends filter evidence; `dotmac_web_analytics.projections.rebuild_projections` is the sole writer of visitor/session/route/source/device/event/funnel projections; `dotmac_web_analytics.retention` deletes through the offline retention/privacy path and rebuilds before the transaction can complete. Property/origin/event/privacy/session/retention policy comes from each adopter. Websites, forms, campaigns, provider observations, customer identity, attribution and revenue remain with their named owners (ADR-0055). |
| Import run and row outcomes | `dotmac_imports.service` — `create_dry_run`, `validate_next_chunk` (which takes no applier and therefore cannot mutate a domain), `promote` (digest-verified, uniquely constrained so a validated run applies once), `apply_next_chunk`, `mark_failed`. A chunk call locks the run, hashes and decodes the recorded bytes, resumes after the committed checkpoint, and returns without committing; `dotmac_kernel.db` remains the one transaction authority. Completed re-delivery is a no-op. Expected domain refusals are typed `RowRejected` outcomes; unexpected exceptions roll back the attempted chunk and escape. The importing domain remains the sole writer of its own rows through the `RowValidator`/`RowApplier` ports, and owns any reversal of what an import created (ADR-0025). |
| Large-import partition plan and worker checkpoint | `dotmac_imports.partitioning` — two-pass verified CSV partition generation, immutable descriptor registration, and three phases: an atomic expiring claim, a session-free bounded object read/verification, then structurally separate validation/apply settlement. A replaced lease cannot settle prepared rows; each domain effect, typed `ok | error | skipped` outcome and partition checkpoint commits together. `dotmac-files` owns every original/derived byte; products decide worker count and retain all field/domain meaning. |
| Editorial plans, content items, variants and creative relations | `dotmac_content.service` — plan/item create, get, list, count and guarded update; variant creation; plan/item creative attachment; immutable snapshot construction. Every write requires explicit `TenantScope`, filters the tenant in the service, mutates and flushes the caller's session, and never commits or rolls back. Backoffice authorizes actors, `dotmac-files` owns bytes, publishing owns releases, `dotmac-campaigns` owns outbound progression, and Integrator owns provider transport; none is a parallel content writer. |
| Publication releases, deliveries, attempts and normalized observations | `dotmac_publishing.service` — idempotent immutable request creation and typed timer scheduling; stale-safe due dispatch; one outbox intent per target attempt; receipt-deduplicated observation recording; explicit partial/all-failed reconciliation; failed-target retry and pre-dispatch cancellation. Every write requires explicit `TenantScope`, filters the tenant in the service, mutates and flushes the caller's session, and never commits or rolls back. An assembly supplies timer storage, Backoffice owns authorization/target policy, content/sites own editable sources, kernel owns idempotency/outbox, and Integrator owns bindings, providers, credentials and transport; none is a parallel publication writer. |
| Outbound campaign identity and recipient progression | `dotmac_campaigns.service` — `create_campaign`/`revise_campaign`, `ingest_audience`, `schedule_campaign`, `accept_due_work`, `record_observation`, pause/resume/cancel/complete, `authorize_delivery`, `request_unsubscribe`, counter rebuild and publication/privacy repair. Every path receives and flushes the caller session. Kernel consent decides eligibility, kernel idempotency owns replay, kernel outbox owns publication, Durable Timers owns due-work mechanics, and product adapters supply audience/render/sender/Sales facts; none is a parallel campaigns writer (ADR-0056). |
| Referral programmes, codes, attribution and conversions | `dotmac_referrals.service` — `create_programme`, `issue_code`, `capture_referral`, and `record_conversion`. Every call receives an explicit tenant scope and caller session; conversion evidence and its reward-request outbox fact flush atomically. Party, Customer, Lead and Billing mutations remain outside the module (ADR-0040). |
| Reseller account identity, hierarchy, delegated authority, bindings and lifecycle | `dotmac_reseller_management.service` — `create_account`, `set_parent`, `publish_authority`, `bind_member`, `bind_customer_account`, and `transition_account`. The owner receives an explicit tenant scope and caller session, rejects hierarchy cycles and authority broader than the parent revision, and flushes provider-neutral status facts through the kernel outbox. Party, Customer, Commercial Agreements, Entitlement Allocation, authentication, commissions, payouts and invoices remain outside the module (ADR-0040). |
| Reusable form definitions, versions, fields/options, submissions and answer snapshots | `dotmac_forms.service` — `create_form`, `create_draft_version`, `add_section`, `add_field`, `add_option`, `publish_version`, and `submit_form`. Published definitions are digest-frozen; stable submission keys conflict on different content. Subject lifecycle, file bytes, rendering and consequences remain outside the module (ADR-0040). |
| User-authored workflow execution, checkpoint claims/results and repair evidence | `dotmac_workflow_runtime.service` — `start_execution`, `claim_checkpoint`, `settle_checkpoint`, and `record_repair`. Checkpoints advance strictly in order under finite leases and bounded attempts; a terminal failure resumes only from explicit repair evidence. Definition authoring, timers, transport and every domain/provider effect remain assembly-owned (ADR-0040). |
| Remote-access requests, grants and observations | `dotmac_remote_access.service.create_request`, `admit_request`, `revoke_grant`, `expire_grants` and `record_observation`. Exact Approval evidence gates one finite grant; activation/revocation are provider-neutral intents. Network Control/Integrator execute and observe them without becoming grant writers. |
| Regulatory classification, packs and filing state | `dotmac_compliance_reporting.service.create_obligation`, `publish_classification`, `assemble_pack`, `submit_pack` and `acknowledge_submission`. Pack digests bind classification, period and every present/missing section; source owners retain their facts and the module never queries them directly. |
| AI intake policy, operation evidence and advisory insights | `dotmac_ai_operations.service.create_policy`, `publish_policy_version`, `activate_policy_version`, `start_operation`, `record_attempt`, `create_insight` and `acknowledge_insight`. `dotmac_ai_operations.advisory` additionally carries a stateless advisory protocol (`AIAdvisoryInvocation`/`AIAdvisoryResult`/`AIActionProposal`/`AIActionDecision`/`AIExecutionObservation`/`AICapabilityExposureRef`) — one invocation and its result crossing a boundary, with capability admission as an opaque exposure reference. The consuming product's own orchestration owner (for example, Sub's `ai.intake`) holds session, routing/orchestration policy and workflow next-step; this package holds none of it. Integrator plugins own provider I/O, while products own prompts, domain context and any action recorded only as opaque evidence. |
| Customer accounts, profiles and Party references | `dotmac_customers.service` — `create_account`, `set_profile`, `link_party_reference`, and `transition_account` are the only writers. Every path takes an explicit tenant scope, mutates and flushes the caller session, and leaves identity, reachability, qualification, services, billing and network state with their owners (ADR-0058). |
| Technical service catalogue | `dotmac_service_catalog.service` — stable specification/family and definition creation plus `publish_plan_family_version` and `publish_service_specification_version` are the only writers. `effective_service_specification` resolves one evidenced technical shape as of a supplied time. Qualification consumes declared inputs but never writes catalogue state (ADR-0058). |
| Qualification cases, evidence and decisions | `dotmac_qualification.service` — `open_qualification`, `record_evidence`, and `record_decision` are the only writers. Evidence remains observation data; the decision writer alone derives the time-bounded outcome (ADR-0058). |
| Service instances and lifecycle history | `dotmac_services.service` — `create_service` and `transition_service` are the only writers. The transition function writes current state and immutable history in one caller-owned transaction; access enforcement and billing remain separate consequences (ADR-0058). |
| Usage observations, corrections and aggregates | `dotmac_usage.service` — `record_usage_observation`, `record_usage_correction`, and `project_usage_aggregate` are the only writers. Aggregates are rebuildable from immutable observations and append-only corrections; raw AAA and monetary rating remain separate (ADR-0058). |
| Rating rules and rated usage obligations | `dotmac_usage_rating.service` — `create_rating_rule` and `rate_usage` are the only writers. Rating creates immutable pre-tax obligations and never writes invoice, tax, payment or accounting state (ADR-0058). |
| Desired service-access policy | `dotmac_service_access_policy.service` — `record_access_input` and `resolve_desired_access` are the only writers. The module decides desired state; Network Access alone reconciles enforcement (ADR-0058). |
| Staffed-inbox queues, routing, presence, FIFO admission and assignments | `dotmac_inbox_operations.service` — `create_queue`, `create_routing_rule` and `assign_conversation` are the only writers of queue, rule and assignment state; `dotmac_inbox_operations.presence` is the only writer of agent presence and the only place dispatch eligibility is stated; `dotmac_inbox_operations.transfers` is the only writer of ownership movement and escalation; `dotmac_inbox_operations.sessions` is the only writer of offline dispositions. Inbox retains conversation/message content and Workforce retains shift and field availability (ADR-0058). `admit_to_queue`, `cancel_queue_entry`, `promote_from_queue` and `next_round_robin_agent` join them in a2; promotion goes through `assign_conversation`, so the queue decides order while presence and capacity still decide admissibility. ADR-0059 adds the availability owner and splits ownership movement into `claim_conversation`, `transfer_conversation`, the warm-transfer request/accept/decline/expire pair, `requeue_conversation` and `escalate_conversation` — escalation records only that an agent ASKED and can never reassign, because the record has no target-agent column; `dotmac-operational-escalations` remains the sole owner of whether an escalation exists and who answered it, and the inbox hands it an `EscalationRequested` carrying a shared dedup key (ADR-0059). |
| Response-time targets, clocks, paused intervals and breach observations | `dotmac_response_obligations.service` — `register_policy`, `set_target`, `start_clock`, `pause_clock`, `resume_clock`, `complete_clock`, `cancel_clock` and `sweep_due_clocks` are the only writers. The subject stays with its own owner and the escalation decision stays with `dotmac-operational-escalations`; the sweep returns typed `EscalationRequested` values and enqueues two declared outbox events rather than deciding or delivering anything (ADR-0060). |
| Workforce teams, skills, schedules, availability and dispatch | `dotmac_workforce.service` is the only writer through its team, skill, membership, certification, shift, availability and dispatch commands. People and Work Orders remain authoritative for worker and work lifecycle (ADR-0058). |
| FX rate types, sources, policies, observations and determinations | `dotmac_fx_policy.service` is the only writer through catalogue, policy, observation and determination commands. Direct-rate selection precedes inverse fallback; Billing, Tax and Accounting consume the immutable determination but own their snapshots and consequences (ADR-0058). |
| Service-delivery orders and activation readiness | `dotmac_service_orders.service` — `open_service_order`, `submit_service_order`, `begin_delivery`, `cancel_service_order`, `decide_readiness` and `confirm_activation` are the only writers. Readiness evidence is append-only in the service AND at the ORM, so a caller cannot rewrite a decision after the fact. |
| Payment intent and confirmation correlation | `dotmac_payments.service` — `open_payment_intent`, `cancel_payment_intent`, `expire_payment_intent`, `submit_transfer_proof`, `review_transfer_proof` and `record_confirmation` are the only writers. `record_confirmation` is the single path by which an intent becomes CONFIRMED; an accepted transfer proof goes through it rather than beside it. |
| Durable service-change requests and their checkpoints | `dotmac_service_changes.service` — `open_service_change`, `decide_service_change`, `cancel_service_change`, `record_checkpoint` and `advance_execution` are the only writers. `advance_execution` is the single guard on the execution chain the source spread across several handlers. |
| Escalation policy versions, instances and settlement | `dotmac_operational_escalations.service` — `register_policy`, `draft_policy_version`, `activate_policy_version`, `raise_escalation`, `acknowledge_escalation`, `resolve_escalation` and `cancel_escalation` are the only writers. Cooldown is enforced as a refusal to raise, because whether an escalation should exist is this owner's decision and not a transport's. |
| Durable timer generations, cancellation and acceptance/rejection evidence | `dotmac_durable_timers.service` is the sole lifecycle writer on both declared planes: `schedule_timer`, `cancel_timer`, `accept_trigger`, `current_timer`, and `purge_history`. Identity-level PostgreSQL advisory locks serialize even the first schedule; cancellation names the observed generation and refuses a newer current generation; trigger acceptance re-derives current state and records stale evidence with observed/current generations and the opaque source version. The package exports typed ports, never ORM models. A schedule resolves the consuming module's manifest-declared outbox event type, calls the kernel outbox writer in the same transaction and sets `available_at=due_at`; `dotmac_kernel.messaging.relay` remains the sole owner of claim, lease, retry and dead-letter behavior. Business deadline policy and the effect after an accepted trigger remain with the adopting product. This reference assembly builds and proves the optional package but does not compose its `dt` lineage. |
| Display formats (timezone/date_format/datetime_format) | owner: `settings` (display domain) — same `update_setting`/`upsert_by_key` write path as every other setting, via the generic web editor and the JSON `PUT /settings/display/{key}` API; no dedicated write path. Consumers: the `local_datetime`/`local_date` Jinja filters ONLY (`dotmac_kernel.templating`) — no service reads these specs directly |

### Known dual-writer: Parties (auth register vs. parties service)

Three service functions independently construct a `Party` + `PartyPerson`
row: `auth/service.py::register` (the `/auth/register` self-service signup
flow — policy-gated `closed` by default since control-plane security Task 2,
creates the `UserCredential` in the same transaction, and NEVER grants a
role: the first-registrant admin bootstrap is deleted),
`tenants/service.py::provision_tenant` (the platform provisioning flow —
the only owner/admin-creation path, same `core/identity` invariants), and
`parties/service.py::create_person_party` /
`create_organization_party` / `update_person_party` /
`update_organization_party` (the tenant-admin `/parties` API and the
`/admin/parties/{id}/edit` web flow, Task 5). This is a **deliberate, not
accidental** dual writer — one flow is "a person signs themselves up," the
other is "an admin manages a contact/customer record" — flagged here per
SOT-complete honesty rather than silently left implicit. The writers
themselves stay two; what changed (Task 5) is that the INVARIANTS both must
preserve are no longer hand-duplicated at each call site — they're
implemented once in `dotmac_kernel.identity` and both writers call the same
functions:

- **Email is lowercased at the write boundary**, via
  `dotmac_kernel.identity.normalize_email` — `auth/service.py::register` and
  `parties/service.py`'s create/update functions all call this one function
  instead of each writing its own `.lower()`. Both must agree because the
  `parties` table's uniqueness index is `lower(email)`-based — a
  mixed-case write from either path that skipped normalization would still
  be rejected by the DB constraint, but a *read*-side comparison
  (`login()`'s `Party` lookup) that skipped it would silently fail to
  match. A new writer of `Party.email` now has an obvious single function
  to call rather than a convention to remember and replicate.
  **F2 resolution (Phase 2b.1 Task 3, RESOLVED):** until this task,
  `app.features.auth.models.UserCredential` carried its OWN `email` column
  — a write-once copy made at `register()` and never touched again. Once
  `update_person_party` (Task 5) could edit or NULL `Party.email`, that
  copy silently drifted from the real profile email, with no cross-feature
  guard possible (parties cannot reach into auth's table under feature
  independence). The fix removes the second column entirely — migration
  `alembic/versions/20260718_0005_single_email_authority.py` drops
  `user_credentials.email` + its unique constraint, and
  `auth/service.py::login` now resolves `Party` by
  `(tenant_id, normalize_email(email), party_type=person)` FIRST, then
  `UserCredential` by `party_id` only. There is exactly one email column
  system-wide now, so the two can never drift again — see the ownership
  table's `Party.email` row above. Documented, intended consequence: a
  person party with a NULL email cannot log in (the query matches no
  string) — see `login()`'s docstring, and the (struck) backlog entry in
  `docs/superpowers/phase2-backlog.md`.
- **`display_name` derivation** — **closed as of Task 5** (previously the
  tracked SOT gap in `docs/superpowers/phase2-backlog.md`). Both writers
  now call `dotmac_kernel.identity.person_display_name(first_name, last_name)`
  for the person case (organizations reassign `legal_name` directly — no
  helper needed, `legal_name` IS the display name); `update_person_party`/
  `update_organization_party` (`parties/service.py`) recompute
  `display_name` INSIDE the update, from the just-updated subtype fields,
  so the projection is refreshed on every write, not just at create. See
  the ownership table above (`Party.display_name` projection row) for the
  owner/repair statement.

## Request flow / middleware order

From `app/main.py`'s docstring, outermost to innermost as FastAPI executes
them (Starlette runs the *last-added* middleware first, so the add order in
the source is the reverse of execution order — the list below is execution
order):

1. **SecurityHeadersMiddleware** — outermost (added last), so it wraps
   every response INCLUDING the middleware short-circuits below (tenant
   404s, 429s, CSRF 403s): sets `X-Content-Type-Options`, `X-Frame-Options`,
   `Referrer-Policy`, `Permissions-Policy`, HSTS on a secure request, and
   the Content-Security-Policy. Only a last-resort UNHANDLED-exception 500
   (Starlette's `ServerErrorMiddleware`, which wraps all user middleware)
   escapes it. Knobs: `SECURITY_HEADERS_ENABLED`, `CONTENT_SECURITY_POLICY`
   (empty → the computed-strict default; a non-empty value may only tighten the
   complete baseline; see `docs/SECURITY.md`).
2. **ObservabilityMiddleware** — assigns/propagates a request ID
   (`TRUST_INBOUND_REQUEST_ID` gates whether an inbound `X-Request-ID` is
   trusted or a fresh one is generated) and emits structured request logs.
3. **TrustedHostMiddleware** — only mounted when `TRUSTED_HOSTS` is set;
   drops requests to unrecognized `Host` headers before any tenant lookup.
4. **TenantResolverMiddleware** — resolves `request.state.tenant` from the
   `Host` header (see below) and sets it before any route runs.
5. **RateLimitMiddleware** — tenant/client-ip/route-template-keyed budget
   check against the bounded store (`dotmac_kernel/middleware/rate_limit.py`;
   unmatched paths collapse into fixed hash buckets — see `docs/SECURITY.md`).
6. **CSRFMiddleware** — issues/rotates signed browser tokens; each composed
   route's explicit `require_csrf` dependency validates unsafe requests.

After middleware, `register_error_handlers(app)` installs the exception
handlers, `/health` is registered directly, `mount_features(...)` mounts enabled
API routers, and `mount_web_surfaces(...)` mounts the validated browser graph.

### Health bypass

`/health` is a liveness check that must not touch the database (container
orchestrators probe it before a DB may even be reachable).
`TenantResolverMiddleware._HEALTH_PATHS` is a frozenset containing `/health`
and `/health/ready`; both are short-circuited before any tenant resolution
(no DB query at all). Today only `/health` is mounted as a route; `/health/ready`
is pre-listed for a future readiness endpoint and currently returns 404 at the
router after bypassing tenant resolution. `/health` is the only route in
`tests/architecture/test_route_guards.py::ALLOWLIST` permitted to carry zero
`require_*` guards. Every other route either carries a `require_*` dependency
or fails the architecture test.

### Static-asset bypass

`/static/*` (the `StaticFiles` mount in `app/main.py`, serving
`static/css/main.css`, vendor JS, etc.) gets the same before-resolution
short-circuit as `/health`, via `_is_static_path()`: `path == "/static"` or
`path.startswith("/static/")` — plain string checks, deliberately no regex.
Before this bypass existed, `TenantResolverMiddleware.dispatch` opened a
`SessionLocal()` for every static-asset request same as any other route; with
the DB unreachable, that raised and turned a should-be-200 static asset into
a 500 — verified as a real repro (`/static/css/main.css` 500s with the DB
down) and fixed alongside the branded HTML error pages in plan 2b Task 2.
`tests/unit/test_tenant_middleware.py` covers both the exact/prefix bypass
(`/static`, `/static/css/main.css`) and the near-miss paths that must NOT
bypass (`/staticevil`, `/static2/x` — a bare `startswith("/static")` without
the trailing-slash check would wrongly match both).

## Tenant resolution

`TenantResolverMiddleware._resolve()`, in order:

1. **Custom domain** — exact match in `tenant_domains.domain` where
   `verified_at IS NOT NULL`, joined to an active, non-deleted `tenants` row.
2. **Subdomain** — `host` stripped of the `.` + `PLATFORM_ROOT_DOMAIN`
   suffix (rejecting nested subdomains) looked up against `tenants.slug`.
3. **Root domain** — `host == PLATFORM_ROOT_DOMAIN` → `request.state.tenant
   = None` (platform context; only `/platform/*` and `/health` are valid
   here — see `_is_platform_path`).
4. **Unknown host** — 404, except for platform paths and `/health`.

## The three-role DB model

Three Postgres roles, three connection URLs (`DATABASE_URL`,
`PLATFORM_DATABASE_URL`, `MIGRATION_DATABASE_URL`), created by the initial
Alembic migration (`alembic/versions/20260504_0001_initial_tenant_schema.py`):

- **`app_user`** (`DATABASE_URL`) — the FastAPI request-path role for
  tenant-scoped routes. RLS-enforced, cannot bypass. `dotmac_kernel.db.get_db`
  runs `SELECT set_config('app.current_tenant', :id, true)` per request
  (transaction-scoped — the next pooled connection starts with no setting).
  RLS policies read that setting via `app_current_tenant_id()`, which
  treats unset/malformed values as `NULL`, so a forgotten tenant scope
  fails closed (zero rows) rather than leaking.
- **`platform_api`** (`PLATFORM_DATABASE_URL`) — used by `dotmac_kernel.db.get_platform_db`
  for platform-wide routes (tenant provisioning). Explicit grants, **no**
  `BYPASSRLS`. Falls back to `DATABASE_URL` if unset (local dev only).
- **`app_admin`** (`MIGRATION_DATABASE_URL`) — `BYPASSRLS`. Used only by
  `alembic upgrade` and `scripts/deploy.sh`'s pre-migration `pg_dump`
  backup — never by request-handling code. Migrations never run on
  container boot: the Dockerfile `CMD` only starts `uvicorn`;
  `scripts/deploy.sh` runs `alembic upgrade heads` as a one-off container
  step before recreating the app service.

Every tenant-scoped table gets `tenant_id UUID NOT NULL REFERENCES
tenants(id)`, a composite unique for anything unique-per-tenant, and
`ENABLE ROW LEVEL SECURITY` + `FORCE ROW LEVEL SECURITY` + a
`USING/WITH CHECK` policy on `tenant_id = app_current_tenant_id()`, applied
in the same migration that creates the table.

## Module registry (module control-plane step 2)

`dotmac_kernel.modules` holds `ModuleManifest` — the **versioned** expansion of
`FeatureManifest`, adding `code`, `version`, `contract_version`, and
`dependencies` — and `ModuleRegistry`, the single authority on whether the
installed module set is coherent. Both are pure and in-memory (same posture as
`capabilities` and `profiles`): they DESCRIBE installed code. They never grant
entitlement (WS2 owns that) and never deploy anything (the vendor control plane
owns that).

**Construction is validation.** `ModuleRegistry(manifests)` fails closed on four
independent checks, each with its own named error under a shared
`ModuleRegistryError` (all `ValueError`s):

| Check | Error | Why it must be fatal |
|---|---|---|
| Duplicate `code` | `DuplicateModuleError` | A code with two owners has no single authority — every downstream reference (dependency edge, profile set, capability owner) becomes ambiguous. |
| `contract_version` outside `SUPPORTED_MODULE_CONTRACT_VERSIONS` | `ModuleContractVersionError` | A module built for a different manifest generation would load half-understood. The supported set is a constructor keyword, so supporting two generations is a rollout, not a flag day. |
| Dependency on a code that is not installed | `MissingModuleDependencyError` | The dependent's routes would 500 at the first request that crosses the edge. |
| Dependency cycle | `ModuleDependencyCycleError` | No startup order exists. The message names the actual path (`a -> b -> a`), not merely "a cycle exists". |

**Deterministic startup order.** `startup_order()` is a pure function of
(declaration order, dependency edges): dependencies first, **declaration order
as the tiebreak**. Declaration order — not alphabetical — is load-bearing:
`FEATURE_MODULES` is a deliberate mount order and FastAPI route matching is
first-match-wins, so adopting the registry must not silently reorder an assembly
whose modules declare no dependencies. Every manifest shipping today declares
none, so the order is provably identical to before the registry existed
(`tests/unit/test_create_app.py::test_reference_assembly_route_order_is_unchanged_by_the_registry`).

**Installed vs. enabled are different facts.** `enabled_codes(disabled)` is the
one definition of enabled (not in `DISABLED_FEATURES`, and not
`enabled_by_default=False`). `enabled_order(disabled)` filters the startup order
to those and **fails closed when an enabled module depends on one that is not
enabled** — "dependencies satisfied" means the dependency is actually running,
not merely present on disk.

**Inventory for health/diagnostics.** `inventory(disabled)` returns
`ModuleInventoryEntry` rows (code, version, contract version, dependencies,
core, enabled) sorted by CODE, so two deployments' inventories are diffable;
`inventory_payload(disabled)` is the JSON-safe document
(`kernel_contract_version`, `modules`, `startup_order`). `create_app` publishes
both on `app.state.module_registry` / `app.state.module_inventory`. Public
`/health` deliberately does NOT report any of it — it is liveness only (see
"Health bypass"), and exposing the installed-module set there would hand an
unauthenticated caller a deployment fingerprint. The authenticated platform
diagnostics surface is a later program step and composes this payload.

**`FeatureManifest` still works, unchanged.** The registry accepts either shape,
freely mixed in one assembly, so feature packages migrate one at a time (or not
at all):

- forward — `ModuleManifest.from_feature(manifest, *, version, contract_version,
  dependencies)` carries every field across and invents nothing; an unversioned
  module records the `UNVERSIONED` sentinel `"0.0.0"`. The keyword arguments let
  the assembly pin a version or declare edges for a package it has not migrated.
- backward — `ModuleManifest` exposes read-only `name`/`routers` properties
  aliasing `code`/`api_routers`, so `mount_features`,
  `install_surface_globals`, and `CapabilityCatalogue.from_manifests` accept a
  module manifest with no call-site change. `AnyManifest` is the union used in
  those signatures.

The directive's `entity_types` and `health_checks` manifest fields are
deliberately absent until the registry code that consumes them lands — the same
directive requires CI to fail when "a declaration has no consumer", and shipping
inert fields would be exactly that. Its `settings` field is present only as
`setting_domains`: a module declares the DOMAINS it owns, while individual
`SettingSpec`s stay in the owning feature's spec module.

## Manifest declaration catalogues

Nine manifest fields work this way, and **ADR-0008 makes the shape the
standard**:
a kernel-level vocabulary whose members belong to modules is DECLARED on module
manifests and validated by a registry — never enumerated by the kernel as an enum
or a fixed list, and never pinned by a CHECK constraint on the backing column.
Each one arrived WITH its consumer, under the directive's "a declaration has no
consumer" rule.

| Declaration | Catalogue (owner) | Real consumer | When an undeclared reference fails |
|---|---|---|---|
| `FeatureManifest`/`ModuleManifest.permissions` (`PermissionSpec`: `code`, `description`, `default_roles`) | `dotmac_kernel.permissions.PermissionCatalogue`; storage-neutral `PermissionPlan` combines the definitions with assembly-owned `ProductAssemblySpec.role_grant_profiles` | `dotmac_kernel.deps.require_permission(code)` — resolves the spec and requires the actor to hold one of its `default_roles`, 403 otherwise; `create_app` exposes the read-only plan for deploy/migration adapters | at BOOT: `create_app` walks every mounted route's stamped code through that same plan and raises `UndeclaredPermissionError` |
| `...capabilities` (`CapabilitySpec`) | `dotmac_kernel.capabilities.CapabilityCatalogue` | `dotmac_kernel.deps.require_capability` | at the request (`UndeclaredCapabilityError`) |
| `...audit_actions` (bare codes) | `dotmac_kernel.audit_actions.AuditActionRegistry` | `dotmac_kernel.audit.write_audit_event` | at the WRITE, before anything is added to the session (`UndeclaredAuditActionError`) |
| `...outbox_event_types` (bare codes) | `dotmac_kernel.outbox_event_types.OutboxEventTypeRegistry` | `dotmac_durable_timers.schedule_timer` | before scheduling takes a lock or writes a timer/outbox row (`UndeclaredOutboxEventTypeError`) |
| `...provisioning_participants` (bare codes) | `dotmac_fulfillment.participants.ParticipantRegistry` | `dotmac_fulfillment.create_run` and `request_attempt` | before a run or attempt can name a participant (`UndeclaredParticipantError`) |
| `...charge_models` / `...obligation_sources` (bare codes) | `dotmac_subscriptions.vocabulary.SubscriptionVocabularyRegistry` | `dotmac_subscriptions.publish_offer_version`, `record_contract_version` and `generate_recurring_charge` | at command validation, before offer, contract or occurrence rows are written (`SubscriptionDataError` with a `vocabulary.*` reason code) |
| Non-standard billing treatment reasons (bare codes) | `dotmac_subscriptions.vocabulary.SubscriptionVocabularyRegistry` — the seven ported codes are owned by the module itself, a product adds its own through `BillingTreatmentReasonDeclaration` | `dotmac_subscriptions.preview_billing_arrangement` (and therefore `approve_billing_arrangement`) | at command validation, before an arrangement row is written (`vocabulary.undeclared_billing_treatment_reason`). The column is a plain string with no CHECK, so widening the vocabulary is not a schema change |
| `...feature_flags` (`FeatureFlagSpec`) | `dotmac_kernel.flags.FlagCatalogue` | `dotmac_kernel.flags.resolve_flag` | at resolution (`UndeclaredFlagError`) |
| `...setting_domains` (bare codes) | `dotmac_kernel.setting_domains.SettingDomainRegistry` | `dotmac_kernel.settings_resolver.upsert_by_key`/`ensure_by_key`, and the settings admin API's path-to-domain lookup | at the WRITE (`UndeclaredSettingDomainError`); an unknown domain in a URL is a 404 |

These catalogues are siblings of `CapabilityCatalogue` (WS1) in shape and
posture, and gate
different questions — capability: "is this TENANT entitled?"; permission: "does
this ACTOR hold it?". A code has exactly one owning module; two declarations of
the same code raise on catalogue construction. Kernel-owned process-wide
catalogues are installed by `create_app` from the INSTALLED module set (not the
enabled subset — disabling a module must not turn a real code into an
undeclared one), the same pattern `install_surface_globals` uses. The
Fulfillment and Subscriptions registries are built from that same installed set
and passed into their owning service boundaries. Permissions default to an
EMPTY catalogue so a missing authorization installer denies safely. Audit
actions, outbox event types and setting domains distinguish NOT INSTALLED from
INSTALLED-EMPTY: the former raises `AuditActionsNotInstalledError` /
`OutboxEventTypesNotInstalledError` / `SettingDomainsNotInstalledError`, while
the latter rejects every member as undeclared. The asymmetry is about what
each default DOES — an uninstalled permission catalogue denies, the safe answer
for an authorization check; an uninstalled write-path registry would reject
writes inside the caller's transaction and turn a wiring mistake into a failed
business operation.

`setting_domains` is the reason `domain_settings.domain` is a plain
`String(120)` rather than the five-member `sa.Enum` it was through kernel
`0.1.0a13` (migration `0014` drops `ck_domain_settings_domain`). This repo
declares five domains; `dotmac_erp` runs twenty-one, and a kernel that
enumerates its consumers' domains needs a migration every time a product invents
one. `SettingDomain` is correspondingly an open `str` subclass — kernel-owned
domains are bound as class attributes (`SettingDomain.branding`), a product
constructs its own (`SettingDomain("payroll")`).

Validation lives at the boundary that USES a member, not at declaration time:
declarations are import-time and process-global while a registry belongs to one
assembly, so `create_app` deliberately does NOT check registered `SettingSpec`s
against the installed registry — importing the settings feature anywhere would
otherwise break every synthetic assembly's boot. That assembly-wide invariant is
checked in CI instead, in both directions
(`test_every_registered_spec_names_a_declared_domain`,
`test_no_orphan_setting_domain_declarations`).

`PermissionSpec.default_roles` is the code-declared DEFAULT binding, standing in
the same relation to a future tenant-configurable role→permission grant that a
`SettingSpec.default` does to a `domain_settings` row — not a second authority.
`require_permission` is a strict generalisation of `require_role`, which remains
supported as the raw role check; both share one `_holds_any_role` query. The
`rbac` feature's JSON routes are migrated to `require_permission`; every other
feature still uses `require_role` and migrates one at a time.

#### Permission provisioning ownership (Stage 1, 2026-08-26)

Permission definitions and product role mappings have different owners. A
module declares the opaque permission code, description, and owning module in
its manifest; it cannot name the role algebra of every assembly that may adopt
it. An assembly declares exact baseline mappings through
`ProductAssemblySpec.role_grant_profiles`. The assembly also declares its role
vocabulary through `role_definitions`, including the explicit policy for a
missing role. A permission with no baseline grant is valid and remains
available for an operator-owned assignment.

`dotmac_kernel.permission_provisioning.PermissionPlan` is the pure composition
contract between those authorities. It normalizes a positive profile version
and emits a deterministic SHA-256 digest for preview and drift evidence.
`create_app` builds it from the INSTALLED manifests, attaches it as
`app.state.permission_plan`, and uses it for the existing mounted-route
declaredness check. That is a read-only startup consumer, not a writer:
persistence adapters belong in product migrations or deploy tooling and
compare their rows with `PermissionPlan.diff`.

The Stage 1 diff is additive only. It may propose a missing permission row, a
missing link, and a missing product role only when that role's assembly-owned
definition has `create_if_missing=True`. It never creates an implicit role,
updates an existing description, reactivates or renames a permission or role,
removes a grant, or deletes unknown/operator state. A missing role without
that opt-in and any inactive desired role or permission are explicit
conflicts. Subtractive reconciliation is not safe until role-permission policy
claims have provenance, because an effective link alone cannot distinguish an
operator's intent from a baseline profile's.

The reference assembly's `starter.admin` profile is an exact explicit shadow of
the nine current `admin` bindings. It is deliberately not derived as “admin
gets every installed permission”: a later operator-only declaration must not
silently expand that role. For this stage, `authorize_party` continues to read
`PermissionSpec.default_roles`; the shadow profile changes no request decision
and gives downstream products an additive adoption seam.

#### The permission seam is authentication-neutral (kernel `0.1.0a62`)

`dotmac_kernel.deps.authorize_party(db, *, tenant, party, code)` is the ONE
place a permission code becomes a role check — the authorization counterpart to
`authenticate_request` one layer down (see "Auth flow: cookie + bearer share one
seam"). It takes an ALREADY-established party and returns a bool; it reads no
header, no cookie and no session.

| Surface | Authenticated by | Refusal | Guard |
|---|---|---|---|
| JSON API | `require_user_auth` (bearer) | 403 | `require_permission(code)` |
| A separate assembly's portal | its own cookie guard | 403 (branded if it likes) | `permission_guard(code, authenticated_party=…, denied=…)` |

`permission_guard` is the route-level factory both go through; `require_permission`
is now that factory bound to the bearer flow and holds no decision of its own.

`denied` answers the AUTHORIZATION question and must never redirect to login: it
runs only once `authenticated_party` has succeeded, so the actor is signed in,
and a redirect would loop against a login page that finds a valid session.
Unauthenticated is `authenticated_party`'s own refusal (a `WebAuthRedirect` on a
cookie surface). "Who are you?" redirects; "may you?" refuses.
Guards built by an ASSEMBLY carry the same `PERMISSION_CODE_ATTR` stamp, so they
keep `create_app`'s boot-time declaration check instead of degrading a typo'd
code into a runtime 500.

Why it exists: `dotmac_workspace` (ADR-0021's third plane) authenticates with
its own `dmws_session` cookie, deliberately not the `access_token` a product
portal reads. Its blocker B1 recorded that `require_permission` was welded to the
bearer header and `require_web_auth` read the wrong cookie while hardcoding
`"admin"` — leaving the assembly to hand-roll the role query, which is how a
plane falls behind a kernel security fix (ADR-0015's academy failure). Enforced
by `tests/architecture/test_permission_seam_is_single.py` (exactly one
code→roles binding) and `tests/unit/test_permission_seam.py` (a foreign cookie
reaches the decision a bearer header reaches).

`web_deps.require_web_auth`'s hardcoded `"admin"` role is UNCHANGED and remains
the phase-3 item its docstring records — this seam is what a fix will be built
on, not the fix itself. ADR-0006's 2026-08-25 amendment now decides the SHAPE of
that fix: authentication (a facet-declared profile) separates from facet
admission (a declared permission evaluated here) from route authorization (the
module's own guards), and the role leaves the authentication layer entirely. Not
implemented — see that amendment and
`docs/inventories/facet-composition-blast-radius-2026-08-25.md`.

### Release-bound product manifests

`ProductAssemblySpec.name` and its installed module manifests are the source of
one canonical, publishable product fact. `ProductManifestSnapshot.from_assembly`
validates the module registry, builds `CapabilityCatalogue` from the INSTALLED
set, and emits canonical JSON containing only the stable product code, the
release version supplied by the product's build, and sorted declared capability
codes. Its `sha256:` digest is the digest of those exact bytes.

The ownership split is load-bearing:

- the kernel owns the pure snapshot schema, encoding, digest and parser;
- each product assembly owns its code, release version and manifest members;
- `dotmac-release-catalog` associates the document digest with exact artifact
  bytes as an attestation, without interpreting the document; and
- a consumer such as the Vendor Control Plane verifies that attestation and
  projects it through its domain port.

There is no kernel product table, list of ERP/CRM/Sub, release selector, network
fetch or entitlement decision. `ModuleRegistry.inventory_payload` remains
deployment diagnostics; `ProductManifestSnapshot` is deliberately narrower and
release-portable. The product-first evidence and first retirement gate are in
`docs/inventories/product-manifest-sources.md`.

### Release-bound product database catalogues

Database table/column structure is a separate build-once release fact. The capability
manifest above deliberately says nothing about persistence, so it remains
byte-for-byte unchanged. `ProductDatabaseCatalogSnapshot` instead freezes the
complete selected database composition for one product release as canonical
JSON: PostgreSQL major, exact schema extent, typed lineage fragments, relation
kind, persistence plane, ordered columns, PostgreSQL type identity and
modifier, nullability, default/identity/generated state, and collation. Its
digest is the digest of those exact bytes.

Column ordinals are PostgreSQL `pg_attribute.attnum`, not a renumbered display
position. Dropping a column leaves a gap in later ordinals; declarations and
observations retain that gap and require only positive, unique, strictly
increasing ordinals. Renumbering surviving columns would conceal physical
drift and prevent a catalogue from describing an existing product lineage.

Schema v1 says `scope=tables_and_columns`. It makes no claim about constraints,
indexes, triggers, privileges or policies; those require an explicit later
contract rather than interpreting absence as agreement.

The ownership chain has no live-database authoring path:

- `ModuleManifest.tables` and `platform_tables` remain the only module table
  and plane declaration; a module database-catalogue contribution may describe
  columns only for that exact set, at one named lineage head;
- `ModuleDatabaseCatalogSnapshot` binds one contribution to distinct
  distribution, module-release and manifest-contract coordinates. It is
  independently publishable and never claims unrelated product schemas;
- `ProductDatabaseCatalogSnapshot.from_assembly` validates the installed module
  registry and explicit plane selections, derives module schema/owner/plane,
  composes explicit kernel/assembly/extension host fragments, and refuses any
  missing, extra or duplicate relation;
- `dotmac-release-catalog` provides distinct, singular module and
  product database-catalogue attestation writers. They parse held canonical
  bytes, check the expected digest and snapshot subject/version against the
  release artifact, and persist a digest/URI pointer without fetching the URI.
  This does not itself prove that artifact bytes produced those tables or that
  a product assembly is complete; the release producer must independently
  retain artifact provenance and construct the product snapshot with
  `from_assembly`. The module's declared kernel floor names the earliest
  published kernel with
  `product_database_catalog`; `scripts/module_floor_check.sh` proves it; and
- `dotmac_kernel.database_catalog_comparator` owns the read-only PostgreSQL
  observation and pure, digest-bound verifier. Its stable IDs are
  `dotmac.postgresql-tables-columns-observation/v1` and
  `dotmac.database-catalog-tables-columns-comparator/v1`.
  `dotmac_kernel.migrations.catalog` retains its RLS/grant authority; neither
  path derives a declaration from the target.

The human `docs/MODULE_CATALOG.md` remains a generated discovery projection and
owns none of these facts. `ProductManifestSnapshot` remains the independent
product/capability attestation. Keeping both documents separate lets a
stateless contract catalogue publish its capability manifest without acquiring
an empty or fictitious persistence identity, and lets Release Catalog join
both claims to the same immutable artifact once it adopts this contract.

## Module database namespaces and migration lineage (ADR-0006 D1)

As-built in kernel `0.1.0a12`. The authority is `dotmac_kernel.namespaces`; the
build-time enforcement is `dotmac_kernel.migrations.gate`; the post-migration
enforcement is `dotmac_kernel.migrations.catalog`.

| Concern | Owner | Enforced by |
|---|---|---|
| Which schema a module owns | `ModuleManifest.short_code` → derived read-only `db_schema` = `mod_<short_code>` | frozen dataclass + `module_schema()` as the only builder |
| That the allocation never moves | `namespaces.MIGRATION_OWNER_LEDGER` (checked-in, kernel-shipped) | unconditional whole-ledger validation, then `NamespaceRegistry.from_manifests` → `UnallocatedNamespaceError` / `NamespaceAllocationError` |
| No two owners share a schema / prefix / branch label / table | `NamespaceRegistry` | construction raises `DuplicateSchemaError` / `DuplicateMigrationPrefixError` / `DuplicateBranchLabelError` / `DuplicateTableOwnerError` |
| Coherent composed migration graph | `migrations.gate.run_gate` | `make migration-gate` (in `make check`; the CI `quality` matrix, which `docker-build` now `needs`) |
| Per-module persistence-plane intent | `ProductAssemblySpec.module_planes` (`ModulePlaneSelection`) checked against each manifest's `supported_plane_sets`; prerequisite bindings remain provider mappings only | assembly construction + `migrations.gate.run_gate`; `NamespaceRegistry.expected_tables` and selectable migrations consume the same declaration (ADR-0028) |
| Live RLS/grant contract per module schema | `migrations.catalog.audit_live_schemas` | `tests/test_module_schema_catalog.py` (Postgres) |

**`public` is a compatibility namespace, not a shared one.** It belongs to the
kernel and to this one host assembly — every feature in `app/features/` is a
host feature whose tables live there, owned by the `assembly` migration owner,
and none declares a `short_code`. An installable module may not claim it
(`HostSchemaClaimError`), and that closure is what makes the verified cross-repo
collisions in `docs/inventories/migration-collisions.md` (`parties`,
`audit_events`, `roles`, `user_credentials`, …) structurally impossible rather
than merely unlikely.

**Attribution, not a second map.** Each version location is attributed to an
owner through its lineage root's branch label. `alembic_version` remains the
migration truth, and `ModuleRegistry.inventory_payload()["migration_owners"]`
plus `GateReport.attribution` are what make an individual row in it explainable.

**Static enforcement follows the real upgrade path.** The composed gate walks
local helpers reachable from `upgrade()`, resolves typed Alembic metadata and
module-level `module_schema()` constants, checks both imperative and inline
foreign keys, and rejects a fully qualified DDL operation when its target is
another owner's schema. An empty manifest `tables` declaration means “owns no
tables”; it is never an allow-all escape hatch. The live gate then checks the
manifest against the migrated catalog in both directions. The host `public`
audit remains a separate policy adapter because it owns explicit platform and
split-policy exceptions, but it reuses the kernel catalog's UNIQUE-constraint
query and enforces the same composite-unique rule for tenant-scoped tables.

**Published migration bytes are immutable history.** The release-history guard
reconstructs every enrolled migration from its release tag and compares
the blob digest with the checked-in tree; a new revision is the only repair
path. Approvals carries the one explicit historical exception:
`ap_0001_approvals` shipped three byte sets across a1–a4 before enrolment; a5
reuses the canonical third set and adds `ap_0002`. The
exception freezes that exact tag/digest census, permits only the latest shipped
bytes in the current tree, and refuses a fourth variant. A PostgreSQL upgrade
matrix builds each released meaning, seeds both selected planes, and proves the
canonical additive `ap_0002` upgrade preserves rows and plane selection; a5
then shipped that additive revision after registry verification. This
records damage already in the registry; it does not legalise future in-place
edits.

**Two grandfathered lineages.** `kernel` (`0001_initial_tenant_schema` …
`0012_platform_outbox`) and `assembly` (`a001_adopt_cfd` …
`a003_revocation_lists`) predate D1. Their ids are already recorded in live
`alembic_version` rows, so `MigrationOwner.legacy_revision_pattern` preserves
their original format and exempts them from the strict
`<prefix>_<sequence>_<slug>` and `schema=` rules. Every installable module gets
the strict rules; no existing revision was renamed.

## Feature-mount sequence

0. `dotmac_kernel.create_app` builds a `ModuleRegistry` from `spec.modules`
   FIRST and derives the startup order from it (see "Module registry" above).
   An incoherent module set raises here, before a single route is mounted.
   Steps 2–3 and 6 below all walk that one order.
   The same spec explicitly controls whether the online kernel platform surface
   exists (`platform_surface_enabled`), declares product configuration checks
   and ordered lifespan startup hooks, and supplies a typed product browser
   security policy. Products do not remove routes after construction or mutate
   kernel settings to express those decisions.
1. `app/main.py` imports `FEATURE_MODULES` from `app/features/__init__.py`
   — a plain list of dotted module paths (currently `tenants`, `auth`,
   `parties`, `rbac`, `settings`, `custom_fields`, `licensing`, `web`).
2. `dotmac_kernel.features.load_manifests(FEATURE_MODULES)` imports each
   `<module>.feature` submodule via `importlib` (so core never statically
   imports `app.features`) and collects its `feature: FeatureManifest`
   (`name`, `routers`, `web_routers`, `nav`, `core: bool`,
   `enabled_by_default: bool` — see "Capability model" above for the
   `web_routers`/`nav` fields).
3. `create_app` builds `WebSurfaceRegistry` from the enabled module order and
   the assembly's facets/profiles/UI/browser-capability declarations before any
   browser route mounts. It composes the namespaced template loader, validates
   facet shells immediately, and resets contract-1 process globals.
4. `mount_features(..., web_enabled=False)` mounts enabled API routers. When
   `WEB_ENABLED=true`, the assembly/static mounts are added and
   `mount_web_surfaces` mounts every legacy-adapted and contract-2 browser route
   with request-scoped state. `WEB_ENABLED=false` omits the entire browser graph
   and static assets while leaving APIs intact.
5. Mount failures in a `core: True` feature re-raise (fails startup); a
   failure in a non-core feature is logged and skipped (fault isolation) —
   the app still boots without it.
6. `tests/architecture/test_feature_manifests.py` guarantees every package
   under `app/features/` on disk is registered in `FEATURE_MODULES` and that
   each manifest's `name` matches its package name — so a feature can never
   silently go unmounted or be mounted twice under a different name. The
   same test module's `test_nav_items_paths_exist_in_web_routers` guarantees
   nav↔route coherence (see "Capability model" above).
7. Separately, still inside `lifespan` and gated by `settings.seed_on_startup`,
   each enabled manifest's optional `seed` hook is dispatched via
   `asyncio.to_thread` (it does sync DB I/O); a seed is DEFERRED and
   NON-FATAL — a failure is caught, logged (`Feature %s seed skipped: %s`),
   and swallowed rather than propagated, so an unreachable DB at boot can
   never take startup down (seeds are idempotent; the next boot retries).

After every router is mounted, the permission and capability declaration
validators walk each route's effective dependency tree. FastAPI through 0.115
stores included `APIRoute` objects directly; FastAPI 0.140 stores lazy included
routers and exposes their prefix-aware dependency trees through
`effective_route_contexts()`. The kernel consumes either representation through
one duck-typed walker, so a framework storage optimization cannot turn a
fail-closed declaration check into a vacuous pass.

## Error handling

`dotmac_kernel/exceptions.py` defines a `DomainError` hierarchy:
`NotFoundError` (404), `BadRequestError` (400), `ConflictError` (409),
`UnauthorizedError` (401), plus FastAPI's own `RequestValidationError`
(422) and an unhandled-exception catch-all (500). `dotmac_kernel/errors.py`
maps every one of these to the same JSON envelope:

```json
{"code": "not_found", "message": "...", "details": null, "request_id": "..."}
```

`request_id` is pulled from `dotmac_kernel.logging.request_id_var`, the same
context var `ObservabilityMiddleware` populates — so every error response
is correlatable with the structured request log line. Services raise
`DomainError` subclasses and let them bubble; routers never construct
`HTTPException` themselves for domain-level failures (see
`test_routers_do_not_issue_direct_queries` — routers stay thin; the
corollary is that error translation is centralized in `dotmac_kernel/errors.py`,
not scattered per-router).

## Transaction authority (control-plane security Task 4)

There is exactly ONE transaction authority in this codebase, and since
2026-08-26 (ADR-0066) it lives in TWO files:
`dotmac_kernel/session_runtime.py` holds the implementation — `DatabaseRuntime`,
the class a product instantiates with its own DSNs, credentials and tenancy
table — and `dotmac_kernel/db.py` is the reference assembly's single INSTANCE of
it, built from the kernel's `Settings` at import. That is one authority in two
files, not two authorities: the behaviour has to live somewhere a second
deployment can construct, and a module whose job is to construct the class
cannot also be forbidden from constructing its sessions. What stays forbidden is
a THIRD place. `dotmac_kernel.db`'s public names are unchanged and still bound
once at module scope, so dependency identity holds; it remains eager on purpose
(entering it still costs a `DATABASE_URL`, which is what keeps the package-root
import guards able to tell a module-level import from a deferred one).

The contract:

- **The boundary owns commit/rollback.** `get_db` and `get_platform_db`
  (request boundaries) and `platform_session` (the non-request boundary for
  lifespan hooks/jobs) construct the session, commit on success, roll back
  on error, and close. Nothing else does. Each is a thin binding over the
  runtime's own generator/context manager, and the runtime's boundaries take a
  tenant id rather than a `Request` — reading tenancy off request state is a
  framework concern, so a product with its own request pipeline writes its own
  four-line adapter and inherits everything below it.
- **Route dependencies enter the boundary lazily.** `dotmac_kernel.deps`
  exports thin `get_db`/`get_platform_db` generator adapters whose only action
  is a function-local import followed by `yield from` the corresponding
  `dotmac_kernel.db` owner. This keeps module manifests and routers importable
  before an assembly resolves `DATABASE_URL` without creating a second session
  or transaction authority.
- **Tenant middleware enters the resolver boundary lazily.** The middleware is
  imported by the public `create_app` composition surface, but importing a
  constructor is not tenant resolution. Its named `resolver_session` adapter
  performs a function-local import of the eager `dotmac_kernel.db` owner only
  when `_resolve` handles a request. Consequently `create_app` is importable
  with both database URLs and `PYTHONPATH` removed, before the consumer-owned
  `psycopg` driver exists; the clean-wheel consumer gate proves that exact
  order and asserts neither `dotmac_kernel.db` nor `psycopg` entered
  `sys.modules`.
- **Services only mutate and flush.** A feature service never calls
  `db.commit()`, never calls `db.rollback()` directly (hard rule; see the
  savepoint section below), and never constructs a session of its own.
- **Expected conflicts use `conflict_savepoint`** — roll back the SAVEPOINT,
  not the transaction (next section).
- **Non-request callers use a named boundary, never a bare factory.**
  `tenant_session` / `tenant_session_by_slug` for work acting as one tenant
  (CLI, jobs, workers), `platform_session` for work acting as the platform, and
  `resolver_session` for the one legitimate unscoped case — deciding WHICH
  tenant to scope to, which cannot itself be scoped. Reaching for
  `SessionLocal` instead is the one mistake nothing here can catch for you: RLS
  fails **closed**, so an unscoped session returns zero rows rather than
  raising, and the caller cannot tell an empty tenant from an invisible one. A
  `dotmac_academy_app` audit command did exactly this and reported a clean
  estate against a database holding 333 banks. `resolver_session` additionally
  RESETs the tenant settings before yielding and expunges before rolling back —
  a scope inherited from a pooled connection would filter the resolver's own
  lookup, and a valid host would resolve to no tenant at all.
- **The tenant scope is transaction-local, and re-armed rather than reset.**
  `tenant_scope` (ported from `dotmac_erp`'s `tenant_scope_for_session` under
  `AGENTS.md` rule 22; see `packages/dotmac-kernel/EXTRACTION.toml`) primes the
  already-open transaction and installs an `after_begin` listener that re-arms
  every later one, then removes the listener on exit. Both halves are needed and
  each alone carries the other's hazard: a session-level `SET` survives commits
  but also survives the session, riding the pooled connection out to the next
  borrower — which is why the old code carried a reset-and-commit dance in a
  `finally`, only as good as the process surviving to run it — while a bare
  `SET LOCAL` cannot leak but dies at the first commit inside a CLI loop or a
  worker drain, leaving the rest running unscoped against a fail-closed policy
  (and `expire_on_commit` then reloading an attribute yields an
  `ObjectDeletedError` on a row the session itself just wrote). Re-arming takes
  the safe half of each: every transaction is scoped, nothing outlives one, and
  there is no reset left that can be skipped.
- **`app.current_tenant` is a schema contract, not a knob.** Every composed
  module lineage writes its RLS policies as
  `tenant_id = public.app_current_tenant_id()`, which reads
  `current_setting('app.current_tenant', true)`, and
  `dotmac_kernel/migrations/verify.py` pins those semantics as a prerequisite
  marker. `DatabaseRuntime` therefore always primes that exact name and offers
  no way to replace it; `legacy_tenant_settings` primes ADDITIONAL names
  alongside it, in the SAME statement and with the same value, for tables a
  product has not yet moved onto a composed lineage (ERP's
  `app.current_organization_id` is the motivating case). One statement, because
  a failure between two would leave the canonical setting armed and a legacy one
  stale — a working scope over the wrong rows. The set is a shrink-only ratchet
  owned by the adopting product's own architecture test; the starter's instance
  declares it empty and keeps it empty.
- **Caller-session services do not enter the engine owner.** Kernel domain
  services such as consent, delivery, idempotency and external identity accept
  the installing assembly's `Session`. Their savepoint mechanic lives in the
  private, engine-free `dotmac_kernel._transactions`, exposed to assemblies as
  `dotmac_kernel.transactions.conflict_savepoint`. `dotmac_kernel.db` retains a
  compatibility re-export for the reference assembly. This is an
  implementation seam, not a second boundary or transaction authority: it
  constructs no engine/session and never commits or rolls back the caller's
  outer transaction (ADR-0024 amendment, 2026-08-19).
- **No route, task, or service constructs an ad hoc session.** The old
  `dotmac_kernel/unit_of_work.py` (`UnitOfWork`, `ConcurrencyConflict`) was a
  second, zero-consumer transaction authority — DELETED under the stronger
  SoT rule (zero consumers → delete), not kept "just in case". The same rule is
  why ADR-0066 added no `database` slot to `ProductAssemblySpec`: a product
  constructs its runtime in its own composition root, so a field nothing reads
  would be the very shape this rule deletes.
- **Provisioning's `SET LOCAL` idiom:** platform-session code that must
  write tenant-scoped rows (atomic tenant provisioning) establishes RLS
  context ON the current transaction with
  `db.execute(select(func.set_config("app.current_tenant", str(tenant.id),
  True)))` after flushing the tenant row — same `set_config(..., is_local
  := true)` idiom `get_db` uses, because `platform_api` has no BYPASSRLS.

Enforced by `tests/architecture/test_session_authority.py` (AST-based: no
module outside the two declared authorities — `dotmac_kernel/session_runtime.py`
and `dotmac_kernel/db.py` — may call `SessionLocal()`, `PlatformSessionLocal()`,
`sessionmaker(...)`, or construct `Session(...)`; no feature module may import
`sessionmaker`; sensitivity self-tested).
`test_every_declared_authority_still_exists` fails loudly if either declared
path is renamed or deleted, so the exclusion cannot silently widen into a hole
— or worse, leave a moved file being scanned as ordinary code. The call
allowlist is EMPTY and is worth keeping that way: its one entry was
`dotmac_kernel/middleware/tenant.py`, which opened a bare `SessionLocal()`
because the resolver runs before any route dependency exists and nothing on the
public surface named that need. `resolver_session()` names it, so the exception
disappeared rather than being documented, which is the outcome an allowlist
should be aiming for. `test_allowlist_is_still_needed` fails on a stale entry,
which is how that one was found.

`tests/architecture/test_session_runtime_is_engine_free.py` asserts the two
modules' deliberately OPPOSITE import contracts as a pair, in a subprocess with
`DATABASE_URL` removed rather than blanked: importing `session_runtime` must
succeed and must not drag `dotmac_kernel.db` in behind it, while importing
`dotmac_kernel.db` must still fail. `tests/unit/test_session_runtime.py` pins
the priming rules (canonical always first, legacy names in one statement, the
canonical name refused as a legacy entry, names validated against the plain
Postgres identifier grammar because `set_config` cannot bind them, listener
removed even when the block raises), and `tests/test_tenant_session_scope.py` is
the Postgres canary for the behaviour itself — including
`test_a_bare_session_is_blind_not_loud`, which asserts that the BROKEN path is
silent.

## Conflict handling: savepoints preserve RLS context (2b.1-T2, finding F3)

`get_db` (`dotmac_kernel.db`) owns the request's outer transaction and issues
`SET LOCAL app.current_tenant` on it once, for RLS. The pre-2b.1 convention
at every expected-conflict site (duplicate email/slug/role-grant, etc.) was
`try: db.flush() except IntegrityError: db.rollback(); raise
ConflictError(...)` — but a bare `db.rollback()` rolls back that ENTIRE
outer transaction, discarding the `SET LOCAL` along with it. Any DB access
the caller's `except ConflictError` handler performed afterwards (a web
handler re-rendering a form from an already-loaded ORM object, or
re-querying a list for the re-render) then ran with no tenant context set —
under `FORCE ROW LEVEL SECURITY` that fails closed: either an
`ObjectDeletedError` re-loading an expired attribute, or a silently empty
result set (500s or blank re-renders, invisible on SQLite since it can't
enforce RLS at all — this is why the canary requires Postgres).

`dotmac_kernel.transactions.conflict_savepoint(db)` is the engine-free public
spelling for caller-owned sessions; `dotmac_kernel.db.conflict_savepoint(db)`
remains the reference assembly's compatibility spelling. The helper is a
context manager around `Session.begin_nested()` (a `SAVEPOINT`
scoped INSIDE the outer
transaction): on clean exit it commits the SAVEPOINT (a no-op release, not
the outer `COMMIT`); on any exception it rolls back ONLY the SAVEPOINT —
leaving the outer transaction and its `SET LOCAL` fully intact — then
re-raises unchanged. Every conflict site (parties create/update ×2 each,
`rbac` `create_role`/`assign_role`, `tenants` create, `auth` register,
`custom_fields` create) follows the same shape:

```python
try:
    with conflict_savepoint(db):
        db.add(row)
        db.flush()
except IntegrityError:
    raise ConflictError(...)
```

**The mutation must happen INSIDE the `with` block, never before it** —
entering a nested transaction auto-flushes any already-pending/dirty
objects on the session before the SAVEPOINT is actually established, so a
`db.add(row)` issued before `conflict_savepoint` would let THAT auto-flush
emit the conflicting statement with no savepoint yet in place to protect
the outer transaction, reintroducing the exact bug this helper exists to
fix.

Enforcement: `tests/architecture/test_no_feature_rollback.py` bans a bare
`db.rollback()` anywhere in `app/features/*/service.py` (this is also
CLAUDE.md's hard rule). `tests/test_conflict_rls_context.py` is the
Postgres canary — a duplicate-email person edit and a duplicate role grant,
both via the web flow, asserting a 200 re-render WITH correct data (grants
list still populated; edit form re-renders with the field error) rather
than the pre-fix 500/empty-render. This canary was RED against pre-2b.1
`main` by construction (the bug is invisible on SQLite, where these tests
cannot even run).

`tests/architecture/test_kernel_caller_session_independence.py` separately
guards application composition: it rejects even a deferred
`dotmac_kernel.db` import from caller-session services and runs consent,
idempotency and delivery with a valid caller-owned session while the kernel
`DATABASE_URL` is deliberately unparsable. This proves a service invocation
cannot accidentally construct a second configured runtime.

## Semantic identity and exact replay ordering (ADR-0064 / ADR-0014)

The kernel and module contracts distinguish three identities that are easy to
collapse incorrectly:

| Identity | Answers | Canonical shape |
|---|---|---|
| mutation revision | which accepted mutation came later? | explicit sequence or optimistic-concurrency token |
| semantic content identity | is this the same complete normalized evidence? | algorithm-versioned fingerprint (`cv1:…`) |
| idempotency identity | has this operation key already produced an effect? | `(scope, key)` plus the separately stored request fingerprint |

A generic ORM `version` or `updated_at` is only the first row. It cannot become
the second or third merely by being copied into a field with a stronger name.
When an inter-application fact needs ordering and semantic equality, it carries
both explicitly. A digest-field change creates a new algorithm namespace and a
named cutover; persisted old submissions replay their stored bytes/version
rather than being recomputed into duplicate evidence.

At-most-once writers establish trust before replay and replay before mutable
business preconditions:

`authenticate/authorize → canonicalize/fingerprint → replay-or-conflict → mutable preflight → effect + ledger`

The replay position matters because overlap, uniqueness and "already open"
checks observe the state the first success created. Re-running those checks on
an exact retry makes the operation reject itself. Authorization, tenant scope,
command validity and fingerprint conflict remain before replay so a stored
result is neither leaked nor returned for a different request.

As built, `dotmac_kernel.idempotency.execute_once` and its platform peer validate
the key, resolve replay/conflict, and only then call the operation.
`dotmac_subscriptions.treatments.approve_billing_arrangement` likewise resolves
and fingerprint-checks the stored arrangement before rerunning its overlap
preview. The architecture guard checks both orders and rejects direct
`.version`/`.updated_at` flows into semantic identity sinks; the treatment unit
canary builds one command once and submits it twice.

Enforcement:
`tests/architecture/test_semantic_identity_and_replay.py`,
`tests/unit/test_subscriptions_treatments.py`; encoding and cutover contract:
ADR-0064; transaction/result-replay contract: ADR-0014.

## External-identity login: the decision and the session are one locked step (kernel `0.1.0a64`)

`dotmac_kernel.external_identity` exposes two entry points that answer the same
question, and only one of them may end in a session.

| Call | What it is | May a session follow? |
|---|---|---|
| `resolve_external_identity` | a READ — no lock, no write | **No.** True when it looked; not necessarily when you act. |
| `finalize_external_login` | the LOGIN path — locks, re-checks, stamps | **Yes**, and only this one. |

The defect this closes: a caller that resolved and then issued its own session
left two statements with a gap between them, and an administrator could disable
the binding in the gap. The result is a live session derived from an identity
revoked before that session existed — and both halves look successful. The
disable recorded a disable, the row is inactive, every later resolution refuses,
and the session the disable existed to prevent outlives it. Returning
`binding_id` from the resolution did not close this; that removed a redundant
READ, and the window is between a read and the WRITE that depends on it.

`finalize_external_login` takes the binding `SELECT … FOR UPDATE`, re-checks
`is_active` and the party's own state (`is_active`, `party_type == person`)
while holding that lock, stamps `last_authenticated_at`, and returns the party
— so the caller adds its session in the SAME transaction with the row still
held. `disable_external_identity_binding`'s `UPDATE` needs that same row lock,
so the two serialize: the login holds it first (session issued, disable commits
behind it) or the disable does (login blocks, re-reads `is_active = False`,
refuses). Every refusal is `None`; a typed error per reason would let a caller
distinguish "no such subject" from "disabled binding", which is a
subject-enumeration oracle handed to whoever can drive a login.

Two implementation details are load-bearing rather than incidental. The locking
read matches on the identity tuple alone and re-checks `is_active` in Python, so
the re-check is visible to a reader and does not silently stop being one under
an isolation level that raises rather than re-evaluates (the re-read assumes
READ COMMITTED; REPEATABLE READ raises a serialization failure, which also fails
closed). And both reads pass `populate_existing=True`: without it a session that
had already loaded either row would get the identity map's copy, so the lock
would be taken and then a value cached from BEFORE the concurrent disable
examined — a lock guarding a stale attribute is worse than no lock, because it
reads as correct.

**One gap closed in a67, one stated and still open.**

Disabling a binding now RETRACTS the sessions it produced.
`auth_sessions.external_identity_binding_id` records which binding minted a
session, and `disable_external_identity_binding` revokes on that column in the
same transaction, under an explicit `SELECT … FOR UPDATE` on the binding row.

Ownership, since three writers touch this and only one owns each fact:

| fact | owner |
|---|---|
| whether a binding is active | `dotmac_kernel.external_identity` |
| whether a session is revoked | `dotmac_kernel.external_identity` (one writer) |
| that a session EXISTS at all | the assembly that mints it |
| which binding a session came from | the assembly, stamping the kernel's answer |

The assembly mints sessions and therefore stamps the column, using the
`binding_id` `finalize_external_login` returned and nothing else. The kernel
cannot enforce that — it does not mint sessions — so the rule is stated in the
module docstring and the cost of ignoring it (an unattributable session) is
stated with it. What the kernel DOES own is revocation: a product that revoked
sessions itself would be a second writer of `revoked_at`, so the helper is
private to the disable path.

The FK carries `party_id` deliberately —
`(tenant_id, party_id, external_identity_binding_id)` → `(tenant_id, party_id,
id)`. Without it a session could cite a binding belonging to a different party
in the same tenant, and selective revocation would revoke the wrong person.

**Still open:** the login re-reads the party but does not LOCK it. `parties` has
many other writers, and locking binding-then-party would deadlock against any
transaction that touches a party before its binding. The answer is unchanged —
revoke the sessions, do not lock the world.

`record_external_authentication` is DEPRECATED: it stamps a decision the caller
already made, which is the second half of the racy pair. It is retained only for
a step-up ceremony that mints no session, and removed in the next minor unless
such a consumer is named.

Proof: `tests/unit/test_external_identity.py` (logic, plus
`test_the_unit_lane_cannot_see_the_lock` — SQLite compiles `FOR UPDATE` away, so
the unit lane would pass against an implementation that never locked) and
`tests/test_external_identity_login_race.py` (bounded two-session Postgres
canary; the winner takes the row lock BEFORE the barrier, so each direction is
forced rather than hoped for).

## Human credential lifecycle (`dotmac_kernel.credential_lifecycle`)

A kernel-owned CONTRACT, published and tested, and composed by nothing in this
assembly. It is recorded here because a new concept gets its owner row before it
gets a consumer — not because the reference assembly routes through it today.
`app.features.auth.service` and `app.features.tenants.service` remain the
as-built credential writers, and both appear in the frozen debt baseline.

**What it owns.** Every decision about a human password credential: provision,
verify, complete an individually authorized reset, plan and apply an approved
cohort force reset. `dotmac_kernel.security` keeps the primitives; the facility
is the one owner ABOVE them.

**Why it exists.** Measured at exact commits (see the inventory):
`dotmac_sub` has FOUR verification owners across four files, each re-deriving
active, locked and reset-required for itself because a boolean cannot carry the
answer; and eleven files call `hash_password`, two of them seed scripts. The
narrower reason is sharper still — `reseller_onboarding._create_credential` took
a caller-supplied `password` no supported caller ever passed, and that unused
parameter is how one value reached 24 external organisations. Sub removed it;
this facility makes the shape unrepresentable rather than merely absent.

**The three structural properties.**

1. *Provisioning has nowhere to put a secret and nowhere to return one.* Material
   is generated from an injectable cryptographic source, hashed, marked
   reset-required, persisted through the product adapter in the caller's
   transaction, and forgotten. The subject reaches a usable credential only
   through a durable RECOVERY INTENT and the product's own channel.
2. *Verification returns `accepted` / `reset_required` / `invalid` / `locked` /
   `disabled`,* and never a session. The password is checked first — against
   throwaway material when no credential exists — so lifecycle state is
   disclosed only after a correct password and a missing credential costs the
   same work as a live one.
3. *A cohort reset is planned, approved and applied as three separable steps.*
   The plan sorts targets canonically and refuses empty, duplicate, malformed,
   stale and changed cohorts; `apply_force_reset` recalculates the typed digest
   rather than trusting the authorization's copy, locks and version-checks every
   target before mutating any, and produces an append-only secret-free receipt
   that doubles as the idempotency record.

**Transaction authority is unchanged (hard rule 8).** The facility opens no
session, never commits and never rolls back. "All targets atomically or none" is
a property of the caller's boundary, which is the only place it can honestly
live — so a product applying a cohort reset does it inside one of its own
transactions.

**Authority boundary.** This is PRODUCT security authority.
`dotmac-deployment-control` owns fleet deployment intent and must not authorize
an account mutation; the approval identity on a plan is a product approval
policy code and version, re-checked against the authorization.

**Not in scope**, and each excluded deliberately: machine credentials
(`dotmac_kernel.machine_auth`), federated identity (`external_identity`,
ADR-0069), and DEVICE/SERVICE credentials — `AccessCredential` and
`SnmpCredential` in `dotmac_sub` are not human credentials, and a sweep keyed on
`*Credential` would have handed the facility responsibilities it must not have.

## Testing model

- **Unit** (`tests/unit/`, `tests/architecture/`) — in-memory SQLite, no
  network, no RLS. Fast; run with `make test-unit`. Covers CRUD/query
  helpers, error envelopes, feature registry, logging, tenant middleware
  logic, and the static architecture governance checks (thin routers, route
  guards including the tiered auth-guard test, feature registration, web
  template/import conventions
  (`tests/architecture/test_web_conventions.py`), and the per-route
  non-admin sweep (`tests/unit/test_admin_route_sweep.py`) — see CLAUDE.md's
  "Web portal (admin UI)" section for what each of these checks.
- **Integration** (`tests/*.py` at the top level —
  `test_cross_tenant_isolation.py`, `test_auth_tenant_claim.py`,
  `test_rbac_audit_isolation.py`, `test_security_middleware.py`,
  `test_party_isolation.py`, `test_settings_isolation.py`,
  `test_custom_fields_isolation.py`, `test_web_auth_isolation.py`,
  `test_admin_portal_e2e.py`) — require a real, migrated Postgres, because
  SQLite cannot enforce RLS. The first eight are the tenancy canaries: two
  tenants, cross-tenant read/write attempts must come back empty/404.
  `test_web_auth_isolation.py` is `test_auth_tenant_claim.py`'s cookie-path
  mirror (2b-T3): a tenant A cookie replayed against tenant B's host must
  redirect to login, never reach the dashboard, since
  `authenticate_request`'s tenant-claim check runs identically for both
  the bearer and cookie paths (the shared seam — see "Admin portal" above);
  it also proves logout only revokes the calling tenant's own session.
  `test_admin_portal_e2e.py::test_admin_portal_end_to_end_canary` is the
  phase's proof canary — one test function drives the ENTIRE portal purely
  through cookies/HTML forms (register → cookie login with the CSRF header
  bridge → create a party → define + set a custom field via the
  values-panel → view settings → a second tenant's cookie jar confirms RLS
  isolation holds across every one of those pages, not just the API layer →
  logout revokes the session server-side, not just the client cookie). Run
  with `make test-db-up && make test-integration && make test-db-down`
  (disposable Postgres via `docker-compose.test.yml`, trust auth,
  localhost-only, throwaway). `TEST_DB_PORT` (and the other `TEST_DB_*`
  Make vars) are `?=`-overridable if the default port is taken.
- **CI** (`.github/workflows/ci.yml`) — four jobs: `quality` (matrix over
  lint/lint-imports/type-check/security, `fail-fast: false`), `unit`
  (`tests/unit` + `tests/architecture` with coverage), `integration` (drives
  `docker-compose.test.yml` directly rather than a `services:` block,
  because the `env:` context isn't available there), and `docker-build`
  (builds the prod image, boots it with a deliberately unreachable
  `DATABASE_URL`, and health-gates `/health`).

## Deploy

### GitHub Actions bundle observation ownership

`scripts/bundle_github_observation.py` is Starter's owner for observing and
binding a trusted GitHub Actions run, artifact, and workflow identity through
the fixed-origin transport. The SHA-pinned
`.github/actions/verified-dependency-bundle` action executes Starter's own
`scripts/run_bundle_action.py` through `GITHUB_ACTION_PATH`, never an executable
from the caller checkout. Its policy inputs (repository ID/name, workflow path,
and exact artifact names) must be set by the protected producer/consumer
workflow, not copied from a candidate's claims. REST identities are evidence;
a manifest `environment_name` remains descriptive and unverified because these
endpoints do not prove environment protection. The observed artifact digest and
byte size are compared to the downloaded ZIP before any byte claim is earned.
`scripts/bundle_artifact_download.py` owns that bounded, no-overwrite byte
handoff: it observes first, streams the artifact ZIP from the fixed GitHub API
path, and returns only after both observed values match and the linked output
inode matches the verified, fsynced file descriptor. The action creates an owned
mode-0700 child under runner temp for the handoff. A caller workflow must run
the verification in a fresh job BEFORE checkout or execution of candidate code
(so no candidate-started same-UID process can race it), and abandon that child
on publication refusal; neither the downloader nor the action can prove job
placement or concurrency from a pathname.

The approved envelope is two GitHub artifacts from one protected producer run.
First upload the archive artifact containing exactly `bundle.zip`; only after
the upload action returns its positive `artifact-id` may `construct` write the
canonical `bundle-manifest.json` sidecar and upload it as a separate artifact.
The sidecar's `run.artifact_id` and name bind the **archive**, not the sidecar.
`verify-and-index` independently observes and hashes both outer artifact ZIPs,
requires the same producing run/repository/head SHA/workflow, reads the exact
sidecar member, binds its run record to the archive observation, verifies the
inner archive and extracted members, and builds a local index with no registry
fetch. GitHub's artifact-read token is passed only by environment, never argv;
it is not a Forgejo registry credential.

The action's `expected-file` is an exact JSON v1 document with keys
`schema_version: 1`, `plan_digest` (64 lowercase hex), and nonempty `artifacts`
records carrying only `package_normalised_name`, `filename`, and `sha256`.
Starter validates and reconciles that document but **does not derive or prove
its product-policy provenance**. ERP/Workspace must compute it from their own
immutable candidate dependency state and pass the trusted producer coordinates
through reviewed, source-bound workflows. The action returns `manifest-path`
after construction and `index-root` after verification, both under runner temp.
`deployment-conformance-bundle.yml` is the additive, secret-free successor to
the existing reusable conformance workflow. It preserves the descriptor and
image checks but accepts observed producer coordinates, materializes the exact
one-wheel expected document under runner temp, invokes the action at the
immutable Starter commit that owns it **before candidate checkout**, and
installs the declared `dotmac-deployment-foundation` wheel with `--no-index
--no-deps` from the verified local index. It accepts no caller secret. The plan
digest, wheel filename and wheel digest inputs are shape-checked, and the
filename must carry the exact declared foundation version; the workflow still
cannot prove the caller derived those coordinates from its actual dependency
manifest. That caller-side binding is explicitly unmonitored until ERP and
Workspace adopt the successor.

During migration, `deployment-conformance.yml` and
`deployment-conformance-bundle.yml` duplicate the descriptor/image check body.
That is named transition debt, not a second permanent owner: retire the old
credentialed workflow after both immutable caller pins move and their exact-head
CI passes. No caller uses the successor yet, no protected producer exists, and
the protected environment, source-bound ruleset, broad-secret removal, and
rotation remain separate work. ERP still executes its original verifier; this
workflow is not a cutover receipt.

`docker-compose.yml` (prod) requires a published `APP_IMAGE`, no bind
mounts, resource limits (`APP_MEM_LIMIT`, `APP_PIDS_LIMIT`), and a
container healthcheck against `/health`. `docker-compose.dev.yml` is an
overlay adding a local build + throwaway Postgres (`make docker-dev`).
`scripts/deploy.sh <tag>` is the only production migration path: verify
image on registry → `pg_dump` backup → pin `APP_IMAGE` in `.env` → pull →
`alembic upgrade heads` (one-off container) → recreate `app` → health gate
(retries/interval/timeout all config knobs) → auto-rollback to the previous
pin on health-gate failure (migrations are not auto-reverted; new revisions
must stay backward-compatible with the previous release).
