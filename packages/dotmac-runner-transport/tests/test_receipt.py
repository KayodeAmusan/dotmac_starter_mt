from __future__ import annotations

from dataclasses import replace

import pytest
from dotmac_runner_transport import (
    AdapterIdentityV1,
    EvidenceFieldV1,
    EvidenceStatus,
    ExactHost,
    HostDirectEgressGrantV1,
    HostNftablesBindingV1,
    HostProxyIdentityV1,
    HostRunnerIdentityV1,
    LifecycleEvidenceDocumentV1,
    LifecycleEvidenceV1,
    ProviderRunnerIdentityV1,
    ResolvedRunnerTransportPolicyV1,
    RunnerTransportCapability,
    RunnerTransportReceiptV1,
    RunnerTransportRequirementsV1,
    TransportEndpointV1,
    WorkloadEgressPolicyV1,
    render_host_bundle,
)
from dotmac_runner_transport.receipt import REQUIRED_ITEMS

IDENTITY = ProviderRunnerIdentityV1(
    logical_runner_name="runner-one",
    provider_runner_name="provider-runner-one",
    repository="owner/repository",
    required_labels=("runner-one", "self-hosted"),
)
SOURCE_REVISION = "a" * 40
ADAPTER = AdapterIdentityV1("fake-provider", "1", "sha256:" + "c" * 64)


def _document(
    name: str,
    identity: ProviderRunnerIdentityV1 = IDENTITY,
    value: str = "success",
) -> LifecycleEvidenceDocumentV1:
    return LifecycleEvidenceDocumentV1(
        schema="RunnerTransportLifecycleEvidence.v1",
        item=name,
        status=EvidenceStatus.EXECUTED_PASSED,
        mutated=False,
        source="provider-control-plane",
        observed_at="2026-08-31T15:00:00Z",
        source_revision=SOURCE_REVISION,
        adapter=ADAPTER,
        runner_identity=identity,
        fields=(EvidenceFieldV1("outcome", value),),
    )


def _item(
    document: LifecycleEvidenceDocumentV1,
    status: EvidenceStatus = EvidenceStatus.EXECUTED_PASSED,
) -> LifecycleEvidenceV1:
    return LifecycleEvidenceV1(document.item, status, document.digest)


def _documents(
    identity: ProviderRunnerIdentityV1 = IDENTITY,
) -> tuple[LifecycleEvidenceDocumentV1, ...]:
    return tuple(_document(name, identity) for name in REQUIRED_ITEMS)


def _retained(
    documents: tuple[LifecycleEvidenceDocumentV1, ...],
) -> tuple[bytes, ...]:
    return tuple(document.canonical_bytes for document in documents)


def _bundle(*direct_grants: HostDirectEgressGrantV1):
    endpoint = TransportEndpointV1(
        RunnerTransportCapability.CONTROL, ExactHost("transport.invalid")
    )
    policy = ResolvedRunnerTransportPolicyV1(
        schema="RunnerEgressPolicy.v1",
        requirements=RunnerTransportRequirementsV1(
            (RunnerTransportCapability.CONTROL,)
        ),
        adapter=ADAPTER,
        snapshot_digest="sha256:" + "d" * 64,
        endpoints=(endpoint,),
    )
    return render_host_bundle(
        policy,
        (HostRunnerIdentityV1("runner-one", 2001, 3128, 3129),),
        HostProxyIdentityV1("squid", 2010),
        HostNftablesBindingV1(
            "inet",
            "dotmac_egress",
            "output",
            ("ip daddr @mgmt_v4 accept", 'oifname "lo" accept'),
        ),
        (WorkloadEgressPolicyV1("runner-one", (ExactHost("work.invalid"),)),),
        tuple(direct_grants),
    )


def _receipt(
    bundle,
    documents: tuple[LifecycleEvidenceDocumentV1, ...],
    *,
    identity: ProviderRunnerIdentityV1 = IDENTITY,
    status_by_item: dict[str, EvidenceStatus] | None = None,
) -> RunnerTransportReceiptV1:
    environment = bundle.runner_environments[0]
    statuses = status_by_item or {}
    return RunnerTransportReceiptV1(
        schema="RunnerTransportReceipt.v1",
        source_revision=SOURCE_REVISION,
        runner_identity=identity,
        specification_digest=bundle.policy_digest,
        authorized_plan_digest=bundle.policy_digest,
        execution_policy_digest=bundle.policy_digest,
        adapter=bundle.adapter,
        binding_digest=bundle.binding_digest,
        rendered_squid_digest=bundle.squid_sha256,
        rendered_nftables_digest=bundle.nftables_sha256,
        runner_environment_digest=environment.sha256,
        workload_environment_digest=environment.workload_sha256,
        items=tuple(
            _item(document, statuses.get(document.item, EvidenceStatus.EXECUTED_PASSED))
            for document in documents
        ),
    )


def test_all_executed_rows_accept() -> None:
    bundle = _bundle()
    documents = _documents()
    receipt = _receipt(bundle, documents)
    receipt.assert_accepted(bundle, SOURCE_REVISION, IDENTITY, _retained(documents))
    assert receipt.digest.startswith("sha256:")


def test_another_well_formed_source_revision_refuses() -> None:
    bundle = _bundle()
    documents = _documents()
    receipt = _receipt(bundle, documents)
    replayed = replace(receipt, source_revision="b" * 40)
    with pytest.raises(ValueError, match="wrong source revision"):
        replayed.assert_accepted(bundle, "b" * 40, IDENTITY, _retained(documents))


@pytest.mark.parametrize(
    "status",
    [
        status
        for status in EvidenceStatus
        if status is not EvidenceStatus.EXECUTED_PASSED
    ],
)
def test_every_nonpassing_status_refuses_independently(status: EvidenceStatus) -> None:
    bundle = _bundle()
    documents = _documents()
    receipt = _receipt(bundle, documents, status_by_item={"result_uploaded": status})
    with pytest.raises(ValueError, match="result_uploaded"):
        receipt.assert_accepted(bundle, SOURCE_REVISION, IDENTITY, _retained(documents))


def test_zero_exit_shape_with_no_provider_completion_refuses() -> None:
    bundle = _bundle()
    documents = _documents()
    receipt = _receipt(
        bundle,
        documents,
        status_by_item={"provider_recorded_success": EvidenceStatus.NOT_EXECUTED},
    )
    with pytest.raises(ValueError, match="provider_recorded_success"):
        receipt.assert_accepted(bundle, SOURCE_REVISION, IDENTITY, _retained(documents))


def test_digest_mismatch_refuses() -> None:
    bundle = _bundle()
    documents = _documents()
    receipt = _receipt(bundle, documents)
    object.__setattr__(receipt, "execution_policy_digest", "sha256:" + "f" * 64)
    with pytest.raises(ValueError, match="digests differ"):
        receipt.assert_accepted(bundle, SOURCE_REVISION, IDENTITY, _retained(documents))


def test_missing_duplicate_or_unknown_rows_refuse() -> None:
    bundle = _bundle()
    documents = _documents()
    receipt = _receipt(bundle, documents)
    duplicate = replace(receipt.items[-1], item="provider_selected")
    object.__setattr__(receipt, "items", (*receipt.items[:-1], duplicate))
    with pytest.raises(ValueError, match="missing, duplicated or unknown"):
        receipt.assert_accepted(bundle, SOURCE_REVISION, IDENTITY, _retained(documents))


def test_binding_digest_drift_refuses() -> None:
    bundle = _bundle()
    documents = _documents()
    receipt = _receipt(bundle, documents)
    object.__setattr__(receipt, "binding_digest", "sha256:" + "f" * 64)
    with pytest.raises(ValueError, match="receipt binding differs"):
        receipt.assert_accepted(bundle, SOURCE_REVISION, IDENTITY, _retained(documents))


def test_wrong_adapter_identity_refuses_against_expected_bundle() -> None:
    bundle = _bundle()
    documents = _documents()
    receipt = _receipt(bundle, documents)
    object.__setattr__(
        receipt,
        "adapter",
        AdapterIdentityV1("other-provider", "1", "sha256:" + "e" * 64),
    )
    with pytest.raises(ValueError, match="adapter identity differs"):
        receipt.assert_accepted(bundle, SOURCE_REVISION, IDENTITY, _retained(documents))


def test_retained_evidence_cannot_replay_under_another_adapter() -> None:
    bundle = _bundle()
    documents = _documents()
    receipt = _receipt(bundle, documents)
    adapter = AdapterIdentityV1("other-provider", "2", "sha256:" + "e" * 64)
    changed_binding = replace(bundle.binding, adapter=adapter)
    changed_bundle = replace(bundle, adapter=adapter, binding=changed_binding)
    replayed = replace(
        receipt,
        adapter=adapter,
        binding_digest=changed_bundle.binding_digest,
    )
    with pytest.raises(ValueError, match="wrong adapter identity"):
        replayed.assert_accepted(
            changed_bundle,
            SOURCE_REVISION,
            IDENTITY,
            _retained(documents),
        )


@pytest.mark.parametrize(
    "expected_identity",
    [
        replace(IDENTITY, provider_runner_name="provider-runner-two"),
        replace(IDENTITY, repository="other/repository"),
        replace(
            IDENTITY,
            required_labels=("extra-label", "runner-one", "self-hosted"),
        ),
    ],
    ids=("swapped-provider-display-name", "wrong-repository", "wrong-labels"),
)
def test_provider_runner_coordinates_are_independent_acceptance_inputs(
    expected_identity: ProviderRunnerIdentityV1,
) -> None:
    bundle = _bundle()
    documents = _documents()
    receipt = _receipt(bundle, documents)
    with pytest.raises(ValueError, match="provider runner identity differs"):
        receipt.assert_accepted(
            bundle, SOURCE_REVISION, expected_identity, _retained(documents)
        )


def test_retained_evidence_bytes_are_required_and_load_bearing() -> None:
    bundle = _bundle()
    documents = _documents()
    receipt = _receipt(bundle, documents)

    with pytest.raises(ValueError, match="documents are missing"):
        receipt.assert_accepted(
            bundle, SOURCE_REVISION, IDENTITY, _retained(documents[:-1])
        )

    first = documents[0]
    with pytest.raises(ValueError, match="not canonical"):
        receipt.assert_accepted(
            bundle,
            SOURCE_REVISION,
            IDENTITY,
            (first.canonical_bytes + b"\n", *_retained(documents[1:])),
        )

    tampered_bytes = first.canonical_bytes.replace(b'"success"', b'"failure"')
    with pytest.raises(ValueError, match="retained evidence bytes differ"):
        receipt.assert_accepted(
            bundle,
            SOURCE_REVISION,
            IDENTITY,
            (tampered_bytes, *_retained(documents[1:])),
        )

    invented_digest = replace(receipt.items[0], evidence_digest="sha256:" + "f" * 64)
    object.__setattr__(receipt, "items", (invented_digest, *receipt.items[1:]))
    with pytest.raises(ValueError, match="retained evidence bytes differ"):
        receipt.assert_accepted(bundle, SOURCE_REVISION, IDENTITY, _retained(documents))


def test_preconstructed_evidence_objects_are_not_an_acceptance_input() -> None:
    bundle = _bundle()
    documents = _documents()
    receipt = _receipt(bundle, documents)
    with pytest.raises(ValueError, match="must be canonical bytes"):
        receipt.assert_accepted(
            bundle,
            SOURCE_REVISION,
            IDENTITY,
            documents,  # type: ignore[arg-type]
        )


def test_retained_document_verdict_must_match_the_receipt_row() -> None:
    bundle = _bundle()
    documents = _documents()
    receipt = _receipt(bundle, documents)
    refused = replace(documents[0], status=EvidenceStatus.EXECUTED_FAILED)
    with pytest.raises(ValueError, match="wrong verdict"):
        receipt.assert_accepted(
            bundle,
            SOURCE_REVISION,
            IDENTITY,
            _retained((refused, *documents[1:])),
        )


def test_retained_bytes_bind_the_receipt_mutation_flag() -> None:
    bundle = _bundle()
    documents = _documents()
    receipt = _receipt(bundle, documents)
    replayed = replace(
        receipt,
        items=(replace(receipt.items[0], mutated=True), *receipt.items[1:]),
    )
    with pytest.raises(ValueError, match="wrong mutation flag"):
        replayed.assert_accepted(
            bundle,
            SOURCE_REVISION,
            IDENTITY,
            _retained(documents),
        )


def test_evidence_document_round_trip_refuses_noncanonical_or_wrong_subject() -> None:
    document = _document("provider_selected")
    assert (
        LifecycleEvidenceDocumentV1.from_canonical_bytes(document.canonical_bytes)
        == document
    )
    with pytest.raises(ValueError, match="not canonical"):
        LifecycleEvidenceDocumentV1.from_canonical_bytes(
            document.canonical_bytes + b"\n"
        )

    bundle = _bundle()
    documents = _documents()
    receipt = _receipt(bundle, documents)
    wrong_identity = replace(IDENTITY, provider_runner_name="provider-runner-two")
    wrong_document = _document(documents[0].item, wrong_identity)
    with pytest.raises(ValueError, match="wrong runner identity"):
        receipt.assert_accepted(
            bundle,
            SOURCE_REVISION,
            IDENTITY,
            _retained((wrong_document, *documents[1:])),
        )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("schema", "RunnerTransportReceipt.v2", "schema must be v1"),
        ("source_revision", "A" * 40, "lowercase Git SHA"),
        ("binding_digest", "f" * 64, "binding digest must be typed"),
    ],
)
def test_malformed_receipt_coordinates_refuse(field, value, message) -> None:
    bundle = _bundle()
    receipt = _receipt(bundle, _documents())
    with pytest.raises(ValueError, match=message):
        replace(receipt, **{field: value})


def test_no_proxy_and_both_environment_digests_are_load_bearing() -> None:
    original = _bundle()
    changed = _bundle(
        HostDirectEgressGrantV1("runner-one", "100.64.0.1/32", 8200, "tcp", "wg0")
    )
    original_environment = original.runner_environments[0]
    changed_environment = changed.runner_environments[0]
    assert "NO_PROXY=100.64.0.1" in changed_environment.content
    assert "NO_PROXY=100.64.0.1" in (changed_environment.workload_content or "")

    documents = _documents()
    receipt = _receipt(original, documents)
    object.__setattr__(receipt, "binding_digest", changed.binding_digest)
    object.__setattr__(receipt, "rendered_squid_digest", changed.squid_sha256)
    object.__setattr__(receipt, "rendered_nftables_digest", changed.nftables_sha256)
    with pytest.raises(ValueError, match="runner environment differs"):
        receipt.assert_accepted(
            changed, SOURCE_REVISION, IDENTITY, _retained(documents)
        )

    object.__setattr__(receipt, "runner_environment_digest", changed_environment.sha256)
    assert receipt.workload_environment_digest == original_environment.workload_sha256
    with pytest.raises(ValueError, match="workload environment differs"):
        receipt.assert_accepted(
            changed, SOURCE_REVISION, IDENTITY, _retained(documents)
        )


def test_acceptance_revalidates_bundle_content_instead_of_trusting_digest_fields() -> (
    None
):
    bundle = _bundle()
    documents = _documents()
    receipt = _receipt(bundle, documents)
    object.__setattr__(
        bundle,
        "adapter",
        AdapterIdentityV1("other-provider", "1", "sha256:" + "e" * 64),
    )
    with pytest.raises(ValueError, match="bundle adapter differs"):
        receipt.assert_accepted(bundle, SOURCE_REVISION, IDENTITY, _retained(documents))

    bundle = _bundle()
    documents = _documents()
    receipt = _receipt(bundle, documents)
    object.__setattr__(bundle.binding, "schema", "HostRunnerTransportSpec.v2")
    with pytest.raises(ValueError, match="host runner transport spec schema"):
        receipt.assert_accepted(bundle, SOURCE_REVISION, IDENTITY, _retained(documents))

    bundle = _bundle()
    documents = _documents()
    receipt = _receipt(bundle, documents)
    object.__setattr__(bundle, "squid_conf", bundle.squid_conf + "# stale bytes\n")
    with pytest.raises(ValueError, match="Squid digest differs"):
        receipt.assert_accepted(bundle, SOURCE_REVISION, IDENTITY, _retained(documents))

    bundle = _bundle()
    documents = _documents()
    receipt = _receipt(bundle, documents)
    environment = bundle.runner_environments[0]
    object.__setattr__(
        environment, "content", environment.content + "NO_PROXY=203.0.113.9\n"
    )
    with pytest.raises(ValueError, match="runner environment digest differs"):
        receipt.assert_accepted(bundle, SOURCE_REVISION, IDENTITY, _retained(documents))

    bundle = _bundle()
    documents = _documents()
    receipt = _receipt(bundle, documents)
    environment = bundle.runner_environments[0]
    object.__setattr__(
        environment,
        "workload_content",
        (environment.workload_content or "") + "# stale bytes\n",
    )
    with pytest.raises(ValueError, match="workload environment digest differs"):
        receipt.assert_accepted(bundle, SOURCE_REVISION, IDENTITY, _retained(documents))
