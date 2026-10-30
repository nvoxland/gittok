import pytest

from codescroll import validator
from codescroll.config import Repo
from tests.cards import example_card, text_card

PERSONAS = ["greybeard", "penny_learns", "archivist", "meme_compiler", "paranoid_sec", "shipit_sam"]


@pytest.fixture
def repos(fixture_repo):
    return {"fixture": Repo(name="fixture", path=fixture_repo.path, ref="main")}


def check(cards, repos):
    return validator.validate_cards(cards, repos, PERSONAS)


def reasons(rejected):
    return [r.reason for r in rejected]


def test_rejects_lines_out_of_range(fixture_repo, repos):
    card = example_card(fixture_repo)
    card["visual"]["lines"] = [3, 99]
    accepted, rejected = check([card], repos)
    assert accepted == []
    assert reasons(rejected) == ["lines_out_of_range"]
    assert rejected[0].index == 0


def test_accepts_valid_card_and_resolves_code(fixture_repo, repos):
    accepted, rejected = check([example_card(fixture_repo)], repos)
    assert rejected == []
    [a] = accepted
    assert a.card["visual"]["commit"] == fixture_repo.shas["invoice_add"]
    assert a.resolved["visual"]["code"].startswith("def total(items):")
    assert a.resolved["visual"]["language"] == "python"
    assert a.resolved["visual"]["start_line"] == 1
    assert a.resolved["depth"][0] is None
    assert "+    return round(t, 2)" in a.resolved["depth"][1]["diff"]
    assert len(a.story_key) == 16


def test_dirs_accept_plain_and_repo_prefixed(fixture_repo, repos):
    for dirs in (["billing"], ["fixture/billing"], ["src", "billing/"], []):
        accepted, rejected = check([example_card(fixture_repo, dirs=dirs)], repos)
        assert rejected == [], dirs


def test_rejects_unknown_dir(fixture_repo, repos):
    for dirs in (["nope"], ["fixture/nope"], ["src/app.py"]):
        _, rejected = check([example_card(fixture_repo, dirs=dirs)], repos)
        assert reasons(rejected) == ["unknown_dir"], dirs


def _mutate(fixture_repo, fn):
    card = example_card(fixture_repo)
    fn(card, fixture_repo.shas)
    return card


MUTATIONS = {
    "schema": lambda c, s: c.update(tone="smug"),
    "unknown_repo": lambda c, s: c.update(repos=["fixture", "other"]),
    "unknown_commit": lambda c, s: c["visual"].update(commit="abcdef1234"),
    "commit_not_in_ref": lambda c, s: c["visual"].update(commit=s["unmerged"]),
    "path_not_at_commit": lambda c, s: c["visual"].update(commit=s["initial"]),
    "excerpt_too_long": lambda c, s: (
        c["visual"].update(path="data/big.txt", commit=s["huge"], lines=[1, 41]),
        c["visual"].pop("callouts"),
    ),
    "callout_out_of_range": lambda c, s: c["visual"]["callouts"][0].update(line=9),
    # src/app.py did not change in the commit that deleted legacy.py
    "empty_diff": lambda c, s: c["depth"][1].update(commit=s["delete_legacy"], path="src/app.py"),
    "missing_explain_panel": lambda c, s: c.update(depth=c["depth"][1:]),
    "excerpt_mismatch": lambda c, s: c["visual"].update(excerpt="def total(items):\n    pass"),
}


@pytest.mark.parametrize("reason", sorted(MUTATIONS))
def test_reject_reasons(fixture_repo, repos, reason):
    card = _mutate(fixture_repo, MUTATIONS[reason])
    accepted, rejected = check([card], repos)
    assert accepted == []
    assert reasons(rejected) == [reason], rejected[0].detail


def test_excerpt_matching_ignores_trailing_space_and_tabs(fixture_repo, repos):
    card = example_card(fixture_repo)
    card["visual"]["excerpt"] = (
        "\ndef total(items):   \n    t = 0\n\tfor price in items:\n"
        "        t += price\n    return round(t)\n\n"
    )
    accepted, rejected = check([card], repos)
    assert rejected == []
    assert accepted[0].resolved["visual"]["code"].splitlines()[2] == "    for price in items:"


def test_source_path_checked_at_repo_ref(fixture_repo, repos):
    card = example_card(fixture_repo)
    card["sources"] = [{"repo": "fixture", "path": "src/legacy.py"}]
    _, rejected = check([card], repos)
    assert reasons(rejected) == ["path_not_at_commit"]


def test_duplicate_story_in_same_submission(fixture_repo, repos):
    accepted, rejected = check([example_card(fixture_repo), example_card(fixture_repo)], repos)
    assert len(accepted) == 1
    assert [(r.index, r.reason) for r in rejected] == [(1, "duplicate_story")]


def test_one_bad_card_does_not_block_others(fixture_repo, repos):
    bad = example_card(fixture_repo, persona="nobody")
    accepted, rejected = check([bad, text_card(fixture_repo)], repos)
    assert [a.index for a in accepted] == [1]
    assert [r.index for r in rejected] == [0]


def test_input_card_not_mutated(fixture_repo, repos):
    card = example_card(fixture_repo)
    short = card["visual"]["commit"]
    check([card], repos)
    assert card["visual"]["commit"] == short


def test_rejects_directory_as_path(fixture_repo, repos):
    card = example_card(fixture_repo)
    card["visual"]["path"] = "billing"
    _, rejected = check([card], repos)
    assert reasons(rejected) == ["path_not_at_commit"]
    assert "directory" in rejected[0].detail


def test_code_diff_path_is_literal_and_must_exist(fixture_repo, repos):
    for bad in ("billing/*.py", ":(glob)**/*.py", "billing"):
        card = example_card(fixture_repo)
        card["depth"][1]["path"] = bad
        _, rejected = check([card], repos)
        assert reasons(rejected) == ["path_not_at_commit"], bad


def test_code_diff_allows_deleted_file(fixture_repo, repos):
    card = example_card(fixture_repo)
    card["depth"][1].update(commit=fixture_repo.shas["delete_legacy"], path="src/legacy.py")
    accepted, rejected = check([card], repos)
    assert rejected == []


def test_line_numbers_follow_newlines_only(tmp_path):
    from tests.fixture_repo import build_small_repo

    fr = build_small_repo(tmp_path / "r", {"a.txt": b"one\x0ctwo\nthree\r\nfour\n", "z.py": b"x\n"})
    repos = {"fixture": Repo(name="fixture", path=fr.path, ref="main")}
    gc = validator._GitCache(repos=repos)
    assert gc.file_lines("fixture", fr.shas["head"], "a.txt") == ["one\x0ctwo", "three", "four"]


def test_code_diff_on_merge_commit_uses_first_parent(fixture_repo, repos):
    card = example_card(fixture_repo)
    card["depth"][1].update(commit=fixture_repo.shas["merge"], path="src/new_feature.py")
    accepted, rejected = check([card], repos)
    assert rejected == []
    assert "+def shiny():" in accepted[0].resolved["depth"][1]["diff"]


def test_hex_sha_resolves_as_object_not_branch(tmp_path):
    from tests.fixture_repo import build_shadowed_sha_repo

    fr = build_shadowed_sha_repo(tmp_path / "r")
    repos = {"fixture": Repo(name="fixture", path=fr.path, ref="main")}
    gc = validator._GitCache(repos=repos)
    assert gc.commit("fixture", fr.shas["head"][:7]) == fr.shas["head"]


def test_rejects_repo_not_in_card_repos(fixture_repo, repos):
    other = {**repos, "other": Repo(name="other", path=fixture_repo.path, ref="main")}
    for mutate in (
        lambda c: c["visual"].update(repo="other"),
        lambda c: c["depth"][1].update(repo="other"),
        lambda c: c["sources"][0].update(repo="other"),
    ):
        card = example_card(fixture_repo)
        mutate(card)
        _, rejected = check([card], other)
        assert reasons(rejected) == ["repo_not_in_card"]


def test_leading_dot_slash_is_normalized_and_dedups(fixture_repo, repos):
    card = example_card(fixture_repo)
    card["visual"]["path"] = "./billing/invoice.py"
    card["depth"][1]["path"] = "././billing/invoice.py"
    card["sources"][1]["path"] = "./billing/invoice.py"
    plain = example_card(fixture_repo)
    accepted, rejected = check([card, plain], repos)
    assert [r.reason for r in rejected] == ["duplicate_story"]
    [a] = accepted
    assert a.card["visual"]["path"] == "billing/invoice.py"
    assert a.card["depth"][1]["path"] == "billing/invoice.py"
    assert a.card["sources"][1]["path"] == "billing/invoice.py"


def test_dirs_are_normalized_in_returned_card(fixture_repo, repos):
    card = example_card(fixture_repo, dirs=["fixture/billing", "./src/", "billing/"])
    accepted, rejected = check([card], repos)
    assert rejected == []
    assert accepted[0].card["dirs"] == ["billing", "src"]


# ---------------------------------------------------------------------------
# M2 formats
# ---------------------------------------------------------------------------
from codescroll.config import Mascot, MemeTemplate  # noqa: E402
from tests import cards as C  # noqa: E402

MEME_TEMPLATES = {"drake": MemeTemplate("drake", 2), "success": MemeTemplate("success", 1)}
MASCOTS = {
    "otter": Mascot("otter", "fixture", "otter style", 1),
    "crow": Mascot("crow", None, "crow style", 2),
}


def check2(cards, repos, **kw):
    kw.setdefault("meme_templates", MEME_TEMPLATES)
    kw.setdefault("mascots", MASCOTS)
    return validator.validate_cards(cards, repos, PERSONAS, **kw)


def test_format_kind_mismatch(fixture_repo, repos):
    card = C.meme_card(fixture_repo, format="text_meme")
    accepted, rejected = check2([card], repos)
    assert reasons(rejected) == ["format_kind_mismatch"]
    card = C.template_card(fixture_repo, "thread", format="hot_take")
    assert reasons(check2([card], repos)[1]) == ["format_kind_mismatch"]
    card = C.template_card(fixture_repo, "hot_take")
    assert reasons(check2([card], repos)[1]) == []
    assert reasons(check2([text_card(fixture_repo, format="meme")], repos)[1]) == [
        "format_kind_mismatch"
    ]


def test_meme_valid_and_unknown_template(fixture_repo, repos):
    accepted, rejected = check2([C.meme_card(fixture_repo)], repos)
    assert rejected == []
    assert accepted[0].resolved["visual"] is None
    bad = C.meme_card(
        fixture_repo, visual={"kind": "meme", "template": "nope", "lines": ["a", "b"]}
    )
    assert reasons(check2([bad], repos)[1]) == ["unknown_meme_template"]


def test_meme_too_many_lines_for_template(fixture_repo, repos):
    card = C.meme_card(
        fixture_repo, visual={"kind": "meme", "template": "success", "lines": ["a", "b"]}
    )
    assert reasons(check2([card], repos)[1]) == ["meme_lines"]
    one = C.meme_card(
        fixture_repo, visual={"kind": "meme", "template": "drake", "lines": ["only one"]}
    )
    assert check2([one], repos)[1] == []


def test_illustration_default_mascot_from_repo(fixture_repo, repos):
    accepted, rejected = check2([C.illustration_card(fixture_repo)], repos)
    assert rejected == []
    assert accepted[0].card["visual"]["mascots"] == ["otter"]
    assert accepted[0].resolved["visual"] is None


def test_illustration_default_mascot_falls_back_to_repo_field(fixture_repo):
    repos = {"fixture": Repo(name="fixture", path=fixture_repo.path, ref="main", mascot="crow")}
    mascots = {"crow": MASCOTS["crow"]}
    accepted, rejected = check2([C.illustration_card(fixture_repo)], repos, mascots=mascots)
    assert rejected == []
    assert accepted[0].card["visual"]["mascots"] == ["crow"]


def test_illustration_without_any_default_mascot_rejected(fixture_repo, repos):
    mascots = {"crow": MASCOTS["crow"]}
    assert reasons(check2([C.illustration_card(fixture_repo)], repos, mascots=mascots)[1]) == [
        "unknown_mascot"
    ]


def test_unknown_mascot_rejected(fixture_repo, repos):
    v = {"kind": "illustration", "prompt": "p", "caption": "c", "mascots": ["otter", "walrus"]}
    assert reasons(check2([C.illustration_card(fixture_repo, visual=v)], repos)[1]) == [
        "unknown_mascot"
    ]
    v = {
        "kind": "comic",
        "panels": C.comic_card(fixture_repo)["visual"]["panels"],
        "mascots": ["x"],
    }
    assert reasons(check2([C.comic_card(fixture_repo, visual=v)], repos)[1]) == ["unknown_mascot"]


def test_comic_default_mascots_and_explicit_kept(fixture_repo, repos):
    accepted, _ = check2([C.comic_card(fixture_repo)], repos)
    assert accepted[0].card["visual"]["mascots"] == ["otter"]
    v = {**C.comic_card(fixture_repo)["visual"], "mascots": ["crow", "otter"]}
    accepted, _ = check2([C.comic_card(fixture_repo, visual=v)], repos)
    assert accepted[0].card["visual"]["mascots"] == ["crow", "otter"]


def test_illustration_budget_counts_panels_in_order(fixture_repo, repos):
    cards = [
        C.illustration_card(fixture_repo),  # 1
        C.comic_card(fixture_repo, panels=3, hook="comic hook"),  # 3 -> total 4
        C.illustration_card(fixture_repo, hook="over"),  # 5th: over
    ]
    cards[1]["sources"] = [{"repo": "fixture", "path": "README.md"}]
    cards[2]["sources"] = [{"repo": "fixture", "path": "src/util.py"}]
    accepted, rejected = check2(cards, repos, illustration_budget=4)
    assert [a.index for a in accepted] == [0, 1]
    assert [(r.index, r.reason) for r in rejected] == [(2, "illustration_budget")]


def test_illustration_budget_zero_and_none(fixture_repo, repos):
    assert reasons(
        check2([C.illustration_card(fixture_repo)], repos, illustration_budget=0)[1]
    ) == ["illustration_budget"]
    assert check2([C.illustration_card(fixture_repo)], repos)[1] == []


def test_card_account_file_and_dir_resolved(fixture_repo, repos):
    accepted, rejected = check2(
        [C.text_meme_card(fixture_repo, account="fixture:./src/app.py")], repos
    )
    assert rejected == []
    assert accepted[0].card["account"] == "fixture:src/app.py"
    assert accepted[0].resolved["account"] == {
        "handle": "@app.py",
        "repo": "fixture",
        "path": "src/app.py",
        "kind": "file",
    }
    accepted, _ = check2([C.text_meme_card(fixture_repo, account="fixture:billing/")], repos)
    assert accepted[0].resolved["account"]["kind"] == "dir"
    assert accepted[0].resolved["account"]["handle"] == "@billing"
    assert accepted[0].card["account"] == "fixture:billing"


def test_no_account_means_no_resolved_account(fixture_repo, repos):
    accepted, _ = check2([C.text_meme_card(fixture_repo)], repos)
    assert "account" not in accepted[0].resolved


def test_unknown_account_rejected(fixture_repo, repos):
    for acct in ("fixture:src/missing.py", "other:src/app.py", "fixture:../x"):
        card = C.text_meme_card(fixture_repo, account=acct)
        assert reasons(check2([card], repos)[1]) in (["unknown_account"], ["schema"]), acct
    card = C.text_meme_card(fixture_repo, account="fixture:src/missing.py")
    assert reasons(check2([card], repos)[1]) == ["unknown_account"]


def test_account_repo_must_be_in_card_repos(fixture_repo, repos):
    both = {**repos, "other": Repo(name="other", path=fixture_repo.path, ref="main")}
    card = C.text_meme_card(fixture_repo, account="other:src/app.py")
    assert reasons(check2([card], both)[1]) == ["unknown_account"]


def test_template_account_fields(fixture_repo, repos):
    assert check2([C.template_card(fixture_repo, "group_chat")], repos)[1] == []
    assert check2([C.template_card(fixture_repo, "dating_profile")], repos)[1] == []
    assert check2([C.template_card(fixture_repo, "horoscope")], repos)[1] == []
    assert check2([C.template_card(fixture_repo, "day_in_life")], repos)[1] == []
    bad = C.TEMPLATE_DATA["group_chat"] | {
        "messages": [{"from": "linus", "text": "hi"}, {"from": "greybeard", "text": "yo"}]
    }
    assert reasons(check2([C.template_card(fixture_repo, "group_chat", bad)], repos)[1]) == [
        "unknown_account"
    ]
    bad = C.TEMPLATE_DATA["horoscope"] | {"subject": "fixture:nope.py"}
    assert reasons(check2([C.template_card(fixture_repo, "horoscope", bad)], repos)[1]) == [
        "unknown_account"
    ]


def test_template_account_path_normalized(fixture_repo, repos):
    data = C.TEMPLATE_DATA["dating_profile"] | {"name": "fixture:./src/app.py"}
    accepted, rejected = check2([C.template_card(fixture_repo, "dating_profile", data)], repos)
    assert rejected == []
    assert accepted[0].card["visual"]["data"]["name"] == "fixture:src/app.py"


FAKE_SIGNALS = {
    "churn": {
        "files": {
            "30": [{"path": "a.py", "commits": 2, "lines": 5}],
            "90": [{"path": f"f{i}.py", "commits": i, "lines": 1} for i in range(1, 13)],
        },
        "dirs": {"90": [{"path": "src", "commits": 7, "lines": 9}]},
    },
    "commit_times": {"hour_histogram": list(range(24))},
    "author_shares": {
        "by_dir": {
            "src": [
                {"author": "Alice", "commits": 3, "lines": 9, "share": 0.756},
                {"author": "Bob", "commits": 1, "lines": 3, "share": 0.244},
            ]
        }
    },
    "co_change": [
        {"a": f"a{i}.py", "b": f"b{i}.py", "count": i, "jaccard": 0.5, "same_dir": True}
        for i in range(1, 13)
    ],
}


def fake_signals(repo_name):
    return FAKE_SIGNALS if repo_name == "fixture" else None


def chart_visual(chart, **kw):
    return {"kind": "chart", "chart": chart, "repo": "fixture", "title": "T", **kw}


def chart_resolved(fixture_repo, repos, chart, **kw):
    card = C.chart_card(fixture_repo, chart, visual=chart_visual(chart, **kw))
    accepted, rejected = check2([card], repos, signals_for=fake_signals)
    assert rejected == [], rejected
    return accepted[0].resolved["visual"]


def test_chart_top_churn_files(fixture_repo, repos):
    v = chart_resolved(fixture_repo, repos, "top_churn_files")  # default window 90
    assert v["type"] == "bar" and v["title"] == "T"
    assert len(v["bars"]) == 10
    assert v["bars"][0] == {"label": "f12.py", "value": 12}
    assert v["bars"][-1]["value"] == 3
    v = chart_resolved(fixture_repo, repos, "top_churn_files", window="30")
    assert v["bars"] == [{"label": "a.py", "value": 2}]


def test_chart_top_churn_dirs(fixture_repo, repos):
    v = chart_resolved(fixture_repo, repos, "top_churn_dirs")
    assert v["bars"] == [{"label": "src", "value": 7}]


def test_chart_commit_hours(fixture_repo, repos):
    v = chart_resolved(fixture_repo, repos, "commit_hours")
    assert [b["label"] for b in v["bars"]] == [f"{h:02d}" for h in range(24)]
    assert v["bars"][5]["value"] == 5


def test_chart_author_shares(fixture_repo, repos):
    v = chart_resolved(fixture_repo, repos, "author_shares", dir="src")
    assert v["bars"] == [{"label": "Alice", "value": 76}, {"label": "Bob", "value": 24}]


def test_chart_co_change(fixture_repo, repos):
    v = chart_resolved(fixture_repo, repos, "co_change")
    assert len(v["bars"]) == 10
    assert v["bars"][0] == {"label": "a12.py + b12.py", "value": 12}


def test_chart_no_data(fixture_repo, repos):
    card = C.chart_card(fixture_repo)
    assert reasons(check2([card], repos)[1]) == ["chart_no_data"]  # no signals_for
    assert reasons(check2([card], repos, signals_for=lambda n: None)[1]) == ["chart_no_data"]
    for kind, kw in [
        ("top_churn_files", {"window": "365"}),
        ("author_shares", {"dir": "nope"}),
    ]:
        card = C.chart_card(fixture_repo, kind, visual=chart_visual(kind, **kw))
        assert reasons(check2([card], repos, signals_for=fake_signals)[1]) == ["chart_no_data"]


def test_chart_repo_must_be_in_card_repos(fixture_repo, repos):
    both = {**repos, "other": Repo(name="other", path=fixture_repo.path, ref="main")}
    v = chart_visual("commit_hours") | {"repo": "other"}
    card = C.chart_card(fixture_repo, visual=v, format="chart")
    assert reasons(check2([card], both, signals_for=lambda n: FAKE_SIGNALS)[1]) == [
        "repo_not_in_card"
    ]


def test_null_resolved_visuals(fixture_repo, repos):
    for card in (
        C.text_meme_card(fixture_repo),
        C.diagram_card(fixture_repo),
        C.template_card(fixture_repo, "thread"),
    ):
        accepted, rejected = check2([card], repos)
        assert rejected == [] and accepted[0].resolved["visual"] is None


def test_meme_dot_only_lines_rejected(fixture_repo, repos):
    for line in (".", "..", "..."):
        card = C.meme_card(
            fixture_repo, visual={"kind": "meme", "template": "drake", "lines": ["ok", line]}
        )
        _, rejected = check2([card], repos)
        assert reasons(rejected) == ["meme_lines"]
        assert "only dots" in rejected[0].detail
    ok = C.meme_card(
        fixture_repo, visual={"kind": "meme", "template": "drake", "lines": ["a.b", "v1.2"]}
    )
    assert check2([ok], repos)[1] == []


def test_breaking_news_without_ticker_normalizes_to_empty(fixture_repo, repos):
    card = C.template_card(fixture_repo, "breaking_news", {"headline": "Rounding fixed"})
    accepted, rejected = check2([card], repos)
    assert rejected == []
    assert accepted[0].card["visual"]["data"]["ticker"] == []


def test_comic_over_three_panels_rejected(fixture_repo, repos):
    _, rejected = check2([C.comic_card(fixture_repo, panels=4)], repos)
    assert reasons(rejected) == ["schema"]
