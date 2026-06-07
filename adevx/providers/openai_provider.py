"""OpenAI provider adapter."""

from __future__ import annotations

import os

from adevx.providers.http_compat import OpenAICompatHTTPProvider


class OpenAIProvider(OpenAICompatHTTPProvider):
    def __init__(
        self,
        model: str = "gpt-4.1-mini",
        api_key: str | None = None,
        api_base: str | None = None,
    ) -> None:
        resolved_key = (api_key or os.environ.get("OPENAI_API_KEY", "")).strip()
        resolved_base = (api_base or os.environ.get("ADEVX_OPENAI_BASE", "https://api.openai.com/v1")).strip()
        timeout = float(os.environ.get("ADEVX_REQUEST_TIMEOUT", "45"))
        max_tokens = int(os.environ.get("ADEVX_MAX_TOKENS", "600"))
        super().__init__(
            name="openai",
            model=model,
            api_key=resolved_key,
            api_base=resolved_base,
            request_timeout_s=timeout,
            max_tokens=max_tokens,
        )
