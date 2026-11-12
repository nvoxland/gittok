import copy

import pytest

from gittok import validator
from tests.cards import example_card, text_card

PERSONAS = ["greybeard", "penny_learns", "archivist", "meme_compiler", "paranoid_sec", "shipit_sam"]


def errors(card):
    return validator.schema_errors(card, PERSONAS)


def test_example_card_passes_schema(fixture_repo):
    assert errors(example_card(fixture_repo)) == []


def test_learn_is_required_and_bounded(fixture_repo):
    card = example_card(fixture_repo)
    del card["learn"]
    assert errors(card)
    assert errors(example_card(fixture_repo, learn="too short"))
    assert errors(example_card(fixture_repo, learn="x" * 141))


def test_text_card_passes_schema(fixture_repo):
    assert errors(text_card(fixture_repo)) == []


def test_unknown_story_type_rejected(fixture_repo):
    errs = errors(example_card(fixture_repo, story_type="mystery"))
    assert errs and "story_type" in errs[0]


def test_unknown_persona_rejected(fixture_repo):
    assert errors(example_card(fixture_repo, persona="linus"))


def test_comment_persona_must_be_known(fixture_repo):
    card = example_card(fixture_repo, comments=[{"persona": "Real Person", "text": "hi"}])
    assert errors(card)


def test_additional_properties_rejected(fixture_repo):
    card = example_card(fixture_repo)
    card["visual"]["secret"] = 1
    assert errors(card)


@pytest.mark.parametrize("kind", ["meme", "illustration", "chart", "diagram", "template"])
def test_m2_visual_kinds_not_yet_allowed(fixture_repo, kind):
    assert errors(example_card(fixture_repo, visual={"kind": kind}))


def test_depth_required_and_bounded(fixture_repo):
    assert errors(example_card(fixture_repo, depth=[]))
    five = [{"kind": "explain", "text": "x"}] * 5
    assert errors(example_card(fixture_repo, depth=five))


def test_lines_must_be_pair_of_positive_ints(fixture_repo):
    card = example_card(fixture_repo)
    bad = copy.deepcopy(card)
    bad["visual"]["lines"] = [0, 3]
    assert errors(bad)
    bad["visual"]["lines"] = [1, 2, 3]
    assert errors(bad)


def test_commit_must_look_like_sha(fixture_repo):
    card = example_card(fixture_repo)
    card["visual"]["commit"] = "HEAD~1"
    assert errors(card)


def test_series_is_null_or_key_part_of(fixture_repo):
    assert errors(example_card(fixture_repo, series=None)) == []
    ok = {"key": "retry-saga", "part": 2, "of": 3}
    assert errors(example_card(fixture_repo, series=ok)) == []
    bad = [
        {"key": "x", "part": 3, "of": 2},
        {"key": "x", "part": 0, "of": 2},
        {"key": "x", "part": 1, "of": 6},
        {"key": "x", "part": 1},
        {"key": "", "part": 1, "of": 2},
        {"key": "x", "part": 1, "of": 2, "extra": 1},
    ]
    for s in bad:
        assert errors(example_card(fixture_repo, series=s)), s


def test_comment_spoiler_flag_is_optional_boolean(fixture_repo):
    good = [{"persona": "greybeard", "text": "hi", "spoiler": False}]
    assert errors(example_card(fixture_repo, comments=good)) == []
    bad = [{"persona": "greybeard", "text": "hi", "spoiler": "no"}]
    assert errors(example_card(fixture_repo, comments=bad))


def test_schema_document_wraps_cards(fixture_repo):
    doc = validator.card_schema(PERSONAS)
    assert doc["type"] == "object"
    assert doc["properties"]["cards"]["items"] == {"$ref": "#/$defs/card"}


def test_new_kinds_pass_schema(fixture_repo):
    from tests import cards as c

    for card in [
        c.meme_card(fixture_repo),
        c.text_meme_card(fixture_repo),
        c.illustration_card(fixture_repo),
        c.comic_card(fixture_repo),
        c.chart_card(fixture_repo),
        c.diagram_card(fixture_repo),
        *[c.template_card(fixture_repo, t) for t in c.TEMPLATE_DATA],
    ]:
        assert errors(card) == [], card["format"]


def test_new_kind_schema_limits(fixture_repo):
    from tests import cards as c

    bad = [
        c.template_card(fixture_repo, "thread", {"posts": ["only one"]}),
        c.template_card(fixture_repo, "flags", {"subject": "x", "red": [], "green": []}),
        c.template_card(fixture_repo, "hot_take", {"take": "x", "extra": 1}),
        c.template_card(
            fixture_repo, "tier_list", {"title": "t", "rows": [{"tier": "Z", "items": []}] * 2}
        ),
        c.comic_card(fixture_repo, panels=1),
        c.meme_card(fixture_repo, visual={"kind": "meme", "template": "d", "lines": ["x"] * 5}),
        c.text_meme_card(
            fixture_repo, visual={"kind": "text_meme", "style": "nope", "lines": ["x"]}
        ),
        c.chart_card(
            fixture_repo,
            "author_shares",
            visual={"kind": "chart", "chart": "author_shares", "repo": "fixture"},
        ),
        c.illustration_card(fixture_repo, account="no-colon"),
        c.illustration_card(
            fixture_repo, visual={"kind": "illustration", "prompt": "x" * 401, "caption": "c"}
        ),
    ]
    for card in bad:
        assert errors(card), card["visual"]
    assert errors(c.illustration_card(fixture_repo, account="fixture:src/app.py")) == []


INTERACTIVE = [
    "spot_the_bug_card",
    "guess_who_card",
    "guess_when_card",
    "quiz_card",
    "this_or_that_card",
]


def _builder(name):
    from tests import cards

    return getattr(cards, name)


@pytest.mark.parametrize("name", INTERACTIVE)
def test_interactive_cards_pass_schema(fixture_repo, name):
    assert errors(_builder(name)(fixture_repo)) == []


def _quiz(fixture_repo):
    return _builder("quiz_card")(fixture_repo)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda i: i.update(choices=["only one"]),
        lambda i: i.update(choices=list("abcde")),
        lambda i: i.update(choices=["x" * 121, "y"]),
        lambda i: i.update(question="q" * 201),
        lambda i: i.update(explanation="e" * 401),
        lambda i: i.update(answer_index=-1),
        lambda i: i.pop("question"),
        lambda i: i.pop("explanation"),
        lambda i: i.update(extra=1),
    ],
)
def test_interaction_limits(fixture_repo, mutate):
    card = _quiz(fixture_repo)
    mutate(card["interaction"])
    assert errors(card)


def test_quiz_allows_code_and_text_visuals_only_in_schema(fixture_repo):
    card = _builder("guess_who_card")(fixture_repo)
    assert errors(card) == []
    card["format"] = "quiz"
    card["visual"] = {"kind": "meme", "template": "drake", "lines": ["a"]}
    assert errors(card) == []  # kind/format pairing is a validator rule (format_kind_mismatch)


def test_cross_repo_story_types_pass_schema():
    from tests.cards import cross_card

    for t in ("weekly_recap", "drift_alert", "ripple"):
        assert errors(cross_card("a" * 40, "b" * 40, story_type=t)) == [], t


def test_verdict_is_optional_and_limited_to_scout_verdicts(fixture_repo):
    from gittok.scout import VERDICTS

    for v in VERDICTS:
        assert errors(example_card(fixture_repo, verdict=v)) == []
    assert errors(example_card(fixture_repo, verdict="meh"))
