from pathlib import Path

import pytest

from gittok.config import ConfigError, load_config, resolve_roots


def write(root: Path, name: str, text: str) -> None:
    p = root / ("local" if name in ("repos.yaml", "mascots.yaml") else "config") / name
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


def test_unknown_settings_key_is_a_warning_and_the_config_still_loads(tmp_path, caplog):
    """A running process may read a newer settings file: an unknown key must not stop it."""
    write(tmp_path, "repos.yaml", "repos:\n  a:\n    path: /x\n")
    write(tmp_path, "settings.yaml", "agent:\n  nope: 1\n  max_count: 7\nfuture: {x: 1}\n")
    with caplog.at_level("WARNING", logger="gittok.config"):
        cfg = load_config(tmp_path)
    assert cfg.settings.agent.max_count == 7
    assert len(cfg.warnings) == 2
    assert any("'agent.nope'" in w and "config/settings.yaml" in w for w in cfg.warnings)
    assert any("'future'" in w and "config/settings.yaml" in w for w in cfg.warnings)
    assert "agent.nope" in caplog.text and "future" in caplog.text


def test_unknown_settings_key_is_logged_once_per_process(tmp_path, caplog):
    write(tmp_path, "settings.yaml", "agent:\n  only_once: 1\n")
    with caplog.at_level("WARNING", logger="gittok.config"):
        load_config(tmp_path)
        assert load_config(tmp_path).warnings  # every load still reports it
    assert caplog.text.count("only_once") == 1


def test_shipped_settings_have_no_unknown_keys(tmp_path):
    """Typos in the shipped file must not hide behind the warning."""
    shipped = Path(__file__).parents[1]
    assert load_config(tmp_path, shared=shipped).warnings == ()


def test_unknown_key_in_persona(tmp_path):
    write(tmp_path, "repos.yaml", "repos:\n  a:\n    path: /x\n")
    write(tmp_path, "personas.yaml", "personas:\n  p:\n    name: P\n    voice: v\n    x: 1\n")
    with pytest.raises(ConfigError, match="personas.p.x'.*personas.yaml"):
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
    assert (s.server.host, s.server.port) == ("127.0.0.1", 7313)
    assert (s.agent.default_count, s.agent.max_count) == (10, 20)
    assert (s.agent.per_day_runs, s.agent.packet_size) == (4, 2)
    assert s.analysis.churn_windows_days == (30, 90, 365)
    assert s.analysis.history_window_days == 720
    assert s.research.max_read_lines == 300
    # A file the root does not have is the shipped one.
    assert "greybeard" in cfg.personas


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
    write(tmp_path, "settings.yaml", "{}\n")
    monkeypatch.setenv("GITTOK_ROOT", str(tmp_path))
    assert resolve_roots()[1] == tmp_path.resolve()


def test_project_root_walks_up(tmp_path, monkeypatch):
    monkeypatch.delenv("GITTOK_ROOT", raising=False)
    write(tmp_path, "settings.yaml", "{}\n")
    deep = tmp_path / "a" / "b"
    deep.mkdir(parents=True)
    assert resolve_roots(deep)[1] == tmp_path.resolve()


def test_project_root_not_found(tmp_path, monkeypatch):
    monkeypatch.delenv("GITTOK_ROOT", raising=False)
    with pytest.raises(ConfigError):
        resolve_roots(tmp_path)


def test_shipped_config_loads_without_user_files(tmp_path):
    """The shipped config alone (an empty home, no local/) is a complete config."""
    cfg = load_config(tmp_path, shared=Path(__file__).parents[1])
    assert cfg.repos == {}
    assert len(cfg.personas) == 6
    assert cfg.personas["greybeard"].name == "Greybeard"


def test_no_mascot_is_shipped(tmp_path):
    """A mascot belongs to the user's own repo: it lives in local/mascots.yaml only."""
    shipped = Path(__file__).parents[1]
    assert not (shipped / "config" / "mascots.yaml").exists()
    assert load_config(tmp_path, shared=shipped).mascots == {}


def test_a_shipped_style_mascots_file_is_not_read(tmp_path):
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "mascots.yaml").write_text("mascots:\n  m: {style: s, seed: 1}\n")
    assert load_config(tmp_path).mascots == {}


def test_shipped_config_has_meme_templates_and_render_settings(tmp_path):
    cfg = load_config(tmp_path, shared=Path(__file__).parents[1])
    assert cfg.meme_templates["drake"].lines == 2
    assert cfg.settings.render.max_illustrations_per_run == 6
    assert cfg.settings.render.meme_source.startswith("https://raw.githubusercontent.com/")


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

    from gittok.config import ConfigError, load_config

    (tmp_path / "local").mkdir()
    (tmp_path / "local" / "repos.yaml").write_text("repos: {r: {path: /tmp/r}}\n")
    (tmp_path / "local" / "mascots.yaml").write_text(
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
    (warning,) = load_config(tmp_path).warnings
    assert "'agent.nope'" in warning and "local/settings.yaml" in warning
    wl(tmp_path, "settings.yaml", "bogus: 1\n")
    (warning,) = load_config(tmp_path).warnings
    assert "'bogus'" in warning and "local/settings.yaml" in warning


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


def test_mascots_come_from_the_local_file(tmp_path):
    wl(tmp_path, "mascots.yaml", "mascots:\n  m: {style: s, seed: 5, repo: a}\n  n: {style: t}\n")
    got = load_config(tmp_path).mascots
    assert (got["m"].style, got["m"].seed, got["m"].repo) == ("s", 5, "a")
    assert got["n"].style == "t" and got["n"].seed == 0


def test_server_lan_defaults_on_and_loads_from_the_overlay(tmp_path):
    write(tmp_path, "settings.yaml", "server:\n  port: 9000\n")
    s = load_config(tmp_path).settings.server
    assert s.lan is True and s.allowed_hosts == ()
    (tmp_path / "local").mkdir()
    (tmp_path / "local" / "settings.yaml").write_text(
        "server:\n  lan: false\n  allowed_hosts: [feed.example.net]\n"
    )
    s = load_config(tmp_path).settings.server
    assert s.lan is False and s.allowed_hosts == ("feed.example.net",)
    assert s.port == 9000


def test_shipped_settings_serve_the_lan():
    import yaml

    shipped = Path(__file__).parents[1] / "config" / "settings.yaml"
    server = yaml.safe_load(shipped.read_text())["server"]
    assert server["lan"] is True and server["allowed_hosts"] == []
    assert server["host"] == "127.0.0.1"


@pytest.mark.parametrize(
    "text", ["lan: maybe", "lan: 1", "allowed_hosts: one.example", "allowed_hosts: [1, 2]"]
)
def test_server_settings_reject_wrong_types(tmp_path, text):
    write(tmp_path, "settings.yaml", f"server:\n  {text}\n")
    with pytest.raises(ConfigError, match="settings.server"):
        load_config(tmp_path)


def test_health_prints_unknown_settings_keys(tmp_path, monkeypatch, capsys):
    """`gittok health` keeps a typo visible: stderr for the JSON form, a line for the hint."""
    from gittok import cli

    write(tmp_path, "settings.yaml", "agent:\n  max_cuont: 7\n")
    monkeypatch.setenv("GITTOK_ROOT", str(tmp_path))
    assert cli.main(["health"]) == 0
    io = capsys.readouterr()
    assert "max_cuont" in io.err and "settings.yaml" in io.err
    assert "max_cuont" not in io.out
    assert cli.main(["health", "--hint"]) == 0
    assert "max_cuont" in capsys.readouterr().out


def test_git_timeout_setting_has_a_default_and_reaches_gitq(tmp_path, monkeypatch):
    from gittok import gitq

    monkeypatch.setattr(gitq, "_timeout_s", gitq.timeout_s())  # restore after the test
    write(tmp_path, "settings.yaml", "{}\n")
    assert load_config(tmp_path).settings.analysis.git_timeout_s == 120
    assert gitq.timeout_s() == 120
    write(tmp_path, "settings.yaml", "analysis:\n  git_timeout_s: 30\n")
    assert load_config(tmp_path).settings.analysis.git_timeout_s == 30
    assert gitq.timeout_s() == 30


@pytest.mark.parametrize("bad", ["0", "-5", "true", "'abc'", "[1]"])
def test_git_timeout_setting_must_be_a_positive_number(tmp_path, bad):
    write(tmp_path, "settings.yaml", f"analysis:\n  git_timeout_s: {bad}\n")
    with pytest.raises(ConfigError, match="git_timeout_s"):
        load_config(tmp_path)


def test_shipped_settings_file_names_the_git_timeout():
    import yaml

    shipped = Path(__file__).parents[1] / "config" / "settings.yaml"
    assert yaml.safe_load(shipped.read_text())["analysis"]["git_timeout_s"] == 120


def test_shipped_settings_file_lists_every_setting():
    """config/settings.yaml is the reference: each key the code reads is there with its default."""
    import dataclasses

    import yaml

    from gittok import config

    shipped = yaml.safe_load((Path(__file__).parents[1] / "config" / "settings.yaml").read_text())
    missing = []
    for f in dataclasses.fields(config.Settings):
        if f.name not in shipped:
            missing.append(f.name)
            continue
        section = config._SECTIONS.get(f.name)
        if section is not None:
            have = shipped[f.name] or {}
            names = [s.name for s in dataclasses.fields(section)]
            missing += [f"{f.name}.{n}" for n in names if n not in have]
    assert not missing, f"config/settings.yaml does not list: {', '.join(missing)}"


@pytest.mark.parametrize("value", ["0", "-1", "true", ".inf", ".nan", "oops"])
def test_render_timeout_must_be_finite_positive_seconds(tmp_path, value):
    write(tmp_path, "settings.yaml", f"render:\n  mflux_timeout_s: {value}\n")
    with pytest.raises(ConfigError, match="mflux_timeout_s"):
        load_config(tmp_path)


def test_render_low_ram_must_be_boolean(tmp_path):
    write(tmp_path, "settings.yaml", 'render:\n  mflux_low_ram: "false"\n')
    with pytest.raises(ConfigError, match="mflux_low_ram"):
        load_config(tmp_path)


@pytest.mark.parametrize("value", ["0", "-1", "true", ".inf", ".nan", "oops"])
def test_batch_idle_grace_requires_finite_positive_seconds(tmp_path, value):
    write(tmp_path, "settings.yaml", f"render:\n  mflux_batch_idle_s: {value}\n")
    with pytest.raises(ConfigError, match="mflux_batch_idle_s"):
        load_config(tmp_path)
