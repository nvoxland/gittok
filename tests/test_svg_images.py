"""Claude's agent images: the illustrator subagent draws SVG and the server rasterizes it."""

from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image

from gittok import agent_images, db, home
from gittok.cli import _renderers as REAL_RENDERERS
from tests.test_render import card_row, render_cfg, seed_pending

ROOT = Path(__file__).parents[1]

SVG = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 125">'
       '<defs><linearGradient id="g"><stop offset="0" stop-color="#fc6"/>'
       '<stop offset="1" stop-color="#f60"/></linearGradient></defs>'
       '<rect width="100" height="125" fill="url(#g)"/>'
       '<circle id="c" cx="50" cy="60" r="30" fill="#4a8"/><use href="#c" x="5"/></svg>')


def _pending(cfg, fixture_repo, visual):
    (cid,) = seed_pending(cfg, fixture_repo, visual)
    return cid, card_row(cfg, cid)["run_id"]


def test_svg_submit_renders_each_panel_at_the_requested_size(fixture_repo, tmp_path):
    cfg = render_cfg(fixture_repo, tmp_path, image_backend="agent")
    visual = {"kind": "comic", "panels": [{"prompt": "one"}, {"prompt": "two"}]}
    cid, run_id = _pending(cfg, fixture_repo, visual)
    with db.open_db(cfg.settings.data_dir / "gittok.db") as conn:
        agent_images.pending(conn, cfg, run_id)
        assert agent_images.submit(conn, cfg, cid, svgs=[SVG, SVG])["status"] == "ready"
        rows = conn.execute("SELECT path FROM assets WHERE card_id=? ORDER BY path",
                            (cid,)).fetchall()
    assert len(rows) == 2
    for row in rows:
        with Image.open(BytesIO((cfg.settings.data_dir / row["path"]).read_bytes())) as im:
            assert im.format == "PNG"
            assert im.size == (cfg.settings.render.image_width, cfg.settings.render.image_height)


@pytest.mark.parametrize("bad", [
    # local files and remote resources: resvg would read a local file into the image
    '<svg xmlns="http://www.w3.org/2000/svg"><image href="/etc/hosts" width="9" height="9"/></svg>',
    '<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink">'
    '<use xlink:href="other.svg#a"/></svg>',
    '<svg xmlns="http://www.w3.org/2000/svg"><rect fill="url(file:///etc/x)"/></svg>',
    '<svg xmlns="http://www.w3.org/2000/svg"><rect style="fill:url(http://x/y)"/></svg>',
    '<svg xmlns="http://www.w3.org/2000/svg"><style>@import "x.css";</style></svg>',
    '<!DOCTYPE svg [<!ENTITY x SYSTEM "file:///etc/hosts">]>'
    '<svg xmlns="http://www.w3.org/2000/svg"><text>&x;</text></svg>',
    '<svg xmlns="http://www.w3.org/2000/svg"><foreignObject/></svg>',
    '<svg xmlns="http://www.w3.org/2000/svg"><script>1</script></svg>',
])
def test_svg_with_external_references_is_rejected(fixture_repo, tmp_path, bad):
    cfg = render_cfg(fixture_repo, tmp_path, image_backend="agent")
    cid, run_id = _pending(cfg, fixture_repo, {"kind": "illustration", "prompt": "one"})
    with db.open_db(cfg.settings.data_dir / "gittok.db") as conn:
        agent_images.pending(conn, cfg, run_id)
        with pytest.raises(agent_images.ImageError, match="SVG"):
            agent_images.submit(conn, cfg, cid, svgs=[bad])
    assert card_row(cfg, cid)["status"] == "pending_render"


@pytest.mark.parametrize("bad,match", [
    ("<svg", "cannot render SVG"),
    ("<html/>", "root must be <svg>"),
    ('<svg xmlns="http://www.w3.org/2000/svg">' + " " * 600_000 + "</svg>", "too large"),
])
def test_broken_svg_gives_an_actionable_error(fixture_repo, tmp_path, bad, match):
    cfg = render_cfg(fixture_repo, tmp_path, image_backend="agent")
    cid, run_id = _pending(cfg, fixture_repo, {"kind": "illustration", "prompt": "one"})
    with db.open_db(cfg.settings.data_dir / "gittok.db") as conn:
        agent_images.pending(conn, cfg, run_id)
        with pytest.raises(agent_images.ImageError, match=match):
            agent_images.submit(conn, cfg, cid, svgs=[bad])


def test_submit_takes_exactly_one_image_source(fixture_repo, tmp_path):
    cfg = render_cfg(fixture_repo, tmp_path, image_backend="agent")
    cid, run_id = _pending(cfg, fixture_repo, {"kind": "illustration", "prompt": "one"})
    with db.open_db(cfg.settings.data_dir / "gittok.db") as conn:
        agent_images.pending(conn, cfg, run_id)
        with pytest.raises(agent_images.ImageError, match="exactly one"):
            agent_images.submit(conn, cfg, cid, svgs=[SVG], data_urls=["data:x"])
        with pytest.raises(agent_images.ImageError, match="exactly one"):
            agent_images.submit(conn, cfg, cid)


def test_requests_can_be_limited_to_one_card(fixture_repo, tmp_path):
    cfg = render_cfg(fixture_repo, tmp_path, image_backend="agent")
    ids = seed_pending(cfg, fixture_repo, {"kind": "illustration", "prompt": "one"}, count=2)
    run_id = card_row(cfg, ids[0])["run_id"]
    with db.open_db(cfg.settings.data_dir / "gittok.db") as conn:
        assert len(agent_images.pending(conn, cfg, run_id)) == 2
        (one,) = agent_images.pending(conn, cfg, run_id, card_id=ids[1])
    assert one["card_id"] == ids[1]


def test_illustrator_agent_draws_svg_with_only_the_image_tools():
    text = (ROOT / ".claude" / "agents" / "gittok-illustrator.md").read_text()
    head = text.split("---")[1]
    tools = next(ln for ln in head.splitlines() if ln.startswith("tools:"))
    assert {t.strip() for t in tools.removeprefix("tools:").split(",")} == {
        "mcp__gittok__get_image_requests", "mcp__gittok__submit_images",
    }
    assert "model: sonnet" in head
    assert "svgs" in text and "card_id" in text
    assert "gittok-illustrator.md" in home.AGENT_FILES


def test_generate_skill_sends_claude_images_to_the_illustrator():
    skill = (ROOT / ".claude" / "skills" / "gittok-generate" / "SKILL.md").read_text()
    step = skill.split("3a.")[1].split("\n4.")[0]
    assert "gittok-illustrator" in step and "native image tool" in step


def test_mascot_hint_counts_agent_images_as_a_renderer(fixture_repo, tmp_path, monkeypatch):
    # conftest stubs cli._renderers; REAL_RENDERERS was taken at import, before the stub.
    from gittok import render

    cfg = render_cfg(fixture_repo, tmp_path)
    monkeypatch.setattr(render, "worker_check", lambda model: "mflux is not installed")
    assert REAL_RENDERERS(cfg) == {"illustration": True}


def test_svg_without_viewbox_is_scaled_to_fill_the_panel():
    from gittok.agent_images import svg_image

    svg = ('<svg xmlns="http://www.w3.org/2000/svg" width="100" height="125">'
           '<rect width="100" height="125" fill="#f00"/></svg>')
    image = svg_image(svg, 200, 250)
    with Image.open(BytesIO(image.data)) as im:
        assert im.convert("RGBA").getpixel((190, 240)) == (255, 0, 0, 255)


def test_svg_in_a_markdown_fence_is_accepted():
    from gittok.agent_images import svg_image

    assert svg_image(f"```svg\n{SVG}\n```", 100, 125).width == 100


def test_svg_text_is_rejected_because_no_fonts_are_loaded():
    from gittok.agent_images import svg_image

    svg = '<svg xmlns="http://www.w3.org/2000/svg"><text x="1" y="9">hi</text></svg>'
    with pytest.raises(agent_images.ImageError, match="text"):
        svg_image(svg, 100, 100)


def test_a_new_run_also_gets_agent_cards_that_earlier_runs_left_pending(
    fixture_repo, tmp_path,
):
    from gittok import runs

    cfg = render_cfg(fixture_repo, tmp_path, image_backend="agent")
    old, old_run = _pending(cfg, fixture_repo, {"kind": "illustration", "prompt": "old"})
    with db.open_db(cfg.settings.data_dir / "gittok.db") as conn:
        assert [r["card_id"] for r in agent_images.pending(conn, cfg, old_run)] == [old]
        runs.finish_run(conn, old_run, None)
        new_run = runs.open_run(conn, cfg, repo=None, brief="b", requested=1)
        assert [r["card_id"] for r in agent_images.pending(conn, cfg, new_run)] == [old]
        (one,) = agent_images.pending(conn, cfg, new_run, card_id=old)
        assert one["card_id"] == old


@pytest.mark.anyio
async def test_submit_images_counts_in_the_run_of_its_card(fixture_repo, tmp_path):
    from mcp.client import Client

    from gittok import mcp_server, runs
    from tests.test_mcp_e2e import data

    cfg = render_cfg(fixture_repo, tmp_path, image_backend="agent")
    cid, run_id = _pending(cfg, fixture_repo, {"kind": "illustration", "prompt": "one"})
    async with Client(mcp_server.build_server(lambda: cfg)) as client:
        data(await client.call_tool("get_image_requests", {"run_id": run_id}))
        data(await client.call_tool("submit_images", {"card_id": cid, "svgs": [SVG]}))
    with db.open_db(cfg.settings.data_dir / "gittok.db") as conn:
        summary = runs.finish_run(conn, run_id, None)
    assert summary["mcp_calls"].get("submit_images") == 1


def test_one_malformed_card_does_not_hide_the_others(fixture_repo, tmp_path):
    cfg = render_cfg(fixture_repo, tmp_path, image_backend="agent")
    bad, good = seed_pending(cfg, fixture_repo, {"kind": "illustration", "prompt": "one"},
                             count=2)
    run_id = card_row(cfg, bad)["run_id"]
    with db.open_db(cfg.settings.data_dir / "gittok.db") as conn:
        agent_images.pending(conn, cfg, run_id)
        conn.execute("UPDATE cards SET spec = '{}' WHERE id = ?", (bad,))
        conn.commit()
        assert [r["card_id"] for r in agent_images.pending(conn, cfg, run_id)] == [good]


FILTER = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><filter id="f">{}</filter>'
          '<rect width="10" height="10" filter="url(#f)"/></svg>')


@pytest.mark.parametrize("primitive", [
    '<feTurbulence numOctaves="200"/>',
    '<feMorphology radius="100000"/>',
    '<feGaussianBlur stdDeviation="5000"/>',
    "<feGaussianBlur/>" * 60,
])
def test_svg_filters_that_cost_minutes_of_cpu_are_rejected(primitive):
    from gittok.agent_images import svg_image

    with pytest.raises(agent_images.ImageError, match="filter"):
        svg_image(FILTER.format(primitive), 100, 100)


def test_svg_rendering_has_a_time_limit(monkeypatch):
    from gittok.agent_images import svg_image

    monkeypatch.setattr(agent_images, "RENDER_TIMEOUT_S", 0.001)
    with pytest.raises(agent_images.ImageError, match="took too long"):
        svg_image(SVG, 100, 125)


def test_agent_can_still_submit_a_card_that_failed_or_was_left_rendering(fixture_repo, tmp_path):
    cfg = render_cfg(fixture_repo, tmp_path, image_backend="agent")
    failed, stuck = seed_pending(cfg, fixture_repo, {"kind": "illustration", "prompt": "one"},
                                 count=2)
    with db.open_db(cfg.settings.data_dir / "gittok.db") as conn:
        agent_images.pending(conn, cfg, card_row(cfg, failed)["run_id"])
        conn.execute("UPDATE cards SET status = 'render_failed' WHERE id = ?", (failed,))
        resolved = db.loads(card_row(cfg, stuck)["resolved"])
        resolved["rendering_since"] = "2020-01-01T00:00:00+00:00"
        conn.execute("UPDATE cards SET status = 'rendering', resolved = ? WHERE id = ?",
                     (db.dumps(resolved), stuck))
        conn.commit()
        assert agent_images.submit(conn, cfg, failed, svgs=[SVG])["status"] == "ready"
        assert agent_images.submit(conn, cfg, stuck, svgs=[SVG])["status"] == "ready"


def test_submitted_staged_files_are_deleted(fixture_repo, tmp_path):
    from tests.test_render import png_bytes

    cfg = render_cfg(fixture_repo, tmp_path, image_backend="agent")
    cid, run_id = _pending(cfg, fixture_repo, {"kind": "illustration", "prompt": "one"})
    with db.open_db(cfg.settings.data_dir / "gittok.db") as conn:
        (request,) = agent_images.pending(conn, cfg, run_id)
        path = Path(request["staging_dir"]) / "panel.png"
        path.write_bytes(png_bytes())
        assert agent_images.submit(conn, cfg, cid, paths=[str(path)])["status"] == "ready"
    assert not path.exists()


def test_the_mflux_check_never_runs_inside_a_write_transaction(fixture_repo, tmp_path,
                                                               monkeypatch):
    """worker_check may start a subprocess for seconds; the feed server's writes must not wait."""
    from gittok import render, runs
    from tests.cards import illustration_card

    cfg = render_cfg(fixture_repo, tmp_path)
    monkeypatch.delenv("GITTOK_AGENT", raising=False)
    with db.open_db(cfg.settings.data_dir / "gittok.db") as conn:
        seen = []
        monkeypatch.setattr(render, "worker_check",
                            lambda model: seen.append(conn.in_transaction) or "missing")
        run_id = runs.open_run(conn, cfg, repo=None, brief="b", requested=1)
        result = runs.submit(conn, cfg, run_id, [illustration_card(fixture_repo)])
        assert result["accepted"], result
        agent_images.pending(conn, cfg, run_id)
    assert seen and not any(seen)
