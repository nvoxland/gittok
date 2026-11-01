import dataclasses
import struct
import subprocess
import time
import zlib
from pathlib import Path

import httpx
import pytest

from codescroll import db, render, runs
from codescroll.config import Mascot, RenderSettings
from codescroll.render import RenderedImage
from tests.cards import text_card
from tests.conftest import make_config


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("hello world", "hello_world"),
        ("a_b", "a__b"),
        ("a-b", "a--b"),
        ("why?", "why~q"),
        ("100%", "100~p"),
        ("#1", "~h1"),
        ("a/b", "a~sb"),
        ('say "hi"', "say_''hi''"),
        ("one\ntwo", "one~ntwo"),
        ("", "_"),
        ("  ", "__"),
    ],
)
def test_memegen_escape(text, expected):
    assert render.memegen_escape(text) == expected


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


def test_meme_renderer_fetches_escaped_url_and_reads_size():
    seen = []

    def handler(request):
        seen.append(request.url.raw_path.decode())
        return httpx.Response(200, content=png_bytes(30, 20))

    r = render.MemeRenderer("http://memegen.test", transport=httpx.MockTransport(handler))
    visual = {"kind": "meme", "template": "drake", "lines": ["a b?", "c/d"]}
    (img,) = r.render(visual, None, {})
    assert seen == ["/images/drake/a_b~q/c~sd.png"]
    assert (img.width, img.height) == (30, 20)
    assert img.meta["template"] == "drake"


def test_meme_renderer_availability_and_connection_errors():
    def down(request):
        raise httpx.ConnectError("refused")

    r = render.MemeRenderer("http://memegen.test", transport=httpx.MockTransport(down))
    assert r.available() is False
    with pytest.raises(render.RendererUnavailable):
        r.render({"template": "drake", "lines": ["x"]}, None, {})

    ok = render.MemeRenderer(
        "http://memegen.test", transport=httpx.MockTransport(lambda req: httpx.Response(200))
    )
    assert ok.available() is True


def test_meme_renderer_http_error_is_render_error():
    r = render.MemeRenderer(
        "http://memegen.test", transport=httpx.MockTransport(lambda req: httpx.Response(404))
    )
    with pytest.raises(render.RenderError):
        r.render({"template": "nope", "lines": ["x"]}, None, {})


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
    assert timeout == 300
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


def test_illustration_unavailable_without_mflux(monkeypatch):
    monkeypatch.setattr(render.shutil, "which", lambda name: None)
    monkeypatch.setattr(render.importlib.util, "find_spec", lambda name: None)
    r = render.IllustrationRenderer()
    assert r.available() is False
    with pytest.raises(render.RendererUnavailable):
        r.render({"kind": "illustration", "prompt": "p"}, None, {"repos": []})


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
    with db.open_db(cfg.settings.data_dir / "codescroll.db") as conn:
        run_id = runs.open_run(conn, cfg, repo=None, brief="b", requested=5)
        res = runs.submit(conn, cfg, run_id, [text_card(fixture_repo)])
        ids = [res["accepted"][0]["card_id"]]
        for i in range(1, count):
            conn.execute(
                "INSERT INTO cards SELECT ?, run_id, repo_id, story_type, format, persona, tone, "
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
    with db.open_db(cfg.settings.data_dir / "codescroll.db") as conn:
        return conn.execute("SELECT * FROM cards WHERE id=?", (cid,)).fetchone()


MEME = {"kind": "meme", "template": "drake", "lines": ["a", "b"]}


def test_render_pending_writes_assets_and_marks_ready(fixture_repo, tmp_path):
    cfg = render_cfg(fixture_repo, tmp_path)
    (cid,) = seed_pending(cfg, fixture_repo, MEME)
    with db.open_db(cfg.settings.data_dir / "codescroll.db") as conn:
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
    with db.open_db(cfg.settings.data_dir / "codescroll.db") as conn:
        render.render_pending(conn, cfg, {"illustration": FakeRenderer()})
    visual = db.loads(card_row(cfg, cid)["resolved"])["visual"]
    assert visual["images"] == [f"/assets/{cid}/{n}.png" for n in range(3)]


def test_render_pending_failure_marks_render_failed(fixture_repo, tmp_path):
    cfg = render_cfg(fixture_repo, tmp_path)
    (cid,) = seed_pending(cfg, fixture_repo, MEME)
    bad = FakeRenderer(error=render.RenderError("memegen returned 404"))
    with db.open_db(cfg.settings.data_dir / "codescroll.db") as conn:
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
        with db.open_db(cfg.settings.data_dir / "codescroll.db") as conn:
            counts = render.render_pending(conn, cfg, {"meme": renderer})
        assert counts == {"rendered": 0, "failed": 0, "waiting": 1}
        assert card_row(cfg, cid)["status"] == "pending_render"


def test_render_pending_oldest_first_with_limit(fixture_repo, tmp_path):
    cfg = render_cfg(fixture_repo, tmp_path)
    ids = seed_pending(cfg, fixture_repo, MEME, count=3)
    with db.open_db(cfg.settings.data_dir / "codescroll.db") as conn:
        counts = render.render_pending(conn, cfg, {"meme": FakeRenderer()}, limit=2)
    assert counts["rendered"] == 2
    assert [card_row(cfg, c)["status"] for c in ids] == ["ready", "ready", "pending_render"]


def test_retry_failed_resets_status(fixture_repo, tmp_path):
    cfg = render_cfg(fixture_repo, tmp_path)
    (cid,) = seed_pending(cfg, fixture_repo, MEME)
    with db.open_db(cfg.settings.data_dir / "codescroll.db") as conn:
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


def test_render_worker_survives_a_failing_pass(fixture_repo, tmp_path):
    def boom():
        raise RuntimeError("config broke")

    worker = render.RenderWorker(boom, renderers={})
    worker.start()
    time.sleep(0.05)
    assert worker.is_alive()
    worker.stop()
    assert not worker.is_alive()


def test_memegen_path_never_has_dot_segments():
    for lines in (["."], ["..", "ok"], ["a", "..."], [".", "."]):
        path = render.memegen_path("drake", lines)
        segs = path.removesuffix(".png").split("/")
        assert "." not in segs and ".." not in segs, path
        assert all(set(seg) != {"."} for seg in segs[3:]), path
    assert render.memegen_path("drake", ["a.b", "c"]) == "/images/drake/a.b/c.png"


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
            with db.open_db(self.cfg.settings.data_dir / "codescroll.db") as conn2:
                render.render_pending(conn2, self.cfg, {"meme": self})
        return super().render(visual, cfg, spec)


def test_interleaved_passes_render_each_card_once(fixture_repo, tmp_path):
    cfg = render_cfg(fixture_repo, tmp_path)
    ids = seed_pending(cfg, fixture_repo, MEME, count=3)
    r = ReentrantRenderer(cfg)
    with db.open_db(cfg.settings.data_dir / "codescroll.db") as conn:
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

    with db.open_db(cfg.settings.data_dir / "codescroll.db") as conn:
        render.render_pending(conn, cfg, {"meme": Peek()})
    assert seen == ["rendering"]


def test_unavailable_during_render_returns_to_pending(fixture_repo, tmp_path):
    cfg = render_cfg(fixture_repo, tmp_path)
    (cid,) = seed_pending(cfg, fixture_repo, MEME)
    r = FakeRenderer(error=render.RendererUnavailable("down"))
    with db.open_db(cfg.settings.data_dir / "codescroll.db") as conn:
        render.render_pending(conn, cfg, {"meme": r})
    assert card_row(cfg, cid)["status"] == "pending_render"


def test_stale_rendering_cards_are_reset(fixture_repo, tmp_path):
    from datetime import UTC, datetime, timedelta

    cfg = render_cfg(fixture_repo, tmp_path)
    old, fresh = seed_pending(cfg, fixture_repo, MEME, count=2)
    now = datetime.now(UTC)
    with db.open_db(cfg.settings.data_dir / "codescroll.db") as conn:
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
    with db.open_db(cfg.settings.data_dir / "codescroll.db") as conn:
        conn.execute("UPDATE cards SET status='rendering' WHERE id=?", (cid,))
        conn.commit()
        assert conn.execute("SELECT count(*) FROM cards WHERE status='ready'").fetchone()[0] == 0


def test_failed_store_removes_partial_pngs(fixture_repo, tmp_path):
    cfg = render_cfg(fixture_repo, tmp_path)
    (cid,) = seed_pending(cfg, fixture_repo, MEME)

    class Broken(FakeRenderer):
        def render(self, visual, cfg_, spec):
            return [RenderedImage(png_bytes(), 4, 6), RenderedImage(None, 4, 6)]

    with db.open_db(cfg.settings.data_dir / "codescroll.db") as conn:
        counts = render.render_pending(conn, cfg, {"meme": Broken()})
    assert counts["failed"] == 1
    assert card_row(cfg, cid)["status"] == "render_failed"
    folder = cfg.settings.data_dir / "assets" / cid
    assert not folder.exists() or list(folder.iterdir()) == []


def test_corrupt_spec_fails_that_card_only(fixture_repo, tmp_path):
    cfg = render_cfg(fixture_repo, tmp_path)
    bad, good = seed_pending(cfg, fixture_repo, MEME, count=2)
    with db.open_db(cfg.settings.data_dir / "codescroll.db") as conn:
        conn.execute("UPDATE cards SET spec='{not json' WHERE id=?", (bad,))
        conn.commit()
        counts = render.render_pending(conn, cfg, {"meme": FakeRenderer()})
    assert counts == {"rendered": 1, "failed": 1, "waiting": 0}
    assert card_row(cfg, bad)["status"] == "render_failed"
    assert card_row(cfg, good)["status"] == "ready"


def test_unknown_kind_fails_that_card_only(fixture_repo, tmp_path):
    cfg = render_cfg(fixture_repo, tmp_path)
    (cid,) = seed_pending(cfg, fixture_repo, {"nokind": 1})
    with db.open_db(cfg.settings.data_dir / "codescroll.db") as conn:
        counts = render.render_pending(conn, cfg, {"meme": FakeRenderer()})
    assert counts["failed"] == 1
    assert card_row(cfg, cid)["status"] == "render_failed"


def test_mark_failed_tolerates_deleted_card(fixture_repo, tmp_path):
    cfg = render_cfg(fixture_repo, tmp_path)
    with db.open_db(cfg.settings.data_dir / "codescroll.db") as conn:
        render._mark_failed(conn, "c_gone", "boom")


def test_mflux_command_matches_model_family(monkeypatch):
    from codescroll import render

    found = {
        "mflux-generate-z-image": "/bin/zi",
        "mflux-generate": "/bin/gen",
        "mflux-generate-flux2": "/bin/f2",
    }
    monkeypatch.setattr(render.shutil, "which", lambda name: found.get(name))
    assert render._mflux_command("z-image-turbo") == ["/bin/zi"]
    assert render._mflux_command("flux2-klein-4b") == ["/bin/f2"]
    assert render._mflux_command("schnell") == ["/bin/gen"]


def test_meme_availability_probes_one_template_not_the_full_list():
    # /templates/ lists every template and takes ~1 s; a 1 s probe flapped.
    seen = []

    def handler(request):
        seen.append(request.url.path)
        return httpx.Response(200)

    r = render.MemeRenderer("http://memegen.test", transport=httpx.MockTransport(handler))
    assert r.available() is True
    assert seen == ["/templates/drake"]
