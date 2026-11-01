"""Helpers that build card specs citing real fixture-repo content."""

from __future__ import annotations

import copy

LEARN = "After this card you know how the fixture repo's code works."


def explain(ident: str | None = None) -> str:
    """An explain text that clears the floor; `ident` must occur in the cited code."""
    ident = ident or "main()` or `parse(s)` or `Fixture"
    return (
        f"The code in question is `{ident}`, and it does one small job: it takes its input, "
        "does the work in a single pass, and hands the result back to its caller.\n\n"
        "Nothing else in the module depends on how it does that, which is why the "
        "history around it stays so quiet and why a reader can trust it."
    )


def example_card(fixture_repo, **overrides) -> dict:
    s = fixture_repo.shas
    card = {
        "story_type": "commit_drama",
        "format": "code_card",
        "persona": "paranoid_sec",
        "tone": "dry-deadpan",
        "repos": ["fixture"],
        "dirs": ["billing"],
        "difficulty": 2,
        "hook": "Rounding was fixed twice in two days.",
        "learn": LEARN,
        "visual": {
            "kind": "code",
            "repo": "fixture",
            "path": "billing/invoice.py",
            "commit": s["invoice_add"][:7],
            "lines": [1, 5],
            "callouts": [{"line": 5, "text": "round() with no digits drops the cents."}],
        },
        "depth": [
            {"kind": "explain", "text": explain("round(t)")},
            {
                "kind": "code_diff",
                "repo": "fixture",
                "commit": s["fix1"],
                "path": "billing/invoice.py",
            },
        ],
        "comments": [{"persona": "greybeard", "text": "Floats and money. Name a worse pair."}],
        "series": None,
        "sources": [
            {"repo": "fixture", "commit": s["fix1"]},
            {"repo": "fixture", "path": "billing/invoice.py", "lines": [1, 5]},
        ],
    }
    card = copy.deepcopy(card)
    card.update(overrides)
    return card


def text_card(fixture_repo, **overrides) -> dict:
    card = {
        "story_type": "rip",
        "format": "text_post",
        "persona": "archivist",
        "tone": "wholesome-nerdy",
        "repos": ["fixture"],
        "dirs": ["src"],
        "hook": "RIP legacy.py, a short and quiet life.",
        "learn": LEARN,
        "visual": {
            "kind": "text",
            "title": "In memoriam",
            "body": "It returned 1. Every time.",
            "bullets": ["Born in the initial commit", "Replaced by util.py"],
        },
        "depth": [{"kind": "explain", "text": explain("old()")}],
        "sources": [{"repo": "fixture", "commit": fixture_repo.shas["delete_legacy"]}],
    }
    card.update(overrides)
    return card


def _base(fixture_repo, fmt: str, base_visual: dict, /, **overrides) -> dict:
    visual = overrides.pop("visual", base_visual)
    card = {
        "story_type": "what_it_does",
        "format": fmt,
        "persona": "meme_compiler",
        "tone": "chaotic-absurd",
        "repos": ["fixture"],
        "dirs": ["src"],
        "hook": "A short hook.",
        "learn": LEARN,
        "visual": visual,
        "depth": [{"kind": "explain", "text": explain()}],
        "sources": [{"repo": "fixture", "path": "src/app.py", "lines": [1, 2]}],
    }
    card.update(overrides)
    return card


def meme_card(fixture_repo, **overrides) -> dict:
    v = {"kind": "meme", "template": "drake", "lines": ["Reading docs", "Reading git blame"]}
    return _base(fixture_repo, "meme", v, **overrides)


def text_meme_card(fixture_repo, **overrides) -> dict:
    v = {"kind": "text_meme", "style": "nobody_me", "lines": ["nobody:", "me: fix rounding again"]}
    return _base(fixture_repo, "text_meme", v, **overrides)


def illustration_card(fixture_repo, **overrides) -> dict:
    v = {"kind": "illustration", "prompt": "the mascot stacking crates", "caption": "Friday deploy"}
    return _base(fixture_repo, "mascot_scene", v, **overrides)


def comic_card(fixture_repo, panels: int = 2, **overrides) -> dict:
    v = {
        "kind": "comic",
        "panels": [{"prompt": f"scene {i}", "caption": f"caption {i}"} for i in range(panels)],
    }
    return _base(fixture_repo, "comic", v, **overrides)


def chart_card(fixture_repo, chart: str = "top_churn_files", **overrides) -> dict:
    v = {"kind": "chart", "chart": chart, "repo": "fixture", "title": "Where the edits go"}
    if chart == "author_shares":
        v["dir"] = "src"
    return _base(fixture_repo, "chart", v, **overrides)


def diagram_card(fixture_repo, **overrides) -> dict:
    v = {"kind": "diagram", "title": "Flow", "mermaid": "flowchart LR\n  A[api] --> B[store]"}
    return _base(fixture_repo, "diagram", v, **overrides)


TEMPLATE_DATA = {
    "iceberg": {
        "title": "Iceberg",
        "layers": [{"label": f"L{i}", "items": ["a", "b"]} for i in range(3)],
    },
    "tier_list": {
        "title": "Tiers",
        "rows": [
            {"tier": "S", "items": [{"name": "app.py", "why": "small"}]},
            {"tier": "F", "items": [{"name": "util.py", "why": "TODO"}]},
        ],
    },
    "group_chat": {
        "title": "chat",
        "messages": [{"from": "greybeard", "text": "hi"}, {"from": "archivist", "text": "yo"}],
    },
    "flags": {"subject": "app.py", "red": ["no tests"], "green": ["tiny"]},
    "dating_profile": {
        "name": "fixture:src/app.py",
        "age": "3 weeks",
        "bio": "likes long walks",
        "likes": ["main"],
        "dealbreakers": ["globals"],
    },
    "glow_up": {
        "subject": "invoice",
        "before": {"label": "v1", "text": "round(t)"},
        "after": {"label": "v2", "text": "round(t, 2)"},
    },
    "breaking_news": {"headline": "Rounding fixed", "ticker": ["more soon"]},
    "horoscope": {"subject": "greybeard", "sign": "Capricorn", "forecast": "You will merge."},
    "thread": {"posts": ["one", "two"]},
    "day_in_life": {
        "subject": "fixture:src",
        "steps": [
            {"time": "09:00", "text": "boot"},
            {"time": "10:00", "text": "run"},
            {"time": "11:00", "text": "sleep"},
        ],
    },
    "hot_take": {"take": "Tabs are fine."},
}


def template_card(fixture_repo, template: str = "hot_take", data: dict | None = None, **overrides):
    import copy as _copy

    d = _copy.deepcopy(data if data is not None else TEMPLATE_DATA[template])
    v = {"kind": "template", "template": template, "data": d}
    return _base(fixture_repo, template, v, **overrides)


def _interactive(fixture_repo, story_type: str, visual: dict, interaction: dict, /, **overrides):
    card = {
        "story_type": story_type,
        "format": "quiz",
        "persona": "penny_learns",
        "tone": "earnest-teacher",
        "repos": ["fixture"],
        "dirs": ["src"],
        "hook": "Quick check before you scroll on.",
        "learn": LEARN,
        "visual": visual,
        "interaction": interaction,
        "depth": [
            {
                "kind": "explain",
                "text": explain(
                    "total(items)" if story_type in ("guess_when", "spot_the_bug") else "main()"
                ),
            }
        ],
        "sources": [{"repo": "fixture", "path": "src/app.py", "lines": [1, 2]}],
    }
    card.update(overrides)
    return card


def spot_the_bug_card(fixture_repo, **overrides) -> dict:
    """Visual at `invoice_add` (the buggy `round(t)`); the fix is `fix1`, whose parent it is."""
    s = fixture_repo.shas
    visual = {
        "kind": "code",
        "repo": "fixture",
        "path": "billing/invoice.py",
        "commit": s["invoice_add"],
        "lines": [1, 5],
    }
    interaction = {
        "question": "What is wrong with this total?",
        "choices": ["It never loops", "round(t) drops the cents", "It returns a string"],
        "answer_index": 1,
        "explanation": "round() with no digits rounds to whole units, so the cents are lost.",
    }
    return _interactive(
        fixture_repo,
        "spot_the_bug",
        visual,
        interaction,
        dirs=["billing"],
        depth=[
            {"kind": "explain", "text": explain("total(items)")},
            {"kind": "code_diff", "repo": "fixture", "commit": s["fix1"], "path": visual["path"]},
        ],
        sources=[
            {"repo": "fixture", "commit": s["fix1"]},
            {"repo": "fixture", "path": "billing/invoice.py", "lines": [1, 5]},
        ],
        **overrides,
    )


def guess_who_card(fixture_repo, **overrides) -> dict:
    """src/app.py lines 1-2 at head are all Alice Archer's (Bob wrote the rest)."""
    visual = {
        "kind": "code",
        "repo": "fixture",
        "path": "src/app.py",
        "commit": fixture_repo.shas["head"],
        "lines": [1, 2],
    }
    interaction = {
        "question": "Who wrote main()?",
        "choices": ["Alice Archer", "Bob Builder"],
        "answer_index": 0,
        "explanation": "git blame credits both lines to Alice in the initial commit.",
    }
    return _interactive(fixture_repo, "guess_who", visual, interaction, **overrides)


def guess_when_card(fixture_repo, **overrides) -> dict:
    """billing/invoice.py was written in January 2026."""
    visual = {
        "kind": "code",
        "repo": "fixture",
        "path": "billing/invoice.py",
        "commit": fixture_repo.shas["invoice_add"],
        "lines": [1, 5],
    }
    interaction = {
        "question": "When was this written?",
        "choices": ["2023", "2024", "January 2026"],
        "answer_index": 2,
        "explanation": "Every line comes from the invoice commit of 2026-01-15.",
    }
    return _interactive(
        fixture_repo,
        "guess_when",
        visual,
        interaction,
        dirs=["billing"],
        sources=[{"repo": "fixture", "path": "billing/invoice.py", "lines": [1, 5]}],
        **overrides,
    )


def quiz_card(fixture_repo, **overrides) -> dict:
    visual = {"kind": "text", "body": "Which file defines main()?"}
    interaction = {
        "question": "Which file defines main()?",
        "choices": ["src/app.py", "src/util.py", "billing/invoice.py"],
        "answer_index": 0,
        "explanation": "main() lives in src/app.py.",
    }
    return _interactive(fixture_repo, "quiz", visual, interaction, **overrides)


def this_or_that_card(fixture_repo, **overrides) -> dict:
    visual = {"kind": "text", "body": "Rounding money: round early or round late?"}
    interaction = {
        "question": "Round early or round late?",
        "choices": ["Round early", "Round late"],
        "explanation": "Both are defensible; the thread argues it out.",
    }
    return _interactive(
        fixture_repo,
        "this_or_that",
        visual,
        interaction,
        comments=[
            {"persona": "greybeard", "text": "Round late. Always."},
            {"persona": "shipit_sam", "text": "Round early, ship today."},
        ],
        **overrides,
    )


def cross_card(a_sha: str, b_sha: str, **overrides) -> dict:
    """A text_post cross-repo story citing one commit in repo `api` and one in repo `web`."""
    card = {
        "story_type": "ripple",
        "format": "text_post",
        "persona": "shipit_sam",
        "tone": "hype",
        "repos": ["api", "web"],
        "dirs": [],
        "hook": "The export endpoint landed in api and web the same week.",
        "learn": LEARN,
        "visual": {
            "kind": "text",
            "title": "Export ripple",
            "body": "api added the endpoint, web wired the button.",
            "bullets": ["api first", "web a day later"],
        },
        "depth": [{"kind": "explain", "text": explain("A = 2` or `A = 3")}],
        "sources": [
            {"repo": "api", "commit": a_sha},
            {"repo": "web", "commit": b_sha},
        ],
    }
    card.update(overrides)
    return card
