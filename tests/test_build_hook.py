"""The wheel build hook: a clone without web/build can still be installed for development."""

from __future__ import annotations

import importlib.util
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]


def _hook(root: Path, target: str = "wheel"):
    spec = importlib.util.spec_from_file_location("hatch_build", ROOT / "hatch_build.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    hook = object.__new__(mod.WebBuildCheck)  # skip hatch's own constructor
    hook._BuildHookInterface__root = str(root)
    hook._BuildHookInterface__target_name = target
    return hook


def test_editable_build_needs_no_web_build(tmp_path):
    data = {"force_include": {}}
    _hook(tmp_path).initialize("editable", data)
    assert data["force_include"] == {}


def test_wheel_build_without_web_build_fails_with_the_fix(tmp_path):
    with pytest.raises(RuntimeError, match="npm --prefix web run build"):
        _hook(tmp_path).initialize("standard", {"force_include": {}})


def test_wheel_build_bundles_the_web_build(tmp_path):
    (tmp_path / "web" / "build").mkdir(parents=True)
    (tmp_path / "web" / "build" / "index.html").write_text("<html>")
    data = {"force_include": {}}
    _hook(tmp_path).initialize("standard", data)
    assert data["force_include"] == {str(tmp_path / "web" / "build"): "gittok/_bundled/web"}


def test_sdist_build_is_not_checked(tmp_path):
    _hook(tmp_path, target="sdist").initialize("standard", {"force_include": {}})


def test_pyproject_does_not_force_include_the_web_build():
    # hatch fails on a missing force-include path, even for an editable install.
    cfg = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    inc = cfg["tool"]["hatch"]["build"]["targets"]["wheel"]["force-include"]
    assert "web/build" not in inc


def test_project_declares_its_licence():
    cfg = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert cfg["project"]["license"] == "Apache-2.0"
    assert (ROOT / "LICENSE").read_text(encoding="utf-8").lstrip().startswith("Apache License")
