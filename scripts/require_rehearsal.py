#!/usr/bin/env python3
"""Refuse to publish the deployment facility unless the LANE 3 exposure
rehearsal executed and passed every one of its sixteen items, on the exact SHA.

Lane 3, not Lane 2 — corrected 2026-08-30
-----------------------------------------
This gate used to demand `deployment-rehearsal.yml`, which is **Lane 2**: a real
engine, database, ingress handoff, restore and observability loop. That is a
genuine and valuable proof, and it is a proof of a different thing. `0.3.0a1`'s
entire subject is ADDRESS-FAMILY EXPOSURE, and Lane 2 never watches an IPv6
socket refuse the internet. Gating the release named after that property on a
lane which cannot observe it is the "green preflight reads as attested" failure
with two lanes standing in for two gates.

So the oracle is now `exposure-rehearsal.yml`, and passing the run is no longer
enough on its own: the run publishes a `RehearsalReceipt.v1`, and this gate
reads it. **No `partial`, `not_applicable`, `hand_measured`, `vacuous`,
`incomplete` or missing result can satisfy publication** — only sixteen
`executed_passed`. A Lane 2 receipt offered here is refused by lane number
rather than counted.

Two oracles, deliberately, because they fail differently. The Actions API says a
run of the right workflow completed successfully on this SHA (AGENTS.md rule 30:
an external oracle with immutable coordinates). The receipt says WHAT that run
established. A green run with a receipt full of `blocked` rows is exactly the
shape this pair exists to catch, and either oracle alone would miss it.

Why this exists as CODE and not as a sentence in a document
-----------------------------------------------------------
`dotmac-deployment-foundation` executes migrations, takes and verifies backups,
performs the warm-candidate handoff and rolls back. Every one of those paths is
covered in-repo by a fake `Effects` implementation, which is exactly the right
tool for asserting that the PLAN refuses at the right step — and is incapable of
telling anyone whether a real Docker daemon honours
`service_completed_successfully`, whether a real `pg_dump` produced restorable
bytes, or whether nginx actually drained the old upstream.

`docs/inventories/deployment-exposure-rehearsal.md` said the sixteen items must
close before publication, in a hand-maintained table whose header once claimed
"14 of 16 CLOSED" while the rows below it recorded four `partial` and one `n/a`.
A prose requirement is bypassed by anyone who does not read it, including a
future automation that has no eyes — and a hand-maintained tally can contradict
its own evidence. The status document is now GENERATED from the receipt, and
this gate reads the receipt rather than the document.

The oracle is the GitHub Actions API: the MOST RECENT run of the rehearsal
workflow whose `head_sha` is byte-identical to the SHA under release, which
must itself be completed with conclusion `success`. Newest-then-check, never
check-then-newest — otherwise an old green run masks a newer one that failed,
was cancelled or is still queued. Not a committed file — a committed file is written by
the same hand that wants to publish. Not "a rehearsal ran recently" — a
rehearsal that passed on a different commit says nothing about this one, and
that substitution is the single most likely way this gate would be defeated
while still appearing green.

Fails CLOSED on every ambiguity: a transport error, an unparseable body, zero
runs, a run still in progress, any conclusion other than `success`, and any
`head_sha` mismatch. There is deliberately no `--allow-missing` escape hatch;
the way to publish without a rehearsal is to run the rehearsal.

Organization execution — amended 2026-10-05 (ADR-0070)
------------------------------------------------------
Lane 3 no longer runs in this public, personal-account repository. The runs
read are those of ONE workflow in ONE organization repository, pinned by
immutable IDs in `.github/lane3-execution.json` (`lane3_execution.py`). Each
run's title names the Starter revision it rehearsed, in the launcher's dispatch
grammar. `select_runs` projects that revision into `head_sha`, so `decide`
keeps its newest-then-check semantics unchanged. Three facts are then
required of the selected run, each from its own API:
- its launcher commit is admitted;
- every job ran on the pinned runner group;
- the expected reviewer approved its Environment.

The receipt is downloaded by THIS process from THAT run. It must be a
`RehearsalReceipt.v2` bound to that run's repository ID, run ID and attempt
(`require_execution_run`). While the topology file records no admitted
surface, every call refuses (docs/LANE3_EXECUTION_TOPOLOGY.md § 9).
"""

from __future__ import annotations

import argparse
import io
import json
import os
import pathlib
import sys
import urllib.error
import urllib.request
import zipfile
from datetime import UTC, datetime
from typing import Any

# Launched `-E -P` by the release job, which removes this file's own directory
# from `sys.path`; put it back explicitly so the `lane3_execution` sibling
# resolves to THIS checkout's copy and nothing ambient.
_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

EXIT_OK = 0
EXIT_REFUSED = 1
EXIT_USAGE = 2

API_ROOT = "https://api.github.com"


class RehearsalMissing(Exception):
    """The oracle did not affirmatively prove a rehearsal for this SHA."""


def _ordering_key(run: dict[str, Any]) -> tuple[datetime, int]:
    """The coordinate runs are ordered by, or a refusal.

    `run_started_at` is the only field that says WHEN, and `id` breaks ties
    monotonically. If a run carries neither in a usable form the ordering is
    not trustworthy, and an untrustworthy ordering is exactly how an older
    success ends up masking a newer failure — so it refuses instead of falling
    back to list order, which the API does not promise.
    """
    started = run.get("run_started_at")
    if not isinstance(started, str) or not started:
        raise RehearsalMissing(
            f"rehearsal run {run.get('id')} carries no `run_started_at`, so "
            "'newest' cannot be established. Refusing rather than guessing "
            "which run is current"
        )
    try:
        when = datetime.fromisoformat(started.replace("Z", "+00:00"))
    except ValueError as exc:
        raise RehearsalMissing(
            f"rehearsal run {run.get('id')} has an unparseable "
            f"`run_started_at` {started!r}; refusing rather than ordering on a "
            "value nothing understood"
        ) from exc
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    identifier = run.get("id")
    if not isinstance(identifier, int):
        raise RehearsalMissing(
            f"rehearsal run at {started} carries no integer `id` to break ties "
            "with; refusing rather than ordering non-deterministically"
        )
    return (when, identifier)


def decide(runs: list[dict[str, Any]], sha: str) -> dict[str, Any]:
    """Pure decision over the API's `workflow_runs` array.

    LATEST-RUN SEMANTICS, and the order of these two operations is the whole
    point. Select the NEWEST run for this SHA, THEN require that run to be
    completed and successful.

    Filtering to successes first and taking the newest of those was the
    original shape and it was wrong: an old green rehearsal would mask a newer
    one that failed, was cancelled, or is still queued. The newest run is the
    current statement about this commit — if somebody re-rehearsed and it
    broke, that is the answer, and an earlier success does not overrule it.
    The one case that must still pass is the honest repair: an older failure
    followed by a newer success.

    Separated from the fetch so this logic is unit-testable without a network,
    which is the half that has to be right.
    """
    if not sha or len(sha) != 40 or any(c not in "0123456789abcdef" for c in sha):
        raise RehearsalMissing(
            "the SHA under release must be a full 40-character hex commit "
            f"id, got {sha!r}"
        )
    if not runs:
        raise RehearsalMissing(
            f"no rehearsal run exists for {sha}. Run the disposable-host "
            "rehearsal workflow against this exact commit before publishing"
        )

    for run in runs:
        head = run.get("head_sha")
        if head != sha:
            # The API was asked to filter by head_sha; if it returned something
            # else, do not trust the filter — say so rather than accepting it.
            raise RehearsalMissing(
                f"rehearsal run {run.get('id')} reports head_sha {head!r}, which "
                f"is not the SHA under release {sha!r}. A rehearsal that passed "
                "on another commit is not evidence about this one"
            )

    newest = max(runs, key=_ordering_key)
    status, conclusion = newest.get("status"), newest.get("conclusion")
    if status != "completed" or conclusion != "success":
        raise RehearsalMissing(
            f"the most recent rehearsal for {sha} (run {newest.get('id')}, "
            f"started {newest.get('run_started_at')}) is {status}/{conclusion}, "
            "not completed/success. An earlier successful run does not "
            "overrule the current one — re-run the rehearsal and let it pass"
        )
    return {
        "run_id": newest.get("id"),
        "head_sha": newest.get("head_sha"),
        "html_url": newest.get("html_url"),
        "run_started_at": newest.get("run_started_at"),
    }


def _fetch(url: str, token: str) -> Any:
    """GET one API resource, or a refusal. Never an exception type by accident."""
    request = urllib.request.Request(url)  # noqa: S310 - fixed https API root
    request.add_header("Accept", "application/vnd.github+json")
    request.add_header("X-GitHub-Api-Version", "2022-11-28")
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310
            body = response.read()
        return json.loads(body.decode("utf-8"))
    except urllib.error.HTTPError as exc:  # fail closed, loudly
        raise RehearsalMissing(
            f"the rehearsal oracle is unreachable (HTTP {exc.code} for {url}). "
            "Refusing to publish: an oracle that cannot be read has not said yes"
        ) from exc
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        raise RehearsalMissing(
            f"the rehearsal oracle could not be read ({exc}). Refusing to publish"
        ) from exc


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Surface a redirect instead of following it with the caller's headers."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        return None


def _download(url: str, token: str) -> bytes:
    """An artifact archive, following its ONE redirect WITHOUT the token.

    GitHub answers an artifact download with a redirect to a pre-signed storage
    URL. `urllib` would follow it carrying the `Authorization` header, which the
    storage host rejects and which hands the token to a third party. So the
    redirect is taken by hand and the signed URL fetched with no credential.
    """
    request = urllib.request.Request(url)  # noqa: S310 - fixed https API root
    request.add_header("Accept", "application/vnd.github+json")
    request.add_header("X-GitHub-Api-Version", "2022-11-28")
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    opener = urllib.request.build_opener(_NoRedirect)
    try:
        with opener.open(request, timeout=60) as response:
            return response.read()
    except urllib.error.HTTPError as exc:
        location = exc.headers.get("Location") if exc.code in (301, 302, 307) else None
        if not location or not location.startswith("https://"):
            raise RehearsalMissing(
                f"the receipt artifact could not be downloaded (HTTP {exc.code})"
            ) from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise RehearsalMissing(
            f"the receipt artifact could not be read ({exc})"
        ) from exc
    try:
        with urllib.request.urlopen(location, timeout=60) as response:  # noqa: S310
            return response.read()
    except (urllib.error.URLError, TimeoutError) as exc:
        raise RehearsalMissing(
            f"the receipt artifact's signed URL could not be read ({exc})"
        ) from exc


def _list(url: str, key: str, token: str) -> list[dict[str, Any]]:
    """Every page of a listing, or a refusal. A partial listing is not a listing.

    ``total_count`` is compared with what was collected: a listing that changed
    or truncated while being read could have dropped exactly the newest run.
    """
    collected: list[dict[str, Any]] = []
    total: Any = None
    page = 1
    while True:
        separator = "&" if "?" in url else "?"
        body = _fetch(f"{url}{separator}per_page=100&page={page}", token)
        items = body.get(key) if isinstance(body, dict) else None
        if not isinstance(items, list):
            raise RehearsalMissing(
                f"the rehearsal oracle returned no `{key}` array; refusing to "
                "treat an unrecognised response as approval"
            )
        if total is None:
            total = body.get("total_count")
        collected.extend(items)
        if len(items) < 100:
            break
        page += 1
    if not isinstance(total, int) or total != len(collected):
        raise RehearsalMissing(
            f"the oracle reported {total!r} {key} and {len(collected)} were read. "
            "An incomplete listing may have dropped the newest run"
        )
    return collected


def _receipt_bytes(repo: str, run_id: int, artifact: str, token: str) -> bytes:
    """The receipt from EXACTLY the selected run's one artifact named ``artifact``.

    Fetched here rather than by an earlier workflow step, so the run whose
    receipt is read is the run that was selected — nothing can land between a
    selection and a separate download. More than one artifact of that name is
    refused as ambiguous; the receipt's own run binding then refuses one taken
    from an earlier attempt.
    """
    listed = _list(
        f"{API_ROOT}/repos/{repo}/actions/runs/{run_id}/artifacts?name={artifact}",
        "artifacts",
        token,
    )
    if len(listed) != 1 or listed[0].get("expired"):
        raise RehearsalMissing(
            f"execution run {run_id} carries {len(listed)} artifact(s) named "
            f"{artifact!r} (or it expired). Exactly one live receipt is required"
        )
    archive = _download(
        f"{API_ROOT}/repos/{repo}/actions/artifacts/{listed[0]['id']}/zip", token
    )
    try:
        with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
            return bundle.read("receipt.json")
    except (zipfile.BadZipFile, KeyError) as exc:
        raise RehearsalMissing(
            f"the receipt artifact of execution run {run_id} has no readable "
            f"receipt.json ({exc})"
        ) from exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="require_rehearsal.py",
        description=(
            "Fail unless the pinned Lane 3 execution workflow rehearsed the exact "
            "SHA and published a passing RehearsalReceipt.v2 for these bytes."
        ),
    )
    parser.add_argument("sha", help="the full 40-character commit under release")
    parser.add_argument(
        "--repo",
        default=os.environ.get("GITHUB_REPOSITORY", ""),
        help=(
            "owner/name of THIS repository; must equal the topology's "
            "starter_repository, so a topology copied from elsewhere refuses"
        ),
    )
    parser.add_argument(
        "--topology",
        default=str(_ROOT / ".github" / "lane3-execution.json"),
        help="the checked-in Lane3ExecutionTopology.v1",
    )
    parser.add_argument(
        "--receipt-out",
        required=True,
        help=(
            "where to write the receipt read from the selected run, for the "
            "record. It is read by THIS process from the run it selected, never "
            "supplied by the caller"
        ),
    )
    # REQUIRED, and that is the whole design. The receipt says what a run
    # established and at which revision; nothing in it was ever compared with
    # the BYTES about to be published, so a rehearsal of candidate A satisfied
    # a publication of candidate B whenever both ran at one commit. A default
    # here would be a check the caller may omit; argparse refusing is a check
    # whose absence stops the lane.
    parser.add_argument(
        "--artifact-digest",
        required=True,
        help=(
            "sha256 of the candidate the release is about to publish, as "
            "`release_facility.py resolve-candidate` emitted it. The receipt "
            "must record a rehearsal of exactly these bytes"
        ),
    )
    args = parser.parse_args(argv)
    if not args.repo:
        print("error: --repo (or $GITHUB_REPOSITORY) is required", file=sys.stderr)
        return EXIT_USAGE
    token = os.environ.get("GITHUB_TOKEN", "")

    from lane3_execution import (
        ExecutionRunRefused,
        TopologyRefused,
        load_topology,
        require_run_context,
        select_runs,
    )

    try:
        topology = load_topology(pathlib.Path(args.topology))
        if topology.starter_repository != args.repo:
            raise TopologyRefused(
                f"the topology is for {topology.starter_repository}, and this is "
                f"{args.repo}"
            )
        repo = topology.execution_repository
        workflow = pathlib.PurePosixPath(topology.workflow_path).name
        runs = _list(
            f"{API_ROOT}/repos/{repo}/actions/workflows/{workflow}/runs"
            "?event=workflow_dispatch&branch=main",
            "workflow_runs",
            token,
        )
        candidates = select_runs(runs, sha=args.sha, topology=topology)
        proof = decide(candidates, args.sha)
        selected = next(run for run in candidates if run.get("id") == proof["run_id"])
        attempt = selected.get("run_attempt")
        if isinstance(attempt, bool) or not isinstance(attempt, int) or attempt < 1:
            raise RehearsalMissing(
                f"execution run {proof['run_id']} reports no usable run_attempt "
                f"({attempt!r}); the receipt's run binding cannot be checked"
            )
        jobs = _list(
            f"{API_ROOT}/repos/{repo}/actions/runs/{proof['run_id']}"
            f"/attempts/{attempt}/jobs",
            "jobs",
            token,
        )
        approvals = _fetch(
            f"{API_ROOT}/repos/{repo}/actions/runs/{proof['run_id']}/approvals",
            token,
        )
        if not isinstance(approvals, list):
            raise RehearsalMissing("the approvals oracle returned no array")
        require_run_context(selected, jobs=jobs, approvals=approvals, topology=topology)
        receipt_bytes = _receipt_bytes(
            repo, proof["run_id"], topology.receipt_artifact, token
        )
    except (RehearsalMissing, TopologyRefused, ExecutionRunRefused) as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return EXIT_REFUSED

    # The second oracle. Imported here rather than at module scope so the pure
    # `decide` half stays importable by a test with nothing installed. The
    # caller must use the isolated interpreter holding the digest-verified
    # candidate wheel; reaching into checkout source here would let the gate
    # validate a different contract from the bytes it later publishes.
    from dotmac_deployment_foundation.errors import SpecError
    from dotmac_deployment_foundation.rehearsal import (
        ExecutionRunBindingV1,
        RehearsalReceiptV2,
        require_execution_run,
        require_rehearsed_artifact,
        verify_publication,
    )

    pathlib.Path(args.receipt_out).write_bytes(receipt_bytes)
    try:
        # v2 ONLY: a v1 receipt cannot carry the authorized
        # `ExecutionPlanDigestV1`, so the reader refuses it by schema.
        receipt = RehearsalReceiptV2.from_json(receipt_bytes)
        verify_publication(receipt, revision=args.sha)
        # THE RUN BINDING. The receipt must have been produced by exactly the run
        # selected above — same repository ID, run ID and attempt — so a receipt
        # from an earlier passing run cannot stand in for the newest one.
        require_execution_run(
            receipt,
            run=ExecutionRunBindingV1(
                repository_id=topology.execution_repository_id,
                run_id=int(proof["run_id"]),
                run_attempt=attempt,
            ),
        )
        # THE THIRD BINDING. `verify_publication` above compares the LANE 3
        # RUNNER revision with the RELEASE revision; this compares the receipt
        # with the ARTIFACT, which is what makes the CANDIDATE SOURCE revision
        # bound rather than merely recorded — the digest identifies exactly one
        # `CandidateArtifact.v1`, and that record names exactly one `source_sha`.
        require_rehearsed_artifact(receipt, artifact_digest=args.artifact_digest)
    except (SpecError, TypeError, ValueError) as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return EXIT_REFUSED

    print(f"rehearsal_run_id={proof['run_id']}")
    print(f"rehearsal_run_attempt={attempt}")
    print(f"rehearsal_execution_repository_id={topology.execution_repository_id}")
    print(f"rehearsal_run_url={proof['html_url']}")
    print(f"rehearsal_launcher_revision={selected.get('launcher_sha')}")
    print(f"rehearsal_lane={receipt.lane}")
    print(f"rehearsal_receipt_digest={receipt.sha256_digest()}")
    print(f"rehearsal_execution_plan_digest={receipt.execution_plan_digest}")
    # All THREE revisions, named separately, on the record that decides the
    # publish. A reader comparing them should not have to join two files.
    print(f"rehearsal_runner_revision={receipt.foundation_revision}")
    print(f"release_revision={args.sha}")
    print(f"rehearsed_artifact_digest={receipt.foundation_artifact_digest}")
    return EXIT_OK


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
