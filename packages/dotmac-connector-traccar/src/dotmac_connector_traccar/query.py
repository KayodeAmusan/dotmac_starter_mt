"""Fixed, provider-neutral Fleet requests over the Traccar transport."""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Final

from dotmac_integration.spi import QueryRequest, QueryResult, QueryStatus

from dotmac_connector_traccar.client import (
    TraccarFailure,
    TraccarSessionPool,
    parse_config,
    parse_material,
)
from dotmac_connector_traccar.mapping import (
    TraccarMalformedResponse,
    normalize_device,
    normalize_position,
)

HEALTH_CAPABILITY_ID: Final = "integration.provider.health.v1"
DEVICE_CAPABILITY_ID: Final = "fleet.tracking.device.read.v1"
LATEST_POSITION_CAPABILITY_ID: Final = "fleet.tracking.position.latest.v1"
HISTORY_CAPABILITY_ID: Final = "fleet.tracking.position.history.v1"
CAPABILITY_IDS: Final = frozenset(
    {
        HEALTH_CAPABILITY_ID,
        DEVICE_CAPABILITY_ID,
        LATEST_POSITION_CAPABILITY_ID,
        HISTORY_CAPABILITY_ID,
    }
)

MAX_HISTORY_RANGE: Final = timedelta(days=7)
MAX_HISTORY_POSITIONS: Final = 5_000
_UNIQUE_ID: Final = re.compile(r"[A-Za-z0-9_.:-]{1,160}")
_PROVIDER_REF: Final = re.compile(r"[1-9][0-9]{0,18}")


def _result(
    status: QueryStatus, observation: Mapping[str, object] | None = None
) -> QueryResult:
    return QueryResult(status=status, observation=observation)


def _json(response) -> object:
    try:
        return response.json()
    except ValueError:
        raise TraccarFailure(QueryStatus.MALFORMED_PROVIDER_RESPONSE) from None


def _items(value: object, *, label: str) -> list[object]:
    if not isinstance(value, list):
        raise TraccarMalformedResponse(f"{label} is not a list")
    return value


def _selector(payload: Mapping[str, object]) -> tuple[str, str]:
    allowed = {"provider_device_ref", "unique_id"}
    if set(payload) - allowed or len(payload) != 1:
        raise TraccarFailure(QueryStatus.INVALID_QUERY)
    provider_ref = payload.get("provider_device_ref")
    unique_id = payload.get("unique_id")
    if isinstance(provider_ref, str) and _PROVIDER_REF.fullmatch(provider_ref):
        return "id", provider_ref
    if isinstance(unique_id, str) and _UNIQUE_ID.fullmatch(unique_id):
        return "uniqueId", unique_id
    raise TraccarFailure(QueryStatus.INVALID_QUERY)


def _instant(value: object) -> datetime:
    if not isinstance(value, str) or not value:
        raise TraccarFailure(QueryStatus.INVALID_QUERY)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise TraccarFailure(QueryStatus.INVALID_QUERY) from None
    if parsed.tzinfo is None:
        raise TraccarFailure(QueryStatus.INVALID_QUERY)
    return parsed.astimezone(UTC)


def _wire_time(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


class TraccarRequestHandler:
    """REQUEST handler with a closed capability/path mapping."""

    def __init__(self, pool: TraccarSessionPool) -> None:
        self._pool = pool

    def _get(
        self,
        request: QueryRequest,
        path: str,
        params: dict[str, str] | None = None,
    ):
        config = parse_config(request.config)
        email, password = parse_material(request.secrets)
        return self._pool.request(
            connection_ref=str(request.installation_id),
            config=config,
            email=email,
            password=password,
            path=path,
            params=params,
        )

    def _device(
        self, request: QueryRequest, selector: Mapping[str, object]
    ) -> dict[str, object]:
        name, value = _selector(selector)
        items = _items(
            _json(self._get(request, "/api/devices", {name: value})),
            label="device response",
        )
        normalized = [normalize_device(item) for item in items]
        matching = [
            item
            for item in normalized
            if (name == "id" and item["provider_device_ref"] == value)
            or (name == "uniqueId" and item["unique_id"] == value)
        ]
        if not matching:
            raise TraccarFailure(QueryStatus.NOT_FOUND)
        if len(matching) != 1:
            raise TraccarFailure(QueryStatus.MALFORMED_PROVIDER_RESPONSE)
        return matching[0]

    def _device_ref(self, request: QueryRequest, selector: Mapping[str, object]) -> str:
        name, value = _selector(selector)
        if name == "id":
            return value
        return str(self._device(request, selector)["provider_device_ref"])

    def _health(self, request: QueryRequest) -> Mapping[str, object]:
        if request.payload:
            raise TraccarFailure(QueryStatus.INVALID_QUERY)
        body = _json(self._get(request, "/api/server"))
        if not isinstance(body, Mapping):
            raise TraccarFailure(QueryStatus.MALFORMED_PROVIDER_RESPONSE)
        return {"available": True}

    def _latest(self, request: QueryRequest) -> Mapping[str, object]:
        device_ref = self._device_ref(request, request.payload)
        items = _items(
            _json(
                self._get(
                    request,
                    "/api/positions",
                    {"deviceId": device_ref},
                )
            ),
            label="position response",
        )
        positions = [normalize_position(item) for item in items]
        positions = [
            item for item in positions if item["provider_device_ref"] == device_ref
        ]
        if not positions:
            raise TraccarFailure(QueryStatus.NOT_FOUND)
        return max(
            positions,
            key=lambda item: (
                str(item["observed_at"]),
                int(str(item["provider_position_ref"])),
            ),
        )

    def _history(self, request: QueryRequest) -> Mapping[str, object]:
        if set(request.payload) not in (
            {"provider_device_ref", "from", "to"},
            {"unique_id", "from", "to"},
        ):
            raise TraccarFailure(QueryStatus.INVALID_QUERY)
        selector = {
            key: request.payload[key]
            for key in ("provider_device_ref", "unique_id")
            if key in request.payload
        }
        start = _instant(request.payload["from"])
        end = _instant(request.payload["to"])
        if start >= end or end - start > MAX_HISTORY_RANGE:
            raise TraccarFailure(QueryStatus.INVALID_QUERY)
        device_ref = self._device_ref(request, selector)
        items = _items(
            _json(
                self._get(
                    request,
                    "/api/positions",
                    {
                        "deviceId": device_ref,
                        "from": _wire_time(start),
                        "to": _wire_time(end),
                    },
                )
            ),
            label="position history response",
        )
        if len(items) > MAX_HISTORY_POSITIONS:
            raise TraccarFailure(QueryStatus.MALFORMED_PROVIDER_RESPONSE)
        positions = [normalize_position(item) for item in items]
        if any(item["provider_device_ref"] != device_ref for item in positions):
            raise TraccarFailure(QueryStatus.MALFORMED_PROVIDER_RESPONSE)
        positions.sort(
            key=lambda item: (
                str(item["observed_at"]),
                int(str(item["provider_position_ref"])),
            )
        )
        return {
            "from": _wire_time(start),
            "to": _wire_time(end),
            "positions": positions,
        }

    def query(self, request: QueryRequest) -> QueryResult:
        if request.capability_id not in CAPABILITY_IDS:
            return _result(QueryStatus.INVALID_QUERY)
        try:
            if request.capability_id == HEALTH_CAPABILITY_ID:
                observation = self._health(request)
            elif request.capability_id == DEVICE_CAPABILITY_ID:
                observation = self._device(request, request.payload)
            elif request.capability_id == LATEST_POSITION_CAPABILITY_ID:
                observation = self._latest(request)
            else:
                observation = self._history(request)
        except TraccarFailure as exc:
            return _result(exc.status)
        except TraccarMalformedResponse:
            return _result(QueryStatus.MALFORMED_PROVIDER_RESPONSE)
        return _result(QueryStatus.SUCCEEDED, observation)
