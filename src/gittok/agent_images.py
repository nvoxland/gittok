"""Agent illustration handoff. Card validation and asset storage stay shared.

Codex sends files or data URLs from its native image tool. Claude has no image tool, so
its illustrator subagent draws SVG, and this module rasterizes it (svg_image)."""

import base64
import binascii
import re
import xml.etree.ElementTree as ET
from pathlib import Path

import resvg_py

from gittok import db, private, render
from gittok import render_jobs as jobs

MAX_BYTES = jobs.MAX_BYTES
MAX_SVG_BYTES = 512 * 1024
# Elements that load other documents, files or code. resvg reads local files for <image>.
_BLOCKED_TAGS = {"image", "feImage", "script", "style", "foreignObject"}
_URL = re.compile(r"url\(\s*['\"]?\s*([^)'\"\s]*)")


ImageError = jobs.JobError


def pending(conn, cfg, run_id: str, card_id: str | None = None) -> list[dict]:
    if conn.execute("SELECT 1 FROM runs WHERE id = ?", (run_id,)).fetchone() is None:
        raise ImageError(f"unknown run: {run_id}")
    staging = (cfg.settings.data_dir / "agent-images").resolve()
    result = []
    with db.immediate(conn):
        rows = conn.execute(
            "SELECT id, spec, resolved FROM cards WHERE run_id = ? AND status = 'pending_render' "
            "ORDER BY created_at, id", (run_id,),
        ).fetchall()
        for row in rows:
            spec = db.loads(row["spec"])
            if spec["visual"]["kind"] not in {"illustration", "comic"}:
                continue
            resolved = db.loads(row["resolved"]) or {}
            if resolved.get("image_backend") != "agent":
                # Recover older unassigned cards when this session uses agent rendering.
                if render.image_backend(cfg) != "agent":
                    continue
                if ("image_backend" in resolved
                        and render.worker_check(cfg.settings.render.mflux_model) is None):
                    continue
                resolved["image_backend"] = "agent"
                conn.execute("UPDATE cards SET resolved = ? WHERE id = ?",
                             (db.dumps(resolved), row["id"]))
        for cid in jobs.pending_ids(conn, "agent", run_id=run_id):
            if card_id is not None and cid != card_id:
                continue
            request = jobs.request(conn, cfg, cid, backend="agent")
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


def svg_image(svg: str, width: int, height: int) -> jobs.RenderedImage:
    """Rasterize one drawn panel to exactly width x height, with no outside resources."""
    if len(svg.encode()) > MAX_SVG_BYTES:
        raise ImageError(f"SVG is too large (over {MAX_SVG_BYTES // 1024} KB); simplify it")
    if "<!DOCTYPE" in svg.upper() or "<!ENTITY" in svg.upper() or "<?xml-stylesheet" in svg:
        raise ImageError("SVG must not have a DOCTYPE, entities or stylesheets")
    try:
        root = ET.fromstring(svg)
    except ET.ParseError as e:
        raise ImageError(f"cannot render SVG: {e}") from e
    if _local(root.tag) != "svg":
        raise ImageError("SVG root must be <svg>")
    for el in root.iter():
        if (tag := _local(str(el.tag))) in _BLOCKED_TAGS:
            raise ImageError(f"SVG must not use <{tag}>: draw with shapes, paths and gradients")
        for name, value in el.attrib.items():
            refs = _URL.findall(value)
            if _local(name) == "href":
                refs.append(value.strip())
            if any(not ref.startswith("#") for ref in refs):
                raise ImageError("SVG may only reference its own elements (href=\"#id\", "
                                 "url(#id)); outside files and URLs are not loaded")
    root.set("width", str(width))
    root.set("height", str(height))
    try:
        data = resvg_py.svg_to_bytes(svg_string=ET.tostring(root, encoding="unicode"),
                                     skip_system_fonts=True)
    except ValueError as e:
        raise ImageError(f"cannot render SVG: {e}") from e
    return jobs.decode_image(bytes(data), meta={"backend": "agent", "drawn": "svg"})


def submit(conn, cfg, card_id: str, paths: list[str] | None = None,
           data_urls: list[str] | None = None, svgs: list[str] | None = None) -> dict:
    request = jobs.request(conn, cfg, card_id, backend="agent")
    if request.status == "ready":
        return jobs.complete(conn, cfg, jobs.RenderCompletion(request, ()))
    if sum(x is not None for x in (paths, data_urls, svgs)) != 1:
        raise ImageError("provide exactly one of paths, data_urls and svgs")
    if paths is not None:
        images = [_read(cfg, path) for path in paths]
    elif data_urls is not None:
        images = [_from_data_url(url) for url in data_urls]
    else:
        sizes = [(i["width"], i["height"]) for i in request.images]
        if len(svgs) != len(sizes):
            raise ImageError(f"expected {len(sizes)} images in panel order; got {len(svgs)}")
        images = [svg_image(svg, w, h) for svg, (w, h) in zip(svgs, sizes, strict=True)]
    return jobs.complete(conn, cfg, jobs.RenderCompletion(request, tuple(images)))
