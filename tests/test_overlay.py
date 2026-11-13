"""local/ overrides of every shipped config file: the merge rule, warnings, errors, the cache."""

import os
import textwrap
from pathlib import Path

import pytest
import yaml

from gittok import config as config_mod
from gittok import overlay
from gittok.config import ConfigError, load_config

SHIPPED = config_mod.shipped_root() / "config"


def local(home: Path, rel: str, text: str) -> Path:
    p = home / "local" / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(textwrap.dedent(text))
    return p


def shipped(rel: str) -> dict:
    return yaml.safe_load((SHIPPED / rel).read_text())


# --- the merge rule ----------------------------------------------------------------------------


def test_maps_merge_key_by_key_at_every_depth():
    base = {"a": {"x": 1, "y": 2}, "b": 3}
    assert overlay.merge(base, {"a": {"y": 5, "z": 6}}) == {"a": {"x": 1, "y": 5, "z": 6}, "b": 3}
    assert base == {"a": {"x": 1, "y": 2}, "b": 3}  # the shipped value is not changed


def test_a_local_list_adds_its_items_to_the_shipped_list():
    assert overlay.merge({"scan": ["*.py", "*.go"]}, {"scan": ["*.proto", "*.go"]}) == {
        "scan": ["*.py", "*.go", "*.proto"]
    }


def test_a_list_can_remove_items_or_replace_the_shipped_list():
    base = {"scan": ["*.py", "*.go"]}
    assert overlay.merge(base, {"scan": {"$remove": ["*.go"], "$add": ["*.kt"]}}) == {
        "scan": ["*.py", "*.kt"]
    }
    assert overlay.merge(base, {"scan": {"$replace": ["*.kt"]}}) == {"scan": ["*.kt"]}


def test_a_map_can_remove_keys_or_replace_the_shipped_map():
    base = {"templates": {"a": {"lines": 2}, "b": {"lines": 3}}}
    assert overlay.merge(base, {"templates": {"$remove": ["a"], "c": {"lines": 1}}}) == {
        "templates": {"b": {"lines": 3}, "c": {"lines": 1}}
    }
    assert overlay.merge(base, {"templates": {"$replace": True, "c": {"lines": 1}}}) == {
        "templates": {"c": {"lines": 1}}
    }


def test_named_list_items_merge_by_name():
    base = {"patterns": [{"name": "jwt", "regex": "a"}, {"name": "aws", "regex": "b"}]}
    got = overlay.merge(base, {"patterns": [{"name": "aws", "min_length": 9}, {"name": "acme"}]})
    assert got["patterns"] == [
        {"name": "jwt", "regex": "a"},
        {"name": "aws", "regex": "b", "min_length": 9},
        {"name": "acme"},
    ]
    assert overlay.merge(base, {"patterns": {"$remove": ["jwt"]}})["patterns"] == [
        {"name": "aws", "regex": "b"}
    ]


def test_a_scalar_replaces_and_an_empty_value_is_ignored():
    assert overlay.merge({"a": 1, "b": [1]}, {"a": 2, "b": None}) == {"a": 2, "b": [1]}


def test_a_bad_list_form_is_an_error():
    with pytest.raises(ConfigError, match=r"scan.*\$add"):
        overlay.merge({"scan": ["a"]}, {"scan": {"add": ["b"]}})


# --- every file: local adds, local changes, unknown key warns, broken file errors -------------

CASES = {
    # file: (local text, check(data), an unknown key path in the warning)
    "scan_defaults": (
        "scan: ['*.proto']\nkinds: {test: ['**/it/**']}\nzzz: 1\n",
        lambda d: (
            "*.proto" in d["scan"]
            and "*.py" in d["scan"]
            and "**/it/**" in d["kinds"]["test"]
            and "**/tests/**" in d["kinds"]["test"]
        ),
    ),
    "file_types": (
        "highlight: {.zig: rust}\nfile_words: [toml2]\nzzz: 1\n",
        lambda d: (
            d["highlight"][".zig"] == "rust"
            and d["highlight"][".py"] == "python"
            and "toml2" in d["file_words"]
            and "txt" in d["file_words"]
        ),
    ),
    "languages": (
        "thresholds: {long_function: 80}\nlanguages:\n  python:\n    extensions: [.pyi]\n"
        "  zig:\n    extensions: [.zig]\n    func_start: '^fn\\s+(\\w+)'\nzzz: 1\n",
        lambda d: (
            d["thresholds"]["long_function"] == 80
            and d["thresholds"]["deep_nesting"] == 5
            and d["languages"]["python"]["extensions"] == [".py", ".pyi"]
            and d["languages"]["zig"]["func_start"].startswith("^fn")
        ),
    ),
    "queries": (
        "languages:\n  zig:\n    extensions: {.zig: zig}\n    comment: '//'\n"
        "  go: {thresholds: {deep_nesting: 7}}\nzzz: 1\n",
        lambda d: (
            d["languages"]["zig"]["extensions"] == {".zig": "zig"}
            and d["languages"]["go"]["thresholds"]["deep_nesting"] == 7
            and d["languages"]["go"]["comment"] == "//"
        ),
    ),
    "claims": (
        "nilable_words: [undefined]\ntyped_phrases: {returns: ['\\s+yields\\b']}\nzzz: 1\n",
        lambda d: (
            "undefined" in d["nilable_words"]
            and "nil" in d["nilable_words"]
            and len(d["typed_phrases"]["returns"]) == 3
        ),
    ),
    "secrets": (
        "patterns:\n  - {name: acme_key, regex: 'ACME-[A-Z0-9]{12}'}\nzzz: 1\n",
        lambda d: (
            [p["name"] for p in d["patterns"]][-1] == "acme_key"
            and "jwt" in [p["name"] for p in d["patterns"]]
        ),
    ),
    "meme_templates": (
        "templates:\n  mine: {lines: 2, hint: 'my own'}\n  drake: {hint: 'changed'}\nzzz: 1\n",
        lambda d: (
            d["templates"]["mine"]["lines"] == 2
            and d["templates"]["drake"]
            == {**shipped("meme_templates.yaml")["templates"]["drake"], "hint": "changed"}
        ),
    ),  # fmt: skip
    "defaults": (
        "categories: {memes: 0.05}\nvisual_mix: {image_min_share: 0.3}\nzzz: 1\n",
        lambda d: (
            d["categories"]["memes"] == 0.05
            and d["categories"]["code"] == shipped("defaults.yaml")["categories"]["code"]
            and d["visual_mix"]["image_min_share"] == 0.3
        ),
    ),
    "reward": (
        "weights: {like: 0.5}\nskip_ms: 800\nzzz: 1\n",
        lambda d: (
            d["weights"]["like"] == 0.5
            and d["weights"]["save"] == shipped("reward.yaml")["weights"]["save"]
            and d["skip_ms"] == 800
        ),
    ),
    "personas": (
        "personas:\n  greybeard: {voice: Tired.}\nzzz: 1\n",
        lambda d: (
            d["personas"]["greybeard"]["voice"] == "Tired."
            and d["personas"]["greybeard"]["name"] == "Greybeard"
        ),
    ),
}


@pytest.mark.parametrize("name", sorted(CASES))
def test_local_file_adds_and_changes_and_an_unknown_key_only_warns(name, tmp_path):
    text, check = CASES[name]
    spec = overlay.FILES[name]
    local(tmp_path, spec.rel, text)
    got = overlay.load(name, home=tmp_path)
    assert check(got.data), got.data
    assert "zzz" not in got.data
    assert any("'zzz'" in w and f"local/{spec.rel}" in w for w in got.warnings), got.warnings
    assert overlay.load(name, home=None).data == overlay.shipped(name)  # no home: shipped only


@pytest.mark.parametrize("name", sorted(CASES))
def test_broken_local_file_is_a_one_line_error_that_names_the_file(name, tmp_path):
    spec = overlay.FILES[name]
    local(tmp_path, spec.rel, "a: [1, 2\nb: }\n")
    with pytest.raises(ConfigError) as e:
        overlay.load(name, home=tmp_path)
    assert f"local/{spec.rel}" in str(e.value) and "\n" not in str(e.value)
    local(tmp_path, spec.rel, "- just\n- a list\n")
    with pytest.raises(ConfigError, match="must be a mapping") as e:
        overlay.load(name, home=tmp_path)
    assert f"local/{spec.rel}" in str(e.value)


@pytest.mark.parametrize(
    "name, text, word",
    [
        ("languages", "languages: {python: {func_start: '('}}\n", "pattern"),
        ("languages", "languages: {zig: {comment: '//'}}\n", "extensions"),
        ("scan_defaults", "scan: 7\n", "scan"),
        ("scan_defaults", "generated_markers: ['(']\n", "generated_markers"),
        ("file_types", "highlight: [a]\n", "highlight"),
        ("claims", "typed_phrases: {returns: ['(']}\n", "typed_phrases"),
        ("secrets", "patterns: [{name: x, regex: '('}]\n", "x"),
        ("secrets", "patterns: [{name: x}]\n", "regex"),
        ("secrets", "patterns: [{name: x, regex: a, flags: q}]\n", "flags"),
        ("meme_templates", "templates: {mine: {lines: many}}\n", "lines"),
        ("defaults", "categories: {memes: lots}\n", "memes"),
        ("reward", "weights: 3\n", "weights"),
        ("queries", "languages: {zig: {extensions: [.zig]}}\n", "extensions"),
    ],
)
def test_a_bad_value_in_a_local_file_is_an_error_that_names_the_file(name, text, word, tmp_path):
    local(tmp_path, overlay.FILES[name].rel, text)
    with pytest.raises(ConfigError) as e:
        overlay.load(name, home=tmp_path)
    msg = str(e.value)
    assert word in msg and f"local/{overlay.FILES[name].rel}" in msg and "\n" not in msg


def test_unknown_keys_inside_an_entry_and_a_closed_map_warn(tmp_path):
    local(tmp_path, "languages.yaml", "languages: {python: {func_strat: 'x'}}\n")
    got = overlay.load("languages", home=tmp_path)
    assert "func_strat" not in got.data["languages"]["python"]
    assert any("languages.python.func_strat" in w for w in got.warnings)
    local(tmp_path, "reward.yaml", "weights: {lik: 1}\n")
    got = overlay.load("reward", home=tmp_path)
    assert "lik" not in got.data["weights"]
    assert any("weights.lik" in w for w in got.warnings)
    local(tmp_path, "defaults.yaml", "categories: {mems: 1}\n")
    assert any("categories.mems" in w for w in overlay.load("defaults", home=tmp_path).warnings)


def test_shipped_files_load_with_no_warning_and_no_error():
    for name in overlay.FILES:
        if overlay.FILES[name].shipped:
            assert overlay.load(name, home=None).warnings == (), name


# --- secrets: adding is easy, dropping needs an explicit form --------------------------------


def test_local_secrets_cannot_drop_the_shipped_patterns_whole(tmp_path):
    for text in (
        "patterns: {$replace: [{name: mine, regex: 'x{9}'}]}\n",
        "$remove: [patterns]\n",
        "$replace: true\npatterns: [{name: mine, regex: 'x{9}'}]\n",
    ):
        local(tmp_path, "secrets.yaml", text)
        with pytest.raises(ConfigError, match=r"local/secrets.yaml.*\$remove"):
            overlay.load("secrets", home=tmp_path)


def test_turning_a_shipped_secret_pattern_off_or_changing_it_is_explicit_and_warns(tmp_path):
    local(tmp_path, "secrets.yaml", "patterns: {$remove: [jwt]}\n")
    got = overlay.load("secrets", home=tmp_path)
    assert "jwt" not in [p["name"] for p in got.data["patterns"]]
    assert "aws_access_key_id" in [p["name"] for p in got.data["patterns"]]
    assert any("'jwt'" in w and "off" in w and "local/secrets.yaml" in w for w in got.warnings)
    local(tmp_path, "secrets.yaml", "patterns: [{name: jwt, regex: 'nothing-like-a-jwt'}]\n")
    got = overlay.load("secrets", home=tmp_path)
    assert any("'jwt'" in w and "changed" in w for w in got.warnings)


def test_local_secret_pattern_redacts_at_once(tmp_path):
    from gittok import secrets

    local(tmp_path, "gittok.yaml", "")  # only to make local/
    cfg = load_config(tmp_path, shared=config_mod.shipped_root())
    text = "key = ACME-0123456789AB"
    assert secrets.redact(text)[1] == 0
    local(tmp_path, "secrets.yaml", "patterns:\n  - {name: acme, regex: 'ACME-[A-Z0-9]{12}'}\n")
    assert secrets.redact(text) == ("key = <redacted: 17 chars>", 1)
    assert secrets.redact("AKIAABCDEFGHIJKLMNOP")[1] == 1  # the shipped ones still work
    assert cfg.root == tmp_path.resolve()


# --- the cache ---------------------------------------------------------------------------------


def test_a_load_is_cached_until_the_local_file_changes(tmp_path):
    first = overlay.load("defaults", home=tmp_path)
    assert overlay.load("defaults", home=tmp_path) is first
    p = local(tmp_path, "defaults.yaml", "visual_mix: {image_min_share: 0.4}\n")
    second = overlay.load("defaults", home=tmp_path)
    assert second is not first and second.data["visual_mix"]["image_min_share"] == 0.4
    assert overlay.load("defaults", home=tmp_path) is second
    p.write_text("visual_mix: {image_min_share: 0.5}\n")
    os.utime(p, ns=(1, 1))  # same size: the time alone must count
    assert overlay.load("defaults", home=tmp_path).data["visual_mix"]["image_min_share"] == 0.5
    p.unlink()
    assert overlay.load("defaults", home=tmp_path).data == overlay.shipped("defaults")


def test_memo_lives_as_long_as_the_loaded_file(tmp_path):
    calls = []
    a = overlay.load("claims", home=tmp_path)
    assert a.memo("k", lambda d: calls.append(1) or len(d)) == a.memo("k", lambda d: 0)
    assert calls == [1]


# --- load_config ties it together --------------------------------------------------------------


def test_load_config_uses_the_local_files_and_collects_their_warnings(tmp_path):
    local(tmp_path, "defaults.yaml", "visual_mix: {image_min_share: 0.4}\nnope: 1\n")
    local(tmp_path, "scan_defaults.yaml", "scan: ['*.proto']\n")
    local(tmp_path, "meme_templates.yaml", "templates: {mine: {lines: 1, hint: h}}\n")
    local(tmp_path, "languages.yaml", "thresholds: {long_function: 99}\n")
    local(tmp_path, "file_types.yaml", "bogus: 1\n")
    cfg = load_config(tmp_path, shared=config_mod.shipped_root())
    assert cfg.defaults["visual_mix"]["image_min_share"] == 0.4
    assert "*.proto" in cfg.scan_defaults["scan"]
    assert cfg.meme_templates["mine"].hint == "h" and "drake" in cfg.meme_templates
    assert cfg.languages["thresholds"]["long_function"] == 99
    assert any("'nope'" in w and "local/defaults.yaml" in w for w in cfg.warnings)
    assert any("'bogus'" in w and "local/file_types.yaml" in w for w in cfg.warnings)
    assert cfg.fileset("none").reads("api/v1/thing.proto")


def test_load_config_makes_its_home_the_one_the_global_readers_use(tmp_path):
    from gittok import validator

    local(tmp_path, "file_types.yaml", "highlight: {.zig: rust}\n")
    assert validator.language_for("a.zig") is None
    load_config(tmp_path, shared=config_mod.shipped_root())
    assert validator.language_for("a.zig") == "rust"
    assert ".zig" not in config_mod.source_extensions()
    local(tmp_path, "file_types.yaml", "highlight: {.zig: rust}\nsource_extensions: [.zig]\n")
    assert ".zig" in config_mod.source_extensions()  # picked up with no reload


def test_local_reward_file_changes_the_reward_config(tmp_path):
    from gittok import learning

    local(tmp_path, "reward.yaml", "weights: {like: 0.9}\nhalf_life_days: 5\n")
    cfg = load_config(tmp_path, shared=config_mod.shipped_root())
    rc = learning.load_reward_config(cfg)
    assert rc.weights["like"] == 0.9 and rc.half_life_days == 5
    assert rc.weights["save"] == learning.default_reward_config().weights["save"]


def test_local_claims_file_adds_a_typed_phrase(tmp_path):
    from gittok import factcheck

    load_config(tmp_path, shared=config_mod.shipped_root())
    n = len(factcheck._claims()["typed_phrases"]["returns"])
    local(tmp_path, "claims.yaml", "typed_phrases: {returns: ['\\s+yields\\b']}\n")
    assert len(factcheck._claims()["typed_phrases"]["returns"]) == n + 1


# --- queries: a local .scm file and a local language ------------------------------------------


def test_local_query_file_replaces_the_shipped_one_and_adds_a_grammar(tmp_path):
    from gittok import structure

    load_config(tmp_path, shared=config_mod.shipped_root())
    assert (
        structure._shipped_query("python", "python")
        == (SHIPPED / "queries" / "python.scm").read_text()
    )
    local(tmp_path, "queries/python.scm", "(comment) @comment\n")
    local(tmp_path, "queries/zig.scm", "(line_comment) @comment\n")
    local(
        tmp_path,
        "queries/languages.yaml",
        "languages:\n  zig:\n    extensions: {.zig: zig}\n    comment: '//'\n",
    )
    assert structure._shipped_query("python", "python") == "(comment) @comment\n"
    assert structure._shipped_query("zig", "zig") == "(line_comment) @comment\n"
    assert structure.language_for("src/main.zig") == "zig"
    assert structure.language_for("src/main.py") == "python"
    assert ".zig" in config_mod.language_extensions()


def test_local_query_that_does_not_compile_is_reported_by_check(tmp_path):
    from gittok import structure

    if not (structure.available() and structure.ready("python")):
        pytest.skip("the python grammar is not downloaded")
    local(tmp_path, "queries/python.scm", "(no_such_node) @comment\n")
    out = overlay.check(config_mod.shipped_root(), tmp_path)
    assert out["ok"] is False
    assert any("local/queries/python.scm" in e for e in out["errors"])


# --- the registry: what the agent reads --------------------------------------------------------


def test_registry_lists_every_shipped_file_with_its_local_path_and_rule(tmp_path):
    on_disk = {p.name for p in SHIPPED.glob("*.yaml")} | {"queries/languages.yaml"}
    assert {s.rel for s in overlay.FILES.values() if s.shipped} == on_disk
    local(tmp_path, "scan_defaults.yaml", "scan: ['*.proto']\n")
    rows = {r["file"]: r for r in overlay.describe(config_mod.shipped_root(), tmp_path)}
    row = rows["scan_defaults"]
    assert row["local"] == "local/scan_defaults.yaml" and row["local_exists"] is True
    assert row["shipped"] == "config/scan_defaults.yaml"
    assert "add" in row["merge"] and row["takes_effect"] and row["edited_by"]
    assert rows["defaults"]["local_exists"] is False
    assert rows["mascots"]["shipped"] is None and rows["repos"]["shipped"] is None
    assert "queries" in rows and "local/queries/<grammar>.scm" in rows["queries"]["local"]


def test_get_returns_shipped_local_and_effective_for_a_file_or_a_key(tmp_path):
    local(tmp_path, "reward.yaml", "weights: {like: 0.9}\n")
    out = overlay.get(config_mod.shipped_root(), tmp_path, "reward", "weights.like")
    assert out == {
        "file": "reward",
        "key": "weights.like",
        "shipped": shipped("reward.yaml")["weights"]["like"],
        "local": 0.9,
        "effective": 0.9,
        "local_path": "local/reward.yaml",
        "merge": overlay.FILES["reward"].merge,
    }
    whole = overlay.get(config_mod.shipped_root(), tmp_path, "reward")
    assert whole["local"] == {"weights": {"like": 0.9}}
    assert whole["effective"]["weights"]["save"] == whole["shipped"]["weights"]["save"]
    with pytest.raises(ConfigError, match="no key 'weights.nope'"):
        overlay.get(config_mod.shipped_root(), tmp_path, "reward", "weights.nope")
    with pytest.raises(ConfigError, match="unknown config file 'rewards'.*reward"):
        overlay.get(config_mod.shipped_root(), tmp_path, "rewards")


def test_get_masks_nothing_but_keeps_dotted_keys_readable(tmp_path):
    out = overlay.get(config_mod.shipped_root(), tmp_path, "file_types", "highlight/.py")
    assert out["effective"] == "python"


def test_check_reports_errors_and_warnings_of_every_file(tmp_path):
    assert overlay.check(config_mod.shipped_root(), tmp_path) == {
        "ok": True,
        "errors": [],
        "warnings": [],
        "local_files": [],
        "takes_effect": overlay.TAKES_EFFECT,
    }
    local(tmp_path, "defaults.yaml", "nope: 1\n")
    local(tmp_path, "secrets.yaml", "patterns: [{name: x, regex: '('}]\n")
    local(tmp_path, "settings.yaml", "agent: {max_count: 5, zzz: 1}\n")
    out = overlay.check(config_mod.shipped_root(), tmp_path)
    assert out["ok"] is False
    assert len(out["errors"]) == 1 and "local/secrets.yaml" in out["errors"][0]
    assert any("'nope'" in w for w in out["warnings"])
    assert any("agent.zzz" in w for w in out["warnings"])
    assert out["local_files"] == [
        "local/defaults.yaml",
        "local/secrets.yaml",
        "local/settings.yaml",
    ]


@pytest.mark.parametrize("name", ["file_types", "queries", "reward", "scan_defaults"])
@pytest.mark.parametrize("text", ["$replace: true\n", "$remove: [{key}]\n"])
def test_a_local_file_cannot_drop_a_whole_section_of_the_shipped_file(name, text, tmp_path):
    """Code reads the top-level keys of a file: they stay. Removal works inside a key."""
    key = next(iter(overlay.shipped(name)))
    local(tmp_path, overlay.FILES[name].rel, text.format(key=key))
    with pytest.raises(ConfigError, match=r"inside a key.*local/"):
        overlay.load(name, home=tmp_path)


def test_a_local_query_that_no_language_uses_is_reported(tmp_path):
    local(tmp_path, "queries/zig.scm", "(line_comment) @comment\n")
    out = overlay.check(config_mod.shipped_root(), tmp_path)
    assert out["ok"] is False and "local/queries/zig.scm" in out["errors"][0]
    assert "never used" in out["errors"][0]
    local(tmp_path, "queries/languages.yaml", "languages: {zig: {extensions: {.zig: zig}}}\n")
    assert overlay.check(config_mod.shipped_root(), tmp_path)["ok"] is True


def test_a_local_language_and_a_local_query_are_used_by_the_parser(tmp_path):
    from gittok import structure

    if not (structure.available() and structure.ready("python")):
        pytest.skip("the python grammar is not downloaded")
    load_config(tmp_path, shared=config_mod.shipped_root())
    src = "# a note\ndef build():\n    return 1\n"
    assert structure.parse("rules.bzl", src) is None  # no language has this extension
    local(
        tmp_path,
        "queries/languages.yaml",
        "languages:\n  starlark:\n    extensions: {.bzl: python}\n    comment: '#'\n",
    )
    facts = structure.parse("rules.bzl", src)
    assert facts.lang == "starlark" and [d.name for d in facts.defs] == ["build"]
    # A local query replaces the shipped one of its grammar, for every language that uses it.
    local(tmp_path, "queries/python.scm", "(comment) @comment\n")
    facts = structure.parse("rules.bzl", src)
    assert facts.defs == [] and len(facts.comments) == 1
    (tmp_path / "local" / "queries" / "python.scm").unlink()
    assert [d.name for d in structure.parse("a.py", src).defs] == ["build"]
