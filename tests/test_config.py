from pathlib import Path

import pytest

from blamescroll.config import ConfigError, load_config, project_root


def write(root: Path, name: str, text: str) -> None:
    p = root / ("local" if name == "repos.yaml" else "config") / name
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
    assert (s.agent.per_day_runs, s.agent.packet_size) == (4, 2)
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
    monkeypatch.setenv("BLAMESCROLL_ROOT", str(tmp_path))
    assert project_root() == tmp_path.resolve()


def test_project_root_walks_up(tmp_path, monkeypatch):
    monkeypatch.delenv("BLAMESCROLL_ROOT", raising=False)
    write(tmp_path, "settings.yaml", "{}\n")
    deep = tmp_path / "a" / "b"
    deep.mkdir(parents=True)
    assert project_root(deep) == tmp_path.resolve()


def test_project_root_not_found(tmp_path, monkeypatch):
    monkeypatch.delenv("BLAMESCROLL_ROOT", raising=False)
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

    from blamescroll.config import load_config

    cfg = load_config(Path(__file__).parents[1])
    assert cfg.mascots["otter"].repo == "storefront"
    assert cfg.mascots["otter"].seed == 4242
    assert "a small round otter" in cfg.mascots["otter"].style
    assert cfg.meme_templates["drake"].lines == 2
    assert cfg.settings.render.max_illustrations_per_run == 6
    assert cfg.settings.render.memegen_url.startswith("http://127.0.0.1")


def test_meme_template_fits_is_loaded(tmp_path):
    write(tmp_path, "repos.yaml", "repos:\n  a:\n    path: /x/a\n")
    write(
        tmp_path,
        "meme_templates.yaml",
        "templates:\n  a: {lines: 2, fits: [commit_drama]}\n  b: {lines: 1}\n",
    )
    cfg = load_config(tmp_path)
    assert cfg.meme_templates["a"].fits == ("commit_drama",)
    assert cfg.meme_templates["b"].fits == ()


def test_mascot_with_unknown_key_is_an_error(tmp_path):
    import pytest

    from blamescroll.config import ConfigError, load_config

    (tmp_path / "config").mkdir()
    (tmp_path / "local").mkdir()
    (tmp_path / "local" / "repos.yaml").write_text("repos: {r: {path: /tmp/r}}\n")
    (tmp_path / "config" / "mascots.yaml").write_text(
        "mascots: {crow: {repo: r, style: s, seed: 1, color: red}}\n"
    )
    with pytest.raises(ConfigError, match="color"):
        load_config(tmp_path)


@pytest.mark.parametrize(
    "files",
    [
        {"repos.yaml": "repos:\n  on:\n    path: /x/a\n"},
        {"repos.yaml": "repos:\n  123:\n    path: /x/a\n"},
        {"repos.yaml": "repos:\n  a:\n    path: /x/a\ngroups:\n  null:\n    repos: [a]\n"},
        {
            "repos.yaml": "repos:\n  a:\n    path: /x/a\n",
            "mascots.yaml": "mascots:\n  yes:\n    style: s\n",
        },
        {
            "repos.yaml": "repos:\n  a:\n    path: /x/a\n",
            "personas.yaml": "personas:\n  1:\n    name: n\n    voice: v\n",
        },
        {
            "repos.yaml": "repos:\n  a:\n    path: /x/a\n",
            "meme_templates.yaml": "templates:\n  true:\n    lines: 2\n",
        },
    ],
)
def test_non_string_keys_are_config_errors(tmp_path, files):
    for name, body in files.items():
        write(tmp_path, name, body)
    with pytest.raises(ConfigError, match="must be text"):
        load_config(tmp_path)


def test_repos_allowed_roots_setting(tmp_path):
    write(tmp_path, "repos.yaml", "repos:\n  a:\n    path: /x/a\n")
    assert load_config(tmp_path).settings.repos.allowed_roots == ()
    write(tmp_path, "settings.yaml", "repos:\n  allowed_roots: [~/src, /opt/code]\n")
    roots = load_config(tmp_path).settings.repos.allowed_roots
    assert roots[1] == Path("/opt/code").resolve()
    assert roots[0] == (Path("~/src").expanduser()).resolve()


def test_fetch_defaults_to_false_and_can_be_enabled(tmp_path):
    write(
        tmp_path,
        "repos.yaml",
        "repos:\n  a:\n    path: /x/a\n  b:\n    path: /x/b\n    fetch: true\n",
    )
    cfg = load_config(tmp_path)
    assert cfg.repo("a").fetch is False
    assert cfg.repo("b").fetch is True
    assert cfg.settings.analysis.fetch_min_interval_s == 900


def wl(root: Path, name: str, text: str) -> None:
    p = root / "local" / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)


def test_missing_local_repos_means_no_repos(tmp_path):
    write(tmp_path, "settings.yaml", "{}\n")
    cfg = load_config(tmp_path)
    assert cfg.repos == {} and cfg.groups == {}


def test_local_settings_merge_over_config_by_key(tmp_path):
    write(
        tmp_path,
        "settings.yaml",
        "server:\n  port: 9000\n  host: 0.0.0.0\nagent:\n  max_count: 7\n",
    )
    wl(tmp_path, "settings.yaml", "server:\n  port: 9100\ndata_dir: elsewhere\n")
    cfg = load_config(tmp_path)
    assert cfg.settings.server.port == 9100
    assert cfg.settings.server.host == "0.0.0.0"
    assert cfg.settings.agent.max_count == 7
    assert cfg.settings.data_dir == (tmp_path / "elsewhere").resolve()


def test_local_settings_unknown_key_names_the_local_file(tmp_path):
    write(tmp_path, "settings.yaml", "{}\n")
    wl(tmp_path, "settings.yaml", "agent:\n  nope: 1\n")
    with pytest.raises(ConfigError, match=r"nope.*local/settings.yaml"):
        load_config(tmp_path)
    wl(tmp_path, "settings.yaml", "bogus: 1\n")
    with pytest.raises(ConfigError, match=r"bogus.*local/settings.yaml"):
        load_config(tmp_path)


def test_local_personas_merge_field_by_field(tmp_path):
    write(
        tmp_path,
        "personas.yaml",
        "personas:\n  a:\n    name: A\n    voice: v\n    bio: hi\n"
        "  b:\n    name: B\n    voice: w\n",
    )
    wl(
        tmp_path,
        "personas.yaml",
        "personas:\n  a:\n    voice: new\n  c:\n    name: C\n    voice: z\n",
    )
    got = load_config(tmp_path).personas
    assert (got["a"].name, got["a"].voice, got["a"].bio) == ("A", "new", "hi")
    assert got["b"].voice == "w" and got["c"].name == "C"


def test_local_mascots_merge_over_config(tmp_path):
    write(tmp_path, "mascots.yaml", "mascots:\n  m: {style: s, seed: 1}\n")
    wl(tmp_path, "mascots.yaml", "mascots:\n  m: {seed: 5}\n  n: {style: t}\n")
    got = load_config(tmp_path).mascots
    assert got["m"].style == "s" and got["m"].seed == 5 and got["n"].style == "t"
