import pytest

from forgecc.core.settings import Settings
from forgecc.interface.cli_startup import (
    CliStartupError,
    apply_cli_settings_overrides,
    normalize_resume_id,
    validate_prompt_options,
)


def _settings() -> Settings:
    return Settings(
        api_key="sk-env",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        model="qwen3.6-plus",
        context_budget=128000,
        max_rounds=60,
        workspace="/tmp/work",
        permission_mode="prompt",
        client_type="azure",
        api_version="2024-12-01-preview",
    )


def test_normalize_resume_id_rejects_blank_resume() -> None:
    with pytest.raises(CliStartupError) as exc:
        normalize_resume_id("   ", lambda: "latest")

    assert exc.value.message == "Session ID must be non-empty."
    assert exc.value.exit_code == 1


def test_normalize_resume_id_resolves_latest_checkpoint() -> None:
    assert normalize_resume_id("latest", lambda: "session-2") == "session-2"


def test_normalize_resume_id_rejects_latest_when_no_sessions() -> None:
    with pytest.raises(CliStartupError) as exc:
        normalize_resume_id("latest", lambda: None)

    assert exc.value.message == "No saved sessions."
    assert exc.value.exit_code == 1


def test_apply_cli_settings_overrides_forces_openai_client_for_base_url() -> None:
    settings = apply_cli_settings_overrides(
        _settings(),
        model=None,
        base_url=" https://api.openai.com/v1 ",
        api_key=" sk-openai ",
    )

    assert settings.api_key == "sk-openai"
    assert settings.base_url == "https://api.openai.com/v1"
    assert settings.client_type == "openai"
    assert settings.api_version == ""


def test_apply_cli_settings_overrides_rejects_blank_model() -> None:
    with pytest.raises(CliStartupError) as exc:
        apply_cli_settings_overrides(_settings(), model="   ", base_url=None, api_key=None)

    assert exc.value.message == "Model name must be non-empty."
    assert exc.value.exit_code == 1


def test_validate_prompt_options_rejects_json_without_prompt() -> None:
    with pytest.raises(CliStartupError) as exc:
        validate_prompt_options(None, "json")

    assert exc.value.message == "--output-format json requires --prompt."
    assert exc.value.exit_code == 1


def test_validate_prompt_options_rejects_jsonl_for_prompt_mode() -> None:
    with pytest.raises(CliStartupError) as exc:
        validate_prompt_options("hello", "jsonl")

    assert exc.value.message == "--output-format jsonl is only supported by export."
    assert exc.value.exit_code == 1
