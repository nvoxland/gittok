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


def build(count=10, packet_size=4, recent=None, sig=None, **kw):
    return brief.build_brief(
        repo_signals={"fixture": {"t0": T0, "head_sha": "9" * 40, "signals": sig or signals()}},
        defaults=DEFAULTS,
        personas=PERSONAS,
        count=count,
        packet_size=packet_size,
        recent=recent or [],
        **kw,
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


def test_category_shares_shift_quotas_toward_favored_category():
    shares = {**DEFAULTS["categories"], "code": 0.75}
    b = build(count=20, category_shares=shares)
    assert b.quotas["code"] > build(count=20).quotas["code"]
    assert sum(b.quotas.values()) == 20


def test_floor_gives_every_category_one_slot_when_count_allows():
    shares = {**{k: 0.001 for k in DEFAULTS["categories"]}, "code": 0.995}
    b = build(count=6, category_shares=shares)
    assert all(v >= 1 for v in b.quotas.values()) and sum(b.quotas.values()) == 6
    b = build(count=10, category_shares=shares)
    assert all(v >= 1 for v in b.quotas.values()) and sum(b.quotas.values()) == 10
    assert b.quotas["code"] == 5


def test_floor_does_not_apply_when_count_is_below_category_count():
    shares = {**{k: 0.001 for k in DEFAULTS["categories"]}, "code": 0.995}
    b = build(count=3, category_shares=shares)
    assert sum(b.quotas.values()) == 3 and b.quotas["code"] == 3


def test_no_shares_keeps_default_quotas_without_floor():
    b = build(count=3, category_shares=None)
    assert b.quotas == brief.largest_remainder(DEFAULTS["categories"], 3)
    assert 0 in b.quotas.values()


def test_markdown_mix_line_default_and_learned():
    assert "Mix: default\n" in build().to_markdown()
    md = build(category_shares=DEFAULTS["categories"], evidence=42).to_markdown()
    assert "Mix: learned from 42 rewards\n" in md
    assert (
        "Mix: learned from 1 reward\n"
        in build(category_shares=DEFAULTS["categories"], evidence=1).to_markdown()
    )


def test_zero_evidence_keeps_default_mix_even_with_shares():
    shares = {**DEFAULTS["categories"], "code": 0.75}
    b = build(count=10, category_shares=shares, evidence=0)
    assert b.quotas == build(count=10).quotas
    assert "Mix: default\n" in b.to_markdown()


# ---- active rules (SPEC 10.3) and unavailable formats


def rule(type, feature, value, **kw):
    return {
        "type": type,
        "feature": feature,
        "value": value,
        "factor": kw.pop("factor", None),
        "slots": kw.pop("slots", None),
        "max_share": kw.pop("max_share", None),
        "expires_at": kw.pop("expires_at", None),
        "reason": kw.pop("reason", ""),
        "id": kw.pop("id", 1),
    }


def all_formats(b):
    return [f for p in b.packets for f in p.formats]


def test_ban_format_excludes_it_from_every_slot():
    b = build(count=20, rules=[rule("ban", "format", "code_card")])
    assert "code_card" not in all_formats(b)
    assert sum(p.count for p in b.packets) == 20


def test_ban_story_type_excludes_it_and_falls_back_in_category():
    b = build(count=20, rules=[rule("ban", "story_type", "commit_drama")])
    assert "commit_drama" not in {t for p in b.packets for t in p.story_types}
    assert sum(p.count for p in b.packets) == 20


def test_ban_every_format_of_a_category_drops_it_and_renormalizes():
    rules = [rule("ban", "format", "meme"), rule("ban", "format", "text_meme")]
    b = build(count=10, rules=rules)
    assert "memes" not in b.quotas
    assert sum(b.quotas.values()) == 10
    assert sum(p.count for p in b.packets) == 10


def test_ban_tone_and_persona_are_not_assigned():
    rules = [rule("ban", "tone", "roast"), rule("ban", "persona", "greybeard")]
    b = build(count=20, rules=rules)
    assert "roast" not in {t for p in b.packets for t in p.tones}
    assert "roast" not in b.tone_quotas
    assert "greybeard" not in {x for p in b.packets for x in p.personas}


def test_boost_format_biases_rotation_toward_it():
    base = all_formats(build(count=20)).count("hot_take")
    boosted = all_formats(build(count=20, rules=[rule("boost", "format", "hot_take", factor=10.0)]))
    assert boosted.count("hot_take") > base


def test_prefer_story_type_picks_it_more_often():
    def n(rules):
        return sum(
            1 for p in build(count=20, rules=rules).packets for t in p.story_types if t == "rip"
        )

    assert n([rule("prefer", "story_type", "rip", factor=10.0)]) >= n([])


def test_boost_repo_shifts_slots_to_that_repo():
    sig = signals()
    rs = {
        "a": {"t0": T0, "head_sha": "9" * 40, "signals": sig},
        "b": {"t0": T0, "head_sha": "8" * 40, "signals": sig},
    }
    kw = dict(
        repo_signals=rs, defaults=DEFAULTS, personas=PERSONAS, count=20, packet_size=4, recent=[]
    )
    even = {r: sum(p.count for p in brief.build_brief(**kw).packets if p.repo == r) for r in "ab"}
    b = brief.build_brief(**kw, rules=[rule("boost", "repo", "a", factor=3.0)])
    got = {r: sum(p.count for p in b.packets if p.repo == r) for r in "ab"}
    assert got["a"] > even["a"]
    assert got["a"] + got["b"] == 20


def test_focus_dir_puts_its_leads_first_and_adds_focus_line():
    sig = signals()
    sig["churn"]["files"]["90"] = [
        {"path": "other/x.py", "commits": 9, "lines": 90},
        {"path": "src/app.py", "commits": 2, "lines": 10},
    ]
    b = build(count=10, sig=sig, rules=[rule("focus", "dir", "src", slots=3, reason="sync work")])
    md = b.to_markdown()
    assert "Focus: src/ (3 slots)" in md
    hot = [pk for pk in b.packets if any("[hot_spot]" in x for x in pk.leads)]
    for pk in hot:
        leads = [x for x in pk.leads if x.startswith("[hot_spot]")]
        assert "src/" in leads[0]


def test_markdown_lists_active_rules_with_reason():
    md = build(
        count=5,
        rules=[rule("boost", "format", "quiz", factor=2.0, reason="more quizzes please")],
    ).to_markdown()
    assert "Rules:" in md
    assert "boost format=quiz" in md
    assert "more quizzes please" in md


def test_no_rules_section_without_rules():
    assert "Rules:" not in build(count=5).to_markdown()


def test_unavailable_formats_are_never_assigned_and_are_noted():
    gone = frozenset({"meme", "mascot_scene", "comic"})
    b = build(count=20, unavailable_formats=gone)
    assert not gone & set(all_formats(b))
    assert "Skipping meme, mascot_scene, comic: renderer not available" in b.to_markdown()
    assert sum(p.count for p in b.packets) == 20


# --- cross-repo leads and stories (SPEC 6.4) -------------------------------

DAY = 86400


def rc(sha, days_ago, subject, files=(), author="Alice"):
    return {
        "sha": sha * 40,
        "ts": T0 - int(days_ago * DAY),
        "author": author,
        "subject": subject,
        "files": list(files),
    }


def member(recent, group="dev", path=None):
    sig = {**signals(), "recent_commits": recent}
    return {"t0": T0, "head_sha": "9" * 40, "group": group, "path": path, "signals": sig}


def test_ripple_pairs_commits_sharing_a_ticket_within_three_days():
    members = {
        "api": member([rc("a", 2, "Add export endpoint (API-412)")]),
        "web": member([rc("b", 1, "Export button calls new endpoint API-412")]),
    }
    leads = brief.cross_leads(members)["ripple"]
    assert len(leads) == 1
    assert "api" in leads[0] and "web" in leads[0]
    assert "a" * 10 in leads[0] and "b" * 10 in leads[0]
    assert "api-412" in leads[0].lower()


def test_ripple_needs_the_commits_within_three_days():
    members = {
        "api": member([rc("a", 9, "Add export endpoint (API-412)")]),
        "web": member([rc("b", 1, "Export button calls new endpoint API-412")]),
    }
    assert brief.cross_leads(members).get("ripple", []) == []


def test_ripple_pairs_on_two_significant_subject_words():
    members = {
        "api": member([rc("a", 2, "Add the invoice export endpoint")]),
        "web": member([rc("b", 2, "Wire invoice export into the toolbar")]),
        "x": member([rc("c", 2, "Add the thing")]),
    }
    leads = brief.cross_leads(members)["ripple"]
    assert len(leads) == 1 and "invoice" in leads[0] and "export" in leads[0]


def test_ripple_ignores_one_shared_word_and_same_repo_pairs():
    members = {
        "api": member(
            [rc("a", 2, "Fix invoice rounding"), rc("c", 2, "Fix invoice rounding again")]
        ),
        "web": member([rc("b", 2, "Tweak invoice layout")]),
    }
    assert brief.cross_leads(members).get("ripple", []) == []


def test_weekly_recap_counts_and_top_subjects_per_repo_for_last_seven_days():
    members = {
        "api": member(
            [
                rc("a", 1, "Add export endpoint", ["a.py", "b.py", "c.py"]),
                rc("b", 3, "Fix retry loop", ["a.py"]),
                rc("c", 20, "Old news"),
            ]
        ),
        "web": member([rc("d", 6, "Redesign toolbar", ["t.svelte"])]),
    }
    [lead_a, lead_w] = brief.cross_leads(members)["weekly_recap"]
    assert lead_a.startswith("api: 2 commits")
    assert "Add export endpoint" in lead_a and "Old news" not in lead_a
    assert lead_a.index("Add export endpoint") < lead_a.index("Fix retry loop")  # most files first
    assert lead_w.startswith("web: 1 commit")


def test_weekly_recap_needs_commits_in_two_repos():
    members = {
        "api": member([rc("a", 1, "Add export endpoint")]),
        "web": member([rc("d", 12, "Redesign toolbar")]),
    }
    assert "weekly_recap" not in brief.cross_leads(members)


def test_cross_leads_need_two_repos():
    assert brief.cross_leads({"api": member([rc("a", 1, "x y z")])}) == {}


def test_drift_alert_shared_route_and_env_key_in_both_repos_recent_changes():
    members = {
        "api": member(
            [
                rc("a", 4, "Rename /api/invoices/export to /api/invoices/csv", ["x.py"]),
                rc("c", 3, "Read EXPORT_BATCH_SIZE from env", ["conf.py"]),
            ]
        ),
        "web": member(
            [
                rc("b", 2, "Call /api/invoices/export from toolbar", ["bar.ts"]),
                rc("d", 1, "Default EXPORT_BATCH_SIZE to 50", ["env.ts"]),
            ]
        ),
    }
    leads = brief.cross_leads(members)["drift_alert"]
    text = "\n".join(leads)
    assert "/api/invoices/export" in text and "EXPORT_BATCH_SIZE" in text
    route = next(x for x in leads if "/api/invoices/export" in x)
    assert "a" * 10 in route and "b" * 10 in route and "x.py" in route and "bar.ts" in route


def test_drift_alert_same_basename_changed_in_one_repo_but_not_since_in_the_other():
    members = {
        "api": member([rc("a", 2, "Add currency field", ["schemas/invoice.json"])]),
        "web": member([rc("b", 20, "Add invoice form", ["src/types/invoice.json"])]),
    }
    [lead] = brief.cross_leads(members)["drift_alert"]
    assert "invoice.json" in lead
    assert "api" in lead and "web" in lead and "a" * 10 in lead and "b" * 10 in lead
    assert "not changed since" in lead


def test_drift_alert_ignores_generic_basenames_and_near_simultaneous_changes():
    members = {
        "api": member([rc("a", 2, "bump", ["package.json", "README.md", "schemas/invoice.json"])]),
        "web": member(
            [rc("b", 20, "bump", ["package.json", "README.md"]), rc("c", 1, "x", ["invoice.json"])]
        ),
    }
    assert "drift_alert" not in brief.cross_leads(members)


@pytest.fixture
def two_repos(tmp_path):
    from tests.fixture_repo import build_history_repo

    api = build_history_repo(
        tmp_path / "api",
        [
            ("Initial", {"conf.py": "SYNC_BATCH_SIZE = 10\nSYNC_CHUNK_SIZE = 5\n"}, "2026-02-01T10:00:00+00:00"),  # noqa: E501
            ("Rename SYNC_BATCH_SIZE to SYNC_CHUNK_SIZE", {"conf.py": "SYNC_CHUNK_SIZE = 10\n"}, "2026-02-20T10:00:00+00:00"),  # noqa: E501
        ],
    )  # fmt: skip
    web = build_history_repo(
        tmp_path / "web",
        [
            ("Initial", {"src/env.ts": "export const SYNC_BATCH_SIZE = 10;\n", "a.ts": "1\n"}, "2026-02-01T10:00:00+00:00"),  # noqa: E501
            ("Tweak toolbar", {"a.ts": "2\n"}, "2026-02-21T10:00:00+00:00"),
        ],
    )  # fmt: skip
    return api, web


def analyzed(tmp_path, api, web):
    from codescroll import db, signals
    from codescroll.config import AnalysisSettings, Repo

    conn = db.open_db(tmp_path / "t.db")
    out = {}
    for name, fr in (("api", api), ("web", web)):
        repo = Repo(name=name, path=fr.path, ref="main", group="dev")
        out[name] = signals.analyze(conn, repo, AnalysisSettings())
    conn.close()
    return out


def test_drift_alert_finds_identifier_still_used_in_the_other_repo_via_git_grep(
    tmp_path, two_repos
):
    members = analyzed(tmp_path, *two_repos)
    leads = brief.cross_leads(members)["drift_alert"]
    [lead] = [x for x in leads if "SYNC_BATCH_SIZE" in x]
    assert "api" in lead and "web" in lead
    assert "src/env.ts" in lead  # where web still references it
    assert two_repos[0].shas["1"][:10] in lead  # the api commit that changed it
    assert "possible" in lead


def test_drift_grep_is_bounded_to_five_identifiers_per_repo(tmp_path, two_repos, monkeypatch):
    from codescroll import gitq

    members = analyzed(tmp_path, *two_repos)
    api_recent = members["api"]["signals"]["recent_commits"]
    api_recent[:] = [
        rc(c, 1, f"Change KEY_NUMBER_{c.upper()} for sync") for c in "abcdefgh"
    ] + api_recent
    calls = []
    real = gitq.run_bytes

    def spy(repo, *args, **kw):
        if args and args[0] == "grep":
            calls.append(args)
        return real(repo, *args, **kw)

    monkeypatch.setattr(gitq, "run_bytes", spy)
    brief.cross_leads(members)
    assert 1 <= len(calls) <= 5  # one other repo, so at most 5 greps in total


def cross_members(group_a="dev", group_b="dev"):
    return {
        "api": member([rc("a", 2, "Add export endpoint (API-412)", ["x.py"])], group=group_a),
        "web": member([rc("b", 1, "Export button for endpoint API-412", ["y.ts"])], group=group_b),
    }


def build_cross(members=None, count=10, **kw):
    return brief.build_brief(
        repo_signals=members or cross_members(),
        defaults=DEFAULTS,
        personas=PERSONAS,
        count=count,
        packet_size=4,
        recent=[],
        **kw,
    )


def cross_packets(b):
    return [p for p in b.packets if set(p.story_types) & set(brief.CROSS_STORIES)]


def test_cross_repo_slots_become_a_multi_repo_sonnet_packet():
    b = build_cross(count=20)
    assert sum(p.count for p in b.packets) == 20
    assert sum(b.quotas.values()) == 20
    [pk] = cross_packets(b)
    assert pk.repos == ["api", "web"] and pk.repo == "api"
    assert pk.suggested_model == "sonnet"
    assert "cross_repo_and_recent" in pk.categories
    assert set(pk.story_types) <= set(brief.CROSS_STORIES)
    assert set(pk.formats) <= set(brief.CROSS_FORMATS)
    assert len(pk.formats) == len(pk.tones) == len(pk.personas) == pk.count
    assert any("api-412" in x.lower() and "api" in x and "web" in x for x in pk.leads)
    assert any(x.startswith("[ripple]") for x in pk.leads)
    plain = [p for p in b.packets if p not in cross_packets(b)]
    assert all(p.repos == [p.repo] for p in plain)


def test_cross_packet_markdown_names_all_repos():
    md = build_cross(count=20).to_markdown()
    assert "from repos `api`, `web`" in md
    assert "from repo `api`" in md  # ordinary packets keep the old header


def test_no_cross_stories_without_a_group_of_two_repos_in_the_brief():
    assert cross_packets(build_cross(cross_members("dev", "other"), count=20)) == []
    assert cross_packets(build_cross(cross_members("dev", None), count=20)) == []
    one = {"api": cross_members()["api"]}
    assert cross_packets(build_cross(one, count=20)) == []


def test_explicit_groups_argument_overrides_analysis_group():
    members = cross_members(None, None)
    assert cross_packets(build_cross(members, count=20)) == []
    assert cross_packets(build_cross(members, count=20, groups={"g": ["api", "web"]}))


def test_banned_cross_story_types_are_not_assigned():
    rules = [
        {"type": "ban", "feature": "story_type", "value": t, "reason": "x"}
        for t in brief.CROSS_STORIES
    ]
    assert cross_packets(build_cross(count=20, rules=rules)) == []


def test_cross_slots_fall_back_when_no_cross_lead_exists():
    members = {
        "api": member([rc("a", 40, "Old thing alpha")]),
        "web": member([rc("b", 40, "Other beta")]),
    }
    b = build_cross(members, count=20)
    assert cross_packets(b) == []
    assert sum(p.count for p in b.packets) == 20


# ---- rule semantics shared with the slotter (docs/learning.md section 10)


def two(sig=None, groups=("dev", "ops")):
    sig = sig or signals()
    return {
        "a": {"t0": T0, "head_sha": "9" * 40, "group": groups[0], "signals": sig},
        "b": {"t0": T0, "head_sha": "8" * 40, "group": groups[1], "signals": sig},
    }


def build2(count=20, rs=None, **kw):
    return brief.build_brief(
        repo_signals=rs or two(),
        defaults=DEFAULTS,
        personas=PERSONAS,
        count=count,
        packet_size=4,
        recent=[],
        **kw,
    )


def test_ban_repo_and_group_remove_the_repo():
    b = build2(rules=[rule("ban", "repo", "a")])
    assert {p.repo for p in b.packets} == {"b"}
    b = build2(rules=[rule("ban", "group", "ops")])
    assert {r for p in b.packets for r in p.repos} == {"a"}
    with pytest.raises(ValueError):
        build2(rules=[rule("ban", "repo", "a"), rule("ban", "repo", "b")])


def test_ban_dir_uses_path_prefix_semantics():
    sig = signals()
    sig["churn"]["files"]["90"] = [
        {"path": "src/app.py", "commits": 5, "lines": 40},
        {"path": "lib/src/x.py", "commits": 4, "lines": 30},
    ]
    b = build(count=20, sig=sig, rules=[rule("ban", "dir", "src/")])
    leads = [x for p in b.packets for x in p.leads]
    assert not any("src/app.py" in x.split("lib/src")[0] and "lib/src" not in x for x in leads)
    assert not any(x.startswith("[hot_spot] src/app.py") for x in leads)
    assert any("lib/src/x.py" in x for x in leads)


def test_focus_dir_matches_nested_dirs_not_lookalikes():
    sig = signals()
    sig["churn"]["files"]["90"] = [
        {"path": "lib/src/x.py", "commits": 9, "lines": 90},
        {"path": "src/api/app.py", "commits": 2, "lines": 10},
    ]
    b = build(count=10, sig=sig, rules=[rule("focus", "dir", "src", slots=3)])
    for pk in b.packets:
        hot = [x for x in pk.leads if x.startswith("[hot_spot]")]
        if hot:
            assert "src/api/app.py" in hot[0]


def test_ban_visual_kind_and_template_map_to_formats():
    fmts = all_formats(build(count=30, rules=[rule("ban", "visual_kind", "meme")]))
    assert "meme" not in fmts and "text_meme" in fmts
    fmts = all_formats(build(count=30, rules=[rule("ban", "visual_kind", "template")]))
    assert not set(fmts) & {"iceberg", "hot_take", "group_chat", "breaking_news", "thread"}
    fmts = all_formats(build(count=30, rules=[rule("ban", "template", "iceberg")]))
    assert "iceberg" not in fmts and "hot_take" in fmts


def test_ban_difficulty_drops_interactive_slots():
    b = build(count=20, rules=[rule("ban", "difficulty", "3")])
    assert "interactive" not in b.quotas
    assert sum(p.count for p in b.packets) == 20
    assert "quiz" not in all_formats(b)


def test_ban_one_interactive_story_type_keeps_the_others():
    b = build(count=40, rules=[rule("ban", "interactive", "guess_who")])
    types = {t for p in b.packets for t in p.story_types}
    assert "guess_who" not in types and "quiz" in types
    b = build(count=40, rules=[rule("ban", "interactive", "quiz")])
    assert "quiz" not in {t for p in b.packets for t in p.story_types}


def test_limit_format_story_type_and_tone_are_share_ceilings():
    def n(b, pred):
        return sum(1 for p in b.packets for x in zip(p.formats, p.tones, strict=True) if pred(x))

    base = build(count=40)
    assert n(base, lambda x: x[0] == "meme") > 2
    b = build(count=40, rules=[rule("limit", "format", "meme", max_share=0.05)])
    assert n(b, lambda x: x[0] == "meme") <= 2
    assert sum(p.count for p in b.packets) == 40
    b = build(count=20, rules=[rule("limit", "tone", "roast", max_share=0.05)])
    assert n(b, lambda x: x[1] == "roast") <= 1
    assert sum(b.tone_quotas.values()) == 20
    b = build(count=40, rules=[rule("limit", "story_type", "rip", max_share=0.0)])
    assert "rip" not in {t for p in b.packets for t in p.story_types}


def test_limit_repo_caps_that_repos_slots():
    b = build2(count=20, rules=[rule("limit", "repo", "a", max_share=0.25)])
    got = sum(p.count for p in b.packets if p.repo == "a")
    assert got <= 5
    assert sum(p.count for p in b.packets) == 20


def test_boost_without_stored_factor_is_neutral():
    assert brief._factors([rule("boost", "format", "hot_take")], "format") == {"hot_take": 1.0}
    assert brief._factors(
        [
            rule("boost", "format", "hot_take", factor=3.0),
            rule("prefer", "format", "hot_take", factor=2.0),
        ],
        "format",
    ) == {"hot_take": 6.0}


def test_focus_on_other_features_biases_like_boost():
    base = all_formats(build(count=20)).count("hot_take")
    got = all_formats(build(count=20, rules=[rule("focus", "format", "hot_take", slots=8)]))
    assert got.count("hot_take") > base


def test_boost_group_shifts_slots_to_its_repos():
    even = sum(p.count for p in build2().packets if p.repo == "a")
    b = build2(rules=[rule("boost", "group", "dev", factor=4.0)])
    assert sum(p.count for p in b.packets if p.repo == "a") > even


# ---- ripple and drift lead quality


def test_ripple_ignores_bare_pr_numbers_and_hyphenated_common_words():
    members = {
        "api": member([rc("a", 1, "Fix bug (#12) in pre-commit hook")]),
        "web": member([rc("b", 1, "Add toolbar (#12) with pre-commit follow-up")]),
    }
    assert brief.cross_leads(members).get("ripple", []) == []
    members = {
        "api": member([rc("a", 1, "Make read-only opt-in set-up")]),
        "web": member([rc("b", 1, "Wire read-only opt-in set-up page")]),
    }
    assert brief.cross_leads(members).get("ripple", []) == []


def test_ripple_still_pairs_on_jira_ids():
    members = {
        "api": member([rc("a", 1, "PAY-77 add endpoint")]),
        "web": member([rc("b", 1, "PAY-77 call it")]),
    }
    [lead] = brief.cross_leads(members)["ripple"]
    assert "pay-77" in lead.lower()


def test_drift_grep_matches_whole_words_only(tmp_path):
    from tests.fixture_repo import build_history_repo

    api = build_history_repo(
        tmp_path / "api",
        [("Initial", {"c.py": "A = 1\n"}, "2026-02-01T10:00:00+00:00")],
    )
    web = build_history_repo(
        tmp_path / "web",
        [("Initial", {"env.ts": "X_SYNC_BATCH_SIZE = 1; fetch('/api/users')\n"}, "2026-02-01T10:00:00+00:00")],  # noqa: E501
    )  # fmt: skip
    members = {
        "api": member(
            [rc("a", 1, "Change SYNC_BATCH_SIZE and /api/user", ["c.py"])], path=api.path
        ),
        "web": member([rc("b", 3, "Tweak toolbar", ["bar.ts"])], path=web.path),
    }
    members["web"]["head_sha"] = web.shas["0"]
    leads = brief.cross_leads(members).get("drift_alert", [])
    assert not any("SYNC_BATCH_SIZE" in x or "/api/user " in x for x in leads), leads


def test_drift_since_uses_the_full_changed_file_list(tmp_path):
    from tests.fixture_repo import build_history_repo

    files = {f"f{i}.ts": "1\n" for i in range(25)}
    files["env.ts"] = "SYNC_BATCH_SIZE = 1\n"
    web = build_history_repo(
        tmp_path / "web",
        [
            ("Initial", files, "2026-02-01T10:00:00+00:00"),
            ("Touch env", {"env.ts": "SYNC_BATCH_SIZE = 2\n"}, "2026-02-20T10:00:00+00:00"),
        ],
    )
    # the truncated recent_commits list (20 files) misses env.ts
    touched = [f"f{i}.ts" for i in range(20)]
    api = build_history_repo(
        tmp_path / "api", [("Initial", {"c.py": "A = 1\n"}, "2026-02-01T10:00:00+00:00")]
    )
    members = {
        "api": member([rc("a", 5, "Rename SYNC_BATCH_SIZE", ["c.py"])], path=api.path),
        "web": member([rc("b", 2, "Touch env", touched)], path=web.path),
    }
    members["web"]["head_sha"] = web.shas["1"]
    leads = brief.cross_leads(members).get("drift_alert", [])
    assert not any("possible drift: SYNC_BATCH_SIZE" in x for x in leads), leads


def test_fix_leads_name_parent_and_changed_lines_when_known():
    sig = signals()
    sig["fix_hunks"] = [
        {"sha": "f" * 40, "path": "billing/invoice.py", "parent": "3" * 40, "ranges": [[10, 12]]},
        {
            "sha": "1" * 40,
            "path": "billing/invoice.py",
            "parent": "4" * 40,
            "ranges": [[7, 7], [20, 21]],
        },
    ]
    bug = brief.leads_for("spot_the_bug", sig, T0)
    assert "visual commit (first parent) 3333333333, changed lines 10-12" in bug[0]
    assert "visual commit (first parent) 4444444444, changed lines 7, 20-21" in bug[1]
    after = brief.leads_for("before_after", sig, T0)
    assert any("before: 4444444444, changed lines 7, 20-21" in x for x in after)


def test_summary_and_packet_markdown_split_the_brief():
    recent = [{"story_type": "rip", "hook": "RIP legacy.py"}]
    b = build(count=10, recent=recent)
    summary = b.summary_markdown()
    assert "Make 10 cards" in summary and "Mix:" in summary
    assert "## Packet" not in summary and "RIP legacy.py" not in summary
    p2 = b.packet_markdown("p2")
    assert p2.startswith("## Packet p2")
    assert "## Packet p1" not in p2
    assert "RIP legacy.py" in p2  # each writer sees what not to repeat
    assert b.to_markdown().count("## Packet") == len(b.packets)
    with pytest.raises(KeyError):
        b.packet_markdown("p99")
