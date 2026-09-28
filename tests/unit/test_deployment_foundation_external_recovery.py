"""Recovery a product did not execute, bound so it cannot merely be claimed.

The frozen `0.3.0a2` wheel could not express any of this, and a read-only
measurement of that wheel is what these tests are written against:

* `BackupDataset.VERIFICATIONS` was byte-identical to the published 0.2 line, so
  a descriptor naming `roles`, `ownership`, `memberships` or
  `effective_privileges` was refused AT PARSE — while `recovery.py` had modelled
  every one of them since the bundle contract landed. The vocabulary existed and
  the descriptor could not reach it.
* `backup.assess()` computed the `restore_proof_max_age_days` window correctly
  and had **zero callers**, and `BackupRecord.restore_proved_at_epoch` was
  written by nothing in the package. The enforcement was inert because nothing
  supplied the records, not because the window was wrong.

So the tests below are organised by the seven properties rather than by module,
and each names the defect it repairs. The one to read first is
`test_the_restore_proof_window_now_refuses`: an enforcement nobody calls is the
exact failure being fixed, so a test that only checked `assess()`'s arithmetic
would have passed against the broken wheel too.
"""

from __future__ import annotations

import ast
import copy
import inspect
from pathlib import Path
from typing import Any

import pytest
from dotmac_deployment_foundation.backup import (
    ArtefactClass,
    Assurance,
    BackupRecord,
    assess,
)
from dotmac_deployment_foundation.engine.plan import Phase, StepKind, build_plan
from dotmac_deployment_foundation.errors import PreconditionFailed, SpecError
from dotmac_deployment_foundation.external_recovery import (
    EXTERNAL_BACKUP_PATH_PREFIX,
    VERIFICATION_EVIDENCE,
    accept_external_recovery_receipt,
    backup_record_from_receipt,
    require_restore_proof,
)
from dotmac_deployment_foundation.recovery_identity import (
    EXECUTOR_KINDS,
    PRIVILEGE_VERIFICATIONS,
    DatasetIdentityV1,
    ExternalExecutorV1,
)
from dotmac_deployment_foundation.spec import BackupDataset, ProductDeploymentSpec

from tests.unit.deployment_lock_harness import held_lock

REPO_ROOT = Path(__file__).resolve().parents[2]
DESCRIPTOR = REPO_ROOT / "deploy" / "product.toml"

NOW = 1_800_000_000
DAY = 86_400

EXECUTOR_TOML = """
[backup.datasets.external_executor]
kind = "managed_database_service"
identifier = "hetzner-managed-pg"
version = "2026.08"
key_id = "recovery-signing-01"
"""


class _Accepts:
    def verify(self, *, key_id: str, message: bytes, signature: str) -> bool:
        return True


class _Rejects:
    def verify(self, *, key_id: str, message: bytes, signature: str) -> bool:
        return False


#: The absent verifier, as a sentinel. `_accept` defaults `verifier=None` to
#: the ACCEPTING stub so every other test does not have to pass one, so a
#: literal `None` here would be indistinguishable from the default.
_NO_VERIFIER: Any = None

#: The default for `_accept`, so a test passing `None` means it.
_ACCEPTS: Any = _Accepts()


def _descriptor_text() -> str:
    """The REAL reference descriptor, unmodified.

    This used to strip `"--host", "0.0.0.0", ` before parsing, because the app
    role spelled its in-container bind out in Git and
    `build_canonical_document` refuses an address literal anywhere in a
    descriptor. Editing the file under test to make the test pass is how that
    refusal went unrepaired; the bind now lives in `app/runtime.py`, so the
    real bytes are parsed here.
    """
    return DESCRIPTOR.read_text(encoding="utf-8")


def _spec(*, external: bool) -> ProductDeploymentSpec:
    text = _descriptor_text()
    if external:
        text = text.replace("\n[telemetry]", EXECUTOR_TOML + "\n[telemetry]")
    return ProductDeploymentSpec.loads(text, source="test")


@pytest.fixture
def external_spec() -> ProductDeploymentSpec:
    return _spec(external=True)


@pytest.fixture
def dataset(external_spec: ProductDeploymentSpec) -> BackupDataset:
    return external_spec.backup_datasets[0]


def _document(
    spec: ProductDeploymentSpec, dataset: BackupDataset, **overrides: Any
) -> dict[str, Any]:
    assert dataset.external_executor is not None
    document: dict[str, Any] = {
        "schema": "RecoveryReceipt.v1",
        "dataset_identity": dataset.identity(spec.product).as_document(),
        "descriptor_digest": str(spec.to_canonical_document().sha256_digest()),
        "snapshot_checksum": "a" * 64,
        "snapshot_checksum_algorithm": "sha256",
        "executor": dataset.external_executor.as_document(),
        "verifications": list(dataset.verify),
        "isolated_target": True,
        "proved_at_epoch": NOW - 5 * DAY,
        "restore_duration_seconds": 1320,
    }
    document.update(overrides)
    return document


def _accept(
    spec: ProductDeploymentSpec,
    dataset: BackupDataset,
    envelope: dict[str, Any],
    *,
    verifier: Any = _ACCEPTS,
) -> Any:
    assert dataset.external_executor is not None
    return accept_external_recovery_receipt(
        envelope,
        identity=dataset.identity(spec.product),
        descriptor_digest=str(spec.to_canonical_document().sha256_digest()),
        executor=dataset.external_executor,
        required_verifications=dataset.verify,
        verifier=verifier,
    )


def _envelope(document: dict[str, Any], **overrides: Any) -> dict[str, Any]:
    envelope = {
        "document": document,
        "signature": "a-real-signature",
        "key_id": "recovery-signing-01",
    }
    envelope.update(overrides)
    return envelope


# ── 0. THE STEP, through a real Executor ────────────────────────────────────
#
# The coverage gap: every test below drives the pure functions or the plan
# SHAPE, and `VERIFY_EXTERNAL_RECOVERY_RECEIPT` — the one recovery-shaped
# thing actually wired into the engine — had no Executor-level test at all.
# `test_deployment_foundation_failure_injection.py` drives BACKUP and
# VERIFY_BACKUP through a real Executor and never this. So the step that
# decides whether a deploy proceeds on somebody else's restore proof was
# exercised only as functions it calls, which is the shape of a seam nobody
# has watched refuse.


def _executor_for(spec: ProductDeploymentSpec, effects: Any, **kwargs: Any) -> Any:
    from dotmac_deployment_foundation.engine.run import Executor

    from tests.unit.host_source_stance import valid_host_source_kwargs
    from tests.unit.test_deployment_foundation_execution_binding import (
        _grant,
        _plan_and_digest,
    )
    from tests.unit.test_deployment_foundation_failure_injection import (
        AcceptingVerifier,
        evidence_policy,
    )

    plan = build_plan(spec)
    execution_plan, digest = _plan_and_digest(spec, plan, effects=effects)
    kwargs.setdefault("evidence_policy", evidence_policy())
    kwargs.setdefault("evidence_verifier", AcceptingVerifier())
    for key, value in valid_host_source_kwargs().items():
        kwargs.setdefault(key, value)
    return plan, Executor(
        spec,
        effects,
        _grant(spec, execution_plan=execution_plan),
        execution_plan=execution_plan,
        sleep=lambda _: None,
        now_epoch=NOW,
        **kwargs,
    )


def _recording_effects(spec: ProductDeploymentSpec) -> Any:
    from tests.unit.test_deployment_foundation_execution_binding import (
        RecordingEffects,
    )
    from tests.unit.test_deployment_foundation_failure_injection import (
        signed_evidence,
    )

    effects = RecordingEffects(
        labels={"org.opencontainers.image.revision": spec.source_revision},
        evidence=signed_evidence(revision=spec.source_revision),
        manifest=spec.manifest_digest,
    )
    materials = set(spec.runtime_materials)
    for role in spec.roles:
        materials.update(role.materials)
    if spec.migration is not None:
        materials.add(spec.migration.owner_material)
    effects.materials = sorted(materials)
    effects.roles = {
        role.code: type(next(iter(effects.roles.values())))(
            role.code, True, "sha256:" + "b" * 64, 0
        )
        for role in spec.roles
        if role.replicas > 0
    }
    return effects


def _assert_no_deployment_effect(effects: Any) -> None:
    """Failure evidence may be written; the deployment target may not move."""
    non_evidence = [
        mutation
        for mutation in effects.mutations
        if mutation[0] not in {"emit_annotation", "write_evidence"}
    ]
    assert non_evidence == []
    # `switched_to` is a REAL attribute of `FakeEffects`, so this is a real
    # check. There are deliberately NO `stopped`/`started` assertions beside
    # it, and that absence is the point rather than an oversight:
    # `FakeEffects.stop_roles` mutates `self.roles` and keeps no such lists, so
    # `effects.stopped` raises AttributeError and
    # `getattr(effects, "stopped", [])` is a no-op that reads like coverage.
    # Both shapes are worse than nothing — one errors for an unrelated reason,
    # the other cannot fail. Do NOT "restore" them by inventing the attributes
    # to satisfy them: the mutation-log assertion above already carries the
    # property, because `RecordingEffects` records `stop_roles`,
    # `start_candidate` and `switch` as mutations.
    assert effects.switched_to == []


def test_a_missing_recovery_receipt_refuses_before_any_effect(
    external_spec: ProductDeploymentSpec, dataset: BackupDataset
) -> None:
    """HANDED OVER, never discovered — asserted at the engine, with the host
    proven untouched. A search cannot tell "no proof exists" from "no proof was
    offered", and would happily find last quarter's."""
    effects = _recording_effects(external_spec)
    plan, executor = _executor_for(external_spec, effects)
    outcome = executor.run(plan, lock=held_lock(external_spec.product))
    assert not outcome.succeeded
    assert outcome.failed_step is not None
    assert outcome.failed_step.value == "verify_external_recovery_receipt"
    assert "no recovery receipt was supplied" in outcome.failure
    _assert_no_deployment_effect(effects)


def test_an_accepted_recovery_receipt_lets_the_deploy_proceed(
    external_spec: ProductDeploymentSpec, dataset: BackupDataset
) -> None:
    """The ADMIT half — without it, the refusal above is equally consistent
    with a step that can never pass."""
    effects = _recording_effects(external_spec)
    plan, executor = _executor_for(
        external_spec,
        effects,
        recovery_receipts={dataset.code: _envelope(_document(external_spec, dataset))},
        recovery_verifier=_ACCEPTS,
    )
    outcome = executor.run(plan, lock=held_lock(external_spec.product))
    steps = {record.kind.value: record for record in outcome.records}
    receipt_step = steps.get("verify_external_recovery_receipt")
    assert receipt_step is not None and receipt_step.ok, outcome.failure
    assert "hetzner-managed-pg" in receipt_step.detail
    assert any("recovery receipt" in note for note in outcome.notes)


def test_an_unsigned_recovery_receipt_refuses_at_the_engine(
    external_spec: ProductDeploymentSpec, dataset: BackupDataset
) -> None:
    """A verifier that refuses must stop the DEPLOY, not merely return False
    to a function nobody checks."""
    effects = _recording_effects(external_spec)
    plan, executor = _executor_for(
        external_spec,
        effects,
        recovery_receipts={dataset.code: _envelope(_document(external_spec, dataset))},
        recovery_verifier=_Rejects(),
    )
    outcome = executor.run(plan, lock=held_lock(external_spec.product))
    assert not outcome.succeeded
    assert outcome.failed_step is not None
    assert outcome.failed_step.value == "verify_external_recovery_receipt"
    _assert_no_deployment_effect(effects)


# ── 1. a typed executor, never a free-text owner ────────────────────────────


def test_the_executor_is_typed_and_an_owner_string_is_refused() -> None:
    """`owner = "the DBA team"` cannot be compared with anything, so a receipt
    from the wrong party reads identically to one from the right party."""
    with pytest.raises(SpecError, match="free-text owner"):
        ExternalExecutorV1(
            kind="whoever",
            identifier="hetzner-managed-pg",
            version="2026.08",
            key_id="recovery-signing-01",
        )
    with pytest.raises(SpecError, match="machine-shaped"):
        ExternalExecutorV1(
            kind="operator_team",
            identifier="DBA Team (Lagos)",
            version="2026.08",
            key_id="recovery-signing-01",
        )


def test_the_executor_version_has_no_default() -> None:
    """A receipt from v1 and one from v2 of the same platform are facts about
    different restore procedures."""
    with pytest.raises(SpecError, match="version token"):
        ExternalExecutorV1(
            kind="backup_platform",
            identifier="some-platform",
            version="",
            key_id="recovery-signing-01",
        )


def test_the_executor_kinds_are_a_closed_set() -> None:
    assert "managed_database_service" in EXECUTOR_KINDS
    assert all(kind.islower() for kind in EXECUTOR_KINDS)


# ── 2. dataset identity independent of host and executor ────────────────────


def test_a_host_shaped_lineage_is_refused() -> None:
    """Identity keyed to where the data currently lives is orphaned by the
    first failover — the exact moment the old proofs matter most."""
    with pytest.raises(SpecError):
        DatasetIdentityV1(
            product="p", dataset="primary", lineage="db01.lagos.dotmac.ng"
        )


def test_a_lineage_derived_from_the_executor_is_refused() -> None:
    identity = DatasetIdentityV1(
        product="p", dataset="primary", lineage="hetzner-managed-pg-primary"
    )
    executor = ExternalExecutorV1(
        kind="managed_database_service",
        identifier="hetzner-managed-pg",
        version="2026.08",
        key_id="recovery-signing-01",
    )
    with pytest.raises(SpecError) as caught:
        identity.refuse_executor_derived(executor)
    # The two load-bearing FACTS the refusal has to name, so an operator can see
    # which lineage collided with which executor -- not a prose fragment.
    #
    # This assertion used to be `match="changing supplier"`, and it failed in CI
    # against a message that says "Changing supplier": `re.search` is
    # case-sensitive, and the lowercase phrase existed only in a DOCSTRING a few
    # lines above the raise. A guard matched to wording is a guard that breaks
    # when the wording is improved, and -- worse -- one that keeps passing when
    # the wording survives a change that guts the check behind it.
    message = str(caught.value)
    assert identity.lineage in message
    assert executor.identifier in message


def test_an_external_executor_without_a_lineage_is_refused() -> None:
    """The dataset CODE is unique only inside one descriptor, so two products
    would mint colliding identities and one's receipt would satisfy the other."""
    text = _descriptor_text().replace('lineage = "starter-primary-9d41c6b2"\n', "")
    text = text.replace("\n[telemetry]", EXECUTOR_TOML + "\n[telemetry]")
    with pytest.raises(SpecError, match="lineage"):
        ProductDeploymentSpec.loads(text, source="test")


def test_the_identity_survives_a_change_of_executor(
    external_spec: ProductDeploymentSpec, dataset: BackupDataset
) -> None:
    """The property, stated positively. Same data, different supplier, same
    identity — which is what lets an old proof still be about this dataset."""
    before = dataset.identity(external_spec.product)
    moved = _spec(external=True).backup_datasets[0]
    assert moved.identity(external_spec.product) == before


# ── 3. a SIGNED receipt, bound to everything that could drift ───────────────


def test_no_verifier_means_refuse_not_skip(
    external_spec: ProductDeploymentSpec, dataset: BackupDataset
) -> None:
    """Not "skip signature checking".

    A facility that degrades to trusting unsigned input when its verifier is
    missing has a bypass anyone can trigger by deleting configuration. Same
    rule, same reason, as `evidence.accept_release_evidence` — and it must fire
    on a receipt that is otherwise perfect, which is why the document here is
    the well-formed one.
    """
    with pytest.raises(PreconditionFailed, match="no signature verifier"):
        _accept(
            external_spec,
            dataset,
            _envelope(_document(external_spec, dataset)),
            verifier=_NO_VERIFIER,
        )


def test_a_well_formed_receipt_is_accepted(
    external_spec: ProductDeploymentSpec, dataset: BackupDataset
) -> None:
    """The ADMIT. Every refusal below is worthless without it: a function that
    refused everything would pass each of them."""
    receipt = _accept(
        external_spec, dataset, _envelope(_document(external_spec, dataset))
    )
    assert receipt.executor.identifier == "hetzner-managed-pg"
    assert receipt.sha256_digest().startswith("sha256:")
    assert set(PRIVILEGE_VERIFICATIONS) <= set(receipt.verifications)


def test_the_accepted_receipt_carries_the_declared_key_not_an_echo(
    external_spec: ProductDeploymentSpec, dataset: BackupDataset
) -> None:
    """The signed document does not name its own key — a document carrying its
    own key id would let a forger nominate the key that verifies it — so the
    PARSED executor holds a sentinel for that field.

    An earlier version echoed the identifier there instead, which reads like a
    real key id to anyone inspecting `receipt.executor.key_id`. A
    plausible-looking wrong value is worse than an obviously absent one, so the
    accepted receipt substitutes the DECLARED executor, and the signed bytes are
    unchanged by the substitution.
    """
    assert dataset.external_executor is not None
    receipt = _accept(
        external_spec, dataset, _envelope(_document(external_spec, dataset))
    )
    assert receipt.executor.key_id == dataset.external_executor.key_id
    assert receipt.executor.key_id != receipt.executor.identifier
    # The key id stays OUTSIDE the signed message.
    assert dataset.external_executor.key_id not in receipt.canonical_bytes().decode()


@pytest.mark.parametrize(
    ("label", "overrides", "match"),
    [
        ("descriptor", {"descriptor_digest": "sha256:" + "0" * 64}, "descriptor"),
        (
            "lineage",
            {
                "dataset_identity": {
                    "product": "dotmac_starter_mt",
                    "dataset": "primary",
                    "lineage": "someother-lineage",
                }
            },
            "another dataset",
        ),
        ("isolation", {"isolated_target": False}, "isolated target"),
        ("snapshot", {"snapshot_checksum": "   "}, "no snapshot checksum"),
        ("verifications", {"verifications": ["schema"]}, "does not claim"),
    ],
)
def test_a_receipt_missing_a_binding_is_refused(
    external_spec: ProductDeploymentSpec,
    dataset: BackupDataset,
    label: str,
    overrides: dict[str, Any],
    match: str,
) -> None:
    """Drop any one binding and the receipt is reusable somewhere it was never
    meant to apply — the enumeration `ExecutionGrant` makes for a deploy."""
    with pytest.raises(PreconditionFailed, match=match):
        _accept(
            external_spec,
            dataset,
            _envelope(_document(external_spec, dataset, **overrides)),
        )


def test_a_receipt_from_a_different_executor_version_is_refused(
    external_spec: ProductDeploymentSpec, dataset: BackupDataset
) -> None:
    assert dataset.external_executor is not None
    stale = dict(dataset.external_executor.as_document(), version="2025.01")
    with pytest.raises(PreconditionFailed, match="different fact"):
        _accept(
            external_spec,
            dataset,
            _envelope(_document(external_spec, dataset, executor=stale)),
        )


def test_an_unsigned_or_stranger_signed_receipt_is_refused(
    external_spec: ProductDeploymentSpec, dataset: BackupDataset
) -> None:
    document = _document(external_spec, dataset)
    with pytest.raises(PreconditionFailed, match="no signature"):
        _accept(external_spec, dataset, _envelope(document, signature=""))
    with pytest.raises(PreconditionFailed, match="still a stranger"):
        _accept(external_spec, dataset, _envelope(document, key_id="somebody-else"))
    with pytest.raises(PreconditionFailed, match="does not verify"):
        _accept(external_spec, dataset, _envelope(document), verifier=_Rejects())


def test_the_signature_is_checked_before_the_content(
    external_spec: ProductDeploymentSpec, dataset: BackupDataset
) -> None:
    """Refusing on content first would let an attacker probe which values this
    facility accepts using documents they never had to sign."""
    wrong_everything = _document(
        external_spec,
        dataset,
        descriptor_digest="sha256:" + "0" * 64,
        isolated_target=False,
    )
    with pytest.raises(PreconditionFailed, match="does not verify"):
        _accept(
            external_spec,
            dataset,
            _envelope(wrong_everything),
            verifier=_Rejects(),
        )


def test_a_receipt_missing_a_required_field_is_refused(
    external_spec: ProductDeploymentSpec, dataset: BackupDataset
) -> None:
    """A document missing a field this version checks is one it cannot judge;
    treating the absence as satisfied is how a gate quietly stops gating."""
    document = _document(external_spec, dataset)
    del document["executor"]
    with pytest.raises(SpecError, match="missing required field"):
        _accept(external_spec, dataset, _envelope(document))


def test_the_signed_message_is_canonical_not_the_raw_bytes(
    external_spec: ProductDeploymentSpec, dataset: BackupDataset
) -> None:
    """Key order must not change the standing of identical facts."""
    document = _document(external_spec, dataset)
    shuffled = dict(reversed(list(document.items())))
    first = _accept(external_spec, dataset, _envelope(document))
    second = _accept(external_spec, dataset, _envelope(shuffled))
    assert first.canonical_bytes() == second.canonical_bytes()
    assert first.sha256_digest() == second.sha256_digest()


# ── 4. the vocabulary the descriptor could not reach ────────────────────────


def test_the_descriptor_can_now_name_every_privilege_verification() -> None:
    """This is the whole of requirement 4 and it is PLUMBING, not design: the
    frozen wheel refused these four at parse while `recovery.py` modelled all
    of them."""
    assert set(PRIVILEGE_VERIFICATIONS) <= set(BackupDataset.VERIFICATIONS)
    parsed = _spec(external=False).backup_datasets[0]
    assert set(PRIVILEGE_VERIFICATIONS) <= set(parsed.verify)


def test_every_verification_names_the_evidence_that_answers_it() -> None:
    """A receipt claiming `effective_privileges` claims something about a
    specific body of evidence, and a reader needs to know which."""
    assert set(BackupDataset.VERIFICATIONS) == set(VERIFICATION_EVIDENCE)
    assert "direct-grant set" in VERIFICATION_EVIDENCE["effective_privileges"]


def test_an_unknown_verification_is_still_refused() -> None:
    """Widening the vocabulary must not open it."""
    text = _descriptor_text().replace('"effective_privileges",', '"vibes",')
    with pytest.raises(SpecError, match="unknown verification"):
        ProductDeploymentSpec.loads(text, source="test")


# ── 5. the enforcement that nothing called ──────────────────────────────────


def test_an_accepted_receipt_writes_the_timestamp_nothing_wrote(
    external_spec: ProductDeploymentSpec, dataset: BackupDataset
) -> None:
    """`restore_proved_at_epoch` was written by nothing in the whole package,
    which is why the window was inert."""
    receipt = _accept(
        external_spec, dataset, _envelope(_document(external_spec, dataset))
    )
    record = backup_record_from_receipt(receipt, path="external:x", size_bytes=1)
    assert record.assurance is Assurance.PROVED
    assert record.artefact_class is ArtefactClass.RECOVERY_BUNDLE
    assert record.restore_proved_at_epoch == receipt.proved_at_epoch


def test_a_non_prefixed_path_is_refused(
    external_spec: ProductDeploymentSpec, dataset: BackupDataset
) -> None:
    """The prefix is enforced at the ONE producer, not merely documented: the
    only caller of `backup_record_from_receipt` cannot emit a record that a
    reader (`transition_receipt.py`) would fail to recognise as external."""
    receipt = _accept(
        external_spec, dataset, _envelope(_document(external_spec, dataset))
    )
    with pytest.raises(SpecError, match="must start with"):
        backup_record_from_receipt(receipt, path="not-external", size_bytes=1)

    # near miss: the conforming prefix is accepted
    record = backup_record_from_receipt(
        receipt, path=f"{EXTERNAL_BACKUP_PATH_PREFIX}x", size_bytes=1
    )
    assert record.path == f"{EXTERNAL_BACKUP_PATH_PREFIX}x"


def test_the_restore_proof_window_now_refuses(
    external_spec: ProductDeploymentSpec, dataset: BackupDataset
) -> None:
    """THE repair. `assess()` had zero callers, so a correct window refused
    nothing. `require_restore_proof` is the caller, and it raises rather than
    reporting — a window that produces a warning nobody blocks on is the same
    artefact as no window."""
    fresh = backup_record_from_receipt(
        _accept(external_spec, dataset, _envelope(_document(external_spec, dataset))),
        path="external:x",
        size_bytes=1,
    )
    assert "inside the" in require_restore_proof(
        external_spec, "primary", [fresh], now_epoch=NOW
    )

    overdue = backup_record_from_receipt(
        _accept(
            external_spec,
            dataset,
            _envelope(
                _document(external_spec, dataset, proved_at_epoch=NOW - 60 * DAY)
            ),
        ),
        path="external:x",
        size_bytes=1,
    )
    with pytest.raises(PreconditionFailed, match="60 days old"):
        require_restore_proof(external_spec, "primary", [overdue], now_epoch=NOW)

    with pytest.raises(PreconditionFailed, match="none has ever been recorded"):
        require_restore_proof(external_spec, "primary", [], now_epoch=NOW)


def test_cadence_and_proof_age_stay_two_controls(
    external_spec: ProductDeploymentSpec, dataset: BackupDataset
) -> None:
    """A product taking hourly backups nobody has restored passes the first and
    fails the second, and that is the state the fleet was actually in. Merging
    them would delete the only control reporting the real problem."""
    assert dataset.expected_backup_interval_seconds != (
        dataset.restore_proof_max_age_days * DAY
    )
    ancient_but_proved = BackupRecord(
        dataset="primary",
        path="p",
        size_bytes=1,
        checksum="c",
        checksum_algorithm="sha256",
        completed_at_epoch=NOW - 10 * DAY,
        assurance=Assurance.PROVED,
        restore_proved_at_epoch=NOW - DAY,
        artefact_class=ArtefactClass.RECOVERY_BUNDLE,
    )
    health = assess(
        external_spec,
        "primary",
        [ancient_but_proved],
        now_epoch=NOW,
        expected_backup_interval_seconds=3600,
    )
    assert health.stale is True
    assert health.restore_proof_overdue is False
    # Stale, and the proof window is satisfied: the deployment proceeds and the
    # staleness is REPORTED. Different remedies, different clocks.
    assert "NOTE" in require_restore_proof(
        external_spec, "primary", [ancient_but_proved], now_epoch=NOW
    )


# ── 6. the plan says what this deployment actually does ─────────────────────


def test_an_external_dataset_gets_a_gate_and_no_backup_step(
    external_spec: ProductDeploymentSpec,
) -> None:
    """A `backup` step here would attribute to the consuming product an act it
    does not perform — and a plan claiming a product backed something up is
    exactly the artefact that read as green while nothing had been restored."""
    plan = build_plan(external_spec)
    assert plan.has(StepKind.VERIFY_EXTERNAL_RECOVERY_RECEIPT)
    assert not plan.has(StepKind.BACKUP)
    assert not plan.has(StepKind.VERIFY_BACKUP)
    assert any("runs no backup for it" in note for note in plan.notes)


def test_the_receipt_check_is_a_gate_and_runs_before_any_mutation(
    external_spec: ProductDeploymentSpec,
) -> None:
    """Discovering after the migration that recovery was never demonstrated is
    discovering it at the one moment it cannot help."""
    plan = build_plan(external_spec)
    step = plan.step(StepKind.VERIFY_EXTERNAL_RECOVERY_RECEIPT)
    assert step is not None
    assert step.phase is Phase.GATE
    assert not step.mutates
    assert plan.steps.index(step) < plan.first_mutating_index


def test_a_self_executed_dataset_still_gets_its_backup_steps() -> None:
    """The other direction. A gate that removed the backup step for every
    dataset would pass the test above and be a catastrophe."""
    plan = build_plan(_spec(external=False))
    assert plan.has(StepKind.BACKUP)
    assert plan.has(StepKind.VERIFY_BACKUP)
    assert not plan.has(StepKind.VERIFY_EXTERNAL_RECOVERY_RECEIPT)


# ── 7. handed over, never discovered ────────────────────────────────────────


#: Attribute names that mean "enumerate a directory" WHATEVER the receiver is.
#: `walk` is deliberately not here — `ast.walk` is pervasive in this repository
#: and means something else entirely — so it is caught by resolution below
#: instead, and only when the receiver really is `os`.
ENUMERATION_ATTRS = frozenset({"glob", "rglob", "iterdir", "scandir", "listdir"})

#: Fully-qualified callables that enumerate. Reached through the import alias
#: map, so `import os as o; o.walk(...)` and `from os import scandir as s; s(...)`
#: both resolve here rather than slipping past a substring scan.
ENUMERATION_DOTTED = frozenset(
    {"os.walk", "os.scandir", "os.listdir", "os.path.walk", "glob.glob", "glob.iglob"}
)

#: Constructs that defeat static resolution. Per the rule, an unresolvable
#: construct in receipt-handling code is REFUSED rather than assumed innocent:
#: it is exactly where a discovery would hide.
DYNAMIC_NAMES = frozenset({"eval", "exec", "__import__"})
DYNAMIC_ATTRS = frozenset({"import_module"})

PACKAGE = (
    REPO_ROOT
    / "packages"
    / "dotmac-deployment-foundation"
    / "src"
    / "dotmac_deployment_foundation"
)


def _alias_map(tree: ast.AST) -> dict[str, str]:
    """Local name → dotted origin, so an alias cannot hide an import."""
    alias: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for name in node.names:
                alias[name.asname or name.name.split(".")[0]] = name.name
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            for name in node.names:
                alias[name.asname or name.name] = f"{node.module}.{name.name}"
    return alias


def _enclosing(tree: ast.AST, lineno: int) -> str:
    best: ast.AST | None = None
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            if node.lineno <= lineno <= (node.end_lineno or node.lineno):
                if best is None or node.lineno > best.lineno:  # type: ignore[attr-defined]
                    best = node
    return getattr(best, "name", "<module>")


def enumeration_sites(source: str) -> list[tuple[int, str, str]]:
    """(line, api, enclosing function) for every filesystem enumeration.

    AST over `Call`/`Attribute`/`Name` nodes rather than substrings, because the
    substring version this replaced was a NAME BLACKLIST: `os.scandir`,
    `os.walk`, an aliased `iterdir` and a one-line helper each defeated it while
    it read as well-guarded, planted positives and all.

    An ATTRIBUTE is flagged whether or not it is called, so binding the method
    first (`walk = root.iterdir`) is caught at the binding.
    """
    tree = ast.parse(source)
    alias = _alias_map(tree)
    found: list[tuple[int, str, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            if node.attr in ENUMERATION_ATTRS:
                found.append(
                    (node.lineno, f".{node.attr}", _enclosing(tree, node.lineno))
                )
            elif node.attr == "walk" and isinstance(node.value, ast.Name):
                if alias.get(node.value.id, node.value.id) in {"os", "os.path"}:
                    found.append(
                        (node.lineno, "os.walk", _enclosing(tree, node.lineno))
                    )
        elif isinstance(node, ast.Name):
            if alias.get(node.id, "") in ENUMERATION_DOTTED:
                found.append(
                    (node.lineno, alias[node.id], _enclosing(tree, node.lineno))
                )
    return sorted(set(found))


def unresolvable_sites(source: str) -> list[tuple[int, str, str]]:
    """Constructs whose target this checker cannot resolve, so it refuses them.

    `getattr` is NOT blanket-refused: `getattr(self, f"_do_{kind}")` resolves to
    methods of the same class, in this same module, every one of which this
    checker already scans — so it cannot hide a discovery. What it refuses is
    `getattr` on an IMPORTED MODULE with a computed attribute, and a computed
    attribute fetched and then called, which can.
    """
    tree = ast.parse(source)
    alias = _alias_map(tree)
    found: list[tuple[int, str, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name) and func.id in DYNAMIC_NAMES:
            found.append((node.lineno, func.id, _enclosing(tree, node.lineno)))
        elif isinstance(func, ast.Attribute) and func.attr in DYNAMIC_ATTRS:
            found.append((node.lineno, func.attr, _enclosing(tree, node.lineno)))
        elif isinstance(func, ast.Name) and func.id == "getattr" and node.args:
            target = node.args[0]
            on_module = isinstance(target, ast.Name) and (
                alias.get(target.id, "") in {"os", "glob", "pathlib", "shutil"}
                or target.id in {"os", "glob", "pathlib", "shutil"}
            )
            computed = len(node.args) > 1 and not isinstance(node.args[1], ast.Constant)
            if on_module and computed:
                found.append(
                    (
                        node.lineno,
                        "getattr(<module>, <computed>)",
                        _enclosing(tree, node.lineno),
                    )
                )
        elif isinstance(func, ast.Call) and isinstance(func.func, ast.Name):
            if func.func.id == "getattr":
                found.append(
                    (node.lineno, "getattr(...)()", _enclosing(tree, node.lineno))
                )
    return sorted(set(found))


#: EVERY filesystem enumeration in the whole facility, each with the reason it
#: is unrelated to receipts. Scanning the whole package rather than only the
#: receipt modules is what closes the one-line-helper evasion: a helper cannot
#: sit in a neighbouring module and be called from receipt code, because there
#: is nowhere in the package for it to hide.
#:
#: Two-directional (ADR-0018): a NEW enumeration anywhere fails until it is
#: recorded here with a reason, and a removed one fails until the row goes.
ALLOWED_ENUMERATION: dict[tuple[str, str, str], str] = {
    ("cli.py", "cmd_render", ".rglob"): (
        "walks the RENDER OUTPUT directory to report stray files. Reads no "
        "receipt and is not on any path that obtains one"
    ),
    ("conformance.py", "check_rendered_assets_match", ".rglob"): (
        "the consumer conformance kit, comparing a product's committed rendered "
        "assets against what its descriptor renders"
    ),
    ("launcher.py", "_package_digest", ".rglob"): (
        "hashes the facility's own .py files to digest the installed package"
    ),
    ("target_identity_guard.py", "scan_tree", ".rglob"): (
        "walks a CALLER-SUPPLIED root comparing address literals against the "
        "embedded-target ledger. It cannot reach a receipt in three independent "
        "ways: the module imports only stdlib and `.errors`, so "
        "`external_recovery` is not reachable from it at all; no other module "
        "in the package calls it, so it is on no path that obtains a receipt; "
        "and its return type is `list[TargetIdentityFinding]`, a closed "
        "four-field record of (path, line, kind, address), so even a receipt "
        "file it happened to walk over could yield nothing but an address "
        "literal. The scan that gates a release is `scan_archive`, which reads "
        "a zip or tar and touches no filesystem enumeration at all"
    ),
}

#: The modules that handle recovery receipts: the contract itself, anything
#: importing it, and anything constructing the `recovery_receipts` argument that
#: carries them. Derived, never listed — a new handler joins the scope by
#: existing rather than by somebody remembering to add it.
RECEIPT_SYMBOLS = frozenset(
    {
        "accept_external_recovery_receipt",
        "backup_record_from_receipt",
        "ExternalRecoveryReceiptV1",
        "recovery_receipts",
    }
)


def _receipt_modules() -> dict[str, str]:
    modules: dict[str, str] = {}
    for path in sorted(PACKAGE.rglob("*.py")):
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        imports_contract = any(
            isinstance(n, ast.ImportFrom)
            and n.module
            and n.module.endswith("external_recovery")
            for n in ast.walk(tree)
        )
        carries = any(
            (isinstance(n, ast.keyword) and n.arg == "recovery_receipts")
            or (isinstance(n, ast.arg) and n.arg == "recovery_receipts")
            for n in ast.walk(tree)
        )
        if imports_contract or carries or path.name == "external_recovery.py":
            modules[str(path.relative_to(PACKAGE))] = source
    return modules


def _handles_receipts(source: str, function: str) -> bool:
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
            and node.name == function
        ):
            body = ast.unparse(node)
            return any(symbol in body for symbol in RECEIPT_SYMBOLS)
    return False


def test_the_facility_enumerates_the_filesystem_in_exactly_these_places() -> None:
    """A receipt is handed over, never discovered — enforced over the WHOLE
    package, so a discovery helper has nowhere to hide."""
    found = {
        (str(path.relative_to(PACKAGE)), scope, api)
        for path in sorted(PACKAGE.rglob("*.py"))
        for _, api, scope in enumeration_sites(path.read_text(encoding="utf-8"))
    }
    assert found == set(ALLOWED_ENUMERATION), (
        "filesystem enumeration in the facility changed.\n"
        f"  new:     {sorted(found - set(ALLOWED_ENUMERATION))}\n"
        f"  removed: {sorted(set(ALLOWED_ENUMERATION) - found)}\n"
        "Record a new one here with the reason it cannot reach a receipt, or "
        "delete the stale row — this ratchet fails in both directions"
    )


def test_no_receipt_handling_function_enumerates_the_filesystem() -> None:
    """The property itself. Every allowlisted site must sit in a function that
    touches no receipt symbol — `cli.cmd_render` walks the render output and is
    the only enumeration in a receipt-handling MODULE at all."""
    offenders = [
        f"{module}::{scope} calls {api}"
        for module, source in _receipt_modules().items()
        for _, api, scope in enumeration_sites(source)
        if _handles_receipts(source, scope)
    ]
    assert not offenders, (
        f"receipt-handling code enumerates the filesystem: {offenders}. A search "
        "cannot tell 'no proof exists' from 'no proof was offered', and will "
        "happily find last quarter's"
    )


def test_no_receipt_handling_module_hides_a_call_behind_dynamic_resolution() -> None:
    """Unresolvable is REFUSED, not assumed innocent — it is precisely where a
    discovery would hide."""
    offenders = [
        f"{module}:{line} {api} in {scope}"
        for module, source in _receipt_modules().items()
        for line, api, scope in unresolvable_sites(source)
    ]
    assert (
        not offenders
    ), f"unresolvable construct in receipt-handling code: {offenders}"


@pytest.mark.parametrize(
    ("label", "code"),
    [
        (
            "os.scandir",
            "import os\ndef find(root):\n    return sorted(os.scandir(root))[-1]",
        ),
        (
            "os.walk",
            "import os\ndef find(root):\n    for _, _, f in os.walk(root): return f",
        ),
        (
            "aliased iterdir",
            "def find(root):\n    walk = root.iterdir\n    return sorted(walk())[-1]",
        ),
        (
            "from-import alias",
            "from os import scandir as s\ndef find(root):\n"
            "    return sorted(s(root))[-1]",
        ),
        ("glob module", "import glob\ndef find(root):\n    return glob.glob(root)"),
        (
            "the original planted case",
            "def find(root):\n    return sorted(root.glob('*.json'))[-1]",
        ),
    ],
)
def test_the_detector_catches_every_demonstrated_evasion(label: str, code: str) -> None:
    """Each of these defeated the substring blacklist while it looked guarded.
    A guard is only worth its planted positives if the plants are the ways it
    would actually be got round."""
    assert enumeration_sites(code), f"{label} evaded the detector"


def test_the_detector_admits_legitimate_code() -> None:
    """The other direction, and the reason the previous coarse check had to go:
    a detector that cries wolf is one somebody eventually silences."""
    assert not enumeration_sites(
        "import ast\ndef f(tree):\n    return list(ast.walk(tree))"
    )
    assert not unresolvable_sites(
        'import os\ndef f():\n    return getattr(os, "O_NOFOLLOW", 0)'
    )
    assert not unresolvable_sites(
        'def f(self, kind):\n    return getattr(self, f"_do_{kind}", None)'
    )


def test_dynamic_resolution_that_could_hide_a_walk_is_refused() -> None:
    """`getattr(self, …)` resolves to methods this checker already scans;
    `getattr(os, name)` resolves to whatever the caller computed."""
    assert unresolvable_sites("import os\ndef f(n):\n    return getattr(os, n)('/tmp')")
    assert unresolvable_sites(
        "import importlib\ndef f(m):\n    return importlib.import_module(m)"
    )


def test_the_receipt_is_the_acceptors_first_positional_argument() -> None:
    """The seam, asserted structurally and without naming anything.

    The envelope is the only positional parameter and every expectation is
    keyword-only, so a caller with no receipt has nothing to pass — rather than
    a path it could be tempted to fill in. This replaced an assertion that the
    signature contained no parameter called `path`/`directory`/`search_root`/
    `pattern`, which a parameter named `receipt_dir` or `root` walked straight
    past.
    """
    signature = inspect.signature(accept_external_recovery_receipt)
    parameters = list(signature.parameters.values())
    assert parameters[0].kind is inspect.Parameter.POSITIONAL_OR_KEYWORD
    assert all(p.kind is inspect.Parameter.KEYWORD_ONLY for p in parameters[1:]), [
        (p.name, str(p.kind)) for p in parameters[1:]
    ]
    assert not any(
        p.kind in {inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD}
        for p in parameters
    )


def test_a_receipt_document_is_never_mutated_by_acceptance(
    external_spec: ProductDeploymentSpec, dataset: BackupDataset
) -> None:
    document = _document(external_spec, dataset)
    before = copy.deepcopy(document)
    _accept(external_spec, dataset, _envelope(document))
    assert document == before
