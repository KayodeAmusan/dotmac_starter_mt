"""``HostLeaseRelease.v1`` — the other end of the lease contract.

`load_lease` refuses to BEGIN without a lease record. Nothing recorded the END,
so the only evidence a shared host was finished with was the absence of a running
process and a timestamp going by. Both are inferences.

## The design under test: EXPIRY IS NOT RELEASE

Three standings, not a boolean. A boolean "is the lease live?" has two values for
three cases, so one case borrows another's answer — and the borrowed one is
always the crash, because a crashed run and a finished one both stop being live.

`EXPIRED_HELD` is that third case, and
`test_an_expired_lease_does_NOT_authorize_destruction` is the assertion the whole
module exists for.

## A refused run is terminal

A schema accepting only receipts would hold a host forever after any legitimate
refusal, and somebody would release it by hand — the mechanism this record exists
to remove. So a refusal releases, and the refusal vocabulary is closed and owned
here: a schema validating against a set the writer invents is not a validation.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from dotmac_deployment_foundation.controller_identity import (
    ControllerSshFingerprintV1,
)
from dotmac_deployment_foundation.errors import PreconditionFailed, SpecError
from dotmac_deployment_foundation.lease import HostLease
from dotmac_deployment_foundation.lease_release import (
    RELEASE_DUPLICATE,
    RELEASE_FOREIGN,
    RELEASE_MALFORMED,
    RELEASE_MISSING,
    RELEASE_NOT_DESTROYABLE,
    RELEASE_NOT_TERMINAL,
    RELEASE_PREMATURE,
    RELEASE_STALE,
    TERMINAL_REFUSALS,
    CleanupDisposition,
    HostClosure,
    HostLeaseReleaseV1,
    HostStanding,
    ReleasingPrincipal,
    TerminalOutcome,
    TerminalRefusal,
    host_standing,
    lease_digest,
    require_release_before_destruction,
)

SLOT = "dotmacproxmox/102"
PRINCIPAL_SUBJECT = "repo:michaelayoade/dotmac_starter_mt:ref:refs/heads/main"
#: Two REAL OpenSSH fingerprints — `SHA256:` and 43 characters of unpadded
#: base64, as `ssh-keygen -lf` emits. These fixtures used to carry
#: `"sha256:" + "a" * 64`, the CONTENT DIGEST shape the old regex required and
#: the one shape a key fingerprint is never written in.
CONTROLLER = ControllerSshFingerprintV1.parse(
    "SHA256:T1kdK/6QTzzwU1EienO6nUgk8wu9UpjqB8BatKbndSE", field="controller"
)
OTHER_CONTROLLER = ControllerSshFingerprintV1.parse(
    "SHA256:cegy+e5RS5FWNVo7WNxR7JxpNiODBabD/g0PttX3mzA", field="controller"
)
LIVE = datetime(2026, 9, 4, 3, 0, tzinfo=UTC)
AFTER = datetime(2026, 9, 4, 7, 0, tzinfo=UTC)


def _lease(**over) -> HostLease:
    kwargs = {
        "target": "192.0.2.54",
        "holder": "deployment-foundation-rehearsal",
        "authorization_run_id": "33854964978",
        "starts_at": "2026-09-04T00:00:00Z",
        "expires_at": "2026-09-04T06:00:00Z",
        "compose_project_prefix": "rehearsal-",
        "controller_identity_fingerprint": CONTROLLER,
        "workload_principal": PRINCIPAL_SUBJECT,
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
        "authorization_run_id": lease.authorization_run_id,
        "rehearsal_run_id": "33860000001",
        "outcome": TerminalOutcome(receipt_digest="sha256:" + "b" * 64),
        "released_at": "2026-09-04T05:00:00Z",
        "released_by": ReleasingPrincipal(
            kind="github_actions_workload",
            subject=PRINCIPAL_SUBJECT,
            run_binding="33860000001",
        ),
        "controller_identity_fingerprint": CONTROLLER,
        "closure": HostClosure.REUSABLE,
        "cleanup": CleanupDisposition.PURGED,
    }
    kwargs.update(over)
    return HostLeaseReleaseV1(**kwargs)


def _destroy(release, *, now=AFTER, slot=SLOT, candidate="0.4.0a1", **kw):
    return require_release_before_destruction(
        _lease(), release, now=now, vm_slot=slot, candidate_version=candidate, **kw
    )


# ── the record names WHICH ARTIFACT ran, and separately WHICH RUNNER ───────
#
# `source_revision`'s own docstring said "WHICH artifact ran — a release from
# another candidate's run is evidence about another run", and the runner
# populated it with its OWN head SHA. The field said one thing and carried
# another, so a destroyer reading it attributed the bytes to the wrong commit.


def test_the_release_names_both_revisions_and_they_are_not_one_field() -> None:
    """Two questions, two fields. Fails before the change: `HostLeaseReleaseV1`
    took `source_revision` and had no `runner_revision`, so this construction
    raises `TypeError`."""
    release = _release()
    assert release.candidate_source_revision == "0" * 40
    assert release.runner_revision == "1" * 40
    assert release.candidate_source_revision != release.runner_revision


def test_the_document_carries_both_under_their_own_names() -> None:
    """The rename reaches the DOCUMENT, not just the attribute. A destroyer
    reads the stored JSON, so a field renamed in Python and left alone in
    `as_document` would change nothing where it matters."""
    document = _release().as_document()
    assert document["candidate_source_revision"] == "0" * 40
    assert document["runner_revision"] == "1" * 40
    assert "source_revision" not in document, (
        "the old name is still emitted, so one record now answers the same "
        "question twice and a reader may believe either"
    )


def test_the_writer_and_the_READER_agree_on_both_new_names(
    tmp_path: Path,
) -> None:
    """A rename that reaches `as_document` and not the parser produces a record
    the store can write and cannot read back. Driven through the real pair.

    Written and reloaded through `lease.py`'s store, which is the only publisher
    — the same one the `os.link` sweep pins — so this exercises the path a
    destroyer actually reads from.
    """
    from dotmac_deployment_foundation.lease import write_lease
    from dotmac_deployment_foundation.lease_release import load_release, write_release

    lease = _lease()
    write_lease(lease, directory=tmp_path)
    original = _release(lease)
    write_release(original, target=lease.target, directory=tmp_path)
    reloaded = load_release(lease.target, directory=tmp_path)
    assert reloaded is not None
    assert reloaded.candidate_source_revision == original.candidate_source_revision
    assert reloaded.runner_revision == original.runner_revision
    assert reloaded.digest() == original.digest()


@pytest.mark.parametrize("field", ["candidate_source_revision", "runner_revision"])
def test_neither_revision_may_be_empty(field: str) -> None:
    """Both are things a destroyer checks before wiping a machine, so both are
    required. A field added as optional would be a field nobody fills."""
    with pytest.raises(SpecError) as exc:
        _release(**{field: "   "})
    assert exc.value.code == RELEASE_MALFORMED
    assert field in str(exc.value)


def test_the_record_carries_NO_publication_revision() -> None:
    """The producer cannot observe it, so the field must not exist.

    A release is sealed by the Lane 3 runner. Which commit later publishes has
    not been decided at that moment, so any value here would be a guess, a
    default, or a copy of one of the other two — and each reads to a destroyer
    as an established fact. A field its only producer cannot fill truthfully is
    worse than an absent one.

    Asserted over the DOCUMENT's key set rather than by name-spotting, so a
    future `release_revision`, `publication_revision` or `tag_revision` is
    caught by the same test rather than by whichever alias someone picks.
    """
    keys = set(_release().as_document())
    forbidden = {k for k in keys if "publi" in k or "release_revision" in k}
    assert forbidden == set(), (
        f"the release record carries {sorted(forbidden)}. The Lane 3 runner "
        "cannot observe the publication revision; a field it cannot fill "
        "truthfully must not exist in its record"
    )
    # And the two it CAN observe are both present, so this is not passing by
    # the record being empty.
    assert {"candidate_source_revision", "runner_revision"} <= keys


# ── expiry is not release ───────────────────────────────────────────────────


def test_the_three_standings_are_three_and_not_a_boolean() -> None:
    assert {s.value for s in HostStanding} == {"held", "expired_held", "released"}


def test_a_live_unreleased_lease_is_HELD() -> None:
    assert host_standing(_lease(), None, now=LIVE) is HostStanding.HELD


def test_an_expired_unreleased_lease_is_EXPIRED_HELD_not_released() -> None:
    """The crash's shape. A boolean would report it as "not live", which is the
    same answer a finished run gets."""
    assert host_standing(_lease(), None, now=AFTER) is HostStanding.EXPIRED_HELD


def test_a_released_lease_is_RELEASED() -> None:
    assert host_standing(_lease(), _release(), now=AFTER) is HostStanding.RELEASED


def test_an_expired_lease_does_NOT_authorize_destruction() -> None:
    """THE assertion this module exists for.

    A run that dies at 03:00 leaves no release; its lease expires at 06:00; a
    destroyer reading only "is the lease live?" finds "no" and takes it as
    permission. It is not permission — it is the absence of a holder who can say
    anything, which is exactly when destroying a host is least safe.
    """
    with pytest.raises(PreconditionFailed) as exc:
        _destroy(None)
    assert exc.value.code == RELEASE_MISSING


def test_a_live_lease_does_not_authorize_destruction_either() -> None:
    """Distinguished from the above by its own code: destroying a host out from
    under a working holder is a different mistake from destroying one whose
    holder vanished."""
    with pytest.raises(PreconditionFailed) as exc:
        _destroy(None, now=LIVE)
    assert exc.value.code == RELEASE_PREMATURE
    assert RELEASE_PREMATURE != RELEASE_MISSING


def test_a_release_authorizes_destruction() -> None:
    """The positive control. Without it every refusal above could come from a
    gate that refuses everything."""
    assert _destroy(_release()) is not None


# ── a refused run is terminal ───────────────────────────────────────────────


def test_a_refused_run_may_release_the_host() -> None:
    """A schema accepting only receipts holds the host forever after any
    legitimate refusal, and somebody then releases it by hand — which is the
    mechanism this record exists to remove."""
    release = _release(
        outcome=TerminalOutcome(refusal=TerminalRefusal.EVIDENCE_INCOMPLETE),
        cleanup=CleanupDisposition.NOT_ATTEMPTED,
    )
    assert _destroy(release).outcome.refused


def test_an_outcome_with_neither_is_NOT_terminal() -> None:
    with pytest.raises(SpecError) as exc:
        TerminalOutcome()
    assert exc.value.code == RELEASE_NOT_TERMINAL


def test_an_outcome_with_both_is_a_run_that_ended_twice() -> None:
    with pytest.raises(SpecError) as exc:
        TerminalOutcome(
            receipt_digest="sha256:" + "b" * 64,
            refusal=TerminalRefusal.PROBE_REFUSED,
        )
    assert exc.value.code == RELEASE_MALFORMED


def test_the_refusal_vocabulary_is_closed_and_owned_here() -> None:
    """A schema validating a code against a set the WRITER invents is not a
    validation. The reader of this record decides whether a host may be
    destroyed, so the vocabulary it branches on belongs with the record.

    Written longhand so a member appearing or disappearing is a reviewed diff.
    """
    assert set(TERMINAL_REFUSALS) == {
        "evidence_unreadable",
        "evidence_incomplete",
        "probe_refused",
        "receipt_inconsistent",
        "precondition_unfit",
        # Was `provocation_unestablished`, which named ONE instance of the
        # condition and left every other instance — a `StepFailed` from a failed
        # compose apply above all — with no member at all. Renamed and
        # generalized, not added to: still six.
        "host_state_uncertified",
    }
    assert len(set(TERMINAL_REFUSALS)) == 6


def test_no_member_is_inert() -> None:
    """Every member maps to at least one real raise site, recorded in the enum's
    own docstring table.

    An earlier draft carried `vantage_unavailable`, derived from one site that
    was then correctly remapped — leaving a member nobody raises, which is a code
    for something that cannot happen and a test that can never fail. That is the
    defect the release-evidence lane caught in itself, and this is the check that
    keeps it from arriving here by arithmetic.
    """
    from dotmac_deployment_foundation import lease_release

    table = lease_release.TerminalRefusal.__doc__ or ""
    for member in TERMINAL_REFUSALS:
        assert f"`{member}`" in table, (
            f"{member} appears in no row of the derivation table, so no site "
            "raises it. A member without a site is inert"
        )


def test_the_two_host_state_refusals_are_opposite_operator_actions() -> None:
    """`precondition_unfit` means do not touch the machine, fix the input.
    `host_state_uncertified` means inspect the machine before re-running — nobody
    can say what state it is in. One member cannot carry both."""
    assert TerminalRefusal.PRECONDITION_UNFIT != TerminalRefusal.HOST_STATE_UNCERTIFIED
    # CONSTRUCTIBILITY, not destroyability. The two are different claims and this
    # test is about the first: `inspection_required` is a legitimate closure that
    # deliberately does NOT authorize a wipe, which is
    # `test_inspection_required_does_NOT_authorize_destruction`'s subject.
    assert _release(
        outcome=TerminalOutcome(refusal=TerminalRefusal.PRECONDITION_UNFIT),
        cleanup=CleanupDisposition.NOT_ATTEMPTED,
        closure=HostClosure.REUSABLE,
    )
    assert _release(
        outcome=TerminalOutcome(refusal=TerminalRefusal.HOST_STATE_UNCERTIFIED),
        cleanup=CleanupDisposition.NOT_ATTEMPTED,
        closure=HostClosure.INSPECTION_REQUIRED,
    )


def test_an_open_string_is_not_a_refusal() -> None:
    with pytest.raises(SpecError) as exc:
        TerminalOutcome(refusal="the probe did not come back")  # type: ignore[arg-type]
    assert exc.value.code == RELEASE_MALFORMED


# ── VM identity: the slot, not the address ─────────────────────────────────


def test_an_ADDRESS_is_refused_as_the_vm_identity() -> None:
    """The addresses are exactly what a destroy-and-restore can change, so an
    address binds by coincidence and could name a different machine afterwards."""
    with pytest.raises(SpecError) as exc:
        _release(vm_slot="192.0.2.54")
    assert exc.value.code == RELEASE_MALFORMED


def test_the_slot_must_be_the_slot_about_to_be_destroyed() -> None:
    with pytest.raises(PreconditionFailed) as exc:
        _destroy(_release(), slot="dotmacproxmox/103")
    assert exc.value.code == RELEASE_FOREIGN


def test_an_empty_installation_id_is_a_STATED_value() -> None:
    """The same rule `application_profile_digest` follows: `""` means "not
    recorded" and is accepted; a default would let a writer carry the answer
    without deciding it."""
    assert _destroy(_release(vm_installation_id="")) is not None


def test_a_reprovisioned_slot_is_caught_when_the_installation_IS_recorded() -> None:
    """The one case the slot alone cannot catch."""
    with pytest.raises(PreconditionFailed) as exc:
        _destroy(_release(vm_installation_id="a" * 32), vm_installation_id="b" * 32)
    assert exc.value.code == RELEASE_FOREIGN


def test_a_malformed_installation_id_is_refused() -> None:
    with pytest.raises(SpecError) as exc:
        _release(vm_installation_id="not-a-machine-id")
    assert exc.value.code == RELEASE_MALFORMED


# ── the release must be THIS lease's ────────────────────────────────────────


def test_the_lease_digest_is_a_pure_function_of_the_PARSED_lease() -> None:
    """No path, no raw bytes. The runner digests the lease it already loaded, so
    there is no second opinion about where a lease lives and `load_lease` needs
    no new return value."""
    lease = _lease()
    twin = _lease()
    assert lease_digest(lease) == lease_digest(twin)
    assert lease_digest(_lease(target="other")) != lease_digest(lease)


def test_a_release_for_another_lease_is_refused() -> None:
    with pytest.raises(PreconditionFailed) as exc:
        _destroy(_release(lease_digest="sha256:" + "9" * 64))
    assert exc.value.code == RELEASE_FOREIGN


def test_a_release_for_another_candidate_is_refused() -> None:
    with pytest.raises(PreconditionFailed) as exc:
        _destroy(_release(candidate_version="0.3.0a6"))
    assert exc.value.code == RELEASE_FOREIGN


def test_a_release_under_another_authorization_is_refused() -> None:
    """`HostLease` already refuses to be self-granted; a release that could be
    self-granted would reopen that at the other end."""
    with pytest.raises(PreconditionFailed) as exc:
        _destroy(_release(authorization_run_id="99"))
    assert exc.value.code == RELEASE_FOREIGN


def test_a_release_dated_before_the_lease_is_stale() -> None:
    with pytest.raises(PreconditionFailed) as exc:
        _destroy(_release(released_at="2026-09-03T00:00:00Z"))
    assert exc.value.code == RELEASE_STALE


def test_a_second_release_of_one_lease_is_refused() -> None:
    """Either a replay, or two runs each believing they finished the same work."""
    release = _release()
    with pytest.raises(PreconditionFailed) as exc:
        _destroy(release, seen_release_digests=frozenset({release.digest()}))
    assert exc.value.code == RELEASE_DUPLICATE


# ── the schema must not push the writer toward a bare except ───────────────


def test_nothing_required_is_producible_ONLY_by_a_graceful_path() -> None:
    """The writing lane emits on typed terminal outcomes and deliberately not
    from a bare `except`, because collapsing an exception with a SIGKILL is how
    a killed run comes to authorise a destroy.

    A schema requiring a field only the graceful path can produce would push the
    writer back toward the broad handler. So the hardest case is asserted
    constructible: a refusal that created nothing, with no receipt and no
    cleanup performed — every remaining field is known at lease-acquisition
    time.
    """
    assert _release(
        outcome=TerminalOutcome(refusal=TerminalRefusal.PRECONDITION_UNFIT),
        cleanup=CleanupDisposition.NOT_ATTEMPTED,
        vm_installation_id="",
    )


def test_cleanup_is_closed_and_has_no_default() -> None:
    """ "Cleaned up" is the claim most worth being unable to make vaguely."""
    assert {c.value for c in CleanupDisposition} == {
        "purged",
        "retained_for_inspection",
        "not_attempted",
        "failed",
        "outcome_unknown",
    }
    with pytest.raises(SpecError) as exc:
        _release(cleanup="done")  # type: ignore[arg-type]
    assert exc.value.code == RELEASE_MALFORMED


def test_the_document_names_its_schema() -> None:
    assert _release().as_document()["schema"] == "HostLeaseRelease.v1"
    assert _release().digest().startswith("sha256:")


def test_the_two_subprocess_sites_still_cannot_discriminate() -> None:
    """The amendment trigger for `vantage_unavailable`, as a red build.

    The writing lane filed the inside-vantage probe's non-zero exit as "the jump
    could not be used at all" — a real fact, different from the probe phase's
    "the probe ran and the target refused it", and pointing at the opposite
    investigation.

    But both sites run a shell script through `subprocess.run(check=False)` and
    raise on `returncode != 0`, carrying stderr into the message. NOTHING
    interprets the exit codes, so both collapse "unreachable", "refused" and
    "bad argument" into one raise. A `vantage_unavailable` member today would
    have to be populated by matching stderr prose — a code that says something
    false, which is worse than one that says nothing.

    When the scripts grow distinct statuses, this fails, and the failure is the
    prompt: the discrimination is now possible, so the vocabulary can grow and
    `vantage_unavailable` arrives with a site that genuinely raises it.
    """
    import ast
    from pathlib import Path as _P

    root = _P(__file__).resolve().parents[2] / "scripts"
    comparisons = []
    for name in ("lane3_inside_vantage.py", "exposure_rehearsal_runner.py"):
        tree = ast.parse((root / name).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Compare) and "returncode" in ast.unparse(node.left):
                comparisons.append(ast.unparse(node))
    assert comparisons, "the sweep found no returncode comparison at all"
    assert all(c.endswith("!= 0") for c in comparisons), (
        f"a probe site now discriminates WHY a subprocess failed: {comparisons}. "
        "That is the change that makes `vantage_unavailable` derivable rather "
        "than guessed — revisit TerminalRefusal and add it with its site"
    )


# ── the closure axis: the refusal BOUNDS what the host may be used for ─────


def test_host_state_uncertified_may_NEVER_be_generally_reusable() -> None:
    """The constraint enforced by the type, not by the writer's discipline.

    The failure it prevents is concrete: a run that seeded a foreign rule,
    failed, and partially unwound — or one whose compose apply failed on the
    host — releasing a host the NEXT lease treats as clean.
    """
    with pytest.raises(SpecError) as exc:
        _release(
            outcome=TerminalOutcome(refusal=TerminalRefusal.HOST_STATE_UNCERTIFIED),
            closure=HostClosure.REUSABLE,
        )
    assert exc.value.code == RELEASE_MALFORMED


@pytest.mark.parametrize(
    "closure", [HostClosure.INSPECTION_REQUIRED, HostClosure.DESTROY_ONLY]
)
def test_host_state_uncertified_may_close_into_the_two_it_is_allowed(
    closure: HostClosure,
) -> None:
    assert _release(
        outcome=TerminalOutcome(refusal=TerminalRefusal.HOST_STATE_UNCERTIFIED),
        closure=closure,
    )


def test_the_cleanup_axis_still_ANSWERS_when_the_refusal_bounds_the_closure() -> None:
    """A refusal that constrains the closure does not excuse the cleanup axis.

    `cleanup` has no default on `HostLeaseReleaseV1`, so it cannot be omitted —
    and reusability stays the INTERSECTION of the two constraints rather than
    whichever one happened to fire. "The state is uncertified" and "something the
    lease created is still there" are different facts, and a destroyer reads them
    differently.
    """
    import dataclasses

    field = HostLeaseReleaseV1.__dataclass_fields__["cleanup"]
    assert field.default is dataclasses.MISSING
    assert field.default_factory is dataclasses.MISSING

    uncertified = TerminalOutcome(refusal=TerminalRefusal.HOST_STATE_UNCERTIFIED)
    # Bounded by the REFUSAL while the cleanup axis is unconstrained...
    assert (
        _release(
            outcome=uncertified,
            cleanup=CleanupDisposition.PURGED,
            closure=HostClosure.INSPECTION_REQUIRED,
        ).cleanup
        is CleanupDisposition.PURGED
    )
    # ...and bounded by the CLEANUP where the refusal is not, so neither axis is
    # doing the other's work.
    with pytest.raises(SpecError):
        _release(
            outcome=TerminalOutcome(receipt_digest="sha256:" + "b" * 64),
            cleanup=CleanupDisposition.FAILED,
            closure=HostClosure.REUSABLE,
        )


def test_precondition_unfit_CAN_take_the_releasable_pole() -> None:
    """Both directions, or the constraint only ever says no and cannot be shown
    to permit anything. Untouched and safely releasable is the whole point of
    this pole — with `LANE3_JUMP_KEY` unset the runner refuses before it opens a
    single TCP connection, which is where that sentence is true."""
    assert _release(
        outcome=TerminalOutcome(refusal=TerminalRefusal.PRECONDITION_UNFIT),
        closure=HostClosure.REUSABLE,
    )


def test_the_two_axes_do_not_collapse() -> None:
    """Why the run ended, and what the host may now be used for. A refusal code
    that only describes is one an operator cannot act against."""
    assert {c.value for c in HostClosure} == {
        "reusable",
        "inspection_required",
        "destroy_only",
    }
    assert len({c.value for c in HostClosure} & set(TERMINAL_REFUSALS)) == 0


# ── released_by is a derived principal, not a name ────────────────────────


def test_an_operator_name_is_refused_as_the_releasing_principal() -> None:
    """A non-empty string is satisfied by whoever was watching. The principal
    that CLOSED the lease is the authenticated workload."""
    with pytest.raises(SpecError) as exc:
        ReleasingPrincipal(
            kind="github_actions_workload",
            subject="Michael Ayoade",
            run_binding="33860000001",
        )
    assert exc.value.code == RELEASE_MALFORMED


def test_a_principal_from_ANOTHER_run_is_refused() -> None:
    """`run_binding` is what makes it derived rather than declared."""
    with pytest.raises(SpecError) as exc:
        _release(
            released_by=ReleasingPrincipal(
                kind="github_actions_workload",
                subject=PRINCIPAL_SUBJECT,
                run_binding="some-other-run",
            )
        )
    assert exc.value.code == RELEASE_FOREIGN


def test_the_controller_fingerprint_is_NOT_the_releasing_principal() -> None:
    """Two facts, two fields: who touched the host, and who closed the lease."""
    document = _release().as_document()
    assert document["controller_identity_fingerprint"].startswith("SHA256:")
    assert document["released_by"]["kind"] == "github_actions_workload"
    assert "SHA256:" not in document["released_by"]["subject"]


def test_the_release_controller_must_be_this_leases_controller() -> None:
    """A well-formed fingerprint of the WRONG key. It parses; it is not this
    lease's controller, and the gate compares DECODED DIGESTS rather than
    text."""
    with pytest.raises(PreconditionFailed) as exc:
        _destroy(_release(controller_identity_fingerprint=OTHER_CONTROLLER))
    assert exc.value.code == RELEASE_FOREIGN


# ── HostLease.v2: three fields, three facts ───────────────────────────────


def test_the_lease_writes_v2_and_v1_is_historical() -> None:
    """V1's reader and writer shipped in five built candidate wheels, including
    the one that is Platform CP's bootstrap input. A contract that has crossed an
    artifact boundary cannot be widened."""
    from dotmac_deployment_foundation.lease import (
        HOST_LEASE_SCHEMA,
        HOST_LEASE_SCHEMA_V1,
        HistoricalLeaseV1,
    )

    assert HOST_LEASE_SCHEMA == "HostLease.v2"
    assert HOST_LEASE_SCHEMA_V1 == "HostLease.v1"
    assert _lease().as_document()["schema"] == HOST_LEASE_SCHEMA
    # Readable, and structurally unable to authorize: no `covers()` to call and
    # no principal to bind. Not "it would be rejected".
    assert not hasattr(HistoricalLeaseV1, "covers")
    assert "workload_principal" not in {
        f.name for f in HistoricalLeaseV1.__dataclass_fields__.values()
    }


def test_all_three_identity_fields_are_in_the_canonical_bytes() -> None:
    """The fingerprint is a separate FACT but not a separate DOCUMENT, so a lease
    that swapped credentials while keeping its principal must digest
    differently."""
    base = _lease()
    for field, value in (
        ("holder", "deployment-foundation-rehearsal"),
        ("workload_principal", "repo:michaelayoade/other:ref:refs/heads/main"),
        ("controller_identity_fingerprint", OTHER_CONTROLLER),
    ):
        if field == "holder":
            continue  # a fixed token; the other two are the movable ones
        assert lease_digest(_lease(**{field: value})) != lease_digest(base), field


def test_released_by_must_be_THIS_leases_workload_principal() -> None:
    """A principal that merely authenticated is not the party that took the
    host."""
    other = _lease(workload_principal="repo:michaelayoade/other:ref:refs/heads/main")
    release = _release(other)
    with pytest.raises(PreconditionFailed) as exc:
        require_release_before_destruction(
            _lease(),
            release,
            now=AFTER,
            vm_slot=SLOT,
            candidate_version="0.4.0a1",
        )
    assert exc.value.code in {RELEASE_FOREIGN}


def test_a_workload_rotation_requires_a_NEW_lease() -> None:
    """The property that stops a long-lived lease outliving the identity that
    took it. Rotating the principal makes every release under the old lease
    refuse — there is no way to keep the lease and change who holds it."""
    rotated = ReleasingPrincipal(
        kind="github_actions_workload",
        subject="repo:michaelayoade/dotmac_starter_mt:ref:refs/heads/rotated",
        run_binding="33860000001",
    )
    with pytest.raises(PreconditionFailed) as exc:
        _destroy(_release(released_by=rotated))
    assert exc.value.code == RELEASE_FOREIGN


# ── cleanup: failed OR unknown never reaches general availability ─────────


@pytest.mark.parametrize(
    "cleanup", [CleanupDisposition.FAILED, CleanupDisposition.OUTCOME_UNKNOWN]
)
def test_failed_or_unknown_cleanup_may_not_be_generally_reusable(
    cleanup: CleanupDisposition,
) -> None:
    """Both, and for different reasons landing in the same place: something the
    lease created is either still there, or nobody can say it is not."""
    with pytest.raises(SpecError) as exc:
        _release(cleanup=cleanup, closure=HostClosure.REUSABLE)
    assert exc.value.code == RELEASE_MALFORMED


@pytest.mark.parametrize(
    "cleanup", [CleanupDisposition.FAILED, CleanupDisposition.OUTCOME_UNKNOWN]
)
@pytest.mark.parametrize(
    "closure", [HostClosure.INSPECTION_REQUIRED, HostClosure.DESTROY_ONLY]
)
def test_failed_or_unknown_cleanup_may_take_the_restricted_closures(
    cleanup: CleanupDisposition, closure: HostClosure
) -> None:
    assert _release(cleanup=cleanup, closure=closure)


def test_unknown_cleanup_does_not_borrow_not_attempteds_answer() -> None:
    """ "We did not try" and "we tried and do not know" are different facts, and
    the borrowed answer is always the one that looks safer. `not_attempted` may
    still be reusable; `outcome_unknown` may not."""
    assert _release(
        cleanup=CleanupDisposition.NOT_ATTEMPTED, closure=HostClosure.REUSABLE
    )
    with pytest.raises(SpecError):
        _release(
            cleanup=CleanupDisposition.OUTCOME_UNKNOWN, closure=HostClosure.REUSABLE
        )


def test_the_two_constraints_compose_rather_than_replace() -> None:
    """A refusal's permitted set and a cleanup's are intersected. Either alone
    would let the other's restricted case through."""
    assert _release(
        outcome=TerminalOutcome(refusal=TerminalRefusal.PRECONDITION_UNFIT),
        cleanup=CleanupDisposition.OUTCOME_UNKNOWN,
        closure=HostClosure.DESTROY_ONLY,
    )
    with pytest.raises(SpecError):
        _release(
            outcome=TerminalOutcome(refusal=TerminalRefusal.PRECONDITION_UNFIT),
            cleanup=CleanupDisposition.OUTCOME_UNKNOWN,
            closure=HostClosure.REUSABLE,
        )


# ── an explicit release is not by itself permission to destroy ────────────


def test_inspection_required_does_NOT_authorize_destruction() -> None:
    """The second axis has to bite at the gate too, or it is decorative.

    `inspection_required` says a human looks BEFORE anything else uses this host,
    and destroying it is the one act that makes that inspection impossible.
    Reading "a release exists" as "the host may be wiped" collapses the closure
    axis back into the refusal axis — which is the whole reason they are separate.
    """
    release = _release(
        outcome=TerminalOutcome(refusal=TerminalRefusal.HOST_STATE_UNCERTIFIED),
        cleanup=CleanupDisposition.FAILED,
        closure=HostClosure.INSPECTION_REQUIRED,
    )
    with pytest.raises(PreconditionFailed) as exc:
        _destroy(release)
    assert exc.value.code == RELEASE_NOT_DESTROYABLE


@pytest.mark.parametrize("closure", [HostClosure.DESTROY_ONLY, HostClosure.REUSABLE])
def test_the_other_two_closures_do_authorize_destruction(
    closure: HostClosure,
) -> None:
    """The positive control: the gate must not be one that refuses every
    release. `destroy_only` is fit for nothing else; `reusable` is a host nobody
    needs to look at first."""
    assert _destroy(_release(closure=closure))
