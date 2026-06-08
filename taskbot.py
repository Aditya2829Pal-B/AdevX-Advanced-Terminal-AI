#!/usr/bin/env python
"""
AdevX: a practical "do-many-tasks" chatbot starter.

Features:
- Interactive CLI chat.
- Optional online tool-calling mode (OpenAI/OpenRouter/Groq).
- Local fallback mode with slash commands if no API key is present.
- Built-in tools: file operations, search, calculator, URL fetch, shell commands.

This bot is intentionally transparent and extensible. It cannot literally do
"any task," but it provides a strong foundation for broad task automation.
"""

from __future__ import annotations

import argparse
import asyncio
import ast
import hashlib
import json
import math
import operator
import os
import re
import subprocess
import sys
import threading
import textwrap
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from adevx.core.git_intelligence import GitIntelligence
from adevx.rag.index import WorkspaceIndexAdapter
from adevx.telemetry.benchmarks import BenchmarkRunner


WORKSPACE_ROOT = Path.cwd().resolve()
MAX_FILE_READ_CHARS = 10_000
MAX_HTTP_CHARS = 12_000
MAX_TOOL_STEPS = 8
MAX_HISTORY_MESSAGES = 30
DEVELOPER_CREDIT = "Developed by [Aditya Pal](https://adityapal.vercel.app)"
ABOUT_TEXT = (
    "I'm AdevX, an AI assistant developed by "
    "[Aditya Pal](https://adityapal.vercel.app). I'm built for deep "
    "reasoning, coding, and reliable task execution. I can handle file "
    "operations, calculations, web/API tasks, command-line workflows, and "
    "structured problem-solving. I work in both online and offline modes, "
    "plan before acting, and verify outputs so results are practical and "
    "dependable."
)

CREATOR_PATTERNS = [
    r"\bwho\s+(made|created|developed)\s+(you|adevx)\b",
    r"\bwho\s+is\s+your\s+(creator|developer)\b",
    r"\bwho\s+developed\s+you\b",
    r"\bwho\s+created\s+you\b",
    r"\bdeveloper\s+name\b",
    r"\bcreated\s+by\b",
    r"\bdeveloped\s+by\b",
]

IDENTITY_PATTERNS = [
    r"\bwho\s+are\s+you\b",
    r"\bwhat\s+are\s+you\b",
    r"\bintroduce\s+yourself\b",
    r"\babout\s+you\b",
    r"\bwho\s+is\s+adevx\b",
]

LOCAL_FACTS: dict[str, str] = {
    "chatgpt": (
        "ChatGPT is a conversational AI assistant by OpenAI that can help with "
        "writing, coding, research, and task planning."
    ),
    "vin diesel": (
        "Vin Diesel (born Mark Sinclair) is an American actor and producer, best "
        "known for playing Dominic Toretto in the Fast & Furious films."
    ),
}

LOCAL_FACT_ALIASES: dict[str, str] = {
    "vin deisel": "vin diesel",
}

FREE_MODEL_CATALOG: dict[str, list[str]] = {
    "openrouter": ["openrouter/free"],
    "groq": ["llama-3.1-8b-instant", "openai/gpt-oss-20b", "openai/gpt-oss-120b"],
    "together": ["openai/gpt-oss-20b", "openai/gpt-oss-120b"],
    "ollama-local": [
        "gpt-oss:20b",
        "qwen3:30b",
        "llama3.1:70b",
        "deepseek-coder:33b",
        "qwen2.5:7b",
        "llama3.1:8b",
        "mistral:7b",
    ],
}

MODE_CATALOG: dict[str, dict[str, str]] = {
    "chat": {
        "summary": "General conversation, Q&A, and everyday tasks.",
        "instruction": (
            "Active mode is chat. Prioritize clear, natural answers and ask for "
            "clarification only when necessary."
        ),
    },
    "coding": {
        "summary": "Code generation, debugging, refactors, and architecture help.",
        "instruction": (
            "Active mode is coding. Default to production-quality code, include "
            "edge cases, and prefer concise technical explanations with complexity "
            "notes when relevant."
        ),
    },
    "image": {
        "summary": "Image-focused flow with file analysis and visual reasoning.",
        "instruction": (
            "Active mode is image. If a local image path is provided, analyze it "
            "first using tools, then answer based on detected metadata and content "
            "hints. Be explicit about limits when only metadata is available."
        ),
    },
    "research": {
        "summary": "Structured analysis, tradeoffs, and decision support.",
        "instruction": (
            "Active mode is research. Provide structured comparisons, assumptions, "
            "risks, and recommendation rationale."
        ),
    },
    "agent": {
        "summary": "Execution-first mode for multi-step task completion.",
        "instruction": (
            "Active mode is agent. Plan briefly, execute with tools when useful, "
            "verify results, and report concrete outcomes."
        ),
    },
}

MODE_ALIASES: dict[str, str] = {
    "default": "chat",
    "general": "chat",
    "normal": "chat",
    "code": "coding",
    "dev": "coding",
    "developer": "coding",
    "img": "image",
    "vision": "image",
    "analyze": "image",
    "analysis": "research",
    "study": "research",
    "auto": "agent",
    "autonomous": "agent",
    "tools": "agent",
}

SUPPORTED_IMAGE_SUFFIXES = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".bmp",
    ".webp",
}

BASE_DEVELOPER_PROMPT = (
    "You are AdevX, an expert AI assistant focused on deep reasoning, coding "
    "quality, and reliable task completion. Work like a strong pair programmer "
    "and researcher: clarify ambiguous intent when needed, plan before acting, "
    "use tools for verifiable facts, and check your work before final answers. "
    "Keep responses concise, but include enough detail to be useful. Never "
    "invent tool results. When you change files, mention what changed and why. "
    "AdevX was developed by Aditya Pal. If asked who developed or created you, "
    "answer exactly: 'Developed by Aditya Pal.' Never attribute development to "
    "AdevX itself. Follow this workflow: PLAN -> ANALYZE -> EXECUTE -> VERIFY -> "
    "IMPROVE. If uncertain, state uncertainty clearly."
)


def normalize_mode_name(mode: str) -> str | None:
    key = re.sub(r"\s+", " ", mode.strip().lower())
    if not key:
        return None
    if key in MODE_CATALOG:
        return key
    return MODE_ALIASES.get(key)


def mode_instruction_text(mode: str) -> str:
    data = MODE_CATALOG.get(mode)
    if not data:
        return ""
    return data.get("instruction", "").strip()


def modes_text() -> str:
    lines = ["Available modes:"]
    for name, data in MODE_CATALOG.items():
        lines.append(f"- {name}: {data['summary']}")
    lines.append("Switch with: /mode <name>")
    return "\n".join(lines)


def is_creator_query(lower_text: str) -> bool:
    return any(re.search(pattern, lower_text) for pattern in CREATOR_PATTERNS)


def is_identity_query(lower_text: str) -> bool:
    return any(re.search(pattern, lower_text) for pattern in IDENTITY_PATTERNS)


def looks_like_math_expression(text: str) -> bool:
    if not re.search(r"\d", text):
        return False
    return bool(re.fullmatch(r"[0-9A-Za-z_\s\+\-\*\/\%\.\(\),]+", text))


def normalize_fact_key(text: str) -> str:
    key = re.sub(r"\s+", " ", text.strip().lower())
    return LOCAL_FACT_ALIASES.get(key, key)


def parse_parameter_size_to_billions(value: str | None) -> float:
    """
    Parse strings like '70.6B', '20.9B', '776M' into billions.
    """
    if not value:
        return 0.0
    raw = value.strip().upper()
    match = re.match(r"^\s*([0-9]+(?:\.[0-9]+)?)\s*([BM])\s*$", raw)
    if not match:
        return 0.0
    num = float(match.group(1))
    unit = match.group(2)
    if unit == "B":
        return num
    if unit == "M":
        return num / 1000.0
    return 0.0


def ollama_api_root(api_base: str) -> str:
    base = api_base.rstrip("/")
    if base.endswith("/v1"):
        return base[: -len("/v1")]
    return base


def model_aliases(model_name: str) -> set[str]:
    name = model_name.strip()
    aliases = {name}
    if ":" in name:
        base, tag = name.split(":", 1)
        if tag == "latest":
            aliases.add(base)
    else:
        aliases.add(f"{name}:latest")
    return aliases


def run_async(coro: Any) -> Any:
    return asyncio.run(coro)


class MemoryStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or (WORKSPACE_ROOT / ".adevx_memory.json")
        self._data: dict[str, Any] = {
            "notes": [],
            "records": [],
            "project_memory": {},
            "summaries": [],
        }
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                notes = raw.get("notes", [])
                if isinstance(notes, list):
                    clean_notes = [str(x).strip() for x in notes if str(x).strip()]
                    self._data["notes"] = clean_notes[:200]
                records = raw.get("records", [])
                if isinstance(records, list):
                    clean_records: list[dict[str, Any]] = []
                    for item in records:
                        if not isinstance(item, dict):
                            continue
                        text = str(item.get("text", "")).strip()
                        if not text:
                            continue
                        clean_records.append(
                            {
                                "text": text,
                                "kind": str(item.get("kind", "conversation")),
                                "created_at": str(item.get("created_at", "")) or time.strftime("%Y-%m-%dT%H:%M:%S"),
                                "metadata": dict(item.get("metadata", {})) if isinstance(item.get("metadata"), dict) else {},
                            }
                        )
                    self._data["records"] = clean_records[-500:]
                project_memory = raw.get("project_memory", {})
                if isinstance(project_memory, dict):
                    clean_projects: dict[str, list[str]] = {}
                    for key, values in project_memory.items():
                        if not isinstance(values, list):
                            continue
                        clean_projects[str(key)] = [str(x).strip() for x in values if str(x).strip()][-120:]
                    self._data["project_memory"] = clean_projects
                summaries = raw.get("summaries", [])
                if isinstance(summaries, list):
                    self._data["summaries"] = [str(x).strip() for x in summaries if str(x).strip()][-50:]
        except Exception:
            self._data = {"notes": [], "records": [], "project_memory": {}, "summaries": []}

    def _save(self) -> None:
        self.path.write_text(json.dumps(self._data, indent=2), encoding="utf-8")

    def add_note(self, note: str) -> None:
        note = note.strip()
        if not note:
            return
        notes = self._data.setdefault("notes", [])
        if note not in notes:
            notes.append(note)
            # Keep bounded memory.
            if len(notes) > 200:
                del notes[0 : len(notes) - 200]
        self.add_record(
            note,
            kind="semantic",
            metadata={"source": "remember", "project": WORKSPACE_ROOT.name},
            save=False,
        )
        self._save()

    def add_record(
        self,
        text: str,
        *,
        kind: str = "conversation",
        metadata: dict[str, Any] | None = None,
        save: bool = True,
    ) -> None:
        value = text.strip()
        if not value:
            return
        records = self._data.setdefault("records", [])
        records.append(
            {
                "text": value,
                "kind": kind.strip().lower() or "conversation",
                "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "metadata": {
                    "project": WORKSPACE_ROOT.name,
                    **(metadata or {}),
                },
            }
        )
        if len(records) > 500:
            del records[0 : len(records) - 500]
        project = str((metadata or {}).get("project", WORKSPACE_ROOT.name)).strip()
        if project:
            project_memory = self._data.setdefault("project_memory", {}).setdefault(project, [])
            if value not in project_memory:
                project_memory.append(value)
                if len(project_memory) > 120:
                    del project_memory[0 : len(project_memory) - 120]
        if save:
            self._save()

    def clear(self) -> None:
        self._data = {"notes": [], "records": [], "project_memory": {}, "summaries": []}
        self._save()

    def notes(self, limit: int = 20) -> list[str]:
        notes = self._data.get("notes", [])
        if not isinstance(notes, list):
            return []
        return [str(x) for x in notes][-limit:]

    def formatted_context(self, limit: int = 10) -> str:
        notes = self.notes(limit=limit)
        if not notes:
            return ""
        lines = ["User memory notes:"]
        for note in notes:
            lines.append(f"- {note}")
        return "\n".join(lines)

    @staticmethod
    def _terms(text: str) -> list[str]:
        return re.findall(r"[a-zA-Z_][a-zA-Z0-9_]{1,}", text.lower())

    def search_records(self, query: str, limit: int = 8) -> list[dict[str, Any]]:
        question = query.strip()
        if not question:
            return []
        q_terms = set(self._terms(question))
        if not q_terms:
            return []
        scored: list[tuple[float, dict[str, Any]]] = []
        for record in self._data.get("records", []):
            if not isinstance(record, dict):
                continue
            text = str(record.get("text", ""))
            terms = set(self._terms(text))
            overlap = len(q_terms & terms)
            if overlap <= 0:
                continue
            kind = str(record.get("kind", "conversation"))
            kind_boost = {
                "semantic": 0.25,
                "project": 0.2,
                "episodic": 0.14,
                "summary": 0.12,
                "conversation": 0.08,
            }.get(kind, 0.05)
            score = overlap / max(1, len(q_terms)) + kind_boost
            scored.append((score, record))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [record for _, record in scored[: max(1, limit)]]

    def stats_text(self) -> str:
        records = self._data.get("records", [])
        if not isinstance(records, list):
            records = []
        kind_counts: dict[str, int] = {}
        for record in records:
            if not isinstance(record, dict):
                continue
            kind = str(record.get("kind", "conversation"))
            kind_counts[kind] = kind_counts.get(kind, 0) + 1
        project_counts = {
            key: len(values)
            for key, values in self._data.get("project_memory", {}).items()
            if isinstance(values, list)
        }
        lines = ["Memory stats:"]
        lines.append(f"- notes: {len(self._data.get('notes', []))}")
        lines.append(f"- records: {len(records)}")
        lines.append(f"- summaries: {len(self._data.get('summaries', []))}")
        if kind_counts:
            lines.append("- kinds: " + ", ".join(f"{key}={value}" for key, value in sorted(kind_counts.items())))
        if project_counts:
            lines.append("- project memory: " + ", ".join(f"{key}={value}" for key, value in sorted(project_counts.items())))
        return "\n".join(lines)

    def search_text(self, query: str) -> str:
        hits = self.search_records(query, limit=10)
        if not hits:
            return f"No memory matched '{query}'."
        lines = [f"Memory search for '{query}':"]
        for record in hits:
            lines.append(f"- [{record.get('kind', 'conversation')}] {record.get('text', '')}")
        return "\n".join(lines)

    def consolidate_text(self, keep_recent: int = 80) -> str:
        records = list(self._data.get("records", []))
        if not records:
            return "Memory is empty."
        deduped: list[dict[str, Any]] = []
        seen: set[str] = set()
        for record in reversed(records):
            if not isinstance(record, dict):
                continue
            text = str(record.get("text", "")).strip()
            key = text.lower()
            if not text or key in seen:
                continue
            seen.add(key)
            deduped.append(record)
        deduped.reverse()

        collapsed = max(0, len(deduped) - keep_recent)
        older = deduped[:collapsed]
        recent = deduped[collapsed:]
        if not older:
            return "Memory is already compact."

        counter: dict[str, int] = {}
        for record in older:
            for term in self._terms(str(record.get("text", ""))):
                if len(term) < 4:
                    continue
                counter[term] = counter.get(term, 0) + 1
        topics = [term for term, _count in sorted(counter.items(), key=lambda item: item[1], reverse=True)[:8]]
        summary = "Memory consolidation: " + ", ".join(topics) if topics else "Memory consolidation summary"
        self._data.setdefault("summaries", []).append(summary)
        self.add_record(summary, kind="summary", metadata={"source": "consolidate"}, save=False)
        self._data["records"] = recent[-500:]
        if len(self._data["summaries"]) > 50:
            del self._data["summaries"][0 : len(self._data["summaries"]) - 50]
        self._save()
        return f"Consolidated {len(older)} records.\n{summary}"


class ProjectRAGStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or (WORKSPACE_ROOT / ".adevx_rag_index.json")
        self._data: dict[str, Any] = {
            "version": 1,
            "enabled": True,
            "built_at": 0,
            "files_indexed": 0,
            "chunks_indexed": 0,
            "chunk_lines": 60,
            "overlap_lines": 15,
            "chunks": [],
            "df": {},
        }
        self._stopwords = {
            "the",
            "and",
            "for",
            "with",
            "that",
            "this",
            "from",
            "into",
            "your",
            "you",
            "are",
            "was",
            "were",
            "have",
            "has",
            "had",
            "not",
            "but",
            "can",
            "will",
            "all",
            "any",
            "use",
            "using",
            "used",
            "then",
            "else",
            "when",
            "what",
            "who",
            "how",
            "why",
            "let",
            "get",
            "set",
            "new",
        }
        self._allowed_suffixes = {
            ".py",
            ".js",
            ".ts",
            ".tsx",
            ".jsx",
            ".java",
            ".c",
            ".cc",
            ".cpp",
            ".cxx",
            ".h",
            ".hpp",
            ".cs",
            ".go",
            ".rs",
            ".rb",
            ".php",
            ".swift",
            ".kt",
            ".kts",
            ".m",
            ".mm",
            ".scala",
            ".sql",
            ".json",
            ".yaml",
            ".yml",
            ".toml",
            ".ini",
            ".md",
            ".txt",
            ".html",
            ".css",
            ".scss",
            ".xml",
            ".sh",
            ".ps1",
            ".bat",
        }
        self._skip_dirs = {
            ".git",
            ".adevx_test_tmp",
            "__pycache__",
            "node_modules",
            ".venv",
            "venv",
            ".mypy_cache",
            ".pytest_cache",
            "dist",
            "build",
            "target",
            ".idea",
            ".vscode",
        }
        self._max_file_chars = 120_000
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                self._data.update(raw)
                # Basic shape hardening
                if not isinstance(self._data.get("chunks"), list):
                    self._data["chunks"] = []
                if not isinstance(self._data.get("df"), dict):
                    self._data["df"] = {}
        except Exception:
            # Keep defaults if corrupted.
            pass

    def _save(self) -> None:
        self.path.write_text(json.dumps(self._data, indent=2), encoding="utf-8")

    @property
    def enabled(self) -> bool:
        return bool(self._data.get("enabled", True))

    def set_enabled(self, enabled: bool) -> None:
        self._data["enabled"] = bool(enabled)
        self._save()

    def _iter_files(self) -> list[Path]:
        files: list[Path] = []
        root_parts = set(WORKSPACE_ROOT.parts)
        for path in WORKSPACE_ROOT.rglob("*"):
            if not path.is_file():
                continue
            if any(part in self._skip_dirs and part not in root_parts for part in path.parts):
                continue
            if path.name.startswith(".adevx_"):
                continue
            suffix = path.suffix.lower()
            if suffix and suffix not in self._allowed_suffixes:
                continue
            files.append(path)
        return files

    def _terms(self, text: str) -> list[str]:
        tokens = re.findall(r"[A-Za-z_][A-Za-z0-9_]{1,}", text.lower())
        return [t for t in tokens if t not in self._stopwords and len(t) >= 2]

    def _chunk_file(self, rel_path: str, text: str, chunk_lines: int, overlap_lines: int) -> list[dict[str, Any]]:
        lines = text.splitlines()
        if not lines:
            return []
        step = max(1, chunk_lines - overlap_lines)
        chunks: list[dict[str, Any]] = []
        for start_idx in range(0, len(lines), step):
            end_idx = min(len(lines), start_idx + chunk_lines)
            block_lines = lines[start_idx:end_idx]
            block_text = "\n".join(block_lines).strip()
            if len(block_text) < 40:
                if end_idx >= len(lines):
                    break
                continue
            terms = self._terms(block_text)
            if not terms:
                if end_idx >= len(lines):
                    break
                continue
            tf: dict[str, int] = {}
            for term in terms:
                tf[term] = tf.get(term, 0) + 1
            chunks.append(
                {
                    "path": rel_path,
                    "start": start_idx + 1,
                    "end": end_idx,
                    "text": block_text,
                    "tf": tf,
                }
            )
            if end_idx >= len(lines):
                break
        return chunks

    def rebuild(self, chunk_lines: int = 60, overlap_lines: int = 15) -> str:
        files = self._iter_files()
        all_chunks: list[dict[str, Any]] = []
        df: dict[str, int] = {}
        files_indexed = 0

        for path in files:
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if not text.strip():
                continue
            text = text[: self._max_file_chars]
            rel = str(path.relative_to(WORKSPACE_ROOT))
            chunks = self._chunk_file(rel, text, chunk_lines=chunk_lines, overlap_lines=overlap_lines)
            if not chunks:
                continue
            files_indexed += 1
            all_chunks.extend(chunks)
            for chunk in chunks:
                unique_terms = set(chunk["tf"].keys())
                for term in unique_terms:
                    df[term] = df.get(term, 0) + 1

        self._data.update(
            {
                "version": 1,
                "built_at": int(time.time()),
                "files_indexed": files_indexed,
                "chunks_indexed": len(all_chunks),
                "chunk_lines": chunk_lines,
                "overlap_lines": overlap_lines,
                "chunks": all_chunks,
                "df": df,
            }
        )
        self._save()
        return (
            f"RAG index rebuilt: {files_indexed} files, "
            f"{len(all_chunks)} chunks (chunk_lines={chunk_lines}, overlap={overlap_lines})."
        )

    def _idf(self, term: str) -> float:
        chunks = self._data.get("chunks", [])
        n_docs = max(1, len(chunks))
        df_map = self._data.get("df", {})
        df = int(df_map.get(term, 0))
        return math.log((n_docs + 1) / (df + 1)) + 1.0

    def query(self, text: str, top_k: int = 4) -> list[dict[str, Any]]:
        chunks = self._data.get("chunks", [])
        if not isinstance(chunks, list) or not chunks:
            return []
        q_terms = self._terms(text)
        if not q_terms:
            return []
        q_unique = list(dict.fromkeys(q_terms))
        q_lower = text.lower()

        scored: list[tuple[float, dict[str, Any]]] = []
        for chunk in chunks:
            if not isinstance(chunk, dict):
                continue
            tf = chunk.get("tf", {})
            if not isinstance(tf, dict):
                continue
            score = 0.0
            for term in q_unique:
                freq = int(tf.get(term, 0))
                if freq <= 0:
                    continue
                score += (1.0 + math.log(freq)) * self._idf(term)
            block_text = str(chunk.get("text", "")).lower()
            if q_lower and q_lower in block_text:
                score += 3.0
            if score > 0:
                scored.append((score, chunk))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [chunk for _, chunk in scored[:top_k]]

    def retrieve_context(self, question: str, top_k: int = 4, max_chars: int = 3500) -> str:
        if not self.enabled:
            return ""
        hits = self.query(question, top_k=top_k)
        if not hits:
            return ""
        parts = ["Project context (retrieved from workspace index):"]
        total = len(parts[0])
        for hit in hits:
            path = hit.get("path", "")
            start = hit.get("start", 1)
            end = hit.get("end", start)
            block = str(hit.get("text", "")).strip()
            snippet = f"[{path}:{start}-{end}]\n{block}"
            if total + len(snippet) > max_chars:
                remaining = max(0, max_chars - total - 20)
                if remaining > 80:
                    snippet = snippet[:remaining] + "\n...[truncated]"
                else:
                    break
            parts.append(snippet)
            total += len(snippet)
            if total >= max_chars:
                break
        return "\n\n".join(parts)

    def status_text(self) -> str:
        built_at = int(self._data.get("built_at", 0) or 0)
        if built_at > 0:
            built_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(built_at))
        else:
            built_str = "never"
        return (
            f"RAG enabled: {self.enabled}\n"
            f"Files indexed: {self._data.get('files_indexed', 0)}\n"
            f"Chunks indexed: {self._data.get('chunks_indexed', 0)}\n"
            f"Last build: {built_str}"
        )


class PhaseProgressStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or (WORKSPACE_ROOT / ".adevx_phase_progress.json")
        self._data: dict[str, Any] = {
            "last_run_at": 0,
            "phase": "phase2",
            "steps": [],
            "benchmark": {},
        }
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                self._data.update(raw)
        except Exception:
            pass

    def _save(self) -> None:
        self.path.write_text(json.dumps(self._data, indent=2), encoding="utf-8")

    def update(self, phase: str, steps: list[dict[str, Any]], benchmark: dict[str, Any]) -> None:
        self._data["last_run_at"] = int(time.time())
        self._data["phase"] = phase
        self._data["steps"] = steps
        self._data["benchmark"] = benchmark
        self._save()

    def status_text(self) -> str:
        ts = int(self._data.get("last_run_at", 0) or 0)
        if ts > 0:
            when = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts))
        else:
            when = "never"
        phase = str(self._data.get("phase", "unknown"))
        benchmark = self._data.get("benchmark", {})
        score = benchmark.get("score")
        score_part = f"{score}/100" if isinstance(score, int) else "n/a"
        return (
            f"Phase status: {phase}\n"
            f"Last run: {when}\n"
            f"Benchmark score (internal heuristic): {score_part}"
        )

class ToolError(Exception):
    """Raised when a tool fails with a user-facing message."""


def _ensure_within_workspace(path: Path) -> Path:
    """Ensure path stays inside workspace root."""
    path = path.resolve()
    if path == WORKSPACE_ROOT:
        return path
    if WORKSPACE_ROOT not in path.parents:
        raise ToolError(
            f"Path '{path}' is outside workspace '{WORKSPACE_ROOT}'. "
            "For safety, this bot only edits files inside the workspace."
        )
    return path


def resolve_user_path(path_str: str) -> Path:
    """Resolve a user path relative to workspace root."""
    raw = Path(path_str).expanduser()
    target = raw if raw.is_absolute() else (WORKSPACE_ROOT / raw)
    return _ensure_within_workspace(target)


def _jpeg_dimensions(data: bytes) -> tuple[int, int] | None:
    if len(data) < 4 or data[:2] != b"\xff\xd8":
        return None
    idx = 2
    sof_markers = {
        0xC0,
        0xC1,
        0xC2,
        0xC3,
        0xC5,
        0xC6,
        0xC7,
        0xC9,
        0xCA,
        0xCB,
        0xCD,
        0xCE,
        0xCF,
    }
    while idx + 9 < len(data):
        if data[idx] != 0xFF:
            idx += 1
            continue
        marker = data[idx + 1]
        idx += 2
        if marker in {0xD8, 0xD9, 0x01} or 0xD0 <= marker <= 0xD7:
            continue
        if idx + 2 > len(data):
            break
        seg_len = int.from_bytes(data[idx : idx + 2], "big")
        if seg_len < 2 or idx + seg_len > len(data):
            break
        if marker in sof_markers and seg_len >= 7:
            height = int.from_bytes(data[idx + 3 : idx + 5], "big")
            width = int.from_bytes(data[idx + 5 : idx + 7], "big")
            if width > 0 and height > 0:
                return width, height
            break
        idx += seg_len
    return None


def _detect_image_format_and_dimensions(data: bytes) -> tuple[str, tuple[int, int] | None]:
    if len(data) >= 24 and data.startswith(b"\x89PNG\r\n\x1a\n"):
        width = int.from_bytes(data[16:20], "big")
        height = int.from_bytes(data[20:24], "big")
        return "png", (width, height) if width > 0 and height > 0 else None

    if len(data) >= 10 and (data.startswith(b"GIF87a") or data.startswith(b"GIF89a")):
        width = int.from_bytes(data[6:8], "little")
        height = int.from_bytes(data[8:10], "little")
        return "gif", (width, height) if width > 0 and height > 0 else None

    if len(data) >= 26 and data.startswith(b"BM"):
        dib_header_size = int.from_bytes(data[14:18], "little")
        if dib_header_size >= 12:
            if dib_header_size == 12 and len(data) >= 26:
                width = int.from_bytes(data[18:20], "little")
                height = int.from_bytes(data[20:22], "little")
            elif len(data) >= 26:
                width = int.from_bytes(data[18:22], "little", signed=True)
                height = int.from_bytes(data[22:26], "little", signed=True)
                width = abs(width)
                height = abs(height)
            else:
                width, height = 0, 0
            if width > 0 and height > 0:
                return "bmp", (width, height)
        return "bmp", None

    if len(data) >= 30 and data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        chunk = data[12:16]
        if chunk == b"VP8X" and len(data) >= 30:
            width_minus_one = int.from_bytes(data[24:27], "little")
            height_minus_one = int.from_bytes(data[27:30], "little")
            return "webp", (width_minus_one + 1, height_minus_one + 1)
        if chunk == b"VP8 " and len(data) >= 30:
            start = data.find(b"\x9d\x01\x2a", 20)
            if start != -1 and start + 7 < len(data):
                width = int.from_bytes(data[start + 3 : start + 5], "little") & 0x3FFF
                height = int.from_bytes(data[start + 5 : start + 7], "little") & 0x3FFF
                if width > 0 and height > 0:
                    return "webp", (width, height)
            return "webp", None
        if chunk == b"VP8L" and len(data) >= 25:
            b0, b1, b2, b3 = data[21], data[22], data[23], data[24]
            width = 1 + (((b1 & 0x3F) << 8) | b0)
            height = 1 + (((b3 & 0x0F) << 10) | (b2 << 2) | ((b1 & 0xC0) >> 6))
            if width > 0 and height > 0:
                return "webp", (width, height)
            return "webp", None
        return "webp", None

    if data.startswith(b"\xff\xd8"):
        return "jpeg", _jpeg_dimensions(data)

    return "unknown", None


def tool_analyze_image(path: str) -> str:
    target = resolve_user_path(path)
    if not target.exists():
        raise ToolError(f"File not found: {target}")
    if not target.is_file():
        raise ToolError(f"Not a file: {target}")

    suffix = target.suffix.lower()
    if suffix not in SUPPORTED_IMAGE_SUFFIXES:
        raise ToolError(
            "Unsupported image type. Use one of: "
            + ", ".join(sorted(SUPPORTED_IMAGE_SUFFIXES))
        )

    try:
        data = target.read_bytes()
    except OSError as exc:
        raise ToolError(f"Failed to read image: {exc}") from exc

    if not data:
        raise ToolError("Image file is empty.")

    detected_format, dims = _detect_image_format_and_dimensions(data)
    sha = hashlib.sha256(data).hexdigest()
    rel = target.relative_to(WORKSPACE_ROOT)

    lines = [f"Image: {rel}"]
    lines.append(f"Extension: {suffix or '(none)'}")
    lines.append(f"Detected format: {detected_format}")
    lines.append(f"File size: {len(data)} bytes")
    lines.append(f"SHA256: {sha}")
    if dims is not None:
        width, height = dims
        lines.append(f"Dimensions: {width} x {height}")
        lines.append(f"Megapixels: {(width * height) / 1_000_000:.2f} MP")
    else:
        lines.append("Dimensions: unavailable from header parsing")
    lines.append(
        "Tip: Ask in image mode for interpretation, e.g. `/mode image` then "
        "`summarize this image metadata`."
    )
    return "\n".join(lines)


def tool_list_files(path: str = ".") -> str:
    target = resolve_user_path(path)
    if not target.exists():
        raise ToolError(f"Path not found: {target}")
    if not target.is_dir():
        raise ToolError(f"Not a directory: {target}")

    entries = sorted(target.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
    if not entries:
        return f"{target}\n(empty directory)"

    lines = [f"{target}"]
    max_entries = 300
    for idx, item in enumerate(entries):
        if idx >= max_entries:
            lines.append(f"... ({len(entries) - max_entries} more entries)")
            break
        marker = "/" if item.is_dir() else ""
        lines.append(f"- {item.name}{marker}")
    return "\n".join(lines)


def tool_read_file(path: str, max_chars: int = MAX_FILE_READ_CHARS) -> str:
    target = resolve_user_path(path)
    if not target.exists():
        raise ToolError(f"File not found: {target}")
    if not target.is_file():
        raise ToolError(f"Not a file: {target}")

    data = target.read_text(encoding="utf-8", errors="replace")
    if len(data) <= max_chars:
        return data
    return data[:max_chars] + f"\n\n[Truncated to {max_chars} characters]"


def tool_write_file(path: str, content: str) -> str:
    target = resolve_user_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return f"Wrote {len(content)} characters to {target}"


def tool_append_file(path: str, content: str) -> str:
    target = resolve_user_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as handle:
        handle.write(content)
    return f"Appended {len(content)} characters to {target}"


def tool_search_text(query: str, path: str = ".", file_glob: str = "*") -> str:
    target = resolve_user_path(path)
    if not target.exists():
        raise ToolError(f"Path not found: {target}")
    if not target.is_dir():
        raise ToolError(f"Not a directory: {target}")

    pattern = re.compile(re.escape(query), flags=re.IGNORECASE)
    matches: list[str] = []
    max_matches = 120

    for file_path in target.rglob(file_glob):
        if not file_path.is_file():
            continue
        try:
            text = file_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        for lineno, line in enumerate(text.splitlines(), start=1):
            if pattern.search(line):
                rel = file_path.relative_to(WORKSPACE_ROOT)
                snippet = line.strip()
                if len(snippet) > 160:
                    snippet = snippet[:160] + "..."
                matches.append(f"{rel}:{lineno}: {snippet}")
                if len(matches) >= max_matches:
                    break
        if len(matches) >= max_matches:
            break

    if not matches:
        return f"No matches for '{query}'."
    if len(matches) == max_matches:
        matches.append("... (truncated)")
    return "\n".join(matches)


_BIN_OPS: dict[type[ast.AST], Callable[[Any, Any], Any]] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}

_UNARY_OPS: dict[type[ast.AST], Callable[[Any], Any]] = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}

_MATH_FUNCS: dict[str, Callable[..., Any]] = {
    "abs": abs,
    "round": round,
    "sqrt": math.sqrt,
    "sin": math.sin,
    "cos": math.cos,
    "tan": math.tan,
    "log": math.log,
    "log10": math.log10,
    "exp": math.exp,
    "floor": math.floor,
    "ceil": math.ceil,
}
_MATH_CONSTS: dict[str, float] = {"pi": math.pi, "e": math.e}


def _eval_node(node: ast.AST) -> Any:
    if isinstance(node, ast.Expression):
        return _eval_node(node.body)

    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float)):
            return node.value
        raise ToolError("Only numeric constants are allowed.")

    if isinstance(node, ast.Name):
        if node.id in _MATH_CONSTS:
            return _MATH_CONSTS[node.id]
        raise ToolError(f"Name '{node.id}' is not allowed.")

    if isinstance(node, ast.BinOp):
        op_type = type(node.op)
        if op_type not in _BIN_OPS:
            raise ToolError(f"Operator {op_type.__name__} is not allowed.")
        return _BIN_OPS[op_type](_eval_node(node.left), _eval_node(node.right))

    if isinstance(node, ast.UnaryOp):
        op_type = type(node.op)
        if op_type not in _UNARY_OPS:
            raise ToolError(f"Unary operator {op_type.__name__} is not allowed.")
        return _UNARY_OPS[op_type](_eval_node(node.operand))

    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name):
            raise ToolError("Only simple function calls are allowed.")
        func_name = node.func.id
        func = _MATH_FUNCS.get(func_name)
        if func is None:
            raise ToolError(f"Function '{func_name}' is not allowed.")
        args = [_eval_node(arg) for arg in node.args]
        return func(*args)

    raise ToolError(f"Unsupported expression node: {type(node).__name__}")


def tool_calculate(expression: str) -> str:
    try:
        tree = ast.parse(expression, mode="eval")
        value = _eval_node(tree)
    except (SyntaxError, ValueError, ZeroDivisionError, OverflowError) as exc:
        raise ToolError(f"Calculation failed: {exc}") from exc
    except TypeError as exc:
        raise ToolError(f"Invalid arguments: {exc}") from exc
    return f"{value}"


def tool_fetch_url(url: str) -> str:
    if not url.startswith(("http://", "https://")):
        raise ToolError("URL must start with http:// or https://")

    req = urllib.request.Request(
        url,
        headers={"User-Agent": "AdevX/1.0 (+https://example.local)"},
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            body = resp.read(MAX_HTTP_CHARS + 1).decode("utf-8", errors="replace")
            status = resp.status
            final_url = resp.geturl()
    except urllib.error.URLError as exc:
        raise ToolError(f"Request failed: {exc}") from exc

    truncated = len(body) > MAX_HTTP_CHARS
    if truncated:
        body = body[:MAX_HTTP_CHARS] + "\n\n[Truncated]"

    return f"Status: {status}\nURL: {final_url}\n\n{body}"


def tool_run_shell(
    command: str,
    timeout_seconds: int = 30,
    approval_callback: Callable[[str], bool] | None = None,
) -> str:
    if not command.strip():
        raise ToolError("Command cannot be empty.")

    if approval_callback is not None and not approval_callback(command):
        return "Shell command canceled by user."

    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            cwd=str(WORKSPACE_ROOT),
        )
    except subprocess.TimeoutExpired:
        raise ToolError(f"Command timed out after {timeout_seconds} seconds.")

    out = result.stdout.strip()
    err = result.stderr.strip()
    parts = [f"Exit code: {result.returncode}"]
    if out:
        parts.append(f"STDOUT:\n{out}")
    if err:
        parts.append(f"STDERR:\n{err}")
    return "\n\n".join(parts)


def tool_summarize_text(text: str, max_sentences: int = 5) -> str:
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    sentences = [s for s in sentences if s]
    if not sentences:
        return "No text to summarize."

    words = re.findall(r"[A-Za-z]{3,}", text.lower())
    if not words:
        return "Summary: " + " ".join(sentences[:max_sentences])

    freq: dict[str, int] = {}
    for w in words:
        freq[w] = freq.get(w, 0) + 1

    def score(sentence: str) -> int:
        sent_words = re.findall(r"[A-Za-z]{3,}", sentence.lower())
        return sum(freq.get(w, 0) for w in sent_words)

    ranked = sorted(((score(s), idx, s) for idx, s in enumerate(sentences)), reverse=True)
    chosen = sorted(ranked[:max_sentences], key=lambda x: x[1])
    summary = " ".join(s for _, _, s in chosen)
    return summary.strip()


@dataclass
class ToolSpec:
    name: str
    description: str
    json_schema: dict[str, Any]
    handler: Callable[..., str]


@dataclass
class ProviderConfig:
    provider: str
    api_key: str
    api_base: str
    model: str
    extra_headers: dict[str, str]


def _clean_env_secret(value: str | None) -> str | None:
    """Trim env secrets and drop empty values."""
    if value is None:
        return None
    cleaned = value.strip()
    if not cleaned:
        return None
    return cleaned


def _pick_nonempty(*values: str | None, default: str) -> str:
    for value in values:
        if value is None:
            continue
        cleaned = value.strip()
        if cleaned:
            return cleaned
    return default


def _provider_chain_from_env(provider_pref: str) -> list[str]:
    valid = {"openai", "openrouter", "groq", "together", "ollama-local"}
    if provider_pref and provider_pref != "auto":
        return [provider_pref] if provider_pref in valid else []

    raw = os.environ.get(
        "ADEVX_PROVIDER_CHAIN",
        "openai,groq,openrouter,together",
    )
    names: list[str] = []
    for token in raw.split(","):
        name = token.strip().lower()
        if name and name in valid and name not in names:
            names.append(name)
    return names


def _build_provider_config(
    provider_name: str,
    model_override: str | None,
    api_base_override: str | None,
    *,
    generic_key: str | None,
    openai_key: str | None,
    openrouter_key: str | None,
    groq_key: str | None,
    together_key: str | None,
) -> ProviderConfig | None:
    if provider_name == "openai":
        key = generic_key or openai_key
        if not key:
            return None
        model = _pick_nonempty(
            model_override,
            os.environ.get("ADEVX_OPENAI_MODEL"),
            os.environ.get("ADEVX_MODEL"),
            os.environ.get("TASKBOT_MODEL"),
            default="gpt-4.1-mini",
        )
        api_base = _pick_nonempty(
            api_base_override,
            os.environ.get("ADEVX_OPENAI_BASE"),
            default="https://api.openai.com/v1",
        )
        return ProviderConfig(
            provider="openai",
            api_key=key,
            api_base=api_base.rstrip("/"),
            model=model,
            extra_headers={},
        )

    if provider_name == "openrouter":
        key = generic_key or openrouter_key
        if not key:
            return None
        model = _pick_nonempty(
            model_override,
            os.environ.get("ADEVX_OPENROUTER_MODEL"),
            os.environ.get("ADEVX_MODEL"),
            default="openrouter/free",
        )
        api_base = _pick_nonempty(
            api_base_override,
            os.environ.get("ADEVX_OPENROUTER_BASE"),
            default="https://openrouter.ai/api/v1",
        )
        referer = os.environ.get("ADEVX_OPENROUTER_REFERER", "https://localhost").strip()
        title = os.environ.get("ADEVX_OPENROUTER_TITLE", "AdevX").strip()
        headers: dict[str, str] = {}
        if referer:
            headers["HTTP-Referer"] = referer
        if title:
            headers["X-Title"] = title
        return ProviderConfig(
            provider="openrouter",
            api_key=key,
            api_base=api_base.rstrip("/"),
            model=model,
            extra_headers=headers,
        )

    if provider_name == "groq":
        key = generic_key or groq_key
        if not key:
            return None
        model = _pick_nonempty(
            model_override,
            os.environ.get("ADEVX_GROQ_MODEL"),
            os.environ.get("ADEVX_MODEL"),
            default="openai/gpt-oss-20b",
        )
        api_base = _pick_nonempty(
            api_base_override,
            os.environ.get("ADEVX_GROQ_BASE"),
            default="https://api.groq.com/openai/v1",
        )
        return ProviderConfig(
            provider="groq",
            api_key=key,
            api_base=api_base.rstrip("/"),
            model=model,
            extra_headers={},
        )

    if provider_name == "together":
        key = generic_key or together_key
        if not key:
            return None
        model = _pick_nonempty(
            model_override,
            os.environ.get("ADEVX_TOGETHER_MODEL"),
            os.environ.get("ADEVX_MODEL"),
            default="openai/gpt-oss-20b",
        )
        api_base = _pick_nonempty(
            api_base_override,
            os.environ.get("ADEVX_TOGETHER_BASE"),
            default="https://api.together.ai/v1",
        )
        return ProviderConfig(
            provider="together",
            api_key=key,
            api_base=api_base.rstrip("/"),
            model=model,
            extra_headers={},
        )

    if provider_name == "ollama-local":
        enabled = os.environ.get("ADEVX_ENABLE_OLLAMA", "1").strip().lower()
        if enabled in {"0", "false", "no"}:
            return None
        model = _pick_nonempty(
            model_override,
            os.environ.get("ADEVX_OLLAMA_MODEL"),
            os.environ.get("ADEVX_MODEL"),
            default="qwen2.5:7b",
        )
        api_base = _pick_nonempty(
            api_base_override,
            os.environ.get("ADEVX_OLLAMA_BASE"),
            default="http://localhost:11434/v1",
        )
        # Ollama ignores API key for compatibility mode.
        ollama_key = _clean_env_secret(os.environ.get("ADEVX_OLLAMA_API_KEY")) or "ollama"
        return ProviderConfig(
            provider="ollama-local",
            api_key=ollama_key,
            api_base=api_base.rstrip("/"),
            model=model,
            extra_headers={},
        )

    return None


def _resolve_provider_configs(
    model_override: str | None = None,
    provider_override: str | None = None,
) -> list[ProviderConfig]:
    provider_pref = (provider_override or os.environ.get("ADEVX_PROVIDER", "auto")).strip().lower()
    api_base_override = os.environ.get("ADEVX_API_BASE", "").strip() or None
    model_override = (model_override or "").strip() or None

    generic_key = _clean_env_secret(os.environ.get("ADEVX_API_KEY"))
    openai_key = _clean_env_secret(os.environ.get("OPENAI_API_KEY"))
    openrouter_key = _clean_env_secret(os.environ.get("OPENROUTER_API_KEY"))
    groq_key = _clean_env_secret(os.environ.get("GROQ_API_KEY"))
    together_key = _clean_env_secret(os.environ.get("TOGETHER_API_KEY"))

    configs: list[ProviderConfig] = []
    for name in _provider_chain_from_env(provider_pref):
        cfg = _build_provider_config(
            name,
            model_override,
            api_base_override,
            generic_key=generic_key,
            openai_key=openai_key,
            openrouter_key=openrouter_key,
            groq_key=groq_key,
            together_key=together_key,
        )
        if cfg:
            configs.append(cfg)
    return configs


def _resolve_provider_config(model_override: str | None = None) -> ProviderConfig | None:
    configs = _resolve_provider_configs(model_override=model_override, provider_override=None)
    return configs[0] if configs else None


class ToolRegistry:
    def __init__(self, approval_callback: Callable[[str], bool] | None = None) -> None:
        self.approval_callback = approval_callback
        self._tools: dict[str, ToolSpec] = {}
        self._register_defaults()

    def _register(self, spec: ToolSpec) -> None:
        self._tools[spec.name] = spec

    def _register_defaults(self) -> None:
        self._register(
            ToolSpec(
                name="list_files",
                description="List files and directories in a workspace path.",
                json_schema={
                    "type": "object",
                    "properties": {"path": {"type": "string", "default": "."}},
                    "required": [],
                },
                handler=lambda path=".": tool_list_files(path),
            )
        )
        self._register(
            ToolSpec(
                name="read_file",
                description="Read a text file in the workspace.",
                json_schema={
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                    "required": ["path"],
                },
                handler=lambda path: tool_read_file(path),
            )
        )
        self._register(
            ToolSpec(
                name="write_file",
                description="Write content to a file in the workspace.",
                json_schema={
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "content": {"type": "string"},
                    },
                    "required": ["path", "content"],
                },
                handler=lambda path, content: tool_write_file(path, content),
            )
        )
        self._register(
            ToolSpec(
                name="append_file",
                description="Append content to a file in the workspace.",
                json_schema={
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "content": {"type": "string"},
                    },
                    "required": ["path", "content"],
                },
                handler=lambda path, content: tool_append_file(path, content),
            )
        )
        self._register(
            ToolSpec(
                name="search_text",
                description="Search text in files under a workspace directory.",
                json_schema={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "path": {"type": "string", "default": "."},
                        "file_glob": {"type": "string", "default": "*"},
                    },
                    "required": ["query"],
                },
                handler=lambda query, path=".", file_glob="*": tool_search_text(
                    query, path, file_glob
                ),
            )
        )
        self._register(
            ToolSpec(
                name="calculate",
                description="Evaluate a safe arithmetic expression.",
                json_schema={
                    "type": "object",
                    "properties": {"expression": {"type": "string"}},
                    "required": ["expression"],
                },
                handler=lambda expression: tool_calculate(expression),
            )
        )
        self._register(
            ToolSpec(
                name="fetch_url",
                description="Fetch text content from an HTTP or HTTPS URL.",
                json_schema={
                    "type": "object",
                    "properties": {"url": {"type": "string"}},
                    "required": ["url"],
                },
                handler=lambda url: tool_fetch_url(url),
            )
        )
        self._register(
            ToolSpec(
                name="analyze_image",
                description=(
                    "Analyze a local image file and return detected format, dimensions, "
                    "size, and metadata summary."
                ),
                json_schema={
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                    "required": ["path"],
                },
                handler=lambda path: tool_analyze_image(path),
            )
        )
        self._register(
            ToolSpec(
                name="run_shell",
                description=(
                    "Run a shell command in the workspace. Use only when needed and "
                    "prefer read-only commands unless user requests file changes."
                ),
                json_schema={
                    "type": "object",
                    "properties": {
                        "command": {"type": "string"},
                        "timeout_seconds": {"type": "integer", "default": 30},
                    },
                    "required": ["command"],
                },
                handler=lambda command, timeout_seconds=30: tool_run_shell(
                    command=command,
                    timeout_seconds=timeout_seconds,
                    approval_callback=self.approval_callback,
                ),
            )
        )
        self._register(
            ToolSpec(
                name="summarize_text",
                description="Summarize a text passage into key sentences.",
                json_schema={
                    "type": "object",
                    "properties": {
                        "text": {"type": "string"},
                        "max_sentences": {"type": "integer", "default": 5},
                    },
                    "required": ["text"],
                },
                handler=lambda text, max_sentences=5: tool_summarize_text(
                    text, max_sentences
                ),
            )
        )

    def openai_tools(self) -> list[dict[str, Any]]:
        result = []
        for spec in self._tools.values():
            result.append(
                {
                    "type": "function",
                    "function": {
                        "name": spec.name,
                        "description": spec.description,
                        "parameters": spec.json_schema,
                    },
                }
            )
        return result

    def call(self, name: str, arguments: dict[str, Any]) -> str:
        spec = self._tools.get(name)
        if spec is None:
            raise ToolError(f"Unknown tool: {name}")
        try:
            return spec.handler(**arguments)
        except ToolError:
            raise
        except TypeError as exc:
            raise ToolError(f"Invalid arguments for {name}: {exc}") from exc
        except Exception as exc:
            raise ToolError(f"{name} failed: {exc}") from exc


class OnlineChatClient:
    def __init__(
        self,
        config: ProviderConfig,
        tool_registry: ToolRegistry,
        memory_store: MemoryStore | None = None,
        rag_store: ProjectRAGStore | None = None,
    ) -> None:
        self.provider = config.provider
        self.api_key = config.api_key.strip()
        self.model = config.model
        self.api_base = config.api_base.rstrip("/")
        self.extra_headers = dict(config.extra_headers)
        self.tools = tool_registry
        self.memory_store = memory_store
        self.rag_store = rag_store
        if self.provider == "ollama-local":
            self.request_timeout_s = float(os.environ.get("ADEVX_OLLAMA_TIMEOUT", "180"))
            self.max_tokens = int(os.environ.get("ADEVX_OLLAMA_MAX_TOKENS", "220"))
            self.max_history_messages = int(os.environ.get("ADEVX_OLLAMA_HISTORY", "10"))
        else:
            self.request_timeout_s = float(os.environ.get("ADEVX_REQUEST_TIMEOUT", "45"))
            self.max_tokens = int(os.environ.get("ADEVX_MAX_TOKENS", "600"))
            self.max_history_messages = MAX_HISTORY_MESSAGES
        self.mode = "chat"
        self.speed_profile = "balanced"
        self.history: list[dict[str, Any]] = [
            {
                "role": "developer",
                "content": BASE_DEVELOPER_PROMPT,
            }
        ]

    def set_mode(self, mode: str) -> None:
        normalized = normalize_mode_name(mode)
        self.mode = normalized or "chat"

    def _trim_history(self) -> None:
        if len(self.history) <= self.max_history_messages:
            return
        system_msg = self.history[0]
        tail = self.history[-(self.max_history_messages - 1) :]
        self.history = [system_msg, *tail]

    def set_speed_profile(self, profile: str) -> str:
        profile = profile.strip().lower()
        if profile not in {"fast", "balanced", "quality"}:
            return "Usage: /speed fast|balanced|quality"
        self.speed_profile = profile
        if self.provider == "ollama-local":
            if profile == "fast":
                self.max_tokens = 140
                self.max_history_messages = 8
            elif profile == "balanced":
                self.max_tokens = 220
                self.max_history_messages = 10
            else:
                self.max_tokens = 420
                self.max_history_messages = 18
        else:
            if profile == "fast":
                self.max_tokens = 300
                self.max_history_messages = 16
            elif profile == "balanced":
                self.max_tokens = 600
                self.max_history_messages = MAX_HISTORY_MESSAGES
            else:
                self.max_tokens = 1000
                self.max_history_messages = MAX_HISTORY_MESSAGES
        return (
            f"Speed set to {profile} for {self.provider} "
            f"(max_tokens={self.max_tokens}, history={self.max_history_messages})."
        )

    @staticmethod
    def _extract_text_content(content: Any) -> str:
        if isinstance(content, str):
            return content
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

    def _post_chat(self, messages: list[dict[str, Any]], use_tools: bool = True) -> dict[str, Any]:
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.2,
            "max_tokens": self.max_tokens,
        }
        if use_tools:
            payload["tools"] = self.tools.openai_tools()
            payload["tool_choice"] = "auto"

        body = json.dumps(payload).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        headers.update(self.extra_headers)
        req = urllib.request.Request(
            f"{self.api_base}/chat/completions",
            method="POST",
            data=body,
            headers=headers,
        )
        try:
            with urllib.request.urlopen(req, timeout=self.request_timeout_s) as resp:
                response = json.loads(resp.read().decode("utf-8"))
                return response
        except TimeoutError as exc:
            raise RuntimeError(
                f"{self.provider} API timed out after {self.request_timeout_s:.0f}s"
            ) from exc
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            message = raw
            code = ""
            try:
                parsed = json.loads(raw)
                err = parsed.get("error", {})
                if isinstance(err, dict):
                    message = err.get("message", raw)
                    code = err.get("code", "") or ""
            except json.JSONDecodeError:
                pass
            prefix = f"{self.provider} API HTTP error {exc.code}"
            if code:
                prefix += f" ({code})"
            raise RuntimeError(f"{prefix}: {message}") from exc
        except urllib.error.URLError as exc:
            reason = getattr(exc, "reason", "")
            if str(reason).lower().strip() == "timed out" or "timed out" in str(exc).lower():
                raise RuntimeError(
                    f"{self.provider} API timed out after {self.request_timeout_s:.0f}s"
                ) from exc
            raise RuntimeError(f"{self.provider} API request failed: {exc}") from exc

    def ask(self, user_text: str) -> str:
        self.history.append({"role": "user", "content": user_text})
        self._trim_history()
        prefer_tools = self.provider != "ollama-local"
        for _ in range(MAX_TOOL_STEPS):
            messages_for_call = list(self.history)
            mode_instruction = mode_instruction_text(self.mode)
            if mode_instruction:
                messages_for_call.insert(1, {"role": "developer", "content": mode_instruction})
            if self.memory_store is not None:
                memory_context = self.memory_store.formatted_context(limit=10)
                if memory_context:
                    messages_for_call.insert(2, {"role": "developer", "content": memory_context})
            if self.rag_store is not None and self.rag_store.enabled:
                if self.speed_profile == "fast":
                    rag_top_k, rag_max_chars = 2, 1400
                elif self.speed_profile == "quality":
                    rag_top_k, rag_max_chars = 5, 5000
                else:
                    rag_top_k, rag_max_chars = 3, 2800
                rag_context = self.rag_store.retrieve_context(
                    user_text,
                    top_k=rag_top_k,
                    max_chars=rag_max_chars,
                )
                if rag_context:
                    messages_for_call.insert(2, {"role": "developer", "content": rag_context})
            try:
                response = self._post_chat(messages_for_call, use_tools=prefer_tools)
            except RuntimeError as exc:
                text = str(exc).lower()
                # Some compatible providers/models do not support tool-calling.
                if prefer_tools and "tool" in text and ("not supported" in text or "unsupported" in text):
                    response = self._post_chat(messages_for_call, use_tools=False)
                else:
                    raise

            choice = response["choices"][0]
            message = choice["message"]
            tool_calls = message.get("tool_calls") or []

            assistant_message: dict[str, Any] = {"role": "assistant"}
            if message.get("content") is not None:
                assistant_message["content"] = message.get("content")
            if tool_calls:
                assistant_message["tool_calls"] = tool_calls
            self.history.append(assistant_message)

            if tool_calls:
                for tc in tool_calls:
                    name = tc["function"]["name"]
                    raw_args = tc["function"].get("arguments") or "{}"
                    try:
                        args = json.loads(raw_args)
                        if not isinstance(args, dict):
                            raise ValueError("arguments is not a JSON object")
                    except Exception as exc:
                        tool_result = f"Tool arguments parsing failed: {exc}"
                    else:
                        try:
                            tool_result = self.tools.call(name, args)
                        except ToolError as exc:
                            tool_result = f"Tool error: {exc}"
                    if len(tool_result) > MAX_FILE_READ_CHARS:
                        tool_result = (
                            tool_result[:MAX_FILE_READ_CHARS]
                            + "\n\n[Tool output truncated for context window]"
                        )

                    self.history.append(
                        {
                            "role": "tool",
                            "tool_call_id": tc["id"],
                            "content": tool_result,
                        }
                    )
                continue

            content = self._extract_text_content(message.get("content"))
            if content.strip():
                return content.strip()
            return "I completed the task, but I have no textual response."

        return (
            "I hit the maximum number of tool steps for one request. "
            "Please refine the task and try again."
        )


class MultiProviderOnlineBot:
    def __init__(
        self,
        configs: list[ProviderConfig],
        tool_registry: ToolRegistry,
        memory_store: MemoryStore | None = None,
        rag_store: ProjectRAGStore | None = None,
    ) -> None:
        self.tool_registry = tool_registry
        self.memory_store = memory_store
        self.rag_store = rag_store
        self.configs = list(configs)
        self.clients = [
            OnlineChatClient(
                config=cfg,
                tool_registry=tool_registry,
                memory_store=memory_store,
                rag_store=rag_store,
            )
            for cfg in configs
        ]
        self.clients_by_provider = {client.provider: client for client in self.clients}
        self.last_success_provider: str | None = None
        self.last_errors: list[str] = []
        smart = os.environ.get("ADEVX_SMART_ROUTING", "1").strip().lower()
        self.smart_routing = smart not in {"0", "false", "no"}
        self.current_mode = "chat"
        for client in self.clients:
            client.set_mode(self.current_mode)

    def _rebuild_index(self) -> None:
        self.clients_by_provider = {client.provider: client for client in self.clients}

    def _get_or_add_provider(self, provider: str, model_override: str | None = None) -> OnlineChatClient | None:
        provider = provider.strip().lower()
        existing = self.clients_by_provider.get(provider)
        if existing is not None:
            if model_override:
                existing.model = model_override.strip()
                for cfg in self.configs:
                    if cfg.provider == provider:
                        cfg.model = existing.model
                        break
            return existing

        configs = _resolve_provider_configs(
            model_override=model_override,
            provider_override=provider,
        )
        if not configs:
            return None
        cfg = configs[0]
        client = OnlineChatClient(
            config=cfg,
            tool_registry=self.tool_registry,
            memory_store=self.memory_store,
            rag_store=self.rag_store,
        )
        client.set_mode(self.current_mode)
        self.configs.append(cfg)
        self.clients.append(client)
        self._rebuild_index()
        return client

    def _task_type(self, text: str) -> str:
        lower = text.lower()
        if re.search(
            r"\b(code|coding|bug|debug|refactor|function|class|api|compile|error|traceback|test)\b",
            lower,
        ):
            return "coding"
        if re.search(r"\b(math|calculate|equation|integral|algebra|geometry|statistics)\b", lower):
            return "math"
        return "general"

    @staticmethod
    def _parse_provider_list(raw: str) -> list[str]:
        names: list[str] = []
        for token in raw.split(","):
            name = token.strip().lower()
            if name and name not in names:
                names.append(name)
        return names

    def _preferred_provider_order(self, task_type: str) -> list[str]:
        defaults = {
            "coding": "ollama-local,groq,openai,openrouter,together",
            "math": "openai,groq,openrouter,together,ollama-local",
            "general": "openrouter,groq,openai,together,ollama-local",
        }
        route_env_map = {
            "coding": "ADEVX_ROUTE_CODING",
            "math": "ADEVX_ROUTE_MATH",
            "general": "ADEVX_ROUTE_GENERAL",
        }
        raw = os.environ.get(route_env_map[task_type], defaults[task_type])
        return self._parse_provider_list(raw)

    def _ordered_clients_for_text(self, user_text: str) -> list[OnlineChatClient]:
        if not self.smart_routing:
            return list(self.clients)

        task_type = self._task_type(user_text)
        preferred = self._preferred_provider_order(task_type)
        ordered: list[OnlineChatClient] = []
        used: set[str] = set()

        # Keep last successful provider first for continuity if it is still valid.
        if self.last_success_provider and self.last_success_provider in self.clients_by_provider:
            ordered.append(self.clients_by_provider[self.last_success_provider])
            used.add(self.last_success_provider)

        for provider in preferred:
            client = self.clients_by_provider.get(provider)
            if client and provider not in used:
                ordered.append(client)
                used.add(provider)

        for client in self.clients:
            if client.provider not in used:
                ordered.append(client)
                used.add(client.provider)

        return ordered

    def status_text(self) -> str:
        if not self.clients:
            return "No online providers configured."
        chain = " -> ".join(cfg.provider for cfg in self.configs)
        active = self.last_success_provider or self.configs[0].provider
        models = ", ".join(f"{cfg.provider}:{cfg.model}" for cfg in self.configs)
        active_client = self.clients_by_provider.get(active)
        if active_client is not None:
            speed = (
                f"{active_client.speed_profile} "
                f"(max_tokens={active_client.max_tokens}, history={active_client.max_history_messages})"
            )
        else:
            speed = "unknown"
        return f"Active: {active}\nChain: {chain}\nModels: {models}\nSpeed: {speed}"

    def health_check(self, timeout_s: float = 8.0) -> str:
        if not self.configs:
            return "No online providers configured."
        lines = [f"Provider health (timeout={timeout_s:.1f}s):"]
        ok_count = 0
        for cfg in self.configs:
            provider = cfg.provider
            if provider == "ollama-local":
                url = f"{ollama_api_root(cfg.api_base)}/api/tags"
            else:
                url = f"{cfg.api_base.rstrip('/')}/models"
            headers: dict[str, str] = {}
            if cfg.api_key:
                headers["Authorization"] = f"Bearer {cfg.api_key.strip()}"
            headers.update(cfg.extra_headers)

            req = urllib.request.Request(url, method="GET", headers=headers)
            started = time.time()
            try:
                with urllib.request.urlopen(req, timeout=timeout_s) as resp:
                    latency_ms = (time.time() - started) * 1000.0
                    lines.append(
                        f"- {provider}: OK ({resp.status}, {latency_ms:.0f} ms, model={cfg.model})"
                    )
                    ok_count += 1
            except urllib.error.HTTPError as exc:
                latency_ms = (time.time() - started) * 1000.0
                body = exc.read().decode("utf-8", errors="replace")
                short = body.strip().replace("\n", " ")
                if len(short) > 120:
                    short = short[:120] + "..."
                lines.append(
                    f"- {provider}: FAIL (HTTP {exc.code}, {latency_ms:.0f} ms) {short}"
                )
            except Exception as exc:
                latency_ms = (time.time() - started) * 1000.0
                lines.append(f"- {provider}: FAIL ({latency_ms:.0f} ms) {exc}")
        lines.append(f"Healthy providers: {ok_count}/{len(self.configs)}")
        return "\n".join(lines)

    def set_mode(self, mode: str) -> str:
        normalized = normalize_mode_name(mode)
        if not normalized:
            return "Invalid mode. Use /modes."
        self.current_mode = normalized
        for client in self.clients:
            client.set_mode(normalized)
        return f"Online mode set to {normalized}"

    def free_models_text(self) -> str:
        lines = ["Free model presets:"]
        for provider, models in FREE_MODEL_CATALOG.items():
            lines.append(f"{provider}: " + ", ".join(models))
        lines.append("Switch with: /use provider:model")
        return "\n".join(lines)

    def switch_model(self, selector: str) -> str:
        selector = selector.strip()
        if not selector:
            return "Usage: /use provider:model"
        if ":" not in selector:
            return "Usage: /use provider:model"

        provider, model = selector.split(":", 1)
        provider = provider.strip().lower()
        model = model.strip()
        if not provider or not model:
            return "Usage: /use provider:model"

        client = self._get_or_add_provider(provider, model_override=model)
        if client is None:
            return (
                f"Provider '{provider}' is unavailable. Configure its API key first, "
                "or run a local Ollama model."
            )
        client.model = model
        self.last_success_provider = provider
        return f"Switched to {provider}:{model}"

    def set_speed_profile(self, profile: str) -> str:
        if not self.clients:
            return "No online providers configured."
        msgs: list[str] = []
        for client in self.clients:
            msgs.append(client.set_speed_profile(profile))
        # Return one-line summary from the active/last provider when possible.
        active = self.last_success_provider or self.configs[0].provider
        active_client = self.clients_by_provider.get(active)
        if active_client:
            return (
                f"Speed: {active_client.speed_profile} (active={active}, "
                f"max_tokens={active_client.max_tokens}, history={active_client.max_history_messages})"
            )
        return "\n".join(msgs)

    def autotune_ollama(self, max_latency_s: float = 12.0) -> str:
        """
        Benchmark installed Ollama models and pick the best quality model that
        stays under the target latency.
        """
        client = self._get_or_add_provider("ollama-local")
        if client is None:
            return (
                "Ollama local provider is unavailable. Install/start Ollama first, "
                "then run /autotune."
            )

        cfg = next((c for c in self.configs if c.provider == "ollama-local"), None)
        if cfg is None:
            return "Ollama configuration is missing."

        api_root = ollama_api_root(cfg.api_base)

        # 1) List installed local models
        try:
            with urllib.request.urlopen(f"{api_root}/api/tags", timeout=15) as resp:
                tags_data = json.loads(resp.read().decode("utf-8"))
        except Exception as exc:
            return (
                f"Cannot reach Ollama at {api_root}. Start it first (`ollama serve`). "
                f"Details: {exc}"
            )

        models_data = tags_data.get("models", [])
        if not isinstance(models_data, list) or not models_data:
            return (
                "No local models found in Ollama. Pull one first, for example:\n"
                "ollama pull gpt-oss:20b"
            )

        installed_names: set[str] = set()
        model_param_b: dict[str, float] = {}
        for item in models_data:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name", "")).strip()
            model_field = str(item.get("model", "")).strip()
            details = item.get("details", {})
            if isinstance(details, dict):
                param_b = parse_parameter_size_to_billions(str(details.get("parameter_size", "")))
            else:
                param_b = 0.0
            for key in [name, model_field]:
                if not key:
                    continue
                for alias in model_aliases(key):
                    installed_names.add(alias)
                    model_param_b[alias] = max(model_param_b.get(alias, 0.0), param_b)

        preferred = FREE_MODEL_CATALOG.get("ollama-local", [])
        candidates: list[str] = []
        for candidate in preferred:
            if any(alias in installed_names for alias in model_aliases(candidate)):
                candidates.append(candidate)

        # If no preferred catalog models are installed, benchmark top installed models.
        if not candidates:
            discovered = sorted(installed_names, key=lambda n: model_param_b.get(n, 0.0), reverse=True)
            # Skip duplicated :latest alias entries by preferring base model names.
            seen_base: set[str] = set()
            for name in discovered:
                base = name.split(":")[0]
                if base in seen_base:
                    continue
                seen_base.add(base)
                candidates.append(name)
                if len(candidates) >= 4:
                    break

        # Keep benchmarking bounded for responsiveness.
        candidates = candidates[:4]
        if not candidates:
            return "No benchmark candidates found. Try pulling a model and rerun /autotune."

        benchmark_prompt = "Reply with exactly one word: READY"
        results: list[dict[str, Any]] = []
        for model in candidates:
            payload = json.dumps(
                {
                    "model": model,
                    "prompt": benchmark_prompt,
                    "stream": False,
                    "options": {"temperature": 0},
                }
            ).encode("utf-8")
            req = urllib.request.Request(
                f"{api_root}/api/generate",
                method="POST",
                data=payload,
                headers={"Content-Type": "application/json"},
            )
            start = time.time()
            try:
                with urllib.request.urlopen(req, timeout=120) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                wall_s = max(time.time() - start, 0.001)
                eval_count = int(data.get("eval_count", 0) or 0)
                eval_duration = int(data.get("eval_duration", 0) or 0)
                if eval_count > 0 and eval_duration > 0:
                    tps = (eval_count * 1_000_000_000) / eval_duration
                else:
                    tps = 0.0
                param_b = model_param_b.get(model, 0.0)
                results.append(
                    {
                        "model": model,
                        "wall_s": wall_s,
                        "tps": tps,
                        "param_b": param_b,
                    }
                )
            except Exception:
                continue

        if not results:
            return (
                "Autotune couldn't benchmark local models. Ensure Ollama is running and "
                "models are fully downloaded."
            )

        # Prefer the highest parameter model that meets latency budget; otherwise
        # fallback to best speed/quality blended score.
        within_budget = [r for r in results if r["wall_s"] <= max_latency_s]
        used_fallback = False
        if within_budget:
            best = sorted(within_budget, key=lambda r: (r["param_b"], r["tps"]), reverse=True)[0]
        else:
            best = sorted(results, key=lambda r: (r["tps"], r["param_b"]), reverse=True)[0]
            used_fallback = True

        chosen = best["model"]
        switch_text = self.switch_model(f"ollama-local:{chosen}")

        lines = [
            switch_text,
            f"Autotune target latency: <= {max_latency_s:.1f}s",
        ]
        if used_fallback:
            lines.append("No model met latency target; selected fastest available model.")
        lines.append("Benchmarks:")
        for row in sorted(results, key=lambda r: (r["param_b"], r["tps"]), reverse=True):
            lines.append(
                f"- {row['model']}: {row['wall_s']:.2f}s, ~{row['tps']:.1f} tok/s, "
                f"{row['param_b']:.1f}B params"
            )
        return "\n".join(lines)

    def ask(self, user_text: str) -> str:
        if not self.clients:
            raise RuntimeError("No online providers configured.")

        errors: list[str] = []
        for client in self._ordered_clients_for_text(user_text):
            try:
                reply = client.ask(user_text)
                self.last_success_provider = client.provider
                self.last_errors = []
                return reply
            except RuntimeError as exc:
                errors.append(f"{client.provider}: {exc}")
                continue

        self.last_errors = errors
        raise RuntimeError("All providers failed.\n" + "\n".join(f"- {e}" for e in errors))


class FallbackBot:
    """
    Lightweight no-API fallback with slash commands.

    Commands:
    /help
    /ls [path]
    /read <path>
    /write <path> <content>
    /append <path> <content>
    /search <query> [path]
    /calc <expression>
    /fetch <url>
    /image <path>
    /shell <command>
    /summarize <text>
    /health [timeout_seconds]
    """

    def __init__(
        self,
        tools: ToolRegistry,
        memory_store: MemoryStore | None = None,
        rag_store: ProjectRAGStore | None = None,
    ) -> None:
        self.tools = tools
        self.memory_store = memory_store or MemoryStore()
        self.rag_store = rag_store or ProjectRAGStore()
        self.repo_index = WorkspaceIndexAdapter(workspace_root=WORKSPACE_ROOT)
        self.current_mode = "chat"
        local_configs = _resolve_provider_configs(provider_override="ollama-local")
        self.local_llm: OnlineChatClient | None = None
        if local_configs:
            self.local_llm = OnlineChatClient(
                config=local_configs[0],
                tool_registry=tools,
                memory_store=self.memory_store,
                rag_store=self.rag_store,
            )
            self.local_llm.set_mode(self.current_mode)

    def set_mode(self, mode: str) -> str:
        normalized = normalize_mode_name(mode)
        if not normalized:
            return "Invalid mode. Use /modes."
        self.current_mode = normalized
        if self.local_llm is not None:
            self.local_llm.set_mode(normalized)
        return f"Offline mode set to {normalized}"

    @staticmethod
    def _strip_quotes(value: str) -> str:
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            return value[1:-1]
        return value

    def _local_reply(self, text: str) -> str:
        raw = text.strip()
        lower = raw.lower()

        if is_creator_query(lower):
            return DEVELOPER_CREDIT
        if is_identity_query(lower):
            return ABOUT_TEXT
        if lower.startswith("remember "):
            note = raw[len("remember ") :].strip()
            if not note:
                return "Usage: remember <note>"
            self.memory_store.add_note(note)
            return f"Saved memory: {note}"
        if lower in {"show memory", "my memory", "what do you remember"}:
            notes = self.memory_store.notes(limit=30)
            if not notes:
                return "Memory is empty."
            return "Memory:\n" + "\n".join(f"- {note}" for note in notes)
        who_match = re.match(r"^(?:who|what)\s+is\s+(.+?)\??$", raw, flags=re.IGNORECASE)
        if who_match:
            subject = normalize_fact_key(who_match.group(1))
            if subject in LOCAL_FACTS:
                return LOCAL_FACTS[subject]
            if self.local_llm is not None:
                try:
                    return self.local_llm.ask(raw)
                except RuntimeError:
                    pass
            return (
                f"I don't have reliable offline knowledge for '{who_match.group(1).strip()}'. "
                "Use /online for broader answers, or ask me to run local tasks."
            )
        if lower in {"help", "h", "commands", "what can you do"}:
            return self._help()

        try:
            if self.current_mode == "image":
                direct_image = self._strip_quotes(raw)
                if re.search(r"\.(png|jpe?g|gif|bmp|webp)$", direct_image, flags=re.IGNORECASE):
                    return self.tools.call("analyze_image", {"path": direct_image})

            image_match = re.match(
                r"^(?:analy[sz]e|inspect|describe)\s+(?:this\s+)?image\s+(?P<path>.+)$",
                raw,
                flags=re.IGNORECASE,
            )
            if image_match:
                path = self._strip_quotes(image_match.group("path").strip())
                return self.tools.call("analyze_image", {"path": path})

            # create file named notes.txt with text: hello
            create_patterns = [
                r'^(?:create|make|write)\s+(?:a\s+)?file\s+(?:named\s+)?\"(?P<path>[^\"]+)\"\s+(?:with\s+(?:text|content)\s*:?\s*)(?P<content>.+)$',
                r"^(?:create|make|write)\s+(?:a\s+)?file\s+(?:named\s+)?'(?P<path>[^']+)'\s+(?:with\s+(?:text|content)\s*:?\s*)(?P<content>.+)$",
                r"^(?:create|make|write)\s+(?:a\s+)?file\s+(?:named\s+)?(?P<path>\S+)\s+(?:with\s+(?:text|content)\s*:?\s*)(?P<content>.+)$",
            ]
            for pattern in create_patterns:
                match = re.match(pattern, raw, flags=re.IGNORECASE)
                if match:
                    path = self._strip_quotes(match.group("path"))
                    content = match.group("content")
                    return self.tools.call("write_file", {"path": path, "content": content})

            append_patterns = [
                r'^(?:append|add)\s+(?:to\s+)?(?:file\s+)?\"(?P<path>[^\"]+)\"\s+(?P<content>.+)$',
                r"^(?:append|add)\s+(?:to\s+)?(?:file\s+)?'(?P<path>[^']+)'\s+(?P<content>.+)$",
                r"^(?:append|add)\s+(?:to\s+)?(?:file\s+)?(?P<path>\S+)\s+(?P<content>.+)$",
            ]
            for pattern in append_patterns:
                match = re.match(pattern, raw, flags=re.IGNORECASE)
                if match:
                    path = self._strip_quotes(match.group("path"))
                    content = match.group("content")
                    return self.tools.call("append_file", {"path": path, "content": content})

            read_patterns = [
                r'^(?:read|show|open)\s+(?:file\s+)?\"(?P<path>[^\"]+)\"$',
                r"^(?:read|show|open)\s+(?:file\s+)?'(?P<path>[^']+)'$",
                r"^(?:read|show|open)\s+(?:file\s+)?(?P<path>\S+)$",
            ]
            for pattern in read_patterns:
                match = re.match(pattern, raw, flags=re.IGNORECASE)
                if match:
                    path = self._strip_quotes(match.group("path"))
                    return self.tools.call("read_file", {"path": path})

            list_match = re.match(
                r"^(?:list|show)(?:\s+all)?\s+files(?:\s+in\s+(?P<path>.+))?$",
                raw,
                flags=re.IGNORECASE,
            )
            if list_match:
                path = (list_match.group("path") or ".").strip()
                path = self._strip_quotes(path)
                return self.tools.call("list_files", {"path": path})

            search_match = re.match(
                r"^(?:search|find)\s+(?P<query>.+?)(?:\s+in\s+(?P<path>.+))?$",
                raw,
                flags=re.IGNORECASE,
            )
            if search_match:
                query = self._strip_quotes(search_match.group("query").strip())
                path = search_match.group("path")
                if path:
                    return self.tools.call(
                        "search_text",
                        {"query": query, "path": self._strip_quotes(path.strip())},
                    )
                return self.tools.call("search_text", {"query": query})

            calc_match = re.match(
                r"^(?:calc|calculate|compute)\s+(?P<expr>.+)$",
                raw,
                flags=re.IGNORECASE,
            )
            if calc_match:
                return self.tools.call(
                    "calculate",
                    {"expression": calc_match.group("expr").strip()},
                )
            if looks_like_math_expression(raw):
                return self.tools.call("calculate", {"expression": raw})

            summarize_match = re.match(
                r"^(?:summarize|summary)\s+(?P<text>.+)$",
                raw,
                flags=re.IGNORECASE,
            )
            if summarize_match:
                return self.tools.call(
                    "summarize_text",
                    {"text": summarize_match.group("text").strip()},
                )

            fetch_match = re.match(
                r"^(?:fetch|get)\s+(?P<url>https?://\S+)$",
                raw,
                flags=re.IGNORECASE,
            )
            if fetch_match:
                return self.tools.call("fetch_url", {"url": fetch_match.group("url")})
        except ToolError as exc:
            return f"Tool error: {exc}"

        if self.local_llm is not None:
            try:
                return self.local_llm.ask(raw)
            except RuntimeError:
                pass

        if self.rag_store.enabled:
            rag_context = self.rag_store.retrieve_context(raw, top_k=3, max_chars=2200)
            if rag_context:
                return (
                    "I found relevant project context from local RAG index:\n\n"
                    f"{rag_context}\n\n"
                    "Tip: for stronger synthesis, run /online with a model enabled."
                )

        if self.current_mode == "image":
            return (
                "Image mode is active. Try one of these:\n"
                "- /image assets/photo.png\n"
                "- analyze image assets/photo.png\n"
                "- switch mode with /mode chat"
            )

        return (
            "Local mode supports minimal reasoning without cloud API. Try:\n"
            "- create a file named notes.txt with text: hello\n"
            "- read notes.txt\n"
            "- list files\n"
            "- calculate sqrt(144) + 6\n"
            "- search hello in .\n"
            "- /image <path-to-image>\n"
            "- or run Ollama locally for full offline chat AI\n"
            "Use /help for full command list."
        )

    def _help(self) -> str:
        return textwrap.dedent(
            """\
            Offline mode (local minimal reasoning + slash commands):
            - /h
            - /remember <note>
            - /memory
            - /memory stats|search <query>|consolidate
            - /forget
            - /ls [path]
            - /read <path>
            - /write <path> <content>
            - /append <path> <content>
            - /search <query> [path]
            - /calc <expression>
            - /fetch <url>
            - /shell <command>
            - /summarize <text>
            - /health [timeout_seconds]
            - /about
            - /models
            - /use provider:model
            - /autotune [max_latency_seconds]
            - /speed fast|balanced|quality
            - /modes
            - /mode <name>
            - /image <path>
            - /rag status|rebuild|query <text>|on|off
            - /repo symbols|graph|explain <symbol>|references <symbol>
            - /agent plan|execute|review <text>
            - /git analyze|summarize [rev]|impact [path|rev-range]
            - /benchmark
            - /metrics
            - /phase run|status
            - /status
            - /online
            - /offline
            - /help
            - /exit
            """
        ).strip()

    def ask(self, user_text: str) -> str:
        text = user_text.strip()
        if not text:
            return "Please enter a command or message."

        if not text.startswith("/"):
            return self._local_reply(text)

        parts = text.split(maxsplit=2)
        cmd = parts[0].lower()

        try:
            if cmd in {"/help", "/h"}:
                return self._help()
            if cmd == "/about":
                return ABOUT_TEXT
            if cmd == "/memory":
                notes = self.memory_store.notes(limit=30)
                if not notes:
                    return "Memory is empty."
                return "Memory:\n" + "\n".join(f"- {note}" for note in notes)
            if cmd == "/remember":
                note = text[len("/remember") :].strip()
                if not note:
                    return "Usage: /remember <note>"
                self.memory_store.add_note(note)
                return f"Saved memory: {note}"
            if cmd == "/forget":
                self.memory_store.clear()
                return "Memory cleared."
            if cmd == "/ls":
                path = parts[1] if len(parts) > 1 else "."
                return self.tools.call("list_files", {"path": path})
            if cmd == "/read":
                if len(parts) < 2:
                    return "Usage: /read <path>"
                return self.tools.call("read_file", {"path": parts[1]})
            if cmd == "/write":
                if len(parts) < 3:
                    return "Usage: /write <path> <content>"
                return self.tools.call("write_file", {"path": parts[1], "content": parts[2]})
            if cmd == "/append":
                if len(parts) < 3:
                    return "Usage: /append <path> <content>"
                return self.tools.call("append_file", {"path": parts[1], "content": parts[2]})
            if cmd == "/search":
                if len(parts) < 2:
                    return "Usage: /search <query> [path]"
                # Support optional path by splitting query tail.
                tail = parts[1] if len(parts) == 2 else f"{parts[1]} {parts[2]}"
                # Last token can be a path if it exists.
                tokens = tail.split()
                if len(tokens) >= 2:
                    possible_path = tokens[-1]
                    try:
                        p = resolve_user_path(possible_path)
                        if p.exists() and p.is_dir():
                            query = " ".join(tokens[:-1]).strip()
                            return self.tools.call(
                                "search_text", {"query": query, "path": possible_path}
                            )
                    except ToolError:
                        pass
                return self.tools.call("search_text", {"query": tail})
            if cmd == "/calc":
                if len(parts) < 2:
                    return "Usage: /calc <expression>"
                expr = text[len("/calc") :].strip()
                return self.tools.call("calculate", {"expression": expr})
            if cmd == "/fetch":
                if len(parts) < 2:
                    return "Usage: /fetch <url>"
                return self.tools.call("fetch_url", {"url": parts[1]})
            if cmd in {"/image", "/analyze-image"}:
                image_path = text[len(cmd) :].strip()
                if not image_path:
                    return "Usage: /image <path>"
                return self.tools.call("analyze_image", {"path": image_path})
            if cmd == "/shell":
                if len(parts) < 2:
                    return "Usage: /shell <command>"
                command = text[len("/shell") :].strip()
                return self.tools.call("run_shell", {"command": command})
            if cmd == "/summarize":
                if len(parts) < 2:
                    return "Usage: /summarize <text>"
                summary_text = text[len("/summarize") :].strip()
                return self.tools.call("summarize_text", {"text": summary_text})
            return "Unknown command. Use /help. For normal chat, do not start with '/'."
        except ToolError as exc:
            return f"Tool error: {exc}"


class AdevXBot:
    def __init__(
        self,
        offline_bot: FallbackBot,
        online_bot: MultiProviderOnlineBot | None,
        provider_configs: list[ProviderConfig],
    ) -> None:
        self.offline_bot = offline_bot
        self.online_bot = online_bot
        self.provider_configs = provider_configs
        self.rag_store = offline_bot.rag_store
        self.phase_store = PhaseProgressStore()
        self.use_online = online_bot is not None
        self.last_online_error = ""
        self.current_mode = "chat"
        self.command_metrics: dict[str, Any] = {
            "commands": {},
            "errors": 0,
            "latency_ms": {},
        }
        self.git_intel = GitIntelligence(WORKSPACE_ROOT)
        self.offline_bot.set_mode(self.current_mode)
        if self.online_bot is not None:
            self.online_bot.set_mode(self.current_mode)

    @property
    def mode_label(self) -> str:
        return "online" if self.use_online and self.online_bot else "offline"

    @staticmethod
    def _is_creator_query(lower_text: str) -> bool:
        return is_creator_query(lower_text)

    @staticmethod
    def _is_identity_query(lower_text: str) -> bool:
        return is_identity_query(lower_text)

    def _status_text(self) -> str:
        rag_line = (
            f"RAG: {'on' if self.rag_store.enabled else 'off'} "
            f"({self.rag_store._data.get('files_indexed', 0)} files, "
            f"{self.rag_store._data.get('chunks_indexed', 0)} chunks)"
        )
        last_error_line = (
            f"\nLast online error: {self.last_online_error}" if self.last_online_error else ""
        )
        if self.online_bot and self.provider_configs:
            live_mode = "online" if self.use_online else "offline (manual)"
            return (
                f"Mode: {live_mode}\n"
                f"AdevX mode: {self.current_mode}\n"
                f"{self.online_bot.status_text()}\n"
                f"{rag_line}\n"
                f"{self.phase_store.status_text()}\n"
                f"{last_error_line}\n"
                "Tip: /offline switches to local no-API mode, /online switches back."
            )
        return (
            "Mode: offline (local minimal reasoning)\n"
            f"AdevX mode: {self.current_mode}\n"
            "Local engine: rule-based + optional Ollama local LLM (no cloud token billing)\n"
            f"{rag_line}\n"
            f"{self.phase_store.status_text()}\n"
            f"{last_error_line}\n"
            "Set one of OPENAI_API_KEY, OPENROUTER_API_KEY, GROQ_API_KEY, TOGETHER_API_KEY, "
            "then restart AdevX for online mode."
        )

    def set_mode(self, mode: str) -> str:
        normalized = normalize_mode_name(mode)
        if not normalized:
            return "Invalid mode. Use /modes."
        self.current_mode = normalized
        self.offline_bot.set_mode(normalized)
        if self.online_bot is not None:
            self.online_bot.set_mode(normalized)
        mode_summary = MODE_CATALOG[normalized]["summary"]
        return f"Mode set to {normalized}: {mode_summary}"

    @staticmethod
    def _score_reasoning_answer(answer: str) -> int:
        text = answer.lower()
        score = 0
        if len(answer.strip()) >= 140:
            score += 12
        if "o(" in text or "complexity" in text:
            score += 12
        if any(marker in answer for marker in ["1.", "2.", "-", "*"]):
            score += 6
        if "merge" in text and "sort" in text:
            score += 5
        return min(35, score)

    @staticmethod
    def _score_coding_answer(answer: str) -> int:
        text = answer.lower()
        score = 0
        if "```" in answer:
            score += 10
        if "merge" in text and "sort" in text:
            score += 10
        if any(token in text for token in ["vector<int>", "void", "int main", "std::"]):
            score += 8
        if "complexity" in text or "o(" in text:
            score += 7
        return min(35, score)

    def _run_capability_benchmark(self) -> dict[str, Any]:
        details: list[str] = []
        total = 0

        # RAG coverage score (30)
        rag_hits = self.rag_store.retrieve_context("speed profile", top_k=2, max_chars=1000)
        rag_score = 30 if rag_hits else 10
        total += rag_score
        details.append(f"RAG score: {rag_score}/30")

        # Model reasoning + coding scores (70)
        model_score = 0
        if self.online_bot is None:
            details.append("Model score: 0/70 (no online/local model active)")
        else:
            # Prefer quick benchmark mode
            self.online_bot.set_speed_profile("fast")
            try:
                reasoning_prompt = (
                    "Explain merge sort in 4 short points and include time complexity."
                )
                reasoning_answer = self.online_bot.ask(reasoning_prompt)
                r_score = self._score_reasoning_answer(reasoning_answer)
                model_score += r_score
                details.append(f"Reasoning score: {r_score}/35")
            except Exception as exc:
                details.append(f"Reasoning score: 0/35 ({exc})")

            try:
                coding_prompt = (
                    "Write C++ merge sort for vector<int> with a small main example "
                    "and include complexity."
                )
                coding_answer = self.online_bot.ask(coding_prompt)
                c_score = self._score_coding_answer(coding_answer)
                model_score += c_score
                details.append(f"Coding score: {c_score}/35")
            except Exception as exc:
                details.append(f"Coding score: 0/35 ({exc})")

        total += model_score
        total = max(0, min(100, total))
        level = "starter"
        if total >= 80:
            level = "strong"
        elif total >= 60:
            level = "good"
        elif total >= 40:
            level = "developing"

        return {
            "score": total,
            "level": level,
            "details": details,
        }

    def _run_phase_automation(self) -> str:
        steps: list[dict[str, Any]] = []

        # Step 1: Rebuild RAG index.
        try:
            rag_result = self.rag_store.rebuild(chunk_lines=60, overlap_lines=15)
            steps.append({"step": "rag_rebuild", "ok": True, "info": rag_result})
        except Exception as exc:
            steps.append({"step": "rag_rebuild", "ok": False, "info": str(exc)})

        # Step 2: Ensure an online/local model is available (prefer ollama-local).
        if self.online_bot is None:
            provider_configs = _resolve_provider_configs(
                model_override=None,
                provider_override="ollama-local",
            )
            if provider_configs:
                self.online_bot = MultiProviderOnlineBot(
                    configs=provider_configs,
                    tool_registry=self.offline_bot.tools,
                    memory_store=self.offline_bot.memory_store,
                    rag_store=self.offline_bot.rag_store,
                )
                self.online_bot.set_mode(self.current_mode)
                self.provider_configs = provider_configs
                self.use_online = True
                steps.append({"step": "enable_model", "ok": True, "info": "ollama-local enabled"})
            else:
                steps.append(
                    {
                        "step": "enable_model",
                        "ok": False,
                        "info": "No local model configured. Use /use ollama-local:<model>.",
                    }
                )
        else:
            steps.append({"step": "enable_model", "ok": True, "info": "model already active"})

        # Step 3: Autotune local model if possible.
        if self.online_bot is not None:
            tune_info = self.online_bot.autotune_ollama(max_latency_s=20.0)
            tune_ok = not (
                tune_info.lower().startswith("cannot reach ollama")
                or tune_info.lower().startswith("ollama local provider is unavailable")
                or tune_info.lower().startswith("no local models found")
                or tune_info.lower().startswith("autotune couldn't benchmark")
            )
            steps.append({"step": "autotune", "ok": tune_ok, "info": tune_info})
            speed_info = self.online_bot.set_speed_profile("fast")
            steps.append({"step": "speed", "ok": True, "info": speed_info})
        else:
            steps.append({"step": "autotune", "ok": False, "info": "skipped (no model)"})

        # Step 4: Benchmark capability.
        benchmark = self._run_capability_benchmark()
        self.phase_store.update(phase="phase2", steps=steps, benchmark=benchmark)

        lines = ["Phase automation complete."]
        for item in steps:
            mark = "OK" if item.get("ok") else "SKIP/FAIL"
            lines.append(f"- {item.get('step')}: {mark} - {item.get('info')}")
        lines.append(
            f"Benchmark score (internal heuristic): {benchmark['score']}/100 "
            f"({benchmark['level']})"
        )
        for detail in benchmark.get("details", []):
            lines.append(f"- {detail}")
        lines.append("Use /phase status for latest progress.")
        return "\n".join(lines)

    def _record_command_metric(self, name: str, started_at: float, ok: bool = True) -> None:
        elapsed_ms = max(0.0, (time.perf_counter() - started_at) * 1000.0)
        commands = self.command_metrics.setdefault("commands", {})
        commands[name] = int(commands.get(name, 0)) + 1
        latency = self.command_metrics.setdefault("latency_ms", {}).setdefault(name, [])
        if isinstance(latency, list):
            latency.append(round(elapsed_ms, 2))
            if len(latency) > 40:
                del latency[0 : len(latency) - 40]
        if not ok:
            self.command_metrics["errors"] = int(self.command_metrics.get("errors", 0)) + 1

    def _run_tracked_command(self, name: str, action: Callable[[], str]) -> str:
        started_at = time.perf_counter()
        try:
            result = action()
        except Exception as exc:
            self._record_command_metric(name, started_at, ok=False)
            return f"{name} command failed: {exc}"
        self._record_command_metric(name, started_at, ok=True)
        return result

    def _handle_memory_command(self, tail: str) -> str:
        sub = tail.strip()
        if not sub:
            notes = self.offline_bot.memory_store.notes(limit=30)
            if not notes:
                return "Memory is empty."
            return "Memory:\n" + "\n".join(f"- {note}" for note in notes)
        lowered = sub.lower()
        if lowered == "stats":
            return self.offline_bot.memory_store.stats_text()
        if lowered == "consolidate":
            return self.offline_bot.memory_store.consolidate_text()
        if lowered.startswith("search "):
            query = sub[7:].strip()
            if not query:
                return "Usage: /memory search <query>"
            return self.offline_bot.memory_store.search_text(query)
        return "Usage: /memory | /memory stats | /memory search <query> | /memory consolidate"

    def _handle_repo_command(self, tail: str) -> str:
        sub = tail.strip()
        if not sub:
            return "Usage: /repo symbols|graph|explain <symbol>|references <symbol>"
        if sub.lower() == "symbols":
            return run_async(self.offline_bot.repo_index.repo_symbols_text())
        if sub.lower().startswith("symbols "):
            search = sub[8:].strip()
            return run_async(self.offline_bot.repo_index.repo_symbols_text(search=search))
        if sub.lower() == "graph":
            return run_async(self.offline_bot.repo_index.repo_graph_text())
        if sub.lower().startswith("graph "):
            focus = sub[6:].strip()
            return run_async(self.offline_bot.repo_index.repo_graph_text(focus=focus))
        if sub.lower().startswith("explain "):
            symbol = sub[8:].strip()
            if not symbol:
                return "Usage: /repo explain <symbol>"
            return run_async(self.offline_bot.repo_index.repo_explain_text(symbol))
        if sub.lower().startswith("references "):
            symbol = sub[11:].strip()
            if not symbol:
                return "Usage: /repo references <symbol>"
            return run_async(self.offline_bot.repo_index.repo_references_text(symbol))
        return "Usage: /repo symbols|graph|explain <symbol>|references <symbol>"

    def _build_runtime(self) -> Any:
        from adevx.core.config import RuntimeConfig
        from adevx.runtime.app import AdevXRuntime

        config = RuntimeConfig.from_env()
        if not os.environ.get("ADEVX_LOG_LEVEL"):
            config.log_level = "ERROR"
        return AdevXRuntime.create(config=config)

    def _handle_agent_command(self, tail: str) -> str:
        sub = tail.strip()
        if not sub:
            return "Usage: /agent plan <goal> | /agent execute <goal> | /agent review <text>"
        if sub.lower().startswith("plan "):
            from adevx.core.models import UserRequest

            goal = sub[5:].strip()
            if not goal:
                return "Usage: /agent plan <goal>"
            runtime = self._build_runtime()
            request = UserRequest(text=goal, mode=self.current_mode, session_id="cli-agent")
            plan = run_async(runtime.context.planner_agent.plan(request))
            lines = ["Agent plan:"]
            lines.append(f"- goal: {plan.goal.objective}")
            lines.append(f"- selected strategy: {plan.selected_plan.candidate.strategy}")
            lines.append(f"- confidence: {plan.selected_plan.candidate.confidence:.2f}")
            lines.append("Tasks:")
            for task in plan.selected_plan.candidate.tasks:
                deps = ", ".join(task.depends_on) if task.depends_on else "<none>"
                lines.append(f"- {task.task_id}: {task.title} [{task.capability}] deps={deps}")
            if plan.thought_trace.strip():
                lines.append("Reasoning:")
                lines.append(plan.thought_trace)
            return "\n".join(lines)
        if sub.lower().startswith("execute "):
            from adevx.core.models import UserRequest

            goal = sub[8:].strip()
            if not goal:
                return "Usage: /agent execute <goal>"
            runtime = self._build_runtime()
            request = UserRequest(text=goal, mode=self.current_mode, session_id="cli-agent")
            response = run_async(runtime.context.autonomous_engine.run(request))
            return response.text
        if sub.lower().startswith("review "):
            text = sub[7:].strip()
            if not text:
                return "Usage: /agent review <text>"
            runtime = self._build_runtime()
            verdict = run_async(runtime.context.reviewer_agent.critique(text))
            memory_hint = run_async(runtime.context.memory_agent.search("cli-agent", text, limit=3))
            lines = [f"Agent review: {verdict}"]
            if memory_hint:
                lines.append("Related memory:")
                for item in memory_hint:
                    lines.append(f"- {item}")
            return "\n".join(lines)
        return "Usage: /agent plan <goal> | /agent execute <goal> | /agent review <text>"

    def _handle_git_command(self, tail: str) -> str:
        sub = tail.strip()
        if not sub:
            return "Usage: /git analyze|summarize [rev]|impact [path|rev-range]"
        if sub.lower() == "analyze":
            return self.git_intel.analyze()
        if sub.lower().startswith("analyze "):
            return self.git_intel.analyze(sub[8:].strip())
        if sub.lower() == "summarize":
            return self.git_intel.summarize("HEAD")
        if sub.lower().startswith("summarize "):
            return self.git_intel.summarize(sub[10:].strip())
        if sub.lower() == "impact":
            snapshot = run_async(self.offline_bot.repo_index.repo_snapshot())
            return self.git_intel.impact(repo_snapshot=snapshot)
        if sub.lower().startswith("impact "):
            snapshot = run_async(self.offline_bot.repo_index.repo_snapshot())
            return self.git_intel.impact(sub[7:].strip(), repo_snapshot=snapshot)
        return "Usage: /git analyze|summarize [rev]|impact [path|rev-range]"

    def _handle_benchmark_command(self) -> str:
        retrieval = run_async(BenchmarkRunner(self.offline_bot.repo_index).run_retrieval())
        lines = [BenchmarkRunner.format_report(retrieval)]
        if self.online_bot is not None:
            lines.append("")
            lines.append("Provider health:")
            lines.append(self.online_bot.health_check(timeout_s=6.0))
            capability = self._run_capability_benchmark()
            lines.append("")
            lines.append(
                f"Capability benchmark: {capability['score']}/100 ({capability['level']})"
            )
            for detail in capability.get("details", []):
                lines.append(f"- {detail}")
        else:
            lines.append("")
            lines.append("Provider health: online providers are not configured.")
        return "\n".join(lines)

    def _handle_metrics_command(self) -> str:
        lines = ["AdevX command metrics:"]
        lines.append(f"- errors: {int(self.command_metrics.get('errors', 0))}")
        commands = self.command_metrics.get("commands", {})
        latency = self.command_metrics.get("latency_ms", {})
        if not isinstance(commands, dict) or not commands:
            lines.append("- commands: <none recorded>")
            return "\n".join(lines)
        for name in sorted(commands.keys()):
            count = int(commands.get(name, 0))
            samples = latency.get(name, []) if isinstance(latency, dict) else []
            avg_ms = 0.0
            if isinstance(samples, list) and samples:
                avg_ms = sum(float(item) for item in samples) / len(samples)
            lines.append(f"- {name}: count={count}, avg_latency_ms={avg_ms:.2f}")
        return "\n".join(lines)

    def ask(self, user_text: str) -> str:
        text = user_text.strip()
        lower = text.lower()
        no_slash_lower = lower.lstrip("/").strip()

        if no_slash_lower.startswith("remember "):
            note = text.lstrip("/").strip()[len("remember ") :].strip()
            if not note:
                return "Usage: remember <note>"
            self.offline_bot.memory_store.add_note(note)
            return f"Saved memory: {note}"
        if no_slash_lower in {"show memory", "my memory", "what do you remember"}:
            notes = self.offline_bot.memory_store.notes(limit=30)
            if not notes:
                return "Memory is empty."
            return "Memory:\n" + "\n".join(f"- {note}" for note in notes)

        if self._is_creator_query(lower) or self._is_creator_query(no_slash_lower):
            return DEVELOPER_CREDIT
        if self._is_identity_query(lower) or self._is_identity_query(no_slash_lower):
            return ABOUT_TEXT

        if lower == "/memory" or lower.startswith("/memory "):
            tail = text[len("/memory") :].strip()
            return self._run_tracked_command("memory", lambda: self._handle_memory_command(tail))

        if lower.startswith("/repo"):
            tail = text[len("/repo") :].strip()
            return self._run_tracked_command("repo", lambda: self._handle_repo_command(tail))

        if lower.startswith("/agent"):
            tail = text[len("/agent") :].strip()
            return self._run_tracked_command("agent", lambda: self._handle_agent_command(tail))

        if lower.startswith("/git"):
            tail = text[len("/git") :].strip()
            return self._run_tracked_command("git", lambda: self._handle_git_command(tail))

        if lower == "/benchmark":
            return self._run_tracked_command("benchmark", self._handle_benchmark_command)

        if lower == "/metrics":
            return self._run_tracked_command("metrics", self._handle_metrics_command)

        if lower == "/modes":
            return modes_text()

        if lower == "/mode" or lower.startswith("/mode "):
            tail = text[len("/mode") :].strip()
            if not tail:
                return (
                    f"Current mode: {self.current_mode}\n"
                    f"{MODE_CATALOG[self.current_mode]['summary']}\n"
                    "Use /modes to list all modes."
                )
            return self.set_mode(tail)

        if lower == "/models":
            if self.online_bot:
                return self.online_bot.free_models_text()
            lines = ["Free model presets:"]
            for provider, models in FREE_MODEL_CATALOG.items():
                lines.append(f"{provider}: " + ", ".join(models))
            lines.append("Use /use provider:model after enabling an online provider.")
            return "\n".join(lines)

        if lower.startswith("/use "):
            selector = text[len("/use") :].strip()
            if not selector:
                return "Usage: /use provider:model"
            if self.online_bot is None:
                # Lazy-create online bot for requested provider if possible.
                provider = selector.split(":", 1)[0].strip().lower() if ":" in selector else ""
                provider_configs = _resolve_provider_configs(
                    model_override=None,
                    provider_override=provider or "auto",
                )
                if provider_configs:
                    self.online_bot = MultiProviderOnlineBot(
                        configs=provider_configs,
                        tool_registry=self.offline_bot.tools,
                        memory_store=self.offline_bot.memory_store,
                        rag_store=self.offline_bot.rag_store,
                    )
                    self.online_bot.set_mode(self.current_mode)
                    self.provider_configs = provider_configs
                    self.use_online = True
                else:
                    return (
                        "Cannot enable requested provider. Configure API key (or Ollama) first, "
                        "then retry /use provider:model."
                    )
            result = self.online_bot.switch_model(selector)
            if result.startswith("Switched to "):
                self.use_online = True
            return result

        if lower.startswith("/autotune"):
            # Usage: /autotune or /autotune 15
            max_latency_s = 12.0
            tail = text[len("/autotune") :].strip()
            if tail:
                try:
                    max_latency_s = float(tail)
                    if max_latency_s <= 0:
                        raise ValueError("must be positive")
                except ValueError:
                    return "Usage: /autotune [max_latency_seconds], e.g. /autotune 15"

            if self.online_bot is None:
                provider_configs = _resolve_provider_configs(
                    model_override=None,
                    provider_override="ollama-local",
                )
                if not provider_configs:
                    return (
                        "Ollama local provider is unavailable. Start Ollama and pull a model, "
                        "then run /autotune."
                    )
                self.online_bot = MultiProviderOnlineBot(
                    configs=provider_configs,
                    tool_registry=self.offline_bot.tools,
                    memory_store=self.offline_bot.memory_store,
                    rag_store=self.offline_bot.rag_store,
                )
                self.online_bot.set_mode(self.current_mode)
                self.provider_configs = provider_configs

            tune_result = self.online_bot.autotune_ollama(max_latency_s=max_latency_s)
            if tune_result.startswith("Switched to ") or "Autotune target latency:" in tune_result:
                self.use_online = True
            return tune_result

        if lower.startswith("/speed"):
            tail = text[len("/speed") :].strip().lower()
            if tail not in {"fast", "balanced", "quality"}:
                return "Usage: /speed fast|balanced|quality"
            if self.online_bot is None:
                return "Online provider not active. Use /online or /use provider:model first."
            return self.online_bot.set_speed_profile(tail)

        if lower.startswith("/health"):
            timeout_s = 8.0
            tail = text[len("/health") :].strip()
            if tail:
                try:
                    timeout_s = float(tail)
                    if timeout_s <= 0:
                        raise ValueError("must be positive")
                except ValueError:
                    return "Usage: /health [timeout_seconds], e.g. /health 8"
            if self.online_bot is None:
                return (
                    "Online providers are not configured. Set provider keys or Ollama first, "
                    "then retry /health."
                )
            return self.online_bot.health_check(timeout_s=timeout_s)

        if lower.startswith("/rag"):
            tail = text[len("/rag") :].strip()
            if not tail or tail.lower() == "status":
                return self.rag_store.status_text()
            if tail.lower() == "on":
                self.rag_store.set_enabled(True)
                return "RAG enabled."
            if tail.lower() == "off":
                self.rag_store.set_enabled(False)
                return "RAG disabled."
            if tail.lower().startswith("rebuild"):
                # Optional syntax: /rag rebuild 80 20
                parts = tail.split()
                chunk_lines = 60
                overlap_lines = 15
                if len(parts) >= 2:
                    try:
                        chunk_lines = max(20, min(200, int(parts[1])))
                    except ValueError:
                        return "Usage: /rag rebuild [chunk_lines] [overlap_lines]"
                if len(parts) >= 3:
                    try:
                        overlap_lines = max(5, min(chunk_lines - 1, int(parts[2])))
                    except ValueError:
                        return "Usage: /rag rebuild [chunk_lines] [overlap_lines]"
                return self.rag_store.rebuild(
                    chunk_lines=chunk_lines,
                    overlap_lines=overlap_lines,
                )
            if tail.lower().startswith("query "):
                query_text = tail[6:].strip()
                if not query_text:
                    return "Usage: /rag query <text>"
                context = self.rag_store.retrieve_context(query_text, top_k=4, max_chars=3000)
                if not context:
                    return (
                        "No RAG hits found. Run /rag rebuild first, or refine your query."
                    )
                return context
            return "Usage: /rag status|rebuild|query <text>|on|off"

        if lower.startswith("/phase"):
            tail = text[len("/phase") :].strip().lower()
            if not tail or tail == "status":
                return self.phase_store.status_text()
            if tail == "run":
                return self._run_phase_automation()
            return "Usage: /phase run|status"

        if lower == "/status":
            return self._status_text()
        if lower == "/offline":
            self.use_online = False
            return "Switched to offline mode. Use /help for commands."
        if lower == "/online":
            if not self.online_bot:
                return (
                    "Online mode is unavailable. Set OPENAI_API_KEY, "
                    "OPENROUTER_API_KEY, GROQ_API_KEY, TOGETHER_API_KEY, or run "
                    "a local Ollama model and restart."
                )
            self.use_online = True
            self.last_online_error = ""
            return "Switched to online mode.\n" + self.online_bot.status_text()

        # Slash commands always run locally for predictable control.
        if text.startswith("/"):
            return self.offline_bot.ask(text)

        if self.use_online and self.online_bot:
            try:
                return self.online_bot.ask(text)
            except RuntimeError as exc:
                message = str(exc)
                lowered = message.lower()
                if (
                    "insufficient_quota" in lowered
                    or "http error 429" in lowered
                    or "429" in lowered
                    or "too many requests" in lowered
                ):
                    self.use_online = False
                    self.last_online_error = message
                    return (
                        "Online quota/rate limit reached. I switched to offline mode.\n"
                        "Use /status to see provider state, then /online after credits/reset.\n\n"
                        f"{self.offline_bot.ask(text)}"
                    )
                if "invalid header value" in lowered:
                    self.use_online = False
                    self.last_online_error = message
                    return (
                        "Your API key looks malformed (often hidden newline/space). "
                        "I switched to offline mode.\n\n"
                        f"{self.offline_bot.ask(text)}"
                    )
                if "timed out" in lowered and "ollama-local" in lowered:
                    self.use_online = False
                    self.last_online_error = message
                    return (
                        "Local model timed out on this request. I switched to offline mode.\n"
                        "Try: /autotune 20, then retry your prompt."
                    )
                if "all providers failed" in lowered:
                    self.use_online = False
                    self.last_online_error = message
                    return (
                        "All online providers are currently unavailable. "
                        "I switched to offline mode.\n\n"
                        f"{self.offline_bot.ask(text)}"
                    )
                self.last_online_error = message
                return f"Online error: {message}"

        return self.offline_bot.ask(text)


def ask_shell_approval(command: str) -> bool:
    print(f"\nAbout to run shell command:\n  {command}")
    answer = input("Allow this command? [y/N]: ").strip().lower()
    return answer in {"y", "yes"}


def ask_with_animation(bot: AdevXBot, user_text: str, animate: bool) -> str:
    if not animate:
        return bot.ask(user_text)

    state: dict[str, Any] = {"reply": None, "error": None}
    done = threading.Event()

    def worker() -> None:
        try:
            state["reply"] = bot.ask(user_text)
        except Exception as exc:  # pragma: no cover - forwarded to caller
            state["error"] = exc
        finally:
            done.set()

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()

    frames = ("|", "/", "-", "\\")
    idx = 0
    start = time.time()
    while not done.wait(0.1):
        elapsed = int(time.time() - start)
        frame = frames[idx % len(frames)]
        print(f"\rAdevX is thinking {frame} {elapsed}s", end="", flush=True)
        idx += 1

    # Clear the animation line.
    print("\r" + (" " * 48) + "\r", end="", flush=True)

    if state["error"] is not None:
        raise state["error"]
    return str(state["reply"] or "")


def build_bot(model_override: str = "", provider_override: str = "auto") -> AdevXBot:
    provider_override = (provider_override or "auto").strip().lower()
    tools = ToolRegistry(approval_callback=ask_shell_approval)
    memory_store = MemoryStore()
    rag_store = ProjectRAGStore()
    offline_bot = FallbackBot(tools, memory_store=memory_store, rag_store=rag_store)
    provider_configs = _resolve_provider_configs(
        model_override=model_override,
        provider_override=provider_override,
    )
    online_bot = (
        MultiProviderOnlineBot(
            configs=provider_configs,
            tool_registry=tools,
            memory_store=memory_store,
            rag_store=rag_store,
        )
        if provider_configs
        else None
    )
    return AdevXBot(
        offline_bot=offline_bot,
        online_bot=online_bot,
        provider_configs=provider_configs,
    )


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="AdevX CLI")
    parser.add_argument(
        "--provider",
        choices=["auto", "openai", "openrouter", "groq", "together", "ollama-local"],
        default=os.environ.get("ADEVX_PROVIDER", "auto"),
        help="LLM provider for online mode.",
    )
    parser.add_argument(
        "--model",
        default=os.environ.get("ADEVX_MODEL", ""),
        help="Optional model override. If omitted, provider defaults are used.",
    )
    parser.add_argument(
        "--mode",
        default=os.environ.get("ADEVX_MODE", "chat"),
        help="Startup mode: chat|coding|image|research|agent",
    )
    parser.add_argument(
        "--once",
        default="",
        help="Run one prompt and exit.",
    )
    parser.add_argument(
        "--no-animation",
        action="store_true",
        help="Disable the interactive thinking animation.",
    )
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    bot = build_bot(model_override=args.model, provider_override=args.provider)
    if normalize_mode_name(args.mode):
        bot.set_mode(args.mode)
    provider_line = "Provider: offline only"
    if bot.provider_configs:
        chain = " -> ".join(cfg.provider for cfg in bot.provider_configs)
        provider_line = f"Providers: {chain}"
    banner = (
        f"AdevX ready in {bot.mode_label} mode.\n"
        f"{DEVELOPER_CREDIT}\n"
        f"AdevX mode: {bot.current_mode}\n"
        f"{provider_line}\n"
        f"Workspace: {WORKSPACE_ROOT}\n"
        "Type /status, /modes, /mode <name>, /online, /offline, or /exit."
    )
    print(banner)

    if args.once:
        reply = bot.ask(args.once)
        print(f"\nAssistant:\n{reply}")
        return 0

    while True:
        try:
            user_text = input("\nYou: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nExiting.")
            return 0

        if user_text.lower() in {"/exit", "exit", "quit"}:
            print("Exiting.")
            return 0
        if not user_text:
            continue

        try:
            use_animation = (not args.no_animation) and (not user_text.startswith("/"))
            reply = ask_with_animation(bot, user_text, animate=use_animation)
        except Exception as exc:
            reply = f"Error: {exc}"
        print(f"\nAssistant:\n{reply}")


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

