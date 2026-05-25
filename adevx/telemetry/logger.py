"""Structured logging with JSON-like payload formatting."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass(slots=True)
class StructuredLogger:
    name: str = "adevx"
    level: str = "INFO"
    _logger: logging.Logger = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._logger = logging.getLogger(self.name)
        if not self._logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter("%(message)s")
            handler.setFormatter(formatter)
            self._logger.addHandler(handler)
        self._logger.setLevel(getattr(logging, self.level.upper(), logging.INFO))

    def _emit(self, severity: str, message: str, **fields: Any) -> None:
        payload = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": severity.upper(),
            "logger": self.name,
            "msg": message,
            **fields,
        }
        line = json.dumps(payload, ensure_ascii=True, default=str)
        getattr(self._logger, severity.lower(), self._logger.info)(line)

    def debug(self, message: str, **fields: Any) -> None:
        self._emit("debug", message, **fields)

    def info(self, message: str, **fields: Any) -> None:
        self._emit("info", message, **fields)

    def warning(self, message: str, **fields: Any) -> None:
        self._emit("warning", message, **fields)

    def error(self, message: str, **fields: Any) -> None:
        self._emit("error", message, **fields)
