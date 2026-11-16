"""The illustration model: a pre-quantized mflux model that GitTok downloads by itself.

The model (settings.render.mflux_repo at mflux_revision, about 6 GB) goes into
<data_dir>/models/<repo name>, inside the GitTok directory, unless `mflux_path` names a folder
of the user's own. A download fills `<folder>.partial` and moves it into place only when it is
complete, so a folder at the final path is always whole. The feed server's render worker
starts the download when the illustration renderer is installed (`maybe_start`); `gittok images
--download` runs it by hand. Status is a small JSON file next to the model, so every process
(the MCP server, the feed server, the CLI) sees the same state.
"""

from __future__ import annotations

import fcntl
import json
import os
import shutil
import subprocess
import sys
import threading
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from gittok import private

# The parts of a saved mflux model. Each weighted part has an index of its shards.
COMPONENTS = ("transformer", "text_encoder", "vae")
TOKENIZER = "tokenizer/tokenizer.json"
APPROX_GB = 6
RETRY_AFTER_S = 3600  # after a failed download, wait this long before starting one by itself
STARTING_S = 60  # a started download has this long to take the lock before it counts as gone
STATUS_FILE = "download.json"
MARKER_FILE = ".model-complete-marker"  # in each folder a download made; only that is replaced
LOCK_FILE = ".download.lock"
PATTERNS = [f"{c}/" for c in (*COMPONENTS, "tokenizer")]  # a folder: everything in it


class DownloadError(Exception):
    """The download did not finish, or what it wrote is not a complete model."""


def models_root(cfg) -> Path:
    return Path(cfg.settings.data_dir) / "models"


def model_dir(cfg) -> Path:
    r = cfg.settings.render
    if r.mflux_path:
        return Path(r.mflux_path).expanduser()
    return models_root(cfg) / r.mflux_repo.rsplit("/", 1)[-1]


def user_path(cfg) -> bool:
    """True when `render.mflux_path` names the model folder: the user's own, never written."""
    return bool(cfg.settings.render.mflux_path)


def ready(path: Path) -> bool:
    """A complete model folder: every weighted part with its index and all its shards (none
    empty), and the tokenizer. Checked without loading any weights."""
    path = Path(path)
    try:
        for comp in COMPONENTS:
            indexes = list((path / comp).glob("*.safetensors.index.json"))
            if not indexes:
                return False
            for index in indexes:
                refs = json.loads(index.read_text())["weight_map"]
                if not isinstance(refs, dict) or not refs:
                    return False
                for name in set(refs.values()):
                    shard = index.parent / name
                    if not shard.is_file() or shard.stat().st_size == 0:
                        return False
        return (path / TOKENIZER).is_file()
    except (OSError, ValueError, KeyError, TypeError):
        return False


# ---------------------------------------------------------------- status and locking


def _status_path(cfg) -> Path:
    return models_root(cfg) / STATUS_FILE


def _write_status(cfg, **data) -> None:
    private.make_dir(models_root(cfg))
    tmp = _status_path(cfg).with_suffix(".tmp")
    tmp.write_text(json.dumps({**data, "at": datetime.now(UTC).isoformat()}))
    os.replace(tmp, _status_path(cfg))


def _read_status(cfg) -> dict:
    try:
        data = json.loads(_status_path(cfg).read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _lock(cfg):
    private.make_dir(models_root(cfg))
    return open(models_root(cfg) / LOCK_FILE, "a", opener=private.opener)


def _age(saved: dict) -> float:
    """Seconds since a status was written; infinite when unknown."""
    try:
        return (datetime.now(UTC) - datetime.fromisoformat(saved.get("at", ""))).total_seconds()
    except (TypeError, ValueError):
        return float("inf")


def downloading(cfg) -> bool:
    """True while some process holds the download lock."""
    with _lock(cfg) as f:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        fcntl.flock(f, fcntl.LOCK_UN)
        return False


def status(cfg) -> dict:
    """{state: ready | downloading | failed | missing | invalid path, path, done, total, error}."""
    path = model_dir(cfg)
    out = {"state": "missing", "path": str(path), "done": 0, "total": 0, "error": None}
    if ready(path):
        return {**out, "state": "ready"}
    if user_path(cfg):
        return {**out, "state": "invalid path",
                "error": f"render.mflux_path {path} is not a complete saved mflux model "
                         "(each of transformer, text_encoder and vae with its index and "
                         "shards, and tokenizer/tokenizer.json); GitTok never downloads into it"}
    saved = _read_status(cfg)
    if downloading(cfg) or (saved.get("state") == "starting" and _age(saved) < STARTING_S):
        return {**out, "state": "downloading", "done": saved.get("done", 0),
                "total": saved.get("total", 0)}
    if saved.get("state") == "failed":
        return {**out, "state": "failed", "error": saved.get("error")}
    return out


# ---------------------------------------------------------------- the download


def _size(path: Path) -> int:
    return sum(p.stat().st_size for p in path.rglob("*") if p.is_file()) if path.exists() else 0


def _remote_total(repo: str, revision: str) -> int:
    from huggingface_hub import HfApi

    info = HfApi().model_info(repo, revision=revision, files_metadata=True)
    return sum(
        s.size or 0 for s in info.siblings
        if s.rfilename.split("/", 1)[0] in (*COMPONENTS, "tokenizer")
    )


def _hf_fetch(cfg) -> Callable[[str, str, Path], None]:
    def fetch(repo: str, revision: str, dest: Path) -> None:
        # Keep the hub's caches inside the GitTok directory too. Set before the first import.
        os.environ.setdefault("HF_HOME", str(models_root(cfg) / ".hf"))
        os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
        from huggingface_hub import snapshot_download

        snapshot_download(repo, revision=revision, local_dir=dest, allow_patterns=PATTERNS)

    return fetch


def download(cfg, *, fetch=None, total: int | None = None, poll_s: float = 2.0,
             on_progress: Callable[[int, int], None] | None = None) -> Path:
    """Download the model into its folder. Resumes a partial download. Raises DownloadError."""
    r = cfg.settings.render
    final = model_dir(cfg)
    partial = final.with_name(final.name + ".partial")
    if user_path(cfg) and not ready(final):
        raise DownloadError(status(cfg)["error"])
    with _lock(cfg) as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise DownloadError("a download is already running") from None
        if ready(final):
            _write_status(cfg, state="ready")
            return final
        if final.exists() and not (final / MARKER_FILE).exists():
            raise DownloadError(f"{final} exists and GitTok did not make it; "
                                "move it away to download the model there")
        try:
            if total is None:
                total = _remote_total(r.mflux_repo, r.mflux_revision)
            private.make_dir(partial)
            _write_status(cfg, state="downloading", done=_size(partial), total=total)
            done = threading.Event()

            def report():
                while not done.wait(poll_s):
                    n = _size(partial)
                    _write_status(cfg, state="downloading", done=n, total=total)
                    if on_progress:
                        on_progress(n, total)

            watcher = threading.Thread(target=report, daemon=True)
            watcher.start()
            try:
                (fetch or _hf_fetch(cfg))(r.mflux_repo, r.mflux_revision, partial)
            finally:
                done.set()
                watcher.join()
            if not ready(partial):
                raise DownloadError(f"the download of {r.mflux_repo} is incomplete")
            (partial / MARKER_FILE).write_text("made by gittok images --download\n")
            if final.exists():
                shutil.rmtree(final)  # an incomplete folder that a download made
            os.replace(partial, final)
        except Exception as e:
            _write_status(cfg, state="failed", error=str(e) or type(e).__name__)
            raise e if isinstance(e, DownloadError) else DownloadError(str(e)) from e
        _write_status(cfg, state="ready")
        return final


# ---------------------------------------------------------------- starting it by itself


def _spawn(cmd: list[str], home: Path) -> None:
    """Run the download in its own process in the GitTok directory, under the renderer
    supervisor so that it stops with the feed server. A later start resumes it."""
    subprocess.Popen(
        [sys.executable, "-m", "gittok.render_process", str(os.getpid()), *cmd],
        cwd=home, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL, start_new_session=True,
    )


def download_command() -> list[str]:
    return [sys.executable, "-m", "gittok", "images", "--download"]


def maybe_start(cfg, *, installed: bool, spawn: Callable[[list[str]], None] | None = None) -> bool:
    """Start the download in the background when the renderer is installed, the model is
    missing, no download runs, automatic downloads are on, and no download failed in the
    last RETRY_AFTER_S. Returns True when it started one."""
    if not installed or not cfg.settings.render.mflux_auto_download:
        return False
    st = status(cfg)
    if st["state"] in ("ready", "downloading", "invalid path"):
        return False
    if st["state"] == "failed" and _age(_read_status(cfg)) < RETRY_AFTER_S:
        return False
    _write_status(cfg, state="starting")
    (spawn or (lambda cmd: _spawn(cmd, Path(cfg.root))))(download_command())
    return True
