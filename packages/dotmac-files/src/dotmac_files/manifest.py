"""Installable module declaration for the stored-file owner."""

from dotmac_kernel.modules import ModuleManifest
from dotmac_kernel.planes import ModulePlane
from dotmac_kernel.prerequisites import (
    MODULE_DATABASE_ROLES_V1,
    TENANT_SCOPE_CATALOG_V1,
)

from dotmac_files.models import PLATFORM_TABLES, TENANT_TABLES

module = ModuleManifest(
    code="files",
    version="0.1.0a5",
    core=False,
    short_code="files",
    migration_prefix="fi",
    migration_branch="files",
    tables=TENANT_TABLES,
    platform_tables=PLATFORM_TABLES,
    # Stored bytes need a tenant to hang a foreign key on and roles to grant to
    # — not an identity estate. Naming the effects instead of kernel revision
    # `0001` is what lets this module install into an assembly that supplies
    # them from its own lineage.
    requires=(TENANT_SCOPE_CATALOG_V1.name, MODULE_DATABASE_ROLES_V1.name),
    # The released fi_0001 root needs the tenant catalogue for every
    # installation, so PLATFORM alone is not a truthful promise. ERP and
    # Academy are named TENANT candidates for the deferred cohort; neither is
    # yet a consumer. The full set preserves a2's atomic catalogue. fi_0002
    # consumes this selection and removes an empty,
    # unselected platform table without rewriting the released root.
    supported_plane_sets=(
        (ModulePlane.TENANT,),
        (ModulePlane.TENANT, ModulePlane.PLATFORM),
    ),
)

__all__ = ["module"]
