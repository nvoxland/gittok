"""Robustness of the log parsers (control bytes, committer time, blame errors)."""

import os
import subprocess

from gittok import gitq, signals
from tests.fixture_repo import build_history_repo


def _history(tmp_path, subject="one"):
    return build_history_repo(
        tmp_path / "h",
        [
            ("first", {"a.py": "a = 1\n"}, "2026-01-05T10:00:00+00:00"),
            (subject, {"b.py": "b = 1\n"}, "2026-01-06T10:00:00+00:00"),
        ],
    )


def test_control_bytes_in_subject_do_not_break_log_parsing(tmp_path):
    fr = _history(tmp_path, subject="odd\x1esubject\x1fwith\x1ebytes")
    commits = signals.parse_log(fr.path, "main")
    assert len(commits) == 2
    assert {f.path for c in commits for f in c.files} == {"a.py", "b.py"}
    signals.new_files(fr.path, "main", None)
    signals.deleted_paths(fr.path, "main", None)
    signals.reverts(fr.path, "main")
    assert signals.commits_since(fr.path, "main", fr.shas["0"])["count"] == 1


def test_log_windows_use_committer_time(tmp_path):
    fr = _history(tmp_path)
    subprocess.run(
        ["git", "commit", "-q", "--amend", "--no-edit", "--date=2001-01-01T00:00:00+00:00"],
        cwd=fr.path,
        check=True,
        env={
            **os.environ,
            "GIT_COMMITTER_DATE": "2026-01-06T10:00:00+00:00",
            "GIT_CONFIG_GLOBAL": os.devnull,
        },
    )
    commits = signals.parse_log(fr.path, "main")
    assert commits[0].ts == gitq.commit_time(fr.path, "main")


def test_oldest_lines_skips_a_file_whose_blame_fails(tmp_path, monkeypatch):
    fr = _history(tmp_path)
    real = gitq.run_bytes

    def flaky(repo, *args, **kw):
        if args and args[0] == "blame" and args[-1] == "a.py":
            raise gitq.GitError("boom")
        return real(repo, *args, **kw)

    monkeypatch.setattr(gitq, "run_bytes", flaky)
    commits = signals.parse_log(fr.path, "main")
    rows = signals.oldest_lines(fr.path, "main", commits)
    assert [r["path"] for r in rows] == ["b.py"]


def test_todo_ages_caps_the_grep_output(tmp_path, monkeypatch):
    fr = _history(tmp_path)
    seen = {}
    real = gitq.run_bytes

    def spy(repo, *args, **kw):
        if args and args[0] == "grep":
            seen["max_bytes"] = kw.get("max_bytes")
        return real(repo, *args, **kw)

    monkeypatch.setattr(gitq, "run_bytes", spy)
    signals.todo_ages(fr.path, "main")
    assert seen["max_bytes"]
