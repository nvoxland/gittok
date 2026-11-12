from pathlib import Path

import pytest

from tests.fixture_repo import FixtureRepo, build_fixture_repo


@pytest.fixture(scope="session")
def fixture_repo(tmp_path_factory) -> FixtureRepo:
    """Read-only shared fixture repo. Tests must not modify it."""
    return build_fixture_repo(Path(tmp_path_factory.mktemp("fixture")) / "repo")


def make_config(fixture_repo, tmp_path, **agent):
    """A full Config for the fixture repo, with real personas and the shipped default mix."""
    import yaml

    from gittok.config import (
        AgentSettings,
        AnalysisSettings,
        Config,
        Persona,
        Repo,
        ResearchSettings,
        ServerSettings,
        Settings,
    )

    root = Path(__file__).parents[1]
    raw = yaml.safe_load((root / "config" / "personas.yaml").read_text())["personas"]
    personas = {h: Persona(h, p["name"], p["voice"]) for h, p in raw.items()}
    defaults = yaml.safe_load((root / "config" / "defaults.yaml").read_text())
    return Config(
        root=tmp_path,
        repos={"fixture": Repo(name="fixture", path=fixture_repo.path, ref="main")},
        groups={},
        settings=Settings(
            data_dir=tmp_path / "data",
            # Test-only: Starlette's TestClient sends `Host: testserver`.
            server=ServerSettings(allowed_hosts=("testserver",)),
            agent=AgentSettings(**{"max_count": 20, "per_day_runs": 4, **agent}),
            analysis=AnalysisSettings(),
            research=ResearchSettings(),
        ),
        defaults=defaults,
        personas=personas,
    )


def store_card(conn, cfg, run_id: str, acc, now: str | None = None) -> str:
    """Insert one accepted card in its own transaction (the app inserts in runs.submit)."""
    from gittok import store

    with conn:
        return store.insert_card(conn, cfg, run_id, acc, now)


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture(autouse=True)
def _fixed_choice_order(monkeypatch):
    """Most tests pin quiz answers to the positions the card was written with."""
    from gittok import store

    monkeypatch.setattr(store, "SHUFFLE", False)
