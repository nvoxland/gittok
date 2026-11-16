import dataclasses
import struct
import subprocess
import threading
import time
import zlib
from types import SimpleNamespace

import pytest

from gittok import db, render, runs
from gittok.config import Mascot, RenderSettings
from gittok.render import RenderedImage
from tests.cards import text_card
from tests.conftest import make_config


def png_bytes(w=4, h=6) -> bytes:
    def chunk(tag, body):
        return struct.pack(">I", len(body)) + tag + body + struct.pack(">I", zlib.crc32(tag + body))

    ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
    raw = b"".join(b"\x00" + b"\x00\x00\x00" * w for _ in range(h))
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


def render_cfg(fixture_repo, tmp_path, **render_kw):
    cfg = make_config(fixture_repo, tmp_path)
    repo = dataclasses.replace(cfg.repos["fixture"], mascot="otter")
    settings = dataclasses.replace(
        cfg.settings, render=RenderSettings(image_width=64, image_height=48, **render_kw)
    )
    return dataclasses.replace(
        cfg,
        repos={"fixture": repo},
        settings=settings,
        mascots={
            "otter": Mascot("otter", "fixture", "flat vector otter", 7),
            "crow": Mascot("crow", None, "ink crow", 99),
        },
    )


def ready_model(tmp_path):
    from tests.test_image_model import write_model

    return write_model(tmp_path / "model")


def illustrator(tmp_path, check=lambda: None, path=None):
    return render.IllustrationRenderer(
        model="z-image-turbo", path=path or ready_model(tmp_path), check=check
    )


def test_illustration_request_carries_prompt_seed_size_and_model(fixture_repo, tmp_path, batch):
    cfg = render_cfg(fixture_repo, tmp_path, mflux_steps=6)
    r = illustrator(tmp_path)
    visual = {"kind": "illustration", "prompt": "stacking crates", "mascots": ["otter", "crow"]}
    (img,) = r.render(visual, cfg, {"repos": ["fixture"]})
    request, timeout = batch.calls[0]
    assert timeout == 120
    assert request["prompt"] == "flat vector otter, ink crow, stacking crates, no text, no letters"
    assert request["seed"] == 7 and (request["width"], request["height"]) == (64, 48)
    assert request["model"] == "z-image-turbo" and request["steps"] == 6
    assert request["path"] == str(tmp_path / "model") and request["low_ram"] is True
    assert "quantize" not in request  # the downloaded model is quantized already
    assert (img.width, img.height) == (64, 48)
    assert img.meta["seed"] == 7 and img.meta["model"] == "z-image-turbo"
    assert img.meta["prompt"].endswith("no text, no letters")


def test_illustration_default_mascot_is_first_repos(fixture_repo, tmp_path, batch):
    cfg = render_cfg(fixture_repo, tmp_path)
    illustrator(tmp_path).render({"kind": "illustration", "prompt": "p"}, cfg,
                                 {"repos": ["fixture"]})
    assert batch.calls[0][0]["prompt"].startswith("flat vector otter, p")


def test_comic_renders_one_image_per_panel_with_seed_offset(fixture_repo, tmp_path, batch):
    cfg = render_cfg(fixture_repo, tmp_path)
    visual = {"kind": "comic", "panels": [{"prompt": "one"}, {"prompt": "two"}]}
    imgs = illustrator(tmp_path).render(visual, cfg, {"repos": ["fixture"]})
    assert len(imgs) == 2
    assert [c["seed"] for c, _ in batch.calls] == [7, 8]
    assert "two" in batch.calls[1][0]["prompt"]


def test_illustration_model_failure_is_render_error(fixture_repo, tmp_path, batch):
    cfg = render_cfg(fixture_repo, tmp_path)
    batch.fail = True
    with pytest.raises(render.RenderError, match="boom"):
        illustrator(tmp_path).render({"kind": "illustration", "prompt": "p"}, cfg,
                                     {"repos": ["fixture"]})


def test_illustration_unavailable_when_the_model_code_cannot_load(tmp_path, batch):
    r = illustrator(tmp_path, check=lambda: "mflux is not installed")
    assert r.available() is False
    with pytest.raises(render.RendererUnavailable, match="not installed"):
        r.render({"kind": "illustration", "prompt": "p"}, None, {"repos": []})
    assert batch.calls == []


def test_illustration_waits_until_the_model_is_downloaded(tmp_path, batch):
    """A missing or partial model: cards wait as pending_render, they do not fail."""
    from tests.test_image_model import write_model

    folder = tmp_path / "not-yet"
    r = illustrator(tmp_path, path=folder)
    assert r.available() is False
    with pytest.raises(render.RendererUnavailable, match="downloaded"):
        r.render({"kind": "illustration", "prompt": "p"}, None, {"repos": []})
    write_model(folder, skip={"vae"})
    assert r.available() is False
    import shutil

    shutil.rmtree(folder)
    write_model(folder)
    assert r.available() is True


def test_worker_check_imports_what_the_batch_uses(monkeypatch):
    """The installed check runs the worker's own imports (not a CLI script), in a child
    process, so a moved mflux class shows up here and not as failed cards."""
    calls = []

    def run(cmd, **kw):
        calls.append(cmd)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(render.subprocess, "run", run)
    assert render.check_worker("z-image-turbo") is None
    assert calls == [[render.sys.executable, "-m", "gittok.mflux_worker", "--check",
                      "z-image-turbo"]]
    monkeypatch.setattr(render.subprocess, "run", lambda cmd, **kw: SimpleNamespace(
        returncode=1, stdout="", stderr="ModuleNotFoundError: No module named 'mflux'"))
    assert "mflux" in render.check_worker("z-image-turbo")


class FakeRenderer:
    def __init__(self, is_available=True, error=None, n=1):
        self.is_available = is_available
        self.error = error
        self.n = n
        self.calls = 0

    def available(self):
        return self.is_available

    def render(self, visual, cfg, spec):
        self.calls += 1
        if self.error:
            raise self.error
        n = len(visual["panels"]) if visual.get("kind") == "comic" else self.n
        return [
            RenderedImage(png_bytes(10, 20), 10, 20, {"model": "fake", "seed": i, "prompt": "p"})
            for i in range(n)
        ]


def seed_pending(cfg, fixture_repo, visual, count=1):
    with db.open_db(cfg.settings.data_dir / "gittok.db") as conn:
        run_id = runs.open_run(conn, cfg, repo=None, brief="b", requested=5)
        res = runs.submit(conn, cfg, run_id, [text_card(fixture_repo)])
        ids = [res["accepted"][0]["card_id"]]
        for i in range(1, count):
            conn.execute(
                "INSERT INTO cards(id, run_id, repo_id, story_type, format, persona, tone, "
                "spec, resolved, status, story_key, created_at) "
                "SELECT ?, run_id, repo_id, story_type, format, persona, tone, "
                "spec, resolved, status, ?, created_at FROM cards WHERE id = ?",
                (f"c_copy{i}", f"key{i}", ids[0]),
            )
            ids.append(f"c_copy{i}")
        for i, cid in enumerate(ids):
            spec = db.loads(conn.execute("SELECT spec FROM cards WHERE id=?", (cid,)).fetchone()[0])
            spec["visual"] = visual
            conn.execute(
                "UPDATE cards SET status='pending_render', spec=?, resolved=?, "
                "created_at=? WHERE id=?",
                (db.dumps(spec), db.dumps({"visual": None}), f"2026-01-0{i + 1}T00:00:00Z", cid),
            )
        conn.commit()
    return ids


def card_row(cfg, cid):
    with db.open_db(cfg.settings.data_dir / "gittok.db") as conn:
        return conn.execute("SELECT * FROM cards WHERE id=?", (cid,)).fetchone()


MEME = {"kind": "meme", "template": "drake", "lines": ["a", "b"]}


def test_render_pending_writes_assets_and_marks_ready(fixture_repo, tmp_path):
    cfg = render_cfg(fixture_repo, tmp_path)
    (cid,) = seed_pending(cfg, fixture_repo, MEME)
    with db.open_db(cfg.settings.data_dir / "gittok.db") as conn:
        counts = render.render_pending(conn, cfg, {"meme": FakeRenderer()})
        assets = conn.execute("SELECT * FROM assets WHERE card_id=?", (cid,)).fetchall()
    assert counts == {"rendered": 1, "failed": 0, "waiting": 0}
    row = card_row(cfg, cid)
    assert row["status"] == "ready"
    assert db.loads(row["resolved"])["visual"] == {
        "images": [f"/assets/{cid}/0.png"],
        "width": 10,
        "height": 20,
    }
    assert (cfg.settings.data_dir / "assets" / cid / "0.png").read_bytes() == png_bytes(10, 20)
    assert [(a["kind"], a["path"]) for a in assets] == [("meme", f"assets/{cid}/0.png")]
    meta = db.loads(assets[0]["meta"])
    assert meta["width"] == 10 and meta["model"] == "fake" and meta["prompt"] == "p"


def test_render_pending_comic_has_one_image_per_panel(fixture_repo, tmp_path):
    cfg = render_cfg(fixture_repo, tmp_path)
    comic = {"kind": "comic", "panels": [{"prompt": "a"}, {"prompt": "b"}, {"prompt": "c"}]}
    (cid,) = seed_pending(cfg, fixture_repo, comic)
    with db.open_db(cfg.settings.data_dir / "gittok.db") as conn:
        render.render_pending(conn, cfg, {"illustration": FakeRenderer()})
    visual = db.loads(card_row(cfg, cid)["resolved"])["visual"]
    assert visual["images"] == [f"/assets/{cid}/{n}.png" for n in range(3)]


def test_render_pending_failure_marks_render_failed(fixture_repo, tmp_path):
    cfg = render_cfg(fixture_repo, tmp_path)
    (cid,) = seed_pending(cfg, fixture_repo, MEME)
    bad = FakeRenderer(error=render.RenderError("memegen returned 404"))
    with db.open_db(cfg.settings.data_dir / "gittok.db") as conn:
        counts = render.render_pending(conn, cfg, {"meme": bad})
    assert counts == {"rendered": 0, "failed": 1, "waiting": 0}
    row = card_row(cfg, cid)
    assert row["status"] == "render_failed"
    assert "404" in db.loads(row["resolved"])["render_error"]


def test_render_pending_unavailable_stays_pending(fixture_repo, tmp_path):
    cfg = render_cfg(fixture_repo, tmp_path)
    (cid,) = seed_pending(cfg, fixture_repo, MEME)
    for renderer in (
        FakeRenderer(is_available=False),
        FakeRenderer(error=render.RendererUnavailable("down")),
    ):
        with db.open_db(cfg.settings.data_dir / "gittok.db") as conn:
            counts = render.render_pending(conn, cfg, {"meme": renderer})
        assert counts == {"rendered": 0, "failed": 0, "waiting": 1}
        assert card_row(cfg, cid)["status"] == "pending_render"


def test_render_pending_oldest_first_with_limit(fixture_repo, tmp_path):
    cfg = render_cfg(fixture_repo, tmp_path)
    ids = seed_pending(cfg, fixture_repo, MEME, count=3)
    with db.open_db(cfg.settings.data_dir / "gittok.db") as conn:
        counts = render.render_pending(conn, cfg, {"meme": FakeRenderer()}, limit=2)
    assert counts["rendered"] == 2
    assert [card_row(cfg, c)["status"] for c in ids] == ["ready", "ready", "pending_render"]


def test_retry_failed_resets_status(fixture_repo, tmp_path):
    cfg = render_cfg(fixture_repo, tmp_path)
    (cid,) = seed_pending(cfg, fixture_repo, MEME)
    with db.open_db(cfg.settings.data_dir / "gittok.db") as conn:
        render.render_pending(conn, cfg, {"meme": FakeRenderer(error=render.RenderError("x"))})
        assert render.retry_failed(conn) == 1
    row = card_row(cfg, cid)
    assert row["status"] == "pending_render"
    assert "render_error" not in db.loads(row["resolved"])


def test_render_worker_renders_in_background_and_stops(fixture_repo, tmp_path):
    cfg = render_cfg(fixture_repo, tmp_path, worker_interval_s=0.01)
    (cid,) = seed_pending(cfg, fixture_repo, MEME)
    worker = render.RenderWorker(lambda: cfg, renderers={"meme": FakeRenderer()})
    worker.start()
    try:
        for _ in range(200):
            if card_row(cfg, cid)["status"] == "ready":
                break
            time.sleep(0.02)
    finally:
        worker.stop()
    assert card_row(cfg, cid)["status"] == "ready"
    assert not worker.is_alive()


def test_render_worker_survives_a_failing_pass(fixture_repo, tmp_path, monkeypatch):
    def boom():
        raise RuntimeError("config broke")

    handled = threading.Event()  # set when the worker has caught the failure of a pass
    monkeypatch.setattr(render.log, "exception", lambda *a, **k: handled.set())
    worker = render.RenderWorker(boom, renderers={})
    worker.start()
    assert handled.wait(5)
    assert worker.is_alive()
    worker.stop()
    assert not worker.is_alive()


class ReentrantRenderer(FakeRenderer):
    """While rendering the first card, runs a second pass on another connection."""

    def __init__(self, cfg):
        super().__init__()
        self.cfg = cfg
        self.inner_done = False
        self.visuals = []

    def render(self, visual, cfg, spec):
        self.visuals.append(spec["visual"])
        if not self.inner_done:
            self.inner_done = True
            with db.open_db(self.cfg.settings.data_dir / "gittok.db") as conn2:
                render.render_pending(conn2, self.cfg, {"meme": self})
        return super().render(visual, cfg, spec)


def test_interleaved_passes_render_each_card_once(fixture_repo, tmp_path):
    cfg = render_cfg(fixture_repo, tmp_path)
    ids = seed_pending(cfg, fixture_repo, MEME, count=3)
    r = ReentrantRenderer(cfg)
    with db.open_db(cfg.settings.data_dir / "gittok.db") as conn:
        counts = render.render_pending(conn, cfg, {"meme": r})
    assert r.calls == 3
    assert [card_row(cfg, c)["status"] for c in ids] == ["ready"] * 3
    assert counts["rendered"] + counts["failed"] <= 3


def test_claimed_card_is_rendering_during_render(fixture_repo, tmp_path):
    cfg = render_cfg(fixture_repo, tmp_path)
    (cid,) = seed_pending(cfg, fixture_repo, MEME)
    seen = []

    class Peek(FakeRenderer):
        def render(self, visual, cfg_, spec):
            seen.append(card_row(cfg, cid)["status"])
            return super().render(visual, cfg_, spec)

    with db.open_db(cfg.settings.data_dir / "gittok.db") as conn:
        render.render_pending(conn, cfg, {"meme": Peek()})
    assert seen == ["rendering"]


def test_unavailable_during_render_returns_to_pending(fixture_repo, tmp_path):
    cfg = render_cfg(fixture_repo, tmp_path)
    (cid,) = seed_pending(cfg, fixture_repo, MEME)
    r = FakeRenderer(error=render.RendererUnavailable("down"))
    with db.open_db(cfg.settings.data_dir / "gittok.db") as conn:
        render.render_pending(conn, cfg, {"meme": r})
    assert card_row(cfg, cid)["status"] == "pending_render"


def test_stale_rendering_cards_are_reset(fixture_repo, tmp_path):
    from datetime import UTC, datetime, timedelta

    cfg = render_cfg(fixture_repo, tmp_path)
    old, fresh = seed_pending(cfg, fixture_repo, MEME, count=2)
    now = datetime.now(UTC)
    with db.open_db(cfg.settings.data_dir / "gittok.db") as conn:
        for cid, age in ((old, 31), (fresh, 5)):
            since = (now - timedelta(minutes=age)).isoformat()
            conn.execute(
                "UPDATE cards SET status='rendering', resolved=? WHERE id=?",
                (db.dumps({"visual": None, "rendering_since": since}), cid),
            )
        conn.commit()
        render.render_pending(conn, cfg, {"meme": FakeRenderer(is_available=False)})
    assert card_row(cfg, old)["status"] == "pending_render"
    assert card_row(cfg, fresh)["status"] == "rendering"


def test_not_ready_cards_are_not_in_feed(fixture_repo, tmp_path):
    cfg = render_cfg(fixture_repo, tmp_path)
    (cid,) = seed_pending(cfg, fixture_repo, MEME)
    with db.open_db(cfg.settings.data_dir / "gittok.db") as conn:
        conn.execute("UPDATE cards SET status='rendering' WHERE id=?", (cid,))
        conn.commit()
        assert conn.execute("SELECT count(*) FROM cards WHERE status='ready'").fetchone()[0] == 0


def test_failed_store_removes_partial_pngs(fixture_repo, tmp_path):
    cfg = render_cfg(fixture_repo, tmp_path)
    (cid,) = seed_pending(cfg, fixture_repo, MEME)

    class Broken(FakeRenderer):
        def render(self, visual, cfg_, spec):
            return [RenderedImage(png_bytes(), 4, 6), RenderedImage(None, 4, 6)]

    with db.open_db(cfg.settings.data_dir / "gittok.db") as conn:
        counts = render.render_pending(conn, cfg, {"meme": Broken()})
    assert counts["failed"] == 1
    assert card_row(cfg, cid)["status"] == "render_failed"
    folder = cfg.settings.data_dir / "assets" / cid
    assert not folder.exists() or list(folder.iterdir()) == []


def test_corrupt_spec_fails_that_card_only(fixture_repo, tmp_path):
    cfg = render_cfg(fixture_repo, tmp_path)
    bad, good = seed_pending(cfg, fixture_repo, MEME, count=2)
    with db.open_db(cfg.settings.data_dir / "gittok.db") as conn:
        conn.execute("UPDATE cards SET spec='{not json' WHERE id=?", (bad,))
        conn.commit()
        counts = render.render_pending(conn, cfg, {"meme": FakeRenderer()})
    assert counts == {"rendered": 1, "failed": 1, "waiting": 0}
    assert card_row(cfg, bad)["status"] == "render_failed"
    assert card_row(cfg, good)["status"] == "ready"


def test_unknown_kind_fails_that_card_only(fixture_repo, tmp_path):
    cfg = render_cfg(fixture_repo, tmp_path)
    (cid,) = seed_pending(cfg, fixture_repo, {"nokind": 1})
    with db.open_db(cfg.settings.data_dir / "gittok.db") as conn:
        counts = render.render_pending(conn, cfg, {"meme": FakeRenderer()})
    assert counts["failed"] == 1
    assert card_row(cfg, cid)["status"] == "render_failed"


def test_mark_failed_tolerates_deleted_card(fixture_repo, tmp_path):
    from gittok import render_jobs

    cfg = render_cfg(fixture_repo, tmp_path)
    with db.open_db(cfg.settings.data_dir / "gittok.db") as conn:
        render_jobs.fail(conn, "c_gone", "boom")


def test_illustration_with_no_mascot_draws_the_scene_alone(fixture_repo, tmp_path, batch):
    cfg = dataclasses.replace(render_cfg(fixture_repo, tmp_path), mascots={})
    cfg = dataclasses.replace(
        cfg, repos={"fixture": dataclasses.replace(cfg.repos["fixture"], mascot=None)}
    )
    illustrator(tmp_path).render({"kind": "illustration", "prompt": "stacking crates"}, cfg,
                                 {"repos": ["fixture"]})
    assert batch.calls[0][0]["prompt"].startswith("stacking crates, no text")
    assert batch.calls[0][0]["seed"] == 0


def test_renderer_setup_says_what_is_missing_and_how_it_gets_there(fixture_repo, tmp_path,
                                                                   monkeypatch):
    cfg = render_cfg(fixture_repo, tmp_path)
    monkeypatch.setattr(render, "worker_check", lambda model: None)
    ill = render.renderer_setup(cfg)["illustration"]
    assert ill["installed"] is True and ill["available"] is False
    assert ill["download"]["state"] == "missing" and "downloaded" in ill["reason"]
    assert ill["command"] == "gittok images --download"
    assert render.renderer_setup(cfg)["meme"]["available"] is True  # bundled
    monkeypatch.setattr(render, "worker_check", lambda model: "No module named 'mflux'")
    ill = render.renderer_setup(cfg)["illustration"]
    assert ill["installed"] is False and ill["command"] is None
    assert ill["backend"] == "agent" and ill["available"] is True
    assert ill["reason"] is None and "mflux" in ill["python_reason"]


def test_low_ram_mode_and_timeout_can_be_overridden(fixture_repo, tmp_path, batch):
    cfg = render_cfg(fixture_repo, tmp_path, mflux_low_ram=False, mflux_timeout_s=45)
    illustrator(tmp_path).render({"kind": "illustration", "prompt": "scene"}, cfg, {})
    request, timeout = batch.calls[0]
    assert request["low_ram"] is False and timeout == 45


def test_render_worker_stop_cancels_the_active_illustration(fixture_repo, tmp_path,
                                                           monkeypatch):
    cfg = render_cfg(fixture_repo, tmp_path, worker_interval_s=0.01)
    entered = threading.Event()
    renderer = illustrator(tmp_path)

    class Waiting:
        alive = True

        def render(self, request, timeout):
            entered.set()
            assert renderer._cancel.wait(5)
            raise render.RendererUnavailable("rendering stopped")

        def close(self):
            self.alive = False

    monkeypatch.setattr(render, "_start_batch_process", lambda cfg, cancel: Waiting())
    (cid,) = seed_pending(cfg, fixture_repo, {"kind": "illustration", "prompt": "scene"})
    worker = render.RenderWorker(lambda: cfg, {"illustration": renderer})
    worker.start()
    try:
        assert entered.wait(5)
    finally:
        worker.stop()
    assert not worker.is_alive()
    assert card_row(cfg, cid)["status"] == "pending_render"


def test_render_supervisor_stops_children_after_parent_is_killed(tmp_path):
    """Exercise crash cleanup with tiny Python sleepers, never an image model."""
    import json
    import os
    import signal

    heartbeat, pids = tmp_path / "heartbeat", tmp_path / "pids.json"
    pulse = (
        "import sys,time; from pathlib import Path; p=Path(sys.argv[1]); "
        "exec('while True:\\n p.write_text(str(time.monotonic()))\\n time.sleep(0.05)')"
    )
    child = (
        "import os,sys,subprocess,json,time; from pathlib import Path; "
        f"p=subprocess.Popen([sys.executable,'-c',{pulse!r},sys.argv[1]]); "
        "Path(sys.argv[2]).write_text(json.dumps({'supervisor':os.getppid(),'child':p.pid})); "
        "time.sleep(30)"
    )
    outer = (
        "import os,sys,subprocess,time; "
        "subprocess.Popen([sys.executable,'-m','gittok.render_process',str(os.getpid()),"
        f"sys.executable,'-c',{child!r},{str(heartbeat)!r},{str(pids)!r}],"
        "start_new_session=True); time.sleep(30)"
    )
    parent = subprocess.Popen([render.sys.executable, "-c", outer], start_new_session=True)
    try:
        deadline = time.monotonic() + 5
        while not heartbeat.exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        assert heartbeat.exists(), "supervised child never started"
        parent.kill()
        parent.wait(timeout=5)
        time.sleep(0.6)  # the orphaned supervisor checks its parent every 0.2 seconds
        stamp = heartbeat.read_text()
        time.sleep(0.2)
        assert heartbeat.read_text() == stamp  # the grandchild was stopped too
    finally:
        if parent.poll() is None:
            parent.kill()
        parent.wait(timeout=5)
        if pids.exists():
            group = json.loads(pids.read_text())["supervisor"]
            try:
                os.killpg(group, signal.SIGKILL)
            except ProcessLookupError:
                pass


def _run_worker_once(cfg_getter):
    worker = render.RenderWorker(cfg_getter)
    worker.start()
    time.sleep(0.3)
    worker.stop()


def test_the_render_worker_starts_the_model_download_by_itself(fixture_repo, tmp_path,
                                                             monkeypatch):
    from gittok import image_model

    cfg = render_cfg(fixture_repo, tmp_path, worker_interval_s=0.05)
    started = []
    monkeypatch.setattr(render, "worker_check", lambda model: None)
    monkeypatch.setattr(image_model, "_spawn", lambda cmd, home: started.append((cmd, home)))
    _run_worker_once(lambda: cfg)
    assert len(started) == 1  # once: "starting" counts as downloading until it takes the lock
    assert started[0][0][-2:] == ["images", "--download"] and started[0][1] == cfg.root


def test_the_render_worker_does_not_download_when_the_renderer_is_not_installed(
    fixture_repo, tmp_path, monkeypatch
):
    from gittok import image_model

    cfg = render_cfg(fixture_repo, tmp_path, worker_interval_s=0.05)
    monkeypatch.setattr(image_model, "_spawn", lambda cmd, home: pytest.fail("no download"))
    _run_worker_once(lambda: cfg)  # worker_check says "not installed" in unit tests


def test_the_render_worker_rebuilds_its_renderers_when_data_dir_changes(fixture_repo, tmp_path):
    from gittok import memes

    cfg = render_cfg(fixture_repo, tmp_path, worker_interval_s=0.05)
    moved = dataclasses.replace(
        cfg, settings=dataclasses.replace(cfg.settings, data_dir=tmp_path / "moved")
    )
    current = [cfg]
    worker = render.RenderWorker(lambda: current[0])
    worker.start()
    try:
        time.sleep(0.2)
        current[0] = moved
        time.sleep(0.3)
        assert worker._active["meme"].store == memes.store(moved)
    finally:
        worker.stop()


def test_a_card_the_agent_takes_over_during_a_pass_is_not_failed(fixture_repo, tmp_path):
    first, second = seed_pending(cfg := render_cfg(fixture_repo, tmp_path),
                                 fixture_repo, {"kind": "illustration", "prompt": "x"}, count=2)

    class TakeOver(FakeRenderer):
        def render(self, visual, cfg_, spec):
            # get_image_requests reassigns the next card while this one draws
            with db.open_db(cfg.settings.data_dir / "gittok.db") as other:
                other.execute("UPDATE cards SET resolved = ? WHERE id = ?",
                              (db.dumps({"image_backend": "agent"}), second))
                other.commit()
            return super().render(visual, cfg_, spec)

    with db.open_db(cfg.settings.data_dir / "gittok.db") as conn:
        counts = render.render_pending(conn, cfg, {"illustration": TakeOver()})
    assert counts["failed"] == 0
    assert card_row(cfg, second)["status"] == "pending_render"


def test_unavailable_renderer_does_not_block_available_kinds(fixture_repo, tmp_path):
    cfg = render_cfg(fixture_repo, tmp_path)
    ids = seed_pending(cfg, fixture_repo, {"kind": "illustration", "prompt": "x"}, count=3)
    meme_visual = {"kind": "meme", "template": "drake", "lines": ["a", "b"]}
    with db.open_db(cfg.settings.data_dir / "gittok.db") as conn:
        spec = db.loads(conn.execute("SELECT spec FROM cards WHERE id=?", (ids[0],)).fetchone()[0])
        spec["visual"] = meme_visual
        conn.execute("UPDATE cards SET spec=?, created_at='2030-01-01T00:00:00Z' WHERE id=?",
                     (db.dumps(spec), ids[0]))
        conn.commit()
        render.render_pending(conn, cfg, {"meme": FakeRenderer(),
                                          "illustration": FakeRenderer(is_available=False)},
                              limit=2)
    assert card_row(cfg, ids[0])["status"] == "ready"


def test_failed_model_download_hands_local_cards_to_the_agent(fixture_repo, tmp_path, monkeypatch):
    from gittok import image_model

    cfg = render_cfg(fixture_repo, tmp_path)
    (cid,) = seed_pending(cfg, fixture_repo, {"kind": "illustration", "prompt": "x"})
    monkeypatch.setattr(image_model, "status", lambda c: {"state": "failed", "error": "boom",
                                                          "path": "p", "done": 0, "total": 0})
    monkeypatch.setattr(render, "image_backend", lambda c: "local")
    with db.open_db(cfg.settings.data_dir / "gittok.db") as conn:
        render.render_pending(conn, cfg, {"illustration": FakeRenderer(is_available=False)})
    row = card_row(cfg, cid)
    assert row["status"] == "pending_render"
    assert db.loads(row["resolved"])["image_backend"] == "agent"


def test_stale_limit_follows_render_timeouts(fixture_repo, tmp_path):
    from datetime import timedelta

    cfg = render_cfg(fixture_repo, tmp_path, mflux_timeout_s=3600.0)
    assert render.stale_limit(cfg) >= timedelta(seconds=600 + 3600)
    assert render.stale_limit(render_cfg(fixture_repo, tmp_path)) >= timedelta(minutes=30)


def test_reset_stale_can_be_limited_to_one_backend(fixture_repo, tmp_path):
    from gittok import render_jobs as jobs

    cfg = render_cfg(fixture_repo, tmp_path)
    (cid,) = seed_pending(cfg, fixture_repo, MEME)
    with db.open_db(cfg.settings.data_dir / "gittok.db") as conn:
        r = jobs.request(conn, cfg, cid, backend="local")
        assert jobs.claim(conn, r)
        res = db.loads(conn.execute("SELECT resolved FROM cards WHERE id=?", (cid,)).fetchone()[0])
        res["rendering_since"] = "2020-01-01T00:00:00+00:00"
        conn.execute("UPDATE cards SET resolved=? WHERE id=?", (db.dumps(res), cid))
        conn.commit()
        assert jobs.reset_stale_rendering(conn, backend="agent") == 0
        assert jobs.reset_stale_rendering(conn, backend="local") == 1
