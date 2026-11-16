"""Backend-neutral render requests and completions, from pending cards to ready assets.

Adapters produce image bytes locally or receive them later from an agent. They both use
request(), claim() and complete(); this module never invokes a model or an agent tool.
"""

from __future__ import annotations

import shutil
import struct
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from io import BytesIO
from typing import Any

from PIL import Image, UnidentifiedImageError

from gittok import db, private

STALE_RENDERING = timedelta(minutes=30)
RENDERING_SINCE = "rendering_since"
MAX_BYTES = 32 * 1024 * 1024
MAX_PIXELS = 16 * 1024 * 1024


class RendererUnavailable(Exception):
    """The backend is not reachable or not installed; try again later."""


class RenderError(Exception):
    """The backend ran and failed; the card cannot be rendered."""


@dataclass
class RenderedImage:
    data: bytes
    width: int
    height: int
    meta: dict[str, Any] = field(default_factory=dict)


class JobError(RenderError):
    """An actionable request or completion error."""


@dataclass(frozen=True)
class RenderRequest:
    card_id: str
    backend: str
    kind: str
    spec: dict = field(repr=False)
    images: tuple[dict, ...]
    status: str

    @property
    def expected_images(self) -> int:
        return len(self.images) if self.kind in {"illustration", "comic"} else 1


@dataclass(frozen=True)
class RenderCompletion:
    request: RenderRequest
    images: tuple[RenderedImage, ...]


def pending_ids(conn, backend: str, *, run_id: str | None = None,
                limit: int | None = None) -> list[str]:
    """Select work by assignment; a malformed spec cannot prevent later cards running."""
    sql = ("SELECT id FROM cards WHERE status = 'pending_render' "
           "AND coalesce(json_extract(resolved, '$.image_backend'), 'local') = ?")
    args: list = [backend]
    if run_id is not None:
        sql += " AND run_id = ?"
        args.append(run_id)
    sql += " ORDER BY created_at, id"
    if limit is not None:
        sql += " LIMIT ?"
        args.append(limit)
    return [r["id"] for r in conn.execute(sql, args)]


def request(conn, cfg, card_id: str, *, backend: str) -> RenderRequest:
    row = conn.execute(
        "SELECT spec, resolved, status FROM cards WHERE id = ?", (card_id,),
    ).fetchone()
    if row is None:
        raise JobError(f"unknown card: {card_id}")
    assigned = (db.loads(row["resolved"]) or {}).get("image_backend", "local")
    if assigned != backend:
        raise JobError(f"this card is not assigned to {backend} rendering")
    spec = db.loads(row["spec"])
    kind = spec["visual"]["kind"]
    images = (illustration_requests(spec["visual"], cfg, spec)
              if kind in {"illustration", "comic"} else [])
    return RenderRequest(card_id, backend, kind, spec, tuple(images), row["status"])


def claim(conn, request: RenderRequest) -> bool:
    return _claim_card(conn, request.card_id, backend=request.backend)


def complete(conn, cfg, completion: RenderCompletion, *, claimed: bool = False) -> dict:
    """Validate and publish a completion, now or after an external tool returns.

    Local adapters claim before expensive work. External adapters can complete later and
    claim here. Both paths validate before writing assets and release on a failed write.
    Repeating a successful completion never overwrites the published images.
    """
    job = completion.request
    current = request(conn, cfg, job.card_id, backend=job.backend)
    if current.status == "ready":
        return {"card_id": job.card_id, "status": "ready"}
    if claimed and current.status != "rendering":
        raise JobError("card is not claimed for rendering")
    owns_claim = claimed
    try:
        if len(completion.images) != current.expected_images:
            raise JobError(f"expected {current.expected_images} images in panel order; "
                           f"got {len(completion.images)}")
        for image in completion.images:
            validate_image(image)
        if not claimed and not claim(conn, current):
            raise JobError("card is busy; retry after the current image submission finishes")
        owns_claim = True
        _store_images(conn, cfg, job.card_id, current.kind, list(completion.images))
    except BaseException:
        if owns_claim:
            release(conn, job.card_id)
        raise
    return {"card_id": job.card_id, "status": "ready"}


def _open_image(data: bytes):
    if len(data) > MAX_BYTES:
        raise JobError("generated image exceeds 32 MB")
    image = Image.open(BytesIO(data))
    if image.width * image.height > MAX_PIXELS:
        image.close()
        raise JobError("generated image exceeds 16 megapixels")
    return image


def decode_image(data: bytes, *, meta: dict | None = None) -> RenderedImage:
    """Normalize external PNG/JPEG/WebP bytes to the PNG completion contract."""
    try:
        with _open_image(data) as image:
            if image.format not in {"PNG", "JPEG", "WEBP"}:
                raise JobError("generated image must be PNG, JPEG or WebP")
            w, h = image.size
            output = BytesIO()
            image.convert("RGBA" if "A" in image.getbands() else "RGB").save(output, format="PNG")
            return RenderedImage(output.getvalue(), w, h, meta or {})
    except (OSError, ValueError, UnidentifiedImageError, Image.DecompressionBombError) as e:
        raise JobError(f"cannot read generated image: {e}") from e


def validate_image(image: RenderedImage) -> None:
    try:
        with _open_image(image.data) as decoded:
            if decoded.format != "PNG" or decoded.size != (image.width, image.height):
                raise JobError("completion must contain PNG images with matching dimensions")
            decoded.verify()
    except (OSError, ValueError, UnidentifiedImageError, Image.DecompressionBombError) as e:
        raise JobError(f"cannot read generated image: {e}") from e


def png_size(data: bytes) -> tuple[int, int]:
    if data[:8] != b"\x89PNG\r\n\x1a\n" or len(data) < 24:
        raise RenderError("backend did not return a PNG")
    return struct.unpack(">II", data[16:24])


def mascots_for(visual: dict, cfg, spec: dict) -> list:
    """Mascots named by the visual, else the mascot of the card's first repo."""
    names = list(visual.get("mascots") or [])
    if not names:
        repo = cfg.repos.get((spec.get("repos") or [None])[0])
        if repo is not None and repo.mascot:
            names = [repo.mascot]
        elif repo is not None:
            names = [m.name for m in cfg.mascots.values() if m.repo == repo.name][:1]
    return [cfg.mascots[n] for n in names if n in cfg.mascots]


def illustration_requests(visual: dict, cfg, spec: dict) -> list[dict]:
    """One prompt per panel, shared by the agent and local model paths."""
    scenes = visual["panels"] if visual.get("kind") == "comic" else [visual]
    mascots = mascots_for(visual, cfg, spec)
    seed = visual.get("seed", mascots[0].seed if mascots else 0)
    style = ", ".join(m.style for m in mascots)
    return [{
        "prompt": ", ".join(p for p in (style, scene["prompt"]) if p) + ", no text, no letters",
        "seed": seed + i,
        "width": cfg.settings.render.image_width,
        "height": cfg.settings.render.image_height,
    } for i, scene in enumerate(scenes)]


def retry_failed(conn) -> int:
    rows = conn.execute("SELECT id, resolved FROM cards WHERE status = 'render_failed'").fetchall()
    with db.immediate(conn):
        for r in rows:
            resolved = db.loads(r["resolved"]) or {}
            resolved.pop("render_error", None)
            conn.execute(
                "UPDATE cards SET status = 'pending_render', resolved = ? WHERE id = ?",
                (db.dumps(resolved), r["id"]),
            )
    return len(rows)


def _store_images(conn, cfg, card_id: str, kind: str, images: list[RenderedImage]) -> None:
    folder = cfg.settings.data_dir / "assets" / card_id
    private.make_dir(folder)
    try:
        paths = []
        for n, img in enumerate(images):
            (folder / f"{n}.png").write_bytes(img.data)
            paths.append((n, f"assets/{card_id}/{n}.png", img))
        with db.immediate(conn):
            row = conn.execute(
                "SELECT resolved, status FROM cards WHERE id = ?", (card_id,),
            ).fetchone()
            if row is None:
                raise JobError("card was removed while rendering")
            if row["status"] != "rendering":
                raise JobError("card is not claimed for rendering")
            resolved = db.loads(row["resolved"]) or {}
            resolved.pop("render_error", None)
            resolved.pop(RENDERING_SINCE, None)
            resolved["visual"] = {
                "images": [f"/{p}" for _, p, _ in paths],
                "width": images[0].width,
                "height": images[0].height,
            }
            conn.execute("DELETE FROM assets WHERE card_id = ?", (card_id,))
            for _, path, img in paths:
                meta = {"width": img.width, "height": img.height, **img.meta}
                conn.execute(
                    "INSERT INTO assets(card_id, kind, path, meta) VALUES (?, ?, ?, ?)",
                    (card_id, kind, path, db.dumps(meta)),
                )
            conn.execute(
                "UPDATE cards SET status = 'ready', resolved = ? "
                "WHERE id = ? AND status = 'rendering'",
                (db.dumps(resolved), card_id),
            )
    except BaseException:
        shutil.rmtree(folder, ignore_errors=True)
        raise


def fail(conn, card_id: str, error: str) -> None:
    with db.immediate(conn):
        row = conn.execute("SELECT resolved FROM cards WHERE id = ?", (card_id,)).fetchone()
        if row is None:  # the card was deleted while it rendered
            return
        resolved = db.loads(row["resolved"]) or {}
        resolved["render_error"] = error
        resolved.pop(RENDERING_SINCE, None)
        conn.execute(
            "UPDATE cards SET status = 'render_failed', resolved = ? "
            "WHERE id = ? AND status IN ('rendering', 'pending_render')",
            (db.dumps(resolved), card_id),
        )


def release(conn, card_id: str) -> None:
    """Put a claimed card back to `pending_render` (renderer unavailable)."""
    with db.immediate(conn):
        row = conn.execute("SELECT resolved FROM cards WHERE id = ?", (card_id,)).fetchone()
        if row is None:
            return
        resolved = db.loads(row["resolved"]) or {}
        resolved.pop(RENDERING_SINCE, None)
        conn.execute(
            "UPDATE cards SET status = 'pending_render', resolved = ? "
            "WHERE id = ? AND status = 'rendering'",
            (db.dumps(resolved), card_id),
        )


def _claim_card(conn, card_id: str, backend: str = "local") -> bool:
    """Atomically move one card from `pending_render` to `rendering`."""
    since = datetime.now(UTC).isoformat()
    with db.immediate(conn):
        row = conn.execute("SELECT resolved FROM cards WHERE id = ?", (card_id,)).fetchone()
        resolved = (db.loads(row["resolved"]) or {}) if row else {}
        if resolved.get("image_backend", "local") != backend:
            return False
        resolved[RENDERING_SINCE] = since
        cur = conn.execute(
            "UPDATE cards SET status = 'rendering', resolved = ? "
            "WHERE id = ? AND status = 'pending_render'",
            (db.dumps(resolved), card_id),
        )
    return cur.rowcount == 1


def reset_stale_rendering(conn, max_age: timedelta = STALE_RENDERING) -> int:
    """Cards left in `rendering` by a crashed pass go back to `pending_render`."""
    cutoff = datetime.now(UTC) - max_age
    rows = conn.execute("SELECT id, resolved FROM cards WHERE status = 'rendering'").fetchall()
    n = 0
    for r in rows:
        resolved = db.loads(r["resolved"]) or {}
        try:
            since = datetime.fromisoformat(resolved.get(RENDERING_SINCE, ""))
        except ValueError:
            since = datetime.min.replace(tzinfo=UTC)  # no usable timestamp: treat as stale
        if since < cutoff:
            resolved.pop(RENDERING_SINCE, None)
            with db.immediate(conn):
                cur = conn.execute(
                    "UPDATE cards SET status = 'pending_render', resolved = ? "
                    "WHERE id = ? AND status = 'rendering'",
                    (db.dumps(resolved), r["id"]),
                )
            n += cur.rowcount
    return n

