"""The story key: one hash of a card's story type and sources.

The validator computes it for a card; the ledger predicts it for a lead. Keep both in step:
`source_key` and `story_key_of` give the same text and hash as the validator's inline code.
"""

from __future__ import annotations

import hashlib


def source_key(repo: str, commit: str | None = None, path: str | None = None, lines=None) -> str:
    """Key text of one source: a commit, or a path with an optional line span."""
    if commit:
        return f"{repo}:{commit}"
    span = "-".join(map(str, lines or []))
    return f"{repo}:{path}:{span}"


def story_key_of(story_type: str, keys: list[str]) -> str:
    return hashlib.sha1((story_type + "|" + "|".join(sorted(keys))).encode()).hexdigest()[:16]


def story_key(story_type: str, repo: str, **source) -> str:
    """The key of a one-source story (the usual case)."""
    return story_key_of(story_type, [source_key(repo, **source)])
