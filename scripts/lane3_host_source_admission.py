"""D4: Lane 3's own ``HostSourceAdmissionProvider``, refusing until Gate 0.

``Executor.run`` verifies the host source before its first effect, through the
``admission_provider`` it is constructed with. The installed CLI hard-codes
``RefusingHostSourceAdmissionProvider``, which is why D4 drives the
``Executor`` in-process (roadmap Q1, answered 2026-10-06). The provider it
hands in is this one: Starter-owned execution tooling, so it can grow without
touching Foundation ``src/`` and without spending the candidate.

## What the real implementation must check

It calls the public ``admit_host_source`` with nothing the caller could forge:

- **The candidate and installed attestations:** two ``AttestationEnvelopeV2``,
  signed by the Gate-0 attester (``gate0-attester-01``). The candidate half
  binds the wheel digest the plan authorized; the installed half binds what the
  target's interpreter actually loads.
- **The verifier and trust policy:** an ``AttestationVerifier`` and an
  ``AttestationTrustPolicy`` pinned to the attester key recorded in Gate-0 trust
  state. They must not come from the job's inputs.
- **The expected subject:** the plan's ``host_id``, the observation the
  attester signed, and the ``dotmac-deployment-foundation`` package.
- **Freshness and context:** the ``verification_context_digest`` Control issues
  for this dispatch, and the current time.

None of those exists yet. The attester VMs, its key and the trust-state
records are Gate-0 steps A3-A5, and Control has no API that hands a provider
current context. So this provider refuses, and refuses exactly as the
reference implementation does: same codes, zero effects.
"""

from __future__ import annotations

from dotmac_deployment_foundation.host_source import HostSource
from dotmac_deployment_foundation.host_source_admission import (
    HostSourceAdmissionTrace,
    RefusingHostSourceAdmissionProvider,
)


class Lane3HostSourceAdmissionProvider:
    """The provider D4's ``Executor`` is constructed with. Refuses today."""

    def admit_host_source(self) -> tuple[HostSource, HostSourceAdmissionTrace]:
        # Delegation, not a new refusal vocabulary: until the Gate-0 v2
        # attestation pair exists there is nothing to admit, and Foundation's
        # reference refusal already says that precisely.
        return RefusingHostSourceAdmissionProvider().admit_host_source()
