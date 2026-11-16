"""Facts and candidates are rebuilt when an input changes, not only when HEAD or queries do."""

import pytest

from gittok import db, facts, gitq, signals, structure
from gittok.config import AnalysisSettings, Repo
from gittok.profiles import Detector, Profile
from tests.fixture_repo import build_history_repo

needs_structure = pytest.mark.skipif(
    not (structure.available() and structure.ready("python")), reason="needs the python grammar"
)


@pytest.fixture
def conn(tmp_path):
    c = db.open_db(tmp_path / "t.db")
    yield c
    c.close()


@pytest.fixture
def repo(tmp_path):
    steps = [
        (
            "one",
            {
                "a.py": "# TODO: fix\ndef run():\n    return 1\n",
                "b.py": "def go():\n    return 2\n",
            },
            "2026-01-01T10:00:00+00:00",
        )
    ]
    return build_history_repo(tmp_path / "r", steps)


def _refresh(conn, r, settings=None, profile=None, force=False):
    head, t0 = gitq.rev_parse(r.path, "main"), gitq.commit_time(r.path, "main")
    conn.execute(
        "INSERT OR IGNORE INTO repos(name, path, ref) VALUES ('fx', ?, 'main')", (str(r.path),)
    )
    return facts.refresh(
        conn, "fx", r.path, head, t0, settings or AnalysisSettings(), profile, force=force
    )


@needs_structure
def test_facts_rebuild_when_a_facts_setting_changes(conn, repo):
    assert _refresh(conn, repo)["built"] is True
    assert _refresh(conn, repo)["built"] is False
    assert _refresh(conn, repo, AnalysisSettings(facts_max_files=1))["built"] is True


@needs_structure
def test_facts_rebuild_when_the_file_set_changes(conn, repo):
    assert _refresh(conn, repo)["built"] is True
    assert _refresh(conn, repo, profile=Profile(ignore=("b.py",)))["built"] is True
    assert _refresh(conn, repo, profile=Profile(ignore=("b.py",)))["built"] is False


def test_input_key_follows_settings_and_file_set():
    base = facts.input_key(AnalysisSettings(), None)
    assert base == facts.input_key(AnalysisSettings(), None)
    assert base != facts.input_key(AnalysisSettings(facts_max_calls=5), None)
    assert base != facts.input_key(AnalysisSettings(), Profile(scan=("**/*.py",)))
    assert base != facts.input_key(AnalysisSettings(), Profile(queries={"python": "x"}))


def _repo_cfg(r):
    return Repo(name="fx", path=r.path, ref="main")


def test_analyze_force_reaches_facts(conn, repo, monkeypatch):
    seen = []
    real = facts.refresh

    def spy(*a, **kw):
        seen.append(kw.get("force", False))
        return real(*a, **kw)

    monkeypatch.setattr(facts, "refresh", spy)
    signals.analyze(conn, _repo_cfg(repo), AnalysisSettings(), force=True)
    assert seen == [True]


def test_cached_analyze_remines_candidates_after_a_profile_change(conn, repo):
    cfg = _repo_cfg(repo)
    signals.analyze(conn, cfg, AnalysisSettings())
    assert conn.execute("SELECT COUNT(*) FROM candidates WHERE rule_id = 'r'").fetchone()[0] == 0
    rule = Detector(id="r", tag="marker", paths=("**/*.py",), weight=1.0, regex="TODO")
    again = signals.analyze(conn, cfg, AnalysisSettings(), profile=Profile(detectors=(rule,)))
    assert again["cached"] is True
    assert conn.execute("SELECT COUNT(*) FROM candidates WHERE rule_id = 'r'").fetchone()[0] >= 1
    assert signals.load_signals(conn, "fx").keys() == set(signals.SIGNAL_KINDS)
