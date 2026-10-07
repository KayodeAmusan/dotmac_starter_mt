from __future__ import annotations

from collections.abc import Callable
from typing import Any
from uuid import UUID

import httpx
import pytest
from dotmac_connector_traccar import MANIFEST, __version__
from dotmac_connector_traccar import client as traccar_client
from dotmac_connector_traccar.client import (
    ORIGIN,
    SERVICE_EMAIL,
    SERVICE_PASSWORD_BINDING,
    TraccarSessionPool,
    parse_config,
)
from dotmac_connector_traccar.plugin import CONTRACT_DIGESTS, TraccarPlugin
from dotmac_connector_traccar.query import (
    DEVICE_CAPABILITY_ID,
    HEALTH_CAPABILITY_ID,
    HISTORY_CAPABILITY_ID,
    LATEST_POSITION_CAPABILITY_ID,
)
from dotmac_integration.conformance import assert_plugin_conforms
from dotmac_integration.spi import ConnectorMode, QueryRequest, QueryStatus

EMAIL = "service@example.invalid"
PASSWORD = "held-provider-password"


def _config(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "base_url": ORIGIN,
        "connect_timeout_seconds": 2.5,
        "read_timeout_seconds": 8.0,
    }
    value.update(overrides)
    return value


def _secrets(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        SERVICE_EMAIL: EMAIL,
        SERVICE_PASSWORD_BINDING: PASSWORD,
    }
    value.update(overrides)
    return value


def _request(
    capability_id: str,
    payload: dict[str, object],
    *,
    installation_id: UUID = UUID("11111111-1111-1111-1111-111111111111"),
    config: dict[str, object] | None = None,
    secrets: dict[str, object] | None = None,
) -> QueryRequest:
    return QueryRequest(
        installation_id=installation_id,
        capability_id=capability_id,
        payload=payload,
        config=config or _config(),
        secrets=secrets or _secrets(),
    )


def _plugin(respond: Callable[[httpx.Request], httpx.Response]) -> TraccarPlugin:
    return TraccarPlugin(transport=httpx.MockTransport(respond))


def _authenticated(
    read_response: Callable[[httpx.Request], httpx.Response],
) -> Callable[[httpx.Request], httpx.Response]:
    def respond(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            assert request.url.path == "/api/session"
            return httpx.Response(
                200,
                headers={"set-cookie": "JSESSIONID=session-one; Path=/; HttpOnly"},
                json={"id": 1},
            )
        return read_response(request)

    return respond


def _position(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "id": 91,
        "deviceId": 42,
        "fixTime": "2026-10-07T10:00:00Z",
        "serverTime": "2026-10-07T10:00:01Z",
        "latitude": 9.0765,
        "longitude": 7.3986,
        "valid": True,
        "speed": 12.5,
        "course": 180.0,
        "altitude": 500.0,
        "accuracy": 4.0,
        "attributes": {"ignition": True, "password": "must-not-cross"},
        "protocol": "gps103",
    }
    value.update(overrides)
    return value


def test_manifest_is_an_exact_request_runtime_contract() -> None:
    plugin = _plugin(_authenticated(lambda request: httpx.Response(200, json={})))
    assert MANIFEST.connector_key == "traccar"
    assert MANIFEST.version == __version__ == "0.1.0a1"
    assert plugin.modes == frozenset({ConnectorMode.REQUEST})
    assert MANIFEST.capability_ids == {
        HEALTH_CAPABILITY_ID,
        DEVICE_CAPABILITY_ID,
        LATEST_POSITION_CAPABILITY_ID,
        HISTORY_CAPABILITY_ID,
    }
    assert tuple(item.name for item in MANIFEST.secret_bindings or ()) == (
        SERVICE_EMAIL,
        SERVICE_PASSWORD_BINDING,
    )
    assert MANIFEST.egress is not None
    assert MANIFEST.egress.hosts == ("traccar",)
    assert_plugin_conforms(plugin)


def test_manifest_claims_every_reviewed_owner_contract_digest() -> None:
    expected = {
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
    assert dict(CONTRACT_DIGESTS) == expected
    assert {
        capability.capability_id: capability.claims_contract_digest
        for capability in MANIFEST.capabilities
    } == expected


def test_provider_client_ignores_ambient_proxy_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    constructed: list[dict[str, Any]] = []
    real_client = httpx.Client
    monkeypatch.setenv("HTTP_PROXY", "http://ambient-proxy.invalid:8080")

    def capture_client(**kwargs: Any) -> httpx.Client:
        constructed.append(kwargs)
        return real_client(**kwargs)

    monkeypatch.setattr(traccar_client.httpx, "Client", capture_client)
    session = TraccarSessionPool(
        transport=httpx.MockTransport(lambda request: httpx.Response(500))
    ).session(
        "connection-one",
        parse_config(_config()),
        EMAIL,
        PASSWORD,
    )
    try:
        assert constructed[0]["trust_env"] is False
    finally:
        session.client.close()


def test_session_is_lazy_then_reused_for_later_queries() -> None:
    seen: list[httpx.Request] = []

    def read(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        assert request.headers["cookie"] == "JSESSIONID=session-one"
        return httpx.Response(200, json={"version": "6.15.3"})

    plugin = _plugin(_authenticated(read))
    handler = plugin.request_handler_for(HEALTH_CAPABILITY_ID)
    first = handler.query(_request(HEALTH_CAPABILITY_ID, {}))
    second = handler.query(_request(HEALTH_CAPABILITY_ID, {}))

    assert first.status is QueryStatus.SUCCEEDED
    assert first.observation == {"available": True}
    assert second.status is QueryStatus.SUCCEEDED
    assert len(seen) == 2


def test_sessions_are_isolated_by_opaque_connection_reference() -> None:
    login_count = 0
    seen_cookies: list[str] = []

    def respond(request: httpx.Request) -> httpx.Response:
        nonlocal login_count
        if request.method == "POST":
            login_count += 1
            return httpx.Response(
                200,
                headers={"set-cookie": f"JSESSIONID=s{login_count}; Path=/"},
                json={"id": 1},
            )
        seen_cookies.append(request.headers["cookie"])
        return httpx.Response(200, json={"version": "6.15.3"})

    handler = _plugin(respond).request_handler_for(HEALTH_CAPABILITY_ID)
    assert (
        handler.query(
            _request(
                HEALTH_CAPABILITY_ID,
                {},
                installation_id=UUID("11111111-1111-1111-1111-111111111111"),
            )
        ).status
        is QueryStatus.SUCCEEDED
    )
    assert (
        handler.query(
            _request(
                HEALTH_CAPABILITY_ID,
                {},
                installation_id=UUID("22222222-2222-2222-2222-222222222222"),
            )
        ).status
        is QueryStatus.SUCCEEDED
    )
    assert seen_cookies == ["JSESSIONID=s1", "JSESSIONID=s2"]


def test_a_config_revision_replaces_and_closes_the_cached_client() -> None:
    pool = TraccarSessionPool()
    first = pool.session(
        "opaque-installation",
        parse_config(_config()),
        EMAIL,
        PASSWORD,
    )
    second = pool.session(
        "opaque-installation",
        parse_config(_config(read_timeout_seconds=9.0)),
        EMAIL,
        PASSWORD,
    )

    assert first is not second
    assert first.client.is_closed
    assert not second.client.is_closed


def test_a_401_causes_exactly_one_reauthentication_and_read_replay() -> None:
    auth_calls = 0
    read_calls = 0

    def respond(request: httpx.Request) -> httpx.Response:
        nonlocal auth_calls, read_calls
        if request.method == "POST":
            auth_calls += 1
            return httpx.Response(
                200,
                headers={"set-cookie": f"JSESSIONID=s{auth_calls}; Path=/"},
                json={"id": 1},
            )
        read_calls += 1
        if read_calls == 1:
            return httpx.Response(401, text=f"{PASSWORD} provider-private")
        assert request.headers["cookie"] == "JSESSIONID=s2"
        return httpx.Response(200, json={"version": "6.15.3"})

    result = (
        _plugin(respond)
        .request_handler_for(HEALTH_CAPABILITY_ID)
        .query(_request(HEALTH_CAPABILITY_ID, {}))
    )
    assert result.status is QueryStatus.SUCCEEDED
    assert (auth_calls, read_calls) == (2, 2)


def test_a_second_unauthorized_response_is_not_retried_or_leaked() -> None:
    calls: list[str] = []

    def respond(request: httpx.Request) -> httpx.Response:
        calls.append(request.method)
        if request.method == "POST":
            return httpx.Response(
                200,
                headers={"set-cookie": "JSESSIONID=s; Path=/"},
                json={"id": 1},
            )
        return httpx.Response(403, text=f"{PASSWORD} provider-private")

    result = (
        _plugin(respond)
        .request_handler_for(HEALTH_CAPABILITY_ID)
        .query(_request(HEALTH_CAPABILITY_ID, {}))
    )
    assert result.status is QueryStatus.UNAUTHORIZED_PROVIDER_SESSION
    assert calls == ["POST", "GET", "POST", "GET"]
    assert PASSWORD not in repr(result)


def test_device_lookup_is_exact_and_normalized() -> None:
    def read(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/devices"
        assert dict(request.url.params) == {"uniqueId": "imei-123"}
        return httpx.Response(
            200,
            json=[
                {
                    "id": 42,
                    "uniqueId": "imei-123",
                    "name": "Tracker 42",
                    "status": "online",
                    "phone": "+234-secret-provider-field",
                }
            ],
        )

    result = (
        _plugin(_authenticated(read))
        .request_handler_for(DEVICE_CAPABILITY_ID)
        .query(_request(DEVICE_CAPABILITY_ID, {"unique_id": "imei-123"}))
    )
    assert result.status is QueryStatus.SUCCEEDED
    assert result.observation == {
        "provider_device_ref": "42",
        "unique_id": "imei-123",
        "name": "Tracker 42",
        "connection_status": "online",
    }


def test_latest_position_discards_raw_attributes_and_protocol() -> None:
    def read(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/positions"
        assert dict(request.url.params) == {"deviceId": "42"}
        return httpx.Response(200, json=[_position()])

    result = (
        _plugin(_authenticated(read))
        .request_handler_for(LATEST_POSITION_CAPABILITY_ID)
        .query(
            _request(
                LATEST_POSITION_CAPABILITY_ID,
                {"provider_device_ref": "42"},
            )
        )
    )
    assert result.status is QueryStatus.SUCCEEDED
    assert result.observation is not None
    assert result.observation["provider_position_ref"] == "91"
    assert "attributes" not in result.observation
    assert "protocol" not in result.observation
    assert PASSWORD not in repr(result)


def test_history_is_bounded_sorted_and_uses_only_fixed_query_parameters() -> None:
    def read(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/positions"
        assert dict(request.url.params) == {
            "deviceId": "42",
            "from": "2026-10-07T00:00:00Z",
            "to": "2026-10-08T00:00:00Z",
        }
        return httpx.Response(
            200,
            json=[
                _position(id=92, fixTime="2026-10-07T11:00:00Z"),
                _position(id=91, fixTime="2026-10-07T10:00:00Z"),
            ],
        )

    result = (
        _plugin(_authenticated(read))
        .request_handler_for(HISTORY_CAPABILITY_ID)
        .query(
            _request(
                HISTORY_CAPABILITY_ID,
                {
                    "provider_device_ref": "42",
                    "from": "2026-10-07T00:00:00Z",
                    "to": "2026-10-08T00:00:00Z",
                },
            )
        )
    )
    assert result.status is QueryStatus.SUCCEEDED
    assert result.observation is not None
    positions = result.observation["positions"]
    assert isinstance(positions, tuple)
    assert [item["provider_position_ref"] for item in positions] == ["91", "92"]


def test_history_over_seven_days_is_refused_before_provider_io() -> None:
    called = False

    def respond(request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(500)

    result = (
        _plugin(respond)
        .request_handler_for(HISTORY_CAPABILITY_ID)
        .query(
            _request(
                HISTORY_CAPABILITY_ID,
                {
                    "provider_device_ref": "42",
                    "from": "2026-10-01T00:00:00Z",
                    "to": "2026-10-09T00:00:00Z",
                },
            )
        )
    )
    assert result.status is QueryStatus.INVALID_QUERY
    assert called is False


@pytest.mark.parametrize(
    ("response", "status"),
    [
        (httpx.Response(302), QueryStatus.PROVIDER_UNAVAILABLE),
        (httpx.Response(429), QueryStatus.PROVIDER_UNAVAILABLE),
        (httpx.Response(503), QueryStatus.PROVIDER_UNAVAILABLE),
        (
            httpx.Response(200, content=b"not-json"),
            QueryStatus.MALFORMED_PROVIDER_RESPONSE,
        ),
        (
            httpx.Response(200, json={"not": "a-list"}),
            QueryStatus.MALFORMED_PROVIDER_RESPONSE,
        ),
    ],
)
def test_provider_failures_are_normalized_without_body_leakage(
    response: httpx.Response, status: QueryStatus
) -> None:
    result = (
        _plugin(_authenticated(lambda request: response))
        .request_handler_for(DEVICE_CAPABILITY_ID)
        .query(_request(DEVICE_CAPABILITY_ID, {"unique_id": "imei-123"}))
    )
    assert result.status is status
    assert result.observation is None
    assert PASSWORD not in repr(result)


def test_timeout_is_distinct_from_provider_unavailable() -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(
                200,
                headers={"set-cookie": "JSESSIONID=s; Path=/"},
                json={"id": 1},
            )
        raise httpx.ReadTimeout("provider private", request=request)

    result = (
        _plugin(respond)
        .request_handler_for(HEALTH_CAPABILITY_ID)
        .query(_request(HEALTH_CAPABILITY_ID, {}))
    )
    assert result.status is QueryStatus.TIMEOUT


def test_an_oversized_provider_history_is_malformed_not_a_caller_error() -> None:
    def read(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[{}] * 5_001)

    result = (
        _plugin(_authenticated(read))
        .request_handler_for(HISTORY_CAPABILITY_ID)
        .query(
            _request(
                HISTORY_CAPABILITY_ID,
                {
                    "provider_device_ref": "42",
                    "from": "2026-10-07T00:00:00Z",
                    "to": "2026-10-08T00:00:00Z",
                },
            )
        )
    )
    assert result.status is QueryStatus.MALFORMED_PROVIDER_RESPONSE


def test_an_origin_change_is_refused_before_secret_or_network_use() -> None:
    called = False

    def respond(request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(500)

    result = (
        _plugin(respond)
        .request_handler_for(HEALTH_CAPABILITY_ID)
        .query(
            _request(
                HEALTH_CAPABILITY_ID,
                {},
                config=_config(base_url="http://attacker.invalid:8082"),
            )
        )
    )
    assert result.status is QueryStatus.INVALID_QUERY
    assert called is False
