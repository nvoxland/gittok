import pytest

from codescroll import gitq
from tests.fixture_repo import INVOICE_V1


def test_show_returns_file_at_commit(fixture_repo):
    sha = fixture_repo.shas["invoice_add"]
    assert gitq.show_file(fixture_repo.path, sha, "billing/invoice.py") == INVOICE_V1.encode()


def test_show_missing_path_raises_giterror(fixture_repo):
    with pytest.raises(gitq.GitError):
        gitq.show_file(fixture_repo.path, fixture_repo.shas["initial"], "billing/invoice.py")


def test_rev_parse_expands_short_sha(fixture_repo):
    full = fixture_repo.shas["fix1"]
    assert gitq.rev_parse(fixture_repo.path, full[:8]) == full


def test_rev_parse_unknown_raises(fixture_repo):
    with pytest.raises(gitq.GitError):
        gitq.rev_parse(fixture_repo.path, "deadbeefdeadbeef")


def test_rev_parse_rejects_option_injection(fixture_repo):
    with pytest.raises(gitq.GitError):
        gitq.rev_parse(fixture_repo.path, "--output=/tmp/x")


def test_is_ancestor(fixture_repo):
    s = fixture_repo.shas
    assert gitq.is_ancestor(fixture_repo.path, s["fix1"], "main")
    assert not gitq.is_ancestor(fixture_repo.path, s["unmerged"], "main")


def test_commit_time(fixture_repo):
    # 2026-02-20T15:00:00Z
    assert gitq.commit_time(fixture_repo.path, "main") == 1771599600


def test_object_type(fixture_repo):
    head = fixture_repo.shas["head"]
    assert gitq.object_type(fixture_repo.path, head, "src") == "tree"
    assert gitq.object_type(fixture_repo.path, head, "src/app.py") == "blob"
    assert gitq.object_type(fixture_repo.path, head, "src/legacy.py") is None


def test_run_caps_output(fixture_repo):
    out = gitq.run(fixture_repo.path, "show", f"{fixture_repo.shas['huge']}:data/big.txt",
                   max_bytes=100)
    assert len(out.encode()) <= 100 + len(gitq.TRUNCATED_MARKER.encode())
    assert out.endswith(gitq.TRUNCATED_MARKER)


def test_run_does_not_touch_worktree(fixture_repo):
    before = (fixture_repo.path / ".git" / "index").stat().st_mtime_ns
    gitq.run(fixture_repo.path, "status", "--porcelain")
    assert (fixture_repo.path / ".git" / "index").stat().st_mtime_ns == before


def test_show_file_rejects_directory(fixture_repo):
    with pytest.raises(gitq.GitError):
        gitq.show_file(fixture_repo.path, fixture_repo.shas["head"], "src")


def test_split_lines_only_on_newline():
    assert gitq.split_lines("a\fb\x85c d\re\nlast\r\n") == ["a\fb\x85c d\re", "last"]
    assert gitq.split_lines("") == []
    assert gitq.split_lines("x\n\n") == ["x", ""]
    assert gitq.split_lines("x") == ["x"]


def test_run_closes_stdin(fixture_repo):
    empty_blob = "e69de29bb2d1d6434b8b29ae775ad8c2e48c5391"
    assert gitq.run(fixture_repo.path, "hash-object", "--stdin").strip() == empty_blob


def test_run_kills_git_once_max_bytes_exceeded(tmp_path, monkeypatch):
    import subprocess

    from tests.fixture_repo import build_small_repo

    fr = build_small_repo(tmp_path / "r", {"big.txt": b"x" * 3_000_000})
    procs = []
    real = subprocess.Popen

    def spy(*a, **kw):
        p = real(*a, **kw)
        procs.append(p)
        return p

    monkeypatch.setattr(gitq.subprocess, "Popen", spy)
    out = gitq.run(fr.path, "cat-file", "blob", "HEAD:big.txt", max_bytes=100)
    assert out == "x" * 100 + gitq.TRUNCATED_MARKER
    assert procs and procs[0].returncode != 0  # killed, not drained to the end


def test_resolve_commit_id_ignores_branch_named_like_sha(tmp_path):
    from tests.fixture_repo import build_shadowed_sha_repo

    fr = build_shadowed_sha_repo(tmp_path / "r")
    prefix = fr.shas["head"][:7]
    assert gitq.rev_parse(fr.path, prefix) == fr.shas["second"]  # the ref wins here
    assert gitq.resolve_commit_id(fr.path, prefix) == fr.shas["head"]
    assert gitq.resolve_commit_id(fr.path, fr.shas["head"]) == fr.shas["head"]


def test_resolve_commit_id_unknown_or_non_commit(fixture_repo):
    with pytest.raises(gitq.GitError):
        gitq.resolve_commit_id(fixture_repo.path, "deadbee")
    with pytest.raises(gitq.GitError):
        gitq.resolve_commit_id(fixture_repo.path, "not-hex")
