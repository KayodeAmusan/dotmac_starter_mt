"""Sub invoice-accounting-sync feed reconciliation through the engine-owned cursor.

One request per :meth:`poll` call, no internal retry or sleep — that is the
generic Integration engine's job, not this connector's. This handler only
builds the request, validates the response shape and every item, maps each
item through :mod:`dotmac_connector_sub_accounting.mapping`, and returns the
events found plus the cursor to persist next.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Final

import httpx
from dotmac_integration.spi import InboundEvent

from dotmac_connector_sub_accounting.mapping import SubAccountingMappingError, map_item

#: Sub's registered production hostname (declared in ``plugin.py``'s
#: ``EgressDeclaration`` too; duplicated here rather than cross-imported, the
#: same small-constant pattern ``dotmac_connector_paystack.polling`` uses for
#: ``API_HOST``). PRODUCTION COORDINATE — see plugin.py and CHANGELOG.md.
API_HOST: Final = "selfcare.dotmac.io"
FEED_PATH: Final = "/api/v1/invoices/accounting-sync/v2"
#: Matches the ``sub_api_key`` ``SecretBindingDeclaration`` name in
#: ``plugin.py`` — read here by its literal string, mirroring how
#: ``dotmac_connector_paystack.polling`` reads ``"api_secret_key"``.
SUB_API_KEY: Final = "sub_api_key"
DEFAULT_LIMIT: Final = 100
MAX_LIMIT: Final = 500


class SubAccountingPollError(RuntimeError):
    """One poll call could not produce a trustworthy complete page."""


def _decode_cursor(cursor: str | None) -> tuple[str | None, str | None]:
    """A cursor carries exactly ``after_id`` and ``after_updated_at``, or neither.

    A partial cursor (only one of the two keys) is a connector-internal error,
    never silently accepted — mirroring Sub's own API-level validation of the
    same pair, so this connector never even constructs an invalid request.
    """
    if cursor is None:
        return None, None
    try:
        decoded = json.loads(cursor)
    except json.JSONDecodeError:
        raise SubAccountingPollError("cursor is not valid JSON") from None
    if not isinstance(decoded, dict) or set(decoded) != {
        "after_id",
        "after_updated_at",
    }:
        raise SubAccountingPollError(
            "cursor must contain exactly after_id and after_updated_at, or neither"
        )
    after_id = decoded["after_id"]
    after_updated_at = decoded["after_updated_at"]
    if not isinstance(after_id, str) or not after_id.strip():
        raise SubAccountingPollError("cursor after_id is invalid")
    if not isinstance(after_updated_at, str) or not after_updated_at.strip():
        raise SubAccountingPollError("cursor after_updated_at is invalid")
    return after_id, after_updated_at


def _encode_cursor(after_id: str, after_updated_at: str) -> str:
    return json.dumps(
        {"after_id": after_id, "after_updated_at": after_updated_at},
        sort_keys=True,
        separators=(",", ":"),
    )


@dataclass(frozen=True, slots=True)
class SubAccountingPollHandler:
    transport: httpx.BaseTransport | None = field(default=None, repr=False)
    timeout_seconds: float = 30.0

    def poll(
        self,
        cursor: str | None,
        *,
        config: dict[str, object],
        secrets: dict[str, str],
    ) -> tuple[tuple[InboundEvent, ...], str | None]:
        limit = config.get("limit", DEFAULT_LIMIT)
        if (
            not isinstance(limit, int)
            or isinstance(limit, bool)
            or not 1 <= limit <= MAX_LIMIT
        ):
            raise SubAccountingPollError("limit is invalid")
        updated_since = config.get("updated_since")
        if updated_since is not None and (
            not isinstance(updated_since, str) or not updated_since.strip()
        ):
            raise SubAccountingPollError("updated_since is invalid")
        api_key = secrets.get(SUB_API_KEY)
        if not isinstance(api_key, str) or not api_key:
            raise SubAccountingPollError("required material is unavailable")

        after_id, after_updated_at = _decode_cursor(cursor)

        params: dict[str, str | int] = {"limit": limit}
        if after_id is not None and after_updated_at is not None:
            params["after_id"] = after_id
            params["after_updated_at"] = after_updated_at
        if updated_since is not None:
            params["updated_since"] = updated_since

        try:
            with httpx.Client(
                base_url=f"https://{API_HOST}",
                transport=self.transport,
                timeout=self.timeout_seconds,
                follow_redirects=False,
            ) as client:
                response = client.get(
                    FEED_PATH,
                    params=params,
                    headers={"X-API-Key": api_key},
                )
        except httpx.RequestError:
            raise SubAccountingPollError("provider_request_failed") from None

        if response.status_code >= 400:
            raise SubAccountingPollError(
                "authentication_rejected"
                if response.status_code in {401, 403}
                else "rate_limited"
                if response.status_code == 429
                else "provider_request_failed"
            )

        try:
            body = json.loads(response.content, parse_float=Decimal)
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise SubAccountingPollError("provider response is not JSON") from None
        if not isinstance(body, Mapping):
            raise SubAccountingPollError("provider response is not an object")
        items = body.get("items")
        if not isinstance(items, list):
            raise SubAccountingPollError("provider response page is invalid")
        for key in ("count", "limit", "offset"):
            value = body.get(key)
            if value is not None and (
                not isinstance(value, int) or isinstance(value, bool)
            ):
                raise SubAccountingPollError("provider response page is invalid")

        if not items:
            # Mirrors dotmac-connector-nira's empty-page convention: an empty
            # page (including the very first poll, cursor is None) returns no
            # events and leaves the persisted cursor exactly where it was.
            return (), cursor

        events: list[InboundEvent] = []
        last_position: tuple[datetime, str] | None = None
        for item in items:
            if not isinstance(item, Mapping):
                raise SubAccountingPollError("provider item is not an object")
            try:
                event, updated_at, invoice_id = map_item(item)
            except SubAccountingMappingError as exc:
                raise SubAccountingPollError(
                    f"provider item is invalid: {exc}"
                ) from exc
            position = (updated_at, invoice_id)
            if last_position is not None and position <= last_position:
                raise SubAccountingPollError("provider page is not strictly increasing")
            last_position = position
            events.append(event)

        final_payload = events[-1].payload
        next_cursor = _encode_cursor(
            str(final_payload["source_invoice_id"]),
            str(final_payload["source_updated_at"]),
        )
        return tuple(events), next_cursor
