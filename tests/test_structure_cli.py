"""`gittok structure` and the health hint."""

import json

import pytest

from gittok import cli, profiling, structure
from tests.conftest import make_config


@pytest.fixture
def cfg(fixture_repo, tmp_path, monkeypatch):
    cfg = make_config(fixture_repo, tmp_path)
    monkeypatch.setattr(cli, "load_config", lambda: cfg)
    return cfg


def test_needed_grammars_come_from_the_files_of_configured_repos(cfg):
    got = profiling.needed_grammars(cfg)
    assert "python" in got and "go" not in got


def test_structure_command_reports_status(cfg, capsys, monkeypatch):
    monkeypatch.setattr(structure, "available", lambda: True)
    monkeypatch.setattr(structure, "ready", lambda g: g != "python")
    assert cli.main(["structure"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["installed"] is True and out["missing"] == ["python"]


def test_prefetch_downloads_only_missing_grammars(cfg, capsys, monkeypatch):
    got = []
    monkeypatch.setattr(structure, "available", lambda: True)
    monkeypatch.setattr(structure, "ready", lambda g: g != "python")
    monkeypatch.setattr(
        structure, "download", lambda names: got.append(sorted(names)) or len(names)
    )
    assert cli.main(["structure", "--prefetch"]) == 0
    assert got == [["python"]]
    assert "python" in capsys.readouterr().out


def test_prefetch_without_the_group_says_how_to_install(cfg, capsys, monkeypatch):
    monkeypatch.setattr(structure, "available", lambda: False)
    assert cli.main(["structure", "--prefetch"]) == 1
    out = capsys.readouterr().out
    assert "reinstall gittok" in out and "--group" not in out


def test_prefetch_reports_a_failed_download(cfg, capsys, monkeypatch):
    def boom(names):
        raise OSError("no network")

    monkeypatch.setattr(structure, "available", lambda: True)
    monkeypatch.setattr(structure, "ready", lambda g: False)
    monkeypatch.setattr(structure, "download", boom)
    assert cli.main(["structure", "--prefetch"]) == 1
    assert "no network" in capsys.readouterr().out


def test_health_hint_has_one_line_when_grammars_are_missing(cfg, capsys, monkeypatch):
    from gittok import supply

    monkeypatch.setattr(profiling, "profile_hint", lambda cfg: None)
    monkeypatch.setattr(
        supply, "feed_health", lambda conn, cfg, now: {"backlog": 9, "runway_days": 9, "want": 0}
    )
    monkeypatch.setattr(structure, "available", lambda: True)
    monkeypatch.setattr(structure, "ready", lambda g: False)
    assert cli.main(["health", "--hint"]) == 0
    lines = capsys.readouterr().out.strip().splitlines()
    assert len(lines) == 1 and "structure --prefetch" in lines[0] and "python" in lines[0]
    assert "Offer to download" in lines[0] and "with Bash" in lines[0]


def test_health_hint_is_silent_without_the_group(cfg, capsys, monkeypatch):
    from gittok import supply

    monkeypatch.setattr(profiling, "profile_hint", lambda cfg: None)
    monkeypatch.setattr(
        supply, "feed_health", lambda conn, cfg, now: {"backlog": 9, "runway_days": 9, "want": 0}
    )
    monkeypatch.setattr(structure, "available", lambda: False)
    assert cli.main(["health", "--hint"]) == 0
    assert capsys.readouterr().out == ""
