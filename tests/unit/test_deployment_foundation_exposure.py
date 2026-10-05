"""Execution and proof for `IngressPolicy.v1`: apply it, then go and look.

Slice 1 proves the CONTRACT refuses the wrong descriptor. This file proves the
RUNTIME refuses the wrong host, which is a different question: a descriptor can
be perfect and the socket still wrong, and every way that happened on this
fleet has a case here.

## The mutation matrix

Each row is a real defect, planted into an otherwise-conforming observation, so
the verifier is shown to fail on it rather than merely to pass on a clean tree
(ADR-0018 — a checker over a conforming input passes for the wrong reason):

| planted | why the naive check misses it |
|---|---|
| a missing `host_ip` | short syntax publishes on every family; the file reads fine |
| a wildcard bind | the descriptor said loopback and the socket did not |
| the wrong address family | a v6 socket where only v4 was declared |
| an inert chain | v6 rules in `DOCKER-USER` count as rules and fire on nothing |
| an incomplete source set | ACCEPTs with no terminal DROP enforce nothing |
| `--dport` on a remapped publish | post-DNAT it matches the container port |
| a leftover `docker-proxy` | a socket no reviewed file describes |
| a private port bound to loopback | an outage that looks like a hardening |

## The privileged-vantage refusal

The workstation sits inside `203.0.113.0/24`, which several of this fleet's
allowlists explicitly ACCEPT. On 2026-08-29 two agents independently connected
to "public" ports from it and each escalated a P0 that did not exist. The
refusal is tested in both directions: a privileged vantage cannot conclude, and
an ESTABLISHED outside vantage can — a refusal that refused everything would
pass the first test and be useless.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import pytest
from dotmac_deployment_foundation import ingress
from dotmac_deployment_foundation.errors import PreconditionFailed
from dotmac_deployment_foundation.exposure import (
    APPLY_COMMAND,
    HostObservation,
    ObservedChain,
    PrivilegedVantageError,
    ProbeOutcome,
    ProbeResult,
    ProbeVantage,
    Severity,
    accept_public_exposure_evidence,
    conclude_binding,
    expected_bindings,
    observation_from_text,
    parse_docker_proxy_processes,
    parse_iptables_save,
    parse_socket_listing,
    refuse_non_recreating_apply,
    verify_exposure,
)
from dotmac_deployment_foundation.spec import ProductDeploymentSpec

from tests.unit.exposure_reconciliation import reconcile

_MANIFEST_DIGEST = "sha256:" + "a" * 64
_IMAGE = f"registry.example.com/acme/app@sha256:{'b' * 64}"

_DESCRIPTOR = f"""
schema = "ProductDeploymentSpec.v1"
product = "acme"
environment = "prod"

[assembly]
manifest_path = "deploy/product.toml"
manifest_digest = "{_MANIFEST_DIGEST}"

[image]
reference = "{_IMAGE}"
source_revision = "{"c" * 40}"

[migration]
command = ["alembic", "upgrade", "heads"]
heads_command = ["alembic", "current"]
owner_material = "MIGRATION_DATABASE_URL"
expected_heads = ["abc123"]
compatibility = "online"
lock_timeout_seconds = 300

[[roles]]
code = "app"
command = ["python", "-m", "app"]
replicas = 1

[roles.resources]
cpus = "0.5"
memory = "256m"

[roles.health.ready]
path = "/readyz"
port = 8003

[[roles.ports]]
container = 8003
host = 8003
protocol = "tcp"
exposure = "loopback"
address_family = "dual_stack"

[[roles.ports]]
container = 5432
host = 9001
protocol = "tcp"
exposure = "private"
address_family = "ipv4"
tls = "none"
source_set = "operations-vpn"
"""


@pytest.fixture(scope="module")
def spec() -> ProductDeploymentSpec:
    return ProductDeploymentSpec.loads(_DESCRIPTOR, source="<exposure-fixture>")


# ── the conforming observation, and the negative control ────────────────────


def _ss(local: str, *, pid: int, process: str = "docker-proxy") -> str:
    """One `ss -tlnp` line. `ss` pads to variable widths and this does not; the
    parser reads columns, not alignment, and building the line here keeps the
    real output's shape without a hundred-column literal."""
    return f'LISTEN 0 4096 {local} 0.0.0.0:* users:(("{process}",pid={pid},fd=4))'


def _proxy(host_ip: str, host_port: int, container_port: int, *, pid: int) -> str:
    return (
        f"root {pid} /usr/bin/docker-proxy -proto tcp -host-ip {host_ip} "
        f"-host-port {host_port} -container-ip 172.18.0.3 "
        f"-container-port {container_port}"
    )


CONFORMING_SOCKETS = "\n".join(
    [
        "State Recv-Q Send-Q Local Address:Port Peer Address:Port Process",
        _ss("127.0.0.1:8003", pid=101),
        _ss("[::1]:8003", pid=102),
        _ss("10.20.0.7:9001", pid=103),
    ]
)

CONFORMING_PROCESSES = "\n".join(
    [
        _proxy("127.0.0.1", 8003, 8003, pid=101),
        _proxy("::1", 8003, 8003, pid=102),
        _proxy("10.20.0.7", 9001, 5432, pid=103),
    ]
)

CONFORMING_V4 = """
*filter
:DOCKER-USER - [0:0]
-A DOCKER-USER -p tcp -m conntrack --ctorigdstport 9001 -s 10.9.0.0/24 -j ACCEPT
-A DOCKER-USER -p tcp -m conntrack --ctorigdstport 9001 -j DROP
COMMIT
"""

CONFORMING_V6 = """
*filter
:INPUT ACCEPT [0:0]
:DOCKER-USER - [0:0]
COMMIT
"""


def _observation(
    *,
    sockets: str = CONFORMING_SOCKETS,
    processes: str = CONFORMING_PROCESSES,
    v4: str = CONFORMING_V4,
    v6: str = CONFORMING_V6,
    closed_port_behaviour: str = "reset",
) -> HostObservation:
    return observation_from_text(
        socket_listing=sockets,
        process_listing=processes,
        iptables_save={"ipv4": v4, "ipv6": v6},
        closed_port_behaviour=closed_port_behaviour,
    )


def _codes(spec: ProductDeploymentSpec, observation: HostObservation) -> set[str]:
    return {
        finding.code
        for finding in verify_exposure(spec, observation).findings
        if finding.severity is Severity.REFUSE
    }


def test_a_conforming_host_verifies_clean(spec: ProductDeploymentSpec) -> None:
    """The negative control, first.

    Every other test in this section plants a defect. A verifier that refused
    everything would pass all of them and be worthless, so the conforming case
    is asserted before any of them — and it must verify something, because
    green over an empty binding set is not a proof.
    """
    report = verify_exposure(spec, _observation())
    assert report.ok, [finding.detail for finding in report.refusals]
    assert len(report.verified) == 3


def test_every_declared_family_becomes_its_own_expected_binding(
    spec: ProductDeploymentSpec,
) -> None:
    bindings = expected_bindings(spec)
    assert {(binding.family, binding.host_port) for binding in bindings} == {
        ("ipv4", 8003),
        ("ipv6", 8003),
        ("ipv4", 9001),
    }


# ── the mutation matrix ─────────────────────────────────────────────────────


def test_a_missing_socket_is_refused_and_names_the_restart_trap(
    spec: ProductDeploymentSpec,
) -> None:
    """A correct Compose diff plus `docker compose restart` looks exactly like
    this: the file says one thing and the host still has the old container."""
    without_v6 = "\n".join(
        line for line in CONFORMING_SOCKETS.splitlines() if "[::1]" not in line
    )
    report = verify_exposure(spec, _observation(sockets=without_v6))
    assert "socket_missing" in {finding.code for finding in report.refusals}
    assert any("restart" in finding.detail for finding in report.refusals)


def test_a_wildcard_bind_is_refused(spec: ProductDeploymentSpec) -> None:
    """The mutation the long syntax exists to make impossible in the FILE.

    It is still possible on the host — an operator can publish by hand — so it
    is checked again against the socket rather than trusted from the render.
    """
    wildcard = ".".join(["0"] * 4)
    mutated = CONFORMING_SOCKETS.replace("127.0.0.1:8003", f"{wildcard}:8003")
    assert "wildcard_bind" in _codes(spec, _observation(sockets=mutated))


def test_a_private_publication_that_bound_loopback_is_refused(
    spec: ProductDeploymentSpec,
) -> None:
    """The failure direction nobody guards, because it looks like the safe one.

    9001 is declared private for `operations-vpn`. Bound to loopback it is
    unreachable by the source set it exists for — an outage wearing a
    hardening's clothes, and one nobody investigates for hours because the
    socket is "correctly" bound.
    """
    mutated = CONFORMING_SOCKETS.replace("10.20.0.7:9001", "127.0.0.1:9001")
    assert "narrower_than_declared" in _codes(spec, _observation(sockets=mutated))


def test_a_missing_host_ip_publishing_on_every_family_is_refused(
    spec: ProductDeploymentSpec,
) -> None:
    """What "no host_ip" actually looks like on the host: a docker-proxy per
    family, one of them on the wildcard, answering from anywhere."""
    mutated = CONFORMING_PROCESSES.replace("-host-ip 127.0.0.1", "-host-ip ::")
    codes = _codes(spec, _observation(processes=mutated))
    assert "proxy_wildcard" in codes


def test_a_socket_on_the_wrong_family_is_refused(
    spec: ProductDeploymentSpec,
) -> None:
    """9001 is declared IPv4-only. A v6 socket on it is the undeclared family
    the whole contract exists to prevent, and nothing in the descriptor would
    ever mention it."""
    mutated = CONFORMING_SOCKETS + "\n" + _ss("[fd00::7]:9001", pid=104)
    assert "undeclared_socket" in _codes(spec, _observation(sockets=mutated))


def test_a_v6_rule_in_docker_user_is_refused_as_inert(
    spec: ProductDeploymentSpec,
) -> None:
    """The measured defect, planted.

    Two rules exactly like this were found in production with zero packet
    counters while the ports they named were open. A verifier that counts rules
    reports containment; this one reports the chain.
    """
    private_v6 = ProductDeploymentSpec.loads(
        _DESCRIPTOR.replace(
            'host = 9001\nprotocol = "tcp"\nexposure = "private"\n'
            'address_family = "ipv4"',
            'host = 9001\nprotocol = "tcp"\nexposure = "private"\n'
            'address_family = "ipv6"',
        ),
        source="<exposure-fixture-v6>",
    )
    mutated_v6 = CONFORMING_V6.replace(
        ":DOCKER-USER - [0:0]",
        ":DOCKER-USER - [0:0]\n-A DOCKER-USER -p tcp --dport 9001 -j DROP",
    )
    sockets = "\n".join(
        [
            _ss("[fd00::7]:9001", pid=104),
            _ss("127.0.0.1:8003", pid=101),
            _ss("[::1]:8003", pid=102),
        ]
    )
    codes = _codes(
        private_v6, _observation(sockets=sockets, processes="", v6=mutated_v6)
    )
    assert "inert_chain" in codes


def test_an_allowlist_with_no_terminal_drop_is_refused(
    spec: ProductDeploymentSpec,
) -> None:
    """Check for the deny, not only the accepts. Everything the ACCEPTs miss
    falls through to the chain policy, ACCEPT on a Docker host."""
    without_deny = "\n".join(
        line for line in CONFORMING_V4.splitlines() if "-j DROP" not in line
    )
    assert "no_terminal_deny" in _codes(spec, _observation(v4=without_deny))


def test_an_incomplete_source_set_leaves_the_port_wide_open(
    spec: ProductDeploymentSpec,
) -> None:
    """The same defect stated the other way: an allowlist that lost its DROP
    still LOOKS like an allowlist, and a rule count is unchanged."""
    without_deny = "\n".join(
        line for line in CONFORMING_V4.splitlines() if "-j DROP" not in line
    )
    assert "--ctorigdstport 9001" in without_deny
    report = verify_exposure(spec, _observation(v4=without_deny))
    assert not report.ok


def test_a_dport_rule_on_a_remapped_publish_is_refused(
    spec: ProductDeploymentSpec,
) -> None:
    """9001 -> 5432 is remapped. Post-DNAT in DOCKER-USER the destination port
    is 5432, so `--dport 9001` matches nothing while reading, in a diff,
    exactly like a rule that works."""
    mutated = CONFORMING_V4.replace("-m conntrack --ctorigdstport", "--dport")
    assert "wrong_port_match" in _codes(spec, _observation(v4=mutated))


def test_a_missing_chain_is_refused_rather_than_read_as_no_rules_needed(
    spec: ProductDeploymentSpec,
) -> None:
    assert "chain_missing" in _codes(spec, _observation(v4="*filter\nCOMMIT\n"))


def test_a_leftover_docker_proxy_on_an_undeclared_port_is_refused(
    spec: ProductDeploymentSpec,
) -> None:
    """Checked in the other direction on purpose: a verifier that only walks
    the descriptor cannot see the port the descriptor does not mention, and
    that is the port that stays open."""
    mutated = CONFORMING_SOCKETS + "\n" + _ss("127.0.0.1:6391", pid=110)
    assert "undeclared_socket" in _codes(spec, _observation(sockets=mutated))


def test_a_non_docker_listener_is_not_reported_as_an_undeclared_publication(
    spec: ProductDeploymentSpec,
) -> None:
    """The sensitivity proof for the check above. `sshd` is not a publication,
    and a guard that reported every host listener would be turned off within a
    week."""
    mutated = CONFORMING_SOCKETS + "\n" + _ss("127.0.0.1:22", pid=900, process="sshd")
    assert verify_exposure(spec, _observation(sockets=mutated)).ok


# ── the privileged-vantage refusal ──────────────────────────────────────────

INSIDE = ProbeVantage(
    name="workstation",
    inside_source_sets=frozenset({"dotmac-corporate"}),
    membership_established=True,
)
OUTSIDE = ProbeVantage(
    name="dedicated-test-host",
    inside_source_sets=frozenset(),
    membership_established=True,
)
UNKNOWN = ProbeVantage(
    name="some-cloud-shell",
    inside_source_sets=frozenset(),
    membership_established=False,
)


def _probe(vantage: ProbeVantage) -> ProbeResult:
    return ProbeResult(
        endpoint_token="v1|acme|prod|db|tcp|ipv4|9001|private",
        family="ipv4",
        vantage=vantage,
        outcome=ProbeOutcome.REACHED,
    )


def test_a_probe_from_inside_the_allowlist_cannot_prove_public_exposure() -> None:
    """The refusal that cost this programme two false P0 escalations.

    The workstation's public address sits inside `203.0.113.0/24`, which
    several allowlists ACCEPT. Both a coordinator and an agent independently
    connected and concluded "publicly exposed". The connection was real; the
    conclusion was not.
    """
    with pytest.raises(PrivilegedVantageError) as caught:
        accept_public_exposure_evidence(
            _probe(INSIDE), accepted_source_sets=["dotmac-corporate", "partner-vpn"]
        )
    assert "INSIDE" in str(caught.value)
    assert "allowlist works" in str(caught.value)


def test_a_vantage_that_never_established_its_membership_cannot_conclude() -> None:
    """Fail closed. An unproven vantage is not a neutral one, and treating it
    as neutral is the same error with the checking step removed."""
    with pytest.raises(PrivilegedVantageError) as caught:
        accept_public_exposure_evidence(
            _probe(UNKNOWN), accepted_source_sets=["dotmac-corporate"]
        )
    assert "has not established" in str(caught.value)


def test_an_established_outside_vantage_is_accepted() -> None:
    """The negative control. A refusal that refused every vantage would pass
    both tests above and make external verification impossible."""
    accept_public_exposure_evidence(
        _probe(OUTSIDE), accepted_source_sets=["dotmac-corporate"]
    )


def test_a_probe_is_accepted_when_the_plan_accepts_nothing_it_is_inside() -> None:
    accept_public_exposure_evidence(
        _probe(INSIDE), accepted_source_sets=["partner-vpn"]
    )


# ── what a probe may conclude about a binding ───────────────────────────────


def test_on_a_dropping_host_an_external_probe_alone_concludes_nothing() -> None:
    """One host in this fleet silently DROPs a closed port and another RSTs, so
    the same silence means two different things. On the dropping host,
    loopback-bound and wildcard-bound-and-dropped are indistinguishable from
    outside — the answer is INCONCLUSIVE, not "closed"."""
    assert (
        conclude_binding(
            probe=ProbeResult(
                endpoint_token="v1|acme|prod|db|tcp|ipv4|9001|private",
                family="ipv4",
                vantage=OUTSIDE,
                outcome=ProbeOutcome.SILENT,
            ),
            sockets=(),
            host_port=9001,
            family="ipv4",
            closed_port_behaviour="drop",
        )
        == "inconclusive"
    )


def test_on_a_resetting_host_silence_does_conclude_absence() -> None:
    assert (
        conclude_binding(
            probe=None,
            sockets=(),
            host_port=9001,
            family="ipv4",
            closed_port_behaviour="reset",
        )
        == "absent"
    )


def test_on_host_socket_evidence_decides(spec: ProductDeploymentSpec) -> None:
    observation = _observation()
    assert (
        conclude_binding(
            probe=None,
            sockets=observation.sockets,
            host_port=8003,
            family="ipv6",
            closed_port_behaviour="drop",
        )
        == "bound"
    )


def test_reaching_a_port_with_no_observed_socket_is_inconclusive_not_absent() -> None:
    """The observation is incomplete, not the port gone. Reporting "absent"
    here would be the reassuring answer and the wrong one."""
    assert (
        conclude_binding(
            probe=ProbeResult(
                endpoint_token="v1|acme|prod|db|tcp|ipv4|9001|private",
                family="ipv4",
                vantage=OUTSIDE,
                outcome=ProbeOutcome.REACHED,
            ),
            sockets=(),
            host_port=9001,
            family="ipv4",
            closed_port_behaviour="reset",
        )
        == "inconclusive"
    )


# ── parsers ─────────────────────────────────────────────────────────────────


def test_the_socket_parser_splits_ipv6_on_the_LAST_colon() -> None:
    """Splitting on the first colon reads `[::1]:8003` as host `` port `:1`,
    silently, and every v6 assertion downstream then passes vacuously."""
    sockets = parse_socket_listing(CONFORMING_SOCKETS)
    v6 = [socket for socket in sockets if socket.family == "ipv6"]
    assert [(socket.address, socket.port) for socket in v6] == [("::1", 8003)]


def test_an_unclassifiable_socket_address_surfaces_rather_than_disappearing() -> None:
    """An IPv4-mapped listener is the most interesting socket on the host.

    Skipping it in the parser would also remove it from the undeclared-socket
    sweep, so the absence of a finding would mean "we could not read it"
    while looking exactly like "there was nothing there".
    """
    parsed = parse_socket_listing(
        'LISTEN 0 4096 ::ffff:10.0.0.1:9001 *:* users:(("docker-proxy",pid=1,fd=4))'
    )
    assert [socket.family for socket in parsed] == ["unknown"]


def test_the_socket_parser_normalizes_the_star_wildcard() -> None:
    parsed = parse_socket_listing(
        'LISTEN 0 4096 *:8003 *:* users:(("docker-proxy",pid=1,fd=4))'
    )
    assert parsed[0].address == "::"


def test_the_proxy_parser_reads_the_remapped_container_port() -> None:
    proxies = parse_docker_proxy_processes(CONFORMING_PROCESSES)
    remapped = [proxy for proxy in proxies if proxy.host_port == 9001]
    assert remapped[0].container_port == 5432


def test_the_iptables_parser_keeps_an_empty_chain() -> None:
    """ "The chain exists and holds nothing" and "the chain does not exist" are
    different facts, and only the first one is a missing rule."""
    chains = parse_iptables_save(CONFORMING_V6, family="ipv6")
    by_name = {chain.name: chain for chain in chains}
    assert by_name["DOCKER-USER"].rules == ()
    assert by_name["INPUT"].policy == "ACCEPT"


def test_the_rule_parser_distinguishes_the_two_port_matches() -> None:
    chains = parse_iptables_save(CONFORMING_V4, family="ipv4")
    rules = chains[0].rules
    assert all(rule.matched_port == 9001 for rule in rules)
    assert all(rule.matches_original_destination for rule in rules)
    assert [rule.target for rule in rules] == ["ACCEPT", "DROP"]


# ── the transaction ─────────────────────────────────────────────────────────


class _FakeEffects:
    """A host that behaves however the test needs it to.

    Records every call in order, because the ORDERING is the contract under
    test: snapshot before mutate, re-observe after, restore from the snapshot.
    """

    def __init__(self, *, before: HostObservation, after: HostObservation) -> None:
        self._observations = [before, after]
        self.calls: list[str] = []
        self.restored: list[ObservedChain] = []
        self.applied: list[tuple[str, ...]] = []

    def observe(self) -> HostObservation:
        self.calls.append("observe")
        return self._observations.pop(0) if self._observations else HostObservation()

    def apply_compose(self, command: Sequence[str], *, timeout_seconds: int) -> None:
        self.calls.append("apply_compose")
        self.applied.append(tuple(command))

    def replace_rules(
        self, family: str, chain: str, rules: Sequence[ingress.FirewallRule]
    ) -> None:
        self.calls.append(f"replace_rules:{family}")

    def restore_chains(self, chains: Sequence[ObservedChain]) -> None:
        self.calls.append("restore_chains")
        self.restored = list(chains)


def test_a_verifying_reconciliation_snapshots_applies_and_reobserves(
    spec: ProductDeploymentSpec,
) -> None:
    """The ordering, now owned by `Executor` rather than by a second executor.

    Note what is NOT in `calls` any more: `apply_compose`. The old transaction
    recreated the containers itself and then replaced the rules, which made the
    rule write a SECOND mutation on top of an already-irreversible one. The
    recreate belongs to `_do_switch`, which has run by the time this does, so
    the reconciliation performs the one half nothing else performs.
    """
    effects = _FakeEffects(before=_observation(), after=_observation())
    outcome = reconcile(spec, effects)

    assert effects.calls[0] == "observe", "it looks BEFORE it touches anything"
    assert effects.calls[-1] == "observe", "the last thing it does is LOOK"
    assert "apply_compose" not in effects.calls
    assert "restore_chains" not in effects.calls
    applied = [call for call in effects.calls if call.startswith("replace_rules")]
    assert applied == ["replace_rules:ipv4", "replace_rules:ipv6"]
    assert [(r.kind.value, r.ok) for r in outcome.records] == [("apply_exposure", True)]
    assert outcome.mutated, (
        "a reconciliation that wrote to a shared chain and reported "
        "`mutated=False` would tell an operator it is safe to re-run"
    )


def test_an_apply_that_does_not_verify_is_rolled_back_to_the_SNAPSHOT(
    spec: ProductDeploymentSpec,
) -> None:
    """Rolled back to an OBSERVED state, not a remembered intention. A rollback
    that restores only what it thinks it changed cannot repair what it did not
    notice changing."""
    wildcard = ".".join(["0"] * 4)
    before = _observation()
    after = _observation(
        sockets=CONFORMING_SOCKETS.replace("127.0.0.1:8003", f"{wildcard}:8003")
    )
    effects = _FakeEffects(before=before, after=after)

    with pytest.raises(PreconditionFailed, match="did not verify"):
        reconcile(spec, effects, families=("ipv4",))

    assert "restore_chains" in effects.calls
    assert effects.restored == list(before.chains), (
        "compensation must restore the OBSERVED snapshot. Restoring a "
        "remembered intention cannot repair what it did not notice changing"
    )


def test_the_reconciliation_takes_no_lock_of_its_own(
    spec: ProductDeploymentSpec, tmp_path: Path
) -> None:
    """The inversion, and it is the whole reason boundaries 1 and 3 are one change.

    This test used to assert the OPPOSITE: that the transaction held the
    product lock across its own duration. It did — by taking it itself — and
    that is what made exposure impossible to sequence inside a deployment.
    `fcntl.flock` attaches to the open file description, so a caller already
    holding the product's lock got `EAGAIN` against its own process when the
    transaction reached for it again.

    So the requirement inverted. The reconciliation must take NO lock: the
    caller's hold, proven as a `DeploymentLockHeld` by `Executor.run`, covers
    the whole mutating sequence including this. A lock taken here would be a
    second acquisition that can only fail.
    """
    from dotmac_deployment_foundation.engine.lock import lock_path

    effects = _FakeEffects(before=_observation(), after=_observation())
    reconcile(spec, effects)

    assert not lock_path(spec.product, directory=tmp_path).exists(), (
        "the reconciliation took a lock of its own. Nested acquisition in one "
        "process refuses with EAGAIN, so this does not merely duplicate the "
        "caller's hold — it makes exposure unreachable from inside a deployment"
    )


@pytest.mark.parametrize(
    "command",
    [("restart",), ("restart", "app"), ("up", "-d"), ("ps",)],
)
def test_an_apply_that_cannot_change_a_binding_is_refused(
    command: tuple[str, ...],
) -> None:
    """`docker compose restart` restarts the container it already has, with the
    bindings it already has; a plain `up -d` will not recreate when the image
    is unchanged, and a bind-only change is exactly that case."""
    with pytest.raises(PreconditionFailed):
        refuse_non_recreating_apply(command)


def test_the_recreating_apply_is_accepted() -> None:
    """The negative control for the refusal above."""
    refuse_non_recreating_apply(APPLY_COMMAND)
    refuse_non_recreating_apply([*APPLY_COMMAND, "app"])


def test_the_report_carries_the_descriptor_digest_it_verified_against(
    spec: ProductDeploymentSpec,
) -> None:
    """So a recorded verification can be matched to the exact plan it proves,
    rather than to whatever the descriptor says today.

    It is the CANONICAL DESCRIPTOR digest — the same value deployment control
    binds its authorization to — and not a second digest of the ingress
    section, because two digests over overlapping content would be two answers
    to "what was verified"."""
    report = verify_exposure(spec, _observation())
    assert report.descriptor_digest == spec.to_canonical_document().sha256_digest()
    assert report.descriptor_digest.startswith("sha256:")
