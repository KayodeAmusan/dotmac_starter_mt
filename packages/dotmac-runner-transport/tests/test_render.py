from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path

import pytest
from dotmac_runner_transport import (
    ExactHost,
    HostDirectEgressGrantV1,
    HostNftablesBindingV1,
    HostProxyIdentityV1,
    HostRunnerIdentityV1,
    HostRunnerTransportSpecV1,
    ProviderDomainSnapshotV1,
    RunnerTransportAdapterManifest,
    RunnerTransportCapability,
    RunnerTransportRequirementsV1,
    TransportEndpointV1,
    WorkloadEgressPolicyV1,
    assert_nftables_placement,
    canonical_bytes,
    derive_transport_policy,
    render_host_bundle,
    typed_sha256,
)


@dataclass(frozen=True)
class _Adapter:
    manifest: RunnerTransportAdapterManifest


def _policy():
    host = ExactHost("transport.invalid")
    snapshot = ProviderDomainSnapshotV1(
        source_uri="https://provider.invalid/meta",
        observed_at="2026-08-31T00:00:00Z",
        semantic_sha256=typed_sha256(canonical_bytes((host.value,))),
        field="domains.exact",
        domains=(host,),
    )
    adapter = _Adapter(
        RunnerTransportAdapterManifest(
            key="fake-provider",
            version="1",
            capabilities=(RunnerTransportCapability.CONTROL,),
            endpoints=(TransportEndpointV1(RunnerTransportCapability.CONTROL, host),),
            snapshot=snapshot,
        )
    )
    return derive_transport_policy(
        RunnerTransportRequirementsV1((RunnerTransportCapability.CONTROL,)), adapter
    )


PROXY = HostProxyIdentityV1("squid", 2010)
NFT = HostNftablesBindingV1(
    "inet",
    "dotmac_egress",
    "output",
    ("ip daddr @mgmt_v4 accept", 'oifname "lo" accept'),
)


def _listener_verdict(rendered: str, *, uid: int, port: int) -> str | None:
    for line in rendered.splitlines():
        if "ip daddr 127.0.0.1 tcp dport { " not in line:
            continue
        if "meta skuid " in line:
            rule_uid = int(line.split("meta skuid ", 1)[1].split(" ", 1)[0])
            if rule_uid != uid:
                continue
        ports_text = line.split("tcp dport { ", 1)[1].split(" }", 1)[0]
        ports = {int(value) for value in ports_text.split(", ")}
        if port in ports:
            return line.rsplit(" ", 1)[-1]
    return None


def test_render_is_deterministic_and_binds_the_policy_digest() -> None:
    identities = (
        HostRunnerIdentityV1("starter", 2001, 3128, 3129),
        HostRunnerIdentityV1("observer", 2002, 3130, 3131),
    )
    workloads = (
        WorkloadEgressPolicyV1("observer", (ExactHost("observe.invalid"),)),
        WorkloadEgressPolicyV1("starter", (ExactHost("registry.invalid"),)),
    )
    first = render_host_bundle(_policy(), identities, PROXY, NFT, workloads)
    second = render_host_bundle(
        _policy(), tuple(reversed(identities)), PROXY, NFT, workloads
    )
    assert first == second
    assert f"policy_digest={_policy().digest}" in first.squid_conf
    assert "transport.invalid" in first.squid_conf
    assert "registry.invalid" in first.squid_conf
    lines = first.squid_conf.splitlines()
    transport_acl = {
        line.rsplit(" ", 1)[-1]
        for line in lines
        if line.startswith("acl runner_transport dstdomain ")
    }
    starter_workload_acl = {
        line.rsplit(" ", 1)[-1]
        for line in lines
        if line.startswith("acl allowed_workload_2001 dstdomain ")
    }
    observer_workload_acl = {
        line.rsplit(" ", 1)[-1]
        for line in lines
        if line.startswith("acl allowed_workload_2002 dstdomain ")
    }
    assert transport_acl == {"transport.invalid"}
    assert starter_workload_acl == {"registry.invalid"}
    assert observer_workload_acl == {"observe.invalid"}
    assert transport_acl.isdisjoint(starter_workload_acl | observer_workload_acl)
    assert (
        "http_access allow on_transport_2001 CONNECT SSL_ports runner_transport"
        in lines
    )
    assert (
        "http_access allow on_workload_2001 CONNECT SSL_ports "
        "allowed_workload_2001" in lines
    )


def test_bundle_self_validates_schema_policy_bytes_and_runner_set() -> None:
    bundle = render_host_bundle(
        _policy(),
        (HostRunnerIdentityV1("starter", 2001, 3128, 3129),),
        PROXY,
        NFT,
        (WorkloadEgressPolicyV1("starter", (ExactHost("registry.invalid"),)),),
    )
    bundle.assert_valid()
    invalid = (
        ({"schema": "RunnerEgressBundle.v2"}, "schema must be v1"),
        ({"policy_digest": "sha256:" + "f" * 64}, "policy differs"),
        ({"squid_conf": bundle.squid_conf + "# stale\n"}, "Squid digest differs"),
        (
            {"nftables_conf": bundle.nftables_conf + "# stale\n"},
            "nftables digest differs",
        ),
        (
            {"nftables_jump_rule": bundle.nftables_jump_rule + " "},
            "nftables digest differs",
        ),
        ({"runner_environments": ()}, "match bound identities exactly"),
    )
    for changes, message in invalid:
        with pytest.raises(ValueError, match=message):
            replace(bundle, **changes)

    environment = bundle.runner_environments[0]
    without_workload = replace(environment, workload_content=None, workload_sha256=None)
    with pytest.raises(ValueError, match="match bound listeners exactly"):
        replace(bundle, runner_environments=(without_workload,))


def test_environment_self_validates_transport_and_workload_content() -> None:
    environment = render_host_bundle(
        _policy(),
        (HostRunnerIdentityV1("starter", 2001, 3128, 3129),),
        PROXY,
        NFT,
        (WorkloadEgressPolicyV1("starter", (ExactHost("registry.invalid"),)),),
    ).runner_environments[0]
    with pytest.raises(ValueError, match="runner environment digest differs"):
        replace(environment, content=environment.content + "NO_PROXY=changed.invalid\n")
    with pytest.raises(ValueError, match="workload environment digest differs"):
        replace(
            environment,
            workload_content=(environment.workload_content or "") + "# stale\n",
        )
    with pytest.raises(ValueError, match="present together"):
        replace(environment, workload_sha256=None)


def test_runner_uid_may_reach_proxy_but_direct_web_and_quic_are_refused() -> None:
    rendered = render_host_bundle(
        _policy(), (HostRunnerIdentityV1("starter", 2001, 3128),), PROXY, NFT
    ).nftables_conf
    assert "meta skuid 2001 ip daddr 127.0.0.1 tcp dport { 3128 } accept" in rendered
    assert 'comment "runner starter direct egress refused" reject' in rendered
    assert "meta skuid 2010 meta nfproto ipv4 tcp dport 443 accept" in rendered
    assert (
        "meta skuid 2010 meta nfproto ipv6 counter comment "
        '"runner proxy public IPv6 refused" reject' in rendered
    )
    expected_refusals = {
        "runner starter cross-listener refused",
        "runner starter direct egress refused",
        "runner proxy private IPv4 refused",
        "runner proxy private IPv6 refused",
        "runner proxy public IPv6 refused",
        "runner proxy non-HTTPS refused",
    }
    for comment in expected_refusals:
        assert rendered.count(f'counter comment "{comment}" reject') == 1
    assert "flush" not in rendered


def test_workload_listener_without_a_separate_policy_refuses() -> None:
    with pytest.raises(ValueError, match="workload listener"):
        render_host_bundle(
            _policy(),
            (HostRunnerIdentityV1("starter", 2001, 3128, 3129),),
            PROXY,
            NFT,
        )


def test_listener_isolation_and_direct_grants_are_explicit() -> None:
    identities = (
        HostRunnerIdentityV1("starter", 2001, 3128, 3129),
        HostRunnerIdentityV1("observer", 2002, 3130, 3131),
    )
    workloads = (
        WorkloadEgressPolicyV1("observer", (ExactHost("observe.invalid"),)),
        WorkloadEgressPolicyV1("starter", (ExactHost("registry.invalid"),)),
    )
    bundle = render_host_bundle(
        _policy(),
        identities,
        PROXY,
        NFT,
        workloads,
        (HostDirectEgressGrantV1("observer", "100.64.0.1/32", 8200, "tcp", "wg0"),),
    )
    assert (
        "meta skuid 2001 ip daddr 127.0.0.1 tcp dport { 3128, 3129 } accept"
        in bundle.nftables_conf
    )
    assert (
        "meta skuid 2001 ip daddr 127.0.0.1 "
        "tcp dport { 3128, 3129, 3130, 3131 } counter comment "
        '"runner starter cross-listener refused" reject' in bundle.nftables_conf
    )
    assert (
        'meta skuid 2002 oifname "wg0" ip daddr 100.64.0.1/32 '
        "tcp dport 8200 accept" in bundle.nftables_conf
    )
    environments = {item.runner_name: item for item in bundle.runner_environments}
    assert "127.0.0.1:3128" in environments["starter"].content
    workload_content = environments["starter"].workload_content
    assert workload_content is not None
    assert "127.0.0.1:3129" in workload_content
    assert environments["starter"].workload_sha256 is not None
    observer_environment = environments["observer"]
    assert "no_proxy=100.64.0.1" in observer_environment.content
    assert "NO_PROXY=100.64.0.1" in observer_environment.content
    assert observer_environment.workload_content is not None
    assert "no_proxy=100.64.0.1" in observer_environment.workload_content
    assert "NO_PROXY=100.64.0.1" in observer_environment.workload_content
    for content in (
        observer_environment.content,
        observer_environment.workload_content,
    ):
        bypass_lines = [
            line
            for line in content.splitlines()
            if line.startswith(("no_proxy=", "NO_PROXY="))
        ]
        assert bypass_lines == ["no_proxy=100.64.0.1", "NO_PROXY=100.64.0.1"]
        assert all("transport.invalid" not in line for line in bypass_lines)


def test_every_local_identity_reaches_only_its_own_proxy_listeners() -> None:
    bundle = render_host_bundle(
        _policy(),
        (
            HostRunnerIdentityV1("starter", 2001, 3128, 3129),
            HostRunnerIdentityV1("observer", 2002, 3130, 3131),
        ),
        PROXY,
        NFT,
        (
            WorkloadEgressPolicyV1("starter", (ExactHost("registry.invalid"),)),
            WorkloadEgressPolicyV1("observer", (ExactHost("observe.invalid"),)),
        ),
    )
    expected = {
        2001: {3128: "accept", 3129: "accept", 3130: "reject", 3131: "reject"},
        2002: {3128: "reject", 3129: "reject", 3130: "accept", 3131: "accept"},
        2999: {3128: "reject", 3129: "reject", 3130: "reject", 3131: "reject"},
    }
    for uid, ports in expected.items():
        for port, verdict in ports.items():
            assert (
                _listener_verdict(bundle.nftables_conf, uid=uid, port=port) == verdict
            )

    unlisted_rule = (
        "  ip daddr 127.0.0.1 tcp dport { 3128, 3129, 3130, 3131 } "
        'counter comment "runner unlisted identity listener refused" reject'
    )
    assert bundle.nftables_conf.count(unlisted_rule) == 1
    assert bundle.nftables_conf.index(unlisted_rule) > bundle.nftables_conf.index(
        'comment "runner observer direct egress refused" reject'
    )
    weakened = bundle.nftables_conf.replace(unlisted_rule + "\n", "")
    assert _listener_verdict(weakened, uid=2999, port=3128) is None


def test_direct_grant_interface_is_typed_and_optional() -> None:
    assert (
        HostDirectEgressGrantV1(
            "observer", "100.64.0.1/32", 8200, "tcp", "wg0"
        ).output_interface
        == "wg0"
    )
    assert (
        HostDirectEgressGrantV1("starter", "192.0.2.1/32", 22).output_interface is None
    )
    with pytest.raises(ValueError, match="output interface"):
        HostDirectEgressGrantV1("observer", "100.64.0.1/32", 8200, "tcp", "wg0; accept")


@pytest.mark.parametrize(
    ("identities", "workloads", "grants", "message"),
    [
        (
            (
                HostRunnerIdentityV1("observer", 2001, 3128),
                HostRunnerIdentityV1("starter", 2001, 3130),
            ),
            (),
            (),
            "UIDs must be unique",
        ),
        (
            (
                HostRunnerIdentityV1("observer", 2001, 3128),
                HostRunnerIdentityV1("starter", 2002, 3128),
            ),
            (),
            (),
            "listener ports must be unique",
        ),
        (
            (HostRunnerIdentityV1("starter", 2001, 3128, 3129),),
            (),
            (),
            "match workload listeners",
        ),
        (
            (HostRunnerIdentityV1("starter", 2001, 3128),),
            (),
            (HostDirectEgressGrantV1("observer", "100.64.0.1/32", 8200),),
            "unknown runner",
        ),
    ],
)
def test_public_host_binding_enforces_identity_and_route_invariants(
    identities, workloads, grants, message
) -> None:
    with pytest.raises(ValueError, match=message):
        HostRunnerTransportSpecV1(
            "HostRunnerTransportSpec.v1",
            _policy().digest,
            _policy().adapter,
            identities,
            workloads,
            grants,
            PROXY,
            NFT,
        )

    if "UIDs" in message:
        with pytest.raises(ValueError, match="proxy and runner UIDs"):
            HostRunnerTransportSpecV1(
                "HostRunnerTransportSpec.v1",
                _policy().digest,
                _policy().adapter,
                (HostRunnerIdentityV1("starter", PROXY.uid, 3128),),
                (),
                (),
                PROXY,
                NFT,
            )


@pytest.mark.parametrize(
    "identities",
    [
        (
            HostRunnerIdentityV1("starter", 2001, 3128, 3129),
            HostRunnerIdentityV1("observer", 2002, 3130, 3129),
        ),
        (
            HostRunnerIdentityV1("starter", 2001, 3128, 3128),
            HostRunnerIdentityV1("observer", 2002, 3130, 3131),
        ),
    ],
)
def test_every_listener_port_must_be_unique(identities) -> None:
    workloads = (
        WorkloadEgressPolicyV1("observer", (ExactHost("observe.invalid"),)),
        WorkloadEgressPolicyV1("starter", (ExactHost("registry.invalid"),)),
    )
    with pytest.raises(ValueError, match="listener ports"):
        render_host_bundle(_policy(), identities, PROXY, NFT, workloads)


def test_proxy_is_confined_and_logs_only_host_and_disposition() -> None:
    bundle = render_host_bundle(
        _policy(), (HostRunnerIdentityV1("starter", 2001, 3128),), PROXY, NFT
    )
    assert "http_access deny reserved_v4" in bundle.squid_conf
    assert "http_access deny reserved_v6" in bundle.squid_conf
    assert "http_access deny numeric_connect" in bundle.squid_conf
    assert "%>rd:%>rP" in bundle.squid_conf
    for forbidden in (" squid\n", "%ru", "%rp", "%un", "Authorization"):
        assert forbidden not in bundle.squid_conf
    assert "http_proxy=http://127.0.0.1:3128" in (bundle.runner_environments[0].content)
    assert "before loopback and broad-set accepts" in bundle.nftables_jump_rule


def test_surplus_workload_policy_and_unknown_direct_grant_refuse() -> None:
    identity = (HostRunnerIdentityV1("starter", 2001, 3128),)
    with pytest.raises(ValueError, match="match workload listeners"):
        render_host_bundle(
            _policy(),
            identity,
            PROXY,
            NFT,
            (WorkloadEgressPolicyV1("starter", (ExactHost("registry.invalid"),)),),
        )
    with pytest.raises(ValueError, match="unknown runner"):
        render_host_bundle(
            _policy(),
            identity,
            PROXY,
            NFT,
            direct_grants=(HostDirectEgressGrantV1("observer", "100.64.0.1/32", 8200),),
        )


def test_host_ruleset_requires_the_jump_before_loopback_and_broad_accepts() -> None:
    bundle = render_host_bundle(
        _policy(), (HostRunnerIdentityV1("starter", 2001, 3128),), PROXY, NFT
    )
    indented_chain = bundle.nftables_conf.replace("\n", "\n  ").rstrip()
    ruleset = f"""table inet dotmac_egress {{
  {indented_chain}
  chain output {{
    type filter hook output priority filter; policy drop;
    {bundle.nftables_jump_rule}
    oifname "lo" accept
    ip daddr @mgmt_v4 accept
  }}
}}"""
    assert_nftables_placement(ruleset, bundle)
    wrong = ruleset.replace(
        f'    {bundle.nftables_jump_rule}\n    oifname "lo" accept',
        f'    oifname "lo" accept\n    {bundle.nftables_jump_rule}',
    )
    with pytest.raises(ValueError, match="after bypass anchor"):
        assert_nftables_placement(wrong, bundle)
    weakened = ruleset.replace(
        "meta skuid 2001 counter comment",
        "meta skuid 2001 tcp dport 443 counter comment",
    )
    with pytest.raises(ValueError, match="differs from rendered bytes"):
        assert_nftables_placement(weakened, bundle)


def test_core_contains_no_provider_or_cloud_branch() -> None:
    source_root = Path(__file__).parents[1] / "src" / "dotmac_runner_transport"
    text = "\n".join(
        path.read_text(encoding="utf-8") for path in sorted(source_root.rglob("*.py"))
    ).lower()
    for forbidden in (
        "github",
        "azure",
        "blob.core",
        "actions.githubusercontent",
        "if provider",
        "provider ==",
    ):
        assert forbidden not in text
