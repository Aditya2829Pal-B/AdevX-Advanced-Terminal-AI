"""Provider routing policy helpers."""

from __future__ import annotations

import re


def classify_task_type(text: str) -> str:
    lower = text.lower()
    if re.search(r"\b(code|coding|debug|bug|refactor|compile|function|class)\b", lower):
        return "coding"
    if re.search(r"\b(math|calculate|equation|statistics|algebra|integral)\b", lower):
        return "math"
    if re.search(r"\b(image|photo|screenshot|visual|analyze image)\b", lower):
        return "image"
    return "general"


def preferred_chain(task_type: str) -> list[str]:
    if task_type == "coding":
        return ["ollama-local", "groq", "openai", "openrouter", "together"]
    if task_type == "math":
        return ["openai", "groq", "openrouter", "together", "ollama-local"]
    if task_type == "image":
        return ["openai", "openrouter", "groq", "together", "ollama-local"]
    return ["openrouter", "groq", "openai", "together", "ollama-local"]

