# As-built inventories (F0)

These documents record **what exists today**, not what should exist. They are the
evidence base for ADR-0006 (white-label product foundation) and the input to the
F1–P1 programme steps.

Read them with two cautions:

1. **Facts go stale.** Each file carries an as-of date and the commit it was taken
   at. An inventory that disagrees with the code is wrong, not authoritative —
   re-run it rather than trusting it.
2. **An inventory is not a mandate.** Recording that two products implement the
   same-looking table does not authorise extracting a shared component. ADR-0006
   § "The extraction rule" governs that: same contract, named owner, migration
   path — similarity alone is explicitly insufficient. Once extraction is
   approved, the 2026-08-08 product-first amendment additionally requires the
   qualifying product implementation and tests to be the starting point rather
   than rebuilding the behaviour beside them.

## Adopter naming — corrected 2026-08-21

Two adopter names in these inventories and in `packages/*/EXTRACTION.toml`
moved, and the dossiers were reconciled to them:

- **The back-office destination is the commercial Dotmac ERP product**, not an
  independently deployed `dotmac_backoffice` application. Michael corrected
  this on 2026-08-19 and clarified on 2026-08-22 that the local composition
  sketch was never a separate repository. It is therefore not valid source or
  consumer evidence. Dossier consumer fields name `dotmac-erp`; historical
  source evidence names only the real `dotmac_erp` repository.

  Four names, and only four — do not introduce a fifth:

  | Role | Name |
  |---|---|
  | Product / repository slug | `dotmac-erp` |
  | Authority / assembly id | `asm-dotmac-erp` |
  | Historical source repository | `dotmac_erp` |
  | Human name | Dotmac ERP |

  Dossier **consumer** fields take the product slug `dotmac-erp`. **Authority**
  fields take the assembly id `asm-dotmac-erp` — that is why ERP's writer
  ledger records `asm-dotmac-erp/dotmac-people` rather than the slug. The
  legacy `dotmac_erp` repository is the extraction SOURCE and is archived or
  renamed at final retirement.
- **`dotmac_sub` is the adopter, not a separate ISP assembly.** Corrected
  2026-08-22 by the conversion amendment to governance ADR 0012. Dotmac Sub is
  **not** being retired: it remains the ISP product, runtime, API identity,
  hostname and customer-facing application, and becomes the thin assembly *in
  place*, pinning kernel, UI and released domain modules while each domain
  switches authority internally from legacy code to its module. The operative
  phrase is **"retire legacy Sub implementations, not Dotmac Sub."**

  So every module a cohort assigns names `dotmac_sub` in `candidate_consumers`.
  Where it already did, the earlier `dotmac-isp` entry simply drops; there was
  never a second product. It stays a CANDIDATE: `contract_consumers` drives the
  evidence ratchet in `test_product_first_extraction.py` and still requires a
  proven, exact-pinned composition inside Sub, which none of them has yet.

  The `dotmac-isp` walking skeleton is frozen and holds no programme control.

`source_repositories` and `source_revisions` were deliberately NOT rewritten.
They record which repository a sweep actually ran against, at which commit;
repointing them would falsify the evidence rather than correct a plan. Where
narrative text still says "Backoffice" about a PRIOR plan or sequence, that is
also left standing as history — read it against this correction.

Three platform-plane modules — Support Access, Platform Health and Deployment
Control — deliberately name no ISP consumer at all. `dec-isp-005` resolved them
as external Vendor-control-plane dependencies consumed over versioned APIs, and
Sub composes no platform plane.

Authority hierarchy is unchanged: `docs/ARCHITECTURE.md` is as-built truth for
this repo, `docs/adr/` holds decisions, and these inventories are characterization
across repos.

## Index

| Inventory | Scope | File |
|---|---|---|
| **ERP / Backoffice / general publication readiness** | the joined state for the sixteen audit-complete unpublished packages: a84 allocation train, collision resolutions, first-adopter and dependency seams, exact-commit Observer gate and release discipline | `erp-backoffice-general-publication-readiness.md` |
| **ERP accounting and payables sources** | ERP as the qualifying chart/posting/ledger and supplier-liability source; Sub's separate receivables boundary; exact product pins and the Accounting-before-Payables cutover order | `accounting-payables-sources.md` |
| **Analytics sources** | ERP's metric store/computers as the production base, fleet projection variants, declaration/observation boundary and ERP-first digest-backed cutover | `analytics-sources.md` |
| **Banking, payroll and tax sources** | the three ERP financial owner audits, including Accounting/People prerequisites, Sub fact boundaries and later Backoffice consumption | `banking-sources.md` + `payroll-sources.md` + `tax-sources.md` |
| **Subscriber account disposition sources** | Sub's account deletion, retention window, restore and purge paths measured for Records adoption: retention is one unversioned integer with no series, holds or approval, and `purge` destroys nothing while the code claims a personal-data purge | `subscriber-account-disposition-sources.md` |
| **Documents and Records sources** | ERP handbook and Sub immutable-content evidence for Documents; the exact negative inventory and destructive-safety gate for greenfield Records | `documents-records-sources.md` |
| **Expenses, Finance and Procurement sources** | ERP's qualifying spend, fixed-asset accounting and purchasing behavior; boundary corrections, parity tests, adapter seams and sealed retirement gates | `expenses-sources.md` + `finance-asset-accounting-sources.md` + `procurement-sources.md` |
| **Inbox, Party, Projects, Surveys and Work Orders sources** | Sub-first general-domain extractions, CRM retirement evidence, product-owned linkage/consequence boundaries and the first authoritative writer switches | `inbox-sources.md` + `party-module-sources.md` + `projects-sources.md` + `surveys-sources.md` + `work-orders-sources.md` |
| **Decomposed marketing suite sources** | the seven-module source ruling across `dotmac_mkt`, Sub, ERP, CRM and Backoffice; the Integrator/provider boundary; the greenfield sites proof; campaigns' Sub-first exception; and the release/adoption gates for the merged campaigns and parked media-observations candidates | `marketing-suite-sources.md` |
| **Editorial content extraction dossier** | the first marketing-suite slice: Mkt `Campaign`/`Post`/asset-link parity, the `ContentPlan` rename, editorial-vs-publishing and authorization boundaries, the proposed five-table tenant contract, lifecycle corrections and Backoffice writer-retirement gates | `content-extraction-dossier.md` + `content-writer-retirement.toml` |
| **Publication lifecycle extraction dossier** | the second marketing-suite slice: Mkt scheduling, per-target delivery, partial/all-failed behavior and update/delete paths; the immutable snapshot, timer/outbox, normalized-observation and Integrator boundaries; the proposed four-table tenant contract and ten Backoffice writer-retirement gates | `publishing-extraction-dossier.md` + `publishing-writer-retirement.toml` |
| **Site-builder sources and extraction dossier** | the exact six-repository greenfield proof; local site/page/revision, navigation, SEO and redirect ownership; the five-table forced-RLS contract; immutable local release value; and the publishing/Integrator remote-hosting boundary | `sites-sources.md` + `sites-extraction-dossier.md` |
| **Inventory sources** | ERP as the qualifying stock-ledger source; CRM's mutable copy and Sub's catalogue observations; the reusable SKU/warehouse/movement/reservation/lot/serial/valuation boundary and ERP-first cutover gate | `inventory-sources.md` |
| **Inventory ERP cutover scoping** | the exhaustive 21-table disposition, legacy writer/caller retirement ledger, seven module blockers, clean opening-state/import contract, Finance quantity/value-evidence seam, manifest/query requirements, and evidence-gated cutover/rollback sequence; explicitly records that a1 is published but cannot carry adoption | `inventory-cutover-scoping.md` |
| **Assets sources** | ERP's overlapping fixed-asset and fleet lifecycles; the reusable durable-unit/custody/maintenance/disposal boundary; finance, stock, positioning and vehicle exclusions; ERP-first cutover gate | `assets-sources.md` |
| **Network module sources and dispositions** | the pinned Sub/CRM/ERP/Workspace/Vendor-CP/Cloud-profile review, Sub-first source ruling, nine bounded module targets, current table/service-family assignment, Cloud-vs-ISP scope, provider/observability seams, entry and retirement gates, and machine-readable disposition ledger | `network-module-sources.md` + `network-module-dispositions.toml` |
| **Network module typed contracts** | the suite-wide immutable command/query/snapshot/event surfaces, explicit no-ORM-return rule, opaque cross-owner reference boundary and single coordinated adoption cohort for all nine candidates | `network-module-contracts.toml` |
| **Positioning sources** | the fleet-wide location-evidence census; the provider-neutral observation boundary; why position observation is separated from Assets' authoritative location and from every geofence, SLA, dispatch and billing consequence | `positioning-sources.md` |
| Starter surfaces | `dotmac_starter_mt` routes, UI surfaces, templates, CSS/static, navigation, brand leakage | `starter-surfaces.md` |
| Sub surfaces | `dotmac_sub` portals, templates, CSS/static, navigation, branding mechanisms, kernel adoption | `sub-surfaces.md` |
| ERP + vendor control plane surfaces | `dotmac_erp` and `dotmac_vendor_control_plane`, same shape | `erp-vendor-surfaces.md` |
| Branding and settings | all three repos: brand sourcing/precedence, the brand-field union, tenant custom CSS and its CSP consequence, settings facilities and specs | `branding-settings.md` |
| Migrations and table collisions | all four repos: Alembic topology, revision-ID and table-name collision analysis, namespacing, RLS coverage | `migration-collisions.md` |
| Idempotency sources | ERP's 3 and Sub's 3 idempotency mechanisms, the kernel baseline they extend, defects not to carry forward, and the tests available to port | `idempotency-sources.md` |
| Tenancy characterization | ERP's 398-table `organization_id` catalog and its two-layer isolation, Sub's already-provisioned operator tenant, the GUC divergence, and why ERP's RLS coverage is unmeasurable from source | `tenancy-characterization.md` |
| Product-first module sources | shared distributions plus the ERP/Sub code and tests that must be audited before shared implementation | `module-extraction-sources.md` |
| Consent and suppression sources | Sub's complete do-not-contact ledger, ERP's total absence of one, the marketing/transactional scope rule, defects not to carry forward, and why the extracted owner belongs in the kernel | `consent-suppression-sources.md` |
| Delivery and outbox sources | why Sub's notification queue is the kernel outbox built twice, the bounce→consent feedback loop that exists in neither product, and what a delivery owner is left owning | `delivery-outbox-sources.md` |
| Channel policy sources | why the § 5c channel-policy owner resolves into a settings document with a typed reader rather than a fifth subsystem | `channel-policy-sources.md` |
| Template Studio source audit | ERP document templates vs Sub notification templates vs the package across identity, versioning, publication, placeholder syntax, scoping, seeding, delivery, traceability, permissions and cutover shape — the audit `EXTRACTION.toml` blocks on, plus the six-owner capability map it resolves to | `template-studio-source-audit.md` |
| UI surfaces | the ERP/Sub `src/css/` fork, drift file by file, class usage, the button vocabulary — **plus the 2026-08-11 correction that only ERP still runs its copy**, which supersedes the promotion steps | `ui-surface-inventory.md` |
| Reusable map UI sources | Sub live-map/playback, CRM degraded/list behavior and ERP geofence editing; narrows the portable contract to an accessible provider-neutral frame and records every provider, viewport, data and domain seam that stays product-owned | `map-ui-sources.md` |
| Ticket module sources | Sub/CRM/ERP ticket implementations, why their vocabularies cannot merge and why that does not block the capability, the product-neutral core vs the per-product variant seam, the lifecycle-class mechanism that makes the vocabulary open, and the subject-linkage decision | `ticket-sources.md` |
| Billing sources | the money-domain code across all four repos — Sub's 66 tables / ~74k LOC / 174 test files against ERP's 32 AR/AP tables and the kernel's zero, what the kernel already supplies, ten missing capability areas plus the external lineage gate, ADR-0020's receivables/module rulings, and the non-conformances the extraction must not carry forward | `billing-sources.md` |
| Billing extraction dossier | the `dotmac-billing` dossier fields, the dual-plane persistence design, an eight-slice Sub retirement inventory with the ratchet proving each, and for every recorded non-conformance the corrected revision-1 shape and the shadow measurement that must precede cutover | `billing-extraction-dossier.md` |
| Billing parity tests | the verified Sub and ERP tests the extraction must preserve, each with the behaviour it proves and the defect it guards — including which port **split** between billing meaning and Integrator transport, which port with an **inverted** assertion, and the areas with no adequate source test | `billing-parity-tests.md` |
| Subscription sources | the A2b Vendor-CP/Sub audit of offers, prices, recurring contracts, cadence, proration and obligations, **revised 2026-08-15** for ADR-0030: Sub's ADR-0007 stack is shadow-only while the legacy money path holds the defects, the cadence cursor has eleven writers and no canonical owner, recurrence is not repairable from the contract, and Vendor CP is **not** a source of structural immutability — it grants `UPDATE, DELETE` on `offer_versions` to the online API role | `subscriptions-sources.md` |
| Sub lineage dispositions | the ten kernel/Sub table-name collisions measured against released a40, grouped by what each actually needs — stamp, adopt, reconcile, or union — plus the four ways the measurement was wrong first and the self-check that caught them | `sub-lineage-dispositions.md` |
| Application-portfolio sources | the two mechanical sweeps proving no repository owns a tenant's connected-application portfolio, why the vendor CP's `allocations` is a different unit despite being the nearest neighbour, and the concept-to-owner table the directory module must not absorb | `application-portfolio-sources.md` |
| Federated identity (OIDC) sources | ERP's 409-line Authorization Code + PKCE implementation, its `FederatedIdentity` binding and four boundary tests, the algorithm allowlist and the refuse-unlinked-identity rule that make it the parity suite — plus the unresolved question of whether `OIDC_ENABLED` is true in any production deployment, which decides `product-first` vs `greenfield-after-inventory` | `oidc-sources.md` |
| **External identity sources** | the 2026-08-14 six-repository sweep of the TWO capabilities routinely confused — the OIDC protocol client and the local verified-subject→local-identity binding — finding that ERP owns one half (`federated_identities`, no tenant column, global `(issuer, subject)` uniqueness) and Sub the other (`authentication_bindings`, no issuer/subject at all) and **neither has both or has RLS**; supersedes `oidc-sources.md`'s open gate by finding a host-independent disqualifier (ERP's signature and claim validation are monkeypatched out of every test), which rules the OIDC package `greenfield-after-inventory` | `external-identity-sources.md` |
| Party module sources | CRM/ERP/Sub identity models audited for a composable party module: why Sub is the only qualifying source and ERP/CRM are requirement inputs, the `party_roles` name-vs-meaning collision that blocks extraction, the tenancy delta and the one unique constraint that is a cross-tenant leak, and why gate 5 (Sub's own cutover) is currently binding | `party-module-sources.md` |
| **People directory sources** | the five-repository audit for Backoffice's first vertical replacement slice: kernel Party remains identity; ERP is the qualifying source for employee lifecycle, departments, positions and temporal assignments; Sub/CRM are projection inputs; payroll/auth/attendance/GL stay outside; and the ERP-authority-retirement/Backoffice-runtime cutover is stated explicitly | `people-directory-sources.md` |
| **ISP essential-domain sources** | exact-revision Sub/CRM/ERP/Starter audit for Customers, Service Catalog, Qualification, Services, Usage, Usage Rating, Service Access Policy, Inbox Operations, Workforce and FX Policy, including preserved tests, exclusions and retirement posture | `isp-essential-domain-sources.md` |
| **Customer-journey owner sources** | exact-revision audit of Sub PR #2624 for Service Orders, Payments, Service Changes and Operational Escalations, including preserved tests, the boundary and defect changes made on port, what was deliberately NOT turned into a package, and the boundaries still needing adjudication | `customer-journey-owner-sources.md` |
| `audit_events` disposition | the measured Group E union and implemented R1 integration contract: retained forensic columns, distinct event/persistence time, the closed polymorphic actor identity, immutable audit semantics, coordinated integration branches, and dependency-ordered releases | `audit-events-disposition.md` |
| **Kernel persisted-runtime dependencies** | the fleet audit of kernel audit/settings storage, with the platform-only `platform_audit_log.v1` ruling and a 2026-08-16 implementation addendum; tenant audit remains unnamed and settings remains the wrong prerequisite instrument | `kernel-persisted-runtime-dependencies.md` |
| **Approvals released-migration divergence** | the exact a1–a4 tag/digest census for the three meanings shipped as `ap_0001`, why the exception is closed rather than permission to edit again, and the six PostgreSQL upgrade cases that preserve rows and persistence-plane intent | `approvals-released-migration-divergence.md` |
| **Permission provisioning sources** | product-first inventory of Starter declarations, Sub's typed RBAC owner, ERP's deploy/seed gap, Workspace defaults and Academy role algebras; defines the additive-only Stage 1 boundary and the claim-ledger prerequisite for revocation | `permission-provisioning-sources.md` |
| **Fleet decomposition matrix** | the standing ERP/CRM/Sub/Mkt/vendor-CP capability matrix PRODUCT_VISION § 2 requires — owner, competing writers, consumers, migration owner, authority overlap, target layer and retirement condition per capability, plus the frozen duplication baseline and the sequencing it implies. Mkt joined as the fourth source application on 2026-08-18; the vendor control plane remains a consumer assembly rather than a fifth source application | `fleet-decomposition-matrix.md` |
| **Approvals/workflow A1 source audit** | the exact 24-row decomposition of the former `governance-workflow` measurement bucket, the ERP-vs-Vendor approval behavior comparison, the `dotmac-approvals` source ruling and mandatory port deltas — accepted by ADR-0026 on 2026-08-14 with three recorded corrections (routing stays in ERP, policy codes are data, Vendor CP's cutover is a capability gain), and no package or namespace created — plus the separate automation/forms/domain/retirement dispositions | `approvals-workflow-source-audit.md` + `approval-workflow-dispositions.toml` |
| **WhatsApp/Meta connector sources** | the two fleet implementations of Meta webhook ingress (Sub's `whatsapp_runtime` + `meta_inbox_webhooks` as the qualifying source; CRM's larger `meta_webhooks` as requirement input only, being fused with CRM domain decisions), the ingress-vs-egress scope split for an INGRESS-only connector, the database coupling to remove during the port, the ingress-edge MIRROR shadow plan (Meta configures one callback endpoint and per-WABA overrides move it rather than duplicate delivery, so dual subscription is not available), and the BLOCKING finding that `modes` is decorative across the whole SPI — ingress and poll have no hook at all and delivery is invoked without checking the mode | `whatsapp-connector-sources.md` |
| **WhatsApp/Meta ingress connector dossier** | the PRE-REGISTERED `EXTRACTION.toml` for `dotmac-connector-whatsapp` — coordinates authorized 2026-08-15, the distribution itself still NOT authorized: the three remaining gates (the ADR-0030 § 6 amendment, Team 4's secret resolver, and a published `dotmac-integration` implementing SPI 1.1 — none exists, so no `integration_floor` is nameable and the connector lane refuses the entry), the port/not-port disposition surface by surface, the parity dispositions (the request BODIES port, the assertions do not), the fourteen findings a future connector must NOT inherit (request-digest event identity, the circular handshake, silent drops, the fallback secret that is not rotation), and the provenance of the fixture corpus in `tests/fixtures/meta_whatsapp/` | `whatsapp-connector-dossier.md` |
| **Meta Social connector dossier** | the product-first `dotmac-connector-meta-social` slice ported from Sub's Facebook/Instagram message and comment receiver AND its outbound Graph adapters: exact-byte verification, per-event identity, record-only transport evidence, the `messaging.send.v1` direct-message and comment-reply wire shapes, Graph error-code classification, Sub shadow/cutover, and the reply-window decision that stays with Sub | `../packages/dotmac-connector-meta-social/EXTRACTION.toml` |
| **Integration REQUEST sources** | the Sub Meta profile-read and ERP fleet-read evidence for SPI 1.6's provider-neutral bounded synchronous REQUEST seam, including the greenfield-after-inventory ruling, opaque installation/session key, closed failures, and module-owned bounded retry | `integration-request-sources.md` |
| **Paystack connector dossier** | the product-first `dotmac-connector-paystack` slice: exact-byte HMAC-SHA512 ingress, authenticated paged transaction reconciliation, settlement observations, exact provider evidence, and a Sub-first shadow/cutover that leaves every financial consequence with the product owner | `../../packages/dotmac-connector-paystack/EXTRACTION.toml` |
| **Flutterwave connector dossier** | the product-first, Flutterwave-v4-only `dotmac-connector-flutterwave` slice: exact-byte HMAC-SHA256 ingress, OAuth-authenticated paged charge reconciliation, no v3 fallback or invented provider fee, and a Sub v3-to-v4 cutover that leaves every financial consequence with the product owner | `../../packages/dotmac-connector-flutterwave/EXTRACTION.toml` |
| **Mono connector dossier** | the product-first `dotmac-connector-mono` slice: authenticated v2 account-transaction polling, same-origin pagination, exact lowest-denomination amounts, opaque resumable cursors, and an ERP shadow/cutover that leaves statement and reconciliation authority with ERP | `../../packages/dotmac-connector-mono/EXTRACTION.toml` |
| **Remita connector dossier** | the product-first `dotmac-connector-remita` slice: authenticated RRR status polling, JSON/JSONP parsing, verbatim provider facts without ERP's disputed status mapping, and an ERP shadow/cutover that leaves RRR and accounting authority with ERP | `../../packages/dotmac-connector-remita/EXTRACTION.toml` |
| **Traccar connector dossier** | the greenfield-after-inventory `dotmac-connector-traccar` slice: four fixed read-only REQUEST capabilities, installation-isolated provider sessions, exact private-service egress and strict device/position normalization; release remains disabled pending integration a18 and ERP-owned contract digests | `../../packages/dotmac-connector-traccar/EXTRACTION.toml` |
| **LinkedIn connector dossier** | the fleet-audited greenfield `dotmac-connector-linkedin` slice: challenge-response, exact-byte webhook HMAC, organization-social and Lead Sync batch normalization, deny-all egress, and destination-owned product decisions | `../../packages/dotmac-connector-linkedin/EXTRACTION.toml` |
| **Inter-application synchronization dossier** | the provider-neutral `dotmac-app-sync` contract: authenticated application identity, versioned destination-owned schemas, stable idempotency and payload conflict fingerprints for Sub/ERP/Academy flows, with transport, persistence and decisions retained by each independent product | `../../packages/dotmac-app-sync/EXTRACTION.toml` |
| **Large-import execution inventory** | why `dotmac-imports` remains the sole run owner; exact product revision evidence; the bounded `dotmac-files` partition, checksum, lease and checkpoint lane; and explicit deferral of database extraction, COPY and worker-count policy until adopter evidence | `imports-large-migration-sources.md` |
| **Entitlement allocation sources** | the vendor CP's `allocations` audited as the single qualifying source, and the three couplings to `contracts` the extraction must cut — FK, direct model read, event-type literal — resolved by a typed `ContractSnapshot` port. Records the finding that cutting them is the FIRST step rather than a consequence, which makes the extraction A2-neutral | `entitlement-allocation-sources.md` |
| **Fact-level decomposition** | declared fact ownership extracted from Sub's SOT registry and ERP's `sot_relationships.py`, plus a **direct-import reachability heuristic** over ERP/CRM/Sub/Mkt — explicitly not an ownership measure — and the 29 duplicated tables with no detected edge, held as a manual triage queue | `fleet-fact-level-decomposition.md` |
| Cloud commerce owner sources | the ADR-0030 portfolio pass: a verdict-by-owner table across six repositories for the seven Cloud business owners. **Superseded in part 2026-08-15** — written before the per-owner dossiers, it wrongly rules Fulfillment product-first and credits Vendor CP with immutable publication; where it and a per-owner dossier disagree, the dossier wins | `cloud-commerce-owner-sources.md` |
| **Numbering ERP adoption slice** | the read-only adoption analysis for `dotmac-numbering`'s first candidate consumer, and the source of the defect that produced kernel a66: `allocate` writes the kernel at-most-once ledger at REQUEST time with no `PrerequisiteSpec` covering it, so an adopter running its own tenant lineage migrates cleanly and fails on the first allocation. Also the bank-statement format grammar change (`STMT2026-00001` -> `STMT-2026-00001`), which is customer-visible and undecided | `numbering-erp-adoption-slice.md` |
| **Durable timers sources** | the ADR-0030 step 6 revalidation: product-first with a source SPLIT no earlier dossier records — Sub contributes identity, generation and supersede/cancel; the CLAIMING engine already exists in `dotmac_kernel.messaging.relay` (`FOR UPDATE SKIP LOCKED`, lease reclaim, backoff, dead-letter, both planes, proven on real Postgres) and must be reused rather than re-implemented. Also: Sub's own registry declares the facility `SHADOWING`, one scheduled family has no consumer, the 200-timer fire batch is one transaction with no dead-letter, and the whole suite runs on SQLite | `durable-timers-sources.md` |
| **Billing source variance** | the ADR-0030 step 7 revalidation, and the one that changes the plan: both flagship capabilities are **not the live path in their own repository** — Sub's ADR-0007 obligation stack is `SHADOWING` by declaration and has never raised an invoice, and ERP's `coverage.py` (called "the single highest-value port in the programme") has zero references under `app/`. `source_mode` becomes greenfield-after-inventory; two of six contracts are freezable now, which unblocks `dotmac-document-rendering`; 125 float-on-money casts where the dossier records one | `billing-source-variance.md` |
| **Numbering source revalidation** | the 2026-08-15 recheck of `numbering-sources.md` against current ERP/Sub heads. Every mandatory path is byte-identical to its pin, so the diff is empty — and the dossier's *description* of that unchanged code was still wrong: Sub's credited "monotonic reconciliation" is dead code with no caller. Also: 16 ERP callsites cannot pass a business date, so the required-`reference_date` contract breaks three quarters of the cutover surface; there is not one real-database numbering test in either product; and five new ERP defects including a backdated allocation that rewinds the counter. Where it and `numbering-sources.md` disagree, this file wins | `numbering-source-variance.md` |
| Numbering sources | the ERP-base/Sub-delta verdict for `dotmac-numbering`: ERP's date-aware series model and 41-caller parity suite as the mandatory base, Sub's conflict-safe first-use and monotonic reconciliation as a mandatory port delta, and the five ERP defects — including a query-then-insert first-use race and an operator reset that can reuse a committed number | `numbering-sources.md` |
| Collections sources | Sub's live and target dunning stacks as the only qualifying source, **revised 2026-08-15** for ADR-0030: four §1 properties absent from both stacks and therefore built not ported — exposure membership, immutable policy versions, throttle-as-a-request (throttle writes RADIUS columns inline today), and a persisted owner-side refusal — plus CRM's parallel delinquency classifier and ERP's unfiltered overdue sweep | `collections-sources.md` |
| **Orders sources** | Sub as the only qualifying source (24 caller files, a `SELECT FOR UPDATE` funding gate) against ERP's 2 callers and all-mock suite and CRM's strict subset; the three findings that define the module — **no source keeps an accepted line immutable, none snapshots a price version, none has tenant isolation** — and the live authority bypass where a generic order update can manufacture funding and trigger provisioning | `orders-sources.md` |
| **Fulfillment sources** | the finding that **Sub has no saga engine** — `saga_executions`/`provisioning_step_executions` exist only in migrations and FK to `ont_units`/`olt_devices` — so the ruling is greenfield on `dotmac_kernel.providers.provisioning`, which already supplies plan/apply/observe/cancel, operation-id idempotency, resumable `PARTIAL` and a conformance kit; plus the eleven ISP participants and the one-function/three-structural-coupling seam | `fulfillment-sources.md` |
| **Domains sources** | the greenfield verdict **proven** by an eleven-repository sweep across six term families with every false positive named (the fleet has no DNS client at all), and the `TenantDomain` boundary settled by a Postgres grant rather than convention — it is a platform-plane routing catalogue that tenant-plane Domains physically cannot write | `domains-sources.md` |
| **Hosting sources** | the greenfield verdict proven by a per-term census returning zero panel/account/quota implementations, qualified by three Sub precedents the fresh module must match and Sub retains (reason-scoped multi-lock suspension, receipted consequence attempts, an observation table that is never authoritative for desired state), and the three-way suspension boundary between Sub's ISP subscription, Vendor CP's agreement column and a hosting service aggregate | `hosting-sources.md` |
| **Provider capability and conformance** | five rulings — the connector framework already exists in `dotmac-integration`, PSP is product-first with a complete audit, registrar/DNS/panel are greenfield — plus the finding that **zero Blesta code exists in the fleet**, the four capability surfaces specified as shapes, the conformance-kit obligations, and the blocker that the assembly has no secret resolver so no installation can reach `enabled` | `provider-capability-sources.md` |
| **Media observations sources** | Mkt's qualifying external campaign/group/advertisement hierarchy and daily aggregate metric behavior; CRM's attribution writers as negative evidence; Sub's authoritative immutable Lead-origin boundary; Integrator's transport-only contract; Backoffice/Sub candidate status and the explicit adoption pause | `media-observations-sources.md` |
| **Campaigns sources** | Sub as the qualifying outbound-campaign lifecycle and test source; CRM tracking/correlation parity plus provider/scheduler/Lead coupling defects; dotmac_mkt's editorial and advertising hierarchy preserved outside the owner; Backoffice as independent reuse proof; and the explicit Sub-first resolution of the broader programme's Backoffice-first sequence | `campaigns-sources.md` |
| **Vendor CP recomposition gap sources** | the six-capability audit behind ADR-0057: commercial agreements, licence issuance and brand profiles have qualifying product implementations; deployment control splits into a tested-but-abandoned V6 reference and a plan/rollout half proven absent from every repository (branches, stashes, dangling objects and reflogs all searched); and **support access and notifications are already owned** — ADR-0029 names three owners for the first and ADR-0006 § 5c plus three taken dossiers placed all six decisions of the second. Also records why Sub's UISP desired/observed control is a pattern reference and not a source, and why ERP's `app/licensing/` is receiver-side only | `vendor-cp-gap-sources.md` |
| **Vendor CP composition readiness** | the completion map for ADR-0057: every decision and transition in the Vendor journey against exactly ONE owner, the three steps whose owner is named but whose code is deferred, the six typed seams the future Vendor assembly must implement, the plane derivation for all four new modules, and the four open items the programme surfaced without taking — including that Sub's `semantic_colors` reduction needs a ruling and that ERP's receiver-side licence format is still unretired | `vendor-cp-composition-readiness.md` |
| **Sub vNext parity sources** | the exact-revision audit and ten-capability adjudication for Referrals, Reseller Management, AI Operations, Remote Access, Compliance Reporting, Workflow Runtime, Support Access, Platform Health, Fleet Control and independently reusable Forms; records five product-first sources, three narrow greenfield findings, Deployment Control reuse and every legacy-writer retirement gate | `sub-vnext-parity-sources.md` + `sub-vnext-parity-dispositions.toml` |
| **Machine credential sources** | the two `X-Api-Key` implementations that already exist and DISAGREE: Sub restricts a key to exactly its scopes while ERP treats an empty scope list as granting everything; plus Sub's unsalted-SHA-256 fallback, its verification key derived from the connector encryption key, and its `db.commit()` during a GET, against ERP's SHA-256-only hashing and its requirement that a machine credential name a human `person_id`. Records the wire precedent worth preserving and the eight behaviours that must not be carried into a kernel facility, and the finding that adoption is credential REISSUANCE rather than a hash migration because a stored digest holds no material to re-key from | `machine-credential-sources.md` |
| **Native mobile application sources** | the fleet's three Flutter applications at exact revisions — `dotmac_sub/mobile` (self-care, 128 files / 26,554 lines / 159 test cases), `dotmac_sub/field_mobile` and `dotmac_crm/mobile` (field ops) — with the CRM→Sub copy history and the measured divergence: **51 files differ, 9 are one-sided, and 17 of the 51 differ on CONTRACT** (different backend host, different outbox routing vocabulary, different owner of the job-completion gate, different rule on whether a transport failure ends a session). Records that the two field trees share a byte-identical `pubspec.yaml`/`pubspec.lock`, that an authentication fix landed on the retiring CRM copy on 2026-08-18 and never reached Sub's, and twelve confirmed defects including an entirely unencrypted field database, a logout that clears only the token store, a principal-free response-cache key, a push router that navigates to any raw path the server sends, an Xcode Cloud hook that builds the wrong application, and the fact that **neither field app has ever been released from a tag**. This is one implementation's worth of evidence, not two independent consumers' — duplication evidence, not reuse evidence | `mobile-application-sources.md` |
| **Human credential lifecycle sources** | the call-graph census behind `dotmac_kernel.credential_lifecycle`, at exact commits: `dotmac_sub` has **FOUR** `verify_password` owners in four files (each re-deriving active/locked/reset-required for itself, because the primitive returns a boolean) and **ELEVEN** `hash_password` caller files, two of them seed scripts — so a guard scoped to `app/` sees nine and calls the other two absent. Records why Sub qualifies as the product-first source (it is the only product with reset-required, lockout, recovery intents and per-principal revocation in production), that Platform CP has **no reset-required concept at all**, that `password_needs_rehash` has **zero** callers fleet-wide so the legacy-hash upgrade is NEW behaviour rather than ported, the six deliberate departures from Sub, the reconciliation between the grep census and the AST sweep (identical file sets, different site counts) including one census figure the measurement supersedes, and the exclusion of `AccessCredential`/`SnmpCredential` as device and service credentials. Names `dotmac_sub` as first adopter and the local-copy retirement gate; claims no release, adoption or production state | `credential-lifecycle-sources.md` + `credential-lifecycle-baseline.json` |

| **Executor retirement** | the machinery that lets the programme's "zero retired legacy executors" scoreboard move, and nothing that moves it: a typed per-product census over EIGHT entry-point families (workflow, script, cron, systemd unit, SSH credential, webhook, manual runbook and — since the 2026-08-31 amendment — runtime_reactivation, the supervisor that can return a displaced executor after reboot with nobody invoking anything) in which absence is never a disposition and four families cannot be walked at all, so an absence there needs an observer and a SCOPE — `repository_tree` says nothing about any host, which is how `dotmac-books.service` sat installed and disabled. Records the disposition state machine whose load-bearing property is an ABSENT edge (`active_executor` has no path to `retired`), two-directional ratchets per family AND per disposition plus two over the programme itself, the `ExecutorRetirementReceipt.v1` schema with a "not this" column per field, and `DisplacementWindow.v1`, which proves the negative half by ATTRIBUTION rather than absence — every runtime change linked to a controller receipt or a typed same-image cause, zero unattributed, a quiet window refused as an event source, and `cannot_establish` forcing an UNMONITORED verdict rather than a caveated pass. `SshCredentialConstraintV1` (v3) closes the gap v2 named — the contract could count a key and not characterise it — with fingerprint, exact source restriction, forced-command DIGEST, `restrict` and each forwarding permission stated rather than omitted, and the rule that a RETAINED rollback key must be source-restricted, forced-command-only and incapable of an interactive shell, proven by three separately planted removals. Compose sanction is ENTRY-POINT IDENTITY resolved from installed distribution metadata rather than a path, a filename or a declared premise, with the unsanctioned set ratcheted to empty; and the roster names `dotmac_vendor_control_plane`, because a production host retaining a rollback credential outside the roster is silently unmonitored rather than UNADOPTED. `dotmac_starter_mt` adopts; `dotmac_erp` is the named first adopter and is reported UNADOPTED; `dotmac_sub` follows. Retires nothing, freezes nothing, revokes nothing | `executor-retirement.md` + `executor-retirement/<product>.toml` + `executor-retirement-baseline.json` |

| **Guard lifetime baseline** | the one live relaxation whose stated premise names a lane that re-arms it while nothing does — `deployment-conformance.yml`'s `strict-image-audit`, whose description says "the release lane turns it on" though this repository's only caller is dispatch-only and passes it nothing. The same shape as ERP's `require-real-digests: false` beside a descriptor that already held a real digest. Frozen as an exact two-directional ratchet rather than a blanket allow, per the ADR-0018 amendment the guard itself implements | `guard-lifetime-baseline.json` |

## Cross-repo scale, at a glance

Captured 2026-08-02. Counts are enumerated mechanically; see each file for method.
Persisted-state duplication is measured separately and kept frozen in
[`fleet-decomposition-matrix.md`](fleet-decomposition-matrix.md).

| | starter | Sub | ERP | vendor CP |
|---|---|---|---|---|
| Routes | 65 | 3,183 | ~2,278 effective (3,015 decorators) | 40 |
| Templates | 34 (all kernel package data) | 718 | 865 | 0 |
| Base layouts | 1 | — | 17 | 0 |
| CSS toolchain | Tailwind **v4 CSS-first** | Tailwind **v4 CSS-first** | Tailwind **v3.4.19 + JS config** | none |
| Design tokens | 27, colour/font/animation only | 90 role-named (+82 dead) | 77, **value-named** | none |
| Navigation | manifest-derived | hardcoded per portal | 100% hardcoded | manifest-derived |
| Branding | **stub — cannot show a logo or colour** | 4-layer engine, platform/reseller/organization | 25-column model + runtime CSS generator | none (kernel's) |
| Brand fields consumed | ~2 of 74 | ~35 | ~40 | 0 |
| Competing settings stores | 3 (+1 unwired) | 17 | 15 | — |
| Tenant raw CSS | sanitised, preview-only | **none** (token pipeline) | **verbatim, on a public page** | — |
| CSP | strict, 10 directives | **none at all** | 1 directive, `unsafe-inline` + CDN | kernel's |
| Kernel adoption | is the kernel | `0.1.0a8` pinned, 0 imports (slice S2) | **none at all** | `0.1.0a8`, 9 modules, allowlist test-enforced |
| Tenant isolation | RLS + dynamic catalog audit | no `tenant_id`, no RLS by design | point-in-time sweep migrations only | platform catalog, grants |

Three readings that matter for the programme:

1. **The reference implementation is not the most advanced one.** Sub already has
   the brand-precedence model and the role-named token vocabulary the foundation
   needs; the starter has neither. ADR-0006 § 3 therefore adopts Sub's model
   rather than inventing one, and U1's token vocabulary should start from Sub's
   `design-system.css`, not the starter's 27 colour tokens.
2. **ERP is the outlier on every axis** — no kernel, no import boundary, an older
   CSS toolchain, value-named tokens, and its own licence scheme. It is a
   greenfield adoption target, not a repo with fork drift to reconcile.
3. **Scale is asymmetric by more than an order of magnitude.** Any "extract the
   shared component" plan sized against the starter's 34 templates will be wrong
   by ~20–25× against Sub's 718 or ERP's 865.

## Coverage of the F0 deliverable

| F0 deliverable | Where |
|---|---|
| Foundation ADR | `docs/adr/0006-white-label-product-foundation.md` |
| Module/package ownership map | ADR-0006 § 2 (target) + the per-repo inventories (current owners) |
| Complete UI-surface inventory | `starter-surfaces.md`, `sub-surfaces.md`, `erp-vendor-surfaces.md` |
| Template, CSS, static-asset, navigation inventory | same three |
| Branding/settings inventory across starter, ERP, Sub | `branding-settings.md` |
| Migration/table collision inventory | `migration-collisions.md` |
| Kernel-restatement sweep (adoption recon) | `kernel-restatement-sweep.md` |
| Supported product-profile matrix | ADR-0006 § 4 |
| Brand precedence decision | ADR-0006 § 3 |
| Module vs theme vs product-facet terminology | ADR-0006 § 1 |

## Coverage beyond F0

| Deliverable | Where |
|---|---|
| Native mobile three-app inventory | `mobile-application-sources.md` |
| Mobile client contract (session, data scope, queued mutation, push intent, wipe, auth state machine) | `docs/adr/0065-mobile-clients-are-composed-applications.md` (Proposed) |
| Mobile authorization server, client type, token exchange and rollout order | `docs/adr/0069-mobile-authentication-federates-to-the-existing-identity-provider.md` (Accepted 2026-08-26) |
| Teardown invariants for any client holding a refreshable bearer credential | `docs/adr/0067-a-credential-holding-client-tears-down-atomically.md` (Accepted 2026-08-26) |

ADR-0065 decides **no shared mobile package yet**, and is explicit that this is
a readiness decision rather than a permission problem. ADR-0006's 2026-08-12
amendment ruled that a second consumer is **evidence, not permission**, and that
all three dossier states permit a shared module — so the adopter count is not
the reason. The four grounds are: the contracts are proposed rather than
ratified, the package boundaries are unproven, enforcement is missing
(**thirteen** of the ADR's seventeen enforcement rows say `none yet`, and this
Python repository cannot run Dart checks at all), and
the twelve defects in the inventory's § 6 are the current work (eleven still open; D10, the missing codegen freshness gate, was closed by Sub PR #2719).
Four further findings measured while taking the 2026-08-26 rulings are held
separately as **R1–R4** in the inventory's § 6a, deliberately outside the D-series
count so neither number goes stale.

ERP "DotMac Frontline" is recorded, by Michael's **2026-08-26 ruling**, as a
**future candidate — not a concrete candidate and not an adopter**: `dotmac_erp`
holds zero Dart, so it fails ADR-0006's concrete-candidate test ("an assembly
that exists and will consume it"), and **a specification proves intent, not
consumption**. The consequence is that **no mobile package dossier may be opened
at any state, `audit-complete` included**. Both
documents also establish a standing rule: **evidence is tracked per contract
slice, never per application.** Frontline's locked online-only MVP could
eventually evidence `MobileSessionContextV1` and `MobileDataScopeV1`; it can
never evidence `QueuedMutationV1` or `PushIntentV1`, which have no candidate at
all. ADR-0065 § 11 additionally fixes the shape any future extraction takes, one
of whose rules — regenerate committed code and fail on drift — was never gated
on extraction and has already landed green in `dotmac_sub`'s `field-flutter`
job.

ADR-0069 (Accepted) closes the one question ADR-0065 left open: mobile clients
federate to the existing `idp.dotmac.io` Keycloak realm using **public** native
clients with Authorization Code + PKCE **S256** and OS-browser authentication,
exchanging the ID token inside Sub for a Sub-owned session via
`dotmac_kernel.external_identity.finalize_external_login`. **No client secret and
never the confidential `dotmac-auth-oidc` client goes into a Flutter artifact** —
that package requires a `client_secret`, sends it as HTTP Basic on the token
exchange, and rests on a server-side single-use state store plus an `HttpOnly`
cookie, none of which a device has. `field_mobile` adopts first; customer
self-care is deferred **until Keycloak has HA**. **Seven** of its nine
enforcement rows say `none yet`; one is partial, and one — *identity-provider
roles never grant product permissions* — is already enforced at source level in
the kernel binding seam and its ERP counterpart.

ADR-0067 (Accepted, fleet-wide) owns the four teardown invariants that ADR-0065
§§ 3, 7 and 8 implement for mobile — atomic credential record, generation fencing
with a durable half, one wipe coordinator with no subset clears, and *transport
failure is not revocation*. It binds clients that persist a **refreshable bearer
credential**, explicitly not ordinary server or browser cookie sessions. **Three**
of its four enforcement rows say `none yet` and the fourth is partial, and it
says why: every in-scope client in the fleet is a Flutter application, and this
Python repository cannot run a check over any of them.

## Release records

- `release-record-kernel-a99-ui-a8.md` — publication coordinates for `dotmac-kernel`
  0.1.0a99 and `dotmac-ui` 0.1.0a8 (tags, runs, byte chain, registry read-back,
  installed-artifact canary). Publication only; it asserts no product adoption.

## Presentation-layer census

- `presentation-layer-sources.md` — read-only census of the ten presentation
  categories across `dotmac_sub`, `dotmac_erp`, `dotmac_platform_control_plane`,
  `dotmac_starter_mt` and `dotmac_workspace`, at named commits. Evidence and
  boundary rulings only; explicitly NOT a decision to extract anything
  (ADR-0006 § 5).

- `semantic-encoder-sources.md` — the inventory behind
  `dotmac_kernel.semantic_encoding`'s **`greenfield-after-inventory`**
  classification, at immutable `origin/main` revisions of `dotmac_starter_mt`,
  `dotmac_sub`, `dotmac_erp`, `dotmac_vendor_control_plane`, `dotmac_crm`,
  `dotmac_integrator` and `dotmac_workspace`. The finding is a NEGATIVE: no
  product holds an encoder with all four qualifying properties (length-prefixed
  framing, a TYPED absence sentinel, exact money at currency scale, a
  domain-separated digest), so there was no qualifying product-first source to
  port. Records every near-miss and the exact property it fails on — ERP's
  production `_content_source_version` (P1+P3, no P4, magic-string sentinel),
  Sub's `migration_source/canonical.py` (which rejects the typed sentinel in its
  own docstring), `dotmac-tax`'s `rv1` (the only correct P1), `dotmac-sales`'
  `canonical_digest` (the only correct P4) — and records that NO audited
  implementation has a typed absence sentinel. Claims no release, pin, adoption
  or production state.
