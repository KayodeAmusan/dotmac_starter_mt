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
from typing import Any
from unittest.mock import patch

import pytest
from dotmac_deployment_foundation.backup import ArtefactClass, Assurance, BackupRecord
from dotmac_deployment_foundation.errors import SecretValueError, SpecError
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

#: Sentinel distinguishing "not passed" from "explicitly passed as None", so
#: `_verify` can default `genesis_source`/`previous_receipt` for ordinary
#: tests while still letting a test assert the ambiguous "neither given" and
#: "both given" cases explicitly.
_UNSET = object()


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


#: Deliberately equal to `_backup_record().path` below: `bundle_id` binds to
#: the record's recorded artefact path (see `TransitionBackup.bundle_id`'s
#: docstring), so every positive-control fixture must agree on it.
_BACKUP_PATH = "/backups/starter.bundle"


def _backup(*, bundle_id: str = _BACKUP_PATH) -> TransitionBackup:
    return TransitionBackup(
        bundle_digest="deadbeef" * 8,
        checksum_algorithm="sha256",
        size_bytes=1_000_000,
        bundle_id=bundle_id,
    )


def _backup_record() -> BackupRecord:
    return BackupRecord(
        dataset="starter-db",
        path=_BACKUP_PATH,
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
    spec: Any,
    receipt: TransitionReceiptV1,
    *,
    observed_target_heads=None,
    previous_receipt: TransitionReceiptV1 | None | object = _UNSET,
    genesis_source: TransitionSide | None | object = _UNSET,
    backup_record: BackupRecord | None = None,
    observed_image_digest: str | None = None,
    expected_run_id: str | None = None,
    expected_target: str | None = None,
):
    resolved_previous = None if previous_receipt is _UNSET else previous_receipt
    if genesis_source is _UNSET:
        resolved_genesis = receipt.source if resolved_previous is None else None
    else:
        resolved_genesis = genesis_source
    return verify_transition_receipt(
        receipt,
        spec=spec,
        observed_target_heads=(
            observed_target_heads
            if observed_target_heads is not None
            else spec.migration.expected_heads
        ),
        previous_receipt=resolved_previous,
        genesis_source=resolved_genesis,
        backup_record=backup_record if backup_record is not None else _backup_record(),
        observed_image_digest=(
            observed_image_digest
            if observed_image_digest is not None
            else spec.image_digest
        ),
        expected_run_id=(
            expected_run_id if expected_run_id is not None else receipt.run_id
        ),
        expected_target=(
            expected_target if expected_target is not None else receipt.target
        ),
    )


def _chained_second_receipt(
    spec: ProductDeploymentSpec,
) -> tuple[TransitionReceiptV1, TransitionReceiptV1]:
    """A first receipt and a second whose source is the first's target.

    Both hops stay on ONE host: a chain is per product, environment and
    target (see the module docstring), so a genuine continuation of the chain
    never changes the host.
    """
    first = _receipt(spec)
    second_source = TransitionSide(
        descriptor_sha256=first.target_side.descriptor_sha256,
        migration_heads=first.target_side.migration_heads,
    )
    second = _receipt(
        spec,
        run_id="run-2",
        target=first.target,
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
        target=first.target,
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
        target=first.target,
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
    verdict = _verify(
        spec, receipt, previous_receipt=None, genesis_source=receipt.source
    )
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
        target=first.target,
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


def test_a_chain_hop_to_a_different_host_is_refused() -> None:
    """A chain is per product/environment/TARGET — moving host is not a hop."""
    spec = _spec()
    first, second = _chained_second_receipt(spec)
    cross_host = _receipt(
        spec,
        run_id="run-2",
        target="host-b",
        source=TransitionSide(
            descriptor_sha256=first.target_side.descriptor_sha256,
            migration_heads=first.target_side.migration_heads,
        ),
        previous_receipt_digest=str(first.digest()),
    )
    verdict = _verify(
        spec, cross_host, previous_receipt=first, expected_target="host-b"
    )
    assert TransitionFinding.CHAIN_SCOPE_MISMATCH in verdict.findings

    verdict_ok = _verify(spec, second, previous_receipt=first)
    assert TransitionFinding.CHAIN_SCOPE_MISMATCH not in verdict_ok.findings


def test_neither_previous_receipt_nor_genesis_source_is_refused() -> None:
    spec = _spec()
    receipt = _receipt(spec)
    verdict = _verify(spec, receipt, previous_receipt=None, genesis_source=None)
    assert TransitionFinding.CHAIN_ANCHOR_AMBIGUOUS in verdict.findings

    verdict_ok = _verify(spec, receipt, previous_receipt=None)
    assert TransitionFinding.CHAIN_ANCHOR_AMBIGUOUS not in verdict_ok.findings


def test_both_previous_receipt_and_genesis_source_is_refused() -> None:
    spec = _spec()
    first, second = _chained_second_receipt(spec)
    verdict = _verify(spec, second, previous_receipt=first, genesis_source=first.source)
    assert TransitionFinding.CHAIN_ANCHOR_AMBIGUOUS in verdict.findings

    verdict_ok = _verify(spec, second, previous_receipt=first)
    assert TransitionFinding.CHAIN_ANCHOR_AMBIGUOUS not in verdict_ok.findings


def test_a_first_receipts_source_not_matching_the_named_genesis_is_refused() -> None:
    spec = _spec()
    receipt = _receipt(spec)
    wrong_genesis = TransitionSide(
        descriptor_sha256="sha256:" + "8" * 64,
        migration_heads=("a000",),
    )
    verdict = _verify(
        spec, receipt, previous_receipt=None, genesis_source=wrong_genesis
    )
    assert TransitionFinding.GENESIS_SOURCE_MISMATCH in verdict.findings

    verdict_ok = _verify(
        spec, receipt, previous_receipt=None, genesis_source=receipt.source
    )
    assert TransitionFinding.GENESIS_SOURCE_MISMATCH not in verdict_ok.findings


def test_previous_receipt_digest_computation_failure_is_a_finding() -> None:
    """The 'never raises' claim, made true: a raise from `previous_receipt
    .digest()` is caught (`SpecError` family only) and reported."""
    spec = _spec()
    first, second = _chained_second_receipt(spec)

    def _boom(self: TransitionReceiptV1) -> None:
        raise SpecError("boom", where="<test>")

    with patch.object(TransitionReceiptV1, "digest", _boom):
        verdict = _verify(spec, second, previous_receipt=first)
    assert TransitionFinding.INPUT_NOT_CANONICALIZABLE in verdict.findings

    verdict_ok = _verify(spec, second, previous_receipt=first)
    assert TransitionFinding.INPUT_NOT_CANONICALIZABLE not in verdict_ok.findings


# ── run identity findings ───────────────────────────────────────────────────


def test_a_run_id_not_matching_the_caller_is_refused() -> None:
    spec = _spec()
    receipt = _receipt(spec)
    verdict = _verify(spec, receipt, expected_run_id="a-different-run")
    assert TransitionFinding.RUN_ID_MISMATCH in verdict.findings

    verdict_ok = _verify(spec, receipt)
    assert TransitionFinding.RUN_ID_MISMATCH not in verdict_ok.findings


def test_a_reused_run_id_across_a_chain_hop_is_refused() -> None:
    spec = _spec()
    first, second = _chained_second_receipt(spec)
    reused = _receipt(
        spec,
        run_id=first.run_id,
        target=first.target,
        source=TransitionSide(
            descriptor_sha256=first.target_side.descriptor_sha256,
            migration_heads=first.target_side.migration_heads,
        ),
        previous_receipt_digest=str(first.digest()),
    )
    verdict = _verify(spec, reused, previous_receipt=first)
    assert TransitionFinding.RUN_ID_REUSED in verdict.findings

    verdict_ok = _verify(spec, second, previous_receipt=first)
    assert TransitionFinding.RUN_ID_REUSED not in verdict_ok.findings


# ── scope findings ───────────────────────────────────────────────────────────


def test_a_receipt_environment_not_matching_the_spec_is_refused() -> None:
    spec = _spec()
    receipt = TransitionReceiptV1(
        product=spec.product,
        environment="a-different-environment",
        target="host-a",
        run_id="run-1",
        source=_source(spec),
        target_side=_target_side(spec),
        backup=_backup(),
    )
    verdict = _verify(spec, receipt)
    assert TransitionFinding.ENVIRONMENT_MISMATCH in verdict.findings

    verdict_ok = _verify(spec, _receipt(spec))
    assert TransitionFinding.ENVIRONMENT_MISMATCH not in verdict_ok.findings


def test_a_receipt_target_not_matching_the_launch_target_is_refused() -> None:
    spec = _spec()
    receipt = _receipt(spec, target="host-a")
    verdict = _verify(spec, receipt, expected_target="a-different-host")
    assert TransitionFinding.TARGET_MISMATCH in verdict.findings

    verdict_ok = _verify(spec, receipt)
    assert TransitionFinding.TARGET_MISMATCH not in verdict_ok.findings


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
    assert TransitionFinding.TARGET_HEADS_DECLARED_VS_SPEC in verdict.findings

    verdict_ok = _verify(spec, _receipt(spec))
    assert TransitionFinding.TARGET_HEADS_DECLARED_VS_SPEC not in verdict_ok.findings


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
    assert TransitionFinding.TARGET_HEADS_DECLARED_VS_SPEC in verdict.findings

    verdict_ok = _verify(spec, _receipt(spec))
    assert TransitionFinding.TARGET_HEADS_DECLARED_VS_SPEC not in verdict_ok.findings


def test_a_duplicate_observed_head_is_refused() -> None:
    spec = _spec()
    receipt = _receipt(spec)
    duplicated = list(spec.migration.expected_heads) * 2
    verdict = _verify(spec, receipt, observed_target_heads=duplicated)
    assert TransitionFinding.TARGET_HEADS_DUPLICATE in verdict.findings

    verdict_ok = _verify(spec, receipt)
    assert TransitionFinding.TARGET_HEADS_DUPLICATE not in verdict_ok.findings


def test_an_observed_head_outside_the_declared_set_is_refused() -> None:
    """Survivor-killer: an observed head the receipt never declared."""
    spec = _spec()
    receipt = _receipt(spec)
    observed = [*spec.migration.expected_heads, "not-declared"]
    verdict = _verify(spec, receipt, observed_target_heads=observed)
    assert TransitionFinding.TARGET_HEADS_DECLARED_VS_OBSERVED in verdict.findings

    verdict_ok = _verify(spec, receipt)
    assert (
        TransitionFinding.TARGET_HEADS_DECLARED_VS_OBSERVED not in verdict_ok.findings
    )


def test_a_declared_head_the_host_did_not_report_is_refused() -> None:
    """Survivor-killer: the receipt declares a head no host observation named."""
    spec = _spec()
    declared = tuple(sorted({*spec.migration.expected_heads, "also-declared"}))
    receipt = _receipt(
        spec,
        target_side=TargetSide(
            descriptor_sha256=_descriptor_digest(spec),
            migration_heads=declared,
            image_digest=spec.image_digest,
            image_source_revision="a" * 40,
        ),
    )
    # observed matches declared (so DECLARED_VS_SPEC also fires, but the
    # point of this test is DECLARED_VS_OBSERVED specifically):
    verdict = _verify(spec, receipt, observed_target_heads=declared)
    assert TransitionFinding.TARGET_HEADS_DECLARED_VS_OBSERVED not in verdict.findings
    # now observed omits the extra declared head:
    verdict_missing_observed = _verify(
        spec, receipt, observed_target_heads=spec.migration.expected_heads
    )
    assert (
        TransitionFinding.TARGET_HEADS_DECLARED_VS_OBSERVED
        in verdict_missing_observed.findings
    )


def test_a_heads_only_chain_source_mismatch_is_refused() -> None:
    """Survivor-killer: descriptor agrees but heads alone differ across a hop."""
    spec = _spec()
    first, _ = _chained_second_receipt(spec)
    wrong_heads_only = _receipt(
        spec,
        run_id="run-2",
        target=first.target,
        source=TransitionSide(
            descriptor_sha256=first.target_side.descriptor_sha256,
            migration_heads=("zzzz",),
        ),
        previous_receipt_digest=str(first.digest()),
    )
    verdict = _verify(spec, wrong_heads_only, previous_receipt=first)
    assert TransitionFinding.CHAIN_SOURCE_MISMATCH in verdict.findings


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


def test_a_spec_canonicalization_failure_is_a_finding() -> None:
    """The 'never raises' claim: a raise from `spec.to_canonical_document()`
    is caught (`SpecError` family only) and reported, not propagated."""
    spec = _spec()
    receipt = _receipt(spec)

    class _RaisingSpec:
        def __getattr__(self, name: str) -> Any:
            return getattr(spec, name)

        def to_canonical_document(self) -> Any:
            raise SpecError("boom", where="<test>")

    verdict = _verify(_RaisingSpec(), receipt)
    assert TransitionFinding.INPUT_NOT_CANONICALIZABLE in verdict.findings

    verdict_ok = _verify(spec, receipt)
    assert TransitionFinding.INPUT_NOT_CANONICALIZABLE not in verdict_ok.findings


def test_an_image_not_matching_the_descriptor_is_refused() -> None:
    spec = _spec()
    other_digest = "sha256:" + "5" * 64
    receipt = _receipt(
        spec,
        target_side=TargetSide(
            descriptor_sha256=_descriptor_digest(spec),
            migration_heads=tuple(spec.migration.expected_heads),
            image_digest=other_digest,
            image_source_revision="a" * 40,
        ),
    )
    # observed matches the receipt's (wrong) image so only the descriptor
    # comparison is exercised here:
    verdict = _verify(spec, receipt, observed_image_digest=other_digest)
    assert TransitionFinding.IMAGE_DESCRIPTOR_MISMATCH in verdict.findings

    verdict_ok = _verify(spec, _receipt(spec))
    assert TransitionFinding.IMAGE_DESCRIPTOR_MISMATCH not in verdict_ok.findings


def test_an_image_mismatch_is_refused() -> None:
    spec = _spec()
    receipt = _receipt(spec)
    verdict = _verify(spec, receipt, observed_image_digest="sha256:" + "4" * 64)
    assert TransitionFinding.IMAGE_DIGEST_MISMATCH in verdict.findings

    verdict_ok = _verify(spec, receipt)
    assert TransitionFinding.IMAGE_DIGEST_MISMATCH not in verdict_ok.findings


def test_a_malformed_observed_image_digest_is_a_finding_not_an_exception() -> None:
    spec = _spec()
    receipt = _receipt(spec)
    verdict = _verify(spec, receipt, observed_image_digest="not-a-digest")
    assert TransitionFinding.OBSERVED_IMAGE_MALFORMED in verdict.findings

    verdict_ok = _verify(spec, receipt)
    assert TransitionFinding.OBSERVED_IMAGE_MALFORMED not in verdict_ok.findings


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
        path=_BACKUP_PATH,
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
        path=_BACKUP_PATH,
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


def test_a_backup_id_not_matching_the_records_path_is_refused() -> None:
    spec = _spec()
    receipt = _receipt(spec, backup=_backup(bundle_id="not-the-recorded-path"))
    verdict = _verify(spec, receipt)
    assert TransitionFinding.BACKUP_ID_MISMATCH in verdict.findings

    verdict_ok = _verify(spec, _receipt(spec))
    assert TransitionFinding.BACKUP_ID_MISMATCH not in verdict_ok.findings


def test_a_bundle_digest_mismatch_is_refused() -> None:
    spec = _spec()
    receipt = _receipt(spec)
    record = BackupRecord(
        dataset="starter-db",
        path=_BACKUP_PATH,
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


def test_a_checksum_algorithm_only_backup_mismatch_is_refused() -> None:
    """Survivor-killer: the hex agrees, only the algorithm label differs."""
    spec = _spec()
    receipt = _receipt(spec)
    record = BackupRecord(
        dataset="starter-db",
        path=_BACKUP_PATH,
        size_bytes=1_000_000,
        checksum="deadbeef" * 8,
        checksum_algorithm="sha512",
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
        path=_BACKUP_PATH,
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


# ── constructor guards ───────────────────────────────────────────────────────


def test_migration_heads_refuses_a_bare_string() -> None:
    with pytest.raises(SpecError, match="bare"):
        TransitionSide(descriptor_sha256="sha256:" + "1" * 64, migration_heads="a000")


def test_migration_heads_refuses_a_non_string_element() -> None:
    bad_heads: Any = (1, 2)
    with pytest.raises(SpecError, match="must be a string"):
        TransitionSide(
            descriptor_sha256="sha256:" + "1" * 64, migration_heads=bad_heads
        )


def test_required_refuses_a_non_string_value() -> None:
    bad_bundle_id: Any = 123
    with pytest.raises(SpecError, match="must be a string"):
        TransitionBackup(
            bundle_digest="deadbeef" * 8,
            checksum_algorithm="sha256",
            size_bytes=1,
            bundle_id=bad_bundle_id,
        )


def test_size_bytes_refuses_a_bool() -> None:
    bad_size: Any = True
    with pytest.raises(SpecError, match="must be an integer"):
        TransitionBackup(
            bundle_digest="deadbeef" * 8,
            checksum_algorithm="sha256",
            size_bytes=bad_size,
            bundle_id=_BACKUP_PATH,
        )


def test_size_bytes_refuses_a_float() -> None:
    bad_size: Any = 1.5
    with pytest.raises(SpecError, match="must be an integer"):
        TransitionBackup(
            bundle_digest="deadbeef" * 8,
            checksum_algorithm="sha256",
            size_bytes=bad_size,
            bundle_id=_BACKUP_PATH,
        )


def test_size_bytes_refuses_negative() -> None:
    with pytest.raises(SpecError, match="negative"):
        TransitionBackup(
            bundle_digest="deadbeef" * 8,
            checksum_algorithm="sha256",
            size_bytes=-1,
            bundle_id=_BACKUP_PATH,
        )


# ── parse(): strict, typed, canonical, no secrets ───────────────────────────


def _valid_document(spec: ProductDeploymentSpec) -> dict:
    return _receipt(spec).as_mapping()


def test_parse_round_trips_a_valid_document() -> None:
    spec = _spec()
    receipt = _receipt(spec)
    parsed = TransitionReceiptV1.parse(receipt.as_mapping())
    assert parsed.digest() == receipt.digest()
    assert parsed.as_mapping() == receipt.as_mapping()


def test_parse_as_mapping_round_trips_for_every_accepted_fixture() -> None:
    """Property-style: `parse(doc).as_mapping() == doc` for several distinct
    accepted documents, not just one lucky fixture."""
    spec = _spec()
    first, second = _chained_second_receipt(spec)
    genesis_only = _receipt(spec, run_id="run-3", target="host-c")
    for candidate in (first, second, genesis_only):
        document = candidate.as_mapping()
        parsed = TransitionReceiptV1.parse(document)
        assert parsed.as_mapping() == document


def test_parse_refuses_an_unknown_top_level_key() -> None:
    spec = _spec()
    document = _valid_document(spec)
    document["unexpected_field"] = "surprise"
    with pytest.raises(SpecError, match="unknown field"):
        TransitionReceiptV1.parse(document)


def test_parse_refuses_an_unknown_key_in_source() -> None:
    spec = _spec()
    document = _valid_document(spec)
    document["source"]["unexpected"] = "surprise"
    with pytest.raises(SpecError, match="unknown field"):
        TransitionReceiptV1.parse(document)


def test_parse_refuses_an_unknown_key_in_target_side() -> None:
    spec = _spec()
    document = _valid_document(spec)
    document["target_side"]["unexpected"] = "surprise"
    with pytest.raises(SpecError, match="unknown field"):
        TransitionReceiptV1.parse(document)


def test_parse_refuses_an_unknown_key_in_backup() -> None:
    spec = _spec()
    document = _valid_document(spec)
    document["backup"]["unexpected"] = "surprise"
    with pytest.raises(SpecError, match="unknown field"):
        TransitionReceiptV1.parse(document)


def test_parse_refuses_a_missing_required_key() -> None:
    spec = _spec()
    document = _valid_document(spec)
    del document["backup"]["bundle_id"]
    with pytest.raises(SpecError, match="missing required field"):
        TransitionReceiptV1.parse(document)


def test_parse_refuses_a_wrong_type() -> None:
    spec = _spec()
    document = _valid_document(spec)
    document["source"]["migration_heads"] = "a003"  # should be a list
    with pytest.raises(SpecError):
        TransitionReceiptV1.parse(document)


def test_parse_refuses_unsorted_declared_heads() -> None:
    spec = _spec()
    document = _valid_document(spec)
    document["target_side"]["migration_heads"] = ["b000", "a000"]
    with pytest.raises(SpecError, match="sorted"):
        TransitionReceiptV1.parse(document)


def test_parse_refuses_duplicate_declared_heads() -> None:
    spec = _spec()
    document = _valid_document(spec)
    document["target_side"]["migration_heads"] = ["a000", "a000"]
    with pytest.raises(SpecError, match="duplicate"):
        TransitionReceiptV1.parse(document)


def test_parse_refuses_a_non_string_head() -> None:
    spec = _spec()
    document = _valid_document(spec)
    document["source"]["migration_heads"] = [123]
    with pytest.raises(SpecError):
        TransitionReceiptV1.parse(document)


def test_parse_refuses_a_bool_size_bytes() -> None:
    spec = _spec()
    document = _valid_document(spec)
    document["backup"]["size_bytes"] = True
    with pytest.raises(SpecError, match="must be an integer"):
        TransitionReceiptV1.parse(document)


def test_parse_refuses_a_bool_previous_receipt_digest() -> None:
    spec = _spec()
    document = _valid_document(spec)
    document["previous_receipt_digest"] = True
    with pytest.raises(SpecError, match="string or null"):
        TransitionReceiptV1.parse(document)


def test_parse_refuses_an_uppercase_digest() -> None:
    spec = _spec()
    document = _valid_document(spec)
    document["target_side"]["descriptor_sha256"] = document["target_side"][
        "descriptor_sha256"
    ].upper()
    with pytest.raises(SpecError, match="canonical digest"):
        TransitionReceiptV1.parse(document)


def test_parse_refuses_a_bare_hex_digest() -> None:
    spec = _spec()
    document = _valid_document(spec)
    document["target_side"]["image_digest"] = document["target_side"][
        "image_digest"
    ].split(":", 1)[1]
    with pytest.raises(SpecError, match="canonical digest"):
        TransitionReceiptV1.parse(document)


def test_parse_refuses_a_padded_digest() -> None:
    spec = _spec()
    document = _valid_document(spec)
    document["source"]["descriptor_sha256"] = (
        document["source"]["descriptor_sha256"] + " "
    )
    with pytest.raises(SpecError):
        TransitionReceiptV1.parse(document)


def test_parse_refuses_a_secret_shaped_value() -> None:
    spec = _spec()
    document = _valid_document(spec)
    document["backup"]["bundle_id"] = "AKIAIOSFODNN7EXAMPLE"
    with pytest.raises(SecretValueError):
        TransitionReceiptV1.parse(document)


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
    assert TransitionReceiptV1.parse(shuffled).digest() == receipt.digest()


# ── golden vector (AGENTS.md rule 37: a cross-repo producer needs a pin) ─────


def test_the_canonical_form_matches_a_pinned_golden_vector() -> None:
    """One fixed receipt document, pinned to its exact canonical bytes and
    digest, both as literals — not derived from this module at test time.
    Proves a future change to key order, separators or ``ensure_ascii``
    would be caught even though every OTHER test in this file only checks
    internal consistency (parse/as_mapping round trips)."""
    document = {
        "schema": TRANSITION_RECEIPT_SCHEMA,
        "product": "golden-product",
        "environment": "golden-env",
        "target": "golden-host",
        "run_id": "golden-run-1",
        "source": {
            "descriptor_sha256": "sha256:" + "1" * 64,
            "migration_heads": ["a000"],
        },
        "target_side": {
            "descriptor_sha256": "sha256:" + "2" * 64,
            "migration_heads": ["a000", "a001"],
            "image_digest": "sha256:" + "3" * 64,
            "image_source_revision": "a" * 40,
        },
        "backup": {
            "bundle_digest": "deadbeef" * 8,
            "checksum_algorithm": "sha256",
            "size_bytes": 123456,
            "bundle_id": "/backups/golden.bundle",
        },
        "previous_receipt_digest": None,
    }
    receipt = TransitionReceiptV1.parse(document)

    expected_canonical_bytes = (
        b'{"backup":{"bundle_digest":"deadbeefdeadbeefdeadbeefdeadbeefdeadbeef'
        b'deadbeefdeadbeefdeadbeef","bundle_id":"/backups/golden.bundle",'
        b'"checksum_algorithm":"sha256","size_bytes":123456},'
        b'"environment":"golden-env","previous_receipt_digest":null,'
        b'"product":"golden-product","run_id":"golden-run-1",'
        b'"schema":"DeploymentTransitionReceipt.v1",'
        b'"source":{"descriptor_sha256":'
        b'"sha256:1111111111111111111111111111111111111111111111111111111111111111",'
        b'"migration_heads":["a000"]},"target":"golden-host",'
        b'"target_side":{"descriptor_sha256":'
        b'"sha256:2222222222222222222222222222222222222222222222222222222222222222",'
        b'"image_digest":'
        b'"sha256:3333333333333333333333333333333333333333333333333333333333333333",'
        b'"image_source_revision":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",'
        b'"migration_heads":["a000","a001"]}}'
    )
    expected_digest = (
        "sha256:e82d1d23035992a1541c863724b5f45e8b45e6fc32c037101337fa54580fe11a"
    )

    assert receipt.canonical_bytes() == expected_canonical_bytes
    assert str(receipt.digest()) == expected_digest
    assert receipt.as_mapping() == document
