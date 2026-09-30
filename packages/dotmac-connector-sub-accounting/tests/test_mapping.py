"""``map_item`` — translation, disposition/issues consistency, digest forwarding."""

from __future__ import annotations

import pytest
from dotmac_connector_sub_accounting.mapping import (
    CAPABILITY_ID,
    CONTRACT_VERSION,
    SubAccountingMappingError,
    map_item,
)

INVOICE_ID = "11111111-1111-1111-1111-111111111111"
ACCOUNT_ID = "22222222-2222-2222-2222-222222222222"
LINE_ID = "33333333-3333-3333-3333-333333333333"

#: A real, known-good digest from dotmac_sub's own fixture data for this same
#: initiative (Sub computes it; this connector only validates and forwards).
VALID_PROJECTION_DIGEST = (
    "0dfecf2e1f96a2d1a63eb8e5e9f78f0aefbf661ab2c424b841b5bb2eda85aa7c"
)


def _item(**overrides: object) -> dict[str, object]:
    # Field names match Sub's real `InvoiceAccountingSyncRead`
    # (dotmac_sub/app/schemas/billing.py:334), verified by direct cross-repo
    # read — not the `id`/`status`/`total_amount` this fixture used before,
    # which matched the (buggy) mapper rather than Sub's actual wire shape.
    base: dict[str, object] = {
        "source_invoice_id": INVOICE_ID,
        "account_id": ACCOUNT_ID,
        "contract_version": CONTRACT_VERSION,
        "source_kind": "native",
        "updated_at": "2026-09-01T00:00:00+00:00",
        "disposition": "ready",
        "total": "100.00",
        "currency": "ngn",
        "issues": [],
        "digest_version": 1,
        "projection_digest": VALID_PROJECTION_DIGEST,
    }
    base.update(overrides)
    return base


def _blocked_issue(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "code": "amount_mismatch",
        "line_id": LINE_ID,
        "expected_amount": "50.00",
        "actual_amount": "40.00",
    }
    base.update(overrides)
    return base


# -- happy path ---------------------------------------------------------------


def test_maps_a_ready_item_with_no_issues() -> None:
    event, updated_at, invoice_id = map_item(_item())

    assert invoice_id == INVOICE_ID
    assert updated_at.isoformat() == "2026-09-01T00:00:00+00:00"
    assert event.event_type == CAPABILITY_ID
    assert event.payload["capability_id"] == CAPABILITY_ID
    assert event.payload["source_invoice_id"] == INVOICE_ID
    assert event.payload["source_account_id"] == ACCOUNT_ID
    assert event.payload["source_updated_at"] == "2026-09-01T00:00:00+00:00"
    assert event.payload["source_kind"] == "native"
    assert event.payload["disposition"] == "ready"
    assert event.payload["source_total_amount"] == "100.00"
    assert event.payload["source_currency"] == "NGN"
    assert event.payload["issues"] == []
    assert "organization_id" not in event.payload
    assert "idempotency_key" not in event.payload
    assert "source_issued_at" not in event.payload
    assert "source_due_at" not in event.payload
    assert event.payload["digest_version"] == 1
    assert event.payload["projection_digest"] == VALID_PROJECTION_DIGEST


def test_maps_a_blocked_item_and_renames_line_id_to_source_line_id() -> None:
    event, _, _ = map_item(_item(disposition="blocked", issues=[_blocked_issue()]))

    assert event.payload["issues"] == [
        {
            "code": "amount_mismatch",
            "source_line_id": LINE_ID,
            "expected_amount": "50.00",
            "actual_amount": "40.00",
        }
    ]
    assert "line_id" not in event.payload["issues"][0]


def test_optional_dates_pass_through_when_present() -> None:
    event, _, _ = map_item(
        _item(issued_at="2026-08-01T00:00:00Z", due_at="2026-09-15T00:00:00Z")
    )
    assert event.payload["source_issued_at"] == "2026-08-01T00:00:00Z"
    assert event.payload["source_due_at"] == "2026-09-15T00:00:00Z"


# -- disposition/issues consistency -------------------------------------------


def test_rejects_blocked_disposition_with_no_issues() -> None:
    with pytest.raises(SubAccountingMappingError, match="no issues"):
        map_item(_item(disposition="blocked", issues=[]))


def test_rejects_non_blocked_disposition_with_issues() -> None:
    with pytest.raises(SubAccountingMappingError, match="carries issues"):
        map_item(_item(disposition="ready", issues=[_blocked_issue()]))


# -- contract version and identity --------------------------------------------


def test_rejects_unsupported_contract_version() -> None:
    with pytest.raises(SubAccountingMappingError, match="contract_version"):
        map_item(_item(contract_version="invoice-accounting-sync.v1"))


def test_rejects_invalid_invoice_id() -> None:
    with pytest.raises(SubAccountingMappingError, match="id is not a valid UUID"):
        map_item(_item(source_invoice_id="not-a-uuid"))


def test_rejects_invalid_account_id() -> None:
    with pytest.raises(SubAccountingMappingError, match="account_id"):
        map_item(_item(account_id="not-a-uuid"))


def test_preserves_the_exact_uuid_string_sub_sent() -> None:
    # Validated, never reformatted -- required so the next poll's cursor can
    # echo the exact value back to Sub.
    mixed_case = "11111111-AAAA-1111-1111-111111111111"
    event, _, invoice_id = map_item(_item(source_invoice_id=mixed_case))
    assert event.payload["source_invoice_id"] == mixed_case
    assert invoice_id == mixed_case


# -- timestamps -----------------------------------------------------------


def test_rejects_a_naive_updated_at() -> None:
    with pytest.raises(SubAccountingMappingError, match="timezone"):
        map_item(_item(updated_at="2026-09-01T00:00:00"))


def test_rejects_a_malformed_updated_at() -> None:
    with pytest.raises(SubAccountingMappingError, match="updated_at"):
        map_item(_item(updated_at="not-a-timestamp"))


def test_rejects_a_naive_optional_date() -> None:
    with pytest.raises(SubAccountingMappingError, match="issued_at"):
        map_item(_item(issued_at="2026-08-01T00:00:00"))


# -- money and issues shape ----------------------------------------------


def test_rejects_missing_header_money_fields() -> None:
    with pytest.raises(SubAccountingMappingError, match="money"):
        map_item(_item(total=None))


def test_rejects_an_invalid_currency() -> None:
    with pytest.raises(SubAccountingMappingError, match="money"):
        map_item(_item(currency="not-a-currency"))


def test_rejects_an_issue_entry_missing_its_code() -> None:
    # `code` is the only genuinely required field on an issue entry.
    with pytest.raises(SubAccountingMappingError, match="issue entry"):
        map_item(
            _item(
                disposition="blocked",
                issues=[{"line_id": "line-1", "actual_amount": "10.00"}],
            )
        )


def test_accepts_an_issue_entry_with_missing_optional_fields() -> None:
    # Sub's real `InvoiceAccountingSyncIssueRead` declares `line_id`,
    # `expected_amount`, and `actual_amount` as all genuinely optional (e.g.
    # a header-level discount-allocation issue has no specific line and no
    # "expected" amount) -- a missing (or null) optional field is omitted
    # from the mapped dict, not rejected.
    event, _, _ = map_item(
        _item(
            disposition="blocked",
            issues=[{"code": "x", "line_id": None, "expected_amount": None}],
        )
    )
    assert event.payload["issues"] == [{"code": "x"}]
    assert "source_line_id" not in event.payload["issues"][0]
    assert "expected_amount" not in event.payload["issues"][0]
    assert "actual_amount" not in event.payload["issues"][0]


def test_accepts_an_issue_entry_shaped_like_the_shared_fixtures_real_issue() -> None:
    # code present; line_id/expected_amount absent; actual_amount present --
    # exactly the shape of the shared Sub fixture's real issue entry.
    event, _, _ = map_item(
        _item(
            disposition="blocked",
            issues=[
                {"code": "discount_allocation_undefined", "actual_amount": "10000.00"}
            ],
        )
    )
    assert event.payload["issues"] == [
        {"code": "discount_allocation_undefined", "actual_amount": "10000.00"}
    ]
    assert "source_line_id" not in event.payload["issues"][0]
    assert "expected_amount" not in event.payload["issues"][0]


def test_rejects_an_issue_entry_with_a_present_but_malformed_line_id() -> None:
    # "missing" and "present but invalid" are different outcomes -- a
    # present, non-null, non-UUID line_id is rejected rather than passed
    # through as an opaque string.
    with pytest.raises(SubAccountingMappingError, match="source_line_id"):
        map_item(
            _item(
                disposition="blocked",
                issues=[
                    {"code": "x", "line_id": "not-a-uuid", "actual_amount": "10.00"}
                ],
            )
        )


def test_rejects_an_issue_entry_with_a_present_but_malformed_expected_amount() -> None:
    # "missing" and "present but invalid" are different outcomes -- a
    # present, non-null, unparseable value is still rejected.
    with pytest.raises(SubAccountingMappingError, match="expected_amount"):
        map_item(
            _item(
                disposition="blocked",
                issues=[
                    {
                        "code": "x",
                        "expected_amount": "not-a-number",
                        "actual_amount": "10.00",
                    }
                ],
            )
        )


def test_rejects_an_issue_entry_with_a_present_but_malformed_actual_amount() -> None:
    with pytest.raises(SubAccountingMappingError, match="actual_amount"):
        map_item(
            _item(
                disposition="blocked",
                issues=[{"code": "x", "actual_amount": "not-a-number"}],
            )
        )


def test_rejects_issues_that_is_not_a_list() -> None:
    with pytest.raises(SubAccountingMappingError, match="issues is not a list"):
        map_item(_item(issues={"code": "x"}))


# -- digest_version / projection_digest: forwarded verbatim, never computed --


def test_forwards_digest_version_and_projection_digest_unchanged() -> None:
    raw = _item(digest_version=7, projection_digest=VALID_PROJECTION_DIGEST)
    event, _, _ = map_item(raw)
    assert event.payload["digest_version"] == 7
    assert event.payload["projection_digest"] == VALID_PROJECTION_DIGEST


@pytest.mark.parametrize(
    "digest_version",
    [0, -1, 1.0, True, False, None],
)
def test_rejects_a_malformed_digest_version(digest_version: object) -> None:
    with pytest.raises(SubAccountingMappingError, match="digest_version"):
        map_item(_item(digest_version=digest_version))


def test_rejects_a_missing_digest_version() -> None:
    raw = _item()
    del raw["digest_version"]
    with pytest.raises(SubAccountingMappingError, match="digest_version"):
        map_item(raw)


@pytest.mark.parametrize(
    "projection_digest",
    [
        "a" * 63,  # too short
        "a" * 65,  # too long
        "A" * 64,  # uppercase
        "g" * 64,  # non-hex character
        "",
        None,
        123,
    ],
)
def test_rejects_a_malformed_projection_digest(projection_digest: object) -> None:
    with pytest.raises(SubAccountingMappingError, match="projection_digest"):
        map_item(_item(projection_digest=projection_digest))


def test_rejects_a_missing_projection_digest() -> None:
    raw = _item()
    del raw["projection_digest"]
    with pytest.raises(SubAccountingMappingError, match="projection_digest"):
        map_item(raw)
