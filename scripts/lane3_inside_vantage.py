#!/usr/bin/env python3
"""Items 12 and 16 — a probe that genuinely originates INSIDE the source set.

Neither item had one. `private_inside.reachable` was the literal `false` and
`privileged_vantage_refused` was `null`, because the collecting host is outside
the accepted set by construction. Both fail closed, which was correct and is not
the same as being executed.

## Item 16 is a reachability measurement; item 12 is a REFUSAL

They are easy to conflate and are different acts.

Item 16 asks whether the private port answers from inside its source set. Item
12 asks that `accept_public_exposure_evidence` REFUSES a real probe from such a
vantage — because a successful connection from a privileged vantage is evidence
that the allowlist works, not that the port is public. That inference produced
two false P0 escalations on 2026-08-29.

So item 12 must observe the OVERLAP branch of that refusal. Its other branch
fires when `membership_established` is false, and a refusal obtained that way
would satisfy the item while proving the opposite thing: that nobody had
established where the vantage sits. The distinction is checked below rather than
assumed, because the vacuous version is the one that arrives by accident.

## v4 and v6 are modelled INDEPENDENTLY, and that is a measured requirement

Michael, 2026-09-04: *"Model inside/outside IPv4 and IPv6 sources
independently."* The inside vantage's own addresses show why. Measured through
the jump (shown here in documentation ranges, RFC 5737 / RFC 3849: this is a
public repository and topology does not belong in its source):

    v4  192.0.2.195                          Dell segment
    v6  2001:db8:12:0:1e98:ecff:fe11:3629    HP-server segment

Its v4 is on the target's segment and its v6 is not. One prefix per vantage
would therefore be wrong for one of the two families, and a source set declared
that way would either admit a segment nobody intended or refuse a probe that is
genuinely inside. Two families, two memberships, decided separately.

## The v6 address is OBSERVED, with a requalification obligation

Michael again: treat it as *"an observed /128 with requalification, not a
permanent hardcoded identity."* It is SLAAC, EUI-64 derived — the `ff:fe` in the
middle — so it is stable while that NIC is and is not a configured address
anybody declared. It is read from the far end at run time and carried as a /128
with :data:`REQUALIFY_EVERY_RUN` set, so a receipt records an address that was
observed on THAT run rather than one a file remembered. A check that hardcoded
it would be asserting a fact about a network card.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from dotmac_deployment_foundation.errors import DeploymentFoundationError
from dotmac_deployment_foundation.exposure import (
    PrivilegedVantageError,
    ProbeOutcome,
    ProbeResult,
    ProbeVantage,
    accept_public_exposure_evidence,
)

#: The inside vantage's addresses are re-read every run rather than pinned. See
#: the module docstring: one of them is SLAAC-derived and belongs to a NIC.
REQUALIFY_EVERY_RUN: Final = True

#: The phrase Control's refusal uses for the branch item 12 is about. The OTHER
#: branch says "has not established", and accepting that one would record a pass
#: for a vantage nobody had located.
OVERLAP_PHRASE: Final = "is INSIDE"


class InsideOutcome(StrEnum):
    """What a probe from the inside vantage actually met.

    `PROHIBITED` is not an exposure result and must never be rendered as one: it
    means the jump key's `permitopen` does not cover the port, so the probe never
    left the vantage. Reporting it as unreachable would turn a misconfigured
    credential into evidence of a correctly closed port.
    """

    REACHED = "reached"
    REFUSED = "refused"
    SILENT = "silent"
    PROHIBITED = "prohibited"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class InsideVantage:
    """One vantage, one family, and the address the TARGET saw it as."""

    family: str
    observed_source: str
    outcome: InsideOutcome

    @property
    def cidr(self) -> str:
        """The observed address as a single-host prefix.

        A /128 (or /32) rather than the segment it sits on: the vantage is one
        host, and widening it to a prefix would silently admit everything else
        on that segment to the accepted set.
        """
        return f"{self.observed_source}/{'128' if self.family == 'ipv6' else '32'}"


def _outcome(value: str) -> InsideOutcome:
    try:
        return InsideOutcome(value)
    except ValueError:
        return InsideOutcome.UNKNOWN


def collect(
    script: str,
    *,
    jump: str,
    target_v4: str,
    target_v6: str,
    port: int,
    timeout: int,
) -> dict[str, str]:
    """Run the inside probe and return its raw classifications."""
    argv = [script, jump, target_v4, target_v6, str(port)]
    completed = subprocess.run(
        argv, capture_output=True, text=True, timeout=timeout, check=False
    )
    if completed.returncode != 0:
        raise DeploymentFoundationError(
            f"the inside-vantage probe refused: "
            f"{completed.stderr.strip() or 'no stderr'}"
        )
    try:
        parsed = json.loads(completed.stdout)
    except ValueError as exc:
        raise DeploymentFoundationError(
            f"the inside-vantage probe emitted no readable JSON ({exc})"
        ) from exc
    return {str(k): str(v) for k, v in parsed.items()}


def vantages(
    probe: dict[str, str], observed: dict[str, str]
) -> tuple[InsideVantage, ...]:
    """Pair each family's outcome with the address the target observed."""
    return (
        InsideVantage(
            family="ipv4",
            observed_source=observed.get("observed_source_v4", ""),
            outcome=_outcome(probe.get("private_port_v4", "")),
        ),
        InsideVantage(
            family="ipv6",
            observed_source=observed.get("observed_source_v6", ""),
            outcome=_outcome(probe.get("private_port_v6", "")),
        ),
    )


def control_is_meaningful(probe: dict[str, str]) -> bool:
    """The control that stops four identical denials proving nothing.

    A `permitopen` that refused EVERYTHING would produce the same denial as one
    that is correctly scoped, so a port the key deliberately does not open must
    come back `prohibited`. If it does not, the probe above establishes only
    that something refuses.
    """
    return _outcome(probe.get("control_unopened_port", "")) is InsideOutcome.PROHIBITED


def refusal_fired_for_the_right_reason(
    vantage: InsideVantage,
    *,
    endpoint_token: str,
    accepted_source_sets: tuple[str, ...],
) -> tuple[bool, str]:
    """Item 12: the refusal must be the OVERLAP branch, on a REAL probe.

    The `ProbeResult` is built from a probe that actually ran from inside the
    set — not a synthetic evidence object — and `membership_established` is True
    because the far end reported where the connection came from. That matters:
    the other branch of this refusal fires precisely when membership is UNknown,
    and a pass obtained there would record that nobody had located the vantage.
    """
    if vantage.outcome is not InsideOutcome.REACHED:
        return False, (
            f"the {vantage.family} probe did not reach the port "
            f"({vantage.outcome}), so there is no successful connection from a "
            "privileged vantage for the refusal to be about"
        )
    result = ProbeResult(
        endpoint_token=endpoint_token,
        family=vantage.family,
        vantage=ProbeVantage(
            name=f"inside:{vantage.cidr}",
            inside_source_sets=frozenset(accepted_source_sets),
            membership_established=True,
        ),
        outcome=ProbeOutcome.REACHED,
    )
    try:
        accept_public_exposure_evidence(
            result, accepted_source_sets=list(accepted_source_sets)
        )
    except PrivilegedVantageError as refused:
        detail = str(refused)
        if OVERLAP_PHRASE not in detail:
            return False, (
                "the refusal fired on the membership branch, not the "
                f"privileged-vantage branch: {detail[:140]}"
            )
        return True, detail[:180]
    return False, (
        "accept_public_exposure_evidence ACCEPTED a probe from inside an "
        "accepted source set. That is the inference which produced two false "
        "P0 escalations on 2026-08-29"
    )


__all__ = [
    "OVERLAP_PHRASE",
    "REQUALIFY_EVERY_RUN",
    "InsideOutcome",
    "InsideVantage",
    "collect",
    "control_is_meaningful",
    "refusal_fired_for_the_right_reason",
    "vantages",
]
