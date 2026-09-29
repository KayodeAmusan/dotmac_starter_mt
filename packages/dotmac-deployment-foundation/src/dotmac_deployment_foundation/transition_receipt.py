"""``DeploymentTransitionReceipt.v1`` — verifying a two-sided recovery receipt.

## The D16 ruling this implements

Recovery needs a receipt that binds BOTH sides of a source-to-target
transition: the previous descriptor and migration heads it left from, the
target descriptor, heads and image digest it landed on, the backup id,
checksum and size of the backup taken of the source before migration, and
the run identity that
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
a separate, pure function over its ten parameters (``receipt``, ``spec``,
``observed_target_heads``, ``previous_receipt``, ``genesis_source``,
``backup_record``, ``bundle_manifest``, ``observed_image_digest``,
``expected_run_id``, ``expected_target``) and returns a
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

## Why ``spec`` is untyped here even though this module does import ``spec.py``

This module imports ``spec.py`` for one concrete name
(``BackupDataset.CHECKSUMS`` — see :data:`_ALLOWED_CHECKSUM_ALGORITHMS``),
so the import-cycle argument that once justified keeping ``spec.py``
unimported no longer holds; ``external_recovery.py``, which this module also
imports, already imports ``spec.py`` at top level, and no cycle results.
``verify_transition_receipt``'s ``spec`` PARAMETER stays untyped (``Any``)
regardless, for a narrower reason than avoiding an import: this function's
contract is the SHAPE it reads off ``spec`` (``spec.product``,
``spec.environment``, ``spec.source_revision``, ``spec.image_digest``,
``spec.migration.expected_heads``, ``spec.to_canonical_document()``), not a
promise to accept exactly one concrete class — the same shape-typed
duck-typing :func:`recovery.restore_plan` uses ``spec: Any`` for.

## The chain, and what "first receipt" means

A transition receipt's ``previous_receipt_digest`` is ``None`` for exactly the
first receipt in a chain, and a real digest for every other one. Both
directions are refused: a first receipt that names a previous one is claiming
a history it does not have, and a non-first receipt that names none is
claiming to be the start of a chain that already exists. Both refusals are
distinct finding codes for the same reason every other pair in this module is:
an operator debugging a broken chain needs to know WHICH end broke.

## Genesis is anchored, never inferred

A first receipt's source cannot be verified by comparing it to a
``previous_receipt`` — there is none. The temptation is to treat "no
``previous_receipt``" as "trust the receipt's own ``source``", which would let
a chain start ANYWHERE the receipt claims, unverified. Instead the caller must
name where the chain starts by passing ``genesis_source`` — the descriptor and
heads the chain actually left from, established independently of the receipt —
and the verifier checks the receipt's ``source`` against it. Exactly one of
``previous_receipt`` and ``genesis_source`` is given for any one receipt: both
absent means "verify this against nothing", and both present is a caller that
cannot decide whether this is the first hop. Both are refused as
``CHAIN_ANCHOR_AMBIGUOUS`` rather than one silently winning.

## A chain is per product, environment and target

``previous_receipt`` links two receipts of the SAME transition history.
Product, environment and target identify which history that is; a receipt
whose product, environment or target differs from its predecessor's is not a
continuation of that chain, it is a different deployment that happens to name
the same previous digest — refused as ``CHAIN_SCOPE_MISMATCH``. Moving to a
different host is not a transition along the chain; it is the start of a new
one (via ``genesis_source``, not ``previous_receipt``).

## The receipt says less than the run that produced it

``run_id`` identifies the run that produced the receipt — not what the
descriptor says, but who is claiming to have done the work. A caller supplies
the run id it actually launched (``expected_run_id``) and the target it
actually launched onto (``expected_target``); a receipt naming a different run
or a different target is not evidence about the run or target the caller
cares about, no matter how well everything else in it checks out. A receipt
that reuses its predecessor's ``run_id`` (``RUN_ID_REUSED``) is claiming two
distinct hops happened under one run, which the run identity was supposed to
rule out.

## Relationship to ``transition.py``

:class:`~.transition.DatabaseTransitionV1` and
:class:`~.transition.DatabaseTransitionReceiptV1` are a DIFFERENT, narrower
receipt: one pre-authored database-descriptor transition
(``from_descriptor_digest`` → ``to_descriptor_digest``, optionally through
declared checkpoints) and the terminal evidence that one database's result and
descriptor promotion agree. This module's :class:`TransitionReceiptV1` is
broader and host-scoped rather than database-scoped: it binds a whole
deployment host's source-to-target hop — descriptor, migration heads, the
image it now runs, the backup taken of the source before migration, and the
run that did it —
so D16 recovery can verify a promotion or rollback across everything that
moved, not only the database. The two receipts are produced by different
actors for different questions and neither reads the other; a deployment that
uses both keeps them as separate, independently verifiable records.

## Canonical form (the golden vector this module is pinned to)

A receipt's digest is ``sha256`` over ``as_mapping()`` rendered with
``json.dumps(..., sort_keys=True, separators=(",", ":"), ensure_ascii=False)``:
keys sorted at every depth, no insignificant whitespace, and
``previous_receipt_digest`` present as JSON ``null`` for a genesis receipt
rather than omitted. ``ensure_ascii=False`` is deliberate and is kept exactly
as it is — it differs from :mod:`external_recovery`, which canonicalizes with
``ensure_ascii`` at its default (``True``); a cross-repo producer that hashes
the same document differently from either module produces a digest nothing
here will ever match, which is the entire point of pinning the exact
serialization in a golden-vector test rather than merely testing that
``parse`` and ``as_mapping`` round-trip.

## Parsing accepts canonical input only

``parse`` and the ``__post_init__`` of every sub-shape refuse a digest-shaped
field (a descriptor digest, the target image digest, the backup's
``manifest_digest``, or ``previous_receipt_digest``) that is not ALREADY
exactly ``sha256:`` followed by 64 lowercase hex characters, and refuse any
string field carrying leading or trailing whitespace. This module does not
silently normalize a differently-spelled digest into its canonical form the
way :class:`Digest` does for other callers (see ``digest.py``): a receipt is
evidence a chain of custody depends on, so accepting an uppercase or bare-hex
spelling here and rewriting it would let a byte-for-byte comparison against an
externally-signed or previously-hashed copy of the same receipt silently
diverge. A producer that emits anything else is refused at the boundary rather
than accommodated. :func:`verify_transition_receipt`'s
``observed_image_digest`` — not receipt content, but an external observation —
is held to the identical canonical rule (``OBSERVED_IMAGE_MALFORMED`` for
anything else), for the same reason: normalizing the caller's spelling before
comparing would hide the exact spelling drift a byte-for-byte match exists to
catch."""

from __future__ import annotations

import dataclasses
import json
import re
from collections.abc import Mapping, Sequence
from enum import Enum
from typing import Any, Final

from .backup import ArtefactClass, Assurance, BackupEvidenceOrigin, BackupRecord
from .digest import Digest
from .errors import SpecError
from .external_recovery import EXTERNAL_BACKUP_PATH_PREFIX
from .recovery import BundleComponent, load_manifest
from .secrets_guard import require_no_secrets
from .spec import BackupDataset

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

#: The one accepted spelling of a digest this module parses: `sha256:` plus 64
#: lowercase hex characters, exactly. See the module docstring's "Parsing
#: accepts canonical input only" for why this refuses rather than normalizes.
_CANONICAL_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")

#: The one allowed checksum-algorithm set, taken directly from
#: `BackupDataset.CHECKSUMS` (spec.py) rather than a hand-mirrored copy — see
#: the module docstring's "Why `spec` is untyped here" for why importing this
#: one name is safe despite `verify_transition_receipt`'s `spec` parameter
#: staying untyped.
_ALLOWED_CHECKSUM_ALGORITHMS: Final[tuple[str, ...]] = BackupDataset.CHECKSUMS

#: `bundle_digest`'s expected hex length, by algorithm — matches
#: `_ALLOWED_CHECKSUM_ALGORITHMS`. Existing producers (`external_recovery.py`,
#: this package's own tests) spell a checksum as BARE lowercase hex, the same
#: shape `Digest.hex` documents as "the shape Control's column holds" — never
#: `sha256:`-prefixed — so this checks bare hex of the right length rather
#: than inventing a new spelling.
_CHECKSUM_HEX_LENGTHS: Final[dict[str, int]] = {"sha256": 64, "sha512": 128}
_LOWERCASE_HEX = re.compile(r"^[0-9a-f]+$")


# ── small strict-parsing helpers, mirroring transition.py's own ────────────


def _str(value: object, *, where: str) -> str:
    if not isinstance(value, str):
        raise SpecError(f"{where} must be a string, got {type(value).__name__}")
    return value


def _required(value: object, *, where: str) -> str:
    text = _str(value, where=where)
    if text != text.strip():
        raise SpecError(f"{where} must not have leading or trailing whitespace")
    if not text:
        raise SpecError(f"{where} is required and cannot be empty")
    try:
        text.encode("utf-8")
    except UnicodeEncodeError as exc:
        # A lone surrogate survives `json.loads` and `ensure_ascii=False`, then
        # fails `canonical_bytes()`'s UTF-8 encode. Refusing it here keeps
        # "parse accepts" and "canonicalizes" the same set of documents.
        raise SpecError(f"{where} is not encodable as UTF-8") from exc
    return text


def _canonical_digest(value: object, *, where: str) -> str:
    """Refuse anything but ``sha256:`` + 64 lowercase hex. See the module
    docstring: this module does not normalize a differently-spelled digest."""
    text = _str(value, where=where)
    if text != text.strip():
        raise SpecError(f"{where} must not have leading or trailing whitespace")
    if not _CANONICAL_DIGEST.match(text):
        raise SpecError(
            f"{where}: {text!r} is not a canonical digest (sha256: followed by "
            "64 lowercase hex characters). This module parses canonical input "
            "only; fix the producer rather than relying on normalization here"
        )
    return text


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


def _validated_heads(heads: object, *, where: str) -> tuple[str, ...]:
    """Sorted and unique, or refuse. See the module docstring for why this is a
    construction-time invariant on the receipt's OWN declared heads, distinct
    from the raw ``observed_target_heads`` a verifier compares it with.

    A bare ``str``/``bytes`` is refused rather than iterated character-by-
    character (the classic gotcha of ``tuple(str(item) for item in "abc")``),
    and every element must already be a ``str`` — this constructs from
    already-typed data, so a non-string element is a caller bug, not a value
    to coerce. Each element is held to the same ``_required`` standard as
    every other string field on this receipt: no leading/trailing whitespace,
    not empty — a padded or empty "head" is not a real migration head and
    must be refused rather than silently accepted as a distinct value.
    """
    if isinstance(heads, str | bytes):
        raise SpecError(
            f"{where} must be a list of strings, not a bare {type(heads).__name__}"
        )
    if not isinstance(heads, Sequence):
        raise SpecError(f"{where} must be a list of strings")
    values: tuple[str, ...] = tuple(
        _required(item, where=f"{where}[]") for item in heads
    )
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
            _canonical_digest(
                self.descriptor_sha256, where="transition_side.descriptor_sha256"
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
            _canonical_digest(
                self.descriptor_sha256, where="target_side.descriptor_sha256"
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
            _canonical_digest(self.image_digest, where="target_side.image_digest"),
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
    """The backup taken of the SOURCE database before migration, as the
    receipt names it. It records recovery material; it claims no restore.

    For a RECOVERY_BUNDLE, the backup record's ``path`` and ``checksum`` name
    the bundle's ``database_dump`` archive file: its write-time checksum is
    what links it to the manifest's ``database_dump`` component. No producer
    in this package writes such a record yet; a producer must follow this
    contract.

    ``bundle_digest`` is deliberately NOT run through :class:`Digest`, and is
    NOT required to be canonical ``sha256:``-prefixed form the way the other
    digest-shaped fields on this receipt are — a :class:`~.backup.BackupRecord`
    checksum is not guaranteed to be a ``sha256:``-prefixed value
    (``backup_record_from_receipt`` carries whatever
    ``snapshot_checksum_algorithm`` an external executor declared), so forcing
    the receipt's shape to be narrower than the record it is compared against
    would make an honest match unrepresentable. It is still refused if it
    carries leading or trailing whitespace, and is compared to
    ``BackupRecord.checksum`` by exact string equality, unnormalized, alongside
    ``checksum_algorithm`` (see :func:`_check_backup`) — the same comparison
    this module always made, not a new one. It is the artefact's OWN checksum,
    nothing more — Michael's 2026-09-28 correction of an earlier ruling here
    that bound this field to the bundle manifest's digest, which made a real
    backup (whose recorded checksum is the write-time artefact checksum, not
    a manifest digest) unverifiable. A sha512 dataset still cannot verify a
    bundle-backed receipt: it is refused by name, because the manifest's
    component digests are sha256-only.

    ``manifest_digest`` is the separate field that carries the bundle
    manifest's own identity: a canonical ``sha256:`` digest, compared against
    ``RecoveryBundleManifestV1.sha256_digest()`` (see :func:`_check_backup`'s
    manifest section). The artefact (``bundle_digest``) is linked to that
    manifest through the manifest's own ``database_dump`` component digest,
    not by conflating the two digests into one field.

    ``bundle_id`` binds this receipt to a *specific* backup artefact.
    :class:`~.backup.BackupRecord` carries no id field of its own, so
    ``bundle_id`` is defined to be exactly the recorded artefact
    ``BackupRecord.path`` — the one field that already uniquely names which
    backup a record describes, PROVIDED the caller has attested that it is a
    local artefact. The path is an identifier, not proof of provenance. A
    record built by
    :func:`~.external_recovery.backup_record_from_receipt` does not: its one
    caller (`engine/run.py`) writes
    ``path=f"{EXTERNAL_BACKUP_PATH_PREFIX}{executor identifier}"`` — enforced
    by :func:`~.external_recovery.backup_record_from_receipt` itself as an
    additional guard — and ``size_bytes=max(1,
    restore_duration_seconds)``: a stand-in identifying WHICH EXECUTOR ran,
    and a byte count that is actually a duration in seconds, not a real
    artefact id and size. This module requires an explicit
    ``LOCAL_ARTEFACT`` evidence origin and refuses such a record
    (``BACKUP_RECORD_NOT_ARTEFACT_BOUND``) rather than let
    ``bundle_id``/``size_bytes`` agreement on those stand-in values be read
    as agreement on the backup itself. Verifying a transition whose backup
    was externally proved is a tracked follow-up, not silently accepted here.
    """

    bundle_digest: str
    checksum_algorithm: str
    size_bytes: int
    bundle_id: str
    manifest_digest: str

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
        object.__setattr__(
            self,
            "manifest_digest",
            _canonical_digest(self.manifest_digest, where="backup.manifest_digest"),
        )
        size = _int(self.size_bytes, where="backup.size_bytes")
        if size < 0:
            raise SpecError("backup.size_bytes cannot be negative")
        object.__setattr__(self, "size_bytes", size)

    def as_document(self) -> dict[str, Any]:
        return {
            "bundle_digest": self.bundle_digest,
            "checksum_algorithm": self.checksum_algorithm,
            "size_bytes": self.size_bytes,
            "bundle_id": self.bundle_id,
            "manifest_digest": self.manifest_digest,
        }

    @classmethod
    def from_document(cls, value: object, *, where: str) -> TransitionBackup:
        document = _mapping(value, where=where)
        known = {
            "bundle_digest",
            "checksum_algorithm",
            "size_bytes",
            "bundle_id",
            "manifest_digest",
        }
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
            manifest_digest=_str(
                document["manifest_digest"], where=f"{where}.manifest_digest"
            ),
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
                _canonical_digest(
                    self.previous_receipt_digest,
                    where="transition_receipt.previous_receipt_digest",
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

    CHAIN_ANCHOR_AMBIGUOUS = "chain_anchor_ambiguous"
    CHAIN_DIGEST_MISMATCH = "chain_digest_mismatch"
    CHAIN_SOURCE_MISMATCH = "chain_source_mismatch"
    CHAIN_SCOPE_MISMATCH = "chain_scope_mismatch"
    CHAIN_PREVIOUS_UNEXPECTED = "chain_previous_unexpected"
    CHAIN_PREVIOUS_MISSING = "chain_previous_missing"
    GENESIS_SOURCE_MISMATCH = "genesis_source_mismatch"
    RUN_ID_MISMATCH = "run_id_mismatch"
    RUN_ID_REUSED = "run_id_reused"
    ENVIRONMENT_MISMATCH = "environment_mismatch"
    TARGET_MISMATCH = "target_mismatch"
    TARGET_HEADS_DECLARED_VS_SPEC = "target_heads_declared_vs_spec"
    TARGET_HEADS_DECLARED_VS_OBSERVED = "target_heads_declared_vs_observed"
    TARGET_HEADS_DUPLICATE = "target_heads_duplicate"
    TARGET_DESCRIPTOR_MISMATCH = "target_descriptor_mismatch"
    IMAGE_DESCRIPTOR_MISMATCH = "image_descriptor_mismatch"
    IMAGE_DIGEST_MISMATCH = "image_digest_mismatch"
    OBSERVED_IMAGE_MALFORMED = "observed_image_malformed"
    IMAGE_REVISION_INVALID = "image_revision_invalid"
    IMAGE_REVISION_DESCRIPTOR_MISMATCH = "image_revision_descriptor_mismatch"
    BACKUP_NOT_RECOVERY_BUNDLE = "backup_not_recovery_bundle"
    BACKUP_ASSURANCE_TOO_LOW = "backup_assurance_too_low"
    BACKUP_ID_MISMATCH = "backup_id_mismatch"
    BACKUP_DIGEST_MISMATCH = "backup_digest_mismatch"
    BACKUP_DIGEST_MALFORMED = "backup_digest_malformed"
    BACKUP_ALGORITHM_UNSUPPORTED = "backup_algorithm_unsupported"
    BACKUP_DATASET_NOT_DECLARED = "backup_dataset_not_declared"
    BACKUP_ALGORITHM_NOT_DECLARED = "backup_algorithm_not_declared"
    BACKUP_SIZE_MISMATCH = "backup_size_mismatch"
    BACKUP_RECORD_NOT_ARTEFACT_BOUND = "backup_record_not_artefact_bound"
    BACKUP_MANIFEST_NOT_A_BUNDLE = "backup_manifest_not_a_bundle"
    BACKUP_MANIFEST_DIGEST_MISMATCH = "backup_manifest_digest_mismatch"
    BACKUP_MANIFEST_SCOPE_MISMATCH = "backup_manifest_scope_mismatch"
    BACKUP_ARTEFACT_NOT_IN_MANIFEST = "backup_artefact_not_in_manifest"
    BACKUP_ALGORITHM_NOT_BUNDLE_COMPATIBLE = "backup_algorithm_not_bundle_compatible"
    PRODUCT_MISMATCH = "product_mismatch"
    INPUT_NOT_CANONICALIZABLE = "input_not_canonicalizable"


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


def _check_run_identity(
    receipt: TransitionReceiptV1,
    expected_run_id: str,
    previous_receipt: TransitionReceiptV1 | None,
) -> list[TransitionFinding]:
    findings: list[TransitionFinding] = []
    if receipt.run_id != expected_run_id:
        findings.append(TransitionFinding.RUN_ID_MISMATCH)
    if previous_receipt is not None and previous_receipt.run_id == receipt.run_id:
        findings.append(TransitionFinding.RUN_ID_REUSED)
    return findings


def _check_scope(
    receipt: TransitionReceiptV1,
    spec: Any,
    expected_target: str,
    previous_receipt: TransitionReceiptV1 | None,
) -> list[TransitionFinding]:
    findings: list[TransitionFinding] = []
    if receipt.environment != spec.environment:
        findings.append(TransitionFinding.ENVIRONMENT_MISMATCH)
    if receipt.target != expected_target:
        findings.append(TransitionFinding.TARGET_MISMATCH)
    if previous_receipt is not None and (
        receipt.product != previous_receipt.product
        or receipt.environment != previous_receipt.environment
        or receipt.target != previous_receipt.target
    ):
        findings.append(TransitionFinding.CHAIN_SCOPE_MISMATCH)
    return findings


def _check_chain(
    receipt: TransitionReceiptV1,
    previous_receipt: TransitionReceiptV1 | None,
    genesis_source: TransitionSide | None,
) -> list[TransitionFinding]:
    if (previous_receipt is None) == (genesis_source is None):
        # Neither given (verify against nothing) or both given (the caller
        # cannot decide whether this is the first hop) are equally refused —
        # see the module docstring's "Genesis is anchored, never inferred".
        return [TransitionFinding.CHAIN_ANCHOR_AMBIGUOUS]

    if genesis_source is not None:
        findings: list[TransitionFinding] = []
        if receipt.previous_receipt_digest is not None:
            findings.append(TransitionFinding.CHAIN_PREVIOUS_UNEXPECTED)
        if receipt.source != genesis_source:
            findings.append(TransitionFinding.GENESIS_SOURCE_MISMATCH)
        return findings

    if previous_receipt is None:
        # Unreachable: the xor check above guarantees exactly one of
        # `previous_receipt`/`genesis_source` is set, and `genesis_source`
        # being set was just ruled out above by the `if genesis_source is not
        # None` branch returning. Stated as a real, named branch rather than
        # an `assert` (no asserts in src) so this stays a finding, never a
        # crash, even if that invariant is ever broken by a future edit.
        return [TransitionFinding.CHAIN_ANCHOR_AMBIGUOUS]

    findings = []
    if receipt.previous_receipt_digest is None:
        findings.append(TransitionFinding.CHAIN_PREVIOUS_MISSING)
    else:
        try:
            previous_digest = str(previous_receipt.digest())
        except (SpecError, UnicodeEncodeError):
            findings.append(TransitionFinding.INPUT_NOT_CANONICALIZABLE)
        else:
            if receipt.previous_receipt_digest != previous_digest:
                findings.append(TransitionFinding.CHAIN_DIGEST_MISMATCH)
    # Source-vs-previous-target is independent of whether a digest was named
    # at all -- report it too rather than stopping at CHAIN_PREVIOUS_MISSING,
    # per the "report every finding" rule.
    previous_target = previous_receipt.target_side
    if (
        receipt.source.descriptor_sha256 != previous_target.descriptor_sha256
        or receipt.source.migration_heads != previous_target.migration_heads
    ):
        findings.append(TransitionFinding.CHAIN_SOURCE_MISMATCH)
    return findings


def _check_target_heads(
    receipt: TransitionReceiptV1, spec: Any, observed_target_heads: object
) -> list[TransitionFinding]:
    findings: list[TransitionFinding] = []
    declared = set(receipt.target_side.migration_heads)
    # `spec.migration.expected_heads` is already `tuple[str, ...]` (parsed by
    # `Migration.parse`'s `table.str_list(...)`) -- no `str()` coercion needed.
    expected = set(spec.migration.expected_heads)
    # Declared-vs-spec needs neither `observed_target_heads` nor its shape, so
    # it still runs even when the observed side below is unusable.
    if declared != expected:
        findings.append(TransitionFinding.TARGET_HEADS_DECLARED_VS_SPEC)

    observed_list: list[str] | None = None
    if not (
        isinstance(observed_target_heads, str | bytes)
        or not isinstance(observed_target_heads, Sequence)
    ):
        collected: list[str] = []
        malformed = False
        for head in observed_target_heads:
            # Held to the same standard as a DECLARED head (`_required`): a
            # non-string, empty, or padded element is refused, not coerced.
            if not isinstance(head, str) or not head or head != head.strip():
                malformed = True
                break
            collected.append(head)
        if not malformed:
            observed_list = collected
    if observed_list is None:
        findings.append(TransitionFinding.INPUT_NOT_CANONICALIZABLE)
    else:
        if len(set(observed_list)) != len(observed_list):
            findings.append(TransitionFinding.TARGET_HEADS_DUPLICATE)
        observed = set(observed_list)
        if declared != observed:
            findings.append(TransitionFinding.TARGET_HEADS_DECLARED_VS_OBSERVED)
    return findings


def _check_target_descriptor(
    receipt: TransitionReceiptV1, spec: Any
) -> list[TransitionFinding]:
    try:
        computed = str(spec.to_canonical_document().sha256_digest())
    except SpecError:
        return [TransitionFinding.INPUT_NOT_CANONICALIZABLE]
    if receipt.target_side.descriptor_sha256 != computed:
        return [TransitionFinding.TARGET_DESCRIPTOR_MISMATCH]
    return []


def _check_image(
    receipt: TransitionReceiptV1, spec: Any, observed_image_digest: str
) -> list[TransitionFinding]:
    findings: list[TransitionFinding] = []
    if receipt.target_side.image_digest != spec.image_digest:
        findings.append(TransitionFinding.IMAGE_DESCRIPTOR_MISMATCH)
    try:
        # Canonical-only, like `parse()` -- see the module docstring's
        # "Parsing accepts canonical input only". `observed_image_digest` is
        # an external observation, not receipt content, but a caller who
        # normalizes an uppercase or bare-hex spelling before comparing would
        # hide the exact spelling drift a byte-for-byte match is supposed to
        # catch, so this refuses rather than normalizes too.
        observed = _canonical_digest(
            observed_image_digest, where="observed_image_digest"
        )
    except SpecError:
        findings.append(TransitionFinding.OBSERVED_IMAGE_MALFORMED)
    else:
        if receipt.target_side.image_digest != observed:
            findings.append(TransitionFinding.IMAGE_DIGEST_MISMATCH)
    if not _REVISION.match(receipt.target_side.image_source_revision):
        findings.append(TransitionFinding.IMAGE_REVISION_INVALID)
    if receipt.target_side.image_source_revision != spec.source_revision:
        findings.append(TransitionFinding.IMAGE_REVISION_DESCRIPTOR_MISMATCH)
    return findings


def _declared_dataset(spec: Any, code: str) -> Any | None:
    for dataset in spec.backup_datasets:
        if dataset.code == code:
            return dataset
    return None


def _check_backup(
    receipt: TransitionReceiptV1,
    spec: Any,
    backup_record: BackupRecord,
    bundle_manifest: object,
) -> list[TransitionFinding]:
    findings: list[TransitionFinding] = []

    # `BackupRecord` is a plain dataclass with no runtime type enforcement on
    # these fields (see backup.py), so a caller assembling one from external
    # data can hand this function anything. Each is checked before use, and
    # every comparison below that NEEDS a malformed field is skipped rather
    # than raising -- see the module docstring's "never raises" section.
    path_ok = isinstance(backup_record.path, str)
    assurance_ok = isinstance(backup_record.assurance, Assurance)
    artefact_class_ok = isinstance(backup_record.artefact_class, ArtefactClass)
    origin_ok = isinstance(backup_record.evidence_origin, BackupEvidenceOrigin)
    checksum_ok = isinstance(backup_record.checksum, str)
    dataset_ok = isinstance(backup_record.dataset, str)
    for ok in (
        path_ok,
        assurance_ok,
        artefact_class_ok,
        origin_ok,
        checksum_ok,
        dataset_ok,
    ):
        if not ok:
            findings.append(TransitionFinding.INPUT_NOT_CANONICALIZABLE)

    if artefact_class_ok and backup_record.artefact_class is not (
        ArtefactClass.RECOVERY_BUNDLE
    ):
        findings.append(TransitionFinding.BACKUP_NOT_RECOVERY_BUNDLE)
    # VERIFIED, not RESTORABLE (Michael's 2026-09-28 correction of the prior
    # ruling here, which conflated two distinct facts). Completeness -- that
    # the artefact is a whole recovery bundle, not merely intact bytes -- is
    # established below by BINDING the receipt to the bundle's own manifest
    # (see the manifest checks), not by the assurance level. VERIFIED is then
    # exactly the remaining claim this level is FOR: the bytes are intact.
    # A disposable restore (RESTORABLE and above) is a separate, stronger
    # proof this receipt does not make.
    if assurance_ok and backup_record.assurance.rank < Assurance.VERIFIED.rank:
        findings.append(TransitionFinding.BACKUP_ASSURANCE_TOO_LOW)
    if path_ok and receipt.backup.bundle_id != backup_record.path:
        findings.append(TransitionFinding.BACKUP_ID_MISMATCH)
    if checksum_ok and (
        backup_record.checksum != receipt.backup.bundle_digest
        or backup_record.checksum_algorithm != receipt.backup.checksum_algorithm
    ):
        findings.append(TransitionFinding.BACKUP_DIGEST_MISMATCH)
    if receipt.backup.checksum_algorithm not in _ALLOWED_CHECKSUM_ALGORITHMS:
        findings.append(TransitionFinding.BACKUP_ALGORITHM_UNSUPPORTED)
    expected_hex_length = _CHECKSUM_HEX_LENGTHS.get(receipt.backup.checksum_algorithm)
    if expected_hex_length is not None and (
        not _LOWERCASE_HEX.match(receipt.backup.bundle_digest)
        or len(receipt.backup.bundle_digest) != expected_hex_length
    ):
        findings.append(TransitionFinding.BACKUP_DIGEST_MALFORMED)
    record_size = backup_record.size_bytes
    if isinstance(record_size, bool) or not isinstance(record_size, int):
        findings.append(TransitionFinding.INPUT_NOT_CANONICALIZABLE)
    elif record_size != receipt.backup.size_bytes:
        findings.append(TransitionFinding.BACKUP_SIZE_MISMATCH)
    if dataset_ok:
        declared = _declared_dataset(spec, backup_record.dataset)
        if declared is None:
            findings.append(TransitionFinding.BACKUP_DATASET_NOT_DECLARED)
        elif (
            declared.checksum != receipt.backup.checksum_algorithm
            or declared.checksum != backup_record.checksum_algorithm
        ):
            findings.append(TransitionFinding.BACKUP_ALGORITHM_NOT_DECLARED)
    # This is caller-attested provenance, not independent authentication of
    # local bytes. Control's future producer must read and hash the local
    # bundle, bind its manifest and database dump, then call this pure verifier.
    if backup_record.evidence_origin is not BackupEvidenceOrigin.LOCAL_ARTEFACT or (
        path_ok and backup_record.path.startswith(EXTERNAL_BACKUP_PATH_PREFIX)
    ):
        findings.append(TransitionFinding.BACKUP_RECORD_NOT_ARTEFACT_BOUND)

    # The classification above (RECOVERY_BUNDLE) is a label on the RECORD; it
    # is not backed by anything until it is bound to the bundle's own
    # manifest. `load_manifest` is pure (JSON parsing only, no I/O) and is
    # the Foundation's one answer to "is this artefact a whole bundle" --
    # see its own docstring on why an incomplete bundle is refused on shape
    # rather than graded.
    if not isinstance(bundle_manifest, str | bytes):
        findings.append(TransitionFinding.INPUT_NOT_CANONICALIZABLE)
    else:
        # Every step below -- parsing, reading a property, hashing -- is
        # untrusted-input handling over a caller-supplied document, and every
        # one of these exception types is a real, reachable failure mode
        # (not merely a defensive guess): `load_manifest` raises `SpecError`
        # on a malformed document; a pathologically nested payload can blow
        # the parser's recursion limit (`RecursionError`) before `SpecError`
        # is even reached; `.sha256_digest()` re-encodes the content to UTF-8
        # and a lone surrogate in a string field raises `UnicodeEncodeError`
        # (a `ValueError` subclass, listed by name anyway for the same reason
        # the caller's instructions name it explicitly); and `TypeError`/
        # `ValueError` cover a shape this function's own checks below did not
        # anticipate. All of it becomes one finding, never a raise.
        try:
            manifest = load_manifest(bundle_manifest)
            manifest_product = manifest.content.get("product")
            manifest_heads_raw = manifest.content.get("migration_heads")
            if not isinstance(manifest_product, str):
                raise SpecError("manifest product must be a string")
            if not isinstance(manifest_heads_raw, list) or not all(
                isinstance(head, str) for head in manifest_heads_raw
            ):
                raise SpecError("manifest migration_heads must be a list of strings")
            manifest_heads = tuple(sorted(set(manifest_heads_raw)))
            manifest_digest = manifest.sha256_digest()
        except (
            SpecError,
            TypeError,
            ValueError,
            UnicodeEncodeError,
            RecursionError,
        ):
            findings.append(TransitionFinding.BACKUP_MANIFEST_NOT_A_BUNDLE)
        else:
            # The manifest's own identity is its canonical digest -- compared
            # against the receipt's separate `manifest_digest` field, NOT
            # `bundle_digest` (which stays bound to the artefact's own
            # write-time checksum, above). The digest is computed inside the
            # guard above, so a manifest that cannot be encoded is a finding.
            if receipt.backup.manifest_digest != manifest_digest:
                findings.append(TransitionFinding.BACKUP_MANIFEST_DIGEST_MISMATCH)
            # The artefact is linked to the manifest through the manifest's
            # own `database_dump` component digest -- the one piece of the
            # manifest that describes the actual dump bytes `bundle_digest`
            # is a checksum of. Every manifest component digest this
            # Foundation can express is `sha256` (`digest.ALGORITHMS` has no
            # other entry), so the link can only hold when the RECORD's own
            # checksum is also sha256; a sha512 (or any other) dataset is an
            # explicit, named refusal rather than an impossible comparison.
            if backup_record.checksum_algorithm != "sha256":
                findings.append(
                    TransitionFinding.BACKUP_ALGORITHM_NOT_BUNDLE_COMPATIBLE
                )
            elif checksum_ok:
                dump_digest = manifest.component_digest(BundleComponent.DATABASE_DUMP)
                if backup_record.checksum != dump_digest.hex:
                    findings.append(TransitionFinding.BACKUP_ARTEFACT_NOT_IN_MANIFEST)
            # The backup is of the SOURCE database, before this transition's
            # migration runs -- so it is `receipt.source`, not
            # `receipt.target_side`, that the manifest's own scope must agree
            # with.
            if (
                manifest_product != receipt.product
                or manifest_heads != receipt.source.migration_heads
            ):
                findings.append(TransitionFinding.BACKUP_MANIFEST_SCOPE_MISMATCH)
    return findings


def _check_product(receipt: TransitionReceiptV1, spec: Any) -> list[TransitionFinding]:
    if receipt.product != str(spec.product):
        return [TransitionFinding.PRODUCT_MISMATCH]
    return []


def _check_self_canonicalization(
    receipt: TransitionReceiptV1,
) -> list[TransitionFinding]:
    """A receipt built directly (not through :meth:`TransitionReceiptV1.parse`)
    never ran ``require_no_secrets`` at construction — only ``as_mapping()``
    runs it, on every call, and nothing in the checks above calls it. Without
    this check a directly-constructed receipt carrying a secret-shaped field
    (say, a ``bundle_id`` chosen to also satisfy ``BACKUP_ID_MISMATCH``) would
    verify clean. Catching ``SpecError`` here, the same family every other
    "cannot itself be canonicalized" check catches, closes that gap."""
    try:
        receipt.canonical_bytes()
    except (SpecError, UnicodeEncodeError):
        return [TransitionFinding.INPUT_NOT_CANONICALIZABLE]
    return []


def verify_transition_receipt(
    receipt: TransitionReceiptV1,
    *,
    spec: Any,
    observed_target_heads: Sequence[str],
    previous_receipt: TransitionReceiptV1 | None,
    backup_record: BackupRecord,
    bundle_manifest: str | bytes,
    observed_image_digest: str,
    expected_run_id: str,
    expected_target: str,
    genesis_source: TransitionSide | None = None,
) -> TransitionVerdict:
    """Every way ``receipt`` disagrees with the world. Empty means verified.

    PURE: no I/O, no clock, no network. Every input is a value already in
    hand — ``spec`` is the parsed descriptor, ``observed_target_heads`` is
    whatever the caller already read off the target, ``previous_receipt`` is
    the prior link in the chain, ``genesis_source`` is where the chain
    actually starts (exactly one of the two is given — see the module
    docstring's "Genesis is anchored, never inferred"), ``backup_record`` is
    the caller's own evidence about the backup taken of the source. Its
    ``LOCAL_ARTEFACT`` origin is an attestation, not independent authentication:
    Control's future producer must read and hash local bundle bytes and bind
    the manifest and database dump before calling this pure verifier.
    ``bundle_manifest`` is that backup's own recovery-bundle manifest
    document (see :func:`recovery.load_manifest`) — the caller's classification
    of the record as a ``RECOVERY_BUNDLE`` is a label; this is what backs it,
    ``observed_image_digest`` is what the caller actually observed running,
    and ``expected_run_id``/``expected_target`` are the run and target the
    caller actually launched. Never raises: every disagreement, including an
    input that cannot itself be canonicalized, becomes a
    :class:`TransitionFinding` rather than an exception, so an operator sees
    every way the receipt is wrong at once rather than one refusal per re-run.
    """
    findings: list[TransitionFinding] = []
    findings.extend(_check_self_canonicalization(receipt))
    findings.extend(_check_run_identity(receipt, expected_run_id, previous_receipt))
    findings.extend(_check_scope(receipt, spec, expected_target, previous_receipt))
    findings.extend(_check_chain(receipt, previous_receipt, genesis_source))
    findings.extend(_check_target_heads(receipt, spec, observed_target_heads))
    findings.extend(_check_target_descriptor(receipt, spec))
    findings.extend(_check_image(receipt, spec, observed_image_digest))
    findings.extend(_check_backup(receipt, spec, backup_record, bundle_manifest))
    findings.extend(_check_product(receipt, spec))
    outcome = TransitionOutcome.REFUSED if findings else TransitionOutcome.VERIFIED
    return TransitionVerdict(outcome=outcome, findings=tuple(findings))
