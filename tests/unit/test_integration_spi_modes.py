"""SPI 1.x — the frozen contract, and proof that each refusal bites.

`ConnectorMode` shipped in SPI 1.0 with three members and nothing consulting
them. The consequences ran from "cannot work" to "works wrongly":

* `INGRESS` had no executable protocol at all, so a webhook connector could be
  declared and never run;
* `POLL` likewise — a label with no machinery behind it;
* `DELIVERY` was invoked WITHOUT checking the declaration, so a binding pointed
  at an ingress-only connector reached `handler_for` and failed with an
  `AttributeError` from inside a lookup, which reads as a broken plugin rather
  than as a misconfigured binding.

SPI 1.1 answers all three: a base protocol carrying identity and metadata, one
executable protocol per mode, an implication checked in BOTH directions at
discovery, and the SHAPE of what a factory returns checked rather than merely
its presence.

SPI 1.2 adds provider-neutral verification evidence while retaining SPI 1.1's
boolean result. It also closes the truthiness hole explicitly: a random truthy
object is not proof that a request was authenticated.

SPI 1.4 maps each capability to its executable modes. Omission preserves the
legacy all-plugin-modes meaning; an explicit map stops conformance from calling
an ingress factory for a delivery-only capability or the reverse.

SPI 1.5 adds the fourth executable mode, provider-neutral provisioning, as the
typed plan/apply/observe/cancel seam.

Every guard below is paired with a case that makes it FIRE. A test that only
shows a guard accepting a good connector proves nothing about what it refuses,
and the empty-set trap is real here: three of these checks would pass vacuously
against a plugin that declares no modes.
"""

from __future__ import annotations

import dataclasses
from enum import Enum
from typing import Any
from uuid import uuid4

import pytest
from dotmac_integration.conformance import (
    ConformanceFailure,
    assert_plugin_conforms,
    fake_manifest,
    fake_plugin,
    fake_registry,
)
from dotmac_integration.discovery import discover
from dotmac_integration.dispatch import PreparedDispatch, invoke
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
    DeliveryPlugin,
    Diagnostic,
    DispatchRequest,
    EgressDeclaration,
    InboundEvent,
    IngressHandler,
    IngressPlugin,
    IngressRequest,
    InvalidAcknowledgementError,
    ModeContractError,
    ModeNotDeclaredError,
    PollHandler,
    PollPlugin,
    ProvisioningHandler,
    ProvisionPlugin,
    SpiIncompatibleError,
    SpiRange,
    SpiVersion,
    VerificationResult,
    _modes_without_contracts,
    require_mode,
    verify_plugin_modes,
)

FAKE = "conformance.echo.v1"


# ── The shape of the split ──────────────────────────────────────────────────


def test_the_base_protocol_carries_no_data_movement() -> None:
    """`handler_for` is not on the base.

    A base demanding it forces an ingress-only connector to either lie or raise,
    and it is exactly what made `modes` decorative in SPI 1.0: if every plugin
    must supply a delivery handler, declaring `DELIVERY` says nothing.
    """
    base = {m for m in dir(ConnectorPlugin) if not m.startswith("_")}
    assert base == {"manifest", "historical_manifests", "modes", "validate_connection"}
    assert "handler_for" not in base


@pytest.mark.parametrize(
    ("mode", "plugin_protocol", "factory", "handler_protocol"),
    [
        (ConnectorMode.DELIVERY, DeliveryPlugin, "handler_for", CapabilityHandler),
        (ConnectorMode.INGRESS, IngressPlugin, "ingress_handler_for", IngressHandler),
        (ConnectorMode.POLL, PollPlugin, "poll_handler_for", PollHandler),
        (
            ConnectorMode.PROVISION,
            ProvisionPlugin,
            "provisioning_handler_for",
            ProvisioningHandler,
        ),
    ],
)
def test_each_mode_has_exactly_one_executable_protocol(
    mode: ConnectorMode,
    plugin_protocol: type,
    factory: str,
    handler_protocol: type,
) -> None:
    contract = MODE_PROTOCOLS[mode]
    assert contract.plugin_protocol is plugin_protocol
    assert contract.factory == factory
    assert contract.handler_protocol is handler_protocol
    added = {m for m in dir(plugin_protocol) if not m.startswith("_")} - {
        m for m in dir(ConnectorPlugin) if not m.startswith("_")
    }
    assert added == {factory}, (
        f"{plugin_protocol.__name__} should add exactly {factory!r} — a mode "
        "protocol that adds two methods is two modes wearing one name"
    )


def test_capabilities_can_map_to_different_modes_without_false_factory_calls() -> None:
    """SPI 1.3 called every factory for every capability.

    That made an honest receive=INGRESS/send=DELIVERY connector impossible:
    conformance required both factories to lie about supporting both contracts.
    """
    receive = "messaging.receive.v1"
    send = "messaging.send.v1"
    manifest = ConnectorManifest(
        connector_key="mode_specific",
        version="1.0.0",
        spi_range=SpiRange.parse(">=1.4,<2.0"),
        capabilities=(
            CapabilityDeclaration(
                capability_id=receive,
                modes=frozenset({ConnectorMode.INGRESS}),
            ),
            CapabilityDeclaration(
                capability_id=send,
                modes=frozenset({ConnectorMode.DELIVERY}),
            ),
        ),
        secret_bindings=(),
        egress=EgressDeclaration(),
    )

    registry = fake_registry([manifest])
    plugin = registry.plugin("mode_specific")
    verify_plugin_modes(plugin)


def test_a_capability_cannot_name_a_mode_the_plugin_does_not_declare() -> None:
    manifest = ConnectorManifest(
        connector_key="mode_mismatch",
        version="1.0.0",
        spi_range=SpiRange.parse(">=1.4,<2.0"),
        capabilities=(
            CapabilityDeclaration(
                capability_id=FAKE,
                modes=frozenset({ConnectorMode.POLL}),
            ),
        ),
        secret_bindings=(),
        egress=EgressDeclaration(),
    )
    plugin = fake_plugin(
        manifest_=manifest,
        modes_=frozenset({ConnectorMode.INGRESS, ConnectorMode.DELIVERY}),
    )
    with pytest.raises(ModeContractError, match="undeclared modes.*poll"):
        verify_plugin_modes(plugin)


# ── The mode registry is FROZEN: closed, exhaustive, uninventable ───────────


def test_every_mode_is_covered_by_the_contract_map() -> None:
    """A new mode cannot be added without deciding what makes it runnable.

    This is the omission that left `POLL` unimplementable: the enum grew and
    nothing forced a matching protocol.
    """
    assert set(MODE_PROTOCOLS) == set(ConnectorMode)
    assert _modes_without_contracts(ConnectorMode, MODE_PROTOCOLS) == frozenset()


def test_the_exhaustiveness_guard_bites() -> None:
    """The sensitivity proof for the import-time refusal in `spi`.

    The check above passes against the current pair and would also pass if the
    predicate were `frozenset() == frozenset()`. This runs the SAME function
    against a mode set that has grown a member nobody wrote a contract for, and
    requires it to name that member.
    """

    class _Grown(str, Enum):
        DELIVERY = "delivery"
        INGRESS = "ingress"
        POLL = "poll"
        PROVISION = "provision"
        TELEPATHY = "telepathy"

    missing = _modes_without_contracts(_Grown, MODE_PROTOCOLS)
    assert missing == {_Grown.TELEPATHY}


def test_the_mode_table_cannot_be_written_to() -> None:
    """A product that could assign into this table could invent a mode the
    engine has no worker, route or scheduler for — the exact failure the table
    exists to prevent."""
    with pytest.raises(TypeError):
        MODE_PROTOCOLS[ConnectorMode.DELIVERY] = MODE_PROTOCOLS[  # type: ignore[index]
            ConnectorMode.INGRESS
        ]


def test_a_product_cannot_invent_a_mode_member() -> None:
    """Closed three ways, and this is two of them.

    ADR-0008 says a new vocabulary is a declaration registry, never an enum —
    and this module obeys that for capability ids, which are a regex-validated
    open namespace with no enum anywhere. A mode is the other kind of name:
    every member obliges the ENGINE to run machinery a product cannot bring
    with it, so an invented member would be a label with nothing behind it.
    """
    with pytest.raises(ValueError, match="telepathy"):
        ConnectorMode("telepathy")

    with pytest.raises(TypeError, match="[Cc]annot extend"):

        class _Extended(ConnectorMode):  # type: ignore[misc]
            TELEPATHY = "telepathy"


# ── The implication, both directions, AT DISCOVERY ──────────────────────────


class _DeclaresPollButCannotPoll:
    """Declares POLL and implements no `poll_handler_for`.

    Written out longhand rather than produced by a kit knob: removing a method
    from a frozen dataclass is not something a knob can do honestly, and this
    is the exact shape SPI 1.0 accepted — a connector that looks installed and
    whose scheduler has nothing to call.
    """

    def __init__(self) -> None:
        self._manifest = ConnectorManifest(
            connector_key="poll_in_name_only",
            version="1.0.0",
            spi_range=SpiRange.parse(">=1.0,<2.0"),
            capabilities=(CapabilityDeclaration(capability_id=FAKE),),
        )

    @property
    def manifest(self) -> ConnectorManifest:
        return self._manifest

    @property
    def historical_manifests(self) -> tuple[ConnectorManifest, ...]:
        return ()

    @property
    def modes(self) -> frozenset[ConnectorMode]:
        return frozenset({ConnectorMode.POLL})

    def validate_connection(
        self, *, config: dict[str, object], secrets: dict[str, object]
    ) -> tuple[Diagnostic, ...]:
        return (Diagnostic(ok=True, code="reachable"),)


def test_a_declared_mode_must_be_implemented_at_discovery() -> None:
    """Direction 1, and it fails at BOOT — not at the first scheduled poll."""
    with pytest.raises(ModeContractError) as excinfo:
        fake_registry(plugins=[_DeclaresPollButCannotPoll()])
    message = str(excinfo.value)
    assert "declares mode 'poll'" in message
    assert "poll_handler_for" in message
    assert "poll_in_name_only" in message, "the refusal must name the connector"


def test_a_declared_mode_must_be_implemented_in_the_kit_too() -> None:
    """The author-facing half of the same rule, so a connector cannot pass its
    own conformance suite and then refuse to boot in the host."""
    with pytest.raises(ConformanceFailure, match="declares mode 'poll'"):
        assert_plugin_conforms(_DeclaresPollButCannotPoll())


def test_an_implemented_mode_must_be_declared() -> None:
    """Direction 2.

    Undeclared-but-implemented is not harmless: the runtime starts workers from
    `modes`, so a delivery handler nobody declared is simply never called and
    the connector looks installed and inert.
    """
    plugin = fake_plugin(modes_=frozenset({ConnectorMode.INGRESS}))
    with pytest.raises(ModeContractError) as excinfo:
        verify_plugin_modes(plugin)
    message = str(excinfo.value)
    assert "implements 'handler_for'" in message
    assert "does not declare mode 'delivery'" in message

    with pytest.raises(ConformanceFailure, match="does not declare mode 'delivery'"):
        assert_plugin_conforms(plugin)


def test_a_plugin_declaring_what_it_implements_conforms() -> None:
    """The positive case, so the two rules above cannot pass by rejecting
    everything — and it covers all four modes, so no mode's contract goes
    unrun."""
    plugin = fake_plugin()
    assert_plugin_conforms(plugin)
    assert plugin.modes == frozenset(ConnectorMode)
    assert isinstance(plugin, DeliveryPlugin)
    assert isinstance(plugin, IngressPlugin)
    assert isinstance(plugin, PollPlugin)
    assert isinstance(plugin, ProvisionPlugin)
    assert fake_registry(plugins=[plugin]).keys == {"conformance_fake"}


#: A value that must never survive the boundary. Distinctive enough that a
#: substring search cannot match it by accident.
SECRET_SENTINEL = "SENTINEL-MATERIALIZED-SECRET-9f3a71"


class _FactoryRaises:
    """A connector whose handler factory throws WITH secret material attached.

    Not contrived: `verify_plugin_modes` calls the factory during DISCOVERY,
    which happens after configuration has been resolved, so a plugin that
    interpolates a resolved credential into its own error — a very ordinary
    connector bug — hands that credential to this module.
    """

    def __init__(self) -> None:
        self.manifest_ = fake_manifest()

    @property
    def manifest(self) -> Any:
        return self.manifest_

    @property
    def historical_manifests(self) -> tuple[Any, ...]:
        return ()

    @property
    def modes(self) -> frozenset[ConnectorMode]:
        return frozenset({ConnectorMode.DELIVERY})

    def handler_for(self, capability_id: str) -> Any:
        raise KeyError(f"no route for {SECRET_SENTINEL}")

    def validate_connection(
        self, *, config: dict[str, object], secrets: dict[str, object]
    ) -> tuple[Any, ...]:
        return ()


def test_a_connector_exception_never_reaches_the_mode_contract_error(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A connector's exception is not repeated, chained, rendered or logged.

    The engine layer already holds this invariant for the REQUEST path
    (`ingress.HandlerUnavailable`, raised `from None`). Discovery held the
    inverse: it interpolated `{exc}` and chained `from exc`, so the connector's
    message reached the operator's boot log verbatim.

    Four surfaces, because suppressing only the first three is the usual
    incomplete fix — `from None` is what closes the last two, and a message
    fixed without it still leaks through any handler using `exc_info`.
    """
    import logging
    import traceback

    with pytest.raises(ModeContractError) as excinfo:
        verify_plugin_modes(_FactoryRaises())
    error = excinfo.value

    # 1. the message
    assert SECRET_SENTINEL not in str(error)
    # 2. the representation
    assert SECRET_SENTINEL not in repr(error)
    # 3. the rendered traceback, chain included
    rendered = "".join(
        traceback.format_exception(type(error), error, error.__traceback__)
    )
    assert SECRET_SENTINEL not in rendered
    # 4. a log record carrying exc_info — the surface a fixed message misses
    with caplog.at_level(logging.ERROR):
        logging.getLogger(__name__).error("discovery failed", exc_info=error)
    assert SECRET_SENTINEL not in caplog.text

    # The chain is SUPPRESSED, not merely absent: `raise ... from None` is what
    # makes every renderer above stop before the original.
    assert error.__cause__ is None
    assert error.__suppress_context__ is True

    # Still diagnosable. An operator must be able to find the connector, the
    # capability, the mode and the failing hook without the message.
    message = str(error)
    assert "conformance_fake" in message
    assert "handler_for" in message
    assert "KeyError" in message, "the exception TYPE is safe and locates the bug"


def test_the_sanitisation_guard_would_catch_a_leak() -> None:
    """Sensitivity proof: the four assertions above must be able to fail.

    A guard checking `sentinel not in ...` passes trivially if the sentinel
    never had a route to those surfaces. Here the same value IS interpolated
    and chained, the way the defect did it, and every surface is shown to
    carry it — so the checks above are known to be load-bearing.
    """
    import traceback

    source = KeyError(f"no route for {SECRET_SENTINEL}")
    try:
        try:
            raise source
        except Exception as exc:
            raise ModeContractError(f"but returns no handler: {exc}") from exc
    except ModeContractError as leaked:
        assert SECRET_SENTINEL in str(leaked)
        assert SECRET_SENTINEL in repr(leaked)
        rendered = "".join(
            traceback.format_exception(type(leaked), leaked, leaked.__traceback__)
        )
        assert SECRET_SENTINEL in rendered
        assert leaked.__cause__ is source


def test_a_connector_declaring_no_mode_is_still_refused() -> None:
    """Asserted so the two-way loop cannot swallow it: an empty `modes` makes
    BOTH directions of the implication vacuously true, and the per-mode factory
    loop below it iterates nothing."""
    with pytest.raises(ConformanceFailure, match="declares no modes"):
        assert_plugin_conforms(fake_plugin(modes_=frozenset()))
    with pytest.raises(ModeContractError, match="declares no modes"):
        fake_registry(plugins=[fake_plugin(modes_=frozenset())])


# ── The returned handler's SHAPE, not merely that it exists ─────────────────


@pytest.mark.parametrize(
    ("knob", "factory", "expected"),
    [
        ("delivery_handler_wrong_shape", "handler_for", "CapabilityHandler"),
        ("ingress_handler_wrong_shape", "ingress_handler_for", "IngressHandler"),
        ("poll_handler_wrong_shape", "poll_handler_for", "PollHandler"),
    ],
)
def test_a_factory_returning_the_wrong_handler_fails_discovery(
    knob: str, factory: str, expected: str
) -> None:
    """The sensitivity proof for the shape check.

    A `handler is not None` check waves every one of these through, and the
    failure then surfaces on a provider's request — inside a webhook, having
    already answered the provider — rather than at boot.
    """
    plugin = fake_plugin(**{knob: True})
    with pytest.raises(ModeContractError) as excinfo:
        fake_registry(plugins=[plugin])
    message = str(excinfo.value)
    assert factory in message
    assert expected in message


@pytest.mark.parametrize(
    ("knob", "factory"),
    [
        ("delivery_handler_wrong_shape", "handler_for"),
        ("ingress_handler_wrong_shape", "ingress_handler_for"),
        ("poll_handler_wrong_shape", "poll_handler_for"),
    ],
)
def test_the_wrong_handler_is_not_none(knob: str, factory: str) -> None:
    """Specificity for the test above: each wrong handler is a real object.

    Without this, the refusals above would be consistent with the check having
    caught `None` — which is the weaker check SPI 1.1 replaced, and the whole
    point is that these cases get past it.
    """
    handler = getattr(fake_plugin(**{knob: True}), factory)(FAKE)
    assert handler is not None


def test_correct_handlers_satisfy_their_protocols() -> None:
    """The positive half, so the three refusals above are not simply a factory
    check that rejects everything."""
    plugin = fake_plugin()
    assert isinstance(plugin.handler_for(FAKE), CapabilityHandler)
    assert isinstance(plugin.ingress_handler_for(FAKE), IngressHandler)
    assert isinstance(plugin.poll_handler_for(FAKE), PollHandler)


def test_the_wrong_delivery_handler_is_specifically_the_ingress_one() -> None:
    """ "Wrong callable" is the case the brief names, so it is the case driven:
    an ingress handler is a perfectly good object that is not callable at all,
    and a delivery dispatch would have called it."""
    handler = fake_plugin(delivery_handler_wrong_shape=True).handler_for(FAKE)
    assert isinstance(handler, IngressHandler)
    assert not callable(handler)


# ── The dispatch-time refusal ───────────────────────────────────────────────


def test_require_mode_refuses_an_undeclared_mode() -> None:
    plugin = fake_plugin(modes_=frozenset({ConnectorMode.INGRESS}))
    with pytest.raises(ModeNotDeclaredError) as excinfo:
        require_mode(plugin, ConnectorMode.DELIVERY)
    assert "does not declare mode 'delivery'" in str(excinfo.value)
    assert "['ingress']" in str(excinfo.value), (
        "the message must say what the connector DOES declare, or an operator "
        "learns only that something was wrong"
    )
    assert "conformance_fake" in str(excinfo.value)


def test_require_mode_accepts_a_declared_and_implemented_mode() -> None:
    for mode in ConnectorMode:
        require_mode(fake_plugin(), mode)


# ── The raw request envelope ────────────────────────────────────────────────


def test_all_three_hooks_receive_the_same_envelope_object() -> None:
    """Identity, not equality.

    What `verify` authenticated and what `normalize` interpreted must be the
    same bytes. Two equal copies would satisfy a value comparison while still
    letting an engine re-read or re-decode the body between the calls — and a
    signature check that guards a different byte string guards nothing.
    """
    plugin = fake_plugin()
    handler = plugin.ingress_handler_for(FAKE)
    request = IngressRequest(
        raw_body=b'{"a":1}', headers={"h": "v"}, params={"challenge": "c"}
    )

    handler.challenge(request, config={}, secrets={})
    handler.verify(request, config={}, secrets={})
    handler.normalize(request, config={})

    assert len(plugin.requests_seen) == 3
    assert all(seen is request for seen in plugin.requests_seen)


def test_verify_receives_the_exact_bytes_it_was_given() -> None:
    """A re-serialized body invalidates any real HMAC."""
    raw = b'{"entry":[{"changes":[]}]}  '  # trailing space is significant
    plugin = fake_plugin()
    plugin.ingress_handler_for(FAKE).verify(
        IngressRequest(
            raw_body=raw, headers={"X-Hub-Signature-256": "sha256=deadbeef"}
        ),
        config={},
        secrets={},
    )
    assert plugin.verified == [raw]


def test_nothing_is_normalised_on_the_way_in() -> None:
    """Header and query names and values arrive exactly as given.

    A lowercasing envelope would be a signature scheme's problem the day a
    provider signs the header name, and a trimming one would silently repair a
    value the provider intended to send.
    """
    request = IngressRequest(
        raw_body=b"  spaced  ",
        headers={"X-Hub-Signature-256": " sha256=AbC ", "content-type": "TEXT/plain"},
        params={"hub.Challenge": " 1234 "},
    )
    assert request.raw_body == b"  spaced  "
    assert request.headers["X-Hub-Signature-256"] == " sha256=AbC "
    assert "x-hub-signature-256" not in request.headers
    assert request.headers["content-type"] == "TEXT/plain"
    assert request.params["hub.Challenge"] == " 1234 "


def test_the_envelope_cannot_be_mutated_by_a_plugin() -> None:
    """`frozen` and `slots` together: no hook can change what a later hook
    sees, and none can smuggle a session on as an ad-hoc attribute."""
    request = IngressRequest(raw_body=b"{}", headers={"a": "b"}, params={"c": "d"})

    with pytest.raises(dataclasses.FrozenInstanceError):
        request.raw_body = b"tampered"  # type: ignore[misc]
    # An UNDECLARED name raises `TypeError` rather than `FrozenInstanceError`:
    # `slots=True` rebuilds the class, and the frozen `__setattr__` closes over
    # the pre-rebuild one, so its `super()` call fails before it reaches the
    # refusal it meant to raise. Refused either way, which is what matters here
    # — but asserted as written rather than as hoped, because a test that
    # demanded `FrozenInstanceError` would be asserting a CPython detail this
    # contract does not control.
    with pytest.raises((dataclasses.FrozenInstanceError, TypeError)):
        request.db = object()  # type: ignore[attr-defined]
    with pytest.raises(TypeError):
        request.headers["a"] = "tampered"  # type: ignore[index]
    with pytest.raises(TypeError):
        request.params["c"] = "tampered"  # type: ignore[index]


def test_the_envelope_does_not_alias_the_mapping_it_was_built_from() -> None:
    """The copy matters as much as the proxy.

    A proxy over a dict the CALLER still holds is immutable only from the
    plugin's side: the engine could edit it between `verify` and `normalize`,
    which is exactly the drift one envelope exists to make impossible.
    """
    headers = {"a": "b"}
    request = IngressRequest(raw_body=b"{}", headers=headers)
    headers["a"] = "changed"
    headers["injected"] = "yes"
    assert request.headers["a"] == "b"
    assert "injected" not in request.headers


def test_a_body_that_is_not_bytes_is_refused() -> None:
    """A `str` body has already been decoded by somebody, and the decoding is
    the thing a signature check cannot survive."""
    with pytest.raises(InvalidAcknowledgementError, match="RAW bytes"):
        IngressRequest(raw_body="{}")  # type: ignore[arg-type]


def test_the_envelope_does_not_render_its_material() -> None:
    """It is a frame local in every traceback that leaves the plugin phase, and
    it holds the raw body, the signature header and any cookie a misconfigured
    proxy passed through."""
    request = IngressRequest(
        raw_body=b"secret-payload",
        headers={"Authorization": "Bearer hunter2"},
        params={"token": "leaked"},
    )
    rendered = repr(request)
    assert "secret-payload" not in rendered
    assert "hunter2" not in rendered
    assert "leaked" not in rendered
    # Still THERE — a rendering rule, not a removal.
    assert request.headers["Authorization"] == "Bearer hunter2"


# ── The constrained acknowledgement ─────────────────────────────────────────


def test_the_connector_owns_the_body_and_the_media_type() -> None:
    ack = Acknowledgement(body=b"EXACTLY THIS", media_type="text/plain")
    assert ack.body == b"EXACTLY THIS"
    assert ack.media_type == "text/plain"


def test_the_connector_cannot_choose_the_status_code_or_headers() -> None:
    """The split this type exists to draw.

    A status code is a retry instruction — 200 means "never send this again",
    5xx means "send it again", 4xx means "stop and page someone" — and only the
    engine knows whether the batch committed. A connector able to set it could
    discard events the engine believes are safely persisted.
    """
    assert {f.name for f in dataclasses.fields(Acknowledgement)} == {
        "body",
        "media_type",
    }
    with pytest.raises(TypeError):
        Acknowledgement(body=b"", status_code=200)  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        Acknowledgement(body=b"", headers={"Set-Cookie": "a=b"})  # type: ignore[call-arg]


@pytest.mark.parametrize(
    "media_type",
    [
        "text/plain\r\nX-Injected: 1",
        "text/plain\nX-Injected: 1",
        "text/plain; charset=utf-8; boundary=--x",
        "text",
        "*/*; q=0.9",
        "",
        " text/plain",
    ],
)
def test_a_media_type_that_is_not_a_bare_type_subtype_is_refused(
    media_type: str,
) -> None:
    """It IS a response header value. An unvalidated one carrying CRLF is
    header injection with extra steps, and one carrying arbitrary parameters is
    a connector shaping the response beyond the knob it was granted."""
    with pytest.raises(InvalidAcknowledgementError, match="type/subtype"):
        Acknowledgement(body=b"x", media_type=media_type)


@pytest.mark.parametrize(
    "media_type",
    ["text/plain", "application/json", "text/plain; charset=utf-8", "text/xml"],
)
def test_an_honest_media_type_is_accepted(media_type: str) -> None:
    """Specificity: the rule above must not be "refuse everything"."""
    assert Acknowledgement(body=b"x", media_type=media_type).media_type == media_type


def test_an_acknowledgement_body_that_is_not_bytes_is_refused() -> None:
    """The engine writes it back verbatim and will not guess an encoding — a
    provider comparing an exact response body is comparing bytes."""
    with pytest.raises(InvalidAcknowledgementError, match="must be bytes"):
        Acknowledgement(body="ok")  # type: ignore[arg-type]


def test_the_engine_fills_an_unset_media_type_and_never_overrides_a_set_one() -> None:
    assert Acknowledgement(body=b"x").resolved("text/plain").media_type == "text/plain"
    chosen = Acknowledgement(body=b"x", media_type="application/json")
    assert chosen.resolved("text/plain").media_type == "application/json"
    assert chosen.resolved("text/plain") is chosen


def test_the_acknowledgement_does_not_render_its_material() -> None:
    """A connector is free to echo a slice of the request into its
    acknowledgement — that is what an echo handshake IS — so this object must be
    assumed to hold request material."""
    assert "echoed-secret" not in repr(Acknowledgement(body=b"echoed-secret"))


# ── The ingress hooks ───────────────────────────────────────────────────────


def test_normalize_returns_a_tuple_of_events_and_an_acknowledgement() -> None:
    """One provider POST can batch many events.

    A single-event signature would silently drop every event after the first,
    and the loss would be invisible: the provider gets a 200 and never resends.
    The acknowledgement is built HERE — before anything is persisted — because
    this is the last connector code that runs on the delivery path.
    """
    events = (
        InboundEvent(provider_event_id="evt.1", event_type="message", payload={}),
        InboundEvent(provider_event_id="evt.2", event_type="message", payload={}),
    )
    ack = Acknowledgement(body=b"received")
    plugin = fake_plugin(inbound=events, acknowledgement=ack)

    got_events, got_ack = plugin.ingress_handler_for(FAKE).normalize(
        IngressRequest(raw_body=b"{}"), config={}
    )

    assert isinstance(got_events, tuple)
    assert len(got_events) == 2
    assert got_ack is ack


def test_an_ingress_handler_can_reject() -> None:
    handler = fake_plugin(signature_valid=False).ingress_handler_for(FAKE)
    assert (
        handler.verify(IngressRequest(raw_body=b"{}"), config={}, secrets={}) is False
    )


def test_challenge_returns_an_acknowledgement_or_none() -> None:
    """`None` means "not mine", so the engine can state a refusal rather than
    falling through to the delivery path.

    The kit's fake reads a NEUTRAL `"challenge"` parameter. Which part of the
    request identifies a real handshake is the connector's business, and naming
    a particular provider's would breach ADR-0024 § 7 inside the module itself.
    """
    handler = fake_plugin().ingress_handler_for(FAKE)
    assert handler.challenge(IngressRequest(), config={}, secrets={}) is None
    answered = handler.challenge(
        IngressRequest(params={"challenge": "abc"}), config={}, secrets={}
    )
    assert answered == Acknowledgement(body=b"abc")
    # The media type is left unset, so the ENGINE decides it. A connector that
    # picked one here would be choosing part of the response it was not granted.
    assert answered is not None and answered.media_type is None


def test_a_poll_handler_is_given_the_cursor_and_hands_the_next_one_back() -> None:
    """The module owns the checkpoint, so a handler cannot advance past events
    it failed to return."""
    events = (InboundEvent(provider_event_id="p.1", event_type="x", payload={}),)
    plugin = fake_plugin(inbound=events, next_cursor="page-2")

    got, cursor = plugin.poll_handler_for(FAKE).poll(
        "page-1", config={"variant": "a"}, secrets={"token": "t"}
    )

    assert got == events
    assert cursor == "page-2"
    assert plugin.cursors_seen == ["page-1"]


def test_an_undeclared_capability_has_no_handler_in_any_mode() -> None:
    """A typo must fail at binding time, not at the first webhook."""
    plugin = fake_plugin()
    for mode in ConnectorMode:
        factory = getattr(plugin, MODE_PROTOCOLS[mode].factory)
        with pytest.raises(Exception):  # noqa: B017 - any refusal is correct
            factory("nope.not.declared.v1")


# ── SPI 1.0 compatibility: a real fixture connector, not a claim ────────────


class _Spi10DeliveryConnector:
    """A delivery-only connector as an SPI 1.0 author wrote one.

    `handler_for` directly on the plugin, `modes` naming DELIVERY and nothing
    else, `>=1.0,<2.0`, and no knowledge whatsoever of ingress, poll,
    `IngressRequest` or `Acknowledgement` — because none of those existed when
    it was written. It is deliberately not built from the conformance kit: a
    compatibility claim proved with the current release's own helper proves the
    helper, not the compatibility.
    """

    def __init__(self, *, spi_range: str = ">=1.0,<2.0") -> None:
        self._manifest = ConnectorManifest(
            connector_key="legacy_delivery",
            version="1.4.2",
            spi_range=SpiRange.parse(spi_range),
            capabilities=(
                CapabilityDeclaration(capability_id="ticket.observation.v1"),
            ),
        )
        self.calls: list[DispatchRequest] = []

    @property
    def manifest(self) -> ConnectorManifest:
        return self._manifest

    @property
    def historical_manifests(self) -> tuple[ConnectorManifest, ...]:
        return ()

    @property
    def modes(self) -> frozenset[ConnectorMode]:
        return frozenset({ConnectorMode.DELIVERY})

    def handler_for(self, capability_id: str) -> CapabilityHandler:
        self._manifest.require_declares(capability_id)

        def _handle(request: DispatchRequest) -> Outcome:
            self.calls.append(request)
            return Outcome(status=OutcomeStatus.SUCCEEDED)

        return _handle

    def validate_connection(
        self, *, config: dict[str, object], secrets: dict[str, object]
    ) -> tuple[Diagnostic, ...]:
        return (Diagnostic(ok=True, code="reachable"),)


def test_an_spi_1_0_delivery_connector_still_discovers() -> None:
    """The compatibility claim the whole freeze rests on.

    1.1 adds machinery 1.0 had no expressible form of; it does not move the
    ground a 1.0 delivery connector stands on. A major bump would have excluded
    every honest `>=1.0,<2.0` connector to protect a promise nothing consumed.
    """
    connector = _Spi10DeliveryConnector()
    registry = discover(points=[_point(connector)])
    assert registry.keys == {"legacy_delivery"}
    assert registry.require_compatible("legacy_delivery").version == "1.4.2"


def test_an_spi_1_0_delivery_connector_still_conforms() -> None:
    assert_plugin_conforms(_Spi10DeliveryConnector())


def test_an_spi_1_0_delivery_connector_still_delivers() -> None:
    """Loading is not working. This one is actually dispatched to.

    `invoke` takes no session by signature, so the whole delivery path is
    exercisable here without a database — which is the same property that keeps
    a plugin from holding a transaction across provider I/O.
    """
    connector = _Spi10DeliveryConnector()
    registry = discover(points=[_point(connector)])
    prepared = PreparedDispatch(
        delivery_id=uuid4(),
        installation_id=uuid4(),
        binding_id=uuid4(),
        connector_key="legacy_delivery",
        capability_id="ticket.observation.v1",
        event_type="ticket.created",
        payload={"id": "T-1"},
        config={"base_url": "https://example.invalid"},
        secret_refs={"token": "bao://kv/x#t"},
        idempotency_key="idem-1",
        config_revision_id=None,
        attempt_number=1,
    )

    outcome = invoke(
        prepared, registry=registry, resolve_secrets=lambda refs: {"token": "value"}
    )

    assert outcome.status is OutcomeStatus.SUCCEEDED
    assert [c.capability_id for c in connector.calls] == ["ticket.observation.v1"]
    assert connector.calls[0].secrets == {"token": "value"}


def test_the_1_0_connector_is_refused_for_a_mode_it_never_declared() -> None:
    """Specificity: it works BECAUSE it declares delivery, not because the mode
    check is inert."""
    connector = _Spi10DeliveryConnector()
    require_mode(connector, ConnectorMode.DELIVERY)
    for mode in (
        ConnectorMode.INGRESS,
        ConnectorMode.POLL,
        ConnectorMode.PROVISION,
    ):
        with pytest.raises(ModeNotDeclaredError, match="legacy_delivery"):
            require_mode(connector, mode)


def test_the_spi_range_check_is_live_for_the_fixture() -> None:
    """The sensitivity proof for the three tests above.

    They would all pass if `SpiRange.require` had been quietly turned off. A
    connector pinned below the running SPI must still be refused, which is what
    makes ">=1.0,<2.0 is admitted" a fact about the range rather than about
    nothing being checked.
    """
    assert SpiRange.parse(">=1.0,<2.0").admits(CURRENT_SPI_VERSION)
    assert CURRENT_SPI_VERSION == SpiVersion(1, 5)
    with pytest.raises(SpiIncompatibleError, match="running module implements"):
        discover(points=[_point(_Spi10DeliveryConnector(spi_range=">=1.0,<1.3"))])


def test_verification_result_refuses_contradictory_or_unsafe_positions() -> None:
    assert VerificationResult(
        accepted=True, matched_secret_positions=(0, 2)
    ).matched_secret_positions == (0, 2)

    for positions in ((-1,), (1, 1), (2, 1)):
        with pytest.raises(ValueError, match="secret positions"):
            VerificationResult(accepted=True, matched_secret_positions=positions)

    with pytest.raises(ValueError, match="rejected verification"):
        VerificationResult(accepted=False, matched_secret_positions=(0,))

    with pytest.raises(ValueError, match="accepted must be a boolean"):
        VerificationResult(accepted=1)  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="positions must be a tuple"):
        VerificationResult(
            accepted=True,
            matched_secret_positions=[0],  # type: ignore[arg-type]
        )


def _point(plugin: ConnectorPlugin) -> Any:
    """An `EntryPoint`-shaped stand-in, so discovery runs for real without
    installing a distribution."""

    class _Point:
        name = plugin.manifest.connector_key

        def load(self) -> ConnectorPlugin:
            return plugin

    return _Point()
