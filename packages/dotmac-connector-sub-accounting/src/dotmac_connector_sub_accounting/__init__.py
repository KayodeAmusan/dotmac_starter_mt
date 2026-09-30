"""Public surface for the Dotmac Sub invoice-accounting-sync connector."""

from dotmac_connector_sub_accounting.mapping import (
    CONTRACT_VERSION,
    SubAccountingMappingError,
    map_item,
)
from dotmac_connector_sub_accounting.plugin import (
    CAPABILITY_ID,
    CONNECTOR_KEY,
    MANIFEST,
    PLUGIN,
    SubAccountingConnector,
)
from dotmac_connector_sub_accounting.polling import (
    SubAccountingPollError,
    SubAccountingPollHandler,
)

__version__ = "0.1.0a1"

__all__ = [
    "CAPABILITY_ID",
    "CONNECTOR_KEY",
    "CONTRACT_VERSION",
    "MANIFEST",
    "PLUGIN",
    "SubAccountingConnector",
    "SubAccountingMappingError",
    "SubAccountingPollError",
    "SubAccountingPollHandler",
    "__version__",
    "map_item",
]
