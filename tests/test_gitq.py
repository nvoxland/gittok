import pytest

from gittok import gitq
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


# --- config-driven execution -------------------------------------------------------------------


def _raw_git(cwd, *args, stdin=None):
    import subprocess

    ident = ["-c", "user.name=T", "-c", "user.email=t@example.com", "-c", "commit.gpgsign=false"]
    return subprocess.run(
        ["git", "-C", str(cwd), *ident, *args], check=True, capture_output=True, input=stdin
    ).stdout


def _hostile_config(marks) -> str:
    """Git config that runs a script (touching a file in `marks`) at every knob we know."""
    marks.mkdir(exist_ok=True)
    bin_dir = marks.parent / "evil-bin"
    bin_dir.mkdir(exist_ok=True)

    def script(name, then="exit 0"):
        path = bin_dir / name
        path.write_text(f"#!/bin/sh\ntouch {marks / name}\n{then}\n")
        path.chmod(0o755)
        return path

    return (
        '[diff "evil"]\n'
        f"\ttextconv = {script('textconv', 'cat "$1"')}\n"
        f"\tcommand = {script('driver')}\n"
        "[diff]\n"
        f"\texternal = {script('external')}\n"
        "[core]\n"
        f"\tfsmonitor = {script('fsmonitor')}\n"
        f"\tpager = {script('pager', 'cat')}\n"
        "[pager]\n"
        "\tshow = true\n\tlog = true\n\tdiff = true\n\tblame = true\n\tgrep = true\n"
        "[log]\n\tshowSignature = true\n"
        f"[gpg]\n\tprogram = {script('gpg', 'exit 1')}\n"
    )


def _hostile_repo(tmp_path):
    """A normal checkout whose .git/config and attributes try to run commands."""
    repo = tmp_path / "hostile"
    repo.mkdir()
    _raw_git(repo, "init", "-q", "-b", "main")
    (repo / "a.txt").write_text("one\ntwo\n")
    _raw_git(repo, "add", "-A")
    _raw_git(repo, "commit", "-q", "-m", "first")
    (repo / "a.txt").write_text("one\nTWO\nthree\n")
    _raw_git(repo, "add", "-A")
    _raw_git(repo, "commit", "-q", "-m", "second")
    # a "signed" tip, so log.showSignature would call gpg.program
    body = _raw_git(repo, "cat-file", "commit", "HEAD")
    head, sep, msg = body.partition(b"\n\n")
    sig = b"gpgsig -----BEGIN PGP SIGNATURE-----\n \n iQEzBAAB\n -----END PGP SIGNATURE-----"
    signed = _raw_git(
        repo, "hash-object", "-t", "commit", "-w", "--stdin", stdin=head + b"\n" + sig + sep + msg
    )
    _raw_git(repo, "update-ref", "refs/heads/main", signed.decode().strip())
    (repo / ".git" / "info").mkdir(exist_ok=True)
    (repo / ".git" / "info" / "attributes").write_text("* diff=evil\n")
    marks = tmp_path / "marks"
    with (repo / ".git" / "config").open("a") as fh:
        fh.write(_hostile_config(marks))
    return repo, marks


def _every_read(repo):
    """Each kind of git call the package makes, through gitq."""
    calls = [
        ("show", "HEAD"),
        ("show", "--format=", "--stat", "HEAD"),
        ("show", "-s", "--format=%B", "HEAD"),
        ("show", "HEAD:a.txt"),
        ("log", "-p", "-n2", "HEAD"),
        ("log", "-n2", "--format=%H", "HEAD"),
        ("diff", "HEAD~1", "HEAD"),
        ("diff", "--name-only", "HEAD~1..HEAD"),
        ("blame", "--date=short", "-L", "1,2", "HEAD", "--", "a.txt"),
        ("grep", "-n", "-I", "-F", "-e", "one", "HEAD", "--"),
        ("ls-tree", "-r", "HEAD"),
        ("rev-list", "-n", "1", "HEAD"),
        ("status", "--porcelain"),
    ]
    for args in calls:
        try:
            gitq.run(repo, *args)
        except gitq.GitError:
            pass
    for fn in (
        lambda: gitq.blame_range(repo, "HEAD", "a.txt", 1, 2),
        lambda: gitq.changed_old_ranges(repo, "HEAD", "a.txt"),
        lambda: gitq.log_new_hunks(repo, "HEAD", None, 5),
        lambda: gitq.grep_word(repo, "HEAD", "one"),
        lambda: gitq.show_file(repo, "HEAD", "a.txt"),
        lambda: gitq.read_blobs(repo, list(gitq.ls_tree_blobs(repo, "HEAD").values())),
        lambda: gitq.recent_commits(repo, "HEAD", 0),
        lambda: gitq.remote_url(repo),
    ):
        try:
            fn()
        except gitq.GitError:
            pass


def test_hostile_repo_config_runs_without_the_hardening(tmp_path):
    """The fixture is real: plain git does run the configured commands."""
    import subprocess

    repo, marks = _hostile_repo(tmp_path)
    for args in (["show", "HEAD"], ["diff", "HEAD~1", "HEAD"], ["blame", "HEAD", "--", "a.txt"]):
        subprocess.run(["git", "-C", str(repo), *args], capture_output=True)
    made = {p.name for p in marks.iterdir()}
    assert {"textconv", "gpg"} <= made and made & {"driver", "external"}


def test_repo_config_cannot_run_commands_through_gitq(tmp_path):
    repo, marks = _hostile_repo(tmp_path)
    _every_read(repo)
    assert sorted(p.name for p in marks.iterdir()) == []
    # the reads still work
    assert "TWO" in gitq.run(repo, "show", "HEAD")
    assert gitq.blame_range(repo, "HEAD", "a.txt", 1, 1)[0]["author"] == "T"
    assert gitq.changed_old_ranges(repo, "HEAD", "a.txt") == [(2, 2)]


def _embedded_git_dir(tmp_path):
    """An outer repo that has, as ordinary committed files, a directory laid out like a bare
    git dir (HEAD, config, objects, refs) with a hostile config."""
    import shutil

    hostile, marks = _hostile_repo(tmp_path)
    outer = tmp_path / "outer"
    outer.mkdir()
    _raw_git(outer, "init", "-q", "-b", "main")
    (outer / "README").write_text("outer\n")
    inner = outer / "vendor" / "data"
    shutil.copytree(hostile / ".git", inner)
    cfg = (inner / "config").read_text().replace("bare = false", "bare = true")
    (inner / "config").write_text(cfg)
    _raw_git(outer, "add", "-A", "-f")
    _raw_git(outer, "commit", "-q", "-m", "outer")
    for p in marks.iterdir():
        p.unlink()
    return outer, inner, marks


def test_embedded_bare_git_dir_is_not_used_as_a_repo(tmp_path):
    outer, inner, marks = _embedded_git_dir(tmp_path)
    assert (inner / "HEAD").is_file() and (inner / "objects").is_dir()
    _every_read(inner)
    assert sorted(p.name for p in marks.iterdir()) == []
    # git refuses the directory; it never reads the embedded config or history
    with pytest.raises(gitq.GitError, match="bare repository"):
        gitq.run(inner, "log", "-n1", "--format=%s", "HEAD")
    assert gitq.run(outer, "log", "-n1", "--format=%s", "HEAD").strip() == "outer"


def test_fetch_does_not_run_repo_hooks_or_ext_transport(tmp_path):
    repo, marks = _hostile_repo(tmp_path)
    origin = tmp_path / "origin.git"
    _raw_git(tmp_path, "clone", "-q", "--bare", str(repo), str(origin))
    _raw_git(repo, "remote", "add", "origin", str(origin))
    _raw_git(repo, "fetch", "-q", "origin")
    hooks = tmp_path / "hooks"
    hooks.mkdir()
    hook = hooks / "reference-transaction"
    hook.write_text(f"#!/bin/sh\ntouch {marks / 'hook'}\n")
    hook.chmod(0o755)
    _raw_git(repo, "config", "core.hooksPath", str(hooks))
    for p in marks.iterdir():
        p.unlink()
    _raw_git(repo, "update-ref", "-d", "refs/remotes/origin/main")
    assert (marks / "hook").exists()  # the hook is live for plain git
    _raw_git(repo, "-c", "core.hooksPath=/dev/null", "fetch", "-q", "origin")
    for p in marks.iterdir():
        p.unlink()
    assert gitq.fetch_ref(repo, "origin/main") == "fetched"
    assert sorted(p.name for p in marks.iterdir()) == []
    _raw_git(repo, "remote", "set-url", "origin", f"ext::sh -c 'touch {marks / 'ext'}'")
    for p in marks.iterdir():
        p.unlink()
    assert gitq.fetch_ref(repo, "origin/main") == "failed"
    assert sorted(p.name for p in marks.iterdir()) == []


# --- clone (for repos added by URL) ------------------------------------------------------------


@pytest.fixture
def bare_remote(fixture_repo, tmp_path):
    """A local bare repo that stands in for a remote. No network."""
    remote = tmp_path / "remote.git"
    _raw_git(tmp_path, "clone", "-q", "--bare", str(fixture_repo.path), str(remote))
    return remote


def test_clone_makes_a_full_non_bare_clone_without_a_checkout(bare_remote, fixture_repo, tmp_path):
    dest = tmp_path / "home" / "repos" / "proj"
    gitq.clone(str(bare_remote), dest)
    assert (dest / ".git").is_dir()
    assert [p.name for p in dest.iterdir()] == [".git"]  # no files checked out
    assert gitq.default_remote_ref(dest) == "origin/main"
    assert gitq.rev_parse(dest, "origin/main") == fixture_repo.shas["head"]
    assert not (dest / ".git" / "shallow").exists()
    assert gitq.rev_parse(dest, fixture_repo.shas["initial"])  # full history
    assert gitq.run(dest, "tag").strip() == ""
    assert gitq.fetch_ref(dest, "origin/main") == "fetched"


def test_clone_failure_removes_the_partial_directory(tmp_path):
    dest = tmp_path / "home" / "repos" / "gone"
    with pytest.raises(gitq.GitError, match="clone"):
        gitq.clone(str(tmp_path / "missing.git"), dest)
    assert not dest.exists()


def test_clone_refuses_an_existing_target_and_leaves_it(bare_remote, tmp_path):
    dest = tmp_path / "taken"
    dest.mkdir()
    (dest / "keep.txt").write_text("mine")
    with pytest.raises(gitq.GitError, match="already exists"):
        gitq.clone(str(bare_remote), dest)
    assert (dest / "keep.txt").read_text() == "mine"


def test_clone_never_runs_a_command_from_the_source(tmp_path):
    mark = tmp_path / "mark"
    for source in (f"ext::sh -c 'touch {mark}'", f"--upload-pack=touch {mark}", "-x"):
        dest = tmp_path / "out"
        with pytest.raises(gitq.GitError):
            gitq.clone(source, dest)
        assert not dest.exists() and not mark.exists()


def test_clone_and_fetch_do_not_prompt(monkeypatch):
    monkeypatch.delenv("GIT_SSH_COMMAND", raising=False)
    monkeypatch.delenv("GIT_SSH", raising=False)
    monkeypatch.setattr(gitq, "_configured_ssh_command", lambda repo: "")
    env = gitq._net_env(None)
    assert env["GIT_TERMINAL_PROMPT"] == "0"
    assert "BatchMode=yes" in env["GIT_SSH_COMMAND"]
    # the user's own ssh command wins, from the environment or from git config
    monkeypatch.setenv("GIT_SSH_COMMAND", "ssh -i ~/.ssh/work")
    assert gitq._net_env(None)["GIT_SSH_COMMAND"] == "ssh -i ~/.ssh/work"
    monkeypatch.delenv("GIT_SSH_COMMAND")
    monkeypatch.setattr(gitq, "_configured_ssh_command", lambda repo: "ssh -i ~/.ssh/work")
    assert "GIT_SSH_COMMAND" not in gitq._net_env(None)
