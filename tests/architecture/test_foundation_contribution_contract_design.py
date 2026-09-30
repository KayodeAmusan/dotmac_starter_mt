"""The DESIGN's own evidence, kept honest — not the contract's implementation.

`docs/superpowers/specs/2026-09-05-foundation-concern-contribution-contract.md`
is a proposal. It carries golden byte fixtures, and a golden fixture nobody
re-derives is a decoration — which is precisely the inert shape the design it
supports is written about. So the fixture is re-derived here from the SHIPPED
canonicalizer.

**This file guards the fixture. It does not implement the contract.** There is
no build tool here, no discovery, no module declaration and no entry-point
group. When item 7 lands, its tests are elsewhere and these stay.

The document itself is asserted only where a claim in it is checkable against
this repository. Prose is not tested — a detector that matched its own docstring
is a defect this package has already shipped once — but a NUMBER in a review
package that no longer holds is a false statement in the artifact a decision
gets made from.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from dotmac_deployment_foundation.application_profile import (
    APPLICATION_PROFILE_SCHEMA,
    FoundationConcern,
    canonical_profile_bytes,
    profile_digest,
)
from dotmac_deployment_foundation.errors import SpecError

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "docs" / "inventories" / "foundation-profile-golden.json"
DESIGN = (
    ROOT
    / "docs"
    / "superpowers"
    / "specs"
    / "2026-09-05-foundation-concern-contribution-contract.md"
)


def _fixture() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_the_golden_digest_is_re_derived_from_the_shipped_canonicalizer() -> None:
    """The fixture's whole value is that a second implementation must reproduce
    it byte for byte. If the canonicalizer moves and the fixture does not, the
    review package is quoting a digest nobody can produce."""
    fixture = _fixture()
    document = fixture["document"]
    assert profile_digest(document) == fixture["profile_digest"]
    assert len(canonical_profile_bytes(document)) == fixture["canonical_length"]


def test_the_design_document_quotes_the_digest_the_fixture_holds() -> None:
    """A number in a review package that no longer holds is a false statement in
    the artifact a decision gets made from."""
    text = DESIGN.read_text(encoding="utf-8")
    fixture = _fixture()
    assert fixture["profile_digest"] in text
    assert str(fixture["canonical_length"]) in text


def test_the_fixture_exercises_BOTH_slot_kinds() -> None:
    """Non-vacuity of the fixture itself.

    A golden profile of thirteen identical bindings would pin the canonical form
    and prove nothing about the slot value the design turns on. The
    absent-proven slot became representable on 2026-09-05 and is the reason this
    fixture exists rather than an older one.
    """
    concerns = _fixture()["document"]["concerns"]
    states = {slot["state"] for slot in concerns.values()}
    assert states == {"bound", "absent_proven"}, states
    assert concerns["integration"]["state"] == "absent_proven"
    # And the proof binds the WHEEL, not a self-referential image.
    assert "artifact_digest" in concerns["integration"]
    assert "image_digest" not in concerns["integration"]


def test_the_fixture_is_a_COMPLETE_profile() -> None:
    """Thirteen slots, every one filled. A fixture that omitted one would pin the
    canonical form of a document the profile type refuses to construct."""
    concerns = _fixture()["document"]["concerns"]
    assert set(concerns) == {concern.value for concern in FoundationConcern}
    assert len(concerns) == 13
    assert _fixture()["document"]["schema"] == APPLICATION_PROFILE_SCHEMA


def test_the_canonicalizer_still_refuses_a_wrapper() -> None:
    """The design cites this rule rather than restating it, so it is checked
    where it is cited. Hashing a wrapper that merely CONTAINS a profile is how
    two parties compute permanently unequal values while both look correct."""
    wrapped = {"profile": _fixture()["document"]}
    with pytest.raises(SpecError):
        canonical_profile_bytes(wrapped)


def test_the_derivation_guard_would_notice_a_drifted_fixture() -> None:
    """Sensitivity. The assertions above pass over a fixture that is already
    correct, which says nothing about their ability to fail — and a golden
    fixture is the single easiest thing in a repository to leave behind."""
    document = _fixture()["document"]
    drifted = json.loads(json.dumps(document))
    drifted["application"] = "someone-elses-app"
    assert profile_digest(drifted) != _fixture()["profile_digest"]
    # A near miss: re-serialising the SAME document through a different key
    # order must NOT change the digest, or the canonical form is not canonical.
    reordered = dict(reversed(list(document.items())))
    assert profile_digest(reordered) == _fixture()["profile_digest"]


def test_the_design_is_marked_PROPOSED_and_allocates_no_ADR_number() -> None:
    """It becomes authoritative by an accepted ADR, not by being merged.

    `docs/superpowers/specs/` is defined by this repository as non-authoritative
    intent; a proposal that read as a decision would be a decision nobody took.
    """
    text = DESIGN.read_text(encoding="utf-8")
    assert "CONTRACT DESIGN ONLY" in text
    assert "not implemented" in text
    # Michael's standing scope line: this is neither of the two things a reader
    # is most likely to mistake it for.
    assert (
        "not** profile\nadmission" in text
        or "not profile admission" in text.replace("**", "").replace("\n", " ")
    )
    assert not list(
        (ROOT / "docs" / "adr").glob("*concern-contribution*")
    ), "the design allocated an ADR number while still under review"


# ── the parity map is a RATCHET, in both directions ────────────────────────

PARITY = ROOT / "docs" / "inventories" / "foundation-admission-parity-map.json"
APPLICATION_PROFILE_SOURCE = (
    ROOT
    / "packages"
    / "dotmac-deployment-foundation"
    / "src"
    / "dotmac_deployment_foundation"
    / "application_profile.py"
)


def _parity() -> dict:
    return json.loads(PARITY.read_text(encoding="utf-8"))


def test_the_parity_map_holds_its_counts_in_both_directions() -> None:
    """A one-directional map lets either half slip: a shrinking count reads as
    cleanup and a growing one as progress. Both totals are fixed, so a case
    cannot appear or vanish as a side effect of some other change."""
    parity = _parity()
    assert parity["legacy_total"] == 53
    assert sum(parity["legacy_breakdown"].values()) == parity["legacy_total"]
    assert len(parity["added"]) == parity["added_total"]


def test_the_added_cases_are_the_ones_the_dialect_could_not_STATE() -> None:
    """Reproducing 53 and adding none would mean the generic path had reproduced
    the dialect rather than replaced it. Each added case records WHY the dialect
    has no counterpart, so a row cannot be added as a round number."""
    added = _parity()["added"]
    cases = {row["case"] for row in added}
    assert cases == {
        "all_negative",
        "answers_everything",
        "foreign_inventory",
        "foreign_provenance",
        "retirement_round_trip",
        "unknown_key",
        "uninjected",
        "wrong_assembly",
        "wrong_composition",
        "wrong_site",
    }
    # `nonce_only` was dropped in revision 3: the nonce no longer exists, so the
    # shape cannot be represented and the row could never fire. A row that
    # cannot fire is the inert shape this whole design is about, and the ratchet
    # would have frozen it in place.
    assert "nonce_only" not in cases
    for row in added:
        assert row["requires"].strip()
        assert row["absent_from_dialect_because"].strip()


def test_the_parity_GATE_blocks_deletion_and_is_not_merely_a_note() -> None:
    """Revision 2 recorded the debt and gated nothing: it asserted
    `legacy_rows_supplied_here` stays false, and nothing failed if Platform's
    dialect were deleted while it was.

    A field that records an obligation without blocking on it is a note. The
    gate is false today and flipping it requires the per-row mapping, so this
    test is what makes "owed" mean "blocking".
    """
    parity = _parity()
    assert parity["parity_gate_passed"] is False
    # And the two are not independent: the gate cannot be true while the rows
    # are still owed, which is the pairing that makes the flip meaningful.
    assert parity["legacy_rows_supplied_here"] is False
    assert not (
        parity["parity_gate_passed"] and not parity["legacy_rows_supplied_here"]
    )


def test_the_two_halves_of_the_parity_map_RECONCILE_arithmetically() -> None:
    """Platform's row map is merged, so the count this file is accountable to and
    the states that account for it must add up — by arithmetic rather than by
    two teams asserting the same number.

    The five unmapped rows block deletion, and all five are envelope-level: they
    had no successor code at all, because `missing` is per-concern and N17 makes
    13x`missing` unrepresentable for a document that was never read.
    """
    parity = _parity()
    rows = parity["platform_row_map"]
    assert sum(rows["states"].values()) == parity["legacy_total"] == 53
    assert rows["states"]["unmapped"] == 5
    assert rows["unmapped_blocks_deletion"] is True
    assert len(rows["unmapped_rows"]) == rows["states"]["unmapped"]
    # Row identity is spent, never reused — recorded so a later editor cannot
    # "tidy up" a retired ordinal.
    assert "NEVER reused" in rows["row_identity"]


def test_the_added_list_does_not_OVERSTATE_what_the_successor_gains() -> None:
    """Three relations, not a boolean — and the third is why.

    Platform classifies `uninjected` as `approximated`: it carries a legacy row,
    because Platform asserted the requirement at construction and could not
    OBSERVE it, so the runtime refusal is new and the intent is not. A boolean
    could not say that, and this map called it simply new. The honest count of
    genuine additions is 7, not 8.

    Two numbers, deliberately: `added_total` is the obligation and
    `added_new_total` is the gain.
    """
    parity = _parity()
    relations = {r["case"]: r["legacy_relation"] for r in parity["added"]}
    assert set(relations.values()) <= {
        "has_counterpart",
        "approximated",
        "no_counterpart",
    }
    assert relations["foreign_inventory"] == "has_counterpart"
    assert relations["unknown_key"] == "has_counterpart"
    assert relations["uninjected"] == "approximated"
    assert (
        parity["added_new_total"]
        == sum(1 for v in relations.values() if v == "no_counterpart")
        == 7
    )
    # The coarse boolean must not come back: it is what lost Platform's third
    # state in the first place.
    assert all("new_to_the_successor" not in r for r in parity["added"])


def test_the_join_is_ANCHORED_to_counterpart_BYTES_not_a_citation() -> None:
    """A pinned commit says WHICH artifact; a digest says the bytes compared were
    the bytes pinned. Without the digest this is a citation, and a citation is
    what "independently green suites are insufficient" rules out.
    """
    rows = _parity()["platform_row_map"]
    assert rows["repository"] == "michaelayoade/dotmac_platform_control_plane"
    assert len(rows["counterpart_sha256"]) == 64
    assert rows["verified_at_pin"] is True
    assert rows["commit"] == "74dab8a8ec97bd8492d4eec5bde4edab74d4c957"


def test_every_row_that_BLOCKS_DELETION_has_a_successor_code() -> None:
    """The gate, joined by Platform ROW ID rather than by counting to five.

    Counting would pass if five envelope codes existed and covered four of
    Platform's rows plus one of our own invention.
    """
    parity = _parity()
    join = parity["envelope_join"]
    assert join["unmapped_rows_closed"] == join["unmapped_rows_total"]
    assert (
        join["unmapped_rows_total"] == parity["platform_row_map"]["states"]["unmapped"]
    )
    ids = {row["row_id"] for row in join["rows"]}
    assert ids == {"PCP-V-01", "PCP-V-02", "PCP-V-03", "PCP-V-04", "PCP-V-11"}
    for row in join["rows"]:
        assert row["foundation_code"].startswith("envelope_")
        assert row["platform_case"]


def test_VERSION_SKEW_is_distinguished_from_disagreement() -> None:
    """A join that could not tell them apart would report progress as a defect.

    Platform measured against revision 2; this is revision 8. `nonce_only` is
    only in Platform's list because revision 3 removed the nonce; two cases are
    only in ours because revisions 4 and 5 added them.
    """
    parity = _parity()
    join = parity["case_join"]
    skew = {row["case"] for row in join["version_skew"]}
    assert skew == {"nonce_only", "foreign_provenance", "wrong_composition"}
    for row in join["version_skew"]:
        assert row["only_in"] in {"platform", "foundation"}
        assert row["why"].strip()
    # The one real disagreement is recorded WITH its resolution, not smoothed.
    assert [row["case"] for row in join["disagree"]] == ["uninjected"]
    assert parity["platform_row_map"]["measured_against_foundation_revision"] == 2


def test_the_gate_names_what_would_let_it_FLIP() -> None:
    """A gate whose conditions are not written down is a gate somebody flips
    because the branch is green."""
    parity = _parity()
    assert parity["parity_gate_passed"] is False
    requires = parity["parity_gate_requires"]
    assert len(requires) >= 8
    joined = " ".join(requires)
    assert "sha256" in joined and "unmapped" in joined and "sum to" in joined
    assert "retained Platform artifact" in joined
    assert "semantic translator" in joined
    assert "local receipt writer" in joined
    assert "EvaluatorRegistrationDigestV1" in joined
    cross_repo = parity["retained_artifact_cross_repository_evidence"]
    assert cross_repo["status"] == "unavailable-blocks-parity-gate"
    assert (
        cross_repo["required_receipt_schema"]
        == "ApplicationFoundationAdmissionReceipt.v1"
    )
    assert cross_repo["required_join"] == "five-part receipt join"
    assert cross_repo["required_verifier_registry"] == "EvaluatorRegistrationDigestV1"
    no_shim = parity["no_shim_or_local_writer_evidence"]
    assert no_shim["status"] == "unavailable-blocks-parity-gate"
    assert "Platform local receipt writer" in no_shim["forbidden"]
    assert "revision 8" in parity["platform_row_map"]["measured_against_note"]


def test_the_map_does_not_RESTATE_platforms_rows() -> None:
    """A copy of another repository's inventory is a second authority that
    drifts. The map is accountable to the count and names who owns the rows."""
    parity = _parity()
    assert parity["legacy_rows_supplied_here"] is False
    assert "d7b8ca6a" in parity["legacy_rows_owned_by"]


def test_the_design_and_the_map_agree_on_the_added_cases() -> None:
    """A number in a review package that no longer holds is a false statement in
    the artifact a decision gets made from — the same rule as the golden digest,
    applied to the case list."""
    text = DESIGN.read_text(encoding="utf-8")
    for row in _parity()["added"]:
        assert row["case"] in text, row["case"]
    assert str(_parity()["legacy_total"]) in text


def test_revision_8_keeps_the_registry_and_cutover_boundaries_explicit() -> None:
    """A design guard checks named contract surfaces, not prose sentiment.

    These literals are a closed review checklist. Removing one is a material
    weakening: it re-opens a callback/fallback path, lets a product translator
    return, or lets an evaluator-less concern look merely incomplete.
    """
    text = DESIGN.read_text(encoding="utf-8")
    required = {
        "CONTRACT DESIGN ONLY — revision 8",
        "no compatibility adapter",
        "transport, protocol, and host-I/O adapters",
        "FoundationConcern, contract_id, contract_version",
        "There are no caller callbacks, default evaluators, wildcard registrations,",
        "unregistered-blocks-admission",
        "fixed candidate artifact inventory and the installed-distribution inventory",
        "SeedCommitmentV1",
        "ChallengeSetDigestV1",
        "EvaluatorRegistrationDigestV1",
        "five independent parts",
        "No evaluator rows are populated by this document",
    }
    assert all(phrase in text for phrase in required)

    # The receipt's canonical schema table is the implementation-facing source
    # of truth. A separate narrative list is not enough: the past defect was a
    # ruling that reached prose but not the table an implementer would follow.
    table = text.split("### 4.3 `ConcernVerification`", 1)[1].split("### 4.3b", 1)[0]
    for field in (
        "`evaluator_registration_digest`",
        "`fixed_candidate_inventory_digest`",
        "`installed_distribution_inventory_digest`",
        "`verifier_artifact_digest`",
    ):
        assert field in table
    assert "exact immutable verifier artifact digest" in table


def test_revision_8_names_its_mutants_and_positive_controls() -> None:
    """The proposed implementation cannot silently lose its sensitivity proof."""
    text = DESIGN.read_text(encoding="utf-8")
    for name in (
        "unregistered-evaluator",
        "caller-callback",
        "inventory-split",
        "platform-semantic-shim",
    ):
        assert name in text
    for row in ("| N30 |", "| N31 |", "| N32 |", "| N33 |"):
        assert row in text


def test_the_stale_absence_fix_claim_tracks_the_shipped_interim_refusal() -> None:
    """The design must not call a landed line-583 refusal merely proposed."""
    text = DESIGN.read_text(encoding="utf-8")
    assert "The narrow interim repair is landed." in text
    assert "`application_profile.py:583`" in text
    assert "offered and not taken unilaterally" not in text
    source_lines = APPLICATION_PROFILE_SOURCE.read_text(encoding="utf-8").splitlines()
    assert "if self.concern is not FoundationConcern.INTEGRATION:" in source_lines[582]
    section_six = text.split("### 6.0", 1)[1].split("### 6.1", 1)[0]
    historical, landed = section_six.split(
        "That historical construction no longer succeeds:", 1
    )
    # Preserve the incident explanation: the old any-concern construction is
    # evidence for the narrower current type, not prose we erase to go green.
    assert "Before the 2026-09-05 interim repair" in historical
    assert "accepted **any of the thirteen**" in historical
    # The current-state subsection must state the landed truth and must not
    # describe the former constructor as live.
    assert "refuses every concern other than `INTEGRATION`" in landed
    assert "accepted **any of the thirteen**" not in landed
