"""Generic OpenAI-compatible provider for Groq/OpenRouter/Together."""

from __future__ import annotations

import os

from adevx.providers.http_compat import OpenAICompatHTTPProvider


def _default_base(provider_name: str) -> str:
    if provider_name == "openrouter":
        return os.environ.get("ADEVX_OPENROUTER_BASE", "https://openrouter.ai/api/v1").strip()
    if provider_name == "groq":
        return os.environ.get("ADEVX_GROQ_BASE", "https://api.groq.com/openai/v1").strip()
    if provider_name == "together":
        return os.environ.get("ADEVX_TOGETHER_BASE", "https://api.together.ai/v1").strip()
    return os.environ.get("ADEVX_API_BASE", "").strip() or "https://api.openai.com/v1"


def _default_key(provider_name: str) -> str:
    if provider_name == "openrouter":
        return os.environ.get("OPENROUTER_API_KEY", "").strip()
    if provider_name == "groq":
        return os.environ.get("GROQ_API_KEY", "").strip()
    if provider_name == "together":
        return os.environ.get("TOGETHER_API_KEY", "").strip()
    return os.environ.get("ADEVX_API_KEY", "").strip()


class OpenAICompatProvider(OpenAICompatHTTPProvider):
    def __init__(
        self,
        provider_name: str,
        model: str,
        api_key: str | None = None,
        api_base: str | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        headers = dict(extra_headers or {})
        if provider_name == "openrouter":
            referer = os.environ.get("ADEVX_OPENROUTER_REFERER", "https://localhost").strip()
            title = os.environ.get("ADEVX_OPENROUTER_TITLE", "AdevX").strip()
            if referer and "HTTP-Referer" not in headers:
                headers["HTTP-Referer"] = referer
            if title and "X-Title" not in headers:
                headers["X-Title"] = title

        timeout = float(os.environ.get("ADEVX_REQUEST_TIMEOUT", "45"))
        max_tokens = int(os.environ.get("ADEVX_MAX_TOKENS", "600"))
        super().__init__(
            name=provider_name,
            model=model,
            api_key=(api_key if api_key is not None else _default_key(provider_name)),
            api_base=(api_base if api_base is not None else _default_base(provider_name)),
            extra_headers=headers,
            request_timeout_s=timeout,
            max_tokens=max_tokens,
        )
