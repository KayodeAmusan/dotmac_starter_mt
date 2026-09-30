"""Template Studio's `ModuleManifest` — the first STATEFUL one (ADR-0006 M1).

Four fields make it stateful, and they must agree exactly with this module's row
in `dotmac_kernel.namespaces.MIGRATION_OWNER_LEDGER`
(`TEMPLATE_STUDIO_MIGRATION_OWNER`) or `NamespaceRegistry.from_manifests` refuses
the composition at boot:

- `short_code="tstudio"` → the derived, read-only schema `mod_tstudio`. There is
  no settable schema attribute; the namespace is never inferred from `code` or
  from any display name, because a namespace that moves is a data-loss event.
- `migration_prefix="ts"` → revision ids `ts_0001_…`, inside
  `alembic_version.version_num`'s 32-char budget.
- `migration_branch="template_studio"` → how an `alembic_version` row is
  attributed to this owner rather than to the kernel or the assembly.
- `tables=(...)` → the composed gate rejects a migration that creates anything
  outside this declaration, and the live-catalog gate checks it in BOTH
  directions after migrations run (a declared table that does not exist is as
  much a defect as an undeclared one that does).

`permissions` and `audit_actions` are declared and OWNED here: `require_permission`
fails the boot on an undeclared code, and `write_audit_event` refuses an
undeclared action at the write. Both are also checked for a real consumer, so a
code declared and never used fails the build rather than rotting.
"""

from __future__ import annotations

from dotmac_kernel.capabilities import CapabilitySpec
from dotmac_kernel.flags import FeatureFlagSpec
from dotmac_kernel.modules import ModuleManifest
from dotmac_kernel.permissions import PermissionSpec
from dotmac_kernel.prerequisites import (
    MODULE_DATABASE_ROLES_V1,
    TENANT_SCOPE_CATALOG_V1,
)
from dotmac_kernel.web_surfaces import (
    BrowserCapabilityRequirement,
    LocalizedText,
    TemplatePackage,
    WebNavItem,
    WebSurfaceContribution,
)

from dotmac_template_studio.router import router as api_router
from dotmac_template_studio.web import router as web_router
from dotmac_template_studio.web import template_dir

module = ModuleManifest(
    code="template_studio",
    version="0.2.0a5",
    api_routers=[api_router],
    web_surfaces=(
        WebSurfaceContribution(
            code="staff",
            facet="staff_admin",
            routers=(web_router,),
            navigation=(
                WebNavItem(
                    code="template_studio.templates",
                    region="primary",
                    label=LocalizedText("template_studio.templates.nav", "Templates"),
                    route_name="list",
                    order=40,
                ),
            ),
            templates=TemplatePackage(namespace="template_studio", root=template_dir()),
            supported_ui_contract_versions=frozenset({1}),
            browser_capabilities=(BrowserCapabilityRequirement("htmx", 2),),
        ),
    ),
    # ── D1 database identity ────────────────────────────────────────────────
    short_code="tstudio",
    migration_prefix="ts",
    migration_branch="template_studio",
    tables=("templates", "template_versions"),
    # ── Entitlement ─────────────────────────────────────────────────────────
    # The licensable capability code this module owns. A capability code may
    # never be invented outside its owning module's manifest, so an entitlement
    # grant, a deployment profile or a signed licence may only REFERENCE this.
    # Enforced at request time by `require_capability` on both routers: the
    # module is `core=False`, so "is this tenant entitled to it at all?" is a
    # real question with a real answer, not a formality.
    capabilities=(
        CapabilitySpec(
            code="template_studio.use",
            description="Author, publish and render tenant notification templates.",
            # Bundled in the reference assembly, like custom fields. A product
            # that sells Template Studio as an add-on sets this False and the
            # module's routes 403 until an operator grants the capability —
            # no code change, no branch in a route.
            default_granted=True,
        ),
    ),
    # ── Feature flags ───────────────────────────────────────────────────────
    # A real operational switch, not a demo. Rendering is STRICT by default: a
    # missing variable raises rather than sending a half-substituted message.
    # During an incident — a caller stopped supplying a variable a published
    # template still references — an operator flips this off and messages go
    # out with the placeholder intact instead of failing outright. That is a
    # deliberate, temporary degradation someone chooses; the default stays
    # strict.
    #
    # `operational=True`, so evaluating it emits no exposure event: this is
    # read on every render, and one audit row per outbound message would bury
    # the decisions in traffic.
    feature_flags=(
        FeatureFlagSpec(
            code="template_studio.strict_render",
            value_type=bool,
            default=True,
            description=(
                "Raise on a missing template variable instead of leaving the "
                "placeholder in the rendered output."
            ),
            operational=True,
        ),
    ),
    # ── Authorization ───────────────────────────────────────────────────────
    permissions=[
        PermissionSpec(
            code="template_studio.templates.read",
            description="List and read the tenant's templates and their versions.",
        ),
        PermissionSpec(
            code="template_studio.templates.manage",
            description="Create templates and author new versions of them.",
        ),
        PermissionSpec(
            code="template_studio.templates.publish",
            description=(
                "Make a version the published one — the revision every caller "
                "renders. Separate from `manage` on purpose: authoring a draft "
                "and changing what customers actually receive are different "
                "decisions, and a deployment may want to bind them to different "
                "roles."
            ),
        ),
        PermissionSpec(
            code="template_studio.templates.render",
            description="Render a template's published version.",
        ),
    ],
    # The trail's vocabulary for this module. Rendering is deliberately absent:
    # it reads state, and one audit row per outbound message would flood the
    # tenant's log with traffic rather than decisions.
    audit_actions=[
        "template_studio.template.create",
        "template_studio.template.update",
        "template_studio.template.delete",
        "template_studio.version.create",
        "template_studio.version.update",
        "template_studio.version.publish",
    ],
    # Deletable: a deployment that authors no templates should not carry the
    # module's surface. Its DATA survives disablement — ADR-0003 is explicit
    # that disabling a module preserves its data.
    core=False,
    # Needs a tenant catalogue for its foreign keys and roles to grant to —
    # never the kernel's identity/RBAC/audit estate. The assembly binds these
    # effects to the revisions that supply them (ADR-0006 D1 amendment).
    requires=(TENANT_SCOPE_CATALOG_V1.name, MODULE_DATABASE_ROLES_V1.name),
)

__all__ = ["module"]
