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
