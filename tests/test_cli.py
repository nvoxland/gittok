import json

import pytest

from codescroll import cli
from tests.cards import example_card, text_card
from tests.conftest import make_config


@pytest.fixture
def cfg(fixture_repo, tmp_path, monkeypatch):
    cfg = make_config(fixture_repo, tmp_path)
    monkeypatch.setattr(cli, "load_config", lambda: cfg)
    return cfg


def test_validate_file_prints_rejects(cfg, fixture_repo, tmp_path, capsys):
    bad = example_card(fixture_repo)
    bad["visual"]["lines"] = [1, 99]
    path = tmp_path / "cards.json"
    path.write_text(json.dumps({"cards": [text_card(fixture_repo), bad]}))
    code = cli.main(["validate", str(path)])
    out = capsys.readouterr().out
    assert code == 1
    assert "accepted: 1" in out
    assert "#1 lines_out_of_range:" in out


def test_validate_accepts_bare_list_and_exits_zero(cfg, fixture_repo, tmp_path, capsys):
    path = tmp_path / "cards.json"
    path.write_text(json.dumps([text_card(fixture_repo)]))
    assert cli.main(["validate", str(path)]) == 0
    assert "accepted: 1" in capsys.readouterr().out


def test_migrate_creates_db_and_prints_path(cfg, capsys):
    assert cli.main(["migrate"]) == 0
    path = cfg.settings.data_dir / "codescroll.db"
    assert path.exists()
    assert str(path) in capsys.readouterr().out


def test_repos_lists_configured_repos(cfg, capsys):
    assert cli.main(["repos"]) == 0
    out = capsys.readouterr().out
    assert "fixture" in out and "main" in out


def test_analyze_reports_head_then_cached(cfg, capsys):
    assert cli.main(["analyze"]) == 0
    first = capsys.readouterr().out
    assert first.startswith("fixture head=")
    assert "cached=no" in first
    assert cli.main(["analyze"]) == 0
    assert "cached=yes" in capsys.readouterr().out
    assert cli.main(["analyze", "--force"]) == 0
    assert "cached=no" in capsys.readouterr().out


def test_unknown_repo_prints_error_and_exits_1(cfg, capsys):
    assert cli.main(["analyze", "--repo", "nope"]) == 1
    assert "unknown repo: nope" in capsys.readouterr().err


def test_brief_prints_markdown_without_opening_a_run(cfg, capsys):
    from codescroll import db

    assert cli.main(["brief", "--count", "3"]) == 0
    assert "## Packet p1" in capsys.readouterr().out
    with db.open_db(cfg.settings.data_dir / "codescroll.db") as conn:
        assert conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 0


def test_serve_runs_uvicorn_and_prints_urls(cfg, monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(cli.uvicorn, "run", lambda app, **kw: calls.append((app, kw)))
    assert cli.main(["serve", "--port", "9123"]) == 0
    ((app, kw),) = calls
    assert kw == {"host": "127.0.0.1", "port": 9123}
    assert hasattr(app, "router")
    out = capsys.readouterr().out
    assert "http://127.0.0.1:9123" in out
    assert "http://127.0.0.1:9123/mcp" in out


def test_mcp_command_runs_stdio_server(cfg, monkeypatch):
    called = []
    monkeypatch.setattr(cli.mcp_server, "main", lambda: called.append(True))
    assert cli.main(["mcp"]) == 0
    assert called == [True]
