"""D4: render the V3 execution plan Lane 3 executes, from public calls only.

The installed CLI renders its V3 plan in a private helper,
``cli._render_local_execution_plan_v3``. D4 drives the ``Executor`` in-process
(roadmap Q1, answered 2026-10-06), so it cannot go through the CLI, and it must
not import a private name: a private helper can change shape inside a patch
release without any contract noticing. This module is the Starter-local mirror,
built only from public Foundation calls, and
``tests/unit/test_lane3_plan_v3.py`` proves it renders the same plan digest and
the same canonical bytes as the CLI path, and refuses the same inputs.

If the parity test ever fails, the mirror is wrong, not the CLI: the CLI's
render is what the candidate ships. The repair is to follow the CLI, or to ask
Foundation for a public entry point before the Gate-2 freeze. A Foundation
change after the freeze spends the candidate.
"""

from __future__ import annotations

from typing import Any

from dotmac_deployment_foundation import host_source
from dotmac_deployment_foundation.errors import PreconditionFailed
from dotmac_deployment_foundation.execution_plan_v2 import render_execution_plan_v2
from dotmac_deployment_foundation.execution_plan_v3 import (
    FoundationExecutionPlanV3,
    render_execution_plan_v3,
)


def render_local_execution_plan_v3(
    base_plan: Any, *, bindings: Any
) -> FoundationExecutionPlanV3:
    """Render from fresh installed and Control facts, never from receipt fields.

    Same order of questions as the CLI: bindings, provider, observed subject,
    then the installed artifact. ``host_source.read_installed_artifact`` is
    looked up at call time, as the CLI's function-local import does.
    """
    if bindings is None:
        raise PreconditionFailed("no startup-fixed V3 authority is installed")
    provider = bindings.authorization_v3_provider
    if provider is None:
        raise PreconditionFailed("no trusted V2 authorization provider is installed")
    facts = provider.observe()
    if facts.target_ref != base_plan.target or facts.operation != base_plan.operation:
        raise PreconditionFailed("observed target or operation differs from the plan")
    return render_execution_plan_v3(
        render_execution_plan_v2(base_plan),
        candidate_wheel_digest=str(
            host_source.read_installed_artifact().artifact_digest
        ),
        target_id=facts.target_id,
        controller_ssh_fingerprint=facts.controller_ssh_fingerprint,
        host_id=facts.host_id,
        host_incarnation=facts.host_incarnation,
        host_enrolment_ref=facts.host_enrolment_ref,
    )
