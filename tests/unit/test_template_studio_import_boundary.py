"""The pure renderer must remain usable without assembling Template Studio."""

from __future__ import annotations

import os
import subprocess
import sys
import tomllib
from pathlib import Path


def test_pure_renderer_import_and_error_path_load_no_runtime_wiring() -> None:
    root = Path(__file__).resolve().parents[2]
    package_src = root / "packages" / "dotmac-template-studio" / "src"
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(
        part for part in (str(package_src), env.get("PYTHONPATH", "")) if part
    )
    script = """
import sys
from dotmac_template_studio.rendering import MissingTemplateValueError, render

assert render("Hi {name}", {"name": "Ada"}) == "Hi Ada"
assert render("{{name}} {missing}", {}, strict=False) == "{{name}} {missing}"
try:
    render("{missing}", {})
except MissingTemplateValueError as exc:
    assert "missing" in str(exc)
else:
    raise AssertionError("strict rendering accepted an absent value")

forbidden = (
    "dotmac_kernel",
    "dotmac_template_studio.service",
    "dotmac_template_studio.manifest",
    "dotmac_template_studio.web",
    "dotmac_template_studio.router",
    "dotmac_template_studio.models",
)
loaded = sorted(
    name
    for name in sys.modules
    if name in forbidden or name.startswith("dotmac_kernel.")
)
assert not loaded, loaded
"""
    result = subprocess.run(  # noqa: S603 - fixed interpreter and in-tree script
        [sys.executable, "-c", script],
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_public_version_matches_package_metadata_and_manifest() -> None:
    import dotmac_template_studio as studio

    package_file = (
        Path(__file__).resolve().parents[2]
        / "packages"
        / "dotmac-template-studio"
        / "pyproject.toml"
    )
    metadata = tomllib.loads(package_file.read_text(encoding="utf-8"))
    assert studio.__version__ == metadata["tool"]["poetry"]["version"]
    assert studio.module.version == studio.__version__
