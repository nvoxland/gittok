"""Meme cards are drawn in process: `gittok memes --prefetch` downloads memegen's template
images, text layouts and fonts once into the GitTok directory, and Pillow draws the text.
No meme server, no Docker, and no card text leaves the machine."""

import dataclasses
import io

import httpx
import pytest
import yaml
from PIL import Image

from gittok import memes, render
from tests.conftest import make_config

LAYOUT = {
    "name": "Two boxes",
    "text": [
        {"style": "upper", "color": "white", "font": "thick", "anchor_x": 0.0,
         "anchor_y": 0.0, "angle": 0.0, "scale_x": 1.0, "scale_y": 0.2, "align": "center"},
        {"style": "none", "color": "black", "font": "thin", "anchor_x": 0.0,
         "anchor_y": 0.8, "angle": 5.0, "scale_x": 1.0, "scale_y": 0.2, "align": "center"},
    ],
}  # fmt: skip


def jpg(w=200, h=100, color=(40, 90, 160)) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (w, h), color).save(out, "JPEG")
    return out.getvalue()


@pytest.fixture
def cfg(fixture_repo, tmp_path, monkeypatch):
    from gittok.config import MemeTemplate

    monkeypatch.setattr(memes, "BUNDLED", tmp_path / "no-bundled-assets")
    shipped = {t: MemeTemplate(t, 2, "", ()) for t in ("drake", "db", "fine")}
    return dataclasses.replace(make_config(fixture_repo, tmp_path), meme_templates=shipped)


def put_template(cfg, tid="drake", layout=LAYOUT, image=None, ext="jpg"):
    d = memes.store(cfg) / "templates" / tid
    d.mkdir(parents=True, exist_ok=True)
    (d / "config.yml").write_text(yaml.safe_dump(layout))
    (d / f"default.{ext}").write_bytes(image or jpg())
    return d


def source(files: dict[str, bytes]):
    """A fake memegen repo: path -> bytes; anything else is a 404."""
    seen: list[str] = []

    def handler(request):
        path = request.url.path
        seen.append(path)
        return httpx.Response(200, content=files[path]) if path in files else httpx.Response(404)

    return httpx.MockTransport(handler), seen


# ---------------------------------------------------------------- download


def test_prefetch_downloads_layouts_images_and_fonts_into_the_gittok_directory(cfg):
    layout = yaml.safe_dump(LAYOUT).encode()
    files = {
        "/memegen/templates/drake/config.yml": layout,
        "/memegen/templates/drake/default.png": b"\x89PNG fake",
        "/memegen/templates/db/config.yml": layout,
        "/memegen/templates/db/default.jpg": jpg(),  # no png: the jpg is used
        **{f"/memegen/fonts/{f}": b"font" for f in memes.FONT_FILES.values()},
    }
    transport, seen = source(files)
    out = memes.prefetch(cfg, ["drake", "db", "nope"], base="http://src.test/memegen",
                         transport=transport)  # fmt: skip
    assert out["downloaded"] == ["db", "drake"] and set(out["failed"]) == {"nope"}
    root = memes.store(cfg)
    assert root.is_relative_to(cfg.settings.data_dir)
    assert (root / "templates" / "db" / "default.jpg").exists()
    assert all((root / "fonts" / f).exists() for f in memes.FONT_FILES.values())
    assert memes.downloaded(cfg) == {"db", "drake"}
    # A second run asks only for what is missing.
    seen.clear()
    again = memes.prefetch(cfg, ["drake", "db"], base="http://src.test/memegen",
                           transport=transport)  # fmt: skip
    assert again["downloaded"] == [] and seen == []


def test_a_layout_without_text_boxes_is_not_kept(cfg):
    files = {
        "/m/templates/odd/config.yml": b"name: odd\n",
        "/m/templates/odd/default.jpg": jpg(),
        **{f"/m/fonts/{f}": b"font" for f in memes.FONT_FILES.values()},
    }
    transport, _ = source(files)
    out = memes.prefetch(cfg, ["odd"], base="http://src.test/m", transport=transport)
    assert "odd" in out["failed"] and memes.downloaded(cfg) == set()


def test_missing_lists_the_configured_templates_not_downloaded(cfg):
    put_template(cfg, "drake")
    missing = memes.missing(cfg)
    assert "drake" not in missing and "db" in missing
    assert set(memes.usable_templates(cfg)) == {"drake"}


# ---------------------------------------------------------------- drawing


def test_draw_puts_the_text_in_its_boxes_at_memegen_size(cfg):
    d = put_template(cfg, "drake")
    plain = memes.draw(d, memes.store(cfg) / "fonts", ["", ""])
    drawn = memes.draw(d, memes.store(cfg) / "fonts", ["left on unread", "left on read"])
    a, b = Image.open(io.BytesIO(plain)), Image.open(io.BytesIO(drawn))
    assert a.size == b.size == (1200, 600)  # memegen's default: 600 high, the image's ratio
    w, h = b.size

    def differs(box):
        return a.crop(box).tobytes() != b.crop(box).tobytes()

    assert differs((0, 0, w, int(h * 0.2)))  # the top box has text
    assert differs((0, int(h * 0.8), w, h))  # the bottom box too
    assert not differs((0, int(h * 0.35), w, int(h * 0.65)))  # nothing in between


def test_text_styles_follow_the_layout():
    assert memes.stylize("left on read", "upper") == "LEFT ON READ"
    assert memes.stylize("Keep It", "none") == "Keep It"
    assert memes.stylize("it works", "default") == "It works"
    assert memes.stylize("i know", "default") == "I know"
    mock = memes.stylize("mocking text", "mock")
    assert mock.lower() == "mocking text" and mock != mock.lower() and mock != mock.upper()


def test_long_lines_wrap_to_fit_their_box():
    assert memes.split_2("one two three four") == "one two\nthree four"
    assert memes.split_3("aa bb cc dd ee ff").count("\n") == 2


# ---------------------------------------------------------------- the renderer


def test_the_renderer_draws_a_downloaded_template(cfg):
    put_template(cfg, "drake")
    r = render.MemeRenderer(memes.store(cfg))
    assert r.available() is True
    (img,) = r.render({"kind": "meme", "template": "drake", "lines": ["a", "b"]}, cfg, {})
    assert img.data[:8] == b"\x89PNG\r\n\x1a\n" and (img.width, img.height) == (1200, 600)
    assert img.meta == {"template": "drake", "lines": ["a", "b"], "width": 1200, "height": 600}


def test_without_templates_the_renderer_is_unavailable_and_says_how_to_fix_it(cfg):
    r = render.MemeRenderer(memes.store(cfg))
    assert r.available() is False
    with pytest.raises(render.RendererUnavailable, match="gittok memes --prefetch"):
        r.render({"kind": "meme", "template": "drake", "lines": ["a"]}, cfg, {})


def test_default_renderers_draw_memes_in_process(cfg):
    assert isinstance(render.default_renderers(cfg)["meme"], render.MemeRenderer)
    assert render.default_renderers(cfg)["meme"].store == memes.store(cfg)


# ---------------------------------------------------------------- hint and command


def test_the_hint_offers_the_download_while_templates_are_missing(cfg):
    line = memes.hint(cfg)
    assert "gittok memes --prefetch" in line and "MB" in line
    for tid in memes.configured(cfg):
        put_template(cfg, tid)
    assert memes.hint(cfg) is None


def test_the_memes_command_shows_status_and_prefetches(cfg, monkeypatch, capsys):
    import json

    from gittok import cli

    monkeypatch.setattr(cli, "load_config", lambda *a, **k: cfg)
    assert cli.main(["memes"]) == 0
    status = json.loads(capsys.readouterr().out)
    assert status["downloaded"] == [] and "drake" in status["missing"]
    calls = []

    def fake(c, ids, **k):
        calls.append(ids)
        return {"downloaded": ids, "failed": {}}

    monkeypatch.setattr(memes, "prefetch", fake)
    assert cli.main(["memes", "--prefetch"]) == 0
    assert calls == [memes.missing(cfg)] and "Downloaded" in capsys.readouterr().out


def test_every_shipped_template_fits_the_card_limits():
    from gittok import overlay

    shipped = overlay.shipped("meme_templates")["templates"]
    assert len(shipped) >= 90
    for tid, t in shipped.items():
        assert 1 <= t["lines"] <= 4, tid  # the card schema allows 1 to 4 meme lines
        assert t["hint"] and t["fits"], tid


def test_fresh_home_can_draw_all_default_memes_without_downloads(fixture_repo, tmp_path):
    from gittok import config, overlay

    shipped = overlay.shipped("meme_templates")["templates"]
    cfg = dataclasses.replace(make_config(fixture_repo, tmp_path), meme_templates={
        name: config.MemeTemplate(name, item["lines"], item["hint"], tuple(item["fits"]))
        for name, item in shipped.items()
    })
    assert not memes.store(cfg).exists()
    assert memes.missing(cfg) == []
    assert set(memes.usable_templates(cfg)) == set(shipped)
    assert memes.hint(cfg) is None
    renderer = render.default_renderers(cfg)["meme"]
    assert renderer.available()
    for name in ("drake", "fine", "gb"):
        (image,) = renderer.render({"template": name, "lines": ["code"] * shipped[name]["lines"]},
                                   cfg, {})
        assert image.data.startswith(b"\x89PNG")
    assert not memes.store(cfg).exists()  # bundled assets stay read-only in the package


def test_local_template_overrides_bundled_template(cfg, monkeypatch):
    bundled = cfg.settings.data_dir / "bundle"
    (bundled / "templates" / "drake").mkdir(parents=True)
    (bundled / "templates" / "drake" / "config.yml").write_text(yaml.safe_dump(LAYOUT))
    (bundled / "templates" / "drake" / "default.jpg").write_bytes(jpg())
    monkeypatch.setattr(memes, "BUNDLED", bundled)
    put_template(cfg, "drake", image=jpg(w=100, h=200))
    renderer = render.MemeRenderer(memes.store(cfg))
    (image,) = renderer.render({"template": "drake", "lines": ["one", "two"]}, cfg, {})
    assert (image.width, image.height) == (600, 1200)
