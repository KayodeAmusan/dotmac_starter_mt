"""Render a deterministic docker-compose document from a deployment spec.

`ProductDeploymentSpec` is the one thing a product declares (see `spec.py`);
this module is one of the several pure renderers that turn it into an actual
deployment artifact — in this case the docker-compose file a host runs. It
never asks a question the descriptor did not already answer: image, ports,
resource limits, security posture, and dependency order are all DERIVED, so
two products built from the same descriptor cannot disagree about the
resulting compose file, and a descriptor left unchanged renders byte-identical
output no matter when or how many times it is rendered.

## Why hand-rolled YAML

`dotmac-deployment-foundation` ships with ZERO runtime dependencies — that is
what lets a build runner adopt it without adopting a templating engine, a YAML
library, or anything else that could itself drift between renders. A
hand-written emitter is also what makes a future `dotmac-deploy render
--check` meaningful: the committed compose file and a fresh render are
compared BYTE FOR BYTE, and a reviewer reads any difference as an ordinary
text diff rather than as two YAML documents that merely happen to describe the
same thing.

## What is derived, and from where

- The one-shot `migrate` service exists because migration is not a role a
  product declares (`ProductDeploymentSpec.migration`, not
  `ProductDeploymentSpec.roles`) — it is a property of the WHOLE deployment,
  and giving it a dedicated, minimal service is what keeps the owner
  credential (`migration.owner_material`) out of every runtime container.
  `spec.py`'s `_validate_cross_field` already refuses a role that names the
  owner material; this module is the second, independent line of defence
  that docstring promises — nothing here ever reads `owner_material` while
  building a runtime role's environment.
- A role's readiness probe becomes the compose `healthcheck` — the gate
  `depends_on: service_healthy` actually consumes — while its liveness probe
  becomes a label (`io.dotmac.health.live.path`) for a collector to find,
  never the healthcheck itself. Wiring a liveness probe (which by contract
  never touches a dependency — see `spec.py`'s `HealthCheck` docstring) into
  `service_healthy` would make that condition trivially true and defeat the
  whole point of a readiness gate.
- Published ports come from two places and are emitted in ONE syntax. An
  ingress route derives a loopback publication of its upstream, because a
  role behind an edge is reached through that edge on the host and not from
  outside it. Everything else is a `[[roles.ports]]` or
  `[[external_dependencies.ports]]` publication whose `exposure` and
  `address_family` are DECLARED (`IngressPolicy.v1`), and whose bind address
  is derived from them. Both render as Compose LONG SYNTAX, one entry per
  declared family, so `host_ip` is a field that cannot be omitted rather
  than a string position that can — see `_published_port_lines` for the
  IPv6 `docker-proxy` failure that forced it.

## Deployment identity, stamped on every service

Every service carries `io.dotmac.deployment.*` labels naming the product, the
environment, the compose service and what KIND of thing it is; the services
that run the product's own image carry the manifest digest, the configuration
digest and the source revision as well.

The labels exist because a controller that cannot read a release's identity
off the running object has to infer it, and the two things available to infer
from are both wrong. An image TAG is mutable — the same tag names different
bytes on different days, which is exactly why this facility pins a digest
everywhere else. A compose PROJECT name is an operator's `-p` flag or the
directory the file happens to sit in; it is renamed by moving a checkout.
Neither is an authorized identity, and a controller that reconciles against an
inferred one reconciles the wrong release confidently.

The labels are also written by the RENDERER rather than by whatever performed
the deployment, so the identity travels with the file. A rendered compose file
copied to a host and started by hand carries the same identity as one the
engine deployed — and `render --check` proves the labels on a host match the
descriptor, which it could not do for a value the deploy step injected.

## Assumptions this renderer makes beyond the descriptor

`ProductDeploymentSpec` deliberately leaves some things to the renderer (see
its docstring, "what this type deliberately does NOT hold"); the choices
below are THIS MODULE's, not the descriptor's, and are named here so a
reviewer can tell a genuine descriptor gap from a rendering decision:

- **Host port == container port, for an INGRESS-DERIVED publication only.**
  An ingress route names one port, so it is reused for both sides of the
  loopback binding. A declared publication carries `host` and `container`
  separately and is remapped whenever they differ — which is also why a
  derived firewall rule matches `--ctorigdstport` rather than `--dport`.
- **Uploads mount path.** `StaticStrategy` names a volume but not a mount
  point; this renderer mounts it at `/srv/uploads` in every role an ingress
  route targets.
- **Log rotation budget.** Neither `Resources` nor `Role` carries a
  log-rotation policy, so every service gets the same fixed `json-file`
  budget (`_LOG_MAX_SIZE`/`_LOG_MAX_FILE` below) rather than an unbounded
  default.
- **The `migrate` service's own resource/security envelope.** `Migration`
  has no `resources`/`security` table of its own — DDL is a deployment
  property, not a role — so this renderer gives it a fixed, hardened
  envelope (`_MIGRATE_RESOURCES`/`_MIGRATE_SECURITY` below) rather than
  leaving the one process with the widest database grant unbounded.
- **`migrate`'s `stop_grace_period`.** Derived from
  `migration.lock_timeout_seconds` — the same budget the migration itself is
  already bounded by — rather than inventing an unrelated constant.
"""

from __future__ import annotations

import dataclasses
import hashlib
import re
from collections.abc import Iterable, Mapping

from .. import ingress
from ..document import build_canonical_document
from ..errors import SpecError
from ..spec import (
    COLLECTOR_CONFIG_ASSET_DIRECTORY,
    ComposeJob,
    ComposeMount,
    ComposePlacement,
    ExternalDependency,
    PortPublication,
    ProductDeploymentSpec,
    Resources,
    Role,
    Security,
)

__all__ = ["configuration_digest", "render_compose", "render_compose_digest"]

# ── the scalar quoter ────────────────────────────────────────────────────────

# Every character in this set makes a plain YAML scalar ambiguous — as a flow
# indicator, a comment start, or a mapping/sequence marker — so its presence
# anywhere in the string is reason enough to double-quote, rather than trying
# to reason about *where* in the string it would actually matter. Bare
# leading/trailing whitespace gets the same treatment below: over-quoting
# costs nothing, under-quoting costs a wrong value at deploy time.
_SPECIAL_CHARS = frozenset(":#{}[],&*!|>'\"%@`")

# Words YAML 1.1 core-schema loaders parse as bool/null rather than string.
_AMBIGUOUS_WORDS = frozenset(
    {"true", "false", "yes", "no", "on", "off", "null", "~", "y", "n"}
)
_INT_LIKE = re.compile(r"^[+-]?[0-9]+$")
_FLOAT_LIKE = re.compile(r"^[+-]?(\d+\.\d*|\.\d+)([eE][+-]?\d+)?$")


def _needs_quoting(value: str) -> bool:
    """True when `value` is not safe as a bare (unquoted) YAML scalar.

    Deliberately conservative: every rule here is a reason a parser could
    read the plain text as something other than the literal string it is.
    """
    if value == "":
        return True
    if value != value.strip():
        return True
    if any(char in _SPECIAL_CHARS for char in value):
        return True
    if "\n" in value or "\t" in value:
        return True
    if value.lower() in _AMBIGUOUS_WORDS:
        return True
    if _INT_LIKE.match(value) is not None:
        return True
    if _FLOAT_LIKE.match(value) is not None:
        return True
    return False


def _escape(value: str) -> str:
    """Double-quoted-style escaping. Backslash first, or the later escapes
    of `"`, `\\n` and `\\t` would themselves be re-escaped."""
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    escaped = escaped.replace("\n", "\\n").replace("\t", "\\t")
    return f'"{escaped}"'


def _scalar(value: str) -> str:
    """Render `value` as a YAML scalar: bare when safe, double-quoted when
    not. The one function every string in this document passes through, so
    the quoting rule is enforced in exactly one place."""
    return _escape(value) if _needs_quoting(value) else value


def _yaml_bool(value: bool) -> str:
    return "true" if value else "false"


def _duration(seconds: int) -> str:
    return f"{seconds}s"


# ── line-oriented emission helpers ──────────────────────────────────────────


def _indent(level: int) -> str:
    return "  " * level


def _line(level: int, text: str) -> str:
    return f"{_indent(level)}{text}"


def _list_block(level: int, key: str, items: Iterable[str]) -> list[str]:
    """`key:` followed by one `- item` per line, each already YAML-safe.
    Returns nothing at all when `items` is empty, so an optional list never
    shows up as a dangling `key: []` a reader has to interpret."""
    rendered = list(items)
    if not rendered:
        return []
    lines = [_line(level, f"{key}:")]
    lines.extend(_line(level + 1, f"- {item}") for item in rendered)
    return lines


# ── fixed rendering constants ────────────────────────────────────────────────

_NETWORK_SUFFIX = "_net"
_LOG_DRIVER = "json-file"
_LOG_MAX_SIZE = "10m"
_LOG_MAX_FILE = "5"
_NO_NEW_PRIVILEGES = "no-new-privileges:true"
_LIVE_LABEL = "io.dotmac.health.live.path"

# ── the deployment identity vocabulary ──────────────────────────────────────
#
# One namespace, versioned by a schema label of its own, because a reader that
# cannot tell WHICH vocabulary it is reading has to guess what a missing key
# means — "this release predates the key" and "this release does not have that
# property" are different answers and a controller must not conflate them.
#
# Every key is `<prefix>.<group>.<leaf>` and no key is also a prefix of another
# key. Docker keeps labels flat, so this costs nothing here, but a collector
# that projects labels into a tree (an OTel resource, a Prometheus relabel set)
# cannot represent `x.service` holding a string while `x.service.kind` holds
# another — so `service.name` it is, rather than a bare `service`.
_IDENTITY_PREFIX = "io.dotmac.deployment"
_IDENTITY_SCHEMA = "DeploymentIdentity.v1"

_SCHEMA_LABEL = f"{_IDENTITY_PREFIX}.schema"
_PRODUCT_LABEL = f"{_IDENTITY_PREFIX}.product"
_ENVIRONMENT_LABEL = f"{_IDENTITY_PREFIX}.environment"
_SERVICE_NAME_LABEL = f"{_IDENTITY_PREFIX}.service.name"
_SERVICE_KIND_LABEL = f"{_IDENTITY_PREFIX}.service.kind"
_MANIFEST_DIGEST_LABEL = f"{_IDENTITY_PREFIX}.manifest.digest"
_CONFIGURATION_DIGEST_LABEL = f"{_IDENTITY_PREFIX}.configuration.digest"
_SOURCE_REVISION_LABEL = f"{_IDENTITY_PREFIX}.source.revision"

# What a service IS, which is not derivable from its name: `migrate` is a
# convention, `otel-collector` is a convention, and a product free to name a
# role `migrator` would defeat both. Declared here so a controller selects on a
# label rather than on a string it hopes nobody renamed.
_KIND_RELEASE = "release"
_KIND_MIGRATION = "migration"
_KIND_DEPENDENCY = "dependency"
_KIND_TELEMETRY = "telemetry"
_KIND_SUPPORT_RELEASE = "support-release"
_KIND_SUPPORT_DEPENDENCY = "support-dependency"

# The kinds that run the PRODUCT's own image, and therefore the only kinds that
# may carry a release identity. A Redis or a vendor collector is recreated on
# its own schedule and takes no part in the release; stamping this release's
# manifest digest on one would make a container that is not part of the release
# answer "yes" to "are you running release X", which is the exact confusion
# these labels exist to remove. The migration service is in, not out: it runs
# the product image at this revision and is the release's first effect on the
# database, so a controller asking what applied a schema change gets an answer.
_RELEASE_BEARING_KINDS = frozenset(
    {_KIND_RELEASE, _KIND_MIGRATION, _KIND_SUPPORT_RELEASE}
)

# `migrate` runs DDL under the one credential with the widest database grant
# in the whole deployment; it gets a hardened, bounded envelope of its own
# rather than inheriting a role's, because it is not a role (see module
# docstring).
_MIGRATE_RESOURCES = Resources(cpus="1.0", memory="512m", pids=256)
_MIGRATE_SECURITY = Security(
    user="10001:10001",
    read_only_root=True,
    no_new_privileges=True,
    cap_drop=("ALL",),
    # A writable /tmp on a tmpfs IS the hardening, not a lapse from it: the
    # root filesystem is read-only, so the process needs exactly one writable
    # path, and a tmpfs one vanishes with the container.
    tmpfs=("/tmp",),  # noqa: S108  # nosec B108 -- a rendered mount path
    exceptions=(),
)


# ── header ───────────────────────────────────────────────────────────────────


def _header(spec: ProductDeploymentSpec) -> list[str]:
    rule = "# " + "=" * 76
    return [
        rule,
        "# GENERATED by dotmac-deployment-foundation. Do not edit; edit",
        "# deploy/product.toml and re-run `dotmac-deploy render`.",
        "#",
        f"# product:          {spec.product}",
        f"# schema:           {spec.descriptor_schema}",
        # The image this file actually runs, which after a rollback is NOT the
        # descriptor's. A header describing the descriptor while the services
        # below run something else is a comment that contradicts its own file.
        f"# image:            {_image_reference(spec)}",
        f"# descriptor image: {spec.image}",
        f"# source revision:  {spec.source_revision}",
        f"# manifest digest:  {spec.manifest_digest}",
        rule,
    ]


# ── derived shapes ───────────────────────────────────────────────────────────


_IMAGE_OVERRIDE: list[str] = []


def _image_reference(spec: ProductDeploymentSpec) -> str:
    """The image every service runs — the descriptor's, or an override.

    The override exists for exactly one caller: a ROLLBACK. The rendered file
    bakes a literal digest (which is what makes `render --check` a pin and lets
    drift detection compare bytes), so restoring the previous image means
    re-rendering with that digest rather than swapping an environment variable
    the file does not read. Without this, `switch` would write `APP_IMAGE` into
    `.env`, recreate the containers against the same baked digest, and report a
    successful rollback that changed nothing.
    """
    return _IMAGE_OVERRIDE[-1] if _IMAGE_OVERRIDE else spec.image


# ── deployment identity ─────────────────────────────────────────────────────


@dataclasses.dataclass(frozen=True, slots=True)
class _Identity:
    """The identity every service in one render shares.

    Built ONCE per render and passed down, rather than recomputed per service:
    the configuration digest walks the whole descriptor, and a per-service
    recomputation would be both wasteful and — far worse — a place where two
    services in one file could disagree about which release they belong to.
    """

    product: str
    environment: str
    manifest_digest: str
    configuration_digest: str
    source_revision: str


def configuration_digest(spec: ProductDeploymentSpec) -> str:
    """The digest a rendered service carries as its configuration identity.

    Public because other facility code legitimately needs to BIND this identity
    -- a database drift report is checkable only if it names the same digest the
    deployment carries. It is a thin alias on purpose: the derivation, and the
    single `refuse_resolved_material=False` call it depends on, stay here, so
    reuse never becomes a second bypass of that boundary.
    """

    return _configuration_digest(spec)


def _configuration_digest(spec: ProductDeploymentSpec) -> str:
    """`sha256:<hex>` naming the configuration this file was rendered from.

    Deliberately the CANONICAL DESCRIPTOR DOCUMENT's digest and not something
    this renderer invented: that document is what `dotmac-deployment-control`
    binds an approval to, so the value stamped on a container is the same value
    an approval names and the comparison is an `==` rather than a translation.
    A second, renderer-private digest of "roughly the same thing" would be the
    two-spellings-of-one-value failure `digest.py` exists to prevent.

    It cannot be a digest of the rendered compose file, which is the shape a
    reader expects and the one thing that cannot work: the label lives inside
    the file it would be describing, so the value would have to contain its own
    hash. `render --check` already digests the rendered bytes; this answers the
    different question of what the bytes were rendered FROM.

    The digest is taken over the descriptor as ACTUALLY RENDERED, image
    override included. During a rollback the file runs an image the descriptor
    does not name, and a label reporting the descriptor's own digest would
    claim a configuration whose image field disagrees with the container next
    to it. Substituting the effective image means a rollback to a previously
    approved image reproduces that image's approved digest exactly, and a
    rollback to anything else is visibly not an approved configuration — both
    of which are true statements, which the unsubstituted version is not.

    Consequence worth knowing before it surprises somebody: the canonical
    document carries the exact facility version (`document.py` rule 5), so
    upgrading `dotmac-deployment-foundation` changes this value and therefore
    the rendered bytes. `render --check` fails until the assets are
    re-rendered. That is the intended behaviour rather than a cost of it — the
    version is in the digest precisely because a renderer upgrade can change
    what a descriptor word MEANS, and a running container claiming an identity
    minted by a different renderer is the claim being avoided.
    """
    effective = _image_reference(spec)
    subject = (
        spec if effective == spec.image else dataclasses.replace(spec, image=effective)
    )
    # `refuse_resolved_material=False`: see `build_canonical_document`. The
    # refusal is about what may be SENT to deployment control and changes no
    # byte of the document, so the digest is identical either way — but a
    # descriptor it trips (an in-container `--host 0.0.0.0` is enough) must
    # still be renderable, and a container with no identity is worse than a
    # container whose descriptor Control would want edited.
    return build_canonical_document(
        subject, refuse_resolved_material=False
    ).sha256_digest()


def _identity(spec: ProductDeploymentSpec) -> _Identity:
    return _Identity(
        product=spec.product,
        environment=spec.environment,
        manifest_digest=spec.manifest_digest,
        configuration_digest=_configuration_digest(spec),
        source_revision=spec.source_revision,
    )


def _identity_labels(
    identity: _Identity,
    *,
    service: str,
    kind: str,
    extra: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Every label one service carries, as a mapping.

    `environment` is omitted rather than emitted empty when the descriptor
    declares none: a key present with an empty value reads as "deployed to the
    environment named ''", and an absent key reads as "this descriptor does not
    say", which is the true statement. Every other key here is always
    derivable, so an absent one is a renderer bug rather than a descriptor
    silence.
    """
    labels = {
        _SCHEMA_LABEL: _IDENTITY_SCHEMA,
        _PRODUCT_LABEL: identity.product,
        _SERVICE_NAME_LABEL: service,
        _SERVICE_KIND_LABEL: kind,
    }
    if identity.environment:
        labels[_ENVIRONMENT_LABEL] = identity.environment
    if kind in _RELEASE_BEARING_KINDS:
        labels[_MANIFEST_DIGEST_LABEL] = identity.manifest_digest
        labels[_CONFIGURATION_DIGEST_LABEL] = identity.configuration_digest
        labels[_SOURCE_REVISION_LABEL] = identity.source_revision
    labels.update(extra or {})
    return labels


def _labels_block(level: int, labels: Mapping[str, str]) -> list[str]:
    """The `labels:` mapping, key-sorted so the render stays byte-stable.

    Sorted rather than insertion-ordered because the callers build the mapping
    from several places (identity here, a liveness path there) and insertion
    order is then a property of the code's shape rather than of the
    descriptor — the kind of thing a harmless refactor changes, turning a
    no-op into a `render --check` failure.
    """
    lines = [_line(level, "labels:")]
    for key in sorted(labels):
        lines.append(_line(level + 1, f"{key}: {_scalar(labels[key])}"))
    return lines


def _network_name(spec: ProductDeploymentSpec) -> str:
    return f"{spec.product}{_NETWORK_SUFFIX}"


def _ports_for_role(spec: ProductDeploymentSpec, role: Role) -> tuple[int, ...]:
    """Loopback ports to publish for `role` — one per distinct port an
    ingress route names for it. A role no route targets publishes nothing:
    it is reached only from inside the compose network."""
    if spec.ingress is None:
        return ()
    ports = {route.port for route in spec.ingress.routes if route.role == role.code}
    return tuple(sorted(ports))


def _published_port_lines(
    spec: ProductDeploymentSpec, role: Role, body: int
) -> list[str]:
    """The role's `ports:` block, in Compose LONG SYNTAX, always.

    The short form is a colon-delimited string whose host-IP position is
    OPTIONAL, and that is the whole defect. Omit it and Docker publishes on
    every family the host has, spawning a second `docker-proxy -host-ip ::`
    that no `ip6tables DOCKER-USER` rule can filter — that chain is reached
    only from FORWARD while docker-proxy terminates IPv6 locally on INPUT.
    Worse, the position can be filled by an expression whose default hides the
    effective bind: `"${VM_BIND:-127.0.0.1:}8428:8428"` reads as loopback and
    becomes a wildcard the moment somebody sets `VM_BIND` without the trailing
    colon.

    Long syntax makes `host_ip` a field of its own. It cannot be omitted by
    accident, it cannot be smuggled into an adjacent value, and one entry per
    declared family means the families a service serves are COUNTABLE in the
    rendered file rather than inferred from Docker's defaults.
    """
    entries: set[tuple[str, int, int, str, str]] = set()
    # Ingress-routed ports: derived, loopback, on the family the edge declares
    # it reaches its upstreams over. An edge and its upstream share a host, so
    # this is loopback in every deployment shape this facility renders.
    upstream_family = (
        spec.ingress.upstream_address_family if spec.ingress is not None else "ipv4"
    )
    for port in _ports_for_role(spec, role):
        entries.add(
            (
                upstream_family,
                port,
                port,
                ingress.LOOPBACK[upstream_family],
                "tcp",
            )
        )
    entries.update(_publication_entries(role.code, role.ports))
    return _ports_block(entries, body)


def _publication_entries(
    code: str, publications: Iterable[PortPublication]
) -> set[tuple[str, int, int, str, str]]:
    """One rendered entry per declared family, per publication.

    Ports ingress cannot describe. The case that forced the field is Sub's
    syslog listener on UDP 514: an HTTP reverse proxy has no way to express a
    UDP listener, so a descriptor without this section drops the one thing that
    service exists for, silently.

    `exposure = "none"` contributes NOTHING here — `PortPublication.families`
    is empty for it. Not a publication to an address nobody uses: no entry at
    all, so the socket does not exist on the host and there is nothing for a
    firewall rule to be wrong about.
    """
    return {
        (
            family,
            publication.host,
            publication.container,
            publication.host_ip(code, family),
            publication.protocol,
        )
        for publication in publications
        for family in publication.families
    }


def _ports_block(entries: set[tuple[str, int, int, str, str]], body: int) -> list[str]:
    if not entries:
        return []
    lines = [_line(body, "ports:")]
    for _family, host_port, target, host_ip, protocol in sorted(entries):
        lines.append(_line(body + 1, f"- target: {target}"))
        lines.append(_line(body + 2, f"published: {host_port}"))
        lines.append(_line(body + 2, f"host_ip: {_scalar(host_ip)}"))
        lines.append(_line(body + 2, f"protocol: {protocol}"))
    return lines


def _publication_lines(
    code: str, publications: Iterable[PortPublication], body: int
) -> list[str]:
    return _ports_block(_publication_entries(code, publications), body)


def _ingress_role_codes(spec: ProductDeploymentSpec) -> frozenset[str]:
    if spec.ingress is None:
        return frozenset()
    return frozenset(route.role for route in spec.ingress.routes)


def _depends_on(spec: ProductDeploymentSpec, role: Role) -> dict[str, str]:
    """`role`'s full dependency map: its own declared roles, plus `migrate`
    — always, for every runtime role, so nothing can start against a schema
    migration has not finished applying.

    A declared dependency waits on `service_healthy` when the depended-on
    role has a readiness probe — the only condition that means "actually
    able to serve" — and on `service_started` otherwise, since a role with
    no readiness probe can never satisfy `service_healthy` and anything
    waiting on it would never start.
    """
    require_migrate = (
        spec.compose_topology is None or spec.compose_topology.roles_depend_on_migrate
    )
    conditions: dict[str, str] = (
        {"migrate": "service_completed_successfully"} if require_migrate else {}
    )
    managed = {item.code: item for item in spec.managed_dependencies}
    for dep_code in role.depends_on:
        dependency = managed.get(dep_code)
        if dependency is not None:
            # A managed dependency always declares a probe (`spec.py` refuses one
            # that does not), so waiting on `service_healthy` is always
            # satisfiable — and it is the only condition that means anything
            # here. `service_started` on a database is satisfied the instant the
            # container exists, before Postgres has finished recovery.
            conditions[dep_code] = "service_healthy"
            continue
        dep_role = spec.role(dep_code)
        conditions[dep_code] = (
            "service_healthy" if dep_role.ready is not None else "service_started"
        )
    return conditions


def _placement(spec: ProductDeploymentSpec, code: str) -> ComposePlacement | None:
    return (
        spec.compose_topology.placement(code)
        if spec.compose_topology is not None
        else None
    )


def _placement_lines(spec: ProductDeploymentSpec, code: str, level: int) -> list[str]:
    placement = _placement(spec, code)
    if placement is None:
        return _list_block(level, "networks", [_scalar(_network_name(spec))])
    lines = _list_block(level, "profiles", (_scalar(p) for p in placement.profiles))
    if placement.network_mode:
        lines.append(_line(level, f"network_mode: {_scalar(placement.network_mode)}"))
    else:
        lines.extend(
            _list_block(
                level, "networks", (_scalar(network) for network in placement.networks)
            )
        )
    return lines


def _compose_mount(mount: ComposeMount) -> str:
    if mount.kind == "host_material":
        source = f"${{{mount.source_material}:?{mount.source_material} must be set}}"
    elif mount.kind == "repository":
        source = f"./{mount.source.removeprefix('./')}"
    else:
        source = mount.source
    target = (
        f"${{{mount.target_material}:?{mount.target_material} must be set}}"
        if mount.target_material
        else mount.target
    )
    return f"{source}:{target}" + (":ro" if mount.read_only else ":rw")


def _placement_mounts(spec: ProductDeploymentSpec, code: str) -> list[str]:
    placement = _placement(spec, code)
    return (
        [_compose_mount(mount) for mount in placement.mounts]
        if placement is not None
        else []
    )


# ── security ─────────────────────────────────────────────────────────────────


def _security_exception_comments(role: Role, level: int) -> list[str]:
    """`# EXCEPTION:` lines for a `privileged`/`host_network` exception,
    placed directly above the service key so the justification is in the
    file a host reads, not only in the descriptor that produced it. These
    are the two exception kinds that change what the HOST can reach or do —
    not merely what one container can do to itself — which is why they earn
    a comment and the other exception kinds do not.
    """
    exceptions = sorted(
        (
            exc
            for exc in role.security.exceptions
            if exc.kind in ("privileged", "host_network")
        ),
        key=lambda exc: (exc.kind, exc.value),
    )
    return [
        _line(
            level,
            f"# EXCEPTION: {exc.kind} — {exc.justification} "
            f"(approved by {exc.approved_by})",
        )
        for exc in exceptions
    ]


def _security_lines(security: Security, level: int) -> list[str]:
    """The hardened default plus whatever was declared away from it.

    A `writable_path` exception's value is folded into `tmpfs` (a writable
    mount under an otherwise read-only root) and a `capability` exception's
    value into `cap_add` — and nothing else changes, per the exceptions
    contract in `spec.py`'s `SecurityException` docstring. `privileged` is
    the one exception kind with no corresponding compose *value* to render,
    only a boolean.
    """
    lines = [_line(level, f"read_only: {_yaml_bool(security.read_only_root)}")]
    lines.extend(_list_block(level, "security_opt", [_scalar(_NO_NEW_PRIVILEGES)]))
    lines.extend(
        _list_block(level, "cap_drop", [_scalar(v) for v in security.cap_drop])
    )
    cap_add = sorted(security.cap_add)
    lines.extend(_list_block(level, "cap_add", [_scalar(v) for v in cap_add]))
    devices = sorted(exc.value for exc in security.exceptions if exc.kind == "device")
    lines.extend(_list_block(level, "devices", [_scalar(v) for v in devices]))
    lines.append(_line(level, f"user: {_scalar(security.user)}"))
    tmpfs = sorted(set(security.tmpfs) | set(security.writable_paths))
    lines.extend(_list_block(level, "tmpfs", [_scalar(v) for v in tmpfs]))
    if security.privileged:
        lines.append(_line(level, "privileged: true"))
    # Three kinds that an earlier version accepted in the descriptor and then
    # never emitted — so `dotmac_sub`'s `pid: host`, its `/etc/wireguard` mount
    # and its docker-socket mount were declared, reviewed, approved, and absent
    # from the file the host reads. A silently dropped grant is worse than a
    # refused one: the descriptor claims the container has it.
    if security.host_pid:
        lines.append(_line(level, f"pid: {_scalar('host')}"))
    if security.host_ipc:
        lines.append(_line(level, f"ipc: {_scalar('host')}"))
    sysctls = sorted(exc.value for exc in security.of_kind("sysctl"))
    if sysctls:
        lines.append(_line(level, "sysctls:"))
        for entry in sysctls:
            key, _, value = entry.partition("=")
            lines.append(_line(level + 1, f"{key}: {_scalar(value)}"))
    return lines


def _bind_mount_entries(security: Security) -> list[str]:
    """Host bind mounts, from the declared `bind_mount` exceptions ONLY.

    They live in the exceptions list rather than in `[[roles.volumes]]` because
    each one is a security decision — the docker socket is not storage — and the
    exceptions list is where a reviewer looks for grants. `mode` is a separate
    field so a WRITABLE host mount stands out instead of hiding as a `:rw`
    suffix inside what reads as a path.
    """
    return [
        f"{exception.value}:{exception.value}:{exception.mode}"
        for exception in sorted(security.of_kind("bind_mount"), key=lambda e: e.value)
    ]


# ── health ───────────────────────────────────────────────────────────────────


def _healthcheck_lines(role: Role, level: int) -> list[str]:
    """The compose `healthcheck` — built from the READINESS probe only.

    No probe at all when `role.ready` is `None`: a service with no
    healthcheck block is exactly what `service_started` (rather than
    `service_healthy`) means to compose, which is the correct condition for
    a role with no readiness contract to gate on.
    """
    if role.ready is None:
        return []
    probe = role.ready
    # `CMD`, not `CMD-SHELL`, and the argv comes from the descriptor. An earlier
    # version emitted `wget -qO- … || exit 1` — and `dotmac_erp`'s runtime image
    # is `python:*-slim`, which has no `wget`. The healthcheck would have failed
    # permanently, so `depends_on: service_healthy` would never have been
    # satisfied and the deployment would have stalled on a container that was
    # working perfectly. A probe the image cannot run does not report "unknown";
    # it reports UNHEALTHY forever.
    #
    # `HealthCheck.probe_command()` returns the role's declared probe, or a
    # default that uses Python's standard library — which every product in this
    # fleet certainly has, because every one of them is a Python application.
    return [
        _line(level, "healthcheck:"),
        _line(level + 1, "test:"),
        _line(level + 2, f"- {_scalar('CMD')}"),
        *(_line(level + 2, f"- {_scalar(part)}") for part in probe.probe_command()),
        _line(level + 1, f"interval: {_scalar(_duration(probe.interval_seconds))}"),
        _line(level + 1, f"timeout: {_scalar(_duration(probe.timeout_seconds))}"),
        _line(level + 1, f"retries: {probe.retries}"),
        _line(
            level + 1,
            f"start_period: {_scalar(_duration(probe.start_period_seconds))}",
        ),
    ]


# ── environment ──────────────────────────────────────────────────────────────


def _environment_lines(
    level: int,
    materials: Iterable[str],
    literals: Iterable[tuple[str, str]] = (),
) -> list[str]:
    """Material NAMES only, each rendered as `KEY: ${KEY:?KEY must be set}` —
    never a value. A missing material then fails `docker compose up` at
    parse time, before a container starts with an empty credential, rather
    than failing inside the application the first time it is used."""
    names = sorted(set(materials))
    values = sorted(dict(literals).items())
    if not names and not values:
        return []
    collision = sorted(set(names) & {key for key, _ in values})
    if collision:
        raise SpecError(
            f"{collision} appear as both a material NAME and a literal "
            "environment value. One of them is wrong: a material's value never "
            "enters the repository, and a literal's always does"
        )
    lines = [_line(level, "environment:")]
    for name in names:
        placeholder = f"${{{name}:?{name} must be set}}"
        lines.append(_line(level + 1, f"{name}: {_scalar(placeholder)}"))
    # Literal, non-secret configuration. Rendered as a VALUE on purpose — it is
    # reviewable and diffable, which is exactly what a material must never be.
    # The descriptor's secrets guard has already refused anything that looks
    # like a credential here.
    for key, value in values:
        lines.append(_line(level + 1, f"{key}: {_scalar(value)}"))
    return lines


# ── logging / resources (shared by every service) ───────────────────────────


def _logging_lines(level: int) -> list[str]:
    return [
        _line(level, "logging:"),
        _line(level + 1, f"driver: {_scalar(_LOG_DRIVER)}"),
        _line(level + 1, "options:"),
        _line(level + 2, f"max-size: {_scalar(_LOG_MAX_SIZE)}"),
        _line(level + 2, f"max-file: {_scalar(_LOG_MAX_FILE)}"),
    ]


def _resource_lines(
    level: int, resources: Resources, *, replicas: int | None = None
) -> list[str]:
    """`deploy.resources.limits` (cpus/memory/pids) AND the legacy top-level
    `pids_limit`, carrying the SAME number.

    `pids_limit` and `deploy.resources.limits.pids` are ALIASES for one
    setting, and Compose refuses a project where they disagree:

        services.app: can't set distinct values on 'pids_limit' and
        'deploy.resources.limits.pids': invalid compose project

    An ABSENT `pids` under `limits` counts as disagreeing, so emitting
    `pids_limit` beside a `limits` block that lists only cpus and memory —
    which is what this function used to do — produced a file the engine
    refused to load.

    SCOPE OF THAT CLAIM. Observed on **Docker 28.0.4 / Compose 2.38.2** (the
    GitHub runner, where the rehearsal hit it) and independently reproduced on
    **Docker 29.4.3 / Compose v5.1.3**; the repair is accepted by both. It also
    follows from the Compose specification treating the two keys as aliases.
    That is two versions agreeing, roughly a major apart — not a matrix, and
    not a statement about engines nobody has run. Before any product cutover,
    census the adopter hosts' engine versions and record them
    (`docs/inventories/deployment-foundation-rehearsal.md`, "Engine
    evidence").

    Nothing in this repository could have caught it: the renderer emits text,
    and only an engine knows which text it accepts. The disposable-host
    rehearsal did, on its first run (same document, Lane 2).

    Both keys are written rather than just the nested one, so an engine that
    reads only the legacy key still gets the limit. Writing both is safe
    EXACTLY as long as the values are identical, which
    `test_the_two_pids_keys_never_disagree` holds.

    `replicas` is a role property with no equivalent on `migrate` (a one-shot
    job has no scale), so it is only added under `deploy:` when the caller
    passes one."""
    lines = [_line(level, "deploy:")]
    if replicas is not None:
        lines.append(_line(level + 1, f"replicas: {replicas}"))
    lines.append(_line(level + 1, "resources:"))
    lines.append(_line(level + 2, "limits:"))
    lines.append(_line(level + 3, f"cpus: {_scalar(resources.cpus)}"))
    lines.append(_line(level + 3, f"memory: {_scalar(resources.memory)}"))
    lines.append(_line(level + 3, f"pids: {resources.pids}"))
    lines.append(_line(level, f"pids_limit: {resources.pids}"))
    return lines


# ── the migrate service ──────────────────────────────────────────────────────


def _migrate_service(spec: ProductDeploymentSpec, identity: _Identity) -> list[str]:
    """The one-shot DDL service. `restart: "no"` on purpose: a migration
    that fails must stay failed and visible, never silently retried into a
    crash loop that keeps holding the schema lock."""
    body = 2
    lines = [_line(1, "migrate:")]
    lines.append(_line(body, f"image: {_scalar(_image_reference(spec))}"))
    lines.extend(
        _list_block(body, "command", [_scalar(part) for part in spec.migration.command])
    )
    # `migrate` waits on every managed dependency reaching `service_healthy`.
    # It emitted NO `depends_on` at all, so a plain `docker compose up -d` could
    # start the migration against a Postgres that had not finished recovery —
    # and the runtime roles, which correctly wait on `migrate`, would then be
    # gated on a migration that raced. The deployment ENGINE sequences this
    # correctly on its own; the rendered file has to as well, because an
    # operator running `up -d` by hand is a case the file is read in.
    managed = sorted(item.code for item in spec.managed_dependencies)
    if managed:
        lines.append(_line(body, "depends_on:"))
        for code in managed:
            lines.append(_line(body + 1, f"{code}:"))
            lines.append(_line(body + 2, "condition: service_healthy"))
    name = spec.migration.owner_material
    placeholder = f"${{{name}:?{name} must be set}}"
    lines.append(_line(body, "environment:"))
    lines.append(_line(body + 1, f"{name}: {_scalar(placeholder)}"))
    placement_mounts = _placement_mounts(spec, "migrate")
    if placement_mounts:
        lines.extend(
            _list_block(body, "volumes", sorted(_scalar(m) for m in placement_mounts))
        )
    lines.extend(_placement_lines(spec, "migrate", body))
    lines.extend(_resource_lines(body, _MIGRATE_RESOURCES))
    lines.extend(_logging_lines(body))
    lines.extend(_security_lines(_MIGRATE_SECURITY, body))
    lines.append(
        _line(
            body,
            f"stop_grace_period: "
            f"{_scalar(_duration(spec.migration.lock_timeout_seconds))}",
        )
    )
    lines.append(_line(body, f"restart: {_scalar('no')}"))
    lines.extend(
        _labels_block(
            body,
            _identity_labels(identity, service="migrate", kind=_KIND_MIGRATION),
        )
    )
    return lines


# ── a runtime role's service ─────────────────────────────────────────────────


def _role_service(
    spec: ProductDeploymentSpec, role: Role, identity: _Identity
) -> list[str]:
    host_network = any(exc.kind == "host_network" for exc in role.security.exceptions)
    body = 2

    lines = _security_exception_comments(role, level=1)
    lines.append(_line(1, f"{role.code}:"))

    lines.append(_line(body, f"image: {_scalar(_image_reference(spec))}"))
    if role.command:
        lines.extend(
            _list_block(body, "command", [_scalar(part) for part in role.command])
        )
    lines.extend(_environment_lines(body, role.materials, role.environment))

    depends = _depends_on(spec, role)
    if depends:
        lines.append(_line(body, "depends_on:"))
        for dep_name in sorted(depends):
            lines.append(_line(body + 1, f"{dep_name}:"))
            lines.append(_line(body + 2, f"condition: {depends[dep_name]}"))

    lines.extend(_healthcheck_lines(role, body))

    if not host_network:
        lines.extend(_published_port_lines(spec, role, body))

    mounts: list[str] = []
    if (
        role.code in _ingress_role_codes(spec)
        and spec.ingress is not None
        and spec.ingress.static.uploads == "volume"
    ):
        volume_name = spec.ingress.static.uploads_volume
        mounts.append(f"{volume_name}:{spec.ingress.static.uploads_path}")
    for volume in role.volumes:
        suffix = ":ro" if volume.read_only else ""
        mounts.append(f"{volume.name}:{volume.target}{suffix}")
    mounts.extend(_bind_mount_entries(role.security))
    mounts.extend(_placement_mounts(spec, role.code))
    if mounts:
        lines.extend(
            _list_block(body, "volumes", [_scalar(m) for m in sorted(set(mounts))])
        )

    if host_network:
        lines.append(_line(body, f"network_mode: {_scalar('host')}"))
    else:
        lines.extend(_placement_lines(spec, role.code, body))

    lines.extend(_resource_lines(body, role.resources, replicas=role.replicas))
    lines.extend(_logging_lines(body))
    lines.extend(_security_lines(role.security, body))

    lines.append(
        _line(body, f"stop_grace_period: {_scalar(_duration(role.stop_grace_seconds))}")
    )
    lines.append(_line(body, "restart: unless-stopped"))

    # The liveness path joins the identity labels in ONE block rather than
    # getting a second `labels:` key of its own — a compose mapping with two
    # `labels:` keys silently keeps the last one, so the two would not coexist.
    # It stays outside the `io.dotmac.deployment.*` namespace on purpose: it is
    # a probe address a collector reads, not part of the release's identity.
    live = {_LIVE_LABEL: role.live.path} if role.live is not None else {}
    lines.extend(
        _labels_block(
            body,
            _identity_labels(
                identity, service=role.code, kind=_KIND_RELEASE, extra=live
            ),
        )
    )

    return lines


# ── top-level networks / volumes ────────────────────────────────────────────


def _networks_section(spec: ProductDeploymentSpec) -> list[str]:
    if spec.compose_topology is None:
        return ["networks:", _line(1, f"{_network_name(spec)}: {{}}")]
    lines = ["networks:"]
    for network in sorted(spec.compose_topology.networks, key=lambda item: item.code):
        lines.append(_line(1, f"{network.code}:"))
        lines.append(_line(2, "driver: bridge"))
        if network.internal:
            lines.append(_line(2, "internal: true"))
        if network.loopback_default:
            lines.append(_line(2, "driver_opts:"))
            lines.append(
                _line(
                    3,
                    "com.docker.network.bridge.host_binding_ipv4: "
                    + _scalar("127.0.0.1"),
                )
            )
    return lines


def _declared_volume_names(spec: ProductDeploymentSpec) -> tuple[str, ...]:
    """Every named volume anything in this deployment mounts.

    Derived rather than declared separately, so a volume a role mounts and the
    top-level section forgets cannot happen — which is the shape of
    `dotmac_sub`'s `dotmac_sub_db_data`, declared at the top level and mounted
    by nothing, with the real data on a host bind mount instead.
    """
    names: set[str] = set()
    if spec.ingress is not None and spec.ingress.static.uploads == "volume":
        names.add(spec.ingress.static.uploads_volume)
    for role in spec.roles:
        names.update(volume.name for volume in role.volumes)
    for dependency in spec.managed_dependencies:
        names.update(volume.name for volume in dependency.volumes)
    if spec.compose_topology is not None:
        for placement in spec.compose_topology.placements:
            names.update(
                mount.source for mount in placement.mounts if mount.kind == "named"
            )
        for job in spec.compose_topology.jobs:
            names.update(volume.name for volume in job.volumes)
            names.update(
                mount.source for mount in job.placement.mounts if mount.kind == "named"
            )
    return tuple(sorted(names))


def _volumes_section(spec: ProductDeploymentSpec) -> list[str]:
    declared = _declared_volume_names(spec)
    if not declared:
        return []
    # `uploads_volume` carries no pattern validation in `spec.py` (unlike
    # every material/role/product name, which does) — quoted defensively
    # here, both as this map key and inside the mount string above, so an
    # unusual-but-not-rejected name cannot produce broken YAML.
    lines = ["", "volumes:"]
    lines.extend(_line(1, f"{_scalar(name)}: {{}}") for name in declared)
    return lines


# ── entry points ─────────────────────────────────────────────────────────────


def _dependency_service(
    spec: ProductDeploymentSpec,
    dependency: ExternalDependency,
    identity: _Identity,
) -> list[str]:
    """A dependency this deployment RUNS, as a Compose service.

    It is deliberately not a `[[roles]]` entry and is rendered differently in
    three ways that matter: it runs its own image rather than the product's, it
    is not verified against the deploying digest, and it takes no part in the
    warm-candidate handoff. A Redis that got recreated on every release would
    drop every connection the switch was designed to preserve.

    Without this, `dotmac_erp`'s rendered file declared Celery broker
    configuration and no Redis service — internally consistent, and it would not
    have worked.
    """
    body = 2
    lines = [_line(1, f"{dependency.code}:")]
    lines.append(_line(body, f"image: {_scalar(dependency.image)}"))
    if dependency.command:
        lines.extend(
            _list_block(body, "command", [_scalar(part) for part in dependency.command])
        )
    lines.extend(_environment_lines(body, dependency.materials, dependency.environment))
    # A managed dependency publishes through the same typed contract a role
    # does, and for the same reason: the two ports this facility was built to
    # close (a Redis and a Postgres) are dependency publications. A second
    # rendering path here would have been a second place for the short form to
    # survive.
    lines.extend(_publication_lines(dependency.code, dependency.ports, body))
    mounts = [
        f"{volume.name}:{volume.target}" + (":ro" if volume.read_only else "")
        for volume in dependency.volumes
    ]
    mounts.extend(_placement_mounts(spec, dependency.code))
    if mounts:
        lines.extend(_list_block(body, "volumes", sorted(_scalar(m) for m in mounts)))
    lines.append(_line(body, "healthcheck:"))
    lines.append(_line(body + 1, "test:"))
    lines.append(_line(body + 2, f"- {_scalar('CMD')}"))
    for part in dependency.health_probe:
        lines.append(_line(body + 2, f"- {_scalar(part)}"))
    lines.append(_line(body + 1, f"interval: {_scalar(_duration(10))}"))
    lines.append(_line(body + 1, f"timeout: {_scalar(_duration(5))}"))
    lines.append(_line(body + 1, "retries: 10"))
    lines.append(_line(body + 1, f"start_period: {_scalar(_duration(20))}"))
    if dependency.cpus or dependency.memory:
        lines.extend(
            _resource_lines(
                body,
                Resources(
                    cpus=dependency.cpus or "1.0",
                    memory=dependency.memory or "512m",
                    pids=256,
                ),
                replicas=1,
            )
        )
    lines.extend(_placement_lines(spec, dependency.code, body))
    lines.extend(_logging_lines(body))
    lines.append(_line(body, "restart: unless-stopped"))
    lines.extend(
        _labels_block(
            body,
            _identity_labels(identity, service=dependency.code, kind=_KIND_DEPENDENCY),
        )
    )
    return lines


def _collector_service(spec: ProductDeploymentSpec, identity: _Identity) -> list[str]:
    """The OTel collector, when the deployment declares one.

    Rendered as an ordinary service and NOT as a role: it runs somebody else's
    image, has no product health contract, takes no part in the warm-candidate
    handoff, and is not verified against the deploying digest. It also must NOT
    depend on `migrate` — a collector that waits for a migration cannot report
    on the migration, and the one deployment you most want telemetry from is the
    one where the migration is failing.

    Without this, the collector configuration was rendered beside a
    deployment that ran no collector at all: a specification of what a
    collector would need, sitting where a reader reasonably takes it for
    telemetry.

    The configuration is mounted as its DIRECTORY, never as the single file:
    a single-file bind mount keeps the inode present at container creation,
    so a deploy that replaces the file leaves the collector reading the old
    one (see `Telemetry.collector_config_directory`).
    """
    telemetry = spec.telemetry
    if not telemetry.collector_image:
        return []
    body = 2
    mount = (
        f"./{COLLECTOR_CONFIG_ASSET_DIRECTORY}:"
        f"{telemetry.collector_config_directory}:ro"
    )
    lines = [
        "  # The collector deliberately does NOT depend on `migrate`: a collector",
        "  # that waits for a migration cannot report on the migration.",
        _line(1, "otel-collector:"),
        _line(body, f"image: {_scalar(telemetry.collector_image)}"),
        _line(body, "command:"),
        _line(body + 1, f"- {_scalar('--config=' + telemetry.collector_config_mount)}"),
    ]
    lines.extend(_environment_lines(body, [telemetry.endpoint_material], ()))
    mounts = [mount, *_placement_mounts(spec, "otel-collector")]
    lines.extend(_list_block(body, "volumes", sorted(_scalar(m) for m in mounts)))
    lines.extend(_placement_lines(spec, "otel-collector", body))
    lines.extend(
        _resource_lines(
            body, Resources(cpus="0.5", memory="512m", pids=128), replicas=1
        )
    )
    lines.extend(_logging_lines(body))
    lines.append(_line(body, "read_only: true"))
    lines.extend(_list_block(body, "security_opt", [_scalar(_NO_NEW_PRIVILEGES)]))
    lines.extend(_list_block(body, "cap_drop", [_scalar("ALL")]))
    # nosec B108 / noqa S108 -- "/tmp" here is a MOUNT PATH written into a
    # rendered compose file, not a temp file this process opens. It is the
    # writable tmpfs that makes a read-only root filesystem usable.
    tmpfs_mount = "/tmp"  # noqa: S108  # nosec B108 -- a rendered mount path
    lines.extend(_list_block(body, "tmpfs", [_scalar(tmpfs_mount)]))
    lines.append(_line(body, "restart: unless-stopped"))
    lines.extend(
        _labels_block(
            body,
            _identity_labels(identity, service="otel-collector", kind=_KIND_TELEMETRY),
        )
    )
    return lines


def _support_job(
    spec: ProductDeploymentSpec, job: ComposeJob, identity: _Identity
) -> list[str]:
    """Profile-gated support work, never included in the runtime role roster."""
    body = 2
    if job.image_source == "product":
        image = _image_reference(spec)
        kind = _KIND_SUPPORT_RELEASE
    else:
        code = job.image_source.removeprefix("dependency:")
        image = next(
            dependency.image
            for dependency in spec.managed_dependencies
            if dependency.code == code
        )
        kind = _KIND_SUPPORT_DEPENDENCY
    lines = [_line(1, f"{job.code}:")]
    lines.append(_line(body, f"image: {_scalar(image)}"))
    if job.entrypoint:
        lines.extend(
            _list_block(body, "entrypoint", (_scalar(arg) for arg in job.entrypoint))
        )
    lines.extend(_list_block(body, "command", (_scalar(arg) for arg in job.command)))
    lines.extend(_environment_lines(body, job.materials))
    if job.depends_on:
        lines.append(_line(body, "depends_on:"))
        for code in sorted(job.depends_on):
            lines.append(_line(body + 1, f"{code}:"))
            lines.append(_line(body + 2, "condition: service_healthy"))
    mounts = [
        f"{volume.name}:{volume.target}" + (":ro" if volume.read_only else "")
        for volume in job.volumes
    ]
    mounts.extend(_compose_mount(mount) for mount in job.placement.mounts)
    if mounts:
        lines.extend(_list_block(body, "volumes", sorted(_scalar(m) for m in mounts)))
    lines.extend(_placement_lines_for_job(job.placement, body))
    lines.extend(_logging_lines(body))
    lines.extend(_security_lines(job.security, body))
    lines.append(_line(body, f"restart: {_scalar('no')}"))
    lines.extend(
        _labels_block(body, _identity_labels(identity, service=job.code, kind=kind))
    )
    return lines


def _placement_lines_for_job(placement: ComposePlacement, level: int) -> list[str]:
    lines = _list_block(level, "profiles", (_scalar(p) for p in placement.profiles))
    if placement.network_mode:
        lines.append(_line(level, f"network_mode: {_scalar(placement.network_mode)}"))
    else:
        lines.extend(
            _list_block(level, "networks", (_scalar(n) for n in placement.networks))
        )
    return lines


def render_compose(spec: ProductDeploymentSpec, *, image: str = "") -> str:
    """The deterministic docker-compose document for `spec`, as text.

    Same spec in, same bytes out — always: nothing here reads a clock, a
    random source, or an unordered container. Role services are sorted by
    `code` rather than emitted in descriptor order, so reordering the
    `[[roles]]` array in `deploy/product.toml` does not change the render.
    """
    # Managed dependencies first: everything else may wait on them, and a reader
    # scanning the file top-down meets the database before the thing that needs
    # it.
    _IMAGE_OVERRIDE.append(image or spec.image)
    try:
        return _render_compose_body(spec)
    finally:
        _IMAGE_OVERRIDE.pop()


def _render_compose_body(spec: ProductDeploymentSpec) -> str:
    # Built here, once, so every service in this file agrees about which
    # release it belongs to — and inside the `_IMAGE_OVERRIDE` window, because
    # the configuration digest is taken over the image actually rendered.
    identity = _identity(spec)
    blocks = [
        _dependency_service(spec, dependency, identity)
        for dependency in sorted(spec.managed_dependencies, key=lambda d: d.code)
    ]
    collector = _collector_service(spec, identity)
    if collector:
        blocks.append(collector)
    blocks.append(_migrate_service(spec, identity))
    if spec.compose_topology is not None:
        blocks.extend(
            _support_job(spec, job, identity)
            for job in sorted(spec.compose_topology.jobs, key=lambda item: item.code)
        )
    blocks.extend(
        _role_service(spec, role, identity)
        for role in sorted(spec.roles, key=lambda r: r.code)
    )

    lines = _header(spec)
    lines.append("")
    lines.append("services:")
    for block in blocks:
        lines.append("")
        lines.extend(block)

    lines.append("")
    lines.extend(_networks_section(spec))
    lines.extend(_volumes_section(spec))

    return "\n".join(lines) + "\n"


def render_compose_digest(spec: ProductDeploymentSpec) -> str:
    """`sha256:<hex>` of the rendered document — what a drift checker
    compares against a committed compose file without re-parsing either
    one as YAML."""
    rendered = render_compose(spec).encode("utf-8")
    return f"sha256:{hashlib.sha256(rendered).hexdigest()}"
