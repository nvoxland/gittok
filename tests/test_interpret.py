"""Interpretive claims: why/intent statements cite a source."""

import pytest

from blamescroll import validator
from blamescroll.config import AgentSettings, Repo
from tests.cards import example_card
from tests.test_validator import PERSONAS

WHY = (
    "The code in question is `round(t)`, and it does one small job here for every caller.\n\n"
    "It rounds the total because the old float sum drifted by a cent on large invoices. "
    "Callers add up the prices first and then hand the whole sum to it in one single call."
)


@pytest.fixture
def repos(fixture_repo):
    return {
        "fixture": Repo(
            name="fixture",
            path=fixture_repo.path,
            ref="main",
            url="https://github.com/acme/fixture",
        )
    }


def run(card, repos, strict=False):
    return validator.validate_cards(
        [card], repos, PERSONAS, require_claim_sources=strict, claim_checks=False
    )


def card_with(fixture_repo, claims=None, text=None):
    kw = {"claims": claims} if claims is not None else {}
    if text:
        kw["depth"] = [
            {"kind": "explain", "text": text},
            {
                "kind": "code_diff",
                "repo": "fixture",
                "commit": fixture_repo.shas["fix1"],
                "path": "billing/invoice.py",
            },
        ]
    return example_card(fixture_repo, **kw)


def claim(text, **src):
    return {"text": text, "kind": "interpretive", "source": src}


def test_setting_defaults_lenient():
    assert AgentSettings().require_claim_sources is False


def test_commit_claim_overlapping_message_passes(fixture_repo, repos):
    s = fixture_repo.shas["delete_legacy"]
    c = card_with(
        fixture_repo,
        [claim("The author says: Remove legacy module, replaced by util", commit=s[:7])],
    )
    acc, rej = run(c, repos, strict=True)
    assert rej == [] and acc[0].warnings == []


def test_commit_claim_quoting_message_passes(fixture_repo, repos):
    s = fixture_repo.shas["fix2"]
    c = card_with(fixture_repo, [claim('It was "fix rounding again" for a second time', commit=s)])
    assert run(c, repos, strict=True)[1] == []


def test_commit_claim_not_in_message_rejected_when_strict(fixture_repo, repos):
    s = fixture_repo.shas["fix1"]
    c = card_with(
        fixture_repo, [claim("The team wanted to cut latency in every service", commit=s)]
    )
    acc, rej = run(c, repos, strict=True)
    assert acc == [] and rej[0].reason == "claim_unsourced"


def test_commit_claim_not_in_message_warns_when_lenient(fixture_repo, repos):
    s = fixture_repo.shas["fix1"]
    c = card_with(
        fixture_repo, [claim("The team wanted to cut latency in every service", commit=s)]
    )
    acc, rej = run(c, repos)
    assert rej == [] and any("claim_unsourced" in w for w in acc[0].warnings)


def test_unknown_commit_always_rejected(fixture_repo, repos):
    c = card_with(fixture_repo, [claim("anything at all here", commit="deadbeef")])
    assert run(c, repos)[1][0].reason == "unknown_commit"


def test_comment_source_must_be_a_comment_line(fixture_repo, repos):
    src = {"path": "src/util.py", "line": 1}
    ok = card_with(fixture_repo, [claim("The parser is a placeholder", comment=src)])
    assert run(ok, repos, strict=True)[1] == []
    src = {"path": "src/util.py", "line": 2}
    bad = card_with(fixture_repo, [claim("The parser is a placeholder", comment=src)])
    assert run(bad, repos, strict=True)[1][0].reason == "claim_unsourced"
    assert run(bad, repos)[0][0].warnings


def test_comment_line_past_end_or_missing_file_rejected(fixture_repo, repos):
    src = {"path": "src/util.py", "line": 99}
    far = card_with(fixture_repo, [claim("x is here", comment=src)])
    assert run(far, repos)[1][0].reason == "claim_source_missing"
    gone = card_with(fixture_repo, [claim("x is here", doc={"path": "nope.md", "line": 1})])
    assert run(gone, repos)[1][0].reason == "path_not_at_commit"


def test_pr_url_must_match_repo(fixture_repo, repos):
    url = "https://github.com/acme/fixture/pull/12"
    ok = card_with(fixture_repo, [claim("Merged to stop drift", pr=url)])
    assert run(ok, repos, strict=True)[1] == []
    other = "https://github.com/other/thing/pull/12"
    bad = card_with(fixture_repo, [claim("Merged to stop drift", pr=other)])
    assert run(bad, repos)[1][0].reason == "claim_source_missing"


def test_why_sentence_without_claim_flagged(fixture_repo, repos):
    c = card_with(fixture_repo, text=WHY)
    acc, rej = run(c, repos)
    assert rej == [] and any("claim_unsourced" in w and "because" in w for w in acc[0].warnings)
    assert run(c, repos, strict=True)[1][0].reason == "claim_unsourced"


def test_why_sentence_backed_by_overlapping_claim_passes(fixture_repo, repos):
    s = fixture_repo.shas["fix1"]
    c = card_with(
        fixture_repo,
        [claim("fix rounding in invoice because the old float sum drifted by a cent", commit=s)],
        text=WHY,
    )
    acc, rej = run(c, repos, strict=True)
    assert rej == [] and acc[0].warnings == []


def test_plain_explain_has_no_warnings(fixture_repo, repos):
    acc, rej = run(card_with(fixture_repo), repos, strict=True)
    assert rej == [] and acc[0].warnings == []
