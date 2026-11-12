"""Root resolution: clone mode and installed mode (a bundled shared dir plus a home dir)."""

from __future__ import annotations

from pathlib import Path

import pytest

from gittok import config
from gittok.config import load_config

REAL = Path(__file__).parents[1]


@pytest.fixture
def bundle(tmp_path, monkeypatch):
    """A fake bundled dir with the shipped config, and no clone or env roots."""
    import shutil

    b = tmp_path / "bundle"
    shutil.copytree(REAL / "config", b / "config")
    (b / "web").mkdir()
    (b / "web" / "index.html").write_text("<html>bundled</html>")
    for var in ("GITTOK_ROOT", "GITTOK_HOME"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(config, "bundle_dir", lambda: b)
    return b


def test_env_root_wins(tmp_path, monkeypatch, bundle):
    clone = tmp_path / "clone"
    clone.mkdir()
    monkeypatch.setenv("GITTOK_ROOT", str(clone))
    assert config.resolve_roots() == (clone.resolve(), clone.resolve())


def test_clone_found_by_walking_up(tmp_path, bundle):
    clone = tmp_path / "clone"
    (clone / "config").mkdir(parents=True)
    (clone / "config" / "settings.yaml").write_text("{}\n")
    deep = clone / "a" / "b"
    deep.mkdir(parents=True)
    assert config.resolve_roots(deep) == (clone.resolve(), clone.resolve())


def test_installed_mode_uses_bundle_and_home_env(tmp_path, monkeypatch, bundle):
    home = tmp_path / "myhome"
    monkeypatch.setenv("GITTOK_HOME", str(home))
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    shared, h = config.resolve_roots(elsewhere)
    assert shared == bundle and h == home.resolve()
    assert home.is_dir()  # created on first use


def test_installed_mode_default_home(tmp_path, monkeypatch, bundle):
    monkeypatch.setenv("HOME", str(tmp_path / "u"))
    (tmp_path / "u").mkdir()
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    _, h = config.resolve_roots(elsewhere)
    assert h == (tmp_path / "u" / ".gittok").resolve()


def test_no_clone_and_no_bundle_raises(tmp_path, monkeypatch):
    for var in ("GITTOK_ROOT", "GITTOK_HOME"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(config, "bundle_dir", lambda: tmp_path / "nope")
    with pytest.raises(config.ConfigError):
        config.resolve_roots(tmp_path)


def test_load_config_reads_shared_from_bundle_and_local_from_home(tmp_path, monkeypatch, bundle):
    home = tmp_path / "home"
    (home / "local").mkdir(parents=True)
    (home / "local" / "repos.yaml").write_text("repos:\n  a:\n    path: /x/a\n")
    monkeypatch.setenv("GITTOK_HOME", str(home))
    monkeypatch.chdir(tmp_path)
    cfg = load_config()
    assert cfg.shared == bundle
    assert cfg.root == home.resolve()
    assert "a" in cfg.repos
    assert cfg.personas  # from bundle/config/personas.yaml
    assert cfg.languages["languages"]
    assert cfg.settings.data_dir == (home / "data").resolve()


def test_local_overlay_is_read_from_home(tmp_path, monkeypatch, bundle):
    home = tmp_path / "home"
    (home / "local").mkdir(parents=True)
    (home / "local" / "settings.yaml").write_text("data_dir: elsewhere\n")
    monkeypatch.setenv("GITTOK_HOME", str(home))
    monkeypatch.chdir(tmp_path)
    assert load_config().settings.data_dir == (home / "elsewhere").resolve()


def test_clone_mode_shared_is_root(tmp_path):
    cfg = load_config(REAL)
    assert cfg.shared_path("config", "settings.yaml") == REAL / "config" / "settings.yaml"


def test_shipped_root_in_clone_is_repo(monkeypatch):
    monkeypatch.setattr(config, "bundle_dir", lambda: REAL / "nope")
    assert config.shipped_root() == REAL


def test_claude_dir_prefers_dot_claude(tmp_path):
    (tmp_path / ".claude").mkdir()
    assert config.claude_dir(tmp_path) == tmp_path / ".claude"
    other = tmp_path / "b"
    (other / "claude").mkdir(parents=True)
    assert config.claude_dir(other) == other / "claude"


def test_api_serves_web_from_shared_bundle(tmp_path, monkeypatch, bundle):
    from fastapi.testclient import TestClient

    from gittok import api

    monkeypatch.setenv("GITTOK_HOME", str(tmp_path / "home"))
    monkeypatch.chdir(tmp_path)
    # A real config does not know the TestClient default host ("testserver").
    r = TestClient(api.create_app(load_config), base_url="http://localhost").get("/")
    assert "bundled" in r.text


def test_cli_install_env_installed_mode(tmp_path, monkeypatch, bundle):
    import argparse

    from gittok import cli

    home = tmp_path / "home"
    monkeypatch.setenv("GITTOK_HOME", str(home))
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli, "_own_executable", lambda: "/t/bin/gittok")
    env = cli._install_env(load_config(), argparse.Namespace(apply=False, force=False))
    assert env.installed and env.repo_root == bundle and env.exe == "/t/bin/gittok"
    assert env.work_dir == home.resolve()
    assert env.data_dir == (home / "data").resolve()


def test_cli_install_env_clone_mode():
    import argparse

    from gittok import cli

    env = cli._install_env(load_config(REAL), argparse.Namespace(apply=False, force=False))
    assert not env.installed and env.repo_root == REAL
