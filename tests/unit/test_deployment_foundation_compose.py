"""Tests for `dotmac_deployment_foundation.render.compose` — the pure
docker-compose renderer.

The fixture spec is built from a TOML string through
`ProductDeploymentSpec.loads`, not by constructing dataclasses by hand: that
way a mistake in this module's understanding of the loader's defaults (an
`inherits`-style surprise, a validation the parser applies that a
hand-built dataclass would silently skip) fails a test here rather than
surfacing later as a renderer that only works against spec objects nobody's
loader actually produces.

Five roles carry the fixture's coverage on purpose:

- ``web`` and ``api`` both sit behind ingress, both declare a readiness
  probe (required for that — `spec.py`'s cross-field validation refuses an
  ingress role with none), and both get the uploads volume mounted.
- ``worker`` is a background (celery) role with only a liveness probe, and
  depends on ``cache`` — the one case in this fixture where a dependency has
  NO readiness probe, so `depends_on: cache: condition: service_started` is
  exercised alongside `web`'s `depends_on: api: condition: service_healthy`.
- ``cache`` has no health probes at all — an ordinary internal role with
  nothing to prove.
- ``netrole`` declares `host_network`, `privileged` and `writable_path`
  security exceptions and no health probes, covering the exception-comment
  and no-label paths in one place.
"""

from __future__ import annotations

import dataclasses
import hashlib
import pathlib
import re
from collections.abc import Mapping

import pytest
import yaml
from dotmac_deployment_foundation.document import build_canonical_document
from dotmac_deployment_foundation.errors import SpecError
from dotmac_deployment_foundation.render.compose import (
    _scalar,
    render_compose,
    render_compose_digest,
)
from dotmac_deployment_foundation.spec import ProductDeploymentSpec

_MANIFEST_DIGEST = "sha256:" + "a" * 64
_IMAGE = f"registry.example.com/acme/app@sha256:{'b' * 64}"
_SOURCE_REVISION = "c" * 40
_OWNER_MATERIAL = "MIGRATION_DATABASE_URL"

_TOML = f"""
schema = "ProductDeploymentSpec.v1"
product = "acme"
environment = "prod"

[assembly]
manifest_path = "deploy/product.toml"
manifest_digest = "{_MANIFEST_DIGEST}"

[image]
reference = "{_IMAGE}"
source_revision = "{_SOURCE_REVISION}"

[[roles]]
code = "web"
command = ["python", "-m", "app"]
replicas = 2
depends_on = ["api"]
materials = ["DATABASE_URL"]
stop_grace_seconds = 30

[roles.resources]
cpus = "1.0"
memory = "512m"

[roles.health.live]
path = "/livez"
port = 8080

[roles.health.ready]
path = "/readyz"
port = 8080

[roles.security]
[[roles.security.exceptions]]
kind = "capability"
value = "NET_ADMIN"
justification = "needs raw sockets for the outbound connectivity probe"
approved_by = "mayoade"

[[roles]]
code = "api"
command = ["python", "-m", "app.api"]
replicas = 2
materials = ["DATABASE_URL", "CACHE_TOKEN"]
stop_grace_seconds = 25

[roles.resources]
cpus = "1.0"
memory = "512m"

[roles.health.live]
path = "/livez"
port = 4000

[roles.health.ready]
path = "/readyz"
port = 4000

[[roles]]
code = "worker"
command = ["python", "-m", "app.worker"]
replicas = 1
depends_on = ["cache"]
stop_grace_seconds = 90

[roles.resources]
cpus = "0.5"
memory = "256m"

[roles.health.live]
path = "/livez"
port = 9000

[roles.worker]
kind = "celery"
ping_command = ["celery", "inspect", "ping"]

[[roles]]
code = "cache"
command = ["cache-warmer"]
replicas = 1
stop_grace_seconds = 20

[roles.resources]
cpus = "0.25"
memory = "128m"

# Liveness only, deliberately, and NO readiness: this role is the subject
# of the tests that a role without a readiness probe gets no healthcheck
# block and is depended on with `service_started` rather than
# `service_healthy`. Every running role must declare SOME health signal,
# so "no probes at all" is no longer expressible — `migrate` is the
# service that legitimately has none.
[roles.health.live]
path = "/health/live"
port = 6379

[[roles]]
code = "netrole"
command = ["sh", "-c", "relay"]
replicas = 1
stop_grace_seconds = 15

[roles.resources]
cpus = "0.5"
memory = "128m"

# Liveness only, deliberately, and NO readiness: this role is the subject
# of the tests that a role without a readiness probe gets no healthcheck
# block and is depended on with `service_started` rather than
# `service_healthy`. Every running role must declare SOME health signal,
# so "no probes at all" is no longer expressible — `migrate` is the
# service that legitimately has none.
[roles.health.live]
path = "/health/live"
port = 9000

[roles.security]
user = "0:0"
read_only_root = false
[[roles.security.exceptions]]
kind = "host_network"
value = "true"
justification = "the DHCP relay must bind directly to the host's own NIC"
approved_by = "mayoade"
[[roles.security.exceptions]]
kind = "privileged"
value = "true"
justification = "netns manipulation needs CAP_SYS_ADMIN-adjacent syscalls"
approved_by = "mayoade"
[[roles.security.exceptions]]
kind = "writable_path"
value = "/var/lib/relay"
justification = "the DHCP lease database must persist writes on local disk"
approved_by = "mayoade"

[migration]
command = ["alembic", "upgrade", "heads"]
heads_command = ["alembic", "current"]
owner_material = "{_OWNER_MATERIAL}"
expected_heads = ["abc123"]
compatibility = "online"
lock_timeout_seconds = 300

[runtime_materials]
names = ["DATABASE_URL", "CACHE_TOKEN"]

[ingress]
host = "acme.example.com"
exposure = "public"
address_family = "dual_stack"
approval_ref = "deployment.public-exposure"
rationale_url = "https://docs.example/why"

[[ingress.routes]]
path = "/"
role = "web"
port = 8080

[[ingress.routes]]
path = "/api"
role = "api"
port = 4000

[ingress.static]
uploads = "volume"
uploads_volume = "acme_uploads"
"""


@pytest.fixture(scope="module")
def spec() -> ProductDeploymentSpec:
    return ProductDeploymentSpec.loads(_TOML, source="<test-fixture>")


@pytest.fixture(scope="module")
def rendered(spec: ProductDeploymentSpec) -> str:
    return render_compose(spec)


@pytest.fixture(scope="module")
def doc(rendered: str) -> Mapping[str, object]:
    parsed = yaml.safe_load(rendered)
    assert isinstance(parsed, dict)
    return parsed


# ── module-level predicates, shared by the real and the corrupted document ──
#
# Each of these is written to be RUN AGAINST A PARSED YAML MAPPING, not the
# raw text, and each has a companion sensitivity-proof test below that shows
# it actually fails on a corrupted document rather than passing regardless
# of what it is given.


#: The loopback literals a publication may derive, per family. Written out
#: rather than pattern-matched on a prefix: the old predicate accepted anything
#: starting `127.0.0.1:` and would have read `127.0.0.1:x` as loopback, and it
#: could not see IPv6 at all.
_LOOPBACK_LITERALS = frozenset({"127.0.0.1", "::1"})


def _all_published_ports_are_loopback(compose_doc: Mapping[str, object]) -> bool:
    """Every `ports:` entry binds a loopback address, on every family.

    Reads LONG SYNTAX, which is the only syntax this renderer emits since
    0.3.0a1. The short form put the host IP in an optional string position;
    this reads the `host_ip` FIELD, so an entry that omits it is a missing key
    rather than a mapping that silently means "every interface".
    """
    services = compose_doc["services"]
    for service in services.values():
        for entry in service.get("ports", []):
            if not isinstance(entry, Mapping):
                return False
            if entry.get("host_ip") not in _LOOPBACK_LITERALS:
                return False
    return True


def _no_service_declares_a_container_name(compose_doc: Mapping[str, object]) -> bool:
    services = compose_doc["services"]
    return all("container_name" not in service for service in services.values())


def _owner_material_only_reaches_migrate(
    compose_doc: Mapping[str, object], owner_material: str
) -> bool:
    services = compose_doc["services"]
    for name, service in services.items():
        if name == "migrate":
            continue
        if owner_material in (service.get("environment") or {}):
            return False
    return True


# ── fixture sanity ───────────────────────────────────────────────────────────


def test_the_fixture_parses_into_five_roles(spec: ProductDeploymentSpec) -> None:
    """Pins the shape the rest of this file assumes, so a fixture edit that
    silently drops a role fails here with a clear message instead of as a
    confusing failure three tests down."""
    assert spec.role_codes == ("web", "api", "worker", "cache", "netrole")


def test_the_rendered_document_is_valid_yaml(doc: Mapping[str, object]) -> None:
    assert set(doc["services"]) == {
        "migrate",
        "web",
        "api",
        "worker",
        "cache",
        "netrole",
    }


# ── 1. the one-shot migration service ───────────────────────────────────────


def test_migrate_is_a_one_shot_service_running_the_migration_command(
    doc: Mapping[str, object],
) -> None:
    migrate = doc["services"]["migrate"]
    assert migrate["restart"] == "no"
    assert migrate["command"] == ["alembic", "upgrade", "heads"]


def test_migrate_gets_only_the_owner_material_and_no_runtime_materials(
    doc: Mapping[str, object], spec: ProductDeploymentSpec
) -> None:
    migrate = doc["services"]["migrate"]
    assert set(migrate["environment"]) == {spec.migration.owner_material}
    for name in spec.runtime_materials:
        assert name not in migrate["environment"]


# ── 2. every runtime role depends on migrate, plus its own declared deps ───


def test_every_runtime_role_waits_for_migrate_to_finish(
    doc: Mapping[str, object], spec: ProductDeploymentSpec
) -> None:
    for role in spec.roles:
        depends = doc["services"][role.code]["depends_on"]
        assert depends["migrate"] == {"condition": "service_completed_successfully"}


def test_a_dependency_on_a_role_with_a_readiness_probe_waits_for_service_healthy(
    doc: Mapping[str, object],
) -> None:
    """`web` depends on `api`, and `api` declares a readiness probe — the
    only condition that means "actually able to serve"."""
    web_depends_on_api = doc["services"]["web"]["depends_on"]["api"]
    assert web_depends_on_api == {"condition": "service_healthy"}


def test_a_dependency_on_a_role_with_no_readiness_probe_only_waits_for_service_started(
    doc: Mapping[str, object],
) -> None:
    """`worker` depends on `cache`, and `cache` declares no readiness probe
    at all — waiting on `service_healthy` there would never be satisfied."""
    assert doc["services"]["worker"]["depends_on"]["cache"] == {
        "condition": "service_started"
    }


# ── 3. the owner material never reaches a runtime service ──────────────────


def test_the_owner_material_never_appears_in_a_runtime_service(
    doc: Mapping[str, object], spec: ProductDeploymentSpec
) -> None:
    assert _owner_material_only_reaches_migrate(doc, spec.migration.owner_material)


def test_the_owner_material_check_would_catch_a_regression_that_leaked_it(
    rendered: str, spec: ProductDeploymentSpec
) -> None:
    """`_owner_material_only_reaches_migrate` is the assertion the previous
    test relies on; this proves it is not vacuously true by corrupting a
    real rendered document — injecting the owner material into `web`'s
    environment block — and showing the predicate then reports False."""
    owner = spec.migration.owner_material
    marker = "      DATABASE_URL: "
    assert rendered.count(marker) >= 1
    injected = f'      {owner}: "${{{owner}:?leaked}}"\n'
    broken = rendered.replace(marker, injected + marker, 1)
    broken_doc = yaml.safe_load(broken)
    assert not _owner_material_only_reaches_migrate(broken_doc, owner)


# ── 4. loopback-only published ports, derived from ingress ─────────────────


def test_a_role_behind_an_ingress_route_publishes_its_route_port_on_loopback(
    doc: Mapping[str, object],
) -> None:
    assert doc["services"]["web"]["ports"] == [
        {"target": 8080, "published": 8080, "host_ip": "127.0.0.1", "protocol": "tcp"}
    ]
    assert doc["services"]["api"]["ports"] == [
        {"target": 4000, "published": 4000, "host_ip": "127.0.0.1", "protocol": "tcp"}
    ]


def test_a_role_with_no_ingress_route_publishes_nothing(
    doc: Mapping[str, object],
) -> None:
    for code in ("worker", "cache", "migrate"):
        assert "ports" not in doc["services"][code]


def test_the_loopback_check_would_catch_a_regression_that_bound_a_wide_open_port(
    rendered: str,
) -> None:
    """A check that only asserts the string `'127.0.0.1'` appears SOMEWHERE in
    the document passes even if a DIFFERENT port were bound to a routable
    interface — this proves the predicate inspects every published port, by
    showing it catches a corrupted document. (A non-loopback address other
    than the classic "bind all interfaces" one is used here on purpose, to
    keep this file free of that literal.)"""
    doc_ok = yaml.safe_load(rendered)
    assert _all_published_ports_are_loopback(doc_ok)
    broken = rendered.replace("host_ip: 127.0.0.1", "host_ip: 10.0.0.5", 1)
    assert not _all_published_ports_are_loopback(yaml.safe_load(broken))


def test_the_loopback_check_catches_a_publication_that_omits_host_ip_entirely(
    rendered: str,
) -> None:
    """The mutation the LONG syntax exists to make visible.

    Delete the `host_ip` field and Compose publishes on every family the host
    has — the exact shape that put two ports on the public internet over IPv6
    while their IPv4 rules read as containment. The predicate must fail on a
    MISSING key, not merely on a wrong value, because the defect is an absence.
    """
    broken = "\n".join(
        line
        for line in rendered.replace("host_ip: 127.0.0.1", "host_ip: DELETE", 1).split(
            "\n"
        )
        if "host_ip: DELETE" not in line
    )
    assert not _all_published_ports_are_loopback(yaml.safe_load(broken))


# ── 4b. a declared collector image is digest-pinned ────────────────────────
#
# `collector_image` was the ONE image reference in the schema with no pattern
# at all, while `image.reference` has carried `_DIGEST_REF` from the start. A
# mutable `otel/...:0.109.0` tag therefore reached a rendered Compose file and
# no local gate could see it — an external conformance check found it.
#
# The exemption below is the part that needs guarding. "Optional" and
# "unchecked" are one edit apart, so the permissive cases and the refusal are
# asserted together.


def _telemetry(collector: str | None) -> str:
    """The fixture descriptor with its telemetry section rewritten.

    Built from the real loader rather than a hand-made dataclass, so a
    validation this module misunderstands fails here rather than surfacing as a
    renderer that only works against objects no descriptor produces.
    """
    declared = "" if collector is None else f'\ncollector_image = "{collector}"'
    return (
        _TOML
        + f"""
[telemetry]
logs = true
metrics = true
metrics_material = "METRICS_TOKEN"{declared}
"""
    )


def test_a_declared_collector_image_must_be_digest_pinned() -> None:
    """The defect, planted. A tag makes what ran yesterday and what runs after
    the next restart two deployments with one description."""
    with pytest.raises(SpecError) as caught:
        ProductDeploymentSpec.loads(
            _telemetry("otel/opentelemetry-collector-contrib:0.109.0"),
            source="<tagged>",
        )
    assert "collector_image" in str(caught.value)


def test_a_digest_pinned_collector_image_is_accepted() -> None:
    """The negative control. A refusal that refused every value would pass the
    test above and make the field unusable."""
    spec = ProductDeploymentSpec.loads(
        _telemetry(
            "otel/opentelemetry-collector-contrib@sha256:" + "a" * 64,
        ),
        source="<pinned>",
    )
    assert spec.telemetry.collector_image.endswith("@sha256:" + "a" * 64)


def test_declaring_NO_collector_image_stays_legal() -> None:
    """The exemption, and the reason it exists rather than being tidiness.

    A consumer may declare `[telemetry]` and run no collector — `dotmac_erp`
    does exactly that, with a `[telemetry]` section and no `collector_` key of
    any kind. The rule is that a DECLARED collector image is digest-pinned, not
    that one must be declared; requiring declaration is a separate decision
    with its own migration.
    """
    spec = ProductDeploymentSpec.loads(_telemetry(None), source="<absent>")
    assert spec.telemetry.collector_image == ""


def test_an_explicitly_empty_collector_image_stays_legal() -> None:
    """`^$` is carried explicitly in the pattern rather than relying on
    `str_` returning the default before it reaches the pattern branch.

    Both spellings of "no collector" must behave identically, or the contract
    depends on a helper's internal ordering that nothing else asserts.
    """
    spec = ProductDeploymentSpec.loads(_telemetry(""), source="<empty>")
    assert spec.telemetry.collector_image == ""


def test_the_repositorys_own_descriptor_pins_its_collector_by_digest() -> None:
    """The regression this PR exists for, asserted against the real file rather
    than a fixture — a fixture cannot go stale in the way the descriptor did."""
    own = ProductDeploymentSpec.loads(
        pathlib.Path("deploy/product.toml").read_text(),
        source="deploy/product.toml",
    )
    assert "@sha256:" in own.telemetry.collector_image
    assert ":0.109.0" not in own.telemetry.collector_image


# ── 4c. the collector configuration is mounted as a DIRECTORY ──────────────
#
# A single-file bind mount pins the inode present when the container was
# created. A deploy that replaces the file (`git pull`, an atomic rename)
# writes a new inode, and the running container keeps reading the old one;
# SIGHUP re-reads the same stale inode and only recreating the container picks
# the change up. `dotmac_erp`'s vmagent kept a two-week-old configuration on
# production AND staging exactly that way — a literal environment placeholder
# that merged both deployments' metrics into one series. A directory mount
# resolves the name at open time. The directory holds ONLY the collector
# configuration, so the mount exposes nothing else this facility renders.


def _own_spec() -> ProductDeploymentSpec:
    return ProductDeploymentSpec.loads(
        pathlib.Path("deploy/product.toml").read_text(),
        source="deploy/product.toml",
    )


def _own_assets(own: ProductDeploymentSpec) -> dict[str, str]:
    from dotmac_deployment_foundation.cli import _rendered_assets, _thresholds

    return _rendered_assets(own, _thresholds("deploy/alerts/thresholds.json"))


def _bind_sources(service: Mapping[str, object]) -> list[tuple[str, str]]:
    mounts = []
    for volume in service.get("volumes", []):  # type: ignore[attr-defined]
        source, target, *_ = str(volume).split(":")
        if source.startswith("./"):
            mounts.append((source, target))
    return mounts


def test_the_collector_mounts_its_config_directory_never_the_single_file() -> None:
    own = _own_spec()
    doc = yaml.safe_load(render_compose(own, image=_IMAGE))
    collector = doc["services"]["otel-collector"]
    assets = _own_assets(own)

    assert _bind_sources(collector) == [("./otel-collector", "/etc/otelcol")]
    assert collector["command"] == ["--config=/etc/otelcol/config.yaml"]
    assert own.telemetry.collector_config_asset == "otel-collector/config.yaml"
    assert own.telemetry.collector_config_asset in assets
    # The mounted directory holds the collector configuration and nothing else.
    assert [name for name in assets if name.startswith("otel-collector/")] == [
        "otel-collector/config.yaml"
    ]


def test_no_rendered_service_bind_mounts_a_rendered_asset_as_a_single_file() -> None:
    """The general form: every rendered asset reaches a container through its
    directory. The planted single-file mount is the negative control."""
    own = _own_spec()
    assets = set(_own_assets(own))
    doc = yaml.safe_load(render_compose(own, image=_IMAGE))
    single_file = [
        (name, source)
        for name, service in doc["services"].items()
        for source, _target in _bind_sources(service)
        if source.removeprefix("./") in assets
    ]
    assert single_file == []

    planted = {"volumes": ["./otel-collector/config.yaml:/etc/otelcol/config.yaml:ro"]}
    assert [
        source
        for source, _target in _bind_sources(planted)
        if source.removeprefix("./") in assets
    ] == ["./otel-collector/config.yaml"]


def test_a_custom_collector_config_mount_mounts_its_parent_directory() -> None:
    spec = ProductDeploymentSpec.loads(
        _telemetry("otel/opentelemetry-collector-contrib@sha256:" + "a" * 64)
        + 'collector_config_mount = "/etc/otelcol-contrib/otel.yaml"\n',
        source="<custom-mount>",
    )
    doc = yaml.safe_load(render_compose(spec, image=_IMAGE))
    collector = doc["services"]["otel-collector"]

    assert spec.telemetry.collector_config_asset == "otel-collector/otel.yaml"
    assert _bind_sources(collector) == [("./otel-collector", "/etc/otelcol-contrib")]
    assert collector["command"] == ["--config=/etc/otelcol-contrib/otel.yaml"]


@pytest.mark.parametrize("mount", ["/config.yaml", "/etc/../config.yaml"])
def test_a_collector_config_mount_without_a_dedicated_directory_is_refused(
    mount: str,
) -> None:
    """Mounting the parent of `/config.yaml` would mount over `/`."""
    with pytest.raises(SpecError) as caught:
        ProductDeploymentSpec.loads(
            _telemetry(None) + f'collector_config_mount = "{mount}"\n',
            source="<root-mount>",
        )
    assert "collector_config_mount" in str(caught.value)


# ── 5. readiness drives the healthcheck; liveness becomes a label ──────────


def test_the_healthcheck_command_targets_the_readiness_path_not_the_liveness_path(
    doc: Mapping[str, object],
) -> None:
    web = doc["services"]["web"]
    test = web["healthcheck"]["test"]
    # The whole argv, not one element. The probe used to be a `CMD-SHELL` string
    # in `test[1]`; it is now `["CMD", "python", "-c", <script>]`, and an
    # index-based assertion silently moved to reading the interpreter name.
    assert test[0] == "CMD", "a shell-form probe needs a shell the image may not have"
    joined = " ".join(test)
    assert "/readyz" in joined
    assert "/livez" not in joined
    assert "wget" not in joined and "curl" not in joined, (
        "a python:*-slim runtime has neither, and a probe that cannot run "
        "reports UNHEALTHY forever rather than reporting nothing"
    )


def test_a_role_with_no_readiness_probe_gets_no_healthcheck_block(
    doc: Mapping[str, object],
) -> None:
    for code in ("worker", "cache", "netrole", "migrate"):
        assert "healthcheck" not in doc["services"][code]


def test_the_liveness_probe_is_exposed_as_a_label_never_as_the_healthcheck(
    doc: Mapping[str, object],
) -> None:
    worker = doc["services"]["worker"]
    assert "healthcheck" not in worker
    assert worker["labels"]["io.dotmac.health.live.path"] == "/livez"


def test_a_role_with_no_liveness_probe_gets_no_liveness_label(
    doc: Mapping[str, object],
) -> None:
    # `migrate` is now the only service with no probe of any kind. Every RUNNING
    # role must declare a health signal — an HTTP probe, a worker ping or a
    # scheduler tick — so a probe-less role is no longer expressible, and the
    # one-shot migration service is what is left to assert against.
    #
    # It DOES carry a `labels:` block, which it did not before deployment
    # identity existed: every service is now identifiable whether or not it has
    # a probe. The assertion is therefore about the liveness key specifically,
    # not about the presence of labels — the weaker `"labels" not in service`
    # this replaced would now be testing the identity feature by accident and
    # would have to be deleted the first time anything else added a label.
    assert "io.dotmac.health.live.path" not in doc["services"]["migrate"]["labels"]


# ── 6. resource limits on every service ─────────────────────────────────────


def test_every_service_declares_cpu_memory_and_pids_limits(
    doc: Mapping[str, object],
) -> None:
    for name, service in doc["services"].items():
        limits = service["deploy"]["resources"]["limits"]
        assert "cpus" in limits, name
        assert "memory" in limits, name
        assert isinstance(service["pids_limit"], int), name


# ── 7. log rotation on every service ────────────────────────────────────────


def test_every_service_has_bounded_json_file_log_rotation(
    doc: Mapping[str, object],
) -> None:
    for name, service in doc["services"].items():
        logging_config = service["logging"]
        assert logging_config["driver"] == "json-file", name
        assert "max-size" in logging_config["options"], name
        assert "max-file" in logging_config["options"], name


# ── 8. explicit top-level networks / volumes ────────────────────────────────


def test_the_network_is_declared_at_the_top_level_and_named_after_the_product(
    doc: Mapping[str, object],
) -> None:
    assert "acme_net" in doc["networks"]


def test_every_service_joins_the_declared_network_explicitly(
    doc: Mapping[str, object],
) -> None:
    for name, service in doc["services"].items():
        if service.get("network_mode") == "host":
            continue
        assert service["networks"] == ["acme_net"], name


def test_the_uploads_volume_is_declared_at_the_top_level(
    doc: Mapping[str, object],
) -> None:
    assert "acme_uploads" in doc["volumes"]


# ── 9. no container_name anywhere ───────────────────────────────────────────


def test_no_service_declares_a_container_name(doc: Mapping[str, object]) -> None:
    assert _no_service_declares_a_container_name(doc)


def test_the_container_name_check_would_catch_a_regression_that_added_one(
    rendered: str,
) -> None:
    """`'container_name' not in rendered` on its own passes trivially on an
    empty string, so it proves nothing about THIS renderer specifically.
    The negative control below shows the real predicate actually inspects
    the document, by injecting a `container_name` into one service."""
    assert _no_service_declares_a_container_name(yaml.safe_load(rendered))
    broken = rendered.replace(
        "  migrate:\n", "  migrate:\n    container_name: acme_migrate\n", 1
    )
    broken_doc = yaml.safe_load(broken)
    assert not _no_service_declares_a_container_name(broken_doc)


# ── 10. the image is the exact digest reference, on every service ──────────


def test_every_service_uses_the_exact_digest_image_reference(
    doc: Mapping[str, object], spec: ProductDeploymentSpec
) -> None:
    for name, service in doc["services"].items():
        assert service["image"] == spec.image, name
        assert "@sha256:" in service["image"]
        assert not service["image"].endswith(":latest")


# ── 11. security defaults, and exceptions add only what they justify ───────


def test_every_service_gets_the_hardened_security_defaults(
    doc: Mapping[str, object],
) -> None:
    for name, service in doc["services"].items():
        assert service["security_opt"] == ["no-new-privileges:true"], name
        assert service["cap_drop"] == ["ALL"], name
        assert "user" in service, name
        assert isinstance(service["read_only"], bool), name


def test_a_capability_exception_adds_only_cap_add_and_nothing_else(
    doc: Mapping[str, object],
) -> None:
    web = doc["services"]["web"]
    assert web["cap_add"] == ["NET_ADMIN"]
    assert "privileged" not in web
    assert "network_mode" not in web


def test_a_writable_path_exception_adds_a_tmpfs_entry(
    doc: Mapping[str, object],
) -> None:
    netrole = doc["services"]["netrole"]
    assert "/var/lib/relay" in netrole["tmpfs"]
    assert netrole["read_only"] is False


def test_a_privileged_or_host_network_exception_gets_an_exception_comment(
    rendered: str,
) -> None:
    """The justification has to be in the FILE a host reads, not only in the
    descriptor — so this checks the raw text, not the parsed structure
    (YAML has no native comment node)."""
    lines = rendered.splitlines()
    netrole_index = lines.index("  netrole:")
    preceding = "\n".join(lines[max(0, netrole_index - 4) : netrole_index])
    assert "# EXCEPTION: host_network" in preceding
    assert "# EXCEPTION: privileged" in preceding
    assert "approved by mayoade" in preceding


def test_a_host_network_exception_uses_network_mode_host_instead_of_networks(
    doc: Mapping[str, object],
) -> None:
    netrole = doc["services"]["netrole"]
    assert netrole["network_mode"] == "host"
    assert "networks" not in netrole


def test_a_privileged_exception_sets_privileged_true(
    doc: Mapping[str, object],
) -> None:
    assert doc["services"]["netrole"]["privileged"] is True


# ── 12. stop_grace_period from the role ─────────────────────────────────────


def test_stop_grace_period_comes_from_each_roles_own_declared_value(
    doc: Mapping[str, object], spec: ProductDeploymentSpec
) -> None:
    for role in spec.roles:
        service = doc["services"][role.code]
        assert service["stop_grace_period"] == f"{role.stop_grace_seconds}s"


# ── 13. environment carries names only, never a value ───────────────────────


def test_environment_entries_are_the_placeholder_form_not_a_value(
    doc: Mapping[str, object],
) -> None:
    web_env = doc["services"]["web"]["environment"]
    assert web_env == {"DATABASE_URL": "${DATABASE_URL:?DATABASE_URL must be set}"}


def test_a_role_with_no_materials_gets_no_environment_key_at_all(
    doc: Mapping[str, object],
) -> None:
    for code in ("worker", "cache", "netrole"):
        assert "environment" not in doc["services"][code]


# ── 14. the header comment block ─────────────────────────────────────────────


def test_the_header_names_the_product_image_revision_digest_and_schema(
    rendered: str, spec: ProductDeploymentSpec
) -> None:
    header = "\n".join(rendered.splitlines()[:10])
    assert spec.product in header
    assert spec.image in header
    assert spec.source_revision in header
    assert spec.manifest_digest in header
    assert "ProductDeploymentSpec.v1" in header
    assert "GENERATED by dotmac-deployment-foundation" in header
    assert "dotmac-deploy render" in header


# ── 15. uploads volume mounted into every ingress-served role ──────────────


def test_the_uploads_volume_is_mounted_into_every_role_behind_ingress(
    doc: Mapping[str, object],
) -> None:
    assert doc["services"]["web"]["volumes"] == ["acme_uploads:/srv/uploads"]
    assert doc["services"]["api"]["volumes"] == ["acme_uploads:/srv/uploads"]


def test_a_role_not_behind_ingress_gets_no_uploads_mount(
    doc: Mapping[str, object],
) -> None:
    for code in ("worker", "cache", "netrole", "migrate"):
        assert "volumes" not in doc["services"][code]


# ── determinism ──────────────────────────────────────────────────────────────


def test_rendering_the_same_spec_twice_produces_identical_bytes(
    spec: ProductDeploymentSpec,
) -> None:
    assert render_compose(spec) == render_compose(spec)


def test_the_digest_is_the_sha256_of_the_rendered_bytes(
    spec: ProductDeploymentSpec,
) -> None:
    rendered_bytes = render_compose(spec).encode("utf-8")
    expected = f"sha256:{hashlib.sha256(rendered_bytes).hexdigest()}"
    assert render_compose_digest(spec) == expected


def test_the_digest_is_stable_across_calls(spec: ProductDeploymentSpec) -> None:
    assert render_compose_digest(spec) == render_compose_digest(spec)


# ── the scalar quoter ─────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "value",
    ["yes", "no", "on", "off", "null", "~", "1.0", "0755"],
)
def test_yaml_boolean_and_numeric_looking_words_are_quoted(value: str) -> None:
    """Every one of these is a bareword YAML 1.1 loaders would parse as a
    bool, null, or number rather than the literal string it is."""
    assert _scalar(value) == f'"{value}"'


@pytest.mark.parametrize(
    "value",
    ["a: b", "*star", "#hash"],
)
def test_values_containing_a_yaml_indicator_character_are_quoted(value: str) -> None:
    assert _scalar(value) == f'"{value}"'


def test_the_empty_string_is_quoted() -> None:
    assert _scalar("") == '""'


def test_a_string_with_an_embedded_newline_is_quoted_and_escaped() -> None:
    assert _scalar("a\nb") == '"a\\nb"'


def test_an_ordinary_identifier_is_left_unquoted() -> None:
    """The quoter is not "always quote" — it only reaches for quotes when
    plain would be ambiguous, which is what keeps the rendered document
    readable."""
    assert _scalar("web") == "web"
    assert _scalar("json-file") == "json-file"


@pytest.mark.parametrize(
    "value",
    ["yes", "no", "on", "off", "null", "~", "1.0", "0755", "a: b", "a\nb", ""],
)
def test_every_quoted_scalar_round_trips_through_a_real_yaml_parser(value: str) -> None:
    """The proof that matters: not just that `_scalar` wraps the value in
    quotes, but that a real YAML parser reads the quoted form back as the
    exact original string."""
    document = f"key: {_scalar(value)}\n"
    assert yaml.safe_load(document) == {"key": value}


_SCALAR_SPECIAL_CHAR_RE = re.compile(r"""[:#{}\[\],&*!|>'"%@`]""")


def test_scalar_quoting_follows_the_special_char_and_ambiguity_rules() -> None:
    """A sensitivity proof for `_scalar` itself: for every character in the
    documented special-char set, a string built around it must come back
    quoted, and a plain safe string must not — so the predicate is shown to
    distinguish the two rather than quoting (or not) unconditionally."""
    for char in ":#{}[],&*!|>'\"%@`":
        value = f"x{char}y"
        assert _SCALAR_SPECIAL_CHAR_RE.search(value) is not None
        assert _scalar(value).startswith('"'), char
    assert not _scalar("plainvalue").startswith('"')


# ── the pids alias, found by the real engine ────────────────────────────────


def test_the_two_pids_keys_never_disagree(spec: ProductDeploymentSpec) -> None:
    """`pids_limit` and `deploy.resources.limits.pids` are ALIASES.

    Compose refuses a project where they carry different values — and an
    ABSENT `pids` under `limits` counts as different, so a `limits` block
    listing only cpus and memory beside a top-level `pids_limit` is rejected
    outright:

        services.app: can't set distinct values on 'pids_limit' and
        'deploy.resources.limits.pids': invalid compose project

    That is what the renderer emitted until the disposable-host rehearsal ran
    for the first time and the engine threw it out. No test in this file could
    have known: asserting a rendered key proves the key is there, never that
    the engine accepts the document. This one encodes the RULE the engine
    taught us, so the same class fails in a second rather than in a
    45-minute rehearsal.

    Observed on Docker 28.0.4 / Compose 2.38.2 (the runner the rehearsal hit
    it on) and reproduced on Docker 29.4.3 / Compose v5.1.3. This test asserts
    the INVARIANT — the two aliases agree — which holds regardless of engine;
    the parse in CI is what checks a specific engine still agrees, and it
    prints the version it used.

    Every service is checked, not just `app` — `migrate`, the managed
    dependencies and the collector all render through `_resource_lines`.
    """
    rendered = render_compose(spec, image=_IMAGE)
    doc = yaml.safe_load(rendered)

    checked = 0
    for name, service in doc["services"].items():
        legacy = service.get("pids_limit")
        nested = (
            service.get("deploy", {}).get("resources", {}).get("limits", {}).get("pids")
        )
        if legacy is None and nested is None:
            continue
        checked += 1
        assert legacy is not None and nested is not None, (
            f"service {name!r} sets only one of the two pids aliases "
            f"(pids_limit={legacy!r}, limits.pids={nested!r}); Compose treats "
            "the missing one as a disagreement and refuses the project"
        )
        assert int(legacy) == int(nested), (
            f"service {name!r} sets pids_limit={legacy} but "
            f"deploy.resources.limits.pids={nested}; these are one setting"
        )

    assert checked, (
        "no service declared a pids limit, so this test proved nothing — the "
        "fixture must render at least one resource-limited service"
    )


def test_the_rendered_collector_carries_no_uid_override(
    spec: ProductDeploymentSpec,
) -> None:
    """The rehearsal's `--user $(id -u):$(id -g)` is HARNESS-ONLY.

    The rehearsal runs its own throwaway collector with a `file` exporter
    writing into a host-mounted directory, so it must run as the identity that
    owns that directory or it cannot start. That is a property of the
    REHEARSAL, not a contract the product's collector carries: the rendered
    collector service mounts only its config, read-only, and writes no file at
    all, so it has no reason to want a uid — and pinning one here would bake a
    host's numeric identity into every product's deployment.

    This test is the one-way valve. It exists so a future reader who hits the
    permission error in the harness does not "fix" it by teaching the renderer
    to emit `user:`.
    """
    # The shared fixture declares no `collector_image`, so it renders no
    # collector service at all. Use this repository's OWN descriptor, which
    # does — the thing under test is what a real product gets.
    own = ProductDeploymentSpec.loads(
        pathlib.Path("deploy/product.toml").read_text(),
        source="deploy/product.toml",
    )
    doc = yaml.safe_load(render_compose(own, image=_IMAGE))
    collector = doc["services"].get("otel-collector")
    assert collector is not None, (
        "deploy/product.toml must declare a collector_image, or this proves " "nothing"
    )
    assert "user" not in collector, (
        "the rendered collector must not pin a uid — that is the rehearsal "
        "harness's workaround for its own writable sink, not a product contract"
    )
    writable = [
        volume
        for volume in collector.get("volumes", [])
        if not str(volume).endswith(":ro")
    ]
    assert not writable, (
        f"the collector mounts {writable} writable; a read-only config mount is "
        "what makes the uid question moot in the first place"
    )


# ── 14. deployment identity labels ──────────────────────────────────────────
#
# A controller reconciling a host has to answer "which release is this, and
# which configuration produced it" about an object it is looking at. Before
# these labels the only answers available were an image TAG (mutable — the
# reason every other reference in this facility is a digest) and a compose
# PROJECT name (an operator's `-p` flag, or the directory the file sits in).
# Reconciling against either is reconciling against a guess.
#
# The label NAMES below are written out again rather than imported from
# `render.compose`. Importing them would make these tests agree with the
# renderer by construction: renaming a constant would rename it in both places
# and every assertion would keep passing, while every controller matching on
# the old name broke. The names are a wire contract, so they are pinned as
# literals here and a rename has to be made deliberately, twice.

_IDENTITY_PREFIX = "io.dotmac.deployment"
_SCHEMA_LABEL = f"{_IDENTITY_PREFIX}.schema"
_PRODUCT_LABEL = f"{_IDENTITY_PREFIX}.product"
_ENVIRONMENT_LABEL = f"{_IDENTITY_PREFIX}.environment"
_SERVICE_NAME_LABEL = f"{_IDENTITY_PREFIX}.service.name"
_SERVICE_KIND_LABEL = f"{_IDENTITY_PREFIX}.service.kind"
_MANIFEST_DIGEST_LABEL = f"{_IDENTITY_PREFIX}.manifest.digest"
_CONFIGURATION_DIGEST_LABEL = f"{_IDENTITY_PREFIX}.configuration.digest"
_SOURCE_REVISION_LABEL = f"{_IDENTITY_PREFIX}.source.revision"

_UNIVERSAL_IDENTITY_LABELS = frozenset(
    {
        _SCHEMA_LABEL,
        _PRODUCT_LABEL,
        _ENVIRONMENT_LABEL,
        _SERVICE_NAME_LABEL,
        _SERVICE_KIND_LABEL,
    }
)
_RELEASE_IDENTITY_LABELS = frozenset(
    {
        _MANIFEST_DIGEST_LABEL,
        _CONFIGURATION_DIGEST_LABEL,
        _SOURCE_REVISION_LABEL,
    }
)
#: The kinds that run the PRODUCT's image and may therefore claim the release.
_RELEASE_BEARING_KINDS = frozenset({"release", "migration"})

#: The shared fixture declares neither a managed dependency nor a collector, so
#: it renders only release-bearing services — a document in which the "and
#: nothing else claims the release" half of the contract is vacuously true.
#: This adds one of each so both halves have a subject.
_TOML_WITH_AUXILIARY_SERVICES = (
    _TOML
    + f"""
[telemetry]
logs = true
metrics = true
metrics_material = "METRICS_TOKEN"
collector_image = "otel/opentelemetry-collector-contrib@sha256:{"e" * 64}"

[[external_dependencies]]
code = "broker"
kind = "redis"
image = "redis@sha256:{"f" * 64}"
health_probe = ["redis-cli", "ping"]
"""
)


@pytest.fixture(scope="module")
def mixed_spec() -> ProductDeploymentSpec:
    return ProductDeploymentSpec.loads(
        _TOML_WITH_AUXILIARY_SERVICES, source="<mixed-fixture>"
    )


@pytest.fixture(scope="module")
def mixed_rendered(mixed_spec: ProductDeploymentSpec) -> str:
    return render_compose(mixed_spec)


@pytest.fixture(scope="module")
def mixed_doc(mixed_rendered: str) -> Mapping[str, object]:
    parsed = yaml.safe_load(mixed_rendered)
    assert isinstance(parsed, dict)
    return parsed


def _every_service_is_identified(compose_doc: Mapping[str, object]) -> bool:
    """Every service names itself, its product and what kind of thing it is.

    `service.name` is compared against the COMPOSE KEY rather than merely
    checked for presence: a label that says `web` on the service Compose calls
    `api` is worse than no label, because it is an authoritative-looking wrong
    answer to the exact question the labels exist to answer.
    """
    services = compose_doc["services"]
    assert isinstance(services, Mapping)
    for name, service in services.items():
        labels = service.get("labels")
        if not isinstance(labels, Mapping):
            return False
        if not _UNIVERSAL_IDENTITY_LABELS <= set(labels):
            return False
        if labels[_SERVICE_NAME_LABEL] != name:
            return False
    return True


def _release_identity_is_stamped_on_exactly_the_release(
    compose_doc: Mapping[str, object],
) -> bool:
    """Release identity appears on every product-image service and nowhere else.

    Both directions matter and only one is obvious. A missing digest leaves a
    controller unable to identify a release; a digest on the Redis makes a
    container that takes no part in the release answer "yes" to "are you
    running release X", which is a wrong answer rather than a missing one.
    """
    services = compose_doc["services"]
    assert isinstance(services, Mapping)
    for service in services.values():
        labels = service.get("labels")
        if not isinstance(labels, Mapping):
            return False
        claims_release = labels.get(_SERVICE_KIND_LABEL) in _RELEASE_BEARING_KINDS
        present = set(labels) & _RELEASE_IDENTITY_LABELS
        if claims_release and present != _RELEASE_IDENTITY_LABELS:
            return False
        if not claims_release and present:
            return False
    return True


def test_the_mixed_fixture_renders_both_bearing_and_non_bearing_services(
    mixed_doc: Mapping[str, object],
) -> None:
    """The positive control for the whole section.

    Every predicate below quantifies over services, and a `for` loop over a
    document with no non-release service passes its second clause by never
    entering it. This pins that the fixture actually contains both populations,
    so a later fixture edit that drops the Redis fails HERE with a clear
    message rather than quietly hollowing out four tests.
    """
    kinds = {
        name: service["labels"][_SERVICE_KIND_LABEL]
        for name, service in mixed_doc["services"].items()
    }
    assert kinds == {
        "broker": "dependency",
        "otel-collector": "telemetry",
        "migrate": "migration",
        "web": "release",
        "api": "release",
        "worker": "release",
        "cache": "release",
        "netrole": "release",
    }


def test_every_rendered_service_carries_the_deployment_identity_labels(
    mixed_doc: Mapping[str, object],
) -> None:
    assert _every_service_is_identified(mixed_doc)


def test_the_identity_check_would_catch_a_service_that_lost_a_label(
    mixed_rendered: str,
) -> None:
    """`_every_service_is_identified` is what the previous test relies on; this
    proves it is not vacuously true by corrupting a real rendered document —
    misspelling one service's kind key, which is how a renderer regression
    would actually present — and showing the predicate then reports False."""
    marker = f"{_SERVICE_KIND_LABEL}: dependency"
    assert mixed_rendered.count(marker) == 1
    broken = mixed_rendered.replace(marker, f"{_SERVICE_KIND_LABEL}x: dependency", 1)
    assert not _every_service_is_identified(yaml.safe_load(broken))


def test_the_identity_check_would_catch_a_service_naming_the_wrong_service(
    mixed_rendered: str,
) -> None:
    """The other half of the same predicate: presence is not correctness.

    A check that only counted keys would pass a document in which every service
    claimed to be `web`, which is precisely the confident wrong answer these
    labels exist to prevent.
    """
    marker = f"{_SERVICE_NAME_LABEL}: netrole"
    assert mixed_rendered.count(marker) == 1
    broken = mixed_rendered.replace(marker, f"{_SERVICE_NAME_LABEL}: web", 1)
    assert not _every_service_is_identified(yaml.safe_load(broken))


def test_a_release_service_names_its_manifest_configuration_and_source(
    mixed_doc: Mapping[str, object], mixed_spec: ProductDeploymentSpec
) -> None:
    labels = mixed_doc["services"]["web"]["labels"]
    assert labels[_MANIFEST_DIGEST_LABEL] == mixed_spec.manifest_digest
    assert labels[_SOURCE_REVISION_LABEL] == mixed_spec.source_revision
    assert labels[_PRODUCT_LABEL] == mixed_spec.product
    assert labels[_ENVIRONMENT_LABEL] == mixed_spec.environment


def test_the_migration_service_carries_the_release_identity_too(
    mixed_doc: Mapping[str, object], mixed_spec: ProductDeploymentSpec
) -> None:
    """`migrate` runs the product's image at this revision and is the release's
    first effect on the database, so "what applied this schema change" has an
    answer on the object itself rather than in a deploy log."""
    labels = mixed_doc["services"]["migrate"]["labels"]
    assert labels[_MANIFEST_DIGEST_LABEL] == mixed_spec.manifest_digest
    assert labels[_SOURCE_REVISION_LABEL] == mixed_spec.source_revision


def test_release_identity_is_stamped_on_exactly_the_product_image_services(
    mixed_doc: Mapping[str, object],
) -> None:
    assert _release_identity_is_stamped_on_exactly_the_release(mixed_doc)


def test_the_release_identity_check_would_catch_a_stripped_digest(
    mixed_rendered: str,
) -> None:
    """Sensitivity, direction one: a release service that lost its
    configuration digest must fail the predicate."""
    marker = f"      {_CONFIGURATION_DIGEST_LABEL}: "
    assert mixed_rendered.count(marker) >= 1
    broken = mixed_rendered.replace(
        marker, f"      {_CONFIGURATION_DIGEST_LABEL}x: ", 1
    )
    assert not _release_identity_is_stamped_on_exactly_the_release(
        yaml.safe_load(broken)
    )


def test_the_release_identity_check_would_catch_a_redis_claiming_the_release(
    mixed_rendered: str, mixed_spec: ProductDeploymentSpec
) -> None:
    """Sensitivity, direction two — the one a presence-only check misses.

    A predicate that merely required the digests on release services would pass
    a document that stamped them on every container, which is the failure this
    half exists to catch.
    """
    marker = f"      {_SERVICE_KIND_LABEL}: dependency\n"
    assert mixed_rendered.count(marker) == 1
    leaked = (
        f'      {_CONFIGURATION_DIGEST_LABEL}: "{"sha256:" + "0" * 64}"\n'
        f'      {_MANIFEST_DIGEST_LABEL}: "{mixed_spec.manifest_digest}"\n'
        f"      {_SOURCE_REVISION_LABEL}: {mixed_spec.source_revision}\n"
    )
    broken = mixed_rendered.replace(marker, leaked + marker, 1)
    assert not _release_identity_is_stamped_on_exactly_the_release(
        yaml.safe_load(broken)
    )


def test_the_configuration_digest_is_the_canonical_descriptor_document_digest(
    mixed_doc: Mapping[str, object], mixed_spec: ProductDeploymentSpec
) -> None:
    """The label is the value deployment control authorizes, not a lookalike.

    Asserted as an EQUALITY against the canonical document rather than as a
    shape check, because a `sha256:<64 hex>` regex would pass any digest at all
    and the whole point is that a controller may compare this label to an
    approved plan digest with `==`. `refuse_resolved_material=False` mirrors
    the renderer: it changes no byte of the document, only whether a descriptor
    that trips the Control boundary check can be rendered at all.
    """
    expected = build_canonical_document(
        mixed_spec, refuse_resolved_material=False
    ).sha256_digest()
    labels = mixed_doc["services"]["web"]["labels"]
    assert labels[_CONFIGURATION_DIGEST_LABEL] == expected
    # A digest that happened to equal the manifest digest would make the
    # equality above true for the wrong reason — the fixture's manifest digest
    # is a constant, and a renderer that emitted it twice would pass.
    assert expected != mixed_spec.manifest_digest


def test_every_release_service_in_one_render_shares_one_configuration_digest(
    mixed_doc: Mapping[str, object],
) -> None:
    """Two services in one file disagreeing about which release they belong to
    is the failure a per-service recomputation would introduce."""
    digests = {
        service["labels"][_CONFIGURATION_DIGEST_LABEL]
        for service in mixed_doc["services"].values()
        if service["labels"][_SERVICE_KIND_LABEL] in _RELEASE_BEARING_KINDS
    }
    assert len(digests) == 1


def test_a_rollback_render_restamps_the_configuration_digest(
    mixed_doc: Mapping[str, object], mixed_spec: ProductDeploymentSpec
) -> None:
    """The digest tracks what is ACTUALLY rendered, image override included.

    This is also the positive control for the digest itself: a renderer that
    emitted a constant, or that digested the descriptor while ignoring the
    rollback image, would satisfy every other assertion in this section. During
    a rollback the file runs an image the descriptor does not name, and a label
    still reporting the descriptor's own digest would claim a configuration
    whose image field disagrees with the container beside it.
    """
    baseline = mixed_doc["services"]["web"]["labels"][_CONFIGURATION_DIGEST_LABEL]
    rolled_back = f"registry.example.com/acme/app@sha256:{'9' * 64}"
    assert rolled_back != mixed_spec.image

    rolled = yaml.safe_load(render_compose(mixed_spec, image=rolled_back))
    observed = rolled["services"]["web"]["labels"][_CONFIGURATION_DIGEST_LABEL]
    assert observed != baseline
    # And it is not merely DIFFERENT: it is the digest of this descriptor at
    # that image, so a rollback to a previously approved image reproduces that
    # image's approved digest exactly rather than minting a third value.
    assert (
        observed
        == build_canonical_document(
            dataclasses.replace(mixed_spec, image=rolled_back),
            refuse_resolved_material=False,
        ).sha256_digest()
    )


def test_the_liveness_label_shares_one_block_with_the_identity_labels(
    mixed_doc: Mapping[str, object],
) -> None:
    """A compose mapping keeps only the last of two `labels:` keys, so the
    liveness path and the identity have to be emitted together or one of them
    silently disappears. It stays OUTSIDE the identity namespace on purpose: a
    probe address is not part of a release's identity."""
    labels = mixed_doc["services"]["worker"]["labels"]
    assert labels["io.dotmac.health.live.path"] == "/livez"
    assert _UNIVERSAL_IDENTITY_LABELS <= set(labels)


def test_the_identity_labels_are_key_sorted_in_the_rendered_text(
    mixed_rendered: str,
) -> None:
    """Sorted rather than insertion-ordered, because insertion order is a
    property of the code's shape and `render --check` is a byte comparison — a
    harmless-looking refactor would otherwise fail every consumer's check."""
    blocks = re.findall(r"\n    labels:\n((?:      \S+:.*\n)+)", mixed_rendered)
    assert blocks, "no labels block was rendered, so this proved nothing"
    for entry in blocks:
        keys = [line.split(":", 1)[0].strip() for line in entry.strip().splitlines()]
        assert keys == sorted(keys)
