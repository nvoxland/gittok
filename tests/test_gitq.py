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
