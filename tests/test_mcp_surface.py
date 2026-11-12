"""The MCP tool surface is consistent: one name per idea, one error convention, full docs."""

import pytest
from mcp import Client

from gittok import mcp_server
from tests.conftest import make_config

pytestmark = pytest.mark.anyio


@pytest.fixture
async def tools(fixture_repo, tmp_path):
    cfg = make_config(fixture_repo, tmp_path)
    async with Client(mcp_server.build_server(lambda: cfg)) as client:
        yield {t.name: t for t in (await client.list_tools()).tools}


def _params(tool) -> dict:
    return tool.input_schema.get("properties") or {}


async def test_a_cap_argument_is_always_called_limit(tools):
    other = {"max", "max_hits", "max_results", "n", "top", "cap"}
    bad = [f"{name}({p})" for name, t in tools.items() for p in _params(t) if p in other]
    assert not bad, bad
    for name in ("scout_status", "git_log", "git_grep", "recent_cards", "defined_where",
                 "who_calls", "what_calls", "symbol_history", "facts_for"):  # fmt: skip
        assert "limit" in _params(tools[name]), name


async def test_the_taste_tool_and_the_repo_profile_tool_have_distinct_names(tools):
    assert "get_taste_profile" in tools and "get_profile" not in tools
    assert "repo" in _params(tools["save_profile"])
    assert "repo" in tools["save_profile"].description


async def test_every_tool_documents_every_argument(tools):
    """An agent reads only the description: each argument must be named in it."""
    missing = [
        f"{name}: {p}"
        for name, t in tools.items()
        for p in _params(t)
        if p not in (t.description or "")
    ]
    assert not missing, missing
    assert all((t.description or "").strip() for t in tools.values())


def _dummy(schema: dict):
    kind = schema.get("type") or next(
        (s.get("type") for s in schema.get("anyOf", []) if s.get("type") != "null"), "string"
    )
    return {"string": "x", "integer": 1, "number": 1, "boolean": False, "array": [], "object": {}}[
        kind
    ]


async def test_an_unknown_repo_is_an_error_result_in_every_repo_tool(fixture_repo, tmp_path):
    """One error convention: the call fails with one line that names the cause. No tool
    answers a bad repo with a normal result that holds an `error` key."""
    cfg = make_config(fixture_repo, tmp_path)
    async with Client(mcp_server.build_server(lambda: cfg)) as client:
        for t in (await client.list_tools()).tools:
            props = _params(t)
            if "repo" not in props:
                continue
            args = {p: _dummy(props[p]) for p in t.input_schema.get("required", [])}
            args["repo"] = "nope"
            if t.name == "set_mascot":
                args["style"] = "a style"
            res = await client.call_tool(t.name, args)
            assert res.is_error, (t.name, res.content)
            text = res.content[0].text
            assert "unknown repo" in text.lower() and "nope" in text, (t.name, text)
            assert "fixture" in text, (t.name, text)  # it lists the known repos
            assert "\n" not in text and "Traceback" not in text, (t.name, text)
