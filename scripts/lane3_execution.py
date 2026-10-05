"""Lane 3's organization execution topology, as the publication oracle reads it.

``docs/LANE3_EXECUTION_TOPOLOGY.md`` moves Lane 3 out of this public,
personal-account repository into an organization-owned execution repository,
behind a workflow-restricted runner group and a protected Environment
(ADR-0070, amendment 2026-10-05). The publication oracle therefore no longer
reads runs of a workflow in THIS repository. It reads runs of ONE pinned
workflow in ONE pinned repository, identified by immutable IDs checked in here
(``.github/lane3-execution.json``), so changing which runs can satisfy
publication is a reviewed change to this repository.

Stdlib only, like the rest of the oracle's first half: it must be importable
by a test with nothing installed, and by the release job before the candidate
venv exists.

## Fail closed while unprovisioned

Every ID in the checked-in file is ``null`` until provisioning records the real
coordinates AND the admission evidence of § 7 exists. :func:`load_topology`
refuses a topology carrying any ``null``, an empty admitted-launcher list, or no
admission-evidence coordinate. That refusal is the designed state of this lane
today, not a failure to route around: there is no admitted execution surface,
so there is nothing a receipt could truthfully have come from.

## The dispatch grammar is shared, and that is what makes exclusion safe

The oracle selects runs whose ``display_title`` names the Starter revision
under release. A run whose title does not parse is EXCLUDED — and that is safe
only because the launcher's first step refuses exactly the same grammar before
it checks anything out, so such a run cannot have rehearsed any revision.
:data:`RUN_NAME` and :func:`parse_run_name` are that one grammar. The launcher
lives in another repository; it must carry this exact pattern, and the D-S3
guard that compares them is the precondition for this exclusion being sound.
Until that guard exists, :func:`select_runs` refuses a population containing
an unparseable title rather than excluding it.
"""

from __future__ import annotations

import dataclasses
import json
import pathlib
import re
from typing import Any, Final

SCHEMA: Final = "Lane3ExecutionTopology.v1"

#: ``lane3 starter=<40 lowercase hex> candidate=<version>``. The version grammar
#: is PEP 440's public form restricted to what this facility allocates
#: (``0.4.0a2``): digits, dots and one pre-release segment.
RUN_NAME: Final = re.compile(
    r"lane3 starter=(?P<starter>[0-9a-f]{40}) "
    r"candidate=(?P<candidate>[0-9]+(?:\.[0-9]+){2}(?:(?:a|b|rc)[0-9]+)?)"
)

#: Flipped to True only by the change that adds the cross-repository grammar
#: guard (D-S3). While False, an unparseable title REFUSES instead of being
#: excluded, because exclusion is only safe when the launcher provably refuses
#: the same grammar first.
GRAMMAR_GUARD_PROVEN: Final = False


class TopologyRefused(Exception):
    """The checked-in topology cannot identify an admitted execution surface."""


class ExecutionRunRefused(Exception):
    """A listed or selected execution run cannot be evidence for this release."""


@dataclasses.dataclass(frozen=True, slots=True)
class Lane3ExecutionTopology:
    starter_repository: str
    execution_repository: str
    execution_repository_id: int
    execution_owner_id: int
    workflow_path: str
    environment_name: str
    environment_id: int
    reviewer: str
    runner_group_name: str
    runner_group_id: int
    admitted_launcher_revisions: frozenset[str]
    receipt_artifact: str
    admission_evidence: str


def _positive_int(document: dict[str, Any], path: str) -> int:
    node: Any = document
    for part in path.split("."):
        node = node.get(part) if isinstance(node, dict) else None
    if isinstance(node, bool) or not isinstance(node, int) or node < 1:
        raise TopologyRefused(
            f"{path} is {node!r}. The Lane 3 execution surface is not provisioned "
            "until every immutable ID is recorded; a name alone can be renamed or "
            "recreated, which is the substitution an ID refuses"
        )
    return node


def _text(document: dict[str, Any], path: str) -> str:
    node: Any = document
    for part in path.split("."):
        node = node.get(part) if isinstance(node, dict) else None
    if not isinstance(node, str) or not node.strip():
        raise TopologyRefused(f"{path} is empty or missing")
    return node


def parse_topology(document: Any) -> Lane3ExecutionTopology:
    """Parse the checked-in topology, refusing anything not fully admitted."""
    if not isinstance(document, dict) or document.get("schema") != SCHEMA:
        raise TopologyRefused(f"expected a {SCHEMA} document")
    revisions = document.get("admitted_launcher_revisions")
    if (
        not isinstance(revisions, list)
        or not revisions
        or any(
            not isinstance(r, str) or not re.fullmatch(r"[0-9a-f]{40}", r)
            for r in revisions
        )
    ):
        raise TopologyRefused(
            "admitted_launcher_revisions must list at least one full launcher "
            "commit. No launcher revision is admitted until § 7's admission "
            "evidence exists"
        )
    evidence = document.get("admission_evidence")
    if not isinstance(evidence, str) or not evidence.strip():
        raise TopologyRefused(
            "admission_evidence is not recorded. A topology without its negative "
            "and positive admission proofs is a configuration, not an admitted "
            "execution surface (docs/LANE3_EXECUTION_TOPOLOGY.md § 7)"
        )
    return Lane3ExecutionTopology(
        starter_repository=_text(document, "starter_repository"),
        execution_repository=_text(document, "execution_repository"),
        execution_repository_id=_positive_int(document, "execution_repository_id"),
        execution_owner_id=_positive_int(document, "execution_owner_id"),
        workflow_path=_text(document, "workflow_path"),
        environment_name=_text(document, "environment.name"),
        environment_id=_positive_int(document, "environment.id"),
        reviewer=_text(document, "environment.reviewer"),
        runner_group_name=_text(document, "runner_group.name"),
        runner_group_id=_positive_int(document, "runner_group.id"),
        admitted_launcher_revisions=frozenset(revisions),
        receipt_artifact=_text(document, "receipt_artifact"),
        admission_evidence=evidence,
    )


def load_topology(path: pathlib.Path) -> Lane3ExecutionTopology:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise TopologyRefused(f"cannot read {path}: {exc}") from exc
    return parse_topology(document)


def parse_run_name(title: Any) -> tuple[str, str] | None:
    """``(starter_revision, candidate_version)`` for a launcher run, or None."""
    if not isinstance(title, str):
        return None
    match = RUN_NAME.fullmatch(title)
    if match is None:
        return None
    return match.group("starter"), match.group("candidate")


def select_runs(
    runs: list[dict[str, Any]], *, sha: str, topology: Lane3ExecutionTopology
) -> list[dict[str, Any]]:
    """The launcher runs that claim to rehearse ``sha``, projected for ``decide``.

    Every listed run must be the pinned workflow, in the pinned repository, a
    ``workflow_dispatch`` on ``main``. Anything else in the population refuses:
    the API was asked for exactly that, so a different answer means the filter
    cannot be trusted. Each kept run is copied with ``head_sha`` replaced by the
    Starter revision its title names and the launcher's own commit kept as
    ``launcher_sha``, so ``require_rehearsal.decide`` applies its unchanged
    newest-then-check semantics to the revision that matters.
    """
    kept: list[dict[str, Any]] = []
    for run in runs:
        repository = run.get("repository")
        repository_id = repository.get("id") if isinstance(repository, dict) else None
        if (
            repository_id != topology.execution_repository_id
            or run.get("path") != topology.workflow_path
            or run.get("event") != "workflow_dispatch"
            or run.get("head_branch") != "main"
        ):
            raise ExecutionRunRefused(
                f"execution run {run.get('id')} is not the pinned workflow "
                f"{topology.workflow_path} in repository "
                f"{topology.execution_repository_id} dispatched on main "
                f"(repository {repository_id!r}, path {run.get('path')!r}, event "
                f"{run.get('event')!r}, branch {run.get('head_branch')!r})"
            )
        parsed = parse_run_name(run.get("display_title"))
        if parsed is None:
            if GRAMMAR_GUARD_PROVEN:
                continue
            raise ExecutionRunRefused(
                f"execution run {run.get('id')} has a title "
                f"{run.get('display_title')!r} the dispatch grammar does not "
                "parse. Excluding it is safe only once the launcher is proven to "
                "refuse that grammar first (D-S3); until then it refuses, because "
                "an excluded run might be the newest statement about this commit"
            )
        if parsed[0] != sha:
            continue
        kept.append({**run, "head_sha": parsed[0], "launcher_sha": run.get("head_sha")})
    return kept


def require_run_context(
    run: dict[str, Any],
    *,
    jobs: list[dict[str, Any]],
    approvals: list[dict[str, Any]],
    topology: Lane3ExecutionTopology,
) -> None:
    """The selected run used an admitted launcher, the pinned group, and was approved.

    Three facts the run listing does not carry, each read from its own API and
    each refusing on absence: the launcher commit is admitted; the job that
    produced the receipt ran on the pinned runner group (``runner_group_id``);
    and the Environment was approved by the expected reviewer.
    """
    launcher = run.get("launcher_sha")
    if launcher not in topology.admitted_launcher_revisions:
        raise ExecutionRunRefused(
            f"execution run {run.get('id')} ran launcher {launcher!r}, which is not "
            "an admitted launcher revision in .github/lane3-execution.json"
        )
    if not jobs or any(
        job.get("runner_group_id") != topology.runner_group_id for job in jobs
    ):
        raise ExecutionRunRefused(
            f"execution run {run.get('id')} has a job outside runner group "
            f"{topology.runner_group_id} (or reports no jobs). A job on any other "
            "runner was not executed on the admitted, workflow-restricted surface"
        )
    approved = [
        approval
        for approval in approvals
        if approval.get("state") == "approved"
        and isinstance(approval.get("user"), dict)
        and approval["user"].get("login") == topology.reviewer
        and any(
            isinstance(env, dict) and env.get("id") == topology.environment_id
            for env in approval.get("environments", ())
        )
    ]
    if not approved:
        raise ExecutionRunRefused(
            f"execution run {run.get('id')} carries no approval by "
            f"{topology.reviewer} for Environment {topology.environment_id}"
        )
