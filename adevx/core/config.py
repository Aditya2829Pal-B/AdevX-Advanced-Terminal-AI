"""Runtime configuration model and environment loading."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(slots=True)
class RuntimeConfig:
    workspace_root: Path = field(default_factory=lambda: Path.cwd().resolve())
    provider_chain: tuple[str, ...] = ("openai", "groq", "openrouter", "together", "ollama-local")
    default_mode: str = "chat"
    enable_streaming: bool = True
    max_concurrent_agents: int = 4
    request_timeout_s: float = 45.0
    max_tool_steps: int = 8
    max_retries: int = 2
    retry_base_delay_s: float = 0.6
    retry_max_delay_s: float = 4.0
    circuit_fail_threshold: int = 3
    circuit_recovery_s: float = 10.0
    log_level: str = "INFO"
    enable_telemetry: bool = True
    queue_max_size: int = 1000

    @classmethod
    def from_env(cls) -> "RuntimeConfig":
        provider_raw = os.environ.get(
            "ADEVX_PROVIDER_CHAIN",
            "openai,groq,openrouter,together,ollama-local",
        )
        chain = tuple(x.strip().lower() for x in provider_raw.split(",") if x.strip())
        return cls(
            workspace_root=Path.cwd().resolve(),
            provider_chain=chain or cls.provider_chain,
            default_mode=os.environ.get("ADEVX_MODE", "chat").strip().lower() or "chat",
            enable_streaming=os.environ.get("ADEVX_STREAMING", "1").strip().lower() not in {"0", "false", "no"},
            max_concurrent_agents=int(os.environ.get("ADEVX_MAX_AGENTS", "4")),
            request_timeout_s=float(os.environ.get("ADEVX_REQUEST_TIMEOUT", "45")),
            max_tool_steps=int(os.environ.get("ADEVX_MAX_TOOL_STEPS", "8")),
            max_retries=int(os.environ.get("ADEVX_MAX_RETRIES", "2")),
            retry_base_delay_s=float(os.environ.get("ADEVX_RETRY_BASE_DELAY", "0.6")),
            retry_max_delay_s=float(os.environ.get("ADEVX_RETRY_MAX_DELAY", "4.0")),
            circuit_fail_threshold=int(os.environ.get("ADEVX_CIRCUIT_FAIL_THRESHOLD", "3")),
            circuit_recovery_s=float(os.environ.get("ADEVX_CIRCUIT_RECOVERY_S", "10")),
            log_level=os.environ.get("ADEVX_LOG_LEVEL", "INFO").upper(),
            enable_telemetry=os.environ.get("ADEVX_TELEMETRY", "1").strip().lower() not in {"0", "false", "no"},
            queue_max_size=int(os.environ.get("ADEVX_EVENT_QUEUE_MAX", "1000")),
        )

