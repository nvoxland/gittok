"""Secret redaction: detector, outputs that leave the server, cards, miners."""

from __future__ import annotations

import json
from dataclasses import replace
from types import SimpleNamespace

import pytest
from mcp import Client

from gittok import (
    candidates,
    db,
    feed,
    gitq,
    materials,
    mcp_server,
    research,
    secrets,
    validator,
)
from gittok.brief import Lead
from gittok.config import AnalysisSettings, Repo, ResearchSettings
from tests.cards import example_card, explain
from tests.conftest import make_config
from tests.fixture_repo import build_history_repo
from tests.test_mcp_e2e import data
from tests.test_validator import PERSONAS

JWT = (
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
    "eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4ifQ."
    "SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"
)
AWS = "AKIAIOSFODNN7EXAMPLE"
PEM = [
    "-----BEGIN RSA PRIVATE KEY-----",
    "MIIEowIBAAKCAQEA3Tz2mr7SZiAMfQyuvBjM9Oi8vFVkQ1eM0pYhJ0dZ",
    "x8nQwP4o2LrT7bB5fWc9GhJkLmNpQrStUvWxYz0123456789abcdefgh",
    "-----END RSA PRIVATE KEY-----",
]
CREDS = "\n".join(
    [
        "# HACK: dev credentials, replace before shipping",
        "import os",
        "",
        f'CONFIG = {{:aws-eks-token "{JWT}"}}',
        f'AWS_ID = "{AWS}"',
        "KEY = '''",
        *PEM,
        "'''",
        'SHA = "0123456789abcdef0123456789abcdef01234567"',
        "def load_keys():",
        "    return CONFIG",
        "",
    ]
)
NLINES = len(CREDS.splitlines())


@pytest.fixture
def repo(tmp_path):
    return build_history_repo(
        tmp_path / "r",
        [("add creds", {"app/creds.py": CREDS}, "2026-01-05T10:00:00+00:00")],
    )


@pytest.fixture
def cfg(repo, tmp_path):
    return make_config(repo, tmp_path / "cs")


def clean(text: str):
    assert "<redacted" in text
    for s in (JWT, AWS, PEM[1], PEM[2], "eyJhbGci", "AKIAIOSF"):
        assert s not in text


# ---- detector


def test_detects_the_documented_kinds():
    samples = {
        "jwt": JWT,
        "aws": AWS,
        "stripe": "sk_live_" + "a1B2c3D4e5F6g7H8",
        "github": "ghp_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8",
        "slack": "xoxb-" + "1234567890-abcdefghij",
        "google": "AIza" + "SyA1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q",
    }
    for name, s in samples.items():
        assert secrets.find(f"x = {s}\n"), name


def test_redact_keeps_key_and_quotes_and_reports_length():
    out, n = secrets.redact(f'  :aws-eks-token "{JWT}"\n')
    assert n == 1
    assert out == f'  :aws-eks-token "<redacted: {len(JWT)} chars>"\n'


def test_assignment_needs_key_name_length_and_entropy():
    hi = "Zx9Qp3Lm7Vb2Nc8Rt4Wy6Ka1"  # 25 chars, high entropy
    assert secrets.find(f'password = "{hi}"')
    assert secrets.find(f'{{"api_key": "{hi}"}}')
    assert secrets.find(f"api-key: '{hi}'")
    assert not secrets.find(f'username = "{hi}"')  # key name does not match
    assert not secrets.find('password = "short"')
    assert not secrets.find(f'password = "{"a" * 30}"')  # low entropy
    assert not secrets.find('token_error = "Invalid token supplied by the client"')  # spaces


def test_negatives_sha_lockfile_base64_fixture():
    sha = "0123456789abcdef0123456789abcdef01234567"
    assert secrets.redact(f"commit {sha}\nfixes {sha[:7]}")[1] == 0
    assert secrets.find(f'SHA = "{sha}"') == []
    assert secrets.find(f'"integrity": "sha512-{"Ab3/+xY9" * 12}=="') == []
    assert secrets.find('token = "dGVzdA=="') == []  # base64 fixture under 20 chars
    assert secrets.find("eyJ is just a prefix") == []


def test_pem_block_keeps_line_count():
    text = "a\n" + "\n".join(PEM) + "\nb\n"
    out, n = secrets.redact(text)
    assert n == 1
    assert out.count("\n") == text.count("\n")
    assert out.splitlines()[0] == "a" and out.splitlines()[-1] == "b"
    assert "MIIE" not in out and "END RSA" not in out


def test_pem_cut_inside_the_block_runs_to_the_end():
    text = "\n".join(PEM[:3]) + "\n"
    out, _ = secrets.redact(text)
    assert out.count("\n") == text.count("\n") and "MIIE" not in out


def test_redact_is_idempotent_and_keeps_line_prefixes():
    numbered = "\n".join(f"{i}\t{ln}" for i, ln in enumerate(PEM, 5))
    out, _ = secrets.redact(numbered)
    assert [ln.split("\t")[0] for ln in out.splitlines()][1:] == ["6", "7", "8"]
    assert secrets.redact(out) == (out, 0)


# ---- research outputs


def test_read_file_redacts_and_keeps_line_numbers(cfg):
    out = research.read_file(cfg, "fixture", "app/creds.py")
    clean(out)
    assert len(out.splitlines()) == NLINES
    assert out.splitlines()[-1].startswith(f"{NLINES}\t")
    assert "0123456789abcdef0123456789abcdef01234567" in out  # a sha stays


def test_read_file_window_cut_inside_pem(cfg):
    out = research.read_file(cfg, "fixture", "app/creds.py", lines=[8, 9])
    assert "MIIE" not in out and len(out.splitlines()) == 2


def test_git_show_log_grep_blame_redact(repo, cfg):
    sha = repo.shas["0"]
    clean(research.git_show(cfg, "fixture", sha))
    clean(research.git_grep(cfg, "fixture", "AKIA|eyJ|PRIVATE"))
    assert "eyJ" not in research.git_grep(cfg, "fixture", "eyJ")
    clean(research.git_blame(cfg, "fixture", "app/creds.py"))


def test_git_log_body_is_redacted(tmp_path):
    r = build_history_repo(
        tmp_path / "r2",
        [(f"rotate key {AWS}", {"a.py": "x = 1\n"}, "2026-01-05T10:00:00+00:00")],
    )
    c = make_config(r, tmp_path / "cs2")
    out = research.git_log(c, "fixture")
    assert AWS not in out and "<redacted" in out


def test_setting_off_returns_text_as_is(repo, tmp_path):
    c = make_config(repo, tmp_path / "cs3")
    c = replace(c, settings=replace(c.settings, research=ResearchSettings(redact_secrets=False)))
    assert AWS in research.read_file(c, "fixture", "app/creds.py")


def test_shipped_setting_defaults_to_true(cfg):
    assert cfg.settings.research.redact_secrets is True


# ---- materials, scout, profiling


def lead(**kw):
    return Lead(**{"story_type": "x", "repo": "fixture", "kind": "none", **kw}).__dict__


def test_materials_redact_path_and_commit(repo, cfg):
    clean(materials.materials_for(cfg, lead(kind="path", path="app/creds.py")))
    clean(materials.materials_for(cfg, lead(kind="commit", commit=repo.shas["0"])))


@pytest.mark.anyio
async def test_get_candidates_windows_are_redacted(cfg):
    async with Client(mcp_server.build_server(lambda: cfg)) as client:
        st = data(await client.call_tool("scout_status", {}))
        got = data(await client.call_tool("get_candidates", {"batch_id": st["batches"][0]["id"]}))
    texts = [c["text"] for c in got["candidates"]]
    assert texts
    for t in texts:
        assert JWT not in t and AWS not in t and "MIIE" not in t
    assert any("<redacted" in t for t in texts)


@pytest.mark.anyio
async def test_test_detector_samples_are_redacted(cfg):
    rule = {
        "id": "creds",
        "tag": "creds",
        "weight": 1,
        "match": {"regex": "BEGIN RSA|AWS_ID|CONFIG", "paths": ["app/**"]},
    }
    async with Client(mcp_server.build_server(lambda: cfg)) as client:
        out = data(await client.call_tool("test_detector", {"repo": "fixture", "rule": rule}))
    assert out["hits"] >= 1
    text = "\n".join(s["text"] for s in out["samples"])
    clean(text)


def test_survey_text_is_redacted(cfg):
    from gittok import profiling

    out = profiling._redact_survey(cfg, {"profile": {"yaml": f"x: {AWS}"}, "files": 3})
    assert AWS not in json.dumps(out) and out["files"] == 3


# ---- cards


def card_on_creds(repo, **kw):
    ref = {"repo": "fixture", "path": "app/creds.py", "commit": repo.shas["0"]}
    card = example_card(
        SimpleNamespace(shas={"invoice_add": repo.shas["0"], "fix1": repo.shas["0"]}),
        dirs=["app"],
        visual={**ref, "kind": "code", "lines": [4, 5]},
        depth=[
            {"kind": "explain", "text": explain("load_keys")},
            {"kind": "code", **ref, "lines": [6, 9]},
        ],
        comments=[],
        sources=[{"repo": "fixture", "path": "app/creds.py", "lines": [4, 5]}],
        **kw,
    )
    return card


def validate(cards, repo, **kw):
    repos = {"fixture": Repo(name="fixture", path=repo.path, ref="main")}
    return validator.validate_cards(cards, repos, PERSONAS, claim_checks=False, **kw)


def test_resolved_code_is_stored_redacted(repo):
    accepted, rejected = validate([card_on_creds(repo)], repo)
    assert rejected == []
    r = accepted[0].resolved
    clean(r["visual"]["code"] + r["depth"][1]["code"])
    assert len(r["depth"][1]["code"].splitlines()) == 4
    assert "<redacted" in r["visual"]["code"]


def test_excerpt_of_redacted_view_is_accepted(repo):
    card = card_on_creds(repo)
    _, rejected = validate([card], repo)
    shown = research.read_file(
        make_config(repo, repo.path.parent / "cs4"), "fixture", "app/creds.py", lines=[4, 5]
    )
    card["visual"]["excerpt"] = "\n".join(ln.split("\t", 1)[1] for ln in shown.splitlines())
    accepted, rejected = validate([card], repo)
    assert rejected == [] and accepted


def test_code_diff_is_stored_redacted(repo):
    card = card_on_creds(repo)
    card["depth"][1] = {
        "kind": "code_diff",
        "repo": "fixture",
        "commit": repo.shas["0"],
        "path": "app/creds.py",
    }
    accepted, rejected = validate([card], repo)
    assert rejected == []
    diff = accepted[0].resolved["depth"][1]["diff"]
    assert JWT not in diff and AWS not in diff and "MIIE" not in diff and "<redacted" in diff


def test_served_card_redacts_old_stored_resolved(repo):
    class Row(dict):
        pass

    row = Row(
        id="c_1",
        created_at="x",
        spec=db.dumps({"repos": ["fixture"], "hook": "h"}),
        resolved=db.dumps({"visual": {"code": f'k = "{AWS}"'}, "depth": []}),
    )
    out = feed.public_card(row)
    assert AWS not in json.dumps(out)


@pytest.mark.parametrize("where", ["hook", "learn", "explain", "comment", "callout"])
def test_prose_with_a_secret_is_rejected(repo, where):
    card = card_on_creds(repo)
    leak = f"the key is {AWS} here"
    if where == "hook":
        card["hook"] = leak
    elif where == "learn":
        card["learn"] = leak
    elif where == "explain":
        card["depth"][0]["text"] += "\n\n" + leak
    elif where == "comment":
        card["comments"] = [{"persona": "greybeard", "text": leak}]
    else:
        card["visual"]["callouts"] = [{"line": 5, "text": leak}]
    accepted, rejected = validate([card], repo)
    assert accepted == [] and [r.reason for r in rejected] == ["secret_in_card"]


def test_prose_check_off_when_setting_off(repo):
    card = card_on_creds(repo)
    card["hook"] = f"the key is {AWS}"
    accepted, _ = validate([card], repo, redact_secrets=False)
    assert accepted


def test_prose_with_a_sha_is_fine(repo):
    card = card_on_creds(repo)
    card["hook"] = "Commit 0123456789abcdef0123456789abcdef01234567 added it."
    accepted, rejected = validate([card], repo)
    assert [r.reason for r in rejected] != ["secret_in_card"]


# ---- miners


def test_long_line_skips_a_secret_line_but_keeps_a_real_one(tmp_path):
    secret_line = f'TOKEN = "{JWT}" + "{JWT}"\n'
    long_line = "y = '" + "a" * 200 + "'\n"
    r = build_history_repo(
        tmp_path / "m",
        [("one", {"m.py": f"x = 1\n{secret_line}{long_line}"}, "2026-01-01T10:00:00+00:00")],
    )
    t0 = gitq.commit_time(r.path, "main")
    out = candidates.mine(r.path, "main", t0, {}, AnalysisSettings())
    whys = [c["why"] for c in out if c["tag"] == "long_line"]
    assert whys == ["line 3 is 206 characters long"]


def test_big_literal_skips_a_pem_literal(tmp_path):
    inner = [f"    {ln}," for ln in PEM[1:3]] * 20
    pem_literal = "KEYS = [\n" + "\n".join(inner) + "\n]\n"
    plain = "NAMES = [\n" + "\n".join(f"    'n{i}'," for i in range(40)) + "\n]\n"
    secret_lines = "KEYS = [\n" + "\n".join(f'    "{JWT}",' for _ in range(40)) + "\n]\n"
    r = build_history_repo(
        tmp_path / "m2",
        [
            (
                "one",
                {"a.py": plain, "b.py": secret_lines, "c.py": pem_literal},
                "2026-01-01T10:00:00+00:00",
            )
        ],
    )
    t0 = gitq.commit_time(r.path, "main")
    out = candidates.mine(r.path, "main", t0, {}, AnalysisSettings())
    paths = {c["path"] for c in out if c["tag"] == "big_literal"}
    assert "a.py" in paths and "b.py" not in paths
