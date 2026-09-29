# dotmac-files

`dotmac-files` is the optional owner of stored bytes on explicit tenant and
platform security planes. It validates an incoming stream, writes it beneath a
trusted immutable key, records its physical metadata, streams it back through
the bound provider, and reconciles missing, deletion-pending, purged, and
orphaned objects.

Each application consumes an independent installation (ADR-0024): it pins the
package, runs its own `fi` lineage, owns its own metadata rows and binds its own
provider adapter. Applications share this lifecycle contract, never a
`mod_files` schema, object-key authority or provider credential. Cross-app file
data moves only through the owning application's versioned API/webhook; no
consumer reads another application's database or object prefix.

## Two planes, one physical engine

Callers must pass either `TenantScope(tenant_id)` or `PlatformScope()`; absence
of a tenant is never interpreted as platform scope. Tenant metadata lives in
`mod_files.stored_files` with forced RLS. Platform metadata lives separately in
`mod_files.platform_stored_files`, has no tenant column or RLS, and is revoked
from `app_user`. Object keys are similarly disjoint:

- `tenants/<tenant-id>/files/<file-id>`
- `platform/files/<file-id>`

`physical.py` supplies one persistence-free admission/provider engine to both
planes. `service.py` selects the explicitly declared table from the scope type.
The tables share behavior, never rows or foreign keys (ADR-0023).

The lineage supports two explicit installation shapes (ADR-0028): TENANT for
ERP and Academy, and TENANT+PLATFORM to preserve the original a2 catalogue.
There is no PLATFORM-only promise because no named adopter needs it and the
released root requires a tenant catalogue. A TENANT upgrade from a2 refuses to
discard a populated platform table; those rows require an explicit ownership
and data-migration decision first.

Provider codes and endpoints are assembly declarations/configuration. A
provider-specific SDK or wire mapping belongs in the product's
`StorageProvider` adapter, not in this package's execution paths.

It deliberately does **not** own a ticket attachment, invoice document,
subscriber photo, import mapping, or authorization rule. A domain stores the
opaque file UUID and owns why it is attached, who may read it, and when its
retention policy permits `request_deletion`.

## Format boundary

The first contract recognizes and rejects content-type spoofing for PDF, CSV,
legacy Excel (`.xls` compound-file signature), OpenXML Excel (`.xlsx`, with the
workbook entries present in the ZIP package), PNG, JPEG, GIF, and WebP.
Recognition answers “may these bytes enter storage?” It does not interpret a
PDF or spreadsheet, transform an image, or make active SVG safe.

Generic PDF text/table extraction and spreadsheet row readers belong in parser
adapters used by the future `dotmac-imports` module. Column mapping,
row validation, dry-run/apply, duplicate policy, and domain mutations belong to
the importing domain.

## Transaction boundary

Object stores cannot join a PostgreSQL transaction. Upload therefore writes an
immutable object first and stages `TenantStoredFile` or `PlatformStoredFile` in
the caller's transaction. If the transaction fails, the split
list/decide/delete orphan reconciler removes the old unreferenced object.
Deletion is reversed: the domain commits
`deletion_pending`, a worker obtains a `StoredObjectRef`, ends that DB phase,
performs the idempotent provider delete, and records `purged` in a later
transaction. Downloads and presence checks use the same target/action/record
split, so a provider stream or network call never holds a database transaction.

The module never commits or rolls back. A consuming assembly composes its own
`fi` Alembic lineage through the public `dotmac_files.versions_dir()` locator;
it never hard-codes a source-checkout path.

## Reviewed orphan deletion

`recheck_and_delete_orphan` accepts one key from a product-authorized plan. The
product must first commit the run and raw key to a durable repair record. The
operation checks that the live provider still matches the plan, calls the
product's short-lived reference reader across provider codes and lifecycle
states, observes the exact object key, and deletes only when the object's own
`last_modified` precedes the reviewed age cutoff. It returns a typed outcome
for the product to record. The product owns plan review, retention policy,
authorization, outcome commits and retry rules; the callback must close its
database transaction before returning. A failed provider call is propagated
so the product can record failure and stop its run.

The database reference read and object-store delete cannot be atomic. Before
an application adopts this operation, it must enforce that no writer can add
a reference to the reviewed key after the recheck, or hold a product-owned
reservation that its reference writers honor. Immutable object keys must also
prevent replacement between the exact-key observation and delete. Until those
invariants are proved, the operation is a source candidate, not a safe
production cutover.
