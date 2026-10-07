"""Public surface for the Traccar connector plugin."""

from dotmac_connector_traccar.plugin import (
    DEVICE_CAPABILITY_ID,
    HEALTH_CAPABILITY_ID,
    HISTORY_CAPABILITY_ID,
    LATEST_POSITION_CAPABILITY_ID,
    MANIFEST,
    PLUGIN,
    TraccarPlugin,
)

__version__ = "0.1.0a1"

__all__ = [
    "DEVICE_CAPABILITY_ID",
    "HEALTH_CAPABILITY_ID",
    "HISTORY_CAPABILITY_ID",
    "LATEST_POSITION_CAPABILITY_ID",
    "MANIFEST",
    "PLUGIN",
    "TraccarPlugin",
    "__version__",
]
