"""Lease persistence: the terminal release lives BESIDE the lease, in one store.

## Why one store rather than two

A release written anywhere else is a second ledger, and the destroy gate would
then consult one record while the lease lived in another — which is exactly how a
swapped lease goes unnoticed. `release_path` is derived from `_lease_path` rather
than composed independently, so the two records cannot drift apart.

## The gate is only meaningful once a release can exist

`require_release_before_destruction` has refused unconditionally since it was
written, because nothing could produce a release. This is the other half: with a
writer, every refusal below becomes reachable, and the two that matter most are
the ones proving the axes COMPOSE.

## Two questions, two answers

"May this host be destroyed?" and "may a next lease take it as it stands?" are
different, and a host may legitimately answer yes to the first and no to the
second — `destroy_only` is exactly that. So reuse has its own gate, and it is
where `failed` and `outcome_unknown` cleanup refuse.
"""

from __future__ import annotations

import ast
import inspect
import json
import textwrap
import threading
from datetime import UTC, datetime
from pathlib import Path

import pytest
from dotmac_deployment_foundation.controller_identity import (
    ControllerSshFingerprintV1,
)
from dotmac_deployment_foundation.errors import PreconditionFailed, SpecError
from dotmac_deployment_foundation.lease import (
    HostLease,
    release_path,
    write_lease,
    write_store_record,
    write_store_record_once,
)
from dotmac_deployment_foundation.lease_release import (
    RELEASE_DUPLICATE,
    RELEASE_FOREIGN,
    RELEASE_MISSING,
    RELEASE_NOT_DESTROYABLE,
    CleanupDisposition,
    HostClosure,
    HostLeaseReleaseV1,
    ReleasingPrincipal,
    TerminalOutcome,
    TerminalRefusal,
    lease_digest,
    load_release,
    require_release_for_destruction,
    require_release_for_reuse,
    write_release,
)

from tests.unit.working_tree import python_files

PACKAGE = (
    Path(__file__).resolve().parents[2]
    / "packages"
    / "dotmac-deployment-foundation"
    / "src"
    / "dotmac_deployment_foundation"
)
SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"

TARGET = "192.0.2.54"
SLOT = "dotmacproxmox/102"
RUN = "33854964978"
REHEARSAL = "33860000001"
PRINCIPAL = "repo:michaelayoade/dotmac_starter_mt:ref:refs/heads/main"
#: A real OpenSSH fingerprint. It read `"sha256:" + "a" * 64` — the CONTENT
#: DIGEST shape the release plane's old regex required, which `ssh-keygen -lf`
#: never emits and which is therefore a value the field could not really hold.
FINGERPRINT = ControllerSshFingerprintV1.parse(
    "SHA256:T1kdK/6QTzzwU1EienO6nUgk8wu9UpjqB8BatKbndSE", field="controller"
)
LIVE = datetime(2026, 9, 4, 3, 0, tzinfo=UTC)
AFTER = datetime(2026, 9, 4, 7, 0, tzinfo=UTC)


def _lease(**over) -> HostLease:
    kwargs = {
        "target": TARGET,
        "holder": "deployment-foundation-rehearsal",
        "authorization_run_id": RUN,
        "starts_at": "2026-09-04T00:00:00Z",
        "expires_at": "2026-09-04T06:00:00Z",
        "compose_project_prefix": "rehearsal-",
        "controller_identity_fingerprint": FINGERPRINT,
        "workload_principal": PRINCIPAL,
    }
    kwargs.update(over)
    return HostLease(**kwargs)


def _release(lease: HostLease | None = None, **over) -> HostLeaseReleaseV1:
    lease = lease or _lease()
    kwargs = {
        "lease_digest": lease_digest(lease),
        "vm_slot": SLOT,
        "vm_installation_id": "",
        "candidate_version": "0.4.0a1",
        # TWO revisions, DIFFERENT here on purpose: a fixture that used one
        # value for both would let a writer emitting one of them twice pass.
        "candidate_source_revision": "0" * 40,
        "runner_revision": "1" * 40,
        "authorization_run_id": RUN,
        "rehearsal_run_id": REHEARSAL,
        "outcome": TerminalOutcome(receipt_digest="sha256:" + "b" * 64),
        "released_at": "2026-09-04T05:00:00Z",
        "released_by": ReleasingPrincipal(
            kind="github_actions_workload",
            subject=lease.workload_principal,
            run_binding=REHEARSAL,
        ),
        "controller_identity_fingerprint": lease.controller_identity_fingerprint,
        "closure": HostClosure.REUSABLE,
        "cleanup": CleanupDisposition.PURGED,
    }
    kwargs.update(over)
    return HostLeaseReleaseV1(**kwargs)


@pytest.fixture
def store(tmp_path: Path) -> Path:
    write_lease(_lease(), directory=tmp_path, now=LIVE)
    return tmp_path


def _destroy(store: Path, **kw):
    params = {
        "directory": store,
        "now": AFTER,
        "vm_slot": SLOT,
        "candidate_version": "0.4.0a1",
    }
    params.update(kw)
    return require_release_for_destruction(TARGET, **params)


# ── one store, beside the lease ────────────────────────────────────────────


def test_the_release_lives_beside_the_lease(store: Path) -> None:
    """Not a second ledger. Derived from the lease's own path so the two cannot
    come to live in different places."""
    written = write_release(_release(), target=TARGET, directory=store)
    assert written == release_path(TARGET, directory=store)
    assert written.parent == (store / f"{TARGET}.json").parent
    assert {p.name for p in store.iterdir()} == {
        f"{TARGET}.json",
        f"{TARGET}.release.json",
    }


def test_the_release_round_trips_through_the_store(store: Path) -> None:
    original = _release()
    write_release(original, target=TARGET, directory=store)
    assert load_release(TARGET, directory=store) == original


def test_no_release_is_None_and_not_an_error(store: Path) -> None:
    """A host with no release is the ordinary state of one being worked on, and
    the state a crash leaves. The gate decides what that means — "no release
    exists" and "this release does not authorize" must not share an answer."""
    assert load_release(TARGET, directory=store) is None


def test_a_second_release_of_one_lease_is_refused(store: Path) -> None:
    write_release(_release(), target=TARGET, directory=store)
    with pytest.raises(PreconditionFailed) as exc:
        write_release(_release(), target=TARGET, directory=store)
    assert exc.value.code == RELEASE_DUPLICATE


# ── the required refusals ──────────────────────────────────────────────────


def test_missing_release_refuses_destruction(store: Path) -> None:
    with pytest.raises(PreconditionFailed) as exc:
        _destroy(store)
    assert exc.value.code == RELEASE_MISSING


def test_expired_without_release_refuses_destruction(store: Path) -> None:
    """Expiry is not release. This is the shape a crash leaves, and the one case
    where nobody can be asked what happened."""
    with pytest.raises(PreconditionFailed) as exc:
        _destroy(store, now=AFTER)
    assert exc.value.code == RELEASE_MISSING


def test_a_swapped_lease_refuses(store: Path) -> None:
    """The release names the exact lease by CONTENT, so a release written for a
    different lease on this target does not discharge it."""
    other = _lease(compose_project_prefix="other-")
    write_release(_release(other), target=TARGET, directory=store)
    with pytest.raises(PreconditionFailed) as exc:
        _destroy(store)
    assert exc.value.code == RELEASE_FOREIGN


def test_a_wrong_workload_principal_refuses(store: Path) -> None:
    """`released_by` must equal the principal bound into THIS lease."""
    write_release(
        _release(
            released_by=ReleasingPrincipal(
                kind="github_actions_workload",
                subject="repo:michaelayoade/other:ref:refs/heads/main",
                run_binding=REHEARSAL,
            )
        ),
        target=TARGET,
        directory=store,
    )
    with pytest.raises(PreconditionFailed) as exc:
        _destroy(store)
    assert exc.value.code == RELEASE_FOREIGN


def test_a_wrong_candidate_refuses(store: Path) -> None:
    write_release(_release(candidate_version="0.3.0a6"), target=TARGET, directory=store)
    with pytest.raises(PreconditionFailed) as exc:
        _destroy(store)
    assert exc.value.code == RELEASE_FOREIGN


def test_a_wrong_vm_identity_refuses(store: Path) -> None:
    """An address can be re-pointed by the very restoration this authorises; the
    thing that gets wiped is a slot."""
    write_release(_release(), target=TARGET, directory=store)
    with pytest.raises(PreconditionFailed) as exc:
        _destroy(store, vm_slot="dotmacproxmox/107")
    assert exc.value.code == RELEASE_FOREIGN


def test_cleanup_unknown_can_never_be_reused(store: Path) -> None:
    """What the lease created is either still there or nobody can say it is not,
    and a next lease inheriting that host as clean is the same failure either
    way."""
    write_release(
        _release(
            cleanup=CleanupDisposition.OUTCOME_UNKNOWN,
            closure=HostClosure.DESTROY_ONLY,
        ),
        target=TARGET,
        directory=store,
    )
    with pytest.raises(PreconditionFailed) as exc:
        require_release_for_reuse(TARGET, directory=store, now=AFTER)
    assert exc.value.code == RELEASE_NOT_DESTROYABLE


def test_a_clean_release_permits_both(store: Path) -> None:
    """The positive control. Without it every refusal above could come from a
    gate that refuses everything."""
    write_release(_release(), target=TARGET, directory=store)
    assert _destroy(store)
    assert require_release_for_reuse(TARGET, directory=store, now=AFTER)


# ── V1 can neither authorize nor release ──────────────────────────────────


def test_a_v1_lease_cannot_be_loaded_so_it_can_neither_authorize_nor_release(
    tmp_path: Path,
) -> None:
    """It names no workload principal, so nothing it says can be bound to a
    releasing party. Refusing to LOAD is what makes both impossible rather than
    one of them checked."""
    document = _lease().as_document()
    document["schema"] = "HostLease.v1"
    document.pop("workload_principal")
    (tmp_path / f"{TARGET}.json").write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(SpecError):
        _destroy(tmp_path)
    with pytest.raises(SpecError):
        require_release_for_reuse(TARGET, directory=tmp_path, now=AFTER)


# ── the two axes COMPOSE, proved concretely ───────────────────────────────


def test_an_untouched_refusal_releases_only_when_cleanup_permits(
    store: Path,
) -> None:
    """`precondition_unfit` is unrestricted BY REFUSAL — nothing was attempted,
    the host is untouched. It may still be restricted BY CLEANUP.

    So the same refusal reaches `reusable` with clean cleanup and cannot reach it
    with unknown cleanup. That is the intersection doing work: neither axis alone
    produces both answers.
    """
    untouched = TerminalOutcome(refusal=TerminalRefusal.PRECONDITION_UNFIT)
    assert _release(
        outcome=untouched,
        cleanup=CleanupDisposition.NOT_ATTEMPTED,
        closure=HostClosure.REUSABLE,
    )
    with pytest.raises(SpecError):
        _release(
            outcome=untouched,
            cleanup=CleanupDisposition.OUTCOME_UNKNOWN,
            closure=HostClosure.REUSABLE,
        )


def test_a_partially_mutated_host_can_never_become_reusable(store: Path) -> None:
    """The seeder placed a foreign rule, failed, and partially unwound, so the
    machine is in a state nobody has certified — and so is every host a refusal
    reached after mutation may have begun, which is the same member.

    Restricted by the REFUSAL axis whatever the cleanup says — including a
    cleanup that claims success, because a purge claimed after a failed
    provocation is a claim about a host whose state was already uncertified.
    """
    mutated = TerminalOutcome(refusal=TerminalRefusal.HOST_STATE_UNCERTIFIED)
    for cleanup in CleanupDisposition:
        with pytest.raises(SpecError):
            _release(outcome=mutated, cleanup=cleanup, closure=HostClosure.REUSABLE)
    # And the permitted closures remain reachable, so this is a restriction
    # rather than a wall.
    assert _release(
        outcome=mutated,
        cleanup=CleanupDisposition.PURGED,
        closure=HostClosure.DESTROY_ONLY,
    )


# ── create-only: the race, not a sequential rehearsal of it ────────────────
#
# A lease may legitimately be rewritten — it is renewed, and the current row is
# the answer. A RELEASE may not: it records how a lease ended, and a second
# write is either a replay or two runs each believing they finished the same
# work. Overwriting picks one silently, and a destroyer then acts on the wrong
# terminal outcome.
#
# The store is a shared host whose whole premise is that agents contend for the
# target, and the workflow's concurrency group does not cancel in progress — so
# two dispatches at different revisions against one target overlap BY DESIGN.
# This is not a theoretical race.


def _stat_then_write(path: Path, document: dict[str, object], barrier) -> None:
    """The REJECTED implementation, kept as a negative control.

    Not dead code: it is what makes the proof below non-vacuous. A test that
    only ran the real writer would go green against this one too, because
    sequentially the two are indistinguishable — which is exactly how a
    stat-then-write survives a create-only test suite.
    """
    exists = path.exists()
    barrier.wait(timeout=5)  # both racers now past their own check
    if exists:
        raise FileExistsError(path)
    path.write_text(json.dumps(document, sort_keys=True, indent=2) + "\n", "utf-8")


def _race(publish, path: Path) -> tuple[int, int, str]:
    """Two threads publishing different content, interleaved at a barrier."""
    barrier = threading.Barrier(2)
    wins: list[str] = []
    refusals: list[BaseException] = []

    def attempt(which: str) -> None:
        try:
            publish(path, {"which": which}, barrier)
            wins.append(which)
        except (FileExistsError, PreconditionFailed) as exc:
            refusals.append(exc)

    threads = [threading.Thread(target=attempt, args=(w,)) for w in ("A", "B")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)
    stored = (
        json.loads(path.read_text(encoding="utf-8"))["which"] if path.exists() else ""
    )
    return len(wins), len(refusals), stored


def test_TWO_CONCURRENT_PUBLISHES_leave_exactly_one_release(tmp_path: Path) -> None:
    """The property, proven under an interleaving rather than in sequence.

    Both racers are released from the barrier at the point where a
    stat-then-write has already made its decision. `os.link` cannot be beaten
    there: creating the name and failing on a taken name are ONE syscall, so
    whichever thread links second gets EEXIST no matter how the two interleave.
    """

    def publish(path: Path, document: dict[str, object], barrier) -> None:
        barrier.wait(timeout=5)
        write_store_record_once(path, document)

    wins, refusals, stored = _race(publish, tmp_path / "release.json")
    assert (wins, refusals) == (1, 1), f"{wins} publishes succeeded, {refusals} refused"
    assert stored in {"A", "B"}
    assert [p.name for p in tmp_path.iterdir() if ".partial" in p.name] == []


def test_the_RACE_HARNESS_can_actually_see_the_loss(tmp_path: Path) -> None:
    """Sensitivity. Without this, the test above is a green that proves nothing.

    The same interleaving against the implementation this replaced: both racers
    observe `exists() == False`, both write, and the second silently overwrites
    the record of the first. Two successes is the regression, in the harness
    that reported one.
    """
    wins, refusals, _ = _race(_stat_then_write, tmp_path / "release.json")
    assert (wins, refusals) == (2, 0), (
        "the harness did not reproduce the stat-then-write loss, so the test "
        "above is not evidence about atomicity"
    )


def test_sequentially_BOTH_implementations_look_correct(tmp_path: Path) -> None:
    """Stated explicitly so no one mistakes a sequential green for the proof.

    This is a CONTROL, not the race test. Run one after the other, the rejected
    implementation refuses too — which is precisely why a unit suite full of
    sequential create-only tests would have shipped the regression.
    """
    barrier = threading.Barrier(1)
    for publish in (_stat_then_write, lambda p, d, _b: write_store_record_once(p, d)):
        path = tmp_path / f"{publish.__class__.__name__}{id(publish)}.json"
        publish(path, {"which": "first"}, barrier)
        with pytest.raises(FileExistsError):
            publish(path, {"which": "second"}, barrier)
        assert json.loads(path.read_text(encoding="utf-8"))["which"] == "first"


def test_write_release_does_not_CHECK_before_writing() -> None:
    """Structural, because the race above cannot be run through `write_release`
    without a seam that does not exist. The premise is enforceable: the refusal
    must be sourced from the atomic publish, so the body contains no existence
    check for a later reader to reintroduce.
    """
    tree = ast.parse(textwrap.dedent(inspect.getsource(write_release)))
    checks = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and getattr(node.func, "attr", None) == "exists"
    ]
    assert checks == [], (
        "write_release checks for existence before writing; the refusal must "
        "come from the atomic publish or it does not hold when two runs race"
    )


def test_the_LEASE_writer_deliberately_overwrites(tmp_path: Path) -> None:
    """The asymmetry, asserted rather than described. Two writers over one
    shared bytes function, because the difference is real."""
    lease_file = tmp_path / "lease.json"
    write_store_record(lease_file, {"generation": 1})
    write_store_record(lease_file, {"generation": 2})
    assert json.loads(lease_file.read_text(encoding="utf-8")) == {"generation": 2}


def test_both_writers_produce_THE_SAME_bytes(tmp_path: Path) -> None:
    """Different semantics, one mechanism. If these diverge, two records in one
    directory are written two ways and nothing else would fail."""
    document = {"b": 2, "a": {"z": 1, "y": [3, 1]}}
    assert write_store_record(tmp_path / "a.json", document).read_text(
        encoding="utf-8"
    ) == write_store_record_once(tmp_path / "b.json", document).read_text(
        encoding="utf-8"
    )


# ── one publisher, across BOTH file sets ───────────────────────────────────


def _os_link_calls(tree: ast.AST) -> list[ast.Call]:
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and getattr(node.func, "attr", None) == "link"
        and getattr(getattr(node.func, "value", None), "id", None) == "os"
    ]


def _bundle_downloader_premise(source: str) -> bool:
    """Prove downloader publication is unrelated to the lease/release store."""
    tree = ast.parse(source)
    links = _os_link_calls(tree)
    functions = {
        node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)
    }
    acquire = functions.get("acquire_observed_artifact")
    if acquire is None or len(links) != 1 or links[0] not in ast.walk(acquire):
        return False
    forbidden = {"release_path", "lease_store", "write_store_record_once"}
    if any(
        isinstance(node, ast.Name) and node.id in forbidden for node in ast.walk(tree)
    ):
        return False
    if any(
        isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and ".release.json" in node.value
        for node in ast.walk(tree)
    ):
        return False
    return not any(
        isinstance(node, ast.ImportFrom)
        and (
            "lease" in (node.module or "")
            or any(alias.name in forbidden for alias in node.names)
        )
        for node in ast.walk(tree)
    )


def _runner_uses_private_download_destinations(source: str) -> bool:
    """Require this runner's direct downloader calls to use its temp directory."""
    tree = ast.parse(source)
    verify = next(
        (
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "_verify"
        ),
        None,
    )
    if verify is None:
        return False
    all_calls = [
        node
        for node in ast.walk(verify)
        if isinstance(node, ast.Call)
        and getattr(node.func, "id", None) == "acquire_observed_artifact"
    ]
    direct_calls = [
        statement.value
        for statement in verify.body
        if isinstance(statement, ast.Assign)
        and isinstance(statement.value, ast.Call)
        and getattr(statement.value.func, "id", None) == "acquire_observed_artifact"
    ]
    bindings = [
        node
        for node in ast.walk(verify)
        if (
            isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Name) and target.id == "directory"
                for target in node.targets
            )
        )
        or (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == "directory"
        )
        or (
            isinstance(node, ast.AugAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == "directory"
        )
        or (
            isinstance(node, ast.NamedExpr)
            and isinstance(node.target, ast.Name)
            and node.target.id == "directory"
        )
    ]
    direct_bindings = [
        statement
        for statement in verify.body
        if isinstance(statement, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "directory"
            for target in statement.targets
        )
    ]
    binding = bindings[0] if len(bindings) == 1 else None
    has_private_binding = (
        isinstance(binding, ast.Assign)
        and direct_bindings == [binding]
        and isinstance(binding.value, ast.Call)
        and getattr(binding.value.func, "id", None) == "_runner_directory"
        and verify.body.index(binding)
        < min(
            (
                index
                for index, statement in enumerate(verify.body)
                if isinstance(statement, ast.Assign)
                and isinstance(statement.value, ast.Call)
                and getattr(statement.value.func, "id", None)
                == "acquire_observed_artifact"
            ),
            default=0,
        )
    )
    return (
        has_private_binding
        and len(all_calls) == len(direct_calls) == 2
        and all(
            len(call.args) == 5
            and isinstance(call.args[4], ast.BinOp)
            and isinstance(call.args[4].left, ast.Name)
            and call.args[4].left.id == "directory"
            and isinstance(call.args[4].op, ast.Div)
            and isinstance(call.args[4].right, ast.Constant)
            and call.args[4].right.value in {"archive.zip", "sidecar.zip"}
            for call in direct_calls
        )
    )


def _publish_sites() -> set[str]:
    """Inventory every `os.link`; allow only the lease writer and downloader.

    The downloader's one link is a verified-artifact tempfile publication, not
    lease-store persistence. Its AST premise below proves that distinction and
    that its current direct runner caller targets private temporary filenames;
    future aliases or dynamic callers are unmonitored by this static region.
    """
    found: set[str] = set()
    for root in (PACKAGE, SCRIPTS):
        for path in python_files(root):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            if _os_link_calls(tree):
                found.add(path.name)
    return found


def test_only_the_lease_writer_publishes_into_this_store() -> None:
    """`lease.py` owns store persistence; downloader has a proven separate role.

    Independent of the canonicalization ratchet on purpose: that one watches the
    BYTES, this one watches the PUBLISH. A second writer that shared the bytes
    helper and hand-rolled only the atomic create would slip past the first and
    fail here.
    """
    downloader = SCRIPTS / "bundle_artifact_download.py"
    runner = SCRIPTS / "run_bundle_action.py"
    assert _publish_sites() == {"bundle_artifact_download.py", "lease.py"}, (
        f"{sorted(_publish_sites())} publish with os.link. "
        "only the leased-store writer and verified downloader are inventoried"
    )
    assert _bundle_downloader_premise(downloader.read_text(encoding="utf-8"))
    assert _runner_uses_private_download_destinations(
        runner.read_text(encoding="utf-8")
    )


def test_the_publish_sweep_would_see_a_second_writer(tmp_path: Path) -> None:
    """Sensitivity: the assertion above passes over a clean tree, so prove it
    can fail. Its value is entirely in the case that is not present."""
    (tmp_path / "runner.py").write_text(
        "import os\ndef write_create_only(p, d):\n    os.link(p.with_suffix('.t'), p)\n"
    )
    tree = ast.parse((tmp_path / "runner.py").read_text())
    hits = _os_link_calls(tree)
    assert len(hits) == 1


def test_downloader_premise_rejects_a_second_link_or_lease_reference() -> None:
    source = (SCRIPTS / "bundle_artifact_download.py").read_text(encoding="utf-8")
    assert not _bundle_downloader_premise(source + "\nos.link(a, b)\n")
    assert not _bundle_downloader_premise(source + "\nrelease_path = object()\n")


def test_runner_destination_premise_rejects_a_later_reassignment() -> None:
    source = (SCRIPTS / "run_bundle_action.py").read_text(encoding="utf-8")
    mutated = source.replace(
        "    directory = _runner_directory()\n",
        "    directory = _runner_directory()\n    directory = Path('/tmp/other')\n",
        1,
    )
    assert not _runner_uses_private_download_destinations(mutated)


def test_runner_destination_premise_rejects_an_unreachable_binding() -> None:
    source = (SCRIPTS / "run_bundle_action.py").read_text(encoding="utf-8")
    mutated = source.replace(
        "    directory = _runner_directory()\n",
        "    if False:\n        directory = _runner_directory()\n",
        1,
    )
    assert not _runner_uses_private_download_destinations(mutated)
