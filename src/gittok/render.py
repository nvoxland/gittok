"""Render worker: turns `pending_render` cards into PNG assets."""

from __future__ import annotations

import fcntl
import importlib.util
import json
import logging
import os
import shlex
import shutil
import signal
import struct
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Callable
from contextlib import closing, contextmanager, nullcontext
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Protocol

import yaml

from gittok import db, memes, private

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


def _default_runner(
    cmd: list[str], timeout: float, *, cancel: threading.Event | None = None
) -> None:
    """Bound the render's lifetime and reap its entire process group on every exit.

    The small supervisor also handles this Python process being killed abruptly.
    Logs go to disk rather than growing a second in-memory buffer in the feed server.
    """
    if cancel is not None and cancel.is_set():
        raise RendererUnavailable("rendering stopped")
    with tempfile.TemporaryFile(mode="w+b") as errors:
        process = subprocess.Popen(
            [sys.executable, "-m", "gittok.render_process", str(os.getpid()), *cmd],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=errors,
            start_new_session=True,
        )
        deadline = time.monotonic() + timeout
        try:
            while True:
                if cancel is not None and cancel.is_set():
                    raise RendererUnavailable("rendering stopped")
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise subprocess.TimeoutExpired(cmd, timeout)
                try:
                    code = process.wait(timeout=min(0.2, remaining))
                    break
                except subprocess.TimeoutExpired:
                    continue
            if code:
                errors.seek(0, os.SEEK_END)
                errors.seek(max(0, errors.tell() - 4096))
                raise subprocess.CalledProcessError(
                    code, cmd, stderr=errors.read().decode("utf-8", errors="replace")
                )
        finally:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()


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


# mflux ships one CLI per model family; the generic one cannot load every model.
_MFLUX_FAMILIES = (
    ("z-image", "mflux-generate-z-image"),
    ("flux2", "mflux-generate-flux2"),
    ("flux3", "mflux-generate-flux3"),
    ("qwen", "mflux-generate-qwen"),
)


def _mflux_command(model: str = "") -> list[str] | None:
    name = next(
        (cli for prefix, cli in _MFLUX_FAMILIES if model.startswith(prefix)), "mflux-generate"
    )
    exe = _environment_command(name)
    if exe:
        return [exe]
    if name == "mflux-generate" and importlib.util.find_spec("mflux") is not None:
        return [sys.executable, "-m", "mflux.generate"]
    return None


def _environment_command(name: str) -> str | None:
    """uv tools expose gittok, but dependency scripts stay beside the venv's Python.

    Do not resolve Python's symlink: its target is outside the tool environment.
    Prefer this environment's mflux over an unrelated version on PATH.
    """
    sibling = Path(sys.executable).parent / name
    if sibling.is_file() and os.access(sibling, os.X_OK):
        return str(sibling)
    return shutil.which(name)


def _saved_model_ready(path: Path) -> bool:
    """Reject empty/interrupted exports without loading gigabytes of model weights."""
    if not path.is_dir():
        return False
    try:
        weights = list(path.rglob("*.safetensors"))
        if not weights or any(p.stat().st_size == 0 for p in weights):
            return False
        for index in path.rglob("*.safetensors.index.json"):
            refs = json.loads(index.read_text())["weight_map"]
            if not isinstance(refs, dict) or not refs:
                return False
            if any(not (index.parent / name).is_file()
                   or (index.parent / name).stat().st_size == 0 for name in set(refs.values())):
                return False
    except (OSError, ValueError, KeyError, TypeError):
        return False
    return True


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
    """Mascot art through a reusable subprocess batch, including comic panels."""

    def __init__(
        self,
        runner: Callable[[list[str], float], None] | None = None,
        command: list[str] | None = None,
        model: str = "",
        path: str = "",
    ):
        self._runner = runner
        self._cancel = threading.Event()
        self._batch = None
        self._batch_lock = threading.Lock()
        self._command = command
        self._model = model
        # settings.render.mflux_path: a folder from mflux-save. Until it exists the renderer
        # is unavailable, so illustration cards wait as pending_render instead of failing.
        self._path = Path(path).expanduser() if path else None

    def _cmd(self) -> list[str] | None:
        return self._command or _mflux_command(self._model)

    def _installed(self) -> bool:
        # The batch imports the Python API. A CLI in an unrelated uv environment
        # cannot provide those imports; injected commands are used by test runners.
        return self._cmd() is not None and (
            self._command is not None or importlib.util.find_spec("mflux") is not None
        )

    def _why_unavailable(self) -> str | None:
        if not self._installed():
            return ("mflux is not installed in this GitTok environment "
                    "(clone: uv sync --group images; tool: the images extra)")
        if self._path is not None and not _saved_model_ready(self._path):
            return (f"saved model {self._path} is missing or incomplete: "
                    "run mflux-save (docs/install.md)")
        return None

    def available(self) -> bool:
        return self._why_unavailable() is None

    def stop(self) -> None:
        self._cancel.set()
        self.finish_batch()

    def finish_batch(self) -> None:
        with self._batch_lock:
            batch = self._batch
            self._batch = None
        if batch is not None:
            batch.close()

    def setup(self) -> dict:
        installed = self._installed()
        reason = self._why_unavailable()
        command = None
        if reason and installed and self._path is not None:
            save = _environment_command("mflux-save") or "mflux-save"
            command = shlex.join([
                save, "--model", self._model, "--quantize", "4", "--path", str(self._path)
            ])
        return {
            "installed": installed,
            "available": reason is None,
            "reason": reason,
            "command": command,
            "check_command": shlex.join([*self._cmd(), "--help"]) if installed else None,
        }

    def render(self, visual: dict, cfg, spec: dict) -> list[RenderedImage]:
        base = self._cmd()
        why = self._why_unavailable()
        if base is None or why:
            raise RendererUnavailable(why)
        scenes = visual["panels"] if visual.get("kind") == "comic" else [visual]
        mascots = mascots_for(visual, cfg, spec)
        seed0 = visual.get("seed", mascots[0].seed if mascots else 0)
        style = ", ".join(m.style for m in mascots)
        # A real batch owns the slot for its whole warm lifetime. Test/CLI runners
        # are one-shot and retain the existing per-card slot.
        slot = _illustration_slot(cfg) if self._runner is not None else nullcontext()
        with slot:
            return [
                self.generate(base, cfg, style, scene["prompt"], seed0 + i)
                for i, scene in enumerate(scenes)
            ]

    def generate(self, base: list[str], cfg, style: str, scene: str, seed: int) -> RenderedImage:
        r = cfg.settings.render
        prompt = ", ".join(p for p in (style, scene) if p) + ", no text, no letters"
        # A saved folder is already quantized: name it as the model and skip -q. Loading the
        # bf16 weights and quantizing on every run swaps a 36 GB Mac (docs/install.md).
        saved = str(Path(r.mflux_path).expanduser()) if r.mflux_path else ""
        model = saved or r.mflux_model
        model_args = (
            ["--model", saved, "--base-model", r.mflux_model]
            if saved
            else ["--model", r.mflux_model, "-q", str(r.mflux_quantize)]
        )
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out.png"
            cmd = [
                *base,
                *model_args,
                "--prompt", prompt,
                "--seed", str(seed),
                "--steps", str(r.mflux_steps),
                "--width", str(r.image_width),
                "--height", str(r.image_height),
                "--output", str(out),
            ]  # fmt: skip
            if r.mflux_low_ram:
                cmd.append("--low-ram")
            try:
                if self._cancel.is_set():
                    raise RendererUnavailable("rendering stopped")
                if self._runner is None:
                    self._generate_in_batch(cfg, {
                        "model": r.mflux_model, "path": saved, "quantize": r.mflux_quantize,
                        "low_ram": r.mflux_low_ram, "prompt": prompt, "seed": seed,
                        "width": r.image_width, "height": r.image_height,
                        "steps": r.mflux_steps, "output": str(out),
                    })
                else:
                    self._runner(cmd, r.mflux_timeout_s)
            except subprocess.CalledProcessError as e:
                raise RenderError(f"mflux failed: {(e.stderr or str(e)).strip()[-500:]}") from e
            except subprocess.TimeoutExpired as e:
                raise RenderError(f"mflux timed out after {r.mflux_timeout_s}s") from e
            except FileNotFoundError as e:
                raise RendererUnavailable(f"mflux not runnable: {e}") from e
            if not out.is_file():
                raise RenderError("mflux produced no image")
            data = out.read_bytes()
        w, h = png_size(data)
        meta = {"width": w, "height": h, "model": model, "seed": seed, "prompt": prompt}
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


def default_renderers(cfg) -> dict[str, Renderer]:
    return {
        "meme": MemeRenderer(memes.store(cfg)),
        "illustration": IllustrationRenderer(
            model=cfg.settings.render.mflux_model, path=cfg.settings.render.mflux_path
        ),
    }


def renderer_setup(cfg) -> dict:
    """Separate installed renderer code from assets still needed on a fresh install."""
    return {name: renderer.setup() for name, renderer in default_renderers(cfg).items()}


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
                    key = (cfg.root, cfg.settings.render)
                    if self._renderers is not None:
                        self._active = self._renderers
                    elif key != self._active_key:
                        for old in self._active.values():
                            if isinstance(old, IllustrationRenderer):
                                old.stop()
                        self._active = default_renderers(cfg)
                        self._active_key = key
                    renderers = self._active
                with closing(db.open_db(cfg.settings.data_dir / "gittok.db")) as conn:
                    counts = render_pending(conn, cfg, renderers)
                if counts["rendered"]:
                    continue  # drain the queue before sleeping between passes
            except Exception:
                log.exception("render pass failed")
            self._stop.wait(interval)
