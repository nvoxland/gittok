"""Batch lifecycle tests use fake models and tiny Python children, never MLX."""

import threading
import time
from pathlib import Path

import pytest

from gittok import render
from tests.test_render import illustrator, png_bytes, render_cfg


def test_renderer_reuses_model_session_for_cards_and_comic_panels(fixture_repo, tmp_path,
                                                                 monkeypatch):
    cfg = render_cfg(fixture_repo, tmp_path)
    sessions = []

    class FakeSession:
        alive = True

        def __init__(self):
            self.requests = []

        def render(self, request, timeout):
            self.requests.append(request)
            Path(request["output"]).write_bytes(png_bytes())

        def close(self):
            self.alive = False

    def start(cfg, cancel):
        session = FakeSession()
        sessions.append(session)
        return session

    monkeypatch.setattr(render, "_start_batch_process", start)
    renderer = illustrator(tmp_path)
    renderer.render({"kind": "comic", "panels": [{"prompt": "one"}, {"prompt": "two"}]}, cfg, {})
    renderer.render({"kind": "illustration", "prompt": "three"}, cfg, {})
    assert len(sessions) == 1
    assert [r["seed"] for r in sessions[0].requests] == [0, 1, 0]
    assert [r["prompt"].split(',')[0] for r in sessions[0].requests] == ["one", "two", "three"]
    renderer.stop()
    assert not sessions[0].alive


def test_batch_serves_different_prompts_with_one_model():
    from gittok import mflux_worker

    requests = iter([
        {"model": "z-image-turbo", "path": "/saved", "quantize": 4, "low_ram": True,
         "prompt": "one", "seed": 1, "output": "one.png"},
        {"model": "z-image-turbo", "path": "/saved", "quantize": 4, "low_ram": True,
         "prompt": "two", "seed": 2, "output": "two.png"},
    ])
    loads, drawn, replies = [], [], []

    def load(request):
        loads.append(request)
        return lambda request: drawn.append((request["prompt"], request["seed"]))

    assert mflux_worker.serve(lambda: next(requests, None), replies.append, load=load) == 0
    assert len(loads) == 1 and drawn == [("one", 1), ("two", 2)]
    assert replies == [{"ok": True}, {"ok": True}]


def test_batch_model_failure_ends_batch_without_loading_another_model():
    from gittok import mflux_worker

    def load(request):
        def fail(request):
            raise ValueError("model failed")
        return fail

    replies = []
    assert mflux_worker.serve(lambda: {"model": "test"}, replies.append, load=load) == 1
    assert replies == [{"ok": False, "error": "model failed"}]


def test_default_batch_launcher_is_blocked_in_unit_tests(fixture_repo, tmp_path):
    cfg = render_cfg(fixture_repo, tmp_path)
    renderer = illustrator(tmp_path)
    with pytest.raises(pytest.fail.Exception, match="cannot launch mflux"):
        renderer.render({"kind": "illustration", "prompt": "never loaded"}, cfg, {})


def test_batch_session_idle_exit_releases_the_home_slot(
    fixture_repo, tmp_path, real_batch_launcher
):
    cfg = render_cfg(fixture_repo, tmp_path, mflux_batch_idle_s=0.1)
    command = [render.sys.executable, "-u", "-c",
               "import sys,json,time; json.loads(sys.stdin.readline()); "
               "print(json.dumps({'ok':True}),flush=True); time.sleep(0.15)"]
    session = real_batch_launcher(cfg, threading.Event(), worker_command=command)
    try:
        session.render({"prompt": "fake"}, 5)
        session.process.wait(timeout=5)
        deadline = time.monotonic() + 5
        while not session._closed and time.monotonic() < deadline:
            time.sleep(0.01)
        assert session._closed
        # Another session can acquire the lock after the first process exits.
        second = real_batch_launcher(cfg, threading.Event(), worker_command=command)
        second.close()
    finally:
        session.close()


def test_batch_session_timeout_closes_process_and_releases_slot(fixture_repo, tmp_path,
                                                               real_batch_launcher):
    cfg = render_cfg(fixture_repo, tmp_path, mflux_load_timeout_s=0.1)
    sleeper = [render.sys.executable, "-u", "-c", "import time; time.sleep(30)"]
    session = real_batch_launcher(cfg, threading.Event(), worker_command=sleeper)
    with pytest.raises(render.RenderError, match="timed out"):
        session.render({"prompt": "fake"}, 0.2)
    assert not session.alive
    second = real_batch_launcher(cfg, threading.Event(), worker_command=sleeper)
    second.close()


def test_batch_session_reports_failure_and_cancels(fixture_repo, tmp_path, real_batch_launcher):
    cfg = render_cfg(fixture_repo, tmp_path)
    command = [render.sys.executable, "-u", "-c",
               "import sys,json; sys.stdin.readline(); "
               "print(json.dumps({'ok':False,'error':'test failure'}),flush=True)"]
    session = real_batch_launcher(cfg, threading.Event(), worker_command=command)
    with pytest.raises(render.RenderError, match="test failure"):
        session.render({}, 5)
    assert not session.alive


def test_render_worker_reuses_session_across_queue_passes(fixture_repo, tmp_path, monkeypatch):
    import time

    from gittok import db
    from tests.test_render import card_row, seed_pending

    cfg = render_cfg(fixture_repo, tmp_path, worker_interval_s=0.01)
    sessions = []

    class Session:
        alive = True

        def render(self, request, timeout):
            Path(request["output"]).write_bytes(png_bytes())

        def close(self):
            self.alive = False

    def start(cfg, cancel):
        session = Session()
        sessions.append(session)
        return session

    monkeypatch.setattr(render, "_start_batch_process", start)
    monkeypatch.setattr(render, "worker_check", lambda model: None)
    from gittok import image_model
    from tests.test_image_model import write_model

    write_model(image_model.model_dir(cfg))
    worker = render.RenderWorker(lambda: cfg)
    visual = {"kind": "illustration", "prompt": "one"}
    (first,) = seed_pending(cfg, fixture_repo, visual)
    worker.start()
    try:
        deadline = time.monotonic() + 5
        while card_row(cfg, first)["status"] != "ready" and time.monotonic() < deadline:
            time.sleep(0.01)
        assert card_row(cfg, first)["status"] == "ready"
        # Add after the first pass has finished, as a late writer would submit cards.
        with db.open_db(cfg.settings.data_dir / "gittok.db") as conn:
            row = conn.execute("SELECT * FROM cards WHERE id=?", (first,)).fetchone()
            cols = list(row.keys())
            vals = [row[k] for k in cols]
            vals[cols.index("id")] = "c_late"
            vals[cols.index("status")] = "pending_render"
            vals[cols.index("story_key")] = "late-render-story"
            conn.execute(f"INSERT INTO cards ({','.join(cols)}) VALUES "
                         f"({','.join('?' for _ in cols)})", vals)
            conn.commit()
        deadline = time.monotonic() + 5
        while card_row(cfg, "c_late")["status"] != "ready" and time.monotonic() < deadline:
            time.sleep(0.01)
        assert card_row(cfg, "c_late")["status"] == "ready"
        assert len(sessions) == 1
    finally:
        worker.stop()
    assert not sessions[0].alive


def test_reusable_backend_keeps_model_parts_and_clears_prompt_caches(tmp_path, monkeypatch):
    import sys
    from types import ModuleType, SimpleNamespace

    from gittok import mflux_worker

    # Block package discovery completely; every external module below is a stub.
    for name in ("mlx", "mflux", "mflux.callbacks", "mflux.callbacks.instances", "mflux.models",
                 "mflux.models.common"):
        module = ModuleType(name)
        module.__path__ = []
        monkeypatch.setitem(sys.modules, name, module)

    callbacks, models, jobs, cleared = [], [], [], []
    mx = ModuleType("mlx.core")
    mx.clear_cache = lambda: cleared.append(True)
    monkeypatch.setitem(sys.modules, "mlx.core", mx)

    class Model:
        def __init__(self, **kwargs):
            models.append(kwargs)
            self.callbacks = SimpleNamespace(register=callbacks.append)
            self.prompt_cache = {"old prompt": "embedding"}

        def generate_image(self, **kwargs):
            jobs.append(kwargs)
            return SimpleNamespace(save=lambda **kw: Path(kw["path"]).write_bytes(png_bytes()))

    for name, attrs in {
        "mflux.models.z_image": {"ZImage": Model},
        "mflux.models.common.config": {
            "ModelConfig": SimpleNamespace(from_name=lambda **kwargs: kwargs)},
        "mflux.callbacks.instances.memory_saver": {
            "MemorySaver": lambda **kwargs: kwargs},
    }.items():
        module = ModuleType(name)
        module.__dict__.update(attrs)
        monkeypatch.setitem(sys.modules, name, module)

    request = {"model": "z-image-turbo", "path": "/saved", "quantize": 4, "low_ram": True,
               "prompt": "first", "seed": 10, "width": 64, "height": 48, "steps": 8,
               "output": str(tmp_path / "out.png")}
    engine = mflux_worker.load_backend(request)
    engine(request)
    engine({**request, "prompt": "second", "seed": 20})
    assert len(models) == 1 and models[0]["quantize"] is None
    assert [job["prompt"] for job in jobs] == ["first", "second"]
    assert [job["seed"] for job in jobs] == [10, 20]
    assert callbacks[0]["keep_text_encoder"] and callbacks[0]["keep_transformer"]
    assert callbacks[0]["model"].prompt_cache == {} and len(cleared) >= 2


def test_worker_exits_on_idle_without_importing_model_packages(fixture_repo, tmp_path,
                                                            real_batch_launcher):
    cfg = render_cfg(fixture_repo, tmp_path)
    # A future accidental eager import must fail before it can reach any real GPU library.
    command = [render.sys.executable, "-u", "-c",
               "import sys,runpy; sys.modules['mlx']=None; sys.modules['mflux']=None; "
               "sys.argv=['gittok.mflux_worker','0.1']; "
               "runpy.run_module('gittok.mflux_worker',run_name='__main__')"]
    session = real_batch_launcher(cfg, threading.Event(), worker_command=command)
    try:
        assert session.process.wait(timeout=5) == 0
    finally:
        session.close()


def test_real_protocol_reuses_one_model_then_exits_on_idle(fixture_repo, tmp_path,
                                                        real_batch_launcher):
    cfg = render_cfg(fixture_repo, tmp_path)
    loads = tmp_path / "loads"
    source = (
        "import sys; from pathlib import Path; from gittok.mflux_worker import main; "
        "sys.argv=['worker','0.2']; "
        f"exec(\"def load(request):\\n Path({str(loads)!r}).open('a').write('load\\\\n')\\n "
        "return lambda job: Path(job['output']).write_text(job['prompt'])\"); "
        "raise SystemExit(main(load=load))"
    )
    session = real_batch_launcher(cfg, threading.Event(),
                                  worker_command=[render.sys.executable, "-u", "-c", source])
    try:
        for prompt in ("one", "two"):
            out = tmp_path / f"{prompt}.txt"
            session.render({"model": "fake", "path": "", "quantize": 4, "low_ram": True,
                            "prompt": prompt, "output": str(out)}, 5)
            assert out.read_text() == prompt
        assert loads.read_text().splitlines() == ["load"]
        assert session.process.wait(timeout=5) == 0
    finally:
        session.close()


def test_cancelling_inflight_batch_kills_process(fixture_repo, tmp_path, real_batch_launcher):
    from concurrent.futures import ThreadPoolExecutor

    cfg = render_cfg(fixture_repo, tmp_path)
    started = tmp_path / "started"
    code = ("import sys,time; from pathlib import Path; sys.stdin.readline(); "
            f"Path({str(started)!r}).touch(); time.sleep(30)")
    cancel = threading.Event()
    session = real_batch_launcher(cfg, cancel,
                                  worker_command=[render.sys.executable, "-u", "-c", code])
    with ThreadPoolExecutor(max_workers=1) as pool:
        waiting = pool.submit(session.render, {}, 30)
        try:
            deadline = time.monotonic() + 5
            while not started.exists() and time.monotonic() < deadline:
                time.sleep(0.01)
            assert started.exists()
            cancel.set()
            with pytest.raises(render.RendererUnavailable, match="stopped"):
                waiting.result(timeout=5)
            assert not session.alive
        finally:
            cancel.set()
            session.close()


def test_batch_readiness_requires_the_worker_imports(tmp_path):
    # A CLI from another uv tool environment cannot supply this worker's imports.
    renderer = illustrator(tmp_path, check=lambda: "No module named 'mflux'")
    assert not renderer.available()
    assert "images extra" in renderer.why_unavailable()


def test_the_worker_check_imports_the_model_class_and_helpers(monkeypatch):
    from gittok import mflux_worker

    imported = []

    def fake_import(name):
        imported.append(name)
        if name == "mflux.callbacks.instances.memory_saver":
            raise ModuleNotFoundError("No module named 'mflux.callbacks'")
        return type("M", (), {"ZImage": object, "MemorySaver": object, "ModelConfig": object})

    monkeypatch.setattr(mflux_worker.importlib, "import_module", fake_import)
    assert "mflux.callbacks" in mflux_worker.check("z-image-turbo")
    assert "mflux.models.z_image" in imported


def test_the_first_image_of_a_batch_gets_the_load_time_too(fixture_repo, tmp_path,
                                                         real_batch_launcher):
    """Loading the model counts against mflux_load_timeout_s, not the per-image limit."""
    cfg = render_cfg(fixture_repo, tmp_path, mflux_load_timeout_s=5)
    slow = [render.sys.executable, "-u", "-c",
            "import sys,json,time\n"
            "for line in sys.stdin:\n"
            "    time.sleep(0.6)\n"
            "    print(json.dumps({'ok':True}),flush=True)\n"]
    session = real_batch_launcher(cfg, threading.Event(), worker_command=slow)
    try:
        session.render({"prompt": "one"}, 0.3)  # 0.6 s: inside the load limit
        with pytest.raises(render.RenderError, match="timed out"):
            session.render({"prompt": "two"}, 0.3)  # loaded now: 0.3 s is the limit
    finally:
        session.close()
