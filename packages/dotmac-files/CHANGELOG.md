# Changelog — dotmac-files

## 0.1.0a5 — source candidate

- Add a one-key reviewed-orphan operation that checks the live provider
  identity, authoritative references, exact object presence and object age
  before deleting. It returns a typed outcome for the product's durable run
  record; plan authorization and auditing remain product responsibilities.
- Reject an out-of-scope or duplicate exact-key provider listing and naive
  timestamps. The caller's reference read must close its transaction before
  the provider call.

## 0.1.0a4 — tagged; release verification legacy-unverified

Names the engine-free `conflict_savepoint` repair's changed importable source
as a version distinct from a3, so one released version does not name two
importable surfaces. The annotated `dotmac-files-v0.1.0a4` tag exists, but
`docs/inventories/module-release-legacy-unverified.json` still lists it as
legacy-unverified; no producer-owned verification row is checked in.

### Changed

- `service.py` now imports `conflict_savepoint` from `dotmac_kernel.transactions`
  instead of `dotmac_kernel.db`.
- Kernel floor raised to `>=0.1.0a98`, the release that carries
  `dotmac_kernel.transactions.conflict_savepoint`.

## 0.1.0a3 — 2026-08-18

Makes the released dual-plane lineage explicitly tenant-selectable for the
deferred ERP cohort and Academy without changing the published `fi_0001` bytes
or claiming either as a current consumer.

### Changed

- The manifest supports TENANT and TENANT+PLATFORM installations. PLATFORM-only
  remains refused because no named adopter needs it and the released root needs
  the tenant catalogue.
- New `fi_0002_selectable_planes` consumes the assembly's ADR-0028 selection.
  A TENANT installation locks the historical platform table, refuses if it has
  any row, and drops it only while still holding that lock. The full selection
  preserves the a2 catalogue unchanged.
- Kernel floor raised to `>=0.1.0a61`, the first release carrying the explicit
  module-plane selection surface this manifest and migration consume.
- Adds `dotmac_files.versions_dir()` and the matching migrations-submodule
  export, so an independently installed ERP or Academy wheel can compose the
  `fi` lineage without knowing the package's private filesystem layout.

## 0.1.0a2 — 2026-08-13

Declares the database EFFECTS this lineage needs instead of naming a foreign
revision (ADR-0006 D1 amendment).

### Changed

- `fi_0001_stored_files` previously read
  `depends_on = ("0001_initial_tenant_schema",)`. That edge is true only in an
  assembly that runs the kernel lineage: ERP hosts `public.tenants` in its own
  lineage and can never run kernel `0001`, so the module was un-installable
  there for want of a foreign-key target. The manifest now declares
  `requires=("tenant_scope_catalog.v1", "module_database_roles.v1")`, the root
  resolves its `depends_on` from the assembly's bindings, and `upgrade()` proves
  both effects against the live catalog before any DDL.
- Kernel floor raised to `>=0.1.0a56`, the release that added the prerequisite
  contract. A kernel below it cannot import this manifest.


## 0.1.0a1 — 2026-08-13

- Adds streamed admission with size, extension, declared-type, and detected
  content checks for PDF, CSV, `.xls`, `.xlsx`, PNG, JPEG, GIF, and WebP.
- Adds the provider-neutral immutable-object contract and typed failures.
- Adds explicit tenant `mod_files.stored_files` and platform
  `mod_files.platform_stored_files` planes in one independent `fi` lineage.
  Tenant rows use forced RLS; platform rows have no tenant column or RLS and
  are revoked from `app_user` (ADR-0023).
- Shares one persistence-free physical engine across both planes, selected by
  required `TenantScope` or `PlatformScope` values with non-overlapping object
  prefixes.
- Excludes domain attachment relations and import/document parsing by design
  (ADR-0022).
