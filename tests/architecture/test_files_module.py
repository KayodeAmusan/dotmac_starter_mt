"""Structural canaries for the optional ``dotmac-files`` module.

The module owns stored bytes and their repairable physical lifecycle.  It does
not own what those bytes mean to tickets, invoices, subscribers, or imports.
"""

from __future__ import annotations

import ast
import inspect
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
from dotmac_files import models, physical, service
from dotmac_files.manifest import module
from dotmac_kernel.namespaces import FILES_MIGRATION_OWNER, MIGRATION_OWNER_LEDGER
from dotmac_kernel.planes import (
    ModulePlane,
    ModulePlaneSelection,
    ModulePlaneSelectionError,
    supported_plane_sets,
    validate_module_plane_selections,
)

MODULE_ROOT = Path(inspect.getfile(service)).parent
MIGRATIONS = MODULE_ROOT / "migrations/versions"
MIGRATION = MIGRATIONS / "fi_0001_stored_files.py"
PLANE_MIGRATION = MIGRATIONS / "fi_0002_selectable_planes.py"
REPO_ROOT = Path(__file__).resolve().parents[2]


def test_manifest_matches_the_immutable_namespace_allocation() -> None:
    assert FILES_MIGRATION_OWNER in MIGRATION_OWNER_LEDGER
    assert module.code == "files"
    assert module.short_code == "files"
    assert module.migration_prefix == "fi"
    assert module.migration_branch == "files"
    assert module.db_schema == "mod_files"
    assert tuple(module.tables) == ("stored_files",)
    assert tuple(module.platform_tables) == ("platform_stored_files",)
    assert module.core is False


def test_files_supports_only_the_plane_sets_with_named_candidates() -> None:
    """ERP and Academy target TENANT; nobody targets PLATFORM alone today."""
    assert supported_plane_sets(module) == (
        (ModulePlane.TENANT,),
        (ModulePlane.PLATFORM, ModulePlane.TENANT),
    )

    assert validate_module_plane_selections(
        [module],
        [ModulePlaneSelection(module="files", planes=(ModulePlane.TENANT,))],
    )
    assert validate_module_plane_selections(
        [module],
        [
            ModulePlaneSelection(
                module="files",
                planes=(ModulePlane.TENANT, ModulePlane.PLATFORM),
            )
        ],
    )


def test_files_refuses_an_unclaimed_platform_only_installation() -> None:
    with pytest.raises(ModulePlaneSelectionError, match="does not support"):
        validate_module_plane_selections(
            [module],
            [ModulePlaneSelection(module="files", planes=(ModulePlane.PLATFORM,))],
        )


def test_files_refuses_an_omitted_plane_selection() -> None:
    with pytest.raises(ModulePlaneSelectionError, match="has no plane selection"):
        validate_module_plane_selections([module], [])


def test_selectable_plane_migration_is_additive_to_the_released_root() -> None:
    """The published fi_0001 stays immutable; fi_0002 converges final shape."""
    source = PLANE_MIGRATION.read_text(encoding="utf-8")
    assigned = {
        target.id: node.value
        for node in ast.parse(source).body
        if isinstance(node, ast.Assign)
        for target in node.targets
        if isinstance(target, ast.Name)
    }

    assert ast.literal_eval(assigned["revision"]) == "fi_0002_selectable_planes"
    assert ast.literal_eval(assigned["down_revision"]) == "fi_0001_stored_files"
    assert "selected_module_planes(MODULE_CODE)" in source
    assert (
        "LOCK TABLE mod_files.platform_stored_files IN ACCESS EXCLUSIVE MODE" in source
    )
    assert "DROP TABLE mod_files.platform_stored_files" in source


def test_tenant_stored_file_is_scoped_and_has_no_domain_attachment_columns() -> None:
    table = models.TenantStoredFile.__table__
    assert table.schema == "mod_files"
    assert table.c.tenant_id.nullable is False
    unique_columns = {
        tuple(column.name for column in constraint.columns)
        for constraint in table.constraints
        if constraint.__class__.__name__ == "UniqueConstraint"
    }
    assert ("tenant_id", "id") in unique_columns

    forbidden = {
        "entity_type",
        "entity_id",
        "attachment_type",
        "is_public",
        "subscriber_id",
        "ticket_id",
        "invoice_id",
        "import_run_id",
    }
    assert not (forbidden & set(table.c.keys()))


def test_platform_stored_file_is_tenant_free_and_has_no_domain_columns() -> None:
    table = models.PlatformStoredFile.__table__
    assert table.schema == "mod_files"
    assert "tenant_id" not in table.c
    assert {column.name for column in table.primary_key.columns} == {"id"}

    forbidden = {
        "entity_type",
        "entity_id",
        "attachment_type",
        "is_public",
        "vendor_account_id",
        "licence_delivery_id",
        "deployment_id",
    }
    assert not (forbidden & set(table.c.keys()))


def test_the_two_planes_do_not_share_a_mapped_ancestor_or_foreign_key() -> None:
    from dotmac_kernel.models import Base

    tenant = models.TenantStoredFile
    platform = models.PlatformStoredFile
    shared = set(tenant.__mro__) & set(platform.__mro__)
    mapped = {cls for cls in shared if cls is not Base and hasattr(cls, "__table__")}
    assert not mapped

    for model in (tenant, platform):
        for fk in model.__table__.foreign_key_constraints:
            for element in fk.elements:
                target = element.column.table
                assert (
                    target.schema != models.SCHEMA or target.name == model.__tablename__
                )


def test_service_never_owns_a_transaction() -> None:
    tree = ast.parse(Path(inspect.getfile(service)).read_text(encoding="utf-8"))
    calls = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert not ({"commit", "rollback"} & calls)


def test_shared_physical_engine_imports_no_persistence() -> None:
    tree = ast.parse(Path(inspect.getfile(physical)).read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    assert not {
        name
        for name in imported
        if name == "sqlalchemy"
        or name.startswith("sqlalchemy.")
        or name == "dotmac_files.models"
    }


def test_external_provider_actions_are_separate_from_database_recording() -> None:
    """No network/object stream is held open inside a DB transaction phase."""
    for name in (
        "delete_object",
        "delete_orphans",
        "list_objects",
        "observe_object",
        "open_object",
        "prepare_upload",
        "recheck_and_delete_orphan",
    ):
        assert "db" not in inspect.signature(getattr(physical, name)).parameters
    for name in (
        "deletion_target",
        "download_target",
        "finalize_purge",
        "find_orphan_keys",
        "record_presence",
        "reconciliation_target",
        "request_deletion",
        "stage_file",
    ):
        assert "provider" not in inspect.signature(getattr(service, name)).parameters


def test_migration_creates_rls_and_grants_in_the_same_revision() -> None:
    source = MIGRATION.read_text(encoding="utf-8")
    statements = re.sub(r"\s+", " ", re.sub(r'"\s*\n\s*"', "", source))
    assert 'revision = "fi_0001_stored_files"' in source
    assert "down_revision = None" in source
    assert 'branch_labels = ("files",)' in source
    # AMENDED (ADR-0006 D1 amendment): this used to assert
    # `depends_on = ("0001_initial_tenant_schema",)`. A module may not name a
    # foreign revision — that edge was true in the Starter and false in ERP,
    # which hosts `public.tenants` itself and can never run kernel 0001. The
    # module names the EFFECTS; the assembly binds them.
    # Asserted on the AST, not the text: the docstring QUOTES the old
    # `depends_on = ("0001_initial_tenant_schema",)` to explain why it is gone,
    # so a substring check matches the explanation too. The shape of the
    # assignment is the thing that matters, and only a parse can see it.
    assigned = {
        target.id: node.value
        for node in ast.parse(source).body
        if isinstance(node, ast.Assign)
        for target in node.targets
        if isinstance(target, ast.Name)
    }
    assert isinstance(assigned["depends_on"], ast.Call)
    assert getattr(assigned["depends_on"].func, "id", None) == "resolve_depends_on"
    assert ast.literal_eval(assigned["REQUIRES"]) == (
        "tenant_scope_catalog.v1",
        "module_database_roles.v1",
    )
    assert "schema=_SCHEMA" in source
    assert "mod_files.stored_files ENABLE ROW LEVEL SECURITY" in source
    assert "mod_files.stored_files FORCE ROW LEVEL SECURITY" in source
    assert "stored_files_tenant_isolation" in source
    assert "TO app_user" in source
    assert "platform_stored_files" in source
    assert (
        "GRANT SELECT, INSERT, UPDATE, DELETE ON "
        "mod_files.platform_stored_files TO platform_api;"
    ) in statements
    assert "REVOKE ALL ON mod_files.platform_stored_files FROM app_user;" in statements
    assert "platform_stored_files ENABLE ROW LEVEL SECURITY" not in source
    assert "platform_stored_files FORCE ROW LEVEL SECURITY" not in source
    assert "search_path" not in source


def test_package_has_no_web_or_domain_dependencies() -> None:
    offenders: list[str] = []
    for path in MODULE_ROOT.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            else:
                continue
            for name in names:
                if name == "app" or name.startswith("app.") or name == "fastapi":
                    offenders.append(f"{path.name}: {name}")
                if name.startswith("dotmac_") and not name.startswith(
                    ("dotmac_files", "dotmac_kernel")
                ):
                    offenders.append(f"{path.name}: {name}")
    assert not offenders


def test_public_package_import_needs_no_database_configuration() -> None:
    """Provider/validation contracts are usable before an assembly installs DB."""
    import tomllib

    declared = tomllib.loads(
        (REPO_ROOT / "packages/dotmac-files/pyproject.toml").read_text(encoding="utf-8")
    )["tool"]["poetry"]["version"]
    env = os.environ.copy()
    env.pop("DATABASE_URL", None)
    env.pop("PLATFORM_DATABASE_URL", None)
    result = subprocess.run(  # noqa: S603 - this interpreter, fixed probe code
        [
            sys.executable,
            "-c",
            "import dotmac_files; print(dotmac_files.__version__)",
        ],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == declared


def test_lineage_passes_the_composed_migration_gate() -> None:
    """The shipped assembly omits this optional lineage, so compose it here.

    Composing it means answering what it requires: this module declares the
    EFFECTS it needs rather than a foreign revision, so the gate only accepts it
    once an assembly has bound those effects to revisions it actually runs. The
    reference assembly's answer is kernel `0001`; ERP's will be its own tenant
    projection. Passing the binding here exercises the whole loop.
    """
    from dotmac_kernel.migrations.gate import run_gate

    from app.migration_bindings import ASSEMBLY_PREREQUISITE_BINDINGS

    report = run_gate(
        [module],
        [
            REPO_ROOT / "packages/dotmac-kernel/src/dotmac_kernel/migrations/versions",
            REPO_ROOT / "alembic/versions",
            MIGRATIONS,
        ],
        bindings=ASSEMBLY_PREREQUISITE_BINDINGS,
        module_planes=(
            ModulePlaneSelection(module="files", planes=(ModulePlane.TENANT,)),
        ),
    )
    assert report.ok, f"composed gate violations: {report.violations}"


def test_the_gate_refuses_this_module_in_an_assembly_that_binds_nothing() -> None:
    """Sensitivity proof for the test above, and the property that matters for
    Vendor CP: an assembly with no tenant scope must not silently compose a
    tenant-scoped module."""
    from dotmac_kernel.migrations.gate import run_gate

    report = run_gate(
        [module],
        [
            REPO_ROOT / "packages/dotmac-kernel/src/dotmac_kernel/migrations/versions",
            REPO_ROOT / "alembic/versions",
            MIGRATIONS,
        ],
        bindings=(),
        module_planes=(
            ModulePlaneSelection(module="files", planes=(ModulePlane.TENANT,)),
        ),
    )
    assert not report.ok
    assert any("binds no provider" in v for v in report.violations)


def test_dunder_version_matches_the_distribution_and_manifest() -> None:
    """A wheel that misreports its own version lies to every consumer that logs
    it, and the release publishes whatever `pyproject` says regardless.

    This drifted for real: `pyproject` and the manifest moved to `0.1.0a2` while
    `__version__` stayed `0.1.0a1`, and the test above PINNED the stale value —
    so the suite actively protected the drift. The kernel has had this guard
    since its own version sync test; files did not.
    """
    import tomllib

    declared = tomllib.loads(
        (REPO_ROOT / "packages/dotmac-files/pyproject.toml").read_text(encoding="utf-8")
    )["tool"]["poetry"]["version"]
    import dotmac_files

    assert dotmac_files.__version__ == declared, (
        f"dotmac_files.__version__ is {dotmac_files.__version__!r} but the "
        f"distribution declares {declared!r}"
    )
    assert (
        module.version == declared
    ), f"manifest version {module.version!r} != distribution {declared!r}"
