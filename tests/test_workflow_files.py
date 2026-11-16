"""The workflows have one agent-neutral source (src/gittok/workflows/). Each agent program gets
full generated copies with its own last section: no program reads another program's files."""

from pathlib import Path

import pytest

from gittok import home

ROOT = Path(__file__).parents[1]
SOURCES = ROOT / "src" / "gittok" / "workflows"
HARNESS_WORDS = ("Claude", "claude", "Codex", "codex", "haiku", "sonnet", "opus", "subagent",
                 "Agent tool", "Agent call", "Bash", "mcp__", "Skill tool", "/gittok-",
                 "$gittok-", "/mcp", "Reconnect", "/loop", ".claude/", ".agents/")


_split = home.split_frontmatter


@pytest.mark.parametrize("path", sorted((SOURCES / "skills").glob("*.md"))
                         + sorted((SOURCES / "workers").glob("*.md")), ids=lambda p: p.name)
def test_the_shared_source_names_no_agent_program(path):
    text = path.read_text()
    for word in HARNESS_WORDS:
        assert word not in text, (path.name, word)


@pytest.mark.parametrize("name", home.SKILL_NAMES)
def test_each_program_gets_the_full_skill_with_its_own_last_section(name):
    meta, source = _split((SOURCES / "skills" / f"{name}.md").read_text())
    claude = home.claude_code_files()[f".claude/skills/{name}/SKILL.md"].decode()
    codex = home.codex_files()[f".agents/skills/{name}/SKILL.md"].decode()
    claude_meta, claude_body = _split(claude)
    codex_meta, codex_body = _split(codex)
    assert claude_meta == {"name": name, "description": meta["description"], "model": "sonnet"}
    assert codex_meta == {"name": name, "description": meta["description"]}
    assert source.strip() in claude_body and source.strip() in codex_body
    assert claude_body.rstrip().endswith((SOURCES / "harness" / "claude.md").read_text().rstrip())
    assert codex_body.rstrip().endswith((SOURCES / "harness" / "codex.md").read_text().rstrip())
    assert "## In Codex" not in claude and "## In Claude Code" not in codex
    assert ".claude/" not in codex and "Claude" not in codex


@pytest.mark.parametrize("name", home.WORKER_NAMES)
def test_each_program_gets_the_worker_with_its_tool_names_and_model(name):
    meta, source = _split((SOURCES / "workers" / f"{name}.md").read_text())
    claude_file = home.claude_code_files()[f".claude/agents/{name}.md"]
    claude_meta, claude_body = _split(claude_file.decode())
    codex_meta, codex_body = _split(home.codex_files()[f".agents/workers/{name}.md"].decode())
    assert claude_meta["tools"] == ", ".join(f"mcp__gittok__{t}" for t in meta["tools"])
    assert claude_meta["model"] == "inherit"  # the driver passes the tier's model when it has one
    assert codex_meta["tools"] == meta["tools"] and "model" not in codex_meta
    assert claude_body.strip() == source.strip() == codex_body.strip()


def test_the_clone_has_the_generated_files():
    files = {**home.claude_code_files(), **home.codex_files()}
    generated = {rel: data for rel, data in files.items()
                 if rel.startswith((".claude/skills/", ".claude/agents/", ".agents/"))}
    assert generated
    for rel, data in generated.items():
        assert (ROOT / rel).read_bytes() == data, (
            f"{rel} is out of date: run `uv run python -m gittok.home` in the clone")
