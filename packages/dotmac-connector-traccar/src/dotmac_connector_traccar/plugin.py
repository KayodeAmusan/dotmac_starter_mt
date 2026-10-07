"""Versioned Traccar REQUEST plugin and runtime-boundary declarations."""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import Final

import httpx
from dotmac_integration.spi import (
    CapabilityDeclaration,
    ConnectorManifest,
    ConnectorMode,
    Diagnostic,
    EgressDeclaration,
    RequestHandler,
    SecretBindingDeclaration,
    SpiRange,
)

from dotmac_connector_traccar.client import (
    ORIGIN,
    SERVICE_EMAIL,
    SERVICE_PASSWORD_BINDING,
    TraccarFailure,
    TraccarSessionPool,
    parse_config,
    parse_material,
)
from dotmac_connector_traccar.query import (
    CAPABILITY_IDS,
    DEVICE_CAPABILITY_ID,
    HEALTH_CAPABILITY_ID,
    HISTORY_CAPABILITY_ID,
    LATEST_POSITION_CAPABILITY_ID,
    TraccarRequestHandler,
)

CONNECTOR_KEY: Final = "traccar"
VERSION: Final = "0.1.0a1"

CONTRACT_DIGESTS: Final[Mapping[str, str]] = MappingProxyType(
    {
        HEALTH_CAPABILITY_ID: (
            "a08c06fe7ae93ca1dc180b439efe449ae8ee7692a4c6d116559e3d24fc6632a2"
        ),
        DEVICE_CAPABILITY_ID: (
            "c0f08e7c2f980b019ad8618649a512fb410245b90c00b82a53972c0ad7ca39bb"
        ),
        LATEST_POSITION_CAPABILITY_ID: (
            "5f8b4faa3e598b56dcd69189cbdc736be6df131088eb2ce12e51da0234e37ddb"
        ),
        HISTORY_CAPABILITY_ID: (
            "028f65a0b79dc81309e0fa794d74d3d1ab7ee70f0ac5cebd23148a3d08802cbb"
        ),
    }
)
if CONTRACT_DIGESTS.keys() != CAPABILITY_IDS:
    raise RuntimeError("Traccar contract digest inventory does not match capabilities")

CONFIG_SCHEMA: Final[dict[str, object]] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "base_url",
        "connect_timeout_seconds",
        "read_timeout_seconds",
    ],
    "properties": {
        "base_url": {"type": "string", "const": ORIGIN},
        "connect_timeout_seconds": {
            "type": "number",
            "minimum": 0.1,
            "maximum": 60,
        },
        "read_timeout_seconds": {
            "type": "number",
            "minimum": 0.1,
            "maximum": 60,
        },
    },
}

MANIFEST: Final = ConnectorManifest(
    connector_key=CONNECTOR_KEY,
    version=VERSION,
    spi_range=SpiRange.parse(">=1.6,<2.0"),
    capabilities=tuple(
        CapabilityDeclaration(
            capability_id=capability_id,
            config_schema=CONFIG_SCHEMA,
            modes=frozenset({ConnectorMode.REQUEST}),
            claims_contract_digest=CONTRACT_DIGESTS[capability_id],
        )
        for capability_id in sorted(CONTRACT_DIGESTS)
    ),
    secret_bindings=(
        SecretBindingDeclaration(
            name=SERVICE_EMAIL,
            description="Traccar service identity email, materialized at runtime.",
        ),
        SecretBindingDeclaration(
            name=SERVICE_PASSWORD_BINDING,
            description="Traccar service identity password, materialized at runtime.",
        ),
    ),
    egress=EgressDeclaration(hosts=("traccar",)),
)


class TraccarPlugin:
    """One connector plugin with connection-isolated ephemeral sessions."""

    manifest: ConnectorManifest = MANIFEST
    historical_manifests: tuple[ConnectorManifest, ...] = ()
    modes: frozenset[ConnectorMode] = frozenset({ConnectorMode.REQUEST})

    def __init__(self, transport: httpx.BaseTransport | None = None) -> None:
        self._handler = TraccarRequestHandler(TraccarSessionPool(transport=transport))

    def request_handler_for(self, capability_id: str) -> RequestHandler:
        self.manifest.require_declares(capability_id)
        return self._handler

    def validate_connection(
        self,
        *,
        config: dict[str, object],
        secrets: dict[str, object],
    ) -> tuple[Diagnostic, ...]:
        try:
            parse_config(config)
            parse_material(secrets)
        except TraccarFailure:
            return (Diagnostic(ok=False, code="configuration_invalid"),)
        return ()


def query_capabilities() -> Mapping[str, str]:
    """Stable public inventory used by focused contract tests."""

    return {
        HEALTH_CAPABILITY_ID: "provider health",
        DEVICE_CAPABILITY_ID: "device lookup",
        LATEST_POSITION_CAPABILITY_ID: "latest position",
        HISTORY_CAPABILITY_ID: "bounded position history",
    }


PLUGIN: Final = TraccarPlugin()
