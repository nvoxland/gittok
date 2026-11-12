"""Persona avatars: generated PNGs when present, else a deterministic SVG."""

from __future__ import annotations

import hashlib
import re
from html import escape
from pathlib import Path

from gittok import private
from gittok.config import Persona
from gittok.render import IllustrationRenderer, RendererUnavailable

_SAFE_HANDLE = re.compile(r"[A-Za-z0-9_]+")


def _hash(handle: str) -> int:
    return int.from_bytes(hashlib.sha1(handle.encode()).digest()[:4], "big")


def initials(handle: str, name: str | None) -> str:
    if name:
        words = [w for w in re.split(r"\s+", name.strip()) if w]
        letters = [w[0] for w in words[:2]] if len(words) > 1 else [words[0][0]] if words else []
    else:
        base = handle.lstrip("@").rsplit("/", 1)[-1].split(":")[-1]
        base = base.lstrip("._-") or handle
        letters = [base[0]] if base else ["?"]
    return "".join(letters).upper() or "?"


def avatar_svg(handle: str, name: str | None = None) -> str:
    hue = _hash(handle) % 360
    text = escape(initials(handle, name))
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" width="64" height="64">'
        f'<rect width="64" height="64" rx="32" fill="hsl({hue}, 55%, 42%)"/>'
        '<text x="32" y="32" text-anchor="middle" dominant-baseline="central" '
        'font-family="system-ui, sans-serif" font-size="26" font-weight="600" '
        f'fill="#fff">{text}</text></svg>'
    )


def avatar_dir(data_dir: Path) -> Path:
    return data_dir / "assets" / "avatars"


def avatar_png(data_dir: Path, handle: str) -> Path | None:
    if not _SAFE_HANDLE.fullmatch(handle):
        return None
    path = avatar_dir(data_dir) / f"{handle}.png"
    return path if path.is_file() else None


def avatar_scene(persona: Persona) -> str:
    return (
        f"a friendly profile picture of a character matching the name {persona.name} "
        f"and the voice: {persona.voice}, flat vector, no text"
    )


def generate_avatars(cfg, renderer: IllustrationRenderer, force: bool = False) -> dict:
    """Write one PNG per persona. Raises RenderError on a failed render."""
    out = avatar_dir(cfg.settings.data_dir)
    result = {"generated": 0, "skipped": 0, "waiting": False}
    for handle, persona in cfg.personas.items():
        target = out / f"{handle}.png"
        if target.exists() and not force:
            result["skipped"] += 1
            continue
        visual = {"kind": "illustration", "prompt": avatar_scene(persona), "seed": _hash(handle)}
        try:
            (img,) = renderer.render(visual, cfg, {"repos": []})
        except RendererUnavailable:
            result["waiting"] = True
            return result
        private.make_dir(out)
        target.write_bytes(img.data)
        result["generated"] += 1
    return result
