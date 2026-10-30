from pathlib import Path

import pytest

from tests.fixture_repo import FixtureRepo, build_fixture_repo


@pytest.fixture(scope="session")
def fixture_repo(tmp_path_factory) -> FixtureRepo:
    """Read-only shared fixture repo. Tests must not modify it."""
    return build_fixture_repo(Path(tmp_path_factory.mktemp("fixture")) / "repo")
