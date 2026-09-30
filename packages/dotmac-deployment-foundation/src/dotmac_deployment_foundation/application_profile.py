"""``ApplicationFoundationProfile.v1`` — what an assembly composes, per concern.

Governance ADR 0039 (Proposed, `58d5a1bbee`) is the contract. This module is its
typed expression in the facility that verifies it.

## Two halves, and a reader who meets only the first will be wrong

- **The type refuses.** A profile with a missing concern is UNCONSTRUCTABLE.
  There is no warning branch, no degraded mode and no per-deployment knob —
  ADR 0039 § 4 prohibits the warning path explicitly, because given a warning
  branch every incomplete profile becomes a warning and the record survives as
  documentation of a control nobody runs.
- **The verification is report-only.** Nothing on this facility's boot or deploy
  path calls it. No assembly is gated by a profile it cannot yet complete.

**Those are not in tension; they are the two halves ADR 0039's own staging
paragraph describes.** The record stages deliberately: authored and verified in
report-only form first, with the § 4 refusal composed into a live path per
concern, as that concern acquires a real binding in the assembly being deployed.

Say this out loud to the next reader, because the failure mode is specific:
someone who meets the type's refusal concludes the gate is LIVE, and acts on
that belief against an assembly that cannot yet fill every slot.

**A COUNT OF WHICH CONCERNS THE FLEET CAN BIND TODAY USED TO STAND HERE, AND IT
IS WITHDRAWN** (2026-09-04). This module said four of the thirteen have mature
owners and nine do not. Two things were wrong with it, and only the second is
about the number. First, it was a fleet-wide maturity determination made inside
a facility that owns no part of the fleet's estate, cannot re-derive it, and
ships on its own release cadence — so it was a claim with no oracle, in a
package whose entire discipline is that a claim names one. Second, a number
written into a docstring is stale from the moment an owner matures, and it
degrades silently: nothing fails, the sentence simply becomes untrue, and the
next reader budgets against it.

What is true and checkable is narrower, and it is all this module needs: the
verification is report-only because ADR 0039 stages it that way, and WHICH
concerns a given assembly can bind is that assembly's own declaration to make.

What must NOT happen in the interim is the thing § 6 exists to prevent —
completing the profile by marking the unfinished concerns `inapplicable`. An
unfinished concern is MISSING, not absent, and the two are different words for a
reason.

## No hardcoded opinion about which concerns are fillable

This module knows the thirteen concern NAMES and nothing about which of them any
assembly can currently bind. Bindability comes entirely from the assembly's own
declaration.

That is not only correctness. **Which concerns are bindable moves as owners
mature, and this facility is not the thing that would learn of it** — so a
facility carrying a list of "the bindable ones" would need a release every time
the estate moved, and the list would be wrong between releases. The absence of
that list is a decision, not an omission — and it is the same decision as the
withdrawal above: this module declines to hold a fleet fact it cannot check.

## The thirteen are CLOSED

ADR 0039 § 2. Adding a fourteenth is an amendment to that record, not a field
somebody adds to this enum, for the same reason ADR 0019 § 2 closed the receipt
envelope: the pressure never arrives as "let us make this an
everything-framework", it arrives as "it would be so much more useful with just
this one more concern".

**`recovery.BundleComponent` also has exactly thirteen members and is a
completely different vocabulary.** Do not conflate them — and do not stop at
"do not conflate", because the two ARE related and a reader who stops at the
warning will miss it: `BundleComponent`'s thirteen are the database-fact set a
recovery bundle carries, and they are what the verification registry in
`recovery.py` compares. This module's thirteen are the concerns an application
composes. One of those concerns (`deployment / recovery`) is the one whose
binding would OWN that bundle contract. Different vocabularies, one real
relationship. `test_the_two_thirteens_are_not_the_same_vocabulary` holds the
distinction; this paragraph holds the connection.

## A binding names three things and NOTHING else

ADR 0039 § 3 and § 10. Implementation identity, exact version, immutable
artifact coordinates. The test for what belongs is decidable by the author
rather than by a reviewer:

> **If two correct deployments of the same artifacts could hold different values
> for it, it is not a binding.**

A rate limit, a retention period, a timeout, a CORS origin list, a trusted-proxy
range, a key, a quota, a feature flag, a retry budget and a log level all fail
it immediately. Each already has an owner — settings and secrets, the deployment
descriptor, or the entitlement surface — and moving one here creates a second
authority for a value that has one.

**That refusal is STRUCTURAL, not stated.** `ConcernBinding` is a closed field
set, so there is no key a policy value could be written under; proposing one is
a reviewed amendment to ADR 0039 rather than a plausible line in a pull request.
And `from_document` refuses an unknown key rather than ignoring it, because
ignoring is how the closed set quietly opens.
"""

from __future__ import annotations

import dataclasses
import re
from collections.abc import Mapping
from enum import Enum
from typing import Any, Final

from .errors import PreconditionFailed, SpecError

__all__ = [
    "IntegrationSurfaceAbsenceProofV1",
    "INTEGRATION_SURFACE_FAMILIES",
    "INTEGRATION_ABSENCE_SCHEMA",
    "ABSENCE_WRONG_CONCERN",
    "ABSENCE_UNREGISTERED_SURFACE",
    "ABSENCE_UNESTABLISHED",
    "ABSENCE_UNSUPPORTED_CONCERN",
    "ABSENCE_NOT_ABSENT",
    "ABSENCE_INVENTORY_INCOMPLETE",
    "APPLICATION_PROFILE_SCHEMA",
    "BINDING_FIELDS",
    "CONCERN_LABELS",
    "PROFILE_ENTRY_POINT_GROUP",
    "canonical_profile_bytes",
    "discover_profile",
    "profile_digest",
    "require_profile_readback",
    "verify_profile_against_candidate",
    "AbsenceProof",
    "ApplicationFoundationProfile",
    "ConcernBinding",
    "FoundationConcern",
    "InapplicableConcern",
    "WORK_ENTRY_POINT_FAMILIES",
    "WRITER_DISPOSITIONS",
    "WRITER_STATES",
    "WriterClaim",
]

APPLICATION_PROFILE_SCHEMA: Final = "ApplicationFoundationProfile.v1"


class FoundationConcern(str, Enum):
    """The thirteen universal concerns, CLOSED. ADR 0039 § 2.

    The value is a stable machine identifier; :data:`CONCERN_LABELS` carries the
    ADR's own wording for each, so a reader can check this enum against the
    record without translating.
    """

    IDENTITY_SESSION = "identity_session"
    REQUEST_EVIDENCE_CONTEXT = "request_evidence_context"
    AUTHORIZATION = "authorization"
    PERSISTENCE_MIGRATIONS = "persistence_migrations"
    SETTINGS_SECRETS = "settings_secrets"
    AUDIT_TELEMETRY = "audit_telemetry"
    HEALTH_RUNTIME_ADMISSION = "health_runtime_admission"
    WORKER_EXECUTION = "worker_execution"
    EDGE_SECURITY = "edge_security"
    API_WEB_INTERACTION = "api_web_interaction"
    DATA_GOVERNANCE = "data_governance"
    INTEGRATION = "integration"
    DEPLOYMENT_RECOVERY = "deployment_recovery"


#: ADR 0039 § 2's wording, verbatim and in its numbered order. Kept so a
#: reviewer can compare this module with the record without paraphrasing, and so
#: a renamed enum member cannot silently come to mean a different concern.
CONCERN_LABELS: Final[dict[FoundationConcern, str]] = {
    FoundationConcern.IDENTITY_SESSION: "identity / session",
    FoundationConcern.REQUEST_EVIDENCE_CONTEXT: "request evidence context",
    FoundationConcern.AUTHORIZATION: "authorization",
    FoundationConcern.PERSISTENCE_MIGRATIONS: "persistence / migrations",
    FoundationConcern.SETTINGS_SECRETS: "settings / secrets",
    FoundationConcern.AUDIT_TELEMETRY: "audit / telemetry",
    FoundationConcern.HEALTH_RUNTIME_ADMISSION: "health / runtime admission",
    FoundationConcern.WORKER_EXECUTION: "worker execution",
    FoundationConcern.EDGE_SECURITY: "edge security",
    FoundationConcern.API_WEB_INTERACTION: "API / web interaction",
    FoundationConcern.DATA_GOVERNANCE: "data governance",
    FoundationConcern.INTEGRATION: "integration",
    FoundationConcern.DEPLOYMENT_RECOVERY: "deployment / recovery",
}

#: The closed field set of a binding. ADR 0039 § 10's first mechanical
#: consequence, enforced rather than stated: a key outside this set is REFUSED
#: at parse, so a policy value cannot arrive as a plausible line in a diff.
BINDING_FIELDS: Final[frozenset[str]] = frozenset(
    {"implementation", "version", "coordinates", "displaces", "retirement"}
)

#: ADR 0013 § 3 coordinates. A branch name, `latest`, an unpeeled tag and a bare
#: image tag are all refused: a claim measured against a moving reference is not
#: a claim, and an installation adopts by digest.
_IMMUTABLE_COORDINATE = re.compile(
    r"^(?:[a-z0-9][a-z0-9._\-/]*@sha256:[0-9a-f]{64}|sha256:[0-9a-f]{64}|[0-9a-f]{40})$"
)
_MOVING_REFERENCE = re.compile(r"(^|[:/@])(latest|main|master|HEAD|stable|edge)$")

#: `product_writers`' closed vocabulary, consumed BY SHAPE. The four states are
#: the implementing repository's and are cited rather than reinvented.
WRITER_STATES: Final[frozenset[str]] = frozenset(
    {"qualifying_source", "legacy_writer", "no_writer", "inventory_only"}
)

#: ADR 0039 § 9 property 4 — the disposition, which exists NOWHERE today. 340
#: typed rows can say a retirement is owed and none can say it happened.
#:
#: Carried HERE, in this facility's own typed shape, and deliberately NOT added
#: to `EXTRACTION.toml`: ADR 0039 § 11 says that schema change belongs to the
#: implementing repository's owner as open decision 44. The profile states the
#: property it needs; where an assembly keeps it is the assembly's business.
#:
#: `not_yet` is permitted. UNSTATED is not — that is the whole point of a typed
#: disposition, and an absent one is UNKNOWN rather than "nothing to retire".
WRITER_DISPOSITIONS: Final[frozenset[str]] = frozenset(
    {
        "retired_in_revision",
        "transferred_to_owner",
        "still_live_with_condition",
        "not_yet",
    }
)

#: Every family by which work can ENTER an assembly. AGENTS.md rule 25: a guard
#: enumerates entry-point FAMILIES, never a single directory — "no worker
#: runtime" is admissible only when the proof visited every one of these and
#: found each empty. A proof that looked in one directory has established a fact
#: about that directory.
WORK_ENTRY_POINT_FAMILIES: Final[tuple[str, ...]] = (
    "worker",
    "scheduler",
    "cron",
    "task",
)

_IMMUTABLE_REVISION = re.compile(r"^[0-9a-f]{40}$")


def _require_coordinate(value: str, *, where: str) -> str:
    text = str(value).strip()
    if not text:
        raise SpecError(f"{where}: coordinates may not be empty", where=where)
    if _MOVING_REFERENCE.search(text) or not _IMMUTABLE_COORDINATE.match(text):
        raise SpecError(
            f"{where}: {text!r} is not an immutable coordinate. ADR 0013 § 3 "
            "refuses a branch name, 'latest', an unpeeled tag and a bare image "
            "tag: an installation adopts BY DIGEST, so a claim measured against "
            "a reference that can move is not a claim about any particular "
            "bytes. Use `<name>@sha256:<64 hex>`, `sha256:<64 hex>`, or a "
            "peeled 40-character commit",
            where=where,
        )
    return text


@dataclasses.dataclass(frozen=True, slots=True)
class WriterClaim:
    """One TYPED retirement claim about one product. ADR 0039 § 9.

    Consumed by SHAPE, never by file layout. `[[product_writers]]` in
    `dotmac_starter_mt`'s `EXTRACTION.toml` is the fleet's current instance of
    this shape and is **an** instance, not the requirement — an assembly holding
    the same properties elsewhere satisfies § 9, provided the binding points at
    where they live. A contract that named a path would import one repository's
    layout into every assembly.

    **The prose field is deliberately not read.** `local_copy_retirement` is the
    human account of the obligation: worth reading, explains what a typed row
    cannot, and NOT the evidence. The implementing repository already ruled on
    the weaker form and the ruling is cited rather than restated —

        reading `local_copy_retirement` prose instead is worse — a sentence is
        not a claim a checker can compare.

    The measured failure behind that sentence is the one to keep in mind:
    **Expenses was rostered "no ISP writer in scope" while Sub held two writers
    its own prose field required to ratchet to zero.** The prose was present, it
    was correct, and it did not prevent the roster from being wrong — because
    prose cannot be compared. A future reader proposing "why not just read the
    prose, it is right there" should meet that, and not a preference.
    """

    product: str
    writer_state: str
    retirement_required: bool
    revision: str
    evidence_paths: tuple[str, ...]
    #: Property 4. `not_yet` is permitted; UNSTATED is not. See
    #: :data:`WRITER_DISPOSITIONS`.
    disposition: str

    def __post_init__(self) -> None:
        where = f"writer claim for {self.product!r}"
        if not str(self.product).strip():
            raise SpecError("a writer claim with no product names nobody")
        if self.writer_state not in WRITER_STATES:
            raise SpecError(
                f"{where}: writer_state must be one of "
                f"{sorted(WRITER_STATES)}, got {self.writer_state!r}"
            )
        if not isinstance(self.retirement_required, bool):
            raise SpecError(f"{where}: retirement_required must be a boolean")
        if self.disposition not in WRITER_DISPOSITIONS:
            raise SpecError(
                f"{where}: disposition must be one of "
                f"{sorted(WRITER_DISPOSITIONS)}, got {self.disposition!r}. "
                "'not_yet' is a permitted value; UNSTATED is not, because a "
                "missing disposition is UNKNOWN rather than 'nothing to retire' "
                "— which is exactly how the Expenses roster came to be wrong"
            )
        if not _IMMUTABLE_REVISION.fullmatch(str(self.revision)):
            raise SpecError(
                f"{where}: revision must be an immutable 40-character commit; "
                "a claim measured against a moving branch is not a claim"
            )
        if self.writer_state in {"qualifying_source", "legacy_writer"} and not (
            self.evidence_paths
        ):
            raise SpecError(
                f"{where}: claims {self.writer_state!r} and cites no evidence "
                "path; the paths are what a reviewer checks the claim against"
            )

    @property
    def outstanding(self) -> bool:
        """A retirement this claim says is OWED and does not say is done."""
        return self.retirement_required and self.disposition == "not_yet"


@dataclasses.dataclass(frozen=True, slots=True)
class AbsenceProof:
    """An EXECUTABLE proof that a concern's subject is absent. ADR 0039 § 6.

    `inapplicable` is the state that keeps a profile honest for an assembly that
    genuinely has no worker runtime, no web surface, no outbound integration. It
    is also the state that will be used to AVOID completing a profile, so it is
    constrained harder than anything else here.

    This is `AGENTS.md` **rule 25** and its ADR-0018 arriving in a new place,
    verbatim rather than by analogy — cited by number so the next reader finds
    the requirement instead of reading this as one module's local habit:

        A guard exemption states an enforceable premise, or it is not an
        exemption. Guards enumerate ENTRY-POINT FAMILIES (tasks, scripts, CLI,
        workers, cron), never a single directory.

    And an absence proof is a negative claim about a corpus, so ADR 0033 governs
    it in full. Its five requirements are conjunctive and each is checked here:

    1. a closed, authoritative subject inventory — :data:`WORK_ENTRY_POINT_FAMILIES`,
       enumerated BEFORE the proof runs and never from the proof's own results;
    2. exact refs — the artifact digest, not "the build";
    3. complete enumeration — every family visited, each outcome individually
       known, so a family that was never looked at is distinguishable from one
       that was looked at and found empty;
    4. a local, parser-aware scan — entry-point metadata, an AST walk or a
       declared manifest; never a remote index and never a substring search;
    5. an explicit refusal when enumeration is incomplete — a family that cannot
       be reached makes the proof REFUSE, not report a subset.

    ADR 0033 § 3's positive control applies unchanged and is the field most
    likely to be skipped: **the instrument must first be shown to find a thing
    known to exist**, using the same scan, scope and credential as the claim.
    An absence prover that never finds anything and an assembly that has nothing
    are the same colour.
    """

    #: Requirement 2. Which BYTES were scanned.
    image_digest: str
    #: Requirement 3. family -> the members found in it. Empty tuple means
    #: visited and empty. A family absent from this mapping was NOT VISITED.
    families: Mapping[str, tuple[str, ...]]
    #: Requirement 4. How the corpus was read, e.g. "entry-point metadata".
    method: str
    #: ADR 0033 § 3. What the SAME instrument found that is known to exist. An
    #: empty control means the instrument was never shown to be able to find
    #: anything, and the proof refuses.
    positive_control: tuple[str, ...]

    def __post_init__(self) -> None:
        _require_coordinate(self.image_digest, where="absence proof image_digest")
        if not str(self.method).strip():
            raise PreconditionFailed(
                "an absence proof must say HOW the corpus was read. ADR 0033's "
                "fourth requirement is a local, parser-aware scan — entry-point "
                "metadata, an AST walk, a declared manifest — never a remote "
                "index and never a substring search"
            )
        missing = [
            family
            for family in WORK_ENTRY_POINT_FAMILIES
            if family not in self.families
        ]
        if missing:
            raise PreconditionFailed(
                f"the absence proof did not visit {missing}. AGENTS.md rule 25: "
                "a guard enumerates ENTRY-POINT FAMILIES, never one directory, "
                "and ADR 0033's fifth requirement makes an incomplete "
                "enumeration a REFUSAL rather than a subset. A family that was "
                "never looked at is not a family that was found empty"
            )
        occupied = {
            family: members for family, members in self.families.items() if members
        }
        if occupied:
            raise PreconditionFailed(
                f"the absence proof found work entry points: {occupied}. The "
                "concern is not inapplicable; it is unbound"
            )
        if not self.positive_control:
            raise PreconditionFailed(
                "the absence proof carries no positive control. ADR 0033 § 3: "
                "the instrument must first be shown to find something known to "
                "exist, using the same scan and scope. An absence prover that "
                "never finds anything and an assembly that has nothing are the "
                "same colour, and this proof cannot tell you which one it is"
            )


#: The integration surfaces an application could carry. CLOSED, enumerated
#: BEFORE any proof runs and never from a proof's own results.
#:
#: ADR 0033's first requirement, and the one an absence proof cannot supply for
#: itself: "none present" is a statement about a KNOWN UNIVERSE. An open
#: inventory makes absence unfalsifiable, because a surface nobody enumerated
#: silently satisfies "none found" — which is the failure mode absence proofs
#: actually have, as distinct from the one people guard against.
INTEGRATION_SURFACE_FAMILIES: Final[tuple[str, ...]] = (
    "outbound_connector",
    "inbound_webhook",
    "scheduled_sync",
    "message_consumer",
    "external_api_client",
)

#: Refusals. Assert these; read the prose. Every one of them is RAISED below —
#: a declared code with no raiser is false coverage, and
#: `test_every_declared_absence_code_is_actually_raised` fails when one appears.
#: A foreign artifact is deliberately NOT among them: `satisfies` ANSWERS that
#: question with False rather than refusing, and the readback that must refuse
#: it is the consuming platform's, which owns its own code for it.
ABSENCE_WRONG_CONCERN: Final = "absence_proof.wrong_concern"
ABSENCE_INVENTORY_INCOMPLETE: Final = "absence_proof.inventory_incomplete"
ABSENCE_UNREGISTERED_SURFACE: Final = "absence_proof.unregistered_surface"
ABSENCE_NOT_ABSENT: Final = "absence_proof.not_absent"
ABSENCE_UNESTABLISHED: Final = "absence_proof.unestablished"

#: Refused: this proof TYPE has one inventory and it is integration's, so it can
#: prove no other concern's absence. A DISTINCT code from
#: `ABSENCE_WRONG_CONCERN`, which already carries two meanings — "not a
#: `FoundationConcern` at all" at construction, and "filed under the wrong slot
#: key" at the profile level. A third meaning would make three different repairs
#: indistinguishable in a log, which is the discrimination argument this package
#: makes everywhere else.
ABSENCE_UNSUPPORTED_CONCERN: Final = "absence_proof.unsupported_concern"

INTEGRATION_ABSENCE_SCHEMA: Final = "IntegrationSurfaceAbsenceProofV1"


@dataclasses.dataclass(frozen=True, slots=True)
class IntegrationSurfaceAbsenceProofV1:
    """A concern's subject is genuinely absent, as a POSITIVE proven claim.

    ## Four states, and none of them is the absence of the others

    A profile concern is in exactly one of:

    * **bound** — a provider exists and answers (`ConcernBinding`);
    * **not yet implemented** — owed and missing, which is the default and is
      NOT a state anything constructs;
    * **inapplicable** — refused by a standing ruling, and never reintroduced
      under a new name;
    * **absent-proven** — this type.

    Collapsing any pair is the two-values-for-three-cases shape, and here it is
    four. An absence proof is a positive statement carrying provenance — who
    established it, against what, and when — not a null a reader interprets
    charitably.

    ## It SATISFIES the concern, and the reason is forced rather than chosen

    13/13 is required before a candidate is built. If a proven absence could not
    satisfy a concern, a product with genuinely no integration surface could
    never reach 13/13 — and an unmeetable gate gets weakened or waived rather
    than met. Making absence count is what keeps the threshold real.

    **But it satisfies only when ESTABLISHED, never when merely well-formed.**
    That is the load-bearing half: a proof a caller can construct without
    establishing anything is a placeholder wearing a type, and it would turn
    "the gate is reachable" into "the gate is bypassable". Hence
    :meth:`satisfies`, which takes the artifact's own inventory and compares —
    construction alone proves nothing and grants nothing.

    ## Why the evidence cannot be manufactured

    ``observed_inventory_digest`` is a digest over the INSTALLED ARTIFACT's own
    distribution inventory. A caller can write any string there; it cannot make
    that string EQUAL the digest a verifier computes independently from the
    artifact without actually having examined it. Parse and compare, never
    construct and trust — the same shape the fleet's received-digest types use.

    ``source_revision`` and ``artifact_digest`` bind it to one artifact, so a
    perfectly well-formed proof produced for a different build says nothing about
    this one. Platform's readback already refuses that case by name.

    ## ``artifact_digest``, and why it is NOT ``image_digest``

    The field was named ``image_digest`` and the name invited a binding that
    cannot be satisfied. **What this proof binds is the Platform APPLICATION
    WHEEL, not the OCI image the proof travels inside.** A proof embedded in an
    image cannot carry that image's own digest: the digest is over the finished
    image, and the image is not finished until the proof is in it. Naming the
    field for the image asks a producer for a value that does not exist yet, and
    the ways out of that are all worse than the rename — a placeholder, a digest
    of a different image, or a second build.

    So the field names the artifact whose inventory was actually scanned. Every
    other ``image_digest`` in this package is a real OCI image digest and keeps
    its name; this one never was one.

    ## ADR 0033's five requirements, each checked

    1. a closed authoritative inventory — :data:`INTEGRATION_SURFACE_FAMILIES`,
       enumerated before the proof and never from its own results;
    2. exact refs — the image digest, not "the build";
    3. complete enumeration — every family visited, each outcome individually
       known, so a family never looked at is distinguishable from one looked at
       and found empty;
    4. a local, parser-aware scan — recorded as ``method``; never a remote index
       and never a substring search;
    5. an explicit refusal when enumeration is incomplete — a family that cannot
       be reached makes the proof REFUSE rather than report a subset.
    """

    #: WHICH concern this proves absent. Discriminated, so one proof cannot
    #: certify a different concern's emptiness — the same failure as a single
    #: `AbsenceProof` for all thirteen, one level up.
    concern: FoundationConcern
    source_revision: str
    #: The digest of the ARTIFACT whose inventory was scanned — the Platform
    #: application wheel. NOT an OCI image digest: see the class docstring for
    #: why a proof travelling inside an image cannot name that image.
    artifact_digest: str
    #: A digest over the installed artifact's own distribution inventory. The
    #: unmanufacturable half: see the class docstring.
    observed_inventory_digest: str
    #: Every family in the closed inventory, mapped to what was found. An empty
    #: tuple means "visited and found nothing", which is a different fact from a
    #: family that is absent from this mapping entirely.
    families: Mapping[str, tuple[str, ...]]
    #: How the scan was performed — a local, parser-aware method.
    method: str
    #: The instrument shown finding something it is known to find, with the same
    #: scan and scope. ADR 0033 § 3: an absence prover that never finds anything
    #: and an artifact that has nothing are the same colour without this.
    positive_control: tuple[str, ...]
    established_at: str
    established_by: str

    def __post_init__(self) -> None:
        if not isinstance(self.concern, FoundationConcern):
            raise SpecError(
                f"concern must be a FoundationConcern, got "
                f"{type(self.concern).__name__}. An absence proof that cannot "
                "say WHICH concern it proves absent could certify any of them",
                code=ABSENCE_WRONG_CONCERN,
            )
        # THE INVENTORY IS INTEGRATION'S, so the concern must be integration's.
        #
        # `families` is validated against `INTEGRATION_SURFACE_FAMILIES` while
        # `concern` accepted any of the thirteen. A proof with
        # `concern=WORKER_EXECUTION` carrying INTEGRATION families therefore
        # constructed cleanly — and then PASSED the profile's misfiling guard,
        # because that guard compares the slot key with this same `concern`
        # field. The two things that agree were the two things checked; the
        # inventory, the only thing that would have disagreed, was never
        # consulted.
        #
        # The misfiling guard is not vacuous in general — it catches a correctly
        # built proof filed under the wrong key. It cannot catch a proof BUILT
        # against the wrong inventory, which is the earlier and quieter defect
        # and the one this refuses.
        if self.concern is not FoundationConcern.INTEGRATION:
            raise SpecError(
                f"this proof type carries the INTEGRATION surface inventory "
                f"{list(INTEGRATION_SURFACE_FAMILIES)} and cannot establish the "
                f"absence of {self.concern.value}. Its families would be "
                "enumerated from a closed inventory belonging to a different "
                "concern, so a complete enumeration would prove the emptiness "
                "of something nobody asked about. A concern with its own "
                "absence surface needs its own closed inventory and its own "
                "positive control",
                code=ABSENCE_UNSUPPORTED_CONCERN,
            )
        for field in ("source_revision", "method", "established_at", "established_by"):
            if not str(getattr(self, field)).strip():
                raise SpecError(
                    f"IntegrationSurfaceAbsenceProofV1.{field} is empty. A proof "
                    "carries provenance — who established it, against what, and "
                    "when — or it is a null with a type around it",
                    code=ABSENCE_UNESTABLISHED,
                )
        _require_coordinate(self.artifact_digest, where="absence proof artifact_digest")
        _require_coordinate(
            self.observed_inventory_digest, where="absence proof inventory digest"
        )
        visited = set(self.families)
        expected = set(INTEGRATION_SURFACE_FAMILIES)
        unregistered = sorted(visited - expected)
        if unregistered:
            raise SpecError(
                f"the proof reports families {unregistered}, which are not in "
                f"the closed inventory {list(INTEGRATION_SURFACE_FAMILIES)}. A "
                "surface nobody registered must REFUSE rather than disappear: an "
                "unregistered family silently satisfies 'none present', which is "
                "the failure mode absence proofs actually have",
                code=ABSENCE_UNREGISTERED_SURFACE,
            )
        missing = sorted(expected - visited)
        if missing:
            raise SpecError(
                f"the proof did not visit {missing}. Complete enumeration is "
                "ADR 0033's third requirement: a family that was never looked at "
                "is not a family that was found empty, and reporting a subset is "
                "the shape this refusal exists to prevent",
                code=ABSENCE_INVENTORY_INCOMPLETE,
            )
        occupied = {name: found for name, found in self.families.items() if found}
        if occupied:
            raise SpecError(
                f"the scan found integration surfaces: {occupied}. The concern "
                "is not absent; it is UNBOUND, which is a different state and "
                "needs a provider rather than a proof",
                code=ABSENCE_NOT_ABSENT,
            )
        if not self.positive_control:
            raise SpecError(
                "the proof carries no positive control. ADR 0033 § 3: the "
                "instrument must first be shown finding something known to "
                "exist, using the same scan and scope. Without it, a prover that "
                "never finds anything and an artifact that has nothing are the "
                "same colour, and this proof cannot say which it is",
                code=ABSENCE_UNESTABLISHED,
            )

    def satisfies(
        self,
        concern: FoundationConcern,
        *,
        artifact_digest: str,
        inventory_digest: str,
    ) -> bool:
        """Does this proof ESTABLISH that concern's absence for THIS artifact?

        Not "is it well-formed" — that was settled at construction. This is the
        half that makes absence count without making the gate bypassable: the
        caller supplies the artifact digest and the inventory digest it computed
        ITSELF, and both must equal what the proof claims.

        A caller can write any string into the proof. It cannot make that string
        equal one an independent party derived from the artifact without having
        examined it, which is why this compares rather than trusts.

        The keyword is ``artifact_digest`` and the rename is deliberate at the
        CALL as well as in the record: a caller that still passes an OCI image
        digest here is answering a different question, and a keyword-only
        parameter makes that a `TypeError` rather than a silent mismatch.
        """
        return (
            self.concern is concern
            and str(self.artifact_digest) == str(artifact_digest)
            and str(self.observed_inventory_digest) == str(inventory_digest)
        )

    def as_document(self) -> dict[str, Any]:
        return {
            "concern": self.concern.value,
            "established_at": self.established_at,
            "established_by": self.established_by,
            "families": {
                name: sorted(found) for name, found in sorted(self.families.items())
            },
            "artifact_digest": self.artifact_digest,
            "method": self.method,
            "observed_inventory_digest": self.observed_inventory_digest,
            "positive_control": sorted(self.positive_control),
            "schema": INTEGRATION_ABSENCE_SCHEMA,
            "source_revision": self.source_revision,
            "state": "absent_proven",
        }


@dataclasses.dataclass(frozen=True, slots=True)
class ConcernBinding:
    """One concern, BOUND. Implementation identity, version, coordinates.

    Nothing else — see this module's docstring for § 10's test and why the
    closed field set is the enforcement rather than a reviewer's memory.
    """

    implementation: str
    version: str
    coordinates: str
    #: Local writers or executors this binding DISPLACES. Naming one creates a
    #: retirement obligation (ADR 0039 § 9); leaving it empty claims none.
    displaces: tuple[str, ...] = ()
    #: The TYPED writer claims that answer the obligation. Never prose.
    retirement: tuple[WriterClaim, ...] = ()

    def __post_init__(self) -> None:
        where = f"binding {self.implementation!r}"
        if not str(self.implementation).strip():
            raise SpecError("a binding with no implementation names nothing")
        if not str(self.version).strip():
            raise SpecError(f"{where}: version may not be empty; § 3 requires it exact")
        _require_coordinate(self.coordinates, where=where)

        if not self.displaces:
            if self.retirement:
                raise SpecError(
                    f"{where}: carries retirement evidence and displaces "
                    "nothing. Evidence for an obligation nobody owes is a claim "
                    "about the wrong thing"
                )
            return

        # § 9: a binding that displaces a local writer or executor OWES typed
        # retirement evidence. Silence is UNKNOWN, never "nothing to retire" —
        # a consumer that needs an answer refuses rather than reading absence
        # as a clean bill of health. That rule is not new here; it is what the
        # Expenses roster violated.
        if not self.retirement:
            raise SpecError(
                f"{where}: displaces {list(self.displaces)} and carries NO "
                "typed retirement evidence. Silence is UNKNOWN, not 'nothing to "
                "retire' — reading absence as clearance is exactly the Expenses "
                "failure, where a product was rostered 'no writer in scope' "
                "while another held two. Supply WriterClaim rows, not prose",
                where=where,
            )
        claimed = {claim.product for claim in self.retirement}
        unanswered = sorted(set(self.displaces) - claimed)
        if unanswered:
            raise SpecError(
                f"{where}: displaces {unanswered} and no writer claim names "
                "them. A claim about some of the displaced writers is not "
                "evidence about the others",
                where=where,
            )
        outstanding = sorted(
            claim.product for claim in self.retirement if claim.outstanding
        )
        if outstanding:
            raise SpecError(
                f"{where}: {outstanding} still owe a retirement this binding "
                "claims to have displaced (retirement_required with disposition "
                "'not_yet'). ADR 0039 § 9 fixes the order: a binding is "
                "COMPOSED, then PROVEN, then the writer it displaces is "
                "RETIRED — never the same change. Claiming displacement before "
                "the retirement has a disposition is claiming the third step "
                "happened because the first one did",
                where=where,
            )

    def as_document(self) -> dict[str, Any]:
        return {
            "coordinates": self.coordinates,
            "displaces": sorted(self.displaces),
            "implementation": self.implementation,
            "state": "bound",
            "version": self.version,
        }


@dataclasses.dataclass(frozen=True, slots=True)
class InapplicableConcern:
    """A concern that genuinely does not apply — reason AND executable proof."""

    reason: str
    proof: AbsenceProof

    def __post_init__(self) -> None:
        if not str(self.reason).strip():
            raise SpecError(
                "an inapplicable concern must state a reason. A proof with no "
                "premise proves something nobody asked"
            )
        if not isinstance(self.proof, AbsenceProof):
            raise SpecError(
                "an inapplicable concern must carry an executable AbsenceProof, "
                f"got {type(self.proof).__name__}. Under ADR 0033 § 2 a "
                "negative claim without one is not a weaker claim — it is not a "
                "claim, and the concern is an UNMONITORED region rather than an "
                "exempt one"
            )

    def as_document(self) -> dict[str, Any]:
        return {
            "image_digest": self.proof.image_digest,
            "method": self.proof.method,
            "reason": self.reason,
            "state": "inapplicable",
            "visited": sorted(self.proof.families),
        }


#: WHAT A CONCERN SLOT MAY HOLD. Three constructible members for the four
#: states, and the fourth is deliberately not constructible.
#:
#: * :class:`ConcernBinding` — **bound**: a provider exists and answers;
#: * :class:`IntegrationSurfaceAbsenceProofV1` — **absent-proven**: the
#:   concern's subject is genuinely not there, established rather than assumed;
#: * :class:`InapplicableConcern` — **inapplicable**: refused by a standing
#:   ruling, carrying the ruling and an executable proof;
#: * **not-yet-implemented** has NO member, and that is the 13/13 gate. It is
#:   the absence of a slot, and :class:`ApplicationFoundationProfile` refuses a
#:   profile with any concern unfilled. A constructible "owed" member would be
#:   the knob that admits an incomplete profile for one deployment.
#:
#: ``IntegrationSurfaceAbsenceProofV1`` joined this union on 2026-09-05. Before
#: that it was a type nobody could put anywhere: its own docstring described
#: absent-proven as one of four states and said it SATISFIES a concern, while
#: the profile refused any slot that was not a binding or an inapplicable. So a
#: product with genuinely no integration surface could construct the proof and
#: still not reach 13/13 — the unmeetable gate the type was written to prevent,
#: reintroduced one level up by the vocabulary it was bolted beside.
ConcernSlot = ConcernBinding | InapplicableConcern | IntegrationSurfaceAbsenceProofV1


@dataclasses.dataclass(frozen=True, slots=True)
class ApplicationFoundationProfile:
    """One assembly's profile. THIRTEEN slots, every one filled.

    ``application`` is the assembly's name and must equal the entry point's,
    which is discovery refusal 5 — a profile answering to a different name was
    selected by nobody.
    """

    application: str
    slots: Mapping[FoundationConcern, ConcernSlot]

    def __post_init__(self) -> None:
        if not str(self.application).strip():
            raise SpecError("a profile with no application name identifies nothing")
        missing = sorted(
            concern.value for concern in FoundationConcern if concern not in self.slots
        )
        if missing:
            raise SpecError(
                f"the profile for {self.application!r} omits {missing}. "
                "ADR 0039 § 4: a profile that omits a concern does not compose "
                "— not with a warning, not in a degraded mode, and not behind a "
                "knob that admits it for one deployment. A profile missing a "
                "concern is not a smaller profile; it is not one"
            )
        unknown = sorted(
            str(key) for key in self.slots if not isinstance(key, FoundationConcern)
        )
        if unknown:
            raise SpecError(
                f"the profile for {self.application!r} names {unknown}, which "
                "are not concerns. The thirteen are CLOSED (ADR 0039 § 2); a "
                "fourteenth is an amendment to that record"
            )
        wrong = sorted(
            concern.value
            for concern, slot in self.slots.items()
            if not isinstance(
                slot,
                ConcernBinding | InapplicableConcern | IntegrationSurfaceAbsenceProofV1,
            )
        )
        if wrong:
            raise SpecError(
                f"the profile for {self.application!r} fills {wrong} with none "
                "of the three slot values: a ConcernBinding, a proven absence, "
                "or an InapplicableConcern"
            )
        # A proof carries its OWN concern, and the mapping key is the concern the
        # profile is claiming about. Nothing checked they agreed, because until
        # a proof could be a slot the question could not arise — and the moment
        # it can, it is the same failure the proof's own type refuses one level
        # down: one concern's evidence certifying another's emptiness. A profile
        # is the more dangerous level for it, because 13/13 is read off the slots.
        misfiled = sorted(
            f"{concern.value} is filled by a proof about {slot.concern.value}"
            for concern, slot in self.slots.items()
            if isinstance(slot, IntegrationSurfaceAbsenceProofV1)
            and slot.concern is not concern
        )
        if misfiled:
            raise SpecError(
                f"the profile for {self.application!r} misfiles proven "
                f"absences: {misfiled}. A proof establishes the absence of the "
                "concern it names and of no other; filed elsewhere it is a "
                "well-formed claim about a question nobody asked",
                code=ABSENCE_WRONG_CONCERN,
            )

    @property
    def bound(self) -> tuple[FoundationConcern, ...]:
        return tuple(
            concern
            for concern in FoundationConcern
            if isinstance(self.slots[concern], ConcernBinding)
        )

    @property
    def absent_proven(self) -> tuple[FoundationConcern, ...]:
        """Concerns whose subject was established ABSENT.

        A distinct answer from :attr:`inapplicable`, and the two must not be
        read together: inapplicable means a standing ruling says the question
        does not arise here, absent-proven means the question arose, was asked
        of the artifact, and the answer was nothing. One is a decision and the
        other is a measurement.
        """
        return tuple(
            concern
            for concern in FoundationConcern
            if isinstance(self.slots[concern], IntegrationSurfaceAbsenceProofV1)
        )

    @property
    def inapplicable(self) -> tuple[FoundationConcern, ...]:
        return tuple(
            concern
            for concern in FoundationConcern
            if isinstance(self.slots[concern], InapplicableConcern)
        )

    def as_document(self) -> dict[str, Any]:
        """The document the profile digest covers. Sorted, no wrapper."""
        return {
            "application": self.application,
            "concerns": {
                concern.value: self.slots[concern].as_document()
                for concern in FoundationConcern
            },
            "schema": APPLICATION_PROFILE_SCHEMA,
        }


# ── discovery: from the CANDIDATE IMAGE, never from a source checkout ────────

#: ADR 0039 § 5. The profile is DISCOVERED from the installed distribution's
#: entry-point metadata, not declared in `deploy/product.toml`.
#:
#: That is ADR 0021 § 2 applied to a second surface, and the asymmetry is worth
#: naming precisely: a source tree states what an assembly INTENDS to compose;
#: an image holds what it WILL run. They differ routinely and innocently — an
#: uncommitted pin, a build argument, a dependency resolved to a newer
#: compatible release, a wheel that never reached the registry — and every one
#: of those differences is invisible to a profile checked against the checkout.
#:
#: A profile in `deploy/product.toml` would be a CHECKOUT FACT DESCRIBING AN
#: IMAGE, which is the shape this group exists to refuse.
PROFILE_ENTRY_POINT_GROUP: Final = "dotmac_deployment_foundation.application_profile"


def discover_profile(*, entries: Any = None) -> ApplicationFoundationProfile | None:
    """Locate THE declared profile, or None, or refuse.

    The SECOND consumer of `discovery.discover_one`, and the reason that core
    was extracted rather than copied. All five refusals arrive by construction:
    two declarations, a failed import, a raising factory, a look-alike, and a
    profile answering to a name other than the entry point's.

    `name_of` reads `application` back off the profile, so the entry point name
    and the profile's own identity cannot drift.
    """
    from .discovery import discover_one

    return discover_one(
        group=PROFILE_ENTRY_POINT_GROUP,
        expected_type=ApplicationFoundationProfile,
        subject="application foundation profile",
        name_of=lambda profile: str(profile.application),
        entries=entries,
    )


# ── the digest, and the read-back parser ─────────────────────────────────────


def canonical_profile_bytes(document: Any) -> bytes:
    """The exact bytes the profile digest covers.

    The same rules `execution_plan.py` states exhaustively, for the same reason:
    more than one party computes or compares this value, so "whatever
    json.dumps did" is not a specification. Sorted keys at every depth, tight
    separators, ASCII only, no wrapper.
    """
    import json

    if not isinstance(document, dict):
        raise SpecError("a profile document must be a JSON object")
    if document.get("schema") != APPLICATION_PROFILE_SCHEMA:
        raise SpecError(
            f"this is not a {APPLICATION_PROFILE_SCHEMA} document (schema "
            f"{document.get('schema')!r}). The digest covers THIS document "
            "alone; hashing a wrapper that merely contains one is how two "
            "parties come to compute permanently unequal values while both "
            "look correct"
        )
    return json.dumps(
        document, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")


def profile_digest(document: Any) -> str:
    """``sha256`` over :func:`canonical_profile_bytes`."""
    from .digest import Digest

    return str(Digest.of(canonical_profile_bytes(document)))


def _binding_from_document(
    document: Mapping[str, Any], *, where: str
) -> ConcernBinding:
    unknown = sorted(set(document) - BINDING_FIELDS - {"state"})
    if unknown:
        raise SpecError(
            f"{where}: unknown binding field(s) {unknown}. ADR 0039 § 10's "
            "field set is CLOSED and an extra key is REFUSED rather than "
            "ignored — ignoring is how a closed set quietly opens, and a "
            "profile is the single most attractive place in an architecture to "
            "put a value with nowhere else to live. If two correct deployments "
            "of the same artifacts could hold different values for it, it is "
            "not a binding: it belongs to settings, the deployment descriptor, "
            "or the entitlement surface",
            where=where,
        )
    # V1 REJECTS retirement evidence rather than accepting and discarding it.
    #
    # `retirement` is in `BINDING_FIELDS`, so the closed-field check above lets
    # it through; this parser never read it; and `ConcernBinding.as_document`
    # never emits it. Three consequences followed, and the third is why this is
    # a refusal rather than a TODO:
    #
    #   * the PROFILE DIGEST DOES NOT COVER DISPLACEMENT EVIDENCE. A value the
    #     digest does not cover is a value nobody is bound to, however carefully
    #     it was written;
    #   * a caller supplying `displaces` WITH its `retirement` rows was refused
    #     by `ConcernBinding.__post_init__` for carrying NO typed retirement
    #     evidence — a message that is FALSE ABOUT ITS INPUT, because the input
    #     carried exactly that. An operator reading it would go and add what was
    #     already there;
    #   * so the accepting path silently dropped the evidence and the refusing
    #     path lied about why. Neither is a state to leave reachable.
    #
    # V2 represents displacement and retirement canonically — the profile binds
    # the specific legacy responsibility and its evidence reference, and terminal
    # retirement binds back to the replacing assembly and provider. Until then V1
    # says so, at the parse, in a message that is true about the document it was
    # handed.
    if "retirement" in document:
        raise SpecError(
            f"{where}: this document carries `retirement`, and "
            "ApplicationFoundationProfile.v1 cannot bind it — `as_document` "
            "does not emit it, so the profile digest would not cover it and "
            "nothing would be bound to what you wrote. Accepting and discarding "
            "it is worse than refusing: the binding would then be refused for "
            "carrying no retirement evidence, which is false about this "
            "document. Displacement and retirement are represented canonically "
            "in the successor admission contract; V1 rejects them",
            where=where,
        )
    return ConcernBinding(
        implementation=str(document["implementation"]),
        version=str(document["version"]),
        coordinates=str(document["coordinates"]),
        displaces=tuple(str(item) for item in document.get("displaces", ())),
    )


# ── B5: verify before deployment, read back after ────────────────────────────


def _absence_findings(
    concern: FoundationConcern,
    slot: IntegrationSurfaceAbsenceProofV1,
    *,
    label: str,
    artifact_digest: str,
    observed: Mapping[FoundationConcern, str],
) -> list[str]:
    """Re-ask a proven absence against independently derived values.

    Split out rather than inlined because the establishment rule is the reason
    an absence may fill a slot at all, and a rule buried in a loop body next to
    two version comparisons reads as one more check rather than as the thing
    holding the gate up.

    Every branch is a FINDING and none is a skip. The two missing-input cases
    are findings for the same reason a missing binding is: an oracle that could
    not be consulted has not agreed with anything, and reporting silence as
    agreement is how "13/13" stops meaning what it says.
    """
    findings: list[str] = []
    if not str(artifact_digest).strip():
        findings.append(
            f"{concern.value} ({label}) is filled by a proven absence and no "
            "artifact digest was supplied, so the proof could not be checked "
            "against anything. A proof satisfies only when ESTABLISHED; an "
            "oracle nobody consulted is not agreement"
        )
        return findings
    inventory = str(observed.get(concern, "")).strip()
    if not inventory:
        findings.append(
            f"{concern.value} ({label}) is filled by a proven absence and no "
            "independently observed inventory digest was supplied for it. The "
            "unmanufacturable half of the proof is exactly this comparison — "
            "without it the slot is a caller's own string agreeing with itself"
        )
        return findings
    if not slot.satisfies(
        concern, artifact_digest=artifact_digest, inventory_digest=inventory
    ):
        findings.append(
            f"{concern.value} ({label}) carries a proven absence that does NOT "
            f"establish anything about this artifact: the proof names "
            f"{slot.artifact_digest} / {slot.observed_inventory_digest} and the "
            f"artifact in hand is {artifact_digest} / {inventory}. A proof "
            "produced for another build is well-formed and says nothing about "
            "this one"
        )
    return findings


def verify_profile_against_candidate(
    profile: ApplicationFoundationProfile,
    *,
    image_digest: str,
    installed: Mapping[str, str],
    artifact_digest: str = "",
    observed_inventory_digests: Mapping[FoundationConcern, str] | None = None,
) -> tuple[str, ...]:
    """Every way the profile disagrees with what the CANDIDATE IMAGE holds.

    Findings, not an exception: an operator should see all of them at once, and
    this is report-only (see this module's docstring for the staging).

    ``installed`` maps implementation identity to the version the image actually
    carries, derived by the CALLER from the image's own distribution metadata.
    This facility opens no socket and reads no image; the subject of the check
    is an image DIGEST, and a verification that cannot say which bytes it read
    has made a claim about a directory rather than about an artifact (§ 5).

    **The verifier may not be the builder.** A job reporting on the bytes it
    just produced is not an independent witness of them. That split is the
    caller's to arrange — this function cannot enforce it — and it is stated
    here because a reader wiring this into the build job would otherwise be
    satisfying the letter of § 5 while losing its point.

    ADR 0039 § 7 requires each binding to carry a positive AND a negative test.
    The three planted defects that must each refuse, naming the binding, are:
    the binding removed; the binding naming a version other than the installed
    one; the binding naming a version installed in the CHECKOUT but absent from
    the IMAGE. The third is why ``installed`` is the image's inventory and never
    the source tree's.

    ## Proven absences are RE-ESTABLISHED here, and this is the half that keeps
    ## the gate from being bypassable

    A proven absence became a slot value on 2026-09-05, and admitting it is the
    easy half. The load-bearing half is Michael's standing constraint: **it
    satisfies only when ESTABLISHED, never when merely well-formed.**

    Construction settles well-formedness and nothing else — a caller can write
    any string into ``observed_inventory_digest``. So every absent-proven slot
    is re-asked here against values the CALLER derived independently, through
    the proof's own :meth:`~IntegrationSurfaceAbsenceProofV1.satisfies`, which
    compares rather than trusts.

    **A slot whose evidence was not supplied is a FINDING, never a pass.** That
    is the whole point: had the verifier skipped an absent-proven slot the way
    it skips a non-binding one, a well-formed proof of nothing would have filled
    a concern and reached 13/13 without anybody examining an artifact. Silence
    and establishment must not produce the same outcome.

    ## Two digests, and they are not the same value

    ``image_digest`` is the candidate OCI image, and it is what a BINDING is
    checked against. ``artifact_digest`` is the Platform application wheel, and
    it is what a PROVEN ABSENCE is checked against — a proof travelling inside
    an image cannot name that image, which is why the proof's field was renamed
    away from ``image_digest`` in the first place. Comparing a proof against the
    image digest would never match and would make the gate unsatisfiable, which
    is the failure that looks like strictness.

    ``artifact_digest`` defaults to empty so a profile with no proven absence is
    unaffected. A profile that HAS one and no artifact digest is a finding — an
    unavailable oracle is not a pass.
    """
    _require_coordinate(image_digest, where="candidate image_digest")
    observed = dict(observed_inventory_digests or {})
    findings: list[str] = []
    for concern in FoundationConcern:
        slot = profile.slots[concern]
        label = CONCERN_LABELS[concern]
        if isinstance(slot, IntegrationSurfaceAbsenceProofV1):
            findings.extend(
                _absence_findings(
                    concern,
                    slot,
                    label=label,
                    artifact_digest=artifact_digest,
                    observed=observed,
                )
            )
            continue
        if not isinstance(slot, ConcernBinding):
            continue
        present = installed.get(slot.implementation)
        if present is None:
            findings.append(
                f"{concern.value} ({label}) binds {slot.implementation!r} "
                f"{slot.version}, which the candidate image {image_digest} does "
                "NOT carry. A binding names what the image WILL run; a source "
                "tree stating what it intends to compose is a different claim"
            )
            continue
        if str(present) != str(slot.version):
            findings.append(
                f"{concern.value} ({label}) binds {slot.implementation!r} "
                f"{slot.version} and the candidate image carries {present}. An "
                "approval for a reviewed version does not authorize another"
            )
    return tuple(findings)


def require_profile_readback(*, authorized: str, observed: str) -> str:
    """Compare the running system's profile digest with the authorized one.

    **This COMPARES; it never DERIVES.** ADR 0032 § 2 is directional and applies
    without modification: the profile is the authority and the running system is
    not the transcript it is written from. Editing an accepted profile to match
    what a deployed image turned out to contain inverts the relationship, and
    from that moment drift and correction arrive as the same commit, with the
    same diff, for the same stated reason.

    A disagreement is repaired by promoting a candidate through the mechanism,
    which leaves a receipt — never by an edit that leaves only a diff.

    An EMPTY observed digest is a mismatch, not a pass: a running system that
    cannot say which profile it composed has not answered the question.
    """
    if not str(authorized).strip():
        raise PreconditionFailed(
            "no authorized profile digest was supplied, so the read-back has "
            "nothing to compare against. Refusing rather than accepting "
            "whatever the running system reports — that is the direction ADR "
            "0032 § 2 forbids"
        )
    if str(observed) != str(authorized):
        raise PreconditionFailed(
            f"the authorized application profile digest is {authorized} and the "
            f"running system reports {observed or '(nothing)'}. The deployed "
            "system is not composing what was approved. This is NOT repaired by "
            "editing the profile to match: promote a candidate through the "
            "mechanism, which leaves a receipt, rather than an edit that leaves "
            "only a diff"
        )
    return str(authorized)
