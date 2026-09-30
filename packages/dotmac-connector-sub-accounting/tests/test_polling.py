"""``SubAccountingPollHandler.poll`` — request shape, cursor, page validation."""

from __future__ import annotations

import json

import httpx
import pytest
from dotmac_connector_sub_accounting.mapping import CONTRACT_VERSION
from dotmac_connector_sub_accounting.plugin import SUB_API_KEY, SubAccountingConnector
from dotmac_connector_sub_accounting.polling import (
    API_HOST,
    FEED_PATH,
    SubAccountingPollError,
)
from dotmac_integration.spi import PollHandler

CAPABILITY_ID = "invoices.accounting_sync.observation.v1"
API_KEY_VALUE = "held-sub-api-key-material"


def _handler(respond) -> PollHandler:
    plugin = SubAccountingConnector(transport=httpx.MockTransport(respond))
    return plugin.poll_handler_for(CAPABILITY_ID)


def _secrets() -> dict[str, str]:
    return {SUB_API_KEY: API_KEY_VALUE}


def _item(**overrides: object) -> dict[str, object]:
    # Field names match Sub's real `InvoiceAccountingSyncRead`
    # (dotmac_sub/app/schemas/billing.py:334), verified by direct cross-repo
    # read -- not the `id`/`status`/`total_amount` this fixture used before,
    # which matched the (buggy) mapper rather than Sub's actual wire shape.
    base: dict[str, object] = {
        "source_invoice_id": "11111111-1111-1111-1111-111111111111",
        "account_id": "22222222-2222-2222-2222-222222222222",
        "contract_version": CONTRACT_VERSION,
        "source_kind": "native",
        "updated_at": "2026-09-01T00:00:00+00:00",
        "disposition": "ready",
        "total": "100.00",
        "currency": "NGN",
        "issues": [],
        "digest_version": 1,
        "projection_digest": (
            "0dfecf2e1f96a2d1a63eb8e5e9f78f0aefbf661ab2c424b841b5bb2eda85aa7c"
        ),
    }
    base.update(overrides)
    return base


def _page(items: list[dict[str, object]]) -> dict[str, object]:
    return {"items": items, "count": len(items), "limit": 100, "offset": 0}


# -- request shape -------------------------------------------------------


def test_first_poll_has_no_cursor_and_sends_only_limit() -> None:
    seen: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=_page([]))

    handler = _handler(respond)
    events, cursor = handler.poll(None, config={}, secrets=_secrets())

    assert events == ()
    assert cursor is None
    request = seen[0]
    assert request.url.host == API_HOST
    assert request.url.path == FEED_PATH
    assert dict(request.url.params) == {"limit": "100"}
    assert request.headers["x-api-key"] == API_KEY_VALUE


def test_cursor_round_trips_after_id_and_after_updated_at() -> None:
    seen: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=_page([]))

    handler = _handler(respond)
    cursor = json.dumps(
        {
            "after_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            "after_updated_at": "2026-08-31T00:00:00+00:00",
        }
    )
    handler.poll(cursor, config={}, secrets=_secrets())

    params = dict(seen[0].url.params)
    assert params["after_id"] == "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    assert params["after_updated_at"] == "2026-08-31T00:00:00+00:00"


@pytest.mark.parametrize(
    "cursor",
    [
        "not json",
        json.dumps({"after_id": "x"}),
        json.dumps({"after_updated_at": "2026-08-31T00:00:00+00:00"}),
        json.dumps(
            {
                "after_id": "x",
                "after_updated_at": "2026-08-31T00:00:00+00:00",
                "extra": "y",
            }
        ),
        json.dumps({"after_id": "", "after_updated_at": "2026-08-31T00:00:00+00:00"}),
        json.dumps([1, 2]),
    ],
)
def test_a_malformed_or_partial_cursor_is_a_connector_internal_error(
    cursor: str,
) -> None:
    handler = _handler(lambda request: httpx.Response(200, json=_page([])))
    with pytest.raises(SubAccountingPollError):
        handler.poll(cursor, config={}, secrets=_secrets())


def test_updated_since_sent_only_when_configured() -> None:
    seen: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=_page([]))

    handler = _handler(respond)
    handler.poll(None, config={}, secrets=_secrets())
    assert "updated_since" not in dict(seen[0].url.params)

    handler.poll(
        None,
        config={"updated_since": "2026-08-01T00:00:00Z"},
        secrets=_secrets(),
    )
    assert dict(seen[1].url.params)["updated_since"] == "2026-08-01T00:00:00Z"


@pytest.mark.parametrize("limit", [0, -1, 501, 5000])
def test_limit_out_of_range_is_rejected(limit: int) -> None:
    handler = _handler(lambda request: httpx.Response(200, json=_page([])))
    with pytest.raises(SubAccountingPollError, match="limit"):
        handler.poll(None, config={"limit": limit}, secrets=_secrets())


def test_max_page_size_is_sent_verbatim() -> None:
    seen: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=_page([]))

    handler = _handler(respond)
    handler.poll(None, config={"limit": 500}, secrets=_secrets())
    assert dict(seen[0].url.params)["limit"] == "500"


def test_missing_material_is_rejected() -> None:
    handler = _handler(lambda request: httpx.Response(200, json=_page([])))
    with pytest.raises(SubAccountingPollError, match="material"):
        handler.poll(None, config={}, secrets={})


# -- empty page conventions ------------------------------------------------


def test_empty_initial_page_returns_no_events_and_none_cursor() -> None:
    handler = _handler(lambda request: httpx.Response(200, json=_page([])))
    events, cursor = handler.poll(None, config={}, secrets=_secrets())
    assert events == ()
    assert cursor is None


def test_empty_subsequent_page_leaves_the_cursor_unchanged() -> None:
    handler = _handler(lambda request: httpx.Response(200, json=_page([])))
    prior_cursor = json.dumps(
        {
            "after_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            "after_updated_at": "2026-08-31T00:00:00+00:00",
        }
    )
    events, cursor = handler.poll(prior_cursor, config={}, secrets=_secrets())
    assert events == ()
    assert cursor == prior_cursor


# -- multi-page advancement and ordering --------------------------------------


def test_multi_page_advancement_uses_the_final_items_position() -> None:
    first = _item(
        source_invoice_id="11111111-1111-1111-1111-111111111111",
        updated_at="2026-09-01T00:00:00+00:00",
    )
    second = _item(
        source_invoice_id="33333333-3333-3333-3333-333333333333",
        updated_at="2026-09-01T00:00:01+00:00",
    )
    handler = _handler(lambda request: httpx.Response(200, json=_page([first, second])))
    events, cursor = handler.poll(None, config={}, secrets=_secrets())
    assert len(events) == 2
    # A multi-item page always yields a real cursor string; narrows the type
    # for mypy without changing runtime behavior.
    assert cursor is not None
    assert json.loads(cursor) == {
        "after_id": "33333333-3333-3333-3333-333333333333",
        "after_updated_at": "2026-09-01T00:00:01+00:00",
    }


def test_tied_timestamp_ordering_by_invoice_id_is_accepted() -> None:
    same_timestamp = "2026-09-01T00:00:00+00:00"
    first = _item(
        source_invoice_id="11111111-1111-1111-1111-111111111111",
        updated_at=same_timestamp,
    )
    second = _item(
        source_invoice_id="99999999-9999-9999-9999-999999999999",
        updated_at=same_timestamp,
    )
    handler = _handler(lambda request: httpx.Response(200, json=_page([first, second])))
    events, cursor = handler.poll(None, config={}, secrets=_secrets())
    assert len(events) == 2
    # A multi-item page always yields a real cursor string; narrows the type
    # for mypy without changing runtime behavior.
    assert cursor is not None
    assert json.loads(cursor)["after_id"] == "99999999-9999-9999-9999-999999999999"


def test_non_monotonic_page_is_refused_not_silently_accepted() -> None:
    later = _item(
        source_invoice_id="99999999-9999-9999-9999-999999999999",
        updated_at="2026-09-01T00:00:01+00:00",
    )
    earlier = _item(
        source_invoice_id="11111111-1111-1111-1111-111111111111",
        updated_at="2026-09-01T00:00:00+00:00",
    )
    handler = _handler(
        lambda request: httpx.Response(200, json=_page([later, earlier]))
    )
    with pytest.raises(SubAccountingPollError, match="strictly increasing"):
        handler.poll(None, config={}, secrets=_secrets())


def test_a_repeated_tied_position_is_refused() -> None:
    same = _item()
    handler = _handler(lambda request: httpx.Response(200, json=_page([same, same])))
    with pytest.raises(SubAccountingPollError, match="strictly increasing"):
        handler.poll(None, config={}, secrets=_secrets())


# -- provider error handling ---------------------------------------------


@pytest.mark.parametrize("status", [401, 403])
def test_authentication_rejected_is_classified(status: int) -> None:
    handler = _handler(lambda request: httpx.Response(status, json={}))
    with pytest.raises(SubAccountingPollError, match="authentication_rejected"):
        handler.poll(None, config={}, secrets=_secrets())


def test_rate_limited_is_classified() -> None:
    handler = _handler(lambda request: httpx.Response(429, json={}))
    with pytest.raises(SubAccountingPollError, match="rate_limited"):
        handler.poll(None, config={}, secrets=_secrets())


def test_other_server_errors_are_a_generic_provider_failure() -> None:
    handler = _handler(lambda request: httpx.Response(500, json={}))
    with pytest.raises(SubAccountingPollError, match="provider_request_failed"):
        handler.poll(None, config={}, secrets=_secrets())


def test_malformed_json_body_is_refused() -> None:
    handler = _handler(lambda request: httpx.Response(200, content=b"not json at all"))
    with pytest.raises(SubAccountingPollError, match="not JSON"):
        handler.poll(None, config={}, secrets=_secrets())


def test_missing_items_key_is_refused() -> None:
    handler = _handler(lambda request: httpx.Response(200, json={"count": 0}))
    with pytest.raises(SubAccountingPollError, match="page is invalid"):
        handler.poll(None, config={}, secrets=_secrets())


def test_a_malformed_item_in_the_page_is_refused() -> None:
    handler = _handler(
        lambda request: httpx.Response(
            200, json=_page([_item(contract_version="wrong-version")])
        )
    )
    with pytest.raises(SubAccountingPollError, match="provider item is invalid"):
        handler.poll(None, config={}, secrets=_secrets())


def test_a_non_object_item_in_the_page_is_refused() -> None:
    bad_page = _page(["not-an-object"])  # type: ignore[list-item]
    handler = _handler(lambda request: httpx.Response(200, json=bad_page))
    with pytest.raises(SubAccountingPollError, match="not an object"):
        handler.poll(None, config={}, secrets=_secrets())


def test_a_transport_failure_is_refused() -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom", request=request)

    handler = _handler(respond)
    with pytest.raises(SubAccountingPollError, match="provider_request_failed"):
        handler.poll(None, config={}, secrets=_secrets())


def test_redirects_are_not_followed() -> None:
    # follow_redirects=False: an unexpected redirect must not be silently
    # chased. Its 3xx body is not the feed's JSON shape, so it surfaces as an
    # ordinary malformed-response refusal rather than a followed hop.
    handler = _handler(
        lambda request: httpx.Response(
            302, headers={"location": "https://elsewhere.example/"}
        )
    )
    with pytest.raises(SubAccountingPollError):
        handler.poll(None, config={}, secrets=_secrets())


def test_one_request_per_poll_call() -> None:
    seen: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=_page([]))

    handler = _handler(respond)
    handler.poll(None, config={}, secrets=_secrets())
    assert len(seen) == 1


# -- secret hygiene --------------------------------------------------------


def test_the_api_key_value_never_appears_in_a_raised_error() -> None:
    handler = _handler(lambda request: httpx.Response(401, json={}))
    with pytest.raises(SubAccountingPollError) as excinfo:
        handler.poll(None, config={}, secrets=_secrets())
    assert API_KEY_VALUE not in str(excinfo.value)
    assert API_KEY_VALUE not in repr(excinfo.value)
