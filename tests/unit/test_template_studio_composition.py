"""The composition seam assembles full rendered content without rewriting it."""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest
from dotmac_template_studio import service


def _part(
    part_id: str, order: int, subject: str | None, body: str
) -> service.RenderedEmailPart:
    return service.RenderedEmailPart(
        part_id=part_id, order=order, subject=subject, body=body
    )


def test_compose_preserves_full_rendered_parts_and_declared_order() -> None:
    custom_copy = "Dear Ada,\n\nYour service is active.\nRegards, Support\n"
    receipt_copy = (
        "Dear Ada,\n\nYour receipt is ready: "
        "https://portal.example.test/receipts/r-123?view=full\nThanks, Billing"
    )
    receipt = _part("receipt-123", 20, "  Receipt R-123  ", receipt_copy)
    service_notice = _part("service-456", 10, "Service is active", custom_copy)

    result = service.compose_email(
        [receipt, service_notice], primary_part_id="receipt-123"
    )

    assert result.subject == receipt.subject
    assert result.body == custom_copy + "\n\n" + receipt_copy
    assert result.parts == (service_notice, receipt)
    assert result.primary_part_id == "receipt-123"
    assert result.parts[0].body == custom_copy
    assert result.parts[1].body == receipt_copy
    # Full templates can repeat a greeting; the content layer must not edit it.
    assert result.body.count("Dear Ada,") == 2


def test_single_part_is_returned_without_separator_or_rewrite() -> None:
    part = _part("one", 7, "Subject", "  Exact body\n")
    result = service.compose_email((part,), primary_part_id="one")
    assert result.subject == "Subject"
    assert result.body == "  Exact body\n"
    assert result.parts == (part,)


def test_result_and_source_provenance_are_immutable_snapshots() -> None:
    parts = [_part("one", 1, "Subject", "Body")]
    result = service.compose_email(parts, primary_part_id="one")
    parts.append(_part("two", 2, None, "Another body"))
    assert len(result.parts) == 1
    with pytest.raises(FrozenInstanceError):
        result.body = "changed"  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        result.parts[0].body = "changed"  # type: ignore[misc]


@pytest.mark.parametrize(
    ("parts", "primary_part_id", "error"),
    [
        ([], "one", "nonempty"),
        ([_part("one", 1, "S", "B")], "missing", "primary_part_id"),
        (
            [_part("one", 1, "S", "B"), _part("one", 2, "S", "B")],
            "one",
            "duplicate part_id",
        ),
        (
            [_part("one", 1, "S", "B"), _part("two", 1, "S", "B")],
            "one",
            "duplicate order",
        ),
        ([_part("one", 1, None, "B")], "one", "nonblank subject"),
        ([_part("one", 1, "  ", "B")], "one", "nonblank subject"),
    ],
)
def test_invalid_compositions_fail_closed(
    parts: list[service.RenderedEmailPart], primary_part_id: str, error: str
) -> None:
    with pytest.raises(ValueError, match=error):
        service.compose_email(parts, primary_part_id=primary_part_id)


@pytest.mark.parametrize(
    ("part_id", "order", "subject", "body", "error"),
    [
        (" ", 0, "S", "B", "part_id"),
        (" one ", 0, "S", "B", "part_id"),
        ("one", -1, "S", "B", "order"),
        ("one", True, "S", "B", "order"),
        ("one", 0, 123, "B", "subject"),
        ("one", 0, "S", " \n ", "body"),
    ],
)
def test_invalid_rendered_parts_fail_closed(
    part_id: str, order: int, subject: str | None, body: str, error: str
) -> None:
    with pytest.raises(ValueError, match=error):
        _part(part_id, order, subject, body)
