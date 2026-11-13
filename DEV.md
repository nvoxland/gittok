# Developing GitTok

This file is for people who change and test GitTok. To use GitTok, read the docs site: <https://nvoxland.github.io/gittok/> (its source is `docs/`, see "Documentation site" below).

- [AGENTS.md](AGENTS.md): the architecture, the conventions, and the rules for coding agents.
- [SPEC.md](SPEC.md): the design. What a card is, and how the parts fit.

## Set up a clone

You need macOS, [uv](https://docs.astral.sh/uv/), git, Node 22, and Claude Code.

```bash
git clone <this-repo-url> gittok
cd gittok
uv sync --group images                                   # Python 3.13, the dependencies, and mflux
npm --prefix web install && npm --prefix web run build   # the web app, into web/build
```

The `images` group installs mflux (Apple silicon, a large download). GitTok uses it for illustration and comic cards, and for the persona avatars. Always pass `--group images` to `uv sync`: a plain `uv sync` removes the group again.

To work without mflux, use a plain `uv sync` instead:

```bash
uv sync                                                  # Python 3.13 and the dependencies, no mflux
```

Without mflux, GitTok makes no illustration or comic cards and no avatars. Everything else works.

## Run from the clone

Start Claude Code in the clone:

```bash
claude
```

The project `.mcp.json` makes Claude Code start `uv run gittok mcp --ui`. Approve the `gittok` MCP server when Claude Code asks. That process is the MCP server (stdio). It also starts a child `gittok serve --reload` that serves the feed on port 7313 while the session runs (an installed tool starts the child without `--reload`). The child restarts when a file in `src/gittok/` changes. A change to the MCP tools themselves needs `/mcp`, gittok, Reconnect.

A clone is its own GitTok directory: your repo list and settings are in `local/`, the database is in `data/`, and clones of repos added by URL are in `repos/`. All three are in `.gitignore`. `GITTOK_ROOT=<dir>` makes a `gittok` command in any directory use that clone or GitTok directory. It is the only such variable.

Then use GitTok as the docs site says: ask Claude to add a repo, profile it, make cards, and pair a phone. The project `.claude/settings.json` has the two SessionStart hooks (`docs/scheduling.md`).

Commands that help during development (`uv run gittok --help` lists all):

```bash
uv run gittok serve                  # the feed server by hand, without a session (:7313, no MCP)
uv run gittok serve --no-lan         # the same, for this computer only
uv run gittok repos add <name> <path-or-url>
uv run gittok structure --prefetch   # download the tree-sitter grammars (once, needs network)
uv run gittok brief                  # print the brief without opening a run
uv run gittok health                 # feed health as JSON
uv run gittok render                 # one render pass
uv run gittok init /tmp/gittok-try   # make a GitTok directory with the code of the clone
```

If port 7313 is in use (another session, or a `gittok serve` that you started), `gittok mcp --ui` runs MCP only and tells Claude which directory has the port.

A directory from `uv run gittok init` has a `.mcp.json` that runs the `gittok` on your PATH, not the clone. To try the clone's code in such a directory, install the clone as the tool first (`uv tool install --editable .`), or build and install the wheel (below).

## Test and lint

```bash
uv run pytest                 # unit tests (live tests are skipped unless GITTOK_LIVE=1)
uv run pytest -n auto         # the same, on all cores
uv run ruff check             # lint
npm --prefix web test         # vitest component tests
npm --prefix web run build    # the static build
uv run --only-group docs mkdocs build --strict   # the docs site
```

Rules:

- **Red/green TDD.** Write the failing test first, see it fail, then write the code.
- Tests build their own fixture git repo. A unit test never needs the network or a Claude session.
- Some structure tests are skipped until the grammars are in the local cache (`uv run gittok structure --prefetch`).
- No logic for one programming language in the shipped Python. Language data lives in `config/` (`tests/test_no_language_logic.py`).
- The shipped `config/` goes to every user. It holds defaults for any repo: nothing about one project, one stack or one computer. A user changes a default in `local/` of the GitTok directory (`docs/config.md`). Read a config file through `overlay.py`, which merges the local file over the shipped one; a new config file needs an entry in `overlay.FILES`, an example in `src/gittok/prompts/config_examples.yaml`, and a section in `docs/config.md` (tests check all three).
- Run all the gates before you commit (the docs build when you changed `docs/` or `mkdocs.yml`).

CI (`.github/workflows/ci.yml`) runs the same gates on macOS for each push to `main` and each pull request, and builds the wheel.

## Documentation site

The user docs are a MkDocs Material site, built the same way as the bundlebase and oxplow sites. The source is `docs/` with `mkdocs.yml`; `.github/workflows/docs.yml` builds it with `--strict` and deploys it to GitHub Pages (<https://nvoxland.github.io/gittok/>) on each push to `main` that changes it.

```bash
uv run --only-group docs mkdocs serve            # live preview at http://localhost:8000
uv run --only-group docs mkdocs build --strict   # one-shot build into site/ (gitignored)
```

- `docs/getting-started/` and `docs/guide/` are the user pages. The other pages in `docs/` (config, install, formats, learning, scheduling, social, api) are the in-depth pages; the nav puts them at the end of the Guide section. Code, tests and `AGENTS.md` cite them by path, so they stay where they are.
- `docs/overrides/home.html` and `docs/stylesheets/extra.css` are the home page and the theme.
- The README is the PyPI page too: every link in it is absolute, to the site or to GitHub (`tests/test_one_directory_model.py`).
- **Release notes are blog posts** in `docs/blog/posts/`, one per release. There is no CHANGELOG file. A post with `draft: true` is not built: set it to false (or remove it) when the release ships.
- One-time setup: in the repository settings, Pages → Source: **GitHub Actions**.

## Build the wheel by hand

```bash
npm --prefix web install
npm --prefix web run build      # the web build goes into the wheel
uv build                        # writes dist/gittok-<version>.tar.gz and dist/gittok-<version>-py3-none-any.whl
```

The build stops with an error if `web/build/index.html` is missing. The wheel bundles `config/`, the web build, and the Claude Code skills and agents (`gittok/_bundled/`). The files that `gittok init` writes from templates are package data in `src/gittok/templates/`. A git URL install (`uv tool install git+<url>`) does not work, because the web build is not committed.

Until the first release is on PyPI, `uv tool install gittok` does not work. Install a wheel that you built:

```bash
uv tool install ./dist/gittok-<version>-py3-none-any.whl
uv tool install 'gittok[images] @ ./dist/gittok-<version>-py3-none-any.whl'   # with mflux
gittok init ~/gittok
cd ~/gittok && claude
```

An installed tool keeps your files in the GitTok directory that you made, not in the clone. `docs/install.md` describes `gittok init`, `gittok update`, and how GitTok picks its folders.

## Release

A release is a pushed tag `vX.Y.Z`. The workflow `.github/workflows/release.yml` does the rest.

One-time setup (PyPI trusted publishing: no token, no secret):

1. On PyPI, under Your account → Publishing, add a trusted publisher (a pending one before the first release) for the project `gittok`: owner `nvoxland`, repository `gittok`, workflow `release.yml`, environment `pypi`.
2. In the GitHub repository settings, add an environment named `pypi`. It needs no secret. Limit it to tags `v*` if you want only a release tag to publish.

The `publish-pypi` job has `id-token: write`, which trusted publishing uses to log in.

For each release:

1. Set the new version in **both** places: `version` in `pyproject.toml` and `__version__` in `src/gittok/__init__.py`. Run `uv lock` so `uv.lock` has the new version.
2. Write the blog post for the release in `docs/blog/posts/` (or take `draft: true` off the post you wrote), with the release date.
3. Run the gates (see "Test and lint"). Commit.
4. Tag and push:

   ```bash
   git tag vX.Y.Z
   git push origin main
   git push origin vX.Y.Z
   ```

What the workflow does:

| Job | What it does |
|---|---|
| `validate-version` | Fails when the tag (without the `v`) is not the version in `pyproject.toml` and in `src/gittok/__init__.py`. The error names the file to fix |
| `test` | On macOS: `uv sync`, `ruff check`, `pytest`, then the web tests on Node 22 |
| `build` | On Linux: builds the web app, runs `uv build` (sdist, then the wheel from the sdist), checks that both hold the web build, installs the wheel into a fresh environment, runs `gittok --version`, makes a GitTok directory with `gittok init` and checks its files, and uploads `dist/*` |
| `publish-pypi` | After the three jobs above pass: publishes `dist/*` to PyPI |
| `create-release` | After PyPI: makes the GitHub release `Release vX.Y.Z` with generated notes and attaches the sdist and the wheel |

If a job fails before `publish-pypi`, fix the cause, delete the tag (`git tag -d vX.Y.Z`, `git push origin :refs/tags/vX.Y.Z`), and tag again. PyPI does not accept the same version twice: after a publish, a fix needs a new version.
