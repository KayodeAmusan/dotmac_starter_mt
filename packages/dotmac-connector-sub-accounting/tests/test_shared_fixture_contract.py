"""Contract test: ``map_item`` against Sub's own real, shared fixture.

``tests/fixtures/shared_invoice_accounting_sync_v2_sample.json`` is copied
verbatim from dotmac_sub's `tests/fixtures/invoice_accounting_sync_v2_sample.json`
at commit ``d67d9d968`` (branch ``feat/invoice-accounting-sync-canonical-digest``).
It is Sub's own canonical-digest fixture — a realistic 2-line, discounted,
BLOCKED-disposition invoice whose embedded ``projection_digest`` is Sub's
real, independently-verified-twice hardcoded oracle value, not something
this repo computes. If Sub's fixture is ever updated, this copy must be
updated to match, by hand — dotmac_sub and this connector are independent
git repositories with no shared build/dependency graph or cross-repo CI job;
consistency is enforced by this provenance note plus each repo's own test
suite, not by a shared file.

This test is deliberately separate from ``test_mapping.py``: it exists to
catch field-name drift in ``mapping.py`` against REAL Sub data, not just
synthetic connector-only fixtures.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from dotmac_connector_sub_accounting.mapping import map_item
from dotmac_integration import (
    ProductObservationSource,
    ProductRequest,
    product_observation_document,
)

FIXTURE_PATH = (
    Path(__file__).parent / "fixtures" / "shared_invoice_accounting_sync_v2_sample.json"
)
GOLDEN_DOCUMENT_PATH = (
    Path(__file__).parent / "fixtures" / "shared_invoice_product_observation_v1.json"
)


def _canonical_json(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


@dataclass(frozen=True, slots=True)
class _FixtureScope:
    kind: str
    ref: str


@dataclass(frozen=True, slots=True)
class _FixtureDestination:
    capability_binding_id: UUID
    capability_id: str
    application: str
    scope: _FixtureScope
    contract_version: int
    destination_revision_id: UUID


def test_maps_subs_real_shared_fixture_without_error() -> None:
    raw = json.loads(FIXTURE_PATH.read_text())

    event, _, _ = map_item(raw)

    assert event.payload["source_invoice_id"] == "11111111-1111-1111-1111-111111111111"
    assert event.payload["source_account_id"] == "22222222-2222-2222-2222-222222222222"
    # Sub's exact string, preserved unreformatted -- not normalized to
    # `+00:00`.
    assert event.payload["source_updated_at"] == "2026-01-15T10:30:00Z"
    assert event.payload["source_kind"] == "native"
    assert event.payload["disposition"] == "blocked"
    assert event.payload["source_total_amount"] == "147000.00"
    assert event.payload["source_currency"] == "NGN"
    assert event.payload["source_issued_at"] == "2026-01-15T10:30:00Z"
    assert event.payload["source_due_at"] == "2026-02-14T10:30:00Z"

    # The fixture's single issue has `line_id: null` and
    # `expected_amount: null` -- a header-level "discount has nowhere to
    # allocate" issue with no specific line and no "expected" amount, only
    # an actual one. Both are OMITTED keys, not present with value `None`.
    assert event.payload["issues"] == [
        {"code": "discount_allocation_undefined", "actual_amount": "10000.00"}
    ]
    assert "source_line_id" not in event.payload["issues"][0]
    assert "expected_amount" not in event.payload["issues"][0]

    # The single most important assertion: the connector forwards Sub's own
    # real digest byte-identical, unrecomputed.
    assert event.payload["digest_version"] == 1
    assert (
        event.payload["projection_digest"]
        == "0dfecf2e1f96a2d1a63eb8e5e9f78f0aefbf661ab2c424b841b5bb2eda85aa7c"
    )


def test_real_fixture_uses_generic_product_observation_wire_builder() -> None:
    assert hashlib.sha256(GOLDEN_DOCUMENT_PATH.read_bytes()).hexdigest() == (
        "dec305d41b87d34563198faf4fd110f5884da3314ca8afa33770d014262ec038"
    )
    raw = json.loads(FIXTURE_PATH.read_text())
    event, _, _ = map_item(raw)
    destination = _FixtureDestination(
        capability_binding_id=UUID("bbbbbbbb-2222-4222-8222-222222222222"),
        capability_id="invoices.accounting_sync.observation.v1",
        application="erp",
        scope=_FixtureScope(kind="organization", ref="shared-fixture-org"),
        contract_version=1,
        destination_revision_id=UUID("aaaaaaaa-1111-4111-8111-111111111111"),
    )
    request = ProductRequest(
        destination=destination,
        source=ProductObservationSource(
            installation_id=UUID("cccccccc-3333-4333-8333-333333333333"),
            connector_key="sub_accounting",
        ),
        contract_version=1,
        idempotency_key="receipt:fixture",
        request_fingerprint="fixture-fingerprint",
        correlation_id="fixture-correlation",
        receipt_id=UUID("dddddddd-dddd-dddd-dddd-dddddddddddd"),
        provider_event_id=event.provider_event_id,
        event_type=event.event_type,
        observation=event.payload,
    )

    expected = json.loads(GOLDEN_DOCUMENT_PATH.read_text())
    assert _canonical_json(product_observation_document(request)) == _canonical_json(
        expected
    )
