#!/usr/bin/env python3
"""Lane 3's fail-closed Control V2 authorization standing.

The current workflow has neither a trusted CP-rendered
``FoundationExecutionPlanV3`` nor a startup-installed V2 pair provider. Its
single historical authorization document cannot authorize a rehearsal. A
future trusted composition may pass the typed plan and exact Control
authorization+dispatch pair through :func:`establish_authorization`; this
module never invents host facts, chooses an attester, or accepts a request
clock. Until then the lane reports a non-green, explicit precondition.
"""

from __future__ import annotations

import argparse
import dataclasses
import enum
import json
import pathlib
import sys
from collections.abc import Iterable, Mapping
from typing import TYPE_CHECKING, Any, Final

if TYPE_CHECKING:
    from dotmac_deployment_foundation.execution_plan_v3 import FoundationExecutionPlanV3

#: The group an assembly declares its bindings in. Restated here as a LITERAL
#: on purpose: this module must be able to say what it looked for even when the
#: installed Foundation is too old to define the constant, which is precondition
#: `published_foundation`. The architecture test compares it against the
#: package's own value so the two cannot drift.
ENTRY_POINT_GROUP: Final = "dotmac_deployment_foundation.execution_bindings"

#: The operation Lane 3 rehearses. Named rather than defaulted at the call site,
#: because `authorize_v3()` refuses a grant for a different one and a silent
#: default is how a rollback approval comes to cover a deploy.
LANE_OPERATION: Final = "deploy"

EXIT_ATTESTED, EXIT_VIOLATION, EXIT_INDETERMINATE = 0, 1, 2


@dataclasses.dataclass(frozen=True, slots=True)
class Precondition:
    """One thing that must exist before Lane 3's authorization can be verified.

    ``observable`` is the honest half. An entry a machine can check here is
    checked, and its absence is what a refusal cites; an entry nothing in this
    repository can decide is marked False and stays a STATED requirement. A
    stated requirement is not an enforced one, and conflating the two is how a
    checklist comes to be read as coverage (ADR-0018).
    """

    code: str
    statement: str
    owner: str
    evidence: str
    observable: bool

    def render(self) -> str:
        seen = "observable here" if self.observable else "STATED, not enforced"
        return (
            f"  - {self.code} ({seen})\n"
            f"      {self.statement}\n"
            f"      owner: {self.owner}\n"
            f"      measured: {self.evidence}"
        )


#: THE list, corrected 2026-09-25 for the C1 Gate-3 successor contract.
#: Stated entries remain unadmitted until the owning CP composition supplies
#: immutable plan and V2 pair coordinates.
PRECONDITIONS: Final[tuple[Precondition, ...]] = (
    Precondition(
        code="verifier_implementation",
        statement=(
            "A startup-fixed `ExecutionAuthorityV3Provider` composes the Control "
            "V2 pair attester, trusted clock and independent host/target observer. "
            "Foundation ships the protocol but no provider; a verifier selected "
            "by the dispatch request has no authority."
        ),
        owner=(
            "the assembly — the only party that legitimately depends on both "
            "Control and the Foundation"
        ),
        evidence=("no ratified CP provider coordinate is composed into this lane"),
        observable=True,
    ),
    Precondition(
        code="bindings_entry_point",
        statement=(
            f"That implementation is declared as ONE {ENTRY_POINT_GROUP!r} "
            "entry point and installed into the same environment the runner "
            "executes in — the isolated candidate venv, not the checkout."
        ),
        owner="the assembly's bindings distribution, installed by the supply chain",
        evidence=f"zero declarations of {ENTRY_POINT_GROUP!r} exist fleet-wide",
        observable=True,
    ),
    Precondition(
        code="signed_document_reaches_the_runner",
        statement=(
            "The runner receives both signed Control V2 authorization and "
            "dispatch documents, not a single historical V1 receipt or a "
            "caller-computed digest."
        ),
        owner="Platform CP, which issues it, and the workflow that carries it",
        evidence=(
            "the workflow supplies no Control V2 pair; the old V1 document "
            "input was removed rather than carried as authority"
        ),
        observable=True,
    ),
    Precondition(
        code="issuer_to_verifier_translation",
        statement=(
            "Trusted CP composition must supply a typed "
            "`FoundationExecutionPlanV3` rendered from the exact candidate and "
            "Control/Fleet-resolved host, plus the Control V2 authorization and "
            "dispatch pair whose signed execution-plan digest equals it."
        ),
        owner="the assembly; neither side may normalize the other's document",
        evidence=(
            "no ratified CP provider/plan coordinate is available to this workflow"
        ),
        observable=False,
    ),
    Precondition(
        code="published_foundation",
        statement=(
            "The bytes Lane 3 installs contain the verifying code — "
            "`authorization_v3.authorize_v3` and "
            "`execution_bindings.discover_bindings`. Lane 3 installs a recorded "
            "`CandidateArtifact.v1` wheel, so the verifier has to be inside "
            "that wheel rather than in the checkout beside it."
        ),
        owner="the Foundation's release pipeline",
        evidence=(
            "the verifying code lives in dotmac-deployment-foundation 0.4.0a1, "
            "which has never been built and is unpublished (version.py; "
            "docs/inventories/declared-publication-baseline.json)"
        ),
        observable=True,
    ),
    Precondition(
        code="middle_term_is_the_execution_plan_digest",
        statement=(
            "Gate item 9's middle term is `ExecutionPlanDigestV1` — the plan "
            "the Foundation renders and Control merely freezes (AGENTS.md rule "
            "49). It is explicitly NOT the descriptor digest and NOT the "
            "authorization-envelope digest, so an attested receipt alone does "
            "not restore the term: `rehearsal.build_receipt` still asserts "
            "`authorization_document_digest == descriptor_digest == "
            "execution_report_digest`, which is the degenerate two-term shape "
            "its own docstring warns about."
        ),
        owner=(
            "this lane's runner. The Foundation half is repaired: "
            "`rehearsal.build_receipt_v2` checks item 9 as a chain over the "
            "authorized plan, and the release gate reads only `RehearsalReceipt.v2`"
        ),
        evidence=(
            "the runner still emits a v1 receipt through `build_receipt`, whose "
            "`require_same_digest` forces the three terms equal; it cannot call "
            "`build_receipt_v2` until it drives `Executor` and holds the "
            "authorized `FoundationExecutionPlanV3` and its `DeploymentOutcome`"
        ),
        observable=False,
    ),
)

_BY_CODE: Final[dict[str, Precondition]] = {p.code: p for p in PRECONDITIONS}


class Standing(enum.Enum):
    """What can be established about this run's authorization. Closed."""

    ATTESTED = "attested"
    UNATTESTABLE = "unattestable"
    UNANSWERABLE = "unanswerable"

    @property
    def exit_status(self) -> int:
        """0 attested / 1 violation / 2 indeterminate — never collapsed.

        The same statuses `check_allocation_serialized.py` uses, and the same
        rule: an indeterminate answer is not a pass, and a violation is not an
        indeterminate answer.
        """
        if self is Standing.ATTESTED:
            return EXIT_ATTESTED
        if self is Standing.UNATTESTABLE:
            return EXIT_VIOLATION
        return EXIT_INDETERMINATE


class AuthorizationUnverifiable(Exception):
    """Lane 3's authorization could not be established, and why.

    Deliberately NOT a `DeploymentFoundationError` subclass at definition time:
    this module must be importable and must be able to REFUSE even when the
    installed Foundation is too old to import from, which is the
    `published_foundation` precondition. The runner translates it into its own
    `PreconditionUnfit` at the call site — where the fact "the host has not been
    touched" is known — rather than this module asserting it from a distance.
    """

    def __init__(
        self, standing: Standing, reason: str, unmet: Iterable[str] = ()
    ) -> None:
        self.standing = standing
        self.reason = reason
        self.unmet: tuple[str, ...] = tuple(unmet)
        super().__init__(self.render())

    @property
    def exit_status(self) -> int:
        return self.standing.exit_status

    def render(self) -> str:
        cited = [_BY_CODE[code] for code in self.unmet if code in _BY_CODE]
        lines = [
            f"Lane 3 authorization is {self.standing.value}: {self.reason}",
            "",
            "Caller-supplied `--authorization-run` and any document digest are "
            "RECORDED, never believed. Matching text is not a binding, and this "
            "lane exists to prove the Foundation cannot authorize itself.",
        ]
        if cited:
            lines += ["", "What would have to exist:"]
            lines += [p.render() for p in cited]
        lines += [
            "",
            "The full list, including the entries nothing here can decide, is "
            "`PRECONDITIONS` in scripts/lane3_authorization.py.",
        ]
        return "\n".join(lines)


def _verifying_symbols() -> tuple[Any, Any]:
    """The Foundation's verifying entry points, from the INSTALLED distribution.

    Imported here rather than at module scope so an installed Foundation that
    predates them produces a named, enumerated refusal instead of an
    `ImportError` at collection time. Which distribution answers is exactly the
    question `published_foundation` asks, and the import is how it is asked.
    """
    try:
        from dotmac_deployment_foundation.authorization_v3 import authorize_v3
        from dotmac_deployment_foundation.execution_bindings import discover_bindings
    except ImportError as exc:
        raise AuthorizationUnverifiable(
            Standing.UNANSWERABLE,
            (
                "the installed dotmac-deployment-foundation does not carry the "
                f"verifying code ({exc}). Nothing here can attest an "
                "authorization, so nothing here can tell one from a fabrication"
            ),
            unmet=("published_foundation",),
        ) from exc
    return authorize_v3, discover_bindings


def _find_provider(discover_bindings: Any, entries: Iterable[Any] | None) -> Any:
    """The startup-installed V3 authority provider, or an UNANSWERABLE refusal.

    Looked for BEFORE the document is read. With nothing able to attest, a
    missing document says nothing about the caller, and citing it would report
    an environment gap as an operator error.
    """
    try:
        bindings = discover_bindings(entries=entries)
    except Exception as exc:
        raise AuthorizationUnverifiable(
            Standing.UNANSWERABLE,
            (
                f"the execution bindings could not be resolved ({exc}). A "
                "broken deployment environment is not a quieter one"
            ),
            unmet=("bindings_entry_point",),
        ) from exc
    if bindings is None:
        raise AuthorizationUnverifiable(
            Standing.UNANSWERABLE,
            (
                f"no distribution declares {ENTRY_POINT_GROUP!r}, so this "
                "environment ships no V3 authority provider and cannot "
                "distinguish a Platform CP authorization from text typed into "
                "a workflow_dispatch field"
            ),
            unmet=("verifier_implementation", "bindings_entry_point"),
        )
    provider = getattr(bindings, "authorization_v3_provider", None)
    if provider is None:
        raise AuthorizationUnverifiable(
            Standing.UNANSWERABLE,
            (
                f"the bindings declared by {ENTRY_POINT_GROUP!r} carry no "
                "authorization_v3_provider. Bindings that inject effects but no "
                "V2 pair provider leave this question exactly as unanswerable as none "
                "at all"
            ),
            unmet=("verifier_implementation",),
        )
    return bindings


def _read_document(path: str | pathlib.Path | None) -> Mapping[str, Any]:
    """The exact two-member Control V2 pair, never a V1 document.

    Every failure here is a VIOLATION rather than indeterminate: a verifier is
    already in hand by the time this runs, so the environment could have
    answered the question and the run did not give it anything to answer with.
    """
    if not path:
        raise AuthorizationUnverifiable(
            Standing.UNATTESTABLE,
            (
                "a verifier is installed and no --authorization-document was "
                "supplied. The run cites an authorization it cannot show, and "
                "a run id plus a digest is a claim about a document rather "
                "than the document"
            ),
            unmet=("signed_document_reaches_the_runner",),
        )
    try:
        raw = pathlib.Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        raise AuthorizationUnverifiable(
            Standing.UNATTESTABLE,
            f"the authorization document at {path} could not be read ({exc})",
            unmet=("signed_document_reaches_the_runner",),
        ) from exc
    try:
        document = json.loads(raw)
    except ValueError as exc:
        raise AuthorizationUnverifiable(
            Standing.UNATTESTABLE,
            f"the authorization document at {path} is not valid JSON ({exc})",
            unmet=("signed_document_reaches_the_runner",),
        ) from exc
    if not isinstance(document, Mapping):
        raise AuthorizationUnverifiable(
            Standing.UNATTESTABLE,
            (
                f"the authorization document at {path} is a "
                f"{type(document).__name__}, not an object"
            ),
            unmet=("signed_document_reaches_the_runner",),
        )
    if set(document) != {"authorization_material", "dispatch_material"} or not all(
        isinstance(document[name], Mapping)
        for name in ("authorization_material", "dispatch_material")
    ):
        raise AuthorizationUnverifiable(
            Standing.UNATTESTABLE,
            "a single V1 receipt is non-authorizing; Lane 3 requires the "
            "Control V2 authorization+dispatch pair",
            unmet=("signed_document_reaches_the_runner",),
        )
    return document


def establish_authorization(
    *,
    descriptor_digest: str,
    target: str,
    authorization_document: str | pathlib.Path | None,
    execution_plan: FoundationExecutionPlanV3 | None = None,
    operation: str = LANE_OPERATION,
    entries: Iterable[Any] | None = None,
) -> Any:
    """The ONLY route from Lane 3's inputs to an `ExecutionGrant`.

    Note what is NOT a parameter: the authorization run id and the document
    digest the workflow dispatches. They are recorded on the receipt and
    compared against the lease elsewhere, and neither can reach this function,
    so no path through it can promote caller-supplied text into permission. That
    is the difference between a guard and a convention — a caller who wants an
    unverified grant has nothing to call.

    No request clock or verifier is accepted. The fixed provider owns both.

    Returns the Foundation's `ExecutionGrant`. Raises
    :class:`AuthorizationUnverifiable` otherwise — never a sentinel, so a caller
    cannot treat "refused" as "granted" by forgetting to look.
    """
    authorize_v3, discover_bindings = _verifying_symbols()
    bindings = _find_provider(discover_bindings, entries)
    document = _read_document(authorization_document)
    if execution_plan is None:
        raise AuthorizationUnverifiable(
            Standing.UNANSWERABLE,
            "Lane 3 has no trusted FoundationExecutionPlanV3 from CP; "
            "descriptor/target text cannot construct host authority",
            unmet=("issuer_to_verifier_translation",),
        )
    try:
        return authorize_v3(
            bindings=bindings,
            authorization_material=document["authorization_material"],
            dispatch_material=document["dispatch_material"],
            plan=execution_plan,
            operation=operation,
            descriptor_digest=descriptor_digest,
            target=target,
        )
    except Exception as exc:
        raise AuthorizationUnverifiable(
            Standing.UNATTESTABLE,
            (
                f"the attested authorization does not cover this run ({exc}). "
                "The terms are authentic and they are for other work"
            ),
        ) from exc


def standing_of(**kwargs: Any) -> tuple[Standing, str]:
    """:func:`establish_authorization` reduced to its verdict, for the gate."""
    try:
        establish_authorization(**kwargs)
    except AuthorizationUnverifiable as refusal:
        return refusal.standing, refusal.render()
    return (
        Standing.ATTESTED,
        "Lane 3 authorization is attested: an installed verifier vouched for "
        "the signed document and its terms bind to this descriptor, target and "
        "operation.",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="lane3_authorization.py",
        description=(
            "Report whether Lane 3's authorization can be verified in THIS "
            "environment. 0 attested / 1 violation / 2 indeterminate."
        ),
    )
    parser.add_argument("--descriptor", required=True, help="the rehearsal fixture")
    parser.add_argument("--target", required=True, help="the leased host")
    parser.add_argument(
        "--authorization-document",
        default="",
        help="the signed Platform CP authorization document (a path)",
    )
    parser.add_argument("--operation", default=LANE_OPERATION)
    arguments = parser.parse_args(argv)

    try:
        from dotmac_deployment_foundation.spec import ProductDeploymentSpec
    except ImportError as exc:
        print(
            AuthorizationUnverifiable(
                Standing.UNANSWERABLE,
                f"dotmac-deployment-foundation is not importable ({exc})",
                unmet=("published_foundation",),
            ).render(),
            file=sys.stderr,
        )
        return EXIT_INDETERMINATE

    spec = ProductDeploymentSpec.load(arguments.descriptor)
    standing, report = standing_of(
        descriptor_digest=spec.to_canonical_document().sha256_digest(),
        target=arguments.target,
        authorization_document=arguments.authorization_document,
        operation=arguments.operation,
    )
    stream = sys.stdout if standing is Standing.ATTESTED else sys.stderr
    print(report, file=stream)
    return standing.exit_status


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
