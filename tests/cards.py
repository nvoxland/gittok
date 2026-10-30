"""Helpers that build card specs citing real fixture-repo content."""

from __future__ import annotations

import copy


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
        "visual": {
            "kind": "code",
            "repo": "fixture",
            "path": "billing/invoice.py",
            "commit": s["invoice_add"][:7],
            "lines": [1, 5],
            "callouts": [{"line": 5, "text": "round() with no digits drops the cents."}],
        },
        "depth": [
            {"kind": "explain", "text": "The first version rounded to whole units."},
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
        "hook": "RIP legacy.py, 2026-01-05 to 2026-01-25.",
        "visual": {
            "kind": "text",
            "title": "In memoriam",
            "body": "It returned 1. Every time.",
            "bullets": ["Born in the initial commit", "Replaced by util.py"],
        },
        "depth": [{"kind": "explain", "text": "legacy.py was deleted when util.py took over."}],
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
        "visual": visual,
        "depth": [{"kind": "explain", "text": "Plain explanation."}],
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
