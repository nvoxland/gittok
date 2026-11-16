import pytest

from gittok import db, mcp_server, render, runs
from tests.cards import illustration_card
from tests.test_render import (
    FakeRenderer,
    card_row,
    png_bytes,
    render_cfg,
    seed_pending,
)


@pytest.mark.parametrize("harness,preference,installed,expected", [
    ("claude", "auto", True, "local"),
    ("codex", "auto", True, "agent"),
    ("claude", "agent", True, "agent"),
    ("codex", "local", True, "local"),
    ("claude", "local", False, "agent"),
    ("claude", "auto", False, "agent"),
])
def test_backend_selection(fixture_repo, tmp_path, monkeypatch,
                           harness, preference, installed, expected):
    cfg = render_cfg(fixture_repo, tmp_path, image_backend=preference)
    monkeypatch.setenv("GITTOK_AGENT", harness)
    monkeypatch.setattr(render, "worker_check", lambda model: None if installed else "missing")
    assert render.image_backend(cfg) == expected
    if expected == "agent":
        assert not mcp_server.unavailable_formats(cfg) & {"mascot_scene", "comic"}
        setup = render.renderer_setup(cfg)["illustration"]
        assert setup["backend"] == "agent" and setup["available"]


def test_submitted_image_card_records_backend(fixture_repo, tmp_path, monkeypatch):
    cfg = render_cfg(fixture_repo, tmp_path)
    monkeypatch.setenv("GITTOK_AGENT", "codex")
    with db.open_db(cfg.settings.data_dir / "gittok.db") as conn:
        run_id = runs.open_run(conn, cfg, repo=None, brief="b", requested=1)
        result = runs.submit(conn, cfg, run_id, [illustration_card(fixture_repo)])
    cid = result["accepted"][0]["card_id"]
    assert db.loads(card_row(cfg, cid)["resolved"])["image_backend"] == "agent"


def test_agent_comic_handoff_is_atomic_and_worker_does_not_render_it(
    fixture_repo, tmp_path, monkeypatch,
):
    from gittok import agent_images

    monkeypatch.setenv("GITTOK_AGENT", "codex")
    cfg = render_cfg(fixture_repo, tmp_path)
    visual = {"kind": "comic", "panels": [{"prompt": "one"}, {"prompt": "two"}]}
    (cid,) = seed_pending(cfg, fixture_repo, visual)
    with db.open_db(cfg.settings.data_dir / "gittok.db") as conn:
        run_id = card_row(cfg, cid)["run_id"]
        requests = agent_images.pending(conn, cfg, run_id)
        (request,) = requests
        assert request["card_id"] == cid
        assert [p["prompt"] for p in request["images"]] == [
            f"flat vector otter, {scene}, no text, no letters" for scene in ("one", "two")
        ]
        # Even a different harness with a working renderer cannot consume this card.
        monkeypatch.setenv("GITTOK_AGENT", "claude")
        counts = render.render_pending(conn, cfg, {"illustration": FakeRenderer()})
        assert counts["rendered"] == 0
        paths = []
        for n in range(2):
            path = cfg.settings.data_dir / "agent-images" / f"panel{n}.png"
            path.write_bytes(png_bytes())
            paths.append(str(path))
        with pytest.raises(agent_images.ImageError, match="2 images"):
            agent_images.submit(conn, cfg, cid, paths[:1])
        assert card_row(cfg, cid)["status"] == "pending_render"
        assert agent_images.submit(conn, cfg, cid, paths)["status"] == "ready"
        assert agent_images.submit(conn, cfg, cid, paths)["status"] == "ready"
        count = conn.execute("SELECT count(*) FROM assets WHERE card_id=?", (cid,)).fetchone()[0]
        assert count == 2
        assert agent_images.pending(conn, cfg, run_id) == []


def test_agent_rejects_files_outside_staging_and_corrupt_images(fixture_repo, tmp_path):
    from gittok import agent_images

    cfg = render_cfg(fixture_repo, tmp_path, image_backend="agent")
    (cid,) = seed_pending(cfg, fixture_repo, {"kind": "illustration", "prompt": "one"})
    with db.open_db(cfg.settings.data_dir / "gittok.db") as conn:
        agent_images.pending(conn, cfg, card_row(cfg, cid)["run_id"])
        outside = tmp_path / "outside.png"
        outside.write_bytes(png_bytes())
        with pytest.raises(agent_images.ImageError, match="agent-images"):
            agent_images.submit(conn, cfg, cid, [str(outside)])
        path = cfg.settings.data_dir / "agent-images" / "bad.png"
        path.symlink_to(outside)
        with pytest.raises(agent_images.ImageError, match="agent-images"):
            agent_images.submit(conn, cfg, cid, [str(path)])
        path.unlink()
        path.write_bytes(b"not an image")
        with pytest.raises(agent_images.ImageError, match="image"):
            agent_images.submit(conn, cfg, cid, [str(path)])
        assert card_row(cfg, cid)["status"] == "pending_render"


def test_agent_config_invalid_backend_is_rejected(tmp_path):
    from gittok.config import ConfigError, RenderSettings, _section

    with pytest.raises(ConfigError, match="image_backend"):
        _section(RenderSettings, {"image_backend": "typo"}, "render", tmp_path / "settings.yaml")


@pytest.mark.anyio
async def test_mcp_image_handoff_can_resume_after_run_finishes(fixture_repo, tmp_path, monkeypatch):
    from mcp.client import Client

    from tests.test_mcp_e2e import data

    monkeypatch.setenv("GITTOK_AGENT", "codex")
    cfg = render_cfg(fixture_repo, tmp_path)
    with db.open_db(cfg.settings.data_dir / "gittok.db") as conn:
        run_id = runs.open_run(conn, cfg, repo=None, brief="b", requested=1)
    async with Client(mcp_server.build_server(lambda: cfg)) as client:
        result = data(await client.call_tool("submit_cards", {
            "run_id": run_id, "cards": [illustration_card(fixture_repo)],
        }))
        cid = result["accepted"][0]["card_id"]
        data(await client.call_tool("finish_run", {"run_id": run_id}))
        (request,) = data(await client.call_tool("get_image_requests", {"run_id": run_id}))
        assert request["card_id"] == cid
        from pathlib import Path

        path = Path(request["staging_dir"]) / "image.png"
        path.write_bytes(b"bad")
        result = await client.call_tool("submit_images", {"card_id": cid, "paths": [str(path)]})
        assert result.is_error and "cannot read generated image" in result.content[0].text
        path.write_bytes(png_bytes())
        result = data(await client.call_tool("submit_images", {
            "card_id": cid, "paths": [str(path)],
        }))
        assert result["status"] == "ready"


def test_waiting_agent_cards_do_not_starve_python_queue(fixture_repo, tmp_path):
    from gittok import agent_images
    from tests.test_render import MEME

    cfg = render_cfg(fixture_repo, tmp_path, image_backend="agent")
    ids = seed_pending(cfg, fixture_repo, {"kind": "illustration", "prompt": "one"}, count=12)
    with db.open_db(cfg.settings.data_dir / "gittok.db") as conn:
        agent_images.pending(conn, cfg, card_row(cfg, ids[0])["run_id"])
        spec = db.loads(card_row(cfg, ids[-1])["spec"])
        spec["visual"] = MEME
        conn.execute("UPDATE cards SET spec=?, resolved='{}' WHERE id=?", (db.dumps(spec), ids[-1]))
        conn.commit()
        assert render.render_pending(conn, cfg, {"meme": FakeRenderer()}, limit=10)["rendered"] == 1


def test_native_image_tool_can_submit_data_urls_without_file_handoff(fixture_repo, tmp_path):
    import base64

    from gittok import agent_images

    cfg = render_cfg(fixture_repo, tmp_path, image_backend="agent")
    (cid,) = seed_pending(cfg, fixture_repo, {"kind": "illustration", "prompt": "one"})
    with db.open_db(cfg.settings.data_dir / "gittok.db") as conn:
        agent_images.pending(conn, cfg, card_row(cfg, cid)["run_id"])
        with pytest.raises(agent_images.ImageError, match="data URL"):
            agent_images.submit(conn, cfg, cid, data_urls=["https://example.com/image.png"])
        with pytest.raises(agent_images.ImageError, match="data URL"):
            agent_images.submit(conn, cfg, cid, data_urls=["data:image/png;base64,broken!"])
        url = "data:image/png;base64," + base64.b64encode(png_bytes()).decode()
        result = agent_images.submit(conn, cfg, cid, data_urls=[url])
        assert result["status"] == "ready"
