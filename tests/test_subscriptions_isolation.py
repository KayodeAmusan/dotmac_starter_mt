"""PostgreSQL canaries for subscriptions' two declared persistence planes."""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Barrier

import pytest
from dotmac_kernel.cache import TenantScope
from dotmac_kernel.planes import ModulePlane, ModulePlaneSelection
from dotmac_subscriptions import list_effective_offers
from dotmac_subscriptions.models import PLATFORM_TABLES, TENANT_TABLES
from sqlalchemy import create_engine, event, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

REPO_ROOT = Path(__file__).resolve().parent.parent
KERNEL_VERSIONS = (
    REPO_ROOT / "packages/dotmac-kernel/src/dotmac_kernel/migrations/versions"
)
ASSEMBLY_VERSIONS = REPO_ROOT / "alembic/versions"
SUBSCRIPTIONS_VERSIONS = (
    REPO_ROOT
    / "packages/dotmac-subscriptions/src/dotmac_subscriptions/migrations/versions"
)


def _superuser_url() -> str:
    url = os.getenv("TEST_MIGRATION_DATABASE_URL") or os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL not set — these proofs need Postgres")
    return url


def _url_for(base_url: str, dbname: str, *, user: str | None = None) -> str:
    scheme_userhost, _, _ = base_url.rpartition("/")
    if user is not None:
        scheme, _, userhost = scheme_userhost.partition("://")
        host = userhost.rpartition("@")[2]
        scheme_userhost = f"{scheme}://{user}@{host}"
    return f"{scheme_userhost}/{dbname}"


@pytest.fixture
def subscriptions_scratch() -> Iterator[tuple[str, str, str]]:
    """A migrated disposable database with both module planes selected."""
    superuser = _superuser_url()
    name = f"subscriptions_{uuid.uuid4().hex[:12]}"
    server = create_engine(superuser, isolation_level="AUTOCOMMIT")
    with server.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{name}"'))

    setup = create_engine(_url_for(superuser, name), isolation_level="AUTOCOMMIT")
    with setup.connect() as conn:
        conn.execute(text("ALTER SCHEMA public OWNER TO app_admin"))
        conn.execute(text(f'GRANT CREATE ON DATABASE "{name}" TO app_admin'))
        conn.execute(text(f'GRANT CONNECT ON DATABASE "{name}" TO app_user'))
        conn.execute(text(f'GRANT CONNECT ON DATABASE "{name}" TO platform_api'))
        conn.execute(text("GRANT USAGE ON SCHEMA public TO app_user"))
    setup.dispose()

    previous_url = os.environ.get("MIGRATION_DATABASE_URL")
    try:
        from alembic import command
        from alembic.config import Config

        cfg = Config(str(REPO_ROOT / "alembic.ini"))
        cfg.set_main_option("script_location", str(REPO_ROOT / "alembic"))
        cfg.set_main_option(
            "version_locations",
            f"{KERNEL_VERSIONS} {ASSEMBLY_VERSIONS} {SUBSCRIPTIONS_VERSIONS}",
        )
        cfg.attributes["module_plane_selections"] = (
            ModulePlaneSelection(
                module="subscriptions",
                planes=(ModulePlane.TENANT, ModulePlane.PLATFORM),
            ),
        )
        admin_url = _url_for(superuser, name, user="app_admin")
        os.environ["MIGRATION_DATABASE_URL"] = admin_url
        command.upgrade(cfg, "heads")
        yield (
            admin_url,
            _url_for(superuser, name, user="app_user"),
            _url_for(superuser, name, user="platform_api"),
        )
    finally:
        if previous_url is None:
            os.environ.pop("MIGRATION_DATABASE_URL", None)
        else:
            os.environ["MIGRATION_DATABASE_URL"] = previous_url
        with server.connect() as conn:
            conn.execute(
                text(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname = :name AND pid <> pg_backend_pid()"
                ),
                {"name": name},
            )
            conn.execute(text(f'DROP DATABASE IF EXISTS "{name}"'))
        server.dispose()


def _make_tenants(admin_url: str) -> tuple[uuid.UUID, uuid.UUID]:
    tenants = (uuid.uuid4(), uuid.uuid4())
    engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with engine.connect() as conn:
        for tenant_id in tenants:
            conn.execute(
                text(
                    "INSERT INTO public.tenants (id, name, slug, is_active) "
                    "VALUES (:id, :name, :slug, true)"
                ),
                {
                    "id": tenant_id,
                    "name": f"tenant-{tenant_id.hex[:8]}",
                    "slug": tenant_id.hex[:8],
                },
            )
    engine.dispose()
    return tenants


def _tenant_engine(url: str, tenant_id: uuid.UUID):
    engine = create_engine(url)

    @event.listens_for(engine, "connect")
    def _set_tenant(dbapi_connection, _record):
        with dbapi_connection.cursor() as cursor:
            cursor.execute(
                "SELECT set_config('app.current_tenant', %s, false)",
                (str(tenant_id),),
            )

    return engine


def test_tenant_rows_are_invisible_across_tenant_contexts(
    subscriptions_scratch: tuple[str, str, str],
) -> None:
    admin_url, user_url, _ = subscriptions_scratch
    left, right = _make_tenants(admin_url)
    offer_id = uuid.uuid4()
    left_engine = _tenant_engine(user_url, left)
    with left_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO mod_subscriptions.offers "
                "(id, tenant_id, code, name, status) "
                "VALUES (:id, :tenant_id, 'offer-a', 'Offer A', 'draft')"
            ),
            {"id": offer_id, "tenant_id": left},
        )
    left_engine.dispose()

    right_engine = _tenant_engine(user_url, right)
    with right_engine.connect() as conn:
        assert conn.scalar(text("SELECT count(*) FROM mod_subscriptions.offers")) == 0
    right_engine.dispose()


def test_offer_catalog_read_cannot_cross_tenant_scope(
    subscriptions_scratch: tuple[str, str, str],
) -> None:
    admin_url, user_url, _ = subscriptions_scratch
    left, right = _make_tenants(admin_url)
    owner = create_engine(admin_url)
    now = datetime(2026, 8, 18, tzinfo=UTC)
    with owner.begin() as conn:
        for tenant_id, code, name in (
            (left, "left.offer", "Left offer"),
            (right, "right.offer", "Right offer"),
        ):
            offer_id = uuid.uuid4()
            version_id = uuid.uuid4()
            conn.execute(
                text(
                    "INSERT INTO mod_subscriptions.offers "
                    "(id, tenant_id, code, name, status) "
                    "VALUES (:offer, :tenant, :code, :name, 'published')"
                ),
                {
                    "offer": offer_id,
                    "tenant": tenant_id,
                    "code": code,
                    "name": name,
                },
            )
            conn.execute(
                text(
                    "INSERT INTO mod_subscriptions.offer_versions "
                    "(id, tenant_id, offer_id, version, charge_model_code, "
                    "pricing_mode, state, effective_from, "
                    "source_code, source_id, source_version, command_id, "
                    "content_digest) VALUES "
                    "(:version, :tenant, :offer, 1, 'recurring_access', "
                    "'catalog_price', 'published', :now, "
                    "'accepted_order_line', :source, 1, :command, :digest)"
                ),
                {
                    "version": version_id,
                    "tenant": tenant_id,
                    "offer": offer_id,
                    "now": now,
                    "source": uuid.uuid4(),
                    "command": uuid.uuid4(),
                    "digest": tenant_id.hex * 2,
                },
            )
            conn.execute(
                text(
                    "INSERT INTO mod_subscriptions.offer_version_prices "
                    "(id, tenant_id, offer_version_id, price_key, "
                    "charge_model_code, amount, currency, scale, quantity) "
                    "VALUES (:id, :tenant, :version, 'base', "
                    "'recurring_access', 100, 'EUR', 2, 1)"
                ),
                {"id": uuid.uuid4(), "tenant": tenant_id, "version": version_id},
            )
    owner.dispose()

    right_engine = _tenant_engine(user_url, right)
    with Session(right_engine) as db:
        page = list_effective_offers(
            db,
            scope=TenantScope(right),
            effective_at=now,
        )
    right_engine.dispose()

    assert page.total == 1
    assert [item.code for item in page.items] == ["right.offer"]


def test_rls_canary_is_sensitive_to_the_policy(
    subscriptions_scratch: tuple[str, str, str],
) -> None:
    admin_url, user_url, _ = subscriptions_scratch
    left, right = _make_tenants(admin_url)
    left_engine = _tenant_engine(user_url, left)
    with left_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO mod_subscriptions.offers "
                "(id, tenant_id, code, name, status) "
                "VALUES (gen_random_uuid(), :tenant_id, 'offer-a', 'Offer A', 'draft')"
            ),
            {"tenant_id": left},
        )
    left_engine.dispose()

    owner = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with owner.connect() as conn:
        conn.execute(
            text("DROP POLICY offers_tenant_isolation " "ON mod_subscriptions.offers")
        )
        conn.execute(
            text("ALTER TABLE mod_subscriptions.offers " "NO FORCE ROW LEVEL SECURITY")
        )
        conn.execute(
            text("ALTER TABLE mod_subscriptions.offers " "DISABLE ROW LEVEL SECURITY")
        )
    owner.dispose()

    right_engine = _tenant_engine(user_url, right)
    with right_engine.connect() as conn:
        assert conn.scalar(text("SELECT count(*) FROM mod_subscriptions.offers")) == 1
    right_engine.dispose()


@pytest.mark.parametrize("table", TENANT_TABLES)
def test_every_tenant_table_enables_and_forces_rls(
    subscriptions_scratch: tuple[str, str, str], table: str
) -> None:
    admin_url, _, _ = subscriptions_scratch
    engine = create_engine(admin_url)
    with engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT relrowsecurity, relforcerowsecurity FROM pg_class "
                "WHERE oid = CAST(:table_name AS regclass)"
            ),
            {"table_name": f"mod_subscriptions.{table}"},
        ).one()
    engine.dispose()

    assert row == (True, True)


@pytest.mark.parametrize("table", TENANT_TABLES)
def test_every_tenant_table_has_a_required_tenant_id(
    subscriptions_scratch: tuple[str, str, str], table: str
) -> None:
    admin_url, _, _ = subscriptions_scratch
    engine = create_engine(admin_url)
    with engine.connect() as conn:
        not_null = conn.scalar(
            text(
                "SELECT a.attnotnull FROM pg_attribute a "
                "WHERE a.attrelid = CAST(:table_name AS regclass) "
                "AND a.attname = 'tenant_id' AND NOT a.attisdropped"
            ),
            {"table_name": f"mod_subscriptions.{table}"},
        )
    engine.dispose()

    assert not_null is True


@pytest.mark.parametrize("table", PLATFORM_TABLES)
def test_tenant_role_is_revoked_from_every_platform_table(
    subscriptions_scratch: tuple[str, str, str], table: str
) -> None:
    _, user_url, _ = subscriptions_scratch
    engine = create_engine(user_url)
    with engine.connect() as conn, pytest.raises(DBAPIError, match="permission denied"):
        conn.execute(
            text(f"SELECT 1 FROM mod_subscriptions.{table} LIMIT 1")  # noqa: S608
        )
    engine.dispose()


@pytest.mark.parametrize("table", PLATFORM_TABLES)
def test_platform_tables_have_no_rls_and_no_tenant_column_privilege(
    subscriptions_scratch: tuple[str, str, str], table: str
) -> None:
    admin_url, _, _ = subscriptions_scratch
    engine = create_engine(admin_url)
    with engine.connect() as conn:
        rls = conn.execute(
            text(
                "SELECT relrowsecurity, relforcerowsecurity FROM pg_class "
                "WHERE oid = CAST(:table_name AS regclass)"
            ),
            {"table_name": f"mod_subscriptions.{table}"},
        ).one()
        column_grants = conn.scalar(
            text(
                "SELECT count(*) FROM information_schema.column_privileges "
                "WHERE table_schema = 'mod_subscriptions' "
                "AND table_name = :table AND grantee = 'app_user'"
            ),
            {"table": table},
        )
        tenant_columns = conn.scalar(
            text(
                "SELECT count(*) FROM information_schema.columns "
                "WHERE table_schema = 'mod_subscriptions' "
                "AND table_name = :table AND column_name = 'tenant_id'"
            ),
            {"table": table},
        )
    engine.dispose()

    assert rls == (False, False)
    assert column_grants == 0
    assert tenant_columns == 0


@pytest.mark.parametrize("table", PLATFORM_TABLES)
def test_platform_role_can_reach_every_platform_table(
    subscriptions_scratch: tuple[str, str, str], table: str
) -> None:
    _, _, platform_url = subscriptions_scratch
    engine = create_engine(platform_url)
    with engine.connect() as conn:
        conn.execute(
            text(f"SELECT 1 FROM mod_subscriptions.{table} LIMIT 1")  # noqa: S608
        )
    engine.dispose()


def test_no_foreign_key_crosses_the_planes(
    subscriptions_scratch: tuple[str, str, str],
) -> None:
    admin_url, _, _ = subscriptions_scratch
    engine = create_engine(admin_url)
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT src.relname, dst.relname "
                "FROM pg_constraint c "
                "JOIN pg_class src ON src.oid = c.conrelid "
                "JOIN pg_class dst ON dst.oid = c.confrelid "
                "JOIN pg_namespace n ON n.oid = src.relnamespace "
                "WHERE c.contype = 'f' AND n.nspname = 'mod_subscriptions'"
            )
        ).all()
    engine.dispose()

    tenant = set(TENANT_TABLES)
    platform = set(PLATFORM_TABLES)
    assert not [
        (source, target)
        for source, target in rows
        if (source in tenant and target in platform)
        or (source in platform and target in tenant)
    ]


def test_published_offer_version_and_price_are_structurally_immutable(
    subscriptions_scratch: tuple[str, str, str],
) -> None:
    admin_url, _, _ = subscriptions_scratch
    left, _ = _make_tenants(admin_url)
    engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with engine.connect() as conn:
        offer_id = uuid.uuid4()
        version_id = uuid.uuid4()
        conn.execute(
            text(
                "INSERT INTO mod_subscriptions.offers "
                "(id, tenant_id, code, name, status) "
                "VALUES (:id, :tenant, 'offer-a', 'Offer A', 'published')"
            ),
            {"id": offer_id, "tenant": left},
        )
        conn.execute(
            text(
                "INSERT INTO mod_subscriptions.offer_versions "
                "(id, tenant_id, offer_id, version, charge_model_code, "
                "pricing_mode, state, effective_from, "
                "source_code, source_id, source_version, command_id, content_digest) "
                "VALUES (:id, :tenant, :offer, 1, 'recurring_access', "
                "'catalog_price', 'published', now(), "
                "'migration', gen_random_uuid(), 1, gen_random_uuid(), :digest)"
            ),
            {
                "id": version_id,
                "tenant": left,
                "offer": offer_id,
                "digest": "a" * 64,
            },
        )
        with pytest.raises(DBAPIError, match="immutable"):
            conn.execute(
                text(
                    "UPDATE mod_subscriptions.offer_versions "
                    "SET created_at = created_at + interval '1 second' WHERE id = :id"
                ),
                {"id": version_id},
            )
        with pytest.raises(DBAPIError, match="valid withdrawal"):
            conn.execute(
                text(
                    "UPDATE mod_subscriptions.offer_versions "
                    "SET state = 'withdrawn' WHERE id = :id"
                ),
                {"id": version_id},
            )
        price_id = uuid.uuid4()
        conn.execute(
            text(
                "INSERT INTO mod_subscriptions.offer_version_prices "
                "(id, tenant_id, offer_version_id, price_key, charge_model_code, "
                "amount, currency, scale, quantity) "
                "VALUES (:id, :tenant, :version, 'base', 'recurring_access', "
                "100, 'EUR', 2, 1)"
            ),
            {"id": price_id, "tenant": left, "version": version_id},
        )
        with pytest.raises(DBAPIError):
            conn.execute(
                text(
                    "UPDATE mod_subscriptions.offer_version_prices "
                    "SET amount = 101 WHERE id = :id"
                ),
                {"id": price_id},
            )
    engine.dispose()


def _run_platform_occurrence_race(
    admin_url: str, *, remove_natural_identity_guard: bool = False
) -> tuple[list[bool], int, uuid.UUID]:
    engine = create_engine(admin_url)
    offer_id = uuid.uuid4()
    offer_version_id = uuid.uuid4()
    contract_id = uuid.uuid4()
    contract_version_id = uuid.uuid4()
    line_key = uuid.uuid4()
    source_id = uuid.uuid4()
    period_start = datetime(2026, 8, 1, tzinfo=UTC)
    period_end = datetime(2026, 9, 1, tzinfo=UTC)

    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO mod_subscriptions.platform_offers "
                "(id, code, name, status) VALUES "
                "(:id, 'offer.concurrent', 'Concurrent offer', 'published')"
            ),
            {"id": offer_id},
        )
        conn.execute(
            text(
                "INSERT INTO mod_subscriptions.platform_offer_versions "
                "(id, offer_id, version, charge_model_code, pricing_mode, state, "
                "effective_from, source_code, "
                "source_id, source_version, command_id, content_digest) VALUES "
                "(:id, :offer_id, 1, 'recurring_access', 'catalog_price', "
                "'published', :starts_at, 'order_line', "
                ":source_id, 1, :command_id, :digest)"
            ),
            {
                "id": offer_version_id,
                "offer_id": offer_id,
                "starts_at": period_start,
                "source_id": source_id,
                "command_id": uuid.uuid4(),
                "digest": "a" * 64,
            },
        )
        if remove_natural_identity_guard:
            conn.execute(
                text(
                    "ALTER TABLE "
                    "mod_subscriptions.platform_recurring_charge_occurrences "
                    "DROP CONSTRAINT uq_platform_occurrences_natural_identity"
                )
            )
        conn.execute(
            text(
                "INSERT INTO mod_subscriptions.platform_subscription_contracts "
                "(id, source_code, source_id) VALUES "
                "(:id, 'order_line', :source_id)"
            ),
            {"id": contract_id, "source_id": source_id},
        )
        conn.execute(
            text(
                "INSERT INTO "
                "mod_subscriptions.platform_subscription_contract_versions "
                "(id, contract_id, version, state, source_code, source_id, "
                "source_version, starts_at, currency, rate_basis, rate_unit, "
                "rate_quantity, service_interval_unit, service_interval_count, "
                "invoice_interval_unit, invoice_interval_count, collection_timing, "
                "alignment, end_of_month_rule, timezone_name, proration_policy, "
                "rating_policy_version, actor, reason, recorded_at, command_id, "
                "correlation_id, idempotency_key, content_digest) VALUES "
                "(:id, :contract_id, 1, 'effective', 'order_line', :source_id, 1, "
                ":starts_at, 'EUR', 'fixed_per_service_period', 'month', 1, "
                "'month', 1, 'month', 1, 'advance', 'contract_anniversary', "
                "'clamp_to_month_end', 'Africa/Lagos', 'none', 'rating.v1', "
                "'concurrency-test', 'canary setup', :starts_at, :command_id, "
                ":correlation_id, :idempotency_key, :digest)"
            ),
            {
                "id": contract_version_id,
                "contract_id": contract_id,
                "source_id": source_id,
                "starts_at": period_start,
                "command_id": uuid.uuid4(),
                "correlation_id": uuid.uuid4(),
                "idempotency_key": f"contract:{contract_id}",
                "digest": "b" * 64,
            },
        )
        conn.execute(
            text(
                "INSERT INTO "
                "mod_subscriptions.platform_subscription_contract_lines "
                "(id, contract_version_id, contract_line_key, charge_model_code, "
                "source_code, source_id, source_version, description, "
                "product_link_ref, quantity, unit_price, currency, scale, "
                "offer_version_id, offer_version, entitlement_codes) VALUES "
                "(:id, :version_id, :line_key, 'recurring_access', 'order_line', "
                ":source_id, 1, 'Access', 'product:access', 1, 100, 'EUR', 2, "
                ":offer_version_id, 1, '[]'::jsonb)"
            ),
            {
                "id": uuid.uuid4(),
                "version_id": contract_version_id,
                "line_key": line_key,
                "source_id": source_id,
                "offer_version_id": offer_version_id,
            },
        )

    rendezvous = Barrier(2, timeout=30)

    def insert_candidate() -> bool:
        try:
            with engine.begin() as conn:
                rendezvous.wait()
                conn.execute(
                    text(
                        "INSERT INTO "
                        "mod_subscriptions.platform_recurring_charge_occurrences "
                        "(id, contract_id, contract_version_id, contract_line_key, "
                        "charge_model_code, source_code, source_id, source_version, "
                        "period_start, period_end, currency, pre_tax_amount, "
                        "amount_scale, rating_coverage_start, rating_coverage_end, "
                        "rating_unit_price, rating_quantity, rating_rate_basis, "
                        "rating_rate_unit, rating_rate_quantity, rating_rate_units, "
                        "rating_proration_policy, rating_proration_factor, "
                        "rating_timezone_name, rating_policy_version, "
                        "offer_version_ref, request_fingerprint, idempotency_key, "
                        "generation, state, emitted_at, command_id, correlation_id) "
                        "VALUES (:id, :contract_id, :version_id, :line_key, "
                        "'recurring_access', 'order_line', :source_id, 1, "
                        ":period_start, :period_end, 'EUR', 100, 2, :period_start, "
                        ":period_end, 100, 1, 'fixed_per_service_period', 'month', "
                        "1, 1, 'none', 1, 'Africa/Lagos', 'rating.v1', "
                        ":offer_ref, :fingerprint, :idempotency_key, 1, 'emitted', "
                        ":period_start, :command_id, :correlation_id)"
                    ),
                    {
                        "id": uuid.uuid4(),
                        "contract_id": contract_id,
                        "version_id": contract_version_id,
                        "line_key": line_key,
                        "source_id": source_id,
                        "period_start": period_start,
                        "period_end": period_end,
                        "offer_ref": f"{offer_version_id}:1",
                        "fingerprint": "c" * 64,
                        # Deliberately distinct: only the natural identity may win.
                        "idempotency_key": f"candidate:{uuid.uuid4()}",
                        "command_id": uuid.uuid4(),
                        "correlation_id": uuid.uuid4(),
                    },
                )
        except IntegrityError:
            return False
        return True

    with ThreadPoolExecutor(max_workers=2) as pool:
        inserted = list(pool.map(lambda _: insert_candidate(), range(2)))

    with engine.connect() as conn:
        row_count = conn.scalar(
            text(
                "SELECT count(*) FROM "
                "mod_subscriptions.platform_recurring_charge_occurrences "
                "WHERE contract_version_id = :version_id AND period_start = :start"
            ),
            {"version_id": contract_version_id, "start": period_start},
        )
        occurrence_id = conn.scalar(
            text(
                "SELECT id FROM "
                "mod_subscriptions.platform_recurring_charge_occurrences "
                "WHERE contract_version_id = :version_id "
                "ORDER BY id LIMIT 1"
            ),
            {"version_id": contract_version_id},
        )
    engine.dispose()

    assert occurrence_id is not None
    return inserted, int(row_count or 0), uuid.UUID(str(occurrence_id))


def test_concurrent_platform_generators_persist_one_occurrence_output(
    subscriptions_scratch: tuple[str, str, str],
) -> None:
    """The natural identity constraint is the last line of duplicate defence."""
    admin_url, _, _ = subscriptions_scratch
    inserted, row_count, _ = _run_platform_occurrence_race(admin_url)

    assert sorted(inserted) == [False, True]
    assert row_count == 1


def test_occurrence_concurrency_canary_is_sensitive_to_the_unique_guard(
    subscriptions_scratch: tuple[str, str, str],
) -> None:
    admin_url, _, _ = subscriptions_scratch
    inserted, row_count, _ = _run_platform_occurrence_race(
        admin_url,
        remove_natural_identity_guard=True,
    )

    assert inserted == [True, True]
    assert row_count == 2


def test_effective_contract_and_emitted_occurrence_are_structurally_immutable(
    subscriptions_scratch: tuple[str, str, str],
) -> None:
    admin_url, _, _ = subscriptions_scratch
    _, _, occurrence_id = _run_platform_occurrence_race(admin_url)
    engine = create_engine(admin_url)

    with engine.connect() as conn, pytest.raises(DBAPIError, match="immutable"):
        conn.execute(
            text(
                "UPDATE mod_subscriptions.platform_subscription_contract_versions "
                "SET created_at = created_at + interval '1 second' "
                "WHERE id = ("
                "SELECT contract_version_id FROM "
                "mod_subscriptions.platform_recurring_charge_occurrences "
                "WHERE id = :id)"
            ),
            {"id": occurrence_id},
        )
    with (
        engine.connect() as conn,
        pytest.raises(DBAPIError, match="valid terminal transition"),
    ):
        conn.execute(
            text(
                "UPDATE mod_subscriptions.platform_subscription_contract_versions "
                "SET state = 'ended' "
                "WHERE id = ("
                "SELECT contract_version_id FROM "
                "mod_subscriptions.platform_recurring_charge_occurrences "
                "WHERE id = :id)"
            ),
            {"id": occurrence_id},
        )
    with engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE mod_subscriptions.platform_recurring_charge_occurrences "
                "SET output_acknowledged_at = now() WHERE id = :id"
            ),
            {"id": occurrence_id},
        )
    with engine.connect() as conn, pytest.raises(DBAPIError, match="append-only"):
        conn.execute(
            text(
                "UPDATE mod_subscriptions.platform_recurring_charge_occurrences "
                "SET output_acknowledged_at = now() WHERE id = :id"
            ),
            {"id": occurrence_id},
        )
    with engine.connect() as conn, pytest.raises(DBAPIError, match="immutable"):
        conn.execute(
            text(
                "UPDATE mod_subscriptions.platform_recurring_charge_occurrences "
                "SET pre_tax_amount = pre_tax_amount + 1 WHERE id = :id"
            ),
            {"id": occurrence_id},
        )
    with engine.connect() as conn, pytest.raises(DBAPIError, match="cannot be deleted"):
        conn.execute(
            text(
                "DELETE FROM mod_subscriptions.platform_recurring_charge_occurrences "
                "WHERE id = :id"
            ),
            {"id": occurrence_id},
        )
    engine.dispose()


def test_recording_a_contract_version_does_not_depend_on_autoflush(
    subscriptions_scratch: tuple[str, str, str],
) -> None:
    """A module must not depend on its host assembly's session settings.

    `record_contract_version` adds the contract version and its lines and then
    flushes once. Ordering the version's INSERT before the lines' was, until
    this guard, left to whatever else happened to flush first — and with
    `autoflush=True` something always did, because the per-line loop issues a
    SELECT for the offer version.

    An assembly that sets `autoflush=False` gets no such flush, the line INSERT
    reaches PostgreSQL first, and it dies on `fk_contract_lines_version` — which
    the module reports as a conflict, so it reads like a real conflict and is
    not one. Dotmac Cloud found this composing the module for the first time;
    its `DatabaseRuntime` sets `autoflush=False` deliberately, so services add
    and flush while the request boundary owns the transaction.

    `dotmac-billing` already flushes its obligation explicitly for exactly this
    reason. This asserts the same rule in the FAILING configuration rather than
    the passing one — a canary that only ever runs with autoflush on cannot see
    this defect, which is why no existing subscription test caught it.
    """
    from decimal import Decimal

    from dotmac_kernel.cache import TenantScope
    from dotmac_subscriptions import (
        BillingCadence,
        CadenceAlignment,
        CollectionTiming,
        ContractLineInput,
        EndOfMonthRule,
        ExactAmount,
        IntervalUnit,
        OfferPriceInput,
        ProrationPolicy,
        RateBasis,
        SubscriptionVocabularyRegistry,
        TimerCancelResult,
        TimerScheduleResult,
    )
    from dotmac_subscriptions.commands import (
        OfferPricingMode,
        PublishOfferVersionCommand,
        RecordSubscriptionContractVersionCommand,
    )
    from dotmac_subscriptions.service import (
        publish_offer_version,
        record_contract_version,
    )
    from sqlalchemy.orm import sessionmaker

    admin_url, _app_url, _platform_url = subscriptions_scratch
    tenant_id, _other = _make_tenants(admin_url)
    scope = TenantScope(tenant_id=tenant_id)
    now = datetime(2026, 8, 24, 9, 0, tzinfo=UTC)
    starts = datetime(2026, 9, 1, tzinfo=UTC)

    registry = SubscriptionVocabularyRegistry(
        charge_models={"recurring.flat": "A flat recurring charge"},
        obligation_sources={"service": "A provisioned service"},
        billing_treatment_reasons={},
    )

    class _Timer:
        def schedule(self, db, *, scope, contract_line_key, due_at, recorded_at):
            return TimerScheduleResult(generation=1, due_at=due_at)

        def cancel(self, db, *, scope, contract_line_key, recorded_at):
            return TimerCancelResult(canceled=True)

    engine = create_engine(admin_url)
    # autoflush=False is the whole point of this canary.
    sessions = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    price = ExactAmount(amount=Decimal("10000.00"), currency="NGN", scale=2)
    source_id = uuid.uuid4()
    line_key = uuid.uuid4()
    try:
        with sessions() as db:
            db.execute(
                text("SELECT set_config('app.current_tenant', :tenant, true)"),
                {"tenant": str(tenant_id)},
            )
            offer = publish_offer_version(
                db,
                PublishOfferVersionCommand(
                    scope=scope,
                    offer_id=None,
                    offer_code="autoflush.guard",
                    offer_name="Autoflush Guard",
                    charge_model_code="recurring.flat",
                    pricing_mode=OfferPricingMode.catalog_price,
                    version=1,
                    prices=(
                        OfferPriceInput(
                            price_key="monthly",
                            charge_model_code="recurring.flat",
                            unit_price=price,
                            quantity=Decimal("1"),
                        ),
                    ),
                    effective_from=starts,
                    effective_until=None,
                    source_code="service",
                    source_id=source_id,
                    source_version=1,
                    command_id=uuid.uuid4(),
                ),
                registry=registry,
            )
            result = record_contract_version(
                db,
                RecordSubscriptionContractVersionCommand(
                    scope=scope,
                    contract_id=None,
                    source_code="service",
                    source_id=source_id,
                    source_version=1,
                    starts_at=starts,
                    ends_at=None,
                    currency="NGN",
                    cadence=BillingCadence(
                        rate_basis=RateBasis.per_rate_unit,
                        rate_unit=IntervalUnit.month,
                        rate_quantity=Decimal("1"),
                        service_interval_unit=IntervalUnit.month,
                        service_interval_count=1,
                        invoice_interval_unit=IntervalUnit.month,
                        invoice_interval_count=1,
                        collection_timing=CollectionTiming.advance,
                        alignment=CadenceAlignment.contract_anniversary,
                        timezone_name="Africa/Lagos",
                        end_of_month_rule=EndOfMonthRule.clamp_to_month_end,
                        proration_policy=ProrationPolicy.actual_calendar_days,
                        anchor_day=None,
                    ),
                    lines=(
                        ContractLineInput(
                            contract_line_key=line_key,
                            charge_model_code="recurring.flat",
                            source_code="service",
                            source_id=source_id,
                            source_version=1,
                            description="Autoflush guard",
                            product_link_ref="offer:autoflush.guard",
                            quantity=Decimal("1"),
                            unit_price=price,
                            offer_version_id=offer.offer_version_id,
                            offer_version=1,
                            entitlement_codes=(),
                        ),
                    ),
                    actor="autoflush-guard",
                    reason="guard",
                    recorded_at=now,
                    command_id=uuid.uuid4(),
                    correlation_id=uuid.uuid4(),
                    idempotency_key=f"autoflush-guard-{line_key}",
                ),
                registry=registry,
                timer=_Timer(),
            )
            db.commit()

        assert result.line_keys == (line_key,)
        with engine.connect() as conn:
            conn.execute(
                text("SELECT set_config('app.current_tenant', :tenant, true)"),
                {"tenant": str(tenant_id)},
            )
            stored = conn.execute(
                text(
                    "SELECT count(*) FROM mod_subscriptions.subscription_contract_lines"
                    " WHERE contract_version_id = :version"
                ),
                {"version": result.version_id},
            ).scalar_one()
        assert stored == 1
    finally:
        engine.dispose()


# ── su_0003: complimentary / sponsored treatment, structurally ───────────────
#
# The parametrized RLS, tenant-column, revoke and reachability canaries above
# already cover the four new tables, because they read `TENANT_TABLES` and
# `PLATFORM_TABLES`. What follows proves the invariants that only exist because
# of this slice: the mandatory end, the bounded non-cash value, append-only
# grant evidence, frozen approval terms, and the refusal to change commercial
# terms while an approval is open.


#: Fixture-only fingerprints for the direct seed inserts below.
#:
#: These canaries deliberately write rows as `app_admin` in raw SQL rather than
#: through `preview` + `approve`, because most of them exist to attempt a row
#: the SERVICE would refuse — `treatment = 'standard'`, a NULL `ends_at`, an
#: overlapping arrangement, a grant above its ceiling — and prove the DATABASE
#: refuses it too. Going through the service could never reach those inserts.
#:
#: Supplying the fingerprint explicitly is therefore right, and is what the
#: pre-existing occurrence canary in this file already does. Nothing here
#: asserts on a fingerprint: `command_fingerprint` is the evidence the SERVICE
#: stale-preview guard compares, and that guard is proved where it lives, in
#: `tests/unit/test_subscriptions_treatments.py`. What must NOT happen is a
#: `server_default` on the column to make a missing value disappear — a
#: defaulted fingerprint is a fabricated one, and it would let a real approval
#: be stored with no evidence of the preview it confirmed.
_SEED_FINGERPRINT = "c" * 64
_SEED_ARRANGEMENT_FINGERPRINT = "d" * 64


def _seed_tenant_line(admin_url: str, tenant_id: uuid.UUID) -> dict[str, uuid.UUID]:
    """Insert one published offer version, contract version, line and occurrence."""
    ids = {
        "offer": uuid.uuid4(),
        "offer_version": uuid.uuid4(),
        "contract": uuid.uuid4(),
        "contract_version": uuid.uuid4(),
        "line": uuid.uuid4(),
        "line_key": uuid.uuid4(),
        "occurrence": uuid.uuid4(),
    }
    start = datetime(2026, 9, 1, tzinfo=UTC)
    end = datetime(2026, 10, 1, tzinfo=UTC)
    engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with engine.connect() as conn:
        conn.execute(
            text(
                "INSERT INTO mod_subscriptions.offers "
                "(id, tenant_id, code, name, status) "
                "VALUES (:id, :tenant, :code, 'Offer', 'published')"
            ),
            {
                "id": ids["offer"],
                "tenant": tenant_id,
                "code": f"o-{uuid.uuid4().hex[:8]}",
            },
        )
        conn.execute(
            text(
                "INSERT INTO mod_subscriptions.offer_versions "
                "(id, tenant_id, offer_id, version, charge_model_code, pricing_mode, "
                "state, effective_from, source_code, source_id, source_version, "
                "command_id, content_digest) "
                "VALUES (:id, :tenant, :offer, 1, 'recurring_access', 'catalog_price', "
                "'published', :start, 'seed', gen_random_uuid(), 1, "
                "gen_random_uuid(), :digest)"
            ),
            {
                "id": ids["offer_version"],
                "tenant": tenant_id,
                "offer": ids["offer"],
                "start": start,
                "digest": "b" * 64,
            },
        )
        conn.execute(
            text(
                "INSERT INTO mod_subscriptions.subscription_contracts "
                "(id, tenant_id, source_code, source_id) "
                "VALUES (:id, :tenant, 'seed', gen_random_uuid())"
            ),
            {"id": ids["contract"], "tenant": tenant_id},
        )
        conn.execute(
            text(_CONTRACT_VERSION_INSERT),
            {
                "id": ids["contract_version"],
                "tenant": tenant_id,
                "contract": ids["contract"],
                "start": start,
                "key": f"seed-{uuid.uuid4().hex}",
            },
        )
        conn.execute(
            text(
                "INSERT INTO mod_subscriptions.subscription_contract_lines "
                "(id, tenant_id, contract_version_id, contract_line_key, "
                "charge_model_code, source_code, source_id, source_version, "
                "description, product_link_ref, quantity, unit_price, currency, "
                "scale, offer_version_id, offer_version, entitlement_codes) "
                "VALUES (:id, :tenant, :version, :key, 'recurring_access', 'seed', "
                "gen_random_uuid(), 1, 'Access', 'product:access', 1, 100, 'EUR', "
                "2, :offer_version, 1, '[]'::jsonb)"
            ),
            {
                "id": ids["line"],
                "tenant": tenant_id,
                "version": ids["contract_version"],
                "key": ids["line_key"],
                "offer_version": ids["offer_version"],
            },
        )
        conn.execute(
            text(_OCCURRENCE_INSERT),
            {
                "id": ids["occurrence"],
                "tenant": tenant_id,
                "contract": ids["contract"],
                "version": ids["contract_version"],
                "key": ids["line_key"],
                "start": start,
                "end": end,
                "idempotency": f"occ-{uuid.uuid4().hex}",
                "fingerprint": _SEED_FINGERPRINT,
            },
        )
    engine.dispose()
    return ids


_CONTRACT_VERSION_INSERT = (
    "INSERT INTO mod_subscriptions.subscription_contract_versions "
    "(id, tenant_id, contract_id, version, state, source_code, source_id, "
    "source_version, starts_at, currency, rate_basis, rate_unit, rate_quantity, "
    "service_interval_unit, service_interval_count, invoice_interval_unit, "
    "invoice_interval_count, collection_timing, alignment, end_of_month_rule, "
    "timezone_name, proration_policy, rating_policy_version, actor, reason, "
    "recorded_at, command_id, correlation_id, idempotency_key, content_digest) "
    "VALUES (:id, :tenant, :contract, 1, 'effective', 'seed', gen_random_uuid(), 1, "
    ":start, 'EUR', 'fixed_per_service_period', 'month', 1, 'month', 1, 'month', 1, "
    "'advance', 'contract_anniversary', 'clamp_to_month_end', 'UTC', 'none', "
    "'fixed.v1', 'seed', 'seed', :start, gen_random_uuid(), gen_random_uuid(), "
    ":key, 'c0ffee')"
)

_OCCURRENCE_INSERT = (
    "INSERT INTO mod_subscriptions.recurring_charge_occurrences "
    "(id, tenant_id, contract_id, contract_version_id, contract_line_key, "
    "charge_model_code, source_code, source_id, source_version, period_start, "
    "period_end, currency, pre_tax_amount, amount_scale, rating_coverage_start, "
    "rating_coverage_end, rating_unit_price, rating_quantity, rating_rate_basis, "
    "rating_rate_unit, rating_rate_quantity, rating_rate_units, "
    "rating_proration_policy, rating_proration_factor, rating_timezone_name, "
    "rating_policy_version, offer_version_ref, request_fingerprint, "
    "idempotency_key, generation, state, emitted_at, command_id, correlation_id) "
    "VALUES (:id, :tenant, :contract, :version, :key, 'recurring_access', 'seed', "
    "gen_random_uuid(), 1, :start, :end, 'EUR', 100, 2, :start, :end, 100, 1, "
    "'fixed_per_service_period', 'month', 1, 1, 'none', 1, 'UTC', 'fixed.v1', "
    "'offer:1', :fingerprint, :idempotency, 1, 'emitted', :start, "
    "gen_random_uuid(), gen_random_uuid())"
)

#: The same insert as a SECOND draft version of the same contract — the only
#: way the module can change a price, cadence or offer version at all.
_NEXT_CONTRACT_VERSION_INSERT = _CONTRACT_VERSION_INSERT.replace(
    ", 1, 'effective',", ", 2, 'draft',"
)

_ARRANGEMENT_INSERT = (
    "INSERT INTO mod_subscriptions.subscription_billing_arrangements "
    "(id, tenant_id, contract_id, authorized_contract_version_id, "
    "authorized_offer_version_id, contract_line_key, treatment, reason_code, "
    "reason, status, starts_at, ends_at, approval_policy_ref, "
    "approval_policy_version, approval_policy_max_days, maximum_recurring_amount, "
    "currency, scale, service_interval_unit, service_interval_count, approved_by, "
    "approved_at, command_id, correlation_id, idempotency_key, command_fingerprint) "
    "VALUES (:id, :tenant, :contract, :version, :offer_version, :key, "
    ":treatment, 'internal_service', 'seeded approval', 'active', :start, :end, "
    "'policy', 'v1', 366, 100, 'EUR', 2, 'month', 1, 'finance', :start, "
    "gen_random_uuid(), gen_random_uuid(), :idempotency, :fingerprint)"
)

_GRANT_INSERT = (
    "INSERT INTO mod_subscriptions.subscription_billing_grants "
    "(id, tenant_id, arrangement_id, recurring_occurrence_id, contract_line_key, "
    "treatment, reason_code, starts_at, ends_at, contracted_amount, "
    "approved_maximum_amount, foregone_amount, currency, scale, actor, reason, "
    "command_id, correlation_id, idempotency_key, recorded_at) "
    "VALUES (:id, :tenant, :arrangement, :occurrence, :key, 'complimentary', "
    "'internal_service', :start, :end, :contracted, :approved, :foregone, 'EUR', "
    "2, 'finance', 'seeded grant', gen_random_uuid(), gen_random_uuid(), "
    ":idempotency, :start)"
)

_START = datetime(2026, 9, 1, tzinfo=UTC)
_END = datetime(2026, 10, 1, tzinfo=UTC)


def _approve(
    conn,
    tenant_id: uuid.UUID,
    ids: dict[str, uuid.UUID],
    *,
    end: datetime = _END,
) -> uuid.UUID:
    arrangement_id = uuid.uuid4()
    conn.execute(
        text(_ARRANGEMENT_INSERT),
        {
            "id": arrangement_id,
            "tenant": tenant_id,
            "contract": ids["contract"],
            "version": ids["contract_version"],
            "offer_version": ids["offer_version"],
            "key": ids["line_key"],
            "treatment": "complimentary",
            "start": _START,
            "end": end,
            "idempotency": f"arr-{uuid.uuid4().hex}",
            "fingerprint": _SEED_ARRANGEMENT_FINGERPRINT,
        },
    )
    return arrangement_id


def test_a_treatment_approved_by_one_tenant_is_invisible_to_another(
    subscriptions_scratch: tuple[str, str, str],
) -> None:
    admin_url, user_url, _ = subscriptions_scratch
    left, right = _make_tenants(admin_url)
    ids = _seed_tenant_line(admin_url, left)
    owner = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with owner.connect() as conn:
        _approve(conn, left, ids)
    owner.dispose()

    right_engine = _tenant_engine(user_url, right)
    with right_engine.connect() as conn:
        assert (
            conn.scalar(
                text(
                    "SELECT count(*) FROM "
                    "mod_subscriptions.subscription_billing_arrangements"
                )
            )
            == 0
        )
    right_engine.dispose()

    left_engine = _tenant_engine(user_url, left)
    with left_engine.connect() as conn:
        assert (
            conn.scalar(
                text(
                    "SELECT count(*) FROM "
                    "mod_subscriptions.subscription_billing_arrangements"
                )
            )
            == 1
        )
    left_engine.dispose()


def test_an_arrangement_cannot_be_recorded_without_an_end_date(
    subscriptions_scratch: tuple[str, str, str],
) -> None:
    admin_url, _, _ = subscriptions_scratch
    left, _ = _make_tenants(admin_url)
    ids = _seed_tenant_line(admin_url, left)
    engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with engine.connect() as conn, pytest.raises(DBAPIError, match="ends_at"):
        conn.execute(
            text(
                _ARRANGEMENT_INSERT.replace(":end", "NULL").replace(
                    ", :end,", ", NULL,"
                )
            ),
            {
                "id": uuid.uuid4(),
                "tenant": left,
                "contract": ids["contract"],
                "version": ids["contract_version"],
                "offer_version": ids["offer_version"],
                "key": ids["line_key"],
                "treatment": "complimentary",
                "start": _START,
                "idempotency": f"arr-{uuid.uuid4().hex}",
                "fingerprint": _SEED_ARRANGEMENT_FINGERPRINT,
            },
        )
    engine.dispose()


def test_standard_treatment_and_a_permanent_exemption_are_both_unrepresentable(
    subscriptions_scratch: tuple[str, str, str],
) -> None:
    admin_url, _, _ = subscriptions_scratch
    left, _ = _make_tenants(admin_url)
    ids = _seed_tenant_line(admin_url, left)
    engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with engine.connect() as conn, pytest.raises(DBAPIError, match="nonstandard"):
        conn.execute(
            text(_ARRANGEMENT_INSERT),
            {
                "id": uuid.uuid4(),
                "tenant": left,
                "contract": ids["contract"],
                "version": ids["contract_version"],
                "offer_version": ids["offer_version"],
                "key": ids["line_key"],
                "treatment": "standard",
                "start": _START,
                "end": _END,
                "idempotency": f"arr-{uuid.uuid4().hex}",
                "fingerprint": _SEED_ARRANGEMENT_FINGERPRINT,
            },
        )
    engine.dispose()


def test_approved_arrangement_terms_are_frozen_and_only_revocation_updates(
    subscriptions_scratch: tuple[str, str, str],
) -> None:
    admin_url, _, _ = subscriptions_scratch
    left, _ = _make_tenants(admin_url)
    ids = _seed_tenant_line(admin_url, left)
    engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with engine.connect() as conn:
        arrangement_id = _approve(conn, left, ids)
        with pytest.raises(DBAPIError, match="terms are immutable"):
            conn.execute(
                text(
                    "UPDATE mod_subscriptions.subscription_billing_arrangements "
                    "SET maximum_recurring_amount = 1 WHERE id = :id"
                ),
                {"id": arrangement_id},
            )
        with pytest.raises(DBAPIError, match="not a valid revocation"):
            conn.execute(
                text(
                    "UPDATE mod_subscriptions.subscription_billing_arrangements "
                    "SET status = 'revoked' WHERE id = :id"
                ),
                {"id": arrangement_id},
            )
        with pytest.raises(DBAPIError, match="cannot be deleted"):
            conn.execute(
                text(
                    "DELETE FROM mod_subscriptions.subscription_billing_arrangements "
                    "WHERE id = :id"
                ),
                {"id": arrangement_id},
            )
        conn.execute(
            text(
                "UPDATE mod_subscriptions.subscription_billing_arrangements "
                "SET status = 'revoked', revoked_by = 'finance', revoked_at = now(), "
                "revocation_reason = 'migrated to a paid plan', "
                "revocation_command_id = gen_random_uuid(), "
                "revocation_correlation_id = gen_random_uuid(), "
                "revocation_idempotency_key = 'rev-1' WHERE id = :id"
            ),
            {"id": arrangement_id},
        )
        assert (
            conn.scalar(
                text(
                    "SELECT status FROM "
                    "mod_subscriptions.subscription_billing_arrangements "
                    "WHERE id = :id"
                ),
                {"id": arrangement_id},
            )
            == "revoked"
        )
    engine.dispose()


def test_two_open_arrangements_cannot_overlap_on_one_contract_line(
    subscriptions_scratch: tuple[str, str, str],
) -> None:
    admin_url, _, _ = subscriptions_scratch
    left, _ = _make_tenants(admin_url)
    ids = _seed_tenant_line(admin_url, left)
    engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with engine.connect() as conn:
        _approve(conn, left, ids)
        with pytest.raises(DBAPIError, match="overlap"):
            conn.execute(
                text(_ARRANGEMENT_INSERT),
                {
                    "id": uuid.uuid4(),
                    "tenant": left,
                    "contract": ids["contract"],
                    "version": ids["contract_version"],
                    "offer_version": ids["offer_version"],
                    "key": ids["line_key"],
                    "treatment": "sponsored",
                    "start": datetime(2026, 9, 15, tzinfo=UTC),
                    "end": datetime(2026, 11, 1, tzinfo=UTC),
                    "idempotency": f"arr-{uuid.uuid4().hex}",
                    "fingerprint": "e" * 64,
                },
            )
    engine.dispose()


#: Every way a grant could hide what was really given away:
#: a zero contracted price conceals the waiver; a zero grant records nothing;
#: a grant above the contracted amount invents value; and a grant above the
#: approved ceiling escapes the review the approval exists to force.
_UNBOUNDED_GRANTS = [
    (0, 100, 100),
    (100, 100, 0),
    (100, 100, 101),
    (100, 40, 60),
]


@pytest.mark.parametrize(("contracted", "approved", "foregone"), _UNBOUNDED_GRANTS)
def test_the_grant_check_refuses_every_way_to_hide_foregone_revenue(
    subscriptions_scratch: tuple[str, str, str],
    contracted: int,
    approved: int,
    foregone: int,
) -> None:
    admin_url, _, _ = subscriptions_scratch
    left, _ = _make_tenants(admin_url)
    ids = _seed_tenant_line(admin_url, left)
    engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with engine.connect() as conn:
        arrangement_id = _approve(conn, left, ids)
        with pytest.raises(DBAPIError, match="bounded_non_cash_value"):
            conn.execute(
                text(_GRANT_INSERT),
                {
                    "id": uuid.uuid4(),
                    "tenant": left,
                    "arrangement": arrangement_id,
                    "occurrence": ids["occurrence"],
                    "key": ids["line_key"],
                    "start": _START,
                    "end": _END,
                    "contracted": contracted,
                    "approved": approved,
                    "foregone": foregone,
                    "idempotency": f"grant-{uuid.uuid4().hex}",
                },
            )
    engine.dispose()


def test_a_recorded_grant_is_append_only(
    subscriptions_scratch: tuple[str, str, str],
) -> None:
    admin_url, _, _ = subscriptions_scratch
    left, _ = _make_tenants(admin_url)
    ids = _seed_tenant_line(admin_url, left)
    grant_id = uuid.uuid4()
    engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with engine.connect() as conn:
        arrangement_id = _approve(conn, left, ids)
        conn.execute(
            text(_GRANT_INSERT),
            {
                "id": grant_id,
                "tenant": left,
                "arrangement": arrangement_id,
                "occurrence": ids["occurrence"],
                "key": ids["line_key"],
                "start": _START,
                "end": _END,
                "contracted": 100,
                "approved": 100,
                "foregone": 100,
                "idempotency": f"grant-{uuid.uuid4().hex}",
            },
        )
        with pytest.raises(DBAPIError, match="immutable"):
            conn.execute(
                text(
                    "UPDATE mod_subscriptions.subscription_billing_grants "
                    "SET foregone_amount = 1 WHERE id = :id"
                ),
                {"id": grant_id},
            )
        with pytest.raises(DBAPIError, match="immutable"):
            conn.execute(
                text(
                    "DELETE FROM mod_subscriptions.subscription_billing_grants "
                    "WHERE id = :id"
                ),
                {"id": grant_id},
            )
    engine.dispose()


def test_commercial_terms_cannot_change_while_a_treatment_is_open(
    subscriptions_scratch: tuple[str, str, str],
) -> None:
    """The product-neutral port of Sub's `protect_..._treatment_terms` trigger.

    A new contract version is the ONLY way the module can change a price,
    cadence or offer version, because `su_0001` already freezes a version's
    content. So refusing that insert while an approval is open is exactly Sub's
    invariant: revoke, change the contract, and approve again.
    """
    admin_url, _, _ = subscriptions_scratch
    left, _ = _make_tenants(admin_url)
    ids = _seed_tenant_line(admin_url, left)
    engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with engine.connect() as conn:
        # OPEN relative to the database clock, not to a calendar date. The
        # trigger protects only an active arrangement whose `ends_at` is after
        # CURRENT_TIMESTAMP, so the shared fixed window (`_END` = 2026-10-01)
        # made this test pass until that date and fail after it, on every
        # branch, with no code change. Grants elsewhere keep the fixed window.
        arrangement_id = _approve(
            conn, left, ids, end=datetime.now(UTC) + timedelta(days=365)
        )
        with pytest.raises(DBAPIError, match="revoke the open billing treatment"):
            conn.execute(
                text(_NEXT_CONTRACT_VERSION_INSERT),
                {
                    "id": uuid.uuid4(),
                    "tenant": left,
                    "contract": ids["contract"],
                    "start": datetime(2026, 10, 1, tzinfo=UTC),
                    "key": f"seed-{uuid.uuid4().hex}",
                },
            )
        conn.execute(
            text(
                "UPDATE mod_subscriptions.subscription_billing_arrangements "
                "SET status = 'revoked', revoked_by = 'finance', revoked_at = now(), "
                "revocation_reason = 'plan change', "
                "revocation_command_id = gen_random_uuid(), "
                "revocation_correlation_id = gen_random_uuid(), "
                "revocation_idempotency_key = 'rev-2' WHERE id = :id"
            ),
            {"id": arrangement_id},
        )
        conn.execute(
            text(_NEXT_CONTRACT_VERSION_INSERT),
            {
                "id": uuid.uuid4(),
                "tenant": left,
                "contract": ids["contract"],
                "start": datetime(2026, 10, 1, tzinfo=UTC),
                "key": f"seed-{uuid.uuid4().hex}",
            },
        )
    engine.dispose()


def test_the_term_freeze_canary_is_sensitive_to_the_trigger(
    subscriptions_scratch: tuple[str, str, str],
) -> None:
    """A check over a table nobody can write to would pass for the wrong reason."""
    admin_url, _, _ = subscriptions_scratch
    left, _ = _make_tenants(admin_url)
    ids = _seed_tenant_line(admin_url, left)
    engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with engine.connect() as conn:
        _approve(conn, left, ids)
        conn.execute(
            text(
                "DROP TRIGGER contract_versions_treatment_term_freeze "
                "ON mod_subscriptions.subscription_contract_versions"
            )
        )
        conn.execute(
            text(_NEXT_CONTRACT_VERSION_INSERT),
            {
                "id": uuid.uuid4(),
                "tenant": left,
                "contract": ids["contract"],
                "start": datetime(2026, 10, 1, tzinfo=UTC),
                "key": f"seed-{uuid.uuid4().hex}",
            },
        )
    engine.dispose()
