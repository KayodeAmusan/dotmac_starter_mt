"""Persistence-free execution of the SPI 1.6 REQUEST contract.

The capability id selects one domain-owned operation. The owning application's
``command_schema`` bounds its input and ``observation_schema`` defines its
normalized output. Connector code receives no arbitrary URL, path, method or
headers from a product caller.

Expected provider failures cross as :class:`QueryResult`. An unexpected handler
exception is normalized to ``provider_unavailable`` without carrying provider
or secret text. The module retries only ``provider_unavailable`` and ``timeout``
under a small immutable execution policy; factory/configuration failures remain
refusals because retrying the same malformed composition cannot make it healthy.
"""

from __future__ import annotations

import math
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Final
from uuid import UUID

from dotmac_integration.admission import (
    AdmissionDecision,
    admit_installation,
    admit_runtime,
)
from dotmac_integration.capability_registry import (
    CapabilityPayloadRejected,
    CapabilityRegistry,
    require_declared_for_binding,
)
from dotmac_integration.discovery import ConnectorRegistry
from dotmac_integration.models import (
    CapabilityBinding,
    ConnectorConfigRevision,
    ConnectorInstallation,
)
from dotmac_integration.policy import DEFAULT_POLICY, ExecutionPolicy
from dotmac_integration.spi import (
    ConnectorMode,
    ConnectorPlugin,
    QueryRequest,
    QueryResult,
    QueryStatus,
    RequestHandler,
    RequestPlugin,
    _freeze_query_mapping,
    _plain_query_value,
    accepts_manifest_digest,
    require_capability_mode,
)

__all__ = [
    "DEFAULT_QUERY_EXECUTION_POLICY",
    "PreparedQuery",
    "QueryExecutionPolicy",
    "QueryInvocationError",
    "QueryNotAdmitted",
    "QueryPreparationError",
    "execute_prepared_query",
    "execute_query",
    "prepare_query",
]


@dataclass(frozen=True, slots=True)
class QueryExecutionPolicy:
    """Bounded module-owned retry policy for safe synchronous reads."""

    max_attempts: int = 2
    base_backoff_seconds: float = 0.1
    max_backoff_seconds: float = 1.0

    def __post_init__(self) -> None:
        if (
            not isinstance(self.max_attempts, int)
            or isinstance(self.max_attempts, bool)
            or not 1 <= self.max_attempts <= 5
        ):
            raise ValueError("max_attempts must be between 1 and 5")
        for name in ("base_backoff_seconds", "max_backoff_seconds"):
            value = getattr(self, name)
            if (
                not isinstance(value, int | float)
                or isinstance(value, bool)
                or not math.isfinite(value)
                or value < 0
            ):
                raise ValueError(f"{name} must be a finite non-negative number")
        if self.base_backoff_seconds > self.max_backoff_seconds:
            raise ValueError(
                "max_backoff_seconds must be at least base_backoff_seconds"
            )

    def retry_delay_seconds(self, attempts_made: int) -> float:
        """Exponential delay after ``attempts_made``, capped by policy."""

        return min(
            self.max_backoff_seconds,
            self.base_backoff_seconds * (2 ** max(attempts_made - 1, 0)),
        )


DEFAULT_QUERY_EXECUTION_POLICY: Final[QueryExecutionPolicy] = QueryExecutionPolicy()


class QueryInvocationError(RuntimeError):
    """The connector composition cannot serve a synchronous request."""


class QueryPreparationError(RuntimeError):
    """The stored binding/configuration cannot serve a synchronous request."""


class QueryNotAdmitted(QueryPreparationError):
    """The runtime or installation deliberately halted REQUEST execution."""

    def __init__(self, decision: AdmissionDecision) -> None:
        super().__init__(decision.detail or decision.reason)
        self.decision = decision

    @property
    def reason(self) -> str:
        return self.decision.reason


@dataclass(frozen=True, slots=True, repr=False)
class PreparedQuery:
    """A detached immutable REQUEST pin with references, never secret values."""

    installation_id: UUID
    binding_id: UUID
    connector_key: str
    capability_id: str
    payload: Mapping[str, object]
    config: Mapping[str, object]
    secret_refs: Mapping[str, object]
    config_revision_id: UUID | None

    def __post_init__(self) -> None:
        for name in ("payload", "config", "secret_refs"):
            object.__setattr__(
                self,
                name,
                _freeze_query_mapping(getattr(self, name), field_name=name),
            )


def prepare_query(
    db: Any,
    capability_binding_id: UUID,
    payload: Mapping[str, object],
    *,
    registry: ConnectorRegistry,
    capability_registry: CapabilityRegistry,
    runtime_policy: ExecutionPolicy = DEFAULT_POLICY,
) -> PreparedQuery:
    """Resolve and pin one enabled REQUEST binding without provider I/O."""

    runtime_admission = admit_runtime(runtime_policy)
    if not runtime_admission.admitted:
        raise QueryNotAdmitted(runtime_admission)

    binding = db.get(CapabilityBinding, capability_binding_id)
    if binding is None:
        raise QueryPreparationError(
            f"capability binding {capability_binding_id} was not found"
        )
    if binding.state != "enabled":
        raise QueryPreparationError(
            f"binding {binding.id} is {binding.state!r}, not enabled"
        )

    installation = db.get(ConnectorInstallation, binding.installation_id)
    if installation is None:
        raise QueryPreparationError(f"binding {binding.id} has no installation")
    installation_admission = admit_installation(db, installation, policy=runtime_policy)
    if not installation_admission.admitted:
        raise QueryNotAdmitted(installation_admission)
    if installation.state != "enabled":
        raise QueryPreparationError(
            f"installation {installation.name!r} is {installation.state!r}, not enabled"
        )

    try:
        registry.require_compatible(installation.connector_key)
        plugin = registry.plugin(installation.connector_key)
    except Exception as exc:
        raise QueryPreparationError(
            f"connector {installation.connector_key!r} is not usable in this "
            f"runtime: {type(exc).__name__}"
        ) from None
    if not accepts_manifest_digest(plugin, installation.manifest_digest):
        raise QueryPreparationError(
            f"installation {installation.name!r} is pinned to a manifest the "
            f"installed connector {installation.connector_key!r} no longer honours"
        )
    try:
        require_declared_for_binding(
            capability_registry,
            capability_id=binding.capability_id,
            connector_key=installation.connector_key,
            manifest=plugin.manifest,
        )
        require_capability_mode(plugin, binding.capability_id, ConnectorMode.REQUEST)
    except Exception as exc:
        raise QueryPreparationError(
            f"binding {binding.id} cannot serve request capability "
            f"{binding.capability_id!r}: {type(exc).__name__}"
        ) from None

    revision = (
        db.get(ConnectorConfigRevision, installation.current_config_revision_id)
        if installation.current_config_revision_id
        else None
    )
    return PreparedQuery(
        installation_id=installation.id,
        binding_id=binding.id,
        connector_key=installation.connector_key,
        capability_id=binding.capability_id,
        payload=dict(payload),
        config=dict((revision.config_json if revision else {}) or {}),
        secret_refs=dict((revision.secret_refs if revision else {}) or {}),
        config_revision_id=revision.id if revision else None,
    )


def _handler_for(plugin: ConnectorPlugin, capability_id: str) -> RequestHandler:
    require_capability_mode(plugin, capability_id, ConnectorMode.REQUEST)
    if not isinstance(plugin, RequestPlugin):  # pragma: no cover - defensive
        raise QueryInvocationError("the connector has no request factory")
    try:
        handler = plugin.request_handler_for(capability_id)
    except Exception as exc:
        raise QueryInvocationError(
            "the request factory raised "
            f"{type(exc).__name__}; connector logs carry the detail"
        ) from None
    if not isinstance(handler, RequestHandler):
        raise QueryInvocationError(
            "the request factory returned a handler of the wrong shape"
        )
    return handler


def execute_query(
    plugin: ConnectorPlugin,
    request: QueryRequest,
    *,
    registry: CapabilityRegistry,
    policy: QueryExecutionPolicy = DEFAULT_QUERY_EXECUTION_POLICY,
    sleeper: Callable[[float], object] = time.sleep,
) -> QueryResult:
    """Validate, invoke within a bounded retry policy, then validate output.

    The module owns general retry and retries only read-safe transient outcomes.
    A connector may additionally perform exactly one bounded 401/403
    re-authentication-and-replay inside a single handler attempt; an
    ``unauthorized_provider_session`` returned after that is final here.
    """

    contract = registry.get(request.capability_id)
    try:
        contract.require_request(_plain_query_value(request.payload))
    except CapabilityPayloadRejected:
        return QueryResult(status=QueryStatus.INVALID_QUERY)

    handler = _handler_for(plugin, request.capability_id)
    retryable = frozenset({QueryStatus.PROVIDER_UNAVAILABLE, QueryStatus.TIMEOUT})
    for attempts_made in range(1, policy.max_attempts + 1):
        try:
            result = handler.query(request)
        except Exception:
            result = QueryResult(status=QueryStatus.PROVIDER_UNAVAILABLE)

        if not isinstance(result, QueryResult):
            return QueryResult(status=QueryStatus.MALFORMED_PROVIDER_RESPONSE)
        if result.status is QueryStatus.SUCCEEDED:
            try:
                contract.require_observation(_plain_query_value(result.observation))
            except CapabilityPayloadRejected:
                return QueryResult(status=QueryStatus.MALFORMED_PROVIDER_RESPONSE)
            return result
        if result.status not in retryable or attempts_made >= policy.max_attempts:
            return result
        sleeper(policy.retry_delay_seconds(attempts_made))

    raise AssertionError("bounded query attempt loop was empty")  # pragma: no cover


def execute_prepared_query(
    prepared: PreparedQuery,
    *,
    registry: ConnectorRegistry,
    capability_registry: CapabilityRegistry,
    resolve_secrets: Callable[[Mapping[str, object]], Mapping[str, object]],
    policy: QueryExecutionPolicy = DEFAULT_QUERY_EXECUTION_POLICY,
    sleeper: Callable[[float], object] = time.sleep,
) -> QueryResult:
    """Materialize references after DB close, then execute the pinned query."""

    contract = capability_registry.get(prepared.capability_id)
    try:
        contract.require_request(_plain_query_value(prepared.payload))
    except CapabilityPayloadRejected:
        return QueryResult(status=QueryStatus.INVALID_QUERY)

    try:
        secrets = resolve_secrets(prepared.secret_refs)
    except Exception as exc:
        raise QueryInvocationError(
            "the query secret resolver raised "
            f"{type(exc).__name__}; deployment logs carry the detail"
        ) from None
    request = QueryRequest(
        installation_id=prepared.installation_id,
        capability_id=prepared.capability_id,
        payload=prepared.payload,
        config=prepared.config,
        secrets=secrets,
    )
    try:
        plugin = registry.plugin(prepared.connector_key)
    except Exception as exc:
        raise QueryInvocationError(
            f"the prepared query connector is unavailable: {type(exc).__name__}"
        ) from None
    return execute_query(
        plugin,
        request,
        registry=capability_registry,
        policy=policy,
        sleeper=sleeper,
    )
