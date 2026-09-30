"""Persistence-free execution of the SPI 1.5 provisioning contract.

This module is intentionally smaller than a provisioning engine. It proves the
provider-neutral call boundary while leaving durable operations, leasing,
retry, reconciliation and migration ownership to a later allocated slice.

The product owns desired state and the ordered plan. The connector can accept
that plan and execute its steps, but cannot insert, remove, reorder or rewrite
them. The Integrator owns this refusal because it is the only party that sees
both sides of the transport boundary.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable

from dotmac_integration.spi import (
    ConnectorMode,
    ConnectorPlugin,
    ProvisionApplyRequest,
    ProvisionCancelRequest,
    ProvisioningHandler,
    ProvisioningResult,
    ProvisionObserveRequest,
    ProvisionPlanRequest,
    ProvisionPlanResult,
    ProvisionPlugin,
    ProvisionResultStatus,
    ProvisionStep,
    _provision_steps_digest,
    require_capability_mode,
)

__all__ = [
    "ProvisionHandlerRaised",
    "ProvisionInvocationError",
    "ProvisionPlanRewritten",
    "ProvisionResultInvalid",
    "apply_provisioning",
    "cancel_provisioning",
    "observe_provisioning",
    "plan_provisioning",
    "provision_plan_hash",
]


class ProvisionInvocationError(RuntimeError):
    """The provisioning boundary refused an invocation."""


class ProvisionPlanRewritten(ProvisionInvocationError):
    """A connector returned a plan other than the one the owner authored."""


class ProvisionHandlerRaised(ProvisionInvocationError):
    """Connector code raised; its message is withheld as possible material."""


class ProvisionResultInvalid(ProvisionInvocationError):
    """A connector returned a value outside the typed result contract."""


def provision_plan_hash(steps: Iterable[ProvisionStep]) -> str:
    """Canonical identity of the complete ordered plan, excluding secrets."""
    return _provision_steps_digest(steps)


def _handler_for(plugin: ConnectorPlugin, capability_id: str) -> ProvisioningHandler:
    require_capability_mode(plugin, capability_id, ConnectorMode.PROVISION)
    # `require_capability_mode` proves the protocol structurally. Keep the
    # explicit isinstance so a caller that bypassed discovery still fails here
    # before connector code is invoked.
    if not isinstance(plugin, ProvisionPlugin):  # pragma: no cover - defensive
        raise ProvisionResultInvalid("the connector has no provisioning factory")
    try:
        handler = plugin.provisioning_handler_for(capability_id)
    except Exception as exc:
        raise ProvisionHandlerRaised(
            "the provisioning factory raised "
            f"{type(exc).__name__}; connector logs carry the detail"
        ) from None
    if not isinstance(handler, ProvisioningHandler):
        raise ProvisionResultInvalid(
            "the provisioning factory returned a handler of the wrong shape"
        )
    return handler


def _invoke(operation: str, call: Callable[[], object]) -> object:
    try:
        return call()
    except ProvisionInvocationError:
        raise
    except Exception as exc:
        raise ProvisionHandlerRaised(
            f"provisioning {operation} raised {type(exc).__name__}; connector "
            "logs carry the detail"
        ) from None


def plan_provisioning(
    plugin: ConnectorPlugin, request: ProvisionPlanRequest
) -> ProvisionPlanResult:
    """Validate and invoke ``plan`` while forbidding connector-authored drift."""
    expected_hash = request._original_plan_hash
    if (
        request.plan_hash != expected_hash
        or provision_plan_hash(request.steps) != expected_hash
    ):
        raise ProvisionPlanRewritten(
            "the supplied plan_hash does not identify the supplied ordered steps"
        )
    handler = _handler_for(plugin, request.capability_id)
    result = _invoke("plan", lambda: handler.plan(request))
    if not isinstance(result, ProvisionPlanResult):
        raise ProvisionResultInvalid("provisioning plan returned the wrong type")
    if (
        result.plan_hash != expected_hash
        or provision_plan_hash(result.steps) != expected_hash
    ):
        raise ProvisionPlanRewritten(
            "a connector may validate an owner-authored plan but may not rewrite it"
        )
    return result


def _require_result(operation: str, result: object) -> ProvisioningResult:
    if not isinstance(result, ProvisioningResult):
        raise ProvisionResultInvalid(
            f"provisioning {operation} returned the wrong result type"
        )
    if not isinstance(result.status, ProvisionResultStatus):
        raise ProvisionResultInvalid(
            f"provisioning {operation} returned an invalid result status"
        )
    return result


def apply_provisioning(
    plugin: ConnectorPlugin, request: ProvisionApplyRequest
) -> ProvisioningResult:
    handler = _handler_for(plugin, request.capability_id)
    return _require_result("apply", _invoke("apply", lambda: handler.apply(request)))


def observe_provisioning(
    plugin: ConnectorPlugin, request: ProvisionObserveRequest
) -> ProvisioningResult:
    handler = _handler_for(plugin, request.capability_id)
    return _require_result(
        "observe", _invoke("observe", lambda: handler.observe(request))
    )


def cancel_provisioning(
    plugin: ConnectorPlugin, request: ProvisionCancelRequest
) -> ProvisioningResult:
    handler = _handler_for(plugin, request.capability_id)
    return _require_result("cancel", _invoke("cancel", lambda: handler.cancel(request)))
