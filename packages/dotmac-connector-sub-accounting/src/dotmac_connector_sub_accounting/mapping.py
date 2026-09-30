"""Sub invoice-accounting-sync feed item -> normalized source-only observation.

This connector's job stops at producing a normalized :class:`InboundEvent`
carrying only SOURCE-DERIVED fields. It never includes ``organization_id`` or
an ``idempotency_key``-shaped field — those are supplied downstream by the
generic Integration engine and the destination-specific ``ObservationPortClient``,
which know the binding's configured destination org and mint the delivery
idempotency key. Mapping Sub's ``account_id`` onto ERP's ``organization_id``
would conflate two different systems' identifiers and is exactly the
"provider metadata selects destination scope" anti-pattern this fleet's
architecture forbids.

## The digest — forwarded verbatim, never recomputed

Sub now computes and publishes ``digest_version`` (a positive int) and
``projection_digest`` (a 64-lowercase-hex SHA-256 digest) on its own feed
item. This module's only job for those two fields is to validate their wire
shape — a positive, non-boolean int for the version; exactly
``[0-9a-f]{64}`` for the digest — and forward both verbatim into the
observation payload. It never recomputes, canonicalizes, or reinterprets
Sub's digest; a mismatch anywhere downstream now means a real transport or
mapping bug, not an expected reconciliation gap.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Final

from dotmac_integration.spi import InboundEvent

#: Duplicated (not imported) from ``plugin.py`` by design, mirroring how
#: existing connectors (e.g. ``dotmac_connector_paystack``) keep each
#: module's own copy of small identity constants rather than adding a
#: cross-module import for a single string.
CAPABILITY_ID: Final = "invoices.accounting_sync.observation.v1"
CONNECTOR_KEY: Final = "sub_accounting"

#: The exact contract version Sub's feed is documented (this session, not
#: verified against ``dotmac_sub``'s live schema) to publish. A mismatch is
#: refused rather than coerced.
CONTRACT_VERSION: Final = "invoice-accounting-sync.v2"

#: The one disposition token this module treats as "blocked" for the
#: disposition/issues consistency rule. Every other non-empty disposition
#: string is treated as "not blocked". The exact vocabulary Sub publishes
#: beyond "blocked" (e.g. "ready"/"not_applicable") was not confirmed from
#: this worktree — see the module docstring and the task report.
BLOCKED_DISPOSITION: Final = "blocked"

_CURRENCY_RE: Final[re.Pattern[str]] = re.compile(r"[A-Z]{3}")
_PROJECTION_DIGEST_RE: Final[re.Pattern[str]] = re.compile(r"[0-9a-f]{64}")

__all__ = [
    "BLOCKED_DISPOSITION",
    "CONTRACT_VERSION",
    "SubAccountingMappingError",
    "map_item",
]


class SubAccountingMappingError(ValueError):
    """One feed item could not be turned into a trustworthy observation."""


def _text(value: object) -> str | None:
    return value if isinstance(value, str) and value.strip() else None


def _uuid(value: object) -> str | None:
    # Validated, never reformatted: the exact string Sub sent travels
    # unchanged into the observation and, for the invoice id, back into the
    # next poll's cursor.
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        uuid.UUID(value)
    except (ValueError, AttributeError, TypeError):
        return None
    return value


def _currency(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    code = value.strip().upper()
    return code if _CURRENCY_RE.fullmatch(code) is not None else None


def _decimal(value: object) -> Decimal | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, Decimal):
        candidate = value
    elif isinstance(value, int):
        candidate = Decimal(value)
    elif isinstance(value, str) and value.strip():
        try:
            candidate = Decimal(value)
        except InvalidOperation:
            return None
    else:
        return None
    return None if candidate.is_nan() or candidate.is_infinite() else candidate


def _parse_timestamp(value: str, *, label: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise SubAccountingMappingError(f"{label} is invalid") from None
    if parsed.tzinfo is None:
        raise SubAccountingMappingError(f"{label} has no timezone")
    return parsed


def _timestamp(value: object, *, label: str) -> tuple[str, datetime]:
    """Return (exact original string, parsed tz-aware datetime)."""
    text = _text(value)
    if text is None:
        raise SubAccountingMappingError(f"{label} is invalid")
    return text, _parse_timestamp(text, label=label)


def _optional_timestamp(value: object, *, label: str) -> tuple[str, datetime] | None:
    if value is None:
        return None
    return _timestamp(value, label=label)


def _issues(value: object) -> list[dict[str, object]]:
    """Map Sub's ``line_id`` to ``source_line_id``.

    Only ``code`` is required. Sub's real ``InvoiceAccountingSyncIssueRead``
    declares ``line_id``/``expected_amount``/``actual_amount`` as genuinely
    optional (e.g. a header-level "discount has nowhere to allocate" issue
    has no specific line and no "expected" amount, only an actual one) —
    ERP's own ``InvoiceAccountingSyncIssue``/``IntegratorInvoiceSyncIssuePayload``
    schema mirrors this. A field that is missing OR explicitly ``null`` in
    the raw entry is omitted from the mapped dict entirely (matching this
    module's existing top-level convention for ``source_issued_at``/
    ``source_due_at``); a field that IS present with a non-null value that
    fails to parse is still rejected — "absent" and "present but invalid"
    are different outcomes.
    """
    if value is None:
        return []
    if not isinstance(value, list):
        raise SubAccountingMappingError("issues is not a list")
    payload_issues: list[dict[str, object]] = []
    for entry in value:
        if not isinstance(entry, Mapping):
            raise SubAccountingMappingError("issue entry is not an object")
        code = _text(entry.get("code"))
        if code is None:
            raise SubAccountingMappingError("issue entry is missing a required field")

        issue: dict[str, object] = {"code": code}

        raw_line_id = entry.get("line_id")
        if raw_line_id is not None:
            source_line_id = _uuid(raw_line_id)
            if source_line_id is None:
                raise SubAccountingMappingError(
                    "issue entry has an invalid source_line_id"
                )
            issue["source_line_id"] = source_line_id

        raw_expected_amount = entry.get("expected_amount")
        if raw_expected_amount is not None:
            expected_amount = _decimal(raw_expected_amount)
            if expected_amount is None:
                raise SubAccountingMappingError(
                    "issue entry has an invalid expected_amount"
                )
            issue["expected_amount"] = str(expected_amount)

        raw_actual_amount = entry.get("actual_amount")
        if raw_actual_amount is not None:
            actual_amount = _decimal(raw_actual_amount)
            if actual_amount is None:
                raise SubAccountingMappingError(
                    "issue entry has an invalid actual_amount"
                )
            issue["actual_amount"] = str(actual_amount)

        payload_issues.append(issue)
    return payload_issues


def _digest_version(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value if value > 0 else None


def _projection_digest(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    return value if _PROJECTION_DIGEST_RE.fullmatch(value) is not None else None


def map_item(raw: Mapping[str, object]) -> tuple[InboundEvent, datetime, str]:
    """Translate one Sub feed item into a normalized POLL observation.

    Returns the event plus ``(source_updated_at, source_invoice_id)`` as typed
    values, so the caller (``polling.py``) can enforce strictly-increasing
    page positions across the whole page — this function only ever sees one
    item and cannot compare across a page by itself.

    Raises :class:`SubAccountingMappingError` on any malformed field, an
    unsupported ``contract_version``, or a disposition/issues inconsistency
    (a blocked observation with no issues, or a non-blocked observation
    carrying issues) — mirroring ERP's own ``RecordInvoiceSyncOutcome``
    construction rule as defense in depth, not a replacement for it.
    """
    contract_version = _text(raw.get("contract_version"))
    if contract_version != CONTRACT_VERSION:
        raise SubAccountingMappingError(
            f"unsupported contract_version {contract_version!r}"
        )

    # Field names verified directly against Sub's real
    # `InvoiceAccountingSyncRead` (dotmac_sub/app/schemas/billing.py:334) this
    # round — the previous version guessed `id`/`status`/`total_amount`,
    # which do not exist on the wire (Sub sends `source_invoice_id`, a
    # dedicated `source_kind` field distinct from the invoice's own
    # lifecycle `status`, and `total`). Confirmed by direct cross-repo read,
    # not re-guessed.
    source_invoice_id = _uuid(raw.get("source_invoice_id"))
    if source_invoice_id is None:
        raise SubAccountingMappingError("source_invoice_id is not a valid UUID")

    source_account_id = _uuid(raw.get("account_id"))
    if source_account_id is None:
        raise SubAccountingMappingError("account_id is not a valid UUID")

    updated_at_text, updated_at = _timestamp(raw.get("updated_at"), label="updated_at")

    # NOT `status` — Sub's `status: InvoiceStatus` is the invoice's own
    # lifecycle state (draft/issued/paid/...), a different concept entirely.
    # `source_kind` is its own direct field with a disjoint vocabulary
    # (`native`/`splynx_legacy` — `InvoiceAccountingSyncSourceKind`).
    source_kind = _text(raw.get("source_kind"))
    if source_kind is None:
        raise SubAccountingMappingError("source_kind is missing")

    disposition = _text(raw.get("disposition"))
    if disposition is None:
        raise SubAccountingMappingError("disposition is missing")

    total_amount = _decimal(raw.get("total"))
    currency = _currency(raw.get("currency"))
    if total_amount is None or currency is None:
        raise SubAccountingMappingError("header money fields are invalid")

    issued = _optional_timestamp(raw.get("issued_at"), label="issued_at")
    due = _optional_timestamp(raw.get("due_at"), label="due_at")

    payload_issues = _issues(raw.get("issues"))

    is_blocked = disposition == BLOCKED_DISPOSITION
    if is_blocked and not payload_issues:
        raise SubAccountingMappingError("blocked disposition carries no issues")
    if not is_blocked and payload_issues:
        raise SubAccountingMappingError("non-blocked disposition carries issues")

    digest_version = _digest_version(raw.get("digest_version"))
    if digest_version is None:
        raise SubAccountingMappingError("digest_version is missing or invalid")

    projection_digest = _projection_digest(raw.get("projection_digest"))
    if projection_digest is None:
        raise SubAccountingMappingError("projection_digest is missing or malformed")

    payload: dict[str, object] = {
        "capability_id": CAPABILITY_ID,
        "contract_version": contract_version,
        "source_invoice_id": source_invoice_id,
        "source_account_id": source_account_id,
        "source_updated_at": updated_at_text,
        "source_kind": source_kind,
        "disposition": disposition,
        "source_total_amount": str(total_amount),
        "source_currency": currency,
        "issues": payload_issues,
    }
    if issued is not None:
        payload["source_issued_at"] = issued[0]
    if due is not None:
        payload["source_due_at"] = due[0]

    payload["digest_version"] = digest_version
    payload["projection_digest"] = projection_digest

    event = InboundEvent(
        provider_event_id=f"{CONNECTOR_KEY}:{source_invoice_id}:{updated_at_text}",
        event_type=CAPABILITY_ID,
        payload=payload,
    )
    return event, updated_at, source_invoice_id
