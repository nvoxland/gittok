"""Every writer under the data dir makes it private (0700), whichever runs first."""

import os
import re
import stat
from pathlib import Path

import pytest

from gittok import avatars, db, profile, render, steering
from tests.test_render import FakeRunner, render_cfg


@pytest.fixture
def umask_022():
    old = os.umask(0o022)
    yield
    os.umask(old)


def mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def test_avatars_make_a_private_data_dir(fixture_repo, tmp_path, umask_022):
    cfg = render_cfg(fixture_repo, tmp_path)
    assert not cfg.settings.data_dir.exists()
    avatars.generate_avatars(cfg, render.IllustrationRenderer(runner=FakeRunner(), command=["x"]))
    data = cfg.settings.data_dir
    assert [mode(d) for d in (data, data / "assets", data / "assets" / "avatars")] == [0o700] * 3


def test_the_profile_file_makes_a_private_data_dir(fixture_repo, tmp_path, umask_022):
    cfg = render_cfg(fixture_repo, tmp_path)
    conn = db.open_db(tmp_path / "elsewhere" / "x.db")
    assert not cfg.settings.data_dir.exists()
    profile.write_profile(conn, cfg)
    conn.close()
    assert mode(cfg.settings.data_dir) == 0o700


def test_the_config_audit_log_makes_a_private_data_dir(fixture_repo, tmp_path, umask_022):
    cfg = render_cfg(fixture_repo, tmp_path)
    assert not cfg.settings.data_dir.exists()
    steering._audit(cfg, "set_group", {"repo": "fixture"}, "test")
    log = cfg.settings.data_dir / "config_audit.log"
    assert log.exists()
    assert log.stat().st_mode & 0o777 == 0o600
    assert mode(cfg.settings.data_dir) == 0o700


def test_no_module_that_writes_under_the_data_dir_calls_mkdir_itself():
    """Card images, run files and the rest go through `private.make_dir`. A plain `mkdir` is
    left only where the directory is not under the data dir."""
    not_data = {
        "private.py",  # the helper
        "gitq.py",  # the parent of a clone (repos/)
        "home.py",  # the files of a new GitTok directory (`gittok init`)
        "profiling.py",  # local/profiles
        "refit.py",  # an export directory the user names
        "steering.py",  # local/
    }
    src = Path(__file__).parents[1] / "src" / "gittok"
    found = {p.name for p in src.glob("*.py") if re.search(r"\.mkdir\(", p.read_text())}
    assert found <= not_data, sorted(found - not_data)
