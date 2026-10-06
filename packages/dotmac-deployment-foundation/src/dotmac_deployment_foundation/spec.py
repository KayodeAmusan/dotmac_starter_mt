"""Strict ``ProductDeploymentSpec.v1`` and ``.v2`` readers.

A product assembly owns exactly one deployment artifact: `deploy/product.toml`.
Everything else a deployment needs — the Compose file, the Nginx site, the
collector configuration, the alert rules, the ordered deployment plan — is
RENDERED from it by this package. That is the whole build-once claim: the
variation lives in a typed value, never in a copied template and never in a
branch inside shared code.

## Reading rules that are load-bearing

**Unknown keys are refused, not ignored.** A typo in ``read_only`` that
silently disables a read-only filesystem is the exact class of defect this
facility exists to remove, and a permissive parser converts it from a CI
failure into a production one.

**The schema string is checked first and fails closed.** A descriptor written
against a future schema may declare fields whose ABSENCE changes behaviour
rather than merely losing detail — a security exception, say — so an older
renderer refuses rather than rendering a subset it believes is complete.

**Secrets are refused before any field is interpreted** (`secrets_guard`), so a
value pasted into a field the schema does not define is still caught.

**Every duration is seconds and every duration field says so in its name.** A
descriptor that mixes ``timeout = 30`` and ``timeout = "30s"`` across products
is a units bug waiting for the one host where it matters.

## What this type deliberately does NOT hold

- Secret values. Material NAMES and approved pointers only (ADR-0009).
- Environment-specific addresses. A host name is ingress identity; a database
  address is a material the deployment host resolves.
- Anything the facility can derive. Resource attributes, container names and
  the plan's step order are DERIVED, so two products cannot disagree about
  them.

V1 is immutable. V2 adds only typed database-catalogue coordinates: a v1
document carrying that key is refused, while v1 canonical bytes omit the
version-gated dataclass field entirely.
"""

from __future__ import annotations

import re
import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any, ClassVar, Final

from . import ingress as ingress_contract
from .database_catalog import (
    DatabaseCatalogCoordinateV1,
    DatabaseCatalogProductIdentityV1,
    DatabaseCatalogScope,
)
from .errors import SpecError, UnknownFieldError, UnknownSchemaError
from .recovery import EXTERNAL_ONLY_VERIFICATIONS
from .recovery_identity import (
    PRIVILEGE_VERIFICATIONS,
    DatasetIdentityV1,
    ExternalExecutorV1,
)
from .secrets_guard import require_no_secrets

#: Defined HERE rather than in `backup.py`, which is where it used to live: this
#: module now declares a cadence in seconds and `backup.py` already imports this
#: one, so the alternative was two definitions of a constant whose whole value is
#: that everything agrees on it. `backup.py` re-exports it, so no caller moves.
SECONDS_PER_DAY: Final = 86_400


def _contained_relative_path(value: str, *, key: str, where: str) -> str:
    """A descriptor-supplied path that must stay inside the staged deploy root.

    The descriptor is reviewed input, but it is not *trusted* input: it travels
    with the release and is the thing an attacker edits if they can edit
    anything. A path out of it is later joined to the deploy directory and
    read, so it decides WHICH FILE answers a gate — and a gate that can be
    pointed at a file of the writer's choosing is not a gate.

    Refused here, at parse, so the descriptor fails loudly on the way in rather
    than resolving to something surprising later. `providers.compose_host`
    repeats the containment check after resolving, because only that side can
    see a symlink planted inside the deploy directory; this side cannot, and a
    check that can only be made late is still worth making early where it names
    the offending key.
    """
    if not value:
        raise SpecError(f"{key!r} must not be empty", where=where)
    if "\\" in value:
        raise SpecError(
            f"{key!r} must be a POSIX path with `/` separators, got {value!r}. "
            "A backslash is a literal filename character on the deploy host, "
            "not a separator",
            where=where,
        )
    path = PurePosixPath(value)
    if path.is_absolute():
        raise SpecError(
            f"{key!r} must be relative to the deploy directory, got {value!r}. "
            "An absolute path ignores the staged release entirely",
            where=where,
        )
    if ".." in path.parts:
        raise SpecError(
            f"{key!r} must not traverse out of the deploy directory, got "
            f"{value!r}. A `..` component lets a file outside the staged "
            "release answer a gate about the staged release",
            where=where,
        )
    return value


if TYPE_CHECKING:  # pragma: no cover - the runtime import is inside the method
    from .document import DeploymentDescriptorDocumentV1

SCHEMA_V1: Final = "ProductDeploymentSpec.v1"
SCHEMA_V2: Final = "ProductDeploymentSpec.v2"
SCHEMA_V3: Final = "ProductDeploymentSpec.v3"
SCHEMAS: Final = (SCHEMA_V1, SCHEMA_V2, SCHEMA_V3)
# Backwards-compatible public name: existing callers importing SCHEMA mean the
# schema their current descriptors use, not "whichever schema is newest".
SCHEMA: Final = SCHEMA_V1

# A hyphen is allowed, and that is not cosmetic. A role code is emitted VERBATIM
# as the Compose service key, so a schema that forbade hyphens would force
# `dotmac_sub`'s real `celery-worker` to be declared as `celery_worker` — and a
# cutover would then create a parallel service beside the running one instead of
# replacing it. A descriptor that cannot name the thing it is describing is a
# descriptor nobody can adopt.
#
# Trailing separators are refused: `celery-` and `celery_` are the shapes that
# come from a truncated edit, not from a real name.
_CODE = re.compile(r"^[a-z][a-z0-9_-]{0,61}[a-z0-9]$|^[a-z]$")
_MATERIAL_NAME = re.compile(r"^[A-Z][A-Z0-9_]{0,127}$")
# A PostgreSQL role name as this facility will accept it. Deliberately
# narrower than PostgreSQL allows: an unquoted lowercase identifier needs no
# quoting anywhere, and a role name requiring quotes is one a shell, a DSN or
# a comparison eventually gets wrong.
_ROLE_NAME = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")
_ENV_NAME = re.compile(r"^[A-Z][A-Z0-9_]{0,127}$")
_DIGEST_REF = re.compile(r"^[a-z0-9][a-z0-9._\-/:]*@sha256:[0-9a-f]{64}$")
#: The same reference, plus an empty arm — "optional, and constrained when
#: declared". `^$` is the house convention for this shape (see `environment`),
#: and it is doing real work here: a consumer may declare `[telemetry]` and no
#: collector at all, which is exactly what `dotmac_erp` does. The rule is that
#: a DECLARED collector image is digest-pinned, NOT that one must be declared;
#: requiring declaration is a separate decision with its own migration and is
#: not something to smuggle in behind a format check.
_OPTIONAL_DIGEST_REF = re.compile(r"^[a-z0-9][a-z0-9._\-/:]*@sha256:[0-9a-f]{64}$|^$")
_HOSTNAME = re.compile(
    r"^(?=.{1,253}$)([a-z0-9]([a-z0-9\-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$"
)
_ALERT_CODE = re.compile(r"^[A-Z][A-Z0-9]*(_[A-Z0-9]+)*$")


# ── strict-table helpers ────────────────────────────────────────────────────


class _Table:
    """A TOML table that refuses to be read sloppily.

    Every read POPS. Whatever is left when :meth:`done` is called is a key the
    schema does not define, and that is an error rather than a shrug.
    """

    __slots__ = ("_data", "_path")

    def __init__(self, data: Mapping[str, Any], path: str) -> None:
        if not isinstance(data, Mapping):
            raise SpecError("expected a table", where=path)
        self._data = dict(data)
        self._path = path

    @property
    def path(self) -> str:
        return self._path

    def _child_path(self, name: str) -> str:
        return f"{self._path}.{name}" if self._path else name

    def str_(
        self,
        name: str,
        *,
        default: str | None = None,
        pattern: re.Pattern[str] | None = None,
    ) -> str:
        raw = self._data.pop(name, None)
        if raw is None:
            if default is None:
                raise SpecError(f"required key {name!r} is missing", where=self._path)
            return default
        if not isinstance(raw, str):
            raise SpecError(f"{name!r} must be a string", where=self._path)
        if pattern is not None and not pattern.match(raw):
            raise SpecError(
                f"{name!r} does not match {pattern.pattern}",
                where=self._child_path(name),
            )
        return raw

    def int_(
        self,
        name: str,
        *,
        default: int | None = None,
        minimum: int = 0,
        maximum: int | None = None,
    ) -> int:
        raw = self._data.pop(name, None)
        if raw is None:
            if default is None:
                raise SpecError(f"required key {name!r} is missing", where=self._path)
            return default
        if isinstance(raw, bool) or not isinstance(raw, int):
            raise SpecError(f"{name!r} must be an integer", where=self._path)
        if raw < minimum or (maximum is not None and raw > maximum):
            bound = f">= {minimum}" + (
                f" and <= {maximum}" if maximum is not None else ""
            )
            raise SpecError(f"{name!r} must be {bound}", where=self._child_path(name))
        return raw

    def bool_(self, name: str, *, default: bool) -> bool:
        raw = self._data.pop(name, default)
        if not isinstance(raw, bool):
            raise SpecError(f"{name!r} must be a boolean", where=self._path)
        return raw

    def str_list(
        self,
        name: str,
        *,
        default: Sequence[str] | None = None,
        pattern: re.Pattern[str] | None = None,
    ) -> tuple[str, ...]:
        raw = self._data.pop(name, None)
        if raw is None:
            if default is None:
                raise SpecError(f"required key {name!r} is missing", where=self._path)
            return tuple(default)
        if not isinstance(raw, list) or not all(isinstance(item, str) for item in raw):
            raise SpecError(f"{name!r} must be an array of strings", where=self._path)
        if pattern is not None:
            for item in raw:
                if not pattern.match(item):
                    raise SpecError(
                        f"{item!r} does not match {pattern.pattern}",
                        where=self._child_path(name),
                    )
        return tuple(raw)

    def table(self, name: str, *, optional: bool = False) -> _Table | None:
        raw = self._data.pop(name, None)
        if raw is None:
            if optional:
                return None
            raise SpecError(f"required table {name!r} is missing", where=self._path)
        return _Table(raw, self._child_path(name))

    def tables(self, name: str, *, minimum: int = 0) -> list[_Table]:
        raw = self._data.pop(name, [])
        if not isinstance(raw, list):
            raise SpecError(f"{name!r} must be an array of tables", where=self._path)
        if len(raw) < minimum:
            raise SpecError(
                f"{name!r} needs at least {minimum} entries", where=self._path
            )
        return [
            _Table(item, f"{self._child_path(name)}[{index}]")
            for index, item in enumerate(raw)
        ]

    def keys(self) -> tuple[str, ...]:
        """The keys still unread. Used by free-form tables such as `environment`,
        where the schema defines the SHAPE of a key rather than a fixed set."""
        return tuple(self._data)

    def done(self) -> None:
        if self._data:
            raise UnknownFieldError(
                f"unknown key(s) {sorted(self._data)} — the schema defines no such "
                "field, and ignoring one is how a disabled security control looks "
                "exactly like an enabled one",
                where=self._path,
            )


def _unique(values: Sequence[str], *, what: str, where: str) -> None:
    seen: set[str] = set()
    for value in values:
        if value in seen:
            raise SpecError(f"duplicate {what} {value!r}", where=where)
        seen.add(value)


# ── leaf types ──────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class Resources:
    """A role's resource envelope.

    Limits are REQUIRED, not defaulted. An unbounded container on a shared host
    is the mechanism by which one product's memory leak takes down another
    product's database, and a default here would let a product ship unbounded
    while looking configured.
    """

    cpus: str
    memory: str
    pids: int

    @classmethod
    def parse(cls, table: _Table) -> Resources:
        cpus = table.str_("cpus", pattern=re.compile(r"^\d+(\.\d+)?$"))
        memory = table.str_("memory", pattern=re.compile(r"^\d+(m|g|M|G|mb|gb|MB|GB)$"))
        pids = table.int_("pids", default=512, minimum=16, maximum=32768)
        table.done()
        return cls(cpus=cpus, memory=memory, pids=pids)


@dataclass(frozen=True, slots=True)
class SecurityException:
    """One documented departure from the hardened default.

    Sub's network roles genuinely need `NET_ADMIN`; ERP's application role does
    not. The difference is not a judgement the renderer makes — it is a declared
    exception carrying a justification and a named approver, so that a reviewer
    reading a diff sees a capability being added rather than a default being
    quietly loosened.
    """

    kind: str
    value: str
    justification: str
    approved_by: str
    mode: str = "ro"
    """For `bind_mount` and `device`: `ro` or `rw`.

    Defaulted to read-only and stated separately rather than smuggled into
    `value` as a `:rw` suffix, because a reviewer scanning a list of exceptions
    needs the WRITABLE ones to stand out, and a suffix inside a path does not.
    """

    # Every kind here is one a real product needs and the renderer emits. A kind
    # the renderer ignores would be worse than an absent one: the descriptor
    # would say the grant was declared while the rendered file did not carry it,
    # so the container would fail to start for a reason nothing in the
    # descriptor explains.
    #
    # `host_pid`, `bind_mount` and `device` were added after `dotmac_sub`'s
    # descriptor SILENTLY DROPPED its `pid: host`, its `/etc/wireguard` mount
    # and its docker-socket mount — three grants that are load-bearing for
    # WireGuard netns entry, and all three invisible in the rendered output.
    KINDS: ClassVar[tuple[str, ...]] = (
        "capability",
        "writable_path",
        "privileged",
        "host_network",
        "host_pid",
        "host_ipc",
        "device",
        "bind_mount",
        "sysctl",
    )

    @classmethod
    def parse(cls, table: _Table) -> SecurityException:
        kind = table.str_("kind")
        if kind not in cls.KINDS:
            raise SpecError(f"kind must be one of {cls.KINDS}", where=table.path)
        value = table.str_("value")
        justification = table.str_("justification")
        if len(justification) < 24:
            raise SpecError(
                "justification must be a real sentence (>= 24 characters); a "
                "placeholder is worse than no exception because it reads as review",
                where=table.path,
            )
        approved_by = table.str_("approved_by")
        mode = table.str_("mode", default="ro")
        table.done()
        if mode not in ("ro", "rw"):
            raise SpecError("mode must be 'ro' or 'rw'", where=table.path)
        if kind in ("bind_mount", "device") and ":" in value:
            raise SpecError(
                f"{kind} value {value!r} contains a colon. Declare the host path "
                "in `value` and the access in `mode`; a `:rw` suffix hides a "
                "writable grant inside what looks like a path",
                where=table.path,
            )
        return cls(
            kind=kind,
            value=value,
            justification=justification,
            approved_by=approved_by,
            mode=mode,
        )


@dataclass(frozen=True, slots=True)
class Security:
    """The hardened default, plus whatever the product justified away from it."""

    user: str
    read_only_root: bool
    no_new_privileges: bool
    cap_drop: tuple[str, ...]
    tmpfs: tuple[str, ...]
    exceptions: tuple[SecurityException, ...]

    @classmethod
    def parse(cls, table: _Table | None, *, where: str) -> Security:
        if table is None:
            return cls(
                user="10001:10001",
                read_only_root=True,
                no_new_privileges=True,
                cap_drop=("ALL",),
                # A writable /tmp on a tmpfs IS the hardening: the root
                # filesystem is read-only, so the process needs one writable
                # path that vanishes with the container.
                tmpfs=("/tmp",),  # noqa: S108  # nosec B108 -- a mount path
                exceptions=(),
            )
        user = table.str_(
            "user", default="10001:10001", pattern=re.compile(r"^\d+:\d+$")
        )
        read_only_root = table.bool_("read_only_root", default=True)
        no_new_privileges = table.bool_("no_new_privileges", default=True)
        cap_drop = table.str_list("cap_drop", default=("ALL",))
        tmpfs = table.str_list(
            "tmpfs",
            # not a lapse from it. The root filesystem is read-only, so a
            # process needs one writable path that vanishes with the container.
            default=("/tmp",),  # noqa: S108  # nosec B108 -- a mount path
        )
        exceptions = tuple(
            SecurityException.parse(item) for item in table.tables("exceptions")
        )
        table.done()
        # A relaxed default without a matching declared exception is refused:
        # the exception list is what a reviewer reads, so a relaxation that
        # bypasses it is invisible exactly where visibility is the control.
        declared = {exception.kind for exception in exceptions}
        if not read_only_root and "writable_path" not in declared:
            raise SpecError(
                "read_only_root=false needs a declared 'writable_path' exception",
                where=where,
            )
        if not no_new_privileges:
            raise SpecError(
                "no_new_privileges may not be disabled; there is no deployment "
                "shape that needs it and every shape that wants it is a defect",
                where=where,
            )
        if "ALL" not in cap_drop:
            raise SpecError(
                "cap_drop must include 'ALL'; capabilities are ADDED back through "
                "a declared 'capability' exception, never left undropped",
                where=where,
            )
        return cls(
            user=user,
            read_only_root=read_only_root,
            no_new_privileges=no_new_privileges,
            cap_drop=cap_drop,
            tmpfs=tmpfs,
            exceptions=exceptions,
        )

    @property
    def cap_add(self) -> tuple[str, ...]:
        return tuple(
            exception.value
            for exception in self.exceptions
            if exception.kind == "capability"
        )

    @property
    def writable_paths(self) -> tuple[str, ...]:
        return tuple(
            exception.value
            for exception in self.exceptions
            if exception.kind == "writable_path"
        )

    def of_kind(self, kind: str) -> tuple[SecurityException, ...]:
        return tuple(item for item in self.exceptions if item.kind == kind)

    @property
    def host_pid(self) -> bool:
        return bool(self.of_kind("host_pid"))

    @property
    def host_ipc(self) -> bool:
        return bool(self.of_kind("host_ipc"))

    @property
    def privileged(self) -> bool:
        return bool(self.of_kind("privileged"))

    @property
    def host_network(self) -> bool:
        return bool(self.of_kind("host_network"))


@dataclass(frozen=True, slots=True)
class PortPublication:
    """A port this role publishes, beyond whatever ingress routes to it.

    Ingress-routed ports are DERIVED from `[[ingress.routes]]` and must not be
    declared here — two sources for one port is how they drift. This section is
    for the ports ingress cannot describe, and the case that forced it is
    `dotmac_sub`'s syslog listener: **UDP 514**. An HTTP reverse proxy has no
    way to express a UDP listener, so a descriptor with no port section drops it
    silently and the rendered file is missing the one thing that service is for.

    ## Why `bind` was replaced (0.3.0a1)

    `bind` was a free-form string defaulting to loopback, and its docstring
    asked that widening it "be visible in a diff". That is review discipline,
    not a refusal, and it could not express the question that actually matters:
    WHICH ADDRESS FAMILIES. A short-form publish spawns one `docker-proxy` per
    family, so a descriptor that says nothing about IPv6 gets IPv6 anyway — and
    the `ip6tables DOCKER-USER` rules written to cover it cannot fire, because
    that chain is reachable only from FORWARD while `docker-proxy` terminates an
    IPv6 connection locally on INPUT. Every such rule measured on this fleet
    showed a zero packet counter while the port it named was open.

    So `exposure` and `address_family` are DECLARED, both mandatory, and the
    bind address is DERIVED from them. A derived address cannot be misleading;
    a declared one repeatedly was.

    ## What is declared, and what is resolved elsewhere

    Everything here is a NAME or a posture. `source_set` names a set;
    `dotmac-deployment-control` resolves it to addresses at authorization and
    freezes the result into the plan digest. `approval_ref` names a policy;
    `dotmac-approvals` decides. This facility can refuse a shape and can never
    grant one, which is exactly the amount of authority a renderer should have.
    """

    container: int
    host: int
    exposure: str
    address_family: str
    protocol: str
    tls: str
    authentication: str
    source_set: str
    telemetry: bool
    approval_ref: str
    rationale_url: str

    PROTOCOLS: ClassVar[tuple[str, ...]] = ("tcp", "udp")
    EXPOSURES: ClassVar[tuple[str, ...]] = ingress_contract.EXPOSURES
    FAMILIES: ClassVar[tuple[str, ...]] = ingress_contract.ADDRESS_FAMILIES
    AUTHENTICATIONS: ClassVar[tuple[str, ...]] = ingress_contract.AUTHENTICATIONS
    TLS_MODES: ClassVar[tuple[str, ...]] = ingress_contract.TLS_MODES

    @classmethod
    def parse(cls, table: _Table) -> PortPublication:
        container = table.int_("container", minimum=1, maximum=65535)
        host = table.int_("host", minimum=1, maximum=65535)
        protocol = table.str_("protocol", default="tcp")
        # Popped rather than left to `done()`: an unknown-key error would be
        # correct but unhelpful, and this is the one removal a live consumer is
        # guaranteed to hit. A descriptor that still declares `bind` must fail
        # loudly rather than have the value silently ignored — an ignored bind
        # reads, in a diff, exactly like an honoured one.
        if table.str_("bind", default=""):
            raise SpecError(
                "`bind` was removed in 0.3.0a1: declare `exposure` "
                f"({'|'.join(cls.EXPOSURES)}) and `address_family` "
                f"({'|'.join(cls.FAMILIES)}) instead, and the bind address is "
                "derived from them",
                where=table.path,
            )
        exposure = table.str_("exposure")
        address_family = table.str_("address_family")
        # `default=""` rather than a real default, so "declared as none" and
        # "not declared" stay distinguishable: a private or public publication
        # has to SAY what its TLS posture is, and cannot inherit one.
        tls = table.str_("tls", default="")
        authentication = table.str_("authentication", default="")
        source_set = table.str_("source_set", default="")
        telemetry = table.bool_("telemetry", default=False)
        approval_ref = table.str_("approval_ref", default="")
        rationale_url = table.str_("rationale_url", default="")
        table.done()

        where = table.path
        if protocol not in cls.PROTOCOLS:
            raise SpecError(f"protocol must be one of {cls.PROTOCOLS}", where=where)
        if exposure not in cls.EXPOSURES:
            raise SpecError(f"exposure must be one of {cls.EXPOSURES}", where=where)
        if address_family not in cls.FAMILIES:
            raise SpecError(
                f"address_family must be one of {cls.FAMILIES}", where=where
            )
        if tls and tls not in cls.TLS_MODES:
            raise SpecError(f"tls must be one of {cls.TLS_MODES}", where=where)
        if authentication and authentication not in cls.AUTHENTICATIONS:
            raise SpecError(
                f"authentication must be one of {cls.AUTHENTICATIONS}", where=where
            )
        if source_set:
            source_set = ingress_contract.parse_source_set(
                source_set, field="source_set", where=where
            )
        if approval_ref:
            approval_ref = ingress_contract.parse_approval_ref(
                approval_ref, where=where
            )
        if rationale_url:
            ingress_contract.refuse_address_literal(
                rationale_url, field="rationale_url", where=where
            )

        if exposure == "none":
            declared = sorted(
                name
                for name, value in (
                    ("approval_ref", approval_ref),
                    ("authentication", authentication),
                    ("rationale_url", rationale_url),
                    ("source_set", source_set),
                    ("telemetry", telemetry),
                    ("tls", tls not in ("", "none")),
                )
                if value
            )
            if declared:
                raise SpecError(
                    'exposure = "none" emits no publication at all, so it '
                    f"cannot carry {declared}. A control declared on a socket "
                    "that does not exist is a control nobody will look for "
                    "again",
                    where=where,
                )
            tls = "none"
        elif exposure == "loopback":
            if source_set:
                raise SpecError(
                    'exposure = "loopback" is reachable only from the host '
                    "itself, so a source set has nothing to filter. Declaring "
                    "one implies a containment the kernel does not consult",
                    where=where,
                )
            tls = tls or "none"
        else:
            # private and public: the TLS posture is a decision, never a
            # default, because the default would be the wrong one exactly when
            # it matters.
            if not tls:
                raise SpecError(
                    f"exposure = {exposure!r} must declare `tls` explicitly "
                    f"(one of {cls.TLS_MODES}). An inherited TLS posture on a "
                    "routable socket is a posture nobody chose",
                    where=where,
                )
            if not source_set:
                raise SpecError(
                    f"exposure = {exposure!r} must declare a named `source_set`. "
                    "Deployment control resolves the name at authorization; "
                    "this descriptor never holds the addresses",
                    where=where,
                )

        if exposure == "public":
            # Everything else in this vocabulary is reachable only from a place
            # someone already controls. `public` is not, so it carries the whole
            # burden: encrypted, authenticated, source-scoped, observed, and
            # traceable to a policy a reader can go and read.
            missing = sorted(
                name
                for name, value in (
                    ("approval_ref", approval_ref),
                    ("authentication", authentication),
                    ("rationale_url", rationale_url),
                    ("telemetry", telemetry),
                )
                if not value
            )
            if missing:
                raise SpecError(f'exposure = "public" requires {missing}', where=where)
            if tls == "none":
                raise SpecError(
                    'exposure = "public" cannot declare tls = "none"', where=where
                )
        elif approval_ref or rationale_url:
            raise SpecError(
                "approval_ref and rationale_url belong to a public exposure. On "
                f"a {exposure!r} publication they document an approval nothing "
                "checks, which is how an approval locator becomes decoration",
                where=where,
            )

        return cls(
            container=container,
            host=host,
            exposure=exposure,
            address_family=address_family,
            protocol=protocol,
            tls=tls,
            authentication=authentication,
            source_set=source_set,
            telemetry=telemetry,
            approval_ref=approval_ref,
            rationale_url=rationale_url,
        )

    # ── derived ─────────────────────────────────────────────────────────────

    @property
    def families(self) -> tuple[str, ...]:
        """The concrete families this publication declares, in a fixed order.

        Empty for `none`: a publication that emits no socket serves no family,
        and returning `("ipv4",)` there would make every projection count a
        socket that does not exist.
        """
        if self.exposure == "none":
            return ()
        if self.address_family == "dual_stack":
            return ingress_contract.FAMILIES
        return (self.address_family,)

    def host_ip(self, role_code: str, family: str) -> str:
        """The rendered `host_ip` for one family.

        Loopback derives a literal. Everything routable derives a REQUIRED
        variable with no default: a default is precisely what lets a misleading
        value hide the effective bind, so there is nothing to be misled by — an
        operator who supplies nothing gets a refusal, not a wildcard.
        """
        return ingress_contract.derived_host_ip(
            self.exposure, family, role_code, self.host
        )


@dataclass(frozen=True, slots=True)
class VolumeMount:
    """A NAMED volume this role mounts. Host bind mounts are deliberately absent.

    A named volume is ordinary persistence — uploads that outlive an image
    digest. A host BIND mount is something else: it grants the container a piece
    of the host's filesystem, and `dotmac_sub` needs exactly three of them
    (`/etc/wireguard`, the docker socket, the WireGuard state) for reasons that
    are security decisions rather than storage decisions.

    So a bind mount is declared as a `[[roles.security.exceptions]]` of kind
    `bind_mount`, where it carries a justification and a named approver and where
    a reviewer scanning for grants will find it. Allowing it here as well would
    give it a second, quieter home — which is how the docker socket ends up
    mounted with nobody having said why.
    """

    name: str
    target: str
    read_only: bool = False

    @classmethod
    def parse(cls, table: _Table) -> VolumeMount:
        name = table.str_("name", pattern=_CODE)
        target = table.str_("target", pattern=re.compile(r"^/\S+$"))
        read_only = table.bool_("read_only", default=False)
        table.done()
        return cls(name=name, target=target, read_only=read_only)


@dataclass(frozen=True, slots=True)
class HealthCheck:
    """One probe.

    ``kind`` separates the two probes that must never be the same command:
    liveness answers "is this process alive" with NO dependency access, and
    readiness answers "can this process serve" and therefore must fail when a
    dependency is down. ERP's single unconditional ``/health`` is what happens
    when one endpoint tries to be both — it satisfies the liveness contract by
    never failing, which makes it useless as the readiness gate a deployment
    actually needs.
    """

    kind: str
    path: str
    port: int
    interval_seconds: int
    timeout_seconds: int
    retries: int
    start_period_seconds: int
    probe: tuple[str, ...] = ()
    """The command the container runs, when the default will not work.

    The default probes with Python's standard library, because every product in
    this fleet ships a Python runtime and therefore certainly has it. It does
    NOT use `wget` or `curl`: a minimal `python:*-slim` runtime has neither, and
    an earlier version of the renderer emitted a `wget` probe into
    `dotmac_erp`'s Compose file — where the image has no `wget`, so the
    healthcheck would have failed permanently and `depends_on: service_healthy`
    would never have been satisfied. A probe that cannot run is worse than no
    probe: it does not report "unknown", it reports "unhealthy" forever.

    Declare this explicitly for any role whose image is not a Python one.
    """

    KINDS: ClassVar[tuple[str, ...]] = ("live", "ready")

    def probe_command(self) -> tuple[str, ...]:
        """The declared probe, or the stdlib-Python default.

        Derived rather than declared by default so that every product's probe is
        the same shape and a reviewer comparing two rendered files is comparing
        deployments rather than probe styles.
        """
        if self.probe:
            return self.probe
        script = (
            "import sys,urllib.request;"
            f"sys.exit(0 if urllib.request.urlopen("
            f"'http://127.0.0.1:{self.port}{self.path}',"
            f"timeout={self.timeout_seconds}).status==200 else 1)"
        )
        return ("python", "-c", script)

    @classmethod
    def parse(cls, table: _Table, kind: str) -> HealthCheck:
        path = table.str_("path", pattern=re.compile(r"^/\S*$"))
        port = table.int_("port", minimum=1, maximum=65535)
        interval = table.int_("interval_seconds", default=10, minimum=1, maximum=3600)
        timeout = table.int_("timeout_seconds", default=5, minimum=1, maximum=600)
        retries = table.int_("retries", default=3, minimum=1, maximum=60)
        start_period = table.int_(
            "start_period_seconds", default=20, minimum=0, maximum=3600
        )
        probe = table.str_list("probe", default=())
        table.done()
        if timeout >= interval * retries + start_period:
            raise SpecError(
                "timeout_seconds is larger than the whole probe budget; the probe "
                "can never fail, which is the shallow-health defect",
                where=table.path,
            )
        return cls(
            kind=kind,
            path=path,
            port=port,
            interval_seconds=interval,
            timeout_seconds=timeout,
            retries=retries,
            start_period_seconds=start_period,
            probe=probe,
        )


@dataclass(frozen=True, slots=True)
class WorkerContract:
    """How a background role proves it is working, not merely running.

    A Celery worker whose process is up and whose queue is not being drained is
    indistinguishable from a healthy one at the container level. Sub learned
    this the expensive way: a stale Beat container survived a rollout and
    scheduled failing tasks for hours while every container-level check was
    green.
    """

    kind: str
    ping_command: tuple[str, ...]
    heartbeat_max_age_seconds: int
    max_backlog: int

    KINDS: ClassVar[tuple[str, ...]] = ("celery", "custom")

    @classmethod
    def parse(cls, table: _Table) -> WorkerContract:
        kind = table.str_("kind", default="custom")
        if kind not in cls.KINDS:
            raise SpecError(f"kind must be one of {cls.KINDS}", where=table.path)
        ping_command = table.str_list("ping_command")
        if not ping_command:
            raise SpecError("ping_command may not be empty", where=table.path)
        heartbeat = table.int_(
            "heartbeat_max_age_seconds", default=120, minimum=5, maximum=86400
        )
        backlog = table.int_("max_backlog", default=1000, minimum=1)
        table.done()
        return cls(
            kind=kind,
            ping_command=ping_command,
            heartbeat_max_age_seconds=heartbeat,
            max_backlog=backlog,
        )


@dataclass(frozen=True, slots=True)
class Role:
    """One process role: the unit a deployment starts, gates and verifies."""

    code: str
    command: tuple[str, ...]
    replicas: int
    depends_on: tuple[str, ...]
    resources: Resources
    security: Security
    live: HealthCheck | None
    ready: HealthCheck | None
    stop_grace_seconds: int
    worker: WorkerContract | None
    scheduler_tick_max_age_seconds: int | None
    scheduler_tick_command: tuple[str, ...]
    """How to read when the scheduler last ticked — a command printing a UNIX
    timestamp on stdout.

    Required alongside the budget, and declared for the same reason as
    `heads_command`: an earlier provider defaulted to
    `stat -c %Y /tmp/celerybeat-schedule`, which is a Celery Beat implementation
    detail, is wrong for every non-Celery scheduler, and would report the
    schedule FILE's mtime rather than a successful tick even for Celery — a
    Beat that is running and failing every task still touches that file.
    """

    materials: tuple[str, ...]
    environment: tuple[tuple[str, str], ...] = ()
    """Ordinary, non-secret configuration this role needs, as literal values.

    Kept apart from `materials`, which are NAMES the host resolves. The
    distinction is the whole of ADR-0009 applied to a rendered file: a material
    renders as `${NAME:?…}` and its value never enters the repository, while an
    entry here renders literally and is therefore reviewable, diffable and
    permanently in Git history.

    The section exists because without it a descriptor cannot say
    `CELERY_BROKER_URL` or `C_FORCE_ROOT` or `PYTHONUNBUFFERED`, and
    `dotmac_erp`'s rendered Compose file came out with no Celery configuration
    at all — a worker that would start and then have nothing to connect to.

    The secrets guard scans these values like every other string, so a
    credential pasted here is refused at parse time rather than at review time.
    """

    ports: tuple[PortPublication, ...] = ()
    volumes: tuple[VolumeMount, ...] = ()

    @classmethod
    def parse(cls, table: _Table) -> Role:
        code = table.str_("code", pattern=_CODE)
        command = table.str_list("command")
        replicas = table.int_("replicas", default=1, minimum=0, maximum=64)
        depends_on = table.str_list("depends_on", default=(), pattern=_CODE)
        resources = Resources.parse(table.table("resources") or _Table({}, table.path))
        security = Security.parse(
            table.table("security", optional=True), where=table.path
        )
        health = table.table("health", optional=True)
        live = ready = None
        if health is not None:
            live_table = health.table("live", optional=True)
            ready_table = health.table("ready", optional=True)
            live = HealthCheck.parse(live_table, "live") if live_table else None
            ready = HealthCheck.parse(ready_table, "ready") if ready_table else None
            health.done()
        stop_grace = table.int_(
            "stop_grace_seconds", default=30, minimum=1, maximum=3600
        )
        worker_table = table.table("worker", optional=True)
        worker = WorkerContract.parse(worker_table) if worker_table else None
        scheduler = table.table("scheduler", optional=True)
        scheduler_tick: int | None = None
        scheduler_tick_command: tuple[str, ...] = ()
        if scheduler is not None:
            scheduler_tick = scheduler.int_(
                "last_tick_max_age_seconds", minimum=10, maximum=86400
            )
            scheduler_tick_command = scheduler.str_list("tick_command")
            scheduler.done()
            if not scheduler_tick_command:
                raise SpecError("tick_command may not be empty", where=scheduler.path)
        materials = table.str_list("materials", default=(), pattern=_MATERIAL_NAME)
        environment_table = table.table("environment", optional=True)
        environment: tuple[tuple[str, str], ...] = ()
        if environment_table is not None:
            entries: list[tuple[str, str]] = []
            for key in sorted(environment_table.keys()):
                if not _ENV_NAME.match(key):
                    raise SpecError(
                        f"environment key {key!r} is not an UPPER_SNAKE name",
                        where=environment_table.path,
                    )
                entries.append((key, environment_table.str_(key)))
            environment_table.done()
            environment = tuple(entries)
        ports = tuple(PortPublication.parse(item) for item in table.tables("ports"))
        volumes = tuple(VolumeMount.parse(item) for item in table.tables("volumes"))
        table.done()
        if live is not None and ready is not None and live.path == ready.path:
            raise SpecError(
                f"role {code!r} points liveness and readiness at the same path "
                f"({live.path!r}). One of them is then wrong: liveness must not "
                "touch a dependency and readiness must fail when one is down",
                where=table.path,
            )
        return cls(
            code=code,
            command=command,
            replicas=replicas,
            depends_on=depends_on,
            resources=resources,
            security=security,
            live=live,
            ready=ready,
            stop_grace_seconds=stop_grace,
            worker=worker,
            scheduler_tick_max_age_seconds=scheduler_tick,
            scheduler_tick_command=scheduler_tick_command,
            materials=materials,
            environment=environment,
            ports=ports,
            volumes=volumes,
        )


@dataclass(frozen=True, slots=True)
class Migration:
    """The one place DDL happens, and the declaration that decides HOW.

    ``compatibility`` is the field the whole deployment engine branches on, and
    it is the product's declaration rather than the engine's guess:

    - ``online`` — the new schema is readable and writable by the PREVIOUS
      image, so a warm candidate may run beside the old primary and the old
      image remains a valid rollback target.
    - ``maintenance_required`` — it is not, so ingress, app, workers and
      scheduler stop before DDL, and reusing the previous image afterwards is
      REFUSED rather than attempted.

    Getting this wrong in the safe direction costs a maintenance window.
    Getting it wrong in the unsafe direction runs an old image against a schema
    it cannot read, which is a data-loss shape, so the engine refuses the
    online path for a ``maintenance_required`` release rather than warning.
    """

    command: tuple[str, ...]
    owner_material: str
    expected_heads: tuple[str, ...]
    compatibility: str
    lock_timeout_seconds: int
    lock_retries: int
    preflight_command: tuple[str, ...]
    heads_command: tuple[str, ...] = ()
    """How to READ the heads the database is actually at.

    Declared because it cannot be derived. An earlier provider guessed it by
    swapping the `upgrade` token in `command` for `current` — which happens to
    work for `alembic upgrade heads` and silently produces nonsense for
    `python -m dotmac_integrator.migrate upgrade heads` (whose read verb is
    `current` in a different argv position) or for any product whose migration
    entry point is not Alembic-shaped at all.

    A guess that is right for the product you tested on and wrong for the next
    one is the worst kind: `verify_heads` would compare the declared heads
    against the output of a command that did something else, and the comparison
    would fail for a reason nothing explains.
    """

    COMPATIBILITY: ClassVar[tuple[str, ...]] = ("online", "maintenance_required")

    @classmethod
    def parse(cls, table: _Table) -> Migration:
        command = table.str_list("command")
        if not command:
            raise SpecError("command may not be empty", where=table.path)
        owner_material = table.str_("owner_material", pattern=_MATERIAL_NAME)
        expected_heads = table.str_list("expected_heads")
        if not expected_heads:
            raise SpecError(
                "expected_heads may not be empty. `alembic upgrade heads` is "
                "plural because a composition has several lineages, and a "
                "deployment that cannot say which heads it expects cannot "
                "detect a missing one",
                where=table.path,
            )
        compatibility = table.str_("compatibility")
        if compatibility not in cls.COMPATIBILITY:
            raise SpecError(
                f"compatibility must be one of {cls.COMPATIBILITY}", where=table.path
            )
        lock_timeout = table.int_(
            "lock_timeout_seconds", default=300, minimum=5, maximum=7200
        )
        lock_retries = table.int_("lock_retries", default=3, minimum=1, maximum=100)
        preflight = table.str_list("preflight_command", default=())
        heads = table.str_list("heads_command", default=())
        table.done()
        if not heads:
            raise SpecError(
                "heads_command is required. `verify_heads` compares the declared "
                "expected_heads against what this command prints, and there is no "
                "way to derive the read verb from the upgrade command: "
                "`alembic upgrade heads` reads with `alembic current`, while "
                "`python -m x.migrate upgrade heads` reads with "
                "`python -m x.migrate current`. Guessing is right for one product "
                "and wrong for the next",
                where=table.path,
            )
        _unique(expected_heads, what="migration head", where=table.path)
        return cls(
            command=command,
            owner_material=owner_material,
            expected_heads=expected_heads,
            compatibility=compatibility,
            lock_timeout_seconds=lock_timeout,
            lock_retries=lock_retries,
            preflight_command=preflight,
            heads_command=heads,
        )

    @property
    def is_online(self) -> bool:
        return self.compatibility == "online"


@dataclass(frozen=True, slots=True)
class IngressRoute:
    """One location block's worth of declared requirement."""

    path: str
    role: str
    port: int
    websocket: bool
    sse: bool
    max_body_bytes: int
    read_timeout_seconds: int
    send_timeout_seconds: int

    @classmethod
    def parse(cls, table: _Table) -> IngressRoute:
        path = table.str_("path", pattern=re.compile(r"^/\S*$"))
        role = table.str_("role", pattern=_CODE)
        port = table.int_("port", minimum=1, maximum=65535)
        websocket = table.bool_("websocket", default=False)
        sse = table.bool_("sse", default=False)
        max_body = table.int_("max_body_bytes", default=10 * 1024 * 1024, minimum=0)
        read_timeout = table.int_(
            "read_timeout_seconds", default=60, minimum=1, maximum=86400
        )
        send_timeout = table.int_(
            "send_timeout_seconds", default=60, minimum=1, maximum=86400
        )
        table.done()
        if (websocket or sse) and read_timeout < 300:
            raise SpecError(
                "a websocket or SSE route needs read_timeout_seconds >= 300; a "
                "60-second proxy read timeout silently severs long-lived "
                "connections and looks like an application bug",
                where=table.path,
            )
        return cls(
            path=path,
            role=role,
            port=port,
            websocket=websocket,
            sse=sse,
            max_body_bytes=max_body,
            read_timeout_seconds=read_timeout,
            send_timeout_seconds=send_timeout,
        )


@dataclass(frozen=True, slots=True)
class StaticStrategy:
    """How static and uploaded files persist across a digest promotion.

    Three answers, and only three, because the fourth — a bind mount of the
    source tree — is the ERP defect this facility exists to remove:

    - ``image`` — baked into the image. Immutable, promoted with the digest.
    - ``volume`` — a named volume. For USER UPLOADS, which cannot live in an
      image because they outlive it.
    - ``none`` — the product serves them itself.
    """

    static: str
    uploads: str
    uploads_volume: str
    uploads_path: str = "/srv/uploads"
    """Where the uploads volume mounts INSIDE the container.

    Declared rather than invented. The renderer used to hardcode `/srv/uploads`,
    and `dotmac_sub` writes to `/app/uploads` — so a descriptor that declared the
    uploads volume got a mount at a path the application does not use, and a
    role that ALSO declared the real path got two upload volumes. One of them
    would have been silently empty.
    """

    STRATEGIES: ClassVar[tuple[str, ...]] = ("image", "volume", "none")

    @classmethod
    def parse(cls, table: _Table | None, *, where: str) -> StaticStrategy:
        if table is None:
            return cls(static="image", uploads="none", uploads_volume="")
        static = table.str_("static", default="image")
        uploads = table.str_("uploads", default="none")
        uploads_volume = table.str_(
            "uploads_volume",
            default="",
            pattern=re.compile(r"^[a-z0-9][a-z0-9_-]{0,62}$|^$"),
        )
        uploads_path = table.str_(
            "uploads_path", default="/srv/uploads", pattern=re.compile(r"^/\S+$")
        )
        table.done()
        for name, value in (("static", static), ("uploads", uploads)):
            if value not in cls.STRATEGIES:
                raise SpecError(f"{name} must be one of {cls.STRATEGIES}", where=where)
        if uploads == "volume" and not uploads_volume:
            raise SpecError("uploads='volume' needs uploads_volume", where=where)
        if static == "volume":
            raise SpecError(
                "static='volume' is refused. Static assets belong to the image "
                "digest; a volume makes them mutable state that a rollback "
                "cannot restore and a bind mount is how ERP's production host "
                "came to serve a different tree from its image",
                where=where,
            )
        return cls(
            static=static,
            uploads=uploads,
            uploads_volume=uploads_volume,
            uploads_path=uploads_path,
        )


@dataclass(frozen=True, slots=True)
class Ingress:
    """The edge, and the ONE place a `public` exposure legitimately lives.

    A web application is not published publicly; its EDGE is, and the
    application sits on loopback behind it. That separation is the whole reason
    an edge exists, so the edge declares its own `exposure` and
    `address_family` exactly like any other publication and
    `_validate_cross_field` refuses a directly-published application port that
    an edge route already covers. An edge that can be bypassed is decoration.

    `upstream_address_family` is the family the edge reaches its own upstreams
    on — always loopback, never routable, and declared rather than assumed so
    that "which families does this deployment listen on" has one answer read
    off the descriptor instead of two answers inferred from Docker's defaults.
    """

    host: str
    routes: tuple[IngressRoute, ...]
    redirect_http: bool
    tls_policy: str
    trusted_proxies: tuple[str, ...]
    security_headers: bool
    static: StaticStrategy
    exposure: str
    address_family: str
    upstream_address_family: str
    authentication: str
    source_set: str
    approval_ref: str
    rationale_url: str

    TLS_POLICIES: ClassVar[tuple[str, ...]] = ("modern", "intermediate")

    @classmethod
    def parse(cls, table: _Table | None) -> Ingress | None:
        if table is None:
            return None
        host = table.str_("host", pattern=_HOSTNAME)
        routes = tuple(
            IngressRoute.parse(item) for item in table.tables("routes", minimum=1)
        )
        redirect_http = table.bool_("redirect_http", default=True)
        tls_policy = table.str_("tls_policy", default="modern")
        trusted_proxies = table.str_list("trusted_proxies", default=())
        security_headers = table.bool_("security_headers", default=True)
        exposure = table.str_("exposure")
        address_family = table.str_("address_family")
        upstream_address_family = table.str_("upstream_address_family", default="ipv4")
        authentication = table.str_("authentication", default="")
        source_set = table.str_("source_set", default="")
        approval_ref = table.str_("approval_ref", default="")
        rationale_url = table.str_("rationale_url", default="")
        static = StaticStrategy.parse(
            table.table("static", optional=True), where=table.path
        )
        table.done()
        if tls_policy not in cls.TLS_POLICIES:
            raise SpecError(
                f"tls_policy must be one of {cls.TLS_POLICIES}", where=table.path
            )
        if exposure not in ingress_contract.EXPOSURES:
            raise SpecError(
                f"exposure must be one of {ingress_contract.EXPOSURES}",
                where=table.path,
            )
        if exposure == "none":
            raise SpecError(
                'an ingress declaring exposure = "none" publishes no listener, '
                "so every route it declares is unreachable. Delete the "
                "[ingress] table instead — an edge nobody can reach is not a "
                "safer edge, it is an outage that renders cleanly",
                where=table.path,
            )
        if address_family not in ingress_contract.ADDRESS_FAMILIES:
            raise SpecError(
                f"address_family must be one of {ingress_contract.ADDRESS_FAMILIES}",
                where=table.path,
            )
        if upstream_address_family not in ingress_contract.FAMILIES:
            raise SpecError(
                "upstream_address_family must be one of "
                f"{ingress_contract.FAMILIES}; an edge reaches its upstream over "
                "loopback on exactly one family, and dual_stack there would "
                "double every rendered upstream for no reachability gain",
                where=table.path,
            )
        if authentication and authentication not in ingress_contract.AUTHENTICATIONS:
            raise SpecError(
                f"authentication must be one of {ingress_contract.AUTHENTICATIONS}",
                where=table.path,
            )
        if source_set:
            source_set = ingress_contract.parse_source_set(
                source_set, field="source_set", where=table.path
            )
        # `trusted_proxies` used to hold CIDRs, and a CIDR is exactly what the
        # named-source-set rule exists to remove: the set of proxies in front
        # of an edge is environment topology, it differs per environment, and
        # a stale entry here silently makes a spoofed `X-Forwarded-For`
        # authoritative. So each entry is now a source-set NAME that deployment
        # control resolves.
        trusted_proxies = tuple(
            ingress_contract.parse_source_set(
                entry, field="trusted_proxies entry", where=table.path
            )
            for entry in trusted_proxies
        )
        if exposure == "public":
            missing = sorted(
                key
                for key, value in (
                    ("approval_ref", approval_ref),
                    ("rationale_url", rationale_url),
                )
                if not value
            )
            if missing:
                raise SpecError(
                    'an ingress with exposure = "public" requires '
                    f"{missing}: the locator names the policy the exposure "
                    "claims to satisfy, and it is inside the digested document "
                    "so changing it is a plan change",
                    where=table.path,
                )
            approval_ref = ingress_contract.parse_approval_ref(
                approval_ref, where=table.path
            )
        elif approval_ref or rationale_url:
            raise SpecError(
                "approval_ref and rationale_url belong to a public ingress",
                where=table.path,
            )
        if exposure == "private" and not source_set:
            raise SpecError(
                'an ingress with exposure = "private" must name a source_set; '
                "deployment control resolves it at authorization",
                where=table.path,
            )
        _unique(
            [route.path for route in routes],
            what="ingress route path",
            where=table.path,
        )
        return cls(
            host=host,
            routes=routes,
            redirect_http=redirect_http,
            tls_policy=tls_policy,
            trusted_proxies=trusted_proxies,
            security_headers=security_headers,
            static=static,
            exposure=exposure,
            address_family=address_family,
            upstream_address_family=upstream_address_family,
            authentication=authentication,
            source_set=source_set,
            approval_ref=approval_ref,
            rationale_url=rationale_url,
        )

    @property
    def families(self) -> tuple[str, ...]:
        if self.address_family == "dual_stack":
            return ingress_contract.FAMILIES
        return (self.address_family,)


@dataclass(frozen=True, slots=True)
class BackupDataset:
    """One thing that is backed up, and the proof it can come back.

    ``restore_proof_max_age_days`` is the field that separates a backup from a
    belief. An untested backup has never been shown to restore, and the moment
    at which that is discovered is always the worst possible one.

    ``expected_backup_interval_seconds`` is a SEPARATE control and must stay
    one. It is how often a backup is expected, and it decides staleness; the
    field above is how old the newest PROVED restore may be, and it decides
    whether recovery has ever been demonstrated. A product taking hourly backups
    nobody has ever restored passes the first and fails the second, which is
    precisely the state the fleet was in — so merging them would delete the only
    control that was reporting the real problem.

    ``lineage`` names the DATA, independently of the host it currently lives on
    and the party that holds it (`recovery_identity.DatasetIdentityV1`). Those
    are the two things that change while the data does not, and a proof keyed to
    either is orphaned at the exact moment it matters. Optional, because a
    dataset the product restores itself needs no cross-party identity — but
    REQUIRED the moment an external executor is declared.

    ``external_executor`` is what turns a `backup` step into a
    `verify_external_recovery_receipt` step: when another party executes
    recovery, this deployment cannot observe the restore and must not emit a
    plan step claiming it performed one.
    """

    code: str
    kind: str
    material: str
    retention_days: int
    checksum: str
    encryption: str
    offsite: str
    restore_proof_max_age_days: int
    expected_backup_interval_seconds: int
    verify: tuple[str, ...]
    lineage: str = ""
    external_executor: ExternalExecutorV1 | None = None

    KINDS: ClassVar[tuple[str, ...]] = ("postgres", "object_store", "volume")
    CHECKSUMS: ClassVar[tuple[str, ...]] = ("sha256", "sha512")
    ENCRYPTIONS: ClassVar[tuple[str, ...]] = ("age", "gpg", "none")
    #: The four privilege verifications are NOT new vocabulary. `recovery.py`
    #: has modelled `MEMBERSHIPS`, `OBJECT_OWNERSHIP`, role attributes and
    #: `CatalogEvidence.effective_privileges` since the bundle contract landed;
    #: this tuple simply did not list them, so a descriptor asking for the checks
    #: that decide whether a restore is USABLE was refused at parse. Plumbing,
    #: not design.
    VERIFICATIONS: ClassVar[tuple[str, ...]] = (
        "schema",
        "row_counts",
        "migration_heads",
        *PRIVILEGE_VERIFICATIONS,
    )

    @property
    def externally_executed(self) -> bool:
        return self.external_executor is not None

    def identity(self, product: str) -> DatasetIdentityV1:
        """The cross-party identity of this dataset.

        Raises rather than inventing one from `code` when no lineage is
        declared: a lineage silently defaulted to the dataset code would be
        unique only within one descriptor, so two products would produce
        colliding identities and a receipt for one would satisfy the other.
        """
        if not self.lineage:
            raise SpecError(
                f"dataset {self.code!r} declares no `lineage`, so it has no "
                "identity a receipt from another party can be compared against. "
                "Mint one opaque token for this data and never change it"
            )
        return DatasetIdentityV1(
            product=product, dataset=self.code, lineage=self.lineage
        )

    @classmethod
    def parse(cls, table: _Table) -> BackupDataset:
        code = table.str_("code", pattern=_CODE)
        kind = table.str_("kind")
        if kind not in cls.KINDS:
            raise SpecError(f"kind must be one of {cls.KINDS}", where=table.path)
        material = table.str_("material", pattern=_MATERIAL_NAME)
        retention_days = table.int_("retention_days", minimum=1, maximum=3650)
        checksum = table.str_("checksum", default="sha256")
        encryption = table.str_("encryption", default="none")
        offsite = table.str_("offsite", default="")
        restore_proof = table.int_(
            "restore_proof_max_age_days", default=30, minimum=1, maximum=365
        )
        # A SEPARATE control from the window above, defaulting to daily. Minimum
        # 60s rather than 1: a cadence a host cannot meet turns every deployment
        # into a stale-backup report, which is how a real staleness signal gets
        # ignored.
        interval = table.int_(
            "expected_backup_interval_seconds",
            default=SECONDS_PER_DAY,
            minimum=60,
            maximum=30 * SECONDS_PER_DAY,
        )
        lineage = table.str_("lineage", default="")
        executor_table = table.table("external_executor", optional=True)
        # DEFAULT IS `schema` ALONE. It used to be ("schema", "row_counts"),
        # which would now refuse every dataset that simply omits `verify` — and
        # a default that cannot be parsed is worse than a missing one. The
        # default must name only what this facility can actually perform;
        # `row_counts` is declarable deliberately, by a dataset that names an
        # external executor able to satisfy it.
        verify = table.str_list("verify", default=("schema",))
        table.done()
        executor: ExternalExecutorV1 | None = None
        if executor_table is not None:
            executor = ExternalExecutorV1(
                kind=executor_table.str_("kind"),
                identifier=executor_table.str_("identifier"),
                # No defaults. An executor whose version is unstated produces
                # receipts that cannot be compared with the procedure this
                # descriptor accepted, and a defaulted key id would let any
                # signer stand in for the declared one.
                version=executor_table.str_("version"),
                key_id=executor_table.str_("key_id"),
            )
            executor_table.done()
            if not lineage:
                raise SpecError(
                    f"dataset {code!r} declares an external_executor and no "
                    "`lineage`. A receipt from another party has to be about "
                    "THIS data, and the dataset code alone is unique only "
                    "inside one descriptor",
                    where=table.path,
                )
            DatasetIdentityV1(
                product="", dataset=code, lineage=lineage
            ).refuse_executor_derived(executor)
        if checksum not in cls.CHECKSUMS:
            raise SpecError(
                f"checksum must be one of {cls.CHECKSUMS}", where=table.path
            )
        if encryption not in cls.ENCRYPTIONS:
            raise SpecError(
                f"encryption must be one of {cls.ENCRYPTIONS}", where=table.path
            )
        unknown = set(verify) - set(cls.VERIFICATIONS)
        if unknown:
            raise SpecError(
                f"unknown verification(s) {sorted(unknown)}",
                where=table.path,
                code=UNKNOWN_VERIFICATION,
            )
        # A verification this facility cannot PERFORM, on a dataset it will
        # verify itself. Refused here, in one place, rather than left as a
        # declaration nothing honours.
        #
        # `verify_recovery` never received this list — it compared what it knew
        # how to compare, regardless of what the descriptor asked for — so on
        # the internally executed path the declaration and the check were never
        # connected at all. `row_counts` is the member that exposes it:
        # `CatalogEvidence` carries no row counts and nothing in this package
        # can observe one, so a descriptor declaring it was asserting a check
        # that could not run.
        #
        # It stays DECLARABLE for an externally executed dataset, where a
        # receipt from an executor that can count rows genuinely claims it
        # (`external_recovery.VERIFICATION_EVIDENCE`). The refusal is therefore
        # about who will do the verifying, not about the check being worthless.
        if executor is None:
            unperformable = sorted(set(verify) & EXTERNAL_ONLY_VERIFICATIONS)
            if unperformable:
                raise SpecError(
                    f"verification(s) {unperformable} cannot be performed by "
                    "this facility, and this dataset declares no external "
                    "executor to perform them. `verify_recovery` compares two "
                    "catalogues, and nothing it can observe carries row counts "
                    "— so declaring this asks for a check that will never run "
                    "and reports as satisfied. Either remove it, or declare "
                    "the [backup.datasets.external_executor] whose signed "
                    "receipt claims it",
                    where=table.path,
                    code=UNPERFORMABLE_VERIFICATION,
                )
        if kind == "postgres" and "schema" not in verify:
            raise SpecError(
                "a postgres dataset must verify 'schema'; a restore that produces "
                "an empty database succeeds against every other check",
                where=table.path,
            )
        return cls(
            code=code,
            kind=kind,
            material=material,
            retention_days=retention_days,
            checksum=checksum,
            encryption=encryption,
            offsite=offsite,
            restore_proof_max_age_days=restore_proof,
            expected_backup_interval_seconds=interval,
            verify=verify,
            lineage=lineage,
            external_executor=executor,
        )


#: Stable identifiers for this module's backup-verification refusals. Assert
#: these in tests; read the prose. A module with more than one refusal has to be
#: testable on WHICH one fired, and `match=` on a sentence makes the sentence
#: the contract.
UNKNOWN_VERIFICATION: Final = "backup.verification.unknown"
UNPERFORMABLE_VERIFICATION: Final = "backup.verification.unperformable"


@dataclass(frozen=True, slots=True)
class DatabaseRole:
    """A role the product's database requires — as an EXPECTATION, never a source.

    This is the descriptor half of `dotmac_workspace`'s "a binding is a claim,
    not a fact". The product states which roles it believes its database needs;
    the recovery bundle carries what the source catalog actually required; and
    `recovery.verify_recovery` compares them. Nothing in this facility turns a
    declaration here into a `CREATE ROLE`, because a validator that can
    manufacture the role it is checking for can always make its own check pass.

    ``superuser`` is absent by design rather than defaulted to false. There is no
    key to write, so a descriptor cannot ask for one and a reviewer never has to
    catch it.

    ``inherit`` is declared because losing it is invisible. A role that becomes
    INHERIT silently acquires everything every group it belongs to holds, and
    nothing about the database looks different afterwards.
    """

    name: str
    kind: str
    inherit: bool
    login: bool
    bypassrls: bool
    member_of: tuple[str, ...]

    KINDS: ClassVar[tuple[str, ...]] = (
        "migration_owner",
        "tenant_app",
        "platform_app",
        "dispatcher",
        "read_only",
    )

    @classmethod
    def parse(cls, table: _Table) -> DatabaseRole:
        name = table.str_("name", pattern=_ROLE_NAME)
        kind = table.str_("kind")
        if kind not in cls.KINDS:
            raise SpecError(f"kind must be one of {cls.KINDS}", where=table.path)
        inherit = table.bool_("inherit", default=True)
        login = table.bool_("login", default=True)
        bypassrls = table.bool_("bypassrls", default=False)
        member_of = table.str_list("member_of", default=(), pattern=_ROLE_NAME)
        table.done()
        if kind == "tenant_app" and bypassrls:
            raise SpecError(
                f"role {name!r} is the tenant application role and declares "
                "BYPASSRLS. Every row-level policy in the database is then "
                "decorative for the one identity they exist to constrain",
                where=table.path,
            )
        _unique(member_of, what="membership", where=table.path)
        if name in member_of:
            raise SpecError(
                f"role {name!r} cannot be a member of itself", where=table.path
            )
        return cls(
            name=name,
            kind=kind,
            inherit=inherit,
            login=login,
            bypassrls=bypassrls,
            member_of=member_of,
        )


@dataclass(frozen=True, slots=True)
class IsolationInvariant:
    """A privilege that must — or must not — exist after a recovery.

    Both directions, because only checking the denial half is how a plane ends
    up isolated from itself: a control-plane role revoked from everything passes
    every "cannot reach" assertion and cannot run the product.

    Checked against EFFECTIVE privilege (`has_table_privilege` OR
    `has_any_column_privilege`), never against the direct-grant list. See
    `recovery.EffectivePrivilegeFact` for why the obvious query is the wrong one.
    """

    code: str
    role: str
    scope: str
    objects: tuple[str, ...]
    privileges: tuple[str, ...]
    denied: bool

    SCOPES: ClassVar[tuple[str, ...]] = ("table", "schema", "sequence", "function")

    #: All seven table privileges. A gate over the four DML ones would pass a
    #: platform table a supposedly-revoked role could still TRUNCATE, point a
    #: foreign key at, or attach a trigger to.
    TABLE_PRIVILEGES: ClassVar[tuple[str, ...]] = (
        "SELECT",
        "INSERT",
        "UPDATE",
        "DELETE",
        "TRUNCATE",
        "REFERENCES",
        "TRIGGER",
    )

    @classmethod
    def parse(cls, table: _Table) -> IsolationInvariant:
        code = table.str_("code", pattern=_CODE)
        role = table.str_("role", pattern=_ROLE_NAME)
        scope = table.str_("scope", default="table")
        if scope not in cls.SCOPES:
            raise SpecError(f"scope must be one of {cls.SCOPES}", where=table.path)
        objects = table.str_list("objects")
        denied = table.bool_("denied", default=True)
        privileges = table.str_list(
            "privileges",
            default=cls.TABLE_PRIVILEGES if scope == "table" else (),
        )
        table.done()
        if not objects:
            raise SpecError(
                "an isolation invariant over no object always passes and proves "
                "nothing",
                where=table.path,
            )
        if not privileges:
            raise SpecError(
                "an isolation invariant over no privilege always passes",
                where=table.path,
            )
        if scope == "table":
            unknown = set(privileges) - set(cls.TABLE_PRIVILEGES)
            if unknown:
                raise SpecError(
                    f"unknown table privilege(s) {sorted(unknown)}", where=table.path
                )
        _unique(objects, what="object", where=table.path)
        return cls(
            code=code,
            role=role,
            scope=scope,
            objects=objects,
            privileges=privileges,
            denied=denied,
        )


@dataclass(frozen=True, slots=True)
class DatabaseContract:
    """What the product's database is, so a recovery can be checked against it.

    ``postgres_major`` is required and not defaulted. A restore into a different
    major version is a migration wearing a recovery's clothes: it may well
    succeed, and what comes back is not the database that was backed up.
    """

    postgres_major: int
    roles: tuple[DatabaseRole, ...]
    expected_schemas: tuple[str, ...]
    isolation: tuple[IsolationInvariant, ...]
    tablespaces: str
    catalogs: tuple[DatabaseCatalogCoordinateV1, ...] = field(
        default=(), repr=False, metadata={"descriptor_since": SCHEMA_V2}
    )

    TABLESPACES: ClassVar[tuple[str, ...]] = ("none", "mapped", "declared")

    def __post_init__(self) -> None:
        if not isinstance(self.catalogs, tuple) or not all(
            isinstance(catalog, DatabaseCatalogCoordinateV1)
            for catalog in self.catalogs
        ):
            raise SpecError(
                "database catalogs must be a tuple of DatabaseCatalogCoordinateV1"
            )
        keys = tuple(
            (item.scope.value, item.schema, item.path, item.digest)
            for item in self.catalogs
        )
        if keys != tuple(sorted(set(keys))):
            raise SpecError("database catalogs must be unique and sorted")
        product_catalogs = tuple(
            item for item in self.catalogs if item.scope is DatabaseCatalogScope.PRODUCT
        )
        if product_catalogs and len(self.catalogs) != 1:
            raise SpecError("a product catalog cannot be combined with another catalog")
        expected = set(self.expected_schemas)
        covered: set[str] = set()
        for catalog in self.catalogs:
            schemas = set(catalog.complete_schemas)
            if not schemas <= expected:
                raise SpecError(
                    "a database catalog covers a schema outside expected_schemas"
                )
            if schemas & covered:
                raise SpecError("database catalogs overlap on a complete schema")
            covered.update(schemas)
            if catalog.scope is DatabaseCatalogScope.PRODUCT and schemas != expected:
                raise SpecError("a product catalog must cover every expected schema")

    @classmethod
    def parse(
        cls, table: _Table | None, *, descriptor_schema: str
    ) -> DatabaseContract | None:
        if table is None:
            return None
        postgres_major = table.int_("postgres_major", minimum=13, maximum=99)
        expected_schemas = table.str_list("expected_schemas", default=())
        tablespaces = table.str_("tablespaces", default="none")
        roles = tuple(DatabaseRole.parse(item) for item in table.tables("roles"))
        isolation = tuple(
            IsolationInvariant.parse(item) for item in table.tables("isolation")
        )
        catalogs: tuple[DatabaseCatalogCoordinateV1, ...] = ()
        if descriptor_schema in (SCHEMA_V2, SCHEMA_V3):
            parsed_catalogs: list[DatabaseCatalogCoordinateV1] = []
            for catalog_table in table.tables("catalogs"):
                try:
                    scope = DatabaseCatalogScope(catalog_table.str_("scope"))
                except ValueError as exc:
                    raise SpecError(
                        "catalog scope must be 'module' or 'product'",
                        where=catalog_table.path,
                    ) from exc
                product_identity_table = catalog_table.table(
                    "product_identity", optional=True
                )
                product_identity = None
                if product_identity_table is not None:
                    product_identity = DatabaseCatalogProductIdentityV1(
                        descriptor_product=product_identity_table.str_(
                            "descriptor_product"
                        ),
                        catalog_product=product_identity_table.str_("catalog_product"),
                        catalog_version=product_identity_table.str_("catalog_version"),
                        mapping_ref=product_identity_table.str_(
                            "mapping_ref", default=""
                        ),
                    )
                    product_identity_table.done()
                parsed_catalogs.append(
                    DatabaseCatalogCoordinateV1(
                        schema=catalog_table.str_("schema"),
                        path=catalog_table.str_("path"),
                        digest=catalog_table.str_("digest"),
                        scope=scope,
                        complete_schemas=catalog_table.str_list("complete_schemas"),
                        product_identity=product_identity,
                    )
                )
                catalog_table.done()
            catalogs = tuple(parsed_catalogs)
            if not catalogs:
                raise SpecError(
                    "ProductDeploymentSpec.v2 [database] requires at least one "
                    "database catalog coordinate",
                    where=table.path,
                )
        table.done()
        if tablespaces not in cls.TABLESPACES:
            raise SpecError(
                f"tablespaces must be one of {cls.TABLESPACES}. There is no fourth "
                "value meaning 'nobody looked' — a bundle records the decision, and "
                "silence restores fine on the host it came from and fails on the "
                "replacement",
                where=table.path,
            )
        if not roles:
            raise SpecError(
                "a database contract declares at least one role. A product whose "
                "descriptor names no role cannot have a recovery checked against "
                "anything",
                where=table.path,
            )
        _unique([role.name for role in roles], what="database role", where=table.path)
        _unique([item.code for item in isolation], what="invariant", where=table.path)
        declared = {role.name for role in roles}
        for role in roles:
            for group in role.member_of:
                if group not in declared:
                    raise SpecError(
                        f"role {role.name!r} is declared a member of {group!r}, "
                        "which the descriptor does not declare. A membership whose "
                        "group is undeclared is how a closure comes out short",
                        where=table.path,
                    )
        for invariant in isolation:
            if invariant.role not in declared:
                raise SpecError(
                    f"invariant {invariant.code!r} names role {invariant.role!r}, "
                    "which the descriptor does not declare",
                    where=table.path,
                )
        return cls(
            postgres_major=postgres_major,
            roles=roles,
            expected_schemas=expected_schemas,
            isolation=isolation,
            tablespaces=tablespaces,
            catalogs=catalogs,
        )

    def role(self, name: str) -> DatabaseRole:
        for candidate in self.roles:
            if candidate.name == name:
                return candidate
        raise SpecError(f"no database role {name!r}")


#: The rendered-asset directory holding the collector configuration, and the
#: host side of its bind mount. Shared by the renderer and the asset registry so
#: the two cannot disagree about where the file lives.
COLLECTOR_CONFIG_ASSET_DIRECTORY: Final[str] = "otel-collector"


@dataclass(frozen=True, slots=True)
class Telemetry:
    """What the deployment ships, and where.

    The single most important field is ``app_direct_shipping``. If the
    application ships its own logs AND an agent tails the same container, every
    line is stored twice, alert thresholds are silently doubled, and the
    duplicate is invisible in a dashboard. The descriptor declares which of the
    two is authoritative and the renderer refuses to configure both.
    """

    logs: bool
    metrics: bool
    traces: bool
    metrics_material: str
    endpoint_material: str
    app_direct_shipping: bool
    deployment_annotations: bool
    scrape_interval_seconds: int
    collector_image: str = ""
    """The collector image this deployment RUNS, if it runs one.

    Empty means the deployment ships nothing: the configuration is still
    rendered, and it is a specification of what a collector would need rather
    than a collector. Saying that out loud matters, because a rendered
    collector configuration sitting beside a deployment that does not run a
    collector reads, to anyone who does not check, as telemetry.

    Set it and the collector becomes a Compose service that mounts the rendered
    configuration read-only — which is what turns "we generate a collector
    config" into "signals leave this host".
    """

    collector_config_mount: str = "/etc/otelcol/config.yaml"
    """The in-container PATH of the collector configuration file.

    Its parent DIRECTORY is what is bind-mounted, never the file itself; see
    `collector_config_directory`.
    """

    collector_insecure: bool = False
    """Whether the collector's OTLP exporter may use a plaintext connection.

    `False` is the right default and was the wrong CONSTANT: hardcoding it made
    the rendered configuration unusable against a plaintext local sink, so a
    disposable rehearsal could not exercise the very file the facility
    generates. A collector config nobody can run is the same shape of problem
    as an alert nobody can fire.
    """

    @property
    def collector_config_directory(self) -> str:
        """The in-container directory the rendered configuration is mounted at.

        The collector mounts a DIRECTORY, never a single file. A single-file
        bind mount pins the inode that existed when the container was
        created; a deploy that replaces the file (`git pull`, an atomic
        rename) writes a NEW inode, and the running container keeps reading
        the old one until it is recreated. That is not hypothetical:
        `dotmac_erp`'s vmagent kept a two-week-old configuration on production
        and staging that way, with a literal environment placeholder that
        merged both deployments' metrics into one series. A directory mount
        resolves the file name when it is opened, so the pulled file is the
        one the next (re)start reads.
        """
        return str(PurePosixPath(self.collector_config_mount).parent)

    @property
    def collector_config_asset(self) -> str:
        """The rendered asset path, inside a directory that holds nothing else.

        A dedicated directory, so mounting it exposes exactly the collector
        configuration — not the Compose file, the alert rules or the Nginx
        site rendered beside it.
        """
        name = PurePosixPath(self.collector_config_mount).name
        return f"{COLLECTOR_CONFIG_ASSET_DIRECTORY}/{name}"

    @classmethod
    def parse(cls, table: _Table | None, *, where: str) -> Telemetry:
        if table is None:
            return cls(
                logs=True,
                metrics=True,
                traces=False,
                metrics_material="METRICS_TOKEN",
                endpoint_material="OTEL_EXPORTER_OTLP_ENDPOINT",
                app_direct_shipping=False,
                deployment_annotations=True,
                scrape_interval_seconds=30,
            )
        logs = table.bool_("logs", default=True)
        metrics = table.bool_("metrics", default=True)
        traces = table.bool_("traces", default=False)
        metrics_material = table.str_(
            "metrics_material", default="METRICS_TOKEN", pattern=_MATERIAL_NAME
        )
        endpoint_material = table.str_(
            "endpoint_material",
            default="OTEL_EXPORTER_OTLP_ENDPOINT",
            pattern=_MATERIAL_NAME,
        )
        app_direct = table.bool_("app_direct_shipping", default=False)
        annotations = table.bool_("deployment_annotations", default=True)
        scrape = table.int_(
            "scrape_interval_seconds", default=30, minimum=5, maximum=3600
        )
        # Digest-pinned, like `image.reference` — this field was the ONE
        # image reference in the schema with no pattern at all, which is why a
        # mutable `otel/...:0.109.0` tag reached a rendered Compose file and
        # only an external conformance check ever noticed. Incomplete collector
        # evidence cannot support a signed image claim.
        collector_image = table.str_(
            "collector_image", default="", pattern=_OPTIONAL_DIGEST_REF
        )
        collector_insecure = table.bool_("collector_insecure", default=False)
        collector_config_mount = table.str_(
            "collector_config_mount",
            default="/etc/otelcol/config.yaml",
            pattern=re.compile(r"^/\S+$"),
        )
        table.done()
        mount_path = PurePosixPath(collector_config_mount)
        if (
            len(mount_path.parts) < 3
            or ".." in mount_path.parts
            or ":" in collector_config_mount
        ):
            raise SpecError(
                "collector_config_mount must be a file inside a dedicated "
                "container directory (e.g. /etc/otelcol/config.yaml): the "
                "directory is what gets bind-mounted, so a file directly under "
                "'/' would mount over the container's root",
                where=where,
            )
        if app_direct and logs:
            raise SpecError(
                "app_direct_shipping=true with logs=true would ship every line "
                "twice — once from the process and once from the collector "
                "reading the same container. Choose one authoritative path",
                where=where,
            )
        return cls(
            logs=logs,
            metrics=metrics,
            traces=traces,
            metrics_material=metrics_material,
            endpoint_material=endpoint_material,
            app_direct_shipping=app_direct,
            deployment_annotations=annotations,
            scrape_interval_seconds=scrape,
            collector_image=collector_image,
            collector_config_mount=collector_config_mount,
            collector_insecure=collector_insecure,
        )


@dataclass(frozen=True, slots=True)
class Hook:
    """A product command the engine runs at a named point, with a hard budget.

    Unbounded is not an option. A preflight that hangs holds the exclusive
    deployment lock, and the next operator's first symptom is that deployment
    is impossible for reasons nothing reports.
    """

    code: str
    command: tuple[str, ...]
    timeout_seconds: int

    @classmethod
    def parse(cls, table: _Table) -> Hook:
        code = table.str_("code", pattern=_CODE)
        command = table.str_list("command")
        if not command:
            raise SpecError("command may not be empty", where=table.path)
        timeout = table.int_("timeout_seconds", default=120, minimum=1, maximum=3600)
        table.done()
        return cls(code=code, command=command, timeout_seconds=timeout)


@dataclass(frozen=True, slots=True)
class ExternalDependency:
    """Something outside this deployment that it cannot serve without."""

    code: str
    kind: str
    required_for: tuple[str, ...]
    material: str
    image: str = ""
    """Set when THIS deployment runs the dependency, rather than consuming one.

    The distinction is the whole point of the field. A managed dependency is
    rendered as a Compose service and the deployment starts, stops and backs it
    up; an unmanaged one is somebody else's Postgres and this deployment only
    monitors and connects to it.

    Without this, a descriptor could only describe the roles running the
    PRODUCT's image — so `dotmac_erp`'s rendered Compose file came out with no
    Redis service at all, while its workers were configured to reach one. The
    file was internally consistent and would not have worked.

    A managed dependency is still not a `[[roles]]` entry: it runs somebody
    else's image, has no product health contract, takes no part in the
    warm-candidate handoff, and is not verified against the deploying digest.
    """

    command: tuple[str, ...] = ()
    environment: tuple[tuple[str, str], ...] = ()
    materials: tuple[str, ...] = ()
    """Material NAMES this dependency needs — its own password, most often.

    Present for the same reason a role has them: `redis-server --requirepass
    <literal>` would put a credential in the repository. The name renders as a
    `${NAME:?…}` placeholder, and a `command` element may reference it the same
    way, which is exactly what the products' real Compose files already do.
    """

    volumes: tuple[VolumeMount, ...] = ()
    ports: tuple[PortPublication, ...] = ()
    health_probe: tuple[str, ...] = ()
    memory: str = ""
    cpus: str = ""

    KINDS: ClassVar[tuple[str, ...]] = (
        "postgres",
        "redis",
        "object_store",
        "http_api",
        "smtp",
        "other",
    )
    PHASES: ClassVar[tuple[str, ...]] = ("boot", "ready", "migrate", "backup")

    @classmethod
    def parse(cls, table: _Table) -> ExternalDependency:
        code = table.str_("code", pattern=_CODE)
        kind = table.str_("kind")
        if kind not in cls.KINDS:
            raise SpecError(f"kind must be one of {cls.KINDS}", where=table.path)
        required_for = table.str_list("required_for", default=("ready",))
        material = table.str_("material", default="", pattern=None)
        image = table.str_("image", default="")
        command = table.str_list("command", default=())
        env_table = table.table("environment", optional=True)
        environment: tuple[tuple[str, str], ...] = ()
        if env_table is not None:
            entries: list[tuple[str, str]] = []
            for key in sorted(env_table.keys()):
                if not _ENV_NAME.match(key):
                    raise SpecError(
                        f"environment key {key!r} is not an UPPER_SNAKE name",
                        where=env_table.path,
                    )
                entries.append((key, env_table.str_(key)))
            env_table.done()
            environment = tuple(entries)
        materials = table.str_list("materials", default=(), pattern=_MATERIAL_NAME)
        volumes = tuple(VolumeMount.parse(item) for item in table.tables("volumes"))
        ports = tuple(PortPublication.parse(item) for item in table.tables("ports"))
        health_probe = table.str_list("health_probe", default=())
        memory = table.str_("memory", default="")
        cpus = table.str_("cpus", default="")
        table.done()
        if not image and (
            command or environment or volumes or ports or health_probe or materials
        ):
            raise SpecError(
                f"dependency {code!r} declares service configuration but no "
                "`image`. Without an image this deployment does not run it, so "
                "the configuration would be written down and never applied",
                where=table.path,
            )
        if image and not health_probe:
            raise SpecError(
                f"managed dependency {code!r} declares no `health_probe`. A role "
                "that waits on it would wait on `service_started`, which is "
                "satisfied the instant the container exists — before Postgres "
                "has finished recovery or Redis has loaded its dump",
                where=table.path,
            )
        unknown = set(required_for) - set(cls.PHASES)
        if unknown:
            raise SpecError(f"unknown phase(s) {sorted(unknown)}", where=table.path)
        if material and not _MATERIAL_NAME.match(material):
            raise SpecError("material must be an UPPER_SNAKE name", where=table.path)
        return cls(
            code=code,
            kind=kind,
            required_for=required_for,
            material=material,
            image=image,
            command=command,
            environment=environment,
            materials=materials,
            volumes=volumes,
            ports=ports,
            health_probe=health_probe,
            memory=memory,
            cpus=cpus,
        )

    @property
    def managed(self) -> bool:
        """Whether THIS deployment runs it, rather than merely consuming it."""
        return bool(self.image)


@dataclass(frozen=True, slots=True)
class ComposeMount:
    """A typed mount, never an arbitrary Compose fragment.

    Host material names are resolved only when the deployment is authorized.
    Repository paths are confined to the staged asset root; named volumes are
    persistence, not host paths. The target may also be a material name so a
    reusable descriptor need not carry a credential filename.
    """

    kind: str
    source: str
    source_digest: str
    source_material: str
    target: str
    target_material: str
    read_only: bool
    justification: str
    approved_by: str

    @classmethod
    def parse(cls, table: _Table) -> ComposeMount:
        kind = table.str_("kind")
        source = table.str_("source", default="")
        source_digest = table.str_("source_digest", default="")
        source_material = table.str_(
            "source_material", default="", pattern=_MATERIAL_NAME
        )
        target = table.str_("target", default="")
        target_material = table.str_(
            "target_material", default="", pattern=_MATERIAL_NAME
        )
        read_only = table.bool_("read_only", default=True)
        justification = table.str_("justification", default="")
        approved_by = table.str_("approved_by", default="")
        table.done()
        if kind not in ("named", "repository", "host_material"):
            raise SpecError("mount kind must be named, repository or host_material")
        if bool(target) == bool(target_material):
            raise SpecError("mount needs exactly one target or target_material")
        if target and (
            not target.startswith("/")
            or ".." in PurePosixPath(target).parts
            or ":" in target
            or any(character in target for character in ("\n", "\r"))
        ):
            raise SpecError("mount target must be a safe absolute container path")
        if kind == "host_material":
            if source or not source_material:
                raise SpecError(
                    "host_material mount needs source_material and no source"
                )
        elif source_material or not source:
            raise SpecError(f"{kind} mount needs source and no source_material")
        if kind == "named" and not _CODE.fullmatch(source):
            raise SpecError("named mount source must be a volume code")
        if kind == "repository":
            _contained_relative_path(source, key="source", where=table.path)
            if not re.fullmatch(r"sha256:[0-9a-f]{64}", source_digest):
                raise SpecError("repository mount needs an exact source_digest")
            if not read_only:
                raise SpecError("repository mount must be read-only")
        elif source_digest:
            raise SpecError("source_digest applies only to repository mounts")
        if kind != "named" and (len(justification) < 24 or not approved_by):
            raise SpecError(
                "host/repository bind mount needs a real justification and "
                "named approver"
            )
        if kind == "named" and (justification or approved_by):
            raise SpecError("named volume is not a host-bind exception")
        return cls(
            kind=kind,
            source=source,
            source_digest=source_digest,
            source_material=source_material,
            target=target,
            target_material=target_material,
            read_only=read_only,
            justification=justification,
            approved_by=approved_by,
        )


@dataclass(frozen=True, slots=True)
class ComposeNetwork:
    code: str
    internal: bool
    loopback_default: bool

    @classmethod
    def parse(cls, table: _Table) -> ComposeNetwork:
        code = table.str_("code", pattern=_CODE)
        internal = table.bool_("internal", default=False)
        loopback_default = table.bool_("loopback_default", default=False)
        table.done()
        if internal and loopback_default:
            raise SpecError("an internal network has no host binding default")
        return cls(code=code, internal=internal, loopback_default=loopback_default)


@dataclass(frozen=True, slots=True)
class ComposePlacement:
    """Extra topology for an existing role, dependency, or migration service."""

    code: str
    networks: tuple[str, ...]
    network_mode: str
    profiles: tuple[str, ...]
    mounts: tuple[ComposeMount, ...]

    @classmethod
    def parse(cls, table: _Table) -> ComposePlacement:
        code = table.str_("code", pattern=_CODE)
        networks = table.str_list("networks", default=(), pattern=_CODE)
        network_mode = table.str_("network_mode", default="")
        profiles = table.str_list("profiles", default=(), pattern=_CODE)
        mounts = tuple(ComposeMount.parse(row) for row in table.tables("mounts"))
        table.done()
        if network_mode not in ("", "none"):
            raise SpecError("network_mode may only be none")
        if bool(networks) == bool(network_mode):
            raise SpecError(
                f"service {code!r} needs networks or network_mode, not both/neither"
            )
        _unique(networks, what="network", where=code)
        _unique(profiles, what="profile", where=code)
        return cls(
            code=code,
            networks=networks,
            network_mode=network_mode,
            profiles=profiles,
            mounts=mounts,
        )


@dataclass(frozen=True, slots=True)
class ComposeJob:
    """A profile-gated support job; never a parallel runtime role."""

    code: str
    image_source: str
    command: tuple[str, ...]
    entrypoint: tuple[str, ...]
    placement: ComposePlacement
    security: Security
    materials: tuple[str, ...]
    volumes: tuple[VolumeMount, ...]
    depends_on: tuple[str, ...]
    run_during_deploy: bool
    timeout_seconds: int
    verify_command: tuple[str, ...]
    verify_stdout: str
    root_justification: str
    root_approved_by: str

    @classmethod
    def parse(cls, table: _Table) -> ComposeJob:
        code = table.str_("code", pattern=_CODE)
        image_source = table.str_("image_source")
        command = table.str_list("command")
        entrypoint = table.str_list("entrypoint", default=())
        networks = table.str_list("networks", default=(), pattern=_CODE)
        network_mode = table.str_("network_mode", default="")
        profiles = table.str_list("profiles", default=(), pattern=_CODE)
        mounts = tuple(ComposeMount.parse(row) for row in table.tables("mounts"))
        security = Security.parse(
            table.table("security", optional=True), where=table.path
        )
        materials = table.str_list("materials", default=(), pattern=_MATERIAL_NAME)
        volumes = tuple(VolumeMount.parse(row) for row in table.tables("volumes"))
        depends_on = table.str_list("depends_on", default=(), pattern=_CODE)
        run_during_deploy = table.bool_("run_during_deploy", default=False)
        timeout_seconds = table.int_(
            "timeout_seconds", default=120, minimum=1, maximum=3600
        )
        verify_command = table.str_list("verify_command", default=())
        verify_stdout = table.str_("verify_stdout", default="")
        root_justification = table.str_("root_justification", default="")
        root_approved_by = table.str_("root_approved_by", default="")
        table.done()
        if not image_source == "product" and not image_source.startswith("dependency:"):
            raise SpecError("job image_source must be product or dependency:<code>")
        if not command or not profiles:
            raise SpecError("support jobs need a command and an explicit profile")
        if run_during_deploy and (
            image_source == "product" or not verify_command or not verify_stdout
        ):
            raise SpecError(
                "deploy-time support jobs need a dependency image and an "
                "explicit verification command and expected stdout"
            )
        if run_during_deploy and entrypoint:
            raise SpecError(
                "deploy-time support jobs cannot override the entrypoint: "
                "the verification command must execute directly"
            )
        if security.user == "0:0" and (
            len(root_justification) < 24 or not root_approved_by
        ):
            raise SpecError("root support job needs justification and named approver")
        if security.user != "0:0" and (root_justification or root_approved_by):
            raise SpecError("root exception without root support-job user")
        if bool(networks) == bool(network_mode) or network_mode not in ("", "none"):
            raise SpecError("support job needs networks or network_mode=none")
        _unique(networks, what="network", where=code)
        _unique(profiles, what="profile", where=code)
        _unique(depends_on, what="dependency", where=code)
        return cls(
            code=code,
            image_source=image_source,
            command=command,
            entrypoint=entrypoint,
            placement=ComposePlacement(
                code=code,
                networks=networks,
                network_mode=network_mode,
                profiles=profiles,
                mounts=mounts,
            ),
            security=security,
            materials=materials,
            volumes=volumes,
            depends_on=depends_on,
            run_during_deploy=run_during_deploy,
            timeout_seconds=timeout_seconds,
            verify_command=verify_command,
            verify_stdout=verify_stdout,
            root_justification=root_justification,
            root_approved_by=root_approved_by,
        )


@dataclass(frozen=True, slots=True)
class ComposeTopology:
    networks: tuple[ComposeNetwork, ...]
    placements: tuple[ComposePlacement, ...]
    jobs: tuple[ComposeJob, ...]
    roles_depend_on_migrate: bool

    @classmethod
    def parse(cls, table: _Table | None) -> ComposeTopology | None:
        if table is None:
            return None
        networks = tuple(ComposeNetwork.parse(row) for row in table.tables("networks"))
        placements = tuple(
            ComposePlacement.parse(row) for row in table.tables("placements")
        )
        jobs = tuple(ComposeJob.parse(row) for row in table.tables("jobs"))
        roles_depend_on_migrate = table.bool_("roles_depend_on_migrate", default=True)
        table.done()
        if not networks or not placements:
            raise SpecError("compose topology needs networks and placements")
        _unique(tuple(item.code for item in networks), what="network", where=table.path)
        _unique(
            tuple(item.code for item in placements) + tuple(job.code for job in jobs),
            what="compose service",
            where=table.path,
        )
        valid_networks = {item.code for item in networks}
        for item in (*placements, *(job.placement for job in jobs)):
            unknown = set(item.networks) - valid_networks
            if unknown:
                raise SpecError(
                    f"{item.code!r} names unknown networks {sorted(unknown)}"
                )
        return cls(
            networks=networks,
            placements=placements,
            jobs=jobs,
            roles_depend_on_migrate=roles_depend_on_migrate,
        )

    def placement(self, code: str) -> ComposePlacement:
        for item in self.placements:
            if item.code == code:
                return item
        raise SpecError(f"compose topology omits service {code!r}")


@dataclass(frozen=True, slots=True)
class ProductAlert:
    """A DOMAIN alert. Infrastructure alerts belong to the foundation catalogue.

    Every field here exists because an alert missing it wakes somebody who
    cannot act on it: no owner means it is nobody's, no runbook means the
    responder starts from zero at 3am, and no recovery condition means it never
    resolves and is eventually muted, which is the same as deleting it while
    believing it still protects something.
    """

    code: str
    severity: str
    expression: str
    owner: str
    for_seconds: int
    summary: str
    runbook: str
    dedup_by: tuple[str, ...]
    recovery: str
    protects: str

    SEVERITIES: ClassVar[tuple[str, ...]] = ("page", "ticket", "info")

    @classmethod
    def parse(cls, table: _Table) -> ProductAlert:
        code = table.str_("code", pattern=_ALERT_CODE)
        severity = table.str_("severity")
        if severity not in cls.SEVERITIES:
            raise SpecError(
                f"severity must be one of {cls.SEVERITIES}", where=table.path
            )
        expression = table.str_("expression")
        owner = table.str_("owner")
        for_seconds = table.int_("for_seconds", default=300, minimum=0, maximum=86400)
        summary = table.str_("summary")
        runbook = table.str_("runbook")
        dedup_by = table.str_list(
            "dedup_by", default=("product", "environment", "alert")
        )
        recovery = table.str_("recovery")
        protects = table.str_("protects")
        table.done()
        return cls(
            code=code,
            severity=severity,
            expression=expression,
            owner=owner,
            for_seconds=for_seconds,
            summary=summary,
            runbook=runbook,
            dedup_by=dedup_by,
            recovery=recovery,
            protects=protects,
        )


# ── the descriptor ──────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class ProductDeploymentSpec:
    """A strictly parsed ``ProductDeploymentSpec.v1`` or ``.v2`` document."""

    product: str
    environment: str
    manifest_path: str
    manifest_digest: str
    image: str
    source_revision: str
    roles: tuple[Role, ...]
    migration: Migration
    runtime_materials: tuple[str, ...]
    ingress: Ingress | None
    backup_datasets: tuple[BackupDataset, ...]
    database: DatabaseContract | None
    telemetry: Telemetry
    preflight_hooks: tuple[Hook, ...]
    postflight_hooks: tuple[Hook, ...]
    egress_hosts: tuple[str, ...]
    external_dependencies: tuple[ExternalDependency, ...]
    product_alerts: tuple[ProductAlert, ...]
    stability_window_seconds: int
    rollback_images_retained: int
    compose_topology: ComposeTopology | None = field(
        default=None, metadata={"descriptor_since": SCHEMA_V3}
    )
    source: str = field(default="", compare=False)
    descriptor_schema: str = field(
        default=SCHEMA_V1, repr=False, metadata={"canonical_root_only": True}
    )

    def __post_init__(self) -> None:
        if self.descriptor_schema not in SCHEMAS:
            raise UnknownSchemaError(
                f"schema is {self.descriptor_schema!r}, this facility reads "
                f"{list(SCHEMAS)!r}"
            )
        catalogs = self.database.catalogs if self.database is not None else ()
        if self.descriptor_schema == SCHEMA_V1 and catalogs:
            raise SpecError(
                "ProductDeploymentSpec.v1 cannot carry database catalogs; use v2"
            )
        if (
            self.descriptor_schema in (SCHEMA_V2, SCHEMA_V3)
            and self.database is not None
            and not catalogs
        ):
            raise SpecError(
                "ProductDeploymentSpec.v2/v3 [database] requires at least one "
                "database catalog coordinate"
            )
        if self.descriptor_schema != SCHEMA_V3 and any(
            not role.command for role in self.roles
        ):
            raise SpecError(
                "an empty role command (use the image default) requires "
                "ProductDeploymentSpec.v3"
            )
        if self.descriptor_schema == SCHEMA_V3 and self.compose_topology is None:
            raise SpecError("ProductDeploymentSpec.v3 requires [compose_topology]")
        if self.descriptor_schema != SCHEMA_V3 and self.compose_topology is not None:
            raise SpecError("compose_topology requires ProductDeploymentSpec.v3")
        if self.compose_topology is not None:
            expected = {role.code for role in self.roles}
            expected.update(
                item.code for item in self.external_dependencies if item.managed
            )
            expected.add("migrate")
            if self.telemetry.collector_image:
                expected.add("otel-collector")
            placed = {item.code for item in self.compose_topology.placements}
            if expected != placed:
                raise SpecError(
                    "compose placements must exactly cover rendered services: "
                    f"missing={sorted(expected - placed)}, "
                    f"unknown={sorted(placed - expected)}"
                )
            if self.compose_topology.roles_depend_on_migrate:
                raise SpecError(
                    "v3 runtime roles may not depend on migrate: Compose up "
                    "must not execute DDL outside the authorized plan step"
                )
            if not self.compose_topology.placement("migrate").profiles:
                raise SpecError(
                    "migrate must be profile-gated; a bare compose up must "
                    "not run DDL"
                )
            for role in self.roles:
                if role.security.host_network:
                    raise SpecError(
                        f"v3 role {role.code!r} uses host_network and cannot "
                        "also claim a Compose network placement"
                    )
            available = expected | {job.code for job in self.compose_topology.jobs}
            dependencies = {
                item.code: item for item in self.external_dependencies if item.managed
            }
            for dependency in dependencies.values():
                if not _DIGEST_REF.fullmatch(dependency.image):
                    raise SpecError(
                        f"managed dependency {dependency.code!r} needs an exact "
                        "digest image in a v3 deployment"
                    )
            mounts = (
                mount
                for placement in self.compose_topology.placements
                for mount in placement.mounts
            )
            job_mounts = (
                mount
                for job in self.compose_topology.jobs
                for mount in job.placement.mounts
            )
            undeclared_materials = {
                material
                for mount in (*mounts, *job_mounts)
                for material in (mount.source_material, mount.target_material)
                if material and material not in self.runtime_materials
            }
            if undeclared_materials:
                raise SpecError(
                    "compose mounts use undeclared runtime materials "
                    f"{sorted(undeclared_materials)}"
                )
            for job in self.compose_topology.jobs:
                job_mount_materials = {
                    material
                    for mount in job.placement.mounts
                    for material in (mount.source_material, mount.target_material)
                    if material
                }
                if self.migration.owner_material in (
                    set(job.materials) | job_mount_materials
                ):
                    raise SpecError(
                        f"support job {job.code!r} may not hold the migration "
                        "owner material; only the migration service may run DDL"
                    )
                if job.image_source.startswith("dependency:"):
                    dependency_code = job.image_source.removeprefix("dependency:")
                    if dependency_code not in dependencies:
                        raise SpecError(
                            f"job {job.code!r} names unmanaged/unknown image "
                            f"dependency {dependency_code!r}"
                        )
                unknown = set(job.depends_on) - available
                if unknown or job.code in job.depends_on:
                    raise SpecError(
                        f"job {job.code!r} has invalid dependencies "
                        f"{sorted(unknown | ({job.code} & set(job.depends_on)))}"
                    )
                if set(job.depends_on) - dependencies.keys():
                    raise SpecError(
                        f"job {job.code!r} may depend only on health-checked "
                        "managed dependencies"
                    )
        for catalog in catalogs:
            identity = catalog.product_identity
            if identity is not None and identity.descriptor_product != self.product:
                raise SpecError(
                    "database catalog product_identity.descriptor_product must "
                    "equal the descriptor product exactly"
                )

    # ── loading ─────────────────────────────────────────────────────────────

    @classmethod
    def loads(cls, text: str, *, source: str = "<string>") -> ProductDeploymentSpec:
        try:
            document = tomllib.loads(text)
        except tomllib.TOMLDecodeError as exc:
            raise SpecError(f"not valid TOML: {exc}", where=source) from exc
        return cls.from_document(document, source=source)

    @classmethod
    def load(cls, path: str | Path) -> ProductDeploymentSpec:
        path = Path(path)
        return cls.loads(path.read_text(encoding="utf-8"), source=str(path))

    @classmethod
    def from_document(
        cls, document: Mapping[str, Any], *, source: str = "<document>"
    ) -> ProductDeploymentSpec:
        # Order is deliberate: schema, then secrets, then fields. Checking the
        # schema first means a v2 document is refused rather than half-read;
        # scanning for secrets second means a secret in a field this version
        # does not define is still caught.
        declared = document.get("schema")
        if declared not in SCHEMAS:
            raise UnknownSchemaError(
                f"schema is {declared!r}, this facility reads {list(SCHEMAS)!r}. A "
                "descriptor from a newer schema is REFUSED rather than "
                "partially read: a field this version cannot see may be the "
                "one that disables a control",
                where=source,
            )
        require_no_secrets(document, source=source)

        root = _Table(document, "")
        root.str_("schema")  # consume the already-validated key
        product = root.str_("product", pattern=_CODE)
        environment = root.str_(
            "environment", default="", pattern=re.compile(r"^[a-z][a-z0-9_-]{0,31}$|^$")
        )

        # `table()` without `optional=True` raises on a missing table, so this
        # is never None. Narrowed with a real check rather than an assert
        # because `python -O` strips asserts, and the checker still needs the
        # narrowing either way.
        assembly = root.table("assembly")
        if assembly is None:  # pragma: no cover - `table()` raises first
            raise SpecError("assembly table is missing", where=source)
        manifest_path = _contained_relative_path(
            assembly.str_("manifest_path"), key="manifest_path", where=source
        )
        manifest_digest = assembly.str_(
            "manifest_digest", pattern=re.compile(r"^sha256:[0-9a-f]{64}$")
        )
        assembly.done()

        image_table = root.table("image")
        if image_table is None:  # pragma: no cover - `table()` raises first
            raise SpecError("image table is missing", where=source)
        image = image_table.str_("reference", pattern=_DIGEST_REF)
        source_revision = image_table.str_(
            "source_revision", pattern=re.compile(r"^[0-9a-f]{40}$")
        )
        image_table.done()

        roles = tuple(Role.parse(item) for item in root.tables("roles", minimum=1))
        migration = Migration.parse(root.table("migration") or _Table({}, "migration"))

        materials_table = root.table("runtime_materials", optional=True)
        runtime_materials: tuple[str, ...] = ()
        if materials_table is not None:
            runtime_materials = materials_table.str_list(
                "names", default=(), pattern=_MATERIAL_NAME
            )
            materials_table.done()

        ingress = Ingress.parse(root.table("ingress", optional=True))

        backup_table = root.table("backup", optional=True)
        backup_datasets: tuple[BackupDataset, ...] = ()
        if backup_table is not None:
            backup_datasets = tuple(
                BackupDataset.parse(item) for item in backup_table.tables("datasets")
            )
            backup_table.done()

        database = DatabaseContract.parse(
            root.table("database", optional=True), descriptor_schema=str(declared)
        )
        compose_topology = ComposeTopology.parse(
            root.table("compose_topology", optional=True)
        )

        telemetry = Telemetry.parse(
            root.table("telemetry", optional=True), where=source
        )

        hooks_table = root.table("hooks", optional=True)
        preflight: tuple[Hook, ...] = ()
        postflight: tuple[Hook, ...] = ()
        if hooks_table is not None:
            preflight = tuple(
                Hook.parse(item) for item in hooks_table.tables("preflight")
            )
            postflight = tuple(
                Hook.parse(item) for item in hooks_table.tables("postflight")
            )
            hooks_table.done()

        egress_table = root.table("egress", optional=True)
        egress_hosts: tuple[str, ...] = ()
        if egress_table is not None:
            egress_hosts = egress_table.str_list("hosts", default=())
            egress_table.done()

        external = tuple(
            ExternalDependency.parse(item)
            for item in root.tables("external_dependencies")
        )
        product_alerts = tuple(
            ProductAlert.parse(item) for item in root.tables("alerts")
        )

        rollout = root.table("rollout", optional=True)
        stability = 120
        retained = 2
        if rollout is not None:
            stability = rollout.int_(
                "stability_window_seconds", default=120, minimum=10, maximum=3600
            )
            retained = rollout.int_(
                "rollback_images_retained", default=2, minimum=1, maximum=10
            )
            rollout.done()

        root.done()

        spec = cls(
            product=product,
            environment=environment,
            manifest_path=manifest_path,
            manifest_digest=manifest_digest,
            image=image,
            source_revision=source_revision,
            roles=roles,
            migration=migration,
            runtime_materials=runtime_materials,
            ingress=ingress,
            backup_datasets=backup_datasets,
            database=database,
            telemetry=telemetry,
            preflight_hooks=preflight,
            postflight_hooks=postflight,
            egress_hosts=egress_hosts,
            external_dependencies=external,
            product_alerts=product_alerts,
            stability_window_seconds=stability,
            rollback_images_retained=retained,
            compose_topology=compose_topology,
            source=source,
            descriptor_schema=str(declared),
        )
        _validate_cross_field(spec, source)
        return spec

    # ── derived, so two products cannot disagree ────────────────────────────

    def role(self, code: str) -> Role:
        for candidate in self.roles:
            if candidate.code == code:
                return candidate
        raise SpecError(f"no role {code!r}", where=self.source)

    @property
    def image_digest(self) -> str:
        return self.image.rsplit("@", 1)[1]

    @property
    def role_codes(self) -> tuple[str, ...]:
        return tuple(role.code for role in self.roles)

    @property
    def managed_dependencies(self) -> tuple[ExternalDependency, ...]:
        """Dependencies this deployment RUNS, in declaration order."""
        return tuple(item for item in self.external_dependencies if item.managed)

    def to_canonical_document(self) -> DeploymentDescriptorDocumentV1:
        """The canonical, digest-stable projection of this descriptor.

        The hop between a parsed descriptor and
        `dotmac-deployment-control`'s desired specification. The bytes and the
        digest belong to the returned DOCUMENT rather than to this class, so
        there is one answer to "what was signed" and a caller cannot reach the
        digest without holding the bytes it was taken over::

            document = spec.to_canonical_document()
            document.canonical_bytes()
            document.sha256_digest()

        Imported inside the method on purpose: `document.py` reads this module
        to normalize a descriptor, so a module-level import here would be a
        cycle. It is a relative import into this same package, not a new
        dependency — the facility still declares none.
        """
        from .document import build_canonical_document

        return build_canonical_document(self)

    @property
    def publications(self) -> tuple[tuple[str, PortPublication], ...]:
        """Every declared publication, as `(service code, publication)`.

        Roles AND managed dependencies, in one deterministic sequence. Both
        become Compose services and both can publish a host port, and the
        exposure rules apply identically — the two ports this facility was
        built to close (a Redis on 6391 and a Postgres on 9001) are dependency
        publications, not role publications. Iterating only `spec.roles` would
        have left the exact case out of the contract that names it.
        """
        return tuple(
            (owner, publication)
            for owner, ports in sorted(
                [(role.code, role.ports) for role in self.roles]
                + [
                    (dependency.code, dependency.ports)
                    for dependency in self.external_dependencies
                ]
            )
            for publication in sorted(
                ports, key=lambda item: (item.host, item.protocol)
            )
        )

    @property
    def worker_roles(self) -> tuple[Role, ...]:
        return tuple(role for role in self.roles if role.worker is not None)

    @property
    def scheduler_roles(self) -> tuple[Role, ...]:
        return tuple(
            role
            for role in self.roles
            if role.scheduler_tick_max_age_seconds is not None
        )

    @property
    def startup_order(self) -> tuple[str, ...]:
        """Roles in dependency order — the order a deployment starts them.

        Derived rather than declared: an order a product writes by hand is an
        order that drifts from `depends_on` the first time somebody adds a
        role and forgets the other list.
        """
        managed = {item.code for item in self.managed_dependencies}
        remaining = {role.code: set(role.depends_on) - managed for role in self.roles}
        ordered: list[str] = []
        while remaining:
            ready = sorted(
                code for code, deps in remaining.items() if not deps - set(ordered)
            )
            if not ready:
                raise SpecError(
                    f"dependency cycle among roles {sorted(remaining)}",
                    where=self.source,
                )
            ordered.extend(ready)
            for code in ready:
                del remaining[code]
        return tuple(ordered)


def _validate_cross_field(spec: ProductDeploymentSpec, source: str) -> None:
    """Rules that need more than one section to check.

    Kept out of the leaf parsers on purpose: a leaf that reaches for the whole
    document is a leaf that cannot be tested on its own.
    """
    _unique(list(spec.role_codes), what="role code", where=source)
    _unique(list(spec.runtime_materials), what="runtime material", where=source)
    _unique(
        [dataset.code for dataset in spec.backup_datasets],
        what="backup dataset",
        where=source,
    )
    _unique(
        [alert.code for alert in spec.product_alerts], what="alert code", where=source
    )
    if spec.database is not None and not any(
        dataset.kind == "postgres" for dataset in spec.backup_datasets
    ):
        raise SpecError(
            "the descriptor declares a [database] contract - roles, schemas and "
            "isolation invariants - and no postgres backup dataset. That is a "
            "description of a database nobody backs up, and the contract would be "
            "checked against nothing",
            where=source,
        )
    _unique(
        [hook.code for hook in spec.preflight_hooks + spec.postflight_hooks],
        what="hook code",
        where=source,
    )

    managed = {item.code for item in spec.managed_dependencies}
    collisions = sorted(set(spec.role_codes) & managed)
    if collisions:
        raise SpecError(
            f"code(s) {collisions} name both a role and a managed dependency. "
            "Both become Compose service keys, so one would silently overwrite "
            "the other",
            where=source,
        )
    # A role may wait on a managed dependency — that is most of what `depends_on`
    # is for on a single host. It may NOT wait on an unmanaged one: nothing here
    # starts somebody else's Postgres, so the wait would never be satisfiable.
    known = set(spec.role_codes) | managed
    for role in spec.roles:
        unknown = set(role.depends_on) - known
        if unknown:
            unmanaged = {
                item.code for item in spec.external_dependencies if not item.managed
            }
            named_unmanaged = sorted(unknown & unmanaged)
            if named_unmanaged:
                raise SpecError(
                    f"role {role.code!r} depends on {named_unmanaged}, which this "
                    "deployment does not run (no `image` declared). A dependency "
                    "somebody else operates cannot be waited on here — put it in "
                    "the readiness probe instead",
                    where=source,
                )
            raise SpecError(
                f"role {role.code!r} depends on unknown role(s) {sorted(unknown)}",
                where=source,
            )
        if role.code in role.depends_on:
            raise SpecError(f"role {role.code!r} depends on itself", where=source)
    _ = spec.startup_order  # evaluated for its refusal: raises on a cycle

    if spec.ingress is not None:
        for route in spec.ingress.routes:
            if route.role not in known:
                raise SpecError(
                    f"ingress route {route.path!r} names unknown role {route.role!r}",
                    where=source,
                )
            if spec.role(route.role).replicas < 1:
                raise SpecError(
                    f"ingress route {route.path!r} points at role {route.role!r}, "
                    f"which "
                    "runs zero replicas",
                    where=source,
                )

    # THE credential-separation rule. The owner role creates tables; a runtime
    # role must not be able to. Sharing one credential is ERP's defect, and it
    # is checkable statically because both are declared by NAME.
    for role in spec.roles:
        if spec.migration.owner_material in role.materials:
            raise SpecError(
                f"role {role.code!r} is given the migration owner material "
                f"{spec.migration.owner_material!r}. The owner credential exists "
                "so that DDL is possible exactly once, at deploy time, by one "
                "process; a runtime role holding it can create, alter and drop "
                "any table in the database for the life of the deployment",
                where=source,
            )
        unknown = set(role.materials) - set(spec.runtime_materials)
        if unknown:
            raise SpecError(
                f"role {role.code!r} names material(s) {sorted(unknown)} that "
                "runtime_materials.names does not declare",
                where=source,
            )

    # A role that serves ingress must be readiness-gated; there is no way to
    # know when to hand traffic over otherwise, and the warm-candidate handoff
    # degenerates into a sleep.
    if spec.ingress is not None:
        for route in spec.ingress.routes:
            if spec.role(route.role).ready is None:
                raise SpecError(
                    f"role {route.role!r} serves ingress route {route.path!r} but "
                    "declares no readiness probe. A candidate with no readiness "
                    "gate is handed traffic on a timer",
                    where=source,
                )

    # Every running role needs SOME liveness signal, and an HTTP probe is only
    # one of the three shapes it comes in. Demanding one from a Celery worker
    # forces a port nothing listens on into the descriptor — a fiction that
    # renders into a healthcheck which cannot pass, so the role either has no
    # gate or a permanently failing one. `WorkerContract.ping_command` and a
    # scheduler tick budget ARE liveness signals, and better ones: a worker
    # whose process is up and whose queue is not draining answers an HTTP probe
    # perfectly well.
    #
    # What is refused is a role with NONE of the three, because that role is
    # unmonitored rather than exempt (ADR-0018).
    for role in spec.roles:
        if role.replicas == 0:
            continue
        if role.live is not None or role.ready is not None:
            continue
        if role.worker is not None:
            continue
        if role.scheduler_tick_max_age_seconds is not None:
            continue
        raise SpecError(
            f"role {role.code!r} declares no health signal at all — no "
            "[roles.health.live] or [roles.health.ready] probe, no "
            "[roles.worker] ping and no [roles.scheduler] tick budget. "
            "Nothing would notice it dying",
            where=source,
        )

    if spec.telemetry.metrics and not spec.telemetry.metrics_material:
        raise SpecError("metrics=true needs a metrics_material name", where=source)

    _validate_exposure(spec, source)


def _validate_exposure(spec: ProductDeploymentSpec, source: str) -> None:
    """`IngressPolicy.v1`'s cross-section rules.

    Split out from `_validate_cross_field` because these three refusals are the
    ones a reader comes looking for, and because they share one derived fact —
    which role/port pairs the edge already owns — that neither leaf parser can
    see.
    """
    edge_covered: set[tuple[str, int]] = set()
    if spec.ingress is not None:
        edge_covered = {(route.role, route.port) for route in spec.ingress.routes}

    for code, publication in spec.publications:
        where = f"{source} service {code!r} port {publication.host}"
        if (code, publication.container) in edge_covered:
            # Two declarations of one port is how they drift, and the drift is
            # not cosmetic here: the edge publishes its upstream on loopback,
            # so a second declaration is the one that decides whether the
            # application is ALSO reachable directly. An edge that can be
            # bypassed is decoration.
            raise SpecError(
                f"{code!r} publishes container port {publication.container}, "
                "which an ingress route already routes to. The edge owns that "
                "port: it publishes the upstream on loopback itself, so this "
                "second declaration can only make the application reachable "
                "AROUND the edge",
                where=where,
            )
        # Reported TOGETHER rather than one at a time. A publication that
        # claims three controls nothing enforces has three defects, and fixing
        # them one CI run at a time hides how far the descriptor is from what
        # it says it is.
        problems = ingress_contract.capability_refusals(
            role_code=code,
            host_port=publication.host,
            protocol=publication.protocol,
            exposure=publication.exposure,
            families=publication.families,
            authentication=publication.authentication,
            source_set=publication.source_set,
            tls=publication.tls,
        )
        if problems:
            raise SpecError("; ".join(problems), where=where)

    # A host port is a host-wide resource. Two services publishing the same
    # (port, protocol, family) is a `docker compose up` failure at best and a
    # silently unreachable service at worst, and it is checkable here.
    _unique(
        [
            ingress_contract.endpoint_token(
                product=spec.product,
                environment=spec.environment,
                role=code,
                protocol=publication.protocol,
                family=family,
                host_port=publication.host,
                exposure=publication.exposure,
            )
            for code, publication in spec.publications
            for family in publication.families
        ],
        what="published endpoint",
        where=source,
    )
    _unique(
        [
            f"{publication.host}/{publication.protocol}/{family}"
            for _code, publication in spec.publications
            for family in publication.families
        ],
        what="host socket",
        where=source,
    )
