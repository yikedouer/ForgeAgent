"""Pure helpers for validating CLI startup arguments."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from ..core.settings import Settings


@dataclass(frozen=True)
class CliStartupError(Exception):
    message: str
    exit_code: int = 1


def normalize_resume_id(
    resume: str | None,
    latest_checkpoint: Callable[[], str | None],
) -> str | None:
    """Normalize ``--resume`` input, resolving ``latest`` when requested."""
    if resume is None:
        return None
    resume_id = resume.strip()
    if not resume_id:
        raise CliStartupError("Session ID must be non-empty.")
    if resume_id == "latest":
        latest = latest_checkpoint()
        if latest is None:
            raise CliStartupError("No saved sessions.")
        return latest
    return resume_id


def apply_cli_settings_overrides(
    settings: Settings,
    *,
    model: str | None,
    base_url: str | None,
    api_key: str | None,
) -> Settings:
    """Apply direct CLI settings overrides after env/checkpoint defaults."""
    if model is not None:
        model_name = model.strip()
        if not model_name:
            raise CliStartupError("Model name must be non-empty.")
        settings = settings.for_model(model_name)

    overrides: dict = {}
    if base_url is not None:
        normalized_base_url = base_url.strip()
        if not normalized_base_url:
            raise CliStartupError("Base URL must be non-empty.")
        overrides["base_url"] = normalized_base_url
        overrides["client_type"] = "openai"
        overrides["api_version"] = ""
    if api_key is not None:
        normalized_api_key = api_key.strip()
        if not normalized_api_key:
            raise CliStartupError("API key must be non-empty.")
        overrides["api_key"] = normalized_api_key
    if overrides:
        settings = settings.replace(**overrides)
    return settings


def validate_prompt_options(prompt: str | None, output_format: str) -> None:
    """Validate prompt-mode output options before constructing runtime objects."""
    if prompt is not None and not prompt.strip():
        raise CliStartupError("Prompt must be non-empty.")
    if output_format == "json" and prompt is None:
        raise CliStartupError("--output-format json requires --prompt.")
    if output_format == "jsonl":
        raise CliStartupError("--output-format jsonl is only supported by export.")
