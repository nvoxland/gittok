"""'Called from' and 'Defines' with the structure layer."""

import pytest

from blamescroll import materials, structure
from tests.conftest import make_config
from tests.fixture_repo import build_history_repo
from tests.test_materials import _ref

needs = pytest.mark.skipif(
    not (structure.available() and structure.ready("python") and structure.ready("go")),
    reason="needs tree-sitter grammars (structure --prefetch)",
)

FILES = {
    "lib/tax.py": "def compute_tax(x):\n    return x * 2\n",
    "a.py": "from lib.tax import compute_tax\nprint(compute_tax(1))\n",
    "b.py": "# compute_tax(2) is slow\nS = 'compute_tax(3)'\n",
    "util/util.go": "package util\n\nfunc Helper() int { return 1 }\n",
    "cmd/main.go": (
        'package main\n\nimport "example.com/app/util"\n\n// Helper is used\n'
        "func main() { util.Helper() }\n"
    ),
}


@pytest.fixture
def cfg(tmp_path):
    fr = build_history_repo(tmp_path / "r", [("tax", FILES, "2026-01-05T10:00:00+00:00")])
    return make_config(fr, tmp_path)


def called(cfg, path):
    text = materials.materials_for(cfg, _ref(story_type="what_it_does", kind="path", path=path))
    return text, text.split("Called from:")[1].split("\n\n")[0] if "Called from:" in text else ""


@needs
def test_called_from_drops_hits_in_comments_and_strings(cfg):
    _, section = called(cfg, "lib/tax.py")
    assert "a.py:2" in section and "b.py" not in section


def test_called_from_without_the_layer_uses_every_grep_hit(cfg, monkeypatch):
    monkeypatch.setattr(structure, "available", lambda: False)
    _, section = called(cfg, "lib/tax.py")
    assert "a.py:2" in section and "b.py:1" in section and "b.py:2" in section


@needs
def test_a_language_with_only_a_query_gets_defines_callers_and_imports(cfg):
    text, section = called(cfg, "util/util.go")
    assert "Defines:" in text and "Helper" in text.split("Defines:")[1].split("\n\n")[0]
    assert "cmd/main.go:6" in section and "cmd/main.go:5" not in section  # the comment is skipped
    assert "util/util.go" not in section
    cmd, _ = called(cfg, "cmd/main.go")
    assert "Imports:" in cmd and "example.com/app/util" in cmd
