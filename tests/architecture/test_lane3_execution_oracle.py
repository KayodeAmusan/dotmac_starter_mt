"""The amended publication oracle: one pinned organization workflow, or nothing.

ADR-0070's 2026-10-05 amendment moves Lane 3 to an organization-owned
execution repository. `scripts/lane3_execution.py` holds what the oracle reads
from it, and every refusal below is planted, because a gate nobody has watched
refuse is a gate nobody should trust (ADR-0018).

The first test is the one that states today's state: the checked-in topology
records no admitted surface, so the oracle refuses before any network call.
"""

from __future__ import annotations

import copy
import pathlib
import sys
from typing import Any

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))

from lane3_execution import (  # noqa: E402
    GRAMMAR_GUARD_PROVEN,
    ExecutionRunRefused,
    TopologyRefused,
    load_topology,
    parse_run_name,
    parse_topology,
    require_run_context,
    select_runs,
)
from require_rehearsal import RehearsalMissing, decide  # noqa: E402

SHA = "a" * 40
OTHER = "b" * 40
LAUNCHER = "c" * 40
REPO_ID = 1397614141
GROUP_ID = 4
ENV_ID = 23103080999

PROVISIONED: dict[str, Any] = {
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


def _topology(**over: Any):  # type: ignore[no-untyped-def]
    document = copy.deepcopy(PROVISIONED)
    document.update(over)
    return parse_topology(document)


def _run(**over: Any) -> dict[str, Any]:
    run: dict[str, Any] = {
        "id": 10,
        "run_attempt": 1,
        "repository": {"id": REPO_ID},
        "path": PROVISIONED["workflow_path"],
        "event": "workflow_dispatch",
        "head_branch": "main",
        "head_sha": LAUNCHER,
        "display_title": f"lane3 starter={SHA} candidate=0.4.0a2",
        "status": "completed",
        "conclusion": "success",
        "run_started_at": "2026-10-05T10:00:00Z",
        "html_url": "https://example.invalid/run/10",
    }
    run.update(over)
    return run


# ── today: the checked-in topology refuses ─────────────────────────────────


def test_the_checked_in_topology_is_not_an_admitted_surface() -> None:
    """The designed state until § 7's admission evidence exists."""
    with pytest.raises(TopologyRefused):
        load_topology(REPO / ".github" / "lane3-execution.json")


def test_a_fully_provisioned_topology_parses() -> None:
    topology = _topology()
    assert topology.execution_repository_id == REPO_ID
    assert topology.admitted_launcher_revisions == frozenset({LAUNCHER})


@pytest.mark.parametrize(
    "path",
    [
        "execution_repository_id",
        "execution_owner_id",
        "environment.id",
        "runner_group.id",
    ],
)
@pytest.mark.parametrize("value", [None, 0, -1, True, "1397614141"])
def test_every_immutable_id_must_be_recorded(path: str, value: object) -> None:
    document = copy.deepcopy(PROVISIONED)
    node = document
    *parents, leaf = path.split(".")
    for part in parents:
        node = node[part]
    node[leaf] = value
    with pytest.raises(TopologyRefused, match=path):
        parse_topology(document)


@pytest.mark.parametrize("revisions", [[], ["C" * 40], ["c" * 39], [None], "c" * 40])
def test_no_launcher_is_admitted_without_a_full_commit(revisions: object) -> None:
    with pytest.raises(TopologyRefused, match="admitted_launcher_revisions"):
        _topology(admitted_launcher_revisions=revisions)


@pytest.mark.parametrize("evidence", [None, "", "   "])
def test_no_surface_is_admitted_without_admission_evidence(evidence: object) -> None:
    with pytest.raises(TopologyRefused, match="admission_evidence"):
        _topology(admission_evidence=evidence)


# ── the dispatch grammar ───────────────────────────────────────────────────


def test_the_grammar_parses_exactly_the_launcher_title() -> None:
    assert parse_run_name(f"lane3 starter={SHA} candidate=0.4.0a2") == (SHA, "0.4.0a2")


@pytest.mark.parametrize(
    "title",
    [
        f"lane3 starter={SHA.upper()} candidate=0.4.0a2",
        f"lane3 starter={SHA[:39]} candidate=0.4.0a2",
        f"lane3 starter={SHA} candidate=0.4.0a2 extra",
        f"Lane3 starter={SHA} candidate=0.4.0a2",
        f"lane3 starter={SHA} candidate=latest",
        None,
        42,
    ],
)
def test_the_grammar_refuses_anything_else(title: object) -> None:
    assert parse_run_name(title) is None


# ── selection: the population must be the pinned workflow ─────────────────


@pytest.mark.parametrize(
    "over",
    [
        {"repository": {"id": 1}},
        {"repository": None},
        {"path": ".github/workflows/other.yml"},
        {"event": "push"},
        {"event": "pull_request_target"},
        {"head_branch": "feature"},
    ],
)
def test_a_run_outside_the_pinned_workflow_refuses_the_population(
    over: dict[str, Any],
) -> None:
    with pytest.raises(ExecutionRunRefused, match="not the pinned workflow"):
        select_runs([_run(), _run(id=11, **over)], sha=SHA, topology=_topology())


def test_an_unparseable_title_refuses_until_the_grammar_guard_is_proven() -> None:
    assert GRAMMAR_GUARD_PROVEN is False
    with pytest.raises(ExecutionRunRefused, match="does not parse"):
        select_runs(
            [_run(), _run(id=11, display_title="lane3 by hand")],
            sha=SHA,
            topology=_topology(),
        )


def test_selection_projects_the_starter_revision_and_keeps_the_launcher() -> None:
    kept = select_runs(
        [_run(), _run(id=11, display_title=f"lane3 starter={OTHER} candidate=0.4.0a2")],
        sha=SHA,
        topology=_topology(),
    )
    assert [run["id"] for run in kept] == [10]
    assert kept[0]["head_sha"] == SHA
    assert kept[0]["launcher_sha"] == LAUNCHER


def test_an_older_success_does_not_mask_a_newer_failure_across_the_projection() -> None:
    """`decide`'s newest-then-check semantics survive the projection unchanged."""
    runs = [
        _run(id=10, run_started_at="2026-10-05T10:00:00Z"),
        _run(id=11, run_started_at="2026-10-05T11:00:00Z", conclusion="failure"),
    ]
    with pytest.raises(RehearsalMissing, match="not completed/success"):
        decide(select_runs(runs, sha=SHA, topology=_topology()), SHA)


def test_a_rehearsal_of_another_revision_is_not_a_rehearsal_of_this_one() -> None:
    runs = [_run(display_title=f"lane3 starter={OTHER} candidate=0.4.0a2")]
    with pytest.raises(RehearsalMissing, match="no rehearsal run exists"):
        decide(select_runs(runs, sha=SHA, topology=_topology()), SHA)


# ── the selected run's context ─────────────────────────────────────────────


def _selected() -> dict[str, Any]:
    return select_runs([_run()], sha=SHA, topology=_topology())[0]


GOOD_JOBS = [{"id": 1, "runner_group_id": GROUP_ID}]
GOOD_APPROVALS = [
    {
        "state": "approved",
        "user": {"login": "michaelayoade"},
        "environments": [{"id": ENV_ID}],
    }
]


def test_an_admitted_run_on_the_group_with_its_approval_is_accepted() -> None:
    require_run_context(
        _selected(), jobs=GOOD_JOBS, approvals=GOOD_APPROVALS, topology=_topology()
    )


def test_a_launcher_revision_that_was_not_admitted_is_refused() -> None:
    run = {**_selected(), "launcher_sha": "d" * 40}
    with pytest.raises(ExecutionRunRefused, match="not an admitted launcher"):
        require_run_context(
            run, jobs=GOOD_JOBS, approvals=GOOD_APPROVALS, topology=_topology()
        )


@pytest.mark.parametrize(
    "jobs",
    [
        [],
        [{"id": 1, "runner_group_id": 1}],
        [{"id": 1, "runner_group_id": GROUP_ID}, {"id": 2, "runner_group_id": None}],
    ],
)
def test_a_job_off_the_pinned_runner_group_is_refused(
    jobs: list[dict[str, Any]],
) -> None:
    with pytest.raises(ExecutionRunRefused, match="runner group"):
        require_run_context(
            _selected(), jobs=jobs, approvals=GOOD_APPROVALS, topology=_topology()
        )


@pytest.mark.parametrize(
    "approvals",
    [
        [],
        [{**GOOD_APPROVALS[0], "state": "rejected"}],
        [{**GOOD_APPROVALS[0], "user": {"login": "someone-else"}}],
        [{**GOOD_APPROVALS[0], "environments": [{"id": 1}]}],
        [{**GOOD_APPROVALS[0], "user": None}],
    ],
)
def test_an_unapproved_run_is_refused(approvals: list[dict[str, Any]]) -> None:
    with pytest.raises(ExecutionRunRefused, match="no approval"):
        require_run_context(
            _selected(), jobs=GOOD_JOBS, approvals=approvals, topology=_topology()
        )


# ── the release step no longer lists or downloads runs itself ─────────────


def test_the_release_step_does_not_select_or_download_a_run_separately() -> None:
    """A separate `gh run download` could read a different run from the one the
    oracle selected; the oracle reads the receipt from its own selection."""
    text = (REPO / ".github" / "workflows" / "release-facility.yml").read_text()
    assert "gh run download" not in text
    assert "gh run list --workflow exposure-rehearsal.yml" not in text
    assert "--receipt-out .rehearsal/receipt.json" in text
