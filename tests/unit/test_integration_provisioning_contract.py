"""SPI 1.5 provisioning contract — provider-neutral and persistence-free."""

from __future__ import annotations

import ast
import dataclasses
import traceback
from pathlib import Path

import pytest
from dotmac_integration.conformance import FakePlugin, fake_manifest, fake_plugin
from dotmac_integration.provision_contract import (
    ProvisionHandlerRaised,
    ProvisionPlanRewritten,
    ProvisionResultInvalid,
    apply_provisioning,
    cancel_provisioning,
    observe_provisioning,
    plan_provisioning,
    provision_plan_hash,
)
from dotmac_integration.spi import (
    CURRENT_SPI_VERSION,
    MODE_PROTOCOLS,
    ConnectorMode,
    ProvisionApplyRequest,
    ProvisionCancelRequest,
    ProvisionContractError,
    ProvisioningHandler,
    ProvisioningResult,
    ProvisionObserveRequest,
    ProvisionPlanRequest,
    ProvisionPlanResult,
    ProvisionPlugin,
    ProvisionResultStatus,
    ProvisionStep,
    SpiVersion,
    verify_plugin_modes,
)


def test_spi_1_6_preserves_provision_and_adds_one_closed_request_mode() -> None:
    assert CURRENT_SPI_VERSION == SpiVersion(1, 6)
    assert set(ConnectorMode) == {
        ConnectorMode.INGRESS,
        ConnectorMode.POLL,
        ConnectorMode.DELIVERY,
        ConnectorMode.PROVISION,
        ConnectorMode.REQUEST,
    }
    contract = MODE_PROTOCOLS[ConnectorMode.PROVISION]
    assert contract.plugin_protocol is ProvisionPlugin
    assert contract.factory == "provisioning_handler_for"
    assert contract.handler_protocol is ProvisioningHandler


def test_provider_free_fake_exercises_all_provision_operations() -> None:
    plugin = fake_plugin()
    capability_id = plugin.manifest.capabilities[0].capability_id
    handler = plugin.provisioning_handler_for(capability_id)
    step = ProvisionStep(
        step_key="mailbox",
        endpoint_code="mailbox.apply",
        depends_on=(),
        input={"mailbox_ref": "mbx-1"},
    )
    plan = ProvisionPlanRequest(
        capability_id=plugin.manifest.capabilities[0].capability_id,
        command_id="cmd-1",
        plan_hash="a" * 64,
        steps=(step,),
        config={"region": "ng"},
        secrets={"api": "material"},
    )
    assert handler.plan(plan) == ProvisionPlanResult(
        plan_hash=plan.plan_hash,
        steps=plan.steps,
    )

    apply = ProvisionApplyRequest(
        capability_id=plan.capability_id,
        command_id=plan.command_id,
        operation_ref="op-1",
        plan_hash=plan.plan_hash,
        step=step,
        config=plan.config,
        secrets=plan.secrets,
        idempotency_key="idem-1",
    )
    observe = ProvisionObserveRequest(
        capability_id=plan.capability_id,
        command_id=plan.command_id,
        operation_ref="op-1",
        plan_hash=plan.plan_hash,
        step_key=step.step_key,
        provider_operation_ref="provider-op-1",
        target={"mailbox_ref": "mbx-1"},
        config=plan.config,
        secrets=plan.secrets,
    )
    cancel = ProvisionCancelRequest(
        capability_id=plan.capability_id,
        command_id=plan.command_id,
        operation_ref="op-1",
        plan_hash=plan.plan_hash,
        step_key=step.step_key,
        provider_operation_ref="provider-op-1",
        target={"mailbox_ref": "mbx-1"},
        reason="owner withdrew intent",
        idempotency_key="idem-cancel-1",
        config=plan.config,
        secrets=plan.secrets,
    )
    expected = ProvisioningResult(status=ProvisionResultStatus.SUCCEEDED)
    assert handler.apply(apply) == expected
    assert handler.observe(observe) == expected
    assert handler.cancel(cancel) == expected
    assert plugin.provision_requests_seen == [plan, apply, observe, cancel]


def test_provision_request_material_is_hidden_and_immutable() -> None:
    supplied = {"token": "material"}
    request = ProvisionPlanRequest(
        capability_id="managed.resource.v1",
        command_id="cmd-1",
        plan_hash="a" * 64,
        steps=(),
        secrets=supplied,
    )
    supplied["token"] = "changed"
    assert request.secrets["token"] == "material"
    assert "material" not in repr(request)
    with pytest.raises(TypeError):
        request.secrets["token"] = "changed"  # type: ignore[index]
    with pytest.raises(dataclasses.FrozenInstanceError):
        request.command_id = "changed"  # type: ignore[misc]


def test_default_fake_really_conforms_to_the_new_mode() -> None:
    plugin = fake_plugin(manifest_=fake_manifest())
    verify_plugin_modes(plugin)
    assert isinstance(plugin, ProvisionPlugin)


def test_integrator_invokes_the_exact_owner_authored_plan() -> None:
    plugin = fake_plugin()
    step = ProvisionStep(
        step_key="domain",
        endpoint_code="domain.apply",
        input={"domain_ref": "domain-1"},
    )
    request = ProvisionPlanRequest(
        capability_id=plugin.manifest.capabilities[0].capability_id,
        command_id="cmd-1",
        plan_hash=provision_plan_hash((step,)),
        steps=(step,),
    )
    assert plan_provisioning(plugin, request).steps == (step,)


def test_plan_hash_is_a_pinned_byte_contract() -> None:
    step = ProvisionStep(
        step_key="domain",
        endpoint_code="domain.apply",
        input={"domain_ref": "domain-1"},
    )
    assert provision_plan_hash((step,)) == (
        "ae1848b9852d05a6276f64b9b62234b312419d39a7fe2dba50b419f8d9a4ceb8"
    )


def test_plan_hash_mismatch_refuses_before_connector_code_runs() -> None:
    plugin = fake_plugin()
    step = ProvisionStep(step_key="domain", endpoint_code="domain.apply")
    request = ProvisionPlanRequest(
        capability_id=plugin.manifest.capabilities[0].capability_id,
        command_id="cmd-1",
        plan_hash="b" * 64,
        steps=(step,),
    )
    with pytest.raises(ProvisionPlanRewritten, match="does not identify"):
        plan_provisioning(plugin, request)
    assert plugin.provision_requests_seen == []


def test_connector_cannot_rewrite_the_owner_plan() -> None:
    original = ProvisionStep(step_key="domain", endpoint_code="domain.apply")
    inserted = ProvisionStep(step_key="extra", endpoint_code="extra.apply")
    plan_hash = provision_plan_hash((original,))
    plugin = fake_plugin(
        provision_plan_result=ProvisionPlanResult(
            plan_hash=plan_hash,
            steps=(original, inserted),
        )
    )
    request = ProvisionPlanRequest(
        capability_id=plugin.manifest.capabilities[0].capability_id,
        command_id="cmd-1",
        plan_hash=plan_hash,
        steps=(original,),
    )
    with pytest.raises(ProvisionPlanRewritten, match="may not rewrite"):
        plan_provisioning(plugin, request)


@pytest.mark.parametrize("mutation", ["steps", "input"])
def test_handler_cannot_make_a_rewritten_plan_look_like_the_request(
    mutation: str,
) -> None:
    step = ProvisionStep(
        step_key="domain", endpoint_code="domain.apply", input={"nested": ["original"]}
    )

    class HostilePlugin(FakePlugin):
        def provisioning_handler_for(self, capability_id: str) -> ProvisioningHandler:
            ordinary = super().provisioning_handler_for(capability_id)

            class Handler:
                def plan(self, supplied: ProvisionPlanRequest) -> ProvisionPlanResult:
                    if mutation == "steps":
                        changed = ProvisionStep(
                            step_key="extra", endpoint_code="extra.apply"
                        )
                        object.__setattr__(
                            supplied, "steps", (*supplied.steps, changed)
                        )
                    else:
                        with pytest.raises(TypeError):
                            supplied.steps[0].input["nested"][0] = "changed"  # type: ignore[index]
                        changed = ProvisionStep(
                            step_key="domain",
                            endpoint_code="domain.apply",
                            input={"nested": ["changed"]},
                        )
                        object.__setattr__(supplied, "steps", (changed,))
                    return ProvisionPlanResult(
                        plan_hash=supplied.plan_hash, steps=supplied.steps
                    )

                def apply(self, supplied: ProvisionApplyRequest) -> ProvisioningResult:
                    return ordinary.apply(supplied)

                def observe(
                    self, supplied: ProvisionObserveRequest
                ) -> ProvisioningResult:
                    return ordinary.observe(supplied)

                def cancel(
                    self, supplied: ProvisionCancelRequest
                ) -> ProvisioningResult:
                    return ordinary.cancel(supplied)

            return Handler()

    plugin = HostilePlugin()
    request = ProvisionPlanRequest(
        capability_id=plugin.manifest.capabilities[0].capability_id,
        command_id="cmd-1",
        plan_hash=provision_plan_hash((step,)),
        steps=[step],  # type: ignore[arg-type]
    )
    assert isinstance(request.steps, tuple)
    with pytest.raises(ProvisionPlanRewritten, match="may not rewrite"):
        plan_provisioning(plugin, request)


def test_plan_input_is_detached_and_deeply_frozen_at_construction() -> None:
    base = fake_plugin()
    nested = {"entries": [{"name": "original"}]}
    step = ProvisionStep(step_key="domain", endpoint_code="domain.apply", input=nested)
    steps = [step]
    request = ProvisionPlanRequest(
        capability_id=base.manifest.capabilities[0].capability_id,
        command_id="cmd-1",
        plan_hash=provision_plan_hash(steps),
        steps=steps,  # type: ignore[arg-type]
    )
    nested["entries"][0]["name"] = "changed"
    steps.append(ProvisionStep(step_key="extra", endpoint_code="extra.apply"))
    assert request.steps == (step,)
    assert request.steps[0].input["entries"][0]["name"] == "original"  # type: ignore[index]
    with pytest.raises(TypeError):
        request.steps[0].input["entries"][0]["name"] = "changed"  # type: ignore[index]
    assert plan_provisioning(base, request).plan_hash == request.plan_hash


def test_caller_tampering_with_a_step_is_refused_before_the_handler() -> None:
    plugin = fake_plugin()
    step = ProvisionStep(step_key="domain", endpoint_code="domain.apply")
    request = ProvisionPlanRequest(
        capability_id=plugin.manifest.capabilities[0].capability_id,
        command_id="cmd-1",
        plan_hash=provision_plan_hash((step,)),
        steps=(step,),
    )
    object.__setattr__(step, "input", {"changed": True})
    with pytest.raises(ProvisionPlanRewritten, match="does not identify"):
        plan_provisioning(plugin, request)
    assert plugin.provision_requests_seen == []


def test_plan_refuses_mutable_custom_input_without_rendering_its_value() -> None:
    marker = "PRIVATE-MATERIAL-DO-NOT-RENDER"

    class MutableValue:
        def __init__(self) -> None:
            self.value = marker

        def __str__(self) -> str:
            return "stable"

        def __repr__(self) -> str:
            return self.value

    planted = MutableValue()
    with pytest.raises(ProvisionContractError, match="finite JSON values") as excinfo:
        ProvisionStep(
            step_key="domain",
            endpoint_code="domain.apply",
            input={"nested": [planted]},
        )
    planted.value = "changed"
    assert str(planted) == "stable"
    assert marker not in str(excinfo.value)

    plugin = fake_plugin()
    step = ProvisionStep(
        step_key="domain", endpoint_code="domain.apply", input={"nested": ["stable"]}
    )
    request = ProvisionPlanRequest(
        capability_id=plugin.manifest.capabilities[0].capability_id,
        command_id="cmd-1",
        plan_hash=provision_plan_hash((step,)),
        steps=(step,),
    )
    object.__setattr__(step, "input", {"nested": [planted]})
    with pytest.raises(ProvisionContractError, match="finite JSON values"):
        plan_provisioning(plugin, request)
    assert plugin.provision_requests_seen == []

    step = ProvisionStep(step_key="domain", endpoint_code="stable")
    request = ProvisionPlanRequest(
        capability_id=plugin.manifest.capabilities[0].capability_id,
        command_id="cmd-2",
        plan_hash=provision_plan_hash((step,)),
        steps=(step,),
    )
    object.__setattr__(step, "endpoint_code", planted)
    with pytest.raises(ProvisionContractError, match="must be strings"):
        plan_provisioning(plugin, request)
    assert plugin.provision_requests_seen == []


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_plan_refuses_non_finite_numbers(value: float) -> None:
    with pytest.raises(ProvisionContractError, match="finite JSON values"):
        ProvisionStep(
            step_key="domain", endpoint_code="domain.apply", input={"value": value}
        )


def test_plan_refuses_non_string_mapping_keys() -> None:
    with pytest.raises(ProvisionContractError, match="string mapping keys"):
        ProvisionStep(
            step_key="domain",
            endpoint_code="domain.apply",
            input={"nested": {1: "value"}},
        )


def test_plan_step_input_requires_a_mapping() -> None:
    with pytest.raises(ProvisionContractError, match="requires a mapping"):
        ProvisionStep(
            step_key="domain",
            endpoint_code="domain.apply",
            input=["value"],  # type: ignore[arg-type]
        )


@pytest.mark.parametrize("raw_status", ["succeeded", "unknown"])
def test_provisioning_result_requires_status_enum(raw_status: str) -> None:
    with pytest.raises(ProvisionContractError, match="ProvisionResultStatus"):
        ProvisioningResult(status=raw_status)  # type: ignore[arg-type]


@pytest.mark.parametrize("raw_status", ["succeeded", "unknown"])
@pytest.mark.parametrize("operation", ["apply", "observe", "cancel"])
def test_provision_invocation_refuses_forged_string_status(
    raw_status: str, operation: str
) -> None:
    result = ProvisioningResult(status=ProvisionResultStatus.SUCCEEDED)
    object.__setattr__(result, "status", raw_status)
    plugin = fake_plugin(provisioning_result=result)
    step = ProvisionStep(step_key="domain", endpoint_code="domain.apply")
    capability_id = plugin.manifest.capabilities[0].capability_id
    plan_hash = provision_plan_hash((step,))
    request: ProvisionApplyRequest | ProvisionObserveRequest | ProvisionCancelRequest
    if operation == "apply":
        request = ProvisionApplyRequest(
            capability_id=capability_id,
            command_id="cmd-1",
            operation_ref="op-1",
            plan_hash=plan_hash,
            step=step,
            config={},
            secrets={},
            idempotency_key="idem-1",
        )
    elif operation == "observe":
        request = ProvisionObserveRequest(
            capability_id=capability_id,
            command_id="cmd-1",
            operation_ref="op-1",
            plan_hash=plan_hash,
            step_key=step.step_key,
            provider_operation_ref="provider-op-1",
            target={},
            config={},
            secrets={},
        )
    else:
        request = ProvisionCancelRequest(
            capability_id=capability_id,
            command_id="cmd-1",
            operation_ref="op-1",
            plan_hash=plan_hash,
            step_key=step.step_key,
            provider_operation_ref="provider-op-1",
            target={},
            reason="owner withdrew intent",
            idempotency_key="idem-cancel-1",
            config={},
            secrets={},
        )
    with pytest.raises(ProvisionResultInvalid, match="invalid result status"):
        if operation == "apply":
            assert isinstance(request, ProvisionApplyRequest)
            apply_provisioning(plugin, request)
        elif operation == "observe":
            assert isinstance(request, ProvisionObserveRequest)
            observe_provisioning(plugin, request)
        else:
            assert isinstance(request, ProvisionCancelRequest)
            cancel_provisioning(plugin, request)


def test_a_non_provision_connector_is_refused_before_its_factory() -> None:
    plugin = fake_plugin(modes_=frozenset({ConnectorMode.DELIVERY}))
    step = ProvisionStep(step_key="domain", endpoint_code="domain.apply")
    request = ProvisionPlanRequest(
        capability_id=plugin.manifest.capabilities[0].capability_id,
        command_id="cmd-1",
        plan_hash=provision_plan_hash((step,)),
        steps=(step,),
    )
    with pytest.raises(RuntimeError, match="does not declare mode 'provision'"):
        plan_provisioning(plugin, request)
    assert plugin.provision_requests_seen == []


def test_wrong_apply_result_is_refused_at_the_boundary() -> None:
    plugin = fake_plugin(provision_contract_broken=True)
    step = ProvisionStep(step_key="domain", endpoint_code="domain.apply")
    request = ProvisionApplyRequest(
        capability_id=plugin.manifest.capabilities[0].capability_id,
        command_id="cmd-1",
        operation_ref="op-1",
        plan_hash=provision_plan_hash((step,)),
        step=step,
        config={},
        secrets={},
        idempotency_key="idem-1",
    )
    with pytest.raises(ProvisionResultInvalid, match="wrong result type"):
        apply_provisioning(plugin, request)


def test_connector_exception_material_is_not_rendered_or_chained() -> None:
    sentinel = "MATERIALIZED-SECRET-4ddc1"
    plugin = fake_plugin(provision_raises=RuntimeError(sentinel))
    step = ProvisionStep(step_key="domain", endpoint_code="domain.apply")
    request = ProvisionPlanRequest(
        capability_id=plugin.manifest.capabilities[0].capability_id,
        command_id="cmd-1",
        plan_hash=provision_plan_hash((step,)),
        steps=(step,),
    )
    with pytest.raises(ProvisionHandlerRaised) as excinfo:
        plan_provisioning(plugin, request)
    rendered = "".join(
        traceback.format_exception(
            type(excinfo.value), excinfo.value, excinfo.value.__traceback__
        )
    )
    assert sentinel not in str(excinfo.value)
    assert sentinel not in rendered
    assert excinfo.value.__cause__ is None


def _import_roots(source: str) -> set[str]:
    roots: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.split(".", 1)[0])
    return roots


def test_contract_invoker_has_no_persistence_or_network_dependency() -> None:
    path = (
        Path(__file__).parents[2]
        / "packages/dotmac-integration/src/dotmac_integration/provision_contract.py"
    )
    forbidden = {
        "sqlalchemy",
        "httpx",
        "requests",
        "aiohttp",
        "urllib3",
        "socket",
        "subprocess",
    }
    assert _import_roots(path.read_text()) & forbidden == set()
    assert _import_roots("import sqlalchemy\n") & forbidden == {"sqlalchemy"}
