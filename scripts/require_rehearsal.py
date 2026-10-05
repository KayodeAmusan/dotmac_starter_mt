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
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
import urllib.error
import urllib.request
from datetime import UTC, datetime
from typing import Any

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


def _fetch(repo: str, workflow: str, sha: str, token: str) -> list[dict[str, Any]]:
    url = (
        f"{API_ROOT}/repos/{repo}/actions/workflows/{workflow}/runs"
        f"?head_sha={sha}&per_page=100"
    )
    request = urllib.request.Request(url)  # noqa: S310 - fixed https API root
    request.add_header("Accept", "application/vnd.github+json")
    request.add_header("X-GitHub-Api-Version", "2022-11-28")
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:  # fail closed, loudly
        raise RehearsalMissing(
            f"the rehearsal oracle is unreachable (HTTP {exc.code} for {workflow}). "
            "Refusing to publish: an oracle that cannot be read has not said yes"
        ) from exc
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        raise RehearsalMissing(
            f"the rehearsal oracle could not be read ({exc}). Refusing to publish"
        ) from exc
    runs = body.get("workflow_runs")
    if not isinstance(runs, list):
        raise RehearsalMissing(
            "the rehearsal oracle returned no `workflow_runs` array; refusing to "
            "treat an unrecognised response as approval"
        )
    return runs


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="require_rehearsal.py",
        description=(
            "Fail unless a disposable-host rehearsal succeeded on the exact SHA."
        ),
    )
    parser.add_argument("sha", help="the full 40-character commit under release")
    parser.add_argument(
        "--repo",
        default=os.environ.get("GITHUB_REPOSITORY", ""),
        help="owner/name; defaults to $GITHUB_REPOSITORY",
    )
    parser.add_argument(
        "--workflow",
        default="exposure-rehearsal.yml",
        help="the LANE 3 rehearsal workflow file name",
    )
    parser.add_argument(
        "--receipt",
        required=True,
        help=(
            "path to the RehearsalReceipt.v1 the rehearsal run published. "
            "Required: a green run says a job exited 0, and only the receipt "
            "says what it established"
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
    try:
        proof = decide(_fetch(args.repo, args.workflow, args.sha, token), args.sha)
    except RehearsalMissing as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return EXIT_REFUSED

    # The second oracle. Imported here rather than at module scope so the pure
    # `decide` half stays importable by a test with nothing installed. The
    # caller must use the isolated interpreter holding the digest-verified
    # candidate wheel; reaching into checkout source here would let the gate
    # validate a different contract from the bytes it later publishes.
    from dotmac_deployment_foundation.errors import SpecError
    from dotmac_deployment_foundation.rehearsal import (
        RehearsalReceiptV2,
        require_rehearsed_artifact,
        verify_publication,
    )

    receipt_path = pathlib.Path(args.receipt)
    if not receipt_path.exists():
        print(
            f"REFUSED: no rehearsal receipt at {receipt_path}. A run that "
            "published no receipt has not said what it established",
            file=sys.stderr,
        )
        return EXIT_REFUSED
    try:
        # v2 ONLY. A v1 receipt cannot carry the authorized
        # `ExecutionPlanDigestV1` (its item 9 forced three caller digests equal),
        # so the reader refuses it by schema rather than this gate counting it.
        #
        # Not yet called here: `require_execution_run`. The run this oracle
        # selects is still a Starter-repository run, while a v2 receipt binds the
        # organization execution repository's run. Binding the two is the oracle
        # amendment in docs/LANE3_EXECUTION_TOPOLOGY.md § 6 (D-S2), which adds
        # that call together with the new run selection. Until then no v2 receipt
        # can exist: the runner still emits v1 and refuses at qualification.
        receipt = RehearsalReceiptV2.from_json(receipt_path.read_text(encoding="utf-8"))
        verify_publication(receipt, revision=args.sha)
        # THE THIRD BINDING. `verify_publication` above compares the LANE 3
        # RUNNER revision with the RELEASE revision; this compares the receipt
        # with the ARTIFACT, which is what makes the CANDIDATE SOURCE revision
        # bound rather than merely recorded — the digest identifies exactly one
        # `CandidateArtifact.v1`, and that record names exactly one `source_sha`.
        require_rehearsed_artifact(receipt, artifact_digest=args.artifact_digest)
    except SpecError as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return EXIT_REFUSED

    print(f"rehearsal_run_id={proof['run_id']}")
    print(f"rehearsal_run_url={proof['html_url']}")
    print(f"rehearsal_head_sha={proof['head_sha']}")
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
