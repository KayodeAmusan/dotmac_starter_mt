"""Structural guards for `dotmac-commercial-agreements`, each with a sensitivity proof.

A guard that has never been shown RED is a guard nobody has verified. Every
detector in this file is therefore exercised twice: once against the real
package (must pass) and once against a synthetic violation (must fail). ADR-0018
requires the second half, and the reason is concrete — three of the checks here
are regex sweeps, and a regex that matches nothing passes silently forever.

Static only. Nothing here needs a database, which is why it lives in
`tests/architecture` and runs in the SQLite-fast lane.
"""

from __future__ import annotations

import ast
import re
import tomllib
from pathlib import Path

import pytest
from dotmac_commercial_agreements import module
from dotmac_kernel.namespaces import (
    COMMERCIAL_AGREEMENTS_MIGRATION_OWNER,
    MIGRATION_OWNER_LEDGER,
    module_schema,
)

from tests.architecture import adoption_evidence as evidence_schema

REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_ROOT = REPO_ROOT / "packages/dotmac-commercial-agreements"
SRC = PACKAGE_ROOT / "src/dotmac_commercial_agreements"
MIGRATION = SRC / "migrations/versions/cg_0001_agreements.py"

#: Every other installable distribution's import root. A module may import the
#: kernel and nothing else in this list (ADR-0024; the import-linter contract
#: `Modules are independent of each other` states the same rule, and this test
#: states it for the ONE package whose independence is most tempting to break —
#: agreements sits between approvals and entitlement allocation in the journey).
SIBLING_ROOTS = frozenset(
    {
        "dotmac_template_studio",
        "dotmac_ticketing",
        "dotmac_release_catalog",
        "dotmac_entitlement_allocation",
        "dotmac_application_directory",
        "dotmac_files",
        "dotmac_imports",
        "dotmac_integration",
        "dotmac_approvals",
        "dotmac_numbering",
        "dotmac_people",
        "dotmac_durable_timers",
        "dotmac_auth_oidc",
        "dotmac_campaigns",
        "dotmac_ui",
        "app",
        "vendor_cp",
    }
)


def _sources() -> list[Path]:
    return sorted(SRC.rglob("*.py"))


def _imported_roots(source: str) -> set[str]:
    """Every top-level module name this source imports, from the AST.

    An AST walk rather than a regex: `import x  # noqa` , a string mentioning a
    package name, and a name inside a docstring all defeat a textual scan, and
    the docstrings in this package name every sibling it deliberately does NOT
    import.
    """
    roots: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots.add(node.module.split(".")[0])
    return roots


# ── Allocation parity ───────────────────────────────────────────────────────


class TestTheManifestMatchesTheLedger:
    """Construction is validation, but only if the two agree. A manifest whose
    fields drift from the ledger row fails at boot, in a product, rather than
    here."""

    def test_the_ledger_row_exists_and_is_registered(self) -> None:
        assert COMMERCIAL_AGREEMENTS_MIGRATION_OWNER in MIGRATION_OWNER_LEDGER

    def test_every_manifest_field_matches_its_ledger_row(self) -> None:
        owner = COMMERCIAL_AGREEMENTS_MIGRATION_OWNER
        assert module.code == owner.owner == "commercial_agreements"
        assert module.migration_prefix == owner.prefix == "cg"
        assert module.migration_branch == owner.branch_label == "commercial_agreements"
        assert module.db_schema == owner.db_schema == module_schema("agreements")

    def test_the_prefix_and_schema_are_unique_fleet_wide(self) -> None:
        prefixes = [owner.prefix for owner in MIGRATION_OWNER_LEDGER]
        schemas = [o.db_schema for o in MIGRATION_OWNER_LEDGER if o.db_schema]
        assert prefixes.count("cg") == 1
        assert schemas.count(module_schema("agreements")) == 1


class TestThePlaneIsDeclaredNotDiscovered:
    def test_the_tenant_plane_is_empty_and_the_platform_plane_is_not(self) -> None:
        """ADR-0023 rejects inferring a plane from a missing `tenant_id`, and
        ADR-0057 § 7 derives this one from the single consumer that exists.

        a4 adds `agreement_approval_withdrawals` (`cg_0002_approval_withdrawals`)
        as a fourth platform table — a withdrawal is a control-plane fact with no
        `tenant_id` to scope by, same reasoning as the original three.
        """
        assert module.tables == ()
        assert set(module.platform_tables) == {
            "agreements",
            "agreement_lines",
            "agreement_events",
            "agreement_approval_withdrawals",
        }

    def test_the_declared_tables_are_exactly_the_mapped_ones(self) -> None:
        """A table the migration creates but the manifest does not declare is
        invisible to the composed gate and to the live-catalog check."""
        from dotmac_commercial_agreements.models import (
            SCHEMA,
            Agreement,
            AgreementApprovalWithdrawal,
            AgreementEvent,
            AgreementLine,
        )

        mapped_models = (
            Agreement,
            AgreementLine,
            AgreementEvent,
            AgreementApprovalWithdrawal,
        )
        mapped = {model.__tablename__ for model in mapped_models}
        assert mapped == set(module.platform_tables)
        assert all(model.__table__.schema == SCHEMA for model in mapped_models)

    def test_no_model_carries_a_tenant_column(self) -> None:
        """A platform table with a `tenant_id` is a table that has picked the
        wrong plane, and the revoke that isolates it would then be the only
        thing standing between two tenants."""
        from dotmac_commercial_agreements.models import (
            Agreement,
            AgreementApprovalWithdrawal,
            AgreementEvent,
            AgreementLine,
        )

        for model in (
            Agreement,
            AgreementLine,
            AgreementEvent,
            AgreementApprovalWithdrawal,
        ):
            assert "tenant_id" not in model.__table__.columns, model.__tablename__


# ── Independence ────────────────────────────────────────────────────────────


class TestTheModuleImportsNoSibling:
    def test_no_source_file_imports_another_distribution(self) -> None:
        offenders: list[str] = []
        for path in _sources():
            roots = _imported_roots(path.read_text())
            for bad in sorted(roots & SIBLING_ROOTS):
                offenders.append(f"{path.relative_to(REPO_ROOT)} imports {bad}")
        assert not offenders, "\n".join(offenders)

    def test_the_detector_fires_against_a_synthetic_violation(self) -> None:
        """Sensitivity proof (ADR-0018).

        Without this, deleting `SIBLING_ROOTS`' contents — or an AST walk that
        silently returned nothing — would leave the test above green forever.
        """
        assert _imported_roots("from dotmac_approvals import service") & SIBLING_ROOTS
        assert _imported_roots("import vendor_cp.contracts") & SIBLING_ROOTS
        assert not _imported_roots("from dotmac_kernel.audit import x") & SIBLING_ROOTS


class TestTheModuleOwnsNoTransaction:
    """Hard rule 8. The module receives a `Session` and only adds and flushes."""

    _FORBIDDEN = re.compile(
        r"\b(?:db|session|self\._session)\.(?:commit|rollback)\s*\(|"
        r"\bsessionmaker\s*\(|\bSessionLocal\s*\(|\bPlatformSessionLocal\s*\(|"
        r"\bSession\s*\([^)]"
    )

    def test_no_source_file_commits_rolls_back_or_builds_a_session(self) -> None:
        offenders = [
            str(path.relative_to(REPO_ROOT))
            for path in _sources()
            if self._FORBIDDEN.search(path.read_text())
        ]
        assert not offenders, offenders

    def test_the_detector_fires_against_a_synthetic_violation(self) -> None:
        """Sensitivity proof (ADR-0018)."""
        assert self._FORBIDDEN.search("    db.commit()")
        assert self._FORBIDDEN.search("    session.rollback()")
        assert self._FORBIDDEN.search("Factory = sessionmaker(bind=engine)")
        assert not self._FORBIDDEN.search("    session.flush()")
        assert not self._FORBIDDEN.search("    db.add(row)")


# ── Public inspection contract ──────────────────────────────────────────────


def _listing_source(source: str) -> str:
    tree = ast.parse(source)
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "list_agreements":
            return ast.get_source_segment(source, node) or ""
    return ""


def _listing_shape(source: str) -> dict[str, bool]:
    body = _listing_source(source)
    return {
        "stable_keyset": "Agreement.id > after" in body,
        "deterministic_order": ".order_by(Agreement.id)" in body,
        "bounded_probe": ".limit(limit + 1)" in body,
        "detached_lines": "selectinload(Agreement.lines)" in body,
        "no_offset": ".offset(" not in body,
    }


class TestTheAgreementEstateReaderIsPublicAndBounded:
    def test_the_public_surface_returns_typed_detached_values(self) -> None:
        from dotmac_commercial_agreements import (
            MAX_AGREEMENT_PAGE_SIZE,
            AgreementPage,
            AgreementView,
            list_agreements,
        )

        assert list_agreements.__annotations__["return"] == "facts.AgreementPage"
        assert AgreementPage.__dataclass_params__.frozen
        assert AgreementView.__dataclass_params__.frozen
        assert 1 < MAX_AGREEMENT_PAGE_SIZE <= 1_000

    def test_the_reader_uses_one_stable_bounded_keyset_and_eager_lines(self) -> None:
        shape = _listing_shape((SRC / "service.py").read_text())
        assert all(shape.values()), shape

    def test_the_shape_detector_fires_against_offset_pagination(self) -> None:
        synthetic = """
def list_agreements(db, *, after=None, limit=100):
    return db.execute(select(Agreement).offset(after).limit(limit)).all()
"""
        shape = _listing_shape(synthetic)
        assert not shape["stable_keyset"]
        assert not shape["deterministic_order"]
        assert not shape["bounded_probe"]
        assert not shape["detached_lines"]
        assert not shape["no_offset"]


# ── The published vocabulary ────────────────────────────────────────────────


class TestThePublishedFactsMatchWhatIsEmitted:
    """ADR-0008's test applied to an event vocabulary: a published set nobody
    checks is dead vocabulary that reads as a working contract."""

    def test_every_emitted_event_type_is_published(self) -> None:
        from dotmac_commercial_agreements import PUBLISHED_EVENT_TYPES
        from dotmac_commercial_agreements import facts as facts_module

        emitted = {
            value
            for name, value in vars(facts_module).items()
            if name.startswith("AGREEMENT_") and isinstance(value, str)
        }
        assert emitted == set(PUBLISHED_EVENT_TYPES)

    def test_every_published_type_is_referenced_by_the_service(self) -> None:
        """A published type the service never emits is a promise to consumers
        that nothing keeps."""
        from dotmac_commercial_agreements import PUBLISHED_EVENT_TYPES
        from dotmac_commercial_agreements import facts as facts_module

        service_source = (SRC / "service.py").read_text()
        by_value = {
            value: name
            for name, value in vars(facts_module).items()
            if name.startswith("AGREEMENT_") and isinstance(value, str)
        }
        unreferenced = [
            value
            for value in PUBLISHED_EVENT_TYPES
            if f"facts.{by_value[value]}" not in service_source
        ]
        assert not unreferenced, unreferenced

    def test_every_type_carries_an_explicit_version_suffix(self) -> None:
        """The version is in the type so a `v2` can be emitted alongside `v1`
        during a migration window."""
        from dotmac_commercial_agreements import PUBLISHED_EVENT_TYPES

        assert all(re.search(r"\.v\d+$", t) for t in PUBLISHED_EVENT_TYPES)


class TestTheAuditActionIsDeclaredAndConsumed:
    def test_the_manifest_declares_exactly_the_action_the_service_writes(
        self,
    ) -> None:
        """a4 adds a SECOND, distinct action for recording a withdrawal — it is
        deliberately not folded into `AUDIT_ACTION_TRANSITIONED`, because a
        withdrawal never advances `agreements.status` and an auditor searching
        for actual transitions must never see one counted as one."""
        from dotmac_commercial_agreements import (
            AUDIT_ACTION_APPROVAL_WITHDRAWAL_RECORDED,
            AUDIT_ACTION_TRANSITIONED,
        )

        assert module.audit_actions == (
            AUDIT_ACTION_TRANSITIONED,
            AUDIT_ACTION_APPROVAL_WITHDRAWAL_RECORDED,
        )
        service_source = (SRC / "service.py").read_text()
        assert "AUDIT_ACTION_TRANSITIONED" in service_source
        assert "AUDIT_ACTION_APPROVAL_WITHDRAWAL_RECORDED" in service_source


class TestTheApprovalWithdrawalOutcomeVocabularyIsClosed:
    """The five-member closed vocabulary of what recording a withdrawal did.

    Only `RECORDED` and `ALREADY_RECORDED` write anything; the other three are
    refusals. A sixth member appearing here without a corresponding branch in
    `record_approval_withdrawal` would be a promise the service never keeps.
    """

    def test_the_outcome_is_exactly_the_five_documented_values(self) -> None:
        from dotmac_commercial_agreements import ApprovalWithdrawalOutcome

        assert {member.value for member in ApprovalWithdrawalOutcome} == {
            "recorded",
            "already_recorded",
            "decision_not_carried",
            "content_not_bound",
            "evidence_conflict",
        }


class TestTheDatabaseCatalogLineageHeadIsCurrent:
    def test_the_lineage_head_names_the_latest_migration(self) -> None:
        """`database_catalog.lineage_head` is what the live-catalog gate uses to
        know which revision it is comparing against — a stale head would let the
        gate silently stop checking the newest migration's tables."""
        assert module.database_catalog.lineage_head == "cg_0002_approval_withdrawals"


# ── The migration ───────────────────────────────────────────────────────────


#: The tables `cg_0001_agreements.py` itself creates. `module.platform_tables`
#: now names FOUR tables (a4 adds `agreement_approval_withdrawals`, created by
#: `cg_0002_approval_withdrawals.py` instead) — this class inspects one migration
#: file's SQL text, so it is scoped to what THAT file actually creates, not to
#: the manifest's full plane. `TestTheApprovalWithdrawalMigrationStatesItsWhole
#: AccessSurface` below covers `cg_0002` the same way.
_CG_0001_TABLES = ("agreements", "agreement_lines", "agreement_events")


class TestTheMigrationStatesItsWholeAccessSurface:
    """These assertions duplicate what the live-catalog gate proves on Postgres,
    and that duplication is deliberate: this one runs in the fast lane on every
    push, so a dropped REVOKE is caught before a database is ever built."""

    @pytest.fixture
    def sql(self) -> str:
        return MIGRATION.read_text()

    def test_every_table_is_revoked_from_the_tenant_app_role(self, sql: str) -> None:
        """On the platform plane the revoke IS the isolation (hard rule 27)."""
        for table in _CG_0001_TABLES:
            assert f"REVOKE ALL ON mod_agreements.{table} FROM app_user;" in sql

    def test_the_online_platform_role_can_actually_reach_every_table(
        self, sql: str
    ) -> None:
        """Declared-and-unusable is a violation too. `USAGE` on the schema plus
        at least one row DML privilege per table."""
        assert "GRANT USAGE ON SCHEMA mod_agreements TO platform_api" in sql
        for table in _CG_0001_TABLES:
            assert re.search(
                rf"GRANT [A-Z, ]*SELECT[A-Z, ]* ON mod_agreements\.{table} "
                rf"TO platform_api;",
                sql,
            ), table

    def test_the_history_table_grants_no_update_or_delete_to_any_role(
        self, sql: str
    ) -> None:
        """The property that makes it evidence rather than a log."""
        for grant in re.findall(
            r"GRANT ([A-Z, ]+) ON mod_agreements\.agreement_events TO (\w+);", sql
        ):
            privileges, role = grant
            assert "UPDATE" not in privileges, role
            assert "DELETE" not in privileges, role

    def test_the_append_only_trigger_covers_both_update_and_delete(
        self, sql: str
    ) -> None:
        assert "BEFORE UPDATE OR DELETE ON mod_agreements.agreement_events" in sql

    def test_the_history_foreign_key_restricts_rather_than_cascades(
        self, sql: str
    ) -> None:
        """Without RESTRICT, "delete then re-create" would launder a history
        rewrite through a path the trigger never sees."""
        block = sql[sql.index('"agreement_events"') :]
        fk = block[block.index("fk_agreement_events_agreement_id") :][:200]
        assert 'ondelete="RESTRICT"' in fk

    def test_the_schema_is_a_literal_and_fully_qualified_everywhere(
        self, sql: str
    ) -> None:
        """`search_path` is connection state a pooler can change (ADR-0006 D1)."""
        assert 'schema="mod_agreements"' in sql
        assert "search_path" not in sql
        statements = re.findall(
            r"op\.execute\(\s*\n?\s*[\"']{1,3}(.+?)[\"']{1,3}", sql, re.S
        )
        for statement in statements:
            if any(k in statement for k in ("GRANT", "REVOKE", "CREATE TRIGGER")):
                assert "mod_agreements" in statement, statement[:80]

    def test_the_lineage_is_a_root_naming_its_own_branch(self, sql: str) -> None:
        assert 'revision = "cg_0001_agreements"' in sql
        assert "down_revision = None" in sql
        assert 'branch_labels = ("commercial_agreements",)' in sql

    def test_the_revision_id_fits_the_alembic_column(self) -> None:
        """`alembic_version.version_num` is VARCHAR(32); a longer id fails at
        `upgrade`, against a real database, not at authoring time."""
        assert len("cg_0001_agreements") <= 32

    def test_it_names_no_foreign_revision(self, sql: str) -> None:
        """Cross-lineage ordering is LOGICAL: a module declares effects, the
        assembly binds them (ADR-0006 D1 amendment)."""
        assert "depends_on = resolve_depends_on(COMMON_REQUIRES)" in sql
        assert not re.search(r'depends_on\s*=\s*[\'"]', sql)

    def test_it_verifies_both_request_time_prerequisites_before_any_ddl(
        self, sql: str
    ) -> None:
        """Deploy is the last moment at which a missing ledger is a failed
        migration rather than a failed transition in production."""
        assert (
            'COMMON_REQUIRES = ("idempotency_ledger.v1", ' '"platform_audit_log.v1")'
        ) in sql
        verify_at = sql.index("require_prerequisites(op.get_bind(), REQUIRES)")
        first_ddl = sql.index("CREATE SCHEMA IF NOT EXISTS mod_agreements")
        assert verify_at < first_ddl

    def test_the_manifest_declares_the_same_prerequisites(self) -> None:
        assert set(module.requires) == {
            "idempotency_ledger.v1",
            "platform_audit_log.v1",
        }

    def test_the_grant_detector_fires_against_a_synthetic_violation(self) -> None:
        """Sensitivity proof (ADR-0018) for the three regex sweeps above."""
        missing_revoke = "GRANT SELECT ON mod_agreements.agreements TO platform_api;"
        assert (
            "REVOKE ALL ON mod_agreements.agreements FROM app_user;"
            not in missing_revoke
        )
        leaky = "GRANT SELECT, UPDATE ON mod_agreements.agreement_events TO app_admin;"
        found = re.findall(
            r"GRANT ([A-Z, ]+) ON mod_agreements\.agreement_events TO (\w+);", leaky
        )
        assert (
            found and "UPDATE" in found[0][0]
        ), "the history-privilege sweep must match a real GRANT line"


class TestTheApprovalWithdrawalMigrationStatesItsWholeAccessSurface:
    """`cg_0002_approval_withdrawals.py`'s own access-surface guards — the same
    shape `TestTheMigrationStatesItsWholeAccessSurface` proves for `cg_0001`,
    applied to the one table that migration creates."""

    _WITHDRAWALS_MIGRATION = SRC / "migrations/versions/cg_0002_approval_withdrawals.py"

    @pytest.fixture
    def sql(self) -> str:
        return self._WITHDRAWALS_MIGRATION.read_text()

    @pytest.fixture
    def statements(self) -> str:
        """Every string literal in the migration, each on its own line.

        Read through the AST rather than as raw text: Python merges implicitly
        concatenated literals (`"GRANT ... " "TO platform_api;"`) into ONE
        constant, so a statement split across source lines by the formatter is
        still matched whole. Raw-text matching silently found nothing, which
        left the no-UPDATE/DELETE check below passing over an empty set.
        """
        import ast

        tree = ast.parse(self._WITHDRAWALS_MIGRATION.read_text())
        return "\n".join(
            " ".join(node.value.split())
            for node in ast.walk(tree)
            if isinstance(node, ast.Constant) and isinstance(node.value, str)
        )

    def test_the_table_is_revoked_from_the_tenant_app_role(
        self, statements: str
    ) -> None:
        assert (
            "REVOKE ALL ON mod_agreements.agreement_approval_withdrawals "
            "FROM app_user;" in statements
        )

    def test_the_online_platform_role_can_insert_and_select(
        self, statements: str
    ) -> None:
        grants = re.findall(
            r"GRANT ([A-Z, ]+) ON mod_agreements\."
            r"agreement_approval_withdrawals TO (\w+);",
            statements,
        )
        privileges_by_role = {role: privileges for privileges, role in grants}
        assert "platform_api" in privileges_by_role
        assert {"SELECT", "INSERT"} <= {
            p.strip() for p in privileges_by_role["platform_api"].split(",")
        }

    def test_the_table_grants_no_update_or_delete_to_any_role(
        self, statements: str
    ) -> None:
        """The property that makes a withdrawal evidence rather than a log."""
        grants = re.findall(
            r"GRANT ([A-Z, ]+) ON mod_agreements\.agreement_approval_withdrawals "
            r"TO (\w+);",
            statements,
        )
        # Non-vacuity: a check over an empty set passes for the wrong reason.
        assert {role for _, role in grants} >= {"platform_api", "app_admin"}, grants
        for grant in grants:
            privileges, role = grant
            assert "UPDATE" not in privileges, role
            assert "DELETE" not in privileges, role

    def test_the_append_only_trigger_covers_both_update_and_delete(
        self, sql: str
    ) -> None:
        assert (
            "BEFORE UPDATE OR DELETE ON "
            "mod_agreements.agreement_approval_withdrawals" in sql
        )

    def test_the_trigger_message_names_this_table_not_agreement_events(
        self, sql: str
    ) -> None:
        """A rewrite refusal must name the table that actually refused it — this
        migration defines its OWN function rather than reusing
        `refuse_history_rewrite`, whose message names `agreement_events`."""
        assert "refuse_withdrawal_rewrite" in sql
        assert "agreement_approval_withdrawals is append-only" in sql

    def test_the_foreign_key_restricts_rather_than_cascades(self, sql: str) -> None:
        fk = sql[sql.index("fk_agreement_approval_withdrawals_agreement_id") :][:200]
        assert 'ondelete="RESTRICT"' in fk

    def test_it_declares_both_uniqueness_constraints(self, sql: str) -> None:
        """One withdrawal per ref, and one withdrawal per (agreement, decision) —
        the second is defence in depth for the same conflict the service already
        refuses rather than lets become a retried `IntegrityError`."""
        assert "uq_agreement_approval_withdrawals_ref" in sql
        assert '"withdrawal_ref"' in sql
        assert "uq_agreement_approval_withdrawals_decision" in sql
        assert '"agreement_id"' in sql
        assert '"approval_decision_ref"' in sql

    def test_it_declares_a_non_empty_reason_check(self, sql: str) -> None:
        assert "ck_agreement_approval_withdrawals_reason" in sql
        assert "\"reason <> ''\"" in sql

    def test_the_schema_is_a_literal_and_fully_qualified_everywhere(
        self, sql: str
    ) -> None:
        assert 'schema="mod_agreements"' in sql
        assert "search_path" not in sql

    def test_the_lineage_extends_cg_0001_rather_than_rooting_a_new_branch(
        self, sql: str
    ) -> None:
        assert 'revision = "cg_0002_approval_withdrawals"' in sql
        assert 'down_revision = "cg_0001_agreements"' in sql

    def test_the_downgrade_refuses_evidence_before_any_drop(self, sql: str) -> None:
        """Withdrawal rows block approve/activate/reinstate; dropping them would
        silently re-enable every withdrawn agreement (the `ap_0003` guard)."""
        downgrade = sql[sql.index("def downgrade") :]
        lock = downgrade.index("IN ACCESS EXCLUSIVE MODE")
        check = downgrade.index("SELECT EXISTS")
        refuse = downgrade.index("contains immutable withdrawal evidence")
        first_drop = downgrade.index("DROP ")
        assert lock < check < refuse < first_drop

    def test_the_revision_id_fits_the_alembic_column(self) -> None:
        assert len("cg_0002_approval_withdrawals") <= 32

    def test_it_verifies_prerequisites_before_any_ddl(self, sql: str) -> None:
        verify_at = sql.index("require_prerequisites(op.get_bind(), REQUIRES)")
        first_ddl = sql.index('op.create_table(\n        "agreement_approval')
        assert verify_at < first_ddl


# ── The dossier ─────────────────────────────────────────────────────────────


class TestTheExtractionDossierIsHonest:
    @pytest.fixture
    def dossier(self) -> dict[str, object]:
        return tomllib.loads((PACKAGE_ROOT / "EXTRACTION.toml").read_text())

    def test_it_names_the_qualifying_source_and_its_repository(
        self, dossier: dict[str, object]
    ) -> None:
        assert dossier["source_mode"] == "product-first"
        assert "dotmac_vendor_control_plane" in dossier["source_repositories"]  # type: ignore[operator]
        assert any(
            "vendor_cp/contracts/service.py" in path
            for path in dossier["source_paths"]  # type: ignore[union-attr]
        )

    def test_its_status_matches_the_evidence_it_holds(
        self, dossier: dict[str, object]
    ) -> None:
        """The defect ADR-0031 seals against, checked in BOTH directions.

        This used to assert `status == "audit-complete"` with empty evidence.
        That was true when written and became false the moment the vendor
        control plane ran the module in production — so the guard failed on the
        change that made the dossier HONEST rather than on one that made it
        dishonest.

        A literal pinned the state of the world at authoring time. What the test
        NAME claims is a consistency property between two fields, and that
        survives the transition whichever way they move. `adopted` without
        evidence is the overclaim ADR-0031 seals against; evidence without
        `adopted` is the same defect pointing the other way, and it is the one
        that had set in here.

        Scoped to THIS dossier deliberately. It is not asserted repo-wide,
        because it does not hold repo-wide today — see the PR description.
        """
        status = dossier["status"]
        evidence = dossier["adoption_evidence"]
        consumers = dossier["contract_consumers"]
        assert isinstance(evidence, list)
        assert isinstance(consumers, list)

        if status == "audit-complete":
            assert evidence == [], "audit-complete cannot carry adoption evidence"
            assert consumers == [], "audit-complete cannot name a proven consumer"
        else:
            assert status in {"adopted", "reuse-proven"}, status
            assert evidence, "an adopted dossier must cite what it ran"
            assert consumers, "an adopted dossier must name who ran it"

    def test_adoption_evidence_is_re_checkable_not_merely_addressable(
        self, dossier: dict[str, object]
    ) -> None:
        """AdoptionEvidenceV1: every row is frozen to an immutable commit.

        This test used to check that a string split on a colon into two
        non-empty halves. That is ADDRESSABILITY — it says a reader could find
        something — and it passed a stale pin, a seven-hex abbreviation of a
        branch name and a run id with no commit, all on one field on one day.
        Immutability is the different property, and it is the one
        `dotmac_governance` ADR 0013 actually requires.
        """
        rows = dossier["adoption_evidence"]
        assert rows, "an adopted dossier must cite what it ran"
        for row in rows:  # type: ignore[union-attr]
            assert isinstance(row, dict), row
            assert row["kind"] in (
                evidence_schema.ASSERTION_KINDS | evidence_schema.ATTESTATION_KINDS
            ), row
            assert evidence_schema.IMMUTABLE_COMMIT.fullmatch(row["commit"]), row
            assert row["repository"] == "dotmac_vendor_control_plane"
        pin = next(r for r in rows if r["kind"] == "pinned_at")  # type: ignore[union-attr]
        assert pin["commit"] == "af9fcf6d3fbd259fbef6b589d37b39d548f7ba8e"
        assert (
            pin["field"]
            == "tool.poetry.dependencies.dotmac-commercial-agreements.version"
        )
        assert pin["expected"] == "0.1.0a1"

    def test_the_dossier_holds_no_copy_of_the_live_pin(
        self, dossier: dict[str, object]
    ) -> None:
        """The present tense is POINTED AT, never copied.

        A value copied out of the consumer's bill of materials into this file
        has no build that fails when it drifts, which is how a pin went stale in
        twenty minutes. A pointer's failure mode is loud instead.
        """
        pointer = dossier["adoption_evidence_pointer"]
        assert [p["subject"] for p in pointer] == ["current_pin"]  # type: ignore[union-attr]
        assert set(pointer[0]) <= evidence_schema.POINTER_FIELDS  # type: ignore[index]
        assert not (
            set(pointer[0]) & evidence_schema.POINTER_VALUE_FIELDS  # type: ignore[index]
        )

    def test_it_records_the_data_bearing_obligation_the_cutover_owes(
        self, dossier: dict[str, object]
    ) -> None:
        """The vendor's existing contract rows are real. A dossier that said
        "no shadow needed" without saying why would be excusing the wrong
        thing — there is no second WRITER, but there is existing DATA."""
        shadow = str(dossier["shadow_and_drift"])
        assert "content_hash" in shadow
        assert "pending_approval" in shadow
