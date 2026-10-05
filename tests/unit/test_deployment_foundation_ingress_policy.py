"""`IngressPolicy.v1` — the typed exposure contract and its non-mutating projection.

Every refusal in this file was measured on the Dotmac fleet on 2026-08-29, and
each test names the measurement rather than the rule, because the rule without
the measurement is the version that gets relaxed in review.

## The four facts under test

1. **`ip6tables DOCKER-USER` is inert.** It is jumped only from `FORWARD`,
   while an IPv6 publish terminates on `INPUT` inside `docker-proxy`. Two
   production DROP rules were found written into it, both with zero packet
   counters, while the ports they named were open from the internet. The
   contract must refuse to emit there AND must still credit `ip6tables` with
   the containment it really has, in `INPUT`.
2. **A remapped publish needs `--ctorigdstport`.** In `DOCKER-USER` the packet
   is already DNATed, so its destination port is the CONTAINER port; a
   `--dport` rule written against the published port of a remapped publish
   matches nothing and reads, in a diff, exactly like a rule that works.
3. **An allowlist with no terminal DROP enforces nothing.** Everything the
   ACCEPTs miss falls through to the chain policy, which on a Docker host is
   ACCEPT. Check for the deny, not only the accepts.
4. **A short-form publish with no `host_ip` publishes on every family.** That
   is how two ports reached the public internet over IPv6 while their IPv4
   rules read as containment, and it is why long syntax is mandatory.

## Fixture shape

Descriptors are built from TOML through `ProductDeploymentSpec.loads` rather
than by constructing dataclasses, for the reason the compose tests give: a
hand-built dataclass skips every validation the parser applies, so a test
written that way proves the renderer works against objects no loader produces.

`_descriptor()` composes a MINIMAL valid descriptor and takes the publication
and ingress fragments as text, so a test that is about one refusal shows only
the lines that cause it.
"""

from __future__ import annotations

import dataclasses
import json
import tomllib
from pathlib import Path

import pytest
import yaml
from dotmac_deployment_foundation import ingress
from dotmac_deployment_foundation.errors import SpecError
from dotmac_deployment_foundation.policy import (
    build_edge_plan,
    build_firewall_plan,
    ingress_policy_document,
    public_endpoint_tokens,
)
from dotmac_deployment_foundation.render.compose import render_compose
from dotmac_deployment_foundation.spec import ProductDeploymentSpec
from dotmac_deployment_foundation.version import VERSION

PACKAGE_DIR = (
    Path(__file__).resolve().parents[2] / "packages" / "dotmac-deployment-foundation"
)

_MANIFEST_DIGEST = "sha256:" + "a" * 64
_IMAGE = f"registry.example.com/acme/app@sha256:{'b' * 64}"
_SOURCE_REVISION = "c" * 40

_BASE = f"""
schema = "ProductDeploymentSpec.v1"
product = "acme"
environment = "prod"

[assembly]
manifest_path = "deploy/product.toml"
manifest_digest = "{_MANIFEST_DIGEST}"

[image]
reference = "{_IMAGE}"
source_revision = "{_SOURCE_REVISION}"

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
"""


def _descriptor(*, ports: str = "", extra: str = "") -> str:
    return _BASE + ports + extra


def _load(*, ports: str = "", extra: str = "") -> ProductDeploymentSpec:
    return ProductDeploymentSpec.loads(
        _descriptor(ports=ports, extra=extra), source="<ingress-policy-fixture>"
    )


def _refusal(*, ports: str = "", extra: str = "") -> str:
    with pytest.raises(SpecError) as caught:
        _load(ports=ports, extra=extra)
    return str(caught.value)


LOOPBACK_DUAL = """
[[roles.ports]]
container = 8003
host = 8003
protocol = "tcp"
exposure = "loopback"
address_family = "dual_stack"
"""

PRIVATE_DUAL = """
[[roles.ports]]
container = 8200
host = 8200
protocol = "tcp"
exposure = "private"
address_family = "dual_stack"
tls = "mtls"
authentication = "mtls"
source_set = "openbao-clients"
telemetry = true
"""

NONE_PUBLICATION = """
[[roles.ports]]
container = 5432
host = 9001
protocol = "tcp"
exposure = "none"
address_family = "ipv4"
"""

EDGE = """
[ingress]
host = "acme.example.com"
exposure = "public"
address_family = "dual_stack"
approval_ref = "deployment.public-exposure"
rationale_url = "https://docs.example/why-acme-is-public"

[[ingress.routes]]
path = "/"
role = "app"
port = 8003
"""


# ── 1. the vocabulary is mandatory, and `bind` is fatal ─────────────────────


def test_a_publication_that_declares_no_exposure_is_refused() -> None:
    message = _refusal(
        ports="""
[[roles.ports]]
container = 8003
host = 8003
address_family = "ipv4"
"""
    )
    assert "'exposure' is missing" in message


def test_a_publication_that_declares_no_address_family_is_refused() -> None:
    """The defect the whole contract exists for.

    Saying nothing about IPv6 does not produce no IPv6; it produces a second
    `docker-proxy -host-ip ::` and a rule set that cannot reach it.
    """
    message = _refusal(
        ports="""
[[roles.ports]]
container = 8003
host = 8003
exposure = "loopback"
"""
    )
    assert "'address_family' is missing" in message


def test_the_removed_bind_field_fails_loudly_rather_than_being_ignored() -> None:
    """An ignored `bind` reads, in a diff, exactly like an honoured one.

    This is the one removal a live consumer is guaranteed to hit, so it gets a
    message naming the replacement rather than the generic unknown-key error.
    """
    message = _refusal(
        ports="""
[[roles.ports]]
container = 8003
host = 8003
bind = "127.0.0.1"
"""
    )
    assert "`bind` was removed in 0.3.0a1" in message
    assert "exposure" in message
    assert "address_family" in message


@pytest.mark.parametrize("value", ["internal", "external", "private_ipv6", ""])
def test_an_exposure_outside_the_closed_vocabulary_is_refused(value: str) -> None:
    message = _refusal(
        ports=f"""
[[roles.ports]]
container = 8003
host = 8003
exposure = "{value}"
address_family = "ipv4"
"""
    )
    assert "exposure must be one of" in message


@pytest.mark.parametrize("value", ["ipv46", "dual", "both", "any"])
def test_an_address_family_outside_the_closed_vocabulary_is_refused(
    value: str,
) -> None:
    message = _refusal(
        ports=f"""
[[roles.ports]]
container = 8003
host = 8003
exposure = "loopback"
address_family = "{value}"
"""
    )
    assert "address_family must be one of" in message


# ── 2. what each exposure MEANS ─────────────────────────────────────────────


def test_none_emits_no_publication_at_all() -> None:
    """Not "published where nobody looks" — no socket on the host.

    ERP's Redis on 6391 and its Postgres on 9001 are this case, and the reason
    it is a first-class word rather than an omission is that an omission cannot
    be reviewed.
    """
    spec = _load(ports=NONE_PUBLICATION)
    document = yaml.safe_load(render_compose(spec))
    assert "ports" not in document["services"]["app"]
    assert spec.roles[0].ports[0].families == ()


def test_loopback_renders_the_derived_literal_for_every_declared_family() -> None:
    spec = _load(ports=LOOPBACK_DUAL)
    document = yaml.safe_load(render_compose(spec))
    assert document["services"]["app"]["ports"] == [
        {"target": 8003, "published": 8003, "host_ip": "127.0.0.1", "protocol": "tcp"},
        {"target": 8003, "published": 8003, "host_ip": "::1", "protocol": "tcp"},
    ]


def test_a_routable_bind_is_a_required_variable_with_no_default() -> None:
    """No default, deliberately.

    A default is precisely what lets a misleading value hide the effective
    bind: `"${VM_BIND:-127.0.0.1:}8428:8428"` reads as loopback and becomes a
    wildcard the moment somebody sets `VM_BIND` without the trailing colon. An
    operator who supplies nothing must get a refusal from Compose, not a guess.
    """
    spec = _load(ports=PRIVATE_DUAL)
    document = yaml.safe_load(render_compose(spec))
    host_ips = [entry["host_ip"] for entry in document["services"]["app"]["ports"]]
    assert host_ips == [
        "${APP_8200_BIND_IPV4:?required}",
        "${APP_8200_BIND_IPV6:?required}",
    ]
    assert not any(":-" in value for value in host_ips)


def test_private_and_public_must_declare_tls_explicitly() -> None:
    message = _refusal(
        ports="""
[[roles.ports]]
container = 8200
host = 8200
exposure = "private"
address_family = "ipv4"
source_set = "openbao-clients"
"""
    )
    assert "must declare `tls` explicitly" in message


def test_private_and_public_must_name_a_source_set() -> None:
    message = _refusal(
        ports="""
[[roles.ports]]
container = 8200
host = 8200
exposure = "private"
address_family = "ipv4"
tls = "mtls"
"""
    )
    assert "must declare a named `source_set`" in message


def test_public_requires_tls_authentication_telemetry_and_an_approval_locator() -> None:
    message = _refusal(
        ports="""
[[roles.ports]]
container = 8443
host = 8443
exposure = "public"
address_family = "ipv4"
tls = "mtls"
source_set = "partner-gateways"
"""
    )
    assert "approval_ref" in message
    assert "authentication" in message
    assert "rationale_url" in message
    assert "telemetry" in message


def test_public_cannot_declare_tls_none() -> None:
    message = _refusal(
        ports="""
[[roles.ports]]
container = 8443
host = 8443
exposure = "public"
address_family = "ipv4"
tls = "none"
authentication = "mtls"
source_set = "partner-gateways"
telemetry = true
approval_ref = "deployment.public-exposure"
rationale_url = "https://docs.example/why"
"""
    )
    assert 'cannot declare tls = "none"' in message


def test_none_cannot_carry_controls_for_a_socket_that_does_not_exist() -> None:
    message = _refusal(
        ports="""
[[roles.ports]]
container = 5432
host = 9001
exposure = "none"
address_family = "ipv4"
source_set = "operations-vpn"
"""
    )
    assert "emits no publication at all" in message


def test_loopback_cannot_carry_a_source_set() -> None:
    """A source set on a loopback bind implies a containment nothing consults."""
    message = _refusal(
        ports="""
[[roles.ports]]
container = 8003
host = 8003
exposure = "loopback"
address_family = "ipv4"
source_set = "operations-vpn"
"""
    )
    assert "has nothing to filter" in message


def test_an_approval_locator_on_a_non_public_exposure_is_refused() -> None:
    """Otherwise a locator becomes decoration: present, and checked by nothing."""
    message = _refusal(
        ports="""
[[roles.ports]]
container = 8200
host = 8200
exposure = "private"
address_family = "ipv4"
tls = "mtls"
source_set = "openbao-clients"
approval_ref = "deployment.public-exposure"
"""
    )
    assert "belong to a public exposure" in message


# ── 3. named source sets only: no product IP literal, anywhere ──────────────


@pytest.mark.parametrize(
    "literal",
    ["10.0.0.0/8", "192.168.1.10", "2001:db8::/32", "::1", "203.0.113.0/24"],
)
def test_a_source_set_that_is_an_address_literal_is_refused(literal: str) -> None:
    """Foundation renders and enforces; it never decides membership.

    An address in a product descriptor is topology in Git. It differs per
    environment, it goes stale with nothing failing, and it makes the product
    repository the wrong owner of a fact deployment control already resolves.
    """
    message = _refusal(
        ports=f"""
[[roles.ports]]
container = 8200
host = 8200
exposure = "private"
address_family = "ipv4"
tls = "mtls"
source_set = "{literal}"
"""
    )
    assert "is an address literal" in message


def test_a_trusted_proxy_that_is_a_cidr_is_refused() -> None:
    """`trusted_proxies` decides whose `X-Forwarded-For` is believed.

    A stale CIDR there silently makes a spoofed header authoritative, which is
    the worst possible field to hold environment topology.
    """
    message = _refusal(
        extra="""
[ingress]
host = "acme.example.com"
exposure = "public"
address_family = "ipv4"
approval_ref = "deployment.public-exposure"
rationale_url = "https://docs.example/why"
trusted_proxies = ["10.0.0.0/8"]

[[ingress.routes]]
path = "/"
role = "app"
port = 8003
"""
    )
    assert "is an address literal" in message


def test_a_named_source_set_survives_into_the_rendered_edge_as_a_token() -> None:
    from dotmac_deployment_foundation.render.nginx import render_nginx

    spec = _load(
        extra="""
[ingress]
host = "acme.example.com"
exposure = "public"
address_family = "ipv4"
approval_ref = "deployment.public-exposure"
rationale_url = "https://docs.example/why"
trusted_proxies = ["edge-fleet"]

[[ingress.routes]]
path = "/"
role = "app"
port = 8003
"""
    )
    assert "set_real_ip_from @SOURCE_SET:edge-fleet@;" in render_nginx(spec)


# ── 4. source-level admission and semantic normalization ────────────────────


# The v4 wildcard is built rather than written. `S104` flags the literal
# anywhere it appears — including in a test whose whole purpose is to prove the
# value is REFUSED — and a `noqa` on a security rule is the shape that gets
# copied into code where it matters.
_WILDCARDS = (("ipv4", ".".join(["0"] * 4)), ("ipv6", "::"), ("ipv6", "[::]"))


@pytest.mark.parametrize(("family", "wildcard"), _WILDCARDS)
def test_admission_refuses_a_wildcard_bind(family: str, wildcard: str) -> None:
    with pytest.raises(SpecError) as caught:
        ingress.admit_bind_address(
            wildcard, family=family, exposure="private", where="<test>"
        )
    assert "wildcard" in str(caught.value)


@pytest.mark.parametrize(
    "expression",
    ["${APP_8200_BIND_IPV4:?required}", "${VM_BIND:-127.0.0.1:}", "$HOST_IP"],
)
def test_admission_refuses_an_unresolved_expression(expression: str) -> None:
    """Admission runs AFTER substitution, so an expression here means it never
    happened — and an unresolved default is how a loopback-looking string
    becomes a wildcard."""
    with pytest.raises(SpecError) as caught:
        ingress.admit_bind_address(
            expression, family="ipv4", exposure="private", where="<test>"
        )
    assert "unresolved expression" in str(caught.value)


def test_admission_refuses_a_hostname() -> None:
    with pytest.raises(SpecError) as caught:
        ingress.admit_bind_address(
            "bao.internal", family="ipv4", exposure="private", where="<test>"
        )
    assert "not an IP literal" in str(caught.value)


def test_admission_refuses_a_bind_whose_family_disagrees_with_the_declaration() -> None:
    with pytest.raises(SpecError) as caught:
        ingress.admit_bind_address(
            "fd00::5", family="ipv4", exposure="private", where="<test>"
        )
    assert "declares ipv4" in str(caught.value)


def test_admission_refuses_an_ipv4_mapped_ipv6_address() -> None:
    """One socket answering on both families makes the declaration
    unfalsifiable, which is worse than a wrong declaration."""
    with pytest.raises(SpecError) as caught:
        ingress.admit_bind_address(
            "::ffff:127.0.0.1", family="ipv6", exposure="loopback", where="<test>"
        )
    assert "IPv4-mapped" in str(caught.value)


def test_admission_refuses_a_private_exposure_that_resolved_to_loopback() -> None:
    """The failure direction nobody guards: a hardening that is an outage."""
    with pytest.raises(SpecError) as caught:
        ingress.admit_bind_address(
            "127.0.0.1", family="ipv4", exposure="private", where="<test>"
        )
    assert "not a hardening" in str(caught.value)


def test_normalization_makes_two_spellings_of_one_address_one_string() -> None:
    """`::1` and `0:0:0:0:0:0:0:1` are one socket and two strings, and a digest
    computed over the second does not equal a digest computed over the first."""
    assert (
        ingress.normalize_address("0:0:0:0:0:0:0:1", where="<test>").address
        == ingress.normalize_address("::1", where="<test>").address
        == "::1"
    )


def test_admission_accepts_the_addresses_it_is_supposed_to_accept() -> None:
    """The negative control. Every test above is a refusal, and a refuser that
    refuses everything passes all of them."""
    for value, family, exposure in (
        ("127.0.0.1", "ipv4", "loopback"),
        ("::1", "ipv6", "loopback"),
        ("10.4.2.9", "ipv4", "private"),
        ("fd00::5", "ipv6", "private"),
    ):
        admitted = ingress.admit_bind_address(
            value, family=family, exposure=exposure, where="<test>"
        )
        assert admitted.family == family
        assert not admitted.is_wildcard


# ── 5. the provider capability matrix fails closed ──────────────────────────


def test_a_raw_socket_may_not_claim_an_authentication_no_provider_enforces() -> None:
    """An HTTP edge can check a bearer token. A raw published socket cannot.

    A control nothing enforces is worse than an absent one, because it reads as
    present in every review after this one.
    """
    message = _refusal(
        ports="""
[[roles.ports]]
container = 8200
host = 8200
exposure = "private"
address_family = "ipv4"
tls = "none"
authentication = "bearer"
source_set = "openbao-clients"
"""
    )
    assert "can enforce it" in message


def test_a_self_terminating_service_may_claim_mtls() -> None:
    """The negative control for the check above: a capability that IS real must
    be expressible, or the matrix is just a blanket refusal."""
    spec = _load(ports=PRIVATE_DUAL)
    publication = spec.roles[0].ports[0]
    assert publication.authentication == "mtls"
    assert "service_tls" in ingress.available_providers(
        families=publication.families, protocol="tcp", tls=publication.tls
    )


def test_a_public_udp_publication_is_refused() -> None:
    """No provider in the matrix terminates TLS or authenticates a UDP peer, so
    the controls `public` requires cannot exist for it."""
    message = _refusal(
        ports="""
[[roles.ports]]
container = 514
host = 514
protocol = "udp"
exposure = "public"
address_family = "ipv4"
tls = "passthrough"
authentication = "mtls"
source_set = "partner-gateways"
telemetry = true
approval_ref = "deployment.public-exposure"
rationale_url = "https://docs.example/why"
"""
    )
    # Two refusals, reported together. The first is what actually bites for a
    # UDP publication — `service_tls` is TCP-only, so nothing can enforce the
    # mTLS a public exposure requires — and the second names the reason
    # directly. A descriptor with three unenforceable claims should see three,
    # not one per CI run.
    assert "can enforce it" in message
    assert 'exposure = "public" over UDP' in message


def test_every_provider_row_states_which_families_and_protocols_it_covers() -> None:
    for code, capability in ingress.PROVIDERS.items():
        assert capability.code == code
        assert capability.families <= frozenset(ingress.FAMILIES)
        assert capability.protocols <= frozenset({"tcp", "udp"})
        assert capability.authentications <= frozenset(ingress.AUTHENTICATIONS)
        assert capability.note.strip()


def test_the_matrix_records_ip6tables_as_able_to_filter_and_the_chain_as_not() -> None:
    """Both halves of the measured fact, in the two places they belong.

    Recording the PROVIDER as incapable would close a working control;
    recording the CHAIN as capable would open a port. The finding is about the
    chain, so the refusal is about the chain.
    """
    assert ingress.PROVIDERS["ip6tables"].enforces_source_policy is True
    assert ingress.FILTER_CHAIN["ipv6"] == ingress.INPUT_CHAIN
    with pytest.raises(SpecError) as caught:
        ingress.refuse_inert_chain("ipv6", ingress.DOCKER_USER_CHAIN, where="<test>")
    assert "INERT" in str(caught.value)


def test_an_ipv4_rule_in_docker_user_is_not_refused() -> None:
    """The sensitivity proof for the refusal above: it must bite on v6 in
    DOCKER-USER and on nothing else, or it is a blanket ban wearing a reason."""
    ingress.refuse_inert_chain("ipv4", ingress.DOCKER_USER_CHAIN, where="<test>")
    ingress.refuse_inert_chain("ipv6", ingress.INPUT_CHAIN, where="<test>")


# ── 6. the derived firewall plan ────────────────────────────────────────────


def test_every_allowlist_ends_in_a_terminal_drop() -> None:
    """An allowlist whose last rule is an ACCEPT enforces nothing: what the
    ACCEPTs miss falls through to the chain policy, ACCEPT on a Docker host.

    Measured twice on this fleet, and read as containment both times.
    """
    rules = build_firewall_plan(_load(ports=PRIVATE_DUAL))
    assert rules
    for family in ingress.FAMILIES:
        per_family = [rule for rule in rules if rule.family == family]
        assert per_family[-1].action == "DROP"
        assert per_family[-1].terminal is True
        assert per_family[-1].source_set == ""


def test_the_ipv4_rule_matches_ctorigdstport_and_the_ipv6_rule_matches_dport() -> None:
    """Post-DNAT in DOCKER-USER the destination port is the CONTAINER port, so
    a `--dport` rule against a remapped publish matches nothing. On the IPv6
    INPUT path nothing DNATs, so `--dport` is both correct and the only match
    available."""
    rules = build_firewall_plan(
        _load(
            ports="""
[[roles.ports]]
container = 5432
host = 9001
protocol = "tcp"
exposure = "private"
address_family = "dual_stack"
tls = "none"
source_set = "operations-vpn"
"""
        )
    )
    ipv4 = [rule.render() for rule in rules if rule.family == "ipv4"]
    ipv6 = [rule.render() for rule in rules if rule.family == "ipv6"]
    assert all("--ctorigdstport 9001" in rule for rule in ipv4)
    assert not any("--dport" in rule for rule in ipv4)
    # 5432 is the container port. It must not appear: matching it would filter
    # traffic to whatever else happens to use 5432, and not this publication.
    assert not any("5432" in rule for rule in ipv4 + ipv6)
    assert all("--dport 9001" in rule for rule in ipv6)
    assert not any("ctorigdstport" in rule for rule in ipv6)


def test_no_rule_is_derived_for_a_loopback_or_absent_publication() -> None:
    assert build_firewall_plan(_load(ports=LOOPBACK_DUAL)) == ()
    assert build_firewall_plan(_load(ports=NONE_PUBLICATION)) == ()


def test_the_rendered_rule_carries_a_source_set_TOKEN_never_an_address() -> None:
    rules = build_firewall_plan(_load(ports=PRIVATE_DUAL))
    accepts = [rule for rule in rules if rule.action == "ACCEPT"]
    assert accepts
    for rule in accepts:
        assert "@SOURCE_SET:openbao-clients@" in rule.render()


# ── 7. the ingress section of the canonical document ───────────────────────
#
# The DIGEST is not tested here. `DeploymentDescriptorDocument.v1` owns the one
# canonical document and the one digest taken over it — see
# `test_deployment_foundation_canonical_document.py`. Two digests over
# overlapping content would be two answers to "what was signed".


def test_the_ingress_section_names_its_own_schema() -> None:
    document = ingress_policy_document(_load(ports=PRIVATE_DUAL))
    assert document["schema"] == "IngressPolicy.v1"


def test_the_declared_version_matches_the_distribution_metadata() -> None:
    pyproject = tomllib.loads(
        (PACKAGE_DIR / "pyproject.toml").read_text(encoding="utf-8")
    )
    assert pyproject["tool"]["poetry"]["version"] == VERSION


def test_the_ingress_section_carries_no_resolved_bind_address() -> None:
    """A bind MATERIAL name is in; a bind ADDRESS is not.

    Deployment control binds this descriptor's digest into an independently
    signed authorization and resolves the private material separately. The
    moment a resolved address can reach that digest, the two owners have
    collapsed into one — so the section carries the variable NAME and the
    renderer alone produces the address.
    """
    document = ingress_policy_document(_load(ports=PRIVATE_DUAL))
    binds = document["publications"][0]["binds"]
    assert [entry["material"] for entry in binds] == [
        "APP_8200_BIND_IPV4",
        "APP_8200_BIND_IPV6",
    ]
    assert all("host_ip" not in entry for entry in binds)


def test_a_loopback_publication_needs_no_bind_material_at_all() -> None:
    """Its literal is derivable from exposure plus family plus the facility
    version, and all three are inside the digest."""
    document = ingress_policy_document(_load(ports=LOOPBACK_DUAL))
    binds = document["publications"][0]["binds"]
    assert [entry["material"] for entry in binds] == ["", ""]


def test_the_ingress_section_is_stable_across_repeated_projection() -> None:
    spec = _load(ports=PRIVATE_DUAL + NONE_PUBLICATION)
    assert ingress_policy_document(spec) == ingress_policy_document(spec)


def test_the_section_materializes_every_default_rather_than_omitting_it() -> None:
    """Digesting the raw TOML would let a change to a parser default alter
    running behaviour under an unchanged digest, so defaults are materialized
    and nothing is null."""
    document = ingress_policy_document(_load(ports=LOOPBACK_DUAL))
    publication = document["publications"][0]
    for key in ("tls", "authentication", "source_set", "approval_ref", "telemetry"):
        assert key in publication
        assert publication[key] is not None


def test_the_section_survives_a_json_round_trip_unchanged() -> None:
    """The property the canonicalization rules exist for: a reader months later
    has only the stored JSON, and must be able to re-derive the same digest."""
    document = ingress_policy_document(_load(ports=PRIVATE_DUAL))
    assert json.loads(json.dumps(document)) == document


def test_the_edge_section_is_materialized_even_when_there_is_no_edge() -> None:
    document = ingress_policy_document(_load(ports=LOOPBACK_DUAL))
    assert document["edge"]["declared"] is False
    assert document["edge"]["host"] == ""


# ── 8. endpoint tokens: derived, and compared by set equality ───────────────


def test_a_public_endpoint_token_is_derived_from_the_publication() -> None:
    spec = _load(extra=EDGE)
    tokens = public_endpoint_tokens(spec)
    assert tokens == (
        "v1|acme|prod|edge|tcp|ipv4|443|public",
        "v1|acme|prod|edge|tcp|ipv4|80|public",
        "v1|acme|prod|edge|tcp|ipv6|443|public",
        "v1|acme|prod|edge|tcp|ipv6|80|public",
    )


def test_no_public_endpoint_is_reported_when_nothing_is_public() -> None:
    """The sensitivity proof for the sensitivity marker itself: a function that
    always returned a non-empty set would make every plan look approval-worthy
    and the signal worthless."""
    assert public_endpoint_tokens(_load(ports=PRIVATE_DUAL)) == ()
    assert public_endpoint_tokens(_load(ports=LOOPBACK_DUAL)) == ()


PUBLIC_MTLS = """
[[roles.ports]]
container = 9443
host = 9443
protocol = "tcp"
exposure = "public"
address_family = "ipv4"
tls = "mtls"
authentication = "mtls"
source_set = "partner-gateways"
telemetry = true
approval_ref = "deployment.public-exposure"
rationale_url = "https://docs.example/why-9443-is-public"
"""


def test_adding_a_second_public_endpoint_changes_the_token_SET() -> None:
    """Why coverage is set equality and not containment.

    Containment would let a plan that adds a SECOND public port inherit the
    first one's approval: the approved set is still a subset of the proposed
    one, so a containment check passes while a new listener reaches the
    internet unapproved.
    """
    one = set(public_endpoint_tokens(_load(extra=EDGE)))
    two = set(public_endpoint_tokens(_load(ports=PUBLIC_MTLS, extra=EDGE)))
    assert one < two, "the second publication must add tokens"
    assert one <= two, "containment PASSES here, which is exactly the problem"
    assert one != two, "set equality is what catches it"
    assert "v1|acme|prod|app|tcp|ipv4|9443|public" in two - one


def test_an_added_route_is_not_an_added_listener() -> None:
    """The other half: a route is a location block on a listener that already
    exists, so it must NOT invent an endpoint token nothing listens on."""
    one = set(public_endpoint_tokens(_load(extra=EDGE)))
    two = set(
        public_endpoint_tokens(
            _load(
                extra=EDGE
                + """
[[ingress.routes]]
path = "/admin"
role = "app"
port = 8003
"""
            )
        )
    )
    assert one == two


# ── 9. the edge owns its port, and cannot be bypassed ───────────────────────


def test_a_role_may_not_also_publish_a_port_its_edge_already_routes_to() -> None:
    """An edge that can be bypassed is decoration.

    The edge publishes its upstream on loopback itself, so a second declaration
    of the same container port is the one that decides whether the application
    is ALSO reachable directly.
    """
    message = _refusal(ports=LOOPBACK_DUAL, extra=EDGE)
    assert "AROUND the edge" in message


def test_an_edge_declares_its_own_exposure_and_families() -> None:
    spec = _load(extra=EDGE)
    assert spec.ingress is not None
    assert spec.ingress.exposure == "public"
    assert spec.ingress.families == ("ipv4", "ipv6")


def test_an_edge_that_publishes_nothing_is_refused_rather_than_rendered() -> None:
    message = _refusal(
        extra=EDGE.replace('exposure = "public"', 'exposure = "none"')
        .replace('approval_ref = "deployment.public-exposure"\n', "")
        .replace('rationale_url = "https://docs.example/why-acme-is-public"\n', "")
    )
    assert "every route it declares is unreachable" in message


def test_the_edge_plan_names_no_provider() -> None:
    """Provider-neutral is checkable: no field of the plan may carry an
    implementation's name, or a second implementation is a second contract."""
    plan = build_edge_plan(_load(extra=EDGE))
    assert plan
    rendered = " ".join(
        str(value)
        for endpoint in plan
        for value in dataclasses.asdict(endpoint).values()
    ).lower()
    for provider_name in ("nginx", "caddy", "traefik", "haproxy", "envoy"):
        assert provider_name not in rendered


# ── 10. one host socket has one owner ───────────────────────────────────────


def test_two_services_cannot_publish_the_same_host_socket() -> None:
    message = _refusal(
        ports=LOOPBACK_DUAL,
        extra="""
[[external_dependencies]]
code = "cache"
kind = "redis"
image = "redis@sha256:"""
        + "d" * 64
        + """"
health_probe = ["redis-cli", "ping"]

[[external_dependencies.ports]]
container = 6379
host = 8003
protocol = "tcp"
exposure = "loopback"
address_family = "ipv4"
""",
    )
    assert "duplicate host socket" in message


def test_a_managed_dependency_publication_goes_through_the_same_contract() -> None:
    """ERP's Redis on 6391 and its Postgres on 9001 are DEPENDENCY
    publications. A contract that only governed `[[roles.ports]]` would have
    left out the exact two ports it was built to close."""
    spec = _load(
        extra="""
[[external_dependencies]]
code = "cache"
kind = "redis"
image = "redis@sha256:"""
        + "d" * 64
        + """"
health_probe = ["redis-cli", "ping"]

[[external_dependencies.ports]]
container = 6379
host = 6391
protocol = "tcp"
exposure = "none"
address_family = "ipv4"
"""
    )
    assert [code for code, _ in spec.publications] == ["cache"]
    document = yaml.safe_load(render_compose(spec))
    assert "ports" not in document["services"]["cache"]


# ── 11. the fleet's real targets, expressed end to end ──────────────────────


def test_the_measured_fleet_targets_are_all_expressible() -> None:
    """The six shapes this contract was commissioned to express.

    ERP app 8003 and SON 8003/8004 as loopback dual-stack; ERP Redis 6391 and
    Postgres 9001 as `none`; OpenBao 8200 as private dual-stack mTLS behind a
    named client source set; and a public web application with NO direct
    publication, its edge owning ingress.
    """
    spec = _load(
        ports=LOOPBACK_DUAL.replace("8003", "8004") + PRIVATE_DUAL,
        extra="""
[[external_dependencies]]
code = "cache"
kind = "redis"
image = "redis@sha256:"""
        + "d" * 64
        + """"
health_probe = ["redis-cli", "ping"]

[[external_dependencies.ports]]
container = 6379
host = 6391
protocol = "tcp"
exposure = "none"
address_family = "ipv4"
"""
        + EDGE,
    )
    document = ingress_policy_document(spec)
    by_port = {entry["host_port"]: entry for entry in document["publications"]}
    assert by_port[8004]["exposure"] == "loopback"
    assert by_port[8004]["families"] == ["ipv4", "ipv6"]
    assert by_port[6391]["exposure"] == "none"
    assert by_port[6391]["families"] == []
    assert by_port[8200]["exposure"] == "private"
    assert by_port[8200]["source_set"] == "openbao-clients"
    assert by_port[8200]["tls"] == "mtls"
    # The public web application publishes NOTHING of its own; the edge does.
    assert 8003 not in by_port
    assert document["edge"]["exposure"] == "public"
    assert public_endpoint_tokens(spec)
