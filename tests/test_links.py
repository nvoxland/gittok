from dataclasses import replace

import pytest

from gittok import links
from tests.cards import example_card, text_card
from tests.conftest import make_config


@pytest.mark.parametrize(
    "raw, want",
    [
        ("git@github.com:org/name.git", "https://github.com/org/name"),
        ("https://github.com/org/name.git", "https://github.com/org/name"),
        ("https://github.com/org/name", "https://github.com/org/name"),
        ("https://github.com/org/name/", "https://github.com/org/name"),
        ("ssh://git@github.com/org/name.git", "https://github.com/org/name"),
        ("git@gitlab.com:org/name.git", None),
        ("https://example.com/org/name", None),
        ("/some/local/path", None),
        ("", None),
        (None, None),
    ],
)
def test_normalize_github_url(raw, want):
    assert links.normalize_github_url(raw) == want


@pytest.fixture
def cfg(fixture_repo, tmp_path):
    c = make_config(fixture_repo, tmp_path)
    repo = replace(c.repos["fixture"], url="https://github.com/acme/fixture.git")
    return replace(c, repos={"fixture": repo})


def card_of(spec):
    return {**spec, "repo": spec["repos"][0]}


def test_repo_url_is_none_without_config_url_or_remote(fixture_repo, tmp_path):
    c = make_config(fixture_repo, tmp_path)
    assert links.repo_url(c, "fixture") is None  # the fixture repo has no remote
    assert links.repo_url(c, "nope") is None


def test_card_links_for_code_diff_and_sources(cfg, fixture_repo):
    s = fixture_repo.shas
    out = links.card_links(cfg, card_of(example_card(fixture_repo)))
    base = "https://github.com/acme/fixture"
    assert out["repo_url"] == base
    assert out["panels"] == [None, f"{base}/commit/{s['fix1']}"]
    commit_src, path_src = out["sources"]
    assert commit_src == {"label": s["fix1"][:7], "url": f"{base}/commit/{s['fix1']}"}
    # the path source reuses the commit the card cites for that file
    assert path_src["label"] == "billing/invoice.py"
    assert path_src["url"] == f"{base}/blob/{s['invoice_add'][:7]}/billing/invoice.py#L1-L5"


def test_code_panel_links_to_blob_with_lines(cfg, fixture_repo):
    spec = text_card(
        fixture_repo,
        depth=[
            {"kind": "explain", "text": "x"},
            {
                "kind": "code",
                "repo": "fixture",
                "path": "a b.py",
                "commit": "abc1234",
                "lines": [3, 9],
            },
        ],
    )
    out = links.card_links(cfg, card_of(spec))
    assert out["panels"][1] == "https://github.com/acme/fixture/blob/abc1234/a%20b.py#L3-L9"


def test_path_source_uses_branch_ref_when_no_commit_cited(cfg, fixture_repo):
    repo = replace(cfg.repos["fixture"], ref="origin/master")
    cfg = replace(cfg, repos={"fixture": repo})
    spec = text_card(fixture_repo, sources=[{"repo": "fixture", "path": "src/x.py"}])
    out = links.card_links(cfg, card_of(spec))
    assert out["sources"][0]["url"] == "https://github.com/acme/fixture/blob/master/src/x.py"


def test_path_source_without_commit_or_branch_has_no_url(cfg, fixture_repo):
    repo = replace(cfg.repos["fixture"], ref="HEAD")
    cfg = replace(cfg, repos={"fixture": repo})
    spec = text_card(fixture_repo, sources=[{"repo": "fixture", "path": "src/x.py"}])
    out = links.card_links(cfg, card_of(spec))
    assert out["sources"] == [{"label": "src/x.py", "url": None}]


def test_links_are_none_without_a_github_url(fixture_repo, tmp_path):
    c = make_config(fixture_repo, tmp_path)
    assert links.card_links(c, card_of(text_card(fixture_repo))) is None


def test_cross_repo_sources_use_their_own_repo_url(cfg, fixture_repo):
    other = replace(cfg.repos["fixture"], name="other", url="https://github.com/acme/other")
    cfg = replace(cfg, repos={**cfg.repos, "other": other})
    spec = text_card(
        fixture_repo,
        sources=[{"repo": "fixture", "commit": "abc1234"}, {"repo": "other", "commit": "def5678"}],
    )
    out = links.card_links(cfg, card_of(spec))
    assert [s["url"] for s in out["sources"]] == [
        "https://github.com/acme/fixture/commit/abc1234",
        "https://github.com/acme/other/commit/def5678",
    ]


def test_claim_links(cfg, fixture_repo):
    sha = fixture_repo.shas["fix1"]
    base = "https://github.com/acme/fixture"
    claims = [
        {"text": "a b c d", "kind": "interpretive", "source": {"commit": sha[:7]}},
        {"text": "a", "kind": "interpretive", "source": {"pr": f"{base}/pull/3"}},
        {"text": "b", "kind": "interpretive", "source": {"doc": {"path": "a b.md", "line": 4}}},
    ]
    out = links.card_links(cfg, card_of(example_card(fixture_repo, claims=claims)))
    assert out["claims"][0] == f"{base}/commit/{sha[:7]}"
    assert out["claims"][1] == f"{base}/pull/3"
    assert out["claims"][2] == f"{base}/blob/main/a%20b.md#L4"
