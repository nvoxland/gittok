"""Convention vs reality miner. Facts are inserted by hand: no grammar needed."""

import pytest

from gittok import candidates, conventions, db, facts, gitq, profiles
from gittok.config import AnalysisSettings, ConfigError
from tests.fixture_repo import build_history_repo

SVC = """(ns svc)

(defn save-invoice [inv]
  (db/insert! :invoices inv))

(defn charge-card [c]
  (save-invoice c))

(defn compute-total! [xs]
  (reduce + xs))

(defn find-user [id]
  (db/query id))

(defn show-user [id]
  (let [u (find-user id)]
    (:name u)))

(defn show-safe [id]
  (when-let [u (find-user id)]
    (:name u)))
"""
DEFS = [  # name, start, end
    ("save-invoice", 3, 4),
    ("charge-card", 6, 7),
    ("compute-total!", 9, 10),
    ("find-user", 12, 13),
    ("show-user", 15, 17),
    ("show-safe", 19, 21),
]
RAW = {
    "sinks": [{"pattern": r"db/insert!", "kind": "db_write"}],
    "conventions": [{"name_regex": "!$", "means": "effectful"}],
    "nil_guards": ["when-let", r"some->"],
    "nil_markers": [":maybe"],
}


@pytest.fixture
def world(tmp_path):
    steps = [("one", {"src/svc.clj": SVC}, "2026-01-01T10:00:00+00:00")]
    r = build_history_repo(tmp_path / "r", steps)
    conn = db.open_db(tmp_path / "t.db")
    head = gitq.rev_parse(r.path, "main")
    conn.execute("INSERT INTO repos(name, path, ref) VALUES ('fx', ?, 'main')", (str(r.path),))
    rid = conn.execute("SELECT id FROM repos").fetchone()[0]
    ids = {}
    for name, a, b in DEFS:
        fid = facts.fact_id("def", "fx", name)
        ids[name] = fid
        conn.execute(
            'INSERT INTO fact_defines VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,"syntax")',
            (fid, rid, "src/svc.clj", f"svc/{name}", name, "function", a, b, b - a + 1, 1, 1, 0, 1),
        )

    def call(caller, callee, line):
        fid = facts.fact_id("call", "fx", caller, callee, line)
        ids[f"{caller}>{callee}"] = fid
        conn.execute(
            "INSERT INTO fact_calls VALUES (?,?,?,?,?,?,1,?,'syntax')",
            (fid, rid, f"svc/{caller}", callee, "src/svc.clj", line, f"svc/{callee}"),
        )

    call("charge-card", "save-invoice", 7)
    call("show-user", "find-user", 16)
    call("show-safe", "find-user", 20)
    sid = facts.fact_id("sch", "fx", "find-user")
    ids["schema"] = sid
    conn.execute(
        "INSERT INTO fact_schema VALUES (?,?,'returns','src/svc.clj',12,'svc/find-user',"
        "':maybe User',NULL,'schema:t')",
        (sid, rid),
    )
    conn.execute("INSERT INTO fact_builds VALUES (?,?,?,1,'{}','')", (rid, head, db.now_iso()))
    yield conn, r, head, ids
    conn.close()


def prof(**over):
    return profiles.parse({**RAW, **over}, "fx")


def mine(world, profile):
    conn, r, head, _ = world
    return conventions.mine(conn, "fx", r.path, head, profile, AnalysisSettings())


def by_tag(found, tag):
    return [c for c in found if c["tag"] == tag]


def test_hidden_side_effect_with_call_path(world):
    ids = world[3]
    (c,) = [c for c in by_tag(mine(world, prof()), "convention_mismatch") if c["start"] == 6]
    assert "charge-card reaches db/insert! via save-invoice (2 hops)" in c["why"]
    assert c["fact_ids"] == [
        ids["charge-card"],
        ids["charge-card>save-invoice"],
        ids["save-invoice"],
    ]
    assert (c["path"], c["end"]) == ("src/svc.clj", 7)


def test_direct_sink_has_one_hop(world):
    found = by_tag(mine(world, prof()), "convention_mismatch")
    (c,) = [c for c in found if c["start"] == 3]
    assert "(1 hop)" in c["why"] and c["fact_ids"] == [world[3]["save-invoice"]]


def test_pure_function_with_effectful_name(world):
    found = by_tag(mine(world, prof()), "convention_mismatch")
    (c,) = [c for c in found if c["start"] == 9]
    assert "compute-total!" in c["why"] and "no sink" in c["why"]
    assert c["fact_ids"] == [world[3]["compute-total!"]]


def test_nil_contract_flags_unguarded_caller_only(world):
    (c,) = by_tag(mine(world, prof()), "nil_contract")
    ids = world[3]
    assert c["path"] == "src/svc.clj" and c["start"] <= 16 <= c["end"]
    assert c["end"] < 20
    assert c["fact_ids"] == [ids["schema"], ids["show-user>find-user"]]
    assert "find-user" in c["why"] and "show-user" in c["why"]


def test_no_sinks_finds_no_effect_mismatch(world):
    assert by_tag(mine(world, prof(sinks=[])), "convention_mismatch") == []


def test_nothing_without_profile_data(world):
    assert mine(world, profiles.Profile()) == []
    assert mine(world, None) == []
    assert by_tag(mine(world, prof(nil_guards=[])), "nil_contract") == []
    assert by_tag(mine(world, prof(nil_markers=[])), "nil_contract") == []


def test_unique_unresolved_call_counts(world):
    conn = world[0]
    rid = conn.execute("SELECT id FROM repos").fetchone()[0]
    conn.execute("DELETE FROM fact_calls WHERE callee_name = 'save-invoice'")
    conn.execute(
        "INSERT INTO fact_calls VALUES ('call-x',?,'svc/charge-card','save-invoice',"
        "'src/svc.clj',7,0,NULL,'syntax')",
        (rid,),
    )
    found = by_tag(mine(world, prof()), "convention_mismatch")
    (c,) = [c for c in found if c["start"] == 6]
    assert "(2 hops)" in c["why"] and "call-x" in c["fact_ids"]


def test_depth_is_bounded():
    assert conventions.MAX_HOPS == 6


def test_refresh_stores_fact_ids_and_survives_candidate_refresh(world):
    conn, r, head, ids = world
    n = conventions.refresh(conn, "fx", r.path, head, AnalysisSettings(), prof())
    assert n >= 4
    rows = candidates.load_candidates(conn, "fx", tag="convention_mismatch")
    row = next(x for x in rows if x["start"] == 6)
    assert row["fact_ids"][0] == ids["charge-card"]
    # the built-in refresh must not delete these rows
    candidates.refresh(conn, "fx", r.path, head, 0, {}, AnalysisSettings(), prof())
    assert candidates.load_candidates(conn, "fx", tag="nil_contract")
    # a profile without data clears them
    conventions.refresh(conn, "fx", r.path, head, AnalysisSettings(), profiles.Profile())
    assert candidates.load_candidates(conn, "fx", tag="nil_contract") == []
    assert candidates.load_candidates(conn, "fx", tag="convention_mismatch") == []


def test_profile_schema_rejects_bad_data():
    with pytest.raises(ConfigError, match="sinks"):
        profiles.parse({"sinks": [{"pattern": "(", "kind": "x"}]}, "fx")
    with pytest.raises(ConfigError):
        profiles.parse({"conventions": [{"name_regex": "!$", "means": "loud"}]}, "fx")
    with pytest.raises(ConfigError, match="nil_guards"):
        profiles.parse({"nil_guards": ["("]}, "fx")


def test_leads_map_the_tags():
    from gittok import candidate_leads as cl

    for tag in ("convention_mismatch", "nil_contract"):
        assert tag in cl.CLEVER_TAGS and tag in cl.PREFER_TAGS


EVIL = r"(a|aa)+$"  # catastrophic on a long run of "a" that ends in another letter
EVIL_TEXT = "a" * 40 + "b"


def test_a_catastrophic_profile_regex_is_skipped_with_a_reason_not_a_hang(
    world, monkeypatch, caplog
):
    import logging
    import time

    conn, r, head, _ = world
    monkeypatch.setattr(profiles, "REGEX_TIMEOUT_S", 0.1)
    rid = conn.execute("SELECT id FROM repos").fetchone()[0]
    for n in range(40):  # 40 names: a rule that is not dropped after its first timeout is slow
        name = f"{EVIL_TEXT}{n}"
        conn.execute(
            'INSERT INTO fact_defines VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,"syntax")',
            (facts.fact_id("def", "fx", name), rid, "src/svc.clj", f"svc/{name}", name,
             "function", 1, 1, 1, 1, 1, 0, 1),
        )  # fmt: skip
        conn.execute(
            "INSERT INTO fact_calls VALUES (?,?,?,?,?,?,1,?,'syntax')",
            (facts.fact_id("call", "fx", name), rid, "svc/show-safe", name, "src/svc.clj", 20,
             f"svc/{name}"),
        )  # fmt: skip
    profile = prof(
        sinks=[{"pattern": EVIL, "kind": "x"}, {"pattern": r"db/insert!", "kind": "db_write"}],
        conventions=[
            {"name_regex": EVIL, "means": "effectful"},
            {"name_regex": "!$", "means": "effectful"},
        ],
    )
    stats: dict = {}
    started = time.monotonic()
    with caplog.at_level(logging.WARNING, logger="gittok.profiles"):
        found = conventions.mine(conn, "fx", r.path, head, profile, AnalysisSettings(), stats)
    assert time.monotonic() - started < 3
    skipped = {s["rule"]: s["reason"] for s in stats["skipped_rules"]}
    assert set(skipped) == {"sinks[0]", "conventions[0]"}
    assert all("timed out" in reason for reason in skipped.values())
    assert any("sinks[0]" in rec.message and "skipped" in rec.message for rec in caplog.records)
    # The rules that work still give their candidates.
    whys = [c["why"] for c in by_tag(found, "convention_mismatch")]
    assert any("charge-card reaches db/insert!" in w for w in whys)
    assert any("compute-total! is named like an effectful function" in w for w in whys)


def test_nil_guard_regexes_run_under_the_time_limit(world, monkeypatch):
    seen = []
    real = profiles.SafeRegex.search

    def spy(self, text):
        seen.append(self.label)
        return real(self, text)

    monkeypatch.setattr(profiles.SafeRegex, "search", spy)
    mine(world, prof())
    assert {"nil_guards[0]", "sinks[0]", "conventions[0]"} <= set(seen)


def test_safe_regex_stops_after_its_first_timeout(monkeypatch):
    monkeypatch.setattr(profiles, "REGEX_TIMEOUT_S", 0.1)
    skipped: list = []
    rx = profiles.SafeRegex("rule-1", EVIL, skipped=skipped)
    assert rx.search("aab") is None and skipped == []  # fast enough: still in use
    assert rx.search("xaa").group(0) == "aa"
    assert rx.search(EVIL_TEXT) is None
    assert [s["rule"] for s in skipped] == ["rule-1"] and "timed out" in skipped[0]["reason"]
    assert rx.search("xaa") is None  # skipped from now on
    assert len(skipped) == 1


def test_nil_check_matches_each_path_once_and_not_each_pair(world):
    conn, _, _, _ = world
    rid = conn.execute("SELECT id FROM repos").fetchone()[0]
    paths = [f"src/p{i % 3}.clj" for i in range(300)]
    calls = [
        {
            "fact_id": f"call-{i}",
            "path": p,
            "line": i + 1,
            "caller_symbol": f"x{i}",
            "callee_symbol": "svc/find-user" if i % 2 == 0 else "svc/other",
            "callee_name": "find-user",
            "resolved": 1,
        }
        for i, p in enumerate(paths)
    ]
    texts = {p: ["(x)"] * 400 for p in set(paths)}
    checked = []

    class Fs:
        def is_test(self, path):
            checked.append(path)
            return False

    out = conventions._nil(conn, rid, prof(), [], calls, {}, {}, texts, Fs(), [])
    assert len(out) == 150  # the calls that reach find-user and are not guarded
    assert len(checked) <= 3
