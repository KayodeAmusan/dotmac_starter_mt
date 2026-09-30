"""Manifest, mode discipline, and SPI conformance."""

from __future__ import annotations

import pytest
from dotmac_connector_sub_accounting import (
    CAPABILITY_ID,
    CONNECTOR_KEY,
    MANIFEST,
    PLUGIN,
    __version__,
)
from dotmac_connector_sub_accounting.plugin import API_HOST, SUB_API_KEY
from dotmac_integration.conformance import assert_plugin_conforms
from dotmac_integration.spi import (
    ConnectorMode,
    InvalidManifestError,
    verify_plugin_modes,
)

API_KEY_VALUE = "held-sub-api-key-material"


def test_manifest_identity_and_version() -> None:
    assert MANIFEST.connector_key == CONNECTOR_KEY == "sub_accounting"
    assert MANIFEST.version == __version__ == "0.1.0a1"
    assert MANIFEST.spi_range.minimum.major == 1
    assert MANIFEST.spi_range.minimum.minor == 3


def test_declares_exactly_one_poll_only_capability() -> None:
    assert MANIFEST.capability_ids == frozenset({CAPABILITY_ID})
    capability = MANIFEST.require_declares(CAPABILITY_ID)
    assert capability.modes == frozenset({ConnectorMode.POLL})


def test_the_capability_claims_erp_published_contract_digest() -> None:
    # ERP's v3 descriptor owns this schema. The connector only claims it.
    capability = MANIFEST.require_declares(CAPABILITY_ID)
    assert capability.claims_contract_digest == (
        "f69ffd1e486a298bfdff5ab6a4b1a30a6962075b30d91400ef6ca4247609ac74"
    )


def test_declares_exactly_the_one_secret_binding() -> None:
    assert MANIFEST.secret_bindings is not None
    names = tuple(binding.name for binding in MANIFEST.secret_bindings)
    assert names == (SUB_API_KEY,)
    assert MANIFEST.secret_bindings[0].required is True


def test_declares_exact_egress_to_subs_production_host() -> None:
    assert MANIFEST.egress is not None
    assert MANIFEST.egress.hosts == (API_HOST,)
    assert API_HOST == "selfcare.dotmac.io"


def test_plugin_declares_poll_only() -> None:
    assert PLUGIN.modes == frozenset({ConnectorMode.POLL})
    assert ConnectorMode.INGRESS not in PLUGIN.modes
    assert ConnectorMode.DELIVERY not in PLUGIN.modes


def test_plugin_passes_spi_mode_and_full_conformance() -> None:
    verify_plugin_modes(PLUGIN)
    assert_plugin_conforms(PLUGIN)


def test_undeclared_capability_is_refused_not_silently_handled() -> None:
    with pytest.raises(InvalidManifestError):
        PLUGIN.poll_handler_for("invoices.does_not_exist.v1")


def test_validate_connection_requires_the_declared_secret() -> None:
    assert (
        PLUGIN.validate_connection(config={}, secrets={SUB_API_KEY: API_KEY_VALUE})
        == ()
    )
    diagnostics = PLUGIN.validate_connection(config={}, secrets={})
    assert tuple(item.code for item in diagnostics) == (
        "required_material_unavailable",
    )


def test_no_secret_material_leaks_through_a_failed_validation() -> None:
    diagnostics = PLUGIN.validate_connection(config={}, secrets={})
    assert API_KEY_VALUE not in repr(diagnostics)
    assert SUB_API_KEY not in repr(diagnostics)
