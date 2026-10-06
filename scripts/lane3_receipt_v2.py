#!/usr/bin/env python3
"""D4: the Lane 3 side that produces ``RehearsalReceipt.v2``, and only that side.

``RehearsalReceipt.v2`` (#770) is the contract the publication oracle reads, and
``build_receipt_v2`` is its only constructor. This module is the runner-side
caller: it gathers the inputs ``build_receipt_v2`` takes from where each one is
ALLOWED to come from, refuses the ones that cannot be trusted, and writes a
receipt the oracle's own reader has already accepted.

Starter-owned execution tooling, deliberately OUTSIDE Foundation ``src/``. It
uses Foundation's public API only (``build_receipt_v2``,
``RehearsalReceiptV2.from_json``, ``require_execution_run``,
``ExecutionRunBindingV1``, ``Digest``), so landing or changing it costs the
candidate nothing; it moves the release revision, like every other runner fix
(``docs/BUILD_ONCE_CUTOVER_ROADMAP.md`` freeze-boundary table, row 3).

## Where each input comes from

======================  =====================================================
plan, grant, outcome    the trusted CP-rendered ``FoundationExecutionPlanV3``,
                        the ``ExecutionGrant`` only ``authorize_v3()`` issues,
                        and the ``DeploymentOutcome`` of executing that plan.
                        NOT AVAILABLE in this lane yet: :func:`acquire_authority`
                        and :func:`execute_authorized_plan` refuse, naming what
                        must exist first
execution run           the Actions runtime's own coordinates, compared with the
                        pinned topology (:func:`execution_run_from_environment`)
probe vantage           ``<record-key>@<version>`` of the private topology record;
                        never an address
evidence bundle         the SHA-256 of the ENCRYPTED bundle as uploaded
                        (:func:`evidence_bundle_digest` refuses plaintext)
results                 the sixteen rows, each from the phase that measured it
======================  =====================================================

## The run binding is a consistency check, not trust

Environment variables are set by the runtime and readable by the job, but a
job step could overwrite them, so a value read here is not proof of anything.
What makes the binding hold is the ORACLE: ``require_rehearsal`` selects one run
by its API and refuses a receipt whose ``execution_run`` names any other
(``require_execution_run``). This module refuses early when the runtime's own
coordinates already contradict the pinned topology, so a receipt that could
never be accepted is not produced at all.

Exit codes are the repository's three: 0 a receipt was written, 1 refused, 2 the
question cannot be answered here (today, always: no trusted plan provider).
"""

from __future__ import annotations

import argparse
import os
import pathlib
import sys
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Final

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from dotmac_deployment_foundation.digest import Digest
from dotmac_deployment_foundation.errors import SpecError
from dotmac_deployment_foundation.rehearsal import (
    ExecutionRunBindingV1,
    RehearsalReceiptV2,
    RequirementResult,
    build_receipt_v2,
    require_execution_run,
)
from lane3_execution import Lane3ExecutionTopology, TopologyRefused, load_topology

if TYPE_CHECKING:  # pragma: no cover - typing only
    from dotmac_deployment_foundation.authorization import ExecutionGrant
    from dotmac_deployment_foundation.engine.run import DeploymentOutcome
    from dotmac_deployment_foundation.execution_plan_v3 import (
        FoundationExecutionPlanV3,
    )

EXIT_OK, EXIT_REFUSED, EXIT_INDETERMINATE = 0, 1, 2

#: The two encodings `age` writes. Decision 9 adopted an offline `age`
#: recipient; anything else uploaded as "the evidence bundle" is plaintext or a
#: format nobody decided on, and its digest would bind the wrong thing.
AGE_HEADERS: Final = (b"age-encryption.org/v1\n", b"-----BEGIN AGE ENCRYPTED FILE-----")

#: What a trusted run of this lane needs before a v2 receipt can exist, by
#: name, so a refusal cites them instead of a reader re-deriving them. None of
#: these is decidable from this repository.
PRECONDITIONS: Final = (
    "trusted_cp_v3_plan_provider: a CP-rendered FoundationExecutionPlanV3 "
    "delivered to the launcher through a verified channel",
    "control_v2_pair_verifier: an installed AuthorizationVerifier attesting the "
    "Control V2 authorization-and-dispatch pair, so authorize_v3() can issue the "
    "ExecutionGrant",
    "executor_drive: the public Executor driven IN-PROCESS for items 1 (apply "
    "under lock) and 8 (provoked rollback). Q1 answered 2026-10-06: possible "
    "through the public API with no Foundation src/ change, but only with a "
    "Starter-owned HostSourceAdmissionProvider over admit_host_source (the CLI "
    "hard-codes RefusingHostSourceAdmissionProvider), which stays refusing "
    "until Gate-0 attestation exists",
    "topology_record: the OpenBao record "
    "secret/dotmac/starter/lane3/vantage-topology, read with the job's JWT role",
    "lane3_ssh_ca: short-lived lane3-ssh/ certificates for observer and "
    "inside-jump, replacing the static keys",
    "admitted_topology: .github/lane3-execution.json carrying admission_evidence",
)


class ReceiptRefused(Exception):
    """An input contradicts what a v2 receipt may bind. Exit 1."""


class AuthorityUnavailable(Exception):
    """The trusted inputs cannot be obtained in this environment. Exit 2."""

    def __init__(self, missing: Sequence[str]) -> None:
        self.missing = tuple(missing)
        super().__init__(
            "a RehearsalReceipt.v2 cannot be produced here: " + "; ".join(self.missing)
        )


def _positive(environ: Mapping[str, str], name: str) -> int:
    value = environ.get(name, "")
    if not value.isdigit() or int(value) < 1:
        raise ReceiptRefused(
            f"{name} is {value!r}; this does not run as an Actions job, so it "
            "has no run a receipt could bind"
        )
    return int(value)


def execution_run_from_environment(
    environ: Mapping[str, str], *, topology: Lane3ExecutionTopology
) -> ExecutionRunBindingV1:
    """This job's run coordinates, refused if they are not the pinned surface."""
    repository_id = _positive(environ, "GITHUB_REPOSITORY_ID")
    owner_id = _positive(environ, "GITHUB_REPOSITORY_OWNER_ID")
    if repository_id != topology.execution_repository_id:
        raise ReceiptRefused(
            f"this job runs in repository {repository_id} and the pinned Lane 3 "
            f"execution repository is {topology.execution_repository_id}"
        )
    if owner_id != topology.execution_owner_id:
        raise ReceiptRefused(
            f"this job's repository owner is {owner_id} and the pinned owner is "
            f"{topology.execution_owner_id}"
        )
    expected = (
        f"{topology.execution_repository}/{topology.workflow_path}@refs/heads/main"
    )
    for name, wanted in (
        ("GITHUB_EVENT_NAME", "workflow_dispatch"),
        ("GITHUB_REF", "refs/heads/main"),
        ("GITHUB_WORKFLOW_REF", expected),
    ):
        if environ.get(name, "") != wanted:
            raise ReceiptRefused(
                f"{name} is {environ.get(name, '')!r}, not {wanted!r}. Only a "
                "dispatch of the pinned workflow on main can produce a receipt "
                "the oracle would select"
            )
    return ExecutionRunBindingV1(
        repository_id=repository_id,
        run_id=_positive(environ, "GITHUB_RUN_ID"),
        run_attempt=_positive(environ, "GITHUB_RUN_ATTEMPT"),
    )


def evidence_bundle_digest(payload: bytes) -> str:
    """SHA-256 of the evidence bundle exactly as uploaded — ciphertext only."""
    if not payload.startswith(AGE_HEADERS):
        raise ReceiptRefused(
            "the evidence bundle is not age-encrypted. Raw probe evidence carries "
            "topology, and the receipt binds the ciphertext that is published "
            "(docs/LANE3_EXECUTION_TOPOLOGY.md § 5), never a plaintext bundle"
        )
    return str(Digest.of(payload))


def assemble_receipt(
    *,
    foundation_revision: str,
    foundation_artifact_digest: str,
    descriptor_digest: str,
    execution_plan: FoundationExecutionPlanV3,
    grant: ExecutionGrant,
    execution_outcome: DeploymentOutcome,
    fixture_digest: str,
    evidence_bundle: bytes,
    controller_identity: str,
    lease_id: str,
    probe_vantage_ref: str,
    execution_run: ExecutionRunBindingV1,
    started_at: str,
    finished_at: str,
    results: Sequence[RequirementResult],
) -> RehearsalReceiptV2:
    """Build the v2 receipt and prove the oracle's reader accepts its bytes.

    ``build_receipt_v2`` refuses every chain break; this adds the half it cannot
    see. The receipt is re-read from its canonical bytes with the same
    closed-key-set reader ``require_rehearsal`` uses and tied to ``execution_run``
    by the same check, so what is written is what will be read.
    """
    try:
        receipt = build_receipt_v2(
            foundation_revision=foundation_revision,
            foundation_artifact_digest=foundation_artifact_digest,
            descriptor_digest=descriptor_digest,
            execution_plan=execution_plan,
            grant=grant,
            execution_outcome=execution_outcome,
            fixture_digest=fixture_digest,
            evidence_bundle_digest=evidence_bundle_digest(evidence_bundle),
            controller_identity=controller_identity,
            lease_id=lease_id,
            probe_vantage_ref=probe_vantage_ref,
            execution_run=execution_run,
            started_at=started_at,
            finished_at=finished_at,
            results=results,
        )
        again = RehearsalReceiptV2.from_json(receipt.canonical_bytes())
        require_execution_run(again, run=execution_run)
    except SpecError as exc:
        raise ReceiptRefused(str(exc)) from exc
    if again.content != receipt.content:  # pragma: no cover - reader invariant
        raise ReceiptRefused("the receipt does not round-trip through its reader")
    return again


def write_receipt(receipt: RehearsalReceiptV2, path: pathlib.Path) -> str:
    """Write the canonical bytes, create-only. Returns the receipt digest."""
    with path.open("xb") as handle:
        handle.write(receipt.canonical_bytes())
    return receipt.sha256_digest()


def acquire_authority() -> tuple[FoundationExecutionPlanV3, ExecutionGrant]:
    """The trusted plan and its grant. Refuses: no provider exists yet."""
    raise AuthorityUnavailable(
        [p for p in PRECONDITIONS if p.startswith(("trusted_cp", "control_v2"))]
    )


def execute_authorized_plan(
    plan: FoundationExecutionPlanV3, grant: ExecutionGrant
) -> DeploymentOutcome:
    """Drive the Executor under ``grant``. Refuses until host-source admission exists.

    Q1's answer fixes the shape: ``Executor(spec, effects, grant,
    execution_plan=..., admission_provider=..., exposure_effects=...)`` under
    ``deployment_lock``, then ``.run(plan, lock=held)`` (and ``.rollback`` for
    item 8). ``Executor.run`` verifies the host source first, so without an
    admission provider that can attest there is nothing to drive.
    """
    raise AuthorityUnavailable(
        [p for p in PRECONDITIONS if p.startswith("executor_drive")]
    )


def main(
    argv: list[str] | None = None, *, environ: Mapping[str, str] | None = None
) -> int:
    parser = argparse.ArgumentParser(
        prog="lane3_receipt_v2.py",
        description="Produce RehearsalReceipt.v2 for one Lane 3 execution run.",
    )
    parser.add_argument(
        "--topology",
        default=str(
            pathlib.Path(__file__).resolve().parents[1]
            / ".github"
            / "lane3-execution.json"
        ),
    )
    parser.add_argument("--receipt-out", required=True)
    args = parser.parse_args(argv)
    env = os.environ if environ is None else environ
    try:
        topology = load_topology(pathlib.Path(args.topology))
        execution_run_from_environment(env, topology=topology)
        acquire_authority()
    except TopologyRefused as exc:
        print(f"INDETERMINATE: {exc}", file=sys.stderr)
        return EXIT_INDETERMINATE
    except AuthorityUnavailable as exc:
        print(f"INDETERMINATE: {exc}", file=sys.stderr)
        return EXIT_INDETERMINATE
    except ReceiptRefused as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return EXIT_REFUSED
    # Unreachable while `acquire_authority` refuses. When a provider lands, the
    # plan is executed and the receipt assembled here — not before.
    raise AssertionError(  # pragma: no cover
        "acquire_authority returned without a provider"
    )


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
