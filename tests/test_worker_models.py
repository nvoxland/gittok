"""Worker models: the server names a tier per worker; each agent program maps tiers to its
own models in `agent.models` (an empty entry: the session's model)."""

import pytest

from gittok import config, mcp_server
from tests.conftest import make_config


def test_claude_maps_tiers_to_its_models_and_codex_inherits_by_default(fixture_repo, tmp_path,
                                                                       monkeypatch):
    cfg = make_config(fixture_repo, tmp_path)
    monkeypatch.delenv("GITTOK_AGENT", raising=False)
    assert config.harness() == "claude"
    assert config.worker_models(cfg) == {"light": "haiku", "standard": "sonnet"}
    monkeypatch.setenv("GITTOK_AGENT", "codex")
    assert config.harness() == "codex"
    assert config.worker_models(cfg) == {"light": None, "standard": None}


def test_a_local_setting_names_codex_models(fixture_repo, tmp_path, monkeypatch):
    import dataclasses

    cfg = make_config(fixture_repo, tmp_path)
    agent = dataclasses.replace(cfg.settings.agent,
                                models={"claude": {}, "codex": {"light": "gpt-mini"}})
    cfg = dataclasses.replace(cfg, settings=dataclasses.replace(cfg.settings, agent=agent))
    monkeypatch.setenv("GITTOK_AGENT", "codex")
    assert config.worker_models(cfg) == {"light": "gpt-mini", "standard": None}


@pytest.mark.parametrize("models,match", [
    ({"vim": {}}, "claude or codex"),
    ({"codex": {"huge": "x"}}, "light or standard"),
    ({"codex": {"light": 3}}, "model name"),
])
def test_bad_worker_models_are_a_config_error(tmp_path, models, match):
    from gittok.config import AgentSettings, ConfigError, _section

    with pytest.raises(ConfigError, match=match):
        _section(AgentSettings, {"models": models}, "agent", tmp_path / "settings.yaml")


@pytest.mark.anyio
async def test_scout_batches_name_the_light_model(fixture_repo, tmp_path, monkeypatch):
    from mcp.client import Client

    from tests.test_mcp_e2e import data

    monkeypatch.delenv("GITTOK_AGENT", raising=False)
    cfg = make_config(fixture_repo, tmp_path)
    async with Client(mcp_server.build_server(lambda: cfg)) as client:
        status = data(await client.call_tool("scout_status", {}))
    assert status["model"] == "haiku"
