"""``DeploymentTransitionReceipt.v1`` — verifying a two-sided recovery receipt.

## The D16 ruling this implements

Recovery needs a receipt that binds BOTH sides of a source-to-target
transition: the previous descriptor and migration heads it left from, the
target descriptor, heads and image digest it landed on, the backup id,
checksum and size the target was restored from, and the run identity that
performed it. Michael's ruling (D16) splits the work: `dotmac-deployment-control`
PRODUCES the receipt, in a later CP change. This module is only the
Foundation's half — a pure, product-agnostic, zero-dependency VERIFIER and the
closed schema it verifies against.

## Why the receipt type validates less than it looks like it should

:class:`TransitionReceiptV1` and its sub-shapes are containers with STRUCTURAL
invariants only: a descriptor digest is a real digest, migration heads are
sorted and unique, required strings are non-empty. They do not know what the
correct descriptor, heads, image or backup for a given deployment ARE — only
:func:`verify_transition_receipt` does, because that comparison needs the
descriptor (``spec``), the independently observed target state
(``observed_target_heads``), the chain's previous link (``previous_receipt``)
and the backup record. A type that could validate its own correctness against
nothing would always pass, which is why ``verify_transition_receipt`` exists as
a separate, pure function over all five inputs and returns a
:class:`TransitionVerdict` — never raises — naming every way the receipt
disagrees with the world, the same shape :func:`recovery.verify_recovery`
uses for the same reason: an operator who sees one refusal at a time repairs
one problem at a time.

## The head-duplicate distinction this module has to make that ``_do_verify_heads``
does not

`engine/run.py`'s ``_do_verify_heads`` compares two Python ``set``s, which is
correct for ITS job (heads either match or they do not) and would silently
absorb a duplicate if one existed, because a set cannot hold one. This module's
own receipt fields (:class:`TransitionSide.migration_heads`,
:class:`TargetSide.migration_heads`) are validated sorted-and-unique at
construction for exactly that reason: a duplicate in the receipt's OWN
declaration is refused before it can hide inside a set comparison. The
``observed_target_heads`` argument to :func:`verify_transition_receipt` is,
deliberately, a raw, untyped sequence — it is what a host actually reported,
and a host that reported a duplicate has told us something true about itself
that a silent cast to ``set`` would erase. So the target-heads check counts
duplicates in ``observed_target_heads`` explicitly, before ever comparing sets.

## The descriptor digest is not reinvented here

:meth:`spec.ProductDeploymentSpec.to_canonical_document` and that document's
``sha256_digest()`` are the Foundation's one answer to "what digest is this
descriptor". :func:`verify_transition_receipt` calls exactly that — it does
not hash the descriptor a second way.

## Why ``spec`` is untyped here, the same way it is in ``recovery.restore_plan``

``spec.py`` imports ``EXTERNAL_ONLY_VERIFICATIONS`` from ``recovery.py``, so a
module in this family that imported ``ProductDeploymentSpec`` back would risk
the same import cycle ``recovery.restore_plan`` was written to avoid. This
module takes the identical path: ``spec`` is accessed by attribute
(``spec.product``, ``spec.migration.expected_heads``,
``spec.to_canonical_document()``) rather than by import, so this module makes
no promise about which concrete type ``spec`` is beyond the shape it reads.

## The chain, and what "first receipt" means

A transition receipt's ``previous_receipt_digest`` is ``None`` for exactly the
first receipt in a chain, and a real digest for every other one. Both
directions are refused: a first receipt that names a previous one is claiming
a history it does not have, and a non-first receipt that names none is
claiming to be the start of a chain that already exists. Both refusals are
distinct finding codes for the same reason every other pair in this module is:
an operator debugging a broken chain needs to know WHICH end broke.
"""

from __future__ import annotations

import dataclasses
import json
import re
from collections.abc import Mapping, Sequence
from enum import Enum
from typing import Any, Final

from .backup import ArtefactClass, Assurance, BackupRecord
from .digest import Digest
from .errors import SpecError
from .secrets_guard import require_no_secrets

__all__ = [
    "TRANSITION_RECEIPT_SCHEMA",
    "TargetSide",
    "TransitionBackup",
    "TransitionFinding",
    "TransitionOutcome",
    "TransitionReceiptV1",
    "TransitionSide",
    "TransitionVerdict",
    "verify_transition_receipt",
]

TRANSITION_RECEIPT_SCHEMA: Final = "DeploymentTransitionReceipt.v1"

#: A git commit — 40 lowercase hex characters. Not a `Digest`: a source
#: revision names a commit, not a content hash of a known algorithm.
_REVISION = re.compile(r"^[0-9a-f]{40}$")


# ── small strict-parsing helpers, mirroring transition.py's own ────────────


def _required(value: str, *, where: str) -> str:
    text = str(value).strip()
    if not text:
        raise SpecError(f"{where} is required and cannot be empty")
    return text


def _str(value: object, *, where: str) -> str:
    if not isinstance(value, str):
        raise SpecError(f"{where} must be a string, got {type(value).__name__}")
    return value


def _int(value: object, *, where: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise SpecError(f"{where} must be an integer, got {type(value).__name__}")
    return value


def _mapping(value: object, *, where: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise SpecError(f"{where} must be an object")
    return value


def _strict(document: Mapping[str, Any], *, where: str, known: set[str]) -> None:
    unknown = sorted(set(document) - known)
    if unknown:
        raise SpecError(f"{where} has unknown field(s) {unknown}")
    missing = sorted(known - set(document))
    if missing:
        raise SpecError(f"{where} is missing required field(s) {missing}")


def _validated_heads(heads: Sequence[str], *, where: str) -> tuple[str, ...]:
    """Sorted and unique, or refuse. See the module docstring for why this is a
    construction-time invariant on the receipt's OWN declared heads, distinct
    from the raw ``observed_target_heads`` a verifier compares it with."""
    values = tuple(str(item) for item in heads)
    seen: set[str] = set()
    for value in values:
        if value in seen:
            raise SpecError(f"{where}: duplicate migration head {value!r}")
        seen.add(value)
    if list(values) != sorted(values):
        raise SpecError(f"{where}: migration heads must be sorted")
    return values


# ── the two sides of a transition ───────────────────────────────────────────


@dataclasses.dataclass(frozen=True, slots=True)
class TransitionSide:
    """A descriptor and the migration heads it was at, at one end of a hop."""

    descriptor_sha256: str
    migration_heads: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "descriptor_sha256",
            str(
                Digest.parse(
                    self.descriptor_sha256, where="transition_side.descriptor_sha256"
                )
            ),
        )
        object.__setattr__(
            self,
            "migration_heads",
            _validated_heads(
                self.migration_heads, where="transition_side.migration_heads"
            ),
        )

    def as_document(self) -> dict[str, Any]:
        return {
            "descriptor_sha256": self.descriptor_sha256,
            "migration_heads": list(self.migration_heads),
        }

    @classmethod
    def from_document(cls, value: object, *, where: str) -> TransitionSide:
        document = _mapping(value, where=where)
        _strict(document, where=where, known={"descriptor_sha256", "migration_heads"})
        heads = document["migration_heads"]
        if not isinstance(heads, list):
            raise SpecError(f"{where}.migration_heads must be a list")
        return cls(
            descriptor_sha256=_str(
                document["descriptor_sha256"], where=f"{where}.descriptor_sha256"
            ),
            migration_heads=tuple(
                _str(item, where=f"{where}.migration_heads[]") for item in heads
            ),
        )


@dataclasses.dataclass(frozen=True, slots=True)
class TargetSide:
    """The target of a transition: its descriptor, heads, and the image it runs.

    ``image_source_revision`` is deliberately NOT format-checked here. Its
    40-lowercase-hex invariant is a :class:`TransitionFinding` produced by
    :func:`verify_transition_receipt` (see the module docstring on why the
    receipt type validates less than it looks like it should), which is what
    lets a malformed revision be a named, testable REFUSAL rather than an
    exception that never reaches the verifier.
    """

    descriptor_sha256: str
    migration_heads: tuple[str, ...]
    image_digest: str
    image_source_revision: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "descriptor_sha256",
            str(
                Digest.parse(
                    self.descriptor_sha256, where="target_side.descriptor_sha256"
                )
            ),
        )
        object.__setattr__(
            self,
            "migration_heads",
            _validated_heads(self.migration_heads, where="target_side.migration_heads"),
        )
        object.__setattr__(
            self,
            "image_digest",
            str(Digest.parse(self.image_digest, where="target_side.image_digest")),
        )
        object.__setattr__(
            self,
            "image_source_revision",
            _required(
                self.image_source_revision, where="target_side.image_source_revision"
            ),
        )

    def as_document(self) -> dict[str, Any]:
        return {
            "descriptor_sha256": self.descriptor_sha256,
            "migration_heads": list(self.migration_heads),
            "image_digest": self.image_digest,
            "image_source_revision": self.image_source_revision,
        }

    @classmethod
    def from_document(cls, value: object, *, where: str) -> TargetSide:
        document = _mapping(value, where=where)
        known = {
            "descriptor_sha256",
            "migration_heads",
            "image_digest",
            "image_source_revision",
        }
        _strict(document, where=where, known=known)
        heads = document["migration_heads"]
        if not isinstance(heads, list):
            raise SpecError(f"{where}.migration_heads must be a list")
        return cls(
            descriptor_sha256=_str(
                document["descriptor_sha256"], where=f"{where}.descriptor_sha256"
            ),
            migration_heads=tuple(
                _str(item, where=f"{where}.migration_heads[]") for item in heads
            ),
            image_digest=_str(document["image_digest"], where=f"{where}.image_digest"),
            image_source_revision=_str(
                document["image_source_revision"],
                where=f"{where}.image_source_revision",
            ),
        )


@dataclasses.dataclass(frozen=True, slots=True)
class TransitionBackup:
    """The backup a target was restored from, as the receipt names it.

    ``bundle_digest`` is deliberately NOT run through :class:`Digest` — a
    :class:`~.backup.BackupRecord` checksum is not guaranteed to be a
    ``sha256:``-prefixed value (``backup_record_from_receipt`` carries whatever
    ``snapshot_checksum_algorithm`` an external executor declared), so forcing
    the receipt's shape to be narrower than the record it is compared against
    would make an honest match unrepresentable.
    """

    bundle_digest: str
    checksum_algorithm: str
    size_bytes: int
    bundle_id: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "bundle_digest",
            _required(self.bundle_digest, where="backup.bundle_digest"),
        )
        object.__setattr__(
            self,
            "checksum_algorithm",
            _required(self.checksum_algorithm, where="backup.checksum_algorithm"),
        )
        object.__setattr__(
            self, "bundle_id", _required(self.bundle_id, where="backup.bundle_id")
        )
        size = int(self.size_bytes)
        if size < 0:
            raise SpecError("backup.size_bytes cannot be negative")
        object.__setattr__(self, "size_bytes", size)

    def as_document(self) -> dict[str, Any]:
        return {
            "bundle_digest": self.bundle_digest,
            "checksum_algorithm": self.checksum_algorithm,
            "size_bytes": self.size_bytes,
            "bundle_id": self.bundle_id,
        }

    @classmethod
    def from_document(cls, value: object, *, where: str) -> TransitionBackup:
        document = _mapping(value, where=where)
        known = {"bundle_digest", "checksum_algorithm", "size_bytes", "bundle_id"}
        _strict(document, where=where, known=known)
        return cls(
            bundle_digest=_str(
                document["bundle_digest"], where=f"{where}.bundle_digest"
            ),
            checksum_algorithm=_str(
                document["checksum_algorithm"], where=f"{where}.checksum_algorithm"
            ),
            size_bytes=_int(document["size_bytes"], where=f"{where}.size_bytes"),
            bundle_id=_str(document["bundle_id"], where=f"{where}.bundle_id"),
        )


# ── the receipt itself ──────────────────────────────────────────────────────


@dataclasses.dataclass(frozen=True, slots=True)
class TransitionReceiptV1:
    """The two-sided binding D16 requires: source, target, backup, run identity.

    Immutable and closed by construction — see the sub-types above for what
    each carries. ``previous_receipt_digest`` is ``None`` only for the first
    receipt in a chain; :func:`verify_transition_receipt` is what refuses a
    mismatch in either direction.
    """

    product: str
    environment: str
    target: str
    run_id: str
    source: TransitionSide
    target_side: TargetSide
    backup: TransitionBackup
    previous_receipt_digest: str | None = None

    def __post_init__(self) -> None:
        for name in ("product", "environment", "target", "run_id"):
            object.__setattr__(
                self,
                name,
                _required(getattr(self, name), where=f"transition_receipt.{name}"),
            )
        if not isinstance(self.source, TransitionSide):
            raise SpecError("transition_receipt.source must be a TransitionSide")
        if not isinstance(self.target_side, TargetSide):
            raise SpecError("transition_receipt.target_side must be a TargetSide")
        if not isinstance(self.backup, TransitionBackup):
            raise SpecError("transition_receipt.backup must be a TransitionBackup")
        if self.previous_receipt_digest is not None:
            object.__setattr__(
                self,
                "previous_receipt_digest",
                str(
                    Digest.parse(
                        self.previous_receipt_digest,
                        where="transition_receipt.previous_receipt_digest",
                    )
                ),
            )

    def as_mapping(self) -> dict[str, Any]:
        """The canonical document. Belt: ``require_no_secrets`` runs over it —
        it cannot see a value shaped wrong, but it catches a permitted field
        carrying an impermissible one (see ``deployment_evidence``'s docstring
        for why neither check substitutes for the other)."""
        document: dict[str, Any] = {
            "schema": TRANSITION_RECEIPT_SCHEMA,
            "product": self.product,
            "environment": self.environment,
            "target": self.target,
            "run_id": self.run_id,
            "source": self.source.as_document(),
            "target_side": self.target_side.as_document(),
            "backup": self.backup.as_document(),
            "previous_receipt_digest": self.previous_receipt_digest,
        }
        require_no_secrets(document, source="transition receipt")
        return document

    def canonical_bytes(self) -> bytes:
        return json.dumps(
            self.as_mapping(), sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")

    def digest(self) -> Digest:
        return Digest.of(self.canonical_bytes())

    @classmethod
    def parse(cls, document: object) -> TransitionReceiptV1:
        """Strict parsing: unknown keys refused, types checked, no secrets."""
        mapping = _mapping(document, where=TRANSITION_RECEIPT_SCHEMA)
        known = {
            "schema",
            "product",
            "environment",
            "target",
            "run_id",
            "source",
            "target_side",
            "backup",
            "previous_receipt_digest",
        }
        _strict(mapping, where=TRANSITION_RECEIPT_SCHEMA, known=known)
        if mapping["schema"] != TRANSITION_RECEIPT_SCHEMA:
            raise SpecError(
                f"expected {TRANSITION_RECEIPT_SCHEMA!r}, got {mapping['schema']!r}. "
                "A reader of v1 refuses a document it does not understand rather "
                "than interpreting the fields it recognises"
            )
        require_no_secrets(dict(mapping), source="transition receipt")
        previous = mapping["previous_receipt_digest"]
        if previous is not None and not isinstance(previous, str):
            raise SpecError(
                "transition_receipt.previous_receipt_digest must be a string or null"
            )
        return cls(
            product=_str(mapping["product"], where="transition_receipt.product"),
            environment=_str(
                mapping["environment"], where="transition_receipt.environment"
            ),
            target=_str(mapping["target"], where="transition_receipt.target"),
            run_id=_str(mapping["run_id"], where="transition_receipt.run_id"),
            source=TransitionSide.from_document(
                mapping["source"], where="transition_receipt.source"
            ),
            target_side=TargetSide.from_document(
                mapping["target_side"], where="transition_receipt.target_side"
            ),
            backup=TransitionBackup.from_document(
                mapping["backup"], where="transition_receipt.backup"
            ),
            previous_receipt_digest=previous,
        )


# ── the verdict ──────────────────────────────────────────────────────────────


class TransitionOutcome(str, Enum):
    """What the verifier decided. Closed and small, like every other standing
    vocabulary in this package (see ``deployment_evidence.RunStanding``)."""

    VERIFIED = "verified"
    REFUSED = "refused"


class TransitionFinding(str, Enum):
    """Every way a transition receipt can disagree with the world, by name.

    A closed vocabulary rather than free text, for the same reason
    ``deployment_evidence`` closed ``failure`` and ``detail``: a finding an
    operator has to read a sentence to recognise is a finding a second reader
    interprets differently, and a caller that wants to react to ONE kind of
    failure (say, retry on a stale chain digest but page a human on a backup
    class mismatch) needs something to switch on other than prose.
    """

    CHAIN_DIGEST_MISMATCH = "chain_digest_mismatch"
    CHAIN_SOURCE_MISMATCH = "chain_source_mismatch"
    CHAIN_PREVIOUS_UNEXPECTED = "chain_previous_unexpected"
    CHAIN_PREVIOUS_MISSING = "chain_previous_missing"
    TARGET_HEADS_MISSING = "target_heads_missing"
    TARGET_HEADS_EXTRA = "target_heads_extra"
    TARGET_HEADS_DUPLICATE = "target_heads_duplicate"
    TARGET_DESCRIPTOR_MISMATCH = "target_descriptor_mismatch"
    IMAGE_DIGEST_MISMATCH = "image_digest_mismatch"
    IMAGE_REVISION_INVALID = "image_revision_invalid"
    BACKUP_NOT_RECOVERY_BUNDLE = "backup_not_recovery_bundle"
    BACKUP_ASSURANCE_TOO_LOW = "backup_assurance_too_low"
    BACKUP_DIGEST_MISMATCH = "backup_digest_mismatch"
    BACKUP_SIZE_MISMATCH = "backup_size_mismatch"
    PRODUCT_MISMATCH = "product_mismatch"


@dataclasses.dataclass(frozen=True, slots=True)
class TransitionVerdict:
    """Every way ``verify_transition_receipt`` found the receipt to disagree
    with the world. Empty findings means verified."""

    outcome: TransitionOutcome
    findings: tuple[TransitionFinding, ...]

    @property
    def verified(self) -> bool:
        return self.outcome is TransitionOutcome.VERIFIED


# ── the checks, one function per finding family ─────────────────────────────


def _check_chain(
    receipt: TransitionReceiptV1, previous_receipt: TransitionReceiptV1 | None
) -> list[TransitionFinding]:
    if previous_receipt is None:
        if receipt.previous_receipt_digest is not None:
            return [TransitionFinding.CHAIN_PREVIOUS_UNEXPECTED]
        return []
    if receipt.previous_receipt_digest is None:
        return [TransitionFinding.CHAIN_PREVIOUS_MISSING]
    findings: list[TransitionFinding] = []
    if Digest.parse(receipt.previous_receipt_digest) != previous_receipt.digest():
        findings.append(TransitionFinding.CHAIN_DIGEST_MISMATCH)
    previous_target = previous_receipt.target_side
    if (
        receipt.source.descriptor_sha256 != previous_target.descriptor_sha256
        or receipt.source.migration_heads != previous_target.migration_heads
    ):
        findings.append(TransitionFinding.CHAIN_SOURCE_MISMATCH)
    return findings


def _check_target_heads(
    receipt: TransitionReceiptV1, spec: Any, observed_target_heads: Sequence[str]
) -> list[TransitionFinding]:
    findings: list[TransitionFinding] = []
    observed_list = [str(head) for head in observed_target_heads]
    if len(set(observed_list)) != len(observed_list):
        findings.append(TransitionFinding.TARGET_HEADS_DUPLICATE)
    declared = set(receipt.target_side.migration_heads)
    expected = {str(head) for head in spec.migration.expected_heads}
    observed = set(observed_list)
    if (expected - declared) or (observed - declared):
        findings.append(TransitionFinding.TARGET_HEADS_MISSING)
    if (declared - expected) or (declared - observed):
        findings.append(TransitionFinding.TARGET_HEADS_EXTRA)
    return findings


def _check_target_descriptor(
    receipt: TransitionReceiptV1, spec: Any
) -> list[TransitionFinding]:
    computed = str(spec.to_canonical_document().sha256_digest())
    if receipt.target_side.descriptor_sha256 != computed:
        return [TransitionFinding.TARGET_DESCRIPTOR_MISMATCH]
    return []


def _check_image(
    receipt: TransitionReceiptV1, expected_image_digest: str
) -> list[TransitionFinding]:
    findings: list[TransitionFinding] = []
    expected = str(Digest.parse(expected_image_digest, where="expected_image_digest"))
    if receipt.target_side.image_digest != expected:
        findings.append(TransitionFinding.IMAGE_DIGEST_MISMATCH)
    if not _REVISION.match(receipt.target_side.image_source_revision):
        findings.append(TransitionFinding.IMAGE_REVISION_INVALID)
    return findings


def _check_backup(
    receipt: TransitionReceiptV1, backup_record: BackupRecord
) -> list[TransitionFinding]:
    findings: list[TransitionFinding] = []
    if backup_record.artefact_class is not ArtefactClass.RECOVERY_BUNDLE:
        findings.append(TransitionFinding.BACKUP_NOT_RECOVERY_BUNDLE)
    if backup_record.assurance.rank < Assurance.VERIFIED.rank:
        findings.append(TransitionFinding.BACKUP_ASSURANCE_TOO_LOW)
    if (
        backup_record.checksum != receipt.backup.bundle_digest
        or backup_record.checksum_algorithm != receipt.backup.checksum_algorithm
    ):
        findings.append(TransitionFinding.BACKUP_DIGEST_MISMATCH)
    if int(backup_record.size_bytes) != int(receipt.backup.size_bytes):
        findings.append(TransitionFinding.BACKUP_SIZE_MISMATCH)
    return findings


def _check_product(receipt: TransitionReceiptV1, spec: Any) -> list[TransitionFinding]:
    if receipt.product != str(spec.product):
        return [TransitionFinding.PRODUCT_MISMATCH]
    return []


def verify_transition_receipt(
    receipt: TransitionReceiptV1,
    *,
    spec: Any,
    observed_target_heads: Sequence[str],
    previous_receipt: TransitionReceiptV1 | None,
    backup_record: BackupRecord,
    expected_image_digest: str,
) -> TransitionVerdict:
    """Every way ``receipt`` disagrees with the world. Empty means verified.

    PURE: no I/O, no clock, no network. Every input is a value already in
    hand — ``spec`` is the parsed descriptor, ``observed_target_heads`` is
    whatever the caller already read off the target, ``previous_receipt`` is
    the prior link in the chain (or ``None`` for the first), and
    ``backup_record`` is the caller's own evidence about the backup the target
    was restored from. Returns findings rather than raising, driven by six
    independent checks, so an operator sees every way the receipt is wrong at
    once rather than one refusal per re-run.
    """
    findings: list[TransitionFinding] = []
    findings.extend(_check_chain(receipt, previous_receipt))
    findings.extend(_check_target_heads(receipt, spec, observed_target_heads))
    findings.extend(_check_target_descriptor(receipt, spec))
    findings.extend(_check_image(receipt, expected_image_digest))
    findings.extend(_check_backup(receipt, backup_record))
    findings.extend(_check_product(receipt, spec))
    outcome = TransitionOutcome.REFUSED if findings else TransitionOutcome.VERIFIED
    return TransitionVerdict(outcome=outcome, findings=tuple(findings))
