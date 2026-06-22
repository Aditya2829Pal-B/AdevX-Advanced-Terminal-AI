from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from taskbot import (
    AdevXBot,
    FallbackBot,
    MemoryStore,
    ProjectRAGStore,
    ToolRegistry,
    _build_provider_config,
    pick_ollama_model,
)


class _FakeResponse:
    status = 200

    def __init__(self, payload: str) -> None:
        self.payload = payload

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self) -> bytes:
        return self.payload.encode("utf-8")


class _FakeLocalLLM:
    model = "qwen2.5:7b"

    def set_mode(self, _mode: str) -> None:
        return None

    def ask(self, text: str) -> str:
        return (
            "```python\n"
            "def inverse_array(values):\n"
            "    return values[::-1]\n"
            "```\n"
            f"Handled: {text}"
        )


class OllamaLocalFallbackTests(unittest.TestCase):
    def setUp(self) -> None:
        self._old_enable = os.environ.get("ADEVX_ENABLE_OLLAMA")
        os.environ["ADEVX_ENABLE_OLLAMA"] = "0"

    def tearDown(self) -> None:
        if self._old_enable is None:
            os.environ.pop("ADEVX_ENABLE_OLLAMA", None)
        else:
            os.environ["ADEVX_ENABLE_OLLAMA"] = self._old_enable

    def test_pick_ollama_model_prefers_laptop_friendly_coder_model(self) -> None:
        picked = pick_ollama_model(
            [
                {"name": "llama3.1:70b", "details": {"parameter_size": "70B"}},
                {"name": "qwen2.5-coder:7b", "details": {"parameter_size": "7B"}},
            ]
        )
        self.assertEqual(picked, "qwen2.5-coder:7b")

    @patch("urllib.request.urlopen")
    def test_ollama_provider_config_auto_detects_installed_model(self, urlopen_mock) -> None:
        os.environ["ADEVX_ENABLE_OLLAMA"] = "1"
        urlopen_mock.return_value = _FakeResponse(
            '{"models":[{"name":"mistral:7b","details":{"parameter_size":"7B"}}]}'
        )
        cfg = _build_provider_config(
            "ollama-local",
            None,
            None,
            generic_key=None,
            openai_key=None,
            openrouter_key=None,
            groq_key=None,
            together_key=None,
        )
        self.assertIsNotNone(cfg)
        assert cfg is not None
        self.assertEqual(cfg.model, "mistral:7b")
        self.assertEqual(cfg.api_base, "http://localhost:11434/v1")

    def test_offline_prompt_uses_local_generation_before_raw_rag(self) -> None:
        bot = FallbackBot(ToolRegistry(), MemoryStore(), ProjectRAGStore())
        bot.local_llm = _FakeLocalLLM()  # type: ignore[assignment]

        result = bot.ask("Write Python code for array inverse")

        self.assertIn("def inverse_array", result)
        self.assertNotIn("raw retrieved project context", result.lower())

    @patch("taskbot.list_ollama_models")
    def test_ollama_models_command_lists_installed_models(self, list_models_mock) -> None:
        list_models_mock.return_value = [
            {"name": "qwen2.5:7b", "details": {"parameter_size": "7B"}}
        ]
        bot = AdevXBot(
            FallbackBot(ToolRegistry(), MemoryStore(), ProjectRAGStore()),
            None,
            [],
        )

        result = bot.ask("/ollama models")

        self.assertIn("Installed Ollama models:", result)
        self.assertIn("qwen2.5:7b", result)


if __name__ == "__main__":
    unittest.main()
