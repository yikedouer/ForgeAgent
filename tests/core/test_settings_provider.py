"""OpenAI-compatible provider resolution tests."""

from __future__ import annotations

from forgeagent.core.settings import _resolve_provider


def test_resolve_provider_uses_openai_compatible_defaults() -> None:
    api_key, base_url, model, client_type, api_version = _resolve_provider({})

    assert api_key == ""
    assert base_url == "https://api.openai.com/v1"
    assert model == "gpt-4o"
    assert client_type == "openai"
    assert api_version == ""


def test_resolve_provider_uses_generic_openai_compatible_env() -> None:
    api_key, base_url, model, client_type, api_version = _resolve_provider({
        "OPENAI_API_KEY": " sk-test ",
        "OPENAI_BASE_URL": " https://proxy.example/v1 ",
        "MODEL": " custom-model ",
    })

    assert api_key == "sk-test"
    assert base_url == "https://proxy.example/v1"
    assert model == "custom-model"
    assert client_type == "openai"
    assert api_version == ""


def test_resolve_provider_keeps_legacy_model_fallback() -> None:
    api_key, base_url, model, client_type, api_version = _resolve_provider({
        "FORGEAGENT_MODEL": " legacy-model ",
    })

    assert api_key == ""
    assert base_url == "https://api.openai.com/v1"
    assert model == "legacy-model"
    assert client_type == "openai"
    assert api_version == ""


def test_resolve_provider_prefers_model_over_legacy_name() -> None:
    _, _, model, _, _ = _resolve_provider({
        "MODEL": "standard-model",
        "FORGEAGENT_MODEL": "legacy-model",
    })

    assert model == "standard-model"


def test_resolve_provider_ignores_unrelated_provider_specific_keys() -> None:
    api_key, base_url, model, client_type, api_version = _resolve_provider({
        "CUSTOM_PROVIDER": "legacy",
        "CUSTOM_API_KEY": "sk-custom",
        "MODEL": "custom-model",
    })

    assert api_key == ""
    assert base_url == "https://api.openai.com/v1"
    assert model == "custom-model"
    assert client_type == "openai"
    assert api_version == ""
