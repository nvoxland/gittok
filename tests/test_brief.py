import pytest

from codescroll import brief

DEFAULTS = {
    "categories": {
        "git_drama": 0.25,
        "memes": 0.20,
        "illustrated_explainers": 0.20,
        "code": 0.15,
        "interactive": 0.10,
        "cross_repo_and_recent": 0.10,
    },
    "tones": {
        "wholesome-nerdy": 0.20,
        "dry-deadpan": 0.20,
        "roast": 0.15,
        "hype": 0.15,
        "chaotic-absurd": 0.15,
        "earnest-teacher": 0.15,
    },
}
PERSONAS = ["greybeard", "penny_learns", "archivist", "meme_compiler", "paranoid_sec", "shipit_sam"]

T0 = 1771599600


def signals():
    return {
        "churn": {
            "files": {
                "90": [
                    {"path": "src/app.py", "commits": 5, "lines": 40},
                    {"path": "src/util.py", "commits": 4, "lines": 30},
                ],
                "365": [{"path": "src/app.py", "commits": 7, "lines": 60}],
            },
            "dirs": {"90": [{"path": "src", "commits": 6, "lines": 70}]},
        },
        "co_change": [
            {
                "a": "src/app.py",
                "b": "billing/invoice.py",
                "count": 4,
                "jaccard": 0.5,
                "same_dir": False,
            }
        ],
        "author_shares": {
            "by_dir": {"src": [{"author": "Alice", "commits": 5, "lines": 25, "share": 0.7}]}
        },
        "commit_times": {
            "late_night": [
                {
                    "sha": "a" * 40,
                    "author": "Alice",
                    "local_hour": 2,
                    "subject": "Speed up parsing",
                    "ts": T0 - 9000,
                }
            ]
        },
        "huge_diffs": [
            {
                "sha": "b" * 40,
                "subject": "Import fixtures",
                "author": "Bob",
                "ts": T0 - 100,
                "lines": 1200,
                "files": 1,
            }
        ],
        "new_files": [
            {
                "path": "src/new_feature.py",
                "sha": "c" * 40,
                "ts": T0 - 86400,
                "author": "Alice",
                "subject": "Add shiny",
            }
        ],
        "reverts": [
            {
                "sha": "d" * 40,
                "ts": T0 - 5000,
                "author": "Alice",
                "subject": 'Revert "Add feature flag"',
                "reverted_sha": "e" * 40,
                "reverted_subject": "Add feature flag",
            }
        ],
        "fix_chains": [
            {
                "path": "billing/invoice.py",
                "commits": [
                    {"sha": "f" * 40, "ts": T0 - 9, "subject": "fix rounding", "author": "Bob"},
                    {
                        "sha": "1" * 40,
                        "ts": T0 - 8,
                        "subject": "fix rounding again",
                        "author": "Bob",
                    },
                ],
            }
        ],
        "deleted_paths": [
            {
                "path": "src/legacy.py",
                "died_sha": "2" * 40,
                "died_ts": T0 - 9,
                "died_author": "Bob",
                "cause": "Remove legacy",
                "born_sha": "3" * 40,
                "born_ts": T0 - 99999,
                "born_author": "Alice",
                "lived_days": 20,
            }
        ],
        "commits_since": {"base": None, "count": None, "commits": []},
        "oldest_lines": [
            {
                "path": "src/util.py",
                "line": 1,
                "text": "# TODO: replace",
                "author": "Alice",
                "ts": T0 - 99999,
                "sha": "3" * 40,
            }
        ],
        "todo_ages": [
            {
                "path": "src/util.py",
                "line": 1,
                "text": "# TODO: replace",
                "tag": "TODO",
                "author": "Alice",
                "ts": T0 - 99999,
                "sha": "3" * 40,
            }
        ],
    }


def build(count=10, packet_size=4, recent=None, sig=None):
    return brief.build_brief(
        repo_signals={"fixture": {"t0": T0, "head_sha": "9" * 40, "signals": sig or signals()}},
        defaults=DEFAULTS,
        personas=PERSONAS,
        count=count,
        packet_size=packet_size,
        recent=recent or [],
    )


@pytest.mark.parametrize("count", [1, 3, 7, 10, 20])
def test_quotas_sum_to_count(count):
    b = build(count=count)
    assert sum(b.quotas.values()) == count
    assert sum(b.tone_quotas.values()) == count


@pytest.mark.parametrize("count,size", [(10, 4), (20, 5), (3, 3), (1, 4)])
def test_packets_cover_count_and_carry_leads(count, size):
    b = build(count=count, packet_size=size)
    assert sum(p.count for p in b.packets) == count
    for p in b.packets:
        assert 1 <= p.count <= size
        assert p.repo == "fixture"
        assert p.story_types, p
        assert p.leads, p
        assert len(p.tones) == p.count
        assert set(p.story_types) <= set(brief.CATEGORY_STORIES[p.category])
    assert len({p.id for p in b.packets}) == len(b.packets)


def test_unrenderable_categories_are_dropped():
    b = build(count=10)
    assert set(b.quotas) == {"git_drama", "illustrated_explainers", "code", "cross_repo_and_recent"}


def test_concrete_story_packets_suggest_haiku():
    b = build(count=20)
    for p in b.packets:
        concrete = set(p.story_types) <= brief.CONCRETE_TYPES
        assert p.suggested_model == ("haiku" if concrete else "sonnet"), p


def test_markdown_lists_packets_leads_and_recent():
    recent = [{"story_type": "rip", "hook": "RIP legacy.py"}]
    md = build(count=10, recent=recent).to_markdown()
    assert "Make 10 cards" in md
    assert "## Packet p1" in md
    assert "suggested model:" in md
    assert "src/legacy.py" in md
    assert "RIP legacy.py" in md  # recently used, avoid repeating


def test_to_dict_is_json_ready():
    import json

    d = build(count=5).to_dict()
    json.dumps(d)
    assert d["count"] == 5
    assert d["packets"][0]["id"] == "p1"


def test_multi_repo_spreads_packets():
    sig = signals()
    b = brief.build_brief(
        repo_signals={
            "a": {"t0": T0, "head_sha": "9" * 40, "signals": sig},
            "b": {"t0": T0, "head_sha": "8" * 40, "signals": sig},
        },
        defaults=DEFAULTS,
        personas=PERSONAS,
        count=10,
        packet_size=4,
        recent=[],
    )
    assert {p.repo for p in b.packets} == {"a", "b"}


def test_empty_signals_still_produce_packets():
    b = build(count=6, sig={})
    assert sum(p.count for p in b.packets) == 6
    assert all(p.leads for p in b.packets)


def test_guidance_has_rules_personas_and_budget():
    from codescroll.config import Persona

    personas = {"greybeard": Persona("greybeard", "Greybeard", "Grumpy senior. Dry.")}
    md = brief.guidance_markdown(personas)
    assert "@greybeard" in md and "Grumpy senior. Dry." in md
    assert "Real people" in md
    assert "dry-deadpan" in md
    assert "explain" in md and "excerpt" in md
    assert "MCP calls per card" in md
