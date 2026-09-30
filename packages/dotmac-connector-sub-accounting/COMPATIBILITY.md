# Compatibility

`dotmac-connector-sub-accounting 0.1.0a1` implements dotmac-integration SPI
`>=1.3,<2.0` under connector key `sub_accounting`, in POLL mode only.

| capability | modes |
|---|---|
| `invoices.accounting_sync.observation.v1` | POLL |

It declares one required secret binding, `sub_api_key`, and exact egress
`selfcare.dotmac.io` — no other host is reachable. `selfcare.dotmac.io` is
Sub's registered production hostname; declaring it here is a manifest value,
not an activation, binding or deployment decision.

Capability configuration accepts `limit` (integer, 1–500) and an optional
`updated_since` date-time string; no other configuration key is accepted.

`claims_contract_digest` on the one declared capability is `None` — the
parallel ERP-side slice that owns `invoices.accounting_sync.observation.v1`'s
payload contract has not yet published it. This is the SPI's own "nothing
published yet" state (`CapabilityDeclaration.claims_contract_digest = None`),
not a placeholder value standing in for a real digest.

The public Python surface is `MANIFEST`, `PLUGIN`, `SubAccountingConnector`,
`SubAccountingPollHandler`, `SubAccountingPollError`, `map_item`,
`SubAccountingMappingError`, `CONTRACT_VERSION`, `CAPABILITY_ID`,
`CONNECTOR_KEY` and `__version__`.

## Digest fields are forwarded, not computed

`digest_version` and `projection_digest` are computed by Sub and published on
its feed item. This connector validates their wire shape only (positive int;
64-lowercase-hex string) and forwards both verbatim — it never recomputes or
reconstructs Sub's canonicalization algorithm. See `mapping.py`'s module
docstring and `README.md`'s "Digest forwarding" section for the exact
validation rules.

## Not wired into CI yet

This package's tests are not yet enrolled in CI (a separate, already-known
follow-up). Running them requires `poetry install` in this package's
directory or an equivalent local editable install; `make check`/CI do not
currently collect them.
