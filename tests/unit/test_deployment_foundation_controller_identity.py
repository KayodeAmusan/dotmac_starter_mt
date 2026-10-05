"""``ControllerSshFingerprintV1`` — the controller key, decoded rather than matched.

## The defect under test

Both planes of the lease contract carried the controller's SSH key fingerprint
as a bare string, and the release plane validated it against
``^sha256:[0-9a-f]{64}$``. That is the shape of a CONTENT DIGEST and not the
shape of an OpenSSH fingerprint: ``ssh-keygen -lf`` emits ``SHA256:`` followed by
43 characters of unpadded standard base64.

So the field named "the credential that mutated the host" would have refused
every real value and accepted a 64-hex string that is not a key fingerprint at
all. `test_the_old_hexadecimal_digest_shape_is_refused` and
`test_a_real_generated_key_is_accepted` are the two halves of that, and they must
BOTH hold: widening a regex would have satisfied only the second.

## Why decoding rather than a wider pattern

A wider regex accepts more strings. Establishing that a value IS a SHA-256
digest means decoding it and finding 32 bytes, and that is what this type does.
`test_a_wellformed_shape_that_is_not_32_bytes_is_refused` is the assertion a
shape-matching implementation cannot pass.

## Parsing proves shape; COMPARISON proves identity

The case that matters operationally is last:
`test_a_wellformed_fingerprint_of_the_WRONG_key_is_refused_where_compared`. A
substituted key whose fingerprint parses perfectly must be refused at the
destroy gate, because the gate's question is "is this a release for the key that
took the lease", not "is this a fingerprint".
"""

from __future__ import annotations

import base64
import hashlib
import struct
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest
from dotmac_deployment_foundation.controller_identity import (
    CONTROLLER_FINGERPRINT_MALFORMED,
    ControllerSshFingerprintV1,
)
from dotmac_deployment_foundation.errors import PreconditionFailed, SpecError
from dotmac_deployment_foundation.lease import HostLease
from dotmac_deployment_foundation.lease_release import (
    RELEASE_FOREIGN,
    RELEASE_MALFORMED,
    CleanupDisposition,
    HostClosure,
    HostLeaseReleaseV1,
    ReleasingPrincipal,
    TerminalOutcome,
    lease_digest,
    require_release_before_destruction,
)

SLOT = "dotmacproxmox/102"
RUN = "33854964978"
REHEARSAL = "33860000001"
PRINCIPAL = "repo:michaelayoade/dotmac_starter_mt:ref:refs/heads/main"
AFTER = datetime(2026, 9, 4, 7, 0, tzinfo=UTC)


def _ed25519_blob(point: bytes) -> bytes:
    """An `ssh-ed25519` public key blob, in the wire encoding OpenSSH hashes.

    RFC 4253 § 6.6: a length-prefixed key-type string followed by the
    length-prefixed 32-byte point. Built here rather than parsed from a file so
    the fingerprint under test is derived from key BYTES this test chose.
    """
    kind = b"ssh-ed25519"
    return struct.pack(">I", len(kind)) + kind + struct.pack(">I", len(point)) + point


def _openssh_fingerprint(blob: bytes) -> str:
    """What `ssh-keygen -lf` prints, derived from the rule rather than the tool.

    ``SHA256:`` followed by the base64 of the digest with padding stripped.
    `test_the_derivation_matches_the_actual_ssh_keygen` is the check that this
    understanding is the tool's.
    """
    return "SHA256:" + base64.b64encode(hashlib.sha256(blob).digest()).decode(
        "ascii"
    ).rstrip("=")


#: Two DIFFERENT keys. The second exists for the substitution case, which is the
#: one a parser alone cannot answer.
CONTROLLER = _openssh_fingerprint(_ed25519_blob(hashlib.sha256(b"controller").digest()))
INTRUDER = _openssh_fingerprint(_ed25519_blob(hashlib.sha256(b"another-key").digest()))


# ── a real key, and the shape that used to be required instead ─────────────


def test_a_real_generated_key_is_accepted() -> None:
    """The value the bootstrap plan says to record — `ssh-keygen -lf` output.

    `docs/inventories/deployment-exposure-rehearsal.md` § "Record the fingerprint
    before use" names that command as the source of this field. Before this
    change the release plane's validator refused its output outright, so the one
    documented way of producing the value could not produce an accepted one.
    """
    parsed = ControllerSshFingerprintV1.parse(CONTROLLER, field="controller")
    assert str(parsed) == CONTROLLER
    assert len(parsed.digest) == 32


def test_the_derivation_matches_the_actual_ssh_keygen(tmp_path: Path) -> None:
    """The tool, not a restatement of it.

    `_openssh_fingerprint` encodes this suite's UNDERSTANDING of the format, and
    a test that only ever compares that understanding against itself would agree
    with a wrong understanding. So a key is generated and `ssh-keygen -lf` is
    asked what its fingerprint is, and the answer must both equal the derivation
    and parse.

    `ssh-keygen` is invoked unconditionally rather than behind a `skipif`: CI is
    `ubuntu-latest`, which has it, and a skip here would be a test that proves
    nothing while reporting green.
    """
    private = tmp_path / "controller_key"
    subprocess.run(  # noqa: S603 # nosec B603 — fixed argv, no shell
        [  # noqa: S607 # nosec B607
            "ssh-keygen",
            "-t",
            "ed25519",
            "-N",
            "",
            "-C",
            "dotmac-foundation-rehearsal",
            "-f",
            str(private),
            "-q",
        ],
        check=True,
    )
    listed = subprocess.run(  # noqa: S603 # nosec B603 — fixed argv, no shell
        ["ssh-keygen", "-lf", str(private.with_suffix(".pub"))],  # noqa: S607
        capture_output=True,
        text=True,
        check=True,
    )
    emitted = listed.stdout.split()[1]
    blob = base64.b64decode(private.with_suffix(".pub").read_text().split()[1])
    assert emitted == _openssh_fingerprint(blob), (
        "this suite's understanding of the OpenSSH fingerprint format disagrees "
        "with ssh-keygen, so every fixture derived from it is derived wrongly"
    )
    assert str(ControllerSshFingerprintV1.parse(emitted, field="controller")) == emitted


def test_the_old_hexadecimal_digest_shape_is_refused() -> None:
    """The exact value the previous regex required, and it is not a fingerprint.

    `^sha256:[0-9a-f]{64}$` is this package's CONTENT-DIGEST shape. A field
    holding the credential that mutated a host accepting it meant the field
    could never have held a real one.
    """
    with pytest.raises(SpecError) as exc:
        ControllerSshFingerprintV1.parse("sha256:" + "a" * 64, field="controller")
    assert exc.value.code == CONTROLLER_FINGERPRINT_MALFORMED
    assert "CONTENT-DIGEST" in str(exc.value)


# ── wrong algorithms ───────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "value",
    [
        "MD5:2b:e0:5f:6d:1a:9c:44:80:11:3f:ce:9a:07:cd:2e:41",
        "SHA1:" + base64.b64encode(b"\x00" * 20).decode().rstrip("="),
        "SHA512:" + base64.b64encode(b"\x00" * 64).decode().rstrip("="),
        # Lower case is deliberately a DIFFERENT value, not a spelling of this
        # one: it is the content-digest prefix.
        "sha256:T1kdK/6QTzzwU1EienO6nUgk8wu9UpjqB8BatKbndSE",
    ],
)
def test_another_algorithms_output_is_not_a_sha256_digest(value: str) -> None:
    with pytest.raises(SpecError):
        ControllerSshFingerprintV1.parse(value, field="controller")


# ── malformed lengths and encodings ────────────────────────────────────────


def test_a_wellformed_shape_that_is_not_32_bytes_is_refused() -> None:
    """The assertion a shape-matching implementation cannot pass.

    `SHA256:` plus base64 of 31 bytes is 42 characters — perfectly base64,
    perfectly prefixed, and not a SHA-256 digest. Only decoding finds that out.
    """
    short = "SHA256:" + base64.b64encode(b"\x11" * 31).decode().rstrip("=")
    with pytest.raises(SpecError) as exc:
        ControllerSshFingerprintV1.parse(short, field="controller")
    assert "43" in str(exc.value)


@pytest.mark.parametrize(
    ("value", "why"),
    [
        ("SHA256:", "empty body"),
        ("SHA256:" + "A" * 42, "one short"),
        ("SHA256:" + "A" * 44, "one long"),
        # 32 bytes padded to a multiple of four. A second spelling of one key.
        ("SHA256:" + base64.b64encode(b"\x22" * 32).decode(), "padded"),
        # The URL-safe alphabet: the same digest, a different string. Derived
        # from a digest whose standard encoding actually CONTAINS a `/`, or the
        # two alphabets would agree and the case would prove nothing.
        (
            "SHA256:"
            + base64.urlsafe_b64encode(
                base64.b64decode(CONTROLLER[len("SHA256:") :] + "=")
            )
            .decode()
            .rstrip("="),
            "url-safe alphabet",
        ),
        ("SHA256:" + "!" * 43, "not base64 at all"),
    ],
)
def test_a_malformed_or_second_spelling_is_refused(value: str, why: str) -> None:
    """One key, ONE spelling.

    The record is content-digested, so a padded or URL-safe rendering of the same
    digest would produce a second document for one fact — and the destroy gate
    would then hold two lease digests naming one lease.
    """
    with pytest.raises(SpecError):
        ControllerSshFingerprintV1.parse(value, field="controller")


def test_a_noncanonical_encoding_of_the_RIGHT_digest_is_still_refused() -> None:
    """The subtle one, and the reason `parse` re-encodes.

    43 base64 characters carry 258 bits for a 256-bit digest, so the last
    character has two bits of slack: `...E` and `...F` decode to identical bytes.
    Accepting both would give one key two canonical-looking spellings.
    """
    canonical = CONTROLLER
    body = canonical[len("SHA256:") :]
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"
    twin = body[:-1] + alphabet[alphabet.index(body[-1]) ^ 1]
    assert twin != body
    assert base64.b64decode(twin + "=") == base64.b64decode(body + "=")
    with pytest.raises(SpecError) as exc:
        ControllerSshFingerprintV1.parse("SHA256:" + twin, field="controller")
    assert "canonical" in str(exc.value)


def test_an_empty_fingerprint_is_refused() -> None:
    with pytest.raises(SpecError):
        ControllerSshFingerprintV1.parse("   ", field="controller")


def test_the_digest_itself_is_checked_not_only_the_text() -> None:
    """Constructing around `parse` does not get a shorter digest in."""
    with pytest.raises(SpecError):
        ControllerSshFingerprintV1(digest=b"\x00" * 31)
    with pytest.raises(SpecError):
        ControllerSshFingerprintV1(digest="not bytes")  # type: ignore[arg-type]


# ── one name, one type, on BOTH planes ─────────────────────────────────────


def _lease(**over) -> HostLease:
    kwargs = {
        "target": "192.0.2.54",
        "holder": "deployment-foundation-rehearsal",
        "authorization_run_id": RUN,
        "starts_at": "2026-09-04T00:00:00Z",
        "expires_at": "2026-09-04T06:00:00Z",
        "compose_project_prefix": "rehearsal-",
        "controller_identity_fingerprint": ControllerSshFingerprintV1.parse(
            CONTROLLER, field="controller"
        ),
        "workload_principal": PRINCIPAL,
    }
    kwargs.update(over)
    return HostLease(**kwargs)


def _release(lease: HostLease | None = None, **over) -> HostLeaseReleaseV1:
    lease = lease or _lease()
    kwargs = {
        "lease_digest": lease_digest(lease),
        "vm_slot": SLOT,
        "vm_installation_id": "",
        "candidate_version": "0.4.0a1",
        # TWO revisions, DIFFERENT here on purpose: a fixture that used one
        # value for both would let a writer emitting one of them twice pass.
        "candidate_source_revision": "0" * 40,
        "runner_revision": "1" * 40,
        "authorization_run_id": RUN,
        "rehearsal_run_id": REHEARSAL,
        "outcome": TerminalOutcome(receipt_digest="sha256:" + "b" * 64),
        "released_at": "2026-09-04T05:00:00Z",
        "released_by": ReleasingPrincipal(
            kind="github_actions_workload",
            subject=PRINCIPAL,
            run_binding=REHEARSAL,
        ),
        "controller_identity_fingerprint": lease.controller_identity_fingerprint,
        "closure": HostClosure.REUSABLE,
        "cleanup": CleanupDisposition.PURGED,
    }
    kwargs.update(over)
    return HostLeaseReleaseV1(**kwargs)


def test_both_planes_name_the_same_thing_the_same_way() -> None:
    """`host_mutation_evidence` was the release plane's name for the fact the
    lease plane already called `controller_identity_fingerprint`.

    One thing, two names, across a boundary where the two are COMPARED — which
    is the shape that invites a reader to conclude they are different facts.
    The rename reached the unrecorded, drifted `0.4.0a1` candidate but has not
    crossed an admissible published-artifact boundary.
    """
    lease_fields = HostLease.__dataclass_fields__
    release_fields = HostLeaseReleaseV1.__dataclass_fields__
    assert "controller_identity_fingerprint" in lease_fields
    assert "controller_identity_fingerprint" in release_fields
    assert "host_mutation_evidence" not in release_fields
    assert (
        lease_fields["controller_identity_fingerprint"].type
        == release_fields["controller_identity_fingerprint"].type
    )
    assert "controller_identity_fingerprint" in _release().as_document()
    assert "host_mutation_evidence" not in _release().as_document()


def test_neither_plane_accepts_a_bare_string() -> None:
    """A `str` here is the defect returning: it is what let a value that is not a
    fingerprint be recorded as one."""
    with pytest.raises(SpecError):
        _lease(controller_identity_fingerprint=CONTROLLER)
    with pytest.raises(SpecError) as exc:
        _release(controller_identity_fingerprint=CONTROLLER)
    assert exc.value.code == RELEASE_MALFORMED


# ── parsing proves shape; comparison proves identity ───────────────────────


def test_a_wellformed_fingerprint_of_the_WRONG_key_is_refused_where_compared() -> None:
    """THE case. A substituted key whose fingerprint parses perfectly.

    Every shape check passes: `INTRUDER` is a real OpenSSH fingerprint of a real
    key blob and decodes to 32 bytes. What it is not is the key that took this
    lease, and the destroy gate's question is that one. A gate that only parsed
    would admit it.
    """
    intruder = ControllerSshFingerprintV1.parse(INTRUDER, field="controller")
    assert len(intruder.digest) == 32  # it PARSES; that is the point
    with pytest.raises(PreconditionFailed) as exc:
        require_release_before_destruction(
            _lease(),
            _release(controller_identity_fingerprint=intruder),
            now=AFTER,
            vm_slot=SLOT,
            candidate_version="0.4.0a1",
        )
    assert exc.value.code == RELEASE_FOREIGN


def test_the_matching_key_is_admitted_so_the_gate_is_not_a_wall() -> None:
    """The accepting control. A comparison that refuses everything cannot be
    shown to be comparing identity rather than refusing on principle."""
    assert require_release_before_destruction(
        _lease(),
        _release(closure=HostClosure.DESTROY_ONLY),
        now=AFTER,
        vm_slot=SLOT,
        candidate_version="0.4.0a1",
    )


def test_identity_is_the_DIGEST_not_the_text() -> None:
    """Two objects parsed from the same canonical text compare equal, and a
    different key's does not — over the 32 bytes, not over the string."""
    one = ControllerSshFingerprintV1.parse(CONTROLLER, field="a")
    two = ControllerSshFingerprintV1.parse(CONTROLLER, field="b")
    assert one == two
    assert one.digest == two.digest
    assert one != ControllerSshFingerprintV1.parse(INTRUDER, field="c")


def test_a_lease_that_swapped_credentials_digests_differently() -> None:
    """The fingerprint is a separate FACT and not a separate DOCUMENT: it is
    inside the canonical bytes, so the swap is visible in the lease digest."""
    other = _lease(
        controller_identity_fingerprint=ControllerSshFingerprintV1.parse(
            INTRUDER, field="controller"
        )
    )
    assert lease_digest(other) != lease_digest(_lease())
