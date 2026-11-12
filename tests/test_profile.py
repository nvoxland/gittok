import os
import re
import time

import pytest

from blamescroll import db, profile, steering
from tests.conftest import make_config
from tests.test_steering import NOW, add_card, reward


@pytest.fixture
def cfg(fixture_repo, tmp_path):
    return make_config(fixture_repo, tmp_path)


@pytest.fixture
def conn():
    c = db.open_db(":memory:")
    yield c
    c.close()


def test_write_profile_writes_markdown_sections(conn, cfg):
    meme = add_card(conn, cfg, format="meme", dirs=["billing"])
    chart = add_card(conn, cfg, format="chart", dirs=["src"])
    for _ in range(6):
        reward(conn, cfg, meme, 0.9, 2)
        reward(conn, cfg, chart, 0.2, 2)
    steering.add_rule(
        conn, cfg, type="ban", feature="format", value="horoscope", reason="no stars", now=NOW
    )
    path = profile.write_profile(conn, cfg, now=NOW)
    assert path == cfg.settings.data_dir / "profile.md"
    md = path.read_text()
    assert md.startswith("# Blamescroll profile\n")
    assert "2026-06-01" in md
    assert "## What you like" in md
    claim = r"You engaged with meme cards: average score 0\.\d+, and 100% scored well, over 6 views"
    assert re.search(claim, md)
    assert "## Active rules" in md
    assert "ban format=horoscope" in md and "no stars" in md
    assert "## Coverage gaps" in md
    assert "fixture/data" in md  # a dir with no cards at all
    assert not list(path.parent.glob("*.tmp"))


def test_write_profile_on_empty_db_says_not_enough_data(conn, cfg):
    md = profile.write_profile(conn, cfg, now=NOW).read_text()
    assert "Not enough data yet" in md
    assert "No active rules." in md


def test_write_if_stale_only_rewrites_old_files(cfg):
    assert profile.write_if_stale(cfg) is True  # missing: written (also creates the db)
    path = profile.profile_path(cfg)
    assert path.is_file()
    assert profile.write_if_stale(cfg) is False  # fresh
    old = time.time() - 25 * 3600
    os.utime(path, (old, old))
    assert profile.write_if_stale(cfg) is True
    assert time.time() - path.stat().st_mtime < 60
