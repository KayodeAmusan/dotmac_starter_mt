"""Behavioural contract for streamed files on both security planes."""

from __future__ import annotations

import io
import zipfile
from dataclasses import replace
from datetime import UTC, datetime
from typing import IO
from uuid import uuid4

import pytest
from dotmac_files.contracts import (
    FilePolicy,
    FileState,
    PreparedFileConflict,
    UnsafeFile,
)
from dotmac_files.physical import (
    delete_object,
    delete_orphans,
    list_objects,
    observe_object,
    open_object,
    prepare_upload,
    recheck_and_delete_orphan,
)
from dotmac_files.providers import ObjectInfo, StorageBoundaryViolation, StorageProvider
from dotmac_files.service import (
    deletion_target,
    download_target,
    finalize_purge,
    find_orphan_keys,
    reconciliation_target,
    record_presence,
    request_deletion,
    stage_file,
)
from dotmac_kernel.cache import PlatformScope, TenantScope
from sqlalchemy import create_engine
from sqlalchemy.orm import Session


class MemoryProvider(StorageProvider):
    code = "memory"

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def put(
        self,
        key: str,
        content: IO[bytes],
        *,
        content_type: str,
        size_bytes: int,
        checksum_sha256: str,
    ) -> None:
        del content_type, checksum_sha256
        payload = content.read()
        assert len(payload) == size_bytes
        self.objects[key] = payload

    def open(self, key: str) -> io.BytesIO:
        return io.BytesIO(self.objects[key])

    def exists(self, key: str) -> bool:
        return key in self.objects

    def delete(self, key: str) -> None:
        self.objects.pop(key, None)

    def list(self, prefix: str) -> tuple[ObjectInfo, ...]:
        now = datetime.now(UTC)
        return tuple(
            ObjectInfo(key=key, size_bytes=len(value), last_modified=now)
            for key, value in self.objects.items()
            if key.startswith(prefix)
        )


@pytest.fixture
def db() -> Session:
    engine = create_engine(
        "sqlite:///:memory:",
        execution_options={"schema_translate_map": {"mod_files": None}},
    )
    from dotmac_files.models import PlatformStoredFile, TenantStoredFile

    TenantStoredFile.__table__.create(engine)
    PlatformStoredFile.__table__.create(engine)
    with Session(engine) as session:
        yield session


def _policy() -> FilePolicy:
    return FilePolicy(
        max_bytes=1_024,
        allowed_extensions=frozenset({".pdf", ".csv", ".xls", ".xlsx"}),
        allowed_media_types=frozenset(
            {
                "application/pdf",
                "text/csv",
                "application/vnd.ms-excel",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            }
        ),
    )


def _xlsx_payload() -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types />")
        archive.writestr("xl/workbook.xml", "<workbook />")
    return output.getvalue()


def _image_policy() -> FilePolicy:
    return FilePolicy(
        max_bytes=1_048_576,
        allowed_extensions=frozenset({".png", ".jpg", ".jpeg", ".gif", ".webp"}),
        allowed_media_types=frozenset(
            {"image/png", "image/jpeg", "image/gif", "image/webp"}
        ),
    )


def test_upload_uses_only_trusted_scope_and_generated_identity_in_the_key() -> None:
    tenant = uuid4()
    provider = MemoryProvider()
    prepared = prepare_upload(
        provider,
        scope=TenantScope(tenant),
        policy=_policy(),
        original_filename="August Invoice.pdf",
        declared_media_type="application/pdf",
        chunks=(b"%PDF-1.7\nbody",),
    )

    assert prepared.storage_key == f"tenants/{tenant}/files/{prepared.id}"
    assert "August" not in prepared.storage_key
    assert prepared.detected_media_type == "application/pdf"
    assert prepared.checksum_sha256.startswith("sha256:")
    assert provider.objects[prepared.storage_key] == b"%PDF-1.7\nbody"


def test_platform_upload_uses_a_distinct_trusted_prefix() -> None:
    provider = MemoryProvider()
    prepared = prepare_upload(
        provider,
        scope=PlatformScope(),
        policy=_policy(),
        original_filename="licence-bundle.pdf",
        declared_media_type="application/pdf",
        chunks=(b"%PDF-1.7\nplatform",),
    )

    assert prepared.scope == PlatformScope()
    assert prepared.storage_key == f"platform/files/{prepared.id}"
    assert provider.objects[prepared.storage_key] == b"%PDF-1.7\nplatform"


@pytest.mark.parametrize("name", ["../secret.pdf", "/etc/secret.pdf", "", "a\x00.pdf"])
def test_upload_rejects_unsafe_names(name: str) -> None:
    with pytest.raises(UnsafeFile):
        prepare_upload(
            MemoryProvider(),
            scope=TenantScope(uuid4()),
            policy=_policy(),
            original_filename=name,
            declared_media_type="application/pdf",
            chunks=(b"%PDF-1.7\n",),
        )


def test_upload_rejects_content_type_spoofing() -> None:
    with pytest.raises(UnsafeFile, match="does not match"):
        prepare_upload(
            MemoryProvider(),
            scope=TenantScope(uuid4()),
            policy=_policy(),
            original_filename="invoice.pdf",
            declared_media_type="application/pdf",
            chunks=(b"name,email\nAda,ada@example.net\n",),
        )


@pytest.mark.parametrize(
    ("name", "media_type", "payload"),
    [
        (
            "legacy.xls",
            "application/vnd.ms-excel",
            bytes.fromhex("D0CF11E0A1B11AE1") + b"workbook",
        ),
        (
            "modern.xlsx",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            _xlsx_payload(),
        ),
    ],
)
def test_excel_formats_are_recognised_by_content_signature(
    name: str, media_type: str, payload: bytes
) -> None:
    prepared = prepare_upload(
        MemoryProvider(),
        scope=TenantScope(uuid4()),
        policy=_policy(),
        original_filename=name,
        declared_media_type=media_type,
        chunks=(payload,),
    )
    assert prepared.detected_media_type == media_type


@pytest.mark.parametrize(
    ("name", "media_type", "payload"),
    [
        ("avatar.png", "image/png", b"\x89PNG\r\n\x1a\nimage"),
        ("avatar.jpg", "image/jpeg", b"\xff\xd8\xff\xe0image"),
        ("avatar.jpeg", "image/jpeg", b"\xff\xd8\xff\xe1image"),
        ("avatar.gif", "image/gif", b"GIF89aimage"),
        ("avatar.webp", "image/webp", b"RIFF\x05\x00\x00\x00WEBPimage"),
    ],
)
def test_academy_avatar_formats_are_recognised_by_content_signature(
    name: str, media_type: str, payload: bytes
) -> None:
    prepared = prepare_upload(
        MemoryProvider(),
        scope=TenantScope(uuid4()),
        policy=_image_policy(),
        original_filename=name,
        declared_media_type=media_type,
        chunks=(payload,),
    )
    assert prepared.detected_media_type == media_type


def test_upload_stops_at_the_configured_size_limit() -> None:
    policy = FilePolicy(
        max_bytes=4,
        allowed_extensions=frozenset({".pdf"}),
        allowed_media_types=frozenset({"application/pdf"}),
    )
    with pytest.raises(UnsafeFile, match="exceeds"):
        prepare_upload(
            MemoryProvider(),
            scope=TenantScope(uuid4()),
            policy=policy,
            original_filename="x.pdf",
            declared_media_type="application/pdf",
            chunks=(b"%PDF", b"more-data-that-must-not-be-accepted"),
        )


def test_signature_detection_does_not_read_the_entire_file_back_into_memory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Admission may spool to disk but must not defeat that by `read()`ing all."""
    import tempfile

    original = tempfile.SpooledTemporaryFile

    class BoundedReadSpool:
        def __init__(self, *args: object, **kwargs: object) -> None:
            self._wrapped = original(*args, **kwargs)

        def __enter__(self) -> BoundedReadSpool:
            return self

        def __exit__(self, *args: object) -> None:
            self._wrapped.close()

        def write(self, payload: bytes) -> int:
            return self._wrapped.write(payload)

        def seek(self, offset: int, whence: int = 0) -> int:
            return self._wrapped.seek(offset, whence)

        def tell(self) -> int:
            return self._wrapped.tell()

        def read(self, size: int = -1) -> bytes:
            if size < 0:
                raise AssertionError("admission attempted an unbounded read")
            return self._wrapped.read(size)

    monkeypatch.setattr(tempfile, "SpooledTemporaryFile", BoundedReadSpool)

    class ChunkedProvider(MemoryProvider):
        def put(
            self,
            key: str,
            content: IO[bytes],
            *,
            content_type: str,
            size_bytes: int,
            checksum_sha256: str,
        ) -> None:
            del content_type, checksum_sha256
            received = bytearray()
            while chunk := content.read(8):
                received.extend(chunk)
            assert len(received) == size_bytes
            self.objects[key] = bytes(received)

    prepare_upload(
        ChunkedProvider(),
        scope=TenantScope(uuid4()),
        policy=_policy(),
        original_filename="invoice.pdf",
        declared_media_type="application/pdf",
        chunks=(b"%PDF-1.7\n", b"body" * 100),
    )


def test_database_stage_and_deletion_lifecycle_are_caller_transactional(
    db: Session,
) -> None:
    scope = TenantScope(uuid4())
    provider = MemoryProvider()
    prepared = prepare_upload(
        provider,
        scope=scope,
        policy=_policy(),
        original_filename="invoice.pdf",
        declared_media_type="application/pdf",
        chunks=(b"%PDF-1.7\nbody",),
    )
    stored = stage_file(db, prepared=prepared)
    assert db.in_transaction()
    assert stored.state == FileState.AVAILABLE

    request_deletion(db, scope=scope, file_id=stored.id, now=datetime.now(UTC))
    assert stored.state == FileState.DELETION_PENDING
    target = deletion_target(db, scope=scope, file_id=stored.id)
    delete_object(provider, target=target)
    finalize_purge(db, target=target, now=datetime.now(UTC))
    assert stored.state == FileState.PURGED
    assert prepared.storage_key not in provider.objects


def test_platform_database_lifecycle_uses_the_same_engine(db: Session) -> None:
    scope = PlatformScope()
    provider = MemoryProvider()
    prepared = prepare_upload(
        provider,
        scope=scope,
        policy=_policy(),
        original_filename="licence-bundle.pdf",
        declared_media_type="application/pdf",
        chunks=(b"%PDF-1.7\nplatform",),
    )
    stored = stage_file(db, prepared=prepared)

    from dotmac_files.models import PlatformStoredFile

    assert isinstance(stored, PlatformStoredFile)
    assert "tenant_id" not in stored.__table__.c
    target = download_target(db, scope=scope, file_id=stored.id)
    assert target.scope == scope
    assert open_object(provider, target=target).read() == b"%PDF-1.7\nplatform"

    request_deletion(db, scope=scope, file_id=stored.id, now=datetime.now(UTC))
    target = deletion_target(db, scope=scope, file_id=stored.id)
    delete_object(provider, target=target)
    finalized = finalize_purge(db, target=target, now=datetime.now(UTC))
    assert finalized.state == FileState.PURGED


def test_download_stream_opens_after_the_database_phase_has_ended(db: Session) -> None:
    scope = TenantScope(uuid4())
    provider = MemoryProvider()
    prepared = prepare_upload(
        provider,
        scope=scope,
        policy=_policy(),
        original_filename="invoice.pdf",
        declared_media_type="application/pdf",
        chunks=(b"%PDF-1.7\nbody",),
    )
    stage_file(db, prepared=prepared)
    target = download_target(db, scope=scope, file_id=prepared.id)
    db.rollback()

    stream = open_object(provider, target=target)
    try:
        assert stream.read() == b"%PDF-1.7\nbody"
    finally:
        stream.close()


def test_reconciler_records_a_missing_object_without_deleting_metadata(
    db: Session,
) -> None:
    scope = TenantScope(uuid4())
    provider = MemoryProvider()
    prepared = prepare_upload(
        provider,
        scope=scope,
        policy=_policy(),
        original_filename="invoice.pdf",
        declared_media_type="application/pdf",
        chunks=(b"%PDF-1.7\nbody",),
    )
    stored = stage_file(db, prepared=prepared)
    target = reconciliation_target(db, scope=scope, file_id=stored.id)
    provider.delete(prepared.storage_key)

    exists = observe_object(provider, target=target)
    record_presence(
        db,
        target=target,
        exists=exists,
        now=datetime.now(UTC),
    )
    assert stored.state == FileState.MISSING
    assert stored.missing_observed_at is not None


def test_staging_the_same_prepared_file_is_idempotent_and_conflicts_on_drift(
    db: Session,
) -> None:
    scope = TenantScope(uuid4())
    prepared = prepare_upload(
        MemoryProvider(),
        scope=scope,
        policy=_policy(),
        original_filename="invoice.pdf",
        declared_media_type="application/pdf",
        chunks=(b"%PDF-1.7\nbody",),
    )
    first = stage_file(db, prepared=prepared)
    replay = stage_file(db, prepared=prepared)
    assert replay.id == first.id

    with pytest.raises(PreparedFileConflict):
        stage_file(db, prepared=replace(prepared, original_filename="other.pdf"))

    request_deletion(db, scope=scope, file_id=first.id, now=datetime.now(UTC))
    with pytest.raises(PreparedFileConflict, match="lifecycle"):
        stage_file(db, prepared=prepared)


def test_a_storage_key_collision_raises_without_discarding_the_outer_transaction(
    db: Session,
) -> None:
    """Exercises `conflict_savepoint` reached through its new engine-free
    import (`dotmac_kernel.transactions`, not `dotmac_kernel.db`) on the real
    `stage_file` IntegrityError path -- distinct from the idempotency test
    above, which never reaches that path: there, `_find_prepared`'s id lookup
    finds the existing row first and `_require_same_prepared` raises before
    `conflict_savepoint` is ever entered.

    Here two prepared files carry DIFFERENT ids (so `_find_prepared`'s id
    lookup misses both times) but the same tenant, provider and storage key,
    which collides on the DB-level `uq_stored_files_tenant_provider_key`
    unique constraint instead -- a genuine `IntegrityError` raised inside
    `conflict_savepoint`'s `with db.begin_nested()` block.

    `conflict_savepoint` isolates that failure to a SAVEPOINT rather than the
    caller's outer transaction (see its docstring in
    `dotmac_kernel/_transactions.py`). If the import instead reached a
    variant that called a bare `db.rollback()`, the outer transaction --
    including `first`, staged earlier in this same session -- would be
    discarded too. Asserting `first` is still visible and the session is
    still mid-transaction after the collision proves the SAVEPOINT held.
    """
    scope = TenantScope(uuid4())
    provider = MemoryProvider()
    first_prepared = prepare_upload(
        provider,
        scope=scope,
        policy=_policy(),
        original_filename="first.pdf",
        declared_media_type="application/pdf",
        chunks=(b"%PDF-1.7\nfirst",),
    )
    first = stage_file(db, prepared=first_prepared)

    second_prepared = prepare_upload(
        provider,
        scope=scope,
        policy=_policy(),
        original_filename="second.pdf",
        declared_media_type="application/pdf",
        chunks=(b"%PDF-1.7\nsecond",),
    )
    assert second_prepared.id != first_prepared.id
    colliding = replace(second_prepared, storage_key=first_prepared.storage_key)

    with pytest.raises(
        PreparedFileConflict, match="conflicts outside its declared scope"
    ):
        stage_file(db, prepared=colliding)

    assert db.in_transaction()
    assert db.get(type(first), first.id) is not None


def test_orphan_reaper_deletes_only_old_unreferenced_keys_in_the_tenant_prefix(
    db: Session,
) -> None:
    scope = TenantScope(uuid4())
    provider = MemoryProvider()
    prepared = prepare_upload(
        provider,
        scope=scope,
        policy=_policy(),
        original_filename="invoice.pdf",
        declared_media_type="application/pdf",
        chunks=(b"%PDF-1.7\nbody",),
    )
    stage_file(db, prepared=prepared)
    orphan = f"tenants/{scope.tenant_id}/files/{uuid4()}"
    provider.objects[orphan] = b"orphan"

    observations = list_objects(provider, scope=scope)
    orphan_keys = find_orphan_keys(
        db,
        scope=scope,
        provider_code=provider.code,
        observations=observations,
        older_than=datetime.max.replace(tzinfo=UTC),
    )
    delete_orphans(provider, scope=scope, keys=orphan_keys)
    assert orphan_keys == (orphan,)
    assert prepared.storage_key in provider.objects


def test_reviewed_orphan_recheck_never_deletes_referenced_fresh_or_absent_key() -> None:
    scope = TenantScope(uuid4())
    key = f"tenants/{scope.tenant_id}/files/{uuid4()}"
    provider = MemoryProvider()
    provider.objects[key] = b"retained"
    reads: list[str] = []

    def referenced(candidate: str) -> bool:
        reads.append(candidate)
        return True

    result = recheck_and_delete_orphan(
        provider,
        scope=scope,
        key=key,
        expected_provider_code=provider.code,
        older_than=datetime.max.replace(tzinfo=UTC),
        is_referenced=referenced,
    )
    assert result.outcome == "referenced"
    assert reads == [key]
    assert key in provider.objects

    result = recheck_and_delete_orphan(
        provider,
        scope=scope,
        key=key,
        expected_provider_code=provider.code,
        older_than=datetime.min.replace(tzinfo=UTC),
        is_referenced=lambda _: False,
    )
    assert result.outcome == "too_new"
    assert result.observed_last_modified is not None
    assert key in provider.objects

    provider.objects.clear()
    result = recheck_and_delete_orphan(
        provider,
        scope=scope,
        key=key,
        expected_provider_code=provider.code,
        older_than=datetime.max.replace(tzinfo=UTC),
        is_referenced=lambda _: False,
    )
    assert result.outcome == "absent"


def test_reviewed_orphan_recheck_deletes_only_exact_old_key_after_reference_read() -> (
    None
):
    scope = TenantScope(uuid4())
    key = f"tenants/{scope.tenant_id}/files/{uuid4()}"
    lookalike = f"{key}-still-referenced"
    provider = MemoryProvider()
    provider.objects[key] = b"orphan"
    provider.objects[lookalike] = b"keep"
    events: list[str] = []

    def reference_read(candidate: str) -> bool:
        assert candidate == key
        events.append("reference-read-finished")
        return False

    original_delete = provider.delete

    def delete(candidate: str) -> None:
        assert events == ["reference-read-finished"]
        original_delete(candidate)

    provider.delete = delete  # type: ignore[method-assign]
    result = recheck_and_delete_orphan(
        provider,
        scope=scope,
        key=key,
        expected_provider_code=provider.code,
        older_than=datetime.max.replace(tzinfo=UTC),
        is_referenced=reference_read,
    )
    assert result.outcome == "deleted"
    assert result.observed_last_modified is not None
    assert key not in provider.objects
    assert lookalike in provider.objects


def test_reviewed_orphan_recheck_refuses_wrong_provider_or_scope() -> None:
    from dotmac_files import ProviderMismatch

    scope = TenantScope(uuid4())
    provider = MemoryProvider()
    key = f"tenants/{scope.tenant_id}/files/{uuid4()}"
    provider.objects[key] = b"retain"

    with pytest.raises(ProviderMismatch):
        recheck_and_delete_orphan(
            provider,
            scope=scope,
            key=key,
            expected_provider_code="other",
            older_than=datetime.max.replace(tzinfo=UTC),
            is_referenced=lambda _: False,
        )
    with pytest.raises(StorageBoundaryViolation):
        recheck_and_delete_orphan(
            provider,
            scope=scope,
            key=f"tenants/{uuid4()}/files/{uuid4()}",
            expected_provider_code=provider.code,
            older_than=datetime.max.replace(tzinfo=UTC),
            is_referenced=lambda _: False,
        )
    assert key in provider.objects


def test_orphan_reaper_fails_closed_on_a_provider_key_outside_the_tenant_prefix(
    db: Session,
) -> None:
    scope = TenantScope(uuid4())
    foreign_key = f"tenants/{uuid4()}/files/{uuid4()}"

    class MisbehavingProvider(MemoryProvider):
        def list(self, prefix: str) -> tuple[ObjectInfo, ...]:
            del prefix
            return (
                ObjectInfo(
                    key=foreign_key,
                    size_bytes=1,
                    last_modified=datetime.min.replace(tzinfo=UTC),
                ),
            )

    provider = MisbehavingProvider()
    provider.objects[foreign_key] = b"x"
    with pytest.raises(StorageBoundaryViolation):
        list_objects(provider, scope=scope)
    assert foreign_key in provider.objects


def test_platform_orphan_reaper_cannot_cross_into_a_tenant_prefix(db: Session) -> None:
    scope = PlatformScope()
    foreign_key = f"tenants/{uuid4()}/files/{uuid4()}"

    class MisbehavingProvider(MemoryProvider):
        def list(self, prefix: str) -> tuple[ObjectInfo, ...]:
            del prefix
            return (
                ObjectInfo(
                    key=foreign_key,
                    size_bytes=1,
                    last_modified=datetime.min.replace(tzinfo=UTC),
                ),
            )

    provider = MisbehavingProvider()
    provider.objects[foreign_key] = b"x"
    with pytest.raises(StorageBoundaryViolation):
        list_objects(provider, scope=scope)
    assert foreign_key in provider.objects
