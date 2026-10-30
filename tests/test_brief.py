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
        allowed = {t for c in p.categories for t in brief.CATEGORY_STORIES[c]}
        assert set(p.story_types) <= allowed
    assert len({p.id for p in b.packets}) == len(b.packets)


def test_interactive_category_is_renderable():
    b = build(count=10)
    assert set(b.quotas) == set(DEFAULTS["categories"])
    assert b.quotas["interactive"] == 1


def test_interactive_slots_use_quiz_format_and_sonnet_packets():
    b = build(count=20, packet_size=4)
    quiz = [p for p in b.packets if "interactive" in p.categories]
    assert quiz
    assert sum(f == "quiz" for p in b.packets for f in p.formats) == b.quotas["interactive"]
    for p in quiz:
        assert p.suggested_model == "sonnet"
    for p in b.packets:
        if "quiz" in p.formats:
            assert p.suggested_model == "sonnet"


def test_interactive_story_types_are_known_to_the_validator():
    from codescroll import validator

    assert set(brief.CATEGORY_STORIES["interactive"]) == validator.INTERACTIVE_STORIES
    assert brief.CATEGORY_FORMATS["interactive"] == ("quiz",)


def test_spot_the_bug_leads_point_at_fix_commits():
    leads = brief.leads_for("spot_the_bug", signals(), T0)
    assert leads and "billing/invoice.py" in leads[0] and "parent" in leads[0]


def test_concrete_story_packets_suggest_haiku():
    b = build(count=20)
    for p in b.packets:
        cheap = set(p.story_types) <= brief.CONCRETE_TYPES and set(p.formats) <= brief.HAIKU_FORMATS
        assert p.suggested_model == ("haiku" if cheap else "sonnet"), p


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


def test_noise_paths_are_not_leads():
    sig = signals()
    sig["churn"]["files"]["90"] = [
        {"path": "web/package-lock.json", "commits": 9, "lines": 9000},
        {"path": ".beads/issues.jsonl", "commits": 9, "lines": 900},
        {"path": "uv.lock", "commits": 9, "lines": 900},
        {"path": "dist/app.min.js", "commits": 9, "lines": 900},
        {"path": "src/app.py", "commits": 2, "lines": 10},
    ]
    leads = brief.leads_for("hot_spot", sig, T0)
    assert leads[0].startswith("src/app.py")
    assert not any("lock" in x or ".beads" in x or ".min." in x for x in leads)


def test_explainers_skip_test_files():
    sig = signals()
    sig["churn"]["files"]["365"] = [
        {"path": "test/foo/api_test.clj", "commits": 9, "lines": 9},
        {"path": "tests/test_x.py", "commits": 9, "lines": 9},
        {"path": "src/foo/api.clj", "commits": 3, "lines": 9},
    ]
    assert brief.leads_for("what_it_does", sig, T0) == [
        "src/foo/api.clj (3 commits in the last year)"
    ]


def test_ancient_stories_need_old_material():
    sig = signals()
    young = T0 - 5 * 86400
    old = T0 - 400 * 86400
    sig["todo_ages"] = [
        {
            "path": "a.py",
            "line": 1,
            "text": "# TODO new",
            "tag": "TODO",
            "author": "A",
            "ts": young,
            "sha": "1" * 40,
        },
        {
            "path": "b.py",
            "line": 2,
            "text": "# TODO old",
            "tag": "TODO",
            "author": "A",
            "ts": old,
            "sha": "2" * 40,
        },
    ]
    sig["oldest_lines"] = [dict(sig["todo_ages"][0])]
    assert [x.split(":")[0] for x in brief.leads_for("ancient_todo", sig, T0)] == ["b.py"]
    assert brief.leads_for("archaeology", sig, T0) == []


def test_todo_leads_must_be_comments_not_prose():
    sig = signals()
    old = T0 - 400 * 86400
    sig["todo_ages"] = [
        {
            "path": "SPEC.md",
            "line": 1,
            "text": "| **Ancient TODO** | Oldest open TODO |",
            "tag": "TODO",
            "author": "A",
            "ts": old,
            "sha": "1" * 40,
        },
        {
            "path": "x.py",
            "line": 1,
            "text": "x = 1  # FIXME: overflow",
            "tag": "FIXME",
            "author": "A",
            "ts": old,
            "sha": "2" * 40,
        },
        {
            "path": "y.clj",
            "line": 1,
            "text": ";; TODO handle nil",
            "tag": "TODO",
            "author": "A",
            "ts": old,
            "sha": "3" * 40,
        },
    ]
    paths = [x.split(":")[0] for x in brief.leads_for("ancient_todo", sig, T0)]
    assert paths == ["x.py", "y.clj"]


def test_rip_and_new_arrival_skip_noise():
    sig = signals()
    sig["deleted_paths"][0]["path"] = "web/package-lock.json"
    sig["new_files"][0]["path"] = ".beads/issues.jsonl"
    assert brief.leads_for("rip", sig, T0) == []
    assert brief.leads_for("new_arrival", sig, T0) == []


def test_each_category_is_split_across_repos():
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
    drama = {p.repo for p in b.packets if "git_drama" in p.categories}
    assert drama == {"a", "b"}


def test_packets_are_few_and_full():
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
    # At most one partly-filled packet per (repo, model tier).
    assert len(b.packets) <= 6
    groups = {}
    for p in b.packets:
        groups.setdefault((p.repo, p.suggested_model), []).append(p.count)
    for counts in groups.values():
        assert all(c == 4 for c in counts[:-1])


def test_build_brief_without_repos_raises_clear_error():
    with pytest.raises(ValueError, match="no repos"):
        brief.build_brief(
            repo_signals={},
            defaults=DEFAULTS,
            personas=PERSONAS,
            count=3,
            packet_size=4,
            recent=[],
        )


def test_build_brief_without_personas_uses_default_list():
    b = brief.build_brief(
        repo_signals={"fixture": {"t0": T0, "head_sha": "9" * 40, "signals": signals()}},
        defaults=DEFAULTS,
        personas=[],
        count=4,
        packet_size=4,
        recent=[],
    )
    assert all(p.personas for p in b.packets)


def test_code_and_explainer_leads_skip_docs():
    sig = signals()
    sig["churn"]["files"]["365"] = [
        {"path": "AGENTS.md", "commits": 9, "lines": 9},
        {"path": "docs/guide.rst", "commits": 9, "lines": 9},
        {"path": "NOTES.txt", "commits": 9, "lines": 9},
        {"path": "src/real.py", "commits": 2, "lines": 9},
    ]
    for t in ("snippet_callouts", "cursed_clever_line", "what_it_does", "journey", "analogy"):
        assert brief.leads_for(t, sig, T0) == ["src/real.py (2 commits in the last year)"], t


def test_fix_chains_on_noise_paths_are_not_leads():
    sig = signals()
    sig["fix_chains"][0]["path"] = ".beads/issues.jsonl"
    leads = brief.leads_for("commit_drama", sig, T0)
    assert not any(".beads" in x for x in leads)


def test_before_after_skips_noise_fix_chains():
    sig = signals()
    sig["fix_chains"][0]["path"] = ".beads/issues.jsonl"
    assert not any(".beads" in x for x in brief.leads_for("before_after", sig, T0))


def test_packets_carry_one_allowed_format_per_card():
    b = build(count=20)
    for p in b.packets:
        assert len(p.formats) == p.count == len(p.tones) == len(p.personas)
        allowed = {f for c in p.categories for f in brief.CATEGORY_FORMATS[c]}
        assert set(p.formats) <= allowed, p


def test_formats_rotate_in_a_ten_card_brief():
    from collections import Counter

    b = build(count=10)
    counts = Counter(f for p in b.packets for f in p.formats)
    assert max(counts.values()) <= 2, counts


def _illustration_cost(b):
    return sum(brief.ILLUSTRATION_COST.get(f, 0) for p in b.packets for f in p.formats)


def test_illustration_budget_is_respected():
    big = build(count=20)
    assert _illustration_cost(big) > 0  # the budget test below is meaningful
    for budget in (0, 1, 2, 4):
        b = brief.build_brief(
            repo_signals={"fixture": {"t0": T0, "head_sha": "9" * 40, "signals": signals()}},
            defaults=DEFAULTS,
            personas=PERSONAS,
            count=20,
            packet_size=4,
            recent=[],
            max_illustrations=budget,
        )
        assert _illustration_cost(b) <= budget, budget
        assert sum(p.count for p in b.packets) == 20


def test_illustrated_packets_need_sonnet():
    b = build(count=20)
    for p in b.packets:
        if set(p.formats) & (set(brief.ILLUSTRATION_COST) | {"thread", "diagram", "day_in_life"}):
            assert p.suggested_model == "sonnet", p


def test_cheap_formats_on_concrete_stories_use_haiku():
    sig = signals()
    b = brief.build_brief(
        repo_signals={"fixture": {"t0": T0, "head_sha": "9" * 40, "signals": sig}},
        defaults={"categories": {"memes": 1.0}, "tones": DEFAULTS["tones"]},
        personas=PERSONAS,
        count=7,
        packet_size=7,
        recent=[],
    )
    models = {p.suggested_model for p in b.packets if set(p.story_types) <= brief.CONCRETE_TYPES}
    assert models <= {"haiku"} and models
    assert all(set(p.formats) <= {"meme", "text_meme"} for p in b.packets)


def test_markdown_lists_formats_per_packet():
    md = build(count=10).to_markdown()
    assert "- formats, one per card: " in md


def _personas():
    from codescroll.config import Persona

    return {"greybeard": Persona("greybeard", "Greybeard", "Grumpy senior. Dry.")}


def test_guidance_includes_only_requested_format_sections():
    md = brief.guidance_markdown(_personas(), formats=["flags"])
    assert '"template": "flags"' in md
    assert '"kind": "meme"' not in md and '"kind": "comic"' not in md
    assert "Real people" in md  # base guidance stays
    assert "{" + "personas}" not in md


def test_guidance_without_formats_arg_includes_all_sections():
    md = brief.guidance_markdown(_personas())
    for fmt in (*{f for fs in brief.CATEGORY_FORMATS.values() for f in fs},):
        assert f"### Format: `{fmt}`" in md, fmt


def test_base_guidance_explains_account_and_points_to_formats():
    md = brief.guidance_markdown(_personas(), formats=[])
    assert "`account`" in md and "repo:path" in md
    assert "Format:" not in md  # no format sections


def test_meme_section_lists_templates_with_line_counts():
    from codescroll.config import MemeTemplate

    tpl = {"drake": MemeTemplate("drake", 2, "top = rejected, bottom = preferred")}
    md = brief.guidance_markdown(_personas(), formats=["meme"], meme_templates=tpl)
    assert "`drake`" in md and "2 lines" in md and "top = rejected, bottom = preferred" in md


def test_illustration_sections_name_mascots_and_forbid_text():
    from codescroll.config import Mascot

    mascots = {"otter": Mascot("otter", "storefront", "style", 1)}
    for fmt in ("mascot_scene", "comic"):
        md = brief.guidance_markdown(_personas(), formats=[fmt], mascots=mascots)
        assert "`otter`" in md, fmt
        assert "no text" in md.lower(), fmt
