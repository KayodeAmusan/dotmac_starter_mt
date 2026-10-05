# Agent rules — dotmac_starter_mt

Tool-neutral rules for ANY coding agent working in this repo. This file is
the canonical hard-rules reference; `CLAUDE.md` (repo map + web-portal
specifics) points here and must never fork these rules.

## Documentation hierarchy

- `docs/ARCHITECTURE.md` — as-built truth (model provenance, ownership,
  transaction authority, settings, portal). If code and a doc disagree,
  reconcile toward reality and fix the doc.
- `docs/adr/` — decisions with status; amendments are dated notes, never
  rewritten history.
- `docs/superpowers/plans/` and `specs/` — non-authoritative intent; never
  cite a plan as proof of current behavior.
- `README.md` — onboarding. `CONTRIBUTING.md` — human dev rules.
  `docs/SECURITY.md` — security posture (ASVS mapping).
- `docs/CONTROL_EXCEPTIONS.md` — controls that were bypassed, with cost and
  remediation. Append-only: an entry is never deleted, only its remediation
  state changes.

## Hard rules (enforced — test/contract named per rule)

1. **Adapters are thin.** `router.py`/`web.py` never issue direct DB queries
   (no `db.query(`, `db.execute(`, `select(`) — logic lives in `service.py`.
   Adapters validate, authorize, delegate and render; a DECISION belongs to one
   service. This repo identifies an adapter by FILENAME, which is why the check
   is a three-line `rglob` — that naming convention is load-bearing, not
   cosmetic. ADR-0010 makes the rule fleet-wide and says why a repository
   without such a convention cannot enforce it: `dotmac_erp` has 1223 direct
   queries in 83 web modules living inside `app/services/`, where a
   directory-scoped check passes while missing 96% of them.
   (`tests/architecture/test_thin_wrappers.py`; ADR-0010)
2. **Timestamps render only through the `local_datetime`/`local_date` Jinja
   filters** — never a raw `*_at` attribute in a template.
   (`tests/architecture/test_web_conventions.py::test_timestamp_renders_go_through_local_filters`)
3. **Every mounted route carries a `require_*` guard** (route- or
   router-level), or sits in the commented `ALLOWLIST`. Mutating routes
   need a guard from the explicit `AUTH_GUARD_NAMES` set
   (`require_user_auth`, `require_role`, `require_permission`,
   `require_web_auth`, `require_platform_admin` — `require_tenant` alone does
   NOT count) or a
   commented `MUTATING_ALLOWLIST` entry.
   (`tests/architecture/test_route_guards.py`; non-admin sweep in
   `tests/unit/test_admin_route_sweep.py`)
4. **Every `app/features/<name>` package is registered** in
   `FEATURE_MODULES` and exports a `feature.py` manifest named after its
   package. (`tests/architecture/test_feature_manifests.py`)
5. **Features never import each other; core never imports features.**
   (`pyproject.toml` `[tool.importlinter]` contracts, `make lint-imports`)
6. **The import-linter independence contract's `modules` list stays
   byte-for-byte in sync with `FEATURE_MODULES`.**
   (`tests/architecture/test_feature_manifests.py::test_importlinter_independence_contract_matches_feature_modules`)
7. **No `payload: Any` in feature services** — every payload parameter is a
   concrete Pydantic schema.
   (`tests/unit/test_service_typing.py::test_no_any_typed_payloads_in_services`)
8. **There is ONE transaction authority, and it lives in two files.**
   `dotmac_kernel/session_runtime.py` holds the implementation —
   `DatabaseRuntime`, the class a product instantiates with its own DSNs,
   credentials and tenancy table — and `dotmac_kernel/db.py` is the reference
   assembly's single INSTANCE of it. That is one authority in two files, not
   two; what stays forbidden is a THIRD. No module outside those two calls
   `SessionLocal()`/`PlatformSessionLocal()`/`sessionmaker(...)` or
   constructs `Session(...)`; boundaries (`get_db`/`get_platform_db`/
   `platform_session`/`tenant_session`/`resolver_session`) own
   commit/rollback, services only mutate and flush. `app.current_tenant` is a
   schema contract baked into every composed lineage's RLS policies, never a
   deployment knob — `legacy_tenant_settings` adds names alongside it and only
   ever shrinks (ADR-0066).
   See `docs/ARCHITECTURE.md` § "Transaction authority".
   (`tests/architecture/test_session_authority.py`,
   `tests/architecture/test_session_runtime_is_engine_free.py`)
9. **Feature services never call `db.rollback()`.** Expected conflicts use
   `dotmac_kernel.transactions.conflict_savepoint` — the engine-free public
   owner, not the eager `dotmac_kernel.db` re-export — with the mutation
   INSIDE the `with` block — a bare rollback wipes the transaction's
   `SET LOCAL` tenant context. Full rationale: `docs/ARCHITECTURE.md` §
   "Conflict handling".
   (`tests/architecture/test_no_feature_rollback.py`; canaries in
   `tests/test_conflict_rls_context.py`)
10. **Every registered `SettingSpec` has a real reader** under `app/`
    outside the settings feature/resolver. The intentionally-unwired
    allowlist is EMPTY and may only shrink, never grow, without a task/plan
    reference. (`tests/architecture/test_no_orphan_settings.py`)
11. **Every tenant-scoped table:** `tenant_id UUID NOT NULL`, composite
    unique for anything unique-per-tenant, and `ENABLE`+`FORCE ROW LEVEL
    SECURITY` + policy in the SAME migration that creates the table
    (`domain_settings` is the one documented exception). Platform catalog
    tables instead get NO RLS but are REVOKEd from `app_user`. Enforced
    dynamically by `tests/test_rls_catalog.py` plus the per-feature
    isolation canaries — Postgres only (`make test-db-up &&
    make test-integration`); SQLite cannot enforce RLS.
12. **Manifest declarations are unique, referenced, and consumed.** NINE
    vocabularies work this way — permissions, capabilities, audit actions,
    outbox event types, feature flags, setting domains, provisioning
    participants, charge models and obligation sources — and every later
    vocabulary whose members belong to modules must be another declaration
    registry, never an enum or a fixed list. ADR-0008 is a FLEET-WIDE standard:
    it binds every Dotmac
    repository, not only this one, and applies wherever one layer holds a
    vocabulary another layer owns members of. Each member is declared by
    exactly ONE module's manifest; a consumer may only reference a DECLARED
    member (`require_permission` refuses the boot, `require_capability`,
    `write_audit_event`, `resolve_flag`, the settings write path,
    Fulfillment's `ParticipantRegistry`, and Subscriptions'
    `SubscriptionVocabularyRegistry` refuse the operation); every declared
    member needs a real consumer outside its own `feature.py`; and the backing
    DB column stays a plain string, since
    a CHECK constraint would re-close the list and cost a kernel migration
    per consuming product. Orphan allowlists are EMPTY and may only shrink.
    (`tests/architecture/test_manifest_declarations.py`;
    `tests/unit/test_permissions.py`, `tests/unit/test_audit_actions.py`)
13. **Migration discipline.** Migrations run as `app_admin`
    (`MIGRATION_DATABASE_URL`), never on container boot — the Dockerfile
    `CMD` only runs `uvicorn`; `scripts/deploy.sh` is the only place
    migrations run in production. The same migration that creates a table
    creates its RLS and grants.
14. **One namespace and one migration lineage per stateful module**
    (ADR-0006 D1). A STATEFUL module declares `short_code` +
    `migration_prefix` on its `ModuleManifest`, both allocated in
    `dotmac_kernel.namespaces.MIGRATION_OWNER_LEDGER`; its schema is the
    derived `mod_<short_code>`, never inferred from a display name and never
    re-pointed. A STATELESS module declares neither. `public` stays the
    compatibility namespace of the kernel + this one host assembly and is
    NOT available to installable modules. Module models, migrations, FKs,
    policies and raw SQL fully qualify their schema — never `search_path`.
    Revision ids are `<prefix>_<sequence>_<slug>` and must fit
    `alembic_version.version_num`'s VARCHAR(32); each module lineage has its
    own base and branch label, and `down_revision` never crosses lineages.
    **Cross-lineage ordering is LOGICAL, not physical** (ADR-0006 D1
    amendment, 2026-08-13): a module declares the database EFFECTS it needs
    (`ModuleManifest.requires`), the supplying lineage declares
    `MigrationOwner.provides`, and each ASSEMBLY binds requirement to provider
    revision (`app/migration_bindings.py`, installed from `alembic/env.py`).
    `resolve_depends_on` turns that binding back into a real `depends_on` edge
    at script load, so Alembic ordering is unchanged — but a module lineage
    may **never** name a foreign revision itself, because that edge is true
    only in the assembly that wrote it. Host owners (`kernel`, `assembly`)
    keep literal edges. A binding is a claim, so it is checked two ways:
    the composed gate (`make migration-gate`, also in `make check` and in CI
    *before* `docker-build`) rejects duplicate revisions, prefixes, branch
    labels, schema claims, table ownership, unbound requirements, bindings to
    a lineage that never declared the effect, bindings to an uncomposed
    revision, and migration/manifest drift; and `require_prerequisites`
    verifies the real catalog before any DDL, so a STAMPED provider fails.
    Ordering needs no third check — Alembic enforces the resolved edge, and
    `alembic_version` records branch HEADS, not applied history, so asserting
    a root revision appears there is simply wrong. `alembic stamp`, a blanket
    `IF EXISTS`, and a product conditional inside a kernel migration are not
    bindings and stay forbidden.
    **Allocation is SERIALIZED** (2026-08-21): a module's ledger row is merged
    to `main` as an allocation-only change BEFORE any of its source is
    written. Uniqueness is a property of the canonical ledger, and no check a
    branch runs on itself can see a sibling branch — three unmerged trains
    (`sales`, `support_access`, `service_access_policy`) each allocated
    `prefix="sa"` and every one of them was green. `make allocation-gate`
    (its own CI job, needing `fetch-depth: 0`; deliberately NOT in `make
    check`, which stays offline-runnable) fails a branch that changes
    `packages/<pkg>/src/**` for a module with no ledger row at the MERGE BASE,
    and exits 2 rather than passing when it cannot establish an answer.
    What is gated comes from each package's `EXTRACTION.toml`
    `classification` read AT THE BRANCH HEAD — `optional-module` is gated;
    `stateless-protocol-adapter`, `stateless-contract-catalogue`,
    `presentation-foundation` and
    `universal-facility` legitimately own no lineage — never from a directory
    name or from "does it have a manifest", both of which fail open. A missing,
    unreadable or unknown classification FAILS. A genuinely stateless manifest
    (no `short_code`/`migration_prefix`) needs no row. Deleting a module
    passes: its row is a PERMANENT reservation, never reclaimed, so a retired
    prefix can never be handed to a new owner and collide with rows still live
    in a deployed database — a rename is a deletion plus an addition, and the
    added side is gated normally. The in-tree companion,
    `test_every_module_packages_full_allocation_matches_the_ledger`, uses the
    same classification and the same AST parser to check the COMPLETE
    allocation — schema, prefix AND branch label — resolving a row by `code`
    or, if the code was renamed, by `migration_branch` against the immutable
    `branch_label`.
    **Serialization needs a scalar, and the scalar is a content DIGEST**
    (2026-09-04): the merge-base rule above serializes SOURCE behind
    ALLOCATION, and nothing serialized one allocation against another — two
    sibling branches off one base, one appending a row at the tail and one
    inserting a row mid-list with the SAME prefix, merge under `git merge-tree`
    with exit 0 into a ledger holding two rows on one prefix. Every structure
    involved absorbs an independent addition (order-insensitive tuple, list
    `__all__`, SET literal of pinned owners, unordered markdown table), so only
    the composed uniqueness check bites, and it bites after the merge on a red
    `main`. A COUNTER is insufficient: two branches can both change 90 to 91,
    merge cleanly on identical text, and recreate the defect. So the ledger
    carries `MIGRATION_OWNER_LEDGER_DIGEST` — `cv1:<64 hex>` over every field
    of every `MigrationOwner`, rows SORTED BY OWNER, in the kernel's existing
    `cv1` semantic encoding (length-prefixed frames, typed absence sentinel,
    domain-separated hash) rather than a new one. Sorting is load-bearing: a
    mid-list insert and a tail append of the same row must digest identically,
    or relocating a row would dodge the conflict. EVERY commit that adds,
    removes or repoints a row restamps that literal; a stale or malformed one
    is refused in-tree by `verify_migration_owner_ledger_digest()`, and a
    branch that changes a row without moving it is refused by the allocation
    gate against its merge base (a ledger with no digest at all exits 2, never
    passes). The digest forces a HUMAN to resolve and decides nothing about the
    resolution — `test_the_shipped_ledger_itself_composes` stays, and is now
    asserted by name, because it is what catches a resolver who pasted both
    rows and restamped.
    (`tests/unit/test_namespaces.py`, `tests/unit/test_migration_gate.py`,
    `tests/architecture/test_ledger_digest_serialization.py`,
    `tests/unit/test_prerequisites.py`,
    `tests/unit/test_live_catalog_contract.py`;
    `tests/test_module_schema_catalog.py` is the post-migration live-catalog
    gate on Postgres.)
15. **Cross-repository engineering governance is pinned and required.**
    `.dotmac/standards-profile.json` names this repository's declared authority
    and fully typed contract surfaces, and pins the accepted Governance source
    by exact commit. The `Dotmac engineering standards` CI job must execute the
    Governance action at that same commit; a mutable tag/branch, copied policy,
    candidate mode, missing job, or source/profile revision mismatch is not an
    admissible substitute. Product CI is evidence only for the product revision
    it evaluated. (`.github/workflows/engineering-standards.yml`; Governance
    ADR 0006 in `michaelayoade/dotmac_governance`)
16. **The design system is consumed through its published surface only.**
    The assembly imports only names in `dotmac_ui.__all__` or in a
    `SUPPORTED_MODULES` module's `__all__`; `dotmac_ui` itself imports no
    kernel, no assembly, no web framework, no ORM, and no templating engine,
    and declares no runtime dependency beyond `python`. Design tokens are
    named by ROLE, never by value (`--dmui-action-destructive-hover`, never
    `--teal`), and no `.dmui-*` component class ships without being declared
    in `PUBLISHED_COMPONENT_CLASSES` + the package's `COMPATIBILITY.md`
    (ADR-0006 § 5 — a component is extracted only with the same contract, a
    named owner, and a migration path, never because two templates look
    alike). (`tests/architecture/test_ui_public_surface.py`; `pyproject.toml`
    contracts "Kernel must not import the UI package" and "UI package must
    not import the kernel or the assembly")
17. **Every cache key carries its scope, built by `dotmac_kernel.cache`.**
    Scope is a type (`TenantScope`/`PlatformScope`), never a nullable
    `tenant_id`: a `None` tenant is indistinguishable from a forgotten one, and
    the platform entry becomes the bucket every unscoped read lands in. No
    module builds a key by interpolation, and no `@lru_cache` decorates a
    function taking tenant-bearing input — a process-wide memo over tenant data
    serves one tenant's value to every other.
    (`tests/architecture/test_cache_scope.py`)
18. **A feature flag is not a permission and not an entitlement.** Flag codes
    are disjoint from permission and capability codes; every declared flag has
    an owning module and a real consumer; an expired flag fails the build, never
    production. (`tests/architecture/test_feature_flags.py`)
19. **`dotmac-ui`'s compiled assets are COMMITTED and match their token
    source.** `packages/dotmac-ui/src/dotmac_ui/static/**` is the published
    contract, not a build artifact — never gitignore it, never hand-edit it;
    regenerate with `make ui-build` and commit the diff. The stylesheet stays
    self-contained (no `@import`, CDN, remote origin, or `@font-face`) and
    preprocessor-free (no `@tailwind`/`@apply`/`@theme`/`@layer`), so a
    consumer on any Tailwind major — or none — links it as-is (ADR-0006 D3).
    (`make ui-check`, wired into `make check`;
    `tests/unit/test_dotmac_ui_tokens.py`)
20. **A secret is HELD, never dereferenced.** Nothing on the settings
    resolution path reaches a network — not for a value, not for a key. A
    value that cannot be held is not a setting: if it must live in a secret
    store, the product reads it and installs it via
    `dotmac_kernel.secret_sources.SecretSource` (named material) or
    `dotmac_kernel.settings_crypto.KeyProvider` (encryption keys), or seeds it
    as a real setting. A row whose value merely LOOKS like a reference
    (`bao://...`) resolves to that string; the kernel does not recognise the
    scheme. Both seams load once at install, rotate on an explicit refresh,
    keep the working set when a refresh fails, raise rather than start
    degraded, and never log, repr or quote a value — only names (ADR-0009).
    (`tests/unit/test_secret_sources_no_network.py`,
    `tests/architecture/test_secrets_are_held.py`)

21. **Settings resolution reads rows and defaults — never the environment.**
    `env_var` is a declaration whose only consumer is `seed_settings_from_env`,
    which runs idempotently on every application-process start and never
    overwrites an existing row — so changing the variable later does NOT
    update or rotate the setting; the settings owner is the only way in after
    first creation. Precedence is
    `scope chain -> assembly profile default -> spec fallback` (the profile
    level is ADR-0013); the environment does not appear at any rank, because it
    is a loader that produces a row rather than a source that competes with
    one. A value in effect is therefore always one an operator can see and
    change (ADR-0011, amended 2026-08-20).
    (`tests/unit/test_settings_resolution_ignores_env.py`,
    `tests/architecture/test_settings_env_is_bootstrap_only.py`)

22. **A setting declares whether it inherits.** `SettingSpec.inherits`
    defaults to `True` (walk the scope chain, then the spec default) and is set
    `False` for a value that IDENTIFIES something owned by one scope — a ledger
    or bank account, a warehouse, an external system's id. A fallback claims a
    less-specific value answers the question; for an identifier it does not.
    Pair with `required_at` for "must be set here, no fallback, fail loudly".
    Honoured by single-key AND bulk reads (ADR-0012).
    (`tests/unit/test_setting_inherits.py`)

23. **At-most-once execution has ONE owner.** `dotmac_kernel.idempotency`
    owns the ledger, the engine, the conflict rule and the retention sweep;
    `messaging.process_once`/`process_once_platform` are adapters over it, not
    a second mechanism. A scope names the OPERATION, never an HTTP route. The
    effect and its ledger row commit in the SAME transaction — nothing is
    reserved before the effect, so a crashed attempt leaves no marker and the
    retry re-drives, and there is no "in progress" state to get stuck in. The
    request fingerprint is its own column and is never overloaded onto a result
    id; a key reused with a different fingerprint is a conflict, not a replay.
    Retention is the product's policy: `expires_at` is nullable and the kernel
    sets no default TTL. Non-transactional effects belong in the outbox
    instead (ADR-0014).
    (`tests/unit/test_idempotency.py`)

24. **Shared capabilities are extracted product-first, not rebuilt beside a
    mature product implementation.** Before adding kernel/module behaviour,
    inventory ERP, Sub, and every product named in the candidate scope. A
    qualifying production-used, tested implementation is the mandatory
    reference and initial code source; port its behaviour and parity tests,
    generalising only at typed product seams. Every distribution under
    `packages/` carries `EXTRACTION.toml` with its owner, contract, source
    paths/tests, consumers, first cutover, drift proof, and local-copy
    retirement gate. A greenfield shared implementation requires checked-in
    evidence that no qualifying product implementation exists. Copying is a
    one-time extraction: no permanent fork, parallel writer, or second owner.
    (`tests/architecture/test_product_first_extraction.py`; ADR-0006
    § "Decision amendment — 2026-08-08 (product-first extraction)")

    **A pin is installation, not adoption (amendment 2026-08-29).** A dossier's
    `status` and its `adoption_evidence` rows are coupled in BOTH directions.
    An exact pin means a consumer INSTALLED the distribution; it says nothing
    about composition, and lineage absent + storage absent + writer unchanged
    is entirely compatible with one. So an adoption state (`adopted`,
    `reuse-proven`) requires at least one row that can prove COMPOSITION or
    CUTOVER — an `adopted` assertion naming a structured field at an immutable
    commit, or a `live_observation` whose subject is this capability inside the
    consumer's running system. `pinned_at`, `contract_binding`, `workflow_run`,
    `deploy_run` and `image_digest` are installation facts and never suffice:
    one deploy run and one image digest in this tree are each cited by three
    different dossiers, so neither can say WHICH capability was composed.
    Conversely an `adopted` ROW under a status that does not claim adoption is
    the same contradiction read backwards, and the schema defines no
    historical/superseded state that would admit both. A branch name is refused
    in every role including `locator`: `main@<sha>` is not a coordinate, and
    demoting a bad coordinate to a human handle does not make it point at the
    same tree tomorrow. Scopes still resting on installation alone are an
    exact, two-directional backlog (`PIN_ONLY_ADOPTION_DEBT`), which is
    declared debt and not an exemption. No field of AdoptionEvidenceV1 is an
    input to a permission; this refuses a self-contradictory file and
    authorises nothing.
    (`tests/architecture/adoption_evidence.py`;
    `tests/architecture/test_product_first_extraction.py`)
25. **A guard exemption states an enforceable premise, or it is not an
    exemption.** Excluding a path from a lint, type, architecture or security
    check requires a premise that is machine-checkable in the same change; an
    unverifiable premise makes the region unmonitored, not exempt. Guards
    enumerate ENTRY-POINT FAMILIES (tasks, scripts, CLI, workers, cron), never
    a single directory — where a guard's docstring claims broader scope than
    its configuration, the configuration is the defect. An existing backlog is
    retired by a TWO-DIRECTIONAL ratchet that fails when the count rises OR
    falls without being lowered, kept distinct from any per-line
    "reviewed and correct" marker, and carrying a sensitivity proof that the
    detector still fires. (ADR-0018; `dotmac_erp` reference implementation:
    `scripts/check_session_context.py` + `session_context_legacy.txt`)

    **Amended 2026-08-31 — SUBJECT, EXTENT, LIFETIME.** A guard makes a claim
    about a subject, over an extent, for a duration, and each can be wrong
    INDEPENDENTLY while the other two look fine — all three producing an
    unmonitored region that reports as covered. One rule, three shapes.

    *Subject:* a guard that checks a NAME rather than the property. `"PYTHONPATH"
    not in dockerfile` failing on the comment explaining its absence; a ledger
    test catching its own docstring; a verb detector reading a usage comment as
    a deployment and drawing a call edge BACKWARDS, because a path mention is
    symmetric while invocation is not; a ratchet failing on a type-annotation
    import. Move from a name to a property: parse rather than grep, strip prose
    before scanning, resolve an identity from metadata. Corollary: a rejection
    vocabulary other owners import VERBATIM is a published contract, and
    changing it is a contract change wherever the file lives.

    *Extent:* a hand-maintained list, or authored files while derived artifacts
    go unchecked. A profile guard enumerated FIVE stateful modules while the
    assembly composed SIX. And `dotmac_erp` PR #426 (merged `4ab8761d`) asserted
    a deleted entrypoint's absence scoped to the ROOT compose only, while the
    rendered sibling still named `/app/entrypoint-monitoring.sh` in every role —
    a file absent from the image's COPY allowlist. **The rendered project could
    not have started, and the guard for exactly that defect was looking one file
    away.** A repository that RENDERS deployment artifacts has TWO populations,
    and a guard written against the authored one is silent over the deployed
    one. DERIVE the extent, never declare it.

    *Lifetime:* a relaxation that never names its expiry. ERP carried
    `require-real-digests: false` while its descriptor already held a real
    digest; nothing recorded when it should be armed, so it never was. This is
    the premise rule read carefully — **a premise with no expiry is not
    enforceable; it is permanent by default while reading as temporary.** The
    conforming shape names the condition (Vendor CP ADR 0017's stated retirement
    conditions; this repo's `deployment-adopter.yml` numbered re-enabling
    conditions).

    Each shape carries a sensitivity proof — fires on the planted defect, silent
    on the conforming form — and the lifetime guard was introduced over existing
    debt the way this rule requires, as an exact two-directional ratchet rather
    than a blanket allow
    (`tests/architecture/test_guard_subject_extent_lifetime.py`;
    `docs/inventories/guard-lifetime-baseline.json`)

26. **Starter-owned templates author colour against `var(--dmui-*)`, never a
    literal palette.** A hardcoded Tailwind palette utility (`bg-slate-700`,
    `text-primary-600`, `text-white`) or a raw hex/`rgb()` literal in any
    template under `packages/*/src/*/templates` is frozen debt: the existing
    851 occurrences across 29 files are recorded per-file and per-token in
    `tests/architecture/palette_debt_baseline.json`, and the ratchet fails when
    that inventory rises OR falls. A slice that genuinely retires palette usage
    lowers the baseline in the SAME change (`make palette-baseline`) so the
    reduction is reviewable as a diff. The document canvas, tenant login,
    authenticated admin shell, `platform/**`, `layouts/platform.html` and
    Template Studio are token-native and are asserted at zero against the live
    scan, so a regenerated baseline cannot legalise a regression there. (Rule
    25's ratchet shape applied to the design system; `test_palette_ratchet.py`)

27. **A dual-plane module has ONE behaviour and TWO DECLARED persistence
    planes.** A capability that genuinely operates in both security contexts —
    a tenant data plane and the control plane — ships one lifecycle, vocabulary
    and transition engine, and two storage planes declared separately on its
    manifest: `tables` (tenant: `tenant_id NOT NULL`, RLS ENABLEd *and* FORCEd,
    composite uniques) and `platform_tables` (control plane: no tenant column,
    no RLS at all — not even ENABLEd-with-no-policy, which denies every row to
    the control plane while reading as protected — GRANTed to the platform roles
    and **REVOKEd from the tenant app role** across ALL SEVEN table privileges
    and their column-level forms; on that plane the revoke IS the isolation, and
    it is checked as strictly as a policy is on the other side). A platform
    table must also be REACHABLE by the online platform role: that role needs
    schema `USAGE` plus at least one row DML privilege (`SELECT`, `INSERT`,
    `UPDATE`, `DELETE`); `REFERENCES`, `TRIGGER` or `TRUNCATE` alone does not
    make a request path usable. Declared-and-unusable is a violation too. The
    plane is DECLARED, never inferred from a missing `tenant_id`, or a table
    that merely forgot the
    column would reclassify itself and lose isolation silently; a table may
    appear in exactly one plane. **No foreign key crosses the planes** — they
    share a lifecycle, never a row. The gate enforces that for FKs whose SOURCE
    is in the module schema; a product-owned link table in `public` is
    UNMONITORED rather than exempt, which is why a dual-plane module ships one
    link helper PER PLANE and each refuses an unusable configuration. Nullable
    `tenant_id`, sentinel/fake tenants and polymorphic scope columns are
    rejected and refused by the gate. Two
    planes require a real named assembly on each side TODAY; most modules are
    tenant-only and must stay that way. A module whose one lineage can install
    plane subsets declares every supported combination; its assembly MUST make
    one explicit per-module `ModulePlaneSelection`. Prerequisite bindings only
    name providers and NEVER select a plane — a provider may truthfully exist
    while the product intentionally excludes that plane. Missing, duplicate,
    unknown or unsupported selections fail the static composition; migrations
    and the live-catalog gate consume the same selection (ADR-0028). (ADR-0023;
    `tests/unit/test_live_catalog_contract.py`,
    `tests/unit/test_namespaces.py`,
    `tests/architecture/test_ticketing_module.py`)

28. **Applications are independent; they compose by synchronizing DATA.**
    Every application owns its runtime, database, migrations, sessions,
    authorization and domain decisions. Cross-application integration is only
    through versioned APIs/webhooks: an adapter records a typed, deduplicated
    observation, then a local resolver updates a rebuildable projection or asks
    the local owning service to act. An importer never assigns an authoritative
    status, permission, entitlement or lifecycle field directly, and no app
    reads another app's database, tables, ORM models or filesystem. An
    installable module is also independent, but is composed LOCALLY: each app
    pins its own copy, runs its own lineage and owns its own rows; the module
    imports neither its assembly nor a sibling module. Shared execution paths
    contain no product/provider branches or mode flags. Products declare only
    provider-neutral domain ports and capability versions; provider identity,
    wire mappings, endpoints and secret references stay in Integrator connector
    plugins. Outbound synchronization leaves through a durable outbox after the
    local transaction. Configuration binds a transport capability, never the
    business owner. The independently deployed Dotmac Integrator is the sole
    EXTERNAL connector control plane, but deployment is not code location:
    Starter's stateful `dotmac-integration` module owns the registry,
    installations, bindings, secret references, inbox/outbox, retries,
    checkpoints, health, repair and its `mod_*` lineage; the separate
    `dotmac_integrator` repository is a thin assembly that pins kernel, that
    module and connector distributions and runs them. It never implements a
    second engine. Products do not each compose the module, and they carry no
    provider clients,
    provider credentials, provider webhook verification, connector schedules,
    checkpoints or delivery retry engines. Products expose typed domain ports;
    Integrator owns transport evidence and never writes product domain tables.
    External systems are independently released connector PLUGINS discovered
    from package metadata through one versioned SPI; the `dotmac-integration`
    module and thin assembly have no provider enum/import list/conditional.
    Plugins declare versioned
    capabilities and config schemas, translate wire formats and perform I/O,
    while the Starter module exclusively owns bindings, secret materialization,
    inbox/outbox, idempotency, retry, checkpoints, health and repair evidence.
    One installation has exactly one active plugin per capability; duplicate or
    incompatible bindings fail closed.
    A remote projection requires a named local reader and reconciler; foreign-key
    compatibility alone is not a reason to keep one. Correlation-only needs use
    an opaque Integrator reference on the local owning record.
    **One capability id is one contract with one PAYLOAD, and the payload
    belongs to the owning DOMAIN.** `CapabilityContract` — what the owning
    business application publishes — carries `command_schema`, `result_schema`,
    `observation_schema`, a canonical contract digest and deprecation metadata;
    a connector's `CapabilityDeclaration` may only CLAIM that digest and may
    never publish a competing schema, because a schema per connector makes drift
    machine-readable rather than prevented. Enforced at four seams: the command
    before a delivery row exists (`execution.enqueue_delivery`), digest
    agreement at composition AND at binding
    (`capability_registry.require_implements_only_declared`,
    `require_declared_for_binding`), the result before the claim-guarded settle
    (`dispatch.settle`), and every observation before the inbox batch commits
    (`ingress.record_batch`, which the polling path calls). A schema change
    takes a new `.vN` id — a published version is SUCCEEDED, never redefined,
    and `install_capability_registry` refuses a reload that redefines one. A
    contract that has published nothing yet must SAY so, with a
    `SchemaGrace(reason, retire_after)`; silence is refused at construction, the
    ungated set is enumerable (`schema_grace_register`) and the window closes.
    (ADR-0024 §§ 10-12, ADR-0061 A2;
    `tests/unit/test_integration_capability_contract_gate.py`,
    `tests/architecture/test_capability_contract_divergence.py`)
    (ADR-0024; import-linter contracts `Modules must not import the assembly`
    and `Modules are independent of each other`; ADR-0010/0014)

    **Outbound clauses added 2026-08-24, corrected the same day, and extended
    the same day with *(i)*–*(k)* and then *(l)*–*(o)* — REVIEW DISCIPLINE, not
    guards.** Stated here
    because rule 25 forbids implying enforcement that does not exist: no check
    in this repository catches any of the following today, and clauses *(j)*,
    *(k)*, *(m)*, *(n)* and *(o)*
    additionally concern a repository this one does not contain.
    Clause *(f)* names the gate that has to be built
    before most of them can be checked at all; until it exists these are read
    by reviewers, not by CI, and ADR-0024's "Enforcement and evidence"
    additions name the missing machinery.
    *(a)* **One capability, one contract, one payload.**
    `payments.payout.v1`, `messaging.send.v1` and every other id name a
    BUSINESS ACT, not a provider endpoint. No provider-named id
    (`payments.payout.paystack.v1`), no provider-shaped sibling for an act that
    already has a contract (`payments.transfer.v1`), and no per-connector
    command dialect behind a shared id — that last one is the branch relocated
    into whichever product builds the payload.
    *(b)* **A provider branch in a product is one of six concrete things:** an
    `if provider == …`/provider enum/provider-keyed behaviour dict; a provider
    SDK import or hand-written provider HTTP client; a provider credential in
    product config, env, settings rows or a path the product dereferences; a
    provider-named route/task/queue/column/setting/flag/table; a provider
    string inside a business decision (status mapping, currency scale, retry
    eligibility); or a "which provider is configured?" read on a request path.
    Each belongs in the connector distribution or the Integrator binding.
    *(c)* **Connector completeness is Dotmac capability parity** — every
    capability the ecosystem needs, with interchangeable providers behind the
    ones that matter — never coverage of a provider's published surface. A
    withheld surface is DECLARED in the connector's `EXTRACTION.toml`, not
    merely absent (LinkedIn outbound, Mono writes and Flutterwave transfers are
    the three in force).
    *(d)* **A payout is ERP's decision, and the deciding service is NAMED.**
    Whether a payout happens, to whom, for how much, and whether an ambiguous
    attempt may be retried are ERP's calls; no connector, engine path,
    configuration or operator gesture decides them. "ERP's Treasury/payment
    owner" is a role, not an owner, so the owner is named as the services that
    hold the decision today: `PaymentService`
    (`dotmac_erp:app/services/finance/payments/payment_service.py`) owns the
    payout decision and the transfer lifecycle, and is the SOLE interim owner.
    `BatchTransferService` is dead code — zero callers, not exported, zero
    tests — and is NOT an owner; it is a DELETION (clause *(k)*). A shared
    `dotmac-treasury` distribution or namespace is STILL NOT to be created:
    rule 24's product-first dossier now exists
    (`docs/inventories/treasury-payment-execution-sources.md`, on the sibling
    branch `docs/treasury-product-first-dossier`; its § 12.3 G5 asks for the
    record in terms), and its answer is ADR-0063 — clause *(j)*. The release
    condition is no longer "a dossier exists" but "the ERP defect is fixed".
    *(e)* **Modules own metric DEFINITIONS; assemblies own EXPORTERS.** A shared
    module declares stable, namespaced metric names and derives values from its
    own facts at read time; it ships no metrics client, counter registry or
    `/metrics` route, and no second observability path.
    *(f)* **The canonical schema belongs to the DOMAIN, not the connector.**
    The business owner's `CapabilityContract` carries `command_schema`,
    `result_schema`, `observation_schema`, a canonical contract digest, and
    deprecation/replacement metadata. A connector's `CapabilityDeclaration`
    keeps configuration and modes and may only CLAIM the domain contract's
    digest — it never publishes a competing schema, because a schema published
    per connector does not prevent drift, it only makes drift machine-readable.
    The required gate, which is one unit of work and not five: command
    validation before enqueue; connector digest agreement at composition AND
    again at binding; result validation before settlement; observation
    validation before inbox recording; and a schema change taking a new `.vN`
    capability id rather than redefining a published one. Sensitivity tests are
    planted for digest mismatch, missing schema, invalid payload and invalid
    result. None of it exists today.
    *(g)* **A published contract version is never redefined — it is
    SUCCEEDED.** `messaging.send.v1` is repaired by succession, not by
    rewriting: `messaging.direct.send.v2` (provider-neutral direct delivery
    with a DISCRIMINATED text/template/media content shape),
    `social.comment.reply.v1` (public Facebook/Instagram comment consequences)
    and `social.profile.read.v1` (caller-initiated profile observation through
    REQUEST mode). Sub migrates to the successors; v1 is retained only for a
    bounded compatibility window and then retired, and both the migration and
    the retirement are recorded obligations.
    *(h)* **A capability exposes product MEANING, not provider workflow.**
    `payments.payout.v1` exposes `submit_payout`, a product payout reference,
    exact money, a provider-neutral destination, idempotency and correlation.
    Paystack's recipient creation and Flutterwave's direct-transfer details are
    internal connector steps: a product that orchestrates "create recipient"
    then "send transfer" still needs a code release to change a binding, which
    is the whole thing the binding exists to prevent. The same applies to
    `payments.intent.v1` and `payments.refund.v1` — provider customer creation,
    recipient codes and transfer references are normalized RESULTS or connector
    internals, never separate product-visible provider actions, unless a
    genuinely independent lifecycle is argued rather than assumed.
    *(i)* **A capability that names provider workflow is REMOVED, not
    deprecated.** Applying *(h)*'s test to a shipped id:
    `payments.customer.v1` (`create_customer | update_customer |
    read_customer`, `dotmac-connector-paystack`) has **no independent Dotmac
    business lifecycle** — it is Paystack's `/customer` REST surface with a
    Dotmac id painted on it, and no product decides "create a customer at a
    payment provider" as an act of its own. It is REMOVED from the public
    capability manifest. Instead: the product Customer owner keeps customer
    identity; `payments.intent.v1` carries the required customer EVIDENCE; the
    connector creates or resolves any provider-side customer INTERNALLY; the
    result returns an OPAQUE Integrator correlation where one is needed;
    saved-instrument charging consumes an opaque PAYMENT-METHOD correlation
    (the `authorization_code` the connector already takes), never a provider
    customer code; and customer read/create/update disappear from the manifest.
    No compatibility window, because no product binds it, so *(g)*'s succession
    rule is not engaged. A future product needing genuine, independent
    provider-customer synchronization arrives with its own OWNER, CONSUMER,
    LIFECYCLE and SCHEMA in an accepted record — today's Paystack
    synchronization is not preserved merely because it exists. The code removal
    is part of the payout refactor, gated behind *(f)*'s schema seam and *(h)*'s
    result seam; ADR-0061 A5 holds the artifact-by-artifact list, including the
    fact that `delivery._MISALLOCATED`'s import-time bijection check forces the
    `OPERATIONS` and `ACTIONS_BY_CAPABILITY` deletions into ONE change.
    *(j)* **Treasury owns the PAYMENT INSTRUCTION, and the extraction is
    GATED.** The authorized owner is narrow: `PaymentInstruction`
    (`authorized → submitting → ambiguous | submitted → settled | failed |
    reversed`), grouped by `PaymentRun`, over TWO rails from the beginning — an
    Integrator API rail bindable to Paystack or Flutterwave v4, and a manual
    bank-file rail for AP and payroll. Four invariants carry the weight:
    **exporting a spreadsheet must not mark an instruction paid** (`submitted`
    needs operator submission evidence, `settled` needs Banking's settlement
    observation); **run progress is DERIVED from instruction outcomes and never
    from a batch-level response**, because provider calls are not atomic — ten
    transfers can return seven successes, two failures and one ambiguous
    result; **rail routing is PRE-SUBMISSION only** — the rail is stamped
    immutably at authorization, an ambiguous result reconciles against the
    ORIGINAL provider, and rerouting needs a conclusively unsubmitted or
    terminally failed instruction plus a new authorization, so Paystack ↔
    Flutterwave interchangeability is safe CONFIGURATION and never
    cross-provider retry; and **a provider recipient code is never business
    identity** — Party/People/Supplier owns the payee, Banking or the directory
    owner owns verified bank details, Treasury records an immutable versioned
    `PayoutDestinationSnapshot` at authorization, the Integrator holds the
    provider correlation scoped to `(installation, destination fingerprint)`,
    changing bank details creates a new destination version requiring
    reauthorization, and `create_paystack_recipient` is never a product command.
    **The gate: none of it is built before ERP's `PaymentIntent.status`
    three-writer violation is fixed** — porting a three-writer state into a
    shared module would preserve the defect and give every adopter a copy of
    it. Until then, no `dotmac-treasury` distribution, namespace, `mod_*` short
    code or migration lineage. `BatchTransferService` is not the port source;
    `PaymentRun` derives from the live AP/payroll file process and the
    individual expense-transfer lifecycle.
    *(k)* **An ERP payout claim reads "Implemented and tested; production
    enablement unconfirmed."** Verbatim, wherever such a claim is made. The path
    is gated by `paystack_transfers_enabled`, a `domain_settings` ROW with
    `default=False`, seeded once from the environment and never re-read;
    confirming a deployment's value needs an explicitly named target and rule
    30's `deployment_run` oracle, and **no target has been named**. This blocks
    NO construction — not the gated Treasury module, not the connectors — and
    DOES block every claim of production parity, adoption or retirement, in
    both directions. Relatedly, **`BatchTransferService` is to be DELETED** as
    security-sensitive dead code: an ungated, SoD-free call path to
    `PaystackClient.initiate_transfer` that gets no review attention precisely
    because nothing calls it. Its design intent is preserved, measured, in
    `docs/inventories/treasury-payment-execution-sources.md`, which is the
    condition attached to the deletion.
    *(l)* **A capability that names a BUSINESS ACT is KEPT — and the test is
    the same one clause *(i)* applies.** `payments.refund.v1` survives it where
    `payments.customer.v1` failed, and the two outcomes are the test
    discriminating rather than an inconsistency. The discriminating question:
    **if the provider vanished tomorrow, would the thing still exist and still
    need an owner?** A provider-side customer record would not — it is a
    by-product of a charge. A refund obligation would: someone with authority
    decided money goes back, for how much, against which original payment, with
    its own lifecycle, its own evidence and a receivable/revenue consequence.
    **A provider-side customer record is a by-product of an act; a refund IS the
    act.** So the capability is retained while its provider-shaped OPERATIONS
    are removed: ONE command, `request_refund`, carrying exact money (with
    full-versus-partial DECLARED, never signalled by an absent field), the
    original-payment correlation, the authorization reference and idempotency
    identity — provider handles become connector internals, and refund-status
    reads stay reconciliation internals. **An ambiguous refund is never blindly
    retried**, and the reason is sharper here than for a payout: Paystack's
    `/refund` accepts no client reference, so the connector stamps a derived key
    into `merchant_note` and an ambiguous refund becomes DECIDABLE by reading
    the provider's refund list — but **decidable is not refused**. Nothing at
    the provider stands between a re-request and a second refund except that
    read, so the read is mandatory, no transport ever re-requests, and a
    re-request is a NEW authorized decision by the refund owner. **Treasury is
    NOT automatically the refund owner**: a refund reverses a receivable rather
    than discharging a payable, it is not one of ADR-0063 § 6's twelve closed
    items, and broadening that list requires separate evidence and its own
    record. The decision belongs to Billing or another NAMED refund owner, and
    nothing has named one — "the named refund owner" is the honest phrase until
    something does.
    *(m)* **An ambiguous state is SPLIT before it is extracted, and an unprobed
    row is `ambiguous`.** ERP's `PaymentIntent.status` `PROCESSING` means both
    "the provider call is running" and "a worker has picked this row up";
    carrying it into a shared module under a better name would launder the
    ambiguity into a contract. It becomes `submission_requested` (a durable
    intent, no provider outcome attempted), `submitted` (conclusively accepted),
    `ambiguous` (may have landed, reconciliation required), plus terminal
    `settled` / `failed` / `reversed`. **Worker claim/lease state belongs to the
    execution engine, not to the domain record** (rule 23 / ADR-0014) — a task
    that needed somewhere to record a claim and used a business status column is
    most of why that column has three writers. **The migration rule is the
    important part:** existing `PROCESSING` rows are PROBED, the probe is
    READ-ONLY, the worker is QUIESCED for the duration, and **without conclusive
    provider evidence a row maps to `ambiguous`, never `submitted`.** Assuming
    success on migration is how a double payment or a silently lost disbursement
    enters the new module — a row wrongly marked `submitted` is never looked at
    again, so neither the beneficiary paid twice nor the one not paid at all
    appears in any queue.
    *(n)* **Payroll produces `PaymentInstruction` rows, and Treasury never
    receives a salary component.** Payroll owns calculation, approval and the
    net-pay obligation; Treasury owns disbursement. One authorized net-pay
    obligation produces ONE `PaymentInstruction`; a payroll run MAY group them
    into a `PaymentRun`, which confers no authorization; Treasury's manual rail
    produces the bank-upload artifact; **exporting the file does not mark
    payroll paid**; and settlement evidence returns to Payroll as a TYPED
    OBSERVATION that Payroll's own owner consumes. Treasury receives exactly
    four things — **net amount, currency, payee/destination reference, payroll
    obligation reference** — and **never salary components**: not gross, basic,
    allowances, overtime, bonuses, deductions, tax, pension, loan repayments,
    garnishments, grade or band, nor anything they can be derived from, nor a
    breakdown smuggled into a narration field. **This is a PRIVACY boundary as
    much as an ownership one:** the bank-file rail means the artifact leaves,
    its audience is payments operations rather than HR, and the export is
    retained immutably with its digest — so a component that reaches Treasury is
    archived beyond HR's reach to correct or redact. Relatedly, a payee who
    cannot be paid is a STATE, never an omission from a spreadsheet.
    *(o)* **No payout release or enablement passes the authorization blocker.**
    ERP's module-access scope `finance:access` currently satisfies the guard on
    `POST /transfers/{intent_id}/initiate`, which executes a real transfer;
    `payments:read` is referenced by the old helper but is not normally grantable.
    The
    weakest admitted credential defines a path's real authorization, which makes
    every other control on that path decorative; a dedicated ERP security change
    is implemented on `fix/payout-execute-permission-containment`. Until it
    lands: no payout capability is enabled in any environment, no payout release
    is cut, and no claim of payout readiness is made — however much of the rest
    is finished. This gates RELEASE and ENABLEMENT and is INDEPENDENT of
    ADR-0063 § 7's gate on CONSTRUCTION; satisfying either does not satisfy the
    other, and neither changes clause *(k)*'s evidentiary wording in either
    direction. The ordered dependency it sits inside, canonically ADR-0063 A3:
    (1) ERP execute-permission containment, (2) ERP authorization-log audit on a
    NAMED target, (3) delete dead `BatchTransferService`, (4) reduce
    `PaymentIntent.status` to one writer, (5) split `PROCESSING` from
    `ambiguous`, (6) add capability request/result schemas, (7) build Treasury
    `PaymentInstruction` and `PaymentRun`, (8) add expense, AP and payroll
    producers, (9) complete Paystack and Flutterwave payout bindings, (10) build
    refund through its named owner, (11) provider sandbox proof, CI and cutover.
    Steps 1–3 come first because they reduce blast radius and depend on no
    design decision; step 4's digest/version work may continue in parallel.
    (ADR-0061 + its THREE 2026-08-24 amendment sets; ADR-0062; ADR-0063 + its
    2026-08-24 amendment; ADR-0046 Amendment A1;
    ADR-0042 § 3 + ADR-0047 Amendment A1 — ADR-0042 CONTROLS on disbursement
    ownership, and the split is six owners: Expenses eligibility, Payables what
    is owed, Treasury the authorized instruction and its rail, the Integrator
    authentication/transport/evidence, Banking cash observation and
    reconciliation, Accounting journal consequences; ADR-0024 §§ 8–12)

29. **Poetry is an exact build input, not a workstation preference.**
    `[tool.poetry].requires-poetry` is the ONE version source; CI's hash-locked
    bootstrap, the lockfile generator stamp and the production Docker build
    must equal it exactly. A local command running another Poetry version fails
    before it may inspect or rewrite the lock. Validate the COMMITTED lock with
    `poetry check --lock`/`poetry install`; never run `poetry lock` inside a
    validation lane, because that proves repaired state rather than the commit.
    A dependency change and its lock change are one commit. Use ordinary
    `poetry lock` with the pinned tool and review the diff; `--regenerate` is
    reserved for an explicit dependency-upgrade slice. Root-lock validation is
    supplemented by the bidirectional path-package guard because Poetry does
    not re-read nested package metadata for `poetry check --lock`.
    (`scripts/check_poetry_toolchain.py`; `make poetry-lock-check`;
    `tests/architecture/test_poetry_toolchain_contract.py`;
    `tests/architecture/test_lockfile_path_packages.py`)

30. **A repository-local claim comes from repository-local facts; a release,
    registry or production-adoption claim needs an authoritative external
    oracle.** Accepted fleet-wide as `dotmac_governance` ADR 0013 (merge
    `2d711cd594979ba0bc368382b7f5ea69bf21eaa4`, effective 2026-08-22). A
    version existing in `pyproject.toml`, on `main`, or in a CHANGELOG is not
    evidence that it is published, installable or pinnable. Four typed oracles,
    each carrying immutable coordinates: `release_run` (the run that published →
    installed back from the private index → registered → tagged), `peeled_tag`
    (the tag's PEELED commit, never the annotated tag object's SHA),
    `deployment_run` (run, commit, image digest, explicitly named target) and
    `adoption_evidence` (dossier repository, exact commit, path, field). A
    branch name, "current `main`", "latest", an unpeeled tag, a run without its
    id, or an image by tag rather than digest are not coordinates. A positive
    oracle-backed claim is permanent; an ABSENCE is a moment, so record it
    either as an as-of observation with a NAMED refresh owner, or replace it
    with a repository-local positive fact — prefer the second.
    **Enforcement is deliberately narrow.** It is automated only where a
    machine-readable contract already carries a declared oracle: every declared
    distribution is measured against its real tag, and a declared-unpublished
    one must carry a recorded reason that is removed in the SAME change as its
    release. The reason must be WRITTEN: a row whose reason is missing, empty
    or still the generator's own placeholder fails `--check`, because `reason`
    is the only field separating accepted debt from unnoticed drift and a
    ledger regenerated after a rebase emits that placeholder by design. Everywhere else this is stated review discipline, NOT a guard —
    ADR 0013 rejects a generic prose scanner, which cannot separate a claim
    from a description of one and would flag its own incident recital. Saying
    so is the point: an unmonitored region is honest, an implied guard is not
    (ADR-0018). The known-bad case any future automation must fail on is
    `AWAITING_RELEASE_TAG` in `dotmac_vendor_control_plane`, which was NAMED
    for a release tag, read only `pyproject.toml`, and stayed green after the
    tag was published.
    (`scripts/declared_publication_sweep.py`;
    `tests/architecture/test_declared_publication.py`)

31. **Package publication is machine-authorized; production deployment is
    not.** `registry-release` and `pypi-release` are secret and branch-policy
    boundaries, not human-review queues: they allow `main` only and have zero
    required reviewers and zero wait timer. Publication authority is the
    conjunction of protected `main`, every required CI check, a closed release
    allowlist, an explicit version equal to package metadata, build-once
    artifact inspection, and `assert_current_main.sh` immediately before the
    first irreversible registry write. Publish and install-back verification
    proceed without a second human gesture; verification still precedes the
    tag. The generated release-record pull request enables auto-merge and may
    merge only after the protected branch's complete required-check set is
    green.

    An `environment:` declaration remains mandatory on jobs that read release
    credentials, but it must not be described as evidence of human approval.
    GitHub environment protection is mutable external state, so a release
    captain reads back the zero-reviewer, zero-wait, `main`-only policy after a
    settings change and whenever an unexpected wait occurs. The checked-in
    contract is `.github/release-environments.json`; repository tests check its
    shape and workflow coverage, not GitHub's live settings.

    This automation applies only to package publication and its mechanical Git
    bookkeeping. A production deployment remains human-gated unless its owning
    product adopts a separate dated architecture decision with equivalent
    deployment-specific controls. An agent still stops at any protected
    production approval gate and hands the real gate to its named reviewer.

    The retired publication-approval control and its historical attribution
    exceptions remain recorded in `docs/CONTROL_EXCEPTIONS.md`.

32. **A release holds a short, named freeze.** `publish` re-asserts that the
    run's SHA is still the tip of protected `main` immediately before the
    irreversible write. Any merge between dispatch and that check voids the
    run. One release captain holds every merge except the generated release
    record from dispatch through verification, tagging, the record pull
    request's automatic green merge, and verification that protected `main`
    contains the truthful record and is green. The captain announces both ends
    of the window. A tag is not the closing event: it is the instant the
    checked-in publication baseline becomes false.

    This is a real control, not ceremony: the first a91 attempt was voided
    mid-flight by a merge landing before publication, and it stopped BEFORE
    publication. Keep the check; automated publication makes the race window
    short but does not make it zero. If record automation fails after the tag,
    the freeze stays open while the already-pushed branch is repaired and
    merged; publication is never re-run to repair bookkeeping.

    The record branch push and pull request use one dedicated recorder App,
    not the publisher's persisted checkout credential. GitHub's required
    pull-request-write permission also reaches the review API, so do not claim
    the token is review-incapable. Enforce the real separation instead: the App
    authors and last-pushes its PR and enables squash auto-merge; protected
    `main` requires the complete strict CI set and permits no bypass. The App
    receives contents and pull-request write only — never Actions, deployment,
    environment or administration authority. The tagging job's ordinary
    workflow token has exactly `contents: write`, never pull-request write; the
    loud fallback can push the truthful record branch but cannot become a
    second automatic PR identity if a repository setting changes.
    (`scripts/assert_current_main.sh`)

33. **A writer claim is TYPED and COMPLETE.**
    `[[product_writers]]` in a dossier states, per product, whether it is the
    `qualifying_source`, a `legacy_writer` that must stop, a `no_writer`, or
    `inventory_only` — with an immutable revision and evidence paths. Governance
    cites these across the repository boundary, and two rationales were once
    contradicted by the dossiers they described because the cited claim was
    prose.

    Silence still means UNKNOWN rather than `no_writer`, but UNKNOWN is no
    longer admissible in a checked-in dossier: every product named by
    `source_repositories` except this Starter repository has exactly one typed
    row. The row's immutable `revision` equals that product's exactly one
    effective audit coordinate — `revalidation_revisions` when the dossier has
    re-audited that product, otherwise `source_revisions` — so prose cannot be
    refreshed while the typed claim silently continues to describe another
    tree. `source_revisions` is historical provenance and is never rewritten to
    a later tree; a later verified coordinate is added under
    `revalidation_revisions`. The transitional
    prose-only baseline was deleted when every dossier reached complete typed
    coverage on 2026-08-23; recreating a baseline would weaken the absolute
    rule back into an exemption.

    Retire a pair by READING the source product and recording what you found.
    Never by inferring a state from the prose already there — a scanner
    guessing `no_writer` from a sentence manufactures the false confidence this
    exists to remove.
    (`scripts/product_writer_check.py`; `make product-writer-check`;
    `tests/architecture/test_product_writer_completeness.py`)

34. **A PUBLISHED version's manifest is its contract, and a contract does not
    move.** An installation adopts a connector by MANIFEST DIGEST: `mod_intg`
    stores the digest a binding was enabled against and
    `accepts_manifest_digest` decides adoptability from it. So the manifest of a
    version that has a tag is FROZEN. Adding a capability, a mode mapping, a
    secret binding, an egress host or an SPI floor to an already-published
    version is not an edit — it makes one version name two contracts, and every
    installation adopted against the old digest becomes unidentifiable while
    `accepts_manifest_digest` reports the pin as unknown.

    The repair is a NEW version whose `historical_manifests` carries the exact
    published manifest, never an edit of the published one and never a version
    edited down to match. Two manifests sharing one version STRING is the worse
    shape, not the safe one: `accepts_manifest_digest` accepts both, so nothing
    can see the collision — `dotmac-connector-flutterwave` and
    `dotmac-connector-remita` each shipped exactly that, green on every gate,
    because the version-identity guard compares three version SURFACES and the
    publication sweep compares a version to a TAG, and neither reads a manifest.

    `docs/inventories/released-manifest-digests.json` records, per published
    tag, the peeled commit, the release run where the repository can still name
    it, and the digest that tag published. Two halves, either alone defeatable:
    `make manifest-digest-check` compares the ledger with the tree — offline,
    tag-free, in the cheap CI matrix — and the architecture test re-derives every
    recorded digest from the source THAT TAG published, so doctoring the ledger
    requires moving a tag on `origin`. Both directions fail (ADR-0018): a
    published tag with no row, and a row whose tag does not exist or peels
    elsewhere. Rows only GROW — a publication is a permanent positive fact
    (rule 30), unlike the publication baseline's absences.

    Scope is the connector lane. Installable modules are UNMONITORED rather than
    exempt: `ModuleManifest` exposes no digest and nothing adopts a module by
    one — their published bytes are held by rule 14's released-migration map
    instead. (`scripts/released_manifest_sweep.py`;
    `tests/architecture/test_released_manifest_digests.py`)

35. **A row mutation counter is not semantic content identity.** A generic
    `version`/`updated_at` may order mutations or guard optimistic concurrency;
    it does not say which consumer-relevant evidence changed. It therefore may
    not, by itself, become a semantic `source_version`, idempotency/dedup key,
    event-content identity, observation fingerprint or strong ETag. Carry an
    explicit revision/sequence and an algorithm-versioned fingerprint when both
    are needed. The fingerprint binds the COMPLETE normalized decision evidence
    including provenance even when the answer is unchanged; length-prefix its
    fields, canonicalize unordered collections, encode finite money exactly at
    currency scale, distinguish absence with a typed sentinel, and namespace
    the algorithm (`cv1:`, `cv2:`). Changing the field set is a CUTOVER: stored
    submissions replay their stored bytes/version and new submissions use the
    new algorithm; historical facts are never silently rehashed into duplicate
    evidence. A counter may back a weak ETag only when "any accepted mutation"
    is the declared, enforced and sensitivity-tested contract (ADR-0064;
    `tests/architecture/test_semantic_identity_and_replay.py`).

36. **Exact replay precedes mutable-state validation, after trust and request
    validation.** The order is authentication/authorization and scope isolation
    → command/key canonicalization and fingerprint comparison → exact stored
    replay or key-reuse conflict → mutable overlap/uniqueness/availability
    preconditions → new effect and idempotency row in one transaction. A retry
    must not fail its own "already open" guard against the state it created, but
    replay never bypasses authorization, tenant scope, parsing or fingerprint
    conflict. A replay test builds ONE command once and submits it twice; a
    helper that previews and rebuilds the command is testing preflight again,
    not replay (ADR-0014 amendment 2026-08-25;
    `tests/architecture/test_semantic_identity_and_replay.py`;
    `tests/unit/test_subscriptions_treatments.py`).

37. **A caller that cannot deploy atomically with its destination binds to a
    PINNED published contract, and the binding must be able to FAIL.** Scope is
    the rule, not a summary of it: this binds independently released or
    asynchronous callers — a shipped mobile artifact, a connector on its own
    cadence, a scheduled job in another repository, an outbound event sender. It
    is NOT a blanket rule for every caller; one that ships in the same artifact,
    same deploy, same build as its destination already has parity by
    construction. The hazard is that the two sides are on different clocks, so
    some deployed caller is always running against a destination it was never
    built against while each side's own tests stay green. Bind to a published
    version with immutable coordinates — never "the current API", a branch name,
    or whatever `main` serves. **Non-vacuity is the half that actually failed in
    all three fleet instances:** the test exercises the REAL caller shape rather
    than a fixture the caller authored, checks the contract's IDENTITY rather
    than its presence, makes a sender prove a RECEIVER (delivery success is a
    transport fact, not caller-path evidence), and compares vocabulary ACROSS
    the wire rather than round-tripping one side's own spelling. Evidence:
    the vendor-auth 404 outage (Sub PR #2722), CRM's four dead webhook senders,
    and the `on_break`/`work_order_id` field-mobile drift — the client
    serializes `'break'` while Sub's enum and DB `CHECK` declare `'on_break'`.
    A caller path with no such check is an UNMONITORED region and is recorded as
    one (ADR-0018), never described as covered.
    (ADR-0024 amendment 2026-08-26 § 13; enforcement: **none yet** — no guard in
    this repository reads a caller tree in another repository)

38. **A client that persists a REFRESHABLE BEARER CREDENTIAL tears down
    atomically.** Scope is the rule, not a summary of it: this binds clients that
    hold such a credential — a native application, a device agent, a daemon, a
    token-caching CLI, a worker holding a service credential. It does NOT bind an
    ordinary server-side or browser cookie session, where the server owns the
    record, teardown is a row deletion in one transaction, and the client holds
    nothing it can fail to delete. Four invariants: (1) **the credential record is
    ATOMIC** — credential, principal, scope, generation and expiry written and
    destroyed as ONE record, never several keys in sequence, because a process
    killed between two writes leaves a state no reader has a correct branch for;
    (2) **generation fencing with a DURABLE half** — the held generation is
    persisted beside the credential and compared on COLD START, since a fence
    living only in process memory is defeated by the most ordinary event on a
    device; (3) **ONE wipe coordinator, no subset clears** — participants are
    registered rather than discovered, no component clears its own storage on its
    own initiative, and the wipe is journalled and resumable (marker first,
    credentials second, failures collected, marker cleared only on full success,
    a marker found at start-up blocks the client); (4) **transport failure is NOT
    revocation** — a timeout, connection failure, DNS failure or 5xx ends
    nothing; only a 401/403 on the REFRESH EXCHANGE ITSELF or an observed
    generation bump does, and a failed *restore* is not a failed
    *authentication*. Evidence: Sub PR #2717.
    (ADR-0067; ADR-0065 §§ 3, 7, 8 are its mobile expression, not a second owner;
    enforcement: **none yet** in this repository — every in-scope client in the
    fleet is a Flutter application and this Python repository cannot run a check
    over any of them)

39. **Every signed release pipeline verifies the PRODUCED ARTIFACT's application
    identity and its actual signing certificate — not secret or file existence.**
    Read the Android `applicationId` / iOS `CFBundleIdentifier` from the built
    output rather than from a source file, a Gradle property or a workflow input,
    because a pipeline that builds the WRONG application from correct
    configuration is exactly what a source-side check cannot see. Inspect the
    issuer, subject and fingerprint of the certificate that actually signed the
    artifact and compare them to an expected value; "a signing secret was present
    in the environment" and "a file was produced" are preconditions, not results.
    The check carries rule 25's sensitivity proof — shown RED against a
    deliberately debug-signed or wrongly-identified artifact. **And a step is
    renamed if it does not test the property it is named for**, because a guard
    named for a property it does not test converts an unmonitored region into one
    everyone believes is covered, which is worse than no guard at all. Evidence:
    `dotmac_sub/.github/workflows/mobile-release.yml` step *"Verify the artifact
    is not debug-signed"* was `test -n "$OUT"` — it asserted only that `find`
    matched a filename, and would have passed on a debug-signed bundle and on a
    correctly signed bundle of the wrong application; Sub PR #2716 replaces it
    with real certificate inspection.
    (ADR-0018 amendment 2026-08-26; enforcement: **none yet** in this repository —
    the pipeline this governs lives in `dotmac_sub`)

40. **An ADR number is one claim in the merged catalogue.** A number written on
    a branch is not a reservation: the first decision to reach `main` keeps it,
    and a later decision renumbers before merge regardless of when its source
    commit was authored. Every `docs/adr/<number>-*.md` filename has a unique
    four-digit number. Renumbering updates citations by meaning, never with a
    catalogue-wide text replacement, because one ambiguous number can already
    have inbound references to both decisions. The gate is rerun against the
    current merge result after the base moves; a green stale branch cannot see a
    sibling claim that landed later.
    (`tests/architecture/test_adr_numbering.py`)

41. **Deployment is a stateless versioned FACILITY, and a product declares one
    descriptor.** `dotmac-deployment-foundation` is classified
    `universal-facility`: no `ModuleManifest`, no models, no migrations, no
    lineage, no tenant, and ZERO runtime dependencies — not the kernel, not
    SQLAlchemy, not FastAPI, not Jinja, not a YAML library. A build runner that
    renders a Compose file has no database and no web framework and must not
    acquire them to validate a descriptor; that is `dotmac-ui`'s shape, held for
    the same reason. Two import-linter contracts hold it in both directions, and
    the classification guard carries planted-defect proofs for each property.

    A product owns exactly one deployment artifact, `deploy/product.toml`
    (`ProductDeploymentSpec.v1`), holding material NAMES and approved pointers
    and never a secret value (ADR-0009, refused at PARSE time). Every other
    deployment asset is RENDERED from it, and `render --check` is a byte
    comparison a product's own CI runs — so a hand-edited Compose file fails
    review rather than a host at 3am. Variation enters through the typed
    descriptor or a declared extension point; `if product == "erp"` in the
    shared facility is refused by an AST guard.

    The boundary, in four lines: the KERNEL owns in-process contracts and
    mechanics; the FOUNDATION owns build- and deploy-time execution for one
    release on one host; `dotmac-deployment-control` owns durable fleet intent —
    desired state, plans, approvals, rollouts, acknowledgements, drift — and
    gains no Docker, Nginx, SSH, cloud, migration, backup or monitoring
    implementation; the ASSEMBLY owns declarative product input only.
    `dotmac-platform-health` may own normalized health observations; it owns no
    raw signal and no deployment decision. Nginx is the first dedicated-VM
    ingress PROVIDER and decides no tenant, domain, TLS or business lifecycle;
    dynamic customer domains need a domain/DNS/TLS reconciler and are out of its
    scope.

    Three refusals are load-bearing and are not preferences. A
    `maintenance_required` release may not take the online path, because that
    path leaves the previous image querying a schema it cannot read. An image
    rollback is permitted only when the release's own compatibility declaration
    permits it, and a migration is NEVER automatically downgraded. And a backup
    is `COMPLETED`, `VERIFIED`, `RESTORABLE` or `PROVED` — only the last supports
    a recovery claim. `set -euo pipefail` already makes a failing `pg_dump` fail
    the backup in all three products, so COMPLETED is genuinely established;
    what none of them establish is anything after it — no checksum is recorded
    at write time, nothing decompresses the archive, and no product has ever
    restored one.
    (ADR-0070; `tests/architecture/test_deployment_foundation_facility.py`,
    `tests/unit/test_deployment_foundation_failure_injection.py`;
    `docs/inventories/deployment-foundation-sources.md` for the eighteen defects
    deliberately NOT extracted)

42. **A human credential lifecycle has ONE owner, and provisioning cannot be
    handed material.** `dotmac_kernel.credential_lifecycle` owns provisioning,
    verification, individually authorized reset completion and approved cohort
    force reset for HUMAN password credentials. It is stateless: five typed
    product ports, every database effect in the CALLER's transaction, no
    session, no ORM, no HTTP status, no provider client and no network import.
    Machine credentials (`machine_auth`), federated identity (`external_identity`)
    and DEVICE/SERVICE credentials (`AccessCredential`, `SnmpCredential`) are out
    of scope — a sweep keyed on `*Credential` hands the owner responsibilities it
    must not have.

    Four properties, each structural rather than procedural. **Verification
    returns a typed verdict** (`accepted`, `reset_required`, `invalid`, `locked`,
    `disabled`), never a boolean and never a session: a boolean forces every
    caller to re-derive what it cannot carry, which is why `dotmac_sub` has FOUR
    verification owners. **Provisioning has no parameter a secret can arrive
    through and no field one can leave through** — Sub's
    `reseller_onboarding._create_credential` took a caller-supplied `password` no
    supported caller passed, and that unused parameter is how one value reached
    24 external organisations; removal is absence, an unrepresentable shape is
    the fix. **Generated material reaches no return type, log, exception, `repr`,
    receipt or audit row**; the subject recovers through a durable intent and the
    product's channel. **A cohort force reset is product security authority** —
    `dotmac-deployment-control` must not authorize an account mutation; the plan
    carries a typed `CredentialResetPlanDigestV1` owned by this module (not a
    universal digest, not Control's), sorts targets canonically, refuses empty,
    duplicate, malformed, stale and changed cohorts, applies all targets or none,
    and its separate authorization carries `approval_decision_ref` and no
    `approved_by`.

    Direct calls to `hash_password`/`verify_password`/`password_needs_rehash`
    outside the two owner files are FROZEN DEBT, measured by call graph across
    every Python entry-point family (`app`, `packages`, `src`, `scripts`/`bin`,
    `alembic`/`migrations`, `tasks`, `workers`/`jobs`, `cli`, `cron`, and
    repository-root modules — two of Sub's eleven `hash_password` callers are
    seed scripts) in four repositories at immutable commits, and ratcheted
    two-directionally. A repository that cannot be measured at its recorded
    commit ABSTAINS; it is never scored zero. Retiring a caller lowers the
    baseline in the SAME change. (`AGENTS.md` rule 25's ratchet shape applied to
    credentials; ADR-0006 amendment 2026-08-30;
    `tests/architecture/test_credential_lifecycle_ratchet.py`,
    `tests/unit/test_credential_lifecycle.py`,
    `scripts/credential_lifecycle_sweep.py`;
    `docs/inventories/credential-lifecycle-sources.md` for the census, the
    departures from Sub, and the local-copy retirement gate)

43. **A database is restorable only from a bundle carrying its ROLE CLOSURE, and
    a database-only dump is a data export, not a backup.** `pg_dump --dbname`
    captures GRANTs and RLS policies and never captures the roles they name. The
    measured consequence: a `pg_restore` of Vendor CP's newest production backup
    into a disposable PostgreSQL 16 container exited 1 with 114 missing-role
    errors (`app_admin` 56, `platform_api` 34, `app_user` 20, `outbox_dispatcher`
    2, `platform_outbox_dispatcher` 2) from a TOC holding 55 ACL entries, 26
    POLICY entries and ZERO role objects — and LEFT 45 tables, 23 of 26 policies
    and 16 RLS-enabled tables behind. Under rule 27 / ADR-0023 the revocation IS
    the plane isolation, so an operator checking `pg_policies` after that restore
    sees the control and does not have it.

    A `PostgresRecoveryBundleV1` is therefore immutable and CONTAINING: the
    custom-format dump, the role and membership closure DERIVED FROM THE SOURCE
    CATALOG (not from any declaration), role attributes and PostgreSQL 16
    per-membership `INHERIT` state, object ownership, default/schema/object
    privileges, row- and column-level ACL evidence, RLS ENABLE *and* FORCE,
    extensions and versions, an explicit tablespace decision (`none` is a
    decision; silence is not), migration heads, and a canonical manifest whose
    per-component digest states what it covers. **No passwords, no password
    hashes, no superusers, no secret values** — `RoleFact` has no field one
    could be written into, and login material is installed afterwards from the
    product's approved secret source. `pg_dumpall --globals-only` is refused as
    written because it emits SCRAM verifiers; role capture uses
    `--no-role-passwords`.

    Products declare typed database roles, expected schemas, migration heads and
    isolation invariants in `[database]`. **A declaration is a claim, never a
    source**: nothing turns it into role DDL, because a validator that can
    manufacture the role it is checking for can always make its own check pass.
    Isolation is proven against EFFECTIVE privilege (`has_table_privilege` OR
    `has_any_column_privilege`, all seven table privileges) — never
    `information_schema.table_privileges`, which sees only direct grants and
    reports "fully revoked" for a role holding the privilege through PUBLIC,
    through an inherited membership, or on a column.

    Restore is ten ordered steps: fresh isolated target at the declared major;
    roles from the bundle ONLY; objects, ownership, ACLs, policies, data;
    **refuse any non-zero restore and DESTROY the partial target** (a wrapper
    checking only the exit status reports a clean failure and leaves the trap);
    login material afterwards; prove the catalog; prove tenant roles cannot reach
    platform tables; prove the required revocations; start the EXACT product
    image and pass readiness as the REAL application roles; emit a value-free
    receipt carrying the restore WALL CLOCK (a bundle proved at twenty minutes
    and one proved at six hours are both PROVED and are different facts).

    A rehearsal is also a DRIFT DETECTOR. A restored copy violating a declared
    invariant was either restored unfaithfully or restored faithfully from a
    production database that is already wrong; comparing it against the SOURCE
    catalogue separates them (`RESTORE DEFECT` vs `SOURCE DRIFT`) and is nearly
    free because the verification holds both. Both still fail the proof - the
    label changes where the operator looks, never whether the receipt is PROVED.
    Counts are recorded as OBSERVATIONS and gated on by nothing: a grant matrix
    changes with every migration, so the gate is the property, not the total.

    Retention always preserves the newest PROVED bundle regardless of age, and
    keeps an existing `data_export` until that product has a newer PROVED bundle
    — a policy able to delete the only thing that ever worked is not a retention
    policy. Every mutation is proven failing: remove a role, a membership, an
    inheritance flag, an ownership assignment, a default privilege; lose the
    platform revocation while policies remain; let the validator manufacture a
    role; and supply a database-only dump — the last catching a plausible WHOLE
    rather than a missing piece, which is the shape that actually fools an
    operator (ADR-0071;
    `tests/unit/test_deployment_foundation_recovery_bundle.py`)

44. **A bootstrap candidate is built once, preserved by digest, and published as
    the SAME BYTES — never rebuilt.** `release-facility.yml` makes a passing
    Lane 3 rehearsal a pre-publication gate after it has fetched and verified
    the already-built candidate; it never builds a replacement. That closes a
    loop for a bootstrap: Lane 3 needs a live issuer → the issuer
    needs a proved restore → the restore proof needs the candidate wheel → the
    candidate wheel needs Lane 3. `foundation-candidate.yml` breaks it by
    building the candidate once from merged protected main and preserving it
    WITHOUT publishing or tagging.

    **Lane 3 executes the candidate bytes, never the checkout beside them.**
    The rehearsal resolves repository, run, artifact and digest only from the
    committed `CandidateArtifact.v1`, fetches and verifies both recorded
    distribution files, installs the wheel into an isolated environment, and
    drives `exposure_rehearsal_runner.py` with that interpreter. The publication
    oracle parses the resulting receipt with the same installed wheel. A
    dispatch-provided artifact digest or a `sys.path` insertion into
    `packages/dotmac-deployment-foundation/src` would attest checkout behaviour
    while publishing different bytes, so both are refused. The rehearsal runs
    in the organization execution repository pinned by
    `.github/lane3-execution.json` (ADR-0070, amendment 2026-10-05). The
    protected-main oracle is the Starter revision that run's launcher checked
    out:
    - it is named in the run's title, in the shared dispatch grammar;
    - it is recorded in the receipt;
    - `verify_publication` compares it with the release revision.

    The oracle reads a `RehearsalReceipt.v2` from exactly the run it selected.
    `require_execution_run` binds the receipt to that run, and the artifact
    digest binds it, through the committed candidate record, to the bytes it
    executed. While that file records no admitted surface, publication refuses.
    (`tests/architecture/test_lane3_candidate_artifact_execution.py`;
    `tests/architecture/test_lane3_execution_oracle.py`)

    **The lane is incapable of publishing, not merely not asked to.** Publish
    authority here rests on exactly two declarations: `environment:` (the
    credential boundary) and `permissions: contents: write` (the tag
    capability). The candidate lane declares neither — only `contents: read`
    and `actions: read`, the latter REQUIRED because recording the artifact id
    and the real expiry calls the artifacts API. A lane that could publish but
    currently does not is one edit away from being a second publisher, so the
    absence is asserted structurally with planted `environment`,
    `contents: write`, `packages: write`, `id-token: write`, tag-, publish- and
    `pull_request`-trigger mutations, each observed turning the guard red, plus
    a conforming synthetic case that must stay green.

    **Six facts, or the bytes are not re-fetchable**: source SHA, run ID,
    artifact ID, filename, size and SHA-256 (`CandidateArtifact.v1`). A digest
    alone verifies bytes somebody hands you; it does not let you obtain them.
    A run ID alone does not say which bytes came out. `expires_at` is READ BACK
    from the API, never inferred from the requested `retention-days` — a
    repository or org cap silently lowers it and the difference is invisible
    until the bytes are gone. 90 days is the MAXIMUM for this public repository
    (`maximum_allowed_days: 90`), not a preference.

    Consumers address an exact run / artifact / digest, **never "latest"**, and
    bootstrap refuses to START with under 30 days remaining — a precondition to
    check, not a fact to assume, because bootstrap spans a restore proof, an
    issuer stand-up and a full Lane 3 rehearsal.

    **If the artifact expires or becomes unavailable, invalidate every dependent
    receipt and restart bootstrap with a new candidate digest. Rebuilding and
    claiming continuity is FORBIDDEN.** This is the easiest constraint in the
    sequence to violate under pressure: at the point it bites, a rebuild looks
    identical, costs minutes and is wrong — every downstream receipt names the
    candidate's digest, so re-deriving matching bytes is a claim, not a proof.
    Each dependent receipt carries the `artifact_id` and digest as named fields
    so invalidation is a query rather than a recollection. Invalidation is
    RECORDED, and it is recorded beside the receipt rather than inside it — see
    rule 48 for `CandidateDisposition.v1` and the guard that refuses a bound
    version
    (`scripts/foundation_candidate.py check|verify`;
    `tests/architecture/test_candidate_lane_cannot_publish.py`)

45. **A displaced deployment executor retires on PROVED evidence, never on
    adoption — and it is never one script.** ERP is a `contract_consumer` of
    `dotmac-deployment-foundation` and its 486-line `scripts/deploy.sh` is
    retired no sooner for it: a facility adopted as declarative input and a CI
    gate has proven nothing about its ability to replace an executor. The
    programme scoreboard is `retired_total`, it is committed, and only a receipt
    moves it.

    Two opposite failures bracket the removal — deleting the script early takes
    the rollback path with it; leaving it active creates a second deployment
    authority nobody watches. The rule between them is that **a replacement is
    not adopted while the displaced executor can still act normally**, expressed
    as one absent edge in a state machine: `active_executor` may become
    `frozen` and nothing else. It has no path to `displaced` or `retired`.

    A product declares one `ExecutorInventory.v1` over SEVEN entry-point
    families — `workflow`, `script`, `cron`, `systemd_unit`, `ssh_credential`,
    `webhook`, `manual_runbook` — each entrypoint carrying a family, trigger,
    credential IDENTITY and disposition. **Absence is never a disposition**: an
    artifact discovered in the tree and not declared fails, and a family omitted
    from the inventory is refused. Four families cannot be walked at all, and an
    absence in one of them needs an observer, a time, a method and a SCOPE —
    `repository_tree` says nothing about any host, `host_observed` names the
    host. Conflating those is how `dotmac-books.service` sat installed and
    disabled on a production host. A product with no inventory is UNADOPTED,
    never zero.

    Reviewed verdicts carry premises the checker REFUSES: `not_an_executor` over
    an artifact commanding a deployment verb — resolved TRANSITIVELY, because a
    dispatch-only caller reads as inert on its own bytes — and
    `non_production_executor` over one naming a declared production target.
    Ratchets are two-directional per product, family and DISPOSITION (a total
    hides `active_executor` becoming `frozen`), plus `unadopted` and
    `retired_total`, which rises only with a receipt and may not fall at all.
    Every family carries its own planted violation, with at least one proof in
    situ over the real tree.

    The removal writes an `ExecutorRetirementReceipt.v1` that can FAIL: the
    subject and the census digest it was `displaced` in; TWO successful
    controller cycles as distinct runs (one proves the replacement can deploy;
    only the second proves it can deploy again over its own previous state);
    every removal by class INCLUDING the credential, because a live credential
    is a second executor waiting for whoever holds it; the zero-surface guard
    with its sensitivity proof; a PROVED recovery verdict with an exercise
    coordinate, never "rollback is documented"; what was deliberately retained;
    and a digest. Value-free, absence is not a status, corrections by
    supersession. Products own their receipts; Governance owns the
    cross-repository envelope and there is no registry here.

    **Amended 2026-08-31 — an executor with no invoker, and the negative half.**
    An EIGHTH family, `runtime_reactivation` and deliberately NOT
    `restart_policy`: `restart: unless-stopped` normally restarts THE SAME
    CONTAINER, which is no deployment, so naming the family after the policy
    would describe the wrong thing and fire on every benign case. The executor
    property is narrower — **it can reactivate a displaced executor after
    reboot** — which reframes what a retirement owes: not "the artifact is
    gone" but **"the executor cannot autonomously return"**. A row carries
    `reactivates`, checked in BOTH directions, and the receipt gains
    `no_autonomous_return` (typed method, observer, host, mechanisms with their
    disposition after) that must account for every row naming the subject.

    And `DisplacementWindow.v1`, because two positive controller cycles never
    proved the negative: a quiet window is **the claim under test, not evidence
    for it**, so `poll`, `periodic_snapshot` and `quiet_window` are NAMED and
    REFUSED as event sources. The window enumerates every runtime change and
    attributes each to a controller receipt or a typed non-deployment cause —
    **zero unattributed**, because a change nobody can account for is a third
    executor that a zero-invocation guard passes straight over. Bounded with
    exact start/end runtime identities; CHAINED, so a missed transition leaves a
    break and completeness is tested rather than declared; a non-deployment
    cause whose image identity MOVED is refused, which is how the benign restart
    is proven rather than believed; and `cannot_establish` forces the verdict
    `UNMONITORED`, never a pass with a caveat — this rule's own guard gets no
    exemption from rule 25. Both cited cycles must appear inside the window.
    Sensitivity requires BOTH halves observed: the planted third-executor change
    refused, and the properly attributed window admitted, against the same
    reach. Whole-line comments are stripped before verb detection and edge
    resolution — calls, not mentions.

    **Amended 2026-08-31 (v3) — a key is CHARACTERISED, not counted.** Every
    `ssh_credential` row carries an `SshCredentialConstraintV1`: fingerprint,
    principal, the exact source restriction, the forced-command DIGEST (never
    the string — a near-match gets waved through), `restrict`, and each of PTY,
    agent, port and X11 explicitly `denied` or `permitted`, plus the
    host-observed evidence coordinate. A row without one is refused; an
    unrestricted key must SAY `unrestricted` rather than leave a blank that
    reads as "nobody looked"; `restrict = present` beside any `permitted` is
    refused because such a key cannot exist. The constraint is part of the
    census digest, so LOOSENING a key moves it.

    The substantive rule, and it lives here rather than in a hardening document
    because THIS MODEL RETAINS THE LEGACY EXECUTOR'S BYTES — so a rollback
    credential survives every retirement, and a retained key that can open an
    interactive shell is not a rollback path but the executor still reachable by
    hand. A `retained_rollback` key must be SOURCE-RESTRICTED,
    FORCED-COMMAND-ONLY and INCAPABLE OF AN INTERACTIVE SHELL, each checked
    INDEPENDENTLY: `restrict`, `from=` and `command=` are planted and refused
    separately, because a detector that fires only when everything is wrong
    passes the realistic failure of one protection quietly dropped. A fully
    constrained key is admitted at the same reach. `principal` is recorded and
    does not relax the gate. Deliberately narrow: the gate bites on
    `retained_rollback` only — live unrestricted keys are `active_executor` debt
    the ratchet counts, because the census records reality while the gate guards
    the retention this contract itself creates.

    **Amended 2026-09-01 — the conjunction is three, and the coordinate is
    one of the properties.** INCAPABLE OF AN INTERACTIVE SHELL is `restrict` AND a
    forced command AND NO PTY. The pty is its own named refusal rather than
    borrowed from the parse-time `restrict` implication: a gate must not take
    one of its own conditions from another function's invariant, or it goes on
    passing with a third of that conjunction quietly dead. A key holding two of
    the three is not two-thirds safe. OpenSSH's grammar makes a pty-ONLY plant
    UNCONSTRUCTIBLE (`restrict = present` forbids `pty = permitted` at parse),
    and the contract says so rather than manufacturing one — the clause is
    observed by holding `restrict` at `absent` and moving only the pty, taking
    the finding set from one to two. The three plants Michael named stay three:
    each produces exactly ONE finding and the three messages are asserted
    DISTINCT, since three findings all reading "unsafe" would satisfy three
    tests while enforcing one property.

    THE EVIDENCE COORDINATE IS PART OF THE PROPERTY, not metadata beside it.
    Every clause is a claim about a host; read from a checkout it is a claim
    about a checkout. `evidence_scope` is typed in the SAME vocabulary as a
    family absence and DERIVED from `ABSENCE_SCOPES` rather than re-declared —
    the census may hold a `repository_tree` characterisation, the gate requires
    `host_observed`, on the host the ROW names. A coordinate that points at
    nothing is refused at parse (`unknown`, `n/a`, `tbd`, `assumed`, …), because
    a required field satisfied by a filler is worse than a missing one: it reads
    as an answer. `observed_at` must be an ISO date, since a restriction is true
    at a MOMENT and without one a reading from before the loosening is
    indistinguishable from one after. `evidence_scope` stays OUT of the
    canonical form with the other coordinate fields — the canonical form is the
    key's CAPABILITY, so re-observing by a different method must not move the
    census digest.

    Building that exposed a wider hole: the census digest was RECORDED and never
    COMPARED, so any change to a row's content that left the row count identical
    passed silently — a target repointed, a trigger changed, a credential
    renamed, a key unrestricted. The ratchet now compares the recorded census
    digest against the live one, so a content change is re-recorded in the same
    change like every other number here.

    **Compose sanction is ENTRY-POINT IDENTITY.** A compose verb is sanctioned
    IFF reached through the installed `dotmac-deployment-foundation` entry
    point, resolved from installed DISTRIBUTION METADATA — never from a path, a
    comment, a filename or a declared premise. Identity rather than intent for
    the reason this guard already demonstrated on itself: its verb detector read
    a usage comment as a deployment and drew a call edge backwards, because a
    path mention is symmetric while invocation is not. A sanctioned mutation
    runs inside the installed distribution, which is not in the tree, so it
    never resolves; an unsanctioned one always does, and delegation does not
    launder a direct call beside it. The console-script NAME is never written
    down — a literal would turn identity back into a string match — an
    unresolvable distribution is UNMONITORED rather than a pass, and whether it
    is installed is NOT recorded in the baseline, because that is a property of
    where the check runs rather than of the product. The unsanctioned SET is
    ratcheted two-directionally (the set, not the count: a swap leaves the count
    still), and it is a measurement rather than a refusal, because live
    executors are unsanctioned today and refusing them would make an honest
    census impossible on day one. Pairs with the installed `dotmac-platform`
    CLI ratchet; coordinate the vocabulary before either hardens.

    **A production host outside the roster is silently unmonitored.**
    `ADOPTION_TARGETS` names the REPOSITORY that owes an inventory, and a named
    production host retaining a rollback credential must have one — otherwise
    the roster reproduces the failure the code prevents. The roster holds
    repository identities, never host identities: `measure()` resolves
    `<product>.toml`, so a host in the roster names a file nobody can write and
    reports UNADOPTED forever for the wrong reason
    (ADR-0072; `scripts/executor_retirement.py`;
    `tests/architecture/test_executor_retirement_ratchet.py`;
    `tests/unit/test_executor_retirement_receipt.py`)

46. **A database-advancing operation promotes the descriptor it was authorized
    to produce.** Its candidate is authored before execution and the running
    database is never used to derive it. Authorization binds the target, plan
    and result descriptor; the independently observed starting descriptor is a
    precondition and the compare-and-swap source. The operation either has one
    database transaction or declares a descriptor for every durable checkpoint,
    including the final state; otherwise it refuses to start.

    PostgreSQL and the accepted-descriptor registry are separate transaction
    domains. The state after the database commit and before registry promotion
    is therefore named `promotion_pending`, not called atomic. Promotion is an
    idempotent, durably recorded compare-and-swap keyed by transition id, and a
    terminal receipt binds the starting and result descriptors, target, plan,
    database postcondition and promotion event. Recovery re-drives the same
    promotion and cannot infer success merely because the pointer now equals
    the result.

    Drift comparison is two-way at preflight, postflight and recovery:
    declared-but-absent and present-but-undeclared both refuse. Its effective-
    privilege audit extent is selected independently of the descriptor, covers
    inherited, PUBLIC and column-level reach, and must answer every selected
    question. A comparison reports `UNMEASURABLE`, never agreement, for a fact
    the descriptor schema cannot declare. In particular,
    `ProductDeploymentSpec.v1` remains immutable and has no exact table or
    column contract. A typed sidecar can bind MODULE- or PRODUCT-scoped
    catalogue coordinates to its digest without pretending they are v1 facts;
    `ProductDeploymentSpec.v2` embeds them explicitly while the v1 reader keeps
    refusing the new key and preserving v1 canonical bytes. Kernel catalogue
    schemas pair exactly with MODULE or PRODUCT scope, and product catalogues
    bind their product code/version through an explicit descriptor-product
    mapping. Structural evidence requires an integrated verifier over the held
    catalogue and observation bytes, the same observation and PostgreSQL major
    as `ObservedDatabaseState`, complete schema/table/column extent, and drift
    findings in both directions. Contract-id allowlists alone authorize nothing;
    Foundation invokes the injected kernel verifier over both held payloads and
    rechecks its factory-only result, including declaration scope, complete
    schemas and product code/version, before minting a witness.
    Partial `mod_deploy` evidence and every v1 sidecar withhold
    `matched_descriptor_digest`; v2 exposes it only with complete recognized
    coverage. Schema presence or an Alembic head is never
    substituted for structural proof
    (ADR-0070 amendment 2026-08-31;
    `tests/unit/test_deployment_foundation_database_transition.py`;
    `tests/unit/test_deployment_foundation_database_drift.py`).
47. **A product database catalogue is built once from declarations, never
    derived from a running database.** `ModuleManifest.tables` and
    `platform_tables` remain the only module table/plane owner. A module's
    `ModuleDatabaseCatalogContributionV1` may add exact ordered column/type
    structure only for those names at one lineage head; schema, owner and plane
    are derived during composition, never repeated in the contribution.
    `ProductDatabaseCatalogSnapshot` composes every selected stateful module
    with explicit kernel/assembly/extension host fragments, carries exact
    schema extent and PostgreSQL major, and refuses omissions, extras,
    collisions, noncanonical bytes and a host fragment pretending to be a
    module. PostgreSQL identifiers stay structured fields and preserve quoted
    catalogue spelling — no joining or splitting on `.`, `:` or `->`.

    Schema v1 is explicitly `tables_and_columns`; it claims no constraints,
    indexes, triggers, privileges or policies. A module snapshot is separately
    publishable without claiming unrelated product schemas. The product
    snapshot remains all-or-nothing. Kernel's observer and digest-bound
    verifier own the stable observation/comparator IDs; an ID string alone is
    not structural evidence.

    `ProductManifestSnapshot` remains the independent capability-only
    contract. The live migration catalogue is a comparator/observer only:
    disagreement is drift or a failed/unauthorised promotion, never input to
    regenerating the accepted declaration.

    Release Catalog does NOT bind these snapshots to artifact bytes yet, and
    nothing may claim a database catalogue is attested. A RELEASED module
    distribution adopts only kernel code some PUBLISHED kernel contains:
    `scripts/module_floor_check.sh` proves each module's declared
    `dotmac-kernel` floor is sufficient (the module imports at exactly that
    version) AND necessary (it fails against the previous published release),
    and a floor naming an unpublished version is unresolvable by construction.
    No published kernel carries `product_database_catalog`, so the
    `module_database_catalog` / `product_database_catalog` attestation kinds
    and their typed writers land in `dotmac-release-catalog` in a SEPARATE
    change, after the kernel release carrying this contract is published and
    with the floor bump that proves it — the same two-step
    `dotmac-entitlement-allocation` took for `PLATFORM_AUDIT_LOG_V1`.
    (ADR-0017 amendment 2026-08-31;
    `tests/unit/test_product_database_catalog.py`)

48. **A version name binds to ONE source and ONE artifact, and a CONSUMED
    version is never reissued.** `dotmac-deployment-foundation 0.3.0a2` is the
    live case rule 34 predicted: built once as candidate artifact 9740182233
    from `e930f878…`, then commit `0f390a9a…` (#551) changed the facility source
    under that same declared version, so for ten days the repository offered one
    version name over two different contracts. An installation adopts by digest,
    so a version naming two contracts makes every pin against either of them
    unidentifiable.

    **The repair is a NEW version, never an annotation on the old one, and never
    an edit to the artifact's receipt.** `CandidateArtifact.v1` records bytes
    that were built once; that record cannot become false, only the candidate's
    USABILITY can, and a restore proof, an issuer stand-up and Lane 3 all bind
    to it. So the receipt is preserved byte-for-byte and the judgement is
    APPENDED as `CandidateDisposition.v1` — original receipt digest, artifact
    coordinates, disposition, `publishable`, the invalidating commit, the
    reason. **Editing an entry in place is not a supported operation**; a
    judgement that turned out wrong is corrected by appending the correction.

    **Append-only is PROVED, not promised.** A hash chain, so editing any entry
    invalidates every entry after it. An anchor that is not ours to move — entry
    1 chains to the digest of the receipt it dispositions rather than to a zero
    genesis, so one check proves both that the log was not rewritten and that
    `CandidateArtifact.v1` was not touched. Git history as the oracle a single
    commit cannot forge, because with one entry the chain has nothing to link
    and the newest entry is otherwise unprotected. Plus an ADR-0018
    two-directional count ratchet that fails on GROWTH as well as shrinkage, so
    an append cannot be silent.

    **The record states the fact; a separate guard enforces it.** A record that
    both states and enforces is one edit away from being neither.
    `scripts/version_binding_guard.py` reads the real bindings — a git tag (the
    version is published), a `CandidateArtifact.v1` receipt (it was already
    built to specific bytes), a `CandidateDisposition.v1` (it was consumed) —
    and refuses in `foundation-candidate.yml` before a build and in
    `release-facility.yml` before a publish, including in the job that actually
    holds the registry credential. `--purpose release` permits a version's own
    candidate receipt, because publishing those exact bytes IS the designed
    path; a tag and an unpublishable disposition still refuse.

    **Without tags the guard REFUSES TO ANSWER (exit 2), never passes.** It
    could otherwise not see publications and would admit a version already on
    the index — the exact failure it exists to stop. Per Governance ADR 0034 the
    gate demonstrates a **real-target ADMIT** and not merely synthetic
    acceptance: `0.3.0a4`, the version this tree declares, is admitted for both
    purposes against the repository's own bindings, while `0.3.0a2` is refused
    for both, `0.3.0a1` and `0.3.0a3` are each refused for a SECOND BUILD and
    admitted for their own release, and all three published tags are refused —
    all from that same record set. A tree that diverges from a built artifact
    allocates a new version rather than keeping the old one, which is what
    moved the declared identity off `0.3.0a3` on 2026-09-02; the wheel built
    under that name is unaffected, because a consumer resolves it by run and
    artifact id out of the committed receipt, never by what this tree declares
    (`scripts/foundation_disposition.py`, `scripts/version_binding_guard.py`;
    `tests/architecture/test_foundation_candidate_disposition.py`,
    `tests/architecture/test_version_binding_guard.py`)

49. **The middle term of a controlled deployment is a document the FOUNDATION
    renders and Control merely FREEZES.** `ExecutionPlanDigestV1 =
    sha256(canonical FoundationExecutionPlanV1 bytes)`. It is **not** the
    descriptor digest, the authorization-envelope digest, or Control's internal
    snapshot digest — each is a real value a reader could reach for, and
    reaching for the third is exactly what went wrong: Control's `plan_digest`
    hashed the spec WRAPPED IN SIX SIBLING KEYS while the Foundation hashed the
    descriptor ALONE. Same serialization rules, different payload, so the two
    could never be equal for any input — and both sides were internally
    consistent, so it read as correct.

    Patching either end preserves the defect's shape: whoever normalizes decides
    what was authorized and the other party trusts a reconstruction. **Control
    never reconstructs or normalizes the Foundation plan**, and has no
    canonicalizer for it by design, because a second canonicalizer is a second
    answer.

    **The flow, in order.** Foundation renders the target-bound plan from the
    immutable artifact and the authorized environment inventory and computes the
    digest (`dotmac-deploy execution-plan --format digest`) → Platform CP
    submits THAT EXACT DIGEST and an explicit operation to Control → Control
    freezes and signs → Foundation **recomputes the digest before execution**,
    because "nothing changed since we were authorized" is what a long-running
    process cannot assume → the execution report carries the same digest and
    operation. A digest mismatch means the PLAN CHANGED, never that two
    canonicalizers disagreed, and the refusal says so — if a mismatch could mean
    disagreement, the fix a reader reaches for is a normalizer, which is how the
    original divergence became permanent.

    **Canonicalization is byte level, because two repositories bind to it.**
    UTF-8 of `json.dumps(sort_keys=True, separators=(",", ":"),
    ensure_ascii=True)`; ASCII-only and REFUSED otherwise, so the NFC/NFD
    question never arises rather than being answered; keys sorted at every
    depth; every declared key always present and `null` never appearing (a
    missing key and an explicit null are two encodings of one fact); integers
    only (float repr is platform-sensitive); `steps` in PLAN ORDER because a
    reordered procedure is a different procedure, every other array sorted and
    deduplicated; **no prose** — a step's description is excluded, so editing a
    sentence cannot change a digest Control has already signed; the digest
    covers the document ALONE, no wrapper; and `foundation_version` sits inside
    it, because the plan's meaning is the steps THAT version emits.

    The plan binds target, operation, image reference and digest, source
    revision, manifest digest, descriptor digest, strategy, environment
    inventory and steps. Dropping any one produces a plan reusable where it was
    never meant to apply — the enumeration `ExecutionGrant` makes for an
    approval, applied to the thing approved. The inventory is material NAMES
    only, never a resolved value (ADR-0009)
    (`packages/dotmac-deployment-foundation/src/dotmac_deployment_foundation/execution_plan.py`;
    `tests/unit/test_deployment_foundation_execution_plan.py`, whose
    `test_the_digest_covers_the_document_alone` plants the six-sibling-keys
    wrapper and observes both a different digest and an outright refusal)

50. **The window between a candidate BUILD and its PUBLICATION is guarded, and
    a build the tree does not record is the defect — not the bookkeeping.**
    `dotmac-deployment-foundation 0.4.0a1` is the FOURTH recurrence of rule 48's
    shape and the first where every guard was silent *and correct*: run
    `33920058598` built the candidate from `753a004e` on 2026-09-04, the
    `CandidateArtifact.v1` receipt stayed in the run's artifacts and never
    reached `docs/inventories/`, and `#628` and `#631` then moved 4 files of the
    facility's importable source under the unchanged declared name.
    `candidate_source_binding.py --check` reported `0 drifted` because it
    compares against receipts; `version_binding_guard` ADMITTED `0.4.0a1` for a
    fresh build for the same reason; `test_version_binding_guard.py` went on
    asserting the version was *not recorded as built*. All three were true of
    the ledger and false of the artifact. **Allocating a successor is the repair
    that keeps being applied and keeps not preventing recurrence** — the missing
    thing was a gate in the window, so Michael held the release (2026-09-05) to
    build one. That hold authorizes neither committing the old receipt nor
    allocating a successor; those remain separate lifecycle decisions.

    **A LIVE CANDIDATE is a build that happened and has not been consumed** — a
    successful candidate-lane run, at a commit whose declared version for that
    facility is the one this tree declares, that produced the
    `<facility>-candidate` artifact. Not "a receipt in the tree": presupposing
    the record is exactly what made the region look covered.

    **The build oracle is external, because the claim is.** *"No candidate has
    been built for the declared version"* is a claim about the BUILD SYSTEM, so
    per rule 30 it takes an authoritative oracle carrying immutable coordinates
    — the run id and the artifact id, the same two facts `CandidateArtifact.v1`
    records. No repository-local formulation can see this population: at the
    moment `#628` was opened every byte in the tree was consistent with
    `0.4.0a1` never having been built. A run is attributed to a facility by the
    ARTIFACT it produced and to a version by its own commit's `pyproject.toml`,
    never by a workflow input.

    **It compares TREE OBJECTS, never a version string** — a version string is
    what failed to notice this — and it runs in `ci.yml`'s `candidate-window`
    job, on every pull request and every push, which is where the source
    actually moves and where a refusal is cheap. The release lane is not that
    place and cannot become it: its checks fire at dispatch, and
    `release_facility.require_candidate_ancestry` deliberately PERMITS the tree
    to have moved, because requiring equality there would be unsatisfiable and
    would get waived.

    **It refuses and explains; it never chooses the successor.** A check that
    emitted "rebuild as 0.4.0a2" would be issuing a release identity as a side
    effect, and the identity would then exist because a script printed it. The
    refusal names the run, the artifact, both tree objects and the repair —
    commit the receipt for `unrecorded`, allocate a NEW version and append a
    `CandidateDisposition.v1` for `drifted` — and stops. Those are the state
    transitions that would close the findings, not authority to perform them.

    **Exit 0 clean / 1 violation / 2 indeterminate**, and an unreachable oracle,
    an unresolvable build commit or a shallow clone is 2, never a pass. Open
    windows are frozen debt in `tests/architecture/candidate_window_baseline.json`,
    ratcheted in BOTH directions; the row omits the moving current tree so the
    debt is one stable fact rather than a file regenerated per commit
    (`scripts/candidate_source_binding.py --window`; the `candidate-window` job
    in `.github/workflows/ci.yml`;
    `tests/architecture/test_candidate_window_binding.py`, whose sensitivity
    proof replays the real history — the build at `753a004e` against the tree at
    `c427b9df` (`#628`, which must fire) and against the tree at `4895f179`
    (`#629`, which landed on the same candidate, touched no importable source,
    and must stay silent))

51. **Caller-supplied text is never authorization, and a gate that cannot check
    it says so rather than passing.** Lane 3 took `--authorization-run` and
    `--authorization-doc-digest` as `workflow_dispatch` strings and executed on
    them: the only comparison was `lease.covers(authorization_run_id=...)`, a
    string equality against a lease record the same operator writes, and the
    digest reached `build_receipt`, which asserted it equalled the descriptor
    digest — a value any caller computes locally from a file in this repository.
    Nothing imported `provenance.py` or `authorization.py`; no
    `VerifiedAuthorization` and no `ExecutionGrant` were ever constructed. Two
    matching strings LOOKED like a binding while no authorization existed
    anywhere, which is precisely what "the Foundation cannot self-authorize"
    forbids.

    **The unverified case is made UNREPRESENTABLE, not guarded.** The dispatch
    inputs are not parameters of `establish_authorization`, so no path through it
    can promote them into proof by forgetting a comparison; the only route to an
    `ExecutionGrant` is an injected `AuthorizationVerifier` attesting a signed
    document, `verify_authorization` producing the verified terms, and
    `authorize` binding them to this descriptor, this target and this operation.
    An input that names proof and supplies none is REMOVED rather than
    deprecated, at the dispatch as well as at the parser.

    **Three statuses, and neither borrows the other's.** 0 attested, 1 a
    violation — the environment could answer and the answer is no, 2
    indeterminate — no verifier is installed, so the question has no answer here.
    A refusal must never read as indeterminate and an indeterminate gate must
    never read as a pass; the ordering enforces it, because the verifier is
    looked for before the material is read.

    **A chain that cannot be built is BLOCKED, not faked.** Where the
    verification chain does not exist, enumerate the preconditions IN CODE, cite
    them by name in the refusal, and mark the ones nothing local can decide as
    stated rather than enforced. A weak in-house verifier would be worse than the
    gap because it reads as coverage; a checklist that claims to observe what it
    cannot is the same failure one layer up (ADR-0018). Prose alone does not
    hold: this prerequisite was written down on 2026-08-30 and the runner shipped
    accepting the text anyway
    (`scripts/lane3_authorization.py`,
    `docs/inventories/deployment-exposure-rehearsal.md` § "Prerequisite 2";
    `tests/architecture/test_lane3_authorization.py`, which plants the
    fabricated authorization, plants each near miss separately, and proves the
    admit is reachable with an injected verifier so the refusal is not refusing
    everything)

## Everything by config — no hardcoding

Env-specific values are overridable variables with documented defaults,
never literals: new knobs go in `Settings` + `.env.example`; Make vars use
`?=`; compose files use `${VAR:-default}`; `scripts/deploy.sh` falls back
via `: "${VAR:=default}"`. New secrets/knobs that must not keep a dev
default in production are added to `validate_settings`'s prod-fatal list.

## Validation before any commit

**Tests-only-on-Git-hosted-CI — hard rule.** Do not run test commands or
install test/development dependencies on the local workstation or any named
test host. Before the first push, local work is limited to read-only
inspection, editing, formatting, and pinned static checks (for example the
repository's pinned Ruff binary); static checks are not test evidence. Hosted
PR CI tests the synthetic merge result for the pushed head SHA and its base
revision, and Git-hosted CI is the merge-acceptance owner. Every named
required context for that head/base result must be terminal green; rerun the
checks if either the head or base changes. Do not merge with partial or failed
required checks.

**Never run a test workload on Dotmac Observer.** Observer owns the
observability stack, OpenBao and the Knowledge service, and a test run there
takes those down for everyone. This rule previously named Observer as the test
host and offered `-n 2`/`-n 3` instead of `pytest -n auto` as the safeguard.
That mitigation is disproven: a run already capped at `--memory=10g --cpus=3
-n 3` triggered a host-global OOM that killed Prometheus for about fifteen
minutes. A container memory limit bounds one cgroup; it does not reserve memory
for the other services on the host, and the kernel picks its victim by
`oom_score`, where a large resident Prometheus outscores the capped test
process. Reaching Observer for observability, OpenBao or Knowledge work is
unaffected and remains correct.

- `make check` — ruff lint, import-linter, mypy, bandit, the composed
  migration gate (ADR-0006 D1), format check (run on Git-hosted CI).
- `make test-unit` — SQLite-fast: `tests/unit` + `tests/architecture` (run on
  Git-hosted CI).
- `make test-db-up && make test-integration && make test-db-down` —
  Postgres RLS canaries (`TEST_DB_PORT` overridable; run on Git-hosted CI).

## Process

- **TDD / canary-first.** New behavior lands with its test written first;
  tenancy-affecting work starts with the cross-tenant isolation canary (see
  `tests/test_cross_tenant_isolation.py` for the pattern). New governance
  tests must include a sensitivity proof (shown RED against a temporary
  violation).
- **New feature:** create the package + `feature.py`, register in
  `FEATURE_MODULES`, add to the import-linter independence contract, write
  the isolation test first. New settings/custom-field entities: follow the
  Extension points in `CLAUDE.md`.
- **New kernel facility or shared module:** complete the product inventory and
  `EXTRACTION.toml` dossier before implementation. Start from the qualifying
  ERP/Sub implementation and its tests when one exists; an unresolved audit is
  a stop condition, not permission to greenfield the shared version.
- Zero-consumer code is deleted, not kept. Every new concept gets its owner
  row in `docs/ARCHITECTURE.md`'s provenance/ownership tables.
- **Publishing writes a RECORD, not just a tag.** A tag makes that
  distribution's `declared-publication-baseline.json` row false immediately,
  its released migrations become bytes that must not change, and a connector's
  published manifest digest becomes a row owed to
  `released-manifest-digests.json` — so the gates fail from the instant of the
  tag until all of them are recorded. The release
  workflows now open that record themselves
  (`scripts/open_release_record_pr.sh` calling
  `scripts/write_release_record.py`, straight after tagging) — merge that pull
  request as soon as it is green, then verify the resulting protected `main`
  revision is truthful and green before the release captain ends the freeze.
  Run the writer by hand only to repair an older gap; never edit a declared
  version down to make the gates agree.
