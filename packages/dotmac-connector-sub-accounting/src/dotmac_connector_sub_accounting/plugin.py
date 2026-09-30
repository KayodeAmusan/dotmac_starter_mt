"""Sub invoice-accounting-sync feed: a single POLL-only observation connector.

Reconciles Sub's ``invoices/accounting-sync/v2`` feed into
``invoices.accounting_sync.observation.v1`` observations. This distribution
owns the wire translation only — it never constructs the ERP-bound delivery
request (no ``organization_id``, no ``idempotency_key``), which are the
generic Integration engine's and the destination ``ObservationPortClient``'s
responsibility. See ``mapping.py`` for the observation shape and the
``digest_version``/``projection_digest`` forward-only wire-shape contract.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Final

import httpx
from dotmac_integration.spi import (
    CapabilityDeclaration,
    ConnectorManifest,
    ConnectorMode,
    Diagnostic,
    EgressDeclaration,
    PollHandler,
    SecretBindingDeclaration,
    SpiRange,
)

from dotmac_connector_sub_accounting.polling import SubAccountingPollHandler

CONNECTOR_KEY: Final = "sub_accounting"
CAPABILITY_ID: Final = "invoices.accounting_sync.observation.v1"
VERSION: Final = "0.1.0a1"

#: Sub's registered production hostname, confirmed via the fleet registry
#: this session (non-secret, DNS-registered). THIS IS A PRODUCTION
#: COORDINATE: declaring it here only fixes what this manifest PERMITS
#: reaching under SPI 1.3's exact-host egress rule; it is not an activation,
#: binding or deployment decision, and this code must not be bound/enabled
#: without a separate explicit go-ahead.
API_HOST: Final = "selfcare.dotmac.io"

#: The Sub API key's logical purpose, corresponding to an ``ApiKey`` scoped to
#: ``integration:accounting_sync:read`` on the ``dotmac_sub`` side.
#: Provisioning the actual key value is a separate operational step.
SUB_API_KEY: Final = "sub_api_key"

CONFIG_SCHEMA: Final[dict[str, object]] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "limit": {"type": "integer", "minimum": 1, "maximum": 500},
        "updated_since": {"type": "string", "format": "date-time"},
    },
}

MANIFEST: Final = ConnectorManifest(
    connector_key=CONNECTOR_KEY,
    version=VERSION,
    spi_range=SpiRange.parse(">=1.3,<2.0"),
    capabilities=(
        CapabilityDeclaration(
            capability_id=CAPABILITY_ID,
            config_schema=CONFIG_SCHEMA,
            modes=frozenset({ConnectorMode.POLL}),
            # ERP's ProductPort descriptor v3 owns the observation schema.
            # This claim is pinned to its published contract, not a second
            # connector-authored schema. A change requires a new capability id.
            claims_contract_digest=(
                "f69ffd1e486a298bfdff5ab6a4b1a30a6962075b30d91400ef6ca4247609ac74"
            ),
        ),
    ),
    secret_bindings=(
        SecretBindingDeclaration(
            name=SUB_API_KEY,
            description=(
                "Sub API key scoped to integration:accounting_sync:read, "
                "sent as the X-API-Key header on every poll request."
            ),
        ),
    ),
    egress=EgressDeclaration(hosts=(API_HOST,)),
)


def _material(secrets: Mapping[str, object], name: str) -> str | None:
    value = secrets.get(name)
    return value if isinstance(value, str) and value else None


@dataclass(frozen=True, slots=True)
class SubAccountingConnector:
    """One independently released, POLL-only Sub accounting-sync plugin."""

    transport: httpx.BaseTransport | None = field(default=None, repr=False)
    timeout_seconds: float = 30.0
    manifest: ConnectorManifest = MANIFEST
    historical_manifests: tuple[ConnectorManifest, ...] = ()
    modes: frozenset[ConnectorMode] = frozenset({ConnectorMode.POLL})

    def poll_handler_for(self, capability_id: str) -> PollHandler:
        self.manifest.require_declares(capability_id)
        return SubAccountingPollHandler(self.transport, self.timeout_seconds)

    def validate_connection(
        self,
        *,
        config: dict[str, object],
        secrets: dict[str, object],
    ) -> tuple[Diagnostic, ...]:
        del config
        if _material(secrets, SUB_API_KEY) is None:
            return (Diagnostic(ok=False, code="required_material_unavailable"),)
        return ()


PLUGIN: Final = SubAccountingConnector()
