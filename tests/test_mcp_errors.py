"""A failing MCP tool tells the agent the cause in one line: no traceback, no home paths."""

import json
import sqlite3
import subprocess
from pathlib import Path

import pytest
from mcp import Client

from gittok import db, mcp_server
from gittok.config import ConfigError, Repo
from tests.conftest import make_config

pytestmark = pytest.mark.anyio


def error_text(result) -> str:
    assert result.is_error, result.content
    text = result.content[0].text
    assert "Traceback" not in text and "\n" not in text.strip()
    return text


@pytest.fixture
def empty_repo(tmp_path) -> Path:
    """A git repo with no commits."""
    path = tmp_path / "empty-repo"
    subprocess.run(["git", "init", "-q", "-b", "main", str(path)], check=True)
    return path


def _fast_connect(monkeypatch):
    """Make a busy database fail at once instead of after the 5 s busy timeout."""
    real = db.connect

    def connect(path):
        conn = real(path)
        conn.execute("PRAGMA busy_timeout=20")
        return conn

    monkeypatch.setattr(db, "connect", connect)


async def test_locked_database_names_the_cause(fixture_repo, tmp_path, monkeypatch):
    cfg = make_config(fixture_repo, tmp_path)
    db_file = cfg.settings.data_dir / "gittok.db"
    db.open_db(db_file).close()
    _fast_connect(monkeypatch)
    holder = sqlite3.connect(db_file, isolation_level=None)
    holder.execute("BEGIN EXCLUSIVE")
    try:
        server = mcp_server.build_server(lambda: cfg)
        async with Client(server) as client:
            res = await client.call_tool(
                "add_rule",
                {"type": "ban", "feature": "format", "value": "meme", "reason": "no memes"},
            )
    finally:
        holder.rollback()
        holder.close()
    text = error_text(res)
    assert "database is locked" in text and "try again" in text.lower()
    assert str(tmp_path) not in text


async def test_empty_repo_tools_name_the_cause(fixture_repo, empty_repo, tmp_path):
    cfg = make_config(fixture_repo, tmp_path)
    cfg.repos.clear()
    cfg.repos["blank"] = Repo(name="blank", path=empty_repo, ref="HEAD")
    server = mcp_server.build_server(lambda: cfg)
    calls = [
        ("get_brief", {"count": 3}),
        ("git_log", {"repo": "blank"}),
        ("read_file", {"repo": "blank", "path": "README.md"}),
        ("list_dir", {"repo": "blank"}),
        ("git_grep", {"repo": "blank", "pattern": "x"}),
        ("survey_repo", {"repo": "blank"}),
    ]
    async with Client(server) as client:
        for tool, args in calls:
            text = error_text(await client.call_tool(tool, args))
            assert "blank" in text and "no commits" in text, (tool, text)
            assert str(empty_repo.parent) not in text, (tool, text)
        # scout_status skips a repo it cannot read and says why.
        res = await client.call_tool("scout_status", {})
        assert not res.is_error
        skipped = json.loads(res.content[0].text)["skipped"]
        assert [s["repo"] for s in skipped] == ["blank"] and "no commits" in skipped[0]["error"]


async def test_config_error_reaches_the_caller(fixture_repo, tmp_path):
    def broken():
        raise ConfigError(f"invalid YAML in {tmp_path}/local/repos.yaml: mapping values")

    server = mcp_server.build_server(broken)
    async with Client(server) as client:
        text = error_text(await client.call_tool("list_repos", {}))
    assert "invalid YAML" in text and "repos.yaml" in text


async def test_unexpected_error_names_its_type_and_hides_home(fixture_repo, tmp_path, monkeypatch):
    cfg = make_config(fixture_repo, tmp_path)
    home = str(Path.home())

    def boom(*a, **k):
        raise RuntimeError(f"cannot read {home}/secret/place/file.txt")

    monkeypatch.setattr(mcp_server.supply, "feed_health", boom)
    server = mcp_server.build_server(lambda: cfg)
    async with Client(server) as client:
        text = error_text(await client.call_tool("feed_health", {}))
    assert "feed_health" in text and "RuntimeError" in text and "cannot read" in text
    assert home not in text and "~/secret/place/file.txt" in text


async def test_bad_arguments_name_the_argument(fixture_repo, tmp_path):
    cfg = make_config(fixture_repo, tmp_path)
    server = mcp_server.build_server(lambda: cfg)
    async with Client(server) as client:
        text = error_text(await client.call_tool("git_show", {"repo": "fixture"}))
    assert "commit" in text
