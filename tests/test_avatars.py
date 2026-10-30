import re

import pytest

from codescroll import avatars
from codescroll.config import Persona
from tests.test_render import FakeRunner, render_cfg


def test_initials_from_persona_name_or_handle():
    assert avatars.initials("greybeard", "Grey Beard") == "GB"
    assert avatars.initials("archivist", "The Archivist") == "TA"
    assert avatars.initials("solo", "Madonna") == "M"
    assert avatars.initials("greybeard", None) == "G"
    assert avatars.initials("@storefront:src/shipping.clj", None) == "S"


def test_svg_is_deterministic_and_hue_depends_on_handle():
    a = avatars.avatar_svg("greybeard", "Grey Beard")
    assert a == avatars.avatar_svg("greybeard", "Grey Beard")
    assert a.startswith("<svg") and ">GB<" in a
    hue = lambda s: re.search(r"hsl\((\d+)", s).group(1)  # noqa: E731
    assert hue(a) != hue(avatars.avatar_svg("archivist", "The Archivist"))


def test_svg_escapes_markup():
    assert "<script" not in avatars.avatar_svg("<script>", "<b>x</b>")


def test_avatar_prompt_uses_persona_name_and_voice():
    p = avatars.avatar_scene(Persona("greybeard", "Grey Beard", "grumpy veteran"))
    assert "Grey Beard" in p and "grumpy veteran" in p
    assert "flat vector" in p and "no text" in p


def test_generate_avatars_writes_pngs_and_skips_existing(fixture_repo, tmp_path):
    from codescroll import render

    cfg = render_cfg(fixture_repo, tmp_path)
    runner = FakeRunner()
    r = render.IllustrationRenderer(runner=runner, command=["x"])
    res = avatars.generate_avatars(cfg, r)
    n = len(cfg.personas)
    assert res == {"generated": n, "skipped": 0, "waiting": False}
    out = cfg.settings.data_dir / "assets" / "avatars"
    assert sorted(p.stem for p in out.glob("*.png")) == sorted(cfg.personas)
    assert len(runner.calls) == n
    res = avatars.generate_avatars(cfg, r)
    assert res == {"generated": 0, "skipped": n, "waiting": False}
    assert len(runner.calls) == n
    assert avatars.generate_avatars(cfg, r, force=True)["generated"] == n


def test_generate_avatars_reports_waiting_without_mflux(fixture_repo, tmp_path, monkeypatch):
    from codescroll import render

    monkeypatch.setattr(render.shutil, "which", lambda name: None)
    monkeypatch.setattr(render.importlib.util, "find_spec", lambda name: None)
    cfg = render_cfg(fixture_repo, tmp_path)
    res = avatars.generate_avatars(cfg, render.IllustrationRenderer())
    assert res == {"generated": 0, "skipped": 0, "waiting": True}


def test_generate_avatars_propagates_render_errors(fixture_repo, tmp_path):
    from codescroll import render

    cfg = render_cfg(fixture_repo, tmp_path)
    r = render.IllustrationRenderer(runner=FakeRunner(fail=True), command=["x"])
    with pytest.raises(render.RenderError):
        avatars.generate_avatars(cfg, r)
