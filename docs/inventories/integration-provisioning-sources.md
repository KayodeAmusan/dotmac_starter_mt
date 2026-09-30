# Integration provisioning source inventory

Inventory date: 2026-09-03

This inventory answers one question: what may be reused to add provider-neutral
provisioning to `dotmac-integration` without treating an archived experiment as
current product truth?

## Current owner

`origin/main` at `2773345495daf1a08b6c7bf003d87822b9e8f270` owns the live
Integrator module. Its SPI is 1.4 and its executable modes are ingress, poll and
delivery. `CapabilityContract` in
`packages/dotmac-integration/src/dotmac_integration/capability_registry.py`
already gives each capability exactly one product-owned command, result and
observation schema. `CapabilityDeclaration` in `spi.py` claims that contract's
digest and must not publish a connector-owned replacement.

The current persistence lineage ends at `ig_0015_descriptor_contract.py`.
This slice allocates no successor and adds no table: sibling local branches
cannot safely allocate the next migration for themselves.

## Archived experiment

The archived branch
`origin/archive/worktrees/2026-08-25/starter-managed-services-working` at
`5dbc80e4e59dbc4216b32e3aa0742d38969bd841` contains:

- a fourth `PROVISION` mode;
- typed plan/apply/observe/cancel requests and results;
- `provisioning.py`, `provisioning_models.py`, migration `ig_0008`, and tests.

Only the four-operation SPI shape is reused. The archived engine is not
cherry-picked because:

- its `ig_0008` revision collides with the current audit-log revision;
- it reports SPI 1.2, which was later released without provisioning;
- it lets connector declarations carry product contract snapshots, while the
  current owner correctly puts payload meaning in `CapabilityContract`;
- its stateful engine predates the current Integrator lifecycle, evidence and
  retry owners.

## Decision for this slice

Provisioning is additive SPI 1.5. A connector declaring it supplies one
`ProvisioningHandler` with typed `plan`, `apply`, `observe` and `cancel`
operations. The product authors desired state and the exact ordered plan;
Integrator checks that a connector does not rewrite it. The connector performs
provider I/O only. It does not author entitlement, lifecycle state, retry
policy, region, price or any other business decision.

This slice is intentionally persistence-free and provider-free. Durable
operation rows, leases, retry, reconciliation, migrations and assembly wiring
remain separate work after a serialized migration and package-version
allocation. No published version or runtime adoption is claimed here.
