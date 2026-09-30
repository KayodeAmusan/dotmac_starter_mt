# dotmac-connector-sub-accounting

Sub invoice-accounting-sync feed, POLL-only observation connector for the
independently deployed Dotmac Integrator. It pages
`GET https://selfcare.dotmac.io/api/v1/invoices/accounting-sync/v2`
(`X-API-Key` authenticated) through an engine-owned cursor and translates
each item into a provider-neutral `invoices.accounting_sync.observation.v1`
fact.

It owns no database, product identity, allocation, delivery target or
checkpoint. In particular it never constructs the destination-bound request:
`organization_id` (the binding's configured destination org — an
operator-controlled mapping, never derived from Sub's data) and the delivery
`idempotency_key` are supplied downstream by the generic Integration engine
and the destination `ObservationPortClient`, never by this connector. Sub's
`account_id` is never mapped onto ERP's `organization_id` — conflating a
provider identifier with a destination scope is exactly the anti-pattern this
fleet's architecture forbids.

## Observation shape

| field | source |
|---|---|
| `source_invoice_id` | Sub feed item `source_invoice_id` (UUID, unmodified) |
| `source_account_id` | Sub feed item `account_id` (UUID, unmodified — never a destination scope) |
| `source_updated_at` | Sub feed item `updated_at`, exact string |
| `source_kind` | Sub feed item `source_kind`, verbatim (a dedicated field, distinct from the invoice's own lifecycle `status`) |
| `disposition` | Sub feed item `disposition`, verbatim |
| `source_total_amount` / `source_currency` | Sub feed item header money fields |
| `source_issued_at` / `source_due_at` | optional, when present |
| `issues` | Sub feed item `issues`, `line_id` renamed to `source_line_id` |
| `contract_version` | Sub feed item `contract_version`, must equal `invoice-accounting-sync.v2` |
| `digest_version` / `projection_digest` | Sub feed item fields, validated for wire shape and forwarded verbatim — see "Digest forwarding" below |

## Cursor

Canonical compact JSON `{"after_id":"<uuid>","after_updated_at":"<iso datetime>"}`.
A cursor carries exactly both fields or neither; a partial cursor is a
connector-internal error. `limit` is always sent; `updated_since` only when
configured. Pages are validated for strictly-increasing
`(updated_at, source_invoice_id)` positions — a non-monotonic page is a
malformed-response error, not silently accepted. An empty page (including the
first poll) returns no events and leaves the cursor unchanged, mirroring
`dotmac-connector-nira`'s convention. One request per `poll()` call; no
internal retry or sleep.

## Business-rule mirroring

A blocked observation with no issues, or a non-blocked observation carrying
issues, is refused before it is ever emitted — mirroring the consistency rule
ERP's own `RecordInvoiceSyncOutcome` construction enforces, as defense in
depth rather than a replacement for it.

## Digest forwarding

`digest_version` and `projection_digest` are computed by Sub, not by this
connector. This connector validates their wire shape only — `digest_version`
must be a positive, non-boolean int; `projection_digest` must be exactly 64
lowercase hex characters — and forwards both values verbatim into the
observation payload. There is no algorithm here to reconcile with ERP: a
mismatch anywhere downstream means a real transport or mapping bug, not an
expected reconciliation gap.

## Manifest

One capability, `invoices.accounting_sync.observation.v1`, POLL only. One
required secret binding, `sub_api_key` (an `ApiKey` scoped to
`integration:accounting_sync:read` on the `dotmac_sub` side; provisioning the
value is a separate operational step). Egress is exactly
`selfcare.dotmac.io` — Sub's registered production hostname. **This is a
production coordinate declared in code, not an activation**: building the
manifest correctly is still useful for review, but this connector must not be
bound or enabled without a separate explicit go-ahead.

`claims_contract_digest` pins ERP's published v3 ProductPort observation
contract. The connector does not author a competing schema; a digest mismatch
fails composition/binding closed. The port remains disabled pending separate
activation authority.
