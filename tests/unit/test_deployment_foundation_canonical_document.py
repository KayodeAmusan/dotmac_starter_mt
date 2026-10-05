"""`DeploymentDescriptorDocument.v1` — the value an authorization binds to.

`dotmac-deployment-control` owns authorization. It embeds a desired
specification in a frozen plan snapshot, hashes it, and requires an approver's
evidence to carry that exact digest. What was missing was one hop earlier: this
facility had no canonical document, only digests of rendered bytes, so no
descriptor fact was inside any plan digest at all.

Two properties carry this file.

**Completeness.** The descriptor half is derived by walking
`dataclasses.fields`, never by a hand-written serializer, because a
hand-written one is a field allow-list wearing a different hat — the next field
somebody adds stays out of the digest, silently, and nobody finds out until an
unapproved change ships under an approved digest. `test_a_new_descriptor_field_
is_covered_without_touching_this_module` plants a field and proves it.

**Exclusion.** Resolved endpoints, IP addresses, credential bindings and secret
values must not reach the document. That is not tidiness: Control binds this
digest into an independently signed authorization and resolves the private
material separately, so the moment a resolved address can reach the digest, the
two owners have collapsed into one. The guard runs over the FINISHED document
rather than inside each builder, because the risk is a field nobody thought
about — and it has a planted-defect proof, because a scanner over a clean tree
passes for the wrong reason (ADR-0018).
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import tomllib
from pathlib import Path

import pytest
from dotmac_deployment_foundation.document import (
    DESCRIPTOR_DOCUMENT_SCHEMA,
    DeploymentDescriptorDocumentV1,
    _normalize,
    _refuse_resolved_material,
    build_canonical_document,
)
from dotmac_deployment_foundation.errors import SpecError
from dotmac_deployment_foundation.spec import ProductDeploymentSpec
from dotmac_deployment_foundation.version import VERSION

PACKAGE_DIR = (
    Path(__file__).resolve().parents[2] / "packages" / "dotmac-deployment-foundation"
)

_MANIFEST_DIGEST = "sha256:" + "a" * 64
_IMAGE = f"registry.example.com/acme/app@sha256:{'b' * 64}"

_DESCRIPTOR = f"""
schema = "ProductDeploymentSpec.v1"
product = "acme"
environment = "prod"

[assembly]
manifest_path = "deploy/product.toml"
manifest_digest = "{_MANIFEST_DIGEST}"

[image]
reference = "{_IMAGE}"
source_revision = "{"c" * 40}"

[runtime_materials]
names = ["DATABASE_URL"]

[migration]
command = ["alembic", "upgrade", "heads"]
heads_command = ["alembic", "current"]
owner_material = "MIGRATION_DATABASE_URL"
expected_heads = ["abc123"]
compatibility = "online"
lock_timeout_seconds = 300

[rollout]
stability_window_seconds = 240
rollback_images_retained = 3

[backup]
[[backup.datasets]]
code = "primary"
kind = "postgres"
material = "BACKUP_DATABASE_URL"
retention_days = 30
verify = ["schema"]

[[roles]]
code = "app"
command = ["python", "-m", "app"]
replicas = 2
materials = ["DATABASE_URL"]

[roles.resources]
cpus = "0.5"
memory = "256m"

[roles.health.ready]
path = "/readyz"
port = 8003

[[roles.ports]]
container = 8200
host = 8200
protocol = "tcp"
exposure = "private"
address_family = "dual_stack"
tls = "mtls"
authentication = "mtls"
source_set = "openbao-clients"
telemetry = true
"""


@pytest.fixture(scope="module")
def spec() -> ProductDeploymentSpec:
    return ProductDeploymentSpec.loads(_DESCRIPTOR, source="<document-fixture>")


@pytest.fixture(scope="module")
def document(spec: ProductDeploymentSpec) -> DeploymentDescriptorDocumentV1:
    return spec.to_canonical_document()


# ── the API shape ───────────────────────────────────────────────────────────


def test_the_spec_produces_the_document_and_the_document_owns_its_digest(
    spec: ProductDeploymentSpec,
) -> None:
    """The bytes and the digest belong to the DOCUMENT, not to the spec and not
    to a renderer, so there is one answer to "what was signed" — and a caller
    cannot reach the digest without holding the bytes it was taken over."""
    document = spec.to_canonical_document()
    assert isinstance(document, DeploymentDescriptorDocumentV1)
    assert not hasattr(spec, "sha256_digest")
    assert not hasattr(spec, "canonical_bytes")
    assert document.sha256_digest().startswith("sha256:")
    assert len(document.sha256_digest()) == len("sha256:") + 64


def test_the_digest_is_the_sha256_of_exactly_the_canonical_bytes(
    document: DeploymentDescriptorDocumentV1,
) -> None:
    """Re-derivable by a reader who has only the bytes, which is the whole
    point of publishing them alongside the digest."""
    expected = hashlib.sha256(document.canonical_bytes()).hexdigest()
    assert document.sha256_digest() == f"sha256:{expected}"


def test_the_digest_carries_the_prefix_approvals_requires(
    document: DeploymentDescriptorDocumentV1,
) -> None:
    """`dotmac_approvals.validate_digest` wants `sha256:<hex>` and Control's
    own plan digest is bare hex today. One of them has to normalize; the
    facility that PRODUCES the value states its shape."""
    algorithm, _, hexdigest = document.sha256_digest().partition(":")
    assert algorithm == "sha256"
    assert len(hexdigest) == 64
    assert set(hexdigest) <= set("0123456789abcdef")


def test_the_canonical_bytes_are_sorted_compact_utf8(
    document: DeploymentDescriptorDocumentV1,
) -> None:
    raw = document.canonical_bytes()
    assert raw == json.dumps(
        json.loads(raw), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def test_the_same_descriptor_produces_the_same_bytes_every_time(
    spec: ProductDeploymentSpec,
) -> None:
    assert (
        spec.to_canonical_document().canonical_bytes()
        == spec.to_canonical_document().canonical_bytes()
    )


def test_two_readings_of_one_descriptor_agree_despite_different_source_paths() -> None:
    """`ProductDeploymentSpec.source` is the path of whichever machine read the
    file. It is `compare=False` on the dataclass and excluded here for the same
    reason: digesting it would give one descriptor two digests from two
    checkouts."""
    here = ProductDeploymentSpec.loads(_DESCRIPTOR, source="/build/a/product.toml")
    there = ProductDeploymentSpec.loads(_DESCRIPTOR, source="/runner/b/product.toml")
    assert (
        here.to_canonical_document().sha256_digest()
        == there.to_canonical_document().sha256_digest()
    )


# ── what the document must contain ──────────────────────────────────────────


def test_the_document_names_its_schema_and_the_exact_facility_version(
    document: DeploymentDescriptorDocumentV1,
) -> None:
    """`exposure = "public"` is a word; its meaning is the socket THIS version
    renders. Without the version in the digest, a facility upgrade changes a
    running exposure under an identical approved plan."""
    assert document.schema == DESCRIPTOR_DOCUMENT_SCHEMA
    assert document.content["descriptor_schema"] == "ProductDeploymentSpec.v1"
    assert document.foundation_version == VERSION


def test_the_declared_version_matches_the_distribution_metadata() -> None:
    pyproject = tomllib.loads(
        (PACKAGE_DIR / "pyproject.toml").read_text(encoding="utf-8")
    )
    assert pyproject["tool"]["poetry"]["version"] == VERSION


def test_the_digest_changes_when_the_facility_version_changes(
    spec: ProductDeploymentSpec, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The sensitivity proof. Asserting the version is IN the document proves
    it was written; only changing it proves it is COVERED."""
    before = spec.to_canonical_document().sha256_digest()
    monkeypatch.setattr(
        "dotmac_deployment_foundation.document.VERSION", "9.9.9-not-a-real-version"
    )
    assert spec.to_canonical_document().sha256_digest() != before


@pytest.mark.parametrize(
    ("section", "keys"),
    [
        ("roles", ("code", "replicas", "command", "materials")),
        ("migration", ("command", "owner_material", "expected_heads")),
        ("backup_datasets", ("code", "kind", "retention_days", "verify")),
        ("telemetry", ("logs", "metrics", "traces")),
    ],
)
def test_the_document_carries_the_required_sections(
    document: DeploymentDescriptorDocumentV1, section: str, keys: tuple[str, ...]
) -> None:
    """Roster and roles, image references, ingress policy, migrations, backup,
    handoff and rollback — every one of them, because an authorization that
    covers a subset of a release covers none of it."""
    descriptor = document.content["descriptor"]
    assert section in descriptor
    value = descriptor[section]
    sample = value[0] if isinstance(value, list) else value
    for key in keys:
        assert key in sample, f"{section}.{key} is missing from the document"


def test_the_document_carries_the_service_roster_and_the_exact_image(
    document: DeploymentDescriptorDocumentV1,
) -> None:
    descriptor = document.content["descriptor"]
    assert [role["code"] for role in descriptor["roles"]] == ["app"]
    assert [role["replicas"] for role in descriptor["roles"]] == [2]
    assert descriptor["image"] == _IMAGE
    assert descriptor["manifest_digest"] == _MANIFEST_DIGEST


def test_the_document_carries_the_handoff_and_rollback_requirements(
    document: DeploymentDescriptorDocumentV1,
) -> None:
    descriptor = document.content["descriptor"]
    assert descriptor["stability_window_seconds"] == 240
    assert descriptor["rollback_images_retained"] == 3
    assert descriptor["migration"]["compatibility"] == "online"


def test_the_document_carries_the_ingress_policy_section(
    document: DeploymentDescriptorDocumentV1,
) -> None:
    policy = document.content["ingress_policy"]
    assert policy["schema"] == "IngressPolicy.v1"
    assert policy["publications"][0]["exposure"] == "private"


# ── completeness, proven rather than asserted ───────────────────────────────


def test_a_new_descriptor_field_is_covered_without_touching_this_module() -> None:
    """The property a hand-written serializer cannot have.

    A field added to a descriptor dataclass tomorrow is inside the digest
    tomorrow, because normalization walks `dataclasses.fields`. If this ever
    fails, somebody has replaced the walk with an allow-list, and the next
    field they add will ship unapproved under an approved digest.
    """

    @dataclasses.dataclass(frozen=True)
    class _Future:
        existing: str
        added_later: bool

    assert _normalize(_Future(existing="x", added_later=True)) == {
        "existing": "x",
        "added_later": True,
    }


def test_a_compare_false_field_is_the_only_thing_left_out() -> None:
    @dataclasses.dataclass(frozen=True)
    class _WithLocalPath:
        kept: str
        local_path: str = dataclasses.field(default="", compare=False)

    normalized = _normalize(
        _WithLocalPath(kept="x", local_path="/build/runner/product.toml")
    )
    assert normalized == {"kept": "x"}


def test_an_unset_optional_is_materialized_never_null(
    document: DeploymentDescriptorDocumentV1,
) -> None:
    """'Absent', 'null' and 'defaulted' are three states in JSON and must be
    one state here, or the digest is not re-derivable from stored JSONB."""
    role = document.content["descriptor"]["roles"][0]
    assert role["live"] == {"unset": True}
    assert role["worker"] == {"unset": True}
    assert "null" not in document.canonical_bytes().decode("utf-8")


def test_the_document_survives_a_json_round_trip_unchanged(
    document: DeploymentDescriptorDocumentV1,
) -> None:
    assert json.loads(document.canonical_bytes()) == document.content


@pytest.mark.parametrize(
    "planted",
    [
        {"ratio": 0.5},
        {"nested": [{"ratio": 1.5}]},
    ],
)
def test_a_float_anywhere_is_refused(planted: dict[str, object]) -> None:
    """A float does not round-trip identically through every JSON
    implementation, so a digest that depends on one sometimes differs from
    itself."""
    from dotmac_deployment_foundation.document import _canonical

    with pytest.raises(SpecError) as caught:
        _canonical(planted, where="document")
    assert "float is refused" in str(caught.value)


def test_a_null_anywhere_is_refused() -> None:
    from dotmac_deployment_foundation.document import _canonical

    with pytest.raises(SpecError) as caught:
        _canonical({"unset_the_wrong_way": None}, where="document")
    assert "null is refused" in str(caught.value)


def test_a_non_string_key_is_refused() -> None:
    from dotmac_deployment_foundation.document import _canonical

    with pytest.raises(SpecError) as caught:
        _canonical({1: "one"}, where="document")
    assert "non-string key" in str(caught.value)


# ── the exclusion list, with its planted-defect proof ───────────────────────


def test_the_real_document_carries_no_address_literal(
    document: DeploymentDescriptorDocumentV1,
) -> None:
    """The negative control. It must pass on the real document, or every
    planted case below passes for the wrong reason."""
    _refuse_resolved_material(document.content)


@pytest.mark.parametrize(
    "resolved",
    ["10.20.0.7", "2001:db8:2298:8431::1", "10.0.0.0/8", "192.168.1.10"],
)
def test_a_planted_resolved_address_is_refused(
    document: DeploymentDescriptorDocumentV1, resolved: str
) -> None:
    """Deployment control resolves addresses and binds this digest into an
    independently signed authorization. If a resolved address could reach the
    digest, the two owners would have collapsed into one — so the guard runs
    over the FINISHED document rather than trusting each builder."""
    planted = json.loads(document.canonical_bytes())
    planted["descriptor"]["roles"][0]["environment"] = [["UPSTREAM", resolved]]
    with pytest.raises(SpecError) as caught:
        _refuse_resolved_material(planted)
    assert "is an address literal" in str(caught.value)


def test_a_planted_address_deep_inside_a_list_is_still_found(
    document: DeploymentDescriptorDocumentV1,
) -> None:
    """The walk has to be exhaustive. A guard that checked only the top level
    would pass every real descriptor and catch nothing."""
    planted = json.loads(document.canonical_bytes())
    planted["ingress_policy"]["publications"][0]["binds"].append(
        {"family": "ipv4", "material": "10.20.0.7"}
    )
    with pytest.raises(SpecError):
        _refuse_resolved_material(planted)


def test_a_sha256_digest_is_not_mistaken_for_a_resolved_address(
    document: DeploymentDescriptorDocumentV1,
) -> None:
    """The other direction. Image references and manifest digests are REQUIRED
    content; a guard that refused them would make the document unbuildable and
    would be turned off within a day."""
    assert _MANIFEST_DIGEST in document.canonical_bytes().decode("utf-8")
    assert _IMAGE in document.canonical_bytes().decode("utf-8")


def test_a_material_name_is_not_a_credential_binding(
    document: DeploymentDescriptorDocumentV1,
) -> None:
    """Names stay in. The descriptor holds names and approved pointers by
    ADR-0009, `secrets_guard` refuses values at parse time, and a document
    without the names could not say which credentials a release needs."""
    body = document.canonical_bytes().decode("utf-8")
    assert "MIGRATION_DATABASE_URL" in body
    assert "OPENBAO_CLIENTS" not in body


# ── the digest actually moves when the release changes ──────────────────────


@pytest.mark.parametrize(
    ("before", "after"),
    [
        ("replicas = 2", "replicas = 3"),
        ('tls = "mtls"', 'tls = "terminate"'),
        ("telemetry = true", "telemetry = false"),
        ('address_family = "dual_stack"', 'address_family = "ipv4"'),
        ('source_set = "openbao-clients"', 'source_set = "everyone"'),
        ("stability_window_seconds = 240", "stability_window_seconds = 241"),
        ("retention_days = 30", "retention_days = 31"),
        ('compatibility = "online"', 'compatibility = "maintenance_required"'),
    ],
)
def test_every_release_relevant_axis_moves_the_digest(
    spec: ProductDeploymentSpec, before: str, after: str
) -> None:
    """One parametrized case per axis, because "the digest covers the
    descriptor" is a claim and each of these is the evidence for one clause of
    it. An axis that did not move the digest would be an axis an approval does
    not actually cover."""
    baseline = spec.to_canonical_document().sha256_digest()
    mutated = ProductDeploymentSpec.loads(
        _DESCRIPTOR.replace(before, after, 1), source="<document-fixture>"
    )
    assert mutated.to_canonical_document().sha256_digest() != baseline


def test_a_cosmetic_descriptor_change_does_not_move_the_digest() -> None:
    """The negative control for the axis sweep. A digest that changed on
    whitespace would fail every re-approval for no reason, and operators would
    learn to re-approve without reading."""
    spaced = _DESCRIPTOR.replace("\n[image]", "\n\n\n# a comment\n[image]", 1)
    assert (
        ProductDeploymentSpec.loads(spaced, source="<a>")
        .to_canonical_document()
        .sha256_digest()
        == ProductDeploymentSpec.loads(_DESCRIPTOR, source="<b>")
        .to_canonical_document()
        .sha256_digest()
    )


def test_build_canonical_document_and_the_method_agree(
    spec: ProductDeploymentSpec,
) -> None:
    assert (
        build_canonical_document(spec).sha256_digest()
        == spec.to_canonical_document().sha256_digest()
    )
