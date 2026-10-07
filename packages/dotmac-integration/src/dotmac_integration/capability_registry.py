"""Who OWNS a capability contract — and the three ways a declaration is wrong.

`provider-capability-sources.md` § 7.2 records the gap this module closes:

    There is no capability-id *registry* anywhere in the fleet. The id is an
    open string checked by a regex, with no declaration, no owner and no
    collision check across distributions.

ADR-0008's answer to an open vocabulary is a declaration registry, and its
governing rule is the one that shapes every line below: **the layer that HOSTS a
vocabulary never enumerates its members.** `dotmac-integration` hosts capability
ids. It therefore contains no capability-id literal of its own — proven, not
promised, by `tests/architecture/test_capability_ownership.py`.

## Three parties, three verbs

=========================== ================================================
party                       verb
=========================== ================================================
the **business domain owner** DECLARES the capability. `messaging.receive.v1`
                            is Sub's communications contract; Sub says what an
                            inbound message means, and nobody else can.
**`dotmac-integration`**    VALIDATES and BINDS the declaration. It refuses a
                            duplicate, an unknown and an orphan. It never mints
                            one.
the **connector plugin**    IMPLEMENTS a declared capability at an accepted
                            version. A manifest is a claim to implement, never
                            a claim to define.
=========================== ================================================

That split is ADR-0030 § 8.2's, restated as executable refusals.

## The declaration cannot be an import

ADR-0024 makes applications independent: the Integrator does not import Sub, and
could not — they are separate deployments with separate databases. So a
declaration travels as DATA, supplied by the composing assembly at startup, in
exactly the shape `dotmac_kernel.secret_sources.install_secret_source` already
established for material the module cannot fetch for itself:

* installed ONCE, by :func:`install_capability_registry`;
* read afterwards as a plain lookup, never a fetch;
* **fail closed** — :func:`capability_registry` raises when nothing was
  installed, because an empty registry and an uninstalled one are different
  facts and treating them alike would let a misconfigured assembly accept every
  binding by declaring nothing.

## Three failures, three exceptions, three messages

A single "invalid capability" error would tell an operator that something is
wrong and not what to do about it. Each of these has a different fix, so each
has its own type and its own sentence:

:class:`DuplicateCapabilityDeclaration`
    Two owners claim one id, or one owner declared it twice. Fixed by the
    domain owners, agreeing which of them owns the contract.

:class:`UnknownCapabilityError`
    A binding — or a connector manifest — names an id nobody declared. Fixed by
    the operator, binding a declared capability instead.

:class:`OrphanCapabilityError`
    A declaration no installed connector implements. Fixed by the deployment,
    installing a connector that implements it or retiring the declaration.

The orphan check is the one that looks optional and is not. A declared
capability with no implementation reads, on an operations screen, exactly like a
working integration: the contract is published, the vocabulary resolves, and
nothing will ever arrive. That is ADR-0008's "dead vocabulary that reads as a
working gate", in the one registry where the silence is indistinguishable from
an idle channel.

## The SCHEMA is here too, for exactly the same reason as the id

ADR-0024 § 10 (2026-08-24). A capability id was already one contract with one
owner; its PAYLOAD was not. `CapabilityDeclaration` carried a config schema and
`DispatchRequest.payload` was an unvalidated `dict[str, object]`, so
configuration had a declared contract and commands did not — which is how one id
grew two disjoint command vocabularies without any gate noticing.

The obvious repair — let each connector publish a command schema — is the wrong
one, and § 10.1 says why: two connectors serving one id would then publish two
individually valid schemas, and the engine would have no ground to prefer
either. Machine-readable disagreement is still disagreement. So the schema lives
where the MEANING already lives, on the contract the owning application
publishes, of which this registry already permits exactly one per id:

* :attr:`CapabilityContract.command_schema` — what a product may SEND;
* :attr:`CapabilityContract.result_schema` — what a connector may RETURN;
* :attr:`CapabilityContract.observation_schema` — what an inbound fact IS;
* :attr:`CapabilityContract.contract_digest` — those three, canonicalized, so
  agreement is a comparison and never a re-derivation;
* :class:`ContractDeprecation` — which id replaces this one, and by when.

A connector may only CLAIM that digest
(:attr:`~dotmac_integration.spi.CapabilityDeclaration.claims_contract_digest`).
A claim is not a definition.

## What a contract with no schema is allowed to be

Fail-closed on SILENCE, not on absence. Every capability in the fleet predates
this rule, so a contract may still be ungated — but only by SAYING SO, with a
:class:`SchemaGrace` carrying a reason and a `retire_after` date. A contract that
declares neither a schema nor a grace is refused at construction.

That distinction is the whole adoption argument. A permanently optional
`command_schema` is how this defect returns: every future contract would be free
to publish nothing, and the register of what is ungated would be
indistinguishable from the register of what nobody has looked at. A declared,
dated grace makes the ungated set enumerable (:func:`schema_grace_register`),
attributable to an owner, and finite — the window closes, and closing it is a
reviewable diff rather than a decision nobody ever makes.

## A published version is SUCCEEDED, never redefined

ADR-0024 § 11. Three refusals carry it, none of which needs a durable row:

* a schema change changes the digest, so every connector claiming the old one is
  refused at composition AND at binding;
* :func:`install_capability_registry` refuses a reload that gives an already
  published id a DIFFERENT digest — replacement stays allowed, redefinition does
  not;
* a contract that declares itself deprecated must name a successor that is
  declared in the same registry, so a retirement cannot point at nothing.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Final

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError, ValidationError

from dotmac_integration.spi import (
    CapabilityDeclaration,
    ConnectorManifest,
    canonical_digest,
)

__all__ = [
    "EMPTY_REGISTRY",
    "CapabilityContract",
    "CapabilityContractDigestMismatch",
    "CapabilityContractRedefined",
    "CapabilityOwner",
    "CapabilityPayloadRejected",
    "CapabilityRegistry",
    "CapabilityRegistryError",
    "CapabilityRegistryNotInstalled",
    "ContractDeprecation",
    "DuplicateCapabilityDeclaration",
    "InvalidCapabilitySchema",
    "MissingCapabilitySchema",
    "OrphanCapabilityError",
    "SchemaGrace",
    "SchemaGraceEntry",
    "SchemaGraceExpired",
    "UnknownCapabilityError",
    "capability_registry",
    "contract_from_declaration",
    "install_capability_registry",
    "require_contract_agreement",
    "require_declared_for_binding",
    "require_governable",
    "require_implements_only_declared",
    "require_no_expired_grace",
    "require_no_orphans",
    "schema_grace_register",
]


class CapabilityRegistryError(ValueError):
    """A capability declaration, or a reference to one, is not governable."""


class DuplicateCapabilityDeclaration(CapabilityRegistryError):
    """One capability id is declared twice — ambiguous ownership."""


class UnknownCapabilityError(CapabilityRegistryError):
    """Something names a capability id nobody declared."""


class OrphanCapabilityError(CapabilityRegistryError):
    """A declared capability that no installed connector implements."""


class CapabilityRegistryNotInstalled(CapabilityRegistryError):
    """No assembly supplied a registry. Distinct from an EMPTY registry."""


class InvalidCapabilitySchema(CapabilityRegistryError):
    """A contract declares something that is not a valid JSON schema.

    Refused at CONSTRUCTION, like every other malformed declaration here: a
    schema that cannot compile validates nothing, and a gate that silently
    validates nothing is worse than no gate, because an operations screen shows
    a contract with a published payload.
    """


class MissingCapabilitySchema(CapabilityRegistryError):
    """A seam needs a schema this contract's owner never published.

    Distinct from :class:`CapabilityPayloadRejected` on purpose. That one is a
    caller's defect and the caller fixes the payload; this one is the OWNER's
    omission and only the owner can fix it — a delivery capability whose
    contract publishes an `observation_schema` and no `command_schema` is a
    contract that has not decided what a command is.
    """


class CapabilityPayloadRejected(CapabilityRegistryError):
    """A command, result or observation violates its published schema.

    ## Why the message never contains the value

    The payload is the one thing this exception must not repeat. It carries a
    product's business content, and on the result path it has just come back
    from a connector that was handed materialized secrets. `dispatch` already
    reduces a connector exception to its TYPE NAME for exactly this reason, and
    `ingress` converts driver errors precisely because the driver's message
    carries the bound parameters.

    jsonschema's own `ValidationError.message` interpolates the offending
    instance — `'4111111111111111' is not of type 'integer'` — and these
    messages are PERSISTED to `delivery_attempts.error_detail`. So the summary
    is built from the JSON POINTER and the failing KEYWORD only, which locates
    the defect exactly and repeats no value.
    """


class CapabilityContractDigestMismatch(CapabilityRegistryError):
    """A connector's claimed contract digest is not the owner's.

    Three ways, one exception, three sentences — the claim disagrees, the claim
    is missing where a schema is published, or the claim exists where nothing is
    published. All three mean the same thing operationally: this connector was
    built against a payload contract that is not the one installed.
    """


class CapabilityContractRedefined(CapabilityRegistryError):
    """A published capability id was given different schemas.

    ADR-0024 § 11: a published contract version is SUCCEEDED, never redefined.
    The repair is a new `.vN` id with its own contract, and deprecation metadata
    on this one naming it.
    """


class SchemaGraceExpired(CapabilityRegistryError):
    """A contract's declared ungated window has closed.

    Deliberately a refusal rather than a warning. A grace whose expiry does
    nothing is a permanent optional field with a date attached, which is the
    exact shape ADR-0024 § 10 exists to stop. The fix is in the OWNER's
    repository and is one of two reviewable diffs: publish the schemas, or move
    the date and say why.
    """


@dataclass(frozen=True, slots=True)
class CapabilityOwner:
    """The application and module that own a capability's MEANING.

    `application` is an application key in the fleet's own vocabulary (`sub`,
    `erp`, …) — not a URL, not a host and not a connector key. The Integrator
    never resolves it to an address; `dotmac_integration.destination_binding`
    does that only against profiles the assembly supplied.
    """

    application: str
    module: str

    def __post_init__(self) -> None:
        for field_name in ("application", "module"):
            value = getattr(self, field_name)
            if not value or value.strip() != value or value != value.lower():
                raise CapabilityRegistryError(
                    f"capability owner {field_name} {value!r} must be a "
                    "non-empty, lowercase, whitespace-free key"
                )

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"{self.application}/{self.module}"


def _today() -> date:
    """The engine's idea of now, in UTC.

    A grace window is a fleet-wide statement, so it closes on a UTC date rather
    than on whatever the host's local calendar says — otherwise the same
    deployment expires a contract on two different days depending on where its
    workers run.
    """
    return datetime.now(UTC).date()


def _require_valid_schema(capability_id: str, name: str, schema: object) -> None:
    try:
        Draft202012Validator.check_schema(schema)
    except (SchemaError, AttributeError, TypeError):
        raise InvalidCapabilitySchema(
            f"capability {capability_id!r} declares a {name} that is not a valid "
            "JSON Schema (2020-12). A schema that cannot compile validates "
            "nothing, and an operations screen would still show this capability "
            "as having a published payload contract"
        ) from None


def _violation_summary(error: ValidationError) -> str:
    """WHERE it failed and WHICH keyword refused. Never the value.

    See :class:`CapabilityPayloadRejected` for why this is not a convenience.
    `error.message` interpolates the instance, `error.json_path` does not, and
    the difference is a product's business content — or a value a connector
    lifted out of a provider response — in a persisted `error_detail` column.
    """
    return f"{error.json_path}: {error.validator}"


@dataclass(frozen=True, slots=True)
class SchemaGrace:
    """An owner's EXPLICIT statement that a contract is not gated yet.

    The alternative — schemas that are simply optional — is how the defect
    ADR-0024 § 10 records comes back: nothing distinguishes "this owner has not
    published a payload contract" from "nobody has looked at this capability",
    and no operator can enumerate the second set. A grace is that same
    ungatedness, said out loud, with a name attached and an end date.

    `reason` is prose for a REVIEWER, so it must state what is unresolved rather
    than that something is. `retire_after` is the date the window closes, after
    which every seam refuses (:class:`SchemaGraceExpired`) — a compatibility
    window with no closing date is one that never closes.
    """

    reason: str
    retire_after: date
    #: Where the closure is tracked — an ADR id, a plan path, an issue key.
    #: Free text, because the Integrator hosts this vocabulary and enumerates
    #: no member of it (ADR-0008), including the fleet's own record ids.
    tracked_by: str = ""

    def __post_init__(self) -> None:
        if not self.reason.strip():
            raise CapabilityRegistryError(
                "a schema grace must state WHY the contract is ungated; an "
                "unexplained grace is an optional field with a date on it"
            )
        if not isinstance(self.retire_after, date) or isinstance(
            self.retire_after, datetime
        ):
            raise CapabilityRegistryError(
                "a schema grace must retire on a calendar date (datetime.date); "
                "an instant would make the window close at an arbitrary hour"
            )

    def expired(self, now: date | None = None) -> bool:
        return (now or _today()) > self.retire_after


@dataclass(frozen=True, slots=True)
class ContractDeprecation:
    """This version is superseded — by WHAT, and until WHEN it still answers.

    ADR-0024 § 11.1. Both fields are required because both halves of the
    obligation are: a deprecation with no successor tells a product to stop and
    not what to start, and a retirement with no recorded date is a compatibility
    window that never closes.
    """

    replaced_by: str
    retire_after: date
    reason: str = ""

    def __post_init__(self) -> None:
        # The successor is a capability id, so it is shape-checked the one way
        # this package checks capability ids — by constructing the SPI's frozen
        # declaration. A second regex would be a second answer.
        CapabilityDeclaration(capability_id=self.replaced_by)
        if not isinstance(self.retire_after, date) or isinstance(
            self.retire_after, datetime
        ):
            raise CapabilityRegistryError(
                "a deprecation must retire on a calendar date (datetime.date)"
            )


@dataclass(frozen=True, slots=True)
class CapabilityContract:
    """One capability id, its owner, its version — and its PAYLOAD contract.

    The id shape is validated by constructing Team 1's frozen
    :class:`~dotmac_integration.spi.CapabilityDeclaration`, so the registry and
    the SPI cannot drift into two opinions about what a legal id looks like. A
    second regex here would be a second answer to one question.

    ## The three schemas, and the one thing that is refused

    `command_schema`, `result_schema` and `observation_schema` are the payload
    contract ADR-0024 § 10.2 puts here rather than on the connector. A contract
    declares the ones its capability actually has: a DELIVERY capability
    publishes a command and (where a connector returns anything) a result; an
    INGRESS or POLL capability publishes an observation. Declaring all three is
    legitimate for a capability that genuinely has all three; declaring NONE is
    refused unless a :class:`SchemaGrace` says so explicitly.

    That last refusal is the entire adoption decision, and it is deliberately
    not "schemas are optional for now". Optional-for-now has no end and no
    register: nothing would separate an owner who has not published a payload
    contract from an owner nobody has asked, and the fleet would carry an
    unbounded set of ungated ids that reads exactly like a gated one. A grace
    makes that set enumerable (:func:`schema_grace_register`), owned, dated and
    finite.
    """

    capability_id: str
    owner: CapabilityOwner
    summary: str
    #: What a product may SEND for a DELIVERY capability, or supply as the
    #: bounded input to a caller-initiated REQUEST capability. The stored name
    #: remains stable so adding REQUEST does not redefine published digests or
    #: product-port descriptor documents.
    command_schema: dict[str, object] | None = None
    #: The NORMALIZED outcome body a connector may return (`Outcome.result`).
    result_schema: dict[str, object] | None = None
    #: The typed observation an INGRESS or POLL capability yields, or the
    #: normalized synchronous observation a REQUEST returns.
    observation_schema: dict[str, object] | None = None
    #: Set once this version is superseded. Never a way to change it in place.
    deprecation: ContractDeprecation | None = None
    #: Set INSTEAD of the schemas, and only with a reason and a closing date.
    schema_grace: SchemaGrace | None = None

    def __post_init__(self) -> None:
        # Raises `InvalidManifestError` on a malformed id — reused deliberately.
        CapabilityDeclaration(capability_id=self.capability_id)
        if not self.summary.strip():
            raise CapabilityRegistryError(
                f"capability {self.capability_id!r} is declared with no summary; "
                "a contract nobody can describe is not a contract"
            )
        for name, schema in (
            ("command_schema", self.command_schema),
            ("result_schema", self.result_schema),
            ("observation_schema", self.observation_schema),
        ):
            if schema is not None:
                _require_valid_schema(self.capability_id, name, schema)
        if self.declares_schemas and self.schema_grace is not None:
            raise CapabilityRegistryError(
                f"capability {self.capability_id!r} declares both a payload "
                "schema and a schema grace. A grace is the statement that "
                "NOTHING is published yet; publishing anything ends it. Drop the "
                "grace, or publish the remaining schemas"
            )
        if not self.declares_schemas and self.schema_grace is None:
            raise CapabilityRegistryError(
                f"capability {self.capability_id!r} declares no command, result "
                "or observation schema and no SchemaGrace. One capability id is "
                "one contract with one payload (ADR-0024 § 8.1), so an owner "
                "either publishes that payload or states in the declaration that "
                "it has not yet, with a reason and a retire_after date. Silence "
                "is refused: an ungated capability nobody can enumerate is "
                "indistinguishable from a gated one"
            )
        if (
            self.deprecation is not None
            and self.deprecation.replaced_by == self.capability_id
        ):
            raise CapabilityRegistryError(
                f"capability {self.capability_id!r} names ITSELF as its "
                "replacement. A published version is succeeded by a different "
                "id, never by a redefinition of the same one (ADR-0024 § 11)"
            )

    @property
    def domain(self) -> str:
        """Everything before the version — `messaging.receive` for `…receive.v1`."""
        return self.capability_id.rsplit(".", 1)[0]

    @property
    def contract_version(self) -> int:
        """The `vN` suffix. The version is part of the id's IDENTITY, so `.v1`
        and `.v2` are two contracts one owner may publish independently."""
        return int(self.capability_id.rsplit(".v", 1)[1])

    @property
    def declares_schemas(self) -> bool:
        return any(
            schema is not None
            for schema in (
                self.command_schema,
                self.result_schema,
                self.observation_schema,
            )
        )

    @property
    def contract_digest(self) -> str | None:
        """The canonical digest of this contract's PAYLOAD, or `None` in grace.

        Over the three schemas and the id, and nothing else. The id is included
        so a claim is bound to the capability it was made for — otherwise two
        capabilities that happened to share a shape would accept each other's
        claims, and a copy-pasted digest would pass.

        Deliberately NOT over `summary`, `owner`, `deprecation` or
        `schema_grace`. Deprecating a contract must not invalidate every
        connector claiming it — that is the same reasoning
        `ConnectorManifest.digest` states for excluding documentation, and here
        it matters more: deprecation is precisely the moment a fleet needs its
        existing connectors to keep working while products migrate.

        `None` in grace rather than a digest over three nulls, because those are
        different facts. A digest would let a connector CLAIM agreement with a
        payload contract that does not exist, and agreement with nothing is not
        agreement.
        """
        if not self.declares_schemas:
            return None
        return canonical_digest(
            {
                "capability_id": self.capability_id,
                "command_schema": self.command_schema,
                "result_schema": self.result_schema,
                "observation_schema": self.observation_schema,
            }
        )

    # ── The three payload gates ────────────────────────────────────────────

    def require_command(self, payload: object, *, now: date | None = None) -> None:
        """ADR-0024 § 10.4.1 — called before a delivery row exists."""
        self._require("command", self.command_schema, payload, now=now)

    def require_request(self, payload: object, *, now: date | None = None) -> None:
        """Validate caller-initiated read input before connector I/O.

        REQUEST reuses the published ``command_schema`` slot deliberately. It
        is the domain-owned caller-to-connector payload in both modes; adding a
        fourth schema field would change every existing contract digest and the
        exact product-port descriptor v3 wire shape without adding meaning.
        """

        self._require("request", self.command_schema, payload, now=now)

    def require_result(self, body: object, *, now: date | None = None) -> None:
        """ADR-0024 § 10.4.3 — called before the claim-guarded settle UPDATE."""
        self._require("result", self.result_schema, body, now=now)

    def require_observation(self, payload: object, *, now: date | None = None) -> None:
        """ADR-0024 § 10.4.4 — called before an inbound batch is recorded."""
        self._require("observation", self.observation_schema, payload, now=now)

    def _require(
        self,
        direction: str,
        schema: dict[str, object] | None,
        instance: object,
        *,
        now: date | None,
    ) -> None:
        grace = self.schema_grace
        if grace is not None:
            if grace.expired(now):
                raise SchemaGraceExpired(
                    f"capability {self.capability_id!r} (owner {self.owner}) was "
                    f"declared ungated until {grace.retire_after.isoformat()} "
                    f"because: {grace.reason}. That window has closed. Publish "
                    f"the {direction}_schema on the contract, or move the date "
                    "in the owning application's declaration and say why"
                    + (f" — tracked by {grace.tracked_by}" if grace.tracked_by else "")
                )
            return
        if schema is None:
            raise MissingCapabilitySchema(
                f"capability {self.capability_id!r} (owner {self.owner}) "
                f"publishes a payload contract but no {direction}_schema, and "
                f"this is a {direction} path. The owning module declares what a "
                f"{direction} for this capability is — the Integrator will not "
                "guess, and a connector may not decide"
            )
        errors = sorted(
            Draft202012Validator(schema).iter_errors(instance),
            key=lambda error: error.json_path,
        )
        if errors:
            raise CapabilityPayloadRejected(
                f"{direction} rejected by capability {self.capability_id!r}"
                f" (owner {self.owner}): "
                + "; ".join(_violation_summary(error) for error in errors[:5])
                + (f" (+{len(errors) - 5} more)" if len(errors) > 5 else "")
                + ". Reported as JSON pointer and failing keyword only — the "
                "value is deliberately not repeated into a persisted column"
            )


@dataclass(frozen=True, slots=True)
class CapabilityRegistry:
    """The declared capability vocabulary — supplied, never authored, here.

    Construction is validation, matching
    :class:`~dotmac_integration.discovery.ConnectorRegistry`: a registry that
    exists is one whose ids are unique. Duplicate ownership is refused at build
    time rather than at first use, so a misconfigured composition fails at boot
    where an operator is watching.
    """

    contracts: tuple[CapabilityContract, ...]

    def __post_init__(self) -> None:
        seen: dict[str, CapabilityContract] = {}
        for contract in self.contracts:
            previous = seen.get(contract.capability_id)
            if previous is not None:
                raise DuplicateCapabilityDeclaration(
                    f"capability {contract.capability_id!r} is declared twice — "
                    f"by {previous.owner} and by {contract.owner}. A capability "
                    "id names one business contract with one owner; two "
                    "declarations mean two answers to what a payload MEANS, and "
                    "the Integrator cannot choose between them"
                )
            seen[contract.capability_id] = contract
        for contract in self.contracts:
            deprecation = contract.deprecation
            if deprecation is None:
                continue
            if deprecation.replaced_by not in seen:
                raise UnknownCapabilityError(
                    f"capability {contract.capability_id!r} is deprecated in "
                    f"favour of {deprecation.replaced_by!r}, which no owner "
                    "declared in this registry. A retirement that points at "
                    "nothing is a deadline with no destination: the product told "
                    "to migrate has nowhere to migrate to. Publish the successor "
                    "contract in the same declaration (ADR-0024 § 11.1)"
                )

    @classmethod
    def from_declarations(
        cls, contracts: Iterable[CapabilityContract]
    ) -> CapabilityRegistry:
        return cls(tuple(contracts))

    @property
    def declared_ids(self) -> frozenset[str]:
        return frozenset(c.capability_id for c in self.contracts)

    def get(self, capability_id: str) -> CapabilityContract:
        """The declared contract, or :class:`UnknownCapabilityError`."""
        for contract in self.contracts:
            if contract.capability_id == capability_id:
                return contract
        raise UnknownCapabilityError(
            f"capability {capability_id!r} is not declared by any owning "
            f"application; declared: {sorted(self.declared_ids)}. The owning "
            "business module declares a capability — the Integrator never "
            "mints one, and a connector never mints one"
        )

    def owned_by(self, application: str) -> tuple[CapabilityContract, ...]:
        return tuple(c for c in self.contracts if c.owner.application == application)


# ── The assembly-supplied seam ──────────────────────────────────────────────
#
# A module-level holder, exactly like `dotmac_kernel.secret_sources`: this
# module can neither fetch a declaration nor invent one, so the composing
# assembly hands it over once at startup. `None` means "nothing installed" and
# is deliberately distinguishable from an empty registry.

_INSTALLED: CapabilityRegistry | None = None

#: The sentinel an uninstalled registry is NOT. Kept as a name so a reader sees
#: that "empty" is a legitimate, reachable state — a deployment integrating with
#: nothing declares nothing — and that it is not what an omission produces.
EMPTY_REGISTRY: Final[CapabilityRegistry] = CapabilityRegistry(())


def install_capability_registry(registry: CapabilityRegistry) -> None:
    """Install the declared vocabulary. Called ONCE, at startup, by the assembly.

    Idempotent only in the trivial sense: installing a second, different
    registry replaces the first. That is a deliberate allowance for a controlled
    reload, and it is why the registry is a value object — a caller cannot
    mutate the installed one into a state nothing validated.

    **Replacement is allowed; REDEFINITION is not** (ADR-0024 § 11). A reload
    may add contracts, drop contracts, deprecate a contract or fill in a grace
    that has now been published — but it may not give an id that already
    published a payload contract a DIFFERENT one. That is the one edit § 11
    forbids outright, and it is the only edit a digest can detect without a
    durable row: the repair is a new `.vN` id with its own contract and
    deprecation metadata on this one naming it.

    A contract moving OUT of grace (nothing published, then something) is a
    first definition rather than a redefinition, and is allowed — there is no
    published shape for a product or a connector to have been built against.
    """
    global _INSTALLED
    previous = _INSTALLED
    if previous is not None:
        _require_no_redefinition(previous, registry)
    _INSTALLED = registry


def _require_no_redefinition(
    previous: CapabilityRegistry, current: CapabilityRegistry
) -> None:
    published = {
        contract.capability_id: digest
        for contract in previous.contracts
        if (digest := contract.contract_digest) is not None
    }
    for contract in current.contracts:
        was = published.get(contract.capability_id)
        if was is None:
            continue
        now = contract.contract_digest
        if now is None:
            raise CapabilityContractRedefined(
                f"capability {contract.capability_id!r} previously published a "
                "payload contract and is now declared ungated. A published "
                "version cannot be un-published: every product and connector "
                "built against it is still built against it"
            )
        if now != was:
            raise CapabilityContractRedefined(
                f"capability {contract.capability_id!r} was published with "
                f"contract digest {was[:12]} and is being reinstalled with "
                f"{now[:12]}. A published contract version is SUCCEEDED, never "
                "redefined (ADR-0024 § 11): publish the change as a new `.vN` "
                "id, and add ContractDeprecation(replaced_by=..., "
                "retire_after=...) to this one"
            )


def capability_registry() -> CapabilityRegistry:
    """The installed registry, or a refusal.

    Never returns an empty registry as a stand-in for an uninstalled one. An
    assembly that forgot to declare its vocabulary would otherwise get a
    registry that answers "nobody declared that" to every question — which is
    the *correct* answer to a real unknown capability and a *silent
    misconfiguration* here, and the two must not look alike.
    """
    if _INSTALLED is None:
        raise CapabilityRegistryNotInstalled(
            "no capability registry was installed; the composing assembly must "
            "call install_capability_registry(...) at startup with the "
            "declarations its owning applications published. A deployment that "
            "integrates with nothing installs EMPTY_REGISTRY explicitly"
        )
    return _INSTALLED


def _reset_capability_registry() -> None:
    """Test seam. Restores the uninstalled state — not an empty registry."""
    global _INSTALLED
    _INSTALLED = None


# ── The three governance refusals ───────────────────────────────────────────


def require_contract_agreement(
    registry: CapabilityRegistry,
    manifest: ConnectorManifest,
    *,
    capability_ids: Iterable[str] | None = None,
) -> None:
    """Refusal 4: a connector's CLAIM must be the owner's published digest.

    ADR-0024 § 10.4.2. Three failures, one exception, three sentences, because
    an operator reads them differently:

    ==========================  =============================================
    the claim differs           the connector was built against another
                                version of the payload contract. Rebuild it
                                against the installed one, or install the
                                contract it was built for.
    the claim is missing        the owner has published a payload contract and
                                this connector has not said which one it
                                implements. A connector that need not agree is
                                a connector free to disagree, and the gate
                                would be opt-in from the side it polices.
    the claim exists anyway     the owner has published NOTHING, so there is
                                nothing to agree with. A digest here is a
                                connector asserting a payload contract into
                                existence, which is § 10.3's whole prohibition.
    ==========================  =============================================
    """
    wanted = frozenset(capability_ids) if capability_ids is not None else None
    for declaration in manifest.capabilities:
        if wanted is not None and declaration.capability_id not in wanted:
            continue
        contract = registry.get(declaration.capability_id)
        published = contract.contract_digest
        claimed = declaration.claims_contract_digest
        where = (
            f"connector {manifest.connector_key!r} v{manifest.version} "
            f"capability {declaration.capability_id!r}"
        )
        if published is None:
            if claimed is not None:
                raise CapabilityContractDigestMismatch(
                    f"{where} claims contract digest {claimed[:12]}, but its "
                    f"owning application {contract.owner} has published no "
                    "payload schema for it. Agreement with nothing is not "
                    "agreement — a connector claims a digest an owner minted, "
                    "and never mints one (ADR-0024 § 10.3)"
                )
            continue
        if claimed is None:
            raise CapabilityContractDigestMismatch(
                f"{where} makes no contract-digest claim, but its owning "
                f"application {contract.owner} publishes a payload contract "
                f"(digest {published[:12]}). Every connector implementing a "
                "published capability states which contract it implements; a "
                "gate a connector may decline is not a gate"
            )
        if claimed != published:
            raise CapabilityContractDigestMismatch(
                f"{where} claims contract digest {claimed[:12]}, but the "
                f"installed contract published by {contract.owner} is "
                f"{published[:12]}. This connector was built against a "
                "different payload contract for the same capability id — which "
                "is the divergence one id, one contract, one payload exists to "
                "refuse (ADR-0024 § 8.1). Rebuild the connector against the "
                "installed contract, or install the contract it was built for"
            )


def require_declared_for_binding(
    registry: CapabilityRegistry,
    *,
    capability_id: str,
    connector_key: str | None = None,
    manifest: ConnectorManifest | None = None,
) -> CapabilityContract:
    """Refusal 2 (binding side): a binding may only name a DECLARED capability.

    `ConnectorManifest.require_declares` already refuses a binding naming a
    capability the *connector* never implements. This is the other half, and the
    two are not redundant: a connector can happily implement an id no business
    owner ever published, and binding it would create a live integration whose
    payloads have no defined meaning anywhere in the fleet.

    **And, when the binding's manifest is supplied, the digest agreement too.**
    ADR-0024 § 10.4.2 requires it at composition AND here, and the two are not
    redundant for exactly the reason `activation.py` already re-checks all three
    of its refusals against stored state: a distribution can be installed,
    upgraded or replaced after composition ran, and a binding can be activated
    months later. `manifest` is optional because a caller may legitimately hold
    the capability registry without holding a connector registry —
    `destination_binding` resolves a PRODUCT port, not a connector — and such a
    caller gets the declaration check alone. :func:`require_governable` supplies
    it, so the binding-side agreement is exercised by the one function every
    assembly calls at boot.
    """
    try:
        contract = registry.get(capability_id)
    except UnknownCapabilityError as exc:
        where = f" (binding connector {connector_key!r})" if connector_key else ""
        raise UnknownCapabilityError(f"{exc}{where}") from exc
    if manifest is not None:
        require_contract_agreement(registry, manifest, capability_ids=(capability_id,))
    return contract


def require_implements_only_declared(
    registry: CapabilityRegistry, manifest: ConnectorManifest
) -> None:
    """Refusal 2 (connector side): a plugin implements; it does not declare.

    Every capability a manifest claims must already exist in the registry. A
    connector that could add to the vocabulary by publishing a manifest would be
    a connector deciding what a payload means, which ADR-0024 § 7 and
    `provider-capability-sources.md` § 7.2 both put outside the connector layer.
    """
    undeclared = sorted(manifest.capability_ids - registry.declared_ids)
    if undeclared:
        raise UnknownCapabilityError(
            f"connector {manifest.connector_key!r} v{manifest.version} implements "
            f"undeclared capabilities {undeclared}; declared: "
            f"{sorted(registry.declared_ids)}. A connector IMPLEMENTS a "
            "capability an owning application declared — publishing a manifest "
            "is not a way to mint one"
        )
    # The same rule applied to the PAYLOAD. Implementing a declared id while
    # disagreeing about what its payload is, is the same defect one step in:
    # the connector has minted a contract without minting an id.
    require_contract_agreement(registry, manifest)


def require_no_orphans(
    registry: CapabilityRegistry,
    manifests: Sequence[ConnectorManifest],
) -> None:
    """Refusal 3: a declaration nothing implements.

    Reported per-capability WITH its owner, because the fix is the owner's
    decision — install a connector, or retire the declaration — and an error
    that only lists ids sends the operator hunting for who published them.
    """
    implemented: set[str] = set()
    for manifest in manifests:
        implemented |= set(manifest.capability_ids)
    orphans = sorted(
        (c for c in registry.contracts if c.capability_id not in implemented),
        key=lambda c: c.capability_id,
    )
    if orphans:
        listed = ", ".join(f"{c.capability_id} (owner {c.owner})" for c in orphans)
        raise OrphanCapabilityError(
            f"declared capabilities with no installed connector: {listed}. A "
            "declaration nobody implements reads on an operations screen exactly "
            "like a working integration — the contract resolves and nothing ever "
            "arrives. Install a connector that implements it, or retire the "
            "declaration"
        )


def require_governable(
    registry: CapabilityRegistry,
    manifests: Sequence[ConnectorManifest],
    *,
    bound_capability_ids: Iterable[str] = (),
    now: date | None = None,
) -> None:
    """All the refusals, in the order an operator can act on them.

    Duplicates first — construction already raised, so reaching here proves the
    registry is unambiguous. Then the unknowns and the digest disagreements,
    because those are a typo, an unpublished contract or a connector built
    against another version, and all three are cheap to fix. Orphans last: they
    are the only failure whose fix may be "install something".

    Expired schema graces are checked LAST of all, and separately, because they
    are the only failure here that arrives without anybody changing anything —
    a window closed while the deployment sat still. An operator who is also
    holding an unknown capability and a digest mismatch should be told about
    those first; they are why the window was missed.
    """
    for manifest in manifests:
        require_implements_only_declared(registry, manifest)
    for capability_id in bound_capability_ids:
        require_declared_for_binding(
            registry,
            capability_id=capability_id,
            manifest=_implementer(manifests, capability_id),
        )
    require_no_orphans(registry, manifests)
    require_no_expired_grace(registry, now=now)


def _implementer(
    manifests: Sequence[ConnectorManifest], capability_id: str
) -> ConnectorManifest | None:
    for manifest in manifests:
        if capability_id in manifest.capability_ids:
            return manifest
    return None


def require_no_expired_grace(
    registry: CapabilityRegistry, *, now: date | None = None
) -> None:
    """Refusal 5: a declared ungated window that has closed.

    At BOOT rather than mid-flight. Every other refusal in this module fails a
    misconfigured composition where an operator is watching, and this one is
    held to the same place for the same reason — but it is also the one refusal
    a deployment can walk into without editing anything, so
    :func:`schema_grace_register` exists to make the deadline readable long
    before it bites.
    """
    expired = [
        entry for entry in schema_grace_register(registry, now=now) if entry.expired
    ]
    if expired:
        listed = ", ".join(
            f"{entry.capability_id} (owner {entry.owner}, due "
            f"{entry.retire_after.isoformat()}: {entry.reason})"
            for entry in expired
        )
        raise SchemaGraceExpired(
            f"capability contracts whose declared ungated window has closed: "
            f"{listed}. Each is a payload contract its owning application said "
            "it would publish by that date. Publish the schemas, or move the "
            "date in the owning application's declaration and say why — an "
            "expiry that does nothing is a permanent optional field with a date "
            "attached"
        )


@dataclass(frozen=True, slots=True)
class SchemaGraceEntry:
    """One ungated capability, and how long it has left."""

    capability_id: str
    owner: CapabilityOwner
    reason: str
    retire_after: date
    tracked_by: str
    days_remaining: int
    expired: bool


def schema_grace_register(
    registry: CapabilityRegistry, *, now: date | None = None
) -> tuple[SchemaGraceEntry, ...]:
    """Every capability that is NOT payload-gated, with an owner and a deadline.

    The whole point of refusing silence at construction: this function can be
    complete. A deployment can answer "which of my capabilities has no published
    payload contract, who owns each one, and when does that end?" — and the
    answer is a list rather than the absence of one.

    Sorted by deadline, so the thing that expires first reads first.
    """
    moment = now or _today()
    entries = [
        SchemaGraceEntry(
            capability_id=contract.capability_id,
            owner=contract.owner,
            reason=grace.reason,
            retire_after=grace.retire_after,
            tracked_by=grace.tracked_by,
            days_remaining=(grace.retire_after - moment).days,
            expired=grace.expired(moment),
        )
        for contract in registry.contracts
        if (grace := contract.schema_grace) is not None
    ]
    return tuple(
        sorted(entries, key=lambda entry: (entry.retire_after, entry.capability_id))
    )


def contract_from_declaration(
    declaration: CapabilityDeclaration,
    *,
    owner: CapabilityOwner,
    summary: str,
    command_schema: dict[str, object] | None = None,
    result_schema: dict[str, object] | None = None,
    observation_schema: dict[str, object] | None = None,
    deprecation: ContractDeprecation | None = None,
    schema_grace: SchemaGrace | None = None,
) -> CapabilityContract:
    """Adapter for an owner publishing its declaration as SPI-shaped data.

    Exists so an owning application can hand over the same
    :class:`~dotmac_integration.spi.CapabilityDeclaration` value its connector
    authors read, rather than restating the id in a second shape where the two
    can drift.

    The schemas are taken as arguments and NOT read off the declaration, because
    the declaration has nowhere to hold them and must not grow one: a
    `CapabilityDeclaration` is a claim to implement (ADR-0024 § 10.3). What this
    adapter shares with the connector's declaration is the ID and only the id.
    """
    return CapabilityContract(
        capability_id=declaration.capability_id,
        owner=owner,
        summary=summary,
        command_schema=command_schema,
        result_schema=result_schema,
        observation_schema=observation_schema,
        deprecation=deprecation,
        schema_grace=schema_grace,
    )
