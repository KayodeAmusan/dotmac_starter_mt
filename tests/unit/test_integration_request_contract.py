"""SPI 1.6 REQUEST mode: bounded, typed, provider-neutral reads."""

from __future__ import annotations

import dataclasses
import traceback
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from dotmac_integration.capability_registry import (
    CapabilityContract,
    CapabilityOwner,
    CapabilityPayloadRejected,
    CapabilityRegistry,
)
from dotmac_integration.conformance import FakePlugin, fake_manifest, fake_plugin
from dotmac_integration.discovery import ConnectorRegistry
from dotmac_integration.models import (
    CapabilityBinding,
    ConnectorConfigRevision,
    ConnectorInstallation,
)
from dotmac_integration.policy import ExecutionPolicy
from dotmac_integration.query_contract import (
    PreparedQuery,
    QueryExecutionPolicy,
    QueryInvocationError,
    QueryNotAdmitted,
    QueryPreparationError,
    execute_prepared_query,
    execute_query,
    prepare_query,
)
from dotmac_integration.spi import ConnectorMode, QueryRequest, QueryResult, QueryStatus
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

CAPABILITY = "fleet.tracking.position.history.v1"
SECRET = "QUERY-SECRET-SENTINEL-8c22b2"


def _contract() -> CapabilityContract:
    return CapabilityContract(
        capability_id=CAPABILITY,
        owner=CapabilityOwner(application="dotmac_erp", module="fleet"),
        summary="read a bounded normalized vehicle position history",
        command_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["tracker_ref", "lookback_seconds", "limit"],
            "properties": {
                "tracker_ref": {"type": "string", "minLength": 1},
                "lookback_seconds": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 604800,
                },
                "limit": {"type": "integer", "minimum": 1, "maximum": 1000},
            },
        },
        observation_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["positions"],
            "properties": {
                "positions": {
                    "type": "array",
                    "maxItems": 1000,
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["latitude", "longitude"],
                        "properties": {
                            "latitude": {"type": "number"},
                            "longitude": {"type": "number"},
                        },
                    },
                }
            },
        },
    )


def _request(**payload: object) -> QueryRequest:
    values: dict[str, object] = {
        "tracker_ref": "tracker-42",
        "lookback_seconds": 3600,
        "limit": 100,
    }
    values.update(payload)
    return QueryRequest(
        installation_id=uuid4(),
        capability_id=CAPABILITY,
        payload=values,
        config={"base_url": "https://tracking.invalid"},
        secrets={"service_password": SECRET},
    )


def _plugin(*, result: QueryResult | None = None, **knobs: object):
    contract = _contract()
    manifest = fake_manifest(
        capabilities=(CAPABILITY,),
        claims_contract_digest=contract.contract_digest,
    )
    return fake_plugin(
        manifest_=manifest,
        modes_=frozenset({ConnectorMode.REQUEST}),
        query_result=result
        or QueryResult(
            status=QueryStatus.SUCCEEDED,
            observation={"positions": [{"latitude": 9.0, "longitude": 7.0}]},
        ),
        **knobs,
    )


@pytest.fixture()
def engine() -> Engine:
    value = create_engine(
        "sqlite:///:memory:",
        execution_options={"schema_translate_map": {"mod_intg": None}},
    )
    for model in (ConnectorInstallation, ConnectorConfigRevision, CapabilityBinding):
        cast(Any, model.__table__).create(value)
    return value


def _seed_binding(
    engine: Engine,
    *,
    plugin: FakePlugin,
    binding_state: str = "enabled",
    installation_state: str = "enabled",
    manifest_digest: str | None = None,
    name: str = "query-source",
    capability_id: str = CAPABILITY,
) -> tuple[ConnectorRegistry, UUID]:
    with Session(engine) as db:
        installation = ConnectorInstallation(
            id=uuid4(),
            connector_key=plugin.manifest.connector_key,
            connector_version=plugin.manifest.version,
            spi_range=str(plugin.manifest.spi_range),
            manifest_digest=manifest_digest or plugin.manifest.digest,
            name=name,
            state=installation_state,
        )
        db.add(installation)
        db.flush()
        revision = ConnectorConfigRevision(
            id=uuid4(),
            installation_id=installation.id,
            revision=1,
            schema_version="1",
            config_digest="q" * 64,
            config_json={"base_url": "https://tracking.invalid"},
            secret_refs={"service_password": "file:///run/secrets/traccar_password"},
        )
        db.add(revision)
        db.flush()
        installation.current_config_revision_id = revision.id
        binding = CapabilityBinding(
            id=uuid4(),
            installation_id=installation.id,
            capability_id=capability_id,
            state=binding_state,
        )
        db.add(binding)
        db.commit()
        return ConnectorRegistry((plugin,)), binding.id


def test_request_is_deeply_immutable_and_repr_hides_material() -> None:
    payload = {"tracker_ref": "tracker-42", "lookback_seconds": 60, "limit": 1}
    config: dict[str, object] = {"nested": {"headers": ["safe"]}}
    secrets = {"service_password": SECRET}
    request = QueryRequest(
        installation_id=uuid4(),
        capability_id=CAPABILITY,
        payload=payload,
        config=config,
        secrets=secrets,
    )
    payload["limit"] = 999
    nested = config["nested"]
    assert isinstance(nested, dict)
    headers = nested["headers"]
    assert isinstance(headers, list)
    headers.append(SECRET)
    secrets["service_password"] = "changed"
    assert request.payload["limit"] == 1
    assert request.config["nested"] == {"headers": ("safe",)}
    assert request.secrets["service_password"] == SECRET
    assert SECRET not in repr(request)
    assert "tracking.invalid" not in repr(request)
    with pytest.raises(TypeError):
        request.payload["path"] = "/api/raw"  # type: ignore[index]
    with pytest.raises(dataclasses.FrozenInstanceError):
        request.capability_id = "other.read.v1"  # type: ignore[misc]


def test_request_has_no_transport_passthrough_surface() -> None:
    fields = {field.name for field in dataclasses.fields(QueryRequest)}
    assert fields == {
        "installation_id",
        "capability_id",
        "payload",
        "config",
        "secrets",
    }
    assert not fields.intersection({"url", "path", "method", "headers"})


@pytest.mark.parametrize(
    "status",
    [
        QueryStatus.PROVIDER_UNAVAILABLE,
        QueryStatus.UNAUTHORIZED_PROVIDER_SESSION,
        QueryStatus.NOT_FOUND,
        QueryStatus.INVALID_QUERY,
        QueryStatus.TIMEOUT,
        QueryStatus.MALFORMED_PROVIDER_RESPONSE,
    ],
)
def test_failure_results_are_closed_and_carry_no_provider_body(
    status: QueryStatus,
) -> None:
    assert QueryResult(status=status).observation is None
    with pytest.raises(ValueError, match="failure result cannot carry"):
        QueryResult(status=status, observation={"raw": SECRET})


def test_success_requires_a_normalized_observation() -> None:
    with pytest.raises(ValueError, match="successful query requires"):
        QueryResult(status=QueryStatus.SUCCEEDED)


def test_schema_bounds_refuse_before_connector_invocation() -> None:
    plugin = _plugin()
    result = execute_query(
        plugin,
        _request(lookback_seconds=604801),
        registry=CapabilityRegistry((_contract(),)),
    )
    assert result == QueryResult(status=QueryStatus.INVALID_QUERY)
    assert plugin.query_requests_seen == []


def test_prepared_invalid_query_refuses_before_secret_materialization(
    engine: Engine,
) -> None:
    plugin = _plugin()
    registry, binding_id = _seed_binding(engine, plugin=plugin)
    with Session(engine) as db:
        prepared = prepare_query(
            db,
            binding_id,
            {"tracker_ref": "tracker-42", "lookback_seconds": 604801, "limit": 1},
            registry=registry,
            capability_registry=CapabilityRegistry((_contract(),)),
        )
    resolver_calls: list[object] = []
    result = execute_prepared_query(
        prepared,
        registry=registry,
        capability_registry=CapabilityRegistry((_contract(),)),
        resolve_secrets=lambda refs: resolver_calls.append(refs) or {},
    )
    assert result == QueryResult(status=QueryStatus.INVALID_QUERY)
    assert resolver_calls == []
    assert plugin.query_requests_seen == []


def test_prepare_query_captures_current_pin_without_holding_a_session(
    engine: Engine,
) -> None:
    plugin = _plugin()
    registry, binding_id = _seed_binding(engine, plugin=plugin)
    with Session(engine) as db:
        prepared = prepare_query(
            db,
            binding_id,
            {"tracker_ref": "tracker-42", "lookback_seconds": 60, "limit": 1},
            registry=registry,
            capability_registry=CapabilityRegistry((_contract(),)),
        )
    assert isinstance(prepared, PreparedQuery)
    assert prepared.binding_id == binding_id
    assert prepared.connector_key == plugin.manifest.connector_key
    assert prepared.config == {"base_url": "https://tracking.invalid"}
    assert prepared.secret_refs == {
        "service_password": "file:///run/secrets/traccar_password"
    }
    assert prepared.config_revision_id is not None

    seen_refs: list[object] = []

    def resolve(refs):
        seen_refs.append(refs)
        return {"service_password": SECRET}

    result = execute_prepared_query(
        prepared,
        registry=registry,
        capability_registry=CapabilityRegistry((_contract(),)),
        resolve_secrets=resolve,
        policy=QueryExecutionPolicy(max_attempts=1),
    )
    assert result.status is QueryStatus.SUCCEEDED
    assert seen_refs == [prepared.secret_refs]
    assert plugin.query_requests_seen[-1].secrets["service_password"] == SECRET


@pytest.mark.parametrize(
    ("binding_state", "installation_state", "message"),
    [
        ("disabled", "enabled", "not enabled"),
        ("enabled", "disabled", "not enabled"),
    ],
)
def test_prepare_query_refuses_disabled_control_plane_rows(
    engine: Engine,
    binding_state: str,
    installation_state: str,
    message: str,
) -> None:
    plugin = _plugin()
    registry, binding_id = _seed_binding(
        engine,
        plugin=plugin,
        binding_state=binding_state,
        installation_state=installation_state,
    )
    with Session(engine) as db, pytest.raises(QueryPreparationError, match=message):
        prepare_query(
            db,
            binding_id,
            _request().payload,
            registry=registry,
            capability_registry=CapabilityRegistry((_contract(),)),
        )


def test_prepare_query_obeys_runtime_halt_and_installation_quarantine(
    engine: Engine,
) -> None:
    plugin = _plugin()
    registry, binding_id = _seed_binding(engine, plugin=plugin)
    with (
        Session(engine) as db,
        pytest.raises(QueryNotAdmitted, match="dispatch is halted"),
    ):
        prepare_query(
            db,
            binding_id,
            _request().payload,
            registry=registry,
            capability_registry=CapabilityRegistry((_contract(),)),
            runtime_policy=ExecutionPolicy(dispatch_enabled=False),
        )

    quarantined_registry, quarantined_binding_id = _seed_binding(
        engine,
        plugin=plugin,
        installation_state="quarantined",
        name="query-source-quarantined",
    )
    with Session(engine) as db, pytest.raises(QueryNotAdmitted, match="quarantined"):
        prepare_query(
            db,
            quarantined_binding_id,
            _request().payload,
            registry=quarantined_registry,
            capability_registry=CapabilityRegistry((_contract(),)),
        )


def test_prepare_query_refuses_missing_binding_or_installation(engine: Engine) -> None:
    plugin = _plugin()
    registry = ConnectorRegistry((plugin,))
    with Session(engine) as db, pytest.raises(QueryPreparationError, match="not found"):
        prepare_query(
            db,
            uuid4(),
            _request().payload,
            registry=registry,
            capability_registry=CapabilityRegistry((_contract(),)),
        )

    registry, binding_id = _seed_binding(engine, plugin=plugin)
    with Session(engine) as db:
        binding = db.get(CapabilityBinding, binding_id)
        assert binding is not None
        installation = db.get(ConnectorInstallation, binding.installation_id)
        assert installation is not None
        db.delete(installation)
        db.commit()
    with (
        Session(engine) as db,
        pytest.raises(QueryPreparationError, match="has no installation"),
    ):
        prepare_query(
            db,
            binding_id,
            _request().payload,
            registry=registry,
            capability_registry=CapabilityRegistry((_contract(),)),
        )


def test_prepare_query_refuses_manifest_pin_or_request_mode_drift(
    engine: Engine,
) -> None:
    plugin = _plugin()
    registry, binding_id = _seed_binding(
        engine, plugin=plugin, manifest_digest="f" * 64
    )
    with Session(engine) as db, pytest.raises(QueryPreparationError, match="pinned"):
        prepare_query(
            db,
            binding_id,
            _request().payload,
            registry=registry,
            capability_registry=CapabilityRegistry((_contract(),)),
        )

    wrong_mode = fake_plugin(
        manifest_=plugin.manifest,
        modes_=frozenset({ConnectorMode.DELIVERY}),
    )
    wrong_registry, wrong_binding_id = _seed_binding(
        engine, plugin=wrong_mode, name="query-source-wrong-mode"
    )
    with Session(engine) as db, pytest.raises(QueryPreparationError, match="request"):
        prepare_query(
            db,
            wrong_binding_id,
            _request().payload,
            registry=wrong_registry,
            capability_registry=CapabilityRegistry((_contract(),)),
        )


def test_prepare_query_refuses_a_capability_outside_the_owned_contract(
    engine: Engine,
) -> None:
    plugin = _plugin()
    registry, binding_id = _seed_binding(
        engine,
        plugin=plugin,
        capability_id="fleet.tracking.unknown.v1",
    )
    with (
        Session(engine) as db,
        pytest.raises(QueryPreparationError, match="cannot serve request capability"),
    ):
        prepare_query(
            db,
            binding_id,
            _request().payload,
            registry=registry,
            capability_registry=CapabilityRegistry((_contract(),)),
        )


def test_successful_query_uses_one_opaque_installation_key_and_normalizes() -> None:
    plugin = _plugin()
    request = _request()
    result = execute_query(plugin, request, registry=CapabilityRegistry((_contract(),)))
    assert result.status is QueryStatus.SUCCEEDED
    assert result.observation == {"positions": ({"latitude": 9.0, "longitude": 7.0},)}
    assert plugin.query_requests_seen == [request]
    assert plugin.query_requests_seen[0].installation_id == request.installation_id


def test_malformed_normalized_observation_becomes_a_closed_failure() -> None:
    plugin = _plugin(
        result=QueryResult(
            status=QueryStatus.SUCCEEDED,
            observation={"positions": [{"latitude": "provider-text", "longitude": 7}]},
        )
    )
    result = execute_query(
        plugin, _request(), registry=CapabilityRegistry((_contract(),))
    )
    assert result == QueryResult(status=QueryStatus.MALFORMED_PROVIDER_RESPONSE)


def test_handler_exception_is_sanitized_to_provider_unavailable() -> None:
    plugin = _plugin(query_raises=RuntimeError(SECRET))
    result = execute_query(
        plugin, _request(), registry=CapabilityRegistry((_contract(),))
    )
    assert result == QueryResult(status=QueryStatus.PROVIDER_UNAVAILABLE)
    assert SECRET not in repr(result)


@pytest.mark.parametrize(
    "retry_status",
    [QueryStatus.PROVIDER_UNAVAILABLE, QueryStatus.TIMEOUT],
)
def test_only_safe_transient_results_retry_with_bounded_backoff(
    retry_status: QueryStatus,
) -> None:
    plugin = _plugin(result=QueryResult(status=retry_status))
    sleeps: list[float] = []
    result = execute_query(
        plugin,
        _request(),
        registry=CapabilityRegistry((_contract(),)),
        policy=QueryExecutionPolicy(
            max_attempts=3,
            base_backoff_seconds=0.25,
            max_backoff_seconds=1.0,
        ),
        sleeper=sleeps.append,
    )
    assert result == QueryResult(status=retry_status)
    assert len(plugin.query_requests_seen) == 3
    assert sleeps == [0.25, 0.5]


@pytest.mark.parametrize(
    "final_status",
    [
        QueryStatus.UNAUTHORIZED_PROVIDER_SESSION,
        QueryStatus.NOT_FOUND,
        QueryStatus.INVALID_QUERY,
        QueryStatus.MALFORMED_PROVIDER_RESPONSE,
    ],
)
def test_non_transient_results_are_never_retried(final_status: QueryStatus) -> None:
    plugin = _plugin(result=QueryResult(status=final_status))
    sleeps: list[float] = []
    result = execute_query(
        plugin,
        _request(),
        registry=CapabilityRegistry((_contract(),)),
        policy=QueryExecutionPolicy(max_attempts=3),
        sleeper=sleeps.append,
    )
    assert result == QueryResult(status=final_status)
    assert len(plugin.query_requests_seen) == 1
    assert sleeps == []


def test_query_retry_policy_refuses_unbounded_or_invalid_limits() -> None:
    with pytest.raises(ValueError, match="max_attempts must be between 1 and 5"):
        QueryExecutionPolicy(max_attempts=0)
    with pytest.raises(ValueError, match="max_attempts must be between 1 and 5"):
        QueryExecutionPolicy(max_attempts=6)
    with pytest.raises(ValueError, match="base_backoff_seconds"):
        QueryExecutionPolicy(base_backoff_seconds=-0.1)
    with pytest.raises(ValueError, match="max_backoff_seconds"):
        QueryExecutionPolicy(base_backoff_seconds=2.0, max_backoff_seconds=1.0)


def test_unexpected_handler_exception_uses_same_bounded_retry_owner() -> None:
    plugin = _plugin(query_raises=RuntimeError(SECRET))
    sleeps: list[float] = []
    result = execute_query(
        plugin,
        _request(),
        registry=CapabilityRegistry((_contract(),)),
        policy=QueryExecutionPolicy(max_attempts=2, base_backoff_seconds=0.1),
        sleeper=sleeps.append,
    )
    assert result == QueryResult(status=QueryStatus.PROVIDER_UNAVAILABLE)
    assert len(plugin.query_requests_seen) == 2
    assert sleeps == [0.1]


def test_factory_exception_never_leaks_connector_material() -> None:
    plugin = _plugin(query_factory_raises=RuntimeError(SECRET))
    with pytest.raises(QueryInvocationError) as excinfo:
        execute_query(plugin, _request(), registry=CapabilityRegistry((_contract(),)))
    rendered = "".join(
        traceback.format_exception(
            type(excinfo.value), excinfo.value, excinfo.value.__traceback__
        )
    )
    assert SECRET not in str(excinfo.value)
    assert SECRET not in repr(excinfo.value)
    assert SECRET not in rendered
    assert excinfo.value.__cause__ is None


def test_domain_payload_error_remains_available_to_direct_contract_callers() -> None:
    with pytest.raises(CapabilityPayloadRejected, match="request rejected"):
        _contract().require_request(
            {"tracker_ref": "x", "lookback_seconds": 0, "limit": 1}
        )
