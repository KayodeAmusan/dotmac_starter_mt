"""Traccar remains a stateless provider adapter, never a Fleet owner."""

from __future__ import annotations

import ast
import tomllib
from pathlib import Path

import dotmac_connector_traccar
from dotmac_connector_traccar import MANIFEST

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PACKAGE = PROJECT_ROOT / "packages" / "dotmac-connector-traccar"
SOURCE = PACKAGE / "src" / "dotmac_connector_traccar"


def _imports() -> set[str]:
    roots: set[str] = set()
    for path in SOURCE.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                roots.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                roots.add(node.module.split(".")[0])
    return roots


def test_connector_version_is_one_fact_on_every_public_surface() -> None:
    declared = tomllib.loads((PACKAGE / "pyproject.toml").read_text(encoding="utf-8"))
    version = declared["tool"]["poetry"]["version"]
    assert version == dotmac_connector_traccar.__version__ == MANIFEST.version


def test_connector_imports_only_the_spi_among_dotmac_packages() -> None:
    internal = {name for name in _imports() if name.startswith("dotmac_")}
    assert internal - {"dotmac_connector_traccar"} == {"dotmac_integration"}


def test_connector_owns_http_but_no_persistence_scheduler_or_retry_engine() -> None:
    assert "httpx" in _imports()
    forbidden = {
        "alembic",
        "apscheduler",
        "asyncpg",
        "backoff",
        "celery",
        "psycopg",
        "sqlalchemy",
        "tenacity",
    }
    assert not (_imports() & forbidden)


def test_connector_has_no_product_authority_or_direct_secret_source() -> None:
    source = "\n".join(
        path.read_text(encoding="utf-8") for path in sorted(SOURCE.rglob("*.py"))
    ).lower()
    for forbidden in (
        "tenant_id",
        "organization_id",
        "vehicletracker",
        "fleet:tracking:read",
        "openbao",
        "bao://",
        "secret/data/",
        "retry_delay",
        "backoff_seconds",
    ):
        assert forbidden not in source


def test_connector_exposes_no_arbitrary_provider_passthrough() -> None:
    source = (SOURCE / "query.py").read_text(encoding="utf-8")
    assert 'request.payload.get("path")' not in source
    assert 'request.payload.get("method")' not in source
    assert 'request.payload.get("url")' not in source
    assert source.count('"/api/devices"') == 1
    assert source.count('"/api/positions"') == 2
    assert source.count('"/api/server"') == 1


def test_dossier_records_greenfield_inventory_and_no_adoption_claim() -> None:
    dossier = tomllib.loads((PACKAGE / "EXTRACTION.toml").read_text(encoding="utf-8"))
    assert dossier["source_mode"] == "greenfield-after-inventory"
    assert dossier["source_paths"]
    assert all("@" in item and ":" in item for item in dossier["source_paths"])
    assert dossier["contract_consumers"] == []
    assert dossier["status"] == "audit-complete"
