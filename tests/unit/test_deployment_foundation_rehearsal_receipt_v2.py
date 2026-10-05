"""``RehearsalReceipt.v2`` — the receipt the release gate reads.

v1 cannot be repaired in place: its schema has crossed five built candidate
wheels, and its gate item 9 forced three caller-supplied digests equal, so its
"authorized plan" could only ever be the descriptor digest restated
(``scripts/lane3_authorization.py``'s
``middle_term_is_the_execution_plan_digest`` precondition). v2 is a new schema
that binds what v1 has no room for:

- gate item 9 as a chain over the AUTHORIZED ``ExecutionPlanDigestV1``;
- the candidate bytes and controller the plan authorized;
- opaque target identity taken from the plan, with no address;
- a private vantage by reference;
- the run that produced the receipt.

Every refusal below has a planted case, because a gate nobody has watched
refuse is a gate nobody should trust (ADR-0018).
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import Any

import pytest
from dotmac_deployment_foundation.engine.plan import build_plan
from dotmac_deployment_foundation.engine.run import DeploymentOutcome
from dotmac_deployment_foundation.errors import SpecError
from dotmac_deployment_foundation.execution_plan import (
    HostPrestateV1,
    render_execution_plan,
)
from dotmac_deployment_foundation.execution_plan_v3 import FoundationExecutionPlanV3
from dotmac_deployment_foundation.rehearsal import (
    REHEARSAL_RECEIPT_SCHEMA,
    REHEARSAL_RECEIPT_V2_SCHEMA,
    REQUIRED_ITEMS,
    ExecutionRunBindingV1,
    RehearsalReceiptV1,
    RehearsalReceiptV2,
    RequirementResult,
    RequirementStatus,
    build_receipt_v2,
    render_status_document,
    require_execution_run,
    require_rehearsed_artifact,
    verify_publication,
)
from dotmac_deployment_foundation.spec import ProductDeploymentSpec

from tests.unit.foundation_v3_support import CONTROLLER, WHEEL, grant_for_plan, v3_plan

REVISION = "c" * 40
FIXTURE = "sha256:" + "d" * 64
BUNDLE = "sha256:" + "9" * 64
RUN = ExecutionRunBindingV1(repository_id=1397614141, run_id=4242, run_attempt=1)
VANTAGE = "inside-vantage@7"


def _results(**overrides: RequirementStatus) -> list[RequirementResult]:
    return [
        RequirementResult(
            code=item.code,
            status=overrides.get(item.code, RequirementStatus.EXECUTED_PASSED),
            detail=f"{item.title} — measured",
            evidence=(f"bundle:{item.code}",),
        )
        for item in REQUIRED_ITEMS
    ]


@dataclasses.dataclass(frozen=True)
class Subject:
    descriptor_digest: str
    plan: FoundationExecutionPlanV3
    grant: Any
    outcome: DeploymentOutcome


@pytest.fixture
def subject(tmp_path: Path) -> Subject:
    body = Path("scripts/exposure-rehearsal/product.toml").read_text(encoding="utf-8")
    descriptor = tmp_path / "product.toml"
    descriptor.write_text(body, encoding="utf-8")
    spec = ProductDeploymentSpec.load(str(descriptor))
    descriptor_digest = str(spec.to_canonical_document().sha256_digest())
    steps = build_plan(spec)
    plan = v3_plan(
        render_execution_plan(
            spec,
            steps,
            target="rehearsal-target",
            operation="deploy",
            descriptor_digest=descriptor_digest,
            prestate=HostPrestateV1.first_deploy(),
            application_profile_digest="",
        )
    )
    grant = grant_for_plan(spec, plan)
    outcome = DeploymentOutcome(
        plan=steps,
        succeeded=True,
        execution_plan_digest=plan.digest(),
        descriptor_digest=descriptor_digest,
        execution_sequence=grant.execution_sequence,
        attempt_no=grant.attempt_no,
    )
    return Subject(
        descriptor_digest=descriptor_digest, plan=plan, grant=grant, outcome=outcome
    )


def _build(subject: Subject, **overrides: Any) -> RehearsalReceiptV2:
    fields: dict[str, Any] = {
        "foundation_revision": REVISION,
        "foundation_artifact_digest": WHEEL,
        "descriptor_digest": subject.descriptor_digest,
        "execution_plan": subject.plan,
        "grant": subject.grant,
        "execution_outcome": subject.outcome,
        "fixture_digest": FIXTURE,
        "evidence_bundle_digest": BUNDLE,
        "controller_identity": CONTROLLER,
        "lease_id": "lease-1",
        "probe_vantage_ref": VANTAGE,
        "execution_run": RUN,
        "started_at": "2026-10-05T10:00:00+00:00",
        "finished_at": "2026-10-05T10:40:00+00:00",
        "results": _results(),
    }
    fields.update(overrides)
    return build_receipt_v2(**fields)


# ── the positive case, and that it round-trips ─────────────────────────────


def test_a_complete_v2_receipt_publishes_and_round_trips(subject: Subject) -> None:
    receipt = _build(subject)
    verify_publication(receipt, revision=REVISION)
    require_rehearsed_artifact(receipt, artifact_digest=WHEEL)
    require_execution_run(receipt, run=RUN)

    again = RehearsalReceiptV2.from_json(receipt.canonical_bytes())
    assert again.content == receipt.content
    assert again.sha256_digest() == receipt.sha256_digest()
    assert again.content["schema"] == REHEARSAL_RECEIPT_V2_SCHEMA
    # The three item-9 terms are recorded under their OWN names and are not
    # one value restated.
    assert again.execution_plan_digest == subject.plan.digest()
    assert again.content["descriptor_digest"] == subject.descriptor_digest
    assert again.execution_plan_digest != again.content["descriptor_digest"]


def test_identity_comes_from_the_plan_not_the_caller(subject: Subject) -> None:
    receipt = _build(subject)
    assert receipt.content["target_id"] == subject.plan.target_id
    assert receipt.content["host_id"] == subject.plan.host_id
    assert "target" not in receipt.content
    assert "probe_identity" not in receipt.content


# ── gate item 9 is a chain: each link refuses when planted ─────────────────


def test_the_degenerate_v1_shape_is_refused(subject: Subject) -> None:
    """The authorized plan digest restated as the descriptor digest.

    Planted with `dataclasses.replace`, which carries the issued witness: the
    grant guard is in-process code trust (ADR-0070, 2026-09-25), not a
    cryptographic boundary, so the receipt re-checks rather than assumes.
    """
    forged = dataclasses.replace(
        subject.grant, execution_plan_digest=subject.descriptor_digest
    )
    with pytest.raises(SpecError, match="degenerate v1 shape"):
        _build(subject, grant=forged)


def test_an_altered_plan_is_refused_against_the_frozen_digest(
    subject: Subject,
) -> None:
    """The case a caller-supplied digest could not catch: alter the plan, and
    the digest Control froze no longer matches it."""
    altered = dataclasses.replace(subject.plan, host_id="fleet-host-2")
    assert altered.digest() != subject.grant.execution_plan_digest
    with pytest.raises(SpecError, match="Only the plan Control froze"):
        _build(subject, execution_plan=altered)


@pytest.mark.parametrize(
    "stand_in", ["sha256:" + "e" * 64, {"execution_plan_digest": "sha256:" + "e" * 64}]
)
def test_only_an_issued_grant_carries_the_authorized_digest(
    subject: Subject, stand_in: object
) -> None:
    with pytest.raises(SpecError, match="takes the ExecutionGrant"):
        _build(subject, grant=stand_in)


def test_a_grant_for_another_descriptor_is_refused(subject: Subject) -> None:
    forged = dataclasses.replace(subject.grant, descriptor_digest="sha256:" + "3" * 64)
    with pytest.raises(SpecError, match="the grant authorizes descriptor"):
        _build(subject, grant=forged)


def test_a_grant_for_another_target_is_refused(subject: Subject) -> None:
    forged = dataclasses.replace(subject.grant, target="another-target")
    with pytest.raises(SpecError, match="another target"):
        _build(subject, grant=forged)


@pytest.mark.parametrize(
    ("field", "value"),
    [("execution_sequence", 8), ("attempt_no", 2), ("attempt_no", 0)],
)
def test_an_outcome_of_another_dispatch_or_a_replay_is_refused(
    subject: Subject, field: str, value: int
) -> None:
    replayed = dataclasses.replace(subject.outcome, **{field: value})
    with pytest.raises(SpecError, match="another dispatch, or a replay"):
        _build(subject, execution_outcome=replayed)


def test_the_receipt_names_the_dispatch_it_executed(subject: Subject) -> None:
    dispatch = _build(subject).content["control_dispatch"]
    assert dispatch == {
        "dispatch_id": subject.grant.receipt.dispatch_id,
        "execution_sequence": subject.grant.execution_sequence,
        "attempt_no": subject.grant.attempt_no,
    }


def test_a_plan_rendered_from_another_descriptor_is_refused(subject: Subject) -> None:
    with pytest.raises(SpecError, match="rendered from descriptor"):
        _build(subject, descriptor_digest="sha256:" + "7" * 64)


@pytest.mark.parametrize("field", ["execution_plan_digest", "descriptor_digest"])
def test_an_outcome_not_bound_to_the_plan_is_refused(
    subject: Subject, field: str
) -> None:
    """Empty is how `DeploymentOutcome` reports "not bound"; it is refused,
    never skipped."""
    unbound = dataclasses.replace(subject.outcome, **{field: ""})
    with pytest.raises(SpecError, match=f"reports no {field}"):
        _build(subject, execution_outcome=unbound)


def test_an_outcome_that_executed_another_plan_is_refused(subject: Subject) -> None:
    other = dataclasses.replace(
        subject.outcome, execution_plan_digest="sha256:" + "6" * 64
    )
    with pytest.raises(SpecError, match="the outcome executed plan"):
        _build(subject, execution_outcome=other)


def test_an_outcome_that_executed_another_descriptor_is_refused(
    subject: Subject,
) -> None:
    other = dataclasses.replace(subject.outcome, descriptor_digest="sha256:" + "5" * 64)
    with pytest.raises(SpecError, match="the outcome executed descriptor"):
        _build(subject, execution_outcome=other)


def test_a_digest_string_cannot_stand_in_for_the_plan(subject: Subject) -> None:
    with pytest.raises(SpecError, match="takes the authorized"):
        _build(subject, execution_plan=subject.plan.digest())


# ── the plan names the bytes and the controller ────────────────────────────


def test_a_rehearsal_of_other_bytes_is_refused(subject: Subject) -> None:
    with pytest.raises(SpecError, match="the plan authorized candidate"):
        _build(subject, foundation_artifact_digest="sha256:" + "4" * 64)


def test_a_rehearsal_driven_by_another_controller_is_refused(
    subject: Subject,
) -> None:
    with pytest.raises(SpecError, match="the plan binds controller"):
        _build(subject, controller_identity="SHA256:someone-else")


# ── no topology in a published receipt ─────────────────────────────────────


@pytest.mark.parametrize("address", ["203.0.113.10", "2001:db8::10", "[2001:db8::10]"])
def test_an_ip_literal_host_id_is_refused(subject: Subject, address: str) -> None:
    plan = dataclasses.replace(subject.plan, host_id=address)
    with pytest.raises(SpecError, match="is an IP address"):
        _build(subject, execution_plan=plan)


@pytest.mark.parametrize(
    "ref", ["198.51.100.7", "vantage.example.net@3", "inside-vantage", "a@0", "x/y@1"]
)
def test_a_vantage_that_is_not_a_record_reference_is_refused(
    subject: Subject, ref: str
) -> None:
    with pytest.raises(SpecError, match="record-key>@<version>"):
        _build(subject, probe_vantage_ref=ref)


def test_the_status_document_carries_no_caller_topology(subject: Subject) -> None:
    document = render_status_document(_build(subject))
    assert "16 of 16 executed and passed" in document
    assert VANTAGE in document
    assert subject.plan.host_id in document
    assert "rehearsal-target" not in document  # the plan's address-bearing ref


# ── the receipt belongs to one run ─────────────────────────────────────────


@pytest.mark.parametrize(
    "other",
    [
        ExecutionRunBindingV1(repository_id=1, run_id=4242, run_attempt=1),
        ExecutionRunBindingV1(repository_id=1397614141, run_id=4243, run_attempt=1),
        ExecutionRunBindingV1(repository_id=1397614141, run_id=4242, run_attempt=2),
    ],
)
def test_a_receipt_from_another_run_is_refused(
    subject: Subject, other: ExecutionRunBindingV1
) -> None:
    with pytest.raises(SpecError, match="from another"):
        require_execution_run(_build(subject), run=other)


@pytest.mark.parametrize("value", [0, -1, True, "4242"])
def test_a_run_coordinate_must_be_a_positive_integer(value: object) -> None:
    with pytest.raises(SpecError, match="positive integer"):
        ExecutionRunBindingV1(repository_id=1, run_id=value, run_attempt=1)  # type: ignore[arg-type]


# ── reading: v1 is history, and a v2 document is read exactly ──────────────


def test_a_v1_document_is_refused_by_the_v2_reader() -> None:
    with pytest.raises(SpecError, match="history, not publication evidence"):
        RehearsalReceiptV2.from_json(json.dumps({"schema": REHEARSAL_RECEIPT_SCHEMA}))


def test_a_v1_receipt_cannot_be_tied_to_a_run(subject: Subject) -> None:
    v1 = RehearsalReceiptV1(content={"schema": REHEARSAL_RECEIPT_SCHEMA})
    with pytest.raises(SpecError, match="only a RehearsalReceipt.v2"):
        require_execution_run(v1, run=RUN)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("mutate", "match"),
    [
        (lambda c: c.pop("execution_run"), "missing"),
        (lambda c: c.__setitem__("target", "203.0.113.10"), "unknown"),
        (lambda c: c.__setitem__("execution_run", "4242"), "malformed|not an object"),
        (lambda c: c.__setitem__("host_id", "203.0.113.10"), "is an IP address"),
        (lambda c: c.__setitem__("probe_vantage_ref", "198.51.100.7"), "record-key"),
        (lambda c: c["results"].pop(), "omits"),
        (lambda c: c["control_dispatch"].pop("dispatch_id"), "control_dispatch"),
        (
            lambda c: c["control_dispatch"].__setitem__("attempt_no", 0),
            "positive integer",
        ),
        (lambda c: c["results"].append(dict(c["results"][0])), "appears twice"),
    ],
)
def test_a_hand_edited_v2_document_is_refused_on_read(
    subject: Subject, mutate: Any, match: str
) -> None:
    content = json.loads(_build(subject).canonical_bytes())
    mutate(content)
    with pytest.raises(SpecError, match=match):
        RehearsalReceiptV2.from_json(json.dumps(content))


def test_a_v2_receipt_with_a_failing_item_cannot_publish(subject: Subject) -> None:
    receipt = _build(
        subject, results=_results(private_from_source=RequirementStatus.BLOCKED)
    )
    with pytest.raises(SpecError, match="private_from_source=blocked"):
        verify_publication(receipt, revision=REVISION)
