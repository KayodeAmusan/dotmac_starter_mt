"""Postgres proof for `mod_agreements`: migration, grants, isolation, append-only.

Like `tests/test_application_directory_isolation.py`, this provisions its OWN
scratch database and composes the module's lineage explicitly, because the
reference assembly deliberately does not compose `dotmac-commercial-agreements`:
the starter is a target application, and only a vendor control plane holds a
vendor↔operator agreement (ADR-0057 § 7). Adding it to `app/assembly.py` or the
shipped `alembic.ini` would put `mod_agreements` into every starter deployment.

**On the platform plane the REVOKE is the isolation**, and it is checked as
strictly here as a policy is on the tenant side (hard rule 27). Two halves, both
of which have to hold:

1. `app_user` — the tenant data-plane role — can reach nothing.
2. `platform_api` — the ONLINE role — can reach everything it needs. Declared
   and unusable is a violation too, and it is the half a REVOKE-only test would
   miss entirely.

Requires real Postgres (`make test-db-up` / `make test-integration`). SQLite
cannot enforce a grant, so none of this belongs in `tests/unit`.
"""

from __future__ import annotations

import os
import time
import uuid
from collections.abc import Iterator
from datetime import UTC, date, datetime
from pathlib import Path
from threading import Thread

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError, ProgrammingError
from sqlalchemy.orm import Session

REPO_ROOT = Path(__file__).resolve().parent.parent
KERNEL_VERSIONS = (
    REPO_ROOT / "packages/dotmac-kernel/src/dotmac_kernel/migrations/versions"
)
ASSEMBLY_VERSIONS = REPO_ROOT / "alembic/versions"
AGREEMENT_VERSIONS = (
    REPO_ROOT
    / "packages/dotmac-commercial-agreements/src/dotmac_commercial_agreements"
    / "migrations/versions"
)

SCHEMA = "mod_agreements"
#: a4 adds `agreement_approval_withdrawals` (`cg_0002_approval_withdrawals`) as
#: a fourth table on the same platform plane — the parametrised checks below
#: that iterate this tuple extend to it automatically.
TABLES = (
    "agreements",
    "agreement_lines",
    "agreement_events",
    "agreement_approval_withdrawals",
)

#: The seven table privileges. A revoke that covers six is not a revoke.
ALL_PRIVILEGES = (
    "SELECT",
    "INSERT",
    "UPDATE",
    "DELETE",
    "TRUNCATE",
    "REFERENCES",
    "TRIGGER",
)

#: The four that make a request path usable. `REFERENCES`, `TRIGGER` and
#: `TRUNCATE` alone do not — that is the "declared and unusable" case.
ROW_DML = ("SELECT", "INSERT", "UPDATE", "DELETE")


def _superuser_url() -> str:
    url = os.getenv("TEST_MIGRATION_DATABASE_URL") or os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL not set — the platform canary needs Postgres")
    return url


def _url_for(base_url: str, dbname: str, *, user: str | None = None) -> str:
    scheme_userhost, _, _ = base_url.rpartition("/")
    if user is not None:
        scheme, _, userhost = scheme_userhost.partition("://")
        host = userhost.rpartition("@")[2]
        scheme_userhost = f"{scheme}://{user}@{host}"
    return f"{scheme_userhost}/{dbname}"


@pytest.fixture(scope="module")
def migrated_scratch() -> Iterator[tuple[str, str, str]]:
    """Yield `(admin_url, platform_api_url, app_user_url)` at the composed head.

    Module-scoped: building a database and running the whole kernel lineage per
    test would dominate the run, and every test here is read-only or writes rows
    it cleans up by being in a rolled-back transaction.
    """
    superuser = _superuser_url()
    name = f"agreements_{uuid.uuid4().hex[:12]}"
    server = create_engine(superuser, isolation_level="AUTOCOMMIT")
    with server.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{name}"'))

    setup = create_engine(_url_for(superuser, name), isolation_level="AUTOCOMMIT")
    with setup.connect() as conn:
        conn.execute(text("ALTER SCHEMA public OWNER TO app_admin"))
        # A MODULE lineage creates its own schema, and `CREATE SCHEMA` needs
        # CREATE on the DATABASE — not merely ownership of `public`.
        conn.execute(text(f'GRANT CREATE ON DATABASE "{name}" TO app_admin'))
        for role in ("app_user", "platform_api"):
            conn.execute(text(f'GRANT CONNECT ON DATABASE "{name}" TO {role}'))
            conn.execute(text(f"GRANT USAGE ON SCHEMA public TO {role}"))
    setup.dispose()

    admin_url = _url_for(superuser, name, user="app_admin")
    try:
        from alembic import command
        from alembic.config import Config

        cfg = Config(str(REPO_ROOT / "alembic.ini"))
        cfg.set_main_option("script_location", str(REPO_ROOT / "alembic"))
        cfg.set_main_option(
            "version_locations",
            f"{KERNEL_VERSIONS} {ASSEMBLY_VERSIONS} {AGREEMENT_VERSIONS}",
        )
        os.environ["MIGRATION_DATABASE_URL"] = admin_url
        # From an EMPTY database to the composed head. This is the migration
        # proof: the lineage's prerequisite verification runs for real against
        # a catalog the kernel lineage built moments earlier.
        command.upgrade(cfg, "heads")

        yield (
            admin_url,
            _url_for(superuser, name, user="platform_api"),
            _url_for(superuser, name, user="app_user"),
        )
    finally:
        with server.connect() as conn:
            conn.execute(
                text(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname = :n AND pid <> pg_backend_pid()"
                ),
                {"n": name},
            )
            conn.execute(text(f'DROP DATABASE IF EXISTS "{name}"'))
        server.dispose()


def _has_privilege(url: str, table: str, privilege: str, *, role: str) -> bool:
    engine = create_engine(url)
    try:
        with engine.connect() as conn:
            return bool(
                conn.execute(
                    text("SELECT has_table_privilege(:r, :t, :p)"),
                    {"r": role, "t": f"mod_agreements.{table}", "p": privilege},
                ).scalar()
            )
    finally:
        engine.dispose()


# ── Migration from empty ────────────────────────────────────────────────────


class TestTheLineageBuildsFromAnEmptyDatabase:
    def test_the_schema_and_all_four_tables_exist(self, migrated_scratch) -> None:
        admin_url, _, _ = migrated_scratch
        engine = create_engine(admin_url)
        try:
            with engine.connect() as conn:
                for table in TABLES:
                    assert (
                        conn.execute(
                            text("SELECT to_regclass(:t)"),
                            {"t": f"mod_agreements.{table}"},
                        ).scalar()
                        is not None
                    ), table
        finally:
            engine.dispose()

    def test_no_table_carries_a_tenant_column(self, migrated_scratch) -> None:
        """A platform table with a `tenant_id` has picked the wrong plane."""
        admin_url, _, _ = migrated_scratch
        engine = create_engine(admin_url)
        try:
            with engine.connect() as conn:
                rows = conn.execute(
                    text(
                        "SELECT table_name FROM information_schema.columns "
                        "WHERE table_schema = :s AND column_name = 'tenant_id'"
                    ),
                    {"s": SCHEMA},
                ).all()
            assert not rows, rows
        finally:
            engine.dispose()

    def test_no_table_has_row_level_security(self, migrated_scratch) -> None:
        """Not even ENABLEd-with-no-policy, which denies every row to the
        control plane while reading as protected (hard rule 27)."""
        admin_url, _, _ = migrated_scratch
        engine = create_engine(admin_url)
        try:
            with engine.connect() as conn:
                for table in TABLES:
                    enabled, forced = conn.execute(
                        text(
                            "SELECT relrowsecurity, relforcerowsecurity "
                            "FROM pg_class WHERE oid = CAST(:t AS regclass)"
                        ),
                        {"t": f"mod_agreements.{table}"},
                    ).one()
                    assert not enabled and not forced, table
        finally:
            engine.dispose()

    def test_no_foreign_key_leaves_the_module_schema(self, migrated_scratch) -> None:
        """ADR-0006 D1: a cross-lineage FK splices two independently released
        lineages and makes either un-releasable without the other."""
        admin_url, _, _ = migrated_scratch
        engine = create_engine(admin_url)
        try:
            with engine.connect() as conn:
                foreign = conn.execute(
                    text(
                        """
                        SELECT c.conname, tn.nspname
                        FROM pg_constraint c
                        JOIN pg_class t  ON t.oid  = c.conrelid
                        JOIN pg_namespace n ON n.oid = t.relnamespace
                        JOIN pg_class tt ON tt.oid = c.confrelid
                        JOIN pg_namespace tn ON tn.oid = tt.relnamespace
                        WHERE c.contype = 'f' AND n.nspname = :s
                          AND tn.nspname <> :s
                        """
                    ),
                    {"s": SCHEMA},
                ).all()
            assert not foreign, foreign
        finally:
            engine.dispose()


# ── Isolation: the revoke half ──────────────────────────────────────────────


class TestTheTenantAppRoleCanReachNothing:
    @pytest.mark.parametrize("table", TABLES)
    @pytest.mark.parametrize("privilege", ALL_PRIVILEGES)
    def test_app_user_holds_no_privilege(
        self, migrated_scratch, table: str, privilege: str
    ) -> None:
        """All seven privileges, not the four anyone remembers. A revoke that
        covers six is not a revoke."""
        admin_url, _, _ = migrated_scratch
        assert not _has_privilege(admin_url, table, privilege, role="app_user")

    @pytest.mark.parametrize("table", TABLES)
    def test_app_user_holds_no_column_level_privilege(
        self, migrated_scratch, table: str
    ) -> None:
        """Column grants survive a table-level REVOKE that names only tables."""
        admin_url, _, _ = migrated_scratch
        engine = create_engine(admin_url)
        try:
            with engine.connect() as conn:
                rows = conn.execute(
                    text(
                        "SELECT column_name, privilege_type "
                        "FROM information_schema.column_privileges "
                        "WHERE table_schema = :s AND table_name = :t "
                        "AND grantee = 'app_user'"
                    ),
                    {"s": SCHEMA, "t": table},
                ).all()
            assert not rows, rows
        finally:
            engine.dispose()

    def test_a_real_select_as_app_user_is_refused(self, migrated_scratch) -> None:
        """The privilege catalogue and a real connection can disagree; this is
        the one that matters to a request."""
        _, _, app_user_url = migrated_scratch
        engine = create_engine(app_user_url)
        try:
            with (
                engine.connect() as conn,
                pytest.raises((DBAPIError, ProgrammingError)),
            ):
                conn.execute(text("SELECT 1 FROM mod_agreements.agreements"))
        finally:
            engine.dispose()


# ── Isolation: the reachability half ────────────────────────────────────────


class TestTheOnlinePlatformRoleCanActuallyWork:
    """Declared and unusable is a violation too, and a REVOKE-only suite misses
    it completely — every assertion above would still pass if `platform_api`
    had been granted nothing at all."""

    @pytest.mark.parametrize("table", TABLES)
    def test_platform_api_holds_at_least_one_row_dml_privilege(
        self, migrated_scratch, table: str
    ) -> None:
        admin_url, _, _ = migrated_scratch
        held = [
            p
            for p in ROW_DML
            if _has_privilege(admin_url, table, p, role="platform_api")
        ]
        assert held, f"platform_api cannot reach {table} at all"

    def test_platform_api_can_insert_an_agreement_and_read_it_back(
        self, migrated_scratch
    ) -> None:
        _, platform_url, _ = migrated_scratch
        engine = create_engine(platform_url)
        agreement_id = uuid.uuid4()
        try:
            with engine.begin() as conn:
                conn.execute(
                    text(
                        "INSERT INTO mod_agreements.agreements ("
                        " id, reference, agreement_family_id, agreement_version,"
                        " counterparty_ref, agreement_type, status,"
                        " effective_date, expiry_date, record_version"
                        ") VALUES (:id, :ref, :fam, 1, 'acme', 'oem', 'draft',"
                        " DATE '2026-09-01', DATE '2027-08-31', 1)"
                    ),
                    {
                        "id": agreement_id,
                        "ref": f"AGR-{uuid.uuid4().hex[:8]}",
                        "fam": uuid.uuid4(),
                    },
                )
                found = conn.execute(
                    text("SELECT status FROM mod_agreements.agreements WHERE id = :id"),
                    {"id": agreement_id},
                ).scalar()
            assert found == "draft"
        finally:
            engine.dispose()

    def test_platform_api_may_update_the_header_but_not_a_line(
        self, migrated_scratch
    ) -> None:
        """The lifecycle lives on the header, so UPDATE has to exist there. The
        lines are frozen at proposal, which is why they get none."""
        admin_url, _, _ = migrated_scratch
        assert _has_privilege(admin_url, "agreements", "UPDATE", role="platform_api")
        assert not _has_privilege(
            admin_url, "agreement_lines", "UPDATE", role="platform_api"
        )


# ── Append-only history ─────────────────────────────────────────────────────


class TestTheHistoryIsAppendOnlyAgainstEveryRole:
    """A service rule cannot police a path that never calls the service, and an
    evidence history an administrator can rewrite is not evidence."""

    @pytest.fixture
    def seeded(self, migrated_scratch) -> tuple[str, uuid.UUID]:
        admin_url, _, _ = migrated_scratch
        agreement_id, family_id = uuid.uuid4(), uuid.uuid4()
        engine = create_engine(admin_url)
        try:
            with engine.begin() as conn:
                conn.execute(
                    text(
                        "INSERT INTO mod_agreements.agreements ("
                        " id, reference, agreement_family_id, agreement_version,"
                        " counterparty_ref, agreement_type, status,"
                        " effective_date, expiry_date, record_version"
                        ") VALUES (:id, :ref, :fam, 1, 'acme', 'oem', 'draft',"
                        " DATE '2026-09-01', DATE '2027-08-31', 1)"
                    ),
                    {
                        "id": agreement_id,
                        "ref": f"AGR-{uuid.uuid4().hex[:8]}",
                        "fam": family_id,
                    },
                )
                conn.execute(
                    text(
                        "INSERT INTO mod_agreements.agreement_events ("
                        " id, agreement_id, sequence, event_type, to_status,"
                        " command_id"
                        ") VALUES (:id, :aid, 1, 'agreement.proposed.v1',"
                        " 'proposed', 'cmd-1')"
                    ),
                    {"id": uuid.uuid4(), "aid": agreement_id},
                )
        finally:
            engine.dispose()
        return admin_url, agreement_id

    def test_app_admin_cannot_update_a_history_row(self, seeded) -> None:
        """`app_admin` legitimately holds full DML on the other two tables. The
        trigger is the only place this rule holds for it too."""
        admin_url, agreement_id = seeded
        engine = create_engine(admin_url)
        try:
            with engine.begin() as conn, pytest.raises(DBAPIError, match="append-only"):
                conn.execute(
                    text(
                        "UPDATE mod_agreements.agreement_events SET reason = 'edited' "
                        "WHERE agreement_id = :aid"
                    ),
                    {"aid": agreement_id},
                )
        finally:
            engine.dispose()

    def test_app_admin_cannot_delete_a_history_row(self, seeded) -> None:
        admin_url, agreement_id = seeded
        engine = create_engine(admin_url)
        try:
            with engine.begin() as conn, pytest.raises(DBAPIError, match="append-only"):
                conn.execute(
                    text(
                        "DELETE FROM mod_agreements.agreement_events "
                        "WHERE agreement_id = :aid"
                    ),
                    {"aid": agreement_id},
                )
        finally:
            engine.dispose()

    def test_deleting_the_agreement_cannot_launder_a_history_rewrite(
        self, seeded
    ) -> None:
        """`ondelete="RESTRICT"` closes the hole from the other side. Without
        it, "delete then re-create" removes the history through a path the
        trigger never sees."""
        admin_url, agreement_id = seeded
        engine = create_engine(admin_url)
        try:
            with engine.begin() as conn, pytest.raises(DBAPIError):
                conn.execute(
                    text("DELETE FROM mod_agreements.agreements WHERE id = :id"),
                    {"id": agreement_id},
                )
        finally:
            engine.dispose()

    def test_appending_a_further_row_still_works(self, seeded) -> None:
        """The trigger must refuse rewrites without refusing the append that
        every compensating transition depends on — a guard that blocked INSERT
        would make the whole module unusable while passing every test above."""
        admin_url, agreement_id = seeded
        engine = create_engine(admin_url)
        try:
            with engine.begin() as conn:
                conn.execute(
                    text(
                        "INSERT INTO mod_agreements.agreement_events ("
                        " id, agreement_id, sequence, event_type, to_status,"
                        " command_id"
                        ") VALUES (:id, :aid, 2, 'agreement.approved.v1',"
                        " 'approved', 'cmd-2')"
                    ),
                    {"id": uuid.uuid4(), "aid": agreement_id},
                )
                count = conn.execute(
                    text(
                        "SELECT count(*) FROM mod_agreements.agreement_events "
                        "WHERE agreement_id = :aid"
                    ),
                    {"aid": agreement_id},
                ).scalar()
            assert count == 2
        finally:
            engine.dispose()


# ── Constraints hold against raw SQL ────────────────────────────────────────


class TestTheConstraintsHoldWithoutTheService:
    """Every rule below is also enforced in `service.py`. These prove the
    database enforces them too — the service cannot police a path that never
    calls it."""

    @pytest.fixture
    def admin_url(self, migrated_scratch) -> str:
        return migrated_scratch[0]

    def _insert_agreement(self, conn, **overrides: object) -> uuid.UUID:
        params: dict[str, object] = {
            "id": uuid.uuid4(),
            "ref": f"AGR-{uuid.uuid4().hex[:8]}",
            "fam": uuid.uuid4(),
            "version": 1,
            "record_version": 1,
            "effective": "2026-09-01",
            "expiry": "2027-08-31",
        }
        params.update(overrides)
        conn.execute(
            text(
                "INSERT INTO mod_agreements.agreements ("
                " id, reference, agreement_family_id, agreement_version,"
                " counterparty_ref, agreement_type, status, effective_date,"
                " expiry_date, record_version"
                ") VALUES (:id, :ref, :fam, :version, 'acme', 'oem', 'draft',"
                " CAST(:effective AS date), CAST(:expiry AS date), :record_version)"
            ),
            params,
        )
        return params["id"]  # type: ignore[return-value]

    def test_a_duplicate_reference_is_refused(self, admin_url: str) -> None:
        engine = create_engine(admin_url)
        reference = f"AGR-{uuid.uuid4().hex[:8]}"
        try:
            with engine.begin() as conn:
                self._insert_agreement(conn, ref=reference)
            with engine.begin() as conn, pytest.raises(DBAPIError):
                self._insert_agreement(conn, ref=reference)
        finally:
            engine.dispose()

    def test_a_duplicate_family_version_is_refused(self, admin_url: str) -> None:
        """One version per family, so an amendment cannot fork the chain."""
        engine = create_engine(admin_url)
        family_id = uuid.uuid4()
        try:
            with engine.begin() as conn:
                self._insert_agreement(conn, fam=family_id, version=2)
            with engine.begin() as conn, pytest.raises(DBAPIError):
                self._insert_agreement(conn, fam=family_id, version=2)
        finally:
            engine.dispose()

    def test_an_expiry_before_the_effective_date_is_refused(
        self, admin_url: str
    ) -> None:
        engine = create_engine(admin_url)
        try:
            with engine.begin() as conn, pytest.raises(DBAPIError):
                self._insert_agreement(
                    conn, effective="2027-01-01", expiry="2026-01-01"
                )
        finally:
            engine.dispose()

    def test_a_non_positive_line_quantity_is_refused(self, admin_url: str) -> None:
        engine = create_engine(admin_url)
        try:
            with engine.begin() as conn:
                agreement_id = self._insert_agreement(conn)
            with engine.begin() as conn, pytest.raises(DBAPIError):
                conn.execute(
                    text(
                        "INSERT INTO mod_agreements.agreement_lines ("
                        " id, agreement_id, line_no, product_code,"
                        " capability_code, quantity, unit_amount,"
                        " unit_currency_code"
                        ") VALUES (:id, :aid, 1, 'p', 'c', 0, '1.00', 'NGN')"
                    ),
                    {"id": uuid.uuid4(), "aid": agreement_id},
                )
        finally:
            engine.dispose()

    def test_a_duplicate_history_sequence_is_refused(self, admin_url: str) -> None:
        """Dense per-agreement sequencing is what makes a gap detectable; a
        duplicate would let two transitions claim the same position."""
        engine = create_engine(admin_url)
        try:
            with engine.begin() as conn:
                agreement_id = self._insert_agreement(conn)
                conn.execute(
                    text(
                        "INSERT INTO mod_agreements.agreement_events ("
                        " id, agreement_id, sequence, event_type, to_status,"
                        " command_id"
                        ") VALUES (:id, :aid, 1, 'e', 'proposed', 'cmd-1')"
                    ),
                    {"id": uuid.uuid4(), "aid": agreement_id},
                )
            with engine.begin() as conn, pytest.raises(DBAPIError):
                conn.execute(
                    text(
                        "INSERT INTO mod_agreements.agreement_events ("
                        " id, agreement_id, sequence, event_type, to_status,"
                        " command_id"
                        ") VALUES (:id, :aid, 1, 'e2', 'approved', 'cmd-2')"
                    ),
                    {"id": uuid.uuid4(), "aid": agreement_id},
                )
        finally:
            engine.dispose()


# ── The approval-withdrawals table: append-only, its own message ────────────


def _seed_agreement(conn) -> uuid.UUID:
    agreement_id = uuid.uuid4()
    conn.execute(
        text(
            "INSERT INTO mod_agreements.agreements ("
            " id, reference, agreement_family_id, agreement_version,"
            " counterparty_ref, agreement_type, status,"
            " effective_date, expiry_date, record_version"
            ") VALUES (:id, :ref, :fam, 1, 'acme', 'oem', 'draft',"
            " DATE '2026-09-01', DATE '2027-08-31', 1)"
        ),
        {"id": agreement_id, "ref": f"AGR-{uuid.uuid4().hex[:8]}", "fam": uuid.uuid4()},
    )
    return agreement_id


def _seed_withdrawal(conn, agreement_id: uuid.UUID, **overrides: object) -> uuid.UUID:
    params: dict[str, object] = {
        "id": uuid.uuid4(),
        "aid": agreement_id,
        "req": f"req-{uuid.uuid4().hex[:8]}",
        "dec": f"apr-{uuid.uuid4().hex[:8]}",
        "policy": "commercial.oem",
        "version": 3,
        "subject": str(agreement_id),
        "digest": "0" * 64,
        "wref": f"wd-{uuid.uuid4().hex[:10]}",
        "reason": "policy compliance issue",
    }
    params.update(overrides)
    conn.execute(
        text(
            "INSERT INTO mod_agreements.agreement_approval_withdrawals ("
            " id, agreement_id, approval_request_ref, approval_decision_ref,"
            " approval_policy_code, approval_policy_version, subject_ref,"
            " content_hash, withdrawal_ref, reason, withdrawn_at,"
            " status_at_record, approval_carried, command_id"
            ") VALUES (:id, :aid, :req, :dec, :policy, :version, :subject,"
            " :digest, :wref, CAST(:reason AS text), now(), 'approved', false,"
            " 'cmd-seed')"
        ),
        params,
    )
    return params["id"]  # type: ignore[return-value]


class TestTheApprovalWithdrawalsTableIsReachableAndAppendOnly:
    """The same two-halved proof `agreement_events` gets — grants that actually
    work, and a rewrite refusal that names the right table — applied to the
    table `cg_0002_approval_withdrawals` adds."""

    def test_platform_api_can_insert_and_select_a_withdrawal_row(
        self, migrated_scratch
    ) -> None:
        admin_url, platform_url, _ = migrated_scratch
        admin_engine = create_engine(admin_url)
        try:
            with admin_engine.begin() as conn:
                agreement_id = _seed_agreement(conn)
        finally:
            admin_engine.dispose()

        platform_engine = create_engine(platform_url)
        try:
            with platform_engine.begin() as conn:
                withdrawal_id = _seed_withdrawal(conn, agreement_id)
                found = conn.execute(
                    text(
                        "SELECT reason FROM mod_agreements."
                        "agreement_approval_withdrawals WHERE id = :id"
                    ),
                    {"id": withdrawal_id},
                ).scalar()
            assert found == "policy compliance issue"
        finally:
            platform_engine.dispose()

    def test_app_admin_cannot_update_a_withdrawal_row(self, migrated_scratch) -> None:
        admin_url, _, _ = migrated_scratch
        engine = create_engine(admin_url)
        try:
            with engine.begin() as conn:
                agreement_id = _seed_agreement(conn)
                withdrawal_id = _seed_withdrawal(conn, agreement_id)
            with (
                engine.begin() as conn,
                pytest.raises(
                    DBAPIError, match="agreement_approval_withdrawals is append-only"
                ),
            ):
                conn.execute(
                    text(
                        "UPDATE mod_agreements.agreement_approval_withdrawals "
                        "SET reason = 'edited' WHERE id = :id"
                    ),
                    {"id": withdrawal_id},
                )
        finally:
            engine.dispose()

    def test_app_admin_cannot_delete_a_withdrawal_row(self, migrated_scratch) -> None:
        admin_url, _, _ = migrated_scratch
        engine = create_engine(admin_url)
        try:
            with engine.begin() as conn:
                agreement_id = _seed_agreement(conn)
                withdrawal_id = _seed_withdrawal(conn, agreement_id)
            with (
                engine.begin() as conn,
                pytest.raises(
                    DBAPIError, match="agreement_approval_withdrawals is append-only"
                ),
            ):
                conn.execute(
                    text(
                        "DELETE FROM mod_agreements.agreement_approval_withdrawals "
                        "WHERE id = :id"
                    ),
                    {"id": withdrawal_id},
                )
        finally:
            engine.dispose()

    def test_platform_api_cannot_update_a_withdrawal_row(
        self, migrated_scratch
    ) -> None:
        """`platform_api` holds INSERT/SELECT (hard rule 27's reachability
        half), never UPDATE/DELETE — so PostgreSQL refuses the rewrite on
        privilege (42501) before the trigger is reached; the trigger is the
        backstop for roles that do hold the privilege (app_admin, above)."""
        admin_url, platform_url, _ = migrated_scratch
        admin_engine = create_engine(admin_url)
        try:
            with admin_engine.begin() as conn:
                agreement_id = _seed_agreement(conn)
                withdrawal_id = _seed_withdrawal(conn, agreement_id)
        finally:
            admin_engine.dispose()
        engine = create_engine(platform_url)
        try:
            with (
                engine.begin() as conn,
                pytest.raises(DBAPIError, match="permission denied"),
            ):
                conn.execute(
                    text(
                        "UPDATE mod_agreements.agreement_approval_withdrawals "
                        "SET reason = 'edited' WHERE id = :id"
                    ),
                    {"id": withdrawal_id},
                )
        finally:
            engine.dispose()

    def test_platform_api_cannot_delete_a_withdrawal_row(
        self, migrated_scratch
    ) -> None:
        admin_url, platform_url, _ = migrated_scratch
        admin_engine = create_engine(admin_url)
        try:
            with admin_engine.begin() as conn:
                agreement_id = _seed_agreement(conn)
                withdrawal_id = _seed_withdrawal(conn, agreement_id)
        finally:
            admin_engine.dispose()
        engine = create_engine(platform_url)
        try:
            with (
                engine.begin() as conn,
                pytest.raises(DBAPIError, match="permission denied"),
            ):
                conn.execute(
                    text(
                        "DELETE FROM mod_agreements.agreement_approval_withdrawals "
                        "WHERE id = :id"
                    ),
                    {"id": withdrawal_id},
                )
        finally:
            engine.dispose()

    def test_app_admin_cannot_truncate_the_withdrawals_table(
        self, migrated_scratch
    ) -> None:
        """TRUNCATE bypasses row triggers (`refuse_withdrawal_rewrite`'s
        `BEFORE UPDATE OR DELETE` never fires for it) — `cg_0002`'s SECOND,
        statement-level trigger (`refuse_withdrawal_truncate`) is the only
        thing that closes this path, and even `app_admin`, which legitimately
        owns full DML on this table, is refused by it."""
        admin_url, _, _ = migrated_scratch
        engine = create_engine(admin_url)
        try:
            with engine.begin() as conn:
                agreement_id = _seed_agreement(conn)
                _seed_withdrawal(conn, agreement_id)
            with (
                engine.begin() as conn,
                pytest.raises(
                    DBAPIError, match="agreement_approval_withdrawals is append-only"
                ),
            ):
                conn.execute(
                    text("TRUNCATE mod_agreements.agreement_approval_withdrawals")
                )
        finally:
            engine.dispose()


class TestTheApprovalWithdrawalConstraintsHoldWithoutTheService:
    """Every rule below is also enforced in `service.record_approval_
    withdrawal`. These prove the database enforces them too."""

    def test_a_duplicate_withdrawal_ref_across_different_agreements_is_refused(
        self, migrated_scratch
    ) -> None:
        admin_url, _, _ = migrated_scratch
        engine = create_engine(admin_url)
        try:
            withdrawal_ref = f"wd-{uuid.uuid4().hex[:10]}"
            with engine.begin() as conn:
                first_agreement = _seed_agreement(conn)
                _seed_withdrawal(conn, first_agreement, wref=withdrawal_ref)
            with engine.begin() as conn:
                second_agreement = _seed_agreement(conn)
            with engine.begin() as conn, pytest.raises(DBAPIError):
                _seed_withdrawal(conn, second_agreement, wref=withdrawal_ref)
        finally:
            engine.dispose()

    def test_a_duplicate_agreement_and_decision_ref_is_refused(
        self, migrated_scratch
    ) -> None:
        """One withdrawal per decision — the defence in depth the service's
        own `evidence_conflict` outcome relies on never being reached by a race
        it did not itself serialize."""
        admin_url, _, _ = migrated_scratch
        engine = create_engine(admin_url)
        try:
            with engine.begin() as conn:
                agreement_id = _seed_agreement(conn)
                decision_ref = f"apr-{uuid.uuid4().hex[:8]}"
                _seed_withdrawal(conn, agreement_id, dec=decision_ref)
            with engine.begin() as conn, pytest.raises(DBAPIError):
                _seed_withdrawal(conn, agreement_id, dec=decision_ref)
        finally:
            engine.dispose()

    def test_a_blank_reason_is_refused_by_the_check_constraint(
        self, migrated_scratch
    ) -> None:
        admin_url, _, _ = migrated_scratch
        engine = create_engine(admin_url)
        try:
            with engine.begin() as conn:
                agreement_id = _seed_agreement(conn)
            with engine.begin() as conn, pytest.raises(DBAPIError):
                _seed_withdrawal(conn, agreement_id, reason="")
        finally:
            engine.dispose()


def test_the_declared_database_catalog_matches_the_live_migrated_schema(
    migrated_scratch: tuple[str, str, str],
) -> None:
    """The manifest's catalogue contribution — all four tables, including the
    `agreement_approval_withdrawals` contract that was DRAFTED from its
    migration rather than transcribed from a live observation like the
    original three (see `manifest.py`'s module docstring) — is observed
    against the migrated PostgreSQL schema and must show zero drift. This test
    IS the verification that draft depends on, per `manifest.py`'s own
    comment: "verified against a live observation by
    `tests/test_commercial_agreements_platform_isolation.py` in CI"."""
    import dotmac_commercial_agreements
    from dotmac_commercial_agreements.manifest import module
    from dotmac_kernel import (
        ComposedDatabaseLineageHeadV1,
        DatabaseCatalogOwnerKind,
        DatabaseCatalogOwnerV1,
        ModuleDatabaseCatalogSnapshot,
        compare_module_database_catalog,
        observe_postgres_tables_columns,
    )

    admin_url, _, _ = migrated_scratch
    snapshot = ModuleDatabaseCatalogSnapshot.from_manifest(
        module,
        distribution_name="dotmac-commercial-agreements",
        distribution_version=dotmac_commercial_agreements.__version__,
        composed_lineage_head=ComposedDatabaseLineageHeadV1(
            DatabaseCatalogOwnerV1(DatabaseCatalogOwnerKind.MODULE, module.code),
            "cg_0002_approval_withdrawals",
        ),
    )
    engine = create_engine(admin_url)
    try:
        with engine.connect() as conn:
            observation = observe_postgres_tables_columns(
                conn, schemas=("mod_agreements",)
            )
    finally:
        engine.dispose()
    comparison = compare_module_database_catalog(snapshot, observation)
    drifts = [
        f"{d.table}.{d.column} {d.attribute.value} {d.direction.value}: "
        f"declared={d.declared!r} observed={d.observed!r}"
        for d in comparison.drifts
    ]
    assert drifts == [], "\n".join(drifts)
    assert comparison.measurement_issues == ()
    declared_tables = {table.name for table in snapshot.tables}
    assert declared_tables == set(TABLES)


# ── The lock race: a withdrawal and an approve on one agreement ─────────────


class _AlwaysDeclaredCatalogue:
    """A capability reader that never refuses — the lock-race tests are about
    the row lock, not about catalogue validation."""

    def require_declared(self, product_code: str, codes: tuple[str, ...]) -> None:
        return None


def _proposed_agreement(engine):
    """A `proposed` agreement, built through the service's own draft → propose
    path against real Postgres, exactly as the unit tests build one against
    SQLite."""
    from dotmac_commercial_agreements import (
        AgreementPeriod,
        CommercialTerms,
        DraftCommand,
        LineInput,
        ProposeCommand,
        open_draft,
        propose,
    )

    with Session(engine) as db, db.begin():
        drafted = open_draft(
            db,
            DraftCommand(
                command_id=f"cmd-{uuid.uuid4().hex[:12]}",
                reference=f"AGR-{uuid.uuid4().hex[:8]}",
                counterparty_ref="acme-operator",
                agreement_type="oem_reseller",
                period=AgreementPeriod(date(2026, 9, 1), date(2027, 8, 31)),
                lines=(
                    LineInput(
                        product_code="dotmac_sub",
                        capability_code="subscriber.manage",
                        quantity=500,
                        terms=CommercialTerms("12.50", "NGN"),
                    ),
                ),
            ),
            catalogue=_AlwaysDeclaredCatalogue(),
        )
    with Session(engine) as db, db.begin():
        proposed = propose(
            db,
            ProposeCommand(
                command_id=f"cmd-{uuid.uuid4().hex[:12]}",
                agreement_id=drafted.id,
                approval_policy_code="commercial.oem",
                approval_policy_version=3,
            ),
            catalogue=_AlwaysDeclaredCatalogue(),
        )
    return proposed


def _withdrawal_command(
    agreement_id: uuid.UUID, *, decision_ref: str, content_hash: str
):
    from dotmac_commercial_agreements import RecordApprovalWithdrawalCommand

    return RecordApprovalWithdrawalCommand(
        command_id=f"cmd-{uuid.uuid4().hex[:12]}",
        agreement_id=agreement_id,
        approval_request_ref=f"req-{uuid.uuid4().hex[:8]}",
        approval_decision_ref=decision_ref,
        policy_code="commercial.oem",
        policy_version=3,
        subject_ref=str(agreement_id),
        content_hash=content_hash,
        withdrawal_ref=f"wd-{uuid.uuid4().hex[:10]}",
        reason="policy compliance issue",
        withdrawn_at=datetime(2026, 9, 5, 12, 0, tzinfo=UTC),
    )


def _approve_command(agreement_id: uuid.UUID, *, decision_ref: str, content_hash: str):
    from dotmac_commercial_agreements import ApprovalEvidence, ApproveCommand

    return ApproveCommand(
        command_id=f"cmd-{uuid.uuid4().hex[:12]}",
        agreement_id=agreement_id,
        evidence=ApprovalEvidence(
            policy_code="commercial.oem",
            policy_version=3,
            decision_ref=decision_ref,
            content_digest=content_hash,
            decided_at=datetime(2026, 8, 20, 9, 0, tzinfo=UTC),
        ),
    )


def _wait_until_blocked_on_a_lock(
    engine, *, deadline_seconds: float = 20.0, poll_seconds: float = 0.1
) -> bool:
    """Poll `pg_stat_activity` for a backend genuinely waiting on a lock.

    A join timeout alone cannot tell "blocked on the row lock" apart from
    "slow for some other reason" — this looks at Postgres's own view of why
    the backend hasn't returned. Bounded so a caller that never observes the
    wait does not hang CI.
    """
    deadline = time.monotonic() + deadline_seconds
    with engine.connect() as conn:
        while time.monotonic() < deadline:
            waiting = conn.execute(
                text(
                    "SELECT count(*) FROM pg_stat_activity "
                    "WHERE wait_event_type = 'Lock' AND datname = current_database() "
                    "AND pid <> pg_backend_pid()"
                )
            ).scalar()
            if waiting:
                return True
            time.sleep(poll_seconds)
    return False


class TestTheWithdrawalLockRaceAgainstApprove:
    """`_load_locked`'s `FOR UPDATE` is what makes `record_approval_withdrawal`
    and `approve` serialize on one agreement row — proven here against real
    Postgres, because SQLite's coarser locking cannot show a genuine block.

    The lock proof must be NON-VACUOUS: `record_approval_withdrawal`'s own
    write (`row.record_version += 1`) also takes a row lock, so if session A
    simply ran to completion before B tried, B would block on THAT lock
    whether or not `_load_locked` used `FOR UPDATE` at all — the previous
    version of this test (a `SET LOCAL lock_timeout` + a `DBAPIError` match on
    "lock timeout") could not tell the two apart. This version instead
    confirms, via `pg_stat_activity`, that B is GENUINELY blocked — with no
    timeout on B's side to race against — before A ever commits.
    """

    @pytest.fixture(autouse=True)
    def _installed_module_audit_actions(self) -> Iterator[None]:
        """Drive the service as an adopter does: the module's manifest, and so
        its audit actions, are installed — and the process-wide registry this
        replaces is RESTORED afterwards, so no later test in the session sees a
        registry holding only this module's actions."""
        from dotmac_commercial_agreements import module
        from dotmac_kernel.audit_actions import (
            AuditActionRegistry,
            AuditActionsNotInstalledError,
            active_audit_actions,
            install_audit_actions,
        )

        try:
            previous = active_audit_actions()
        except AuditActionsNotInstalledError:
            previous = None
        # Swap in this module's registry for the class, then put back whatever
        # the session had, so a composed app's registry survives these tests.
        install_audit_actions(AuditActionRegistry.from_manifests([module]))
        try:
            yield
        finally:
            if previous is not None:
                install_audit_actions(previous)

    def test_an_in_flight_withdrawal_blocks_approve_until_it_commits(
        self, migrated_scratch
    ) -> None:
        from dotmac_commercial_agreements import (
            TransitionRefusedError,
            approve,
            record_approval_withdrawal,
        )

        _, platform_url, _ = migrated_scratch
        engine = create_engine(platform_url)
        try:
            proposed = _proposed_agreement(engine)
            decision_ref = f"apr-{uuid.uuid4().hex[:8]}"
            digest = proposed.content_hash or ""

            session_a = Session(engine)
            session_a.begin()
            record_approval_withdrawal(
                session_a,
                _withdrawal_command(
                    proposed.id, decision_ref=decision_ref, content_hash=digest
                ),
            )
            # Session A stays open, uncommitted, holding the row lock.

            failures: list[BaseException] = []

            def approve_in_thread() -> None:
                try:
                    with Session(engine) as db, db.begin():
                        approve(
                            db,
                            _approve_command(
                                proposed.id,
                                decision_ref=decision_ref,
                                content_hash=digest,
                            ),
                        )
                except BaseException as exc:
                    failures.append(exc)

            thread = Thread(target=approve_in_thread)
            thread.start()
            try:
                assert _wait_until_blocked_on_a_lock(
                    engine
                ), "approve never blocked on the withdrawal's row lock"
                session_a.commit()
            finally:
                session_a.close()
                thread.join(timeout=10)
            assert not thread.is_alive(), "approve did not unblock once A committed"
            assert len(failures) == 1, failures
            assert isinstance(failures[0], TransitionRefusedError), failures

            with Session(engine) as db:
                row = db.execute(
                    text("SELECT status FROM mod_agreements.agreements WHERE id = :id"),
                    {"id": proposed.id},
                ).scalar_one()
                withdrawal_count = db.execute(
                    text(
                        "SELECT count(*) FROM mod_agreements."
                        "agreement_approval_withdrawals WHERE agreement_id = :id"
                    ),
                    {"id": proposed.id},
                ).scalar_one()
            assert row == "proposed"
            assert withdrawal_count == 1
        finally:
            engine.dispose()

    def test_when_approve_commits_first_the_withdrawal_still_records_as_carried(
        self, migrated_scratch
    ) -> None:
        """The reverse order: nothing here needs the lock to be contested — the
        withdrawal simply observes the now-committed approval's decision_ref
        and records `approval_carried=True`, and the status stays `approved`."""
        from dotmac_commercial_agreements import (
            ApprovalWithdrawalOutcome,
            approve,
            record_approval_withdrawal,
        )

        _, platform_url, _ = migrated_scratch
        engine = create_engine(platform_url)
        try:
            proposed = _proposed_agreement(engine)
            decision_ref = f"apr-{uuid.uuid4().hex[:8]}"
            digest = proposed.content_hash or ""

            with Session(engine) as db, db.begin():
                approved = approve(
                    db,
                    _approve_command(
                        proposed.id, decision_ref=decision_ref, content_hash=digest
                    ),
                )
            assert approved.status == "approved"

            with Session(engine) as db, db.begin():
                result = record_approval_withdrawal(
                    db,
                    _withdrawal_command(
                        proposed.id, decision_ref=decision_ref, content_hash=digest
                    ),
                )
            assert result.outcome == ApprovalWithdrawalOutcome.RECORDED
            assert result.approval_carried is True
            assert result.status == "approved"
        finally:
            engine.dispose()
