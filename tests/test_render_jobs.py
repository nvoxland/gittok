import pytest

from gittok import db, render
from tests.test_render import FakeRenderer, card_row, png_bytes, render_cfg, seed_pending


@pytest.mark.parametrize("backend", ["local", "agent"])
def test_common_request_completion_contract(fixture_repo, tmp_path, backend):
    from gittok import render_jobs as jobs

    cfg = render_cfg(fixture_repo, tmp_path)
    visual = {"kind": "comic", "panels": [{"prompt": "one"}, {"prompt": "two"}]}
    (cid,) = seed_pending(cfg, fixture_repo, visual)
    with db.open_db(cfg.settings.data_dir / "gittok.db") as conn:
        conn.execute("UPDATE cards SET resolved=? WHERE id=?",
                     (db.dumps({"image_backend": backend}), cid))
        conn.commit()
        request = jobs.request(conn, cfg, cid, backend=backend)
        assert request.card_id == cid and request.kind == "comic"
        assert request.images[0]["prompt"] == "flat vector otter, one, no text, no letters"
        assert [i["seed"] for i in request.images] == [7, 8]
        assert (request.images[0]["width"], request.images[0]["height"]) == (64, 48)
        image = jobs.RenderedImage(png_bytes(), 4, 6)
        with pytest.raises(jobs.JobError, match="2 images"):
            jobs.complete(conn, cfg, jobs.RenderCompletion(request, (image,)))
        assert card_row(cfg, cid)["status"] == "pending_render"
        completion = jobs.RenderCompletion(request, (image, image))
        assert jobs.complete(conn, cfg, completion)["status"] == "ready"
        assert jobs.complete(conn, cfg, completion)["status"] == "ready"
        assets = conn.execute("SELECT path FROM assets WHERE card_id=?", (cid,)).fetchall()
        assert len(assets) == 2
        assert all((cfg.settings.data_dir / a["path"]).is_file() for a in assets)


def test_local_completion_validates_image_bytes_before_publishing(fixture_repo, tmp_path):
    cfg = render_cfg(fixture_repo, tmp_path)
    (cid,) = seed_pending(cfg, fixture_repo, {"kind": "illustration", "prompt": "one"})

    class Corrupt(FakeRenderer):
        def render(self, visual, cfg, spec):
            return [render.RenderedImage(b"not an image", 4, 6)]

    with db.open_db(cfg.settings.data_dir / "gittok.db") as conn:
        counts = render.render_pending(conn, cfg, {"illustration": Corrupt()})
    assert counts["failed"] == 1 and counts["rendered"] == 0
    assert card_row(cfg, cid)["status"] == "render_failed"
    assert not (cfg.settings.data_dir / "assets" / cid).exists()


def test_completion_releases_claim_when_asset_storage_fails(fixture_repo, tmp_path, monkeypatch):
    from gittok import render_jobs as jobs

    cfg = render_cfg(fixture_repo, tmp_path)
    (cid,) = seed_pending(cfg, fixture_repo, {"kind": "illustration", "prompt": "one"})
    with db.open_db(cfg.settings.data_dir / "gittok.db") as conn:
        request = jobs.request(conn, cfg, cid, backend="local")
        completion = jobs.RenderCompletion(request, (jobs.RenderedImage(png_bytes(), 4, 6),))

        def broken(*args):
            raise OSError("disk full")

        monkeypatch.setattr(jobs, "_store_images", broken)
        with pytest.raises(OSError, match="disk full"):
            jobs.complete(conn, cfg, completion)
        assert card_row(cfg, cid)["status"] == "pending_render"


def test_claim_prevents_wrong_backend_and_completion_without_ownership(fixture_repo, tmp_path):
    from gittok import render_jobs as jobs

    cfg = render_cfg(fixture_repo, tmp_path)
    (cid,) = seed_pending(cfg, fixture_repo, {"kind": "illustration", "prompt": "one"})
    with db.open_db(cfg.settings.data_dir / "gittok.db") as conn:
        with pytest.raises(jobs.JobError, match="not assigned"):
            jobs.request(conn, cfg, cid, backend="agent")
        request = jobs.request(conn, cfg, cid, backend="local")
        completion = jobs.RenderCompletion(request, (jobs.RenderedImage(png_bytes(), 4, 6),))
        with pytest.raises(jobs.JobError, match="not claimed"):
            jobs.complete(conn, cfg, completion, claimed=True)
        assert jobs.claim(conn, request)
        assert not jobs.claim(conn, request)
        with pytest.raises(jobs.JobError, match="busy"):
            jobs.complete(conn, cfg, completion)
        assert card_row(cfg, cid)["status"] == "rendering"
        assert jobs.complete(conn, cfg, completion, claimed=True)["status"] == "ready"


def test_palette_png_keeps_its_transparency():
    from io import BytesIO

    from PIL import Image

    from gittok import render_jobs as jobs

    image = Image.new("P", (2, 1))
    image.putpalette([255, 0, 0, 0, 0, 255])
    image.putpixel((1, 0), 1)
    out = BytesIO()
    image.save(out, format="PNG", transparency=0)
    decoded = jobs.decode_image(out.getvalue())
    with Image.open(BytesIO(decoded.data)) as im:
        assert im.convert("RGBA").getpixel((0, 0))[3] == 0
        assert im.convert("RGBA").getpixel((1, 0)) == (0, 0, 255, 255)
