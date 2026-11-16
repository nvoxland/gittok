"""Root resolution: a source clone, or a GitTok directory plus the bundled shared files."""

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
    monkeypatch.delenv("GITTOK_ROOT", raising=False)
    monkeypatch.setattr(config, "bundle_dir", lambda: b)
    return b


def gittok_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    (path / config.MARKER).write_text("version: 1.0.0\n")
    return path


def test_clone_found_by_walking_up(tmp_path, bundle):
    clone = tmp_path / "clone"
    (clone / "config").mkdir(parents=True)
    (clone / "config" / "settings.yaml").write_text("{}\n")
    deep = clone / "a" / "b"
    deep.mkdir(parents=True)
    assert config.resolve_roots(deep) == (clone.resolve(), clone.resolve())


def test_gittok_directory_found_by_walking_up_to_the_marker(tmp_path, bundle):
    home = gittok_dir(tmp_path / "myhome")
    deep = home / "local" / "x"
    deep.mkdir(parents=True)
    assert config.resolve_roots(deep) == (bundle, home.resolve())
    assert config.resolve_roots(home) == (bundle, home.resolve())


def test_an_mcp_json_alone_is_not_a_marker(tmp_path, bundle):
    (tmp_path / ".mcp.json").write_text("{}")
    with pytest.raises(config.ConfigError):
        config.resolve_roots(tmp_path)


def test_outside_a_gittok_directory_fails_and_makes_nothing(tmp_path, monkeypatch, bundle):
    fake_home = tmp_path / "u"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    with pytest.raises(config.ConfigError) as e:
        config.resolve_roots(elsewhere)
    text = str(e.value)
    assert "not inside a GitTok directory" in text and "gittok init <dir>" in text
    assert "\n" not in text
    assert list(fake_home.iterdir()) == [] and list(elsewhere.iterdir()) == []
    assert not hasattr(config, "home_dir")


def test_env_root_names_a_gittok_directory_from_anywhere(tmp_path, monkeypatch, bundle):
    home = gittok_dir(tmp_path / "myhome")
    monkeypatch.setenv("GITTOK_ROOT", str(home))
    assert config.resolve_roots(tmp_path) == (bundle, home.resolve())


def test_env_root_names_a_clone_from_anywhere(tmp_path, monkeypatch, bundle):
    clone = tmp_path / "clone"
    (clone / "config").mkdir(parents=True)
    (clone / "config" / "settings.yaml").write_text("{}\n")
    monkeypatch.setenv("GITTOK_ROOT", str(clone))
    assert config.resolve_roots(tmp_path) == (clone.resolve(), clone.resolve())


def test_env_root_that_is_neither_fails(tmp_path, monkeypatch, bundle):
    monkeypatch.setenv("GITTOK_ROOT", str(tmp_path))
    with pytest.raises(config.ConfigError, match="GITTOK_ROOT"):
        config.resolve_roots(tmp_path)


def test_the_old_home_variable_does_nothing(tmp_path, monkeypatch, bundle):
    monkeypatch.setenv("GITTOK_HOME", str(tmp_path / "old"))
    with pytest.raises(config.ConfigError):
        config.resolve_roots(tmp_path)
    assert not (tmp_path / "old").exists()


def test_load_config_reads_shared_from_bundle_and_local_from_home(tmp_path, monkeypatch, bundle):
    home = gittok_dir(tmp_path / "home")
    (home / "local").mkdir(parents=True)
    (home / "local" / "repos.yaml").write_text("repos:\n  a:\n    path: /x/a\n")
    monkeypatch.chdir(home)
    cfg = load_config()
    assert cfg.shared == bundle
    assert cfg.root == home.resolve()
    assert "a" in cfg.repos
    assert cfg.personas  # from bundle/config/personas.yaml
    assert cfg.languages["languages"]
    assert cfg.settings.data_dir == (home / "data").resolve()


def test_local_overlay_is_read_from_home(tmp_path, monkeypatch, bundle):
    home = gittok_dir(tmp_path / "home")
    (home / "local").mkdir(parents=True)
    (home / "local" / "settings.yaml").write_text("data_dir: elsewhere\n")
    monkeypatch.chdir(home)
    assert load_config().settings.data_dir == (home / "elsewhere").resolve()


def test_is_clone(tmp_path):
    assert config.is_clone(REAL)
    assert not config.is_clone(gittok_dir(tmp_path / "home"))


def test_clone_mode_shared_is_root(tmp_path):
    cfg = load_config(REAL)
    assert cfg.shared_path("config", "settings.yaml") == REAL / "config" / "settings.yaml"


def test_shipped_root_in_clone_is_repo(monkeypatch):
    monkeypatch.setattr(config, "bundle_dir", lambda: REAL / "nope")
    assert config.shipped_root() == REAL


def test_api_serves_web_from_shared_bundle(tmp_path, monkeypatch, bundle):
    from fastapi.testclient import TestClient

    from gittok import api

    monkeypatch.chdir(gittok_dir(tmp_path / "home"))
    # A real config does not know the TestClient default host ("testserver").
    r = TestClient(api.create_app(load_config), base_url="http://localhost").get("/")
    assert "bundled" in r.text
