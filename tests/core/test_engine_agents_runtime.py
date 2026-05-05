from __future__ import annotations

from forgecc.core.engine_agents import build_sub_agent_runtime
from forgecc.core.permissions import PermissionMode
from forgecc.core.settings import Settings


def _settings() -> Settings:
    return Settings(
        api_key="test-key",
        base_url="https://test.example/v1",
        model="qwen3.6-plus",
        context_budget=128000,
        max_rounds=60,
        workspace="/tmp/workspace",
        permission_mode="prompt",
    )


def test_build_sub_agent_runtime_inherits_parent_provider_without_model_override():
    settings = _settings()
    provider = object()

    runtime = build_sub_agent_runtime(
        parent_settings=settings,
        parent_provider=provider,
        parent_permission_mode=PermissionMode.PROMPT,
        model=None,
        provider_factory=lambda _: (_ for _ in ()).throw(AssertionError("unused")),
    )

    assert runtime.model == "qwen3.6-plus"
    assert runtime.settings == settings.replace(max_rounds=30)
    assert runtime.provider is provider
    assert runtime.uses_parent_provider is True


def test_build_sub_agent_runtime_rebuilds_provider_for_model_override(monkeypatch):
    settings = _settings()
    parent_provider = object()
    created = []

    monkeypatch.setattr(
        "forgecc.core.settings._load_env_cascade",
        lambda: {"DEEPSEEK_API_KEY": "sk-deepseek"},
    )

    def provider_factory(sub_settings):
        created.append(sub_settings)
        return {"settings": sub_settings}

    runtime = build_sub_agent_runtime(
        parent_settings=settings,
        parent_provider=parent_provider,
        parent_permission_mode=PermissionMode.PROMPT,
        model="deepseek-chat",
        provider_factory=provider_factory,
    )

    assert runtime.model == "deepseek-chat"
    assert runtime.settings.model == "deepseek-chat"
    assert runtime.settings.base_url == "https://api.deepseek.com"
    assert runtime.provider == {"settings": runtime.settings}
    assert runtime.uses_parent_provider is False
    assert created == [runtime.settings]


def test_build_sub_agent_runtime_propagates_plan_permission_mode():
    settings = _settings()

    runtime = build_sub_agent_runtime(
        parent_settings=settings,
        parent_provider=object(),
        parent_permission_mode=PermissionMode.PLAN,
        model=None,
        provider_factory=lambda _: (_ for _ in ()).throw(AssertionError("unused")),
    )

    assert runtime.settings.permission_mode == "plan"
