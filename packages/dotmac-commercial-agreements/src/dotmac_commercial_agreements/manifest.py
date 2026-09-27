"""Commercial Agreements' `ModuleManifest` — the fourteenth stateful module.

Must match `COMMERCIAL_AGREEMENTS_MIGRATION_OWNER` in the kernel ledger exactly
or `NamespaceRegistry.from_manifests` refuses the composition at boot:
`short_code="agreements"` → `mod_agreements`, `migration_prefix="cg"` →
`cg_0001_…`, `migration_branch="commercial_agreements"`, and `tables` /
`platform_tables` bounding what the composed gate will accept the migration
creating.

## Platform plane only, declared and not inferred

`tables=()` is a DECLARATION that this module has no tenant plane, not an
oversight. ADR-0023 rejects inferring a plane from a missing `tenant_id`, and
ADR-0057 § 7 derives the plane from a consumer that exists today: the vendor
control plane owns vendor↔operator agreements, and no tenant data plane holds
one. Sub sells ISP service to subscribers, which is a different subject with a
different owner (`dotmac-subscriptions`, ruling A2(a)).

A tenant plane declared "for later" is a plane whose isolation nobody tests.

## `core=False`, and vendor-assembly-only beyond that

A data plane installing this module would be acquiring the wrong half of the
commercial relationship. Being non-core is the first guard; the import-linter
contract forbidding this repository's assembly from importing it is the second.

## One audit action, declared because it HAS a consumer

`commercial_agreement.transitioned` is written by every transition inside its
idempotent operation, so the declaration is live rather than aspirational —
which is the test ADR-0008's registries apply: a declared code with no consumer
is dead vocabulary that reads as a working gate.

It is deliberately ONE code and not ten. The action is "a commercial agreement
transitioned"; which transition is a detail in the record. Declaring a code per
verb would put the lifecycle in two places — the manifest and the status enum —
and leave them free to drift, which is the duplicate-vocabulary defect ADR-0008
exists to prevent rather than an application of it.

Capabilities and permissions stay undeclared for the inverted reason: this
release ships no routers, so there is nothing for them to gate.
`dotmac-ticketing` proved the point the loud way — CI rejected a declared
capability code no mounted route enforced. They land with the routers, in the
same change as the guards that reference them.

## Two logical prerequisites, both written at REQUEST time

Neither is created by this module's own migrations, and an undeclared runtime
dependency is still a dependency — it just has no DDL to betray it. An adopter
that runs its own lineage and never ran the kernel's would pass every gate this
module has, migrate cleanly, and die on `UndefinedTable` at the first
transition. Same defect as `dotmac-numbering` 0.1.0a1 and `dotmac-integration`
0.1.0a1..a3.

- Every command delegates at-most-once to the kernel (hard rule 23, ADR-0014),
  writing `public.platform_idempotency_records`.
- Every transition writes `public.platform_audit_events` through
  `write_platform_audit_event`, inside the same operation.

COMMON rather than `platform_requires`, for the reason
`dotmac-entitlement-allocation` records: this module has exactly one plane,
`supported_plane_sets` is unset, so the declared platform plane installs
atomically and there is no selection under which the requirement could lapse. A
plane-conditional list would condition on something that cannot vary.
"""

from __future__ import annotations

from dotmac_kernel.modules import ModuleManifest
from dotmac_kernel.prerequisites import IDEMPOTENCY_LEDGER_V1, PLATFORM_AUDIT_LOG_V1
from dotmac_kernel.product_database_catalog import (
    DatabaseColumnContractV1,
    DatabaseColumnGeneration,
    DatabaseRelationKind,
    ModuleDatabaseCatalogContributionV1,
    ModuleDatabaseTableContractV1,
    PostgresTypeContractV1,
    PostgresTypeKind,
)

# The three `cg_0001_agreements` tables were transcribed verbatim from
# `observe_postgres_tables_columns(conn, schemas=("mod_agreements",))` against a
# disposable PostgreSQL 16 database at that composed head. The
# `agreement_approval_withdrawals` table (`cg_0002_approval_withdrawals`) was
# DRAFTED from its migration and is verified against a live observation by
# `tests/test_commercial_agreements_platform_isolation.py` in CI — a
# repository-local claim resting on that test, not on a local observation.
_VARCHAR = "pg_catalog", "varchar"
_UUID = "pg_catalog", "uuid"
_INT4 = "pg_catalog", "int4"
_TEXT = "pg_catalog", "text"
_JSONB = "pg_catalog", "jsonb"
_DATE = "pg_catalog", "date"
_TIMESTAMPTZ = "pg_catalog", "timestamptz"
_BOOL = "pg_catalog", "bool"


def _base_type(schema: str, name: str, formatted: str) -> PostgresTypeContractV1:
    return PostgresTypeContractV1(
        kind=PostgresTypeKind.BASE, schema=schema, name=name, formatted=formatted
    )


def _column(
    name: str,
    ordinal: int,
    type_: tuple[str, str],
    formatted: str,
    *,
    nullable: bool,
    generated_now: bool = False,
) -> DatabaseColumnContractV1:
    return DatabaseColumnContractV1(
        name=name,
        ordinal=ordinal,
        postgres_type=_base_type(type_[0], type_[1], formatted),
        nullable=nullable,
        generation=(
            DatabaseColumnGeneration.DEFAULT
            if generated_now
            else DatabaseColumnGeneration.NONE
        ),
        expression="now()" if generated_now else "",
    )


_AGREEMENT_EVENTS = ModuleDatabaseTableContractV1(
    name="agreement_events",
    relation_kind=DatabaseRelationKind.TABLE,
    columns=(
        _column("id", 1, _UUID, "uuid", nullable=False),
        _column("agreement_id", 2, _UUID, "uuid", nullable=False),
        _column("sequence", 3, _INT4, "integer", nullable=False),
        _column("event_type", 4, _VARCHAR, "character varying(60)", nullable=False),
        _column("from_status", 5, _VARCHAR, "character varying(24)", nullable=True),
        _column("to_status", 6, _VARCHAR, "character varying(24)", nullable=False),
        _column("actor_ref", 7, _VARCHAR, "character varying(200)", nullable=True),
        _column("reason", 8, _TEXT, "text", nullable=True),
        _column("evidence", 9, _JSONB, "jsonb", nullable=True),
        _column("command_id", 10, _VARCHAR, "character varying(200)", nullable=False),
        _column(
            "created_at",
            11,
            _TIMESTAMPTZ,
            "timestamp with time zone",
            nullable=False,
            generated_now=True,
        ),
        _column(
            "updated_at",
            12,
            _TIMESTAMPTZ,
            "timestamp with time zone",
            nullable=False,
            generated_now=True,
        ),
    ),
)

_AGREEMENT_LINES = ModuleDatabaseTableContractV1(
    name="agreement_lines",
    relation_kind=DatabaseRelationKind.TABLE,
    columns=(
        _column("id", 1, _UUID, "uuid", nullable=False),
        _column("agreement_id", 2, _UUID, "uuid", nullable=False),
        _column("line_no", 3, _INT4, "integer", nullable=False),
        _column("product_code", 4, _VARCHAR, "character varying(120)", nullable=False),
        _column("release_ref", 5, _VARCHAR, "character varying(200)", nullable=True),
        _column("offer_ref", 6, _VARCHAR, "character varying(200)", nullable=True),
        _column(
            "capability_code", 7, _VARCHAR, "character varying(120)", nullable=False
        ),
        _column("quantity", 8, _INT4, "integer", nullable=False),
        _column("unit_amount", 9, _VARCHAR, "character varying(40)", nullable=False),
        _column(
            "unit_currency_code", 10, _VARCHAR, "character varying(3)", nullable=False
        ),
        _column(
            "created_at",
            11,
            _TIMESTAMPTZ,
            "timestamp with time zone",
            nullable=False,
            generated_now=True,
        ),
        _column(
            "updated_at",
            12,
            _TIMESTAMPTZ,
            "timestamp with time zone",
            nullable=False,
            generated_now=True,
        ),
    ),
)

_AGREEMENTS = ModuleDatabaseTableContractV1(
    name="agreements",
    relation_kind=DatabaseRelationKind.TABLE,
    columns=(
        _column("id", 1, _UUID, "uuid", nullable=False),
        _column("reference", 2, _VARCHAR, "character varying(120)", nullable=False),
        _column("agreement_family_id", 3, _UUID, "uuid", nullable=False),
        _column("agreement_version", 4, _INT4, "integer", nullable=False),
        _column(
            "counterparty_ref", 5, _VARCHAR, "character varying(200)", nullable=False
        ),
        _column(
            "agreement_type", 6, _VARCHAR, "character varying(120)", nullable=False
        ),
        _column("status", 7, _VARCHAR, "character varying(24)", nullable=False),
        _column("effective_date", 8, _DATE, "date", nullable=False),
        _column("expiry_date", 9, _DATE, "date", nullable=False),
        _column("accepted_snapshot", 10, _JSONB, "jsonb", nullable=True),
        _column("content_hash", 11, _VARCHAR, "character varying(64)", nullable=True),
        _column(
            "approval_policy_code",
            12,
            _VARCHAR,
            "character varying(120)",
            nullable=True,
        ),
        _column("approval_policy_version", 13, _INT4, "integer", nullable=True),
        _column(
            "approval_decision_ref",
            14,
            _VARCHAR,
            "character varying(200)",
            nullable=True,
        ),
        _column(
            "approved_at", 15, _TIMESTAMPTZ, "timestamp with time zone", nullable=True
        ),
        _column(
            "activation_rule", 16, _VARCHAR, "character varying(120)", nullable=True
        ),
        _column(
            "activation_reference",
            17,
            _VARCHAR,
            "character varying(200)",
            nullable=True,
        ),
        _column(
            "activated_at", 18, _TIMESTAMPTZ, "timestamp with time zone", nullable=True
        ),
        _column("suspension_reason", 19, _TEXT, "text", nullable=True),
        _column("termination_reason", 20, _TEXT, "text", nullable=True),
        _column("last_reason", 21, _TEXT, "text", nullable=True),
        _column("supersedes_id", 22, _UUID, "uuid", nullable=True),
        _column("superseded_by_id", 23, _UUID, "uuid", nullable=True),
        _column("record_version", 24, _INT4, "integer", nullable=False),
        _column(
            "created_at",
            25,
            _TIMESTAMPTZ,
            "timestamp with time zone",
            nullable=False,
            generated_now=True,
        ),
        _column(
            "updated_at",
            26,
            _TIMESTAMPTZ,
            "timestamp with time zone",
            nullable=False,
            generated_now=True,
        ),
    ),
)

_AGREEMENT_APPROVAL_WITHDRAWALS = ModuleDatabaseTableContractV1(
    name="agreement_approval_withdrawals",
    relation_kind=DatabaseRelationKind.TABLE,
    columns=(
        _column("id", 1, _UUID, "uuid", nullable=False),
        _column("agreement_id", 2, _UUID, "uuid", nullable=False),
        _column(
            "approval_request_ref",
            3,
            _VARCHAR,
            "character varying(200)",
            nullable=False,
        ),
        _column(
            "approval_decision_ref",
            4,
            _VARCHAR,
            "character varying(200)",
            nullable=False,
        ),
        _column(
            "approval_policy_code",
            5,
            _VARCHAR,
            "character varying(120)",
            nullable=False,
        ),
        _column("approval_policy_version", 6, _INT4, "integer", nullable=False),
        _column("subject_ref", 7, _VARCHAR, "character varying(200)", nullable=False),
        _column("content_hash", 8, _VARCHAR, "character varying(64)", nullable=False),
        _column(
            "withdrawal_ref", 9, _VARCHAR, "character varying(200)", nullable=False
        ),
        _column("reason", 10, _TEXT, "text", nullable=False),
        _column(
            "withdrawn_at",
            11,
            _TIMESTAMPTZ,
            "timestamp with time zone",
            nullable=False,
        ),
        _column(
            "status_at_record", 12, _VARCHAR, "character varying(24)", nullable=False
        ),
        _column("approval_carried", 13, _BOOL, "boolean", nullable=False),
        _column("command_id", 14, _VARCHAR, "character varying(200)", nullable=False),
        _column("actor_ref", 15, _VARCHAR, "character varying(200)", nullable=True),
        _column(
            "created_at",
            16,
            _TIMESTAMPTZ,
            "timestamp with time zone",
            nullable=False,
            generated_now=True,
        ),
        _column(
            "updated_at",
            17,
            _TIMESTAMPTZ,
            "timestamp with time zone",
            nullable=False,
            generated_now=True,
        ),
    ),
)

database_catalog = ModuleDatabaseCatalogContributionV1(
    lineage_head="cg_0002_approval_withdrawals",
    tables=(
        _AGREEMENT_APPROVAL_WITHDRAWALS,
        _AGREEMENT_EVENTS,
        _AGREEMENT_LINES,
        _AGREEMENTS,
    ),
)

module = ModuleManifest(
    code="commercial_agreements",
    version="0.1.0a4",
    core=False,
    short_code="agreements",
    migration_prefix="cg",
    migration_branch="commercial_agreements",
    tables=(),
    platform_tables=(
        "agreements",
        "agreement_lines",
        "agreement_events",
        "agreement_approval_withdrawals",
    ),
    requires=(IDEMPOTENCY_LEDGER_V1.name, PLATFORM_AUDIT_LOG_V1.name),
    audit_actions=(
        "commercial_agreement.transitioned",
        "commercial_agreement.approval_withdrawal_recorded",
    ),
    database_catalog=database_catalog,
)

__all__ = ["module"]
