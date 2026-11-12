"""Render worker: turns `pending_render` cards into PNG assets."""

from __future__ import annotations

import importlib.util
import logging
import shutil
import struct
import subprocess
import sys
import tempfile
import threading
from collections.abc import Callable
from contextlib import closing
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Protocol

import httpx

from gittok import db

log = logging.getLogger("gittok.render")

MFLUX_TIMEOUT_S = 300
STALE_RENDERING = timedelta(minutes=30)
RENDERING_SINCE = "rendering_since"  # key in cards.resolved while status is `rendering`
_ESCAPES = [
    ("_", "__"),
    ("-", "--"),
    (" ", "_"),
    ("?", "~q"),
    ("%", "~p"),
    ("#", "~h"),
    ("/", "~s"),
    ('"', "''"),
    ("\n", "~n"),
]


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


def memegen_escape(text: str) -> str:
    if text == "" or set(text) == {"."}:
        # Empty is a blank line. A dot-only segment ("." or "..") would be resolved as a path
        # segment and change the URL, and memegen has no dot escape, so render it as a blank
        # line too. The validator rejects such lines; this keeps the URL safe on its own.
        return "_"
    out = []
    for ch in text:
        for src, dst in _ESCAPES:
            if ch == src:
                out.append(dst)
                break
        else:
            out.append(ch)
    return "".join(out)


def memegen_path(template: str, lines: list[str]) -> str:
    return f"/images/{template}/" + "/".join(memegen_escape(line) for line in lines) + ".png"


def png_size(data: bytes) -> tuple[int, int]:
    if data[:8] != b"\x89PNG\r\n\x1a\n" or len(data) < 24:
        raise RenderError("backend did not return a PNG")
    return struct.unpack(">II", data[16:24])


class MemeRenderer:
    def __init__(self, base_url: str, transport: httpx.BaseTransport | None = None):
        self.base_url = base_url.rstrip("/")
        self._transport = transport

    def _client(self, timeout: float) -> httpx.Client:
        return httpx.Client(timeout=timeout, transport=self._transport)

    def available(self) -> bool:
        try:
            # One template, not /templates/: the full list takes about a second to build.
            with self._client(2.0) as c:
                return c.get(f"{self.base_url}/templates/drake").status_code < 500
        except httpx.HTTPError:
            return False

    def render(self, visual: dict, cfg, spec: dict) -> list[RenderedImage]:
        url = self.base_url + memegen_path(visual["template"], visual["lines"])
        try:
            with self._client(30.0) as c:
                resp = c.get(url)
        except httpx.TransportError as e:
            raise RendererUnavailable(f"memegen unreachable: {e}") from e
        if resp.status_code != 200:
            raise RenderError(f"memegen returned {resp.status_code} for {visual['template']}")
        w, h = png_size(resp.content)
        meta = {"template": visual["template"], "lines": visual["lines"], "width": w, "height": h}
        return [RenderedImage(resp.content, w, h, meta)]


def _default_runner(cmd: list[str], timeout: float) -> None:
    subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=timeout)


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
    exe = shutil.which(name)
    if exe:
        return [exe]
    if name == "mflux-generate" and importlib.util.find_spec("mflux") is not None:
        return [sys.executable, "-m", "mflux.generate"]
    return None


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


class IllustrationRenderer:
    """Mascot art through mflux, run as a subprocess. Comics call it once per panel."""

    def __init__(
        self,
        runner: Callable[[list[str], float], None] = _default_runner,
        command: list[str] | None = None,
        model: str = "",
        path: str = "",
    ):
        self._runner = runner
        self._command = command
        self._model = model
        # settings.render.mflux_path: a folder from mflux-save. Until it exists the renderer
        # is unavailable, so illustration cards wait as pending_render instead of failing.
        self._path = Path(path).expanduser() if path else None

    def _cmd(self) -> list[str] | None:
        return self._command or _mflux_command(self._model)

    def _why_unavailable(self) -> str | None:
        if self._cmd() is None:
            return "mflux is not installed (clone: uv sync --group images; tool: the images extra)"
        if self._path is not None and not self._path.is_dir():
            return f"saved model {self._path} is missing: run mflux-save (docs/install.md)"
        return None

    def available(self) -> bool:
        return self._why_unavailable() is None

    def render(self, visual: dict, cfg, spec: dict) -> list[RenderedImage]:
        base = self._cmd()
        why = self._why_unavailable()
        if base is None or why:
            raise RendererUnavailable(why)
        scenes = visual["panels"] if visual.get("kind") == "comic" else [visual]
        mascots = mascots_for(visual, cfg, spec)
        seed0 = visual.get("seed", mascots[0].seed if mascots else 0)
        style = ", ".join(m.style for m in mascots)
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
            try:
                self._runner(cmd, MFLUX_TIMEOUT_S)
            except subprocess.CalledProcessError as e:
                raise RenderError(f"mflux failed: {(e.stderr or str(e)).strip()[-500:]}") from e
            except subprocess.TimeoutExpired as e:
                raise RenderError(f"mflux timed out after {MFLUX_TIMEOUT_S}s") from e
            except FileNotFoundError as e:
                raise RendererUnavailable(f"mflux not runnable: {e}") from e
            if not out.is_file():
                raise RenderError("mflux produced no image")
            data = out.read_bytes()
        w, h = png_size(data)
        meta = {"width": w, "height": h, "model": model, "seed": seed, "prompt": prompt}
        return RenderedImage(data, w, h, meta)


RENDERER_KEY = {"meme": "meme", "illustration": "illustration", "comic": "illustration"}


def default_renderers(cfg) -> dict[str, Renderer]:
    return {
        "meme": MemeRenderer(cfg.settings.render.memegen_url),
        "illustration": IllustrationRenderer(
            model=cfg.settings.render.mflux_model, path=cfg.settings.render.mflux_path
        ),
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
    folder.mkdir(parents=True, exist_ok=True)
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
        self._thread = threading.Thread(target=self._run, name="render-worker", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
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
                renderers = default_renderers(cfg) if self._renderers is None else self._renderers
                with closing(db.open_db(cfg.settings.data_dir / "gittok.db")) as conn:
                    render_pending(conn, cfg, renderers)
            except Exception:
                log.exception("render pass failed")
            self._stop.wait(interval)
