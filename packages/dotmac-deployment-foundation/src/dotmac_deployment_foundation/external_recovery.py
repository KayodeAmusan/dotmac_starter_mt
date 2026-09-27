"""Recovery a product did not execute, bound so it cannot be claimed.

The frozen `0.3.0a2` wheel could not express this at all, and the measurement
that found it is the reason this module exists. `BackupDataset.VERIFICATIONS`
carried three words — `schema`, `row_counts`, `migration_heads` — so a descriptor
declaring `effective_privileges` was refused at parse even though `recovery.py`
already modelled `MEMBERSHIPS`, `OBJECT_OWNERSHIP` and
`CatalogEvidence.effective_privileges`. The vocabulary existed and the
descriptor could not reach it. And `backup.assess()`, which computes whether the
last proved restore is older than `restore_proof_max_age_days`, had **zero
callers**: the window was correct, and nothing consulted it, because nothing
supplied the records it reads.

Both halves matter and neither fixes the other. Widening the vocabulary without
a caller for `assess()` gives a richer declaration nobody checks; calling
`assess()` without records gives an enforcement with nothing to enforce over.

## The shape: a receipt, not a claim

When the party that executes recovery is not the deploying product — a managed
database service, a backup platform, an operator team, a sibling product — the
deployment cannot observe the restore. It can only be TOLD about it, and the
entire question is what makes being told different from assuming.

* **The executor is typed** (:class:`ExternalExecutorV1`). Never a free-text
  owner: `owner = "the DBA team"` cannot be compared with anything, so a receipt
  from a different party reads identically to the right one. Kind is a closed
  set, identifier is machine-shaped, and the executor's own VERSION is part of
  its identity — a receipt from v1 and one from v2 of the same platform are
  different facts about different procedures.

* **The dataset identity is independent of host and executor**
  (:class:`DatasetIdentityV1`). If identity were the host, moving the database
  would silently orphan every proof; if it were the executor, changing supplier
  would. Both are exactly when you most need the old proofs to still be about
  the same data, so the lineage is a declared opaque token and this module
  refuses one that is host-shaped or that repeats the executor's identifier.

* **The receipt is SIGNED and bound** (:class:`ExternalRecoveryReceiptV1`) to
  the dataset identity, the descriptor digest, the snapshot checksum, the
  executor identity AND version, and the exact verification set that ran. Drop
  any one and the receipt is reusable somewhere it was never meant to apply —
  the same enumeration `authorization.ExecutionGrant` makes for a deploy
  approval.

* **No verifier means refuse.** Not "skip signature checking". Same rule, same
  reason, as `evidence.accept_release_evidence`: a facility that degrades to
  trusting unsigned input when its verifier is missing has a bypass anybody can
  trigger by deleting configuration.

* **The receipt is passed in, never discovered.** There is no directory scan and
  no `Effects.find_receipt()` — a caller hands over the exact envelope, exactly
  as `--authorization` hands over an `AuthorizationReceipt`. Ambient discovery
  is how a stale receipt from a previous quarter satisfies today's gate.

## And the record it produces

`assess()` reads `BackupRecord`s. Nothing wrote one at
:attr:`~.backup.Assurance.PROVED` with a `restore_proved_at_epoch`, which is why
the window was inert. :func:`backup_record_from_receipt` is that writer, and
:func:`require_restore_proof` is the caller: together they close
receipt → record → assessment → refusal.

## Cadence and proof age are TWO controls

`expected_backup_interval_seconds` is how often a backup is expected. It decides
STALENESS. `restore_proof_max_age_days` is how old the newest proved restore may
be. It decides whether recovery has been demonstrated at all.

They are not two names for one number and must not be merged. A product taking
hourly backups nobody has ever restored is failing the second while passing the
first, and that is the exact state the fleet was in.
"""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Sequence
from typing import Any, Final

from .backup import SECONDS_PER_DAY, ArtefactClass, Assurance, BackupRecord, assess
from .digest import Digest
from .errors import PreconditionFailed, SpecError
from .evidence import SignatureVerifier
from .recovery import BundleComponent
from .recovery_identity import (
    EXECUTOR_KINDS,
    PRIVILEGE_VERIFICATIONS,
    DatasetIdentityV1,
    ExternalExecutorV1,
)
from .spec import BackupDataset, ProductDeploymentSpec

EXTERNAL_RECEIPT_SCHEMA: Final = "RecoveryReceipt.v1"

#: The `BackupRecord.path` prefix every caller of :func:`backup_record_from_receipt`
#: uses for the record it builds from an external recovery receipt (see
#: `engine/run.py`'s
#: ``path=f"{EXTERNAL_BACKUP_PATH_PREFIX}{receipt.executor.identifier}"``).
#: `backup_record_from_receipt` takes `path`/`size_bytes` from its caller rather
#: than constructing them, so this module does not enforce the convention
#: itself — it names it, as the ONE place both this module's callers and any
#: reader of a `BackupRecord` (see `transition_receipt.py`'s use of this
#: constant to detect such a record) agree on what "external" looks like.
EXTERNAL_BACKUP_PATH_PREFIX: Final = "external:"

#: Stands in for the key id a signed document deliberately does not carry.
#: Machine-shaped so `ExternalExecutorV1` accepts it, and obviously not a
#: key so nobody mistakes it for one.
_UNATTRIBUTED_KEY: Final = "unattributed-key-id"

#: What each verification is answered BY. Not documentation: a receipt claiming
#: `effective_privileges` is claiming something about a specific body of
#: evidence, and a reader deciding whether to trust it needs to know which.
#:
#: `effective_privileges` maps to no single bundle component deliberately — it
#: is a DERIVED audit over the whole ACL surface (`CatalogEvidence
#: .effective_privileges`), and answering it from direct grants alone reads as
#: satisfied for a role holding the privilege through PUBLIC, through a group,
#: or through a column-level grant. That is the one check that would go green
#: exactly when the boundary is broken.
VERIFICATION_EVIDENCE: Final[dict[str, str]] = {
    "schema": "the restored catalog's schema list",
    "row_counts": "per-table row counts within the declared tolerance",
    "migration_heads": BundleComponent.MIGRATION_HEADS.value,
    "roles": BundleComponent.ROLE_ATTRIBUTES.value,
    "ownership": BundleComponent.OBJECT_OWNERSHIP.value,
    "memberships": BundleComponent.MEMBERSHIPS.value,
    "effective_privileges": (
        "CatalogEvidence.effective_privileges — the DERIVED audit over PUBLIC, "
        "inherited group and column-level grants, never the direct-grant set"
    ),
}

__all__ = [
    "EXECUTOR_KINDS",
    "EXTERNAL_BACKUP_PATH_PREFIX",
    "EXTERNAL_RECEIPT_SCHEMA",
    "PRIVILEGE_VERIFICATIONS",
    "VERIFICATION_EVIDENCE",
    "DatasetIdentityV1",
    "ExternalExecutorV1",
    "ExternalRecoveryReceiptV1",
    "accept_external_recovery_receipt",
    "backup_record_from_receipt",
    "require_restore_proof",
]

#: Required on every receipt. Absent means refuse — a document missing a field
#: this version checks is one it cannot judge, and treating an absent field as
#: satisfied is how a gate quietly stops gating (`evidence.REQUIRED_FIELDS`).
REQUIRED_RECEIPT_FIELDS: Final[tuple[str, ...]] = (
    "schema",
    "dataset_identity",
    "descriptor_digest",
    "snapshot_checksum",
    "snapshot_checksum_algorithm",
    "executor",
    "verifications",
    "isolated_target",
    "proved_at_epoch",
    "restore_duration_seconds",
)


@dataclasses.dataclass(frozen=True, slots=True)
class ExternalRecoveryReceiptV1:
    """One externally executed recovery, as the thing that vouches for it."""

    identity: DatasetIdentityV1
    descriptor_digest: str
    snapshot_checksum: str
    snapshot_checksum_algorithm: str
    executor: ExternalExecutorV1
    verifications: tuple[str, ...]
    isolated_target: bool
    proved_at_epoch: int
    restore_duration_seconds: int

    def as_document(self) -> dict[str, Any]:
        return {
            "schema": EXTERNAL_RECEIPT_SCHEMA,
            "dataset_identity": self.identity.as_document(),
            "descriptor_digest": self.descriptor_digest,
            "snapshot_checksum": self.snapshot_checksum,
            "snapshot_checksum_algorithm": self.snapshot_checksum_algorithm,
            "executor": self.executor.as_document(),
            "verifications": list(self.verifications),
            "isolated_target": self.isolated_target,
            "proved_at_epoch": self.proved_at_epoch,
            "restore_duration_seconds": self.restore_duration_seconds,
        }

    def canonical_bytes(self) -> bytes:
        """The exact bytes a signature covers — never the raw file bytes.

        Same rule `evidence.py` and `document.py` apply: a signature over raw
        bytes lets an innocent re-serialization read as tampering, and lets two
        byte strings with identical meaning have different standings.
        """
        return json.dumps(
            self.as_document(), sort_keys=True, separators=(",", ":")
        ).encode("utf-8")

    def sha256_digest(self) -> str:
        return str(Digest.of(self.canonical_bytes()))

    @classmethod
    def from_document(cls, document: Any) -> ExternalRecoveryReceiptV1:
        if not isinstance(document, dict):
            raise SpecError("a recovery receipt must be a JSON object")
        missing = sorted(set(REQUIRED_RECEIPT_FIELDS) - set(document))
        if missing:
            raise SpecError(
                f"the recovery receipt is missing required field(s) {missing}. A "
                "document missing a field this version checks is one it cannot "
                "judge; treating the absence as satisfied is how a gate stops "
                "gating"
            )
        if str(document["schema"]) != EXTERNAL_RECEIPT_SCHEMA:
            raise SpecError(
                f"recovery receipt schema is {document['schema']!r}, expected "
                f"{EXTERNAL_RECEIPT_SCHEMA!r}"
            )
        identity_raw = document["dataset_identity"]
        executor_raw = document["executor"]
        if not isinstance(identity_raw, dict) or not isinstance(executor_raw, dict):
            raise SpecError(
                "dataset_identity and executor must each be an object; a bare "
                "string here is the free-text owner and the host-derived "
                "identity this contract refuses"
            )
        duration = int(document["restore_duration_seconds"])
        if duration < 0:
            raise SpecError("a restore duration cannot be negative")
        return cls(
            identity=DatasetIdentityV1(
                product=str(identity_raw.get("product", "")),
                dataset=str(identity_raw.get("dataset", "")),
                lineage=str(identity_raw.get("lineage", "")),
            ),
            descriptor_digest=str(document["descriptor_digest"]),
            snapshot_checksum=str(document["snapshot_checksum"]),
            snapshot_checksum_algorithm=str(document["snapshot_checksum_algorithm"]),
            executor=ExternalExecutorV1(
                kind=str(executor_raw.get("kind", "")),
                identifier=str(executor_raw.get("identifier", "")),
                version=str(executor_raw.get("version", "")),
                # SENTINEL, not a key. The key id lives OUTSIDE the signed
                # document — a document carrying its own key id would let a
                # forger nominate the key that verifies it — so there is
                # nothing here to read, and this type requires the field.
                #
                # Named rather than echoing the identifier, which is what this
                # line used to do: an echo READS like a real key id to anyone
                # inspecting `receipt.executor.key_id`, and a plausible-looking
                # wrong value is worse than an obviously absent one.
                # `accept_external_recovery_receipt` substitutes the DECLARED
                # executor before returning, so the sentinel never reaches a
                # caller through the accepted path.
                key_id=_UNATTRIBUTED_KEY,
            ),
            verifications=tuple(str(item) for item in document["verifications"]),
            isolated_target=bool(document["isolated_target"]),
            proved_at_epoch=int(document["proved_at_epoch"]),
            restore_duration_seconds=duration,
        )


def accept_external_recovery_receipt(
    payload: Any,
    *,
    identity: DatasetIdentityV1,
    descriptor_digest: str,
    executor: ExternalExecutorV1,
    required_verifications: Sequence[str],
    verifier: SignatureVerifier | None,
) -> ExternalRecoveryReceiptV1:
    """Accept a receipt for ``identity``, or refuse and name the failed property.

    ``payload`` is the envelope: ``{"document": {...}, "signature": ...,
    "key_id": ...}``. Signature and key id sit OUTSIDE the signed document on
    purpose — a document carrying its own key id lets a forger nominate the key
    that verifies it, and the declared executor's `key_id` is what makes that
    nomination worthless.

    Every expectation is DECLARED and passed in. A check derived from the
    document it judges compares the document with itself and passes for every
    input, which is the shape of a check that has stopped checking
    (`authorization.authorize` draws the same line about `target`).
    """
    if verifier is None:
        raise PreconditionFailed(
            "no signature verifier is installed, so this recovery receipt "
            "cannot be verified. Refusing rather than accepting it unchecked: "
            "an unverifiable document is not a document that passed, and "
            "degrading to trust when the verifier is missing is a bypass "
            "anyone can trigger by deleting configuration"
        )
    if not isinstance(payload, dict):
        raise SpecError("a recovery receipt envelope must be a JSON object")

    signature = str(payload.get("signature") or "")
    key_id = str(payload.get("key_id") or "")
    if not signature:
        raise PreconditionFailed(
            "the recovery receipt carries no signature. An unsigned file proves "
            "only that somebody could write to this directory — and the whole "
            "premise here is that this deployment did not observe the restore"
        )
    if key_id != executor.key_id:
        raise PreconditionFailed(
            f"the recovery receipt is signed by {key_id!r} and the declared "
            f"executor's key is {executor.key_id!r}. A valid signature from a "
            "stranger is still a stranger"
        )

    receipt = ExternalRecoveryReceiptV1.from_document(payload.get("document"))

    try:
        ok = verifier.verify(
            key_id=key_id, message=receipt.canonical_bytes(), signature=signature
        )
    except Exception as exc:
        raise PreconditionFailed(
            f"recovery receipt signature verification failed: {exc}"
        ) from exc
    if not ok:
        raise PreconditionFailed(
            "the recovery receipt signature does not verify over its canonical "
            "bytes. Either the document was edited after signing or it was "
            "signed by a different key than it claims"
        )

    # Content checks AFTER the signature, deliberately: refusing on content
    # first would let an attacker probe which values this facility accepts using
    # documents they never had to sign.
    if receipt.identity != identity:
        raise PreconditionFailed(
            f"the receipt proves a restore of {receipt.identity.as_document()}, "
            f"not of {identity.as_document()}. A proof about another dataset is "
            "not a proof about this one — and the lineage is what makes that "
            "comparison survive a failover or a change of supplier"
        )
    if receipt.descriptor_digest != descriptor_digest:
        raise PreconditionFailed(
            f"the receipt is bound to descriptor {receipt.descriptor_digest} and "
            f"the descriptor in hand is {descriptor_digest}. The declared roles, "
            "isolation invariants and migration heads a restore was checked "
            "against are exactly what changed"
        )
    if receipt.executor.kind != executor.kind:
        raise PreconditionFailed(
            f"the receipt names executor kind {receipt.executor.kind!r}, not "
            f"{executor.kind!r}"
        )
    if receipt.executor.identifier != executor.identifier:
        raise PreconditionFailed(
            f"the receipt names executor {receipt.executor.identifier!r}, not "
            f"the declared {executor.identifier!r}"
        )
    if receipt.executor.version != executor.version:
        raise PreconditionFailed(
            f"the receipt was produced by {executor.identifier} version "
            f"{receipt.executor.version!r} and the descriptor accepts "
            f"{executor.version!r}. A changed restore procedure is a different "
            "fact, not a newer copy of the same one"
        )
    if not receipt.isolated_target:
        raise PreconditionFailed(
            "the receipt does not claim an isolated target. A restore into "
            "anything the product can reach is not a rehearsal; it is a restore, "
            "and one typo away from being an outage"
        )
    if not receipt.snapshot_checksum.strip():
        raise PreconditionFailed(
            "the receipt carries no snapshot checksum, so it names no particular "
            "bytes. A proof that some snapshot restored is not a proof about the "
            "snapshot this deployment would fall back to"
        )
    missing = sorted(set(required_verifications) - set(receipt.verifications))
    if missing:
        raise PreconditionFailed(
            f"the receipt does not claim verification(s) {missing}, which this "
            f"dataset declares. Present-but-unverified is the state the whole "
            "fleet was in: "
            + "; ".join(
                f"{name} answers {VERIFICATION_EVIDENCE[name]}"
                for name in missing
                if name in VERIFICATION_EVIDENCE
            )
        )
    # Return the receipt carrying the DECLARED executor, whose `key_id` is real.
    # The parsed one holds the sentinel above, because a signed document does not
    # name its own key. Every other field of the declared executor has just been
    # compared against the document, so this substitutes a value that is equal
    # where it was checked and correct where the document was silent.
    return dataclasses.replace(receipt, executor=executor)


def backup_record_from_receipt(
    receipt: ExternalRecoveryReceiptV1,
    *,
    path: str,
    size_bytes: int,
) -> BackupRecord:
    """The writer `restore_proved_at_epoch` never had.

    `assess()` computes whether the newest proved restore is inside
    ``restore_proof_max_age_days``. It was correct and inert, because nothing
    produced a `BackupRecord` at :attr:`~.backup.Assurance.PROVED` carrying a
    timestamp — `restore_proved_at_epoch` was written by nothing in the entire
    package. An accepted receipt is exactly that fact, so this is where it
    becomes a record.

    :attr:`~.backup.ArtefactClass.RECOVERY_BUNDLE` is asserted here rather than
    defaulted, because `BackupRecord` refuses a `data_export` that claims
    RESTORABLE or PROVED — and an accepted receipt has already established the
    thing that refusal is protecting: a restore actually happened, into an
    isolated target, and the privilege surface was checked.
    """
    return BackupRecord(
        dataset=receipt.identity.dataset,
        path=path,
        size_bytes=size_bytes,
        checksum=receipt.snapshot_checksum,
        checksum_algorithm=receipt.snapshot_checksum_algorithm,
        completed_at_epoch=receipt.proved_at_epoch,
        assurance=Assurance.PROVED,
        restore_proved_at_epoch=receipt.proved_at_epoch,
        artefact_class=ArtefactClass.RECOVERY_BUNDLE,
        note=(
            f"externally proved by {receipt.executor.kind}:"
            f"{receipt.executor.identifier}@{receipt.executor.version} in "
            f"{receipt.restore_duration_seconds}s"
        ),
    )


def require_restore_proof(
    spec: ProductDeploymentSpec,
    dataset_code: str,
    records: Sequence[BackupRecord],
    *,
    now_epoch: int,
) -> str:
    """Refuse when the declared restore-proof window has lapsed. The CALLER.

    `assess()` had none. This is the one, and it is deliberately a REFUSAL
    rather than a report: a window that produces a warning nobody blocks on is
    the same artefact as no window, which is what the fleet had.

    The staleness half is reported and does not refuse here, because it is a
    different remedy on a different clock — a stale backup needs the schedule
    looked at; an unproved restore needs a rehearsal run. Collapsing them into
    one verdict tells a responder nothing, which is the distinction
    `BackupHealth` was built to keep.
    """
    dataset = _dataset(spec, dataset_code)
    health = assess(
        spec,
        dataset_code,
        records,
        now_epoch=now_epoch,
        expected_backup_interval_seconds=dataset.expected_backup_interval_seconds,
    )
    if health.restore_proof_overdue:
        age = health.restore_proof_age_seconds
        raise PreconditionFailed(
            f"dataset {dataset_code!r} has no proved restore inside its declared "
            f"{dataset.restore_proof_max_age_days}-day window "
            + (
                "— none has ever been recorded. "
                if age is None
                else f"— the newest is {age // SECONDS_PER_DAY} days old. "
            )
            + "An untested backup is a belief, and the moment its truth is "
            "established is always the worst possible one. Obtain a current "
            "signed RecoveryReceipt.v1 from the declared executor, or run a "
            "rehearsal"
        )
    proof_age = health.restore_proof_age_seconds or 0
    detail = (
        f"restore proved {proof_age // SECONDS_PER_DAY}d ago, inside the "
        f"{dataset.restore_proof_max_age_days}d window"
    )
    if health.stale:
        detail += (
            f"; NOTE the newest backup is {health.age_seconds}s old against a "
            f"{dataset.expected_backup_interval_seconds}s cadence"
        )
    return detail


def _dataset(spec: ProductDeploymentSpec, code: str) -> BackupDataset:
    for dataset in spec.backup_datasets:
        if dataset.code == code:
            return dataset
    raise SpecError(f"no backup dataset {code!r}", where=spec.source)
