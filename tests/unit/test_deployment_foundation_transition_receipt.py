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

import dataclasses
import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from dotmac_deployment_foundation.backup import ArtefactClass, Assurance, BackupRecord
from dotmac_deployment_foundation.digest import Digest
from dotmac_deployment_foundation.errors import SecretValueError, SpecError
from dotmac_deployment_foundation.external_recovery import (
    EXTERNAL_BACKUP_PATH_PREFIX,
    ExternalRecoveryReceiptV1,
    backup_record_from_receipt,
)
from dotmac_deployment_foundation.recovery import RecoveryBundleManifestV1
from dotmac_deployment_foundation.recovery_identity import (
    DatasetIdentityV1,
    ExternalExecutorV1,
)
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

from tests.unit.test_deployment_foundation_recovery_bundle import (
    PRODUCT as _BUNDLE_PRODUCT,
)
from tests.unit.test_deployment_foundation_recovery_bundle import (
    _evidence as _recovery_bundle_evidence,
)
from tests.unit.test_deployment_foundation_recovery_bundle import (
    _manifest as _build_recovery_bundle_manifest,
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


def _sha512_spec() -> ProductDeploymentSpec:
    """The real descriptor with its one backup dataset's declared
    ``checksum`` changed from ``sha256`` to ``sha512`` -- built by patching
    the real text (everything else about the descriptor stays real) rather
    than fabricated from scratch, so a per-dataset algorithm mismatch can be
    tested against an actually-declared sha512 dataset."""
    text = REAL_DESCRIPTOR.replace('checksum = "sha256"', 'checksum = "sha512"')
    assert text.count('checksum = "sha512"') == 1
    return ProductDeploymentSpec.loads(text, source="<test-sha512>")


def _descriptor_digest(spec: ProductDeploymentSpec) -> str:
    return spec.to_canonical_document().sha256_digest()


#: The default SOURCE migration head -- an earlier revision than the
#: target's `spec.migration.expected_heads` ("a003"), so the default fixture
#: is a real migration (source at one head, target landing at a later one)
#: rather than a no-op hop that happens to leave the head unchanged. The
#: shared bundle-manifest fixture, `_bundle_manifest()`, declares this same
#: head by default -- see `_verify`'s default `bundle_manifest`.
_SOURCE_MIGRATION_HEAD = "a002"


def _source(spec: ProductDeploymentSpec) -> TransitionSide:
    """The default source side, at `_SOURCE_MIGRATION_HEAD` -- distinct from
    the target's `spec.migration.expected_heads`."""
    return TransitionSide(
        descriptor_sha256="sha256:" + "1" * 64,
        migration_heads=(_SOURCE_MIGRATION_HEAD,),
    )


def _target_side(
    spec: ProductDeploymentSpec, *, revision: str | None = None
) -> TargetSide:
    return TargetSide(
        descriptor_sha256=_descriptor_digest(spec),
        migration_heads=tuple(spec.migration.expected_heads),
        image_digest=spec.image_digest,
        image_source_revision=(
            revision if revision is not None else spec.source_revision
        ),
    )


#: Deliberately equal to `_backup_record().path` below: `bundle_id` binds to
#: the record's recorded artefact path (see `TransitionBackup.bundle_id`'s
#: docstring), so every positive-control fixture must agree on it.
_BACKUP_PATH = "/backups/starter.bundle"


def _bundle_manifest(
    *, migration_head: str = _SOURCE_MIGRATION_HEAD
) -> RecoveryBundleManifestV1:
    """A REAL, whole recovery-bundle manifest, from the Foundation's own
    fixture (`test_deployment_foundation_recovery_bundle.py`) rather than a
    hand-rolled document: its `product` ("dotmac_starter_mt") matches the
    real descriptor's `spec.product` (asserted below, so this coupling fails
    loudly if that fixture's product ever drifts).

    ``migration_head`` overrides that fixture's own hard-coded "a003" --
    which is the TARGET's head, not the source's -- via
    ``dataclasses.replace`` on its evidence, so a manifest can be built for
    whatever head a test's SOURCE side actually declares. The default,
    `_SOURCE_MIGRATION_HEAD`, matches `_source()`'s own default.
    """
    assert _BUNDLE_PRODUCT == "dotmac_starter_mt"
    evidence = dataclasses.replace(
        _recovery_bundle_evidence(), migration_heads=(migration_head,)
    )
    manifest = _build_recovery_bundle_manifest(evidence=evidence)
    assert manifest.migration_heads == (migration_head,)
    return manifest


def _bundle_manifest_digest_hex(*, migration_head: str = _SOURCE_MIGRATION_HEAD) -> str:
    """The manifest's OWN digest, as bare lowercase hex -- the same shape
    `TransitionBackup.bundle_digest` uses, and the value the manifest-binding
    check compares against (see `_check_backup`'s manifest section)."""
    return Digest.parse(
        _bundle_manifest(migration_head=migration_head).sha256_digest()
    ).hex


def _backup(
    *, bundle_id: str = _BACKUP_PATH, bundle_digest: str | None = None
) -> TransitionBackup:
    return TransitionBackup(
        bundle_digest=(
            bundle_digest
            if bundle_digest is not None
            else _bundle_manifest_digest_hex()
        ),
        checksum_algorithm="sha256",
        size_bytes=1_000_000,
        bundle_id=bundle_id,
    )


def _backup_record(*, checksum: str | None = None) -> BackupRecord:
    return BackupRecord(
        dataset="primary",
        path=_BACKUP_PATH,
        size_bytes=1_000_000,
        checksum=checksum if checksum is not None else _bundle_manifest_digest_hex(),
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
    observed_target_heads: Any = _UNSET,
    previous_receipt: Any = _UNSET,
    genesis_source: Any = _UNSET,
    backup_record: BackupRecord | None = None,
    bundle_manifest: Any = _UNSET,
    observed_image_digest: str | None = None,
    expected_run_id: str | None = None,
    expected_target: str | None = None,
) -> Any:
    resolved_previous: TransitionReceiptV1 | None = (
        None if previous_receipt is _UNSET else previous_receipt
    )
    resolved_genesis: TransitionSide | None
    if genesis_source is _UNSET:
        resolved_genesis = receipt.source if resolved_previous is None else None
    else:
        resolved_genesis = genesis_source
    resolved_heads: Any = (
        spec.migration.expected_heads
        if observed_target_heads is _UNSET
        else observed_target_heads
    )
    resolved_manifest: Any = (
        _bundle_manifest().to_json() if bundle_manifest is _UNSET else bundle_manifest
    )
    return verify_transition_receipt(
        receipt,
        spec=spec,
        observed_target_heads=resolved_heads,
        previous_receipt=resolved_previous,
        genesis_source=resolved_genesis,
        backup_record=backup_record if backup_record is not None else _backup_record(),
        bundle_manifest=resolved_manifest,
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
    spec: ProductDeploymentSpec, *, second_backup: TransitionBackup | None = None
) -> tuple[TransitionReceiptV1, TransitionReceiptV1]:
    """A first receipt and a second whose source is the first's target.

    Both hops stay on ONE host: a chain is per product, environment and
    target (see the module docstring), so a genuine continuation of the chain
    never changes the host. The second hop's source is therefore the
    target's head ("a003"), not the generic default source head
    (`_SOURCE_MIGRATION_HEAD`, "a002") -- most callers don't care (they only
    assert a specific finding, not a fully clean verdict) and get the
    generic default `_backup()`; a caller that needs the second receipt's
    own backup to be bound cleanly passes `second_backup` explicitly.
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
        backup=second_backup if second_backup is not None else _backup(),
        previous_receipt_digest=str(first.digest()),
    )
    return first, second


# ── the negative control ─────────────────────────────────────────────────────


def test_a_fully_valid_chain_of_two_receipts_verifies() -> None:
    """A real two-hop migration: the first receipt's source is at
    `_SOURCE_MIGRATION_HEAD` ("a002") and lands at the target's
    `spec.migration.expected_heads` ("a003"); the second receipt's source is
    that same "a003" -- its own backup must therefore be bound to a manifest
    at "a003", not the generic "a002" default."""
    spec = _spec()
    second_head = spec.migration.expected_heads[0]
    second_manifest = _bundle_manifest(migration_head=second_head)
    second_backup = _backup(
        bundle_digest=Digest.parse(second_manifest.sha256_digest()).hex
    )
    first, second = _chained_second_receipt(spec, second_backup=second_backup)

    first_verdict = _verify(spec, first, previous_receipt=None)
    assert first_verdict.outcome is TransitionOutcome.VERIFIED
    assert first_verdict.findings == ()

    second_verdict = _verify(
        spec,
        second,
        previous_receipt=first,
        bundle_manifest=second_manifest.to_json(),
    )
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


def test_chain_source_mismatch_still_reports_when_previous_digest_is_missing() -> None:
    """A later check that does not depend on the missing digest keeps
    running instead of an early return suppressing it."""
    spec = _spec()
    first, _ = _chained_second_receipt(spec)
    missing_and_wrong_source = _receipt(
        spec,
        run_id="run-2",
        target=first.target,
        source=TransitionSide(
            descriptor_sha256="sha256:" + "7" * 64,
            migration_heads=("a000",),
        ),
        previous_receipt_digest=None,
    )
    verdict = _verify(spec, missing_and_wrong_source, previous_receipt=first)
    assert TransitionFinding.CHAIN_PREVIOUS_MISSING in verdict.findings
    assert TransitionFinding.CHAIN_SOURCE_MISMATCH in verdict.findings


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


def test_a_chain_hop_with_a_different_product_is_refused() -> None:
    """Chain scope is product AND environment AND target -- not just target."""
    spec = _spec()
    first, second = _chained_second_receipt(spec)
    wrong_product = TransitionReceiptV1(
        product="a-different-product",
        environment=first.environment,
        target=first.target,
        run_id="run-2",
        source=TransitionSide(
            descriptor_sha256=first.target_side.descriptor_sha256,
            migration_heads=first.target_side.migration_heads,
        ),
        target_side=_target_side(spec),
        backup=_backup(),
        previous_receipt_digest=str(first.digest()),
    )
    verdict = _verify(spec, wrong_product, previous_receipt=first)
    assert TransitionFinding.CHAIN_SCOPE_MISMATCH in verdict.findings

    verdict_ok = _verify(spec, second, previous_receipt=first)
    assert TransitionFinding.CHAIN_SCOPE_MISMATCH not in verdict_ok.findings


def test_a_chain_hop_with_a_different_environment_is_refused() -> None:
    spec = _spec()
    first, second = _chained_second_receipt(spec)
    wrong_environment = TransitionReceiptV1(
        product=first.product,
        environment="a-different-environment",
        target=first.target,
        run_id="run-2",
        source=TransitionSide(
            descriptor_sha256=first.target_side.descriptor_sha256,
            migration_heads=first.target_side.migration_heads,
        ),
        target_side=_target_side(spec),
        backup=_backup(),
        previous_receipt_digest=str(first.digest()),
    )
    verdict = _verify(spec, wrong_environment, previous_receipt=first)
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
            image_source_revision=spec.source_revision,
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
            image_source_revision=spec.source_revision,
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
            image_source_revision=spec.source_revision,
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

    _, correct_second = _chained_second_receipt(spec)
    verdict_ok = _verify(spec, correct_second, previous_receipt=first)
    assert TransitionFinding.CHAIN_SOURCE_MISMATCH not in verdict_ok.findings


def test_none_observed_heads_is_a_finding_not_a_coercion() -> None:
    """The 'never coerces' claim: `None` is not silently `str()`-ed."""
    spec = _spec()
    receipt = _receipt(spec)
    bad_heads: Any = None
    verdict = _verify(spec, receipt, observed_target_heads=bad_heads)
    assert TransitionFinding.INPUT_NOT_CANONICALIZABLE in verdict.findings

    verdict_ok = _verify(spec, receipt)
    assert TransitionFinding.INPUT_NOT_CANONICALIZABLE not in verdict_ok.findings


def test_a_bare_string_of_observed_heads_is_a_finding_not_a_coercion() -> None:
    """A bare string is iterable character-by-character -- exactly the gotcha
    this must refuse rather than silently walk."""
    spec = _spec()
    receipt = _receipt(spec)
    bad_heads: Any = "a003"
    verdict = _verify(spec, receipt, observed_target_heads=bad_heads)
    assert TransitionFinding.INPUT_NOT_CANONICALIZABLE in verdict.findings

    verdict_ok = _verify(spec, receipt)
    assert TransitionFinding.INPUT_NOT_CANONICALIZABLE not in verdict_ok.findings


def test_a_non_string_observed_head_element_is_a_finding_not_a_coercion() -> None:
    spec = _spec()
    receipt = _receipt(spec)
    bad_heads: Any = [123]
    verdict = _verify(spec, receipt, observed_target_heads=bad_heads)
    assert TransitionFinding.INPUT_NOT_CANONICALIZABLE in verdict.findings

    verdict_ok = _verify(spec, receipt)
    assert TransitionFinding.INPUT_NOT_CANONICALIZABLE not in verdict_ok.findings


def test_an_empty_observed_head_is_a_finding_not_a_coercion() -> None:
    """Held to the same standard as a DECLARED head (`_required`): empty is
    refused, not treated as a distinct value."""
    spec = _spec()
    receipt = _receipt(spec)
    bad_heads: Any = [*spec.migration.expected_heads, ""]
    verdict = _verify(spec, receipt, observed_target_heads=bad_heads)
    assert TransitionFinding.INPUT_NOT_CANONICALIZABLE in verdict.findings

    verdict_ok = _verify(spec, receipt)
    assert TransitionFinding.INPUT_NOT_CANONICALIZABLE not in verdict_ok.findings


def test_a_padded_observed_head_is_a_finding_not_a_coercion() -> None:
    spec = _spec()
    receipt = _receipt(spec)
    bad_heads: Any = [" " + spec.migration.expected_heads[0]]
    verdict = _verify(spec, receipt, observed_target_heads=bad_heads)
    assert TransitionFinding.INPUT_NOT_CANONICALIZABLE in verdict.findings

    verdict_ok = _verify(spec, receipt)
    assert TransitionFinding.INPUT_NOT_CANONICALIZABLE not in verdict_ok.findings


def test_declared_vs_spec_still_reports_when_observed_heads_are_malformed() -> None:
    """A check that does not need `observed_target_heads` at all keeps
    running instead of an early return suppressing it."""
    spec = _spec()
    receipt = _receipt(
        spec,
        target_side=TargetSide(
            descriptor_sha256=_descriptor_digest(spec),
            migration_heads=(),  # disagrees with spec.migration.expected_heads
            image_digest=spec.image_digest,
            image_source_revision=spec.source_revision,
        ),
    )
    bad_heads: Any = None
    verdict = _verify(spec, receipt, observed_target_heads=bad_heads)
    assert TransitionFinding.TARGET_HEADS_DECLARED_VS_SPEC in verdict.findings
    assert TransitionFinding.INPUT_NOT_CANONICALIZABLE in verdict.findings


# ── descriptor / image / product findings ───────────────────────────────────


def test_a_descriptor_mismatch_is_refused() -> None:
    spec = _spec()
    receipt = _receipt(
        spec,
        target_side=TargetSide(
            descriptor_sha256="sha256:" + "3" * 64,
            migration_heads=tuple(spec.migration.expected_heads),
            image_digest=spec.image_digest,
            image_source_revision=spec.source_revision,
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
            image_source_revision=spec.source_revision,
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


def test_a_bare_hex_observed_image_digest_is_malformed_not_normalized() -> None:
    """`observed_image_digest` is held to the same canonical-only rule as
    `parse()` -- a bare-hex spelling is refused, not silently prefixed."""
    spec = _spec()
    receipt = _receipt(spec)
    bare = spec.image_digest.split(":", 1)[1]
    verdict = _verify(spec, receipt, observed_image_digest=bare)
    assert TransitionFinding.OBSERVED_IMAGE_MALFORMED in verdict.findings
    assert TransitionFinding.IMAGE_DIGEST_MISMATCH not in verdict.findings

    verdict_ok = _verify(spec, receipt)
    assert TransitionFinding.OBSERVED_IMAGE_MALFORMED not in verdict_ok.findings


def test_an_uppercase_observed_image_digest_is_malformed_not_normalized() -> None:
    spec = _spec()
    receipt = _receipt(spec)
    upper = spec.image_digest.upper()
    verdict = _verify(spec, receipt, observed_image_digest=upper)
    assert TransitionFinding.OBSERVED_IMAGE_MALFORMED in verdict.findings
    assert TransitionFinding.IMAGE_DIGEST_MISMATCH not in verdict.findings

    verdict_ok = _verify(spec, receipt)
    assert TransitionFinding.OBSERVED_IMAGE_MALFORMED not in verdict_ok.findings


def test_a_bad_revision_is_refused() -> None:
    spec = _spec()
    receipt = _receipt(spec, target_side=_target_side(spec, revision="not-a-git-sha"))
    verdict = _verify(spec, receipt)
    assert TransitionFinding.IMAGE_REVISION_INVALID in verdict.findings

    verdict_ok = _verify(spec, _receipt(spec))
    assert TransitionFinding.IMAGE_REVISION_INVALID not in verdict_ok.findings


def test_a_revision_not_matching_the_descriptor_is_refused() -> None:
    """A well-formed 40-hex revision that simply isn't the one the descriptor
    names -- distinct from `IMAGE_REVISION_INVALID`, which is about shape."""
    spec = _spec()
    other_revision = "b" * 40
    assert other_revision != spec.source_revision
    receipt = _receipt(spec, target_side=_target_side(spec, revision=other_revision))
    verdict = _verify(spec, receipt)
    assert TransitionFinding.IMAGE_REVISION_DESCRIPTOR_MISMATCH in verdict.findings
    assert TransitionFinding.IMAGE_REVISION_INVALID not in verdict.findings

    verdict_ok = _verify(spec, _receipt(spec))
    assert (
        TransitionFinding.IMAGE_REVISION_DESCRIPTOR_MISMATCH not in verdict_ok.findings
    )


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
        dataset="primary",
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


def _record_at(assurance: Assurance) -> BackupRecord:
    return BackupRecord(
        dataset="primary",
        path=_BACKUP_PATH,
        size_bytes=1_000_000,
        checksum=_bundle_manifest_digest_hex(),
        checksum_algorithm="sha256",
        completed_at_epoch=1_700_000_000,
        assurance=assurance,
        artefact_class=ArtefactClass.RECOVERY_BUNDLE,
    )


def test_an_intact_bundle_at_verified_with_a_bound_manifest_verifies_clean() -> None:
    """Michael's 2026-09-28 correction of the prior RESTORABLE ruling: the
    floor is VERIFIED, not RESTORABLE. Completeness comes from the manifest
    BINDING (item 2), not from a higher assurance level -- a disposable
    restore (RESTORABLE and above) is a separate, stronger proof this
    receipt does not claim. Fully clean positive control for that ruling: a
    RECOVERY_BUNDLE record at exactly VERIFIED, bound to a real, whole
    manifest, verifies with zero findings."""
    spec = _spec()
    receipt = _receipt(spec)
    verdict = _verify(spec, receipt, backup_record=_record_at(Assurance.VERIFIED))
    assert verdict.outcome is TransitionOutcome.VERIFIED
    assert verdict.findings == ()


def test_backup_assurance_below_verified_is_refused() -> None:
    spec = _spec()
    receipt = _receipt(spec)
    verdict = _verify(spec, receipt, backup_record=_record_at(Assurance.COMPLETED))
    assert TransitionFinding.BACKUP_ASSURANCE_TOO_LOW in verdict.findings

    verdict_ok = _verify(spec, receipt, backup_record=_record_at(Assurance.VERIFIED))
    assert TransitionFinding.BACKUP_ASSURANCE_TOO_LOW not in verdict_ok.findings


def test_a_manifest_missing_a_required_component_is_not_a_bundle() -> None:
    spec = _spec()
    receipt = _receipt(spec)
    document = json.loads(_bundle_manifest().to_json())
    first_component = next(iter(document["components"]))
    del document["components"][first_component]
    verdict = _verify(spec, receipt, bundle_manifest=json.dumps(document))
    assert TransitionFinding.BACKUP_MANIFEST_NOT_A_BUNDLE in verdict.findings

    verdict_ok = _verify(spec, receipt)
    assert TransitionFinding.BACKUP_MANIFEST_NOT_A_BUNDLE not in verdict_ok.findings


def test_a_non_manifest_payload_is_not_a_bundle() -> None:
    """A `pg_dump` custom-format archive is not a manifest -- `load_manifest`
    refuses it on shape rather than on how a restore later looks."""
    spec = _spec()
    receipt = _receipt(spec)
    verdict = _verify(spec, receipt, bundle_manifest=b"PGDMP-not-json-at-all")
    assert TransitionFinding.BACKUP_MANIFEST_NOT_A_BUNDLE in verdict.findings

    verdict_ok = _verify(spec, receipt)
    assert TransitionFinding.BACKUP_MANIFEST_NOT_A_BUNDLE not in verdict_ok.findings


def test_a_non_str_bundle_manifest_is_a_finding_not_a_coercion() -> None:
    spec = _spec()
    receipt = _receipt(spec)
    bad_manifest: Any = 12345
    verdict = _verify(spec, receipt, bundle_manifest=bad_manifest)
    assert TransitionFinding.INPUT_NOT_CANONICALIZABLE in verdict.findings

    verdict_ok = _verify(spec, receipt)
    assert TransitionFinding.INPUT_NOT_CANONICALIZABLE not in verdict_ok.findings


# ── never-raises on the manifest path (each shape a finding, never a crash) ──


def test_an_int_migration_heads_is_not_a_bundle() -> None:
    spec = _spec()
    receipt = _receipt(spec)
    document = json.loads(_bundle_manifest().to_json())
    document["migration_heads"] = 5
    verdict = _verify(spec, receipt, bundle_manifest=json.dumps(document))
    assert TransitionFinding.BACKUP_MANIFEST_NOT_A_BUNDLE in verdict.findings

    verdict_ok = _verify(spec, receipt)
    assert TransitionFinding.BACKUP_MANIFEST_NOT_A_BUNDLE not in verdict_ok.findings


def test_a_null_migration_heads_is_not_a_bundle() -> None:
    spec = _spec()
    receipt = _receipt(spec)
    document = json.loads(_bundle_manifest().to_json())
    document["migration_heads"] = None
    verdict = _verify(spec, receipt, bundle_manifest=json.dumps(document))
    assert TransitionFinding.BACKUP_MANIFEST_NOT_A_BUNDLE in verdict.findings

    verdict_ok = _verify(spec, receipt)
    assert TransitionFinding.BACKUP_MANIFEST_NOT_A_BUNDLE not in verdict_ok.findings


def test_an_object_migration_heads_is_not_a_bundle() -> None:
    """A dict is iterable (its keys), so this would NOT raise if the code
    merely iterated it instead of checking its shape -- exactly the silent
    wrong-shape acceptance the explicit `isinstance(..., list)` check exists
    to refuse."""
    spec = _spec()
    receipt = _receipt(spec)
    document = json.loads(_bundle_manifest().to_json())
    document["migration_heads"] = {"a003": 1}
    verdict = _verify(spec, receipt, bundle_manifest=json.dumps(document))
    assert TransitionFinding.BACKUP_MANIFEST_NOT_A_BUNDLE in verdict.findings

    verdict_ok = _verify(spec, receipt)
    assert TransitionFinding.BACKUP_MANIFEST_NOT_A_BUNDLE not in verdict_ok.findings


def test_a_lone_surrogate_product_is_not_a_bundle() -> None:
    """A lone surrogate is a valid Python `str` (passes the `isinstance`
    check) but cannot be UTF-8 encoded -- `manifest.sha256_digest()` raises
    `UnicodeEncodeError` re-encoding it, which the manifest section must
    catch rather than propagate."""
    spec = _spec()
    receipt = _receipt(spec)
    document = json.loads(_bundle_manifest().to_json())
    document["product"] = "PRODUCT_PLACEHOLDER"
    raw = json.dumps(document).replace('"PRODUCT_PLACEHOLDER"', '"\\ud800"')
    verdict = _verify(spec, receipt, bundle_manifest=raw)
    assert TransitionFinding.BACKUP_MANIFEST_NOT_A_BUNDLE in verdict.findings

    verdict_ok = _verify(spec, receipt)
    assert TransitionFinding.BACKUP_MANIFEST_NOT_A_BUNDLE not in verdict_ok.findings


def test_a_deeply_nested_payload_is_not_a_bundle() -> None:
    """A pathologically nested payload can raise `RecursionError` out of the
    JSON parser itself, before `load_manifest` ever gets to its own
    `SpecError` refusals -- this must be caught too."""
    spec = _spec()
    receipt = _receipt(spec)
    verdict = _verify(spec, receipt, bundle_manifest="[" * 100_000)
    assert TransitionFinding.BACKUP_MANIFEST_NOT_A_BUNDLE in verdict.findings

    verdict_ok = _verify(spec, receipt)
    assert TransitionFinding.BACKUP_MANIFEST_NOT_A_BUNDLE not in verdict_ok.findings


def test_a_manifest_digest_mismatch_is_refused() -> None:
    spec = _spec()
    receipt = _receipt(spec, backup=_backup(bundle_digest="0" * 64))
    verdict = _verify(spec, receipt)
    assert TransitionFinding.BACKUP_MANIFEST_DIGEST_MISMATCH in verdict.findings

    verdict_ok = _verify(spec, _receipt(spec))
    assert TransitionFinding.BACKUP_MANIFEST_DIGEST_MISMATCH not in verdict_ok.findings


def test_a_manifest_product_mismatch_is_refused() -> None:
    """The bundle's identity is its manifest digest (`bundle_digest` is set
    to match the WRONG-product manifest exactly), so only the scope check --
    not a digest mismatch -- is what catches this."""
    spec = _spec()
    document = json.loads(_bundle_manifest().to_json())
    document["product"] = "a-different-product"
    wrong_manifest = RecoveryBundleManifestV1(content=document)
    receipt = _receipt(
        spec,
        backup=_backup(bundle_digest=Digest.parse(wrong_manifest.sha256_digest()).hex),
    )
    verdict = _verify(spec, receipt, bundle_manifest=wrong_manifest.to_json())
    assert TransitionFinding.BACKUP_MANIFEST_SCOPE_MISMATCH in verdict.findings

    verdict_ok = _verify(spec, _receipt(spec))
    assert TransitionFinding.BACKUP_MANIFEST_SCOPE_MISMATCH not in verdict_ok.findings


def test_a_manifest_heads_mismatch_is_refused() -> None:
    """The backup is of the SOURCE database before migration -- so this
    compares against `receipt.source.migration_heads`, not the target's."""
    spec = _spec()
    document = json.loads(_bundle_manifest().to_json())
    document["migration_heads"] = ["zzzz"]
    wrong_manifest = RecoveryBundleManifestV1(content=document)
    receipt = _receipt(
        spec,
        backup=_backup(bundle_digest=Digest.parse(wrong_manifest.sha256_digest()).hex),
    )
    verdict = _verify(spec, receipt, bundle_manifest=wrong_manifest.to_json())
    assert TransitionFinding.BACKUP_MANIFEST_SCOPE_MISMATCH in verdict.findings

    verdict_ok = _verify(spec, _receipt(spec))
    assert TransitionFinding.BACKUP_MANIFEST_SCOPE_MISMATCH not in verdict_ok.findings


def test_a_manifest_bound_to_the_target_heads_instead_of_source_is_refused() -> None:
    """Survivor-killer distinct from the "zzzz" test above: a manifest whose
    head is a REAL head in this transition -- just the TARGET's, not the
    SOURCE's -- must still be refused. Accepting it would describe a bundle
    already migrated, not the pre-migration backup this receipt claims."""
    spec = _spec()
    target_head = spec.migration.expected_heads[0]
    assert target_head != _SOURCE_MIGRATION_HEAD
    wrong_manifest = _bundle_manifest(migration_head=target_head)
    receipt = _receipt(
        spec,
        backup=_backup(bundle_digest=Digest.parse(wrong_manifest.sha256_digest()).hex),
    )
    verdict = _verify(spec, receipt, bundle_manifest=wrong_manifest.to_json())
    assert TransitionFinding.BACKUP_MANIFEST_SCOPE_MISMATCH in verdict.findings

    verdict_ok = _verify(spec, _receipt(spec))
    assert TransitionFinding.BACKUP_MANIFEST_SCOPE_MISMATCH not in verdict_ok.findings


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
        dataset="primary",
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
        dataset="primary",
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
        dataset="primary",
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


def test_a_non_int_backup_record_size_is_a_finding_not_a_coercion() -> None:
    """The 'never raises'/'never coerces' claim: a float `size_bytes` is a
    finding, not silently truncated by `int()`."""
    spec = _spec()
    receipt = _receipt(spec)
    bad_size: Any = 1_000_000.5
    record = BackupRecord(
        dataset="primary",
        path=_BACKUP_PATH,
        size_bytes=bad_size,
        checksum="deadbeef" * 8,
        checksum_algorithm="sha256",
        completed_at_epoch=1_700_000_000,
        assurance=Assurance.PROVED,
        artefact_class=ArtefactClass.RECOVERY_BUNDLE,
    )
    verdict = _verify(spec, receipt, backup_record=record)
    assert TransitionFinding.INPUT_NOT_CANONICALIZABLE in verdict.findings
    assert TransitionFinding.BACKUP_SIZE_MISMATCH not in verdict.findings

    verdict_ok = _verify(spec, receipt)
    assert TransitionFinding.INPUT_NOT_CANONICALIZABLE not in verdict_ok.findings


def test_a_bool_backup_record_size_is_a_finding_not_a_coercion() -> None:
    spec = _spec()
    receipt = _receipt(spec)
    bad_size: Any = True
    record = BackupRecord(
        dataset="primary",
        path=_BACKUP_PATH,
        size_bytes=bad_size,
        checksum="deadbeef" * 8,
        checksum_algorithm="sha256",
        completed_at_epoch=1_700_000_000,
        assurance=Assurance.PROVED,
        artefact_class=ArtefactClass.RECOVERY_BUNDLE,
    )
    verdict = _verify(spec, receipt, backup_record=record)
    assert TransitionFinding.INPUT_NOT_CANONICALIZABLE in verdict.findings

    verdict_ok = _verify(spec, receipt)
    assert TransitionFinding.INPUT_NOT_CANONICALIZABLE not in verdict_ok.findings


def test_an_unsupported_checksum_algorithm_is_refused() -> None:
    spec = _spec()
    receipt = _receipt(
        spec,
        backup=TransitionBackup(
            bundle_digest="deadbeef" * 8,
            checksum_algorithm="md5",
            size_bytes=1_000_000,
            bundle_id=_BACKUP_PATH,
        ),
    )
    record = BackupRecord(
        dataset="primary",
        path=_BACKUP_PATH,
        size_bytes=1_000_000,
        checksum="deadbeef" * 8,
        checksum_algorithm="md5",
        completed_at_epoch=1_700_000_000,
        assurance=Assurance.PROVED,
        artefact_class=ArtefactClass.RECOVERY_BUNDLE,
    )
    verdict = _verify(spec, receipt, backup_record=record)
    assert TransitionFinding.BACKUP_ALGORITHM_UNSUPPORTED in verdict.findings

    # near miss: sha512 is allowed (mirrors spec.BackupDataset.CHECKSUMS)
    sha512_receipt = _receipt(
        spec,
        backup=TransitionBackup(
            bundle_digest="c" * 128,
            checksum_algorithm="sha512",
            size_bytes=1_000_000,
            bundle_id=_BACKUP_PATH,
        ),
    )
    sha512_record = BackupRecord(
        dataset="primary",
        path=_BACKUP_PATH,
        size_bytes=1_000_000,
        checksum="c" * 128,
        checksum_algorithm="sha512",
        completed_at_epoch=1_700_000_000,
        assurance=Assurance.PROVED,
        artefact_class=ArtefactClass.RECOVERY_BUNDLE,
    )
    verdict_ok = _verify(spec, sha512_receipt, backup_record=sha512_record)
    assert TransitionFinding.BACKUP_ALGORITHM_UNSUPPORTED not in verdict_ok.findings


def test_an_undeclared_dataset_is_refused() -> None:
    spec = _spec()
    receipt = _receipt(spec)
    record = BackupRecord(
        dataset="not-a-declared-dataset",
        path=_BACKUP_PATH,
        size_bytes=1_000_000,
        checksum="deadbeef" * 8,
        checksum_algorithm="sha256",
        completed_at_epoch=1_700_000_000,
        assurance=Assurance.PROVED,
        artefact_class=ArtefactClass.RECOVERY_BUNDLE,
    )
    verdict = _verify(spec, receipt, backup_record=record)
    assert TransitionFinding.BACKUP_DATASET_NOT_DECLARED in verdict.findings

    # near miss: "primary" is the real descriptor's declared dataset
    verdict_ok = _verify(spec, receipt)
    assert TransitionFinding.BACKUP_DATASET_NOT_DECLARED not in verdict_ok.findings


def test_a_declared_dataset_algorithm_mismatch_is_refused() -> None:
    """Survivor-killer for the global allowlist: sha256 is itself an ALLOWED
    algorithm, so only a per-dataset comparison catches it disagreeing with
    what THIS dataset actually declares."""
    sha512_spec = _sha512_spec()
    wrong_receipt = _receipt(
        sha512_spec,
        backup=TransitionBackup(
            bundle_digest="deadbeef" * 8,
            checksum_algorithm="sha256",  # the dataset declares sha512
            size_bytes=1_000_000,
            bundle_id=_BACKUP_PATH,
        ),
    )
    wrong_record = BackupRecord(
        dataset="primary",
        path=_BACKUP_PATH,
        size_bytes=1_000_000,
        checksum="deadbeef" * 8,
        checksum_algorithm="sha256",
        completed_at_epoch=1_700_000_000,
        assurance=Assurance.PROVED,
        artefact_class=ArtefactClass.RECOVERY_BUNDLE,
    )
    verdict = _verify(sha512_spec, wrong_receipt, backup_record=wrong_record)
    assert TransitionFinding.BACKUP_ALGORITHM_NOT_DECLARED in verdict.findings

    # near miss: sha512, matching what this dataset actually declares
    matching_receipt = _receipt(
        sha512_spec,
        backup=TransitionBackup(
            bundle_digest="c" * 128,
            checksum_algorithm="sha512",
            size_bytes=1_000_000,
            bundle_id=_BACKUP_PATH,
        ),
    )
    matching_record = BackupRecord(
        dataset="primary",
        path=_BACKUP_PATH,
        size_bytes=1_000_000,
        checksum="c" * 128,
        checksum_algorithm="sha512",
        completed_at_epoch=1_700_000_000,
        assurance=Assurance.PROVED,
        artefact_class=ArtefactClass.RECOVERY_BUNDLE,
    )
    verdict_ok = _verify(sha512_spec, matching_receipt, backup_record=matching_record)
    assert TransitionFinding.BACKUP_ALGORITHM_NOT_DECLARED not in verdict_ok.findings


def test_an_uppercase_bundle_digest_is_malformed() -> None:
    """Existing producers spell a checksum as bare LOWERCASE hex (see
    `external_recovery.py`, `backup.py`'s own tests) -- uppercase is refused,
    not normalized."""
    spec = _spec()
    receipt = _receipt(
        spec,
        backup=TransitionBackup(
            bundle_digest="DEADBEEF" * 8,
            checksum_algorithm="sha256",
            size_bytes=1_000_000,
            bundle_id=_BACKUP_PATH,
        ),
    )
    record = BackupRecord(
        dataset="primary",
        path=_BACKUP_PATH,
        size_bytes=1_000_000,
        checksum="DEADBEEF" * 8,
        checksum_algorithm="sha256",
        completed_at_epoch=1_700_000_000,
        assurance=Assurance.PROVED,
        artefact_class=ArtefactClass.RECOVERY_BUNDLE,
    )
    verdict = _verify(spec, receipt, backup_record=record)
    assert TransitionFinding.BACKUP_DIGEST_MALFORMED in verdict.findings

    verdict_ok = _verify(spec, _receipt(spec))
    assert TransitionFinding.BACKUP_DIGEST_MALFORMED not in verdict_ok.findings


def test_a_wrong_length_bundle_digest_is_malformed() -> None:
    """Survivor-killer: correct algorithm, correct alphabet, wrong length."""
    spec = _spec()
    receipt = _receipt(
        spec,
        backup=TransitionBackup(
            bundle_digest="deadbeef" * 4,  # 32 hex chars, sha256 needs 64
            checksum_algorithm="sha256",
            size_bytes=1_000_000,
            bundle_id=_BACKUP_PATH,
        ),
    )
    record = BackupRecord(
        dataset="primary",
        path=_BACKUP_PATH,
        size_bytes=1_000_000,
        checksum="deadbeef" * 4,
        checksum_algorithm="sha256",
        completed_at_epoch=1_700_000_000,
        assurance=Assurance.PROVED,
        artefact_class=ArtefactClass.RECOVERY_BUNDLE,
    )
    verdict = _verify(spec, receipt, backup_record=record)
    assert TransitionFinding.BACKUP_DIGEST_MALFORMED in verdict.findings

    verdict_ok = _verify(spec, _receipt(spec))
    assert TransitionFinding.BACKUP_DIGEST_MALFORMED not in verdict_ok.findings


def test_a_record_built_by_backup_record_from_receipt_is_refused() -> None:
    """Exactly the shape `engine/run.py` builds: `backup_record_from_receipt`
    called with `path=f"{EXTERNAL_BACKUP_PATH_PREFIX}{executor.identifier}"`
    and `size_bytes=max(1, restore_duration_seconds)` -- an executor
    identifier and a restore duration, not a real artefact id and size."""
    spec = _spec()
    external_receipt = ExternalRecoveryReceiptV1(
        identity=DatasetIdentityV1(
            product=spec.product, dataset="primary", lineage="lineage-1"
        ),
        descriptor_digest=_descriptor_digest(spec),
        snapshot_checksum="deadbeef" * 8,
        snapshot_checksum_algorithm="sha256",
        executor=ExternalExecutorV1(
            kind="backup_platform",
            identifier="some-executor",
            version="1.0.0",
            key_id="unattributed-key-id",
        ),
        verifications=("schema",),
        isolated_target=True,
        proved_at_epoch=1_700_000_000,
        restore_duration_seconds=42,
    )
    record = backup_record_from_receipt(
        external_receipt,
        path=f"{EXTERNAL_BACKUP_PATH_PREFIX}{external_receipt.executor.identifier}",
        size_bytes=max(1, external_receipt.restore_duration_seconds),
    )
    receipt = _receipt(
        spec,
        backup=TransitionBackup(
            bundle_digest=record.checksum,
            checksum_algorithm=record.checksum_algorithm,
            size_bytes=record.size_bytes,
            bundle_id=record.path,
        ),
    )
    verdict = _verify(spec, receipt, backup_record=record)
    assert TransitionFinding.BACKUP_RECORD_NOT_ARTEFACT_BOUND in verdict.findings

    # near miss: a real, locally written artefact path
    verdict_ok = _verify(spec, _receipt(spec))
    assert TransitionFinding.BACKUP_RECORD_NOT_ARTEFACT_BOUND not in verdict_ok.findings


# ── self-canonicalization / never-raises on BackupRecord shape ─────────────


def test_a_directly_constructed_receipt_with_a_secret_shaped_field_is_refused() -> None:
    """`TransitionReceiptV1.parse` scans for secrets; a receipt built
    directly via the constructor never does. `bundle_id` is chosen equal to
    the record's `path` so `BACKUP_ID_MISMATCH` would NOT fire -- only the
    verifier's own self-canonicalization attempt catches this."""
    spec = _spec()
    secret_shaped = "AKIAIOSFODNN7EXAMPLE"
    receipt = _receipt(
        spec,
        backup=TransitionBackup(
            bundle_digest="deadbeef" * 8,
            checksum_algorithm="sha256",
            size_bytes=1_000_000,
            bundle_id=secret_shaped,
        ),
    )
    record = BackupRecord(
        dataset="primary",
        path=secret_shaped,
        size_bytes=1_000_000,
        checksum="deadbeef" * 8,
        checksum_algorithm="sha256",
        completed_at_epoch=1_700_000_000,
        assurance=Assurance.PROVED,
        artefact_class=ArtefactClass.RECOVERY_BUNDLE,
    )
    verdict = _verify(spec, receipt, backup_record=record)
    assert TransitionFinding.BACKUP_ID_MISMATCH not in verdict.findings
    assert TransitionFinding.INPUT_NOT_CANONICALIZABLE in verdict.findings

    verdict_ok = _verify(spec, _receipt(spec))
    assert TransitionFinding.INPUT_NOT_CANONICALIZABLE not in verdict_ok.findings


def test_a_none_backup_record_path_is_a_finding_not_a_crash() -> None:
    spec = _spec()
    receipt = _receipt(spec)
    bad_path: Any = None
    record = BackupRecord(
        dataset="primary",
        path=bad_path,
        size_bytes=1_000_000,
        checksum="deadbeef" * 8,
        checksum_algorithm="sha256",
        completed_at_epoch=1_700_000_000,
        assurance=Assurance.PROVED,
        artefact_class=ArtefactClass.RECOVERY_BUNDLE,
    )
    verdict = _verify(spec, receipt, backup_record=record)
    assert TransitionFinding.INPUT_NOT_CANONICALIZABLE in verdict.findings
    assert TransitionFinding.BACKUP_ID_MISMATCH not in verdict.findings
    assert TransitionFinding.BACKUP_RECORD_NOT_ARTEFACT_BOUND not in verdict.findings

    verdict_ok = _verify(spec, receipt)
    assert TransitionFinding.INPUT_NOT_CANONICALIZABLE not in verdict_ok.findings


def test_a_string_assurance_is_a_finding_not_a_crash() -> None:
    """`.rank` access on a non-`Assurance` value would raise -- this is the
    'never raises' guarantee made true for `assurance`."""
    spec = _spec()
    receipt = _receipt(spec)
    bad_assurance: Any = "proved"
    record = BackupRecord(
        dataset="primary",
        path=_BACKUP_PATH,
        size_bytes=1_000_000,
        checksum="deadbeef" * 8,
        checksum_algorithm="sha256",
        completed_at_epoch=1_700_000_000,
        assurance=bad_assurance,
        artefact_class=ArtefactClass.RECOVERY_BUNDLE,
    )
    verdict = _verify(spec, receipt, backup_record=record)
    assert TransitionFinding.INPUT_NOT_CANONICALIZABLE in verdict.findings
    assert TransitionFinding.BACKUP_ASSURANCE_TOO_LOW not in verdict.findings

    verdict_ok = _verify(spec, receipt)
    assert TransitionFinding.INPUT_NOT_CANONICALIZABLE not in verdict_ok.findings


# ── constructor guards ───────────────────────────────────────────────────────


def test_migration_heads_refuses_a_bare_string() -> None:
    bad_heads: Any = "a000"
    with pytest.raises(SpecError, match="bare"):
        TransitionSide(
            descriptor_sha256="sha256:" + "1" * 64, migration_heads=bad_heads
        )


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


def test_parse_refuses_a_padded_head() -> None:
    spec = _spec()
    document = _valid_document(spec)
    document["source"]["migration_heads"] = ["a000 "]
    with pytest.raises(SpecError, match="whitespace"):
        TransitionReceiptV1.parse(document)


def test_parse_refuses_an_empty_head() -> None:
    spec = _spec()
    document = _valid_document(spec)
    document["source"]["migration_heads"] = [""]
    with pytest.raises(SpecError, match="empty"):
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


def test_a_second_golden_vector_pins_non_ascii_and_a_chained_digest() -> None:
    """The first golden vector's `target`/`run_id`/`previous_receipt_digest`
    are all plain ASCII and null, so it cannot tell an `ensure_ascii=True`
    canonicalization apart from this module's actual `ensure_ascii=False`
    (both would produce identical bytes for pure-ASCII, null-digest input).
    This vector adds a non-ASCII character in a free-form field (``target``)
    and a non-null ``previous_receipt_digest``, so a future accidental flip
    of ``ensure_ascii`` (`\\u00f4` instead of the raw UTF-8 bytes) or a
    dropped/renamed ``previous_receipt_digest`` key would change the digest
    and be caught here.

    ``expected_canonical_bytes``/``expected_digest`` were derived OUTSIDE
    this test and outside `transition_receipt.py`: the canonical JSON string
    below was typed by hand (not produced by `canonical_bytes()`), written to
    a file, and hashed with both ``shasum -a 256`` and, independently,
    ``openssl dgst -sha256`` on the command line -- not with this module's
    own `hashlib`-based `Digest.of`. Both external tools agreed on
    ``83f2c0790494b1f90978c19dcf537c102d1b5a42d7ac632487d184b6274d04e5``.
    """
    document = {
        "schema": TRANSITION_RECEIPT_SCHEMA,
        "product": "golden-product-2",
        "environment": "golden-env-2",
        "target": "golden-hôte",
        "run_id": "golden-run-2",
        "source": {
            "descriptor_sha256": "sha256:" + "4" * 64,
            "migration_heads": ["a000"],
        },
        "target_side": {
            "descriptor_sha256": "sha256:" + "5" * 64,
            "migration_heads": ["a000", "a001"],
            "image_digest": "sha256:" + "6" * 64,
            "image_source_revision": "b" * 40,
        },
        "backup": {
            "bundle_digest": "deadbeef" * 8,
            "checksum_algorithm": "sha256",
            "size_bytes": 654321,
            "bundle_id": "/backups/golden2.bundle",
        },
        "previous_receipt_digest": "sha256:" + "9" * 64,
    }
    receipt = TransitionReceiptV1.parse(document)

    expected_canonical_bytes = (
        b'{"backup":{"bundle_digest":"deadbeefdeadbeefdeadbeefdeadbeefdeadbeef'
        b'deadbeefdeadbeefdeadbeef","bundle_id":"/backups/golden2.bundle",'
        b'"checksum_algorithm":"sha256","size_bytes":654321},'
        b'"environment":"golden-env-2",'
        b'"previous_receipt_digest":'
        b'"sha256:9999999999999999999999999999999999999999999999999999999999999999",'
        b'"product":"golden-product-2","run_id":"golden-run-2",'
        b'"schema":"DeploymentTransitionReceipt.v1",'
        b'"source":{"descriptor_sha256":'
        b'"sha256:4444444444444444444444444444444444444444444444444444444444444444",'
        b'"migration_heads":["a000"]},'
        b'"target":"golden-h\xc3\xb4te",'
        b'"target_side":{"descriptor_sha256":'
        b'"sha256:5555555555555555555555555555555555555555555555555555555555555555",'
        b'"image_digest":'
        b'"sha256:6666666666666666666666666666666666666666666666666666666666666666",'
        b'"image_source_revision":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",'
        b'"migration_heads":["a000","a001"]}}'
    )
    expected_digest = (
        "sha256:83f2c0790494b1f90978c19dcf537c102d1b5a42d7ac632487d184b6274d04e5"
    )

    assert receipt.canonical_bytes() == expected_canonical_bytes
    assert str(receipt.digest()) == expected_digest
    assert receipt.as_mapping() == document


def test_parse_refuses_a_lone_surrogate() -> None:
    """A lone surrogate passes `json.loads` but cannot be UTF-8 encoded, so it
    would make `canonical_bytes()` (and so the verifier) raise. Refused at the
    boundary instead; the non-ASCII golden vector is the near-miss."""
    spec = _spec()
    document = _valid_document(spec)
    document["target"] = "host-\ud800"
    with pytest.raises(SpecError, match="UTF-8"):
        TransitionReceiptV1.parse(document)


def test_parse_accepts_encodable_non_ascii() -> None:
    spec = _spec()
    document = _valid_document(spec)
    document["target"] = "host-h\u00f4te"
    assert TransitionReceiptV1.parse(document).target == "host-h\u00f4te"
