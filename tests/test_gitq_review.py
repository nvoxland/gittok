"""Review fixes for gitq: hunk parsing, option injection, SHA-256 ids."""

import os
import subprocess

import pytest

from gittok import gitq
from tests.fixture_repo import build_history_repo


def _repo(tmp_path):
    return build_history_repo(
        tmp_path / "r",
        [
            ("one", {"a.py": "x = 1\n", "b.py": "y = 1\n"}, "2026-01-05T10:00:00+00:00"),
            (
                "two",
                {"a.py": "x = 1\n++ b/b.py\nmark \x1e here\n", "b.py": "y = 2\n"},
                "2026-01-06T10:00:00+00:00",
            ),
        ],
    )


def test_hunk_parser_ignores_content_that_looks_like_a_header(tmp_path):
    fr = _repo(tmp_path)
    commits = gitq.log_new_hunks(fr.path, "main", None, 10)
    assert [c["sha"] for c in commits] == [fr.shas["1"], fr.shas["0"]]
    files = commits[0]["files"]
    assert set(files) == {"a.py", "b.py"}
    assert files["a.py"]["ranges"] == [(2, 3)]
    assert files["b.py"]["ranges"] == [(1, 1)]


def test_hunks_take_a_pathspec(tmp_path):
    fr = _repo(tmp_path)
    commits = gitq.log_new_hunks(fr.path, "main", None, 10, {"b.py"})
    assert [set(c["files"]) for c in commits] == [{"b.py"}, {"b.py"}]


def test_hunks_stop_at_the_byte_cap(tmp_path):
    fr = _repo(tmp_path)
    commits = gitq.log_new_hunks(fr.path, "main", None, 10, max_bytes=300)
    assert len(commits) < 2
    for c in commits:
        assert isinstance(c["ts"], int)


def test_fetch_never_treats_a_branch_as_an_option(tmp_path):
    fr = _repo(tmp_path)
    assert gitq._split_remote_ref(fr.path, "origin/-x") is None
    subprocess.run(
        ["git", "remote", "add", "origin", str(fr.path)], cwd=fr.path, check=True
    )
    env = {**os.environ}
    subprocess.run(
        ["git", "update-ref", "refs/remotes/origin/-x", fr.shas["1"]],
        cwd=fr.path,
        check=True,
        env=env,
    )
    assert gitq._split_remote_ref(fr.path, "origin/-x") is None
    subprocess.run(
        ["git", "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/-x"],
        cwd=fr.path,
        check=True,
    )
    with pytest.raises(gitq.GitError):
        gitq.default_remote_ref(fr.path)


def test_sha256_ids_are_accepted():
    import re

    assert re.fullmatch(gitq.HEX_ID_PATTERN, "a" * 64)
    assert gitq._BLAME_HEAD.match("a" * 64 + " 1 1")
    assert gitq._BLAME_HEAD.match("a" * 40 + " 1 1")
