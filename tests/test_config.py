from pathlib import Path

import pytest

from codescroll.config import ConfigError, load_config, project_root


def write(root: Path, name: str, text: str) -> None:
    p = root / "config" / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)


def test_repo_path_expands_tilde(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    write(tmp_path, "repos.yaml", "repos:\n  a:\n    path: ~/code/a\n")
    cfg = load_config(tmp_path)
    assert cfg.repo("a").path == (tmp_path / "code" / "a").resolve()


def test_ref_defaults_to_head(tmp_path):
    write(tmp_path, "repos.yaml", "repos:\n  a:\n    path: /x/a\n")
    assert load_config(tmp_path).repo("a").ref == "HEAD"


def test_group_via_groups_list(tmp_path):
    write(
        tmp_path,
        "repos.yaml",
        "groups:\n  g:\n    repos: [a]\nrepos:\n  a:\n    path: /x/a\n  b:\n    path: /x/b\n",
    )
    cfg = load_config(tmp_path)
    assert cfg.repo("a").group == "g"
    assert cfg.repo("b").group is None
    assert cfg.groups["g"].repos == ("a",)


def test_group_via_repo_key_and_standalone(tmp_path):
    write(
        tmp_path,
        "repos.yaml",
        "groups:\n  side:\n    standalone: true\nrepos:\n  a:\n    path: /x/a\n    group: side\n",
    )
    cfg = load_config(tmp_path)
    assert cfg.repo("a").group == "side"
    assert cfg.groups["side"].standalone is True
    assert cfg.groups["side"].repos == ("a",)


def test_conflicting_group_assignment(tmp_path):
    write(
        tmp_path,
        "repos.yaml",
        "groups:\n  g:\n    repos: [a]\n  h:\n    standalone: true\n"
        "repos:\n  a:\n    path: /x/a\n    group: h\n",
    )
    with pytest.raises(ConfigError, match="conflicting"):
        load_config(tmp_path)


def test_unknown_key_in_repo(tmp_path):
    write(tmp_path, "repos.yaml", "repos:\n  a:\n    path: /x\n    bogus: 1\n")
    with pytest.raises(ConfigError, match="bogus.*repos.yaml"):
        load_config(tmp_path)


def test_unknown_key_in_settings_and_persona(tmp_path):
    write(tmp_path, "repos.yaml", "repos:\n  a:\n    path: /x\n")
    write(tmp_path, "settings.yaml", "agent:\n  nope: 1\n")
    with pytest.raises(ConfigError, match="nope.*settings.yaml"):
        load_config(tmp_path)
    (tmp_path / "config" / "settings.yaml").unlink()
    write(tmp_path, "personas.yaml", "personas:\n  p:\n    name: P\n    voice: v\n    x: 1\n")
    with pytest.raises(ConfigError, match="'x'.*personas.yaml"):
        load_config(tmp_path)


def test_unknown_repo_in_group(tmp_path):
    write(tmp_path, "repos.yaml", "groups:\n  g:\n    repos: [ghost]\nrepos:\n  a:\n    path: /x\n")
    with pytest.raises(ConfigError, match="ghost"):
        load_config(tmp_path)


def test_missing_path(tmp_path):
    write(tmp_path, "repos.yaml", "repos:\n  a:\n    mascot: crow\n")
    with pytest.raises(ConfigError, match="path"):
        load_config(tmp_path)


def test_unknown_repo_lookup(tmp_path):
    write(tmp_path, "repos.yaml", "repos:\n  a:\n    path: /x\n")
    with pytest.raises(ConfigError, match="unknown repo: zzz"):
        load_config(tmp_path).repo("zzz")


def test_settings_defaults_when_absent(tmp_path):
    write(tmp_path, "repos.yaml", "repos:\n  a:\n    path: /x\n")
    cfg = load_config(tmp_path)
    s = cfg.settings
    assert (s.server.host, s.server.port) == ("127.0.0.1", 8008)
    assert (s.agent.default_count, s.agent.max_count) == (10, 20)
    assert (s.agent.per_day_runs, s.agent.packet_size) == (4, 4)
    assert s.analysis.churn_windows_days == (30, 90, 365)
    assert s.analysis.history_window_days == 720
    assert s.research.max_read_lines == 300
    assert cfg.defaults == {}
    assert cfg.personas == {}


def test_partial_settings_merge_with_defaults(tmp_path):
    write(tmp_path, "repos.yaml", "repos:\n  a:\n    path: /x\n")
    write(tmp_path, "settings.yaml", "server:\n  port: 9000\n")
    s = load_config(tmp_path).settings
    assert s.server.port == 9000
    assert s.server.host == "127.0.0.1"


def test_data_dir_relative_to_root(tmp_path):
    write(tmp_path, "repos.yaml", "repos:\n  a:\n    path: /x\n")
    assert load_config(tmp_path).settings.data_dir == (tmp_path / "data").resolve()
    write(tmp_path, "settings.yaml", "data_dir: elsewhere/d\n")
    assert load_config(tmp_path).settings.data_dir == (tmp_path / "elsewhere" / "d").resolve()


def test_data_dir_tilde(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    write(tmp_path, "repos.yaml", "repos:\n  a:\n    path: /x\n")
    write(tmp_path, "settings.yaml", "data_dir: ~/cs\n")
    assert load_config(tmp_path).settings.data_dir == (tmp_path / "cs").resolve()


def test_project_root_env(tmp_path, monkeypatch):
    monkeypatch.setenv("CODESCROLL_ROOT", str(tmp_path))
    assert project_root() == tmp_path.resolve()


def test_project_root_walks_up(tmp_path, monkeypatch):
    monkeypatch.delenv("CODESCROLL_ROOT", raising=False)
    write(tmp_path, "repos.yaml", "repos: {}\n")
    deep = tmp_path / "a" / "b"
    deep.mkdir(parents=True)
    assert project_root(deep) == tmp_path.resolve()


def test_project_root_not_found(tmp_path, monkeypatch):
    monkeypatch.delenv("CODESCROLL_ROOT", raising=False)
    with pytest.raises(ConfigError):
        project_root(tmp_path)


def test_real_repo_config():
    cfg = load_config(Path(__file__).parents[1])
    assert {"gittok", "storefront"} <= set(cfg.repos)
    assert cfg.repo("storefront").ref == "origin/master"
    assert cfg.repo("gittok").group == "dev"
    assert len(cfg.personas) == 6
    assert cfg.personas["greybeard"].name == "Greybeard"


def test_real_config_has_mascots_meme_templates_and_render_settings():
    from pathlib import Path

    from codescroll.config import load_config

    cfg = load_config(Path(__file__).parents[1])
    assert cfg.mascots["otter"].repo == "storefront"
    assert cfg.mascots["otter"].seed == 4242
    assert "a small round otter" in cfg.mascots["otter"].style
    assert cfg.meme_templates["drake"].lines == 2
    assert cfg.settings.render.max_illustrations_per_run == 4
    assert cfg.settings.render.memegen_url.startswith("http://127.0.0.1")


def test_mascot_with_unknown_key_is_an_error(tmp_path):
    import pytest

    from codescroll.config import ConfigError, load_config

    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "repos.yaml").write_text("repos: {r: {path: /tmp/r}}\n")
    (tmp_path / "config" / "mascots.yaml").write_text(
        "mascots: {crow: {repo: r, style: s, seed: 1, color: red}}\n"
    )
    with pytest.raises(ConfigError, match="color"):
        load_config(tmp_path)
