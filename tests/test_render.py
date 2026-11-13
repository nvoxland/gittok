import dataclasses
import struct
import subprocess
import threading
import time
import zlib
from pathlib import Path

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


class FakeRunner:
    def __init__(self, fail=False):
        self.calls = []
        self.fail = fail

    def __call__(self, cmd, timeout):
        self.calls.append((cmd, timeout))
        if self.fail:
            raise subprocess.CalledProcessError(1, cmd, stderr="boom")
        out = Path(cmd[cmd.index("--output") + 1])
        out.write_bytes(png_bytes(64, 48))


def arg(cmd, flag):
    return cmd[cmd.index(flag) + 1]


def test_illustration_renderer_builds_mflux_command(fixture_repo, tmp_path):
    cfg = render_cfg(fixture_repo, tmp_path, mflux_steps=6, mflux_quantize=4)
    runner = FakeRunner()
    r = render.IllustrationRenderer(runner=runner, command=["mflux-generate"])
    visual = {"kind": "illustration", "prompt": "stacking crates", "mascots": ["otter", "crow"]}
    (img,) = r.render(visual, cfg, {"repos": ["fixture"]})
    cmd, timeout = runner.calls[0]
    assert timeout == 120
    assert "--low-ram" in cmd
    assert cmd[0] == "mflux-generate"
    assert arg(cmd, "--prompt") == (
        "flat vector otter, ink crow, stacking crates, no text, no letters"
    )
    assert arg(cmd, "--seed") == "7"
    assert arg(cmd, "--width") == "64" and arg(cmd, "--height") == "48"
    assert arg(cmd, "--model") == "z-image-turbo"
    assert arg(cmd, "--steps") == "6" and arg(cmd, "-q") == "4"
    assert (img.width, img.height) == (64, 48)
    assert img.meta["seed"] == 7 and img.meta["model"] == "z-image-turbo"
    assert img.meta["prompt"].endswith("no text, no letters")


def test_illustration_renderer_uses_saved_model_path(fixture_repo, tmp_path):
    """A pre-quantized folder (mflux-save) replaces the built-in name; no -q at run time."""
    cfg = render_cfg(fixture_repo, tmp_path, mflux_path="~/models/z-image-turbo-q4")
    runner = FakeRunner()
    r = render.IllustrationRenderer(runner=runner, command=["mflux-generate-z-image"])
    (img,) = r.render({"kind": "illustration", "prompt": "crates"}, cfg, {"repos": ["fixture"]})
    cmd, _ = runner.calls[0]
    expanded = str(Path.home() / "models/z-image-turbo-q4")  # mflux gets no shell: expand ~ here
    assert arg(cmd, "--model") == expanded
    assert arg(cmd, "--base-model") == "z-image-turbo"
    assert "-q" not in cmd and "--quantize" not in cmd
    assert img.meta["model"] == expanded


def test_illustration_default_mascot_is_first_repos(fixture_repo, tmp_path):
    cfg = render_cfg(fixture_repo, tmp_path)
    runner = FakeRunner()
    r = render.IllustrationRenderer(runner=runner, command=["x"])
    r.render({"kind": "illustration", "prompt": "p"}, cfg, {"repos": ["fixture"]})
    assert arg(runner.calls[0][0], "--prompt").startswith("flat vector otter, p")


def test_comic_renders_one_image_per_panel_with_seed_offset(fixture_repo, tmp_path):
    cfg = render_cfg(fixture_repo, tmp_path)
    runner = FakeRunner()
    r = render.IllustrationRenderer(runner=runner, command=["x"])
    visual = {"kind": "comic", "panels": [{"prompt": "one"}, {"prompt": "two"}]}
    imgs = r.render(visual, cfg, {"repos": ["fixture"]})
    assert len(imgs) == 2
    assert [arg(c, "--seed") for c, _ in runner.calls] == ["7", "8"]
    assert "two" in arg(runner.calls[1][0], "--prompt")


def test_illustration_subprocess_failure_is_render_error(fixture_repo, tmp_path):
    cfg = render_cfg(fixture_repo, tmp_path)
    r = render.IllustrationRenderer(runner=FakeRunner(fail=True), command=["x"])
    with pytest.raises(render.RenderError, match="boom"):
        r.render({"kind": "illustration", "prompt": "p"}, cfg, {"repos": ["fixture"]})


def test_illustration_unavailable_without_mflux(monkeypatch, tmp_path):
    monkeypatch.setattr(render.sys, "executable", str(tmp_path / "python"))
    monkeypatch.setattr(render.shutil, "which", lambda name: None)
    monkeypatch.setattr(render.importlib.util, "find_spec", lambda name: None)
    r = render.IllustrationRenderer()
    assert r.available() is False
    with pytest.raises(render.RendererUnavailable):
        r.render({"kind": "illustration", "prompt": "p"}, None, {"repos": []})


def test_illustration_unavailable_until_saved_model_exists(tmp_path):
    """mflux_path names a folder mflux-save has not written yet: wait, do not fail cards."""
    missing = tmp_path / "z-image-turbo-q4"
    r = render.IllustrationRenderer(command=["x"], path=str(missing))
    assert r.available() is False
    with pytest.raises(render.RendererUnavailable, match="mflux-save"):
        r.render({"kind": "illustration", "prompt": "p"}, None, {"repos": []})
    missing.mkdir()
    assert r.available() is False  # an empty or interrupted export is not ready
    (missing / "0.safetensors").write_bytes(b"weights")
    assert r.available() is True


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
    cfg = render_cfg(fixture_repo, tmp_path)
    with db.open_db(cfg.settings.data_dir / "gittok.db") as conn:
        render._mark_failed(conn, "c_gone", "boom")


def test_mflux_command_matches_model_family(monkeypatch, tmp_path):
    monkeypatch.setattr(render.sys, "executable", str(tmp_path / "python"))

    found = {
        "mflux-generate-z-image": "/bin/zi",
        "mflux-generate": "/bin/gen",
        "mflux-generate-flux2": "/bin/f2",
    }
    monkeypatch.setattr(render.shutil, "which", lambda name: found.get(name))
    assert render._mflux_command("z-image-turbo") == ["/bin/zi"]
    assert render._mflux_command("flux2-klein-4b") == ["/bin/f2"]
    assert render._mflux_command("schnell") == ["/bin/gen"]


def test_illustration_with_no_mascot_draws_the_scene_alone(fixture_repo, tmp_path):
    cfg = dataclasses.replace(render_cfg(fixture_repo, tmp_path), mascots={})
    cfg = dataclasses.replace(
        cfg, repos={"fixture": dataclasses.replace(cfg.repos["fixture"], mascot=None)}
    )
    runner = FakeRunner()
    r = render.IllustrationRenderer(runner=runner, command=["x"])
    r.render({"kind": "illustration", "prompt": "stacking crates"}, cfg, {"repos": ["fixture"]})
    assert arg(runner.calls[0][0], "--prompt").startswith("stacking crates, no text")
    assert arg(runner.calls[0][0], "--seed") == "0"


@pytest.mark.parametrize("model,name", [
    ("z-image-turbo", "mflux-generate-z-image"),
    ("flux2-klein-4b", "mflux-generate-flux2"),
    ("schnell", "mflux-generate"),
])
def test_mflux_command_finds_entrypoint_in_uv_tool_environment(tmp_path, monkeypatch, model, name):
    # uv exposes only gittok on PATH; mflux scripts sit beside the environment's Python.
    bindir = tmp_path / "tool" / "bin"
    bindir.mkdir(parents=True)
    python = bindir / "python"
    python.symlink_to(render.sys.executable)
    script = bindir / name
    script.write_text("#!/bin/sh\nexit 0\n")
    script.chmod(0o755)
    monkeypatch.setattr(render.sys, "executable", str(python))
    monkeypatch.setattr(render.shutil, "which", lambda name: None)
    monkeypatch.setattr(render.importlib.util, "find_spec", lambda name: None)
    assert render._mflux_command(model) == [str(script)]


def test_renderer_setup_distinguishes_installed_code_from_missing_assets(fixture_repo, tmp_path,
                                                                         monkeypatch):
    from gittok import memes

    monkeypatch.setattr(memes, "BUNDLED", tmp_path / "no-assets")
    cfg = render_cfg(fixture_repo, tmp_path, mflux_path=str(tmp_path / "saved-model"))
    monkeypatch.setattr(render, "_mflux_command",
                        lambda model="": ["/tool/bin/mflux-generate-z-image"])
    monkeypatch.setattr(render.IllustrationRenderer, "_installed", lambda self: True)
    details = render.renderer_setup(cfg)
    assert details["illustration"]["installed"] is True
    assert details["illustration"]["available"] is False
    assert "saved model" in details["illustration"]["reason"]
    assert "mflux-save" in details["illustration"]["command"]
    assert details["meme"]["installed"] is True
    assert details["meme"]["available"] is False
    assert "templates" in details["meme"]["reason"]
    assert "memes --prefetch" in details["meme"]["command"]


def test_saved_model_with_missing_shard_is_not_ready(tmp_path):
    import json

    model = tmp_path / "saved"
    model.mkdir()
    (model / "0.safetensors").write_bytes(b"weights")
    (model / "model.safetensors.index.json").write_text(json.dumps({
        "weight_map": {"a": "0.safetensors", "b": "1.safetensors"}
    }))
    renderer = render.IllustrationRenderer(command=["x"], path=str(model))
    assert not renderer.available()
    (model / "1.safetensors").write_bytes(b"more weights")
    assert renderer.available()


def test_default_illustration_runner_is_blocked_in_unit_tests(fixture_repo, tmp_path):
    cfg = render_cfg(fixture_repo, tmp_path)
    renderer = render.IllustrationRenderer(
        command=[render.sys.executable, "-c", "raise SystemExit(9)"])
    with pytest.raises(pytest.fail.Exception, match="cannot launch mflux"):
        renderer.render({"kind": "illustration", "prompt": "never actually drawn"}, cfg, {})


def test_low_ram_mode_and_timeout_can_be_overridden(fixture_repo, tmp_path):
    cfg = render_cfg(fixture_repo, tmp_path, mflux_low_ram=False, mflux_timeout_s=45)
    runner = FakeRunner()
    renderer = render.IllustrationRenderer(runner=runner, command=["x"])
    renderer.render({"kind": "illustration", "prompt": "scene"}, cfg, {})
    cmd, timeout = runner.calls[0]
    assert "--low-ram" not in cmd and timeout == 45


def test_only_one_illustration_per_home_runs_at_once(fixture_repo, tmp_path):
    from concurrent.futures import ThreadPoolExecutor

    cfg = render_cfg(fixture_repo, tmp_path)
    entered, release = threading.Event(), threading.Event()
    fake = FakeRunner()

    def slow(cmd, timeout):
        entered.set()
        assert release.wait(5)
        fake(cmd, timeout)

    first = render.IllustrationRenderer(runner=slow, command=["x"])
    second = render.IllustrationRenderer(runner=fake, command=["x"])
    visual = {"kind": "illustration", "prompt": "scene"}
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(first.render, visual, cfg, {})
        try:
            assert entered.wait(5)
            with pytest.raises(render.RendererUnavailable, match="busy"):
                second.render(visual, cfg, {})
        finally:
            release.set()
        pending.result(timeout=5)
    assert second.render(visual, cfg, {})  # the slot is released after completion


def test_renderer_runner_cancels_a_running_process(real_render_runner):
    from concurrent.futures import ThreadPoolExecutor

    cancel = threading.Event()
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(real_render_runner,
                              [render.sys.executable, "-c", "import time; time.sleep(30)"],
                              30, cancel=cancel)
        cancel.set()
        with pytest.raises(render.RendererUnavailable, match="stopped"):
            pending.result(timeout=5)


def test_renderer_runner_propagates_exit_and_times_out(real_render_runner):
    with pytest.raises(subprocess.CalledProcessError) as failed:
        real_render_runner([render.sys.executable, "-c",
                            "import sys; sys.stderr.write('test failure'); sys.exit(3)"], 5)
    assert failed.value.returncode == 3 and "test failure" in failed.value.stderr
    with pytest.raises(subprocess.TimeoutExpired):
        real_render_runner([render.sys.executable, "-c", "import time; time.sleep(30)"], 0.2)


def test_render_worker_stop_cancels_the_active_illustration(fixture_repo, tmp_path):
    cfg = render_cfg(fixture_repo, tmp_path, worker_interval_s=0.01)
    entered = threading.Event()
    renderer = render.IllustrationRenderer(command=["x"])

    def wait_for_stop(cmd, timeout):
        entered.set()
        assert renderer._cancel.wait(5)
        raise render.RendererUnavailable("rendering stopped")

    renderer._runner = wait_for_stop
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
        "import sys; from gittok.render import _default_runner; "
        f"_default_runner([sys.executable,'-c',{child!r},{str(heartbeat)!r},{str(pids)!r}],30)"
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
