"""Render worker: turns `pending_render` cards into PNG assets."""

from __future__ import annotations

import fcntl
import functools
import logging
import shutil
import struct
import subprocess
import sys
import tempfile
import threading
from collections.abc import Callable
from contextlib import closing, contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Protocol

import yaml

from gittok import db, image_model, memes, private

log = logging.getLogger("gittok.render")

STALE_RENDERING = timedelta(minutes=30)
RENDERING_SINCE = "rendering_since"  # key in cards.resolved while status is `rendering`


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


class Renderer(Protocol):
    def available(self) -> bool: ...

    def render(self, visual: dict, cfg, spec: dict) -> list[RenderedImage]: ...


def png_size(data: bytes) -> tuple[int, int]:
    if data[:8] != b"\x89PNG\r\n\x1a\n" or len(data) < 24:
        raise RenderError("backend did not return a PNG")
    return struct.unpack(">II", data[16:24])


class MemeRenderer:
    """Draws meme cards in process from the templates that `gittok memes --prefetch`
    downloaded into `store` (memes.py)."""

    def __init__(self, store: Path):
        self.store = Path(store)

    def available(self) -> bool:
        return bool(memes.available_in(self.store))

    def setup(self) -> dict:
        ready = self.available()
        return {
            "installed": True,
            "available": ready,
            "reason": None if ready else "Meme templates and fonts have not been downloaded.",
            "command": None if ready else "gittok memes --prefetch",
        }

    def render(self, visual: dict, cfg, spec: dict) -> list[RenderedImage]:
        tid = visual["template"]
        if tid not in memes.available_in(self.store):
            raise RendererUnavailable(
                f"meme template {tid} is not downloaded: run `gittok memes --prefetch`"
            )
        try:
            data = memes.draw(memes.template_dir(self.store, tid), self.store / "fonts",
                              visual["lines"])
        except (OSError, ValueError, yaml.YAMLError) as e:
            raise RenderError(f"could not draw meme {tid}: {e}") from e
        w, h = png_size(data)
        meta = {"template": tid, "lines": visual["lines"], "width": w, "height": h}
        return [RenderedImage(data, w, h, meta)]


@contextmanager
def _illustration_slot(cfg):
    """UI, CLI, avatars and other sessions of this home share one model-loading slot."""
    private.make_dir(cfg.settings.data_dir)
    with open(cfg.settings.data_dir / "mflux.lock", "a", opener=private.opener) as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as e:
            raise RendererUnavailable("illustration renderer is busy") from e
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def check_worker(model: str) -> str | None:
    """None when the batch worker can import what it needs for `model` (mflux, its model
    class, MemorySaver, ModelConfig), else why not. Runs in a child process: importing mflux
    loads MLX, which the feed server does not need."""
    try:
        done = subprocess.run(
            [sys.executable, "-m", "gittok.mflux_worker", "--check", model],
            capture_output=True, text=True, timeout=120,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        return f"could not check the image renderer: {e}"
    if done.returncode == 0:
        return None
    lines = (done.stderr or done.stdout or "").strip().splitlines()
    return lines[-1] if lines else f"the image renderer check exited with {done.returncode}"


@functools.cache
def worker_check(model: str) -> str | None:
    """`check_worker`, once per process and model."""
    return check_worker(model)


NOT_INSTALLED = (
    "the image renderer (mflux) is not installed in this GitTok environment "
    "(tool: install with the images extra; clone: uv sync --group images)"
)


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


def _start_batch_process(cfg, cancel, **kwargs):
    from .render_batch import RenderBatchSession

    return RenderBatchSession(cfg, cancel, **kwargs)


class IllustrationRenderer:
    """Mascot art and comic panels, drawn by a reusable model batch (render_batch.py).

    `path` is the model folder (image_model.model_dir). Until it holds a complete model the
    renderer is unavailable, so illustration cards wait as pending_render instead of failing.
    `check` says why the model code cannot run (None when it can); by default the batch
    worker's own imports are checked once per process."""

    def __init__(self, model: str = "z-image-turbo", path=None, check=None):
        self._model = model
        self._path = Path(path).expanduser() if path else None
        self._check = check or (lambda: worker_check(model))
        self._cancel = threading.Event()
        self._batch = None
        self._batch_lock = threading.Lock()

    def why_unavailable(self) -> str | None:
        if reason := self._check():
            return f"{NOT_INSTALLED}: {reason}"
        if self._path is None or not image_model.ready(self._path):
            return (f"the image model is not downloaded yet ({self._path}); the feed server "
                    "downloads it, or run `gittok images --download`")
        return None

    def available(self) -> bool:
        return self.why_unavailable() is None

    def stop(self) -> None:
        self._cancel.set()
        self.finish_batch()

    def finish_batch(self) -> None:
        with self._batch_lock:
            batch = self._batch
            self._batch = None
        if batch is not None:
            batch.close()

    def render(self, visual: dict, cfg, spec: dict) -> list[RenderedImage]:
        if why := self.why_unavailable():
            raise RendererUnavailable(why)
        scenes = visual["panels"] if visual.get("kind") == "comic" else [visual]
        mascots = mascots_for(visual, cfg, spec)
        seed0 = visual.get("seed", mascots[0].seed if mascots else 0)
        style = ", ".join(m.style for m in mascots)
        return [
            self.generate(cfg, style, scene["prompt"], seed0 + i)
            for i, scene in enumerate(scenes)
        ]

    def generate(self, cfg, style: str, scene: str, seed: int) -> RenderedImage:
        r = cfg.settings.render
        prompt = ", ".join(p for p in (style, scene) if p) + ", no text, no letters"
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out.png"
            if self._cancel.is_set():
                raise RendererUnavailable("rendering stopped")
            self._generate_in_batch(cfg, {
                "model": self._model, "path": str(self._path), "low_ram": r.mflux_low_ram,
                "prompt": prompt, "seed": seed, "width": r.image_width,
                "height": r.image_height, "steps": r.mflux_steps, "output": str(out),
            })
            if not out.is_file():
                raise RenderError("mflux produced no image")
            data = out.read_bytes()
        w, h = png_size(data)
        meta = {"width": w, "height": h, "model": self._model, "seed": seed, "prompt": prompt}
        return RenderedImage(data, w, h, meta)

    def _generate_in_batch(self, cfg, request):
        from .render_batch import BatchExpired

        for attempt in range(2):
            with self._batch_lock:
                if self._cancel.is_set():
                    raise RendererUnavailable("rendering stopped")
                if self._batch is None or not self._batch.alive:
                    if self._batch is not None:
                        self._batch.close()
                    self._batch = _start_batch_process(cfg, self._cancel)
                batch = self._batch
            try:
                batch.render(request, cfg.settings.render.mflux_timeout_s)
                return
            except BatchExpired:
                batch.close()
                with self._batch_lock:
                    if self._batch is batch:
                        self._batch = None
                if attempt:
                    raise RenderError("mflux batch repeatedly exited before rendering") from None


RENDERER_KEY = {"meme": "meme", "illustration": "illustration", "comic": "illustration"}


def illustration_renderer(cfg) -> IllustrationRenderer:
    return IllustrationRenderer(
        model=cfg.settings.render.mflux_model, path=image_model.model_dir(cfg)
    )


def default_renderers(cfg) -> dict[str, Renderer]:
    return {"meme": MemeRenderer(memes.store(cfg)), "illustration": illustration_renderer(cfg)}


def renderer_setup(cfg) -> dict:
    """For each renderer: installed (its code can run), available (it can draw now), reason,
    and for illustrations the model `download` status and the command that downloads it."""
    model = cfg.settings.render.mflux_model
    not_installed = worker_check(model)
    download = image_model.status(cfg)
    ready = download["state"] == "ready"
    reason = None
    if not_installed:
        reason = f"{NOT_INSTALLED}: {not_installed}"
    elif not ready:
        reason = {
            "downloading": "the image model is being downloaded (about "
                           f"{image_model.APPROX_GB} GB) by the feed server",
            "failed": f"the image model download failed: {download['error']}",
        }.get(download["state"], f"the image model is not downloaded yet (about "
                                 f"{image_model.APPROX_GB} GB)")
    return {
        "meme": MemeRenderer(memes.store(cfg)).setup(),
        "illustration": {
            "installed": not not_installed,
            "available": not not_installed and ready,
            "reason": reason,
            "download": download,
            "command": None if not_installed or ready else "gittok images --download",
        },
    }


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
            row = conn.execute("SELECT resolved FROM cards WHERE id = ?", (card_id,)).fetchone()
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


def _mark_failed(conn, card_id: str, error: str) -> None:
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


def _release(conn, card_id: str) -> None:
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


def _claim(conn, card_id: str) -> bool:
    """Atomically move one card from `pending_render` to `rendering`."""
    since = datetime.now(UTC).isoformat()
    with db.immediate(conn):
        row = conn.execute("SELECT resolved FROM cards WHERE id = ?", (card_id,)).fetchone()
        resolved = (db.loads(row["resolved"]) or {}) if row else {}
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


def render_pending(conn, cfg, renderers: dict[str, Renderer], limit: int = 10) -> dict:
    """One pass over `pending_render` cards, oldest first. Returns counts."""
    counts = {"rendered": 0, "failed": 0, "waiting": 0}
    reset_stale_rendering(conn)
    rows = conn.execute(
        "SELECT id, spec FROM cards WHERE status = 'pending_render' "
        "ORDER BY created_at, id LIMIT ?",
        (limit,),
    ).fetchall()
    up: dict[str, bool] = {}
    for row in rows:
        card_id = row["id"]
        claimed = False
        try:
            spec = db.loads(row["spec"])
            visual = spec["visual"]
            kind = visual["kind"]
            key = RENDERER_KEY[kind]
            renderer = renderers.get(key)
            if renderer is None:
                counts["waiting"] += 1
                continue
            if key not in up:
                up[key] = renderer.available()
            if not up[key]:
                counts["waiting"] += 1
                continue
            if not _claim(conn, card_id):  # another pass took it
                continue
            claimed = True
            images = renderer.render(visual, cfg, spec)
            _store_images(conn, cfg, card_id, kind, images)
        except RendererUnavailable:
            up[key] = False
            counts["waiting"] += 1
            if claimed:
                _release(conn, card_id)
        except Exception as e:  # noqa: BLE001 - any failure fails this card, not the pass
            log.warning("render failed for %s: %s", card_id, e)
            _mark_failed(conn, card_id, str(e) or type(e).__name__)
            counts["failed"] += 1
        else:
            counts["rendered"] += 1
    return counts


class RenderWorker:
    """Background thread that runs `render_pending` every `worker_interval_s`."""

    def __init__(self, get_config: Callable[[], Any], renderers: dict[str, Renderer] | None = None):
        self._get_config = get_config
        self._renderers = renderers
        self._stop = threading.Event()
        self._active_lock = threading.Lock()
        self._active: dict[str, Renderer] = {}
        self._active_key = None
        self._thread = threading.Thread(target=self._run, name="render-worker", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        with self._active_lock:
            for renderer in self._active.values():
                if isinstance(renderer, IllustrationRenderer):
                    renderer.stop()
        if self._thread.is_alive():
            self._thread.join(timeout)

    def is_alive(self) -> bool:
        return self._thread.is_alive()

    def _run(self) -> None:
        interval = 5.0
        while not self._stop.is_set():
            try:
                cfg = self._get_config()
                interval = cfg.settings.render.worker_interval_s
                with self._active_lock:
                    if self._stop.is_set():
                        break
                    key = (cfg.root, cfg.settings.data_dir, cfg.settings.render)
                    if self._renderers is not None:
                        self._active = self._renderers
                    elif key != self._active_key:
                        for old in self._active.values():
                            if isinstance(old, IllustrationRenderer):
                                old.stop()
                        self._active = default_renderers(cfg)
                        self._active_key = key
                    renderers = self._active
                if self._renderers is None:  # the server's own worker, not a test's
                    image_model.maybe_start(
                        cfg, installed=worker_check(cfg.settings.render.mflux_model) is None
                    )
                with closing(db.open_db(cfg.settings.data_dir / "gittok.db")) as conn:
                    counts = render_pending(conn, cfg, renderers)
                if counts["rendered"]:
                    continue  # drain the queue before sleeping between passes
            except Exception:
                log.exception("render pass failed")
            self._stop.wait(interval)
