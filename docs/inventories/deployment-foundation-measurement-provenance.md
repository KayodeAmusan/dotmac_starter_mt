# `dotmac-deployment-foundation` — measurement provenance

> **Addresses redacted 2026-10-05** at the owner's direction: this is a public
> repository and these were live production estate addresses. Each redaction
> names the address's ROLE. The role → address mapping, which keeps this record
> checkable as evidence, is held privately in the Dotmac Knowledge record
> `dotmac-estate-address-redaction-map-2026-10-05`. The original values remain
> in this repository's public Git history; redaction does not withdraw them.


**Record date:** 2026-09-05
**Relocated from:** `packages/dotmac-deployment-foundation/src/dotmac_deployment_foundation/{lease,vantage}.py`
**Reason:** the package is a reusable wheel; a host identity compiled into it
ships to every consumer of the distribution
**Guard:** `dotmac_deployment_foundation.target_identity_guard`

Two module docstrings in `dotmac-deployment-foundation` recorded the host a
measurement was taken on, by address. The finding each records is what the
module needs in order to be understood; the identity of the host it was found
on is *evidence*, and evidence belongs in an inventory rather than in a
published artifact.

This is a relocation, not a deletion. The addresses below are the provenance
for two design decisions that are otherwise unfalsifiable — a reader who cannot
tell where a measurement was taken cannot check it, and "we measured something
somewhere" is not a citation. What changed is only *where* the record lives:
outside the wheel, in the dated inventory that already owns as-built facts.

## Why not in the package

An address in the package survives every environment, ships to anyone who can
`pip download` the distribution, and is the mechanism by which a probe aimed at
staging reaches production after a rebuild nobody re-reviewed. The narrower
point for these two specifically: they are a **target** identity and a
**vantage** identity, and both must arrive through the typed authorization,
lease and challenge inputs, with **no defaults**. A module that stops naming an
address but retains a fallback to one has moved the problem rather than fixed
it. Neither module has such a fallback — `HostLease.target` is required and
`qualify_vantage` decides over observations it is handed — and
`test_no_module_supplies_a_default_target_or_vantage` holds that open.

## `lease.py` — `HostLease.v1`

**Measured:** 2026-08-30
**Host:** `[redacted 2026-10-05: shared rehearsal host IPv4]` (the shared rehearsal host)
**Finding:** `/var/lock` held `lvm/` and `subsys/` and nothing else. There was
no lease mechanism at all, while eleven agents' worktrees and four agents'
containers shared the host. "Exclusive lease" was a sentence in a plan.

## `vantage.py` — `VantageQualification.v1`

**Qualified:** 2026-08-29 · **Re-measured:** 2026-08-30
**Candidate vantage:** `[redacted 2026-10-05: probe vantage IPv4]`
**Finding:** qualified as "outside every Dotmac allowlist" on three refusals and
one positive control, then found to hold a second NIC — `eth1 10.0.0.4/22` —
routing into the `idp-ha` private network. The refusals were real and the
conclusion was not.

**The control that was lost with the risk:** the discriminating check was
`ip route get 10.0.0.2 -> dev eth1`, proving the routing query *selects* a path
rather than always naming the same interface. Re-measured 2026-08-30 the NIC is
gone, so that query answers `eth0` like everything else. The risk is resolved
and the control is gone with it, and those are different facts — which is why
qualification became a set of positive proofs, ending in the far-end
confirmation the vantage cannot fake about itself.

## Scope note

`target_identity_guard` scans the **package and its built artifacts**, not the
repository. This file is deliberately outside that scope: it is the destination
the guard's refusal points at, and a guard that also refused its own evidence
record would leave nowhere for the provenance to go.
