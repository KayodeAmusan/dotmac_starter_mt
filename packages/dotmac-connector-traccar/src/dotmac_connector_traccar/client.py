"""Traccar HTTP/session transport isolated by Integrator connection reference."""

from __future__ import annotations

import hashlib
import threading
from collections import OrderedDict
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Final
from urllib.parse import urlsplit

import httpx
from dotmac_integration.spi import QueryStatus

ORIGIN: Final = "http://traccar:8082"
SERVICE_EMAIL: Final = "service_email"
SERVICE_PASSWORD_BINDING: Final = "service_password"
MAX_SESSIONS: Final = 64


class TraccarFailure(RuntimeError):
    """A value-free normalized failure safe to cross the connector boundary."""

    def __init__(self, status: QueryStatus) -> None:
        self.status = status
        super().__init__(status.value)


@dataclass(frozen=True, slots=True)
class TraccarConfig:
    base_url: str
    connect_timeout_seconds: float
    read_timeout_seconds: float


def parse_config(value: Mapping[str, object]) -> TraccarConfig:
    base_url = value.get("base_url")
    connect = value.get("connect_timeout_seconds")
    read = value.get("read_timeout_seconds")
    if base_url != ORIGIN:
        raise TraccarFailure(QueryStatus.INVALID_QUERY)
    parsed = urlsplit(base_url)
    if (
        parsed.scheme != "http"
        or parsed.hostname != "traccar"
        or parsed.port != 8082
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise TraccarFailure(QueryStatus.INVALID_QUERY)
    for timeout in (connect, read):
        if (
            isinstance(timeout, bool)
            or not isinstance(timeout, int | float)
            or not 0.1 <= float(timeout) <= 60.0
        ):
            raise TraccarFailure(QueryStatus.INVALID_QUERY)
    return TraccarConfig(base_url, float(connect), float(read))


def parse_material(value: Mapping[str, object]) -> tuple[str, str]:
    email = value.get(SERVICE_EMAIL)
    password = value.get(SERVICE_PASSWORD_BINDING)
    if (
        not isinstance(email, str)
        or not email
        or not isinstance(password, str)
        or not password
    ):
        raise TraccarFailure(QueryStatus.INVALID_QUERY)
    return email, password


def _fingerprint(email: str, password: str) -> bytes:
    digest = hashlib.sha256()
    digest.update(email.encode("utf-8"))
    digest.update(b"\0")
    digest.update(password.encode("utf-8"))
    return digest.digest()


@dataclass(slots=True, repr=False)
class _ProviderSession:
    client: httpx.Client
    config: TraccarConfig
    material_fingerprint: bytes = field(repr=False)
    authenticated: bool = False
    lock: threading.RLock = field(default_factory=threading.RLock, repr=False)


class TraccarSessionPool:
    """A bounded process-local cookie pool; it owns no durable retry state."""

    def __init__(
        self,
        *,
        transport: httpx.BaseTransport | None = None,
        max_sessions: int = MAX_SESSIONS,
    ) -> None:
        self._transport = transport
        self._max_sessions = max_sessions
        self._sessions: OrderedDict[str, _ProviderSession] = OrderedDict()
        self._lock = threading.RLock()

    def _new(
        self, config: TraccarConfig, material_fingerprint: bytes
    ) -> _ProviderSession:
        timeout = httpx.Timeout(
            connect=config.connect_timeout_seconds,
            read=config.read_timeout_seconds,
            write=config.read_timeout_seconds,
            pool=config.connect_timeout_seconds,
        )
        return _ProviderSession(
            client=httpx.Client(
                base_url=config.base_url,
                timeout=timeout,
                transport=self._transport,
                follow_redirects=False,
                trust_env=False,
                headers={"accept": "application/json"},
            ),
            config=config,
            material_fingerprint=material_fingerprint,
        )

    def session(
        self,
        connection_ref: str,
        config: TraccarConfig,
        email: str,
        password: str,
    ) -> _ProviderSession:
        if not connection_ref or len(connection_ref) > 200:
            raise TraccarFailure(QueryStatus.INVALID_QUERY)
        fingerprint = _fingerprint(email, password)
        with self._lock:
            current = self._sessions.get(connection_ref)
            if (
                current is not None
                and current.config == config
                and current.material_fingerprint == fingerprint
            ):
                self._sessions.move_to_end(connection_ref)
                return current
            if current is not None:
                current.client.close()
                del self._sessions[connection_ref]
            while len(self._sessions) >= self._max_sessions:
                _, expired = self._sessions.popitem(last=False)
                expired.client.close()
            created = self._new(config, fingerprint)
            self._sessions[connection_ref] = created
            return created

    @staticmethod
    def _failure_for_response(response: httpx.Response) -> QueryStatus:
        if response.status_code in {401, 403}:
            return QueryStatus.UNAUTHORIZED_PROVIDER_SESSION
        if response.status_code == 404:
            return QueryStatus.NOT_FOUND
        if 300 <= response.status_code < 400:
            return QueryStatus.PROVIDER_UNAVAILABLE
        if response.status_code == 429 or response.status_code >= 500:
            return QueryStatus.PROVIDER_UNAVAILABLE
        return QueryStatus.INVALID_QUERY

    def _send(
        self,
        client: httpx.Client,
        method: str,
        path: str,
        *,
        params: dict[str, str] | None = None,
        data: dict[str, str] | None = None,
    ) -> httpx.Response:
        try:
            return client.request(method, path, params=params, data=data)
        except httpx.TimeoutException:
            raise TraccarFailure(QueryStatus.TIMEOUT) from None
        except httpx.RequestError:
            raise TraccarFailure(QueryStatus.PROVIDER_UNAVAILABLE) from None

    def _authenticate(
        self, session: _ProviderSession, email: str, password: str
    ) -> None:
        response = self._send(
            session.client,
            "POST",
            "/api/session",
            data={"email": email, "password": password},
        )
        if not 200 <= response.status_code < 300:
            raise TraccarFailure(self._failure_for_response(response))
        if not session.client.cookies.get("JSESSIONID"):
            raise TraccarFailure(QueryStatus.MALFORMED_PROVIDER_RESPONSE)
        session.authenticated = True

    def request(
        self,
        *,
        connection_ref: str,
        config: TraccarConfig,
        email: str,
        password: str,
        path: str,
        params: dict[str, str] | None = None,
    ) -> httpx.Response:
        session = self.session(connection_ref, config, email, password)
        with session.lock:
            if not session.authenticated:
                self._authenticate(session, email, password)
            response = self._send(session.client, "GET", path, params=params)
            if response.status_code in {401, 403}:
                session.client.cookies.clear()
                session.authenticated = False
                self._authenticate(session, email, password)
                response = self._send(session.client, "GET", path, params=params)
            if not 200 <= response.status_code < 300:
                raise TraccarFailure(self._failure_for_response(response))
            return response
