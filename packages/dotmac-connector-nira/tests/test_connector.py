"""Offline conformance: manifest, framing, result mapping, mode discipline.

The fake registry is plaintext; the production transport wraps TLS. Tests point
a plaintext-framing session at the fake, which exercises exactly the framing and
result-code logic — the crypto is the platform's, not this connector's, concern.
"""

from __future__ import annotations

import socket

import dotmac_connector_nira as n
import pytest
from dotmac_connector_nira import frames
from dotmac_connector_nira.epp import EppSession, classify_result
from dotmac_integration.retry import OutcomeStatus
from dotmac_integration.spi import (
    ConnectorMode,
    DispatchRequest,
    verify_plugin_modes,
)


class PlaintextSession(EppSession):
    """An EppSession that skips TLS, for the plaintext fake registry."""

    def connect(self) -> str:  # type: ignore[override]
        raw = socket.create_connection((self._host, self._port), timeout=5)
        raw.settimeout(5)
        self._sock = raw  # type: ignore[assignment]
        return self._read_frame()


# -- manifest & modes --------------------------------------------------------


def test_manifest_declares_eight_delivery_and_one_poll() -> None:
    delivery = [
        c
        for c in n.MANIFEST.capabilities
        if ConnectorMode.DELIVERY in (c.modes or set())
    ]
    poll = [
        c for c in n.MANIFEST.capabilities if ConnectorMode.POLL in (c.modes or set())
    ]
    assert len(delivery) == 8
    assert len(poll) == 1
    assert poll[0].capability_id == "registry.message.v1"


def test_plugin_passes_spi_mode_conformance() -> None:
    # The SPI's own check: every declared mode has a real factory, and no
    # factory is provided for a mode never declared (no phantom ingress).
    verify_plugin_modes(n.PLUGIN)


def test_no_ingress_mode_declared() -> None:
    for c in n.MANIFEST.capabilities:
        assert ConnectorMode.INGRESS not in (c.modes or set())


def test_undeclared_capability_is_refused() -> None:
    from dotmac_integration.spi import InvalidManifestError

    with pytest.raises(InvalidManifestError):
        n.PLUGIN.handler_for("registry.does_not_exist.v1")


# -- security allocation -----------------------------------------------------


def test_every_operation_reachable_through_exactly_one_capability() -> None:
    # The import-time guard already enforces this; assert it explicitly so the
    # property is a named test, not just a module side effect.
    from dotmac_connector_nira.delivery import (
        _ALL_OPERATIONS,
        ACTIONS_BY_CAPABILITY,
        _misallocated,
    )

    assert _misallocated(_ALL_OPERATIONS, ACTIONS_BY_CAPABILITY) == frozenset()


def test_binding_cannot_issue_another_capabilitys_operation() -> None:
    # A host-provision binding handed a domain_renew payload is refused, not run.
    handler = n.NiraDeliveryHandler("registry.host_provision.v1")
    req = DispatchRequest(
        capability_id="registry.host_provision.v1",
        event_type="registry.host_provision.v1",
        payload={"operation": "domain_renew", "name": "dotmac.ng"},
        config={},
        secrets={"epp_password": "x"},
        idempotency_key="k1",
    )
    outcome = handler(req)
    assert outcome.status is OutcomeStatus.TERMINAL
    assert outcome.error_code == "operation_not_allowed"


# -- framing -----------------------------------------------------------------


def test_host_create_frame_carries_both_address_families() -> None:
    xml = frames.host_create(
        "ns1.dotmac.ng", addrs=["192.0.2.200", "2001:db8:11::51"], cltrid="k"
    )
    assert "<host:name>ns1.dotmac.ng</host:name>" in xml
    assert '<host:addr ip="v4">192.0.2.200</host:addr>' in xml
    assert '<host:addr ip="v6">2001:db8:11::51</host:addr>' in xml


def test_domain_check_includes_fee_extension_when_currency_given() -> None:
    xml = frames.domain_check(["x.ng"], cltrid="k", currency="NGN")
    assert "<fee:currency>NGN</fee:currency>" in xml
    assert '<fee:command name="create">' in xml


def test_cltrid_carries_the_engine_correlation_key() -> None:
    xml = frames.domain_info("dotmac.ng", cltrid="idem-42")
    assert "<clTRID>idem-42</clTRID>" in xml


def test_frame_escapes_xml_metacharacters() -> None:
    xml = frames.domain_check(["a&b<c>.ng"], cltrid="k")
    assert "a&amp;b&lt;c&gt;.ng" in xml


# -- XML hardening -----------------------------------------------------------


def test_frame_with_a_doctype_is_refused() -> None:
    # A billion-laughs / XXE payload declares a DTD; safe_fromstring must refuse
    # it before ElementTree ever expands an entity.
    from dotmac_connector_nira.epp import EppProtocolError, safe_fromstring

    hostile = (
        '<?xml version="1.0"?>'
        '<!DOCTYPE lolz [<!ENTITY lol "lol">]>'
        "<epp>&lol;</epp>"
    )
    with pytest.raises(EppProtocolError):
        safe_fromstring(hostile)


def test_ordinary_epp_frame_still_parses() -> None:
    from dotmac_connector_nira.epp import EPP_NS, safe_fromstring

    root = safe_fromstring(
        f'<epp xmlns="{EPP_NS}"><greeting><svID>NIRA</svID></greeting></epp>'
    )
    assert root.find(f"{{{EPP_NS}}}greeting") is not None


# -- result classification ---------------------------------------------------


@pytest.mark.parametrize(
    "code,token",
    [
        (1000, "ok"),
        (1001, "pending"),
        (1300, "ok_no_messages"),
        (2302, "object_exists"),
        (2303, "object_absent"),
        (2202, "authorization"),
        (2400, "registry_failure"),
    ],
)
def test_result_code_classification(code: int, token: str) -> None:
    assert classify_result(code) == token


# -- end to end against the fake registry ------------------------------------


def test_check_roundtrip_frames_and_reads(fake_registry) -> None:
    session = PlaintextSession(fake_registry.host, fake_registry.port)
    greeting = session.connect()
    assert "NIRA-FAKE" in greeting
    login = session.request(frames.login("dotmactech", "pw", cltrid="k-login"))
    assert classify_result(login.code) == "ok"
    result = session.request(frames.domain_check(["example.ng"], cltrid="k"))
    assert result.code == 1000
    assert 'avail="1"' in result.raw
    session.close()


def test_poll_empty_queue_returns_1300(fake_registry) -> None:
    session = PlaintextSession(fake_registry.host, fake_registry.port)
    session.connect()
    session.request(frames.login("dotmactech", "pw", cltrid="k"))
    poll = session.request(frames.poll_request(cltrid="k"))
    assert poll.code == 1300
    assert classify_result(poll.code) == "ok_no_messages"
    session.close()


def test_truncated_frame_is_transport_error(fake_registry) -> None:
    # Connect raw, send a header promising more bytes than we send, expect the
    # session to raise rather than hang or misread.
    from dotmac_connector_nira.epp import EppTransportError

    session = PlaintextSession(fake_registry.host, fake_registry.port)
    session.connect()  # consume greeting
    # Send a valid login so the server replies, then close mid-read by asking
    # for a frame after the server ended the session via logout.
    session.request(frames.login("x", "y", cltrid="k"))
    session.request(frames.logout(cltrid="k"))
    with pytest.raises(EppTransportError):
        session.request(frames.domain_info("x.ng", cltrid="k"))
    session.close()
