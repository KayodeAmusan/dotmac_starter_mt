"""The connector SPI — what a plugin declares, and what the module checks.

A connector distribution is independently released. The module therefore cannot
import it, cannot enumerate it, and must not contain a provider enum, an import
list or an ``if provider == ...`` branch (ADR-0024 § 7). What it *can* do is
state a contract and refuse anything that does not meet it.

## Three declarations, three refusals

A :class:`ConnectorManifest` declares a stable ``connector_key``, the SPI range
it was built against, and the capabilities it implements. Each maps to exactly
one refusal:

===================== ==========================================================
declaration           refused when
===================== ==========================================================
``connector_key``     two installed distributions claim the same key
``spi_range``         the running module's SPI is outside the declared range
``capabilities``      a binding names a capability the manifest never declared
===================== ==========================================================

All three are checked at **discovery**, again at **startup**, and again at
**activation**. That looks redundant and is not: a distribution can be installed
after discovery ran, and a binding can be activated long after startup, so a
check that happens only once is a check with a window.

## Why the SPI version is stored, not just compared

Sub's platform records ``connector_version`` and ``manifest_digest`` but nothing
about the SPI it was built against — so "an incompatible SPI version refuses
activation" was unenforceable there. Storing the declared range on the
installation is what lets a *later* module upgrade refuse a *previously*
activated binding, which is the case that actually bites: the plugin did not
change, the host did.

## A fourth declaration: the mode, and why it is a CLOSED union

SPI 1.0 shipped :class:`ConnectorMode` with three members and nothing consulting
it. The consequences ran from "cannot work" to "works wrongly": ``INGRESS`` and
``POLL`` had no executable protocol at all, so a webhook connector could be
declared and never run, and ``DELIVERY`` was invoked *without* checking the
declaration, so a binding pointed at an ingress-only connector reached
``handler_for`` and failed with an ``AttributeError`` from inside a lookup —
which reads as a broken plugin rather than as a misconfigured binding.

SPI 1.1 makes each mode an obligation the module verifies. The base
:class:`ConnectorPlugin` carries identity, metadata and connection validation
only; each mode adds exactly one factory in its own protocol
(:class:`DeliveryPlugin`, :class:`IngressPlugin`, :class:`PollPlugin`), and
:data:`MODE_PROTOCOLS` binds mode → protocol → factory → handler shape in one
frozen table.

ADR-0008 says a new vocabulary is a declaration registry, never an enum, and
this module obeys that for the vocabulary that is genuinely open: a capability
id is a regex-validated ``domain.noun.vN`` string with no enum anywhere, because
the module never has to *implement* one — it routes it. A mode is the opposite
kind of name. Each member obliges the **engine** to run machinery only the
engine can supply: ``DELIVERY`` a dispatch worker, ``INGRESS`` a mounted route
and a verify/normalize pipeline, ``POLL`` a scheduler and a cursor it persists.
A product cannot bring that machinery with it, so a product-declared mode would
be a label with nothing behind it — which is precisely how ``POLL`` arrived
unimplementable in 1.0. The union is therefore closed on purpose, closed three
ways, and each way is proved to bite in ``tests/unit/test_integration_spi_modes``:
an ``Enum`` with members cannot be subclassed, ``ConnectorMode("invented")``
raises, and :data:`MODE_PROTOCOLS` is a read-only mapping asserted exhaustive at
import.

## SPI 1.2 adds verification evidence without exposing secret material

``dotmac-integration`` 0.1.0a2 through a4 published SPI 1.1. SPI 1.2 adds
:class:`VerificationResult`: an ingress connector may report only whether
verification succeeded and which POSITIONS in its ordered active-secret set
matched. It cannot report a secret name, reference or value. The host can count
rotation traffic through a provider-neutral observer without importing or
branching on a connector. SPI 1.1's boolean result remains accepted and is
adapted to evidence with no positions, so honest ``>=1.0,<2.0`` connectors keep
working unchanged.

## SPI 1.3 declares the runtime boundary

A connector now declares its named secret bindings and exact external DNS
destinations in the same manifest as its executable contract. The Integrator
projects those declarations into deployment policy; it does not maintain a
provider allowlist of its own. Both declarations are explicit, so an empty
egress tuple means DENY ALL rather than "not configured". SPI 1.2 manifests
remain readable during adoption and retain their persisted digest, but a
connector whose minimum SPI is 1.3 cannot omit either declaration.

## SPI 1.4 maps capabilities to modes

Plugin-wide modes are insufficient for a connector whose receive capability is
INGRESS and whose send capability is DELIVERY. Before 1.4 conformance called
every factory for every capability, forcing a mode-specific factory to lie or
fail discovery. ``CapabilityDeclaration.modes`` is the exact mapping. ``None``
retains the legacy all-plugin-modes meaning, so existing connectors remain
compatible; an explicit mapping is covered by the manifest digest.

## SPI 1.5 adds provider-neutral provisioning operations

``PROVISION`` is a fourth executable mode with one handler exposing four typed
operations: ``plan``, ``apply``, ``observe`` and ``cancel``. The owning product
authors desired state and the exact plan; the connector may validate and carry
that plan to an external engine, but cannot rewrite it. Configuration and
materialized secrets cross only inside repr-hidden immutable request values.

This is an additive SPI contract, not a durable provisioning engine. The
Integrator's persistence, leasing, retry and reconciliation owner will bind it
in a later stateful slice after the next migration revision is allocated.

## SPI 1.6 adds provider-neutral synchronous requests

``REQUEST`` serves caller-initiated reads which return one typed observation.
The capability id selects the operation; the envelope has no URL, HTTP method,
path or headers a product could use as an arbitrary provider passthrough.
Request input is validated against the owning domain's ``command_schema`` and a
successful observation against its ``observation_schema`` by the invocation
boundary. An opaque installation id gives a process-global connector a stable
session-isolation key without exposing product, tenant or provider identity.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Final, Protocol, runtime_checkable
from uuid import UUID

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

__all__ = [
    "CURRENT_SPI_VERSION",
    "MODE_PROTOCOLS",
    "Acknowledgement",
    "CapabilityDeclaration",
    "CapabilityHandler",
    "ConnectorManifest",
    "ConnectorMode",
    "ConnectorPlugin",
    "DeliveryPlugin",
    "Diagnostic",
    "DispatchRequest",
    "EgressDeclaration",
    "InboundDisposition",
    "InboundEvent",
    "IngressHandler",
    "IngressPlugin",
    "IngressRequest",
    "InvalidAcknowledgementError",
    "InvalidManifestError",
    "ModeContract",
    "ModeContractError",
    "ModeNotDeclaredError",
    "PollHandler",
    "PollPlugin",
    "ProvisionContractError",
    "ProvisionApplyRequest",
    "ProvisionCancelRequest",
    "ProvisionObserveRequest",
    "ProvisionPlanRequest",
    "ProvisionPlanResult",
    "ProvisionPlugin",
    "ProvisionResultStatus",
    "ProvisionStep",
    "ProvisioningHandler",
    "ProvisioningResult",
    "QueryContractError",
    "QueryRequest",
    "QueryResult",
    "QueryStatus",
    "RequestHandler",
    "RequestPlugin",
    "SecretBindingDeclaration",
    "SpiIncompatibleError",
    "SpiRange",
    "SpiVersion",
    "VerificationResult",
    "accepts_manifest_digest",
    "canonical_digest",
    "require_capability_mode",
    "require_mode",
    "verify_plugin_modes",
]


#: 64 lowercase hex characters — what :func:`canonical_digest` produces, and
#: therefore the only shape a CLAIM to a domain contract's digest may take.
_CONTRACT_DIGEST_RE: Final[re.Pattern[str]] = re.compile(r"^[0-9a-f]{64}$")


def canonical_digest(value: object) -> str:
    """The ONE canonical-JSON digest rule in this module. SHA-256, sorted keys.

    There was already exactly one such rule — `execution.payload_digest`, which
    digests an outbound payload so a redelivery with reordered keys is still
    recognised as the same effect. ADR-0024 § 10.2 needs the same rule for a
    capability contract's schemas, and a second implementation would be a second
    answer to "are these two structures the same?": the two would agree on every
    case anybody tested and disagree on the first one nobody did.

    So the implementation moved HERE, to the contract layer, and
    `execution.payload_digest` delegates to it. That direction rather than the
    reverse because `capability_registry` must be able to digest a schema
    without importing the persistence layer — `execution` imports the ORM
    models, and a contract value object that dragged a `Session`-shaped
    dependency behind it would be unusable in the one place it matters most, an
    owning application declaring its vocabulary at startup.

    `sort_keys` so structurally equal values digest equally regardless of key
    order. `default=str` so a value the JSON encoder refuses degrades to its
    text form rather than raising — a digest is an identity, and a caller that
    handed over something unserialisable is owed a stable answer rather than a
    traceback from inside a hash function.
    """
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


class SpiIncompatibleError(ValueError):
    """A connector's declared SPI range excludes the running module."""


class InvalidManifestError(ValueError):
    """A connector manifest is malformed — refused before it is ever trusted."""


class InvalidAcknowledgementError(ValueError):
    """A connector built an acknowledgement the engine will not emit.

    Raised by the CONSTRUCTOR, so a malformed acknowledgement cannot exist long
    enough to reach a response writer.
    """


class ModeContractError(ValueError):
    """A plugin's declared modes and its executable shape disagree.

    Raised at DISCOVERY — see :func:`verify_plugin_modes`. A plugin whose
    factory hands back the wrong kind of handler is broken at boot, when
    somebody is watching, rather than at the first provider request, when
    nobody is.
    """


class ModeNotDeclaredError(RuntimeError):
    """A plugin was asked to do something it does not declare.

    Raised BEFORE the plugin is called, so the operator sees "this connector
    does not deliver" rather than an ``AttributeError`` from inside a handler
    lookup.
    """


class ProvisionContractError(ValueError):
    """A provisioning request or result violates the provider-neutral SPI."""


class QueryContractError(ValueError):
    """A synchronous query request or result violates the neutral SPI."""


_KEY_RE: Final[re.Pattern[str]] = re.compile(r"^[a-z][a-z0-9_]{1,118}$")
_DIAGNOSTIC_CODE_RE: Final[re.Pattern[str]] = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
#: `domain.noun.vN` — e.g. `ticket.observation.v1`. A capability id is a
#: CONTRACT name, so the version is part of the identity rather than a
#: separate column: `ticket.observation.v1` and `.v2` are different contracts a
#: connector may implement independently.
_CAPABILITY_RE: Final[re.Pattern[str]] = re.compile(
    r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+\.v[1-9][0-9]*$"
)
_SECRET_BINDING_RE: Final[re.Pattern[str]] = re.compile(r"^[a-z][a-z0-9_]{0,79}$")
#: Exact, lower-case DNS hostnames only, including one-label private service
#: discovery names such as ``traccar``. No URL, path, wildcard, IP literal or
#: trailing root dot: each of those broadens what an allowlist entry means.
_EGRESS_HOST_RE: Final[re.Pattern[str]] = re.compile(
    r"(?=.{1,253}\Z)"
    r"(?:"
    r"(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+"
    r"[a-z](?:[a-z0-9-]{0,61}[a-z0-9])?"
    r"|[a-z](?:[a-z0-9-]{0,61}[a-z0-9])?"
    r")"
)
#: `type/subtype`, optionally with a charset. Anchored and character-restricted
#: because this string is written into a RESPONSE HEADER: an unvalidated one
#: carrying CRLF is header injection, and one carrying arbitrary parameters is a
#: connector shaping the response beyond the one knob it was granted.
_MEDIA_TYPE_RE: Final[re.Pattern[str]] = re.compile(
    r"[a-z0-9][a-z0-9!#$&^_.+-]{0,126}/[a-z0-9][a-z0-9!#$&^_.+-]{0,126}"
    r"(; ?charset=[a-zA-Z0-9._-]{1,64})?"
)
#: The empty mapping every envelope defaults to. A shared frozen proxy rather
#: than a `default_factory`: it can be neither mutated nor accumulated into.
_NO_MATERIAL: Final[Mapping[str, str]] = MappingProxyType({})


@dataclass(frozen=True, slots=True, order=True)
class SpiVersion:
    """A ``major.minor`` SPI version.

    Major is the break; minor is additive. There is deliberately no patch
    component — a patch that changes nothing a plugin can observe does not
    belong in a compatibility decision.
    """

    major: int
    minor: int

    def __post_init__(self) -> None:
        if self.major < 1 or self.minor < 0:
            raise InvalidManifestError(f"invalid SPI version {self}")

    @classmethod
    def parse(cls, text: str) -> SpiVersion:
        match = re.fullmatch(r"(\d+)\.(\d+)", text.strip())
        if not match:
            raise InvalidManifestError(
                f"SPI version {text!r} must be `major.minor`, e.g. '1.0'"
            )
        return cls(int(match.group(1)), int(match.group(2)))

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"{self.major}.{self.minor}"


#: The SPI this module implements. A connector declaring a range that excludes
#: it is refused — at discovery, at startup and at activation.
#
# SPI 1.1 collapsed two unpublished drafts — one adding
# the mode protocols, one replacing the ingress hooks' loose parameters with a
# single immutable envelope — and shipping them as two consecutive BREAKING SPI
# versions inside one unreleased alpha would have been a fiction: no consumer
# could ever have pinned the intermediate one. They are collapsed here.
#
# Minor rather than major, and honestly so. 1.0's executable surface was
# `handler_for` and `modes`; a 1.0 DELIVERY connector declaring `>=1.0,<2.0`
# still discovers, still conforms and still dispatches under 1.1 — proved by
# `test_integration_spi_modes.py`'s fixture connector, not asserted here. What
# 1.1 adds is machinery 1.0 had no expressible form of at all: an ingress
# protocol, a poll protocol, and the verification that a declared mode is real.
# A major bump would have excluded every honest `>=1.0,<2.0` delivery connector
# in order to protect a compatibility promise nothing ever consumed. SPI 1.2
# then added verification evidence without changing the handler protocols. SPI
# 1.3 adds deployment declarations while keeping every handler protocol intact.
CURRENT_SPI_VERSION: Final[SpiVersion] = SpiVersion(1, 6)


@dataclass(frozen=True, slots=True)
class SpiRange:
    """``>=minimum, <exclusive_maximum``, both required.

    An open-ended range is rejected rather than defaulted. "Works with any
    future SPI" is a claim no connector author can honestly make, and accepting
    it would move the failure from activation — where it is a clear refusal —
    to the first dispatch, where it is a traceback.
    """

    minimum: SpiVersion
    below: SpiVersion

    def __post_init__(self) -> None:
        if not self.minimum < self.below:
            raise InvalidManifestError(
                f"SPI range >={self.minimum},<{self.below} admits no version"
            )

    @classmethod
    def parse(cls, text: str) -> SpiRange:
        match = re.fullmatch(r"\s*>=\s*([\d.]+)\s*,\s*<\s*([\d.]+)\s*", text)
        if not match:
            raise InvalidManifestError(
                f"SPI range {text!r} must be '>=<min>,<<max>', e.g. '>=1.0,<2.0'"
            )
        return cls(SpiVersion.parse(match.group(1)), SpiVersion.parse(match.group(2)))

    def admits(self, version: SpiVersion = CURRENT_SPI_VERSION) -> bool:
        return self.minimum <= version < self.below

    def require(self, version: SpiVersion = CURRENT_SPI_VERSION) -> None:
        if not self.admits(version):
            raise SpiIncompatibleError(
                f"connector declares SPI >={self.minimum},<{self.below} but the "
                f"running module implements {version}"
            )

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f">={self.minimum},<{self.below}"


class ConnectorMode(str, Enum):
    """How a connector moves data — a CLOSED union, deliberately.

    Each member obliges the engine to supply machinery a plugin cannot bring:
    a dispatch worker, ingress route, scheduler/checkpoint loop, or durable
    provisioning/reconciliation loop.
    """

    INGRESS = "ingress"
    POLL = "poll"
    DELIVERY = "delivery"
    PROVISION = "provision"
    REQUEST = "request"


@dataclass(frozen=True, slots=True)
class CapabilityDeclaration:
    """One capability contract a connector implements.

    `config_schema` is a JSON-schema fragment describing the capability's
    configuration. It may name secret REFERENCES; it may never carry a secret
    value — see `dotmac_integration.secret_refs`.

    ## What this declaration may NOT contain: a payload schema

    ADR-0024 § 10.3. A connector declares its own CONFIGURATION and its
    executable MODES, because those are genuinely per-connector facts. It never
    declares what a command, a result or an observation LOOKS like, because that
    is what the capability MEANS, and meaning is the owning business
    application's (§ 10.1, `capability_registry.CapabilityContract`).

    The tempting alternative — every connector publishing its own payload schema
    — does not prevent drift, it makes drift machine-readable: two connectors
    serving one id would publish two individually valid schemas and the engine
    would have no ground to prefer either. So the only thing a connector may say
    about the payload is that it AGREES with the one published schema, which is
    `claims_contract_digest`: a claim, never a definition.
    """

    capability_id: str
    config_schema: dict[str, object] = field(default_factory=dict)
    #: Which executable modes serve this capability. ``None`` is the published
    #: SPI 1.0-1.3 meaning: every mode declared by the plugin. New multi-mode
    #: connectors state the mapping explicitly so conformance does not call an
    #: ingress factory for a delivery-only capability (or vice versa).
    modes: frozenset[ConnectorMode] | None = None
    #: The domain contract digest this connector claims to implement — the value
    #: of `CapabilityContract.contract_digest`, copied, never derived here.
    #: ``None`` means "the owning domain has published no schema for this id
    #: yet"; the registry refuses the two ways that can be wrong (a claim where
    #: nothing is published, and a missing claim where something is).
    claims_contract_digest: str | None = None

    def __post_init__(self) -> None:
        if not _CAPABILITY_RE.fullmatch(self.capability_id):
            raise InvalidManifestError(
                f"capability id {self.capability_id!r} must look like "
                "`domain.noun.vN`, e.g. 'ticket.observation.v1'"
            )
        try:
            Draft202012Validator.check_schema(self.config_schema)
        except SchemaError:
            raise InvalidManifestError(
                f"capability {self.capability_id!r} declares an invalid config schema"
            ) from None
        if self.modes is not None and not self.modes:
            raise InvalidManifestError(
                f"capability {self.capability_id!r} declares an empty mode set"
            )
        claim = self.claims_contract_digest
        if claim is not None and not _CONTRACT_DIGEST_RE.fullmatch(claim):
            # Shape-checked HERE so a truncated or upper-cased paste fails at
            # manifest construction with a message about the paste, rather than
            # at composition with a message about disagreement — which would
            # send an author looking for a schema difference that does not
            # exist.
            raise InvalidManifestError(
                f"capability {self.capability_id!r} claims contract digest "
                f"{claim!r}, which is not 64 lowercase hex characters. The claim "
                "is the owning domain contract's `contract_digest`, copied "
                "verbatim — a connector never computes one"
            )


@dataclass(frozen=True, slots=True)
class SecretBindingDeclaration:
    """One logical secret binding a connector needs.

    ``name`` identifies the PURPOSE, never a value or an OpenBao path. A
    deployment binds that name to a reference and proves separately that only
    the Integrator workload identity can dereference the resulting path.
    """

    name: str
    required: bool = True
    description: str = ""

    def __post_init__(self) -> None:
        if not _SECRET_BINDING_RE.fullmatch(self.name):
            raise InvalidManifestError(
                f"secret binding name {self.name!r} must be lower snake_case"
            )


@dataclass(frozen=True, slots=True)
class EgressDeclaration:
    """Exact provider hosts the connector may reach.

    The empty tuple is an explicit DENY-ALL policy. Installation-provided hosts
    are deliberately absent: a mutable configuration value is not a manifest
    declaration and would let an operator widen reachability without installing
    a reviewed connector release.
    """

    hosts: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        seen: set[str] = set()
        for host in self.hosts:
            if host == "localhost" or not _EGRESS_HOST_RE.fullmatch(host):
                raise InvalidManifestError(
                    f"egress host {host!r} must be an exact lower-case DNS hostname"
                )
            if host in seen:
                raise InvalidManifestError(f"egress host {host!r} is declared twice")
            seen.add(host)


@dataclass(frozen=True, slots=True)
class ConnectorManifest:
    """What one connector distribution publishes about itself."""

    connector_key: str
    version: str
    spi_range: SpiRange
    capabilities: tuple[CapabilityDeclaration, ...]
    # ``None`` means a pre-1.3 legacy manifest during its bounded adoption
    # window. Empty tuples/hosts mean the current contract explicitly needs no
    # secret and no provider egress; conflating those states would make deny-all
    # indistinguishable from an omitted policy.
    secret_bindings: tuple[SecretBindingDeclaration, ...] | None = None
    egress: EgressDeclaration | None = None

    def __post_init__(self) -> None:
        if not _KEY_RE.fullmatch(self.connector_key):
            raise InvalidManifestError(
                f"connector key {self.connector_key!r} must be lowercase "
                "alphanumeric with underscores"
            )
        if not self.version.strip():
            raise InvalidManifestError(
                f"connector {self.connector_key!r} declares no version"
            )
        if not self.capabilities:
            raise InvalidManifestError(
                f"connector {self.connector_key!r} declares no capabilities — a "
                "connector that implements nothing cannot be bound to anything"
            )
        if (self.secret_bindings is None) != (self.egress is None):
            raise InvalidManifestError(
                f"connector {self.connector_key!r} must declare secret bindings "
                "and egress together"
            )
        if (
            self.spi_range.minimum >= SpiVersion(1, 3)
            and not self.declares_runtime_boundaries
        ):
            raise InvalidManifestError(
                f"connector {self.connector_key!r} targets SPI >=1.3 but omits "
                "its runtime boundaries"
            )
        secret_names: set[str] = set()
        for binding in self.secret_bindings or ():
            if binding.name in secret_names:
                raise InvalidManifestError(
                    f"connector {self.connector_key!r} declares secret binding "
                    f"{binding.name!r} twice"
                )
            secret_names.add(binding.name)
        seen: set[str] = set()
        for capability in self.capabilities:
            if capability.capability_id in seen:
                raise InvalidManifestError(
                    f"connector {self.connector_key!r} declares capability "
                    f"{capability.capability_id!r} twice"
                )
            seen.add(capability.capability_id)

    @property
    def digest(self) -> str:
        """Stable identity of this manifest's CONTRACT.

        Over the fields a consumer can depend on — key, version, SPI range and
        the capability set. Deliberately not over the whole object: a docstring
        change must not invalidate every installation pinned to it.

        NOT :func:`canonical_digest`: this hashes a field LIST whose ordering and
        separators are its own published contract, not a JSON structure. The two
        answer different questions and are deliberately not one function.
        """
        fields = [
            self.connector_key,
            self.version,
            str(self.spi_range),
            ",".join(sorted(self.capability_ids)),
        ]
        if any(capability.modes is not None for capability in self.capabilities):
            fields.append(
                "capability_modes="
                + ",".join(
                    f"{capability.capability_id}:"
                    + "+".join(sorted(mode.value for mode in capability.modes or ()))
                    for capability in sorted(
                        self.capabilities, key=lambda item: item.capability_id
                    )
                )
            )
        if any(
            capability.claims_contract_digest is not None
            for capability in self.capabilities
        ):
            # Appended only when at least one capability claims, so every
            # manifest published before ADR-0024 § 10 keeps the digest its
            # installations are pinned to. WHICH contract a connector claims to
            # implement is reviewable contract, not documentation: a connector
            # that silently re-pointed at a different published schema would be
            # a different payload shape behind an unchanged installation pin,
            # which is precisely what `accepts_manifest_digest` exists to catch.
            fields.append(
                "capability_contract_claims="
                + ",".join(
                    f"{capability.capability_id}:"
                    f"{capability.claims_contract_digest or ''}"
                    for capability in sorted(
                        self.capabilities, key=lambda item: item.capability_id
                    )
                )
            )
        if self.declares_runtime_boundaries:
            # Description text is documentation, not policy. Names,
            # requiredness and destinations are the reviewable contract and
            # therefore change every installation pin when they change.
            fields.extend(
                (
                    "secrets="
                    + ",".join(
                        f"{binding.name}:{int(binding.required)}"
                        for binding in sorted(
                            self.secret_bindings or (), key=lambda item: item.name
                        )
                    ),
                    "egress="
                    + ",".join(sorted((self.egress or EgressDeclaration()).hosts)),
                )
            )
        material = "|".join(fields)
        return hashlib.sha256(material.encode("utf-8")).hexdigest()

    @property
    def declares_runtime_boundaries(self) -> bool:
        """Whether omission has been retired in favour of explicit deny-all."""

        return self.secret_bindings is not None and self.egress is not None

    @property
    def capability_ids(self) -> frozenset[str]:
        return frozenset(c.capability_id for c in self.capabilities)

    def require_declares(self, capability_id: str) -> CapabilityDeclaration:
        """The undeclared-capability refusal.

        A binding may only name a capability the manifest actually declares.
        Without this a typo binds successfully and fails at the first dispatch,
        by which time the operator has been told the integration is live.
        """
        for capability in self.capabilities:
            if capability.capability_id == capability_id:
                return capability
        raise InvalidManifestError(
            f"connector {self.connector_key!r} does not declare capability "
            f"{capability_id!r}; it declares {sorted(self.capability_ids)}"
        )


# ── The executable contract ─────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class Diagnostic:
    """One finding from validation. `ok=False` blocks enablement.

    Only ``code`` may cross a persistence or operator boundary. ``detail`` is
    connector-owned diagnostic material, hidden from the default repr and
    deliberately ignored by the lifecycle owner because it may contain values
    that were materialized solely for this connection check.
    """

    ok: bool
    code: str
    detail: str = field(default="", repr=False)

    def __post_init__(self) -> None:
        if not _DIAGNOSTIC_CODE_RE.fullmatch(self.code):
            # Do not echo a connector-controlled code in an exception: it may
            # itself contain materialized configuration. Normalising keeps the
            # existing constructor total while making the value safe wherever
            # a caller persists or renders the machine code.
            object.__setattr__(
                self,
                "code",
                "invalid_diagnostic_code",
            )


@dataclass(frozen=True, slots=True)
class DispatchRequest:
    """What a delivery handler is given. Deliberately NOT a database session.

    A handler receives resolved configuration and MATERIALIZED secrets, never a
    connection — the invoke phase runs outside the database transaction, and
    handing over a session would invite a plugin to hold one across provider
    I/O.
    """

    capability_id: str
    event_type: str
    payload: dict[str, object]
    config: dict[str, object]
    #: Materialized at the boundary, never persisted. See `dispatch.invoke`.
    secrets: dict[str, object]
    idempotency_key: str


@dataclass(frozen=True, slots=True, repr=False)
class ProvisionStep:
    """One operation in a plan authored outside the connector.

    ``endpoint_code`` selects connector code; it is not an executable command.
    The absence of a shell, argv or callable field is deliberate: a product
    supplies desired operations, never transport implementation.
    ``input`` contains only finite JSON values with string mapping keys so its
    canonical identity cannot depend on a mutable object's string rendering.
    """

    step_key: str
    endpoint_code: str
    depends_on: tuple[str, ...] = ()
    input: Mapping[str, object] = _NO_MATERIAL

    def __post_init__(self) -> None:
        _require_plan_step_fields(self)
        if not self.step_key or not self.endpoint_code:
            raise ProvisionContractError(
                "a provision step requires non-empty step_key and endpoint_code"
            )
        if len(set(self.depends_on)) != len(self.depends_on):
            raise ProvisionContractError(
                f"provision step {self.step_key!r} repeats a dependency"
            )
        if self.step_key in self.depends_on:
            raise ProvisionContractError(
                f"provision step {self.step_key!r} cannot depend on itself"
            )
        if not isinstance(self.input, Mapping):
            raise ProvisionContractError("provision step input requires a mapping")
        object.__setattr__(self, "depends_on", tuple(self.depends_on))
        object.__setattr__(self, "input", _freeze_plan_value(self.input))


def _require_plan_step_fields(step: ProvisionStep) -> None:
    if (
        type(step.step_key) is not str
        or type(step.endpoint_code) is not str
        or any(type(dependency) is not str for dependency in step.depends_on)
    ):
        raise ProvisionContractError(
            "provision step identifiers and dependencies must be strings"
        )


def _require_plan_keys(value: Mapping[object, object]) -> None:
    if any(type(key) is not str for key in value):
        raise ProvisionContractError(
            "provision step input requires string mapping keys"
        )


def _require_plan_scalar(value: object) -> object:
    if type(value) is float and not math.isfinite(value):
        raise ProvisionContractError("provision step input requires finite JSON values")
    if type(value) in (str, int, float, bool, type(None)):
        return value
    raise ProvisionContractError("provision step input requires finite JSON values")


def _freeze_plan_value(value: object) -> object:
    """Detach finite JSON plan input from its caller and freeze containers."""
    if isinstance(value, Mapping):
        _require_plan_keys(value)
        return MappingProxyType(
            {key: _freeze_plan_value(item) for key, item in value.items()}
        )
    if isinstance(value, list | tuple):
        return tuple(_freeze_plan_value(item) for item in value)
    return _require_plan_scalar(value)


def _plain_plan_value(value: object) -> object:
    """Restore JSON containers for the existing canonical digest rule."""
    if isinstance(value, Mapping):
        _require_plan_keys(value)
        return {key: _plain_plan_value(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_plain_plan_value(item) for item in value]
    return _require_plan_scalar(value)


def _provision_steps_digest(steps: Iterable[ProvisionStep]) -> str:
    steps = tuple(steps)
    for step in steps:
        if not isinstance(step, ProvisionStep):
            raise ProvisionContractError("provision plan requires ProvisionStep values")
        _require_plan_step_fields(step)
    if any(not isinstance(step.input, Mapping) for step in steps):
        raise ProvisionContractError("provision step input requires a mapping")
    return canonical_digest(
        [
            {
                "step_key": step.step_key,
                "endpoint_code": step.endpoint_code,
                "depends_on": list(step.depends_on),
                "input": _plain_plan_value(step.input),
            }
            for step in steps
        ]
    )


def _freeze_provision_material(instance: object, *names: str) -> None:
    """Copy and freeze each mapping held by a provisioning envelope."""
    for name in names:
        object.__setattr__(
            instance,
            name,
            MappingProxyType(dict(getattr(instance, name))),
        )


def _require_plan_hash(plan_hash: str) -> None:
    if not _CONTRACT_DIGEST_RE.fullmatch(plan_hash):
        raise ProvisionContractError(
            "plan_hash must be 64 lowercase hexadecimal characters"
        )


@dataclass(frozen=True, slots=True, repr=False)
class ProvisionPlanRequest:
    """Ask a connector to validate an owner-authored plan without rewriting it."""

    capability_id: str
    command_id: str
    plan_hash: str
    steps: tuple[ProvisionStep, ...]
    config: Mapping[str, object] = _NO_MATERIAL
    secrets: Mapping[str, object] = _NO_MATERIAL
    _original_plan_hash: str = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        _require_plan_hash(self.plan_hash)
        object.__setattr__(self, "steps", tuple(self.steps))
        seen: set[str] = set()
        for step in self.steps:
            if step.step_key in seen:
                raise ProvisionContractError(
                    f"provision plan repeats step_key {step.step_key!r}"
                )
            missing = set(step.depends_on) - seen
            if missing:
                raise ProvisionContractError(
                    f"provision step {step.step_key!r} depends on steps that do "
                    f"not precede it: {sorted(missing)}"
                )
            seen.add(step.step_key)
        _freeze_provision_material(self, "config", "secrets")
        object.__setattr__(
            self, "_original_plan_hash", _provision_steps_digest(self.steps)
        )


@dataclass(frozen=True, slots=True, repr=False)
class ProvisionPlanResult:
    """The connector's acceptance of the exact plan plus transport evidence."""

    plan_hash: str
    steps: tuple[ProvisionStep, ...]
    evidence: Mapping[str, object] = _NO_MATERIAL

    def __post_init__(self) -> None:
        _require_plan_hash(self.plan_hash)
        object.__setattr__(self, "steps", tuple(self.steps))
        _freeze_provision_material(self, "evidence")


@dataclass(frozen=True, slots=True, repr=False)
class ProvisionApplyRequest:
    """Apply one already-approved step; never a whole unbounded plan."""

    capability_id: str
    command_id: str
    operation_ref: str
    plan_hash: str
    step: ProvisionStep
    config: Mapping[str, object]
    secrets: Mapping[str, object]
    idempotency_key: str

    def __post_init__(self) -> None:
        _require_plan_hash(self.plan_hash)
        _freeze_provision_material(self, "config", "secrets")


@dataclass(frozen=True, slots=True, repr=False)
class ProvisionObserveRequest:
    """Observe one provider operation without deciding its business meaning."""

    capability_id: str
    command_id: str
    operation_ref: str
    plan_hash: str
    step_key: str
    provider_operation_ref: str
    target: Mapping[str, object]
    config: Mapping[str, object]
    secrets: Mapping[str, object]

    def __post_init__(self) -> None:
        _require_plan_hash(self.plan_hash)
        _freeze_provision_material(self, "target", "config", "secrets")


@dataclass(frozen=True, slots=True, repr=False)
class ProvisionCancelRequest:
    """Request cancellation; only the owning product decides to issue it."""

    capability_id: str
    command_id: str
    operation_ref: str
    plan_hash: str
    step_key: str
    provider_operation_ref: str
    target: Mapping[str, object]
    reason: str
    idempotency_key: str
    config: Mapping[str, object]
    secrets: Mapping[str, object]

    def __post_init__(self) -> None:
        _require_plan_hash(self.plan_hash)
        _freeze_provision_material(self, "target", "config", "secrets")


class ProvisionResultStatus(str, Enum):
    """Closed transport outcomes; the product still owns lifecycle state."""

    SUCCEEDED = "succeeded"
    ACCEPTED = "accepted"
    PENDING = "pending"
    RETRYABLE = "retryable"
    TERMINAL = "terminal"
    AMBIGUOUS = "ambiguous"
    CANCELLED = "cancelled"
    NOT_FOUND = "not_found"


@dataclass(frozen=True, slots=True, repr=False)
class ProvisioningResult:
    """Provider-neutral execution evidence, never a business decision."""

    status: ProvisionResultStatus
    provider_operation_ref: str | None = None
    evidence: Mapping[str, object] = _NO_MATERIAL
    error_code: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.status, ProvisionResultStatus):
            raise ProvisionContractError(
                "a provisioning result status must be a ProvisionResultStatus"
            )
        if self.error_code is not None and not _DIAGNOSTIC_CODE_RE.fullmatch(
            self.error_code
        ):
            raise ProvisionContractError(
                "a provisioning result error_code must be a stable machine code"
            )
        _freeze_provision_material(self, "evidence")


def _freeze_query_value(value: object) -> object:
    """Detach and deeply freeze finite JSON without provider interpretation."""

    if isinstance(value, Mapping):
        if any(type(key) is not str for key in value):
            raise QueryContractError("query mappings require string keys")
        return MappingProxyType(
            {key: _freeze_query_value(item) for key, item in value.items()}
        )
    if isinstance(value, list | tuple):
        return tuple(_freeze_query_value(item) for item in value)
    if type(value) is float and not math.isfinite(value):
        raise QueryContractError("query values must be finite JSON")
    if type(value) in (str, int, float, bool, type(None)):
        return value
    raise QueryContractError("query values must be finite JSON")


def _freeze_query_mapping(
    value: Mapping[str, object], *, field_name: str
) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise QueryContractError(f"query {field_name} requires a mapping")
    frozen = _freeze_query_value(value)
    if not isinstance(frozen, Mapping):  # pragma: no cover - narrowed above
        raise QueryContractError(f"query {field_name} requires a mapping")
    return frozen


def _plain_query_value(value: object) -> object:
    """Restore ordinary JSON containers for schema validation."""

    if isinstance(value, Mapping):
        return {key: _plain_query_value(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_plain_query_value(item) for item in value]
    return value


class QueryStatus(str, Enum):
    """Closed provider-neutral outcomes for one synchronous read."""

    SUCCEEDED = "succeeded"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    UNAUTHORIZED_PROVIDER_SESSION = "unauthorized_provider_session"
    NOT_FOUND = "not_found"
    INVALID_QUERY = "invalid_query"
    TIMEOUT = "timeout"
    MALFORMED_PROVIDER_RESPONSE = "malformed_provider_response"


@dataclass(frozen=True, slots=True, repr=False)
class QueryRequest:
    """One typed read with no arbitrary provider transport surface.

    ``installation_id`` is an opaque Integrator-owned connection key. A plugin
    may use it to isolate reusable provider sessions; it conveys no tenant,
    product or provider identity and is never supplied by a product caller.
    """

    installation_id: UUID
    capability_id: str
    payload: Mapping[str, object]
    config: Mapping[str, object]
    secrets: Mapping[str, object]

    def __post_init__(self) -> None:
        if not isinstance(self.installation_id, UUID):
            raise QueryContractError("query installation_id requires a UUID")
        if not _CAPABILITY_RE.fullmatch(self.capability_id):
            raise QueryContractError("query capability_id is malformed")
        for name in ("payload", "config", "secrets"):
            object.__setattr__(
                self,
                name,
                _freeze_query_mapping(getattr(self, name), field_name=name),
            )


@dataclass(frozen=True, slots=True, repr=False)
class QueryResult:
    """A normalized observation or one closed failure, never a raw response."""

    status: QueryStatus
    observation: Mapping[str, object] | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.status, QueryStatus):
            raise QueryContractError("query result status is not declared")
        if self.status is QueryStatus.SUCCEEDED:
            if self.observation is None:
                raise QueryContractError(
                    "successful query requires a normalized observation"
                )
            object.__setattr__(
                self,
                "observation",
                _freeze_query_mapping(self.observation, field_name="observation"),
            )
        elif self.observation is not None:
            raise QueryContractError(
                "a failure result cannot carry a provider or observation body"
            )


class InboundDisposition(str, Enum):
    """Whether a verified provider fact is eligible for product delivery.

    Provider errors, malformed entries and unsupported wire types remain
    durable transport evidence without becoming product-domain observations.
    ``RECORD_ONLY`` lets the generic engine close those receipts after writing
    them; no connector-specific worker or payload convention is involved.
    """

    DELIVER = "deliver"
    RECORD_ONLY = "record_only"


@dataclass(frozen=True, slots=True)
class InboundEvent:
    """One normalized provider fact, ready to be recorded.

    Exactly the triple the engine records, and nothing else — an ingress or poll
    handler classifies and shapes; it does not decide what happens next.
    """

    provider_event_id: str
    event_type: str
    payload: dict[str, object]
    disposition: InboundDisposition = InboundDisposition.DELIVER


@dataclass(frozen=True, slots=True, repr=False)
class IngressRequest:
    """ONE immutable envelope for everything that arrived, handed to all three
    ingress hooks unchanged.

    ## Nothing is normalised on the way in

    The engine's obligation is to hand over what it received: the body as the
    exact bytes off the wire, and the header and query names and values exactly
    as they arrived — not lowercased, not trimmed, not decoded, not re-encoded.
    This type preserves whatever it is given and adds nothing; an engine that
    normalises before construction has already broken the contract, and no check
    here can see that it did.

    That matters most for `raw_body`. Every provider worth verifying signs the
    bytes and not a re-serialization of them, so a body that has been through
    ``json.loads``/``json.dumps`` fails a signature check that should have
    passed — or, worse, passes one it should have failed.

    ## Why ONE object, and why the SAME one

    Handing the same object to `verify` and `normalize` is the load-bearing
    part: what was authenticated and what was interpreted are then provably the
    same bytes. Separate parameters can drift — an engine that re-read,
    re-decoded or re-assembled the body between the two calls would authenticate
    one thing and normalize another, and a signature check that guards a
    different byte string guards nothing.

    One envelope also stops the contract acquiring an overload per provider. A
    handshake identified by headers as well as query parameters, or a signature
    that travels in the query string, needs no new signature here: every hook
    already sees everything.

    ## Single-valued mappings — a stated limit of 1.1

    `headers` and `params` are ``Mapping[str, str]``. A repeated header or query
    key is therefore not expressible, and an engine handing over one has to pick
    a value. No provider handshake or signature scheme in the requirement record
    repeats a key, so the simpler shape is frozen — and the escape hatch is
    purely ADDITIVE: a later minor may add multi-valued views beside these
    without breaking a single connector, which is why freezing the scalar view
    now costs nothing later.

    ## What makes it safe to pass around

    `frozen` and `slots` together: no hook can mutate what a later hook sees,
    and none can smuggle a database session on as an ad-hoc attribute. The
    mappings are copied and then wrapped in ``MappingProxyType``, so
    immutability is real rather than promised by a type annotation — a plugin
    holding `request.headers` can neither edit the engine's view nor watch a
    caller edit it afterwards.

    `repr=False` is the disclosure rule: this object is a frame local in every
    traceback that leaves the plugin phase, and it holds the raw body, the
    signature header, and any authorization header or cookie a misconfigured
    proxy passed through. A generated `repr` would render all of it into any log
    line, error report or debugger frame that touched the frame. The values are
    still THERE — this is a rendering rule, not a removal.
    """

    raw_body: bytes = b""
    headers: Mapping[str, str] = _NO_MATERIAL
    params: Mapping[str, str] = _NO_MATERIAL

    def __post_init__(self) -> None:
        if not isinstance(self.raw_body, bytes):
            raise InvalidAcknowledgementError(
                "an ingress request body must be the RAW bytes as received; "
                f"got {type(self.raw_body).__name__}"
            )
        # Copy, then freeze. Copying stops a caller mutating the engine's view
        # after construction; the proxy stops a plugin mutating it at all.
        object.__setattr__(self, "headers", MappingProxyType(dict(self.headers)))
        object.__setattr__(self, "params", MappingProxyType(dict(self.params)))


@dataclass(frozen=True, slots=True)
class VerificationResult:
    """Provider-neutral evidence from an ingress authenticity check.

    ``accepted`` is the SPI 1.1 boolean made explicit.  The optional positions
    are indexes into the connector's ordered active-secret set; they reveal no
    secret name, reference, or value.  A host can therefore count rotation
    traffic generically without importing a connector or learning its scheme.

    Positions are strictly increasing and unique.  A rejected request cannot
    claim a match.  An accepted result may carry no positions for schemes that
    do not authenticate with an ordered secret set, and legacy boolean results
    are adapted to exactly that evidence-free form by the ingress engine.
    """

    accepted: bool
    matched_secret_positions: tuple[int, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.accepted, bool):
            raise ValueError("accepted must be a boolean")
        positions = self.matched_secret_positions
        if not isinstance(positions, tuple):
            raise ValueError("secret positions must be a tuple")
        if any(
            not isinstance(position, int) or isinstance(position, bool) or position < 0
            for position in positions
        ):
            raise ValueError("secret positions must be non-negative integers")
        if tuple(sorted(set(positions))) != positions:
            raise ValueError("secret positions must be unique and increasing")
        if not self.accepted and positions:
            raise ValueError("a rejected verification cannot report secret positions")


@dataclass(frozen=True, slots=True, repr=False)
class Acknowledgement:
    """What a connector wants written back, and NOTHING about how.

    A provider's handshake is a raw echo, another's delivery reply must be
    ``{"status":"ok"}``, and a third rejects anything but an empty 200 body.
    That is provider knowledge, which this module may not hold (ADR-0024 § 7) —
    so the BODY is the connector's, and it is `bytes` rather than `str` for the
    same reason `verify` takes bytes: a provider comparing an exact response
    body is comparing bytes, and an engine-chosen encoding would be a guess.

    ## The split this type exists to draw

    The connector owns the **body** and the **media type**. The engine owns the
    **status code**, and nothing here can express one. That is the point of the
    whole type: a connector must be able to satisfy a provider's exact handshake
    format without being able to lie about whether the engine accepted the
    request.

    * a **status code** is a retry instruction. 200 means "never send this
      again", 5xx means "send it again", 4xx means "stop and page someone". A
      connector choosing it could discard events the engine believes are safely
      persisted, and only the engine knows whether the batch committed.
    * **arbitrary headers** are a response-splitting surface and a place for
      request material to be echoed back out of the module's sight. Neither is
      needed by any handshake in the requirement record, so the capability is
      withheld rather than granted and policed.

    `media_type` is validated against a strict ``type/subtype`` shape precisely
    because it IS a header value: an unvalidated one carrying CRLF is header
    injection with extra steps.

    `repr=False`, like :class:`IngressRequest`: a connector is free to echo a
    slice of the request into its acknowledgement — that is what an echo
    handshake IS — so this object must be assumed to hold request material.
    """

    body: bytes = b""
    #: `None` means "the engine picks", and the engine's default depends on the
    #: operation: a handshake is `text/plain` because providers compare the raw
    #: echoed body, a delivery acknowledgement is `application/json`.
    media_type: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.body, bytes):
            raise InvalidAcknowledgementError(
                "an acknowledgement body must be bytes — the engine writes it "
                "back verbatim and will not guess an encoding; got "
                f"{type(self.body).__name__}"
            )
        if self.media_type is None:
            return
        if not _MEDIA_TYPE_RE.fullmatch(self.media_type):
            raise InvalidAcknowledgementError(
                f"media type {self.media_type!r} is not a bare `type/subtype` "
                "with an optional charset — a response header value is not a "
                "free-text field"
            )

    def resolved(self, default_media_type: str) -> Acknowledgement:
        """This acknowledgement with the engine's default filled in.

        The engine calls it once, on the way out, so an assembly never has to
        decide what an unset media type means.
        """
        if self.media_type is not None:
            return self
        return Acknowledgement(body=self.body, media_type=default_media_type)


@runtime_checkable
class CapabilityHandler(Protocol):
    """MODE: DELIVERY — what a plugin returns for one capability.

    Returns an `Outcome`-shaped result. It classifies; it does not decide what
    happens next — retry, dead-letter and reconciliation belong to the engine,
    which is why a handler cannot reschedule itself.
    """

    def __call__(self, request: DispatchRequest) -> object: ...


@runtime_checkable
class IngressHandler(Protocol):
    """MODE: INGRESS — what a plugin returns for one capability.

    Three separable jobs, kept separate because they have different inputs and
    different failure meanings. All three receive the same immutable
    :class:`IngressRequest`:

    * `challenge` answers the provider's subscription handshake. It is an
      EXPLICIT operation the engine reaches through its own handshake entry
      point, never inferred from the shape of a request: a bodyless POST is
      still a DELIVERY (a provider that signs an empty body and expects it
      recorded must not get a handshake attempt), and a provider that confirms a
      subscription with a BODIED request must still be able to handshake.
      Returning `None` is a REFUSAL — the engine answers 400 and `verify` is
      never reached.
    * `verify` decides authenticity from `request.raw_body`, which is the body
      exactly as received.
    * `normalize` shapes a verified request into events AND the acknowledgement
      the provider should receive. It is never called on an unverified body.

    ## Why `normalize` builds the acknowledgement

    Because it is the last connector code that runs. The engine records the
    batch after `normalize` returns and emits the acknowledgement only once that
    batch has committed — so the acknowledgement must already exist before
    persistence begins. Calling back into the plugin after the commit would put
    plugin exceptions on the far side of a durable write, where a raise would
    answer 5xx for a batch that is safely stored and the provider would
    redeliver it forever.

    `config` reaches `normalize` because a connector's shape can be
    configuration — a provider variant selects which payload shape to read.
    `secrets` deliberately does NOT: normalization that needs a secret is doing
    verification in the wrong place.
    """

    def challenge(
        self,
        request: IngressRequest,
        *,
        config: dict[str, object],
        secrets: dict[str, str],
    ) -> Acknowledgement | None: ...

    def verify(
        self,
        request: IngressRequest,
        *,
        config: dict[str, object],
        secrets: dict[str, str],
    ) -> bool | VerificationResult: ...

    def normalize(
        self, request: IngressRequest, *, config: dict[str, object]
    ) -> tuple[tuple[InboundEvent, ...], Acknowledgement | None]: ...


@runtime_checkable
class PollHandler(Protocol):
    """MODE: POLL — what a plugin returns for one capability.

    Takes the cursor the module persisted and returns the events found plus the
    cursor to persist next. The handler never writes the cursor itself — the
    module owns the checkpoint, so a handler cannot advance past events it
    failed to return.
    """

    def poll(
        self,
        cursor: str | None,
        *,
        config: dict[str, object],
        secrets: dict[str, str],
    ) -> tuple[tuple[InboundEvent, ...], str | None]: ...


@runtime_checkable
class ProvisioningHandler(Protocol):
    """MODE: PROVISION — plan/apply/observe/cancel at the transport seam."""

    def plan(self, request: ProvisionPlanRequest) -> ProvisionPlanResult: ...

    def apply(self, request: ProvisionApplyRequest) -> ProvisioningResult: ...

    def observe(self, request: ProvisionObserveRequest) -> ProvisioningResult: ...

    def cancel(self, request: ProvisionCancelRequest) -> ProvisioningResult: ...


@runtime_checkable
class RequestHandler(Protocol):
    """MODE: REQUEST — one synchronous typed observation."""

    def query(self, request: QueryRequest) -> QueryResult: ...


@runtime_checkable
class ConnectorPlugin(Protocol):
    """The BASE contract: identity, metadata, and connection validation.

    A plugin object rather than a bare manifest, because the module has to DO
    something with a connector: start the right workers, validate a connection
    before enabling it, and call a handler. Metadata alone cannot run anything.

    `historical_manifests` is the adoption window, and it lives INSIDE the one
    distribution on purpose. Shipping an old manifest as a second distribution
    would claim the same `connector_key` twice, which discovery refuses — so
    the pins a still-installed older revision was adopted against travel with
    the connector that supersedes them.

    ## Why `handler_for` is NOT here

    In SPI 1.0 it was, and `modes` was decorative as a result. `handler_for`
    moves DELIVERY data; an ingress-only connector has no meaningful
    implementation of it, and a base protocol demanding one forces every
    connector to either lie or raise. Worse, dispatch called it without asking
    whether the plugin declared `DELIVERY` at all.

    Each mode now has its own executable protocol, and :func:`verify_plugin_modes`
    asserts the implication in BOTH directions at discovery. A declaration that
    nothing verifies is how `modes` became decorative in the first place.
    """

    @property
    def manifest(self) -> ConnectorManifest: ...

    @property
    def historical_manifests(self) -> tuple[ConnectorManifest, ...]: ...

    @property
    def modes(self) -> frozenset[ConnectorMode]: ...

    def validate_connection(
        self, *, config: dict[str, object], secrets: dict[str, object]
    ) -> tuple[Diagnostic, ...]: ...


@runtime_checkable
class DeliveryPlugin(ConnectorPlugin, Protocol):
    """MODE: DELIVERY. Sends to the provider."""

    def handler_for(self, capability_id: str) -> CapabilityHandler: ...


@runtime_checkable
class IngressPlugin(ConnectorPlugin, Protocol):
    """MODE: INGRESS. Receives provider-initiated traffic."""

    def ingress_handler_for(self, capability_id: str) -> IngressHandler: ...


@runtime_checkable
class PollPlugin(ConnectorPlugin, Protocol):
    """MODE: POLL. Asks the provider on a schedule."""

    def poll_handler_for(self, capability_id: str) -> PollHandler: ...


@runtime_checkable
class ProvisionPlugin(ConnectorPlugin, Protocol):
    """MODE: PROVISION. Executes an approved plan through typed operations."""

    def provisioning_handler_for(self, capability_id: str) -> ProvisioningHandler: ...


@runtime_checkable
class RequestPlugin(ConnectorPlugin, Protocol):
    """MODE: REQUEST. Serves caller-initiated provider-neutral reads."""

    def request_handler_for(self, capability_id: str) -> RequestHandler: ...


@dataclass(frozen=True, slots=True)
class ModeContract:
    """What a declared mode obliges a plugin to provide.

    Three facts, in one place, so `conformance` and `discovery` have somewhere
    to look rather than a branch per mode — a branch is how a new mode gets
    added with no checks behind it, which is exactly how `POLL` arrived
    unimplementable.
    """

    #: The PLUGIN protocol a connector must satisfy to declare this mode.
    plugin_protocol: type
    #: The factory that protocol adds, by name.
    factory: str
    #: The protocol the factory's RETURN VALUE must satisfy. Separate from
    #: `plugin_protocol` because "the method exists" and "the method hands back
    #: the right kind of thing" are different claims, and only the first was ever
    #: checked: a factory returning a delivery handler where an ingress handler
    #: was promised used to pass discovery and fail on a provider's request.
    handler_protocol: type


#: One entry per mode, so a new mode cannot be added without deciding what makes
#: it runnable. A read-only proxy rather than a `dict`: a product that could
#: assign into this table could invent a mode the engine has no machinery for,
#: which is the failure this whole table exists to prevent.
MODE_PROTOCOLS: Final[Mapping[ConnectorMode, ModeContract]] = MappingProxyType(
    {
        ConnectorMode.DELIVERY: ModeContract(
            plugin_protocol=DeliveryPlugin,
            factory="handler_for",
            handler_protocol=CapabilityHandler,
        ),
        ConnectorMode.INGRESS: ModeContract(
            plugin_protocol=IngressPlugin,
            factory="ingress_handler_for",
            handler_protocol=IngressHandler,
        ),
        ConnectorMode.POLL: ModeContract(
            plugin_protocol=PollPlugin,
            factory="poll_handler_for",
            handler_protocol=PollHandler,
        ),
        ConnectorMode.PROVISION: ModeContract(
            plugin_protocol=ProvisionPlugin,
            factory="provisioning_handler_for",
            handler_protocol=ProvisioningHandler,
        ),
        ConnectorMode.REQUEST: ModeContract(
            plugin_protocol=RequestPlugin,
            factory="request_handler_for",
            handler_protocol=RequestHandler,
        ),
    }
)


def _modes_without_contracts(
    modes: Iterable[object], contracted: Iterable[object]
) -> frozenset[object]:
    """Which of `modes` has no entry in `contracted`.

    A named function rather than an inline set difference so the import-time
    guard below and its sensitivity proof run the SAME expression. A guard whose
    test re-implements the predicate proves only that two authors agreed.

    Both parameters are `Iterable[object]` rather than the enum: the proof has
    to hand it a mode set that has GROWN a member, which by definition is not a
    `ConnectorMode` — and a signature that could not express the broken case
    could not be tested against it.
    """
    return frozenset(modes) - frozenset(contracted)


# Exhaustive, checked where it cannot be skipped. A test can be deleted; an
# import-time refusal means a mode added without a contract cannot even be
# imported, let alone declared by a connector.
_UNCONTRACTED: Final[frozenset[object]] = _modes_without_contracts(
    ConnectorMode, MODE_PROTOCOLS
)
if _UNCONTRACTED:  # pragma: no cover - an import-time guard, proved by test
    raise ModeContractError(
        f"ConnectorMode has {sorted(str(m) for m in _UNCONTRACTED)} with no "
        "entry in MODE_PROTOCOLS. A mode with no protocol, factory and handler "
        "shape is a label the engine cannot run — which is how POLL shipped "
        "unimplementable in SPI 1.0"
    )


def require_mode(plugin: ConnectorPlugin, mode: ConnectorMode) -> None:
    """Refuse a plugin that does not declare AND implement `mode`.

    The cheap, per-call gate: it asks the two structural questions and calls
    nothing. :func:`verify_plugin_modes` is the thorough one and runs at
    discovery; this one runs on the hot path, before a handler lookup, so a
    binding pointed at a connector that cannot deliver produces "this connector
    does not deliver" rather than an ``AttributeError`` from inside a lookup.
    """
    contract = MODE_PROTOCOLS[mode]
    key = plugin.manifest.connector_key
    if mode not in plugin.modes:
        raise ModeNotDeclaredError(
            f"connector {key!r} does not declare mode {mode.value!r}; it "
            f"declares {sorted(m.value for m in plugin.modes)}"
        )
    if not isinstance(plugin, contract.plugin_protocol):
        raise ModeNotDeclaredError(
            f"connector {key!r} declares mode {mode.value!r} but does not "
            f"implement {contract.plugin_protocol.__name__}"
        )


def require_capability_mode(
    plugin: ConnectorPlugin, capability_id: str, mode: ConnectorMode
) -> None:
    """Refuse when this capability is not mapped to the executable mode.

    A legacy declaration with ``modes=None`` retains SPI 1.0-1.3 semantics and
    is served by every plugin mode. An explicit SPI 1.4 mapping is exact.
    """

    require_mode(plugin, mode)
    capability = plugin.manifest.require_declares(capability_id)
    if capability.modes is not None and mode not in capability.modes:
        raise ModeNotDeclaredError(
            f"connector {plugin.manifest.connector_key!r} does not map "
            f"capability {capability_id!r} to mode {mode.value!r}"
        )


def verify_plugin_modes(plugin: ConnectorPlugin) -> None:
    """The mode contract, checked at DISCOVERY. Raises :class:`ModeContractError`.

    One implementation, two callers — `discovery.discover` runs it on every
    plugin it loads, and `conformance.assert_plugin_conforms` runs it so a
    connector author gets the identical refusal from their own test suite. Two
    copies of this rule would drift, and the drift would surface as "it passed
    conformance and failed at boot".

    ## Both directions of the implication

    A plugin declaring `DELIVERY` without `handler_for` fails at the first
    dispatch. One implementing `handler_for` without declaring `DELIVERY` never
    gets its workers started, so it looks installed and sits inert. Both are
    unusable, both passed SPI 1.0, and only checking both catches both.

    ## The returned handler's SHAPE, not merely that it exists

    Calling the factory and finding it non-null proves almost nothing. A factory
    that hands back a delivery handler where an ingress handler was promised
    satisfies "not None" perfectly and then fails on a provider's request —
    inside a webhook, at 3am, having already answered the provider. So each
    declared mode's factory is called for each declared capability and the
    result is checked against the mode's `handler_protocol`.

    This calls plugin code at boot. That is intended: a factory is a lookup that
    returns a callable, it does not reach a provider, and a factory that cannot
    survive being called at boot is a factory that would not have survived a
    request either.
    """
    key = plugin.manifest.connector_key

    if not plugin.modes:
        raise ModeContractError(
            f"connector {key!r} declares no modes, so the runtime cannot know "
            "which workers to start for it"
        )

    # Report an impossible declaration before inspecting structural extras on
    # the plugin object. This is the more specific contract defect and keeps a
    # test double that implements several factories from masking it.
    for capability in plugin.manifest.capabilities:
        if capability.modes is None:
            continue
        undeclared = capability.modes - plugin.modes
        if undeclared:
            raise ModeContractError(
                f"connector {key!r} maps capability "
                f"{capability.capability_id!r} to undeclared modes "
                f"{sorted(mode.value for mode in undeclared)}"
            )

    for mode, contract in MODE_PROTOCOLS.items():
        declares = mode in plugin.modes
        implements = isinstance(plugin, contract.plugin_protocol)
        if declares and not implements:
            raise ModeContractError(
                f"connector {key!r} declares mode {mode.value!r} but does not "
                f"implement {contract.plugin_protocol.__name__} "
                f"(missing {contract.factory!r})"
            )
        if implements and not declares:
            raise ModeContractError(
                f"connector {key!r} implements {contract.factory!r} but does not "
                f"declare mode {mode.value!r}, so the runtime will never start "
                "the workers that would call it"
            )

    for mode in sorted(plugin.modes, key=lambda m: m.value):
        contract = MODE_PROTOCOLS[mode]
        factory = getattr(plugin, contract.factory)
        capabilities = tuple(
            capability
            for capability in plugin.manifest.capabilities
            if capability.modes is None or mode in capability.modes
        )
        if not capabilities:
            raise ModeContractError(
                f"connector {key!r} declares mode {mode.value!r} but maps no "
                "capability to it"
            )
        for capability in capabilities:
            try:
                handler = factory(capability.capability_id)
            except Exception as exc:
                # The ONLY place this module invokes plugin code and has to
                # decide what to do with what came back out. A connector's
                # exception message is built from whatever the connector knows,
                # which at this point may include MATERIALIZED SECRETS — the
                # factory is called during discovery, after configuration has
                # been resolved. So the type name travels and nothing else:
                # not the message, and not the exception itself.
                #
                # `from None` is the second half. Without it the original is
                # chained as `__cause__`, and every traceback, `logging`
                # call with `exc_info`, and error reporter renders it in full —
                # which would leak exactly what dropping `{exc}` was for.
                #
                # This is the same invariant `ingress.HandlerUnavailable` holds
                # one layer down for the request path; discovery had the
                # inverse. See `test_a_connector_exception_never_reaches_the_
                # mode_contract_error`.
                raise ModeContractError(
                    f"connector {key!r} declares {capability.capability_id!r} "
                    f"for mode {mode.value!r} but its {contract.factory!r} "
                    f"raised {type(exc).__name__} instead of returning a "
                    "handler. The connector's own logs carry the detail; it is "
                    "deliberately not repeated here"
                ) from None
            if not isinstance(handler, contract.handler_protocol):
                raise ModeContractError(
                    f"connector {key!r} returned a "
                    f"{type(handler).__name__} from {contract.factory!r} for "
                    f"{capability.capability_id!r}; mode {mode.value!r} requires "
                    f"a {contract.handler_protocol.__name__}. A handler of the "
                    "wrong shape fails on a provider's request, not here, which "
                    "is why the shape is checked and not merely the presence"
                )


def accepts_manifest_digest(plugin: ConnectorPlugin, digest: str) -> bool:
    """Is an installation pinned to `digest` still adoptable by this plugin?

    Current manifest first, then the historical window. An installation whose
    digest matches neither has been superseded by a connector that no longer
    claims to honour it — which must block adoption rather than proceed and
    hope the shapes still line up.
    """
    if plugin.manifest.digest == digest:
        return True
    return any(m.digest == digest for m in plugin.historical_manifests)
