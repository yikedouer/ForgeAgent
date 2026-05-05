from __future__ import annotations

from forgecc.core.engine_prompt import (
    build_directive_text,
    build_wire_messages,
    select_tool_schemas,
)


def test_build_directive_text_uses_custom_system_prompt_without_builder():
    directive = build_directive_text(
        settings=object(),
        custom_system_prompt="custom prompt",
        plan_file_path="/tmp/plan.md",
        directive_builder=lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("unused")
        ),
    )

    assert directive == "custom prompt"


def test_build_directive_text_includes_plan_prompt_for_main_agent():
    captured = {}

    def directive_builder(settings, *, plan_mode_prompt):
        captured["settings"] = settings
        captured["plan_mode_prompt"] = plan_mode_prompt
        return "main prompt"

    directive = build_directive_text(
        settings="settings",
        custom_system_prompt=None,
        plan_file_path="/tmp/plan.md",
        plan_prompt_builder=lambda path: f"plan:{path}",
        directive_builder=directive_builder,
    )

    assert directive == "main prompt"
    assert captured == {
        "settings": "settings",
        "plan_mode_prompt": "plan:/tmp/plan.md",
    }


def test_build_wire_messages_prepends_system_and_projected_transcript():
    messages = build_wire_messages(
        directive="sys",
        transcript=[{"role": "user", "content": "hi"}],
        collapse=object(),
        project=lambda transcript, collapse: [
            {"role": "assistant", "content": "projected"}
        ],
    )

    assert messages == [
        {"role": "system", "content": "sys"},
        {"role": "assistant", "content": "projected"},
    ]


def test_select_tool_schemas_filters_custom_tools_or_adds_plan_tools():
    all_schemas = [{"name": "read_file"}, {"name": "write_file"}]
    plan_defs = [{"name": "enter_plan_mode"}]

    assert select_tool_schemas(
        all_schemas,
        custom_tool_names={"read_file"},
        plan_tool_defs=plan_defs,
    ) == [{"name": "read_file"}]

    assert select_tool_schemas(
        all_schemas,
        custom_tool_names=None,
        plan_tool_defs=plan_defs,
    ) == [{"name": "read_file"}, {"name": "write_file"}, {"name": "enter_plan_mode"}]
