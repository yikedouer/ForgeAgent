"""Provider preset resolution for runtime settings."""

from __future__ import annotations


_PROVIDER_PRESETS: dict[str, dict[str, str]] = {
    "qwen": {
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "api_key_env": "QWEN_API_KEY",
        "default_model": "qwen3.6-plus",
    },
    "deepseek": {
        "base_url": "https://api.deepseek.com",
        "api_key_env": "DEEPSEEK_API_KEY",
        "default_model": "deepseek-chat",
    },
    "openai": {
        "base_url": "https://api.openai.com/v1",
        "api_key_env": "OPENAI_API_KEY",
        "default_model": "gpt-4o",
    },
    "azure": {
        "base_url": "https://iai.alibaba-inc.com/azure",
        "api_key_env": "AZURE_API_KEY",
        "default_model": "gpt-4.1-0414",
        "client_type": "azure",
        "api_version": "2024-12-01-preview",
    },
    "gemini": {
        "base_url": "https://iai.alibaba-inc.com/google",
        "api_key_env": "GEMINI_API_KEY",
        "default_model": "google/gemini-3.1-pro-preview",
    },
}


_MODEL_PREFIX_MAP: dict[str, str] = {
    "qwen": "qwen",
    "deepseek": "deepseek",
    "gpt": "azure",
    "o1": "azure",
    "o3": "azure",
    "o4": "azure",
    "google/": "gemini",
    "gemini": "gemini",
}


def _infer_provider(model: str) -> str:
    """Infer provider name from a model prefix, defaulting to qwen."""
    model_lower = model.lower().strip()
    for prefix, provider in _MODEL_PREFIX_MAP.items():
        if model_lower.startswith(prefix):
            return provider
    return "qwen"


def _str_env(env: dict[str, str], name: str) -> str:
    value = env.get(name, "")
    return value if isinstance(value, str) else ""


def _resolve_provider(
    env: dict[str, str],
) -> tuple[str, str, str, str, str]:
    """Return ``(api_key, base_url, model, client_type, api_version)``."""
    model = _str_env(env, "FORGECC_MODEL").strip()
    provider_name = _str_env(env, "FORGECC_PROVIDER").strip()

    if not provider_name:
        provider_name = _infer_provider(model) if model else "qwen"

    provider_key = provider_name.lower()
    preset = _PROVIDER_PRESETS.get(provider_key)
    if not preset:
        return (
            _str_env(env, "OPENAI_API_KEY").strip(),
            _str_env(env, "OPENAI_BASE_URL").strip() or "https://api.openai.com/v1",
            model or "gpt-4o",
            "openai",
            "",
        )

    api_key = (
        _str_env(env, preset["api_key_env"]).strip()
        or _str_env(env, "OPENAI_API_KEY").strip()
    )
    client_type = preset.get("client_type", "openai")
    api_version = ""

    if client_type == "azure":
        base_url = _str_env(env, "AZURE_ENDPOINT").strip() or preset["base_url"]
        api_version = (
            _str_env(env, "AZURE_API_VERSION").strip()
            or preset.get("api_version", "2024-12-01-preview")
        )
    else:
        base_url = _str_env(env, "OPENAI_BASE_URL").strip() or preset["base_url"]
        for name, other in _PROVIDER_PRESETS.items():
            if name != provider_key and base_url == other["base_url"]:
                base_url = preset["base_url"]
                break

    if not model:
        model = preset["default_model"]

    return api_key, base_url, model, client_type, api_version
