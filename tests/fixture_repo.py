"""Builds a small, deterministic git repo with known history for tests.

The history is designed so every §10.2 signal has at least one known answer:
co-change pairs, a revert, a fix chain, a late-night commit, a deleted file,
a TODO, a merge, a huge diff, and a commit on a branch that is not merged.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

ALICE = ("Alice Archer", "alice@example.com")
BOB = ("Bob Builder", "bob@example.com")


@dataclass
class FixtureRepo:
    path: Path
    shas: dict[str, str] = field(default_factory=dict)


class _Builder:
    def __init__(self, path: Path):
        self.path = path
        self.env = {
            **os.environ,
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_SYSTEM": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
        }

    def git(self, *args: str, author=ALICE, date: str | None = None) -> str:
        env = dict(self.env)
        env.update(
            GIT_AUTHOR_NAME=author[0],
            GIT_AUTHOR_EMAIL=author[1],
            GIT_COMMITTER_NAME=author[0],
            GIT_COMMITTER_EMAIL=author[1],
        )
        if date:
            env["GIT_AUTHOR_DATE"] = date
            env["GIT_COMMITTER_DATE"] = date
        out = subprocess.run(
            ["git", "-c", "commit.gpgsign=false", "-c", "core.hooksPath=/dev/null", *args],
            cwd=self.path,
            env=env,
            check=True,
            capture_output=True,
            text=True,
        )
        return out.stdout.strip()

    def write(self, rel: str, text: str) -> None:
        p = self.path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)

    def commit(self, msg: str, *, author=ALICE, date: str) -> str:
        self.git("add", "-A")
        self.git("commit", "-q", "-m", msg, author=author, date=date)
        return self.git("rev-parse", "HEAD")


APP_V1 = "def main():\n    print('hello')\n"
UTIL_V1 = (
    "# TODO: replace this parser with something real\ndef parse(s):\n    return s.split(',')\n"
)
INVOICE_V1 = (
    "def total(items):\n"
    "    t = 0\n"
    "    for price in items:\n"
    "        t += price\n"
    "    return round(t)\n"
)


def build_fixture_repo(path: Path) -> FixtureRepo:
    path.mkdir(parents=True, exist_ok=True)
    b = _Builder(path)
    b.git("init", "-q", "-b", "main")
    shas: dict[str, str] = {}

    b.write("README.md", "# Fixture\n")
    b.write("src/app.py", APP_V1)
    b.write("src/util.py", UTIL_V1)
    b.write("src/legacy.py", "def old():\n    return 1\n")
    shas["initial"] = b.commit("Initial commit", date="2026-01-05T10:00:00+00:00")

    b.write("src/app.py", APP_V1 + "\ndef helper():\n    return 2\n")
    b.write("src/util.py", UTIL_V1 + "\ndef join(xs):\n    return ','.join(xs)\n")
    shas["cochange1"] = b.commit(
        "Add helper and join", author=BOB, date="2026-01-10T14:00:00+00:00"
    )

    b.write("src/app.py", APP_V1 + "\ndef helper():\n    return 3\n")
    b.write("src/util.py", UTIL_V1 + "\ndef join(xs):\n    return ', '.join(xs)\n")
    shas["late_night"] = b.commit("Speed up parsing", date="2026-01-12T02:30:00+00:00")

    b.write("billing/invoice.py", INVOICE_V1)
    shas["invoice_add"] = b.commit(
        "Add invoice totals", author=BOB, date="2026-01-15T11:00:00+00:00"
    )

    b.write("billing/invoice.py", INVOICE_V1.replace("round(t)", "round(t, 2)"))
    shas["fix1"] = b.commit("fix rounding in invoice", author=BOB, date="2026-01-16T11:00:00+00:00")

    b.write("billing/invoice.py", INVOICE_V1.replace("round(t)", "round(t + 0.0, 2)"))
    shas["fix2"] = b.commit("fix rounding again", author=BOB, date="2026-01-17T11:00:00+00:00")

    b.write("src/app.py", APP_V1 + "\ndef helper():\n    return 3\n\nFLAG = True\n")
    b.write("src/util.py", UTIL_V1 + "\ndef join(xs):\n    return ', '.join(xs)\n\nFLAG = True\n")
    shas["feature_flag"] = b.commit("Add feature flag", date="2026-01-20T09:00:00+00:00")

    b.git("revert", "--no-edit", "HEAD", date="2026-01-21T09:00:00+00:00")
    shas["revert"] = b.git("rev-parse", "HEAD")

    b.git("rm", "-q", "src/legacy.py")
    shas["delete_legacy"] = b.commit(
        "Remove legacy module, replaced by util", author=BOB, date="2026-01-25T16:00:00+00:00"
    )

    b.git("checkout", "-q", "-b", "feature")
    b.write("src/new_feature.py", "def shiny():\n    return 'new'\n")
    shas["feature_commit"] = b.commit("Add shiny new feature", date="2026-02-01T10:00:00+00:00")
    b.git("checkout", "-q", "main")
    b.git(
        "merge",
        "-q",
        "--no-ff",
        "-m",
        "Merge branch 'feature'",
        "feature",
        date="2026-02-02T10:00:00+00:00",
    )
    shas["merge"] = b.git("rev-parse", "HEAD")

    b.write("data/big.txt", "".join(f"row {i}\n" for i in range(1200)))
    shas["huge"] = b.commit("Import fixtures", author=BOB, date="2026-02-10T12:00:00+00:00")

    b.write("src/app.py", APP_V1 + "\ndef helper():\n    return 4\n")
    b.write("src/util.py", UTIL_V1 + "\ndef join(xs):\n    return '; '.join(xs)\n")
    shas["cochange3"] = b.commit("Tune helper and join", date="2026-02-15T15:00:00+00:00")

    b.write("src/app.py", APP_V1 + "\ndef helper():\n    return 5\n")
    b.write("src/util.py", UTIL_V1 + "\ndef join(xs):\n    return ' | '.join(xs)\n")
    shas["head"] = b.commit(
        "Tweak helper and join again", author=BOB, date="2026-02-20T15:00:00+00:00"
    )

    # A commit that is NOT an ancestor of main.
    b.git("checkout", "-q", "-b", "unmerged", shas["fix1"])
    b.write("billing/experiment.py", "X = 1\n")
    shas["unmerged"] = b.commit("Experiment, never merged", date="2026-02-05T10:00:00+00:00")
    b.git("checkout", "-q", "main")

    return FixtureRepo(path=path, shas=shas)
