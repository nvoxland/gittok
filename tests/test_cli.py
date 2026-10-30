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


def _with_pending(cfg, fixture_repo, monkeypatch, renderer):
    from codescroll import render
    from tests.test_render import MEME, seed_pending

    ids = seed_pending(cfg, fixture_repo, MEME, count=3)
    monkeypatch.setattr(render, "default_renderers", lambda c: {"meme": renderer})
    return ids


def _statuses(cfg, ids):
    from codescroll import db

    with db.open_db(cfg.settings.data_dir / "codescroll.db") as conn:
        return [
            conn.execute("SELECT status FROM cards WHERE id=?", (i,)).fetchone()[0] for i in ids
        ]


def test_render_runs_one_pass_with_limit_and_prints_counts(cfg, fixture_repo, monkeypatch, capsys):
    from tests.test_render import FakeRenderer

    ids = _with_pending(cfg, fixture_repo, monkeypatch, FakeRenderer())
    assert cli.main(["render", "--limit", "2"]) == 0
    assert "rendered=2 failed=0 waiting=0" in capsys.readouterr().out
    assert _statuses(cfg, ids) == ["ready", "ready", "pending_render"]


def test_render_retry_failed_resets_then_renders(cfg, fixture_repo, monkeypatch, capsys):
    from codescroll import render
    from tests.test_render import FakeRenderer

    ids = _with_pending(
        cfg, fixture_repo, monkeypatch, FakeRenderer(error=render.RenderError("nope"))
    )
    cli.main(["render"])
    assert _statuses(cfg, ids) == ["render_failed"] * 3
    monkeypatch.setattr(render, "default_renderers", lambda c: {"meme": FakeRenderer()})
    capsys.readouterr()
    assert cli.main(["render"]) == 0
    assert "rendered=0" in capsys.readouterr().out
    assert cli.main(["render", "--retry-failed"]) == 0
    assert "rendered=3" in capsys.readouterr().out


def test_avatars_command_generates_and_skips(cfg, monkeypatch, capsys):
    from codescroll import render
    from tests.test_render import FakeRunner

    runner = FakeRunner()
    real = render.IllustrationRenderer
    monkeypatch.setattr(
        render, "IllustrationRenderer", lambda **kw: real(runner=runner, command=["x"])
    )
    assert cli.main(["avatars"]) == 0
    n = len(cfg.personas)
    assert f"generated={n} skipped=0" in capsys.readouterr().out
    assert cli.main(["avatars"]) == 0
    assert f"generated=0 skipped={n}" in capsys.readouterr().out
    assert cli.main(["avatars", "--force"]) == 0
    assert f"generated={n} skipped=0" in capsys.readouterr().out


def test_avatars_command_explains_missing_mflux(cfg, monkeypatch, capsys):
    from codescroll import render

    monkeypatch.setattr(render.shutil, "which", lambda name: None)
    monkeypatch.setattr(render.importlib.util, "find_spec", lambda name: None)
    assert cli.main(["avatars"]) == 1
    assert "uv sync --group images" in capsys.readouterr().err


def test_serve_starts_the_render_and_learning_workers(cfg, monkeypatch):
    import uvicorn

    seen = {}
    monkeypatch.setattr(cli, "create_app", lambda get, **kw: seen.update(kw) or "app")
    monkeypatch.setattr(uvicorn, "run", lambda app, **kw: seen.update(app=app))
    assert cli.main(["serve"]) == 0
    assert seen == {"render_worker": True, "learning_worker": True, "app": "app"}


def _seed_learning(cfg, fixture_repo):
    import time

    from codescroll import db, runs

    with db.open_db(cfg.settings.data_dir / "codescroll.db") as conn:
        run_id = runs.open_run(conn, cfg, repo=None, brief="b", requested=2)
        res = runs.submit(conn, cfg, run_id, [example_card(fixture_repo), text_card(fixture_repo)])
        ids = [a["card_id"] for a in res["accepted"]]
        old = int((time.time() - 3 * 3600) * 1000)
        conn.executemany(
            "INSERT INTO events(card_id, type, ts, data, received_at) "
            "VALUES (?, 'impression', ?, '{\"session\": \"s\"}', 'x')",
            [(ids[0], old), (ids[1], old + 1000)],
        )
        conn.commit()


def test_learn_prints_counts_and_is_idempotent(cfg, fixture_repo, capsys):
    _seed_learning(cfg, fixture_repo)
    assert cli.main(["learn"]) == 0
    out = capsys.readouterr().out
    assert "impressions=2" in out and "rewards=2" in out and "weights=" in out
    assert "weights=0" not in out
    assert cli.main(["learn"]) == 0
    assert "impressions=0 rewards=0 weights=0" in capsys.readouterr().out


def test_reset_weights_all_and_by_feature(cfg, fixture_repo, capsys):
    from codescroll import db

    _seed_learning(cfg, fixture_repo)
    cli.main(["learn"])
    with db.open_db(cfg.settings.data_dir / "codescroll.db") as conn:
        persona = conn.execute("SELECT COUNT(*) FROM weights WHERE feature='persona'").fetchone()[0]
        total = conn.execute("SELECT COUNT(*) FROM weights").fetchone()[0]
    capsys.readouterr()
    assert cli.main(["reset-weights", "--feature", "persona"]) == 0
    assert capsys.readouterr().out.strip() == f"deleted {persona} weights"
    assert cli.main(["reset-weights"]) == 0
    assert capsys.readouterr().out.strip() == f"deleted {total - persona} weights"
