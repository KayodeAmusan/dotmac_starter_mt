"""Strict Traccar response normalization with no raw-provider passthrough."""

from __future__ import annotations

import math
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Final


class TraccarMalformedResponse(ValueError):
    """A provider response cannot be represented by the published contract."""


_DEVICE_STATUSES: Final = {
    "online": "online",
    "offline": "offline",
    "unknown": "unknown",
}


def _object(value: object, *, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise TraccarMalformedResponse(f"{label} is not an object")
    return value


def _text(value: object, *, label: str, required: bool = True) -> str | None:
    if value is None and not required:
        return None
    if not isinstance(value, str) or not value.strip():
        raise TraccarMalformedResponse(f"{label} is invalid")
    return value


def _integer(value: object, *, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise TraccarMalformedResponse(f"{label} is invalid")
    return value


def _number(
    value: object,
    *,
    label: str,
    minimum: float | None = None,
    maximum: float | None = None,
) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise TraccarMalformedResponse(f"{label} is invalid")
    result = float(value)
    if not math.isfinite(result):
        raise TraccarMalformedResponse(f"{label} is invalid")
    if minimum is not None and result < minimum:
        raise TraccarMalformedResponse(f"{label} is invalid")
    if maximum is not None and result > maximum:
        raise TraccarMalformedResponse(f"{label} is invalid")
    return result


def _timestamp(value: object, *, label: str) -> str:
    text = _text(value, label=label)
    if text is None:
        raise TraccarMalformedResponse(f"{label} is invalid")
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        raise TraccarMalformedResponse(f"{label} is invalid") from None
    if parsed.tzinfo is None:
        raise TraccarMalformedResponse(f"{label} has no timezone")
    return parsed.astimezone(UTC).isoformat().replace("+00:00", "Z")


def normalize_device(value: object) -> dict[str, object]:
    """Normalize the small device identity/status surface Fleet consumes."""

    item = _object(value, label="device")
    provider_ref = _integer(item.get("id"), label="device id")
    unique_id = _text(item.get("uniqueId"), label="device unique id")
    name = _text(item.get("name"), label="device name")
    raw_status = item.get("status")
    status = (
        _DEVICE_STATUSES.get(raw_status, "unknown")
        if isinstance(raw_status, str)
        else "unknown"
    )
    return {
        "provider_device_ref": str(provider_ref),
        "unique_id": unique_id,
        "name": name,
        "connection_status": status,
    }


def normalize_position(value: object) -> dict[str, object]:
    """Normalize one position; provider attributes deliberately do not cross."""

    item = _object(value, label="position")
    normalized: dict[str, object] = {
        "provider_position_ref": str(_integer(item.get("id"), label="position id")),
        "provider_device_ref": str(
            _integer(item.get("deviceId"), label="position device id")
        ),
        "observed_at": _timestamp(item.get("fixTime"), label="position fix time"),
        "latitude": _number(
            item.get("latitude"), label="position latitude", minimum=-90, maximum=90
        ),
        "longitude": _number(
            item.get("longitude"),
            label="position longitude",
            minimum=-180,
            maximum=180,
        ),
    }
    if not isinstance(item.get("valid"), bool):
        raise TraccarMalformedResponse("position validity is invalid")
    normalized["valid"] = item["valid"]
    optional_numbers = (
        ("speed", "speed", 0.0, None),
        ("course", "course", 0.0, 360.0),
        ("altitude", "altitude", None, None),
        ("accuracy", "accuracy", 0.0, None),
    )
    for source, target, minimum, maximum in optional_numbers:
        if item.get(source) is not None:
            normalized[target] = _number(
                item[source],
                label=f"position {source}",
                minimum=minimum,
                maximum=maximum,
            )
    if item.get("serverTime") is not None:
        normalized["received_at"] = _timestamp(
            item["serverTime"], label="position server time"
        )
    return normalized
