"""Host-side connection to a short-lived image-model batch, with bounded cleanup."""

import json
import os
import selectors
import signal
import subprocess
import sys
import tempfile
import threading
import time

from gittok.render import RenderError, RendererUnavailable, _illustration_slot


class BatchExpired(Exception):
    """A batch exited normally in the idle gap before a new request reached it."""


class RenderBatchSession:
    def __init__(self, cfg, cancel, *, worker_command=None):
        self._lock = threading.RLock()
        self._closed = False
        self._cancel = cancel
        self._slot = _illustration_slot(cfg)
        self._slot.__enter__()
        self._errors = tempfile.TemporaryFile(mode="w+b")
        command = worker_command or [sys.executable, "-m", "gittok.mflux_worker",
                                     str(cfg.settings.render.mflux_batch_idle_s)]
        try:
            self.process = subprocess.Popen(
                [sys.executable, "-m", "gittok.render_process", str(os.getpid()), *command],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self._errors,
                bufsize=0, start_new_session=True,
            )
        except BaseException:
            self._errors.close()
            self._slot.__exit__(None, None, None)
            raise
        threading.Thread(target=self._watch, daemon=True, name="render-batch-watch").start()

    @property
    def alive(self):
        return not self._closed and self.process.poll() is None

    def _watch(self):
        self.process.wait()
        self.close()  # release the home slot even if no more requests arrive

    def close(self):
        with self._lock:
            if self._closed:
                return
            self._closed = True
            try:
                os.killpg(self.process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            self.process.wait()
            self.process.stdin.close()
            self.process.stdout.close()
            self._errors.close()
            self._slot.__exit__(None, None, None)

    def _failure(self):
        self._errors.seek(0, os.SEEK_END)
        self._errors.seek(max(0, self._errors.tell() - 4096))
        return self._errors.read().decode("utf-8", errors="replace").strip()[-1000:]

    def render(self, request, timeout):
        with self._lock:
            if not self.alive:
                raise BatchExpired()
            try:
                if self._cancel.is_set():
                    raise RendererUnavailable("rendering stopped")
                self.process.stdin.write((json.dumps(request) + "\n").encode())
                deadline = time.monotonic() + timeout
                response = b""
                with selectors.DefaultSelector() as ready:
                    ready.register(self.process.stdout, selectors.EVENT_READ)
                    while b"\n" not in response:
                        if self._cancel.is_set():
                            raise RendererUnavailable("rendering stopped")
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            raise RenderError(f"mflux timed out after {timeout}s")
                        if not ready.select(min(0.2, remaining)):
                            continue
                        chunk = os.read(self.process.stdout.fileno(), 8192)
                        if not chunk:
                            code = self.process.wait()
                            if code == 0:
                                raise BatchExpired()
                            raise RenderError(f"mflux batch exited ({code}): {self._failure()}")
                        response += chunk
                        if len(response) > 65536:
                            raise RenderError("mflux batch returned an oversized response")
                result = json.loads(response)
                if not result.get("ok"):
                    raise RenderError(f"mflux failed: {result.get('error', 'unknown error')}")
            except BrokenPipeError as exc:
                self.close()
                raise BatchExpired() from exc
            except BaseException:
                self.close()
                raise
