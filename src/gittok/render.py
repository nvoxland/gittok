"""Render worker: turns `pending_render` cards into PNG assets."""

from __future__ import annotations

import fcntl
import functools
import logging
import os
import subprocess
import sys
import tempfile
import threading
from collections.abc import Callable
from contextlib import closing, contextmanager
from pathlib import Path
from typing import Any, Protocol

import yaml

from gittok import db, image_model, memes, private
from gittok import render_jobs as jobs
from gittok.render_jobs import (
    RenderedImage,
    RenderError,
    RendererUnavailable,
    illustration_requests,
    png_size,
)
from gittok.render_jobs import retry_failed as retry_failed

log = logging.getLogger("gittok.render")


class LocalRenderer(Protocol):
    """Synchronous adapter; the shared request/completion API lives in render_jobs."""

    def available(self) -> bool: ...

    def render(self, visual: dict, cfg, spec: dict) -> list[RenderedImage]: ...


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


def image_backend(cfg) -> str:
    """Choose the session's illustration backend, without loading model weights."""
    preference = cfg.settings.render.image_backend
    if preference == "agent" or (
        preference == "auto" and os.environ.get("GITTOK_AGENT") == "codex"
    ):
        return "agent"
    return "agent" if worker_check(cfg.settings.render.mflux_model) else "local"


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
        return [self.generate_prompt(cfg, request["prompt"], request["seed"])
                for request in illustration_requests(visual, cfg, spec)]

    def generate(self, cfg, style: str, scene: str, seed: int) -> RenderedImage:
        prompt = ", ".join(p for p in (style, scene) if p) + ", no text, no letters"
        return self.generate_prompt(cfg, prompt, seed)

    def generate_prompt(self, cfg, prompt: str, seed: int) -> RenderedImage:
        r = cfg.settings.render
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


def default_renderers(cfg) -> dict[str, LocalRenderer]:
    return {"meme": MemeRenderer(memes.store(cfg)), "illustration": illustration_renderer(cfg)}


def renderer_setup(cfg) -> dict:
    """For each renderer: installed (its code can run), available (it can draw now), reason,
    and for illustrations the model `download` status and the command that downloads it."""
    model = cfg.settings.render.mflux_model
    not_installed = worker_check(model)
    download = image_model.status(cfg)
    ready = download["state"] == "ready"
    backend = image_backend(cfg)
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
            "backend": backend,
            "installed": not not_installed,
            "available": backend == "agent" or (not not_installed and ready),
            "reason": None if backend == "agent" else reason,
            "python_reason": reason,
            "download": download,
            "command": None if backend == "agent" or not_installed or ready
                       else "gittok images --download",
        },
    }


def render_pending(conn, cfg, renderers: dict[str, LocalRenderer], limit: int = 10) -> dict:
    """One pass over `pending_render` cards, oldest first. Returns counts."""
    counts = {"rendered": 0, "failed": 0, "waiting": 0}
    jobs.reset_stale_rendering(conn)
    ids = jobs.pending_ids(conn, "local", limit=limit)
    up: dict[str, bool] = {}
    for card_id in ids:
        claimed = False
        try:
            request = jobs.request(conn, cfg, card_id, backend="local")
            spec = request.spec
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
            if not jobs.claim(conn, request):  # another pass took it
                continue
            claimed = True
            images = renderer.render(visual, cfg, spec)
            jobs.complete(conn, cfg, jobs.RenderCompletion(request, tuple(images)), claimed=True)
        except RendererUnavailable:
            up[key] = False
            counts["waiting"] += 1
            if claimed:
                jobs.release(conn, card_id)
        except Exception as e:  # noqa: BLE001 - any failure fails this card, not the pass
            log.warning("render failed for %s: %s", card_id, e)
            jobs.fail(conn, card_id, str(e) or type(e).__name__)
            counts["failed"] += 1
        else:
            counts["rendered"] += 1
    return counts


class RenderWorker:
    """Background thread that runs `render_pending` every `worker_interval_s`."""

    def __init__(
        self, get_config: Callable[[], Any], renderers: dict[str, LocalRenderer] | None = None,
    ):
        self._get_config = get_config
        self._renderers = renderers
        self._stop = threading.Event()
        self._active_lock = threading.Lock()
        self._active: dict[str, LocalRenderer] = {}
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
                        cfg, installed=image_backend(cfg) == "local"
                    )
                with closing(db.open_db(cfg.settings.data_dir / "gittok.db")) as conn:
                    counts = render_pending(conn, cfg, renderers)
                if counts["rendered"]:
                    continue  # drain the queue before sleeping between passes
            except Exception:
                log.exception("render pass failed")
            self._stop.wait(interval)
