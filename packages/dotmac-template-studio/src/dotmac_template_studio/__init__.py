"""DotMac Template Studio — tenant-authored NOTIFICATION templates.

The FIRST stateful module (ADR-0006: "dotmac-template-studio a MODULE — the first
stateful one, not a kernel facility"). It owns the `mod_tstudio` schema and its
own `ts` migration lineage, and it is installed by an assembly rather than
imported by the kernel.

## Its one decision: what the message SAYS

ADR-0006 § 5b narrowed this module to a single owned decision. It renders and
returns `(subject, body)`. It does **not** decide whether a message may be sent
(consent), over what (channel policy), how it is actually sent (delivery), or
produce documents — those are four separate foundation owners. A module that
absorbed them would be the merge the 2026-08-10 source audit disqualified.

Documents in particular are NOT served here: ERP's document templates need Jinja
control flow, filters and page geometry, and this module substitutes rather than
evaluates, on purpose.

## The public surface

Everything below is what a consuming assembly may use. Anything else is internal
and may change without a contract bump.

- `module` — the `ModuleManifest` an assembly puts in `ProductAssemblySpec.modules`.
- `RenderContext` / `register_contexts()` — the product declares which send paths
  exist and exactly which variables each can supply. Template Studio owns the
  CHECKING; the product owns the VOCABULARY (ADR-0008). A deployment that
  registers no context can create no template.
- `template_dir()` — the packaged Jinja directory declared by the module's
  namespaced `WebSurfaceContribution` (also public for packaging inspection).
- `migrations_dir()` — the packaged Alembic version location for the assembly's
  `version_locations`.
- `service` — the module's own logic, for a product that wants to render a
  template from its own code rather than over HTTP. This is the SUPPORTED way to
  reach Template Studio in-process; the models are not.
- `rendering.render` — single-brace substitution without loading the module's
  web surface or persistence service.

## What a consumer must NOT do

Import `dotmac_template_studio.models` and query it directly. The tables are an
implementation detail behind `service`, and reaching past it re-creates the
parallel-writer problem the source-of-truth standard exists to prevent.
"""

from __future__ import annotations

from importlib import import_module
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from dotmac_template_studio import service
    from dotmac_template_studio.contexts import (
        RenderContext,
        register_contexts,
        registered_contexts,
    )
    from dotmac_template_studio.manifest import module
    from dotmac_template_studio.seeding import (
        SeedOutcome,
        TemplateSeed,
        seed_templates,
    )
    from dotmac_template_studio.web import template_dir

_PKG_DIR = Path(__file__).resolve().parent

# 0.2.0a1, not 0.1.0a2: § 5b is a BREAKING change to every part of the surface —
# `kind` is gone, `channel` and `context` are required, and the render route
# moved. Pre-1.0 a `0.MINOR` bump is how this package signals that (CHANGELOG).
# a3 replaces a foreign revision edge with the logical prerequisite contract;
# a5 adds lossless composition of rendered email parts.
__version__ = "0.2.0a5"


def migrations_dir() -> Path:
    """This module's Alembic version location.

    An assembly appends this to `version_locations` — one of exactly two edits
    that install a module's migrations, the other being its ledger row (which
    ships in the kernel). Resolved by package path so it works installed.
    """
    return _PKG_DIR / "migrations" / "versions"


_LAZY_EXPORTS = {
    "RenderContext": ("contexts", "RenderContext"),
    "register_contexts": ("contexts", "register_contexts"),
    "registered_contexts": ("contexts", "registered_contexts"),
    "SeedOutcome": ("seeding", "SeedOutcome"),
    "TemplateSeed": ("seeding", "TemplateSeed"),
    "seed_templates": ("seeding", "seed_templates"),
    "module": ("manifest", "module"),
    "template_dir": ("web", "template_dir"),
}


def __getattr__(name: str) -> object:
    """Keep the public surface while allowing pure submodules to import alone."""
    if name == "service":
        return import_module(".service", __name__)
    export = _LAZY_EXPORTS.get(name)
    if export is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attribute = export
    return getattr(import_module(f".{module_name}", __name__), attribute)


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))


__all__ = [
    "RenderContext",
    "SeedOutcome",
    "TemplateSeed",
    "__version__",
    "migrations_dir",
    "module",
    "register_contexts",
    "seed_templates",
    "registered_contexts",
    "service",
    "template_dir",
]
