# ruff: noqa: F811
"""Review fixes in cli.py: the feed watch, one-line errors, the renderer hint, the port note."""

from datetime import UTC, datetime, timedelta

import pytest

from gittok import cli, gitq, supply
from tests.test_cli import _append, _poll_steps, cfg  # noqa: F401


def test_feed_watch_ignores_an_old_signal_when_the_feed_is_full(cfg, monkeypatch, capsys):
    now = datetime.now(UTC)
    log = cfg.settings.data_dir / supply.WANTS_FILE
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text(supply.wants_line(now - timedelta(hours=1), 20))
    monkeypatch.setattr(cli, "_feed_wants_cards", lambda c: False)
    pending = _poll_steps(
        monkeypatch, lambda: _append(log, supply.wants_line(now + timedelta(minutes=1), 7))
    )
    assert cli.main(["feed-watch", "--poll", "0.05"]) == 0
    assert pending == []  # it waited for a new line
    assert "want 7 cards" in capsys.readouterr().out


def test_feed_watch_fires_for_an_old_signal_while_the_feed_wants_cards(cfg, capsys, monkeypatch):
    now = datetime.now(UTC)
    log = cfg.settings.data_dir / supply.WANTS_FILE
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text(supply.wants_line(now - timedelta(hours=1), 20))
    monkeypatch.setattr(cli, "_feed_wants_cards", lambda c: True)
    assert cli.main(["feed-watch", "--poll", "0.05"]) == 0
    assert "want 20 cards" in capsys.readouterr().out


@pytest.mark.parametrize("argv", [["validate", "/nonexistent/cards.json"],
                                  ["submit-facts", "--repo", "fixture", "--head", "0" * 40,
                                   "--tool", "kit 1", "/nonexistent/f.json"]])
def test_a_missing_file_is_a_one_line_error(cfg, capsys, argv):
    assert cli.main(argv) == 1
    err = capsys.readouterr().err
    assert err.startswith("error:") and len(err.strip().splitlines()) == 1


def test_a_git_error_is_a_one_line_error(cfg, capsys, monkeypatch):
    def boom(args):
        raise gitq.GitError("repo is missing")

    monkeypatch.setattr(cli, "_repos", boom)
    assert cli.main(["repos"]) == 1
    assert capsys.readouterr().err.strip() == "error: repo is missing"


def test_a_value_error_is_a_one_line_error(cfg, capsys, monkeypatch):
    def boom(args):
        raise ValueError("bad value")

    monkeypatch.setattr(cli, "_repos", boom)
    assert cli.main(["repos"]) == 1
    assert capsys.readouterr().err.strip() == "error: bad value"


def test_the_mascot_hint_needs_a_renderer_that_can_work(cfg, monkeypatch):
    from gittok import image_model, render

    monkeypatch.setattr(render, "image_backend", lambda c: "agent")
    assert cli._illustration_can_draw(cfg) is True
    monkeypatch.setattr(render, "image_backend", lambda c: "local")
    monkeypatch.setattr(image_model, "status", lambda c: {"state": "failed"})
    assert cli._illustration_can_draw(cfg) is False
    monkeypatch.setattr(image_model, "status", lambda c: {"state": "downloading"})
    assert cli._illustration_can_draw(cfg) is True
