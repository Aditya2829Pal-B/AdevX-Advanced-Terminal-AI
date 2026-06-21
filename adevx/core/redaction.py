"""Helpers for removing secrets from user-facing diagnostics."""

from __future__ import annotations

import os
import re


_SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_\-]{12,}"),
    re.compile(r"sk-proj-[A-Za-z0-9_\-]{12,}"),
    re.compile(r"Bearer\s+[A-Za-z0-9_\-\.]{12,}", re.IGNORECASE),
]


def redact_secrets(value: object) -> str:
    text = str(value)
    known_values = [
        os.environ.get(name, "")
        for name in (
            "OPENAI_API_KEY",
            "OPENROUTER_API_KEY",
            "GROQ_API_KEY",
            "TOGETHER_API_KEY",
            "ADEVX_API_KEY",
            "ADEVX_OLLAMA_API_KEY",
        )
    ]
    for secret in known_values:
        secret = secret.strip()
        if secret:
            text = text.replace(secret, "[REDACTED]")
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub("[REDACTED]", text)
    return text
