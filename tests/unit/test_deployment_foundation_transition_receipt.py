"""``DeploymentTransitionReceipt.v1`` — the Foundation's half of D16.

CP produces the receipt in a later change; this file proves the FOUNDATION's
half — the closed schema and the pure verifier — independently of that
producer, using the Starter's own real descriptor (`deploy/product.toml`) as
the spec every check compares against.

One planted-defect test per :class:`TransitionFinding`, each paired with a
near-miss that verifies clean, per ADR-0018: a checker proven only on a clean
tree passes for the wrong reason.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from dotmac_deployment_foundation.backup import ArtefactClass, Assurance, BackupRecord
from dotmac_deployment_foundation.errors import SpecError
from dotmac_deployment_foundation.spec import ProductDeploymentSpec
from dotmac_deployment_foundation.transition_receipt import (
    TRANSITION_RECEIPT_SCHEMA,
    TargetSide,
    TransitionBackup,
    TransitionFinding,
    TransitionOutcome,
    TransitionReceiptV1,
    TransitionSide,
    verify_transition_receipt,
)

REAL_DESCRIPTOR = (
    Path(__file__).resolve().parents[2] / "deploy" / "product.toml"
).read_text(encoding="utf-8")


def _spec() -> ProductDeploymentSpec:
    return ProductDeploymentSpec.loads(REAL_DESCRIPTOR, source="<test>")


def _descriptor_digest(spec: ProductDeploymentSpec) -> str:
    return spec.to_canonical_document().sha256_digest()


def _source(spec: ProductDeploymentSpec) -> TransitionSide:
    return TransitionSide(
        descriptor_sha256="sha256:" + "1" * 64,
        migration_heads=("a000",),
    )


def _target_side(
    spec: ProductDeploymentSpec, *, revision: str = "a" * 40
) -> TargetSide:
    return TargetSide(
        descriptor_sha256=_descriptor_digest(spec),
        migration_heads=tuple(spec.migration.expected_heads),
        image_digest=spec.image_digest,
        image_source_revision=revision,
    )


def _backup() -> TransitionBackup:
    return TransitionBackup(
        bundle_digest="deadbeef" * 8,
        checksum_algorithm="sha256",
        size_bytes=1_000_000,
        bundle_id="bundle-1",
    )


def _backup_record() -> BackupRecord:
    return BackupRecord(
        dataset="starter-db",
        path="/backups/starter.bundle",
        size_bytes=1_000_000,
        checksum="deadbeef" * 8,
        checksum_algorithm="sha256",
        completed_at_epoch=1_700_000_000,
        assurance=Assurance.PROVED,
        artefact_class=ArtefactClass.RECOVERY_BUNDLE,
    )


def _receipt(
    spec: ProductDeploymentSpec,
    *,
    run_id: str = "run-1",
    target: str = "host-a",
    source: TransitionSide | None = None,
    target_side: TargetSide | None = None,
    backup: TransitionBackup | None = None,
    previous_receipt_digest: str | None = None,
) -> TransitionReceiptV1:
    return TransitionReceiptV1(
        product=spec.product,
        environment=spec.environment,
        target=target,
        run_id=run_id,
        source=source if source is not None else _source(spec),
        target_side=target_side if target_side is not None else _target_side(spec),
        backup=backup if backup is not None else _backup(),
        previous_receipt_digest=previous_receipt_digest,
    )


def _verify(
    spec: ProductDeploymentSpec,
    receipt: TransitionReceiptV1,
    *,
    observed_target_heads=None,
    previous_receipt: TransitionReceiptV1 | None = None,
    backup_record: BackupRecord | None = None,
    expected_image_digest: str | None = None,
):
    return verify_transition_receipt(
        receipt,
        spec=spec,
        observed_target_heads=(
            observed_target_heads
            if observed_target_heads is not None
            else spec.migration.expected_heads
        ),
        previous_receipt=previous_receipt,
        backup_record=backup_record if backup_record is not None else _backup_record(),
        expected_image_digest=(
            expected_image_digest
            if expected_image_digest is not None
            else spec.image_digest
        ),
    )


def _chained_second_receipt(
    spec: ProductDeploymentSpec,
) -> tuple[TransitionReceiptV1, TransitionReceiptV1]:
    """A first receipt and a second whose source is the first's target."""
    first = _receipt(spec)
    second_source = TransitionSide(
        descriptor_sha256=first.target_side.descriptor_sha256,
        migration_heads=first.target_side.migration_heads,
    )
    second = _receipt(
        spec,
        run_id="run-2",
        target="host-b",
        source=second_source,
        previous_receipt_digest=str(first.digest()),
    )
    return first, second


# ── the negative control ─────────────────────────────────────────────────────


def test_a_fully_valid_chain_of_two_receipts_verifies() -> None:
    spec = _spec()
    first, second = _chained_second_receipt(spec)

    first_verdict = _verify(spec, first, previous_receipt=None)
    assert first_verdict.outcome is TransitionOutcome.VERIFIED
    assert first_verdict.findings == ()

    second_verdict = _verify(spec, second, previous_receipt=first)
    assert second_verdict.outcome is TransitionOutcome.VERIFIED
    assert second_verdict.findings == ()


# ── chain findings ───────────────────────────────────────────────────────────


def test_a_broken_chain_digest_is_refused() -> None:
    spec = _spec()
    first, second = _chained_second_receipt(spec)
    tampered = _receipt(
        spec,
        run_id="run-2",
        target="host-b",
        source=TransitionSide(
            descriptor_sha256=first.target_side.descriptor_sha256,
            migration_heads=first.target_side.migration_heads,
        ),
        previous_receipt_digest="sha256:" + "9" * 64,
    )
    verdict = _verify(spec, tampered, previous_receipt=first)
    assert TransitionFinding.CHAIN_DIGEST_MISMATCH in verdict.findings

    # near miss: the correct digest passes this check
    verdict_ok = _verify(spec, second, previous_receipt=first)
    assert TransitionFinding.CHAIN_DIGEST_MISMATCH not in verdict_ok.findings


def test_source_not_equal_to_previous_target_is_refused() -> None:
    spec = _spec()
    first, _ = _chained_second_receipt(spec)
    wrong_source = _receipt(
        spec,
        run_id="run-2",
        target="host-b",
        source=TransitionSide(
            descriptor_sha256="sha256:" + "7" * 64,
            migration_heads=("a000",),
        ),
        previous_receipt_digest=str(first.digest()),
    )
    verdict = _verify(spec, wrong_source, previous_receipt=first)
    assert TransitionFinding.CHAIN_SOURCE_MISMATCH in verdict.findings

    _, correct_second = _chained_second_receipt(spec)
    verdict_ok = _verify(spec, correct_second, previous_receipt=first)
    assert TransitionFinding.CHAIN_SOURCE_MISMATCH not in verdict_ok.findings


def test_a_first_receipt_with_a_previous_digest_is_refused() -> None:
    spec = _spec()
    receipt = _receipt(spec, previous_receipt_digest="sha256:" + "2" * 64)
    verdict = _verify(spec, receipt, previous_receipt=None)
    assert TransitionFinding.CHAIN_PREVIOUS_UNEXPECTED in verdict.findings

    # near miss: no previous receipt digest and no previous receipt
    clean = _receipt(spec)
    verdict_ok = _verify(spec, clean, previous_receipt=None)
    assert TransitionFinding.CHAIN_PREVIOUS_UNEXPECTED not in verdict_ok.findings


def test_a_non_first_receipt_without_one_is_refused() -> None:
    spec = _spec()
    first, _ = _chained_second_receipt(spec)
    missing_link = _receipt(
        spec,
        run_id="run-2",
        target="host-b",
        source=TransitionSide(
            descriptor_sha256=first.target_side.descriptor_sha256,
            migration_heads=first.target_side.migration_heads,
        ),
        previous_receipt_digest=None,
    )
    verdict = _verify(spec, missing_link, previous_receipt=first)
    assert TransitionFinding.CHAIN_PREVIOUS_MISSING in verdict.findings

    _, correct_second = _chained_second_receipt(spec)
    verdict_ok = _verify(spec, correct_second, previous_receipt=first)
    assert TransitionFinding.CHAIN_PREVIOUS_MISSING not in verdict_ok.findings


# ── target-heads findings ────────────────────────────────────────────────────


def test_a_head_omission_is_refused() -> None:
    spec = _spec()
    receipt = _receipt(
        spec,
        target_side=TargetSide(
            descriptor_sha256=_descriptor_digest(spec),
            migration_heads=(),
            image_digest=spec.image_digest,
            image_source_revision="a" * 40,
        ),
    )
    verdict = _verify(spec, receipt)
    assert TransitionFinding.TARGET_HEADS_MISSING in verdict.findings

    verdict_ok = _verify(spec, _receipt(spec))
    assert TransitionFinding.TARGET_HEADS_MISSING not in verdict_ok.findings


def test_an_extra_head_is_refused() -> None:
    spec = _spec()
    extra_heads = tuple(sorted({*spec.migration.expected_heads, "zzzz"}))
    receipt = _receipt(
        spec,
        target_side=TargetSide(
            descriptor_sha256=_descriptor_digest(spec),
            migration_heads=extra_heads,
            image_digest=spec.image_digest,
            image_source_revision="a" * 40,
        ),
    )
    verdict = _verify(spec, receipt)
    assert TransitionFinding.TARGET_HEADS_EXTRA in verdict.findings

    verdict_ok = _verify(spec, _receipt(spec))
    assert TransitionFinding.TARGET_HEADS_EXTRA not in verdict_ok.findings


def test_a_duplicate_observed_head_is_refused() -> None:
    spec = _spec()
    receipt = _receipt(spec)
    duplicated = list(spec.migration.expected_heads) * 2
    verdict = _verify(spec, receipt, observed_target_heads=duplicated)
    assert TransitionFinding.TARGET_HEADS_DUPLICATE in verdict.findings

    verdict_ok = _verify(spec, receipt)
    assert TransitionFinding.TARGET_HEADS_DUPLICATE not in verdict_ok.findings


# ── descriptor / image / product findings ───────────────────────────────────


def test_a_descriptor_mismatch_is_refused() -> None:
    spec = _spec()
    receipt = _receipt(
        spec,
        target_side=TargetSide(
            descriptor_sha256="sha256:" + "3" * 64,
            migration_heads=tuple(spec.migration.expected_heads),
            image_digest=spec.image_digest,
            image_source_revision="a" * 40,
        ),
    )
    verdict = _verify(spec, receipt)
    assert TransitionFinding.TARGET_DESCRIPTOR_MISMATCH in verdict.findings

    verdict_ok = _verify(spec, _receipt(spec))
    assert TransitionFinding.TARGET_DESCRIPTOR_MISMATCH not in verdict_ok.findings


def test_an_image_mismatch_is_refused() -> None:
    spec = _spec()
    receipt = _receipt(spec)
    verdict = _verify(spec, receipt, expected_image_digest="sha256:" + "4" * 64)
    assert TransitionFinding.IMAGE_DIGEST_MISMATCH in verdict.findings

    verdict_ok = _verify(spec, receipt)
    assert TransitionFinding.IMAGE_DIGEST_MISMATCH not in verdict_ok.findings


def test_a_bad_revision_is_refused() -> None:
    spec = _spec()
    receipt = _receipt(spec, target_side=_target_side(spec, revision="not-a-git-sha"))
    verdict = _verify(spec, receipt)
    assert TransitionFinding.IMAGE_REVISION_INVALID in verdict.findings

    verdict_ok = _verify(spec, _receipt(spec))
    assert TransitionFinding.IMAGE_REVISION_INVALID not in verdict_ok.findings


def test_a_product_mismatch_is_refused() -> None:
    spec = _spec()
    receipt = TransitionReceiptV1(
        product="a-different-product",
        environment=spec.environment,
        target="host-a",
        run_id="run-1",
        source=_source(spec),
        target_side=_target_side(spec),
        backup=_backup(),
    )
    verdict = _verify(spec, receipt)
    assert TransitionFinding.PRODUCT_MISMATCH in verdict.findings

    verdict_ok = _verify(spec, _receipt(spec))
    assert TransitionFinding.PRODUCT_MISMATCH not in verdict_ok.findings


# ── backup findings ──────────────────────────────────────────────────────────


def test_a_data_export_backup_is_refused() -> None:
    spec = _spec()
    receipt = _receipt(spec)
    record = BackupRecord(
        dataset="starter-db",
        path="/backups/starter.dump",
        size_bytes=1_000_000,
        checksum="deadbeef" * 8,
        checksum_algorithm="sha256",
        completed_at_epoch=1_700_000_000,
        assurance=Assurance.VERIFIED,
        artefact_class=ArtefactClass.DATA_EXPORT,
    )
    verdict = _verify(spec, receipt, backup_record=record)
    assert TransitionFinding.BACKUP_NOT_RECOVERY_BUNDLE in verdict.findings

    verdict_ok = _verify(spec, receipt)
    assert TransitionFinding.BACKUP_NOT_RECOVERY_BUNDLE not in verdict_ok.findings


def test_backup_assurance_below_verified_is_refused() -> None:
    spec = _spec()
    receipt = _receipt(spec)
    record = BackupRecord(
        dataset="starter-db",
        path="/backups/starter.bundle",
        size_bytes=1_000_000,
        checksum="deadbeef" * 8,
        checksum_algorithm="sha256",
        completed_at_epoch=1_700_000_000,
        assurance=Assurance.COMPLETED,
        artefact_class=ArtefactClass.RECOVERY_BUNDLE,
    )
    verdict = _verify(spec, receipt, backup_record=record)
    assert TransitionFinding.BACKUP_ASSURANCE_TOO_LOW in verdict.findings

    verdict_ok = _verify(spec, receipt)
    assert TransitionFinding.BACKUP_ASSURANCE_TOO_LOW not in verdict_ok.findings


def test_a_bundle_digest_mismatch_is_refused() -> None:
    spec = _spec()
    receipt = _receipt(spec)
    record = BackupRecord(
        dataset="starter-db",
        path="/backups/starter.bundle",
        size_bytes=1_000_000,
        checksum="cafebabe" * 8,
        checksum_algorithm="sha256",
        completed_at_epoch=1_700_000_000,
        assurance=Assurance.PROVED,
        artefact_class=ArtefactClass.RECOVERY_BUNDLE,
    )
    verdict = _verify(spec, receipt, backup_record=record)
    assert TransitionFinding.BACKUP_DIGEST_MISMATCH in verdict.findings

    verdict_ok = _verify(spec, receipt)
    assert TransitionFinding.BACKUP_DIGEST_MISMATCH not in verdict_ok.findings


def test_a_size_mismatch_is_refused() -> None:
    spec = _spec()
    receipt = _receipt(spec)
    record = BackupRecord(
        dataset="starter-db",
        path="/backups/starter.bundle",
        size_bytes=999,
        checksum="deadbeef" * 8,
        checksum_algorithm="sha256",
        completed_at_epoch=1_700_000_000,
        assurance=Assurance.PROVED,
        artefact_class=ArtefactClass.RECOVERY_BUNDLE,
    )
    verdict = _verify(spec, receipt, backup_record=record)
    assert TransitionFinding.BACKUP_SIZE_MISMATCH in verdict.findings

    verdict_ok = _verify(spec, receipt)
    assert TransitionFinding.BACKUP_SIZE_MISMATCH not in verdict_ok.findings


# ── parse(): strict, typed, no secrets ──────────────────────────────────────


def _valid_document(spec: ProductDeploymentSpec) -> dict:
    return _receipt(spec).as_mapping()


def test_parse_round_trips_a_valid_document() -> None:
    spec = _spec()
    receipt = _receipt(spec)
    parsed = TransitionReceiptV1.parse(receipt.as_mapping())
    assert parsed.digest() == receipt.digest()
    assert parsed.as_mapping() == receipt.as_mapping()


def test_parse_refuses_an_unknown_top_level_key() -> None:
    spec = _spec()
    document = _valid_document(spec)
    document["unexpected_field"] = "surprise"
    with pytest.raises(SpecError, match="unknown field"):
        TransitionReceiptV1.parse(document)


def test_parse_refuses_a_wrong_type() -> None:
    spec = _spec()
    document = _valid_document(spec)
    document["source"]["migration_heads"] = "a003"  # should be a list
    with pytest.raises(SpecError):
        TransitionReceiptV1.parse(document)


def test_parse_refuses_a_secret_shaped_value() -> None:
    spec = _spec()
    document = _valid_document(spec)
    document["backup"]["bundle_id"] = "AKIAIOSFODNN7EXAMPLE"
    with pytest.raises(Exception) as exc:
        TransitionReceiptV1.parse(document)
    assert exc.type.__name__ in {"SecretValueError", "SpecError"}


def test_parse_refuses_the_wrong_schema() -> None:
    spec = _spec()
    document = _valid_document(spec)
    document["schema"] = "SomethingElse.v1"
    with pytest.raises(SpecError, match=TRANSITION_RECEIPT_SCHEMA):
        TransitionReceiptV1.parse(document)


# ── determinism ──────────────────────────────────────────────────────────────


def test_the_digest_is_stable_across_key_order() -> None:
    spec = _spec()
    receipt = _receipt(spec)
    reordered = json.loads(json.dumps(receipt.as_mapping()))
    # Rebuild a dict with reversed insertion order to prove sort_keys, not
    # incidental dict ordering, is what makes the digest stable.
    shuffled = dict(reversed(list(reordered.items())))
    shuffled["source"] = dict(reversed(list(shuffled["source"].items())))
    shuffled["target_side"] = dict(reversed(list(shuffled["target_side"].items())))
    shuffled["backup"] = dict(reversed(list(shuffled["backup"].items())))
    canonical_a = json.dumps(
        receipt.as_mapping(), sort_keys=True, separators=(",", ":")
    )
    canonical_b = json.dumps(shuffled, sort_keys=True, separators=(",", ":"))
    assert canonical_a == canonical_b
    assert TransitionReceiptV1.parse(shuffled).digest() == receipt.digest()
