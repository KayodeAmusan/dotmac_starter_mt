"""Backup, restore rehearsal, and the difference between them.

Every product in the fleet backs up. No product in the fleet has ever proved a
restore. That asymmetry is the whole content of this module, and it is not a
detail: an untested backup is a belief, and the moment its truth is established
is always the worst possible one.

## What the sources actually verify — and a correction

An earlier version of this docstring said `pg_dump | gzip` reports gzip's exit
status, so a half-written dump passes. **That is wrong, and the correction is
worth keeping rather than quietly deleting.** All three scripts set `set -euo
pipefail`, and `pipefail` makes a pipeline return the rightmost non-zero status —
so a `pg_dump` that exits non-zero DOES fail the backup in every one of them.

| Product | What it establishes | What it does not |
|---|---|---|
| `dotmac_sub` | `pipefail`, non-empty check | integrity, restorability |
| `dotmac_erp` | `pipefail` + the `rclone` exit code | integrity, restorability |
| `dotmac_starter_mt` | `pipefail` + a non-empty check | integrity, restorability |
| `dotmac_integrator` | nothing — no backup exists | everything |

So the real gap is narrower than the retracted claim and still serious. What is
verified is **completion**: the command ran and exited zero. What is not
verified is anything after that — no checksum is recorded at write time, so
corruption during the write, the `rclone` transfer or a year on disk is
invisible; nothing decompresses the archive to prove it is readable end to end;
and **no product has ever restored one**. `dotmac_erp:scripts/restore_from_backup.py`
can restore; nothing runs it on a schedule and nothing records when a restore
last succeeded.

That is why the levels below start at COMPLETED rather than at "it ran": the
sources establish exactly the first level, and every claim a recovery plan
actually depends on lives above it.

## The four levels, deliberately named apart

1. **Completed** — the command exited zero. Says nothing about content.
2. **Verified** — the artefact is intact: expected magic bytes, a full
   decompression, and a checksum recorded at write time that still matches.
3. **Restorable** — it was actually restored into a disposable database.
4. **Proved** — the restored database was inspected: the expected schema is
   present, row counts are within tolerance, and the migration heads match.

Only (4) supports a recovery-point/recovery-time claim. `BackupRecord` keeps
the four apart so that a dashboard cannot report (1) as though it were (4),
which is exactly what "last backup: 2 hours ago" means today.

## What this module does NOT do

It runs no `pg_dump`, opens no socket and reads no credential. It computes the
POLICY — what to back up, how to verify it, whether the last proof is too old —
and the deployment host's `Effects` implementation performs it. That is what
lets the policy be exercised by tests, and a backup policy nobody exercises is
the same shape of problem as a backup nobody restores.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Final

from .errors import SpecError
from .spec import SECONDS_PER_DAY, BackupDataset, ProductDeploymentSpec

#: Re-exported from `spec`, which owns it now that a descriptor declares a
#: cadence in seconds. One definition, two names, no drift.
__all__ = [
    "SECONDS_PER_DAY",
    "ArtefactClass",
    "Assurance",
    "BackupEvidenceOrigin",
    "BackupHealth",
    "BackupRecord",
    "RestoreRehearsal",
    "VerificationPlan",
    "assess",
    "restore_rehearsal",
    "retention_keep",
    "verification_plan",
]


class ArtefactClass(str, Enum):
    """What a stored file actually IS, as distinct from how much is known about it.

    :class:`Assurance` answers "how far has this been checked". This answers a
    prior question that the fleet has been getting wrong by never asking it: a
    `pg_dump --dbname` archive is a **data export**. It carries rows and schema;
    it carries no role, and in three of the fleet's call sites no ownership or
    ACL either. Restoring one produces a database that looks recovered and is
    owned by whoever ran the restore, with every policy naming principals that
    do not exist.

    Calling that file a "backup" is the whole reason nothing in the fleet could
    be restored while every dashboard was green. So the two are different
    classes, not two grades of one thing, and :class:`BackupRecord` refuses to
    let a `data_export` climb past :attr:`Assurance.VERIFIED` — a verified data
    export is a genuine fact (the bytes are intact) and is still not something
    anybody can recover from.
    """

    DATA_EXPORT = "data_export"
    RECOVERY_BUNDLE = "recovery_bundle"


class Assurance(str, Enum):
    """How much is actually known about a backup.

    Ordered, and the ordering is used: a claim at one level never implies the
    level above it.
    """

    COMPLETED = "completed"
    VERIFIED = "verified"
    RESTORABLE = "restorable"
    PROVED = "proved"

    @property
    def rank(self) -> int:
        return _RANK[self]


_RANK: Final[dict[Assurance, int]] = {
    Assurance.COMPLETED: 0,
    Assurance.VERIFIED: 1,
    Assurance.RESTORABLE: 2,
    Assurance.PROVED: 3,
}


class BackupEvidenceOrigin(str, Enum):
    """Caller-attested origin of a record's backup evidence.

    An unspecified legacy record cannot establish a local artefact. LOCAL_ARTEFACT
    remains a caller assertion; this value does not authenticate bytes on disk.
    """

    UNSPECIFIED = "unspecified"
    LOCAL_ARTEFACT = "local_artefact"
    EXTERNAL_RECEIPT = "external_receipt"


@dataclass(frozen=True, slots=True)
class BackupRecord:
    """What is known about one backup artefact.

    ``checksum`` is recorded at WRITE time and re-computed at verification time.
    Computing it only at verification proves the file has not changed since the
    verifier read it, which is a fact about the last few milliseconds.
    """

    dataset: str
    path: str
    size_bytes: int
    checksum: str
    checksum_algorithm: str
    completed_at_epoch: int
    assurance: Assurance = Assurance.COMPLETED
    restore_proved_at_epoch: int | None = None
    note: str = ""
    artefact_class: ArtefactClass = ArtefactClass.DATA_EXPORT
    evidence_origin: BackupEvidenceOrigin = BackupEvidenceOrigin.UNSPECIFIED

    def __post_init__(self) -> None:
        """A data export cannot be restorable, and saying so is the point.

        The default is DATA_EXPORT rather than RECOVERY_BUNDLE because that is
        what every existing artefact in the fleet is, and a default that
        flattered the existing files would have quietly re-created the problem:
        the entire failure was a set of data exports labelled "backup" on a
        dashboard that showed them green.

        Climbing to RESTORABLE or PROVED therefore requires saying, explicitly,
        that this is a recovery bundle - at which point the bundle contract
        (`recovery.load_manifest`) decides whether it really is one.
        """
        if (
            self.artefact_class is ArtefactClass.DATA_EXPORT
            and self.assurance.rank >= Assurance.RESTORABLE.rank
        ):
            raise SpecError(
                f"{self.dataset!r} is labelled a data_export and claims "
                f"{self.assurance.value}. A `pg_dump --dbname` archive carries no "
                "role definitions, so restoring it produces a database owned by "
                "the restoring identity whose every policy names principals that "
                "do not exist - which is exactly the artefact that read as "
                "recovered. Only a recovery_bundle can be RESTORABLE or PROVED"
            )

    def at_least(self, level: Assurance) -> bool:
        return self.assurance.rank >= level.rank

    @property
    def is_recovery_bundle(self) -> bool:
        return self.artefact_class is ArtefactClass.RECOVERY_BUNDLE


@dataclass(frozen=True, slots=True)
class VerificationPlan:
    """What must be checked, for one dataset, before it counts as verified.

    Derived from the dataset declaration so that a product cannot verify less
    than it declared — the checks are not a suggestion the host may skip.
    """

    dataset: str
    checksum_algorithm: str
    require_non_empty: bool
    require_full_decompression: bool
    require_checksum_match: bool
    verifications: tuple[str, ...]

    def describe(self) -> str:
        parts = ["non-empty"] if self.require_non_empty else []
        if self.require_full_decompression:
            parts.append("decompresses fully")
        if self.require_checksum_match:
            parts.append(f"{self.checksum_algorithm} matches the write-time value")
        parts.extend(self.verifications)
        return ", ".join(parts)


def verification_plan(dataset: BackupDataset) -> VerificationPlan:
    """What ``dataset`` must pass to reach :attr:`Assurance.VERIFIED`.

    ``require_full_decompression`` and ``require_checksum_match`` are the two
    the sources do not have. `pipefail` already catches a `pg_dump` that exits
    non-zero; neither it nor a size check can see corruption that happened
    AFTER a clean exit — during the write, during an `rclone` transfer, or over
    a year on disk. Decompressing to `/dev/null` is cheap, reads every byte, and
    is the only check here that touches the whole artefact.
    """
    return VerificationPlan(
        dataset=dataset.code,
        checksum_algorithm=dataset.checksum,
        require_non_empty=True,
        require_full_decompression=True,
        require_checksum_match=True,
        verifications=dataset.verify,
    )


@dataclass(frozen=True, slots=True)
class RestoreRehearsal:
    """A disposable restore, and what it must establish to count as a proof.

    ``target_is_disposable`` is not decoration. A rehearsal that restores into
    anything a product can reach is not a rehearsal; it is a restore, and one
    typo away from being an outage. The host implementation must create the
    target and destroy it, and the name it uses has to say so — the same rule
    `dotmac_sub:AGENTS.md` applies to its integration database, which refuses a
    target whose name does not identify it as test data.
    """

    dataset: str
    target_is_disposable: bool
    verifications: tuple[str, ...]
    expected_migration_heads: tuple[str, ...]
    row_count_tolerance_pct: int = 5

    def describe(self) -> str:
        return (
            f"restore {self.dataset} into a disposable target and verify "
            f"{list(self.verifications)}"
            + (
                f", with heads {list(self.expected_migration_heads)}"
                if "migration_heads" in self.verifications
                else ""
            )
        )


def restore_rehearsal(
    spec: ProductDeploymentSpec, dataset_code: str
) -> RestoreRehearsal:
    dataset = _dataset(spec, dataset_code)
    if dataset.kind != "postgres":
        raise SpecError(
            f"dataset {dataset_code!r} is {dataset.kind!r}; a restore rehearsal is "
            "defined for a postgres dataset. An object store or volume needs its "
            "own proof, and pretending this one covers it would be worse than "
            "having none",
            where=spec.source,
        )
    return RestoreRehearsal(
        dataset=dataset.code,
        target_is_disposable=True,
        verifications=dataset.verify,
        expected_migration_heads=spec.migration.expected_heads,
    )


@dataclass(frozen=True, slots=True)
class BackupHealth:
    """Whether a dataset's backups are currently trustworthy.

    Three independent answers rather than one status, because the remedies
    differ: a stale backup needs the schedule looked at, an unverified one
    needs the verification path looked at, and an unproved one needs a
    rehearsal run. Collapsing them into "unhealthy" tells a responder nothing.
    """

    dataset: str
    age_seconds: int | None
    stale: bool
    unverified: bool
    restore_proof_age_seconds: int | None
    restore_proof_overdue: bool

    @property
    def healthy(self) -> bool:
        return not (self.stale or self.unverified or self.restore_proof_overdue)

    def problems(self) -> tuple[str, ...]:
        problems: list[str] = []
        if self.age_seconds is None:
            problems.append("no backup has ever been recorded")
        elif self.stale:
            problems.append(f"the newest backup is {self.age_seconds}s old")
        if self.unverified:
            problems.append(
                "the newest backup completed but was never verified — a "
                "truncated dump passes a size check"
            )
        if self.restore_proof_overdue:
            age = self.restore_proof_age_seconds
            problems.append(
                "no restore has been proved within the declared window"
                if age is None
                else f"the last proved restore was {age // SECONDS_PER_DAY} days ago"
            )
        return tuple(problems)


def assess(
    spec: ProductDeploymentSpec,
    dataset_code: str,
    records: Sequence[BackupRecord],
    *,
    now_epoch: int,
    expected_backup_interval_seconds: int = SECONDS_PER_DAY,
    stale_multiplier: int = 2,
) -> BackupHealth:
    """Assess one dataset's backups as of ``now_epoch``.

    ``expected_backup_interval_seconds`` carries the same name as the descriptor
    field that supplies it (`BackupDataset`). It used to be
    ``expected_interval_seconds`` — a second name for one control, and one the
    descriptor could not state at all, so every caller silently accepted the
    daily default whatever the product's real cadence was.

    ``stale_multiplier`` exists because a backup that is one interval old is
    normal — it is the one taken last night. Alerting at one interval pages
    every morning; alerting at two catches a schedule that has actually
    stopped.
    """
    dataset = _dataset(spec, dataset_code)
    mine = sorted(
        (record for record in records if record.dataset == dataset_code),
        key=lambda record: record.completed_at_epoch,
    )
    if not mine:
        return BackupHealth(
            dataset=dataset_code,
            age_seconds=None,
            stale=True,
            unverified=True,
            restore_proof_age_seconds=None,
            restore_proof_overdue=True,
        )
    newest = mine[-1]
    age = max(0, now_epoch - newest.completed_at_epoch)
    proofs = [
        record.restore_proved_at_epoch
        for record in mine
        if record.at_least(Assurance.PROVED)
        and record.restore_proved_at_epoch is not None
    ]
    proof_age = None if not proofs else max(0, now_epoch - max(proofs))
    window = dataset.restore_proof_max_age_days * SECONDS_PER_DAY
    return BackupHealth(
        dataset=dataset_code,
        age_seconds=age,
        stale=age > expected_backup_interval_seconds * stale_multiplier,
        unverified=not newest.at_least(Assurance.VERIFIED),
        restore_proof_age_seconds=proof_age,
        restore_proof_overdue=proof_age is None or proof_age > window,
    )


def retention_keep(
    spec: ProductDeploymentSpec,
    dataset_code: str,
    records: Sequence[BackupRecord],
    *,
    now_epoch: int,
) -> tuple[tuple[BackupRecord, ...], tuple[BackupRecord, ...]]:
    """Split ``records`` into (keep, prune) for one dataset.

    Three rules, and the last two are the ones a naive implementation misses:

    - Anything inside the declared retention window is kept.
    - **The newest PROVED bundle is kept regardless of age.** Pruning it because
      it aged out leaves the deployment with artefacts nobody has ever restored,
      which is the state this module exists to prevent. Retention policy must not
      be able to delete the only evidence that recovery has ever worked - and
      "regardless of age" is the whole clause: a rule that kept it only while it
      was recent would delete it precisely when it had become the sole survivor.
    - **A data export is kept until a newer PROVED bundle exists.** The fleet's
      existing dump files are data exports and not backups, and they are the only
      copy of the data that exists today. Deleting them on the strength of a
      retention window, before anything has been proved restorable, would trade a
      weak artefact for none at all. They age out once - and only once - there is
      something better and it has been PROVED.
    """
    dataset = _dataset(spec, dataset_code)
    horizon = now_epoch - dataset.retention_days * SECONDS_PER_DAY
    mine = sorted(
        (record for record in records if record.dataset == dataset_code),
        key=lambda record: record.completed_at_epoch,
        reverse=True,
    )
    proved = next(
        (record for record in mine if record.at_least(Assurance.PROVED)), None
    )
    keep: list[BackupRecord] = []
    prune: list[BackupRecord] = []
    for record in mine:
        if record.completed_at_epoch >= horizon or record is proved:
            keep.append(record)
        elif record.artefact_class is ArtefactClass.DATA_EXPORT and (
            proved is None or proved.completed_at_epoch <= record.completed_at_epoch
        ):
            # Held back deliberately: there is no newer proved bundle, so this
            # export - weak as it is - is the best thing standing between the
            # product and total loss.
            keep.append(record)
        else:
            prune.append(record)
    return tuple(keep), tuple(prune)


def _dataset(spec: ProductDeploymentSpec, code: str) -> BackupDataset:
    for dataset in spec.backup_datasets:
        if dataset.code == code:
            return dataset
    raise SpecError(f"no backup dataset {code!r}", where=spec.source)
