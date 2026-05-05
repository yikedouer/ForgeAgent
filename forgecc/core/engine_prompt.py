"""Engine prompt and tool schema selection helpers."""

from __future__ import annotations

from typing import Callable

from ..context.collapse import project_view
from .plan_mode import build_plan_mode_prompt


DirectiveBuilder = Callable[..., str]
PlanPromptBuilder = Callable[[str], str]
ProjectViewFn = Callable[[list[dict], object | None], list[dict]]


def build_directive_text(
    *,
    settings: object,
    custom_system_prompt: str | None,
    plan_file_path: str | None,
    plan_prompt_builder: PlanPromptBuilder = build_plan_mode_prompt,
    directive_builder: DirectiveBuilder | None = None,
) -> str:
    if custom_system_prompt:
        return custom_system_prompt
    if directive_builder is None:
        from ..interface.directive import build as directive_builder
    plan_prompt = plan_prompt_builder(plan_file_path) if plan_file_path else None
    return directive_builder(settings, plan_mode_prompt=plan_prompt)


def build_wire_messages(
    *,
    directive: str,
    transcript: list[dict],
    collapse: object | None,
    project: ProjectViewFn = project_view,
) -> list[dict]:
    return [{"role": "system", "content": directive}] + project(transcript, collapse)


def select_tool_schemas(
    all_schemas: list[dict],
    *,
    custom_tool_names: set[str] | None,
    plan_tool_defs: list[dict],
) -> list[dict]:
    if custom_tool_names is not None:
        return [
            schema for schema in all_schemas
            if schema["name"] in custom_tool_names
        ]
    return all_schemas + plan_tool_defs
