"""The writer instructions name the facts step: writers skipped the fact tools."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WRITER = (ROOT / ".claude" / "agents" / "gittok-writer.md").read_text()
GUIDE = (ROOT / "src" / "gittok" / "prompts" / "generate.md").read_text()


def test_writer_lists_facts_from_materials_in_every_card():
    assert "Facts in these lines" in WRITER
    assert "`facts`" in WRITER and "every card" in WRITER


def test_guidance_research_tools_include_the_fact_tools():
    budget = GUIDE.split("## Research budget", 1)[1]
    assert "Use only the GitTok MCP tools" in budget
    first = budget.split("\n- ", 2)[1]
    for tool in ("facts_for", "who_calls", "defined_where"):
        assert tool in first


def test_writer_does_not_prescribe_the_stripped_learn_prefix():
    assert '"After this card you know ...":' not in WRITER  # the old template
    assert "Do not start it with" in WRITER


def test_guidance_says_to_list_facts_in_every_card():
    assert "Facts in these lines" in GUIDE
