"""OpenAI-compatible HTTP provider runtime.

Used by OpenAI, OpenRouter, Groq, Together, and Ollama-compatible endpoints.
"""

from __future__ import annotations

import asyncio
import json
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any

from adevx.core.errors import ProviderError
from adevx.core.models import AssistantResponse, ChatMessage, UserRequest
from adevx.providers.base import BaseProvider


def _map_role(role: str) -> str:
    # Many OpenAI-compatible chat endpoints do not accept "developer".
    if role == "developer":
        return "system"
    return role


def _extract_text(content: Any) -> str:
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if not isinstance(item, dict):
                continue
            if item.get("type") == "text" and isinstance(item.get("text"), str):
                parts.append(item["text"])
            elif isinstance(item.get("content"), str):
                parts.append(item["content"])
        return "\n".join(parts).strip()
    return ""


@dataclass(slots=True)
class OpenAICompatHTTPProvider(BaseProvider):
    name: str
    model: str
    api_base: str
    api_key: str = ""
    extra_headers: dict[str, str] = field(default_factory=dict)
    request_timeout_s: float = 45.0
    temperature: float = 0.2
    max_tokens: int = 600

    async def complete(
        self,
        *,
        messages: list[ChatMessage],
        request: UserRequest,
        stream: bool = False,
    ) -> AssistantResponse:
        if stream:
            raise ProviderError(f"{self.name} stream mode is not implemented yet.")
        payload_messages = [
            {
                "role": _map_role(msg.role),
                "content": msg.content,
                **({"name": msg.name} if msg.name else {}),
            }
            for msg in messages
        ]
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": payload_messages,
            "temperature": self.temperature,
        }
        if self.max_tokens > 0:
            payload["max_tokens"] = self.max_tokens

        data = await asyncio.to_thread(self._post_chat, payload)
        text = self._extract_response_text(data)
        return AssistantResponse(
            request_id=request.request_id,
            text=text or "I completed the request, but received an empty response.",
            provider=self.name,
            mode=request.mode,
            metadata={
                "model": self.model,
                "usage": data.get("usage", {}),
                "finish_reason": self._finish_reason(data),
            },
        )

    def _post_chat(self, payload: dict[str, Any]) -> dict[str, Any]:
        body = json.dumps(payload).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key.strip()}"
        headers.update(self.extra_headers)

        url = f"{self.api_base.rstrip('/')}/chat/completions"
        req = urllib.request.Request(url, method="POST", data=body, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=self.request_timeout_s) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
                data = json.loads(raw)
                if not isinstance(data, dict):
                    raise ProviderError(f"{self.name} returned non-object JSON payload.")
                return data
        except TimeoutError as exc:
            raise ProviderError(f"{self.name} request timed out after {self.request_timeout_s:.0f}s") from exc
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            message = raw
            code = ""
            try:
                parsed = json.loads(raw)
                err = parsed.get("error", {})
                if isinstance(err, dict):
                    message = str(err.get("message", raw))
                    code = str(err.get("code", "") or "")
            except json.JSONDecodeError:
                pass
            prefix = f"{self.name} API HTTP error {exc.code}"
            if code:
                prefix += f" ({code})"
            raise ProviderError(f"{prefix}: {message}") from exc
        except urllib.error.URLError as exc:
            reason = str(getattr(exc, "reason", "")).strip().lower()
            if reason == "timed out" or "timed out" in str(exc).lower():
                raise ProviderError(
                    f"{self.name} request timed out after {self.request_timeout_s:.0f}s"
                ) from exc
            raise ProviderError(f"{self.name} API request failed: {exc}") from exc
        except json.JSONDecodeError as exc:
            raise ProviderError(f"{self.name} API returned invalid JSON.") from exc

    @staticmethod
    def _extract_response_text(data: dict[str, Any]) -> str:
        choices = data.get("choices", [])
        if not isinstance(choices, list) or not choices:
            return ""
        first = choices[0]
        if not isinstance(first, dict):
            return ""
        message = first.get("message", {})
        if not isinstance(message, dict):
            return ""
        return _extract_text(message.get("content"))

    @staticmethod
    def _finish_reason(data: dict[str, Any]) -> str:
        choices = data.get("choices", [])
        if not isinstance(choices, list) or not choices:
            return ""
        first = choices[0]
        if not isinstance(first, dict):
            return ""
        return str(first.get("finish_reason", "") or "")

