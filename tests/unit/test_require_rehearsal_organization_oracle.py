"""`require_rehearsal.main` end to end, with the network replaced and a real
`RehearsalReceipt.v2`.

The pure halves are covered in `tests/architecture/test_lane3_execution_oracle.py`.
This file proves the wiring:
- the oracle selects a run, reads that run's receipt, and binds the two;
- a receipt from another attempt is refused;
- the checked-in, unprovisioned topology refuses before any network call.
"""

from __future__ import annotations

import copy
import json
import pathlib
import sys
from typing import Any

import pytest
from dotmac_deployment_foundation.rehearsal import ExecutionRunBindingV1

from tests.unit.foundation_v3_support import WHEEL
from tests.unit.test_deployment_foundation_rehearsal_receipt_v2 import (
    REVISION,
    Subject,
    _build,
    subject,  # noqa: F401 - pytest fixture, used by name
)

REPO = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))

import require_rehearsal  # noqa: E402

LAUNCHER = "e" * 40
REPO_ID = 1397614141
GROUP_ID = 4
ENV_ID = 23103080999
RUN_ID = 4242

TOPOLOGY: dict[str, Any] = {
    "schema": "Lane3ExecutionTopology.v1",
    "starter_repository": "michaelayoade/dotmac_starter_mt",
    "execution_repository": "dotmac-tech/lane3-exposure-execution",
    "execution_repository_id": REPO_ID,
    "execution_owner_id": 335992433,
    "workflow_path": ".github/workflows/lane3-exposure-rehearsal.yml",
    "environment": {
        "name": "lane3-rehearsal-protected",
        "id": ENV_ID,
        "reviewer": "michaelayoade",
    },
    "runner_group": {"name": "lane3-exposure-protected", "id": GROUP_ID},
    "admitted_launcher_revisions": [LAUNCHER],
    "receipt_artifact": "lane3-rehearsal-receipt",
    "admission_evidence": "docs/LANE3_EXECUTION_TOPOLOGY.md#7 run 1",
}

RUN: dict[str, Any] = {
    "id": RUN_ID,
    "run_attempt": 1,
    "repository": {"id": REPO_ID},
    "path": TOPOLOGY["workflow_path"],
    "event": "workflow_dispatch",
    "head_branch": "main",
    "head_sha": LAUNCHER,
    "display_title": f"lane3 starter={REVISION} candidate=0.4.0a2",
    "status": "completed",
    "conclusion": "success",
    "run_started_at": "2026-10-05T10:00:00Z",
    "html_url": "https://example.invalid/run/4242",
}


def _network(
    monkeypatch: pytest.MonkeyPatch, receipt: bytes, *, run: dict[str, Any] = RUN
) -> list[str]:
    calls: list[str] = []

    def fake_list(url: str, key: str, token: str) -> list[dict[str, Any]]:
        calls.append(url)
        return {
            "workflow_runs": [run],
            "jobs": [{"id": 1, "runner_group_id": GROUP_ID}],
            "artifacts": [{"id": 9, "expired": False}],
        }[key]

    def fake_fetch(url: str, token: str) -> Any:
        calls.append(url)
        assert url.endswith("/approvals")
        return [
            {
                "state": "approved",
                "user": {"login": "michaelayoade"},
                "environments": [{"id": ENV_ID}],
            }
        ]

    monkeypatch.setattr(require_rehearsal, "_list", fake_list)
    monkeypatch.setattr(require_rehearsal, "_fetch", fake_fetch)
    monkeypatch.setattr(require_rehearsal, "_receipt_bytes", lambda *a, **k: receipt)
    return calls


def _main(tmp_path: pathlib.Path, topology: dict[str, Any] | None) -> int:
    path = tmp_path / "lane3-execution.json"
    path.write_text(json.dumps(topology if topology is not None else {}))
    return require_rehearsal.main(
        [
            REVISION,
            "--repo",
            "michaelayoade/dotmac_starter_mt",
            "--topology",
            str(path),
            "--receipt-out",
            str(tmp_path / "receipt.json"),
            "--artifact-digest",
            WHEEL,
        ]
    )


def test_a_receipt_from_the_selected_run_publishes(
    subject: Subject,  # noqa: F811
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    receipt = _build(
        subject,
        execution_run=ExecutionRunBindingV1(
            repository_id=REPO_ID, run_id=RUN_ID, run_attempt=1
        ),
    )
    _network(monkeypatch, receipt.canonical_bytes())
    assert _main(tmp_path, TOPOLOGY) == require_rehearsal.EXIT_OK
    out = capsys.readouterr().out
    assert f"rehearsal_runner_revision={REVISION}" in out
    assert f"rehearsal_launcher_revision={LAUNCHER}" in out
    assert (tmp_path / "receipt.json").read_bytes() == receipt.canonical_bytes()


def test_a_receipt_from_another_attempt_of_the_selected_run_is_refused(
    subject: Subject,  # noqa: F811
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The selected run is attempt 2; the receipt is attempt 1's, which passed."""
    receipt = _build(
        subject,
        execution_run=ExecutionRunBindingV1(
            repository_id=REPO_ID, run_id=RUN_ID, run_attempt=1
        ),
    )
    _network(monkeypatch, receipt.canonical_bytes(), run={**RUN, "run_attempt": 2})
    assert _main(tmp_path, TOPOLOGY) == require_rehearsal.EXIT_REFUSED
    assert "from another" in capsys.readouterr().err


def test_a_v1_receipt_is_refused_by_schema(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _network(monkeypatch, json.dumps({"schema": "RehearsalReceipt.v1"}).encode())
    assert _main(tmp_path, TOPOLOGY) == require_rehearsal.EXIT_REFUSED
    assert "history, not publication evidence" in capsys.readouterr().err


def test_a_topology_for_another_repository_is_refused(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = _network(monkeypatch, b"")
    elsewhere = copy.deepcopy(TOPOLOGY)
    elsewhere["starter_repository"] = "someone/else"
    assert _main(tmp_path, elsewhere) == require_rehearsal.EXIT_REFUSED
    assert calls == []


def test_the_checked_in_topology_refuses_before_any_network_call(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    calls = _network(monkeypatch, b"")
    checked_in = json.loads((REPO / ".github" / "lane3-execution.json").read_text())
    assert _main(tmp_path, checked_in) == require_rehearsal.EXIT_REFUSED
    assert calls == []
    assert "REFUSED" in capsys.readouterr().err
