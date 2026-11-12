"""Signal leads follow the profile file set."""

from datetime import UTC, datetime

import pytest

from gittok import brief, db, ledger, profiles
from tests.conftest import make_config
from tests.test_brief import build, signals
from tests.test_fileset import prof

BAD = (".clj-kondo", ".github/aw", "gen/", "out/")
NOW = datetime(2026, 6, 1, tzinfo=UTC)


def bad_fs():
    return profiles.fileset_for(
        prof(
            ignore=[".clj-kondo/**", "gen/**"],
            scan=["*.py", "*.json", "*.clj"],
            kinds={"generated": ["out/**"]},
        )
    )


def bad_sig():
    s = signals()
    s["churn"]["files"]["90"] += [
        {"path": ".clj-kondo/configs/a.clj", "commits": 9, "lines": 90},
        {"path": ".github/aw/actions-lock.yml", "commits": 8, "lines": 80},
        {"path": "out/x.py", "commits": 7, "lines": 70},
    ]
    s["churn"]["dirs"]["90"] += [
        {"path": ".clj-kondo", "commits": 9, "lines": 1},
        {"path": "gen", "commits": 9, "lines": 1},
    ]
    s["author_shares"]["by_dir"][".clj-kondo"] = [{"author": "A", "share": 0.9}]
    s["author_shares"]["by_dir"]["gen"] = [{"author": "A", "share": 0.9}]
    old = {"author": "A", "ts": 1, "sha": "4" * 40}
    s["oldest_lines"].append({"path": ".clj-kondo/configs/a.clj", "line": 1, "text": "x", **old})
    s["new_files"].append(
        {"path": ".github/aw/actions-lock.yml", "sha": "5" * 40, "ts": 5, "author": "A",
         "subject": "lock"}
    )  # fmt: skip
    s["co_change"].append(
        {"a": "src/app.py", "b": ".clj-kondo/c.clj", "count": 9, "jaccard": 0.9, "same_dir": False}
    )
    s["fix_chains"].append(
        {"path": "out/x.py", "commits": [{"sha": "6" * 40, "ts": 1, "subject": "f", "author": "A"}]}
    )
    s["deleted_paths"].append({**s["deleted_paths"][0], "path": "gen/old.py", "died_sha": "7" * 40})
    s["todo_ages"].append({**s["todo_ages"][0], "path": ".clj-kondo/t.clj"})
    s["huge_diffs"].append(
        {**s["huge_diffs"][0], "sha": "8" * 40, "paths": [".clj-kondo/a.clj", "gen/b.py"]}
    )
    s["huge_diffs"].append({**s["huge_diffs"][0], "sha": "9" * 40, "paths": ["src/ok.py", "gen/b"]})
    return s


def cites_bad(path, key, text):
    return any(b in f"{path or ''} {key or ''} {text}" for b in BAD)


def test_every_story_type_skips_ignored_unscanned_and_generated_paths():
    sig, seen = bad_sig(), 0
    for story in dict.fromkeys(t for ts in brief.CATEGORY_STORIES.values() for t in ts):
        for ld in brief.lead_refs_for(story, sig, None, 1000, repo="r", files=bad_fs()):
            seen += 1
            assert not cites_bad(ld.path, ld.key, ld.text), (story, ld)
    assert seen > 8
    # the all-outside huge diff is dropped, the one with a read path stays
    huge = brief.lead_refs_for("commit_drama", sig, None, 1000, repo="r", files=bad_fs())
    assert [x.commit for x in huge if x.text.startswith("huge")] == ["b" * 40, "9" * 40]


def test_without_a_profile_the_bootstrap_defaults_decide():
    plain = brief.lead_refs_for("hot_spot", bad_sig(), None, 1000, repo="r")
    assert any("src/app.py" in ld.text for ld in plain)
    assert not any(".clj-kondo" in ld.text or "out/" in ld.text for ld in plain)  # bootstrap


def test_build_brief_cites_no_ignored_path():
    b = build(
        count=12, sig=bad_sig(), ledger=None, filesets={"fixture": bad_fs()},
        novelty={"fixture": {"src": 0.9}}, intro_share=0.5,
    )  # fmt: skip
    refs = [r for p in b.packets for r in p.lead_refs]
    assert refs
    assert not [r for r in refs if cites_bad(r.get("path"), r.get("key"), r.get("text", ""))]


def test_intro_never_picks_an_unscanned_or_ignored_dir():
    f = bad_fs()
    stale = [
        brief.Lead("hot_spot", "fixture", "path", path=p, text=p, id=i)
        for i, p in enumerate([".github/aw/x.yml", ".clj-kondo/a.clj", "gen/a.py", "out/a.py"])
    ]
    slots = [("fixture", 0, "hot_spot", None, None)] * 4
    ref_by = {("fixture", "hot_spot"): {x.text: x for x in stale}}
    out = brief._assign_intro(slots, {}, ref_by, {"fixture": {}}, 1.0, 4, filesets={"fixture": f})
    assert out == {}


@pytest.fixture
def conn():
    c = db.open_db(":memory:")
    yield c
    c.close()


def test_stored_rows_for_ignored_paths_are_not_offered(conn, tmp_path, fixture_repo):
    cfg = make_config(fixture_repo, tmp_path)
    for p in ("gen/old.py", "src/a.py", ".github/aw/l.yml"):
        conn.execute(
            "INSERT INTO leads(repo, story_type, kind, path, commit_sha, blob_sha, lead_key, text,"
            " strength, head_sha, first_seen_at, last_seen_at) VALUES ('r','hot_spot','path',?,"
            "'','',?,'t',1,'h',?,?)",
            (p, f"p:{p}", ledger.iso(NOW), ledger.iso(NOW)),
        )
    conn.execute(  # a pinned follow-up request stays, whatever its path
        "INSERT INTO leads(repo, story_type, kind, path, commit_sha, blob_sha, lead_key, text,"
        " strength, head_sha, first_seen_at, last_seen_at) VALUES ('r','hot_spot','path',"
        "'gen/pin.py','','','req:1','t',1,'h',?,?)",
        (ledger.iso(NOW), ledger.iso(NOW)),
    )
    f = bad_fs()
    got = ledger.ranked(conn, cfg, "r", "hot_spot", NOW, 10, files=f)
    assert sorted(x.path for x in got) == ["gen/pin.py", "src/a.py"]
    out = ledger.for_brief(conn, cfg, ["r"], NOW, filesets={"r": f})
    assert sorted(x.path for x in out[("r", "hot_spot")]) == ["gen/pin.py", "src/a.py"]
