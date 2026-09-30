"""The shared fake-plugin conformance kit.

Two jobs, and the second is the one that makes it worth shipping:

1. give this module's own tests a connector with **no provider and no network
   I/O**, so the SPI is exercisable in a unit test;
2. give every future connector author the same contract suite, so "does my
   plugin conform?" is a function call rather than an argument.

Shipped as library code rather than left in `tests/` precisely because of (2).
A conformance kit that lives in the host's test tree cannot be imported by the
distribution it is meant to certify.

## Nothing here reaches the network

The fake connector answers from a dict. That is the point: the whole
installation/configuration/binding slice must be provable without a provider,
and a kit that needed credentials would make every author's first experience of
the SPI a secrets problem.

## The kit owns no rules

Every refusal about MODES lives in `dotmac_integration.spi.verify_plugin_modes`,
which `discovery.discover` also runs. The kit calls it rather than restating it:
two copies would drift, and the drift would show up as a connector that passed
conformance and failed at boot.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Any, cast

from dotmac_integration.capability_registry import (
    CapabilityContract,
    CapabilityOwner,
    CapabilityRegistry,
    SchemaGrace,
)
from dotmac_integration.discovery import ConnectorRegistry, discover
from dotmac_integration.retry import Outcome, OutcomeStatus
from dotmac_integration.spi import (
    CURRENT_SPI_VERSION,
    MODE_PROTOCOLS,
    Acknowledgement,
    CapabilityDeclaration,
    CapabilityHandler,
    ConnectorManifest,
    ConnectorMode,
    ConnectorPlugin,
    Diagnostic,
    DispatchRequest,
    EgressDeclaration,
    InboundEvent,
    IngressHandler,
    IngressRequest,
    ModeContractError,
    PollHandler,
    ProvisionApplyRequest,
    ProvisionCancelRequest,
    ProvisioningHandler,
    ProvisioningResult,
    ProvisionObserveRequest,
    ProvisionPlanRequest,
    ProvisionPlanResult,
    ProvisionResultStatus,
    SpiRange,
    verify_plugin_modes,
)

__all__ = [
    "FAKE_CAPABILITY",
    "FAKE_GRACE_RETIRE_AFTER",
    "FAKE_OWNER",
    "ConformanceFailure",
    "FakePlugin",
    "assert_connector_conforms",
    "assert_plugin_conforms",
    "fake_capability_registry",
    "fake_contract",
    "fake_manifest",
    "fake_plugin",
    "fake_registry",
]

#: A capability id used only by the kit. Deliberately not a real contract name
#: so a fake can never be mistaken for one in a catalog dump.
FAKE_CAPABILITY: str = "conformance.echo.v1"


class ConformanceFailure(AssertionError):
    """A connector manifest does not satisfy the SPI contract."""


#: The synthetic owner of the kit's synthetic capability. Like `FAKE_CAPABILITY`
#: it names no application in the fleet, so a kit contract can never be mistaken
#: for one an owning application published.
FAKE_OWNER: CapabilityOwner = CapabilityOwner(application="conformance", module="fake")

#: The kit's grace deadline, pinned far enough out that a fixture is never
#: dated by the calendar. A test that needs an EXPIRED grace passes its own
#: date — one that expires by accident proves nothing about the guard.
FAKE_GRACE_RETIRE_AFTER: date = date(2099, 12, 31)


def fake_contract(
    *,
    capability_id: str = FAKE_CAPABILITY,
    summary: str = "a synthetic contract owned by the conformance kit",
    command_schema: dict[str, object] | None = None,
    result_schema: dict[str, object] | None = None,
    observation_schema: dict[str, object] | None = None,
    owner: CapabilityOwner = FAKE_OWNER,
) -> CapabilityContract:
    """A domain contract for the kit's capability. UNGATED unless told otherwise.

    Defaults to a `SchemaGrace`, because that is the state every capability in
    the fleet is in on the day ADR-0024 § 10 lands, and a kit whose default was
    a published schema would let a connector author's first experience of the
    gate be a failure they cannot reproduce in production.

    Pass any schema to get a GATED contract — at which point the manifest that
    implements it must claim `contract.contract_digest`, which is exactly what
    the negative fixtures exercise.
    """
    gated = any(
        schema is not None
        for schema in (command_schema, result_schema, observation_schema)
    )
    return CapabilityContract(
        capability_id=capability_id,
        owner=owner,
        summary=summary,
        command_schema=command_schema,
        result_schema=result_schema,
        observation_schema=observation_schema,
        schema_grace=(
            None
            if gated
            else SchemaGrace(
                reason=(
                    "the conformance kit's synthetic capability names no business "
                    "contract, so it has no owning domain to publish one"
                ),
                retire_after=FAKE_GRACE_RETIRE_AFTER,
                tracked_by="dotmac_integration.conformance",
            )
        ),
    )


def fake_capability_registry(
    *contracts: CapabilityContract,
) -> CapabilityRegistry:
    """The kit's declared vocabulary — the fake contract unless given others."""
    return CapabilityRegistry.from_declarations(contracts or (fake_contract(),))


def fake_manifest(
    *,
    connector_key: str = "conformance_fake",
    version: str = "1.0.0",
    spi_range: str | None = None,
    capabilities: Sequence[str] = (FAKE_CAPABILITY,),
    claims_contract_digest: str | None = None,
) -> ConnectorManifest:
    """A valid manifest, with every knob a negative test needs to break.

    `claims_contract_digest` is applied to every capability. `None` — the
    default — is a connector that claims nothing, which is correct against an
    ungated contract and is itself a refusal against a gated one; both are
    fixtures the gate needs.
    """
    default_range = f">={CURRENT_SPI_VERSION},<{CURRENT_SPI_VERSION.major + 1}.0"
    return ConnectorManifest(
        connector_key=connector_key,
        version=version,
        spi_range=SpiRange.parse(spi_range or default_range),
        capabilities=tuple(
            CapabilityDeclaration(
                capability_id=c, claims_contract_digest=claims_contract_digest
            )
            for c in capabilities
        ),
        secret_bindings=(),
        egress=EgressDeclaration(),
    )


@dataclass(frozen=True, slots=True)
class FakePlugin:
    """A connector that answers from a dict — no provider, no network.

    The whole installation/configuration/binding/dispatch slice must be provable
    without a provider, and a kit that needed credentials would make every
    author's first encounter with the SPI a secrets problem.

    It declares and implements **all four modes**, so the kit's default fake
    exercises the whole frozen mode registry. A mode with no fake behind it is a
    mode whose contract nothing ever runs — which is how `POLL` spent SPI 1.0 as
    a label. Negative cases get their own vehicle rather than a hole in the
    default: a plugin that declares a mode it does not implement is written out
    longhand in the tests, because removing a method from a frozen dataclass is
    not something a knob can do honestly.

    `outcome` is settable so a test can drive retry, reconciliation and terminal
    paths without inventing a failing provider.
    """

    manifest_: ConnectorManifest = field(default_factory=lambda: fake_manifest())
    historical: tuple[ConnectorManifest, ...] = ()
    modes_: frozenset[ConnectorMode] = frozenset(ConnectorMode)
    outcome: Outcome = field(
        default_factory=lambda: Outcome(status=OutcomeStatus.SUCCEEDED)
    )
    #: Every request the fake was asked to handle, so a test can assert what
    #: crossed the boundary — in particular that secrets arrived materialized
    #: and that no database session did.
    seen: list[DispatchRequest] = field(default_factory=list)
    healthy: bool = True
    #: Make the delivery handler raise, so the engine's "a raising plugin needs
    #: reconciliation" path is testable without inventing a broken provider. A
    #: knob rather than something a test monkeypatches on: this object is frozen
    #: precisely so a test cannot reshape the contract it is meant to check.
    raises: BaseException | None = None
    #: Make live connection validation raise without monkeypatching the frozen
    #: contract under test. The lifecycle must contain connector-owned text.
    validation_raises: Exception | None = None

    # ── ingress ─────────────────────────────────────────────────────────────
    #: What `normalize` returns. A TUPLE by default and empty by default, so a
    #: test must opt into events rather than inherit one it did not think about.
    inbound: tuple[InboundEvent, ...] = ()
    #: Drive the rejected-signature path without owning a signing secret.
    signature_valid: bool = True
    #: Every raw body `verify` was handed, so a test can assert the EXACT bytes
    #: crossed the boundary — a re-serialization would invalidate a real HMAC.
    verified: list[bytes] = field(default_factory=list)
    #: Every raw body `normalize` was handed. Kept SEPARATE from `verified` so a
    #: test can assert normalization never ran on a body whose signature was
    #: rejected — "nothing was written" would still pass if it had.
    normalized: list[bytes] = field(default_factory=list)
    #: Every params mapping `challenge` was handed, WHOLE. A test asserts the
    #: entire mapping crossed rather than a key the module selected, because
    #: selecting one would be provider knowledge in a module that may hold none.
    challenged: list[Mapping[str, str]] = field(default_factory=list)
    #: Every `IngressRequest` OBJECT each hook received, in call order. Recorded
    #: BY IDENTITY rather than by value, because the property that matters is
    #: that `verify` and `normalize` were handed the SAME envelope: two equal
    #: copies would satisfy a value comparison while still allowing an engine to
    #: authenticate one byte string and normalize another.
    requests_seen: list[IngressRequest] = field(default_factory=list)
    #: Every `config` mapping an ingress or poll call was handed, and every
    #: `secrets` one — the route a database session would actually take into a
    #: plugin is a config VALUE, which no field-type check inspects.
    configs_seen: list[dict[str, object]] = field(default_factory=list)
    secrets_seen: list[dict[str, str]] = field(default_factory=list)
    #: Make `verify` and `challenge` throw, driving the engine's connector-raised
    #: path — including the assertion that the thrown message, built from
    #: provider-controlled bytes, never escapes.
    ingress_raises: BaseException | None = None
    #: The same for `normalize`, separately: a throw AFTER a good signature is
    #: the case where a partial batch would otherwise be tempting.
    normalize_raises: BaseException | None = None
    #: Return a `list` of events instead of the `(tuple, acknowledgement)` pair.
    #: A plugin that hands back the wrong container is not a plugin whose output
    #: the engine may iterate.
    ingress_contract_broken: bool = False
    #: Return a bare tuple of events with no acknowledgement beside it. Its own
    #: knob because the failure is different in kind: the container is right and
    #: the engine would index it, making the first `InboundEvent` the body
    #: written back to the provider.
    ingress_returns_bare_events: bool = False
    #: The acknowledgement `normalize` prepares. `None` by default, so the
    #: engine's default is what a test gets unless it opts into one — and so
    #: "the connector's bytes were written back" cannot pass by accident.
    acknowledgement: Acknowledgement | None = None
    #: What `challenge` answers when the neutral handshake parameter is present.
    #: Separate from `acknowledgement` because the two operations are separate;
    #: sharing one knob would let a delivery test pass on a handshake's body.
    challenge_acknowledgement: Acknowledgement | None = None
    #: Make `challenge` hand back something that is not an `Acknowledgement`,
    #: driving the same refusal from the handshake side.
    challenge_contract_broken: bool = False

    # ── poll ────────────────────────────────────────────────────────────────
    #: The cursor `poll` hands back. The module persists it; the handler never
    #: writes it, so a handler cannot advance past events it failed to return.
    next_cursor: str | None = None
    #: Every cursor `poll` was handed, so a test can assert the checkpoint the
    #: module kept is the one the handler saw.
    cursors_seen: list[str | None] = field(default_factory=list)
    #: Make the poll call raise without monkeypatching the frozen contract.
    poll_raises: BaseException | None = None
    #: Return a list rather than the required ``(tuple[InboundEvent], cursor)``
    #: pair, proving the engine validates the whole return shape before write.
    poll_contract_broken: bool = False

    # ── provision ──────────────────────────────────────────────────────────
    #: Every typed provisioning request in call order. One list makes it easy
    #: to prove the fake exercised the entire handler without a provider.
    provision_requests_seen: list[
        ProvisionPlanRequest
        | ProvisionApplyRequest
        | ProvisionObserveRequest
        | ProvisionCancelRequest
    ] = field(default_factory=list)
    #: A provider-neutral result knob; it contains no credential material and
    #: makes pending/retry/terminal paths exercisable by later engine tests.
    provisioning_result: ProvisioningResult = field(
        default_factory=lambda: ProvisioningResult(
            status=ProvisionResultStatus.SUCCEEDED
        )
    )
    provision_plan_result: ProvisionPlanResult | None = None
    provision_raises: BaseException | None = None
    provision_contract_broken: bool = False

    # ── wrong-shape knobs: the sensitivity proofs for the handler check ──────
    #: Hand back the INGRESS handler from the DELIVERY factory. Not callable, so
    #: it is precisely "the wrong callable" the shape check exists to catch, and
    #: a `handler is not None` check would wave it through.
    delivery_handler_wrong_shape: bool = False
    #: Hand back a delivery-shaped callable from the INGRESS factory. Callable,
    #: and missing every one of `challenge`/`verify`/`normalize` — the mirror
    #: case, and the one a "not None" check misses most dangerously, because it
    #: would first fail inside a live webhook.
    ingress_handler_wrong_shape: bool = False
    #: The same for POLL.
    poll_handler_wrong_shape: bool = False
    provision_handler_wrong_shape: bool = False

    @property
    def manifest(self) -> ConnectorManifest:
        return self.manifest_

    @property
    def historical_manifests(self) -> tuple[ConnectorManifest, ...]:
        return self.historical

    @property
    def modes(self) -> frozenset[ConnectorMode]:
        return self.modes_

    def handler_for(self, capability_id: str) -> CapabilityHandler:
        self.manifest_.require_declares(capability_id)
        if self.delivery_handler_wrong_shape:
            return self._ingress_handler()  # type: ignore[return-value]

        def _handle(request: DispatchRequest) -> Outcome:
            self.seen.append(request)
            if self.raises is not None:
                raise self.raises
            return self.outcome

        return _handle

    def ingress_handler_for(self, capability_id: str) -> IngressHandler:
        """An ingress handler that needs no provider and no credentials.

        `verify` answers from the `signature_valid` knob rather than computing
        an HMAC: the kit exists to let an author drive the ENGINE's paths —
        accepted, rejected, batch rollback — without owning a signing secret. A
        real connector's verification is its own business and is tested against
        its own vectors.
        """
        self.manifest_.require_declares(capability_id)
        if self.ingress_handler_wrong_shape:
            return lambda request: None  # type: ignore[return-value]
        return self._ingress_handler()

    def poll_handler_for(self, capability_id: str) -> PollHandler:
        self.manifest_.require_declares(capability_id)
        if self.poll_handler_wrong_shape:
            return lambda request: None  # type: ignore[return-value]
        fake = self

        class _Poll:
            def poll(
                self,
                cursor: str | None,
                *,
                config: dict[str, object],
                secrets: dict[str, str],
            ) -> tuple[tuple[InboundEvent, ...], str | None]:
                fake.cursors_seen.append(cursor)
                fake.configs_seen.append(config)
                fake.secrets_seen.append(secrets)
                if fake.poll_raises is not None:
                    raise fake.poll_raises
                if fake.poll_contract_broken:
                    return list(fake.inbound)  # type: ignore[return-value]
                return fake.inbound, fake.next_cursor

        return _Poll()

    def provisioning_handler_for(self, capability_id: str) -> ProvisioningHandler:
        """A four-operation handler that performs no network or persistence I/O."""
        self.manifest_.require_declares(capability_id)
        if self.provision_handler_wrong_shape:
            return lambda request: None  # type: ignore[return-value]
        fake = self

        class _Provisioning:
            def _record(
                self,
                request: ProvisionPlanRequest
                | ProvisionApplyRequest
                | ProvisionObserveRequest
                | ProvisionCancelRequest,
            ) -> None:
                fake.provision_requests_seen.append(request)
                if fake.provision_raises is not None:
                    raise fake.provision_raises

            def plan(self, request: ProvisionPlanRequest) -> ProvisionPlanResult:
                self._record(request)
                if fake.provision_contract_broken:
                    return "not a plan result"  # type: ignore[return-value]
                if fake.provision_plan_result is not None:
                    return fake.provision_plan_result
                return ProvisionPlanResult(
                    plan_hash=request.plan_hash,
                    steps=request.steps,
                )

            def apply(self, request: ProvisionApplyRequest) -> ProvisioningResult:
                self._record(request)
                if fake.provision_contract_broken:
                    return "not a provisioning result"  # type: ignore[return-value]
                return fake.provisioning_result

            def observe(self, request: ProvisionObserveRequest) -> ProvisioningResult:
                self._record(request)
                return fake.provisioning_result

            def cancel(self, request: ProvisionCancelRequest) -> ProvisioningResult:
                self._record(request)
                return fake.provisioning_result

        return _Provisioning()

    def _ingress_handler(self) -> IngressHandler:
        fake = self

        class _Ingress:
            def challenge(
                self,
                request: IngressRequest,
                *,
                config: dict[str, object],
                secrets: dict[str, str],
            ) -> Acknowledgement | None:
                fake.requests_seen.append(request)
                fake.challenged.append(dict(request.params))
                fake.configs_seen.append(config)
                fake.secrets_seen.append(secrets)
                if fake.ingress_raises is not None:
                    raise fake.ingress_raises
                if fake.challenge_contract_broken:
                    return "not an acknowledgement"  # type: ignore[return-value]
                # A NEUTRAL key. The kit ships inside a module that may not name
                # a provider, and a real provider's handshake parameter is that
                # provider's business — the engine hands over the whole envelope
                # precisely so the connector, not this module, picks what
                # identifies a handshake.
                echo = request.params.get("challenge")
                if echo is None:
                    return None
                if fake.challenge_acknowledgement is not None:
                    return fake.challenge_acknowledgement
                return Acknowledgement(body=echo.encode("utf-8"))

            def verify(
                self,
                request: IngressRequest,
                *,
                config: dict[str, object],
                secrets: dict[str, str],
            ) -> bool:
                fake.requests_seen.append(request)
                fake.verified.append(request.raw_body)
                fake.configs_seen.append(config)
                fake.secrets_seen.append(secrets)
                if fake.ingress_raises is not None:
                    raise fake.ingress_raises
                return fake.signature_valid

            def normalize(
                self, request: IngressRequest, *, config: dict[str, object]
            ) -> tuple[tuple[InboundEvent, ...], Acknowledgement | None]:
                fake.requests_seen.append(request)
                fake.normalized.append(request.raw_body)
                fake.configs_seen.append(config)
                if fake.normalize_raises is not None:
                    raise fake.normalize_raises
                if fake.ingress_returns_bare_events:
                    return fake.inbound  # type: ignore[return-value]
                if fake.ingress_contract_broken:
                    return (list(fake.inbound), fake.acknowledgement)  # type: ignore[return-value]
                return fake.inbound, fake.acknowledgement

        return _Ingress()

    def validate_connection(
        self, *, config: dict[str, object], secrets: dict[str, object]
    ) -> tuple[Diagnostic, ...]:
        if self.validation_raises is not None:
            raise self.validation_raises
        if self.healthy:
            return (Diagnostic(ok=True, code="reachable"),)
        return (
            Diagnostic(ok=False, code="unreachable", detail="fake is set unhealthy"),
        )


def fake_plugin(**kwargs: object) -> FakePlugin:
    """A conforming plugin, with every knob a negative test needs."""
    return FakePlugin(**kwargs)  # type: ignore[arg-type]


@dataclass(frozen=True, slots=True)
class _StaticEntryPoint:
    """An `EntryPoint`-shaped stand-in that loads without importing anything.

    `discover()` takes injected points precisely so the kit does not have to
    install a distribution to test discovery.
    """

    name: str
    plugin: ConnectorPlugin = field(default_factory=fake_plugin)

    def load(self) -> ConnectorPlugin:
        return self.plugin


class _ManifestPlugin:
    """Mode-exact executable stand-in for manifest-only conformance.

    ``FakePlugin`` intentionally implements all four executable protocols. A
    manifest-only check must not therefore reuse it for an SPI 1.4 manifest
    that maps only a subset: two-way mode conformance would correctly report
    the fake's extra factories, not a defect in the manifest under test.
    """

    def __init__(
        self,
        manifest: ConnectorManifest,
        modes: frozenset[ConnectorMode],
        backing: FakePlugin,
    ) -> None:
        self._manifest = manifest
        self._modes = modes
        self._backing = backing

    @property
    def manifest(self) -> ConnectorManifest:
        return self._manifest

    @property
    def historical_manifests(self) -> tuple[ConnectorManifest, ...]:
        return ()

    @property
    def modes(self) -> frozenset[ConnectorMode]:
        return self._modes

    def validate_connection(
        self, *, config: dict[str, object], secrets: dict[str, object]
    ) -> tuple[Diagnostic, ...]:
        return self._backing.validate_connection(config=config, secrets=secrets)


def _plugin_for_manifest(manifest: ConnectorManifest) -> ConnectorPlugin:
    """Build only the factories this manifest's capabilities can execute."""

    if any(capability.modes is None for capability in manifest.capabilities):
        modes = frozenset(ConnectorMode)
    else:
        modes = frozenset(
            mode
            for capability in manifest.capabilities
            for mode in capability.modes or ()
        )
    backing = FakePlugin(manifest_=manifest, modes_=modes)

    def _factory(name: str) -> Callable[[_ManifestPlugin, str], object]:
        def factory(instance: _ManifestPlugin, capability_id: str) -> object:
            return getattr(instance._backing, name)(capability_id)

        return factory

    factories = {
        MODE_PROTOCOLS[mode].factory: _factory(MODE_PROTOCOLS[mode].factory)
        for mode in modes
    }
    plugin_type = type("_ModeExactManifestPlugin", (_ManifestPlugin,), factories)
    return cast(ConnectorPlugin, plugin_type(manifest, modes, backing))


def fake_registry(
    manifests: Iterable[ConnectorManifest] | None = None,
    *,
    plugins: Iterable[ConnectorPlugin] | None = None,
) -> ConnectorRegistry:
    """Run real discovery over fake entry points.

    Uses `discover()` rather than constructing a `ConnectorRegistry` directly,
    so the kit exercises the same duplicate-key, SPI and mode refusals production
    does. A kit that bypassed them would certify connectors against a contract
    nothing enforces.
    """
    if plugins is not None:
        chosen = list(plugins)
    elif manifests is not None:
        chosen = [_plugin_for_manifest(manifest) for manifest in manifests]
    else:
        chosen = [fake_plugin()]
    # Structurally EntryPoint-shaped, deliberately not an EntryPoint: `discover`
    # takes injected points so the kit never has to install a distribution to
    # test discovery.
    points: list[Any] = [
        _StaticEntryPoint(name=p.manifest.connector_key, plugin=p) for p in chosen
    ]
    return discover(points=points)


def assert_connector_conforms(manifest: ConnectorManifest) -> None:
    """The contract suite every connector distribution must pass.

    Call it from the distribution's own tests::

        from dotmac_integration.conformance import assert_connector_conforms
        from my_connector import MANIFEST

        def test_conforms() -> None:
            assert_connector_conforms(MANIFEST)
    """
    if not isinstance(manifest, ConnectorManifest):
        raise ConformanceFailure(
            f"expected a ConnectorManifest, got {type(manifest).__name__}"
        )

    if not manifest.spi_range.admits(CURRENT_SPI_VERSION):
        raise ConformanceFailure(
            f"connector {manifest.connector_key!r} declares SPI "
            f"{manifest.spi_range} which excludes the running module "
            f"{CURRENT_SPI_VERSION}"
        )

    if not manifest.capabilities:
        raise ConformanceFailure(
            f"connector {manifest.connector_key!r} declares no capabilities"
        )

    # Discovery must accept it ALONE — a connector that only validates
    # alongside its neighbours is not independently releasable.
    try:
        registry = fake_registry([manifest])
    except Exception as exc:
        raise ConformanceFailure(
            f"connector {manifest.connector_key!r} is not discoverable on its "
            f"own: {exc}"
        ) from exc

    resolved = registry.get(manifest.connector_key)
    for capability in manifest.capabilities:
        # `require_declares` is what activation calls; a connector whose own
        # declarations do not satisfy it could never be bound.
        resolved.require_declares(capability.capability_id)


def assert_plugin_conforms(plugin: ConnectorPlugin) -> None:
    """The EXECUTABLE half of the contract suite.

    `assert_connector_conforms` checks the metadata; this checks that the plugin
    can actually be used — a distribution that declares a capability it cannot
    hand back a handler of the right shape for passes every metadata check and
    fails on a provider's request.

    The mode rules are not restated here. They are `spi.verify_plugin_modes`,
    which `discovery.discover` runs too, so an author's suite and the host's boot
    reach the same verdict by running the same function. Only the translation to
    `ConformanceFailure` belongs to the kit: an author's test suite should see an
    assertion, not a `ValueError` from a module they did not call.
    """
    assert_connector_conforms(plugin.manifest)

    try:
        verify_plugin_modes(plugin)
    except ModeContractError as exc:
        raise ConformanceFailure(str(exc)) from exc

    key = plugin.manifest.connector_key

    # An undeclared capability must be refused, not silently handled. Per MODE,
    # since an ingress-only connector has no `handler_for` to probe. Author-time
    # only: it is a certification of the plugin's own hygiene rather than
    # something the host needs to know at boot, so it does not belong in
    # `verify_plugin_modes`.
    #
    # Written as a flag rather than `except ...: pass` so the intent is a
    # positive assertion — bandit reads try/except/pass as a swallowed error
    # (B110), and the suppression that used to sit here named ruff's equivalent
    # code instead of bandit's, aimed at the wrong tool.
    for mode in sorted(plugin.modes, key=lambda m: m.value):
        factory: Callable[[str], object] = getattr(plugin, MODE_PROTOCOLS[mode].factory)
        refused = False
        try:
            factory("conformance.undeclared.v1")
        except Exception:
            refused = True
        if not refused:
            raise ConformanceFailure(
                f"connector {key!r} returned a {mode.value} handler for a "
                "capability it never declared"
            )

    diagnostics = plugin.validate_connection(config={}, secrets={})
    if not isinstance(diagnostics, tuple):
        raise ConformanceFailure("validate_connection must return a tuple")

    # Historical manifests must keep the same key, or the adoption window would
    # smuggle a second connector in under one entry point.
    for historical in plugin.historical_manifests:
        if historical.connector_key != plugin.manifest.connector_key:
            raise ConformanceFailure(
                f"historical manifest {historical.connector_key!r} does not "
                f"match {plugin.manifest.connector_key!r} — the adoption window "
                "is for one connector's own past, not another connector"
            )
