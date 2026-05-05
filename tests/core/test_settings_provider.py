"""Provider preset resolution tests."""

from __future__ import annotations

from forgecc.core.settings_provider import _infer_provider, _resolve_provider


def test_infer_provider_defaults_unknown_models_to_qwen() -> None:
    assert _infer_provider("unknown-model") == "qwen"


def test_resolve_provider_uses_deepseek_preset_from_model_prefix() -> None:
    api_key, base_url, model, client_type, api_version = _resolve_provider({
        "DEEPSEEK_API_KEY": " sk-ds ",
        "FORGECC_MODEL": " deepseek-chat ",
    })

    assert api_key == "sk-ds"
    assert base_url == "https://api.deepseek.com"
    assert model == "deepseek-chat"
    assert client_type == "openai"
    assert api_version == ""


def test_resolve_provider_uses_azure_endpoint_and_api_version() -> None:
    api_key, base_url, model, client_type, api_version = _resolve_provider({
        "FORGECC_PROVIDER": "azure",
        "AZURE_API_KEY": "sk-az",
        "AZURE_ENDPOINT": " https://azure.example ",
        "AZURE_API_VERSION": " 2024-12-01-preview ",
    })

    assert api_key == "sk-az"
    assert base_url == "https://azure.example"
    assert model == "gpt-4.1-0414"
    assert client_type == "azure"
    assert api_version == "2024-12-01-preview"
