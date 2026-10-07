# Integration REQUEST source inventory

Status: accepted as the evidence companion to ADR-0024's 2026-10-07 amendment.
Scope: provider-neutral synchronous reads in `dotmac-integration`; no provider
connector, product API, deployment or credential change is authorized here.

## Sources inspected

| Source | Exact evidence | Disposition |
|---|---|---|
| `dotmac_sub` at `457882482cc938bfe70f48ca2fb282dab98beee6` | Meta contact/profile lookup is recorded by the existing `dotmac-connector-meta-social` dossier as a withheld caller-initiated read, and ADR-0024 §11.3 names its successor `social.profile.read.v1` | Qualifying product behavior, but no reusable synchronous engine exists to port |
| `dotmac_erp` at `d8b0dc71c6cfc5dec3d71852d72bba6cba1728af` | Fleet tracking needs provider health, latest position, and bounded position history while ADR-0011 forbids ERP-owned provider transport | Independent adopter requirement; not a source implementation |
| `dotmac_starter_mt` at `b0cc1c872d506ef4adf6786ef5335d0784b19825` | `dotmac-integration` supplies INGRESS, POLL, DELIVERY and PROVISION, domain-owned capability schemas, connector discovery and retry policy, but no synchronous query seam | Correct extension owner; REQUEST is greenfield-after-inventory |

## Ruling

The repeated need is real: Meta profile observation and ERP fleet telemetry are
different products and providers, yet both need the same bounded typed read
shape. No fleet repository contains a provider-neutral synchronous engine to
port. SPI 1.6 therefore adds only the generic seam:

- capability id selects the operation; products cannot forward raw transport;
- `command_schema` bounds input and `observation_schema` bounds output;
- an opaque Integrator installation id isolates connector session state;
- closed failures cannot carry raw provider bodies or secrets;
- `dotmac-integration` owns bounded retry/backoff for unavailable/timeout;
- connectors own one bounded provider-session re-authentication replay.

Provider normalization remains in independently released connector packages.
Product authentication and routes remain assembly concerns. The contract is
persistence-free and adds no migration, table, secret store or network policy.
