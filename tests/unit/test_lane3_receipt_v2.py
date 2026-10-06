"""D4: ``scripts/lane3_receipt_v2.py``, the producer of ``RehearsalReceipt.v2``.

Nothing here contacts a host, OpenBao or GitHub. The plan, grant and outcome
come from the same fixture the Foundation v2 tests use; the run coordinates are
a synthetic Actions environment; the evidence bundle is a synthetic age header.
"""

from __future__ import annotations

import copy
import json
import pathlib
import sys
from typing import Any

import pytest
from dotmac_deployment_foundation.rehearsal import (
    REQUIRED_ITEMS,
    ExecutionRunBindingV1,
    RehearsalReceiptV2,
    RequirementResult,
    RequirementStatus,
    verify_publication,
)

from tests.unit.foundation_v3_support import CONTROLLER, WHEEL
from tests.unit.test_deployment_foundation_rehearsal_receipt_v2 import (
    REVISION,
    Subject,
    subject,  # noqa: F401 - pytest fixture, used by name
)

REPO = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))

import lane3_execution  # noqa: E402
import lane3_receipt_v2 as producer  # noqa: E402

REPO_ID = 1406738001
OWNER_ID = 335992433
WORKFLOW = ".github/workflows/lane3-exposure-rehearsal.yml"
EXECUTION_REPO = "dotmac-tech/lane3-exposure-execution"

DOCUMENT: dict[str, Any] = {
    "schema": "Lane3ExecutionTopology.v1",
    "starter_repository": "michaelayoade/dotmac_starter_mt",
    "execution_repository": EXECUTION_REPO,
    "execution_repository_id": REPO_ID,
    "execution_owner_id": OWNER_ID,
    "workflow_path": WORKFLOW,
    "environment": {
        "name": "lane3-rehearsal-protected",
        "id": 23551908838,
        "reviewer": "michaelayoade",
    },
    "runner_group": {"name": "lane3-exposure-protected", "id": 4},
    "admitted_launcher_revisions": ["e" * 40],
    "receipt_artifact": "lane3-rehearsal-receipt",
    "admission_evidence": "docs/LANE3_EXECUTION_TOPOLOGY.md#7 run 1",
}
TOPOLOGY = lane3_execution.parse_topology(DOCUMENT)

ENVIRON: dict[str, str] = {
    "GITHUB_REPOSITORY_ID": str(REPO_ID),
    "GITHUB_REPOSITORY_OWNER_ID": str(OWNER_ID),
    "GITHUB_RUN_ID": "4242",
    "GITHUB_RUN_ATTEMPT": "1",
    "GITHUB_EVENT_NAME": "workflow_dispatch",
    "GITHUB_REF": "refs/heads/main",
    "GITHUB_WORKFLOW_REF": f"{EXECUTION_REPO}/{WORKFLOW}@refs/heads/main",
}
RUN = ExecutionRunBindingV1(repository_id=REPO_ID, run_id=4242, run_attempt=1)
BUNDLE = b"age-encryption.org/v1\n-> X25519 synthetic\n--- mac\n\x00ciphertext"


def _results() -> list[RequirementResult]:
    return [
        RequirementResult(
            code=item.code,
            status=RequirementStatus.EXECUTED_PASSED,
            detail=f"{item.title} — measured",
            evidence=(f"bundle:{item.code}",),
        )
        for item in REQUIRED_ITEMS
    ]


def _assemble(subj: Subject, **overrides: Any) -> RehearsalReceiptV2:
    fields: dict[str, Any] = {
        "foundation_revision": REVISION,
        "foundation_artifact_digest": WHEEL,
        "descriptor_digest": subj.descriptor_digest,
        "execution_plan": subj.plan,
        "grant": subj.grant,
        "execution_outcome": subj.outcome,
        "fixture_digest": "sha256:" + "d" * 64,
        "evidence_bundle": BUNDLE,
        "controller_identity": CONTROLLER,
        "lease_id": "lease-1",
        "probe_vantage_ref": "inside-vantage@7",
        "execution_run": RUN,
        "started_at": "2026-10-06T10:00:00+00:00",
        "finished_at": "2026-10-06T10:40:00+00:00",
        "results": _results(),
    }
    fields.update(overrides)
    return producer.assemble_receipt(**fields)


# ── the run binding ─────────────────────────────────────────────────────────


def test_the_run_binding_comes_from_the_pinned_runtime() -> None:
    assert producer.execution_run_from_environment(ENVIRON, topology=TOPOLOGY) == RUN


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("GITHUB_REPOSITORY_ID", "1397614141"),
        ("GITHUB_REPOSITORY_OWNER_ID", "1"),
        ("GITHUB_EVENT_NAME", "pull_request"),
        ("GITHUB_EVENT_NAME", "pull_request_target"),
        ("GITHUB_REF", "refs/heads/feature"),
        (
            "GITHUB_WORKFLOW_REF",
            f"{EXECUTION_REPO}/.github/workflows/other.yml@refs/heads/main",
        ),
        ("GITHUB_WORKFLOW_REF", f"{EXECUTION_REPO}/{WORKFLOW}@refs/heads/feature"),
        ("GITHUB_RUN_ID", ""),
        ("GITHUB_RUN_ATTEMPT", "0"),
    ],
)
def test_a_run_outside_the_pinned_surface_is_refused(name: str, value: str) -> None:
    environ = {**ENVIRON, name: value}
    with pytest.raises(producer.ReceiptRefused):
        producer.execution_run_from_environment(environ, topology=TOPOLOGY)


def test_a_missing_runtime_coordinate_is_refused() -> None:
    environ = dict(ENVIRON)
    del environ["GITHUB_RUN_ID"]
    with pytest.raises(producer.ReceiptRefused, match="GITHUB_RUN_ID"):
        producer.execution_run_from_environment(environ, topology=TOPOLOGY)


# ── the evidence bundle ─────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "payload",
    [b"age-encryption.org/v1\nbody", b"-----BEGIN AGE ENCRYPTED FILE-----\nbody"],
)
def test_both_age_encodings_are_accepted(payload: bytes) -> None:
    assert producer.evidence_bundle_digest(payload).startswith("sha256:")


@pytest.mark.parametrize("payload", [b'{"probes": {}}', b"", b"PK\x03\x04zip"])
def test_a_plaintext_bundle_is_refused(payload: bytes) -> None:
    with pytest.raises(producer.ReceiptRefused, match="not age-encrypted"):
        producer.evidence_bundle_digest(payload)


# ── assembly ────────────────────────────────────────────────────────────────


def test_an_assembled_receipt_is_what_the_oracle_reads(
    subject: Subject,  # noqa: F811
) -> None:
    receipt = _assemble(subject)
    verify_publication(receipt, revision=REVISION)
    again = RehearsalReceiptV2.from_json(receipt.canonical_bytes())
    assert again.content == receipt.content
    assert again.execution_run == RUN
    assert receipt.content["evidence_bundle_digest"] == producer.evidence_bundle_digest(
        BUNDLE
    )


def test_a_chain_break_refuses_as_this_lanes_refusal(
    subject: Subject,  # noqa: F811
) -> None:
    with pytest.raises(producer.ReceiptRefused):
        _assemble(subject, foundation_artifact_digest="sha256:" + "0" * 64)


def test_a_plaintext_bundle_refuses_assembly(
    subject: Subject,  # noqa: F811
) -> None:
    with pytest.raises(producer.ReceiptRefused, match="not age-encrypted"):
        _assemble(subject, evidence_bundle=b'{"vantage": {}}')


def test_a_vantage_address_refuses_assembly(
    subject: Subject,  # noqa: F811
) -> None:
    with pytest.raises(producer.ReceiptRefused):
        _assemble(subject, probe_vantage_ref="vantage.example.net@1")


def test_the_receipt_is_written_create_only(
    subject: Subject,  # noqa: F811
    tmp_path: pathlib.Path,
) -> None:
    receipt = _assemble(subject)
    out = tmp_path / "receipt.json"
    digest = producer.write_receipt(receipt, out)
    assert digest == receipt.sha256_digest()
    assert RehearsalReceiptV2.from_json(out.read_bytes()).content == receipt.content
    with pytest.raises(FileExistsError):
        producer.write_receipt(receipt, out)


# ── the integration points refuse, naming what is missing ───────────────────


def test_authority_is_unavailable_and_says_why() -> None:
    with pytest.raises(producer.AuthorityUnavailable) as caught:
        producer.acquire_authority()
    missing = caught.value.missing
    assert any(m.startswith("trusted_cp_v3_plan_provider") for m in missing)
    assert any(m.startswith("control_v2_pair_verifier") for m in missing)


def test_execution_is_unavailable_until_q1_is_answered(
    subject: Subject,  # noqa: F811
) -> None:
    with pytest.raises(producer.AuthorityUnavailable, match="Q1"):
        producer.execute_authorized_plan(subject.plan, subject.grant)


# ── the CLI's three exits ───────────────────────────────────────────────────


def _topology_file(tmp_path: pathlib.Path, document: dict[str, Any]) -> str:
    path = tmp_path / "lane3-execution.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    return str(path)


def test_the_checked_in_topology_is_indeterminate_today(tmp_path: pathlib.Path) -> None:
    # The real file: admission_evidence is null until § 7's proofs exist.
    out = tmp_path / "receipt.json"
    assert producer.main(["--receipt-out", str(out)], environ=ENVIRON) == 2
    assert not out.exists()


def test_an_admitted_topology_is_still_indeterminate_without_a_provider(
    tmp_path: pathlib.Path,
) -> None:
    out = tmp_path / "receipt.json"
    argv = ["--topology", _topology_file(tmp_path, DOCUMENT), "--receipt-out", str(out)]
    assert producer.main(argv, environ=ENVIRON) == 2
    assert not out.exists()


def test_a_foreign_run_is_refused_before_authority_is_asked(
    tmp_path: pathlib.Path,
) -> None:
    out = tmp_path / "receipt.json"
    argv = ["--topology", _topology_file(tmp_path, DOCUMENT), "--receipt-out", str(out)]
    environ = {**ENVIRON, "GITHUB_REPOSITORY_ID": "1397614141"}
    assert producer.main(argv, environ=environ) == 1
    assert not out.exists()


def test_an_unadmitted_topology_never_reaches_the_run_check(
    tmp_path: pathlib.Path,
) -> None:
    document = copy.deepcopy(DOCUMENT)
    document["admission_evidence"] = None
    argv = ["--topology", _topology_file(tmp_path, document), "--receipt-out", "x"]
    assert producer.main(argv, environ={}) == 2
