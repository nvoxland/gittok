"""Deterministic secret detector. The patterns are data in config/secrets.yaml.

`find(text)` lists the secrets in `text`; `redact(text)` replaces each with
`<redacted: N chars>` and keeps the line count, so line numbers stay valid.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache

import yaml

_FLAGS = {"i": re.I, "s": re.S, "m": re.M}


@dataclass(frozen=True)
class Finding:
    name: str
    start: int
    end: int

    @property
    def length(self) -> int:
        return self.end - self.start


@dataclass(frozen=True)
class _Pattern:
    name: str
    rx: re.Pattern
    group: str | int
    min_length: int
    min_entropy: float


def entropy(s: str) -> float:
    """Shannon entropy in bits per character."""
    if not s:
        return 0.0
    n = len(s)
    return -sum(c / n * math.log2(c / n) for c in Counter(s).values())


@lru_cache(maxsize=1)
def _spec() -> tuple[tuple[_Pattern, ...], re.Pattern]:
    from . import config

    file = config.shipped_root() / "config" / "secrets.yaml"
    data = yaml.safe_load(file.read_text()) or {}
    pats = []
    for p in data["patterns"]:
        flags = 0
        for ch in p.get("flags", ""):
            flags |= _FLAGS[ch]
        pats.append(
            _Pattern(
                p["name"],
                re.compile(p["regex"], flags),
                p.get("group", 0),
                int(p.get("min_length", 0)),
                float(p.get("min_entropy", 0)),
            )
        )
    return tuple(pats), re.compile(data.get("keep_prefix") or r"(?!)")


def find(text: str) -> list[Finding]:
    """Secrets in `text`, ordered by position, with overlaps merged into the widest span."""
    if not text:
        return []
    spans: list[Finding] = []
    for p in _spec()[0]:
        for m in p.rx.finditer(text):
            s, e = m.span(p.group)
            if e - s < p.min_length or entropy(text[s:e]) < p.min_entropy:
                continue
            spans.append(Finding(p.name, s, e))
    spans.sort(key=lambda f: (f.start, -f.end))
    merged: list[Finding] = []
    for f in spans:
        if merged and f.start < merged[-1].end:
            if f.end > merged[-1].end:
                last = merged[-1]
                merged[-1] = Finding(last.name, last.start, f.end)
            continue
        merged.append(f)
    return merged


def _mask(segment: str, keep: re.Pattern) -> str:
    if "\n" not in segment:
        return f"<redacted: {len(segment)} chars>"
    out = []
    for i, ln in enumerate(segment.split("\n")):
        m = keep.match(ln) if i else None
        pre = m.group(0) if m else ""
        out.append(pre + f"<redacted: {len(ln) - len(pre)} chars>")
    return "\n".join(out)


def redact(text: str) -> tuple[str, int]:
    """(text with every secret masked, number of secrets). The line count does not change."""
    found = find(text)
    if not found:
        return text, 0
    keep = _spec()[1]
    out, at = [], 0
    for f in found:
        out.append(text[at : f.start])
        out.append(_mask(text[f.start : f.end], keep))
        at = f.end
    out.append(text[at:])
    return "".join(out), len(found)


def guard(cfg, text: str) -> str:
    """`redact`, unless settings.research.redact_secrets is off (unsafe)."""
    if not cfg.settings.research.redact_secrets:
        return text
    return redact(text)[0]


def redact_value(obj):
    """`obj` (nested dicts and lists) with every string redacted."""
    if isinstance(obj, str):
        return redact(obj)[0]
    if isinstance(obj, list):
        return [redact_value(x) for x in obj]
    if isinstance(obj, dict):
        return {k: redact_value(v) for k, v in obj.items()}
    return obj


def strings(obj):
    """Every string inside nested dicts and lists."""
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, list):
        for x in obj:
            yield from strings(x)
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from strings(v)
