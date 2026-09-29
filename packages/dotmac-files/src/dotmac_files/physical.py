"""Pure physical-file engine shared by tenant and platform persistence planes.

This module validates and hashes byte streams, builds immutable keys from an
explicit kernel ``Scope``, and performs provider actions.  It imports neither
SQLAlchemy nor ``dotmac_files.models``: tenant and platform callers therefore
exercise exactly the same admission, streaming, deletion, and boundary checks.
"""

from __future__ import annotations

import csv
import hashlib
import re
import tempfile
import zipfile
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime
from pathlib import PurePath
from typing import IO, Literal
from uuid import uuid4

from dotmac_kernel.cache import PlatformScope, Scope, TenantScope

from dotmac_files.contracts import (
    FilePolicy,
    FileState,
    InvalidFileState,
    PreparedFile,
    ProviderMismatch,
    StoredObjectRef,
    UnsafeFile,
)
from dotmac_files.providers import (
    ObjectInfo,
    ReadableObject,
    StorageBoundaryViolation,
    StorageProvider,
)

_PROVIDER_CODE = re.compile(r"^[a-z][a-z0-9_-]{1,31}$")
_SPOOL_MEMORY_LIMIT = 1_048_576
_MEDIA_BY_EXTENSION = {
    ".pdf": "application/pdf",
    ".csv": "text/csv",
    ".xls": "application/vnd.ms-excel",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
}


def _safe_filename(filename: str) -> str:
    if not filename or "\x00" in filename or len(filename) > 255:
        raise UnsafeFile("filename is empty, over 255 characters, or contains NUL")
    if PurePath(filename).name != filename or "/" in filename or "\\" in filename:
        raise UnsafeFile("filename must not contain a path")
    return filename


def _looks_like_csv(payload: bytes) -> bool:
    try:
        sample = payload[:8192].decode("utf-8-sig")
    except UnicodeDecodeError:
        return False
    if "\n" not in sample:
        return False
    try:
        csv.Sniffer().sniff(sample, delimiters=",;\t")
    except csv.Error:
        return False
    return True


def _is_xlsx(content: IO[bytes]) -> bool:
    try:
        content.seek(0)
        with zipfile.ZipFile(content) as archive:
            names = set(archive.namelist())
    except (OSError, zipfile.BadZipFile):
        return False
    finally:
        content.seek(0)
    return "[Content_Types].xml" in names and "xl/workbook.xml" in names


def _detect_media_type(content: IO[bytes]) -> str:
    content.seek(0)
    sample = content.read(8192)
    content.seek(0)
    if sample.startswith(b"%PDF-"):
        return "application/pdf"
    if sample.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if sample.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if sample.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if len(sample) >= 12 and sample.startswith(b"RIFF") and sample[8:12] == b"WEBP":
        return "image/webp"
    if sample.startswith(bytes.fromhex("D0CF11E0A1B11AE1")):
        return "application/vnd.ms-excel"
    if sample.startswith(b"PK\x03\x04") and _is_xlsx(content):
        return "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    if _looks_like_csv(sample):
        return "text/csv"
    raise UnsafeFile("file content has no supported signature")


def scope_prefix(scope: Scope) -> str:
    """Return the non-overlapping trusted object prefix for an explicit scope."""
    if isinstance(scope, TenantScope):
        return f"tenants/{scope.tenant_id}/files/"
    if isinstance(scope, PlatformScope):
        return "platform/files/"
    raise TypeError(f"unsupported file scope {type(scope).__name__}")


def validate_provider_code(code: str) -> None:
    if not _PROVIDER_CODE.fullmatch(code):
        raise ValueError("provider code must be a stable lowercase identifier")


def prepare_upload(
    provider: StorageProvider,
    *,
    scope: Scope,
    policy: FilePolicy,
    original_filename: str,
    declared_media_type: str,
    chunks: Iterable[bytes],
) -> PreparedFile:
    """Validate a stream and write it once beneath its trusted scope prefix."""
    name = _safe_filename(original_filename)
    extension = PurePath(name).suffix.lower()
    declared = declared_media_type.lower().split(";", 1)[0].strip()
    if extension not in policy.allowed_extensions:
        raise UnsafeFile(f"extension {extension!r} is not allowed")
    if declared not in policy.allowed_media_types:
        raise UnsafeFile(f"media type {declared!r} is not allowed")
    expected = _MEDIA_BY_EXTENSION.get(extension)
    if expected is None or expected != declared:
        raise UnsafeFile(
            f"extension {extension!r} does not match declared media type {declared!r}"
        )
    validate_provider_code(provider.code)

    digest = hashlib.sha256()
    total = 0
    with tempfile.SpooledTemporaryFile(
        max_size=_SPOOL_MEMORY_LIMIT, mode="w+b"
    ) as spool:
        for chunk in chunks:
            if not isinstance(chunk, bytes):
                raise TypeError("upload chunks must be bytes")
            total += len(chunk)
            if total > policy.max_bytes:
                raise UnsafeFile(
                    f"file exceeds the configured {policy.max_bytes}-byte limit"
                )
            digest.update(chunk)
            spool.write(chunk)
        if total == 0:
            raise UnsafeFile("empty files are not accepted")
        detected = _detect_media_type(spool)
        if detected != declared:
            raise UnsafeFile(
                f"detected media type {detected!r} does not match {declared!r}"
            )

        file_id = uuid4()
        storage_key = f"{scope_prefix(scope)}{file_id}"
        checksum = f"sha256:{digest.hexdigest()}"
        spool.seek(0)
        provider.put(
            storage_key,
            spool,
            content_type=detected,
            size_bytes=total,
            checksum_sha256=checksum,
        )

    return PreparedFile(
        id=file_id,
        scope=scope,
        provider_code=provider.code,
        storage_key=storage_key,
        original_filename=name,
        size_bytes=total,
        declared_media_type=declared,
        detected_media_type=detected,
        checksum_sha256=checksum,
    )


def open_object(
    provider: StorageProvider, *, target: StoredObjectRef
) -> ReadableObject:
    """Open a previously authorized target without holding a DB transaction."""
    _require_provider(target, provider)
    if target.state != FileState.AVAILABLE:
        raise InvalidFileState(f"file {target.id} is {target.state}, not available")
    return provider.open(target.storage_key)


def observe_object(provider: StorageProvider, *, target: StoredObjectRef) -> bool:
    """Observe provider presence without holding a database transaction."""
    _require_provider(target, provider)
    if target.state not in {FileState.AVAILABLE, FileState.MISSING}:
        raise InvalidFileState(f"file {target.id} is {target.state}, not reconcilable")
    return provider.exists(target.storage_key)


def delete_object(provider: StorageProvider, *, target: StoredObjectRef) -> None:
    """Idempotently delete a committed target with no database transaction."""
    _require_provider(target, provider)
    if target.state == FileState.PURGED:
        return
    if target.state != FileState.DELETION_PENDING:
        raise InvalidFileState(
            f"file {target.id} must be deletion_pending before physical purge"
        )
    provider.delete(target.storage_key)


def list_objects(provider: StorageProvider, *, scope: Scope) -> tuple[ObjectInfo, ...]:
    """Collect a fail-closed provider observation outside a DB transaction."""
    validate_provider_code(provider.code)
    prefix = scope_prefix(scope)
    observations = tuple(provider.list(prefix))
    for observed in observations:
        if not observed.key.startswith(prefix):
            raise StorageBoundaryViolation(
                f"provider {provider.code!r} returned an object outside "
                "the requested scope prefix"
            )
    return observations


def delete_orphans(
    provider: StorageProvider, *, scope: Scope, keys: tuple[str, ...]
) -> None:
    """Delete a reviewed scope-key set outside a database transaction."""
    validate_provider_code(provider.code)
    prefix = scope_prefix(scope)
    for key in keys:
        if not key.startswith(prefix):
            raise StorageBoundaryViolation(
                "refusing to delete an object outside the requested scope prefix"
            )
    for key in keys:
        provider.delete(key)


@dataclass(frozen=True)
class OrphanRecheckResult:
    """One reviewed key's physical outcome; the caller records it durably."""

    outcome: Literal["referenced", "absent", "too_new", "deleted"]
    observed_last_modified: datetime | None = None


def recheck_and_delete_orphan(
    provider: StorageProvider,
    *,
    scope: Scope,
    key: str,
    expected_provider_code: str,
    older_than: datetime,
    is_referenced: Callable[[str], bool],
) -> OrphanRecheckResult:
    """Recheck one previously authorized orphan and delete it if still eligible.

    The product owns the reviewed plan, its durable pre-delete record, and
    outcome recording. ``is_referenced`` must finish its short database read
    and close that transaction before returning; no provider I/O occurs while
    that read is in progress. References must be checked across provider codes
    and lifecycle states in the product's authoritative file relation.

    This deliberately accepts one key, so a failed delete cannot hide which
    candidate failed. It does not retry or make the database/object-store race
    atomic; the product must stop on an exception and retain its repair record.
    """
    validate_provider_code(provider.code)
    validate_provider_code(expected_provider_code)
    if provider.code != expected_provider_code:
        raise ProviderMismatch("live provider does not match reviewed provider")
    if not key.startswith(scope_prefix(scope)):
        raise StorageBoundaryViolation(
            "refusing to delete an object outside the requested scope prefix"
        )
    if older_than.tzinfo is None or older_than.utcoffset() is None:
        raise ValueError("older_than must be timezone-aware")

    if is_referenced(key):
        return OrphanRecheckResult("referenced")

    # Prefix listing can include lookalikes; only an exact key is eligible.
    observed: ObjectInfo | None = None
    for info in provider.list(key):
        if not info.key.startswith(scope_prefix(scope)):
            raise StorageBoundaryViolation(
                "provider returned an object outside the requested scope prefix"
            )
        if info.key != key:
            continue
        if observed is not None:
            raise StorageBoundaryViolation("provider returned a duplicate object key")
        observed = info
    if observed is None:
        return OrphanRecheckResult("absent")
    if (
        observed.last_modified.tzinfo is None
        or observed.last_modified.utcoffset() is None
    ):
        raise ValueError("object last_modified must be timezone-aware")
    if not observed.last_modified < older_than:
        return OrphanRecheckResult("too_new", observed.last_modified)

    provider.delete(key)
    return OrphanRecheckResult("deleted", observed.last_modified)


def _require_provider(target: StoredObjectRef, provider: StorageProvider) -> None:
    validate_provider_code(provider.code)
    if target.provider_code != provider.code:
        raise ProviderMismatch(
            f"file is stored by {target.provider_code!r}, not {provider.code!r}"
        )


__all__ = [
    "OrphanRecheckResult",
    "delete_object",
    "delete_orphans",
    "list_objects",
    "observe_object",
    "open_object",
    "prepare_upload",
    "recheck_and_delete_orphan",
]
