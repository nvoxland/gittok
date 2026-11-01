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
    out = gitq.run(
        fixture_repo.path, "show", f"{fixture_repo.shas['huge']}:data/big.txt", max_bytes=100
    )
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


def test_blame_range_gives_author_and_time_per_line(fixture_repo):
    s = fixture_repo.shas
    rows = gitq.blame_range(fixture_repo.path, s["head"], "src/app.py", 1, 5)
    assert [r["author"] for r in rows] == [
        "Alice Archer",
        "Alice Archer",
        "Bob Builder",
        "Bob Builder",
        "Bob Builder",
    ]
    assert rows[0]["author_time"] < rows[2]["author_time"]
    assert rows[0]["sha"] == s["initial"]


def test_blame_range_unknown_path_raises(fixture_repo):
    with pytest.raises(gitq.GitError):
        gitq.blame_range(fixture_repo.path, fixture_repo.shas["head"], "nope.py", 1, 2)


def test_first_parent_of_fix_is_the_commit_before(fixture_repo):
    s = fixture_repo.shas
    assert gitq.first_parent(fixture_repo.path, s["fix1"]) == s["invoice_add"]
    assert gitq.first_parent(fixture_repo.path, s["initial"]) is None


def test_changed_old_ranges_lists_hunks_on_the_parent_side(fixture_repo):
    s = fixture_repo.shas
    ranges = gitq.changed_old_ranges(fixture_repo.path, s["fix1"], "billing/invoice.py")
    assert ranges == [(5, 5)]


def test_path_removed_by_detects_delete_and_rename(tmp_path):
    from tests.fixture_repo import _Builder

    path = tmp_path / "r"
    path.mkdir()
    b = _Builder(path)
    b.git("init", "-q", "-b", "main")
    b.write("a.py", "x = 1\ny = 2\n")
    b.write("keep.py", "k = 1\n")
    first = b.commit("first", date="2026-01-05T10:00:00+00:00")
    b.git("mv", "a.py", "b.py")
    renamed = b.commit("rename", date="2026-01-06T10:00:00+00:00")
    b.write("keep.py", "k = 2\n")
    edited = b.commit("edit", date="2026-01-07T10:00:00+00:00")
    b.git("rm", "-q", "b.py")
    deleted = b.commit("delete", date="2026-01-08T10:00:00+00:00")
    assert not gitq.path_removed_by(path, first, "a.py")
    assert gitq.path_removed_by(path, renamed, "a.py")
    assert not gitq.path_removed_by(path, edited, "keep.py")
    assert gitq.path_removed_by(path, deleted, "b.py")


def test_blame_range_reports_author_timezone(tmp_path):
    from tests.fixture_repo import _Builder

    path = tmp_path / "r"
    path.mkdir()
    b = _Builder(path)
    b.git("init", "-q", "-b", "main")
    b.write("a.py", "x = 1\n")
    sha = b.commit("tz", date="2026-01-01T03:00:00+10:30")
    [row] = gitq.blame_range(path, sha, "a.py", 1, 1)
    assert row["author_tz"] == "+1030"


def test_ls_tree_blobs_maps_paths_to_blob_shas(fixture_repo):
    blobs = gitq.ls_tree_blobs(fixture_repo.path, "main")
    assert "billing/invoice.py" in blobs
    assert "billing" not in blobs  # trees are not listed
    assert "src/legacy.py" not in blobs  # deleted before head
    assert all(len(v) == 40 for v in blobs.values())
    want = gitq.run(fixture_repo.path, "rev-parse", "main:billing/invoice.py").strip()
    assert blobs["billing/invoice.py"] == want


def test_ls_tree_blobs_rejects_option_injection(fixture_repo):
    with pytest.raises(gitq.GitError):
        gitq.ls_tree_blobs(fixture_repo.path, "--output=/tmp/x")


def test_remote_url_is_none_without_origin(fixture_repo):
    assert gitq.remote_url(fixture_repo.path) is None


def test_remote_url_reads_origin(tmp_path):
    import subprocess

    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(
        ["git", "-C", str(tmp_path), "remote", "add", "origin", "git@github.com:org/name.git"],
        check=True,
    )
    assert gitq.remote_url(tmp_path) == "git@github.com:org/name.git"


def _git(cwd, *args):
    import subprocess

    return subprocess.run(
        ["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


@pytest.fixture
def cloned(tmp_path):
    origin = tmp_path / "origin.git"
    seed = tmp_path / "seed"
    clone = tmp_path / "clone"
    _git(tmp_path, "init", "--bare", "-b", "master", str(origin))
    _git(tmp_path, "clone", str(origin), str(seed))
    for k, v in (("user.name", "t"), ("user.email", "t@t")):
        _git(seed, "config", k, v)
    (seed / "a.txt").write_text("one\n")
    _git(seed, "add", ".")
    _git(seed, "commit", "-m", "one")
    _git(seed, "push", "origin", "HEAD:master")
    _git(tmp_path, "clone", str(origin), str(clone))
    return origin, seed, clone


def _push_new_commit(seed):
    (seed / "b.txt").write_text("two\n")
    _git(seed, "add", ".")
    _git(seed, "commit", "-m", "two")
    _git(seed, "push", "origin", "HEAD:master")


def test_fetch_ref_updates_remote_tracking_only(cloned):
    _, seed, clone = cloned
    gitq._last_fetch.clear()
    head, status = _git(clone, "rev-parse", "HEAD"), _git(clone, "status", "--porcelain")
    _push_new_commit(seed)
    new = _git(seed, "rev-parse", "HEAD")
    assert gitq.fetch_ref(clone, "origin/master") == "fetched"
    assert _git(clone, "rev-parse", "origin/master") == new
    assert _git(clone, "rev-parse", "HEAD") == head
    assert _git(clone, "status", "--porcelain") == status
    assert not (clone / "b.txt").exists()


def test_fetch_ref_skips_non_remote_ref(cloned):
    _, _, clone = cloned
    assert gitq.fetch_ref(clone, "HEAD") == "skipped"
    assert gitq.fetch_ref(clone, "master") == "skipped"


def test_fetch_ref_throttles(cloned):
    _, seed, clone = cloned
    gitq._last_fetch.clear()
    assert gitq.fetch_ref(clone, "origin/master", min_interval_s=900) == "fetched"
    _push_new_commit(seed)
    before = _git(clone, "rev-parse", "origin/master")
    assert gitq.fetch_ref(clone, "origin/master", min_interval_s=900) == "throttled"
    assert _git(clone, "rev-parse", "origin/master") == before
    assert gitq.fetch_ref(clone, "origin/master", min_interval_s=0) == "fetched"


def test_fetch_ref_failure_returns_failed(cloned, tmp_path):
    _, _, clone = cloned
    gitq._last_fetch.clear()
    _git(clone, "remote", "set-url", "origin", str(tmp_path / "missing.git"))
    assert gitq.fetch_ref(clone, "origin/master") == "failed"
