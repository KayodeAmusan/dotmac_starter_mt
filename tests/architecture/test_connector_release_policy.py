"""A connector may be released only after it has proved it conforms.

The third release lane, and the one whose subject is discovered rather than
called. `.github/release-connectors.json` is the policy;
`scripts/release_connector.py` is the gate that fails closed on it; this file is
the proof the gate bites, because a gate nobody has driven with a violation is
an assertion about a file.

Three layers, as in the module and adapter lanes, and each fails differently:

1. `release_connector.py resolve` refuses an unlisted distribution, an entry
   carrying stateful facts, an incomplete entry, and — the check this lane adds
   — a floor no installer can resolve.
2. `conformance` checks statically what can be checked before installation.
3. `verify-wheel` runs the shipped SPI kit against the INSTALLED bytes.

The lane contains one connector. Synthetic entries still drive each refusal so
the gate cannot rot into a check that merely recognises today's package, while
the real entry has its own resolution and wheel-policy proofs.

**The classification is a shared floor, not the separator.** A connector's
`EXTRACTION.toml` declares `stateless-protocol-adapter` — the same as an
adapter's, because the four properties that classification governs are exactly
the four a connector has, and `connector-plugin` is the name of a release
PROFILE rather than a fourth ADR-0006 classification. So the classification
check cannot be what keeps a connector out of the adapter lane or an adapter out
of this one. What does that work is the strictness this lane adds, and
`test_a_real_adapter_with_the_same_classification_is_still_refused` is the proof
— it drives the gate with `dotmac-auth-oidc`, a genuine
`stateless-protocol-adapter` in the tree, and requires a refusal.
"""

from __future__ import annotations

import importlib.util
import json
import tomllib
import zipfile
from pathlib import Path

import pytest
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]
POLICY_PATH = PROJECT_ROOT / ".github" / "release-connectors.json"
SCRIPT = PROJECT_ROOT / "scripts" / "release_connector.py"
WORKFLOW = PROJECT_ROOT / ".github" / "workflows" / "release-connector.yml"
LEDGER = PROJECT_ROOT / "docs" / "inventories" / "declared-publication-baseline.json"


def _gate():
    spec = importlib.util.spec_from_file_location("release_connector", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _policy() -> dict:
    return json.loads(POLICY_PATH.read_text(encoding="utf-8"))


# A synthetic connector entry: everything the policy requires, nothing it
# forbids. Each proof below breaks exactly one thing about it, so a refusal can
# only be attributed to the thing that was broken.
def _valid_entry() -> dict:
    return {
        "package_dir": "packages/dotmac-connector-example",
        "release_enabled": True,
        "import_name": "dotmac_connector_example",
        "plugin_attr": "PLUGIN",
        "connector_key": "example.v1",
        "spi_range": ">=1.0,<2.0",
        "integration_floor": "0.1.0a1",
        "tag_prefix": "dotmac-connector-example-v",
        "wheel_contents": {"required": [], "forbidden_prefixes": []},
    }


@pytest.fixture
def lane(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """The gate, pointed at a synthetic repository with one planted connector.

    Returns a callable taking allowlist overrides, so each proof states only the
    difference it is testing.
    """
    gate = _gate()
    package = tmp_path / "packages" / "dotmac-connector-example"
    (package / "src" / "dotmac_connector_example").mkdir(parents=True)
    (package / "pyproject.toml").write_text(
        "[tool.poetry]\n"
        'name = "dotmac-connector-example"\n'
        'version = "0.1.0a1"\n'
        "[tool.poetry.dependencies]\n"
        'dotmac-integration = ">=0.1.0a1"\n'
        '[tool.poetry.plugins."dotmac_integration.connectors"]\n'
        '"example.v1" = "dotmac_connector_example:PLUGIN"\n',
        encoding="utf-8",
    )
    (package / "EXTRACTION.toml").write_text(
        'classification = "stateless-protocol-adapter"\n', encoding="utf-8"
    )
    monkeypatch.setattr(gate, "REPO_ROOT", tmp_path)
    # The synthetic repository has no tags of its own. Publication is supplied
    # rather than read from git so each proof states the release history it
    # depends on — the whole point of the floor check is a version that exists
    # in a checkout and nowhere else, which a checkout cannot demonstrate.
    monkeypatch.setattr(
        gate, "git_tags", lambda *_args, **_kwargs: ["dotmac-integration-v0.1.0a1"]
    )

    def configure(entry: dict | None = None, *, connectors: dict | None = None):
        policy = _policy()
        if connectors is None:
            connectors = {} if entry is None else {"dotmac-connector-example": entry}
        policy["connectors"] = connectors
        allowlist = tmp_path / "release-connectors.json"
        allowlist.write_text(json.dumps(policy), encoding="utf-8")
        monkeypatch.setattr(gate, "ALLOWLIST", allowlist)
        return gate, package

    return configure


# ── The gate refuses ─────────────────────────────────────────────────────────


def test_an_unlisted_connector_cannot_be_resolved(lane) -> None:
    """SENSITIVITY PROOF. Without it, "the allowlist gates the lane" is a claim
    about a file nobody proved is consulted."""
    gate, _ = lane(None)
    for impostor in (
        "dotmac-integration",  # the control plane, not a connector
        "dotmac-connector-example",  # real shape, not listed
        "../../etc/passwd",
        "",
    ):
        with pytest.raises(SystemExit) as refusal:
            gate.resolve(impostor, tags={"dotmac-integration-v0.1.0a1"})
        assert "not an allowlisted connector plugin" in str(refusal.value)


def test_a_listed_connector_resolves(lane) -> None:
    """SPECIFICITY for the test above: the gate must refuse because the entry is
    absent, not because it refuses everything."""
    gate, _ = lane(_valid_entry())
    resolved = gate.resolve(
        "dotmac-connector-example", tags={"dotmac-integration-v0.1.0a1"}
    )
    assert resolved["connector_key"] == "example.v1"


def test_a_held_back_connector_is_refused_by_resolve(lane) -> None:
    """SENSITIVITY: listing/composing a connector must not make it releasable.

    Both workflow enforcement points call this same gate, so this refusal
    applies before build and again after protected-environment approval.
    """
    gate, _ = lane({**_valid_entry(), "release_enabled": False})
    with pytest.raises(SystemExit) as refusal:
        gate.resolve("dotmac-connector-example", tags={"dotmac-integration-v0.1.0a1"})
    message = str(refusal.value)
    assert "release_enabled is false" in message
    assert "HELD BACK" in message


def test_release_enabled_must_be_an_exact_boolean(lane) -> None:
    """A truthy string must not turn a reviewed release hold into permission."""
    gate, _ = lane({**_valid_entry(), "release_enabled": "false"})
    with pytest.raises(SystemExit) as refusal:
        gate.resolve("dotmac-connector-example", tags={"dotmac-integration-v0.1.0a1"})
    assert "release_enabled must be a boolean" in str(refusal.value)


def test_an_entry_carrying_stateful_facts_is_refused(lane) -> None:
    """A package with a schema, a manifest attribute or a kernel floor is a
    MODULE. Publishing it here would skip every namespace, lineage and
    dual-plane gate the module lane performs."""
    for field, value in (
        ("db_schema", "mod_example"),
        ("manifest_attr", "module"),
        ("kernel_floor", "0.1.0a61"),
    ):
        gate, _ = lane({**_valid_entry(), field: value})
        with pytest.raises(SystemExit) as refusal:
            gate.resolve(
                "dotmac-connector-example", tags={"dotmac-integration-v0.1.0a1"}
            )
        assert "STATEFUL facts" in str(refusal.value)
        assert field in str(refusal.value)


def test_an_incomplete_entry_is_refused_field_by_field(lane) -> None:
    """Every field is required. An absent one would be read downstream as
    "unknown" rather than "refused" — the optionality trap the adapter lane
    already records about the module lane."""
    for field in _gate().REQUIRED_FIELDS:
        entry = _valid_entry()
        del entry[field]
        gate, _ = lane(entry)
        with pytest.raises(SystemExit) as refusal:
            gate.resolve(
                "dotmac-connector-example", tags={"dotmac-integration-v0.1.0a1"}
            )
        assert field in str(refusal.value), field


def test_a_wrong_classification_is_refused(lane, tmp_path: Path) -> None:
    """The lane is tied to the governed CLASSIFICATION, read from the package,
    not to a name chosen in the allowlist. `optional-module` here would be a
    stateful package trying to reach the index without the namespace, lineage
    and dual-plane gates the module lane performs."""
    gate, package = lane(_valid_entry())
    (package / "EXTRACTION.toml").write_text(
        'classification = "optional-module"\n', encoding="utf-8"
    )
    with pytest.raises(SystemExit) as refusal:
        gate.resolve("dotmac-connector-example", tags={"dotmac-integration-v0.1.0a1"})
    assert "classification" in str(refusal.value)


def test_the_governed_classification_is_not_a_fourth_one() -> None:
    """`connector-plugin` names a release PROFILE, never an `EXTRACTION.toml`
    classification.

    Promoting it would need ADR-0006 and the global validator amended to
    describe the same four properties twice — no `ModuleManifest`, no lineage,
    no ledger allocation, no persistence import — which is exactly the set
    `stateless-protocol-adapter` already governs. Asserted here rather than left
    to prose because the tempting change is a one-word edit to a JSON file.
    """
    conformance = _policy()["conformance"]
    assert conformance["classification"] == "stateless-protocol-adapter"
    declared = {
        tomllib.loads(dossier.read_text(encoding="utf-8")).get("classification")
        for dossier in (PROJECT_ROOT / "packages").glob("*/EXTRACTION.toml")
    }
    assert "connector-plugin" not in declared, (
        "a package declares `connector-plugin` as its EXTRACTION.toml "
        "classification. That is a release-profile name; amend ADR-0006 and the "
        "global validator first, or use `stateless-protocol-adapter`"
    )


def test_a_real_adapter_with_the_same_classification_is_still_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """THE PROOF THE SHARED CLASSIFICATION COSTS NOTHING.

    Since the connector lane and the adapter lane accept the same
    `EXTRACTION.toml` classification, that check can no longer be what keeps one
    lane's package out of the other. This drives the connector gate with
    `dotmac-auth-oidc` — a real `stateless-protocol-adapter` in this tree, with
    a dossier that satisfies the classification check exactly — and requires a
    refusal anyway.

    Without this, "the strictness is what separates the lanes" is a claim about
    checks nobody proved are reached after the classification passes.
    """
    gate = _gate()
    policy = _policy()
    # Everything a connector entry must carry, pointed at the adapter. The path
    # prefix is what refuses first, and each later check would refuse in turn —
    # the assertion below names the reason so a change of order is visible.
    policy["connectors"] = {
        "dotmac-auth-oidc": {
            "package_dir": "packages/dotmac-auth-oidc",
            "release_enabled": True,
            "import_name": "dotmac_auth_oidc",
            "plugin_attr": "PLUGIN",
            "connector_key": "oidc.v1",
            "spi_range": ">=1.0,<2.0",
            "integration_floor": "0.1.0a1",
            "tag_prefix": "dotmac-auth-oidc-v",
            "wheel_contents": {"required": [], "forbidden_prefixes": []},
        }
    }
    allowlist = tmp_path / "release-connectors.json"
    allowlist.write_text(json.dumps(policy), encoding="utf-8")
    monkeypatch.setattr(gate, "ALLOWLIST", allowlist)

    with pytest.raises(SystemExit) as refusal:
        gate.resolve("dotmac-auth-oidc", tags={"dotmac-integration-v0.1.0a1"})
    message = str(refusal.value)
    assert "packages/dotmac-connector-" in message, message
    # …and the dossier it carries really would have passed the classification
    # check, so the refusal above is not an accident of a wrong dossier.
    dossier = tomllib.loads(
        (PROJECT_ROOT / "packages" / "dotmac-auth-oidc" / "EXTRACTION.toml").read_text(
            encoding="utf-8"
        )
    )
    assert dossier["classification"] == _policy()["conformance"]["classification"]


def test_a_connector_must_live_under_the_first_party_path(lane) -> None:
    """First-party connectors are built, tested, versioned and published from
    Starter `packages/dotmac-connector-<provider>/`. Enforced rather than
    conventional: a connector released from an arbitrary directory is governed
    by this lane while looking, to anyone reading the tree, like something else.

    Later third-party connectors may live in their own repositories under the
    same governance profile — this lane governs only the ones Starter builds.
    """
    gate, _ = lane(
        {**_valid_entry(), "package_dir": "packages/dotmac-example-connector"}
    )
    with pytest.raises(SystemExit) as refusal:
        gate.resolve("dotmac-connector-example", tags={"dotmac-integration-v0.1.0a1"})
    assert "packages/dotmac-connector-" in str(refusal.value)


# ── The floor must be installable, not merely declared ──────────────────────


def test_a_floor_naming_an_unpublished_version_is_refused(lane) -> None:
    """THE check this lane adds, and it fires on the live state of the
    repository rather than a hypothetical.

    The tag set here is SYNTHETIC, which is what keeps this test honest as the
    live state moves: it pins the RULE, not today's versions. (It was written
    when `dotmac-integration` declared 0.1.0a2 with only 0.1.0a1 published;
    a3 has since been released and the gap is closed.) A connector flooring at
    an unpublished version would produce a wheel whose dependency resolution
    fails for every consumer — discovered at install time, by someone who did
    not write it. `release-modules.json` already states the rule for kernels ("a floor
    naming an unpublished version cannot be resolved by an installer, so it is
    not a floor at all"); here it is enforced.
    """
    gate, _ = lane({**_valid_entry(), "integration_floor": "0.1.0a2"})
    with pytest.raises(SystemExit) as refusal:
        gate.resolve("dotmac-connector-example", tags={"dotmac-integration-v0.1.0a1"})
    message = str(refusal.value)
    assert "has no release tag" in message
    assert "not a floor" in message
    # It must name what IS installable, or the author cannot act on the refusal.
    assert "0.1.0a1" in message


def test_a_published_floor_is_accepted(lane) -> None:
    """SPECIFICITY: the refusal above is about publication, not about the
    version being unfamiliar."""
    gate, _ = lane(_valid_entry())
    assert gate.resolve(
        "dotmac-connector-example",
        tags={"dotmac-integration-v0.1.0a1", "dotmac-integration-v0.1.0a2"},
    )


def test_a_connector_floor_may_never_name_the_declared_version_blindly() -> None:
    """What a connector author actually depends on, stated so it survives.

    This test has been a fixed-state assertion twice and been overtaken twice.
    It first said `dotmac-integration`'s declared version was RECORDED as
    unpublished; a3 shipped, so it was inverted to say the ledger no longer
    excuses it; and declaring `0.1.0a4` re-opens the gap. Neither state is the
    invariant — a module is declared-unpublished from the moment a version is
    bumped until the moment it is tagged, which is most of the life of an open
    branch.

    The invariant is the one the lane enforces: **the declared version is not
    automatically a usable floor.** A connector author reading
    `pyproject.toml` or `docs/MODULE_CATALOG.md` sees the declared number, and
    naming it as `integration_floor` produces an unresolvable wheel whenever it
    has not been tagged. So the two facts are asserted to AGREE, rather than
    either being pinned:

    * if the declared version is unpublished, the publication ledger must say
      so — that row is the only warning a connector author gets;
    * if it is published, the row must be gone.

    `test_a_floor_naming_an_unpublished_version_is_refused` above is what
    proves the lane refuses such a floor; this one proves the repository still
    knows which case it is in.
    """
    ledger = json.loads(LEDGER.read_text(encoding="utf-8"))["unpublished"]
    sweep_path = PROJECT_ROOT / "scripts" / "declared_publication_sweep.py"
    spec = importlib.util.spec_from_file_location(
        "declared_publication_sweep", sweep_path
    )
    assert spec is not None and spec.loader is not None
    sweep = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sweep)

    finding = sweep.survey(PROJECT_ROOT)["distributions"]["dotmac-integration"]
    published = finding["state"] == sweep.PUBLISHED
    excused = "dotmac-integration" in ledger

    assert published != excused, (
        f"dotmac-integration declares {finding['declared']} "
        + (
            "and it is tagged, but the ledger still excuses it — a row that "
            "outlived its release warns a connector author about nothing"
            if published
            else "with no tag to prove it and no ledger row — a connector "
            "author naming that floor gets an unresolvable wheel and no "
            "warning from this repository"
        )
    )
    if not published:
        assert finding["declared"] not in finding["published_versions"]


# ── Discovery registration ──────────────────────────────────────────────────


def test_a_key_mismatch_between_entry_point_and_allowlist_is_refused(
    lane, capsys: pytest.CaptureFixture[str]
) -> None:
    """Invisible until two connectors collide in a live registry, where the
    winner depends on which wheel was installed second."""
    import argparse

    gate, _ = lane({**_valid_entry(), "connector_key": "something.else.v1"})
    with pytest.raises(SystemExit) as refusal:
        gate.cmd_resolve(
            argparse.Namespace(distribution="dotmac-connector-example", version="")
        )
    assert "connector_key" in str(refusal.value)


def test_entry_point_must_load_the_object_the_release_gate_executes(lane) -> None:
    """A correct key pointing at another object would certify the wrong plugin."""
    import argparse

    gate, package = lane(_valid_entry())
    pyproject = package / "pyproject.toml"
    pyproject.write_text(
        pyproject.read_text(encoding="utf-8").replace(
            "dotmac_connector_example:PLUGIN", "dotmac_connector_example:OTHER"
        ),
        encoding="utf-8",
    )
    with pytest.raises(SystemExit) as refusal:
        gate.cmd_resolve(
            argparse.Namespace(distribution="dotmac-connector-example", version="")
        )
    assert "same object package discovery will load" in str(refusal.value)


def test_a_distribution_must_register_exactly_one_connector(lane, tmp_path) -> None:
    """Two makes "which one failed" unanswerable at boot — discovery is
    fail-closed as a SET. Zero is invisible to the control plane it was built
    for."""
    import argparse

    gate, package = lane(_valid_entry())
    for plugins, expected in (
        ("", "0 entry points"),
        (
            '[tool.poetry.plugins."dotmac_integration.connectors"]\n'
            '"example.v1" = "dotmac_connector_example:PLUGIN"\n'
            '"example.v2" = "dotmac_connector_example:OTHER"\n',
            "2 entry points",
        ),
    ):
        (package / "pyproject.toml").write_text(
            "[tool.poetry]\n"
            'name = "dotmac-connector-example"\n'
            'version = "0.1.0a1"\n'
            "[tool.poetry.dependencies]\n"
            'dotmac-integration = ">=0.1.0a1"\n' + plugins,
            encoding="utf-8",
        )
        with pytest.raises(SystemExit) as refusal:
            gate.cmd_resolve(
                argparse.Namespace(distribution="dotmac-connector-example", version="")
            )
        assert expected in str(refusal.value)


# ── Static conformance ──────────────────────────────────────────────────────


def test_static_conformance_refuses_a_lineage_and_a_mismatched_floor(
    lane,
) -> None:
    """A connector owns no schema and no lineage: its state lives in the control
    plane's `mod_intg`. And the floor a CONSUMER resolves must be the floor this
    gate checked — a pyproject that says something else makes the gate's answer
    about a different package than the one that ships."""
    import argparse

    gate, package = lane(_valid_entry())
    namespace = argparse.Namespace(distribution="dotmac-connector-example")
    gate.cmd_conformance(namespace)  # clean, so the refusals below mean something

    (package / "src" / "dotmac_connector_example" / "migrations").mkdir()
    with pytest.raises(SystemExit) as refusal:
        gate.cmd_conformance(namespace)
    assert "migrations/" in str(refusal.value)


def test_static_conformance_refuses_a_floor_the_package_does_not_declare(
    lane,
) -> None:
    import argparse

    gate, package = lane(_valid_entry())
    (package / "pyproject.toml").write_text(
        "[tool.poetry]\n"
        'name = "dotmac-connector-example"\n'
        'version = "0.1.0a1"\n'
        "[tool.poetry.dependencies]\n"
        'dotmac-integration = "*"\n'
        '[tool.poetry.plugins."dotmac_integration.connectors"]\n'
        '"example.v1" = "dotmac_connector_example:PLUGIN"\n',
        encoding="utf-8",
    )
    with pytest.raises(SystemExit) as refusal:
        gate.cmd_conformance(
            argparse.Namespace(distribution="dotmac-connector-example")
        )
    assert "the floor a consumer resolves" in str(refusal.value)


def test_static_conformance_refuses_a_private_retry_or_checkpoint_engine(
    lane,
) -> None:
    """Delivery retry and feed checkpoints are two of the six categories
    `external-connector-sources.md` is ratcheting OUT of products and into the
    control plane. A connector that rebuilds them locally MOVES the duplication
    rather than retiring it — and invisibly, because connectors are not in the
    sweep's `RUNTIME_ROOTS`, so the fleet count would not even register it.

    The check is on OWNERSHIP, not on the word: a connector calling
    `dotmac_integration.retry` is doing exactly the right thing, and only a
    module of its own trips this.
    """
    import argparse

    gate, package = lane(_valid_entry())
    source = package / "src" / "dotmac_connector_example"
    namespace = argparse.Namespace(distribution="dotmac-connector-example")

    # Calling the control plane's engine is correct and must NOT trip it.
    (source / "client.py").write_text(
        "from dotmac_integration.retry import Outcome\n", encoding="utf-8"
    )
    gate.cmd_conformance(namespace)

    (source / "retry.py").write_text("MAX = 3\n", encoding="utf-8")
    with pytest.raises(SystemExit) as refusal:
        gate.cmd_conformance(namespace)
    assert "its own retry/checkpoint engine" in str(refusal.value)
    assert "retry.py" in str(refusal.value)


def test_static_conformance_refuses_a_secret_shaped_file(lane) -> None:
    """ADR-0024 section 7: a connector holds a REFERENCE to credential material,
    never the value. Uses the module lane's shared name-shape list rather than a
    second copy — two copies drift, silently and in the worst direction."""
    import argparse

    gate, package = lane(_valid_entry())
    (package / "src" / "dotmac_connector_example" / "id_rsa").write_text("x")
    with pytest.raises(SystemExit) as refusal:
        gate.cmd_conformance(
            argparse.Namespace(distribution="dotmac-connector-example")
        )
    assert "secret-shaped" in str(refusal.value)


def _write_wheel(dist: Path, *, files: list[str], requires: list[str]) -> None:
    dist.mkdir(exist_ok=True)
    with zipfile.ZipFile(dist / "example-0.1.0a1-py3-none-any.whl", "w") as wheel:
        for name in files:
            wheel.writestr(name, "")
        metadata = "Metadata-Version: 2.4\n" + "".join(
            f"Requires-Dist: {requirement}\n" for requirement in requires
        )
        wheel.writestr("example-0.1.0a1.dist-info/METADATA", metadata)


def test_wheel_inspection_enforces_required_surface_and_dependency_closure(
    lane, tmp_path: Path
) -> None:
    """The allowlist's wheel policy is executable, not decorative metadata."""
    import argparse

    entry = {
        **_valid_entry(),
        "wheel_contents": {
            "required": ["dotmac_connector_example/plugin.py"],
            "forbidden_prefixes": ["app/", "tests/"],
            "allowed_requires": ["dotmac-integration", "python"],
        },
    }
    gate, _ = lane(entry)
    dist = tmp_path / "dist"
    _write_wheel(
        dist,
        files=["dotmac_connector_example/plugin.py"],
        requires=["dotmac-integration (>=0.1.0a1)", "python (>=3.12)"],
    )
    gate.cmd_inspect(
        argparse.Namespace(distribution="dotmac-connector-example", dist=str(dist))
    )

    wheel = next(dist.glob("*.whl"))
    wheel.unlink()
    _write_wheel(
        dist,
        files=["tests/test_plugin.py"],
        requires=["sqlalchemy (>=2)"],
    )
    with pytest.raises(SystemExit) as refusal:
        gate.cmd_inspect(
            argparse.Namespace(distribution="dotmac-connector-example", dist=str(dist))
        )
    message = str(refusal.value)
    assert "missing from the wheel" in message
    assert "forbidden content" in message
    assert "dependency outside the allowed closure" in message


# ── The policy names a contract that actually exists ────────────────────────


def test_every_named_conformance_assertion_resolves_in_the_shipped_kit() -> None:
    """The policy names its obligations as CALLABLES rather than describing
    them, so a rename in `dotmac-integration` fails here instead of leaving this
    file pointing at a contract that moved. A policy referring to a function
    nobody can call is the governance equivalent of an unpublished version."""
    import importlib

    conformance = _policy()["conformance"]
    kit = importlib.import_module(conformance["kit_module"])
    for name in conformance["required_assertions"]:
        assert callable(getattr(kit, name, None)), name
        assert name in kit.__all__, f"{name} is not part of the kit's public surface"


def test_the_policy_names_the_real_discovery_group() -> None:
    """A connector registering in the wrong group is not discovered at all, and
    nothing in a release run would notice — the wheel installs cleanly and the
    control plane simply never sees it."""
    import importlib

    conformance = _policy()["conformance"]
    discovery = importlib.import_module(conformance["discovery_module"])
    assert conformance["entry_point_group"] == discovery.ENTRY_POINT_GROUP


def test_the_executable_conformance_actually_calls_the_kit() -> None:
    """The `verify-wheel` program is a string, so nothing else would catch it
    silently degrading into a check that imports the package and asserts
    nothing. It must call the STRONGER of the two assertions: metadata alone
    passes for a connector that cannot hand back a handler, which then fails at
    the first dispatch."""
    program = _gate().CONFORMANCE_PROGRAM
    assert "assert_plugin_conforms" in program
    assert "connector_key" in program
    # …and it must certify the INSTALLED bytes, not the checkout.
    assert "source tree" in program


# ── The lane opens only through one complete reviewed diff ──────────────────


def test_the_allowlist_opens_for_only_the_proven_connector() -> None:
    """Release-enabled entries resolve; held-back and neighbouring ones refuse."""
    assert set(_policy()["connectors"]) == {
        "dotmac-connector-flutterwave",
        "dotmac-connector-linkedin",
        "dotmac-connector-meta-social",
        "dotmac-connector-mono",
        "dotmac-connector-nira",
        "dotmac-connector-paystack",
        "dotmac-connector-remita",
        "dotmac-connector-sub-accounting",
        "dotmac-connector-whatsapp",
    }
    gate = _gate()
    for distribution, entry in _policy()["connectors"].items():
        assert isinstance(entry["release_enabled"], bool), distribution
    enabled = {
        distribution
        for distribution, entry in _policy()["connectors"].items()
        if entry["release_enabled"] is True
    }
    assert enabled == {
        "dotmac-connector-flutterwave",
        "dotmac-connector-linkedin",
        "dotmac-connector-meta-social",
        "dotmac-connector-mono",
        "dotmac-connector-paystack",
        "dotmac-connector-remita",
        "dotmac-connector-whatsapp",
    }
    resolved_keys = {
        distribution: gate.resolve(
            distribution,
            tags={
                "dotmac-integration-v0.1.0a10",
                "dotmac-integration-v0.1.0a11",
                "dotmac-integration-v0.1.0a14",
            },
        )["connector_key"]
        for distribution in enabled
    }
    assert resolved_keys == {
        "dotmac-connector-flutterwave": "flutterwave",
        "dotmac-connector-linkedin": "linkedin",
        "dotmac-connector-meta-social": "meta_social",
        "dotmac-connector-mono": "mono",
        "dotmac-connector-paystack": "paystack",
        "dotmac-connector-remita": "remita",
        "dotmac-connector-whatsapp": "meta_whatsapp",
    }
    with pytest.raises(SystemExit) as held_back:
        gate.resolve("dotmac-connector-nira", tags={"dotmac-integration-v0.1.0a14"})
    assert "release_enabled is false" in str(held_back.value)
    for attempt in (
        "dotmac-connector-stripe",  # a plausible future name
        "dotmac-auth-oidc",  # a real package, right classification
        "dotmac-integration",  # the control plane itself
        "",
    ):
        with pytest.raises(SystemExit) as refusal:
            gate.resolve(attempt, tags={"dotmac-integration-v0.1.0a10"})
        assert "not an allowlisted connector plugin" in str(refusal.value), attempt


def test_the_real_entry_resolves_through_the_release_command(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    import argparse

    gate = _gate()
    monkeypatch.setattr(
        gate, "git_tags", lambda *_args, **_kwargs: ["dotmac-integration-v0.1.0a14"]
    )
    gate.cmd_resolve(
        argparse.Namespace(distribution="dotmac-connector-whatsapp", version="0.1.0a4")
    )
    output = capsys.readouterr().out
    assert "connector_key=meta_whatsapp" in output
    assert "tag=dotmac-connector-whatsapp-v0.1.0a4" in output


def test_the_meta_social_entry_resolves_through_the_release_command(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    import argparse

    gate = _gate()
    # The delivery slice raised this connector's floor to the SPI 1.4 release,
    # so the oracle it resolves against is that tag rather than the a10 one.
    monkeypatch.setattr(
        gate, "git_tags", lambda *_args, **_kwargs: ["dotmac-integration-v0.1.0a14"]
    )
    gate.cmd_resolve(
        argparse.Namespace(
            distribution="dotmac-connector-meta-social", version="0.1.0a2"
        )
    )
    output = capsys.readouterr().out
    assert "connector_key=meta_social" in output
    assert "tag=dotmac-connector-meta-social-v0.1.0a2" in output


def test_the_paystack_entry_resolves_through_the_release_command(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    import argparse

    gate = _gate()
    # a14 rather than a11: the outbound slice declares SPI 1.4, and a floor
    # naming a release whose SPI cannot admit the connector is not a floor.
    monkeypatch.setattr(
        gate, "git_tags", lambda *_args, **_kwargs: ["dotmac-integration-v0.1.0a14"]
    )
    gate.cmd_resolve(
        argparse.Namespace(distribution="dotmac-connector-paystack", version="0.1.0a3")
    )
    output = capsys.readouterr().out
    assert "connector_key=paystack" in output
    assert "tag=dotmac-connector-paystack-v0.1.0a3" in output


def test_the_flutterwave_entry_resolves_through_the_release_command(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    import argparse

    gate = _gate()
    # a14, not a11: the outbound slice raised this connector's
    # `integration_floor` to the SPI 1.4 release, and `_refuse_unpublished_floor`
    # resolves the floor against THIS tag set — an a11-only oracle refuses a
    # floor of a14 rather than proving anything about the entry.
    monkeypatch.setattr(
        gate, "git_tags", lambda *_args, **_kwargs: ["dotmac-integration-v0.1.0a14"]
    )
    gate.cmd_resolve(
        argparse.Namespace(
            distribution="dotmac-connector-flutterwave", version="0.1.0a3"
        )
    )
    output = capsys.readouterr().out
    assert "connector_key=flutterwave" in output
    assert "tag=dotmac-connector-flutterwave-v0.1.0a3" in output


def test_the_mono_entry_resolves_through_the_release_command(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    import argparse

    gate = _gate()
    monkeypatch.setattr(
        gate, "git_tags", lambda *_args, **_kwargs: ["dotmac-integration-v0.1.0a11"]
    )
    gate.cmd_resolve(
        argparse.Namespace(distribution="dotmac-connector-mono", version="0.1.0a1")
    )
    output = capsys.readouterr().out
    assert "connector_key=mono" in output
    assert "tag=dotmac-connector-mono-v0.1.0a1" in output


def test_the_linkedin_entry_resolves_through_the_release_command(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    import argparse

    gate = _gate()
    monkeypatch.setattr(
        gate, "git_tags", lambda *_args, **_kwargs: ["dotmac-integration-v0.1.0a11"]
    )
    gate.cmd_resolve(
        argparse.Namespace(distribution="dotmac-connector-linkedin", version="0.1.0a1")
    )
    output = capsys.readouterr().out
    assert "connector_key=linkedin" in output
    assert "tag=dotmac-connector-linkedin-v0.1.0a1" in output


def test_the_remita_entry_resolves_through_the_release_command(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    import argparse

    gate = _gate()
    # a14, not a11: the outbound slice raised this connector's
    # `integration_floor` to the SPI 1.4 release, and `_refuse_unpublished_floor`
    # resolves the floor against THIS tag set — an a11-only oracle refuses a
    # floor of a14 rather than proving anything about the entry.
    monkeypatch.setattr(
        gate, "git_tags", lambda *_args, **_kwargs: ["dotmac-integration-v0.1.0a14"]
    )
    gate.cmd_resolve(
        argparse.Namespace(distribution="dotmac-connector-remita", version="0.1.0a2")
    )
    output = capsys.readouterr().out
    assert "connector_key=remita" in output
    assert "tag=dotmac-connector-remita-v0.1.0a2" in output


def test_the_workflow_choice_matches_release_enabled_connectors_exactly() -> None:
    """TWO-DIRECTIONAL. The UI offers exactly the mechanically enabled subset.

    A held-back connector stays in the governed inventory for composition and
    manifest-digest coverage, but cannot be selected. Enabling or disabling a
    row therefore requires the workflow surface to change in the same diff.
    """
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    connector_input = workflow[True]["workflow_dispatch"]["inputs"]["connector"]
    connectors = _policy()["connectors"]
    enabled = {
        distribution
        for distribution, entry in connectors.items()
        if entry["release_enabled"] is True
    }
    assert enabled
    assert connector_input["type"] == "choice"
    assert set(connector_input["options"]) == enabled
    assert "dotmac-connector-nira" not in connector_input["options"]


def test_nira_is_composable_but_both_release_resolves_refuse_it() -> None:
    """The hold governs publication, not source composition or discovery."""
    root = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    dependency = root["tool"]["poetry"]["group"]["dev"]["dependencies"][
        "dotmac-connector-nira"
    ]
    assert dependency == {
        "path": "packages/dotmac-connector-nira",
        "develop": True,
    }
    assert _policy()["connectors"]["dotmac-connector-nira"]["release_enabled"] is False

    gate = _gate()
    with pytest.raises(SystemExit) as refusal:
        gate.resolve("dotmac-connector-nira", tags={"dotmac-integration-v0.1.0a14"})
    assert "release_enabled is false" in str(refusal.value)

    source = "\n".join(
        line
        for line in WORKFLOW.read_text(encoding="utf-8").splitlines()
        if not line.lstrip().startswith("#")
    )
    assert source.count("release_connector.py resolve") == 2
    publish = source.split("publish:", 1)[1].split("verify:", 1)[0]
    assert "release_connector.py resolve" in publish


def test_the_workflow_says_the_allowlist_is_the_lock() -> None:
    """The failure this lane is most exposed to is a reader taking the merged
    workflow for permission. The disclaimer is load-bearing, so it is asserted
    present rather than trusted to survive the next edit — and so is the reason
    it was merged shut at all."""
    prose = WORKFLOW.read_text(encoding="utf-8").lower()
    assert "the allowlist is the lock, not this file" in prose
    assert "not authorization" in prose
    # The separation-of-review argument, which is why it lands early.
    assert "different review from the first provider" in prose


def test_the_workflow_matches_the_release_security_sequence() -> None:
    """The connector path may not be a weaker version of the others. Each of
    these exists because of a specific failure: publishing from a stale branch,
    publishing bytes other than the ones inspected, publishing after an approval
    whose SHA has since moved, and tagging a release nobody verified was
    installable from the index."""
    source = "\n".join(
        line
        for line in WORKFLOW.read_text(encoding="utf-8").splitlines()
        if not line.lstrip().startswith("#")
    )
    assert source.count("assert_current_main.sh") == 2
    assert "environment: registry-release" in source
    assert "download-artifact" in source, "publish must use the built bytes"
    assert source.count("twine upload") == 1
    assert source.index("poetry build") < source.index("twine upload")
    assert "release_connector.py inspect" in source
    assert source.index("release_connector.py inspect") < source.index("twine upload")
    # Defence in depth: the gate is re-run at the publication boundary.
    publish = source.split("publish:", 1)[1].split("verify:", 1)[0]
    assert "release_connector.py resolve" in publish
    # The tag is written only after registry verification.
    verify = source.split("verify:", 1)[1]
    assert "git tag" in verify
    assert verify.index("verify-wheel") < verify.index("git tag")


def test_the_published_bytes_are_conformance_checked_not_just_installed() -> None:
    """A connector's verification IS its conformance. Installing it and
    asserting nothing would prove only that pip could resolve it — which is the
    weakest claim in the sequence and the easiest one to mistake for the
    strongest."""
    verify = WORKFLOW.read_text(encoding="utf-8").split("verify:", 1)[1]
    assert "release_connector.py verify-wheel" in verify
    # Both index flags: `--index-url` REPLACES the default, so alone it would
    # see the Dotmac distributions and nothing they depend on.
    assert "--index-url" in verify and "--extra-index-url" in verify


def test_the_declared_floor_is_EXECUTED_not_merely_tagged() -> None:
    """`_refuse_unpublished_floor` proves a floor has a release TAG. It does not
    install it, and nothing else did either: pip resolves the connector's own
    `>=<floor>` against the index and takes the NEWEST release, so both the
    pre-publish smoke and the registry smoke certified the CURRENT control
    plane twice and the declared floor zero times.

    That was not hypothetical. `dotmac-connector-linkedin` and `-mono` declare
    `0.1.0a11` and the other five declare `0.1.0a14`, while published
    `dotmac-integration` runs to `0.1.0a16` — so no connector's declared floor
    had ever been executed, and one that would `ImportError` against its own
    stated minimum would have shipped green.

    The gate is now both legs, in both jobs: install `dependency==floor`
    exactly, run the shipped kit there, and separately test the current
    release. Either leg failing refuses the tag.
    """
    source = WORKFLOW.read_text(encoding="utf-8")
    verify = source.split("verify:", 1)[1]

    # Two conformance runs, not one.
    assert verify.count("release_connector.py verify-wheel") == 2, (
        "the verify job must run conformance at the declared floor AND at the "
        "current release"
    )
    # One of them pins the floor EXACTLY. `>=` would resolve to the newest
    # release again and quietly restore the defect this test exists to prevent.
    assert "dotmac-integration==" in verify
    assert "dotmac-integration>=" not in verify

    # Both legs precede the tag: a floor failure must refuse publication
    # evidence, not be discovered after the tag is pushed.
    assert "git tag" in verify
    assert verify.rindex("verify-wheel") < verify.index("git tag")

    # The pre-publish smoke builds the floor from its RELEASE TAG rather than
    # from `packages/dotmac-integration`, which is whatever main is today.
    build = source.split("build:", 1)[1].split("verify:", 1)[0]
    assert "git archive" in build and "dotmac-integration-v" in build
    assert build.count("release_connector.py verify-wheel") == 2


def test_the_policy_states_what_an_entry_does_not_prove() -> None:
    """The failure mode this lane is most exposed to is a reader taking an
    allowlist row for an endorsement of a provider integration. The three
    non-claims are asserted present because prose is the only place they can
    live and the only thing that keeps them there is a test."""
    prose = " ".join(_policy()["$comment"]).lower()
    assert "not that a version was published" in prose
    assert "not that anything adopted it" in prose
    assert "not that the provider works" in prose


def test_the_four_lanes_do_not_overlap() -> None:
    """A distribution in two lanes would be publishable by whichever gate asks
    the fewest questions."""
    modules = set(
        json.loads(
            (PROJECT_ROOT / ".github" / "release-modules.json").read_text(
                encoding="utf-8"
            )
        )["modules"]
    )
    adapters = set(
        json.loads(
            (PROJECT_ROOT / ".github" / "release-adapters.json").read_text(
                encoding="utf-8"
            )
        )["adapters"]
    )
    contracts = set(
        json.loads(
            (PROJECT_ROOT / ".github" / "release-contracts.json").read_text(
                encoding="utf-8"
            )
        )["contracts"]
    )
    connectors = set(_policy()["connectors"])
    assert not modules & adapters
    assert not modules & connectors
    assert not modules & contracts
    assert not adapters & connectors
    assert not adapters & contracts
    assert not connectors & contracts


def test_no_first_party_connector_package_exists_unlisted() -> None:
    """The path prefix is also a discovery rule. A package under
    `packages/dotmac-connector-*` that is NOT in the allowlist is either a
    connector someone forgot to list or one deliberately held back — and the
    difference has to be written down rather than inferred from an empty
    object."""
    on_disk = {
        path.name
        for path in (PROJECT_ROOT / "packages").glob("dotmac-connector-*")
        if path.is_dir()
    }
    listed = set(_policy()["connectors"])
    assert on_disk - listed == set(), (
        f"connector packages exist but are unlisted: {sorted(on_disk - listed)}. "
        "List them in .github/release-connectors.json with their proof, or "
        "record why they are held back — absence must be a decision, not a gap"
    )
