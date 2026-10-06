"""Parity: ``scripts/lane3_plan_v3.py`` renders what the CLI's private render does.

The CLI's ``_render_local_execution_plan_v3`` is imported HERE, in a test, and
only to compare against. The producer never imports it. Both paths read the
installed artifact through ``host_source.read_installed_artifact`` at call
time, so one monkeypatch feeds both the same wheel digest.
"""

from __future__ import annotations

import dataclasses
import pathlib
import sys
from typing import Any

import pytest
from dotmac_deployment_foundation import cli, host_source
from dotmac_deployment_foundation.digest import Digest
from dotmac_deployment_foundation.engine.plan import build_plan
from dotmac_deployment_foundation.errors import PreconditionFailed
from dotmac_deployment_foundation.execution_bindings import ExecutionBindings
from dotmac_deployment_foundation.execution_plan import (
    HostPrestateV1,
    render_execution_plan,
)
from dotmac_deployment_foundation.spec import ProductDeploymentSpec

from tests.unit.foundation_v3_support import WHEEL, provider_for, v3_plan

REPO = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))

import lane3_plan_v3  # noqa: E402


@dataclasses.dataclass(frozen=True)
class _Installed:
    artifact_digest: Digest


@pytest.fixture
def base(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    monkeypatch.setattr(
        host_source,
        "read_installed_artifact",
        lambda *a, **k: _Installed(Digest.parse(WHEEL)),
    )
    body = (REPO / "scripts/exposure-rehearsal/product.toml").read_text("utf-8")
    descriptor = tmp_path / "product.toml"
    descriptor.write_text(body, encoding="utf-8")
    spec = ProductDeploymentSpec.load(str(descriptor))
    plan = render_execution_plan(
        spec,
        build_plan(spec),
        target="rehearsal-target",
        operation="deploy",
        descriptor_digest=str(spec.to_canonical_document().sha256_digest()),
        prestate=HostPrestateV1.first_deploy(),
        application_profile_digest="",
    )
    return spec, plan


def _bindings(spec: Any, base_plan: Any, **context: Any) -> ExecutionBindings:
    provider = provider_for(spec, v3_plan(base_plan))
    if context:
        provider.context = dataclasses.replace(provider.context, **context)
    return ExecutionBindings(provider="lane3-test", authorization_v3_provider=provider)


def test_the_mirror_renders_the_cli_plan_byte_for_byte(base: Any) -> None:
    spec, base_plan = base
    bindings = _bindings(spec, base_plan)
    ours = lane3_plan_v3.render_local_execution_plan_v3(base_plan, bindings=bindings)
    theirs = cli._render_local_execution_plan_v3(base_plan, bindings=bindings)
    assert ours.canonical_bytes() == theirs.canonical_bytes()
    assert ours.digest() == theirs.digest()
    assert ours.candidate_wheel_digest == WHEEL


def test_parity_is_not_vacuous(base: Any) -> None:
    # A different observed host must change both renders, identically.
    spec, base_plan = base
    first = _bindings(spec, base_plan)
    other = _bindings(spec, base_plan, host_id="fleet-host-2")
    a = lane3_plan_v3.render_local_execution_plan_v3(base_plan, bindings=first)
    b = lane3_plan_v3.render_local_execution_plan_v3(base_plan, bindings=other)
    assert a.digest() != b.digest()
    assert (
        b.digest()
        == cli._render_local_execution_plan_v3(base_plan, bindings=other).digest()
    )


def _refusal(render: Any, base_plan: Any, bindings: Any) -> str:
    with pytest.raises(PreconditionFailed) as caught:
        render(base_plan, bindings=bindings)
    return str(caught.value)


@pytest.mark.parametrize("case", ["no_bindings", "no_provider", "target", "operation"])
def test_both_paths_refuse_the_same_inputs_the_same_way(base: Any, case: str) -> None:
    spec, base_plan = base
    bindings: Any
    if case == "no_bindings":
        bindings = None
    elif case == "no_provider":
        bindings = ExecutionBindings(
            provider="lane3-test", build_effects=lambda *a, **k: None
        )
    elif case == "target":
        bindings = _bindings(spec, base_plan, target_ref="another-target")
    else:
        bindings = _bindings(spec, base_plan, operation="rollback")
    ours = _refusal(lane3_plan_v3.render_local_execution_plan_v3, base_plan, bindings)
    theirs = _refusal(cli._render_local_execution_plan_v3, base_plan, bindings)
    assert ours == theirs


def test_the_mirror_imports_no_private_foundation_name() -> None:
    source = (REPO / "scripts/lane3_plan_v3.py").read_text("utf-8")
    imports = [
        line
        for line in source.splitlines()
        if line.startswith(("from dotmac_deployment_foundation", "import dotmac"))
    ]
    assert imports
    assert not any("cli" in line or " _" in line for line in imports)
