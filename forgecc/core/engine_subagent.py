"""Sub-agent runtime preparation helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .permissions import PermissionMode
from .settings import Settings


ProviderFactory = Callable[[Settings], object]


@dataclass(frozen=True)
class SubAgentRuntime:
    settings: Settings
    provider: object
    model: str
    uses_parent_provider: bool


def build_sub_agent_runtime(
    *,
    parent_settings: Settings,
    parent_provider: object,
    parent_permission_mode: PermissionMode,
    model: str | None,
    provider_factory: ProviderFactory,
    max_rounds: int = 30,
) -> SubAgentRuntime:
    use_model = model or parent_settings.model
    sub_settings = parent_settings.replace(max_rounds=max_rounds)
    sub_provider = parent_provider
    uses_parent_provider = True

    if model and model != parent_settings.model:
        sub_settings = sub_settings.for_model(model)
        sub_provider = provider_factory(sub_settings)
        uses_parent_provider = False

    if parent_permission_mode == PermissionMode.PLAN:
        sub_settings = sub_settings.replace(permission_mode="plan")

    return SubAgentRuntime(
        settings=sub_settings,
        provider=sub_provider,
        model=use_model,
        uses_parent_provider=uses_parent_provider,
    )
