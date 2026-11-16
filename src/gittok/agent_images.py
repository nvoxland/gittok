"""Agent illustration handoff. Card validation and asset storage stay shared.

Codex sends files or data URLs from its native image tool. Claude has no image tool, so
its illustrator subagent draws SVG, and this module rasterizes it (svg_image)."""

import base64
import binascii
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

from gittok import db, private, render
from gittok import render_jobs as jobs

MAX_BYTES = jobs.MAX_BYTES
MAX_SVG_BYTES = 512 * 1024
# Elements that load other documents, files or code. resvg reads local files for <image>.
_BLOCKED_TAGS = {"image", "feImage", "script", "style", "foreignObject"}
# No fonts are loaded (skip_system_fonts), so text would render as nothing.
_TEXT_TAGS = {"text", "tspan", "textPath"}
# Filters whose cost grows with a number: a small SVG could hold a CPU core for minutes.
FILTER_LIMITS = {("feTurbulence", "numOctaves"): 10, ("feMorphology", "radius"): 50,
                 ("feGaussianBlur", "stdDeviation"): 100, ("feDropShadow", "stdDeviation"): 100}
MAX_FILTER_ELEMENTS = 50
RENDER_TIMEOUT_S = 30.0
# resvg runs in a child process, so a slow render can be stopped (a thread cannot be).
_RENDER = ("import sys, resvg_py; svg = sys.stdin.buffer.read().decode(); "
           "sys.stdout.buffer.write(bytes(resvg_py.svg_to_bytes(svg_string=svg, "
           "skip_system_fonts=True)))")
_NUMBER = re.compile(r"[+-]?(?:\d+\.?\d*|\.\d+)(?:e[+-]?\d+)?", re.I)
MAX_DEPTH = 64
_FENCE = re.compile(r"\A\s*```[\w-]*\s*\n(.*?)\n\s*```\s*\Z", re.S)
_URL = re.compile(r"url\(\s*['\"]?\s*([^)'\"\s]*)")


ImageError = jobs.JobError


def pending(conn, cfg, run_id: str, card_id: str | None = None) -> list[dict]:
    """The agent cards that wait for images: this run's first, then the ones that earlier runs
    left pending (a failed illustrator, or a session that ended before the image step).

    The backend decision runs before the write lock: worker_check may start a subprocess."""
    if conn.execute("SELECT 1 FROM runs WHERE id = ?", (run_id,)).fetchone() is None:
        raise ImageError(f"unknown run: {run_id}")
    staging = (cfg.settings.data_dir / "agent-images").resolve()
    session_is_agent = render.image_backend(cfg) == "agent"
    local_runs = session_is_agent and (
        render.worker_check(cfg.settings.render.mflux_model) is None)
    result = []
    with db.immediate(conn):
        sql = ("SELECT id, spec, resolved FROM cards WHERE run_id = ? "
               "AND status = 'pending_render'")
        args: list = [run_id]
        if card_id is not None:
            sql += " AND id = ?"
            args.append(card_id)
        for row in conn.execute(sql, args).fetchall() if session_is_agent else []:
            visual = (db.loads(row["spec"]) or {}).get("visual") or {}
            if visual.get("kind") not in {"illustration", "comic"}:
                continue
            resolved = db.loads(row["resolved"]) or {}
            # Recover this run's cards that are unassigned, or assigned to a local renderer
            # that cannot run, when this session uses agent rendering.
            if resolved.get("image_backend") == "agent" or (
                    "image_backend" in resolved and local_runs):
                continue
            resolved["image_backend"] = "agent"
            conn.execute("UPDATE cards SET resolved = ? WHERE id = ?",
                         (db.dumps(resolved), row["id"]))
        ids = jobs.pending_ids(conn, "agent", run_id=run_id)
        ids += [i for i in jobs.pending_ids(conn, "agent") if i not in set(ids)]
        for cid in ids:
            if card_id is not None and cid != card_id:
                continue
            try:
                request = jobs.request(conn, cfg, cid, backend="agent")
            except (KeyError, TypeError, AttributeError):
                continue  # a malformed spec must not hide the other cards
            result.append({
                "card_id": cid, "staging_dir": str(staging),
                "images": list(request.images),
            })
    if result:
        private.make_dir(staging)
    return result


def _read(cfg, path: str) -> jobs.RenderedImage:
    staging = (cfg.settings.data_dir / "agent-images").resolve()
    file = Path(path).resolve()
    if not file.is_relative_to(staging):
        raise ImageError("copy the generated image into data/agent-images before submitting")
    try:
        if file.stat().st_size > MAX_BYTES:
            raise ImageError("generated image exceeds 32 MB")
        return jobs.decode_image(file.read_bytes(), meta={"backend": "agent"})
    except OSError as e:
        raise ImageError(f"cannot read generated image: {e}") from e


def _from_data_url(url: str) -> jobs.RenderedImage:
    if len(url) > MAX_BYTES * 4 // 3 + 100:
        raise ImageError("generated image exceeds 32 MB")
    header, _, payload = url.partition(",")
    if header not in {"data:image/png;base64", "data:image/jpeg;base64", "data:image/webp;base64"}:
        raise ImageError("expected a base64 image data URL; remote URLs are not fetched")
    try:
        return jobs.decode_image(
            base64.b64decode(payload, validate=True), meta={"backend": "agent"},
        )
    except (binascii.Error, ValueError) as e:
        raise ImageError("invalid image data URL") from e


def _local(name: str) -> str:
    return name.rsplit("}", 1)[-1]


def _numbers(value: str, tag: str, attr: str) -> list[float]:
    """The numbers of a number list; anything else is an error (resvg could read it differently)."""
    parts = [p for p in re.split(r"[\s,]+", value.strip()) if p]
    if not parts or not all(_NUMBER.fullmatch(p) for p in parts):
        raise ImageError(f"SVG filter {tag} {attr} must be a number or a list of numbers")
    nums = [float(p) for p in parts]
    if any(n != n for n in nums):
        raise ImageError(f"SVG filter {tag} {attr} must be a number or a list of numbers")
    return nums


def _check_depth(root) -> None:
    stack = [(root, 1)]
    while stack:
        el, depth = stack.pop()
        if depth > MAX_DEPTH:
            raise ImageError(f"SVG is nested deeper than {MAX_DEPTH} levels; flatten it")
        stack.extend((child, depth + 1) for child in el)


def svg_image(svg: str, width: int, height: int) -> jobs.RenderedImage:
    """Rasterize one drawn panel to exactly width x height, with no outside resources."""
    if fenced := _FENCE.match(svg):
        svg = fenced.group(1)
    if len(svg.encode()) > MAX_SVG_BYTES:
        raise ImageError(f"SVG is too large (over {MAX_SVG_BYTES // 1024} KB); simplify it")
    if "<!DOCTYPE" in svg.upper() or "<!ENTITY" in svg.upper() or "<?xml-stylesheet" in svg:
        raise ImageError("SVG must not have a DOCTYPE, entities or stylesheets")
    try:
        root = ET.fromstring(svg)
    except (ET.ParseError, RecursionError) as e:
        raise ImageError(f"cannot render SVG: {e}") from e
    if _local(root.tag) != "svg":
        raise ImageError("SVG root must be <svg>")
    _check_depth(root)
    filters = 0
    for el in root.iter():
        tag = _local(str(el.tag))
        if tag.startswith("fe"):
            filters += 1
            if filters > MAX_FILTER_ELEMENTS:
                raise ImageError(f"SVG uses more than {MAX_FILTER_ELEMENTS} filter elements; "
                                 "use fewer filters")
        for (filter_tag, attr), limit in FILTER_LIMITS.items():
            value = el.get(attr) if tag == filter_tag else None
            if value and any(abs(n) > limit for n in _numbers(value, tag, attr)):
                raise ImageError(f"SVG filter {tag} {attr} is over {limit}; use a smaller value")
        if tag in _BLOCKED_TAGS:
            raise ImageError(f"SVG must not use <{tag}>: draw with shapes, paths and gradients")
        if tag in _TEXT_TAGS:
            raise ImageError("SVG must not use text: no fonts are loaded; draw shapes instead")
        for name, value in el.attrib.items():
            refs = _URL.findall(value)
            if _local(name) == "href":
                refs.append(value.strip())
            if any(not ref.startswith("#") for ref in refs):
                raise ImageError("SVG may only reference its own elements (href=\"#id\", "
                                 "url(#id)); outside files and URLs are not loaded")
    if root.get("viewBox") is None:
        # Keep the drawing's own coordinates, scaled to the panel, not drawn at its corner.
        own = (root.get("width"), root.get("height"))
        if all(v and re.fullmatch(r"\d+(\.\d+)?(px)?", v.strip()) for v in own):
            w, h = (v.strip().removesuffix("px") for v in own)
            root.set("viewBox", f"0 0 {w} {h}")
    root.set("width", str(width))
    root.set("height", str(height))
    try:
        done = subprocess.run(
            [sys.executable, "-I", "-c", _RENDER], capture_output=True,
            input=ET.tostring(root, encoding="unicode").encode(), timeout=RENDER_TIMEOUT_S,
        )
    except RecursionError as e:
        raise ImageError("SVG is nested too deeply; flatten it") from e
    except subprocess.TimeoutExpired as e:
        raise ImageError(f"SVG took too long to render (over {RENDER_TIMEOUT_S:g} s); "
                         "simplify it") from e
    if done.returncode != 0:
        lines = done.stderr.decode(errors="replace").strip().splitlines() or ["unknown error"]
        raise ImageError(f"cannot render SVG: {lines[-1].removeprefix('ValueError: ')}")
    return jobs.decode_image(done.stdout, meta={"backend": "agent", "drawn": "svg"})


def submit(conn, cfg, card_id: str, paths: list[str] | None = None,
           data_urls: list[str] | None = None, svgs: list[str] | None = None) -> dict:
    request = jobs.request(conn, cfg, card_id, backend="agent")
    if request.status == "ready":
        return jobs.complete(conn, cfg, jobs.RenderCompletion(request, ()))
    if sum(x is not None for x in (paths, data_urls, svgs)) != 1:
        raise ImageError("provide exactly one of paths, data_urls and svgs")
    if paths is not None:
        images = [_read(cfg, path) for path in paths]
        result = jobs.complete(conn, cfg, jobs.RenderCompletion(request, tuple(images)))
        for path in paths:  # the asset store has its own copy now
            Path(path).unlink(missing_ok=True)
        return result
    elif data_urls is not None:
        images = [_from_data_url(url) for url in data_urls]
    else:
        sizes = [(i["width"], i["height"]) for i in request.images]
        if len(svgs) != len(sizes):
            raise ImageError(f"expected {len(sizes)} images in panel order; got {len(svgs)}")
        images = [svg_image(svg, w, h) for svg, (w, h) in zip(svgs, sizes, strict=True)]
    return jobs.complete(conn, cfg, jobs.RenderCompletion(request, tuple(images)))
