"""``RehearsalReceipt.v1`` — Lane 3's evidence, and the gate that reads it.

The exposure rehearsal used to be a prose table in
`docs/inventories/deployment-exposure-rehearsal.md`, hand-maintained. On
2026-08-29 its header said *"14 of 16 items CLOSED"* while the table three lines
below recorded four items **partial** and one **n/a**. Fourteen was reached by
counting those as closed, and nothing could catch it, because the summary and
the evidence were written by the same hand into the same file.

So the status document is now GENERATED from this receipt
(:func:`render_status_document`), and publication is gated on the receipt
(:func:`verify_publication`) rather than on the document. A hand-edited table
cannot make a release pass, and a receipt cannot contradict the count derived
from it.

## The status vocabulary is the whole design

Six statuses, and **exactly one of them satisfies publication**:

======================  ======================================================
`executed_passed`       the controller ran it and it passed — the ONLY pass
`executed_failed`       the controller ran it and it failed
`not_executed`          nothing ran it
`hand_measured`         a human measured it; supporting context, never a pass
`blocked`               a prerequisite is missing
`vacuous`               it ran but the fixture could not exercise it
======================  ======================================================

`hand_measured` and `vacuous` exist as their own statuses precisely because the
2026-08-29 count folded them into "closed". A hand-driven step proves the
OPERATOR can do it, not that the CODE can; a check whose fixture derives nothing
passes without observing anything. Naming them separately makes both visible in
the generated table instead of arithmetically invisible.
"""

from __future__ import annotations

import dataclasses
import ipaddress
import json
import re
from collections.abc import Mapping, Sequence
from enum import Enum
from typing import TYPE_CHECKING, Any, Final

from .authorization import ExecutionGrant
from .digest import Digest, require_same_digest
from .errors import SpecError
from .execution_plan_v3 import FoundationExecutionPlanV3
from .version import VERSION

if TYPE_CHECKING:  # pragma: no cover - typing only; engine.run is import-heavy
    from .engine.run import DeploymentOutcome

__all__ = [
    "REHEARSAL_RECEIPT_SCHEMA",
    "REHEARSAL_RECEIPT_V2_SCHEMA",
    "REQUIRED_ITEMS",
    "ExecutionRunBindingV1",
    "LaneThreeItem",
    "RehearsalReceiptV1",
    "RehearsalReceiptV2",
    "RequirementResult",
    "RequirementStatus",
    "build_receipt",
    "build_receipt_v2",
    "render_pending_document",
    "render_status_document",
    "require_execution_run",
    "require_rehearsed_artifact",
    "verify_publication",
]

REHEARSAL_RECEIPT_SCHEMA: Final = "RehearsalReceipt.v1"

#: The successor. A NEW schema name rather than new fields under v1: v1 has
#: crossed an artifact boundary in five built candidate wheels, and one schema
#: name identifying two contracts is the defect this package already paid for
#: once. See :func:`build_receipt_v2` for what v2 binds that v1 cannot.
REHEARSAL_RECEIPT_V2_SCHEMA: Final = "RehearsalReceipt.v2"

#: Lane 3 and only Lane 3. Lane 2 proves a real engine, database, ingress
#: handoff and restore loop; it says nothing about address-family exposure,
#: which is what this release is named after. A Lane 2 receipt offered here is
#: refused rather than credited — see `verify_publication`.
LANE: Final = 3


class RequirementStatus(str, Enum):
    """What actually happened to one gate item."""

    EXECUTED_PASSED = "executed_passed"
    EXECUTED_FAILED = "executed_failed"
    NOT_EXECUTED = "not_executed"
    HAND_MEASURED = "hand_measured"
    BLOCKED = "blocked"
    VACUOUS = "vacuous"

    @property
    def satisfies_publication(self) -> bool:
        return self is RequirementStatus.EXECUTED_PASSED


@dataclasses.dataclass(frozen=True, slots=True)
class LaneThreeItem:
    """One of the sixteen, as a declared member rather than a row in a table."""

    number: int
    code: str
    title: str
    #: Which host produces the evidence. Recorded so the generated document can
    #: group by it without a second, drifting list.
    evidence_from: str


#: The sixteen. Declared here ONCE; the generated document, the gate and the
#: runner all read this tuple, so an item cannot exist in one and not another.
REQUIRED_ITEMS: Final[tuple[LaneThreeItem, ...]] = (
    LaneThreeItem(
        1,
        "apply_under_lock",
        "Apply under the product deployment lock",
        "target",
    ),
    LaneThreeItem(
        2,
        "pre_change_snapshot",
        "Pre-change snapshot (HostObservation)",
        "target",
    ),
    LaneThreeItem(
        3,
        "non_recreating_refused",
        "A non-recreating apply is REFUSED",
        "target",
    ),
    LaneThreeItem(
        4,
        "socket_reobservation",
        "Socket re-observation, per family",
        "target",
    ),
    LaneThreeItem(
        5,
        "proxy_reobservation",
        "docker-proxy PID is NEW, host-ip correct",
        "target",
    ),
    LaneThreeItem(
        6,
        "firewall_reobservation",
        "Firewall rules land in the right chain, terminal DROP present",
        "target",
    ),
    LaneThreeItem(
        7,
        "inert_v6_chain",
        "The inert v6 DOCKER-USER chain, captured with a zero counter",
        "target",
    ),
    LaneThreeItem(
        8,
        "provoked_rollback",
        "Rollback, provoked rather than simulated",
        "target",
    ),
    LaneThreeItem(
        9,
        "digest_equality",
        "Descriptor == authorized plan == execution report",
        "target",
    ),
    LaneThreeItem(
        10,
        "none_emits_no_socket",
        'exposure = "none" emits no socket at all',
        "target",
    ),
    LaneThreeItem(
        11,
        "closed_port_behaviour",
        "The target's closed-port behaviour, recorded",
        "workstation",
    ),
    LaneThreeItem(
        12,
        "privileged_vantage_refused",
        "The privileged-vantage refusal fires on a real probe",
        "workstation",
    ),
    LaneThreeItem(
        13,
        "external_negative_v6",
        "IPv6 external negative against a RUNNING service",
        "probe",
    ),
    LaneThreeItem(
        14,
        "external_positive_v6",
        "IPv6 external positive control to THIS target",
        "probe",
    ),
    LaneThreeItem(
        15,
        "external_v4",
        "IPv4 external negative plus its positive control",
        "probe",
    ),
    LaneThreeItem(
        16,
        "private_from_source",
        "A private exposure reached from inside its source set",
        "probe",
    ),
)

_BY_CODE: Final[dict[str, LaneThreeItem]] = {item.code: item for item in REQUIRED_ITEMS}


@dataclasses.dataclass(frozen=True, slots=True)
class RequirementResult:
    """One item's outcome, with the evidence that produced it."""

    code: str
    status: RequirementStatus
    detail: str
    #: Free-form pointers to the bytes behind the claim — a log path, a command,
    #: an artifact name. Never a secret value.
    evidence: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.code not in _BY_CODE:
            raise SpecError(
                f"{self.code!r} is not one of the sixteen Lane 3 items "
                f"({sorted(_BY_CODE)}). A receipt cannot invent a requirement, "
                "because a gate that accepts unknown item codes can be "
                "satisfied by renaming a failure"
            )
        if not self.detail.strip():
            raise SpecError(
                f"item {self.code!r} carries no detail. A bare status is not "
                "evidence — the detail is what a reader checks the status against"
            )

    @property
    def item(self) -> LaneThreeItem:
        return _BY_CODE[self.code]

    def as_document(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "status": self.status.value,
            "detail": self.detail,
            "evidence": list(self.evidence),
        }


class _ReceiptReading:
    """Readers shared by every receipt schema, over ``self.content``.

    Holds no state of its own; each schema's dataclass owns its ``content``
    and its own parser, so a reader of one schema never interprets another.
    """

    __slots__ = ()
    content: dict[str, Any]

    def canonical_bytes(self) -> bytes:
        return json.dumps(
            self.content, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")

    def sha256_digest(self) -> str:
        return str(Digest.of(self.canonical_bytes()))

    @property
    def lane(self) -> int:
        return int(self.content["lane"])

    @property
    def foundation_revision(self) -> str:
        """The commit whose Lane 3 RUNNER drove this rehearsal.

        Not the commit the artifact was built from. Those are two questions and
        the receipt answers only this one; the other lives in the candidate's
        own ``CandidateArtifact.v1`` and is reached through
        :attr:`foundation_artifact_digest`.
        """
        return str(self.content["foundation_revision"])

    @property
    def foundation_artifact_digest(self) -> str:
        """The digest of the bytes this rehearsal actually executed.

        A READER for a field ``build_receipt`` has always written
        unconditionally — no document changes shape and no v1 receipt in
        existence lacks it. It is exposed because nothing could previously ASK
        the receipt which artifact it was about, so publication compared the
        revision and never the bytes.
        """
        return str(self.content["foundation_artifact_digest"])

    @property
    def results(self) -> tuple[RequirementResult, ...]:
        return tuple(
            RequirementResult(
                code=str(row["code"]),
                status=RequirementStatus(str(row["status"])),
                detail=str(row["detail"]),
                evidence=tuple(str(item) for item in row.get("evidence", ())),
            )
            for row in self.content["results"]
        )

    def result_for(self, code: str) -> RequirementResult:
        for result in self.results:
            if result.code == code:
                return result
        raise SpecError(f"the receipt carries no result for item {code!r}")


@dataclasses.dataclass(frozen=True, slots=True)
class RehearsalReceiptV1(_ReceiptReading):
    """The canonical, digest-bearing record of one Lane 3 execution.

    READABLE AS HISTORY. Its gate item 9 forces three caller-supplied digests
    equal, so its middle term can only ever be the descriptor digest, never the
    authorized ``ExecutionPlanDigestV1`` (``AGENTS.md`` rule 49). The release
    gate therefore reads :class:`RehearsalReceiptV2`.
    """

    content: dict[str, Any]

    @property
    def authorization_run_id(self) -> str:
        return str(self.content["authorization_run_id"])

    @classmethod
    def from_json(cls, payload: str | bytes) -> RehearsalReceiptV1:
        try:
            content = json.loads(payload)
        except ValueError as exc:
            raise SpecError(f"the receipt is not valid JSON: {exc}") from exc
        if not isinstance(content, dict):
            raise SpecError("a receipt is a JSON object")
        schema = content.get("schema")
        if schema != REHEARSAL_RECEIPT_SCHEMA:
            raise SpecError(
                f"expected {REHEARSAL_RECEIPT_SCHEMA}, got {schema!r}. A reader "
                "of v1 refuses a document it does not understand rather than "
                "interpreting unknown fields"
            )
        return cls(content=content)


def build_receipt(
    *,
    foundation_revision: str,
    foundation_artifact_digest: str,
    authorization_run_id: str,
    authorization_document_digest: str,
    descriptor_digest: str,
    execution_report_digest: str,
    fixture_digest: str,
    controller_identity: str,
    target: str,
    lease_id: str,
    probe_identity: str,
    started_at: str,
    finished_at: str,
    results: Sequence[RequirementResult],
) -> RehearsalReceiptV1:
    """Assemble a receipt, refusing anything that could not be checked later.

    The three-term digest equality (gate item 9) is enforced HERE, at
    construction, rather than being one more thing the runner is trusted to have
    done. A receipt that cannot be built is better than one that records a
    mismatch it did not notice.
    """
    for name, value in (
        ("foundation_revision", foundation_revision),
        ("authorization_run_id", authorization_run_id),
        ("controller_identity", controller_identity),
        ("target", target),
        ("lease_id", lease_id),
        ("probe_identity", probe_identity),
        ("started_at", started_at),
        ("finished_at", finished_at),
    ):
        if not str(value).strip():
            raise SpecError(
                f"{name} is empty. Every field on a receipt exists so a reader "
                "can go and check it; an empty one is an unverifiable claim"
            )
    revision = str(foundation_revision).strip().lower()
    if len(revision) != 40 or any(c not in "0123456789abcdef" for c in revision):
        raise SpecError(
            f"foundation_revision {foundation_revision!r} is not a full commit. "
            "A rehearsal is evidence about one exact revision or about nothing"
        )

    # Gate item 9, all THREE terms. Two matching terms cannot pass: the
    # authorized plan is the middle term, and without it the check degenerates
    # into "the report agrees with the descriptor it was generated from".
    agreed = require_same_digest(
        {
            "canonical_descriptor": descriptor_digest,
            "authorized_plan": authorization_document_digest,
            "controller_execution_report": execution_report_digest,
        },
        what="gate item 9 (digest equality)",
    )

    rows = _rows(results)

    content: dict[str, Any] = {
        "schema": REHEARSAL_RECEIPT_SCHEMA,
        "lane": LANE,
        "foundation_version": VERSION,
        "foundation_revision": revision,
        "foundation_artifact_digest": str(
            Digest.parse(foundation_artifact_digest, where="foundation_artifact_digest")
        ),
        "authorization_run_id": str(authorization_run_id).strip(),
        "authorization_document_digest": str(agreed),
        "descriptor_digest": str(agreed),
        "execution_report_digest": str(agreed),
        "fixture_digest": str(Digest.parse(fixture_digest, where="fixture_digest")),
        "controller_identity": str(controller_identity).strip(),
        "target": str(target).strip(),
        "lease_id": str(lease_id).strip(),
        "probe_identity": str(probe_identity).strip(),
        "started_at": str(started_at).strip(),
        "finished_at": str(finished_at).strip(),
        "results": rows,
    }
    return RehearsalReceiptV1(content=content)


def _rows(results: Sequence[RequirementResult]) -> list[dict[str, Any]]:
    """The sixteen rows, each exactly once, in item order — or a refusal."""
    seen: set[str] = set()
    rows: list[dict[str, Any]] = []
    for result in results:
        if result.code in seen:
            raise SpecError(
                f"item {result.code!r} appears twice in the receipt. Two rows "
                "for one item is how a failure hides behind a pass"
            )
        seen.add(result.code)
        rows.append(result.as_document())
    missing = sorted(set(_BY_CODE) - seen)
    if missing:
        raise SpecError(
            f"the receipt omits {missing}. Every one of the sixteen must carry "
            "an explicit status — an absent item is not an implicit pass, and "
            "silence is exactly how the previous count went wrong"
        )
    return sorted(rows, key=lambda row: _BY_CODE[str(row["code"])].number)


@dataclasses.dataclass(frozen=True, slots=True)
class ExecutionRunBindingV1:
    """The one workflow run that produced a receipt, by immutable coordinates.

    Repository ID, not name: a renamed or recreated repository keeps its name
    and changes its ID, so a name would let a receipt from a substitute
    repository pass as this one. Run ID and attempt, because a re-run attempt
    of one run is a different execution with a different outcome.

    A receipt that does not bind its run can be moved from the run that
    produced it to another run of the same revision — the publication oracle
    selects a RUN, and :func:`require_execution_run` is what makes the receipt
    it reads belong to that run rather than merely to that commit.
    """

    repository_id: int
    run_id: int
    run_attempt: int

    def __post_init__(self) -> None:
        for name in ("repository_id", "run_id", "run_attempt"):
            value = getattr(self, name)
            # `bool` is an `int`; `True` is not a run.
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise SpecError(
                    f"execution run {name} must be a positive integer, got "
                    f"{value!r}. A run named by anything else cannot be read "
                    "back from the oracle that selected it"
                )

    def as_document(self) -> dict[str, int]:
        return {
            "repository_id": self.repository_id,
            "run_id": self.run_id,
            "run_attempt": self.run_attempt,
        }


#: A topology-record reference: ``<record-key>@<version>``. The key names an
#: entry in the private topology record; the version is that record's version.
#: No dot, no colon, no slash — a hostname, an address or a path does not
#: parse, so a vantage cannot be written into a public receipt by accident.
_VANTAGE_REF: Final = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}@[1-9][0-9]{0,9}")

_V2_KEYS: Final = frozenset(
    {
        "schema",
        "lane",
        "foundation_version",
        "foundation_revision",
        "foundation_artifact_digest",
        "descriptor_digest",
        "execution_plan_digest",
        "executed_execution_plan_digest",
        "executed_descriptor_digest",
        "fixture_digest",
        "evidence_bundle_digest",
        "controller_identity",
        "target_id",
        "host_id",
        "lease_id",
        "probe_vantage_ref",
        "execution_run",
        "control_dispatch",
        "started_at",
        "finished_at",
        "results",
    }
)


def _require_not_an_address(name: str, value: str) -> None:
    """Refuse an IP literal where an opaque identifier belongs.

    Deliberately narrow. Fleet owns the ``host_id`` grammar (ADR-0073), so this
    module does not invent one; it refuses only the one shape that is never an
    identifier and always topology. A hostname is not caught here, and that
    region is stated rather than implied.
    """
    candidate = value.strip().strip("[]")
    try:
        ipaddress.ip_address(candidate)
    except ValueError:
        return
    raise SpecError(
        f"{name} {value!r} is an IP address. A Lane 3 receipt is published, and "
        "an address in it is topology in public; it carries the plan's opaque "
        "identifier instead"
    )


def _require_dispatch(dispatch: Any) -> None:
    """A Control dispatch coordinate: a non-empty ID and two positive counters."""
    if not isinstance(dispatch, dict) or set(dispatch) != {
        "dispatch_id",
        "execution_sequence",
        "attempt_no",
    }:
        raise SpecError(
            "control_dispatch carries exactly dispatch_id, execution_sequence "
            "and attempt_no"
        )
    if not isinstance(dispatch["dispatch_id"], str) or not dispatch["dispatch_id"]:
        raise SpecError("control_dispatch.dispatch_id is empty")
    for name in ("execution_sequence", "attempt_no"):
        value = dispatch[name]
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise SpecError(f"control_dispatch.{name} must be a positive integer")


@dataclasses.dataclass(frozen=True, slots=True)
class RehearsalReceiptV2(_ReceiptReading):
    """The Lane 3 receipt the release gate reads.

    What v2 binds that v1 cannot, each a field v1's frozen schema has no room
    for:

    - **Gate item 9 as a chain, not an equality.** The canonical descriptor
      digest, the AUTHORIZED ``ExecutionPlanDigestV1`` (the plan Control froze),
      and the executed outcome's own copies of both. v1 forced three
      caller-supplied digests equal, so its "authorized plan" could only ever be
      the descriptor digest restated.
    - **The bytes the plan authorized.** The plan's candidate wheel digest must
      be the artifact this rehearsal executed.
    - **Opaque target identity.** ``target_id`` and ``host_id`` are taken from
      the authorized plan, never from a caller, and an IP literal is refused.
    - **A private vantage, referenced.** ``probe_vantage_ref`` names a record
      key and version; the address stays in the record.
    - **The run that produced it** (:class:`ExecutionRunBindingV1`), and the
      one Control dispatch it executed (``control_dispatch``: dispatch ID,
      execution sequence, attempt), so a replayed execution or a moved receipt
      names a coordinate that does not match.
    - **The raw evidence, by digest.** ``evidence_bundle_digest`` is the digest
      of the evidence bundle exactly as published (encrypted, per the Lane 3
      design), so rows can point into it without the receipt carrying it.
    """

    content: dict[str, Any]

    @property
    def execution_plan_digest(self) -> str:
        return str(self.content["execution_plan_digest"])

    @property
    def execution_run(self) -> ExecutionRunBindingV1:
        run = self.content["execution_run"]
        return ExecutionRunBindingV1(
            repository_id=run["repository_id"],
            run_id=run["run_id"],
            run_attempt=run["run_attempt"],
        )

    @classmethod
    def from_json(cls, payload: str | bytes) -> RehearsalReceiptV2:
        try:
            content = json.loads(payload)
        except ValueError as exc:
            raise SpecError(f"the receipt is not valid JSON: {exc}") from exc
        if not isinstance(content, dict):
            raise SpecError("a receipt is a JSON object")
        schema = content.get("schema")
        if schema != REHEARSAL_RECEIPT_V2_SCHEMA:
            raise SpecError(
                f"expected {REHEARSAL_RECEIPT_V2_SCHEMA}, got {schema!r}. "
                + (
                    "A v1 receipt cannot carry the authorized execution plan "
                    "digest, so it is history, not publication evidence"
                    if schema == REHEARSAL_RECEIPT_SCHEMA
                    else "A reader of v2 refuses a document it does not "
                    "understand rather than interpreting unknown fields"
                )
            )
        keys = set(content)
        if keys != _V2_KEYS:
            raise SpecError(
                f"a {REHEARSAL_RECEIPT_V2_SCHEMA} carries exactly its declared "
                f"fields; missing {sorted(_V2_KEYS - keys)}, unknown "
                f"{sorted(keys - _V2_KEYS)}"
            )
        receipt = cls(content=content)
        # Re-derive every typed field so a hand-edited document is refused on
        # read rather than at the first property access.
        try:
            if not isinstance(content["execution_run"], dict):
                raise SpecError("execution_run is not an object")
            _ = receipt.execution_run
            _require_dispatch(content["control_dispatch"])
            _rows(receipt.results)
        except (KeyError, TypeError, ValueError) as exc:
            raise SpecError(f"the receipt is malformed: {exc}") from exc
        for name in ("target_id", "host_id"):
            _require_not_an_address(name, str(content[name]))
        if not _VANTAGE_REF.fullmatch(str(content["probe_vantage_ref"])):
            raise SpecError("probe_vantage_ref is not `<record-key>@<version>`")
        return receipt


def build_receipt_v2(
    *,
    foundation_revision: str,
    foundation_artifact_digest: str,
    descriptor_digest: str,
    execution_plan: FoundationExecutionPlanV3,
    grant: ExecutionGrant,
    execution_outcome: DeploymentOutcome,
    fixture_digest: str,
    evidence_bundle_digest: str,
    controller_identity: str,
    lease_id: str,
    probe_vantage_ref: str,
    execution_run: ExecutionRunBindingV1,
    started_at: str,
    finished_at: str,
    results: Sequence[RequirementResult],
) -> RehearsalReceiptV2:
    """Assemble a v2 receipt, refusing anything a reader could not check later.

    ## Gate item 9 is a chain of four comparisons

    1. The canonical descriptor this rehearsal loaded is the descriptor the
       plan was rendered from (``execution_plan.descriptor_digest``).
    2. The plan in hand is the plan Control froze: its ``digest()`` equals the
       ``ExecutionPlanDigestV1`` carried by ``grant``. The builder takes the
       :class:`ExecutionGrant` itself, which only ``authorize_v3()`` can issue
       from an attested Control pair, so the authorized digest cannot be a
       value the caller computed from an altered plan.
    3. The executed outcome reports that same authorized plan digest.
    4. The executed outcome reports that same descriptor digest.

    An empty outcome digest is refused rather than skipped: ``DeploymentOutcome``
    reports "not bound to an authorized plan" as empty precisely so that a
    consumer can refuse it. The plan's digest and the descriptor digest are
    different measurements of different documents, so equal values are refused
    too — that is the degenerate v1 shape arriving under a v2 name.

    ## Replay: the outcome executed THIS dispatch

    The outcome's ``execution_sequence`` and ``attempt_no`` must equal the
    grant's, and the receipt records the dispatch. Control consumes a dispatch
    once; a receipt that cites one is about that consumption and no other, and
    :func:`require_execution_run` ties it to one workflow run besides.

    ## The plan also names the bytes and the controller

    Its ``candidate_wheel_digest`` must be ``foundation_artifact_digest`` and its
    ``controller_ssh_fingerprint`` must be ``controller_identity``. A rehearsal
    of other bytes, or driven by another key, is not the rehearsal the plan
    authorized.
    """
    if not isinstance(execution_plan, FoundationExecutionPlanV3):
        raise SpecError(
            "build_receipt_v2 takes the authorized FoundationExecutionPlanV3 "
            f"itself, got {type(execution_plan).__name__}. A digest string in its "
            "place is a claim the receipt could not check"
        )
    if not isinstance(execution_run, ExecutionRunBindingV1):
        raise SpecError("execution_run must be an ExecutionRunBindingV1")
    if not isinstance(grant, ExecutionGrant):
        raise SpecError(
            "build_receipt_v2 takes the ExecutionGrant authorize_v3() issued, got "
            f"{type(grant).__name__}. An authorized digest from anywhere else is "
            "one the caller could have computed from an altered plan"
        )
    for name, value in (
        ("foundation_revision", foundation_revision),
        ("controller_identity", controller_identity),
        ("lease_id", lease_id),
        ("started_at", started_at),
        ("finished_at", finished_at),
    ):
        if not str(value).strip():
            raise SpecError(
                f"{name} is empty. Every field on a receipt exists so a reader "
                "can go and check it; an empty one is an unverifiable claim"
            )
    revision = str(foundation_revision).strip().lower()
    if len(revision) != 40 or any(c not in "0123456789abcdef" for c in revision):
        raise SpecError(
            f"foundation_revision {foundation_revision!r} is not a full commit. "
            "A rehearsal is evidence about one exact revision or about nothing"
        )
    if not _VANTAGE_REF.fullmatch(str(probe_vantage_ref)):
        raise SpecError(
            f"probe_vantage_ref {probe_vantage_ref!r} is not "
            "`<record-key>@<version>`. The vantage is named by its private "
            "record, never by an address or a hostname"
        )
    for name in ("target_id", "host_id"):
        _require_not_an_address(name, getattr(execution_plan, name))

    artifact = str(
        Digest.parse(foundation_artifact_digest, where="foundation_artifact_digest")
    )
    descriptor = str(Digest.parse(descriptor_digest, where="descriptor_digest"))
    authorized = str(
        Digest.parse(grant.execution_plan_digest, where="grant execution_plan_digest")
    )
    granted_descriptor = str(
        Digest.parse(grant.descriptor_digest, where="grant descriptor_digest")
    )
    rendered = str(Digest.parse(execution_plan.digest(), where="execution_plan"))

    # ── gate item 9 ────────────────────────────────────────────────────────
    if authorized == descriptor:
        raise SpecError(
            "gate item 9: the authorized execution plan digest equals the "
            "descriptor digest. They measure different documents, so equality "
            "means one was substituted for the other — the degenerate v1 shape"
        )
    plan_descriptor = str(
        Digest.parse(execution_plan.descriptor_digest, where="plan descriptor_digest")
    )
    if plan_descriptor != descriptor:
        raise SpecError(
            f"gate item 9: the plan was rendered from descriptor {plan_descriptor} "
            f"and this rehearsal loaded {descriptor}"
        )
    if granted_descriptor != descriptor:
        raise SpecError(
            f"the grant authorizes descriptor {granted_descriptor} and this "
            f"rehearsal loaded {descriptor}"
        )
    if grant.target != execution_plan.target:
        raise SpecError(
            "the grant authorizes another target than the plan names; an "
            "approval for one target does not authorize another"
        )
    if rendered != authorized:
        raise SpecError(
            f"gate item 9: the plan in hand digests to {rendered} and the "
            f"authorized plan is {authorized}. Only the plan Control froze is "
            "the authorized plan"
        )
    executed: dict[str, str] = {}
    for name in ("execution_plan_digest", "descriptor_digest"):
        value = str(getattr(execution_outcome, name, "") or "").strip()
        if not value:
            raise SpecError(
                f"gate item 9: the execution outcome reports no {name}. An "
                "outcome not bound to an authorized plan is reported as empty "
                "so that it can be refused, and it is"
            )
        executed[name] = str(Digest.parse(value, where=f"executed {name}"))
    if executed["execution_plan_digest"] != authorized:
        raise SpecError(
            f"gate item 9: the outcome executed plan "
            f"{executed['execution_plan_digest']} and the authorized plan is "
            f"{authorized}"
        )
    if executed["descriptor_digest"] != descriptor:
        raise SpecError(
            f"gate item 9: the outcome executed descriptor "
            f"{executed['descriptor_digest']} and this rehearsal loaded "
            f"{descriptor}"
        )

    # ── replay: the outcome is the execution of THIS dispatch ──────────────
    for name in ("execution_sequence", "attempt_no"):
        if getattr(execution_outcome, name, 0) != getattr(grant, name):
            raise SpecError(
                f"the outcome reports {name} "
                f"{getattr(execution_outcome, name, 0)!r} and the grant was "
                f"issued for {getattr(grant, name)!r}. An execution of another "
                "dispatch, or a replay of this one, is not this rehearsal"
            )

    # ── the plan names the bytes and the controller ────────────────────────
    planned_wheel = str(
        Digest.parse(
            execution_plan.candidate_wheel_digest, where="plan candidate_wheel_digest"
        )
    )
    if planned_wheel != artifact:
        raise SpecError(
            f"the plan authorized candidate {planned_wheel} and this rehearsal "
            f"executed {artifact}. A rehearsal of other bytes is not the one "
            "the plan authorized"
        )
    controller = str(controller_identity).strip()
    if execution_plan.controller_ssh_fingerprint != controller:
        raise SpecError(
            f"the plan binds controller {execution_plan.controller_ssh_fingerprint} "
            f"and this rehearsal was driven by {controller}"
        )

    rows = _rows(results)
    content: dict[str, Any] = {
        "schema": REHEARSAL_RECEIPT_V2_SCHEMA,
        "lane": LANE,
        "foundation_version": VERSION,
        "foundation_revision": revision,
        "foundation_artifact_digest": artifact,
        "descriptor_digest": descriptor,
        "execution_plan_digest": authorized,
        "executed_execution_plan_digest": executed["execution_plan_digest"],
        "executed_descriptor_digest": executed["descriptor_digest"],
        "fixture_digest": str(Digest.parse(fixture_digest, where="fixture_digest")),
        "evidence_bundle_digest": str(
            Digest.parse(evidence_bundle_digest, where="evidence_bundle_digest")
        ),
        "controller_identity": controller,
        "target_id": execution_plan.target_id,
        "host_id": execution_plan.host_id,
        "lease_id": str(lease_id).strip(),
        "probe_vantage_ref": str(probe_vantage_ref),
        "execution_run": execution_run.as_document(),
        "control_dispatch": {
            "dispatch_id": str(grant.receipt.dispatch_id),
            "execution_sequence": grant.execution_sequence,
            "attempt_no": grant.attempt_no,
        },
        "started_at": str(started_at).strip(),
        "finished_at": str(finished_at).strip(),
        "results": rows,
    }
    return RehearsalReceiptV2(content=content)


def require_execution_run(
    receipt: RehearsalReceiptV2, *, run: ExecutionRunBindingV1
) -> None:
    """Refuse unless this receipt was produced by exactly ``run``.

    The publication oracle selects ONE run — newest-then-check — and then reads
    a receipt. Without this, the receipt it reads need only be about the same
    commit, so a receipt produced by an earlier, passing run could stand in for
    the selected run that failed. A separate function, like
    :func:`require_rehearsed_artifact`, so its absence is visible in the gate.
    """
    if not isinstance(receipt, RehearsalReceiptV2):
        raise SpecError(
            "only a RehearsalReceipt.v2 binds the run that produced it; a v1 "
            "receipt cannot be tied to the run the oracle selected"
        )
    if receipt.execution_run != run:
        raise SpecError(
            f"the receipt was produced by run {receipt.execution_run.as_document()} "
            f"and the oracle selected {run.as_document()}. A receipt from another "
            "run says nothing about the run that was selected"
        )


def require_rehearsed_artifact(
    receipt: RehearsalReceiptV1 | RehearsalReceiptV2, *, artifact_digest: str
) -> None:
    """Refuse unless this receipt is about the BYTES in hand.

    ## The gap this closes

    :func:`verify_publication` compares the LANE 3 RUNNER revision with the
    RELEASE revision and every item's status. It does not — and cannot — say
    which artifact the run executed, so a publication of one candidate was
    satisfied by a rehearsal of a different one, provided both ran at the same
    commit. Two candidate versions rehearsed from one protected-main SHA is not
    a hypothetical shape: the rehearsal workflow takes ``candidate_version`` as
    a dispatch input precisely so that it can.

    ## Why this is the binding that makes the THIRD revision real

    The candidate source revision lives in the committed
    ``CandidateArtifact.v1`` and never enters the receipt. That is deliberate:
    ``RehearsalReceipt.v1`` has crossed an artifact boundary in five built
    candidate wheels, and adding a field to it would make one schema name
    identify two contracts — the defect this package already paid for once.

    So the candidate source revision is bound TRANSITIVELY and provably rather
    than by widening a shipped record: this digest identifies exactly one
    ``CandidateArtifact.v1``, and that receipt names exactly one ``source_sha``.
    Assert the digest and the source revision follows; assert nothing and the
    source revision is a value in a file that no gate ever consults.

    Separate from :func:`verify_publication` rather than a parameter on it, and
    the difference is not cosmetic. A keyword with a default is a check the
    caller may omit and nobody will notice; a second function the release gate
    must CALL is a check whose absence is visible in the gate's own source.
    """
    wanted = str(Digest.parse(artifact_digest, where="artifact_digest"))
    if receipt.foundation_artifact_digest != wanted:
        raise SpecError(
            f"the receipt records a rehearsal of "
            f"{receipt.foundation_artifact_digest} and the artifact in hand is "
            f"{wanted}. A rehearsal of other bytes says nothing about these "
            "ones — and because the digest is what identifies the candidate "
            "receipt, it is also what names the revision they were built from"
        )


def verify_publication(
    receipt: RehearsalReceiptV1 | RehearsalReceiptV2, *, revision: str
) -> None:
    """Refuse publication unless EVERY item is `executed_passed` at `revision`.

    Three refusals, in the order a reader would ask them.

    **Lane.** A Lane 2 receipt is refused outright rather than counted. Lane 2
    is a real and valuable proof of a different thing; substituting it here
    would be the "green preflight reads as attested" failure with two lanes
    instead of two gates.

    **Revision.** Evidence from another commit is evidence about another commit.

    **Every item, executed and passed.** No `partial`, no `not_applicable`, no
    `hand_measured`, no `vacuous`, no missing row. The statuses are enumerated
    in the refusal so the operator sees which ones and why, rather than a count.
    """
    if receipt.lane != LANE:
        raise SpecError(
            f"this is a Lane {receipt.lane} receipt and publication requires "
            f"Lane {LANE}. Lane 2 proves a real engine, database and restore "
            "loop; it does not watch an IPv6 socket refuse the internet, which "
            "is the property this release is named after"
        )
    wanted = str(revision).strip().lower()
    if receipt.foundation_revision != wanted:
        raise SpecError(
            f"the receipt is for {receipt.foundation_revision} and the release "
            f"is {wanted}. A rehearsal that passed on another commit says "
            "nothing about this one"
        )
    unsatisfied = [
        result for result in receipt.results if not result.status.satisfies_publication
    ]
    if unsatisfied:
        detail = "; ".join(
            f"{result.item.number} {result.code}={result.status.value}"
            for result in sorted(unsatisfied, key=lambda r: r.item.number)
        )
        raise SpecError(
            f"{len(unsatisfied)} of {len(REQUIRED_ITEMS)} Lane 3 items are not "
            f"`executed_passed`: {detail}. Only a controller-driven pass "
            "satisfies publication — a hand measurement proves the operator can "
            "do it, and a vacuous check observed nothing"
        )


def _table(rows: Mapping[str, tuple[RequirementStatus, str]]) -> list[str]:
    """The sixteen rows plus their tally, derived from ONE mapping.

    Shared by the receipt renderer and the pending renderer so the two can
    never disagree about what the items are or how they are counted — which is
    precisely the failure the generated document exists to prevent.
    """
    lines = [
        "| # | Item | Evidence from | Status | Detail |",
        "|---|---|---|---|---|",
    ]
    tally: dict[str, int] = {}
    for item in REQUIRED_ITEMS:
        status, detail = rows[item.code]
        tally[status.value] = tally.get(status.value, 0) + 1
        mark = "**PASS**" if status.satisfies_publication else status.value
        lines.append(
            f"| {item.number} | {item.title} | {item.evidence_from} | "
            f"{mark} | {detail} |"
        )
    lines.extend(["", "## Tally", ""])
    for status in RequirementStatus:
        lines.append(f"- `{status.value}`: {tally.get(status.value, 0)}")
    passed = tally.get(RequirementStatus.EXECUTED_PASSED.value, 0)
    total = len(REQUIRED_ITEMS)
    lines.extend(
        [
            "",
            f"**Publication requires all {total} to be `executed_passed`.** "
            + (
                "This receipt satisfies it."
                if passed == total
                else f"This does not: {total - passed} item(s) short."
            ),
            "",
        ]
    )
    return lines


def render_pending_document(
    rows: Mapping[str, tuple[RequirementStatus, str]], *, reason: str
) -> str:
    """The status table for a state where NO Lane 3 receipt exists yet.

    A receipt cannot be constructed before an authorization exists — gate item
    9 binds three terms and the middle one is the authorized plan, so
    `build_receipt` refuses. That refusal is correct and it leaves a gap: the
    repository still owes a truthful status document in the meantime.

    This renders one, through the same item list and the same tally as the
    receipt renderer, so the pre-execution document cannot drift from the
    post-execution one or contradict its own rows.
    """
    missing = sorted(set(_BY_CODE) - set(rows))
    if missing:
        raise SpecError(
            f"the pending document omits {missing}. Every one of the sixteen "
            "carries an explicit status — an absent item is not an implicit pass"
        )
    passed = sum(1 for status, _ in rows.values() if status.satisfies_publication)
    lines = [
        "<!-- GENERATED by dotmac_deployment_foundation.rehearsal."
        "render_pending_document — do not hand-edit. -->",
        "",
        f"# Exposure rehearsal (Lane {LANE}) — {passed} of {len(REQUIRED_ITEMS)} "
        "executed and passed",
        "",
        f"**No Lane {LANE} receipt exists.** {reason}",
        "",
        "Historical hand measurements are retained below as supporting context. "
        "They are recorded as `hand_measured`, which **cannot satisfy "
        "publication**: a hand-driven step proves the operator can do it, not "
        "that the controller can. `vacuous` means the check ran against a "
        "fixture that could not exercise it.",
        "",
    ]
    lines.extend(_table(rows))
    return "\n".join(lines)


def render_status_document(receipt: RehearsalReceiptV1 | RehearsalReceiptV2) -> str:
    """The status table, DERIVED from the receipt.

    This function exists because the previous document was hand-maintained and
    its header contradicted its own table. A generated summary cannot: the
    counts below are computed from the same rows they summarise.
    """
    rows = {result.code: (result.status, result.detail) for result in receipt.results}
    passed = sum(1 for status, _ in rows.values() if status.satisfies_publication)
    content = receipt.content
    lines: list[str] = [
        "<!-- GENERATED by dotmac_deployment_foundation.rehearsal."
        "render_status_document — do not hand-edit. -->",
        "",
        f"# Exposure rehearsal (Lane {receipt.lane}) — {passed} of "
        f"{len(REQUIRED_ITEMS)} executed and passed",
        "",
        f"- **Foundation revision:** `{receipt.foundation_revision}`",
    ]
    if isinstance(receipt, RehearsalReceiptV2):
        # Opaque identifiers only: this document is published beside the
        # receipt, so it carries nothing the receipt itself may not.
        run = receipt.execution_run
        lines += [
            f"- **Schema:** `{content['schema']}`",
            f"- **Execution run:** repository `{run.repository_id}`, run "
            f"`{run.run_id}`, attempt `{run.run_attempt}`",
            f"- **Descriptor digest:** `{content['descriptor_digest']}`",
            f"- **Authorized execution plan:** `{content['execution_plan_digest']}`",
            f"- **Target / host:** `{content['target_id']}` / `{content['host_id']}` "
            f"under lease `{content['lease_id']}`",
            f"- **Controller identity:** `{content['controller_identity']}`",
            f"- **Probe vantage:** `{content['probe_vantage_ref']}`",
            f"- **Evidence bundle:** `{content['evidence_bundle_digest']}`",
        ]
    else:
        lines += [
            f"- **Authorization run:** `{receipt.authorization_run_id}`",
            "- **Bound digest (all three terms):** "
            f"`{content['descriptor_digest']}`",
            f"- **Target:** `{content['target']}` under lease `{content['lease_id']}`",
            f"- **Controller identity:** `{content['controller_identity']}`",
            f"- **External probe:** `{content['probe_identity']}`",
        ]
    lines += [
        f"- **Window:** {content['started_at']} → {content['finished_at']}",
        f"- **Receipt digest:** `{receipt.sha256_digest()}`",
        "",
        "Only `executed_passed` satisfies publication. Every other status is "
        "reported as itself rather than folded into a total — the 2026-08-29 "
        'count reached "14 of 16" by counting `partial` and `n/a` as closed.',
        "",
    ]
    lines.extend(_table(rows))
    return "\n".join(lines)
