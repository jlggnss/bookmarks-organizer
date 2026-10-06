"""Factory for creating and auto-detecting LLM clients."""

from __future__ import annotations

import os
from typing import Tuple

from .gemini_llm import GeminiLLM, DEFAULT_GEMINI_MODEL
from .llm_interface import LLMInterface
from .openai_llm import OpenAILLM, DEFAULT_OPENAI_MODEL


def detect_provider(
    requested_provider: str | None = None,
    api_key: str | None = None,
    model: str | None = None,
    base_url: str | None = None,
) -> str:
    """
    Detect whether to use 'gemini' or 'openai'.
    Priority:
    1. Explicit provider parameter if specified (and != 'auto')
    2. PROVIDER environment variable
    3. Model name heuristics (starts with gemini -> gemini, gpt/claude -> openai)
    4. API key prefix (starts with AIza -> gemini)
    5. Presence of GEMINI_API_KEY vs OPENAI_API_KEY
    6. Non-default base_url (-> openai)
    7. Default fallback: gemini if any Gemini key exists, else openai.
    """
    if requested_provider and requested_provider.lower() != "auto":
        return requested_provider.lower()

    env_provider = os.getenv("PROVIDER")
    if env_provider and env_provider.lower() != "auto":
        return env_provider.lower()

    # If a specific model was explicitly passed as argument:
    if model:
        if model.lower().startswith("gemini"):
            return "gemini"
        if model.lower().startswith(("gpt-", "o1", "o3", "text-", "claude")):
            return "openai"

    # Check API key prefix (Google Gemini keys start with 'AIza')
    check_key = api_key or os.getenv("GEMINI_API_KEY") or os.getenv("API_KEY") or ""
    if check_key.startswith("AIza"):
        return "gemini"

    # Check specific env vars
    has_gemini = bool(os.getenv("GEMINI_API_KEY"))
    has_openai = bool(os.getenv("OPENAI_API_KEY"))

    if has_gemini and not has_openai:
        return "gemini"
    if has_openai and not has_gemini:
        return "openai"

    # Check MODEL env var if set
    env_model = os.getenv("MODEL", "")
    if env_model.lower().startswith("gemini"):
        return "gemini"
    if env_model.lower().startswith(("gpt-", "o1", "o3", "text-", "claude")):
        return "openai"

    # Custom base_url implies OpenAI-compatible API
    env_base = os.getenv("BASE_URL")
    if base_url or (env_base and "api.openai.com" not in env_base):
        return "openai"

    if has_gemini:
        return "gemini"

    return "openai"


def create_llm_client(
    provider: str | None = None,
    api_key: str | None = None,
    model: str | None = None,
    base_url: str | None = None,
) -> Tuple[LLMInterface, str, str]:
    """
    Create an LLM client instance based on configuration.
    Returns: (client, resolved_provider, resolved_model)
    """
    resolved_provider = detect_provider(
        requested_provider=provider,
        api_key=api_key,
        model=model,
        base_url=base_url,
    )

    if resolved_provider == "gemini":
        key = api_key or os.getenv("GEMINI_API_KEY") or os.getenv("API_KEY")
        if not key:
            raise ValueError(
                "No Gemini API key provided. Set GEMINI_API_KEY in .env or pass --api-key."
            )

        # Resolve model
        resolved_model = None
        if model and not model.lower().startswith(("gpt-", "o1", "o3")):
            resolved_model = model
        elif os.getenv("GEMINI_MODEL"):
            resolved_model = os.getenv("GEMINI_MODEL")
        elif os.getenv("MODEL") and os.getenv("MODEL", "").lower().startswith("gemini"):
            resolved_model = os.getenv("MODEL")
        else:
            resolved_model = DEFAULT_GEMINI_MODEL

        client = GeminiLLM(api_key=key, model=resolved_model)
        return client, "gemini", resolved_model

    elif resolved_provider == "openai":
        key = api_key or os.getenv("OPENAI_API_KEY") or os.getenv("API_KEY")
        if not key:
            raise ValueError(
                "No OpenAI API key provided. Set API_KEY or OPENAI_API_KEY in .env or pass --api-key."
            )

        resolved_model = None
        if model and not model.lower().startswith("gemini"):
            resolved_model = model
        elif os.getenv("OPENAI_MODEL"):
            resolved_model = os.getenv("OPENAI_MODEL")
        elif os.getenv("MODEL") and not os.getenv("MODEL", "").lower().startswith("gemini"):
            resolved_model = os.getenv("MODEL")
        else:
            resolved_model = DEFAULT_OPENAI_MODEL

        client = OpenAILLM(api_key=key, base_url=base_url, model=resolved_model)
        return client, "openai", resolved_model

    else:
        raise ValueError(f"Unsupported provider: {resolved_provider}. Use 'gemini' or 'openai'.")
