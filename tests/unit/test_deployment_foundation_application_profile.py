"""`ApplicationFoundationProfile.v1` — the contract refuses, the gate reports.

## The two halves, and the reader who will get this wrong

- **The type refuses.** A profile with a missing concern is unconstructable. No
  warning branch (ADR 0039 § 4).
- **The verification is report-only.** Nothing on the boot or deploy path is
  gated by profile completeness, because ADR 0039 stages the § 4 refusal per
  concern rather than switching it on for all thirteen at once. (A count of how
  many concerns the fleet can bind today used to stand here and was withdrawn on
  2026-09-04 — see `application_profile.py`'s docstring for why a facility must
  not hold a fleet-maturity fact it cannot check.)

Those are not in tension — they are the two halves the ADR's own staging
paragraph describes, and together they are exactly Michael's acceptance
condition: **a report-only implementation that can admit a real candidate and
reject planted defects.** The first half is what makes the planted defects
detectable at all.

`test_no_deployment_path_is_gated_by_profile_completeness` holds the second half
so that someone reading the first cannot quietly convert this into a live gate.
"""

from __future__ import annotations

from typing import Final

import pytest
from dotmac_deployment_foundation.application_profile import (
    ABSENCE_WRONG_CONCERN,
    APPLICATION_PROFILE_SCHEMA,
    BINDING_FIELDS,
    CONCERN_LABELS,
    INTEGRATION_SURFACE_FAMILIES,
    WORK_ENTRY_POINT_FAMILIES,
    WRITER_DISPOSITIONS,
    AbsenceProof,
    ApplicationFoundationProfile,
    ConcernBinding,
    FoundationConcern,
    InapplicableConcern,
    IntegrationSurfaceAbsenceProofV1,
    WriterClaim,
    profile_digest,
    require_profile_readback,
    verify_profile_against_candidate,
)
from dotmac_deployment_foundation.errors import PreconditionFailed, SpecError

IMAGE = "acme/app@sha256:" + "c" * 64
COORD = "acme-foundation@sha256:" + "b" * 64
REVISION = "a" * 40


def _binding(**over) -> ConcernBinding:
    fields = {
        "implementation": "acme-foundation",
        "version": "1.0.0",
        "coordinates": COORD,
    }
    fields.update(over)
    return ConcernBinding(**fields)  # type: ignore[arg-type]


def _proof(**over) -> AbsenceProof:
    fields = {
        "image_digest": IMAGE,
        "families": dict.fromkeys(WORK_ENTRY_POINT_FAMILIES, ()),
        "method": "entry-point metadata",
        "positive_control": ("console_scripts:acme-cli",),
    }
    fields.update(over)
    return AbsenceProof(**fields)  # type: ignore[arg-type]


def _profile(**over) -> ApplicationFoundationProfile:
    slots = dict.fromkeys(FoundationConcern, _binding())
    slots.update(over.pop("slots", {}))
    return ApplicationFoundationProfile(
        application=over.pop("application", "acme-app"), slots=slots
    )


# ── the thirteen, closed, and checked against the record ────────────────────


def test_there_are_exactly_thirteen_concerns() -> None:
    assert len(list(FoundationConcern)) == 13


def test_every_concern_carries_the_ADRs_own_wording() -> None:
    """Kept verbatim so a reviewer compares this module with ADR 0039 § 2
    without paraphrasing, and so a renamed member cannot come to mean a
    different concern."""
    assert set(CONCERN_LABELS) == set(FoundationConcern)
    assert CONCERN_LABELS[FoundationConcern.API_WEB_INTERACTION] == (
        "API / web interaction"
    )
    assert CONCERN_LABELS[FoundationConcern.DEPLOYMENT_RECOVERY] == (
        "deployment / recovery"
    )


def test_the_two_thirteens_are_not_the_same_vocabulary() -> None:
    """`recovery.BundleComponent` ALSO has thirteen members. Different
    vocabularies — and the point is not merely 'do not conflate them'.

    They are RELATED, and a reader who stops at the warning misses it:
    `BundleComponent`'s thirteen are the database-fact set a recovery bundle
    carries and the verification registry compares; these thirteen are the
    concerns an application composes, one of which (`deployment / recovery`)
    would OWN that bundle contract. This test holds the distinction; the
    module docstring holds the connection.
    """
    from dotmac_deployment_foundation.recovery import BundleComponent

    assert len(list(BundleComponent)) == 13
    assert not {c.value for c in FoundationConcern} & {c.value for c in BundleComponent}


# ── § 4: a missing concern does not compose, and there is no warning ────────


def test_a_profile_missing_one_concern_is_unconstructable() -> None:
    slots = dict.fromkeys(FoundationConcern, _binding())
    del slots[FoundationConcern.EDGE_SECURITY]
    with pytest.raises(SpecError) as caught:
        ApplicationFoundationProfile(application="acme-app", slots=slots)
    assert "edge_security" in str(caught.value)


@pytest.mark.parametrize("concern", list(FoundationConcern))
def test_every_single_concern_is_individually_required(
    concern: FoundationConcern,
) -> None:
    """All thirteen, not a sample. A required-field check that only ever
    exercised one member would pass while twelve were optional."""
    slots = dict.fromkeys(FoundationConcern, _binding())
    del slots[concern]
    with pytest.raises(SpecError):
        ApplicationFoundationProfile(application="acme-app", slots=slots)


def test_there_is_no_warning_path_at_all() -> None:
    """§ 4 prohibits it explicitly: given a warning branch, every incomplete
    profile becomes a warning and the record survives as documentation of a
    control nobody runs.

    Checked as a PROPERTY, not as a word. The first version of this test grepped
    the class source for "warn" and failed on the docstring explaining that
    there is no warning — a detector reading a name instead of the thing, which
    is the exact subject-shape defect AGENTS.md rule 25 names. Prose is stripped
    by parsing, and what is checked is the two shapes a warning path actually
    takes: a call that emits one, and a parameter that admits an incomplete
    profile.
    """
    import ast
    import inspect
    import textwrap

    tree = ast.parse(textwrap.dedent(inspect.getsource(ApplicationFoundationProfile)))

    emitters = {
        node.func.attr if isinstance(node.func, ast.Attribute) else node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name | ast.Attribute)
    }
    assert not emitters & {
        "warn",
        "warning",
        "warns",
    }, f"the profile emits a warning: {sorted(emitters & {'warn', 'warning', 'warns'})}"

    parameters = {
        argument.arg
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
        for argument in [*node.args.args, *node.args.kwonlyargs]
    }
    bypasses = parameters & {"strict", "force", "allow_incomplete", "warn_only"}
    assert not bypasses, f"the profile takes a bypass parameter: {sorted(bypasses)}"

    fields = set(ApplicationFoundationProfile.__dataclass_fields__)
    assert fields == {"application", "slots"}, (
        f"the profile grew a field: {sorted(fields)}. A knob that admits an "
        "incomplete profile for one deployment is what § 4 forbids"
    )


def test_a_complete_profile_constructs() -> None:
    """POSITIVE CONTROL. A refusal suite whose subject can never be built proves
    nothing about the refusals."""
    assert len(_profile().bound) == 13


# ── § 3 and § 10: a binding names three things and nothing else ─────────────


@pytest.mark.parametrize(
    "coordinate",
    ["main", "latest", "v1.2.3", "acme/app:latest", "acme/app:1.2.3", "abc123", ""],
)
def test_a_moving_coordinate_is_refused(coordinate: str) -> None:
    """ADR 0013 § 3. An installation adopts BY DIGEST, so a claim measured
    against a reference that can move is not a claim about any bytes."""
    with pytest.raises(SpecError):
        _binding(coordinates=coordinate)


@pytest.mark.parametrize(
    "coordinate",
    ["acme/app@sha256:" + "d" * 64, "sha256:" + "e" * 64, "f" * 40],
)
def test_an_immutable_coordinate_is_accepted(coordinate: str) -> None:
    """The positive half: the three admissible shapes actually pass."""
    assert _binding(coordinates=coordinate).coordinates == coordinate


def test_the_binding_field_set_is_closed() -> None:
    assert BINDING_FIELDS == {
        "implementation",
        "version",
        "coordinates",
        "displaces",
        "retirement",
    }


def test_a_policy_value_is_refused_by_the_parser_not_by_a_reviewer() -> None:
    """§ 10's first mechanical consequence. A profile is the most attractive
    place in an architecture to put a value with nowhere else to live, so the
    extra key is REFUSED rather than ignored — ignoring is how a closed set
    quietly opens."""
    from dotmac_deployment_foundation.application_profile import (
        _binding_from_document,
    )

    with pytest.raises(SpecError) as caught:
        _binding_from_document(
            {
                "implementation": "acme-foundation",
                "version": "1.0.0",
                "coordinates": COORD,
                "rate_limit_per_minute": 600,
            },
            where="planted",
        )
    assert "rate_limit_per_minute" in str(caught.value)


def test_a_conforming_binding_document_parses() -> None:
    from dotmac_deployment_foundation.application_profile import (
        _binding_from_document,
    )

    parsed = _binding_from_document(
        {"implementation": "acme-foundation", "version": "1.0.0", "coordinates": COORD},
        where="control",
    )
    assert parsed.version == "1.0.0"


def test_V1_REJECTS_retirement_rather_than_accepting_and_discarding_it() -> None:
    """`retirement` is in `BINDING_FIELDS`, was never read by the parser, and is
    never emitted by `as_document`.

    So the PROFILE DIGEST DOES NOT COVER DISPLACEMENT EVIDENCE — a value the
    digest does not cover is a value nobody is bound to, however carefully it was
    written. Worse, a document supplying `displaces` WITH its retirement rows was
    refused by `ConcernBinding.__post_init__` for carrying NO typed retirement
    evidence: a message false about its own input, sending an operator to add
    what was already there.

    The accepting path dropped the evidence and the refusing path lied about why.
    V1 now says the true thing at the parse. Fails before the change: the
    document below parsed, silently losing `retirement`.
    """
    from dotmac_deployment_foundation.application_profile import (
        _binding_from_document,
    )

    with pytest.raises(SpecError) as caught:
        _binding_from_document(
            {
                "implementation": "acme-foundation",
                "version": "1.0.0",
                "coordinates": COORD,
                "displaces": ["dotmac_sub.legacy_writer"],
                "retirement": [{"product": "dotmac_sub", "outstanding": False}],
            },
            where="planted",
        )
    message = str(caught.value)
    assert "retirement" in message
    # The refusal must be ABOUT retirement, not the generic unknown-key message
    # — `retirement` is a known field of the binding, just not one V1 can bind.
    assert "unknown binding field" not in message


def test_that_rejection_is_not_the_unknown_key_check_wearing_another_name() -> None:
    """The near miss. `retirement` stays in `BINDING_FIELDS`, so the closed-field
    check admits it and the specific refusal is what fires. Removing it from the
    set instead would produce 'unknown binding field', which is false: it IS a
    field of `ConcernBinding`, carrying real rules in `__post_init__`."""
    from dotmac_deployment_foundation.application_profile import (
        BINDING_FIELDS,
        _binding_from_document,
    )

    assert "retirement" in BINDING_FIELDS
    # And an actually-unknown key still gets the generic message, so the two
    # refusals have not collapsed into one.
    with pytest.raises(SpecError) as caught:
        _binding_from_document(
            {
                "implementation": "acme-foundation",
                "version": "1.0.0",
                "coordinates": COORD,
                "rate_limit_per_minute": 600,
            },
            where="planted",
        )
    assert "unknown binding field" in str(caught.value)


def test_a_binding_document_WITHOUT_retirement_still_parses() -> None:
    """Non-vacuity: the rejection must not turn every document into a refusal."""
    from dotmac_deployment_foundation.application_profile import (
        _binding_from_document,
    )

    parsed = _binding_from_document(
        {
            "implementation": "acme-foundation",
            "version": "1.0.0",
            "coordinates": COORD,
            "displaces": [],
        },
        where="control",
    )
    assert parsed.retirement == ()


def test_the_profile_digest_does_not_cover_retirement_which_is_WHY_V1_rejects() -> None:
    """The premise of the rejection, asserted rather than described.

    If `as_document` ever begins emitting `retirement`, this test fails and the
    rejection above should be revisited in the same change — the reason for it
    will have gone.
    """
    document = _binding().as_document()
    assert "retirement" not in document
    assert set(document) == {
        "coordinates",
        "displaces",
        "implementation",
        "state",
        "version",
    }


# ── § 9: retirement evidence is typed, and silence is UNKNOWN ───────────────


def _claim(**over) -> WriterClaim:
    fields = {
        "product": "dotmac_sub",
        "writer_state": "legacy_writer",
        "retirement_required": True,
        "revision": REVISION,
        "evidence_paths": ("app/services/x.py",),
        "disposition": "retired_in_revision",
    }
    fields.update(over)
    return WriterClaim(**fields)  # type: ignore[arg-type]


def test_a_binding_that_displaces_with_no_evidence_is_refused() -> None:
    """The Expenses failure, refused. A product was rostered "no ISP writer in
    scope" while Sub held two writers its own prose field required to ratchet to
    zero — the prose was present and correct and did not prevent the miss."""
    with pytest.raises(SpecError) as caught:
        _binding(displaces=("dotmac_sub",))
    assert "UNKNOWN" in str(caught.value)


def test_evidence_about_a_different_product_does_not_answer() -> None:
    with pytest.raises(SpecError) as caught:
        _binding(
            displaces=("dotmac_sub", "dotmac_erp"),
            retirement=(_claim(product="dotmac_sub"),),
        )
    assert "dotmac_erp" in str(caught.value)


def test_an_outstanding_retirement_refuses_the_displacement_claim() -> None:
    """§ 9's fixed order: composed, then proven, then retired — never the same
    change. Claiming displacement while the retirement is `not_yet` claims the
    third step happened because the first did."""
    with pytest.raises(SpecError) as caught:
        _binding(
            displaces=("dotmac_sub",),
            retirement=(_claim(disposition="not_yet"),),
        )
    assert "not_yet" in str(caught.value)


def test_a_retired_displacement_is_admitted() -> None:
    """POSITIVE CONTROL for the retirement machinery."""
    assert _binding(displaces=("dotmac_sub",), retirement=(_claim(),)).displaces


def test_an_unstated_disposition_is_refused() -> None:
    """`not_yet` is permitted; UNSTATED is not. An absent disposition is UNKNOWN
    rather than "nothing to retire", which is how the roster came to be wrong."""
    with pytest.raises(SpecError):
        _claim(disposition="")
    assert "not_yet" in WRITER_DISPOSITIONS


def test_evidence_for_an_obligation_nobody_owes_is_refused() -> None:
    with pytest.raises(SpecError):
        _binding(retirement=(_claim(),))


def test_a_writer_claim_on_a_moving_revision_is_refused() -> None:
    with pytest.raises(SpecError):
        _claim(revision="main")


# ── § 6 and ADR 0033: the absence proof ─────────────────────────────────────


def test_an_inapplicable_concern_needs_a_proof_not_just_a_reason() -> None:
    with pytest.raises(SpecError) as caught:
        InapplicableConcern(reason="no worker runtime", proof="we looked")  # type: ignore[arg-type]
    assert "UNMONITORED" in str(caught.value)


def test_a_proof_that_visited_one_family_is_refused() -> None:
    """AGENTS.md rule 25, cited by number in the module: a guard enumerates
    ENTRY-POINT FAMILIES, never one directory. A proof that looked in one place
    established a fact about that place."""
    with pytest.raises(PreconditionFailed) as caught:
        _proof(families={"worker": ()})
    message = str(caught.value)
    assert "rule 25" in message
    for family in ("scheduler", "cron", "task"):
        assert family in message


def test_all_four_work_families_must_be_visited() -> None:
    assert set(WORK_ENTRY_POINT_FAMILIES) == {"worker", "scheduler", "cron", "task"}


def test_a_proof_with_no_positive_control_is_refused() -> None:
    """ADR 0033 § 3. An absence prover that never finds anything and an assembly
    that has nothing are the same colour."""
    with pytest.raises(PreconditionFailed) as caught:
        _proof(positive_control=())
    assert "same colour" in str(caught.value)


def test_a_proof_that_found_work_is_refused() -> None:
    """The concern is not inapplicable; it is unbound."""
    with pytest.raises(PreconditionFailed) as caught:
        _proof(
            families={
                **dict.fromkeys(WORK_ENTRY_POINT_FAMILIES, ()),
                "cron": ("nightly-sweep",),
            }
        )
    assert "unbound" in str(caught.value)


def test_a_proof_with_no_method_is_refused() -> None:
    """ADR 0033's fourth requirement: a local, parser-aware scan — never a
    remote index and never a substring search."""
    with pytest.raises(PreconditionFailed):
        _proof(method="")


def test_a_proof_on_a_moving_image_reference_is_refused() -> None:
    with pytest.raises(SpecError):
        _proof(image_digest="acme/app:latest")


def test_a_conforming_absence_proof_is_admitted() -> None:
    """POSITIVE CONTROL for the whole § 6 apparatus."""
    slot = InapplicableConcern(reason="this assembly runs no work", proof=_proof())
    profile = _profile(slots={FoundationConcern.WORKER_EXECUTION: slot})
    assert profile.inapplicable == (FoundationConcern.WORKER_EXECUTION,)


# ── the digest ──────────────────────────────────────────────────────────────


def test_the_digest_is_stable_and_covers_the_document_alone() -> None:
    document = _profile().as_document()
    assert document["schema"] == APPLICATION_PROFILE_SCHEMA
    assert profile_digest(document) == profile_digest(_profile().as_document())


def test_a_changed_binding_moves_the_digest() -> None:
    other = _profile(slots={FoundationConcern.AUTHORIZATION: _binding(version="2.0.0")})
    assert profile_digest(_profile().as_document()) != profile_digest(
        other.as_document()
    )


def test_a_wrapper_is_not_a_profile_document() -> None:
    with pytest.raises(SpecError):
        profile_digest(
            {"schema": "something.else", "profile": _profile().as_document()}
        )


# ── § 7: one positive and THREE negative admission tests ────────────────────


def _installed(**over) -> dict[str, str]:
    inventory = {"acme-foundation": "1.0.0"}
    inventory.update(over)
    return inventory


def test_a_conforming_profile_against_a_conforming_image_is_ADMITTED() -> None:
    """§ 7's positive half. ADR 0034 exists because a gate was built that could
    not admit any artefact it would ever be asked to admit, and nobody learned
    this until a production authorization ran into it. A binding check that has
    never admitted anything is in that state now."""
    assert (
        verify_profile_against_candidate(
            _profile(), image_digest=IMAGE, installed=_installed()
        )
        == ()
    )


def test_negative_one_a_binding_naming_an_absent_implementation_refuses() -> None:
    findings = verify_profile_against_candidate(
        _profile(), image_digest=IMAGE, installed={}
    )
    assert findings and all("acme-foundation" in item for item in findings)


def test_negative_two_a_binding_naming_another_version_refuses() -> None:
    findings = verify_profile_against_candidate(
        _profile(),
        image_digest=IMAGE,
        installed=_installed(**{"acme-foundation": "2.0.0"}),
    )
    assert findings and any("2.0.0" in item for item in findings)


def test_negative_three_installed_in_the_checkout_but_absent_from_the_IMAGE() -> None:
    """The third defect is why `installed` is the IMAGE's inventory and never
    the source tree's. A source tree states what an assembly intends to compose;
    an image holds what it WILL run, and they differ routinely and innocently —
    an uncommitted pin, a build argument, a wheel that never reached the
    registry."""
    findings = verify_profile_against_candidate(
        _profile(), image_digest=IMAGE, installed={"some-other-dist": "1.0.0"}
    )
    assert findings
    assert any("does NOT carry" in item for item in findings)


def test_the_verification_names_the_binding_that_failed() -> None:
    """ADR 0021 § 4: the mutation must fail FOR THE STATED REASON and name the
    missing thing, or a resolver error stands in for the proof."""
    findings = verify_profile_against_candidate(
        _profile(), image_digest=IMAGE, installed={}
    )
    assert any("identity_session" in item for item in findings)
    assert any("identity / session" in item for item in findings)


def test_verification_refuses_a_moving_image_reference() -> None:
    with pytest.raises(SpecError):
        verify_profile_against_candidate(
            _profile(), image_digest="acme/app:latest", installed=_installed()
        )


# ── § 7, closed: the generic admission mechanism, for all thirteen slots ────
#
# The tests above prove the mechanism exists using one shared implementation
# identity (`acme-foundation`) bound to every slot, which is why a handful of
# concern names (identity_session via `test_the_verification_names_the_binding
# _that_failed`, authorization, worker_execution, edge_security,
# api_web_interaction, deployment_recovery via the other module-level tests
# above) ended up named somewhere in this file and the other seven did not.
# That was never a claim about which concerns are fleet-mature — this module
# holds no such opinion (see `application_profile.py`'s docstring) — it was
# simply incomplete exercise of a mechanism that is supposed to work
# identically for all thirteen. The table below closes that gap: every
# `FoundationConcern` gets its own distinguishable SYNTHETIC implementation
# identity (never a real-looking provider or product name) and is proven,
# generically, against a positive match, a missing-implementation finding and
# a wrong-version finding.

#: Hard-coded rather than `tuple(FoundationConcern)`: the point of this table
#: is that it can go OUT of sync with the enum. If a fourteenth concern is
#: added to `FoundationConcern` without a matching entry here,
#: `test_the_admission_case_table_covers_every_declared_concern` fails until
#: this table is updated — the same two-directional-ratchet shape this
#: repository already applies to other closed registries (AGENTS.md rule 25).
_ADMISSION_CASE_CONCERNS: Final[tuple[FoundationConcern, ...]] = (
    FoundationConcern.IDENTITY_SESSION,
    FoundationConcern.REQUEST_EVIDENCE_CONTEXT,
    FoundationConcern.AUTHORIZATION,
    FoundationConcern.PERSISTENCE_MIGRATIONS,
    FoundationConcern.SETTINGS_SECRETS,
    FoundationConcern.AUDIT_TELEMETRY,
    FoundationConcern.HEALTH_RUNTIME_ADMISSION,
    FoundationConcern.WORKER_EXECUTION,
    FoundationConcern.EDGE_SECURITY,
    FoundationConcern.API_WEB_INTERACTION,
    FoundationConcern.DATA_GOVERNANCE,
    FoundationConcern.INTEGRATION,
    FoundationConcern.DEPLOYMENT_RECOVERY,
)


def test_the_admission_case_table_covers_every_declared_concern() -> None:
    """Two-directional: the table cannot silently drop one of today's thirteen,
    and a fourteenth concern added to the enum later cannot silently go
    unexercised by it either."""
    assert set(_ADMISSION_CASE_CONCERNS) == set(FoundationConcern)
    assert len(_ADMISSION_CASE_CONCERNS) == len(FoundationConcern)


def _synthetic_implementation(concern: FoundationConcern) -> str:
    """A distinguishable, obviously-synthetic identity — never a name that
    could be mistaken for a real provider or product."""
    return f"synthetic-concern-{concern.value}"


def _synthetic_slots() -> dict[FoundationConcern, ConcernBinding]:
    return {
        concern: ConcernBinding(
            implementation=_synthetic_implementation(concern),
            version="1.0.0",
            coordinates=f"synthetic-concern-{concern.value}@sha256:" + "0" * 64,
        )
        for concern in FoundationConcern
    }


def _synthetic_profile() -> ApplicationFoundationProfile:
    return ApplicationFoundationProfile(
        application="synthetic-admission-app", slots=_synthetic_slots()
    )


def _synthetic_installed() -> dict[str, str]:
    return {
        _synthetic_implementation(concern): "1.0.0" for concern in FoundationConcern
    }


@pytest.mark.parametrize("concern", _ADMISSION_CASE_CONCERNS)
def test_generic_admission_mechanism_proven_for_every_concern(
    concern: FoundationConcern,
) -> None:
    """The mechanism itself — positive match, missing-implementation finding,
    wrong-version finding — proven uniformly across all thirteen slots. This
    is NOT a fleet-maturity claim about any concern: every implementation
    identity here is synthetic, and this test asserts nothing about which
    concerns any real assembly can bind today."""
    profile = _synthetic_profile()
    label = CONCERN_LABELS[concern]
    implementation = _synthetic_implementation(concern)

    # Positive: the full, correct inventory admits with no findings at all.
    assert (
        verify_profile_against_candidate(
            profile, image_digest=IMAGE, installed=_synthetic_installed()
        )
        == ()
    )
    # Missing implementation: remove ONLY this concern's implementation.
    installed_missing = _synthetic_installed()
    del installed_missing[implementation]
    findings = verify_profile_against_candidate(
        profile, image_digest=IMAGE, installed=installed_missing
    )
    assert len(findings) == 1
    assert concern.value in findings[0]
    assert label in findings[0]
    assert implementation in findings[0]

    # Wrong version: change ONLY this concern's installed version.
    installed_wrong_version = _synthetic_installed()
    installed_wrong_version[implementation] = "9.9.9"
    findings = verify_profile_against_candidate(
        profile, image_digest=IMAGE, installed=installed_wrong_version
    )
    assert len(findings) == 1
    assert concern.value in findings[0]
    assert "1.0.0" in findings[0]
    assert "9.9.9" in findings[0]


# ── a PROVEN ABSENCE is a slot value, and only when ESTABLISHED ────────────
#
# `IntegrationSurfaceAbsenceProofV1`'s own docstring described absent-proven as
# one of four states and said the proof SATISFIES a concern, while the profile
# refused any slot that was not a binding or an inapplicable. So a product with
# genuinely no integration surface could construct the proof and still not reach
# 13/13 — the unmeetable gate the type exists to prevent, reintroduced one level
# up by the vocabulary it was bolted beside.

ARTIFACT = "acme-app@sha256:" + "e" * 64
INVENTORY = "sha256:" + "f" * 64


def _absence(**over) -> IntegrationSurfaceAbsenceProofV1:
    fields = {
        "concern": FoundationConcern.INTEGRATION,
        "source_revision": REVISION,
        "artifact_digest": ARTIFACT,
        "observed_inventory_digest": INVENTORY,
        "families": dict.fromkeys(INTEGRATION_SURFACE_FAMILIES, ()),
        "method": "entry-point metadata + AST walk over the installed wheel",
        "positive_control": ("dotmac_integration.connectors:paystack",),
        "established_at": "2026-09-05T12:00:00Z",
        "established_by": "platform-cp-profile-job",
    }
    fields.update(over)
    return IntegrationSurfaceAbsenceProofV1(**fields)  # type: ignore[arg-type]


def _absent_profile(**over) -> ApplicationFoundationProfile:
    return _profile(slots={FoundationConcern.INTEGRATION: _absence(**over)})


def test_a_proven_absence_FILLS_a_concern_slot() -> None:
    """Fails before the change: the profile refused any slot that was not a
    `ConcernBinding` or an `InapplicableConcern`, so this construction raised."""
    profile = _absent_profile()
    assert FoundationConcern.INTEGRATION in profile.absent_proven
    assert FoundationConcern.INTEGRATION not in profile.bound
    assert FoundationConcern.INTEGRATION not in profile.inapplicable


def test_the_four_states_stay_distinct() -> None:
    """Bound, absent-proven and inapplicable are three answers, and
    not-yet-implemented is the fourth by having NO member at all.

    Collapsing any pair is the two-values-for-three-cases shape. The fourth is
    the 13/13 gate itself: a constructible "owed" member would be the knob that
    admits an incomplete profile for one deployment.
    """
    profile = ApplicationFoundationProfile(
        application="acme-app",
        slots={
            **dict.fromkeys(FoundationConcern, _binding()),
            FoundationConcern.INTEGRATION: _absence(),
            FoundationConcern.WORKER_EXECUTION: InapplicableConcern(
                reason="ruled out", proof=_proof()
            ),
        },
    )
    assert len(profile.bound) == 11
    assert profile.absent_proven == (FoundationConcern.INTEGRATION,)
    assert profile.inapplicable == (FoundationConcern.WORKER_EXECUTION,)
    assert (
        len(profile.bound) + len(profile.absent_proven) + len(profile.inapplicable)
        == 13
    )
    # And "owed" is not constructible: a profile missing a concern is refused
    # rather than filled with a placeholder state.
    with pytest.raises(SpecError):
        ApplicationFoundationProfile(
            application="acme-app",
            slots={
                c: _binding()
                for c in FoundationConcern
                if c is not FoundationConcern.INTEGRATION
            },
        )


def test_a_proof_MISFILED_under_another_concern_is_refused() -> None:
    """The proof carries its own concern and the mapping key is the concern the
    profile claims about. Until a proof could be a slot the question could not
    arise; the moment it can, it is the same failure the proof's own type
    refuses one level down — and the profile is the more dangerous level,
    because 13/13 is read off the slots."""
    with pytest.raises(SpecError) as exc:
        _profile(slots={FoundationConcern.WORKER_EXECUTION: _absence()})
    assert exc.value.code == ABSENCE_WRONG_CONCERN
    assert "worker_execution" in str(exc.value)
    assert "integration" in str(exc.value)


def test_the_document_names_the_absent_proven_state() -> None:
    """A reader of the canonical document must see which of the states a slot
    is in without inferring it from which keys are present."""
    document = _absent_profile().as_document()
    assert document["concerns"]["integration"]["state"] == "absent_proven"
    assert document["concerns"]["identity_session"]["state"] == "bound"


def test_an_ESTABLISHED_absence_verifies_clean() -> None:
    """The accepting control. Without it every refusal below could belong to a
    check that admits nothing — which is ADR 0034's own failure."""
    assert (
        verify_profile_against_candidate(
            _absent_profile(),
            image_digest=IMAGE,
            installed=_installed(),
            artifact_digest=ARTIFACT,
            observed_inventory_digests={FoundationConcern.INTEGRATION: INVENTORY},
        )
        == ()
    )


def test_an_absence_with_NO_artifact_digest_is_a_finding_not_a_pass() -> None:
    """The bypass this closes. Had the verifier skipped an absent-proven slot
    the way it skips a non-binding one, a well-formed proof of nothing would
    fill a concern and reach 13/13 with nobody examining an artifact."""
    findings = verify_profile_against_candidate(
        _absent_profile(), image_digest=IMAGE, installed=_installed()
    )
    assert findings
    assert any("ESTABLISHED" in item for item in findings)


def test_an_absence_with_NO_observed_inventory_is_a_finding() -> None:
    """The unmanufacturable half is exactly this comparison. Without it the slot
    is a caller's own string agreeing with itself."""
    findings = verify_profile_against_candidate(
        _absent_profile(),
        image_digest=IMAGE,
        installed=_installed(),
        artifact_digest=ARTIFACT,
    )
    assert findings
    assert any("independently observed" in item for item in findings)


def test_a_proof_for_ANOTHER_artifact_is_a_finding() -> None:
    """Perfectly well-formed, produced for a different build, says nothing about
    this one."""
    findings = verify_profile_against_candidate(
        _absent_profile(),
        image_digest=IMAGE,
        installed=_installed(),
        artifact_digest="acme-app@sha256:" + "1" * 64,
        observed_inventory_digests={FoundationConcern.INTEGRATION: INVENTORY},
    )
    assert findings and any("another build" in item for item in findings)


def test_a_MANUFACTURED_inventory_digest_is_a_finding() -> None:
    """A caller can write any string into the proof; it cannot make that string
    equal one an independent party derived from the artifact."""
    findings = verify_profile_against_candidate(
        _absent_profile(),
        image_digest=IMAGE,
        installed=_installed(),
        artifact_digest=ARTIFACT,
        observed_inventory_digests={
            FoundationConcern.INTEGRATION: "sha256:" + "9" * 64
        },
    )
    assert findings


def test_the_absence_is_checked_against_the_ARTIFACT_not_the_IMAGE() -> None:
    """Two digests, and they are not the same value.

    `image_digest` is the candidate OCI image and is what a BINDING is checked
    against; `artifact_digest` is the Platform application wheel and is what a
    PROVEN ABSENCE is checked against. Comparing a proof against the image
    digest could never match, and the gate would be unsatisfiable — the failure
    that looks like strictness. Passing the image digest as the artifact one
    must therefore be refused rather than quietly admitted.
    """
    findings = verify_profile_against_candidate(
        _absent_profile(),
        image_digest=IMAGE,
        installed=_installed(),
        artifact_digest=IMAGE,
        observed_inventory_digests={FoundationConcern.INTEGRATION: INVENTORY},
    )
    assert findings, "the image digest was accepted where the artifact's belongs"


def test_a_profile_with_no_absence_is_unaffected_by_the_new_inputs() -> None:
    """Non-vacuity in the other direction: the added parameters must not turn
    every existing profile into a finding, or the checks above would be passing
    because nothing verifies any more."""
    assert (
        verify_profile_against_candidate(
            _profile(), image_digest=IMAGE, installed=_installed()
        )
        == ()
    )


# ── § 8: the read-back COMPARES, never DERIVES ──────────────────────────────


def test_a_matching_read_back_is_admitted() -> None:
    digest = profile_digest(_profile().as_document())
    assert require_profile_readback(authorized=digest, observed=digest) == digest


def test_a_mismatched_read_back_refuses() -> None:
    with pytest.raises(PreconditionFailed) as caught:
        require_profile_readback(
            authorized="sha256:" + "1" * 64, observed="sha256:" + "2" * 64
        )
    assert "leaves a receipt" in str(caught.value)


def test_a_running_system_that_reports_nothing_is_a_mismatch_not_a_pass() -> None:
    with pytest.raises(PreconditionFailed):
        require_profile_readback(authorized="sha256:" + "1" * 64, observed="")


def test_an_absent_authorized_digest_refuses_rather_than_accepting_the_observed() -> (
    None
):
    """The direction ADR 0032 § 2 forbids. Accepting whatever the running system
    reports makes the deployed image the authority, and from that moment drift
    and correction arrive as the same commit with the same diff."""
    with pytest.raises(PreconditionFailed):
        require_profile_readback(authorized="", observed="sha256:" + "2" * 64)


# ── the second half: report-only ────────────────────────────────────────────


def test_no_deployment_path_is_gated_by_profile_completeness() -> None:
    """THE SECOND HALF, held so the first cannot be quietly converted.

    Someone reading the type's refusal concludes the gate is live and acts on
    that belief in a repository with nine unfillable slots. Nothing on the
    deploy path may call the verification or the read-back until the concerns
    have owners — ADR 0039's own staging paragraph.
    """
    import ast
    import pathlib

    package = (
        pathlib.Path(__file__).resolve().parents[2]
        / "packages/dotmac-deployment-foundation/src/dotmac_deployment_foundation"
    )
    cli = package / "cli.py"
    called = {
        node.func.id
        for node in ast.walk(ast.parse(cli.read_text(encoding="utf-8")))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert "verify_profile_against_candidate" not in called
    assert "require_profile_readback" not in called
