"""Runtime policy is a projection of installed connector manifests only."""

from __future__ import annotations

import pytest
from dotmac_integration.conformance import fake_manifest, fake_plugin
from dotmac_integration.discovery import ConnectorRegistry
from dotmac_integration.runtime_policy import (
    RuntimeBoundaryMissing,
    derive_runtime_policy,
)
from dotmac_integration.spi import (
    CapabilityDeclaration,
    ConnectorManifest,
    EgressDeclaration,
    SecretBindingDeclaration,
    SpiRange,
)


def _manifest(
    key: str,
    *,
    hosts: tuple[str, ...] = (),
    secrets: tuple[SecretBindingDeclaration, ...] = (),
) -> ConnectorManifest:
    return ConnectorManifest(
        connector_key=key,
        version="1.0.0",
        spi_range=SpiRange.parse(">=1.3,<2.0"),
        capabilities=(CapabilityDeclaration(capability_id="example.observe.v1"),),
        secret_bindings=secrets,
        egress=EgressDeclaration(hosts=hosts),
    )


def test_policy_is_the_deterministic_union_of_installed_manifests() -> None:
    first = _manifest(
        "first_connector",
        hosts=("shared.provider.example", "one.provider.example"),
        secrets=(SecretBindingDeclaration(name="signing_secret"),),
    )
    second = _manifest(
        "second_connector",
        hosts=("two.provider.example", "shared.provider.example"),
        secrets=(SecretBindingDeclaration(name="access_token", required=False),),
    )

    policy = derive_runtime_policy(
        ConnectorRegistry((fake_plugin(manifest_=second), fake_plugin(manifest_=first)))
    )

    assert tuple(item.connector_key for item in policy.connectors) == (
        "first_connector",
        "second_connector",
    )
    assert policy.egress_hosts == (
        "one.provider.example",
        "shared.provider.example",
        "two.provider.example",
    )
    assert policy.secret_bindings == (
        ("first_connector", "signing_secret", True),
        ("second_connector", "access_token", False),
    )


def test_private_single_label_dns_name_is_an_exact_egress_destination() -> None:
    manifest = _manifest("traccar_connector", hosts=("traccar",))
    policy = derive_runtime_policy(
        ConnectorRegistry((fake_plugin(manifest_=manifest),))
    )
    assert policy.egress_hosts == ("traccar",)


@pytest.mark.parametrize(
    "host",
    [
        "Traccar",
        "-traccar",
        "traccar-",
        "*.traccar",
        "http://traccar",
        "traccar.",
        "127.0.0.1",
    ],
)
def test_single_label_egress_does_not_open_non_dns_surfaces(host: str) -> None:
    with pytest.raises(ValueError, match="exact lower-case DNS hostname"):
        EgressDeclaration(hosts=(host,))


def test_a_legacy_manifest_cannot_be_projected_into_runtime_policy() -> None:
    legacy = ConnectorManifest(
        connector_key="legacy_connector",
        version="0.9.0",
        spi_range=SpiRange.parse(">=1.2,<2.0"),
        capabilities=(CapabilityDeclaration(capability_id="example.observe.v1"),),
    )

    with pytest.raises(RuntimeBoundaryMissing, match="legacy_connector"):
        derive_runtime_policy(ConnectorRegistry((fake_plugin(manifest_=legacy),)))


def test_an_empty_registry_and_explicit_empty_manifest_both_deny_egress() -> None:
    empty = derive_runtime_policy(ConnectorRegistry(()))
    explicit = derive_runtime_policy(
        ConnectorRegistry((fake_plugin(manifest_=fake_manifest()),))
    )

    assert empty.egress_hosts == ()
    assert explicit.egress_hosts == ()
    assert empty.digest != explicit.digest


def test_policy_digest_changes_when_a_manifest_boundary_changes() -> None:
    denied = derive_runtime_policy(
        ConnectorRegistry((fake_plugin(manifest_=_manifest("one_connector")),))
    )
    allowed = derive_runtime_policy(
        ConnectorRegistry(
            (
                fake_plugin(
                    manifest_=_manifest(
                        "one_connector", hosts=("api.provider.example",)
                    )
                ),
            )
        )
    )

    assert denied.digest != allowed.digest
