"""Story-first formats: the packet gives allowed formats per card."""

import pytest

from codescroll import brief, slotter, validator
from codescroll.config import Repo
from tests import cards as C
from tests.test_brief import (
    DEFAULTS,
    NO_LEADS,
    all_formats,
    build,
    rule,
    variant,
    variant_leads,
)

GIT_DRAMA = {"categories": {"git_drama": 1.0}, "tones": DEFAULTS["tones"]}


def slots(b):
    """(story_type, allowed formats) per card, over every packet."""
    return [(s, a) for p in b.packets for s, a in zip(p.card_stories, p.allowed, strict=True)]


def test_story_formats_cover_every_story_and_format():
    stories = {t for ts in brief.CATEGORY_STORIES.values() for t in ts} | set(brief.CROSS_STORIES)
    assert stories <= set(brief.STORY_FORMATS)
    for story, fs in brief.STORY_FORMATS.items():
        assert set(fs) <= set(validator.FORMAT_KIND), story
        assert 2 <= len(fs) <= 4 or (story in validator.INTERACTIVE_STORIES and fs == ("quiz",))


def test_packet_gives_story_and_allowed_formats_not_one_per_card():
    b = build(count=20, packet_size=4)
    md = b.to_markdown()
    assert "formats, one per card" not in md
    assert "pick one: " in md and "(preferred)" in md
    for p in b.packets:
        assert len(p.card_stories) == len(p.allowed) == p.count
        assert p.formats == [a[0] for a in p.allowed]
        for story, allowed in zip(p.card_stories, p.allowed, strict=True):
            assert set(allowed) <= set(brief.STORY_FORMATS[story])
            assert len(allowed) == len(set(allowed))


def test_rip_and_hot_spot_never_list_chart_as_the_only_option():
    b = build(count=30, packet_size=5, defaults=GIT_DRAMA)
    assert {"rip", "hot_spot"} <= {s for s, _ in slots(b)}
    for story, allowed in slots(b):
        if story in ("rip", "hot_spot"):
            assert allowed != ["chart"] and len(allowed) >= 2, (story, allowed)


@pytest.mark.parametrize("banned", ["meme", "chart", "text_post", "code_card", "breaking_news"])
def test_banned_format_never_appears_in_any_allowed_list(banned):
    b = build(count=30, packet_size=5, rules=[rule("ban", "format", banned)])
    assert banned not in [f for _, a in slots(b) for f in a]
    assert banned not in all_formats(b)


def test_empty_allowed_list_falls_back_to_a_category_format():
    gone = brief.STORY_FORMATS["rip"]
    rules = [rule("ban", "format", f, id=i) for i, f in enumerate(gone)]
    b = build(count=30, packet_size=5, defaults=GIT_DRAMA, rules=rules)
    rips = [a for s, a in slots(b) if s == "rip"]
    assert rips
    for a in rips:
        assert a and not set(a) & set(gone)
        assert set(a) <= set(brief.CATEGORY_FORMATS["git_drama"])


def test_learned_weight_puts_a_format_first_in_the_allowed_list():
    d = {"categories": {"code": 1.0}, "tones": DEFAULTS["tones"]}
    b = build(count=6, defaults=d, format_weights={"hot_take": 50.0})
    firsts = [a[0] for s, a in slots(b) if s == "cursed_clever_line"]
    assert firsts and "hot_take" in firsts


def test_variant_names_its_exact_format():
    bare = build(count=10, sig=NO_LEADS, variants=[variant()])
    [line] = variant_leads(bare)
    fmt = line.split("in format `")[1].split("`")[0]
    pk = next(p for p in bare.packets if line in p.leads)
    assert [fmt] in pk.allowed
    assert f"use `{fmt}`" in bare.packet_markdown(pk.id)
    i = next(i for i, x in enumerate(pk.leads) if x.startswith("[variant]"))
    assert pk.lead_refs[i]["format"] == fmt and pk.lead_refs[i]["story_type"] == "commit_drama"


def test_packet_says_how_many_cards_should_use_an_image_format():
    d = {**GIT_DRAMA, "visual_mix": {"image_min_share": 0.5}}
    b = build(count=8, packet_size=8, defaults=d)
    for pk in b.packets:
        can = sum(bool(set(a) & brief.IMAGE_FORMATS) for a in pk.allowed)
        assert pk.images == min(-(-pk.count // 2), can)
        if pk.images:
            assert f"at least {pk.images} of the cards" in b.packet_markdown(pk.id)
    assert sum(p.images for p in b.packets) > 0
    d0 = {**GIT_DRAMA, "visual_mix": {"image_min_share": 0}}
    assert sum(p.images for p in build(count=8, packet_size=8, defaults=d0).packets) == 0
    assert "image format" not in build(count=8, packet_size=8, defaults=d0).to_markdown()


def test_every_format_has_a_rhythm_speed():
    for f in validator.FORMAT_KIND:
        assert slotter.format_speed(f, slotter.DEFAULT_KNOBS) in ("fast", "slow"), f


# --- validator ---------------------------------------------------------------------------


@pytest.fixture
def repos(fixture_repo):
    return {"fixture": Repo(name="fixture", path=fixture_repo.path, ref="main")}


def reasons(rejected):
    return [r.reason for r in rejected]


def test_format_must_be_allowed_for_the_story_type(fixture_repo, repos):
    story = "cursed_clever_line"
    assert "hot_take" in brief.STORY_FORMATS[story]
    assert "tier_list" not in brief.STORY_FORMATS[story]
    ok = C.template_card(fixture_repo, "hot_take", story_type=story)
    assert reasons(validator.validate_cards([ok], repos, list(C_PERSONAS))[1]) == []
    bad = C.template_card(fixture_repo, "tier_list", story_type=story)
    [rej] = validator.validate_cards([bad], repos, list(C_PERSONAS))[1]
    assert rej.reason == "format_not_allowed"
    assert all(f in rej.detail for f in brief.STORY_FORMATS[story])
    # A variant names a format outside the list: the run passes it in.
    got = validator.validate_cards(
        [bad], repos, list(C_PERSONAS), variant_formats={(story, "tier_list")}
    )[1]
    assert "format_not_allowed" not in reasons(got)


C_PERSONAS = [
    "greybeard",
    "penny_learns",
    "archivist",
    "meme_compiler",
    "paranoid_sec",
    "shipit_sam",
]
