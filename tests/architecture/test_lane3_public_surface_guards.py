"""Two guards on what this PUBLIC repository's execution tooling may contain.

Part of Lane 3's move to an organization execution surface
(``docs/LANE3_EXECUTION_TOPOLOGY.md``, D-S3). Both are stated with their limits,
because an implied guard is worse than an honest unmonitored region (ADR-0018).

**1. No self-hosted job on ``main`` is reachable from anything but a manual
dispatch of ``main``.** A ``pull_request_target`` job runs with base-repository
context for a fork's pull request; a ``push`` or ``workflow_call`` job runs for
whatever pushed or called it. On a self-hosted runner, each of those is code
the runner owner did not choose. What this does NOT do: stop a branch from
ADDING a workflow that selects the label, or dispatching a modified copy of one.
A label routes jobs and restricts nothing, which is precisely why Lane 3 moves
to an organization runner group restricted to one ref-pinned workflow. This
guard keeps ``main``'s own workflows from being the hole.

**2. No topology in the tooling.** Execution tooling (``scripts/`` and
``.github/workflows/``) carries no IP literal other than loopback, unspecified
and the documentation ranges (RFC 5737, RFC 3849), and no NEW repository
variable feeding Lane 3 topology. Exceptions are ratcheted in both directions.
R6 lowered the address baseline to empty; R1 lowers the `vars.LANE3_` baseline
when the retiring workflow goes. Scope stops at tooling:
``docs/inventories/`` carries dated measurement records, whose estate
addresses were redacted on 2026-10-05 (the role → address map is held
privately). This guard does not scan docs, so a new address there would not be
caught here.
"""

from __future__ import annotations

import copy
import ipaddress
import pathlib
import re
from typing import Any

import pytest
import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
WORKFLOWS = REPO / ".github" / "workflows"

# ── guard 1: self-hosted reachability ───────────────────────────────────────

#: The only trigger under which a self-hosted job may exist on `main`.
ALLOWED_TRIGGERS = frozenset({"workflow_dispatch"})
MAIN_ONLY = "github.ref == 'refs/heads/main'"


def _triggers(document: dict[Any, Any]) -> set[str]:
    # PyYAML (YAML 1.1) reads the bare key `on` as boolean True.
    raw = document.get("on", document.get(True))
    if isinstance(raw, str):
        return {raw}
    if isinstance(raw, list):
        return {str(item) for item in raw}
    if isinstance(raw, dict):
        return {str(key) for key in raw}
    return set()


def _self_hosted(runs_on: Any) -> bool:
    if isinstance(runs_on, str):
        return runs_on == "self-hosted"
    if isinstance(runs_on, list):
        return "self-hosted" in {str(label) for label in runs_on}
    if isinstance(runs_on, dict):
        # `runs-on: {group: ...}` selects an organization runner group, which
        # is self-hosted by construction; `labels:` may carry the label too.
        return "group" in runs_on or _self_hosted(runs_on.get("labels"))
    return False


def self_hosted_findings(name: str, document: dict[Any, Any]) -> list[str]:
    """Every self-hosted job in one workflow that something else can reach."""
    findings: list[str] = []
    triggers = _triggers(document)
    for job_name, job in (document.get("jobs") or {}).items():
        if not isinstance(job, dict) or not _self_hosted(job.get("runs-on")):
            continue
        extra = sorted(triggers - ALLOWED_TRIGGERS)
        if extra:
            findings.append(
                f"{name}:{job_name} is self-hosted and reachable through {extra}"
            )
        if MAIN_ONLY not in str(job.get("if", "")):
            findings.append(
                f"{name}:{job_name} is self-hosted and does not require {MAIN_ONLY!r}"
            )
    return findings


def _workflows() -> dict[str, dict[Any, Any]]:
    found = {
        path.name: yaml.safe_load(path.read_text(encoding="utf-8"))
        for path in sorted(WORKFLOWS.glob("*.yml"))
    }
    assert found, "no workflows were read; every assertion below would be vacuous"
    return found


def test_no_self_hosted_job_on_main_is_reachable_except_by_dispatching_main() -> None:
    findings = [
        finding
        for name, document in _workflows().items()
        for finding in self_hosted_findings(name, document)
    ]
    assert not findings, "\n".join(findings)


def test_the_reachability_scan_actually_sees_self_hosted_jobs() -> None:
    """Negative control: the guard above passes trivially if it finds nothing."""
    seen = [
        f"{name}:{job_name}"
        for name, document in _workflows().items()
        for job_name, job in (document.get("jobs") or {}).items()
        if isinstance(job, dict) and _self_hosted(job.get("runs-on"))
    ]
    assert seen, "no self-hosted job was recognised; the scan cannot be trusted"


CONFORMING: dict[Any, Any] = {
    True: {"workflow_dispatch": {}},
    "jobs": {
        "privileged": {
            "runs-on": ["self-hosted", "lane3"],
            "if": MAIN_ONLY,
            "steps": [],
        }
    },
}


def test_a_conforming_synthetic_workflow_passes() -> None:
    assert self_hosted_findings("synthetic.yml", CONFORMING) == []


@pytest.mark.parametrize(
    "trigger",
    [
        "pull_request_target",
        "pull_request",
        "push",
        "workflow_call",
        "workflow_run",
        "issue_comment",
        "schedule",
    ],
)
def test_each_other_trigger_on_a_self_hosted_job_is_caught(trigger: str) -> None:
    planted = copy.deepcopy(CONFORMING)
    planted[True][trigger] = {}
    assert self_hosted_findings("planted.yml", planted)


@pytest.mark.parametrize("key", ["on", True])
@pytest.mark.parametrize(
    "triggers", ["pull_request_target", ["workflow_dispatch", "push"]]
)
def test_string_and_list_trigger_forms_are_read(key: Any, triggers: Any) -> None:
    planted = copy.deepcopy(CONFORMING)
    planted.pop(True)
    planted[key] = triggers
    assert self_hosted_findings("planted.yml", planted)


@pytest.mark.parametrize(
    "runs_on",
    [
        "self-hosted",
        ["self-hosted"],
        {"group": "anything"},
        {"labels": ["self-hosted"]},
    ],
)
def test_every_self_hosted_runs_on_form_is_recognised(runs_on: Any) -> None:
    planted = copy.deepcopy(CONFORMING)
    planted[True]["pull_request_target"] = {}
    planted["jobs"]["privileged"]["runs-on"] = runs_on
    assert self_hosted_findings("planted.yml", planted)


def test_a_self_hosted_job_without_the_main_only_condition_is_caught() -> None:
    planted = copy.deepcopy(CONFORMING)
    del planted["jobs"]["privileged"]["if"]
    assert self_hosted_findings("planted.yml", planted)


# ── guard 2: no topology in the tooling ────────────────────────────────────

_V4 = re.compile(r"(?<![\w.])(\d{1,3}(?:\.\d{1,3}){3})(?![\w.])")
_V6 = re.compile(r"(?<![\w:])([0-9A-Fa-f]{0,4}(?::[0-9A-Fa-f]{0,4}){2,7})(?![\w:])")
_DOCUMENTATION = tuple(
    ipaddress.ip_network(n)
    for n in ("192.0.2.0/24", "198.51.100.0/24", "203.0.113.0/24", "2001:db8::/32")
)


def _allowed(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return (
        address.is_loopback
        or address.is_unspecified
        or any(
            address in network
            for network in _DOCUMENTATION
            if network.version == address.version
        )
    )


def address_literals(text: str) -> set[str]:
    """Every IP literal in ``text`` other than loopback, unspecified, documentation."""
    found: set[str] = set()
    for line in text.splitlines():
        for match in [*_V4.finditer(line), *_V6.finditer(line)]:
            try:
                address = ipaddress.ip_address(match.group(1))
            except ValueError:
                continue
            if not _allowed(address):
                found.add(str(address))
    return found


def _tooling() -> list[pathlib.Path]:
    files = [
        path
        for path in sorted((REPO / "scripts").rglob("*"))
        if path.suffix in {".py", ".sh"}
        # Captured command output used as parser fixtures: loopback only, and
        # read as data rather than executed.
        and "observed" not in path.relative_to(REPO).parts
    ] + sorted(WORKFLOWS.glob("*.yml"))
    assert len(files) > 20, "the tooling walk found almost nothing; it is broken"
    return files


#: Address literals execution tooling may carry: none. The last exception, the
#: probe's default "former private paths", was removed by R6 (the value is now
#: required from the private topology record). Any literal now fails.
ADDRESS_BASELINE: set[tuple[str, str]] = set()


def test_execution_tooling_carries_no_new_topology_literal() -> None:
    found = {
        (str(path.relative_to(REPO)), address)
        for path in _tooling()
        for address in address_literals(
            path.read_text(encoding="utf-8", errors="ignore")
        )
    }
    added, removed = sorted(found - ADDRESS_BASELINE), sorted(ADDRESS_BASELINE - found)
    assert not added, (
        f"execution tooling now names {added}. This repository is public; a "
        "target, vantage or jump address belongs in the private topology record "
        "(docs/LANE3_EXECUTION_TOPOLOGY.md § 4), and an example belongs in a "
        "documentation range (RFC 5737 / RFC 3849)"
    )
    assert not removed, (
        f"{removed} no longer appear. Lower ADDRESS_BASELINE in the same change, "
        "so the ratchet records the retirement instead of silently widening"
    )


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("ssh 8.8.4.4", {"8.8.4.4"}),
        ("vantage 10.20.30.40 22", {"10.20.30.40"}),
        ("v6 2606:4700:4700::1001 36088", {"2606:4700:4700::1001"}),
        ("bind 127.0.0.1 and ::1 and 0.0.0.0", set()),
        ("example 192.0.2.54 and 2001:db8:1::1", set()),
        ("version 1.2.3.4.5 and time 10:00:00 and sha256:abcd", set()),
    ],
)
def test_the_address_scan_sees_real_addresses_and_ignores_safe_ones(
    text: str, expected: set[str]
) -> None:
    """Sensitivity proof, in memory: the shapes this guard exists for (a public
    IPv4 vantage, an RFC 1918 target and a public IPv6 source, each once
    committed here with real estate values) are caught, and the allowed forms
    are not. The examples are well-known public resolvers and a generic private
    address, never estate addresses."""
    assert address_literals(text) == expected


#: `vars.LANE3_*` reads per workflow. Repository variables are not masked, so
#: each one feeds topology into public logs. Only the retiring lane may have
#: any; D-S2b (R1) removes that lane and lowers this to {}.
LANE3_VARIABLE_BASELINE = {"exposure-rehearsal.yml": 11}


def test_no_new_workflow_reads_lane3_topology_from_repository_variables() -> None:
    counts = {
        path.name: count
        for path in sorted(WORKFLOWS.glob("*.yml"))
        if (count := path.read_text(encoding="utf-8").count("vars.LANE3_"))
    }
    assert counts == LANE3_VARIABLE_BASELINE, (
        f"vars.LANE3_ reads are {counts}, baseline {LANE3_VARIABLE_BASELINE}. A "
        "new read puts topology in public logs; a removed one means the "
        "baseline must be lowered in the same change"
    )
