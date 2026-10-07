"""The connector manifest is the sole source of runtime reachability.

The declarations are deliberately part of the integration SPI rather than the
Integrator assembly.  A deployment may project them into an egress policy or
an OpenBao policy, but it may not author a second list beside the connector.
"""

from __future__ import annotations

import pytest
from dotmac_integration.spi import (
    CURRENT_SPI_VERSION,
    CapabilityDeclaration,
    ConnectorManifest,
    EgressDeclaration,
    InvalidManifestError,
    SecretBindingDeclaration,
    SpiRange,
)

CAPABILITY = CapabilityDeclaration(capability_id="example.observe.v1")


def _current_manifest(**overrides: object) -> ConnectorManifest:
    values: dict[str, object] = {
        "connector_key": "example_connector",
        "version": "1.0.0",
        "spi_range": SpiRange.parse(
            f">={CURRENT_SPI_VERSION},<{CURRENT_SPI_VERSION.major + 1}.0"
        ),
        "capabilities": (CAPABILITY,),
        "secret_bindings": (),
        "egress": EgressDeclaration(),
    }
    values.update(overrides)
    return ConnectorManifest(**values)  # type: ignore[arg-type]


def test_a_current_connector_must_declare_both_runtime_boundaries() -> None:
    with pytest.raises(InvalidManifestError, match="runtime boundaries"):
        _current_manifest(secret_bindings=None, egress=None)

    with pytest.raises(InvalidManifestError, match="together"):
        _current_manifest(egress=None)


def test_empty_egress_is_an_explicit_deny_all_declaration() -> None:
    manifest = _current_manifest()

    assert manifest.secret_bindings == ()
    assert manifest.egress == EgressDeclaration(hosts=())
    assert manifest.declares_runtime_boundaries


def test_secret_binding_names_are_closed_and_unique() -> None:
    with pytest.raises(InvalidManifestError, match="lower snake_case"):
        SecretBindingDeclaration(name="Webhook Token")

    duplicate = SecretBindingDeclaration(name="webhook_token")
    with pytest.raises(InvalidManifestError, match=r"secret binding.*twice"):
        _current_manifest(secret_bindings=(duplicate, duplicate))


@pytest.mark.parametrize(
    "host",
    [
        "https://provider.example",
        "provider.example/path",
        "*.provider.example",
        "PROVIDER.EXAMPLE",
        "127.0.0.1",
        "localhost",
        "-traccar",
        "traccar-",
        "trac_car",
        "traccar..internal",
        "provider.example.",
    ],
)
def test_egress_hosts_are_exact_external_dns_names(host: str) -> None:
    with pytest.raises(InvalidManifestError, match="DNS hostname"):
        EgressDeclaration(hosts=(host,))


def test_private_single_label_service_name_is_an_exact_dns_host() -> None:
    declaration = EgressDeclaration(hosts=("traccar",))
    assert declaration.hosts == ("traccar",)


def test_egress_hosts_are_unique() -> None:
    with pytest.raises(InvalidManifestError, match=r"egress host.*twice"):
        EgressDeclaration(hosts=("api.provider.example", "api.provider.example"))


def test_runtime_declarations_are_covered_by_the_manifest_digest() -> None:
    denied = _current_manifest()
    permitted = _current_manifest(
        secret_bindings=(SecretBindingDeclaration(name="webhook_token"),),
        egress=EgressDeclaration(hosts=("api.provider.example",)),
    )

    assert denied.digest != permitted.digest


def test_a_legacy_manifest_keeps_its_persisted_digest() -> None:
    """Adding the declarations cannot invalidate every existing manifest pin."""
    legacy = ConnectorManifest(
        connector_key="meta_whatsapp",
        version="0.1.0a1",
        spi_range=SpiRange.parse(">=1.2,<2.0"),
        capabilities=(CapabilityDeclaration(capability_id="messaging.receive.v1"),),
    )

    assert not legacy.declares_runtime_boundaries
    assert (
        legacy.digest
        == "235fdb90fdc4ea0cfd6327c3c9a68c6c1df8387535620fea23d6a632b9c36978"
    )
