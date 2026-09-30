# ADR 0006 — White-label product foundation: packages, modules, themes, brands

**Status:** Accepted
**Date:** 2026-08-02
**Extends:** ADR-0003 (composable deployment profiles), ADR-0002 (starter
consolidation), ADR-0001 (multi-tenancy)
**Owns:** the package split, the module/theme/brand/facet terminology and the
facet runtime contract (2026-08-25 amendment), the brand precedence chain, and
the extraction rule for the white-label foundation programme (F0)
**Does not own:** module/plugin mechanics (the module control-plane directive),
deployment/commercial authority (ADR-0003), artifact distribution (ADR-0005)

## Context

ADR-0003 decided that every Dotmac deployment shape composes from one kernel,
versioned modules, a product assembly, and a deployment profile. It did not
decide **how presentation is shared**. In practice each product has grown its own
templates, its own CSS, its own navigation, and its own notion of "brand", so the
same table, the same form, and the same empty state exist several times over, and
white-labelling a product means editing its source.

The programme objective is:

> Any Dotmac product can be assembled from trusted, versioned modules; presented
> through a consistent accessible UI; branded without source changes; configured
> without hardcoding; and released as a tested SaaS, dedicated, on-premises,
> offline, or OEM deployment.

Three failure modes have to be designed out before any code moves:

1. **Extraction from similarity.** Two templates that look alike are not evidence
   of a shared contract. Extracting them produces a component with two owners and
   no authority — the exact drift ADR-0003 exists to prevent.
2. **Conflating presentation with capability.** If a "portal" is modelled as a
   module, every audience needs its own copy of every capability. If a theme can
   carry behaviour, a branding change becomes a code change with a code change's
   risk.
3. **Conflating display brand with legal identity.** A white-label build that can
   silently change who the data controller is, or who the support contact is, is
   a compliance defect, not a feature.

This ADR fixes the vocabulary and the ownership boundaries so F1–P1 have a
stable frame. It changes no runtime behaviour.

**One F0 finding reframes the work ahead and belongs here rather than buried in
an inventory.** The starter's branding system is largely *inert*: of its brand
keys, only `name` changes anything a user sees. `brand.mark` is rendered by two
templates but appears in no key map, default, or allowlist, so every deployment
shows the same hardcoded letter; `logo_url` is editable, persisted, and read by
no template; `primary_color`/`accent_color` paint swatches in the branding
editor's preview while the real colours are compile-time Tailwind classes. The
practical position is that **the portal cannot currently display a customer logo
or colour at all**. U2 is therefore not "improve branding" — it is "branding is a
stub; build it" — and the token system U1 produces is the prerequisite that makes
a runtime colour possible in the first place. Evidence:
`docs/inventories/starter-surfaces.md`.

## Decision

### 1. Four distinct concepts, with four different authorities

Do not use these words interchangeably. Each has a different authority, a
different lifecycle, and a different blast radius.

| Concept | What it is | Authority | May contain | May NOT contain |
|---|---|---|---|---|
| **Module** | A versioned unit of **capability** | `ModuleManifest` + `ModuleRegistry` (installed code) | routes, services, models, migrations, declarations, capability codes | another module's imports; presentation primitives owned by the UI system |
| **Theme** | A versioned unit of **presentation** | `ThemeManifest` (installed trusted code) | token defaults, packaged assets, declared template/slot overrides | business logic, data, migrations, routes, DB reads |
| **Brand** | **Data** describing display and contact identity | `BrandProfile` (resolved at runtime) | names, logos, colours chosen from allowlisted tokens, URLs, sender/footer presentation | code, Jinja, JavaScript, CSS text, capability grants |
| **Product facet** | A **surface** presenting modules to one audience | the deployment profile (which facets mount) | layout, navigation, and route composition for that audience | capability decisions of its own |

A **product facet** is the concept the codebase has been missing. Staff
administration, tenant administration, customer self-service, reseller, vendor,
field technician, public/signup, email, document, and API-only are *facets*, not
modules and not deployments. A module contributes surfaces to one or more facets;
a deployment profile selects which facets are mounted; a facet never owns a
capability decision. This is what makes "the customer portal needs the same
invoice view as the staff portal" a composition question rather than a
duplication question.

**Corollary — the two version axes.** A module declares both the module contract
version it was built against (kernel-owned, `ModuleManifest.contract_version`)
and the UI contract version it renders against (`dotmac-ui`-owned). They evolve
independently: a UI component library revision must not force every module to
re-declare its capability contract, and vice versa.

### 2. Package ownership map

```text
dotmac-kernel          invariants that must be corrected exactly once
  tenancy, sessions, transactions
  identity, authorization, audit
  settings and branding RESOLUTION
  module registry and lifecycle
  capability/entitlement decisions
  migration orchestration
  app/product composition

dotmac-ui              the presentation system (no business logic, no DB)
  semantic design tokens
  Jinja/HTMX component library
  layouts and navigation primitives
  forms, tables, feedback states
  accessibility contracts
  packaged static assets

dotmac-module-sdk      development and conformance tooling (never a runtime dep)
dotmac-template-studio a MODULE — the first stateful one, not a kernel facility
dotmac-theme-*         trusted packaged themes, where tokens are insufficient

product assemblies     exact pins + selected modules + theme/brand + provider
                       bindings + deployment profile
```

**Dependency direction is one-way and enforced:**

```text
assembly → module → dotmac-ui → dotmac-kernel
```

> **Dependency correction — 2026-08-25.** The linear diagram above is
> superseded by the enforced graph: the assembly independently imports selected
> modules, `dotmac-ui` and the kernel; a module may import the kernel;
> `dotmac-ui` imports none of them and has only Python as a runtime dependency.
> In particular, neither a module nor `dotmac-ui` imports the other. This note
> preserves the historical text while reconciling it with the import-linter
> contracts and AGENTS.md rule 16.

- The kernel never imports `dotmac-ui`, a module, a theme, or an assembly.
- `dotmac-ui` never imports a module or reads a database. It renders what it is
  given.
- A module never imports another module (already enforced by import-linter;
  cross-module UI composition uses the htmx-fragment pattern, not an import).
- A theme never imports a module and never reads the database.
- `dotmac-module-sdk` is a development/test dependency only. A product that ships
  with the SDK in its runtime image is a packaging defect.

**Ownership rulings that follow, and that later steps may not relitigate:**

- **Settings remain one kernel-owned facility.** Modules contribute
  `SettingSpec` declarations. A module that creates its own settings table,
  resolver, or `.env` convention is a defect, not a variation.
- **Branding RESOLUTION is kernel-owned; branding DATA is not code.** A theme
  supplies token *defaults*; a `BrandProfile` supplies *data*; the kernel
  resolves and reports the effective source. No component reads brand config
  directly.
- **Template Studio is a module, not a kernel facility.** It is stateful,
  optional, and has its own lifecycle. The kernel's own operational templates
  (error pages, the login screen) are code and stay in the kernel/UI packages —
  they are not Template Studio content. **Narrowed by the 2026-08-10 amendment
  (§ 5b):** it owns *what the message says* and nothing else — not document
  generation, not consent, not routing, not delivery.
- **Navigation is derived, never authored twice.** A facet's navigation is
  composed from module manifest declarations. A hardcoded link list in a template
  is a defect. This is already the admin portal's design — the sidebar renders
  from the manifest-derived `nav_items` global, and
  `test_nav_items_paths_exist_in_web_routers` fails a nav entry with no mounted
  route — but note that no test yet fails a template that *adds* its own
  hardcoded links. Generalising the rule to every facet needs that missing check,
  which is F2 work, not an existing guarantee.

### 3. Brand precedence

Brand resolution is **per field**, most specific wins:

```text
generic kernel default
  < vendor/deployment brand
  < OEM/reseller brand
  < tenant/operator brand
```

This chain is **not a proposal — three of its four layers already exist and work
in `dotmac_sub`**, whose `BrandProfile.scope_type` is constrained to
`platform | reseller | organization` (`app/models/branding.py:28-29`), backed by
a `brand.json` shared with its Flutter apps and a runtime `/branding/theme.css`
with contrast gating and a fail-safe. The decision is therefore to **adopt Sub's
proven model**, adding the generic kernel-default layer beneath it and the two
rules below — not to design a new one. Sub's implementation is the reference; the
starter's is the stub (see below).

**Adopt Sub's precedence model and token pipeline; do NOT adopt its defaults
module.** Sub's built-in brand defaults are the real DotMac production identity
(`DotMac`, `Dotmac Technologies`, `support@dotmac.ng`, `noreply@dotmac.ng`, and
the `dotmacpay` payment URL scheme) — which the starter deliberately refuses to
ship. Taking that module wholesale would make every unbranded fork send mail as
`noreply@dotmac.ng` and collide on a mobile URL scheme its own Flutter config
says must be unique per brand. The kernel-default layer this ADR adds beneath
Sub's three must be **generic**, and enforcing that is a two-brand-canary check,
not a code review habit.

Three rules make this safe:

1. **Every resolved field reports its source.** "Effective value + which layer
   supplied it" is part of the contract, not a debugging convenience — support
   cannot answer "why does this deployment show that logo?" without it.
2. **A layer may LOCK a field against lower-precedence override.** An OEM that
   must present its own support identity to its downstream tenants needs the
   tenant layer to be unable to replace it. Locking is explicit and recorded, not
   an emergent property of which layer happens to set a value.
3. **Display brand is separate from legal identity.** Legal vendor,
   data-controller, and support identity are contract-derived data with their own
   authority. They are represented as distinct fields, they are not stylable, and
   a lower-precedence layer may never override them. A white-label build changes
   what the product *looks* like; it must never change who is *legally
   responsible* for it without an explicit contractual change.

**Consequence for tenant-supplied CSS.** Raw tenant CSS cannot satisfy rule 3:
CSS alone can obscure, reposition, or restyle legal, consent, and
security-relevant UI, and sanitisation of the *input* does not restore that
invariant — the sanitiser's job is to block script vectors, not to guarantee that
a footer remains legible. The target is therefore **allowlisted brand tokens for
tenants, trusted packaged CSS for OEM themes** — no user-supplied Jinja, no
arbitrary JavaScript, no theme code loaded from the database.

Two facts about the *current* implementation, verified during F0, that this
decision must not misrepresent (see `docs/inventories/starter-surfaces.md` and
`branding-settings.md`):

- `custom_css` today renders **only inside the branding editor's own preview
  pane** (`templates/admin/settings/branding.html`), never in `base.html`. The
  site-wide exposure is therefore *latent*, not live — it becomes real the moment
  someone "finishes the feature" by wiring it into the base layout, which is
  exactly why the decision is being taken now rather than after.
- The CSP relaxations attributable to branding are **two, and only one of them is
  fully recoverable by this decision** (`docs/SECURITY.md` § "Content-Security-Policy
  rationale" is explicit about both causes):
  - `img-src 'self' data: https:` — the `https:` exists *solely* so tenant
    branding can point `logo_url` at an external image. Moving logos to
    deployment-packaged assets recovers `img-src 'self' data:` outright.
  - `style-src 'self' 'unsafe-inline'` — cited as covering the sanitised
    `custom_css` preview **and** Alpine's `x-show` style toggling. Retiring
    `custom_css` therefore does **not** on its own recover `style-src 'self'`;
    that additionally needs the Alpine dependency addressed (its CSP build, or
    splitting `style-src-elem` from `style-src-attr`). Claiming otherwise would
    set up a hardening promise the change cannot keep.

So `custom_css` is a compatibility seam to be retired on a stated path — justified
primarily by rule 3, with a real but partial CSP dividend.

**What CSS injection actually buys an attacker**, since "it's only CSS" is the
usual reason this gets deferred: `display:none` and `::after{content}` hide or
rewrite legal and consent text; `position:fixed` + `z-index` overlays destructive
controls *same-origin*, so `frame-ancestors 'none'` is irrelevant to it; and
attribute selectors of the form `input[value^="a"]{background:url(https://…)}`
exfiltrate field contents character by character — permitted by the starter's
sanitiser, which allows `http`/`https` URLs, and by `img-src https:`. These are
CSS's *intended* semantics, which is precisely why no sanitiser removes them.

### 4. Supported product-profile matrix

The profiles the foundation must prove, as the cross-product of ADR-0003's
independent axes. These are the CI targets, not marketing names:

| Profile | Tenancy | Operator | Connectivity | UI surface | Update authority |
|---|---|---|---|---|---|
| `saas-multitenant` | shared | vendor | online | web + API | vendor automatic |
| `dedicated-single-tenant` | one tenant | vendor | online | web + API | vendor automatic |
| `onprem-online` | one or more | customer | online | web + API | customer-approved |
| `onprem-airgapped` | one or more | customer | air-gapped | web + API | offline bundle |
| `oem-multitenant` | shared | OEM partner | online | web + API | vendor/OEM agreed |
| `api-only` | any | any | online | API only | any |

Orthogonal to the table, every profile must additionally pass the **two-brand
canary**: the same assembly built twice, differing only in configuration, theme,
and lock — never in source.

### 5. The extraction rule (the F0 gate)

**Nothing is extracted into `dotmac-ui`, a shared module, or the kernel on the
grounds that two implementations look similar.** A candidate for extraction must
present:

1. **Two independent consumers of the same CONTRACT** — the same inputs, the same
   semantics, the same failure behaviour. Similar markup is not a contract.
2. **A named owner** for the extracted unit, per the Dotmac source-of-truth
   standard.
3. **A migration and cutover path**: which consumer moves first, what the shadow
   period is, and how drift is detected afterwards.

Absent all three, the duplication is recorded in the inventory and left in place.
Recording it is the deliverable; removing it is not.

## Inventories (the rest of the F0 deliverable)

The as-built characterization this ADR rests on lives in `docs/inventories/`, and
is deliberately separate from this file: the ADR states decisions, the
inventories state facts, and facts go stale. See `docs/inventories/README.md` for
the index and the as-of date of each.

## Open decisions surfaced by F0 (NOT decided here)

F0's job is to record what exists and to decide the foundation's vocabulary and
boundaries. It surfaced eight questions that are **owner decisions, not
inferences this ADR may make on its own**. Each blocks a named later step. They
are listed with evidence so the decision can be taken on facts rather than
re-derived.

| # | Decision needed | Blocks | Evidence |
|---|---|---|---|
| **D1** | **Namespacing for module tables and Alembic revision IDs.** Postgres schema per module, or an enforced table-name prefix? Plus a revision-ID prefix registry. | F4 (migration orchestrator); any module composition at all | `migration-collisions.md` |
| **D2** | **Which licence format survives** — ERP's own scheme (`dotmac_erp/app/licensing/`, 478 lines) or kernel WS8. Two incompatible formats exist in the fleet today. | ERP adoption; O1 | `erp-vendor-surfaces.md` |
| **D3** | **Does `dotmac-ui` require Tailwind v4 CSS-first, or stay toolchain-agnostic?** Starter and Sub are both v4 CSS-first; ERP is v3.4.19 with a JS config. ERP is the outlier, so "require v4" is a migration cost in exactly one repo. | U1 | all three surface inventories |
| **D4** | **Are the vendor-named licence schema IDs** (`dotmac-licence-envelope/1` and three siblings) **renamed before or never?** They are on the signed wire contract; renaming later is a breaking protocol change. | O1; OEM profile | `starter-surfaces.md` |
| **D5** | **Amend the kernel import allowlists to admit a UI package.** Sub's ledger currently permits `assembly, capabilities, features, money, profiles, providers*` and **no** templating/branding/UI module. A shared UI package cannot be adopted without that amendment. | U1 adoption | `sub-surfaces.md` |
| **D6** | **Is `/admin` (and each facet's prefix) configurable?** It is currently baked into 45+ template literals, the web guard, and the governance tests' path prefix. An OEM that wants `/manage` cannot have it. | U1/U2; OEM profile | `starter-surfaces.md` |
| **D7** | **Which CSP the shared kernel emits.** The three postures are mutually exclusive: the starter ships a strict policy; ERP ships literally one directive (`script-src 'self' 'unsafe-eval' 'unsafe-inline' https://cdn.jsdelivr.net`, via `CSP_ALLOW_UNSAFE: 'true'`) plus a *per-organization runtime* Google Fonts URL that cannot be statically allowlisted; Sub emits **no CSP at all**. A kernel emitting the starter's policy breaks ERP on the first request. | U1 adoption; O1 | `branding-settings.md` |
| **D8** | **Does "no tenant-supplied raw CSS; brand customisation is an allowlisted token set" become an approved cross-Dotmac standard?** This ADR decides it for the foundation; making it fleet-wide is a separate ruling. | U2; ERP/Sub convergence | `branding-settings.md` |

**D1 is the one that blocks everything.** It is verified, not theoretical:
`starter ∩ ERP` collide on `audit_events`, `domain_settings`, `people`,
`person_roles`, `roles`, `user_credentials`; `starter ∩ Sub` collide on
`parties`, `party_roles`. Sixteen of seventeen cross-repo duplicate table names
are **same-name, different-shape**, and they sit almost entirely on
kernel-shaped tables — identity, authn, authz, settings, audit. Three of four
repos use no schema namespacing at all, so collision avoidance today rests
entirely on convention. Unlike a revision-ID clash, which fails loudly at
`ScriptDirectory` load, a same-name/different-shape table collision fails
**quietly in the dangerous direction**: an `add_column` mutates another module's
table, and an ORM class mapped to a differently-shaped existing table reads wrong
rows. No module composition should ship before D1 is answered.

### Decision amendment — 2026-08-02 (D1–D8 resolved)

The owner delegated these eight decisions after reviewing the F0 evidence. The
original questions above are retained as the historical decision record; the
rulings below are normative for F2–P1.

#### D1 — a dedicated Postgres schema per stateful module; registered migration prefixes

Every independently installed stateful module owns one immutable Postgres
schema namespace. The namespace is assigned in the module registry, uses the
form `mod_<short_code>`, and is never inferred from a display name. Module
models, migrations, foreign keys, policies, functions, and raw SQL fully
qualify their schema; they never depend on `search_path`. A stateless module
declares no database namespace.

`public` remains the compatibility namespace for the existing kernel and the
one host assembly. It is not available to installable modules. Existing ERP or
Sub tables do not become module tables merely because their code is extracted:
the extraction's expand/contract migration must create or adopt the assigned
module schema explicitly. Until that cutover is proven, the source product and
the candidate module are not composable in one database.

Each migration owner also receives an immutable, globally unique short prefix
from the registry. Revision IDs use `<prefix>_<sequence>_<slug>` within
Alembic's version-column length; the module lineage has its own base and branch
label, and cross-lineage ordering uses `depends_on`, never `down_revision`.
The existing composed `alembic_version` table remains the migration truth;
manifest-to-branch attribution makes its rows explainable. A composed CI gate
must load every selected version location and reject duplicate revisions,
prefixes, branch labels, schema claims, or table ownership before an image can
be built. The post-migration live-catalog gate applies the kernel RLS/grant
contract across every registered module schema.

##### D1 amendment — 2026-08-13: cross-lineage ordering is LOGICAL

The clause above ("cross-lineage ordering uses `depends_on`") is amended. It
assumed a module could name the revision it needs. A module cannot, because the
answer differs per assembly, and a physical edge is therefore a claim about a
deployment the module has never seen.

**The blocked adopter, which is evidence rather than hypothesis.** Kernel
revision `0001_initial_tenant_schema` creates `public.tenants` unconditionally
as its first table. ERP hosts that same table in its own lineage
(`20260813_tenant_projection`, merged to ERP `main` as `c5f933d9`), so kernel
`0001` can never run there — its lineage rehearsal is pinned permanently at that
collision, and no product-side disposition of `people`, `roles` or
`audit_events` can move it. `dotmac-files` declared
`depends_on = ("0001_initial_tenant_schema",)`, which made stored bytes
un-installable in ERP unless ERP first converged its entire identity, RBAC and
audit estate onto the kernel's. That is a large amount of coupling to buy a
foreign-key target, and none of it is required by what files actually needs.

**Amended rule.** A module lineage declares the logical database EFFECTS it
requires (`ModuleManifest.requires`, `dotmac_kernel.prerequisites`); the
answering lineage declares what it supplies (`MigrationOwner.provides`); and each
assembly binds requirement to provider revision in checked-in, typed
`PrerequisiteBinding`s installed from its Alembic `env.py`. A module lineage may
**not** name a foreign revision directly. Host owners (`kernel`, `assembly`) keep
literal edges: they are the deployment, so naming one of their own revisions
asserts nothing about anybody else's.

**Ordering is preserved, not weakened.** `resolve_depends_on` turns the binding
back into a real `depends_on` edge at script-load time, so Alembic orders exactly
as before. What changes is who authors the edge.

**A binding is a claim, so it is never the only control.** Two guards, neither of
which is a comment:

1. the composed gate rejects a module naming a foreign revision, an unbound
   requirement, a binding to a lineage that does not declare the effect, a
   binding to an uncomposed revision, and a migration requiring more than its
   manifest admits;
2. `require_prerequisites` verifies the real catalog before any DDL, so a
   **stamped** or aliased provider fails against the database — stamping writes
   no columns.

Ordering itself needs no third guard, and an early draft that added one was
wrong twice over. It asserted the bound revision appeared in `alembic_version`,
but that table records each branch's current HEAD, not applied history — so the
check failed against every real database once a lineage advanced past its root.
It was also redundant: `resolve_depends_on` emits a real `depends_on` edge and
Alembic will not run a revision before the one it depends on, while a binding
naming an uncomposed revision is already rejected statically. What only the
database can answer is whether the EFFECTS are present, which is guard 2.

A blanket `IF EXISTS`, a product-specific conditional inside a kernel migration,
and `alembic stamp` remain forbidden and are not bindings.

**Vocabulary is a registry, never an enum** (ADR-0008). The kernel ships
`tenant_scope_catalog.v1` and `module_database_roles.v1` because those are the
two effects a real blocked adopter needed; a product names its own without a
kernel change. A changed contract is a new `.vN`, never a redefinition — every
existing binding was accepted against the old one.

**Status under ADR-0017.** This is a blocked-adopter exception, not a
supply-pushed facility: it was built because ERP is blocked today, the
verification logic is EXTRACTED from ERP's proven `20260813_tenant_projection`
rather than invented (hard rule 22, product-first), and it removes an adoption
blocker instead of adding surface awaiting adopters.

#### D2 — kernel WS8 is the sole target licence protocol

The signed, versioned WS8 licence, applied-state, keyring, and revocation
contracts survive. ERP's existing format is legacy input only: ERP E10 must
inventory it, issue or map replacement WS8 state, shadow-verify the cutover,
and retire the old verifier and writer. There is no permanent dual-authority or
"accept either forever" mode.

#### D3 — `dotmac-ui` is toolchain-agnostic to consumers

`dotmac-ui` may use Tailwind v4 to build its own released assets, but its public
contract is compiled, versioned CSS/assets, semantic tokens, stable component
classes/data attributes, and Jinja/HTMX APIs. A consumer does not run the UI
package through its own Tailwind compiler and does not need the same Tailwind
major. ERP may migrate from Tailwind v3 separately; that migration is not an
adoption prerequisite.

#### D4 — the `dotmac-*` licence schema IDs remain permanent protocol identifiers

The schema IDs identify the software/protocol vendor, not the deployment's
display brand. White-labelling must not rewrite signed protocol identity.
They therefore remain stable for version 1 and may change only for a real,
versioned protocol break with an explicit compatibility window — never as an
OEM cosmetic substitution.

#### D5 — allow `dotmac_ui` through a narrow, explicit consumer boundary

Product architecture allowlists will admit the released top-level `dotmac_ui`
public surface in the same change that introduces a real consumer. This does
not grant modules access to kernel templating or branding internals and does
not permit arbitrary presentation packages. The ledger, import guard, wheel
consumer proof, and supported UI-contract range must move together.

#### D6 — facet prefixes are deployment-static, not tenant-runtime settings

HTML facet mount prefixes are assembly/profile configuration resolved at
startup, with `/admin` retained as the default. Templates and redirects use
named route generation rather than literal prefixes. Prefixes must be absolute,
normalized, unique, non-overlapping, and outside reserved API/platform paths.
They cannot vary by tenant inside one running assembly. Versioned JSON API
prefixes remain protocol contracts and are not rebranded.

#### D7 — kernel owns a composed strict CSP contract, not one fleet product's string

The kernel supplies a deny-by-default CSP baseline and a typed composition
mechanism for requirements declared by trusted installed packages and the
assembly. Modules and tenants cannot contribute raw directives or arbitrary
origins. The resolved policy is deterministic and inspectable, and unsafe
directives, wildcards, CDNs, and runtime per-tenant origins fail the supported
profile gate unless an explicit temporary compatibility ADR names their owner
and retirement condition.

The starter policy is the target posture, not something silently imposed on an
incompatible ERP deployment. ERP must vendor its jsDelivr dependencies and
runtime Google Fonts, remove `unsafe-eval`, and pass report-only canaries before
enforcement. Sub gains the composed policy through the same compatibility
gate. `dotmac-ui` ships self-hosted, CSP-compatible assets.

#### D8 — no tenant-supplied raw CSS is a fleet-wide standard

Tenant/operator brand customization is an allowlisted, typed token set with
contrast and URL validation. Trusted CSS exists only in versioned theme/UI
packages. Starter and ERP stop accepting new raw-CSS writes; existing values
are retained only as migration evidence until they are exported, mapped to
tokens where possible, and explicitly retired. Unrepresentable rules are
reported to the operator and are never silently copied or silently discarded.
Sub's token-only pipeline is the reference posture.

### Decision amendment — 2026-08-08 (product-first extraction)

Section 5 prevents speculative extraction, but its phrase "left in place" did
not say what to do once an extraction is approved and one product already has a
mature, tested implementation. The owner has now resolved that ambiguity:

1. **Inventory the products before writing shared behaviour.** For a candidate
   kernel facility or optional module, ERP, Sub, and any other product named in
   the candidate's scope are searched first. When a production-used,
   sufficiently tested implementation already satisfies most of the agreed
   contract, that implementation is the mandatory reference and initial code
   source. A greenfield implementation is admissible only when the checked-in
   inventory shows that no qualifying product implementation exists.
2. **Copy means a one-time extraction, not a maintained fork.** The proven code
   and its behaviour tests are moved or ported into the shared distribution.
   Product-specific dependencies are cut at typed adapter/provider seams; the
   underlying behaviour is not rewritten merely to look more generic. The
   source product is the first cutover consumer and its local owner/writer is
   then removed or explicitly gated for retirement.
3. **Place the unit at the narrowest shared layer.** Behaviour required by every
   assembly and free of business-domain policy belongs in `dotmac-kernel`.
   Optional business capability belongs in its own independently versioned
   `dotmac-<module>` distribution, with its own manifest and, when stateful,
   its own schema and migration lineage. Product-only behaviour remains in its
   product even if another implementation looks similar.
4. **Preserve proof and make the cutover repairable.** Every shared distribution
   carries an extraction dossier naming the contract, source repositories and
   paths, source tests preserved as parity proof, two contract consumers, the
   owner, first cutover, shadow/drift check, and local-copy retirement gate.
   Existing distributions predating this amendment are recorded as explicit,
   non-growing debt rather than silently treated as conforming.

This amends, rather than relaxes, the original F0 gate. The two-consumer,
named-owner, and migration requirements still decide **whether** a unit may be
shared. Product-first extraction decides **how** it is implemented once that
decision is made. It forbids both failure modes: speculative shared code with no
real consumer, and a second implementation written beside mature product code.

### Decision amendment — 2026-08-18 (vertical replacement cutover)

The product-first amendment says the source product is the first cutover
consumer. That remains the default for an in-place extraction. It was written
before an accepted programme had a different, stricter destination: retire a
legacy product vertically into a clean assembly without first rebuilding the
legacy product around the target architecture.

For an **accepted vertical replacement**, the replacement assembly may be the
first runtime consumer when all of the following hold in checked-in evidence:

1. the legacy product is named as the qualifying implementation source and the
   replacement assembly is named as the destination;
2. composing the module in the source would require a throwaway rewrite of a
   lineage, identity or transaction boundary the accepted programme says to
   retire;
3. the replacement imports data only through a versioned API/webhook, never the
   source database, models or filesystem;
4. the overlap is read-only shadow/reconciliation: the source remains the sole
   writer until one sealed cutover makes the replacement the sole writer and
   fails closed the source mutations; and
5. the source writer, fallback and obsolete tables still have explicit
   ratchets and retirement gates. Moving the runtime without retiring the old
   authority earns no adoption evidence.

In that case the source product is the **first authority retired**, while the
replacement assembly is the first exact-pin runtime consumer. Source code and
tests remain the mandatory extraction base. The evidence ladder is unchanged:
one runtime consumer supports `adopted`; `reuse-proven` still requires two
independent consumers of the same released contract.

The first named use is ERP -> Backoffice, accepted in
`dotmac_backoffice/docs/adr/0001-why-backoffice-exists-and-why-replacement-is-vertical.md`.
ERP cannot truthfully compose kernel Party/tenancy without the very aggregate
redesign that decision rejected. Requiring that detour would improve the
temporary bridge instead of retiring it. The specific source ruling and
cutover gates are in
[`../inventories/people-directory-sources.md`](../inventories/people-directory-sources.md).
This amendment does not authorize a merge, release, deployment, production
mutation or destructive retirement.

**Correction — 2026-08-22.** The historical reference above used the working
name `dotmac_backoffice` for a local composition sketch. It was never a
separate repository or product. The destination is the commercial Dotmac ERP
product (`dotmac-erp`), vertically recomposed from Starter modules; the
historical extraction source is the `dotmac_erp` repository. The vertical
replacement mechanics remain accepted, but the separate-application identity
is withdrawn.

### Live defects found while taking the inventory (owned elsewhere)

F0 is documentation-only and fixed nothing. Three defects surfaced that are
**independent of every decision above** — they want fixing whether or not the
foundation programme proceeds — and they are recorded here so they are not lost
with the agents that found them. All three were verified directly against the
source, not accepted on report.

1. **`dotmac_erp` injects unsanitised tenant CSS on a public page.**
   `organization_branding.custom_css` is appended **verbatim** to the generated
   stylesheet (`app/services/finance/branding.py:250` — `lines.append(branding.custom_css)`,
   no sanitiser at any layer), and rendered `{{ brand.css | safe }}` inside
   `<style>` in `templates/login.html:12` and the **unauthenticated** careers
   portal `templates/careers/base_careers.html:40`, each under an explicit
   `{# nosemgrep: semgrep.safe-on-user-content #}` waiver. The same content is
   also served from `GET /branding/org/{org_id}/css` (`app/api/settings.py:717`).
   This is CSS injection, not script execution — but see the paragraph above on
   what CSS injection actually buys an attacker. The starter's equivalent is
   sanitised *and* preview-only; ERP's is neither.

2. **`dotmac_erp`'s cached settings read path is not tenant-scoped.**
   `app/services/settings_cache.py:310-356`: `get_setting_value(db, domain, key,
   default)` takes **no** organization argument, queries
   `select(DomainSetting).where(domain==…, key==…, is_active)` with **no**
   organization filter, takes `db.scalar()` (an arbitrary matching row), and
   caches it under `f"settings:{domain}:{key}"` — a key with no tenant
   component. ERP's other read path (`resolve_value`) *is* organization-aware,
   so the two disagree: in a multi-organization deployment this one can serve
   and then cache one organization's value for another.

3. **`dotmac_sub` has multiple writers for logo/favicon/colours**, alongside
   `sync_platform_brand_from_legacy_settings` as an unfinished one-way
   migration. Consolidating on `BrandProfile` without finishing that migration
   inherits a dangling legacy writer — a direct violation of SOT-complete
   criterion 5.

   > **Corrected 2026-08-03, on evidence.** The original wording named
   > `web_system_company_info.py` as the third writer and described it as raw
   > SQL bypassing the spec registry. Both halves were wrong: it uses the ORM,
   > and it writes no logo/favicon/colour key at all, so it was never the
   > branding violation. (It *is* a spec-bypassing settings writer — the
   > `company_*` keys have no `SettingSpec` — which is a separate finding.) The
   > actual dangling branding writer, which the inventory missed, is the
   > **generic comms settings form**
   > (`web_system_settings_forms.process_settings_update`): it wrote all 13
   > branding keys with none of the owner's validators, skipped the
   > managed-asset delete leg, reset absent keys to spec defaults, and never
   > projected onto `BrandProfile`. Consolidated on branch
   > `chore/branding-writer-consolidation` (`20ad2a4f7`). This is why an
   > inventory is evidence to act on, not evidence to trust.

Recording them here is the deliverable. Fixing 1 and 2 is `dotmac_erp` work and
should not wait on this programme.

### Conformance gaps (already decided, not yet honoured)

These need no new decision — ADR-0003 already rules on them — but F0 found the
implementation does not comply, so they are recorded as debt rather than
questions:

- **Locale/currency are not independent of brand.** Sub hardcodes 274 `NGN` and
  17 `Africa/Lagos` occurrences in `app/`, and its `money` / `app_datetime` Jinja
  filters are documented as fixed to NGN/WAT. ADR-0003 § "Internationalization,
  currency, and jurisdiction" already forbids this. In F0 terms: locale leakage
  is *larger* than brand leakage, and a two-brand canary would pass while a
  two-*country* deployment would not.
- **RLS is repo-local and mutually incompatible.** The starter enforces it with a
  dynamic catalog audit; ERP enforces it only via two point-in-time sweep
  migrations, so anything created afterwards silently gets none; Sub has no
  `tenant_id` columns and no RLS by design. A module moving between them cannot
  assume the invariant holds.
- **`alembic_version` is one shared, unattributed table** in all four repos —
  nothing records which module owns which head row. F4's orchestrator needs that
  attribution.

### Decision amendment — 2026-08-09 (build once; an extension point is not a licence)

Section 5 is a brake on sharing things that merely LOOK alike. It says nothing
about the opposite failure, which has now happened: implementing a shape in a
product that every product needs, because an extension point made it easy.

The owner's ruling: **a capability a second Dotmac app would otherwise
reimplement is built in the shared layer, not in the product.** This covers
value types, adapters, and reusable functions — not only things that feel like
"framework".

1. **An open extension point is not a licence to use it.** The kernel's
   registries — permissions, capabilities, audit actions, feature flags,
   setting domains, setting value types, setting scopes, secret sources — exist
   so a product can declare vocabulary that is genuinely ITS OWN. Declaring a
   UNIVERSAL shape through one is the forking failure ADR-0008 exists to
   prevent, arrived at from the other direction: nothing is duplicated, and the
   fleet still ends up with two incompatible definitions of one thing.

   The applied test, before declaring anything on a product manifest: *would a
   second app need this?* If yes, it belongs to the shared layer, and the
   product declares nothing.

2. **This governs SAMENESS; Section 5 governs SIMILARITY. Neither relaxes the
   other.** Two dashboards that resemble each other are not one component, and
   Section 5 still refuses them. A JSON list, a held secret reference, an exact
   money amount are one thing with one correct encoding, and a second
   implementation of one is a defect rather than a candidate. When a concrete
   case looks like it satisfies both readings, it is a Section 5 case — the
   two-consumer, named-owner and cutover gate decides, and "build once" is not
   an argument for skipping it.

3. **Mechanism is shared; policy stays in the product.** Gapless sequence
   allocation under concurrency is a mechanism; what an invoice number looks
   like is policy the product declares. A shared unit that cannot be described
   without naming a business rule is in the wrong place.

4. **Adapters are shared as PORTS, not as vendor bindings.** The typed
   protocol, the held-credential contract (ADR-0009), timeout/retry/
   circuit-breaking, the error taxonomy and the test fake are one thing, built
   once. A specific vendor binding ships as its own `dotmac-adapter-*`
   distribution against that port — inside the kernel it would make every
   assembly inherit that vendor's SDK and release cadence.

**First application.** Sub's settings cutover needed a `list` setting value
type. Sub could have declared one on its own manifest and nothing in this ADR
forbade it; ERP would then have declared an incompatible one. `list` shipped as
a kernel built-in instead (`0.1.0a27`), and `dotmac-kernel`'s `COMPATIBILITY.md`
now states the test above at the point where a reader is choosing.
`secret_ref` follows the same route once the per-secret classification lands.

**Note for the product-first extraction amendment.** That amendment (dated
2026-08-08, in flight on `docs/product-first-extraction` at the time of
writing) decides HOW a shared unit is implemented once sharing is agreed —
inventory the products, port the proven implementation, place it at the
narrowest shared layer. This amendment decides WHERE NEW work goes when no
product implementation is the reference. Its point 3 and this amendment's
points 3–4 overlap on placement and should be read as one rule when both have
landed; if they are ever in tension, the placement wording in the product-first
amendment is the more specific and wins.

### Decision amendment — 2026-08-10 (sweep for restatements before a cutover)

The 2026-08-08 amendment governs EXTRACTION: inventory the products before
writing shared behaviour. Adoption needs the mirror, and its absence has now
cost a measurable amount.

Sub's settings cutover produced seven CI failures across eight push cycles.
They presented as unrelated — a duplicate spec, a type error, a schema
validation error, two mocked-session failures, two query budgets — and were one
root cause seven times: **a fact the kernel owns had been expressed a second
time inside the product**, and the two copies had drifted.

Restatement is not code duplication. The implementations differ, which is
precisely why it survives review. What is duplicated is a DECISION — which
column a value type uses, what a cache key contains, which duplicate spec wins
— and it drifts in one direction only: the kernel changes and the product's
copy silently stops agreeing.

So, before a product cuts over to a kernel subsystem:

1. **Sweep for restatements, not call sites.** For each fact the incoming
   subsystem owns, find where the product already answers it: a vocabulary held
   as an enum or CHECK; a decision taken by comparing against a literal name; a
   key format, TTL or invalidation rule; a data-access shape baked into test
   doubles. Call-site inventories do not find these — Sub's recon counted 560
   call sites and 574 specs and found none of the seven.
2. **Record the sweep before the first push.** `docs/inventories/
   kernel-restatement-sweep.md` holds it, dated, per product, as facts rather
   than mandates like every other inventory.
3. **Each restatement becomes one expression or one recorded debt.** The
   surviving expression is an ADAPTER that ASKS the kernel; it does not decide.
   Anything not migrated in the cutover is a shrink-only baseline in an
   architecture test, so it is bounded rather than forgotten.
4. **Enforce with a test per fact, not with review.** Sub's
   `tests/architecture/test_kernel_owned_facts_have_one_expression.py` is the
   pattern: the permitted adapter is allowlisted, the adapter is itself checked
   for delegating, and the remaining restatements are a list that may only
   shrink.

5. **The sweep PARSES. It does not grep.** This is a correction to the first
   version of this amendment, and the correction is the worked example.

   That version cited a striking finding: eleven of `dotmac_erp`'s twenty-nine
   value-type branches were in HR employee filtering, so `SettingValueType` had
   been borrowed as a general "what kind of value is this" vocabulary. **That
   was false.** HR's `value_type` is
   `Literal["uuid", "date", "string", "enum", "bool"]` — an unrelated
   filter-field type that happens to share an attribute name. A grep for
   `value_type ==` matched it, and a design narrative was built on the match.

   The same grep-shaped sweep under-reported twice more within the hour, in
   `dotmac_sub`: it missed setting specs declared through a
   `build_*_specs(setting_spec)` CALLABLE rather than a literal constructor,
   which caused a duplicate spec to be registered and every test to fail at
   import; and it missed `from ... import DEFAULTS as _ALIAS`, because the
   alias was searched for instead of the name.

   Three misses, one cause: a pattern was guessed at where the question needed
   the syntax tree. `scripts/restatement_sweep.py` is the sweep, and a sweep
   reported without it is an estimate.

   A detector can also over-report, which is the same failure one sign away.
   The first parsing run counted 139 "local cache keys" in Sub — nearly all of
   them permission codes like `"settings:manage"` — and counted a
   `query().filter().filter()` chain as three reads. A finding is only a
   finding once the detector has been checked against what it matched.

This does not gate adoption on a clean sweep — a product with restatements
still adopts. It gates adoption on a KNOWN sweep, so the cutover's cost is
visible before it is paid rather than discovered one CI run at a time.

### Decision amendment — 2026-08-10b (audit scope, and the communication capability map)

The 2026-08-08 amendment made ERP and Sub mandatory *sources*. Executing the
first audit it required — Template Studio's, in
`docs/inventories/template-studio-source-audit.md` — exposed a gap in that
amendment and produced a ruling large enough to record here.

Dated `10b` because a separate amendment landed the same day (*sweep for
restatements before a cutover*); the two are independent and neither supersedes
the other. See the closing note for how this composes with the 2026-08-09
build-once ruling rather than restating it.

#### 5a. Product-first sources the implementation; ADR-0003 sets the scope

Product-first extraction answers *"who already built this well?"*. It does **not**
answer *"what should the foundation own?"* — ADR-0003 does, and it makes this repo
the foundation for new SaaS, dedicated, self-hosted, OEM and single-tenant
products that are not downstream of ERP or Sub. An audit run as *"which product's
code do we port?"* silently lets the two existing products set the ceiling on what
a capability may become.

Two consequences bind every future audit:

1. **"These implementations do not share a contract" never establishes "this
   capability has no contract."** The first is a finding about implementations and
   justifies rejecting a particular package shape. It does not license concluding
   the capability is unextractable, and it does not license moving the capability
   to an out-of-scope list.
2. **A capability leaves the foundation's scope only when it encodes genuine
   product-domain meaning** — ERP finance/HR entity semantics, Sub
   subscriber/network policy. It does **not** leave scope because only one product
   has built it so far, because it is entangled with one product's vocabulary (the
   ADR-0008 split applies: generic mechanism, product-declared vocabulary), or
   because it carries heavy native dependencies (that argues for an optional
   `core=False` module with its own extra, not for exclusion).

An audit concluding *"no single owner qualifies"* has found that the unit was
drawn wrong, not that the work stops. It must then decompose to one decision per
owner and re-run the sourcing question per owner.

#### 5b. Template Studio narrows to one decision

The audit disqualified the package's `kind ∈ {notification, document}` merge on
evidence, not preference: the two products disagree on placeholder language,
engine class, identity dimension and missing-variable policy, and the package's
double-brace syntax is the syntax Sub rejects at save time after it leaked a
literal `{{amount}}` to customers. Accordingly:

- `kind=document` is dropped from the package.
- The renderer re-bases on Sub's contract — single-brace, closed
  per-send-context allowlist validated at save time, unresolved-placeholder
  suppression on the live path — carrying Sub's seven renderer tests as parity
  proof.
- The three things neither product has are kept: tenant-scoped RLS from
  migration 1, the `manage`/`publish` permission split, and immutable versioning
  (ported from ERP's proven *workflow-rule* version history, not designed fresh).
- Its contract is now **what the message says**. It renders and returns
  `(subject, body)`. It does not decide whether to send, to whom, or over what.

This supersedes the section 2 ownership map's implicit reading that Template
Studio owns tenant document templates. It remains a module, not a kernel facility.

#### 5c. The communication capability map — five owners, not one

The capability a new product needs on day one is author → render → decide
eligibility → route → send → prove. It decomposes into five foundation owners
plus the products' own domain, and is mostly already built:

| Owner | The one decision it owns | Qualifying source |
|---|---|---|
| `dotmac-template-studio` | what the message says | Sub's renderer |
| consent / suppression | may we contact this address on this channel | Sub's `CommunicationSuppression` |
| channel policy | which channels carry this class of message | Sub's matrix, mechanism only |
| delivery / outbox | queue, retry, provider result, dedupe | Sub's `Notification` + `NotificationDelivery` |
| document generation | render → PDF → durable record | ERP's `DocumentGeneratorService` + `GeneratedDocument` |
| product domain | which messages exist and what they mean | stays in ERP and Sub |

Three of these were nearly mis-scoped as product-specific, and the rulings that
keep them in scope are the point of 5a:

- **Consent is a legal decision, not an ISP one.** Erasure, hard bounce and
  unsubscribe apply to any product that sends email, including an ERP that only
  ever sends invoices and offer letters. Sub's model already holds the hard part:
  scope `marketing` vs `all`, keyed on the **address** rather than the person,
  with unsubscribe never permitting suppression of someone's invoice. A second
  product reimplementing that is a build-once violation whose failure mode is a
  billing incident, not a cosmetic drift.
- **`GeneratedDocument` is the only concrete implementation of the SOT criterion
  *"every projection has provenance"* in either product** — `content_hash`,
  sanitised `context_snapshot`, `superseded_by` lifecycle. That is foundation
  material.
- **Channel policy generalises at the mechanism, not the vocabulary.** It is the
  weakest of the three and its extraction is the least proven; it may not be
  taken before its own dossier shows otherwise.

**Each owner needs its own extraction dossier.** Bundling them under Template
Studio's would repeat exactly the merge error this audit was commissioned to
catch, and the 2026-08-08 amendment's per-distribution dossier requirement
already forbids it.

**Sequencing is a constraint, not a preference: consent must be answerable before
delivery exists.** Otherwise the first product on the new stack sends without a
suppression check and the legal gate is retrofitted behind live traffic.

This amends, rather than relaxes, section 5 and the 2026-08-08 amendment, and it
composes with the 2026-08-09 one as a third axis rather than restating it:

- **Section 5 governs SIMILARITY** — two things that look alike are not one
  contract.
- **2026-08-09 governs SAMENESS** — one thing with one correct encoding must not
  be built twice.
- **2026-08-08 governs SOURCING** — once a unit may be shared, a qualifying
  product implementation is where it comes from.
- **5a governs SCOPE** — what the foundation should own is set by ADR-0003, and
  an audit may not narrow it by reasoning from the products' current shapes.

The Template Studio audit is a case where all four bite in sequence: § 5 refused
the two-kind merge, 5a refused the conclusion that the capability was therefore
unextractable, 2026-08-09 kept consent and document provenance in the shared
layer, and 2026-08-08 named Sub and ERP as the sources for the pieces that
survived.

#### 5d. What the per-owner dossiers changed — six owners became four

5c named six owners and required a dossier per owner before extraction. Three of
those dossiers have now been taken, and two of them shrank their own owner. The
map named the DECISIONS correctly; two of them turned out to already have homes.

| § 5c owner | Dossier outcome | Where it landed |
|---|---|---|
| template studio | unchanged | `dotmac-template-studio` 0.2.0a2 |
| consent / suppression | unchanged | `dotmac_kernel.consent` (0.1.0a34) |
| delivery / outbox | **shrank** — not a queue | `dotmac_kernel.delivery` (0.1.0a35) |
| channel policy | **dissolved** — it is a setting | `dotmac_kernel.channel_policy`, a reader over one `SettingSpec` |
| document generation | not yet taken | — |
| product domain | unchanged | stays in ERP and Sub |

**Delivery is not a queue.** `docs/inventories/delivery-outbox-sources.md` found
Sub's `Notification` and the kernel's `OutboxEvent` to be the same machine built
twice — status, attempts, backoff, worker lease, stale reclaim and dead-letter all
appear in both. Sub's predates the kernel's. ADR-0014 already routes
non-transactional effects to the outbox, and sending an email is the canonical
one. The delivery owner therefore reduces to a receipt table, a provider seam,
and the feedback loop below.

**Channel policy is a setting, not a subsystem.**
`docs/inventories/channel-policy-sources.md` found Sub stores its entire policy as
one JSON document in `domain_settings` and resolves it through ordinary settings
precedence. The kernel already owns the resolver, the scope chain, ADR-0012
inheritance, change history and the admin surface; what was missing was a typed
reader. This owner is therefore **folded into settings** rather than standing
alone — the reason it read as "the weakest of the three" in 5c was that the unit
was drawn one size too large, not that the capability was doubtful.

Sub's legacy per-event shadow setting (`notification_event_<code>_channels`),
which its own docstring calls legacy, is deliberately not ported: a second writer
for one decision on day one is the parallel authority the source-of-truth
standard exists to prevent.

#### 5e. Consent needs a writer, or it answers "yes" forever

Taking the delivery dossier surfaced a defect in the source that changes what
consent is worth in production, and it is recorded here because it is a
FLEET-WIDE lesson rather than a Sub bug.

Verified in `dotmac_sub` at `5d6f115b7`: `DeliveryStatus.bounced` is declared and
never assigned; `SuppressionReason.bounce` and `.complaint` have zero call sites;
exactly one site in the product writes a suppression at all — the campaign
unsubscribe link. Sub's consent ledger is therefore **unsubscribe-only in
practice**, and the `all` scope that protects transactional delivery is designed,
documented and never populated by anything automated.

**The ruling: a consent ledger with no automated writer is not a consent
mechanism.** Any product adopting the consent facility must also wire the
provider feedback loop — a hard bounce or spam complaint suppresses the address
with scope `all` — or it has a table that answers "yes, send" forever. The kernel
now ships that loop (`dotmac_kernel.delivery.record_receipt`), so the obligation
is to route sends through it rather than to reimplement it.

The corollary for adapter authors is stated where it can do damage: only a
PERMANENT failure is `bounced`. A soft bounce recorded as `bounced` permanently
stops that customer's invoices, and the kernel cannot classify the difference
because every provider spells it differently.

### Decision amendment — 2026-08-12 (a second consumer is evidence, not permission)

Section 5 point 1 requires "two independent consumers of the same CONTRACT" as a
condition of extraction, and the 2026-08-08 amendment's point 4 requires a
dossier naming "two contract consumers". Read as written, both make two
consumers a **prerequisite for sharing at all**.

That is now amended, following an owner ruling on 2026-08-12:

> A second consumer proves reuse and constrains generalisation; it does **not**
> determine whether a coherent capability belongs in a module.

The contradiction was found by a build rather than a reading. The release
catalogue is a vendor-side capability whose tables REVOKE `app_user` — a product
data plane is disqualified as a consumer **on purpose**, because it must learn
which artifact to run from a signed licence or a deployment plan rather than by
reading the vendor's catalogue. Its second consumer cannot exist until a second
vendor or OEM control plane does. The same holds for the fleet, fleet-health,
support-access and licence-issuance units. A rule requiring two consumers before
sharing does not delay those modules; it forbids them, and pushes the capability
back into the single assembly this programme exists to thin.

**Three dossier states replace the two-state model. All three permit a shared
module.** The state records the evidence level, never the placement permission:

| State | Means | Requires |
|---|---|---|
| `audit-complete` | The inventory ran and the unit was drawn deliberately. Nothing has adopted it. | An audited `source_mode`, **at least one concrete** candidate consumer, and **zero** contract consumers. |
| `adopted` | One real consumer is on the contract and its first cutover is complete. | An audited `source_mode` and **exactly one** contract consumer. |
| `reuse-proven` | Two or more independent consumers exercise the same contract. | An audited `source_mode` and **two or more** contract consumers. |

`approved` becomes `reuse-proven`. The old name described a permission, which is
precisely what the state no longer grants; keeping it would leave the amended
rule readable as the rule it replaces. Grandfathered pre-rule packages keep
their separate, exact debt map — ADR-0018 requires "grandfathered" to stay
distinguishable from "reviewed and correct", and adding a third correct state
does not change that.

**Why the candidate count is lowered to one rather than dropped.** A dossier with
no named candidate is a package built for nobody, which is the speculative
extraction section 5 exists to stop. One *concrete* candidate — an assembly that
exists and will consume it — is the smallest claim that still carries evidence.
Two remain required to reach `reuse-proven`.

**Why `adopted` is a distinct state, not a loosened `audit-complete`.** The
two-state model let a package with one live consumer keep describing itself as
"nothing has adopted it yet". That is a false statement about the fleet, and it
hides the transition ADR-0017 calls the scarce resource — the first cutover.
Splitting the state surfaces the first adoption in the dossier the moment it
happens, and makes a package that has a consumer while claiming none a build
failure rather than a stale comment.

The ratchet holds in both directions: a package may not sit in a state weaker
than its evidence supports (one consumer forces `adopted`, two force
`reuse-proven`), and may not claim a state stronger than its consumers prove.

### Decision amendment — 2026-08-29 (a pin is installation, not adoption)

The 2026-08-12 amendment above made the three states depend on the CONSUMER
COUNT, and AdoptionEvidenceV1 (#496) made each evidence row a re-checkable fact
at an immutable commit. Neither made the state depend on what the rows SAY. So
a dossier could hold `status = "adopted"` while every row beneath it recorded
only that some consumer's dependency file names the distribution, and nine of
the ten dossiers #496 migrated came out in exactly that shape. Nothing was red,
because the two halves were checked by functions that never compared notes.

Owner ruling, 2026-08-29:

> A pin is installation, not adoption. An exact pin means installed. Lineage
> absent + storage absent + writer unchanged means not composed, and therefore
> not adopted.

**`dotmac-tax` is the case it was ruled on, and all of its facts are true at
once.** ERP pins `dotmac-tax 0.1.0a3` at commit `7643d5a2` — the row is correct
and it stays. ERP also declares the module NOT COMPOSED in its own
`app/services/finance/tax/adoption/composition.py`: the `tx` lineage is absent
from ERP's `alembic.ini`, `mod_tax` exists in no ERP database, and no writer is
repointed — this dossier itself types ERP as a `qualifying_source` whose
retirement is still required. The pin was simply never the fact being claimed.
The dossier is corrected to `audit-complete` with zero contract consumers and
ERP moved back to a candidate, which is what the consumer ratchet requires and
what the evidence supports. **The pin history is retained**: it was true when
written and remains true; it was never the thing that was wrong.

**Each evidence kind is classified by what it can prove ON ITS OWN**, and the
classification is total, so a kind added later must be placed on one side
rather than counting as neither:

| Class | Kinds | Proves |
|---|---|---|
| Installation | `pinned_at`, `contract_binding`, `workflow_run`, `deploy_run`, `image_digest` | a consumer installed, shipped or bound the distribution |
| Adoption-proving | `adopted`, `live_observation` | the capability is composed, or a writer moved |

`deploy_run` and `image_digest` sit on the installation side for a reason
visible in this repository's own data rather than by argument: run
`32022599873` and digest `sha256:56ec5531…` are each cited by three dossiers,
and run `32485479666` with digest `sha256:45715e42…` by two more. An
observation equally true of several distributions cannot say which capability
was composed. `live_observation` is the weaker family but carries a
per-capability `subject` — `mod_approvals`, `mod_ealloc`, `mod_relcat` — which
is a statement about composition a shared image digest cannot make.

**The coupling runs both ways.** An adoption state with only installation rows
fails; an `adopted` ROW under a status that does not claim adoption fails too,
because the row is the stronger statement and a dossier that under-reports
makes a false statement about the fleet rather than a missing one. There is no
historical/superseded state that admits both — `historical-pre-rule` is a
grandfathering marker and reusing it as one would collapse the distinction
ADR-0018 requires. The escape hatch is a parameter with an empty set behind it,
exercised by a test so the branch is live code rather than a comment.

**A branch name is refused in every role, `locator` included.** The canonical
coordinate is repository + structured path + 40-character commit; a pull-request
number may be supporting context and never the coordinate. `main@<sha>` remains
forbidden as a locator, because demoting a bad coordinate to a human handle does
not make it point at the same tree tomorrow.

**What is NOT corrected here, and why it is debt rather than an exemption.**
Three scopes still rest on installation alone: `dotmac-auth-oidc`, and
`dotmac-ui`'s `tokens` and `components` slices. Their cutovers are real and are
described in their dossiers — the Workspace deleted its own `identity/oidc.py`
in the pinning commit; Sub, Academy and ERP each serve the packaged assets. What
is missing is a row a checker can re-derive, because every one of those
consumers expresses composition in Python (`app/assembly.py`, a stylesheet
mount) and an AdoptionEvidenceV1 assertion may only address a field in a
structured file. Writing an `adopted` row for any of them today would mean
minting a claim about a tree nobody in the change had read, which is the defect
this train exists to stop. They are recorded in an exact, two-directional
backlog (`PIN_ONLY_ADOPTION_DEBT`) that fails when a scope enters the shape AND
when one leaves it without the row being deleted (ADR-0018 / rule 25). Two
dangling prose references were repaired in the same change: an auth-oidc note
cited a `[[product_writers]]` row for `dotmac_workspace` that was never written,
and a `dotmac-ui` slice note referred to a package-level note that did not
exist.

No field of AdoptionEvidenceV1 becomes an input to a permission. This refuses a
self-contradictory file; it authorises nothing.

### Decision amendment — 2026-08-13 (the presentation system is adoption-led, and may need no theme package)

**The presentation system is completed by a sequence of adoption-led releases,
not by a "design-system completion" project.** Each release earns its place by
being consumed. This amendment states the authorities and the standing rules;
the delivery sequence is an implementation plan, not an architecture decision,
and lives in `docs/superpowers/plans/2026-08-13-presentation-system-programme.md`.

This amends § 1. Naming four concepts was correct; it is NOT a commitment to
build a package per concept. **A complete presentation system may legitimately
ship no structural theme package at all**, if tokens and brand data cover every
real deployment. `ThemeManifest` is therefore not a deliverable. Its trigger is
two deployments needing the same structural presentation difference that tokens
cannot express; until that exists, building it manufactures an authority nobody
asked for — the same failure ADR-0017 names on the kernel side.

#### Composition, and where each authority sits

```text
product / kernel resolver
        │ resolved brand data
        ▼
assembly adapter → dotmac_ui.BrandOverride → same-origin brand CSS
                                             │
dotmac-ui defaults → trusted theme defaults → brand overrides

product templates → published dotmac-ui component contracts
```

- **`dotmac-ui`** owns presentation behaviour: tokens, component markup and CSS,
  and the accessibility contract.
- **Product or kernel services** own brand RESOLUTION. `dotmac-ui` generates CSS
  from resolved data; it never reads a database and never decides precedence.
- **Themes** supply trusted, deployment-static presentation.
- **Brands** supply runtime data.
- **Assemblies** compose all four, and are the only layer permitted to know
  about more than one of them — which is what keeps the dependency direction of
  § 2 acyclic while brand data flows the other way.

The cascade order is fixed: `dotmac-ui` defaults, then trusted theme defaults,
then resolved brand overrides. A product compatibility mapping may occupy the
theme layer temporarily; it may not become a permanent fourth authority.

#### Tenant-supplied CSS is retired, and its removal is not gated

**No tenant may supply CSS, Jinja or JavaScript.** Brand customisation is an
allowlisted token set (D8). A regex denylist is the wrong shape for the problem:
it must enumerate every dangerous construct, while an attacker needs one it
missed.

Retiring such a surface is a **security correction to an existing surface, not a
new facility**, so ADR-0017 does not gate it, and it does not wait for the
feature that replaces it. Retirement is a WRITE-time rule: a value already
stored is data a newer reader ignores, not an invalid setting, and treating it
as invalid would silently degrade the whole record it sits in.

#### Evidence, not permission

Component reuse is evidenced on the ladder this ADR's 2026-08-12 amendment
already defines (`audit-complete` → `adopted` → `reuse-proven`), and evidence is
tracked **per contract slice**. A package may be `reuse-proven` for one contract
— its tokens and compiled assets — while a second contract it also publishes,
such as the component library, has no consumer at all. A dossier that reports
one state for a package publishing two contracts overstates the weaker one.

Consumption by the assembly that OWNS a package is reference proof and never
closes § 5's gate for it. The independent consumers are products, and which
products they are is a sequencing question for the implementation plan, not a
decision this ADR should pin.

#### Completion criteria

The presentation system is complete when: no tenant can supply executable CSS,
Jinja or JavaScript; DotMac and neutral brands run from identical source;
light/dark and the critical facets pass WCAG 2.2 AA; no brand stylesheet or
asset can leak across tenants; every shared component has two RELEASED product
consumers and its superseded local owners deleted; every theme that exists is
installed, exact-pinned, digest-addressed and compatibility-checked; wheels
prove their assets and templates and render on a clean host; and the control
plane manages desired brand and theme state through product APIs, never by
writing to a product database.

Note what is absent: "the component library is finished" and "a theme package
exists" are not criteria. Neither is a measure of the system working.

### Decision amendment — 2026-08-14 (a fourth classification: the stateless protocol adapter)

`EXTRACTION.toml`'s `classification` had three values — `universal-facility`,
`presentation-foundation`, `optional-module` — and all three describe something
a product **installs**. A distribution that speaks an external protocol and
holds nothing fits none of them, and calling it an `optional-module` is not a
harmless approximation: it tells a reader to look for a `ModuleManifest`, a
`mod_*` namespace, a migration lineage and a release-allowlist entry that do not
exist, and it invites the dual-plane and namespace gates to ask questions the
package cannot answer.

`stateless-protocol-adapter` is added for a distribution that a product
**calls** rather than installs. `dotmac-auth-oidc` is the first.

**The classification is GOVERNED, not merely accepted.** A string in a valid-set
is a label; the four properties below are what the word has to mean, and each is
checked generically against any package that claims it — not against a named
package:

1. **No `ModuleManifest`.** Nothing to install, so nothing declares itself
   installable.
2. **No migration lineage.** No `migrations/` tree, and no `short_code` or
   `migration_prefix` (hard rule 14 — stateful and stateless are the only two
   coherent shapes, and this is the stateless one).
3. **No namespace allocation.** No row in `MIGRATION_OWNER_LEDGER`. An
   allocation is permanent once added, and one made for a package that will
   never own a schema is a lie the ledger cannot later retract.
4. **No persistence import.** No ORM, no database driver. A package that grew
   one would have become a module without changing its dossier.

The counterpart matters as much: a package classified any OTHER way must not be
mistaken for this one. The check is keyed on the DECLARED classification, so a
stateful module is simply out of scope rather than accidentally held to a rule
it should fail.

Enforced by `tests/architecture/test_product_first_extraction.py`
(`test_a_stateless_protocol_adapter_holds_no_persistence`), with the sensitivity
proof ADR-0018 requires: the checker is a pure function over a synthetic package
tree, shown to fire on a planted manifest, a planted migrations directory and a
planted ORM import, and shown NOT to fire on a conforming one.

### Decision amendment — 2026-08-26 (a fifth classification: the stateless contract catalogue)

This amendment adds `stateless-contract-catalogue` and, in doing so, departs
from a ruling recorded when the connector lane was built. The departure is the
substance of the amendment, so it is stated first.

**What was ruled, and why it stands.** The connector lane's first cut demanded
`classification = "connector-plugin"` in `EXTRACTION.toml`. That was rejected: a
connector needs a distinct release *profile*, not a new extraction
classification, because the four properties `stateless-protocol-adapter`
governs — no `ModuleManifest`, no lineage, no ledger allocation, no persistence
import — are **exactly** a connector's four. A second word for one set of
properties would mean amending this ADR and the global validator to describe the
same thing twice, and the ruling closed with an explicit instruction: never
promote `connector-plugin` to a classification without amending both first.

That reasoning is correct and is not disturbed here. A connector remains a
release profile over `stateless-protocol-adapter`, and what separates its lane
from the adapter lane remains strictness the adapter lane does not ask for.

**Why a contract catalogue is not the same case.** A catalogue is one product
owner's capability contracts: canonical schema bytes, the digests that attest
them, and a typed public surface. It shares the adapter's four properties, and
if that were the whole story the connector ruling would apply unchanged and this
amendment would be wrong.

It is not the whole story, because the four properties are silent on the one
thing that most distinguishes these packages: **network reach**. An adapter
EXISTS to reach a provider. That is what the word adapter means here, and it is
not incidental — `dotmac-auth-oidc` ships `transport.py`, declares `httpx` in
its own reviewed `allowed_requires`, and this ADR names network I/O as one of
the two concerns that cannot be faked. A contract catalogue reaches nothing at
all. It is held data. Its release lane refuses `httpx`, `requests`, `socket`,
`urllib` and `subprocess` outright.

So the two classifications differ on an enforceable property, not on emphasis.
A single word covering both would have to permit the network import, because
the adapter genuinely needs it — and a catalogue that acquired a provider client
would then be caught by nothing but whether someone remembered to route it
through the stricter lane. That is precisely the failure the connector ruling
was protecting against, arriving from the other direction: there, a second word
would have weakened nothing and duplicated a definition; here, a single word
weakens the check for one of the two shapes it covers.

**The properties the word has to mean.** The shared four are checked identically
to the adapter's, through the same pure function, so the two cannot drift apart
on what they agree about:

1. **No `ModuleManifest`.** Nothing to install.
2. **No migration lineage.** No `migrations/` tree, no `short_code`, no
   `migration_prefix`.
3. **No namespace allocation.** No row in `MIGRATION_OWNER_LEDGER`.
4. **No persistence import.** No ORM, no database driver.

And the fifth, which is the one this classification exists to carry:

5. **No network reach.** No `httpx`, `requests`, `aiohttp`, `urllib`,
   `urllib3`, `socket` or `subprocess` import. A catalogue describes semantics;
   an independently released connector implements them against a provider.

**Where it is checked.** On the DECLARED classification, in
`tests/architecture/test_product_first_extraction.py`
(`contract_catalogue_violations`), so an unlisted catalogue is governed exactly
as much as an allowlisted one — the classification is the gate, not lane
membership. The shared four come from `stateless_package_violations`, renamed
from `stateless_adapter_violations` because it now governs two classifications
and a name that says "adapter" would misdescribe half its callers.

The ADR-0018 sensitivity proof is the discriminator itself, stated as tests: the
same planted network import must be REFUSED for a catalogue and ACCEPTED for an
adapter, and the real `dotmac-auth-oidc` — which passes the adapter checker
exactly — must still be refused by the catalogue checker, because it ships
`transport.py`. If that pair ever passed together, the fifth property would be
decoration and this amendment should be reverted rather than patched.

**The lane.** `.github/release-contracts.json` is the fourth closed allowlist,
gated, built and verified by `release-contract.yml` through
`scripts/release_contract.py`. It lands CLOSED and EMPTY. The seven candidate
catalogues exist only on an archive ref and declare a `dotmac-kernel` floor of
`0.1.0a69` — a number that branch minted for itself and that mainline later
spent on unrelated work — while the capability grammar they import
(`CapabilityContractSnapshot`, `CapabilitySchemaDocument`,
`CapabilityCompositionSnapshot`) is on no published kernel. Absence from the
allowlist is the lock; the workflow is not.

**Not a licence to reclassify.** Adding a fifth value does not invite a sixth
whenever a package fits awkwardly. The test this amendment sets is the one it
had to pass itself: name the property the existing classification cannot
express, show it is enforceable, and show the guard distinguishing the two.
A classification that cannot answer all three is a release profile — which is
what the connector lane correctly remained.

### Decision amendment — 2026-08-15 (a legacy source and its module shadow, disambiguated)

D1 says that until an extraction's cutover is proven, "the source product and
the candidate module are simply not composable in one database." That sentence
is right about the danger and too blunt about the remedy, and a real adoption
found the gap.

The vendor control plane installs `dotmac-entitlement-allocation` in **shadow
mode**: the module's lineage is composed so its schema and migration path are
exercised, while the vendor-local writer stays authoritative until a data
preflight proves every historical row maps to a product. Both sets of tables
therefore exist at once — and because the legacy tables were named `allocations`
and `allocation_entries`, exactly what the module owns in `mod_ealloc`, the
composed live-catalog audit correctly refused the database.

Refusing was right. The two decisions collided because **the names were
ambiguous**, not because shadowing is wrong.

#### What stays forbidden

**Same-named legacy and module tables must not coexist.** `public.allocations`
beside `mod_ealloc.allocations` is refused, and no exemption list may permit it.
This is the original collision class D1 exists to prevent: two tables with one
name, where a mis-set `search_path`, a hand-written query or an ORM mapping
reads the wrong rows. A composition that requires a reader to know which
`allocations` was meant is already broken, whatever the migration state.

#### What is now permitted, narrowly

A **disambiguated** legacy table may coexist temporarily with an **empty,
non-authoritative** module shadow, provided every one of these holds:

1. **The legacy table is renamed, not the module's.** `public.allocations`
   becomes `public.legacy_entitlement_allocations`. The module keeps the clean
   name it will own after cutover, so the end state needs no second rename and
   no reader learns a name that is about to change again.
2. **The rename is a new migration.** The original revision is never edited: it
   already ran in production, and a lineage that rewrites its own history cannot
   be replayed or audited.
3. **Exactly one authoritative writer**, and it is the legacy one. The module
   shadow stays empty and non-authoritative until cutover. Dual-write is not
   shadowing; it is two owners.
4. **No foreign key crosses the planes**, in either direction (ADR-0023 § 4).
   An FK is the one crossing the database itself would enforce, and therefore
   permit.
5. **Every row is preserved.** A rename moves rows; it does not drop and
   recreate.
6. **A named cutover gate and a retirement gate.** The shadow is temporary by
   construction: the dossier records what must be true to cut over, and what
   retires the renamed legacy table afterwards. A shadow with no retirement
   condition is a permanent second copy wearing a temporary label.

#### Why the rename is not a naming trick

Renaming to make a gate pass would be exactly the sort of evasion ADR-0018
forbids. This is the opposite: the ambiguity was itself the defect. Before the
rename a reader cannot tell which `allocations` a query means; after it, the
legacy table says in its own name that it is legacy and scheduled to go. The
gate goes green because the database became honest, not because the check was
weakened.

#### Enforcement, and what enforcement does not reach

**Condition 1 is machine-checked, by the audit that already exists.**
`dotmac_kernel.migrations.catalog.audit_snapshot` reports
`host_schema_squatters` — a module's declared tables found in `public` — and
that is precisely the ambiguity this clarification forbids. It is the check that
refused the vendor database, so it is the one the tests exercise. A second,
parallel predicate was written first and deliberately removed: test-only code
that duplicates a production rule proves nothing about production, and leaves
two definitions to drift apart.

Its sensitivity proof is the pair, not the pass. The audit is shown to refuse
the exact composition that failed in the vendor control plane, and to accept the
same declared tables once the legacy side is renamed — so a squatter check that
degraded to silence fails the suite rather than passing it quietly.

**The other five conditions are NOT machine-checked here, and pretending
otherwise would be worse than saying so.** They are properties of one adopter's
database and cutover, not of a composed manifest, so each names the gate that
owns it:

| Condition | Owning gate |
|---|---|
| One authoritative writer; the shadow takes no writes | the adopter's writer-retirement ratchet (ADR-0018, two-directional), which counts writers and fails when the count rises |
| The module shadow stays empty | the adopter's cutover preflight, which asserts a zero row count before authority moves |
| The rename is a new migration, never an edit | the composed migration gate — an edited revision changes a hash that already ran |
| Every row preserved | the adopter's data preflight, which reconciles counts across the rename |
| No cross-plane foreign key | ADR-0023 § 4, enforced by the kernel gate for FKs whose SOURCE is inside the module schema — a product-owned link table in `public` remains *unmonitored rather than exempt*, and that gap is ADR-0023's own recorded follow-up |
| A named cutover and retirement gate | the module's `EXTRACTION.toml` — `first_cutover`, `shadow_and_drift`, `local_copy_retirement` — which is reviewed, not executed |

Recording the split matters more than closing it. A reader who believes all six
are enforced will skip the five that are not, which is exactly how a shadow
becomes permanent while every check stays green.

### Decision amendment — 2026-08-30 (a credential lifecycle has one owner, and provisioning cannot be handed material)

Extraction of the human credential lifecycle surfaced a rule the earlier
amendments imply but never state: **when the capability being extracted is a
security decision, the extraction must make the dangerous shape
unrepresentable, not merely absent.**

The measurement that forced it (`docs/inventories/credential-lifecycle-sources.md`,
exact commits recorded there):

- `dotmac_sub` has **four** `verify_password` owners in four files. Each one
  re-derives active, locked and reset-required for itself, because the
  primitive returns a boolean and a boolean cannot carry the answer. Four
  owners disagreeing is the predictable result of that return type, not
  carelessness.
- **Eleven** files call `hash_password`, two of them seed scripts under
  `scripts/seed/`. A guard scoped to `app/` sees nine and reports the other two
  as absent — the exact defect hard rule 25 names.
- `reseller_onboarding._create_credential` accepted a caller-supplied
  `password` parameter that **no supported caller ever passed**, and that unused
  parameter is how one value reached 24 external organisations. Sub removed it.

Four rulings follow, and they generalise beyond credentials to any extracted
security decision.

1. **A security decision returns a typed verdict, never a boolean.** A boolean
   forces every caller to re-derive the states it cannot carry, which is how one
   decision becomes four. `CredentialVerificationVerdict` is `accepted`,
   `reset_required`, `invalid`, `locked`, `disabled`; the owner returns it and
   issues nothing. Mapping a verdict to an HTTP status or a session stays with
   the product adapter, where it is one decision in one place.

2. **A parameter that must never be used is deleted, not documented.** An
   unused, undocumented, caller-supplied secret parameter is not latent risk —
   it is the incident, waiting for one caller. Removing it from the product
   (Sub PR #2826) fixes the instance. The extraction must fix the SHAPE: the
   shared owner's provisioning signature has nowhere to put material and its
   receipt has nowhere to return it, so a future caller who thinks they are
   being helpful has no way to be.

3. **Generated credential material leaves through nothing.** Not a return type,
   log line, exception message, `repr`, receipt field or audit row. The subject
   reaches a usable credential through a durable recovery intent and the
   product's own proven channel. A facility that cannot hand you the secret
   cannot leak it, and that is a stronger property than any handling discipline.

4. **Product security authority is not deployment authority.**
   `dotmac-deployment-control` owns fleet deployment intent (ADR-0070) and must
   not authorize an account mutation. A cohort force reset is approved by a
   PRODUCT approval policy, named on the plan and re-checked against a separate
   authorization record. That record carries `approval_decision_ref` and
   deliberately **no** `approved_by`: the approval decision is a product record
   with its own actor, quorum and audit trail, and a copied actor name would be
   a second, weaker claim about who approved — the weaker one being the one an
   automated reader believes.

Two honesty constraints go with it, and both are conditions on the dossier
rather than on the code.

- **New behaviour is labelled new.** `password_needs_rehash` has zero call sites
  across `dotmac_sub`, `dotmac_erp` and `dotmac_vendor_control_plane`. The
  legacy-hash upgrade in the extracted facility is therefore built and tested as
  NEW behaviour; calling it ported would be a false product-first claim, and the
  2026-08-08 amendment's whole value is that its claims can be checked.
- **A measurement that supersedes a census says so.** The AST call-graph sweep
  and the earlier hand census agree exactly on which FILES are callers and
  differ on site counts (grep lines include imports). Both numbers are recorded
  with their definitions, so a later reader does not read a redefinition as
  progress.

Scope note, because a sweep is how this goes wrong: `AccessCredential` and
`SnmpCredential` in `dotmac_sub` are DEVICE and SERVICE credentials.
`UserCredential` alone is the human model. An extraction keyed on the name
`*Credential` would have given the facility responsibilities it must not have.

This amends nothing above. The two-consumer, named-owner and product-first rules
still decide whether and how a unit is shared; this says what an extracted
SECURITY decision additionally owes. Enforcement:
`tests/unit/test_credential_lifecycle.py`,
`tests/architecture/test_credential_lifecycle_ratchet.py`,
`scripts/credential_lifecycle_sweep.py`,
`docs/inventories/credential-lifecycle-baseline.json`. No kernel version is
allocated by the change that added the facility, and no product composes it.

### Decision amendment — 2026-08-25 (the web facet runtime contract)

§ 1 named **product facet** as the concept the codebase was missing, and then
nothing implemented it. That was correct at F0 — the ADR states plainly that it
changes no runtime behaviour — but the deferral has now outlived its usefulness:
installable modules are beginning to grow screens, and every additional
`web_routers`/`nav` declaration made under the implicit "admin" assumption is one
more thing a later audience dimension has to break. This amendment settles the
runtime contract so the kernel API can be committed once.

It decides authority and shape only. It does not implement, and it does not
schedule. The measured characterization behind it is
`docs/inventories/facet-composition-blast-radius-2026-08-25.md`.

#### What was measured first

A facility is not introduced here on reasoning alone. The findings that changed
this amendment's shape:

- **The audience split already exists in production, authored per product.**
  `dotmac_sub` serves five audience template trees (`admin`, `customer`,
  `reseller`, `vendor`, `public`) behind three guards — `require_web_auth`,
  `require_admin_web_auth`, `require_vendor_web_auth`. `dotmac_erp` has its own
  `require_web_auth` and a parallel tree set. This is the duplication § 1
  predicted, now measurable.
- **The pure authentication seam already exists, hand-rolled.**
  `dotmac_workspace.web_auth.require_workspace_auth` reads a cookie name and
  login path from its own `session_contract`, delegates to the shared
  `authenticate_request`, returns a `Party`, and decides no authorization at all.
  That is the authentication profile § 5 names, already running.
- **Sub's admission check is default-deny on principal TYPE, not on a role**
  (`STAFF_PRINCIPAL_TYPES = {"system_user"}`), with per-route
  `require_permission` explicitly retained on top. § 5's three-layer split is
  therefore extracted from a running implementation, not invented here.
- **The CSRF trigger is wrong in a way a prefix rule would not have found.**
  `CSRFMiddleware` is application-wide and prefix-independent — correct — but
  enforces only when `request.cookies` is non-empty, so a cross-site pre-auth
  `POST` arriving without cookies is not checked at all. See § 6.
- **Mutation transport is already divergent across the fleet.** The starter bans
  native `method="post"` forms and bridges htmx/`fetch` to a header; Sub's
  templates carry 488 native `method="post"` occurrences across 228 files with
  hidden-input CSRF. A reusable module screen cannot silently assume one
  product's bridge.

Per the product-first rule (§ "Decision amendment — 2026-08-08") this satisfies
the inventory obligation before a kernel facility is added. Per the
single-consumer correction it does **not** require a second consumer to justify
the module-owned surface itself: a second consumer proves reuse and constrains
generalisation; it does not decide whether a coherent capability belongs to its
module.

#### 0. Scope: this is an interactive-browser contract, and it says so in its name

The runtime this amendment defines is **`WebFacetMount`** — an interactive,
same-origin, server-rendered browser surface. The name carries the scope so a
later reader cannot mistake breadth for generality.

§ 1's facet vocabulary is wider than that: it also names email, document,
public/signup and API-only surfaces, and native mobile sits alongside them.
**Those are not this runtime, and must not be forced into it.** Route prefixes,
shells, navigation regions and cookie authentication profiles are meaningless for
a rendered invoice PDF, a transactional email, or a Flutter client. A single
abstraction spanning them would be a false one — it would have to grow a mode
flag per channel, which is the `if deployment_mode == ...` shape ADR-0003 already
forbids.

Each non-web channel gets its own contract **when a real implementation justifies
one**, and shares what is genuinely shared: domain and API contracts, policy
decisions, semantic design tokens, brand data and localization. Not a rendering
runtime.

Facet codes stay an open manifest-declared vocabulary (ADR-0008), never a closed
kernel enum. A product names `field_tech` or `wholesale` without a kernel change.

#### 1. Four owners, and none may hold another's declaration

| Layer | Owns |
|---|---|
| `dotmac-ui` | semantic design tokens, visual primitives, layout/navigation primitives, accessibility behaviour, published component contracts |
| Domain module | its domain screens and fragments beside its capability: typed render models, commands, permissions, domain language, action availability |
| Web facet | audience shell, authentication context, admission policy, navigation regions, URL namespace |
| Assembly / profile | selects modules and facets; supplies prefixes, brand, theme, deployment policy |

The assembly selects and positions; the module supplies. **An assembly that
reproduces a module's navigation, screens or domain policy is a defect** under
§ 5's extraction rule, not a variation.

Cross-module UI interaction uses typed links, htmx-fetched fragments or declared
ports — never a module-to-module Python import. That rule is unchanged; this
amendment only extends it across facets.

**Template shadowing is replaced by declared slots.** Today an assembly's template
directory shadows any packaged template by name and layer order. That is an
invisible fork: a module ships a screen, an assembly silently replaces it, and no
gate observes the divergence. An override must instead name a **declared,
versioned extension slot** — slot name, owning module, compatibility range, and a
migration test. Anything else is unmonitored rather than permitted.

#### 2. The two runtime records

**`WebFacetMount` is assembly/profile-owned** and declares exactly: `code`,
`url_prefix`, `shell`, `authentication_profile`, optional
`admission_permission`, `navigation_regions`, and assembly-approved
`entry_routes`, plus optional named `login_route`, `landing_route` and
`logout_route`. Login must name an entry; login/landing are parameterless GETs
and logout is a parameterless POST. The collision-free route namespace is
derived from facet, module, surface and local route names; it is not another
authorable string. Shell chrome and redirects resolve these references at
request time; neither the module nor the kernel authors the facet prefix.

**`WebSurfaceContribution` is module-owned** and declares exactly: `code`, the
target `facet`, relative `routers`, stable named-route `navigation` with region,
group and order, optional namespaced `templates` and `static_assets`, the set of
`supported_ui_contract_versions`, and required `browser_capabilities`.
Permissions and entitlements are derived from the target route's stamped
dependencies, so navigation and route enforcement cannot declare two answers.
The assembly selects one exact `ui_contract_version` for the process.

A module never names a prefix, a host, a brand, or another module's facet.

**Startup fails** — a boot-time refusal in the shape `create_app` already uses for
undeclared permission and capability codes, never a runtime 500 — on: an unknown
facet code; an incompatible UI contract range; a route-name collision; a
navigation-ID collision; a template or static namespace collision; an unresolved
browser capability; a navigation entry naming a route that is not mounted; a
surface declaring routers or templates that are absent; or an invalid
authorization binding.

#### 3. Surface state is request-scoped, never a process-global

`dotmac_kernel.templating` holds one module-scope `Jinja2Templates`, and
`install_surface_globals`/`install_stylesheets` write `nav_items`,
`enabled_features`, `extra_stylesheets` and `brand` into `templates.env.globals`.
Two facets in one process cannot have different navigation, stylesheet cascade or
brand under that mechanism.

Per-request state is carried by an **immutable `SurfaceContext`**. There is no
process-global "current portal", and no mutable environment state standing in for
one. The existing `request.state.branding` / `request.state.display` memoization
is the precedent to follow rather than a thing to work around.

**Any cache key touching UI state includes** the facet, the tenant/platform
scope, the identity, the locale, the brand and the UI-contract version. A cache
shared across two facets is a cross-audience leak with a performance
justification.

This is the load-bearing engineering change, and it is larger than the contract
types themselves. Route-name navigation is its visible half, not its whole.

#### 4. Navigation references named routes, not paths

`NavItem` carries a path string today, and
`test_nav_items_paths_exist_in_web_routers` proves the path resolves. Once an
assembly owns the mount prefix, a module-authored absolute path is wrong by
construction: the module cannot know where its own surface was mounted.
Navigation, breadcrumbs and redirects therefore reference **named routes**,
resolved per facet at render time.

Navigation filtering and route authorization consume the **same declared
permissions**, and remain **independently enforced**. Hiding a navigation item or
a button is never authorization — it is a courtesy on top of a guard that must
refuse the request on its own.

#### 5. Authentication, admission, and authorization are three decisions

The load-bearing ruling. **A raw role such as `"admin"` must not live on
`WebFacetMount`.** Roles are configurable bindings; permissions express decisions.
Putting a role on the facet would relocate the hardcoding in
`packages/dotmac-kernel/src/dotmac_kernel/web_deps.py:151` (inside
`require_web_auth`, declared `:93`) rather than remove it, and would hand a
presentation-layer object an authorization decision § 1 forbids it to hold. A
guard callable on a manifest is the same mistake wearing a different type.

| Layer | Question | Owner | Refusal |
|---|---|---|---|
| **Authentication** | who are you? | the facet's named **authentication profile** — staff session, tenant session, customer session, public | redirect |
| **Facet admission** | may you reach this audience surface at all? | a **declared permission**, evaluated through the existing seam | 403, never a redirect |
| **Route and action authorization** | may you do this specific thing? | the **module** — every route keeps its granular guard; row visibility and permitted actions stay module service decisions | 403 |

`docs/ARCHITECTURE.md` § "The permission seam is authentication-neutral" already
supplies layer 2's mechanism: `authorize_party` takes an already-established
party and reads no header, no cookie and no session, and `permission_guard` is
the route-level factory both the bearer and cookie flows go through. **Separate
portal-role work is therefore not a prerequisite.** Designing a role taxonomy
before real facets have established which permissions they need inverts the
order.

`require_web_party` is the pure authenticated-party seam. `require_web_auth`
remains the contract-v1 party/roles mapping adapter, while current admin entry is
preserved by `web.portal.staff.access` on the `staff_admin` facet.

Facets supply **context** — resolved principal, audience, brand, display settings
— and never decide domain authorization.

The authentication profile also owns **session mechanics**: cookie name, scope,
`Secure`, `HttpOnly`, `SameSite`, path/host, rotation on login and logout,
session-fixation protection, idle and absolute expiry, revocation, tenant-switch
behaviour, and whether any session is shared across facets.

##### § 5 amendment — 2026-08-26: facet admission is a TENANT-plane decision

§ 5 named a mechanism for layer 2 without saying which authentication profiles
can supply its arguments. `authorize_party(db, tenant, party, code)` takes an
already-established, tenant-scoped `Party` — that is exactly what makes it
authentication-neutral, and it is also what makes it unanswerable on the other
two planes. A `BrowserSecurityPlane.PLATFORM` profile resolves a
`PlatformAdmin`, a control-plane catalogue row with no tenant and no role
grants; a public profile (`provider=None`, whose plane is forced to `NONE`)
resolves no principal at all. The runtime routes both through its non-tenant
context dependency, which never reads `WebFacetMount.admission_permission`.

A facet naming a platform or public profile alongside an admission permission
was therefore a binding that could not be enforced, and its failure mode was
**silent admission** rather than a crash. The permission was visible on the
facet, `create_app`'s declaration check confirmed it was in the permission
catalogue, the surface read as guarded in review — and every request reached
the routes behind it. A control that is legible and inert is worse than an
absent one, because it retires the question a reviewer would otherwise ask.

**Amended rule.** A facet may declare `admission_permission` only when its
named authentication profile declares `BrowserSecurityPlane.TENANT`.
`WebSurfaceRegistry` refuses any other binding at startup, naming the profile
and the plane it enters. § 5's existing requirement that the code be declared
is unchanged and composes with this one: a tenant-plane facet must still
declare the permission it admits on. Canaries in
`tests/unit/test_web_surfaces.py` cover both refusals, the platform facet that
must keep working, and — the half a one-sided check would lose — that the valid
tenant binding is still consulted on a live request.

A platform or public facet WITHOUT admission remains valid, and is not secured
less by this rule. The plane is rejected as an ANSWER to layer 2, not as an
audience: such a facet authorizes at layer 3, inside its own routes against its
own principal, which is where a non-`Party` principal's authorization has
always belonged.

**No `UI_CONTRACT_VERSION` bump accompanies this.** The contract version
describes what a valid composition may rely on, and every composition that was
valid before this amendment is valid after it. The only assemblies that stop
booting are ones whose admission permission was never evaluated, so no enforced
behaviour changes and no consumer's supported-version range narrows. The
reference assembly is already correct — `staff_admin` is tenant-plane with
`web.portal.staff.access`, `platform_admin` is platform-plane with no admission
— so this closes the hole for the next assembly rather than repairing this one.

#### 6. CSRF follows the declared transport, not a path prefix

**Ruling: CSRF applicability is derived from the declared authentication
transport, never from a route prefix and never from the incidental presence of
cookies on a request.**

The as-built middleware is application-wide and does not inspect `/admin`, so a
new facet prefix does not silently escape it — that part is already right. What is
wrong is the trigger. `CSRFMiddleware` enforces only when `request.cookies` is
non-empty, so that bearer APIs pass. "This request carried some cookie" is not
the same question as "this endpoint participates in a browser session", and the
gap between them is a pre-auth mutation: a cross-site `POST /admin/login` under
`SameSite=lax` arrives with no cookies at all, so the check does not run. Login
CSRF is a real class, not a hypothetical one, and it is not addressed by
`SameSite` alone.

The contract:

- Every cookie-capable browser facet requires CSRF on **every unsafe operation**,
  including the pre-auth ones — login, registration, recovery completion — and
  logout.
- Bearer-only API routes are excluded by **explicit surface classification**. A
  route that accepts cookies is not bearer-only.
- CSRF is **not a per-facet presentation option**. A facet cannot turn it off as
  branding or configuration, and a module cannot choose its own posture.
- Prefer a **synchronizer token bound to the session** (pre-authenticated or
  authenticated). Where double-submit remains, the token is **signed and
  session-bound** rather than a bare random pair.
- The published transport contract supports **both a request header and a hidden
  form field**, so a native HTML form and an htmx/`fetch` client reach the same
  validator. htmx must not become an accidental invariant of the framework: the
  fleet is already split, and a reusable module screen cannot depend on one
  product's bridge.
- Tokens are compared in constant time and never logged.
- Cookie `Secure`, `SameSite`, host/path scope, rotation and expiry are declared,
  and a production configuration that weakens them **fails closed**.
- `Origin`, `Referer` and Fetch Metadata checks are defence in depth, layered on
  top rather than substituted for a token.
- OIDC `state`/`nonce`/PKCE, webhook signatures and bearer tokens are **separate
  protections**, not CSRF exemptions inferred from a path. An OIDC callback is not
  exempt merely because it is a GET; its state is browser-bound and single-use.
- Every exemption states a machine-checkable premise and carries a sensitivity
  proof (ADR-0018).

This belongs to the kernel and the authentication profile — not to
`SurfaceContribution`.

#### 7. The rest of the browser security contract binds to every facet

A new audience must not escape a control through an unmonitored prefix. Bound to
the facet, not to `/admin`:

- **CSP composed from typed browser capabilities.** A module declares what it
  needs; it never appends a raw policy string. Self-hosted assets and
  nonce/hash-approved scripts; no implicit inline-script expansion.
- Trusted hosts, CORS, clickjacking protection, referrer policy, safe-redirect
  handling (the existing `safe_next_url` shape), and cache-control on
  authenticated pages.
- Output escapes by default. User HTML, SVG, filenames, downloads and uploaded
  content are hostile inputs with explicit sanitization and content-disposition
  rules — the `| safe` discipline generalised.
- No secrets, session credentials, sensitive identifiers or customer data in
  URLs, browser storage, analytics or client logs.
- Tenant-context isolation and rate-limit classification apply per facet.

#### 8. Accessibility is a whole-surface requirement

`dotmac-ui` already publishes `ACCESSIBILITY_TARGET = "WCAG 2.2 Level AA"`; this
amendment binds it to composed surfaces rather than to components alone.

Every critical browser journey targets **WCAG 2.2 AA**, in every responsive
variation. Native HTML semantics come before ARIA. Coverage includes keyboard
operation, focus order and restoration, skip links, landmarks, headings, label
and error association, status announcements, target size, zoom and reflow, high
contrast, reduced motion, and alternatives to drag interactions.

Each published component names the criteria it satisfies and the tests that prove
it. **Component-level checks do not establish page-level conformance** — a facet
is conformant only under browser-level journey tests of the composed page, which
is what `dotmac-ui`'s own compatibility document already concedes.

#### 9. Reusable interaction semantics

Declared surface states: initial, loading, ready, empty, validation error,
forbidden, not found, conflict, rate-limited, stale, partial, retryable failure.
A screen implements the ones that mean something for it; nothing is required to
render a meaningless state.

Consistent handling for 403, 404, 409, 422, 429 and server failures, carrying a
request ID and safe retry guidance. Client-side duplicate-submit prevention is
usability only — **server idempotency remains authoritative** (ADR-0014).
Concurrency-sensitive forms carry a version and show an explicit conflict/reload
workflow. Long-running work uses an explicit job/status contract.

**An htmx or JavaScript failure must never downgrade an unsafe mutation into a
GET.** That is the F7 logout defect generalised into a standing rule.

#### 10. Navigation and data surfaces

Search, filters, sort and pagination live in canonical URL state. Lists have
stable sorting with deterministic tie-breakers, truthful counts, declared
pagination semantics, accessible sort state and result announcements.

Templates consume **typed render models**. They do not traverse lazy ORM
relationships and do not make policy decisions — the thin-adapter rule (ADR-0010)
extended to the template layer.

#### 11. Brand and localization are independent axes

Visual brand, legal entity, support identity, locale, timezone and currency are
separate decisions and are resolved separately.

No reusable component hardcodes a currency, `Africa/Lagos`, an English string, an
address format or a phone-number presentation. `lang`, `dir`, pluralization, RTL,
long-string and text-expansion behaviour are declared.

Branding uses typed semantic values and managed same-origin assets — never
tenant-supplied raw CSS, JavaScript, templates or unsanitized SVG (the
2026-08-13 amendment's D8 ruling, unchanged). Runtime brand contrast is validated,
and brand caches are isolated by tenant **and facet**.

#### 12. Client runtime and assets

Module assets are namespaced and digest-addressed. **A consumer needs no npm, no
Tailwind and no frontend build to use a module surface** (D3, unchanged).

A component must not silently depend on htmx, Alpine or any other runtime. Where
JavaScript is genuinely necessary, the module declares a **versioned browser
capability** and the assembly resolves exactly one compatible implementation. Two
modules shipping conflicting copies of a browser framework is a composition
failure the gate must catch, not a packaging detail.

#### 13. Performance and observability

Per-facet budgets for assets, requests, queries and render time. Low-bandwidth
and small-screen conditions are tested; maps, charts and other heavy surfaces
lazy-load. N+1 detection sits at the service/read-model boundary.

For public and customer journeys the default field target is the Core Web Vitals
"good" threshold at the 75th percentile: LCP ≤ 2.5 s, INP ≤ 200 ms, CLS ≤ 0.1.

Telemetry emits facet, module, route, result class, request ID and UI-contract
version — never form bodies, secrets or customer data. Analytics records
observations only and never becomes an owner of an authorization or business
decision (ADR-0043, ADR-0055).

#### 14. Native mobile is a separate reusable layer, and nothing is extracted yet

A mobile application is an **independent client assembly**, not a
`WebFacetMount`. It owns its navigation, local persistence, platform lifecycle,
device integrations and release packaging. Server modules remain authoritative
for permissions, entitlements, prices, workflow transitions and every other
domain decision — a mobile client is a consumer of decisions, never a second
decider. This is ADR-0024's rule applied to a client rather than a service.

Reuse is adopted in this order, and not out of it:

1. versioned APIs, authentication, and domain command/error contracts;
2. semantic design-token, brand and localization exports;
3. a shared mobile shell and typed device-service ports;
4. adopted widgets and screen patterns.

**No `dotmac-mobile-ui` or shared Flutter framework is authorized by this
amendment.** Sub already runs two Flutter applications — `mobile/`
(`dotmac_portal`, customer self-care) and `field_mobile/` (`dotmac_field`, field
technician / vendor) — and a product-first source-and-test inventory of them, and
of any counterpart in another product, comes before any extraction. Two
applications **inside one product** can establish candidate semantics; under the
2026-08-12 amendment they do not by themselves meet the independent-product bar
for `reuse-proven`.

Where mobile theming does arrive, Flutter theme artifacts are **generated from
the canonical semantic tokens**. There is no second hand-maintained colour system,
and `dotmac-ui` never acquires a Flutter dependency.

Build-time application branding is distinct from runtime tenant branding.
Application IDs, signing identity, deep-link schemes and store identity are not
ordinary theme values and do not travel through `BrandProfile`.

The mobile contract must also state: secure credential storage; logout and wipe;
tenant-partitioned caches; push-token lifecycle; safe deep links; minimal
notification payloads; OIDC Authorization Code with PKCE for native
authentication (a WebView using session cookies falls under § 6's browser
contract instead); offline data as an **encrypted, rebuildable projection** whose
queued mutations carry idempotency keys, ordering, conflict policy, expiry and
reconciliation; and typed ports for camera, location, files, notifications,
biometrics and background execution with denial, revocation and degraded-mode
behaviour. Biometrics unlock locally held credentials and never constitute an
independent domain identity decision.

Required test classes: unit, widget/golden, integration, offline/retry,
deep-link, background/foreground, tenant isolation, brand, locale, accessibility
and low-bandwidth.

PWA and service-worker support is a **separate question** from native mobile. Sub
ships a brand-driven web manifest and no service worker today; adding one
requires explicit cache versioning, sensitive-data exclusions, and eviction on
logout and tenant switch.

#### 15. Compatibility, adoption and enforcement

The two version axes stay independent (§ 1). A `SurfaceContribution` declares the
UI contract range its markup is valid against; the assembly declares the contract
it composes; `create_app` refuses a mismatch. Deprecation windows and failure
behaviour are stated, not implied.

Components are extracted **product-first and adoption-led**. Two templates that
look alike is not a candidate; § 5's extraction rule and the 2026-08-12
evidence ladder are unchanged by this amendment.

**Enforcement is manifest-driven, not glob-driven.** Today
`tests/architecture/test_web_conventions.py` scans a hand-maintained
`TEMPLATE_ROOTS` list under `admin/**`, `auth/*` and `platform/**`, and the
non-admin sweep is scoped to the `/admin` prefix. A facet contract multiplies both
roots and prefixes, so the gates must enumerate **declared facets** and fail on an
unenumerated one. Every guard ships a sensitivity canary; this file's own history
is why — `TEMPLATE_ROOTS` was once `PROJECT_ROOT / "templates"`, which stopped
existing when templates moved into the kernel package, and four checks went on
passing while scanning nothing.

Each authentication profile gets **real-browser canaries**: login, navigation,
read, create/edit, destructive mutation, CSRF, permission denial, conflict, error
recovery, logout. Exercised across multiple tenants, brands, locales, RTL,
light/dark, responsive sizes, and keyboard/screen-reader operation.

A **synthetic second facet** is legitimate for proving generic runtime mechanics.
It is not evidence of reuse: presentation components become `reuse-proven` only
through real product adoption.

#### 16. Migration

`web_routers`/`nav` becomes a compatibility adapter onto an assembly-declared
`staff_admin` facet, for one migration window, with a stated deprecation and
removal gate. The kernel never synthesizes that facet: legacy routes require an
explicit authentication profile and admission permission, so an upgrade cannot
silently replace the former admin gate with a public or authentication-only
surface. A `ModuleManifest` omitting `contract_version` while using the legacy
fields infers contract 1; an explicitly named contract is never rewritten. The
adapter is preserved for `staff_admin` only — never extended to a second facet,
which would make the adapter permanent by making it useful.

The kernel's pre-existing platform UI is the narrow exception during this same
migration window. When `platform_surface_enabled=True` and the assembly has no
`platform_admin` declaration, the kernel supplies that one facet with its
existing platform-admin cookie provider and route references. This preserves an
already-secured audience; it is not available to modules and never infers a
tenant permission. An explicit assembly facet replaces the compatibility one.

Template Studio is the canary: it is the only installable module contributing a
surface today, so it is the whole migration and the whole risk. A second audience
facet in a real assembly is what proves the model; a synthetic one only proves the
mechanics.

#### Non-goals

No universal schema-to-page generator. No closed list of facet codes. No raw
roles or guard callables in manifests. No authorization based on hidden UI. No
per-module frontend framework. No arbitrary assembly template shadowing. No
speculative mobile component library. No attempt to reuse one rendering runtime
across web, Flutter, email and documents. And explicitly not remote
microfrontends — this stays server-rendered Jinja/HTMX composition.

#### Ownership and enforcement matrix

Every requirement above names an owner and an enforcement point. Where the
enforcement column says *none yet*, the requirement is **unmonitored rather than
exempt** (ADR-0018) and the implementation branch owes it a gate.

| Requirement | Owner | Enforcement point | Exists today? |
|---|---|---|---|
| Facet codes declared, not enumerated | assembly manifest | registry validation at `create_app` | implemented; canary added |
| `WebFacetMount` shape | assembly/profile | startup validation | implemented; canary added |
| `WebSurfaceContribution` shape | module manifest | startup validation | implemented; canary added |
| Prefix/route-name/nav-ID/namespace collisions | kernel | startup validation | implemented; canaries added |
| UI contract compatibility | `dotmac-ui` + kernel | startup validation | implemented; canary added |
| Surface state request-scoped | kernel | runtime context + architecture test + two-facet request canary | implemented; `test_facet_security_conformance.py` drives two facets in one process and re-checks the first, so cross-facet and cross-request carry-over both fail |
| Navigation by route name | kernel | route registry canary + composed-assembly resolution canary | implemented for v2; v1 adapter bounded. `test_every_declared_route_reference_resolves_in_this_assembly` re-checks every facet entry/login/landing/logout and every nav item against the routes this assembly actually mounts |
| Shell/login/landing/logout by route reference | facet + kernel | startup method validation + template canary | implemented for v2; v1 fallbacks bounded |
| Module template namespace cannot be shadowed | kernel loader | loader precedence canary | implemented for v2; no override slots published yet |
| Authentication profile | facet | typed provider construction | implemented for tenant and platform profiles |
| Facet admission by permission | kernel seam | `authorize_party` + boot-time code check + declaration/plane coherence canary | enforced for `staff_admin`. `test_admission_is_only_declared_where_the_runtime_can_enforce_it` refuses an admission permission on a non-TENANT plane, where the runtime never evaluates it; the behavioural non-admitted journey stays `staff_admin`-only and `test_the_behavioural_admission_journey_covers_every_admitting_facet` asserts that premise instead of assuming it |
| Route authorization | module | route-guard test + facet-derived mutation sweep | implemented. `test_every_facet_mutation_carries_csrf_and_an_auth_tier_guard` enumerates from `assembly.web_facets`, so a new facet is swept by being declared; `test_the_facet_sweep_reaches_more_than_one_facet` stops it collapsing back to `/admin` |
| CSRF by transport | kernel | explicit route dependency + fail-closed canaries | implemented. Canaries cover a missing `CSRFMiddleware`, incomplete middleware state, a cookie-less unsafe request, and every authentication-exempt browser route still carrying the dependency |
| Native POST carries hidden CSRF proof | kernel | `test_web_conventions.py` | implemented across declared template roots |
| CSP from typed capabilities | kernel | composition + tighten-only canary matrix | implemented with a closed requirement vocabulary. The canaries mutate the LIVE composed baseline rather than a restated literal: a raw override beside an active requirement, a dropped directive, a widened source and an untyped directive are each refused, and the unmodified baseline is accepted so the refusals cannot all be passing for the wrong reason |
| WCAG 2.2 AA per journey | `dotmac-ui` + facet | browser journey tests | target declared, page tests absent |
| Typed render models in templates | module | extended thin-adapter test | implemented for the v2 Template Studio canary; legacy surfaces remain unmonitored |
| Brand/locale independence | kernel resolver | contrast + isolation tests | partial |
| One browser runtime per assembly | assembly | capability resolution at startup | implemented for declared capabilities |
| Per-facet budgets / CWV | assembly | performance canary | none yet |
| Mobile as separate assembly | product | dossier + extraction gate | none yet |
| Manifest-driven governance sweep | kernel tests | sensitivity canary | implemented for composed template roots and v2 surface packages, and re-derived from declarations in `test_facet_template_conventions.py` (which asserts it is a widening of the old `admin/**`, `auth/*`, `platform/**` globs, not a re-scoping) |
| Non-page template exemption | kernel | never-rendered premise check | implemented; `test_non_page_templates_are_never_rendered_as_a_response` replaces the `components/` directory premise with a machine-checked one (ADR-0018 § 2) |
| Facet shell reaches the CSRF bridge | facet + kernel | `{% extends %}` chain walk | implemented for every declared facet, with a sensitivity proof |
| Form method is one a browser honours | module | template canary | implemented; no violation today, so the detector carries its own sensitivity proof |
| No authored facet prefix in a template | module + kernel | two-directional ratchet + v2 zero-pin | implemented; contract-v2 surface packages are pinned at zero, legacy v1 debt is frozen in `facet_navigation_debt_baseline.json` (45 occurrences, 27 files) and may only fall by regenerating it |
| Guard exemption states a checkable premise | kernel tests | exemption-integrity canary | implemented; every mutating exemption must be a non-browser route or an assembly-declared facet entry route, exemptions must name routes that exist, `AUTH_GUARD_NAMES` must resolve to real callables, and the counts are a two-directional ratchet |

#### Unresolved, with owners

These are named rather than decided, so they are not lost between this ADR and
the implementation branch:

1. **Whether `dotmac_workspace`'s hand-rolled profile is ported as-is or
   generalised** when the authentication profile becomes a kernel type.
2. **The mobile source-and-test inventory** across Sub's two Flutter apps and any
   counterpart elsewhere, before any shared mobile package is named.

The reference assembly's real `platform_admin` facet is the second audience
canary for the runtime mechanics. It does not prove that a module surface is
portable across products; that still requires the independent-product adoption
evidence in § 15.

### Decision amendment — 2026-09-30 (composition of rendered notification content)

Template Studio may compose multiple **already rendered email bodies** into one
email. The caller supplies the ordered parts and names the part that supplies
the subject. The composition operation preserves each subject/body as rendered;
it does not invent a replacement message, remove template copy, resolve an
event group, infer a recipient, choose a channel, apply consent, or enqueue a
delivery. Full bodies may repeat greetings until a separately specified
fragment-template contract exists. The returned ordered parts retain content
provenance for the adopting product's intent record.

This narrows the Sub payment-notification cutover after its rejected PR #3368:
that attempt grouped events before their per-channel templates ran, replacing
receipt content with a generic email and dropping SMS. Sub remains the owner of
which event facts share a proven payment episode, the bounded wait, and what a
late fact means. The module owns only the reusable content operation. Consent,
channel policy, intent and delivery retain their § 5c owners. No product cutover
is implied by this source addition; the extraction dossier still requires Sub
to pin a released version, shadow rendering, and retire or gate its local
renderer at the cutover.

The source audit found no qualifying production multi-message composition
implementation to port: Sub renders one template at a time, ERP's template
source is for documents, and #3368 was closed without merging. This pure seam
therefore adds only the missing shared content operation; Sub's existing
single-brace renderer and its parity tests remain the product-first source.

The substitution function is also exposed from the package's pure `rendering`
module. Importing that module must not assemble Template Studio's routes,
models, or Kernel web dependencies. The existing `service.render` delegates to
the same function and retains its authoring error contract. This lets Sub run
shadow parity under its own runtime before any authoring or delivery cutover.

## Consequences

- F1–P1 have fixed vocabulary. "Module", "theme", "brand", and "facet" mean one
  thing each, and a design that blurs two of them is rejected on sight rather
  than debated per PR.
- Some duplication survives F0 on purpose. The extraction rule is a brake, and it
  will feel like one; the alternative is a shared component library with no owner.
- Tenant custom CSS acquires a stated retirement path, which is a commitment to
  break something currently supported. The compatibility seam and its removal
  gate are the price of the CSP and legal-identity invariants.
- The two version axes (module contract, UI contract) mean two compatibility
  matrices to maintain. That is the cost of letting the UI system evolve without
  a fleet-wide module re-declaration.
- The ADR text alone is not implementation evidence. The 2026-08-25 facet
  implementation that followed it supplies the runtime and canaries recorded in
  the enforcement matrix; rows still marked partial or `none yet` remain open.
- The facet implementation replaces process-static surface state for composed
  v2 requests and removes `require_web_auth`'s hardcoded role from facet
  admission. The v1 adapter remains bounded to `staff_admin` for the migration
  window.
- The amendment also identified a live security defect rather than only a design
  gap: CSRF used to mean "the request carried some cookie", which missed a
  pre-auth cross-site POST. The independent kernel fix now derives protection
  from the composed browser route and validates signed, session-bound proof on
  every unsafe operation, including login and logout.
- At amendment time its enforcement matrix was deliberately mostly "none yet".
  The matrix now records the implementation evidence that followed, while the
  remaining `none yet`/partial rows stay unmonitored rather than exempt under
  ADR-0018. Naming a requirement creates an obligation; changing a row requires
  a real gate or canary, not prose.
- The mobile section commits to no mobile code. It exists to stop `WebFacetMount`
  being stretched into a channel-agnostic abstraction later, which is cheaper to
  prevent now than to unpick after two adopters.

## References

- `docs/adr/0003-unified-deployment-profiles.md`
- `docs/superpowers/reviews/2026-07-18-module-control-plane-directive.md`
- `docs/inventories/README.md`
- `docs/inventories/module-extraction-sources.md` (the product-first dossier index)
- `docs/inventories/template-studio-source-audit.md` (evidence for the 2026-08-10
  amendment)
- `docs/inventories/facet-composition-blast-radius-2026-08-25.md` (evidence for
  the 2026-08-25 facet amendment)
- `packages/dotmac-kernel/COMPATIBILITY.md` (kernel public surface + versioning)
