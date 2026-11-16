"""The illustration model: a pre-quantized download that GitTok fetches by itself into the
GitTok directory, and the check that a model folder is complete."""

import dataclasses
import json
import time

import pytest

from gittok import image_model
from gittok.config import RenderSettings
from tests.conftest import make_config


@pytest.fixture
def cfg(fixture_repo, tmp_path):
    return make_config(fixture_repo, tmp_path)


def with_render(cfg, **kw):
    return dataclasses.replace(
        cfg, settings=dataclasses.replace(cfg.settings, render=RenderSettings(**kw))
    )


def write_model(root, *, skip=(), empty=()):
    """A model folder in mflux's saved layout: an index per weighted component, its shards,
    and the tokenizer."""
    for comp in image_model.COMPONENTS:
        if comp in skip:
            continue
        d = root / comp
        d.mkdir(parents=True)
        shards = ["0.safetensors", "1.safetensors"]
        index = {"weight_map": {f"w{i}": s for i, s in enumerate(shards)}}
        (d / "model.safetensors.index.json").write_text(json.dumps(index))
        for s in shards:
            (d / s).write_bytes(b"" if f"{comp}/{s}" in empty else b"weights")
    if "tokenizer" not in skip:
        (root / "tokenizer").mkdir(parents=True)
        (root / "tokenizer" / "tokenizer.json").write_text("{}")
    return root


# ---------------------------------------------------------------- where and when ready


def test_the_model_lives_in_the_gittok_directory_unless_a_path_is_set(cfg, tmp_path):
    assert image_model.model_dir(cfg).is_relative_to(cfg.settings.data_dir)
    custom = with_render(cfg, mflux_path=str(tmp_path / "elsewhere"))
    assert image_model.model_dir(custom) == tmp_path / "elsewhere"


def test_a_complete_model_folder_is_ready(tmp_path):
    assert image_model.ready(write_model(tmp_path / "m")) is True


@pytest.mark.parametrize("part", ["transformer", "text_encoder", "vae", "tokenizer"])
def test_a_folder_without_one_part_is_not_ready(tmp_path, part):
    """An interrupted save can leave whole parts out: the rest being fine is not enough."""
    assert image_model.ready(write_model(tmp_path / "m", skip={part})) is False


def test_a_missing_or_empty_shard_is_not_ready(tmp_path):
    m = write_model(tmp_path / "m", empty={"vae/1.safetensors"})
    assert image_model.ready(m) is False
    m2 = write_model(tmp_path / "m2")
    (m2 / "transformer" / "1.safetensors").unlink()
    assert image_model.ready(m2) is False
    assert image_model.ready(tmp_path / "nothing") is False


# ---------------------------------------------------------------- the download


def test_download_fills_a_partial_folder_and_moves_it_into_place(cfg):
    seen = {}

    def fetch(repo, revision, dest):
        seen.update(repo=repo, revision=revision, dest=dest)
        write_model(dest)

    path = image_model.download(cfg, fetch=fetch, total=100)
    assert path == image_model.model_dir(cfg) and image_model.ready(path)
    assert seen["repo"] == cfg.settings.render.mflux_repo
    assert seen["revision"] == cfg.settings.render.mflux_revision
    assert seen["dest"] != path and not seen["dest"].exists()  # the partial folder moved
    assert image_model.status(cfg)["state"] == "ready"


def test_an_interrupted_download_is_not_ready_and_says_why(cfg):
    def fetch(repo, revision, dest):
        write_model(dest, skip={"vae"})
        raise OSError("connection reset")

    with pytest.raises(image_model.DownloadError, match="connection reset"):
        image_model.download(cfg, fetch=fetch, total=100)
    st = image_model.status(cfg)
    assert st["state"] == "failed" and "connection reset" in st["error"]
    assert not image_model.ready(image_model.model_dir(cfg))


def test_a_download_that_ends_incomplete_fails(cfg):
    with pytest.raises(image_model.DownloadError, match="incomplete"):
        image_model.download(cfg, fetch=lambda r, v, d: write_model(d, skip={"tokenizer"}),
                             total=100)


def test_status_reports_progress_while_downloading(cfg):
    progress = []

    def fetch(repo, revision, dest):
        (dest / "part.bin").parent.mkdir(parents=True, exist_ok=True)
        (dest / "part.bin").write_bytes(b"x" * 40)
        time.sleep(0.3)
        progress.append(image_model.status(cfg))
        (dest / "part.bin").unlink()
        write_model(dest)

    image_model.download(cfg, fetch=fetch, total=100, poll_s=0.05)
    st = progress[0]
    assert st["state"] == "downloading" and st["total"] == 100 and st["done"] >= 40


def test_only_one_download_runs_at_a_time(cfg):
    inner = {}

    def fetch(repo, revision, dest):
        inner["running"] = image_model.downloading(cfg)
        with pytest.raises(image_model.DownloadError, match="already"):
            image_model.download(cfg, fetch=lambda *a: None, total=1)
        write_model(dest)

    image_model.download(cfg, fetch=fetch, total=1)
    assert inner["running"] is True and image_model.downloading(cfg) is False


# ---------------------------------------------------------------- starting it by itself


def test_the_render_worker_starts_the_download_when_the_renderer_is_installed(cfg):
    started = []
    assert image_model.maybe_start(cfg, installed=True, spawn=started.append) is True
    assert started and started[0][-2:] == ["images", "--download"]
    # Not again while it runs, and not when not installed or turned off.
    assert image_model.maybe_start(cfg, installed=False, spawn=started.append) is False
    off = with_render(cfg, mflux_auto_download=False)
    assert image_model.maybe_start(off, installed=True, spawn=started.append) is False


def test_no_automatic_retry_soon_after_a_failure(cfg):
    with pytest.raises(image_model.DownloadError):
        image_model.download(cfg, fetch=lambda *a: (_ for _ in ()).throw(OSError("x")), total=1)
    started = []
    assert image_model.maybe_start(cfg, installed=True, spawn=started.append) is False
    assert started == []


def test_no_download_when_the_model_is_ready(cfg):
    write_model(image_model.model_dir(cfg))
    assert image_model.maybe_start(cfg, installed=True, spawn=lambda c: None) is False
    assert image_model.status(cfg)["state"] == "ready"


# ---------------------------------------------------------------- gittok images


def test_the_images_command_shows_status_and_downloads(cfg, monkeypatch, capsys):
    from gittok import cli

    monkeypatch.setattr(cli, "load_config", lambda *a, **k: cfg)
    assert cli.main(["images"]) == 0
    shown = json.loads(capsys.readouterr().out)
    assert shown["state"] == "missing" and shown["path"] == str(image_model.model_dir(cfg))

    def fake_download(c, **kw):
        kw["on_progress"](3_000_000_000, 6_000_000_000)
        return write_model(image_model.model_dir(c))

    monkeypatch.setattr(image_model, "download", fake_download)
    assert cli.main(["images", "--download"]) == 0
    out = capsys.readouterr().out
    assert "3.0 of 6.0 GB" in out and "ready" in out.lower()


def test_the_images_command_reports_a_failed_download(cfg, monkeypatch, capsys):
    from gittok import cli

    monkeypatch.setattr(cli, "load_config", lambda *a, **k: cfg)

    def fail(c, **kw):
        raise image_model.DownloadError("connection reset")

    monkeypatch.setattr(image_model, "download", fail)
    assert cli.main(["images", "--download"]) == 1
    assert "connection reset" in capsys.readouterr().err


def test_user_model_path_is_never_downloaded_into_or_deleted(fixture_repo, tmp_path):
    cfg = make_config(fixture_repo, tmp_path)
    mine = tmp_path / "my-models"
    mine.mkdir()
    (mine / "precious.safetensors").write_bytes(b"x" * 10)
    cfg = with_render(cfg, mflux_path=str(mine))
    st = image_model.status(cfg)
    assert st["state"] == "invalid path" and st["error"]
    spawned = []
    assert image_model.maybe_start(cfg, installed=True, spawn=spawned.append) is False
    assert spawned == []
    with pytest.raises(image_model.DownloadError):
        image_model.download(cfg, fetch=lambda repo, rev, dest: write_model(dest), total=1)
    assert (mine / "precious.safetensors").exists()


def test_download_keeps_a_folder_it_did_not_create(fixture_repo, tmp_path):
    cfg = make_config(fixture_repo, tmp_path)
    final = image_model.model_dir(cfg)
    final.mkdir(parents=True)
    (final / "other.txt").write_text("not ours")
    with pytest.raises(image_model.DownloadError):
        image_model.download(cfg, fetch=lambda repo, rev, dest: write_model(dest), total=1)
    assert (final / "other.txt").exists()
