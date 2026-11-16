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
