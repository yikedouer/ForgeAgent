from __future__ import annotations

from forgeagent.core.subagent_runtime import run_configured_sub_agent
from forgeagent.core.permissions import PermissionMode
from forgeagent.core.settings import Settings


def _settings() -> Settings:
    return Settings(
        api_key="test-key",
        base_url="https://test.example/v1",
        model="base-model",
        context_budget=128000,
        max_rounds=60,
        workspace="/tmp/workspace",
        permission_mode="prompt",
    )


class FakeEngine:
    instances = []

    def __init__(
        self,
        *,
        settings,
        provider,
        is_sub_agent,
        custom_system_prompt,
        custom_tool_names,
    ):
        self.settings = settings
        self.provider = provider
        self.is_sub_agent = is_sub_agent
        self.custom_system_prompt = custom_system_prompt
        self.custom_tool_names = custom_tool_names
        self._total_input_tokens = 11
        self._total_output_tokens = 7
        FakeEngine.instances.append(self)

    def run(self, prompt):
        self.prompt = prompt
        return "done"


class FailingEngine(FakeEngine):
    def run(self, prompt):
        raise RuntimeError("boom")


def test_run_configured_sub_agent_builds_runtime_engine_and_record():
    FakeEngine.instances = []
    parent_provider = object()
    begun = []
    finished = []

    result = run_configured_sub_agent(
        engine_cls=FakeEngine,
        parent_settings=_settings(),
        parent_provider=parent_provider,
        parent_permission_mode=PermissionMode.PROMPT,
        workspace="/tmp/workspace",
        agent_type="explore",
        description="inspect code",
        prompt="look around",
        model=None,
        allowed_tools=("read_file", "agent"),
        available_tool_names=("read_file", "write_file", "agent", "team"),
        provider_factory=lambda _: (_ for _ in ()).throw(AssertionError("unused")),
        config_lookup=lambda _: {
            "system_prompt": "explore prompt",
            "tool_names": None,
        },
        agent_id_factory=lambda: "agent-1",
        begin_record=lambda **kwargs: begun.append(kwargs) or {"record": "one"},
        finish_record=lambda record, **kwargs: finished.append((record, kwargs)),
    )

    assert result.result == "done"
    assert result.description == "inspect code"
    assert result.tokens_in == 11
    assert result.tokens_out == 7
    assert result.error is None
    assert result.model == "base-model"
    assert result.uses_parent_provider is True

    assert len(FakeEngine.instances) == 1
    sub = FakeEngine.instances[0]
    assert sub.provider is parent_provider
    assert sub.is_sub_agent is True
    assert sub.custom_system_prompt == "explore prompt"
    assert sub.custom_tool_names == {"read_file"}
    assert sub.prompt == "look around"
    assert begun[0]["agent_id"] == "agent-1"
    assert begun[0]["description"] == "inspect code"
    assert finished == [
        ({"record": "one"}, {
            "result": "done",
            "tokens_in": 11,
            "tokens_out": 7,
            "error": None,
        })
    ]


def test_run_configured_sub_agent_turns_run_exception_into_result():
    finished = []

    result = run_configured_sub_agent(
        engine_cls=FailingEngine,
        parent_settings=_settings(),
        parent_provider=object(),
        parent_permission_mode=PermissionMode.PROMPT,
        workspace="/tmp/workspace",
        agent_type="general",
        description="broken",
        prompt="fail",
        model=None,
        allowed_tools=None,
        available_tool_names=("read_file",),
        provider_factory=lambda _: (_ for _ in ()).throw(AssertionError("unused")),
        config_lookup=lambda _: {
            "system_prompt": "general prompt",
            "tool_names": {"read_file"},
        },
        begin_record=lambda **kwargs: {"record": "two"},
        finish_record=lambda record, **kwargs: finished.append((record, kwargs)),
    )

    assert result.result == "(Sub-agent failed: boom)"
    assert result.error == "boom"
    assert result.tokens_in == 11
    assert result.tokens_out == 7
    assert finished[0][1]["error"] == "boom"
    assert finished[0][1]["result"] == "(Sub-agent failed: boom)"
