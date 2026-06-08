"""Incremental workspace intelligence index with advanced hybrid retrieval.

This module preserves the existing workspace indexing contract while extending it
with:
- incremental file change detection
- lexical + sparse semantic + dense-lite retrieval
- query decomposition, expansion, reranking, and compression
- Python AST parsing
- symbol extraction, import graph, call graph, and reference tracking
"""

from __future__ import annotations

import ast
import asyncio
import hashlib
import json
import math
import os
import re
import time
from pathlib import Path
from typing import Any


_TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{1,}")
_CAMEL_RE = re.compile(r"[A-Z]+(?=[A-Z][a-z]|[0-9]|$)|[A-Z]?[a-z]+|[0-9]+")

_SYMBOL_PATTERNS = [
    re.compile(r"^\s*(?:async\s+def|def|class)\s+([A-Za-z_][A-Za-z0-9_]*)\b"),
    re.compile(r"^\s*(?:function|class|interface|enum|type)\s+([A-Za-z_][A-Za-z0-9_]*)\b"),
    re.compile(r"^\s*(?:const|let|var)\s+([A-Za-z_][A-Za-z0-9_]*)\s*="),
    re.compile(r"^\s*(?:func|fn)\s+([A-Za-z_][A-Za-z0-9_]*)\b"),
    re.compile(
        r"^\s*(?:public|private|protected|static|virtual|inline|\s)*"
        r"[A-Za-z_][A-Za-z0-9_:<>,\*&\s]+\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(",
    ),
]

_IMPORT_PATTERNS = [
    re.compile(r"^\s*import\s+([A-Za-z0-9_./]+)", re.IGNORECASE),
    re.compile(r"^\s*from\s+([A-Za-z0-9_./]+)\s+import\b", re.IGNORECASE),
    re.compile(r"^\s*#include\s+[<\"]([^>\"]+)[>\"]"),
    re.compile(r"^\s*require\(\s*[\"']([^\"']+)[\"']\s*\)"),
]

_QUERY_EXPANSIONS = {
    "repo": ["repository", "workspace", "project"],
    "auth": ["authentication", "authorize", "login"],
    "config": ["configuration", "settings", "env"],
    "bug": ["error", "failure", "issue"],
    "test": ["tests", "testing", "assert"],
    "refactor": ["cleanup", "restructure", "rename"],
    "function": ["def", "method", "callable"],
    "class": ["type", "object", "model"],
    "graph": ["dependency", "import", "call"],
}


class WorkspaceIndexAdapter:
    def __init__(
        self,
        workspace_root: Path | None = None,
        path: Path | None = None,
    ) -> None:
        self.workspace_root = (workspace_root or Path.cwd()).resolve()
        self.path = path or (self.workspace_root / ".adevx_semantic_index.json")
        self._lock = asyncio.Lock()
        self._refresh_interval_s = float(os.environ.get("ADEVX_RAG_REFRESH_S", "8"))
        self._max_file_chars = int(os.environ.get("ADEVX_RAG_MAX_FILE_CHARS", "140000"))
        self._vector_dim = int(os.environ.get("ADEVX_RAG_VECTOR_DIM", "128"))
        self._default_chunk_lines = int(os.environ.get("ADEVX_RAG_CHUNK_LINES", "80"))
        self._default_overlap = int(os.environ.get("ADEVX_RAG_OVERLAP_LINES", "20"))
        self._advanced_retrieval = (
            os.environ.get("ADEVX_ADVANCED_RETRIEVAL", "1").strip().lower()
            not in {"0", "false", "no", "off"}
        )
        self._last_refresh_ts = 0.0

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
        self._data: dict[str, Any] = self._default_data()
        self._load()

    def _default_data(self) -> dict[str, Any]:
        return {
            "version": 3,
            "enabled": True,
            "built_at": 0,
            "updated_at": 0,
            "files_indexed": 0,
            "chunks_indexed": 0,
            "chunk_lines": self._default_chunk_lines,
            "overlap_lines": self._default_overlap,
            "avg_chunk_len": 0.0,
            "files": {},
            "chunks": {},
            "df": {},
            "repo": {
                "symbol_index": {},
                "import_graph": {},
                "call_graph": {},
                "references": {},
                "definition_count": 0,
            },
        }

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return
        if not isinstance(raw, dict):
            return

        data = self._default_data()
        data.update(raw)
        if not isinstance(data.get("files"), dict):
            data["files"] = {}
        if not isinstance(data.get("chunks"), dict):
            data["chunks"] = {}
        if not isinstance(data.get("df"), dict):
            data["df"] = {}
        repo = data.get("repo")
        if not isinstance(repo, dict):
            repo = self._default_data()["repo"]
        repo.setdefault("symbol_index", {})
        repo.setdefault("import_graph", {})
        repo.setdefault("call_graph", {})
        repo.setdefault("references", {})
        repo.setdefault("definition_count", 0)
        data["repo"] = repo
        self._data = data

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(self._data, indent=2, sort_keys=True), encoding="utf-8")
        tmp.replace(self.path)

    @property
    def enabled(self) -> bool:
        return bool(self._data.get("enabled", True))

    async def set_enabled(self, enabled: bool) -> None:
        async with self._lock:
            self._data["enabled"] = bool(enabled)
            await asyncio.to_thread(self._save)

    async def rebuild(self, chunk_lines: int = 80, overlap_lines: int = 20) -> str:
        async with self._lock:
            return await asyncio.to_thread(self._rebuild_sync, chunk_lines, overlap_lines)

    async def status_text(self) -> str:
        async with self._lock:
            return await asyncio.to_thread(self._status_text_sync)

    async def refresh(self) -> str:
        async with self._lock:
            return await asyncio.to_thread(self._update_incremental_sync)

    async def retrieve_context(self, query: str, top_k: int = 4, max_chars: int = 3500) -> str:
        async with self._lock:
            return await asyncio.to_thread(self._retrieve_context_sync, query, top_k, max_chars)

    async def repo_symbols_text(self, limit: int = 120, search: str = "") -> str:
        async with self._lock:
            return await asyncio.to_thread(self._repo_symbols_text_sync, limit, search)

    async def repo_graph_text(self, focus: str = "", max_edges: int = 80) -> str:
        async with self._lock:
            return await asyncio.to_thread(self._repo_graph_text_sync, focus, max_edges)

    async def repo_explain_text(self, symbol: str) -> str:
        async with self._lock:
            return await asyncio.to_thread(self._repo_explain_text_sync, symbol)

    async def repo_references_text(self, symbol: str, limit: int = 30) -> str:
        async with self._lock:
            return await asyncio.to_thread(self._repo_references_text_sync, symbol, limit)

    async def repo_snapshot(self) -> dict[str, Any]:
        async with self._lock:
            return await asyncio.to_thread(self._repo_snapshot_sync)

    def _status_text_sync(self) -> str:
        built_at = int(self._data.get("built_at", 0) or 0)
        updated_at = int(self._data.get("updated_at", 0) or 0)
        built_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(built_at)) if built_at else "never"
        updated_str = (
            time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(updated_at)) if updated_at else "never"
        )
        repo = self._data.get("repo", {})
        return (
            f"RAG enabled: {self.enabled}\n"
            f"Files indexed: {self._data.get('files_indexed', 0)}\n"
            f"Chunks indexed: {self._data.get('chunks_indexed', 0)}\n"
            f"Definitions indexed: {repo.get('definition_count', 0) if isinstance(repo, dict) else 0}\n"
            f"Last full build: {built_str}\n"
            f"Last incremental update: {updated_str}\n"
            f"Chunk lines: {self._data.get('chunk_lines', self._default_chunk_lines)}\n"
            f"Overlap lines: {self._data.get('overlap_lines', self._default_overlap)}\n"
            f"Advanced retrieval: {'on' if self._advanced_retrieval else 'off'}"
        )

    def _iter_source_files(self) -> list[Path]:
        files: list[Path] = []
        root_parts = set(self.workspace_root.parts)
        for path in self.workspace_root.rglob("*"):
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

    @staticmethod
    def _hash_text(text: str) -> str:
        return hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()

    def _tokenize(self, text: str) -> list[str]:
        tokens: list[str] = []
        for raw in _TOKEN_RE.findall(text):
            parts = [raw]
            if "_" in raw:
                parts.extend(p for p in raw.split("_") if p)
            parts.extend(_CAMEL_RE.findall(raw))
            for part in parts:
                t = part.lower().strip()
                if len(t) < 2:
                    continue
                tokens.append(t)
        return tokens

    @staticmethod
    def _char_ngrams(text: str, size: int = 3) -> list[str]:
        collapsed = re.sub(r"\s+", " ", text.lower()).strip()
        if len(collapsed) < size:
            return [collapsed] if collapsed else []
        return [collapsed[i : i + size] for i in range(0, len(collapsed) - size + 1)]

    @staticmethod
    def _extract_symbols(text: str) -> list[str]:
        symbols: list[str] = []
        for line in text.splitlines():
            for pattern in _SYMBOL_PATTERNS:
                match = pattern.search(line)
                if not match:
                    continue
                symbol = match.group(1).strip()
                if symbol and symbol not in symbols:
                    symbols.append(symbol)
                break
            if len(symbols) >= 24:
                break
        return symbols

    def _vectorize(self, tokens: list[str]) -> dict[str, float]:
        if not tokens:
            return {}
        counts: dict[int, float] = {}
        for token in tokens:
            digest = hashlib.sha1(token.encode("utf-8", errors="ignore")).hexdigest()[:8]
            index = int(digest, 16) % self._vector_dim
            counts[index] = counts.get(index, 0.0) + 1.0
        norm = math.sqrt(sum(value * value for value in counts.values()))
        if norm <= 0:
            return {}
        return {str(key): round(value / norm, 6) for key, value in counts.items()}

    def _chunk_file(
        self,
        rel_path: str,
        text: str,
        *,
        chunk_lines: int,
        overlap_lines: int,
    ) -> list[dict[str, Any]]:
        lines = text.splitlines()
        if not lines:
            return []
        step = max(1, chunk_lines - overlap_lines)
        starts = {0}
        for index, line in enumerate(lines):
            if any(pattern.search(line) for pattern in _SYMBOL_PATTERNS):
                starts.add(max(0, index - 2))
        for index in range(0, len(lines), step):
            starts.add(index)

        seen_ranges: set[tuple[int, int]] = set()
        chunks: list[dict[str, Any]] = []
        for start in sorted(starts):
            end = min(len(lines), start + chunk_lines)
            rng = (start, end)
            if rng in seen_ranges:
                continue
            seen_ranges.add(rng)

            block = "\n".join(lines[start:end]).strip()
            if len(block) < 30:
                continue
            tokens = self._tokenize(block)
            if not tokens:
                continue
            tf: dict[str, int] = {}
            for token in tokens:
                tf[token] = tf.get(token, 0) + 1
            symbols = self._extract_symbols(block)
            sparse_vec = self._vectorize(tokens)
            dense_vec = self._vectorize(self._char_ngrams(block))
            chunk_id = hashlib.sha1(
                f"{rel_path}:{start + 1}:{end}:{self._hash_text(block)}".encode("utf-8")
            ).hexdigest()
            chunks.append(
                {
                    "id": chunk_id,
                    "path": rel_path,
                    "start": start + 1,
                    "end": end,
                    "text": block,
                    "tf": tf,
                    "tokens_len": len(tokens),
                    "symbols": symbols,
                    "vec": sparse_vec,
                    "dense_vec": dense_vec,
                }
            )
        return chunks

    @staticmethod
    def _line_snippet(lines: list[str], line_no: int) -> str:
        if 1 <= line_no <= len(lines):
            return lines[line_no - 1].strip()
        return ""

    @staticmethod
    def _function_signature(node: ast.AST) -> str:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return ""
        parts = [arg.arg for arg in node.args.args]
        if node.args.vararg:
            parts.append("*" + node.args.vararg.arg)
        if node.args.kwarg:
            parts.append("**" + node.args.kwarg.arg)
        return f"{node.name}({', '.join(parts)})"

    @staticmethod
    def _callable_name(node: ast.AST) -> str:
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            base = WorkspaceIndexAdapter._callable_name(node.value)
            return f"{base}.{node.attr}" if base else node.attr
        if isinstance(node, ast.Call):
            return WorkspaceIndexAdapter._callable_name(node.func)
        return ""

    def _extract_python_repo_metadata(self, rel_path: str, text: str) -> dict[str, Any]:
        lines = text.splitlines()
        symbols: list[dict[str, Any]] = []
        imports: list[str] = []
        calls: list[dict[str, Any]] = []
        references: list[dict[str, Any]] = []

        try:
            tree = ast.parse(text)
        except SyntaxError:
            return self._extract_text_repo_metadata(rel_path, text)

        seen_refs: set[tuple[str, int, str]] = set()

        class Visitor(ast.NodeVisitor):
            def __init__(self, outer: WorkspaceIndexAdapter) -> None:
                self.outer = outer
                self.stack: list[str] = []

            def _push_symbol(self, node: ast.AST, kind: str) -> None:
                if not hasattr(node, "name"):
                    return
                name = str(getattr(node, "name"))
                qualified = ".".join([*self.stack, name]) if self.stack else name
                doc = ast.get_docstring(node) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) else None
                symbols.append(
                    {
                        "name": name,
                        "qualified_name": qualified,
                        "kind": kind,
                        "line": int(getattr(node, "lineno", 1)),
                        "end_line": int(getattr(node, "end_lineno", getattr(node, "lineno", 1))),
                        "signature": self.outer._function_signature(node),
                        "docstring": (doc or "").strip()[:400],
                        "container": ".".join(self.stack),
                    }
                )

            def visit_Import(self, node: ast.Import) -> None:
                for alias in node.names:
                    imports.append(alias.name)
                self.generic_visit(node)

            def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
                module = node.module or ""
                if module:
                    imports.append(module)
                for alias in node.names:
                    target = f"{module}.{alias.name}".strip(".")
                    if target:
                        imports.append(target)
                self.generic_visit(node)

            def visit_ClassDef(self, node: ast.ClassDef) -> None:
                self._push_symbol(node, "class")
                self.stack.append(node.name)
                self.generic_visit(node)
                self.stack.pop()

            def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
                kind = "method" if self.stack else "function"
                self._push_symbol(node, kind)
                self.stack.append(node.name)
                self.generic_visit(node)
                self.stack.pop()

            def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
                kind = "method" if self.stack else "function"
                self._push_symbol(node, kind)
                self.stack.append(node.name)
                self.generic_visit(node)
                self.stack.pop()

            def visit_Call(self, node: ast.Call) -> None:
                callee = WorkspaceIndexAdapter._callable_name(node.func)
                caller = ".".join(self.stack) or "<module>"
                if callee:
                    calls.append(
                        {
                            "caller": caller,
                            "callee": callee,
                            "line": int(getattr(node, "lineno", 1)),
                        }
                    )
                self.generic_visit(node)

            def visit_Name(self, node: ast.Name) -> None:
                symbol = node.id
                key = (symbol.lower(), int(getattr(node, "lineno", 1)), "name")
                if key not in seen_refs:
                    seen_refs.add(key)
                    references.append(
                        {
                            "symbol": symbol,
                            "line": int(getattr(node, "lineno", 1)),
                            "kind": "name",
                            "snippet": WorkspaceIndexAdapter._line_snippet(lines, int(getattr(node, "lineno", 1))),
                        }
                    )
                self.generic_visit(node)

            def visit_Attribute(self, node: ast.Attribute) -> None:
                symbol = node.attr
                key = (symbol.lower(), int(getattr(node, "lineno", 1)), "attribute")
                if key not in seen_refs:
                    seen_refs.add(key)
                    references.append(
                        {
                            "symbol": symbol,
                            "line": int(getattr(node, "lineno", 1)),
                            "kind": "attribute",
                            "snippet": WorkspaceIndexAdapter._line_snippet(lines, int(getattr(node, "lineno", 1))),
                        }
                    )
                self.generic_visit(node)

        Visitor(self).visit(tree)
        return {
            "language": "python",
            "symbols": symbols[:200],
            "imports": sorted(dict.fromkeys(imports))[:200],
            "calls": calls[:600],
            "references": references[:900],
        }

    def _extract_text_repo_metadata(self, rel_path: str, text: str) -> dict[str, Any]:
        lines = text.splitlines()
        symbols: list[dict[str, Any]] = []
        imports: list[str] = []
        calls: list[dict[str, Any]] = []
        references: list[dict[str, Any]] = []
        seen_symbols: set[str] = set()
        seen_refs: set[tuple[str, int, str]] = set()

        for line_no, line in enumerate(lines, start=1):
            for pattern in _IMPORT_PATTERNS:
                match = pattern.search(line)
                if match:
                    imports.append(match.group(1))
            for pattern in _SYMBOL_PATTERNS:
                match = pattern.search(line)
                if not match:
                    continue
                symbol = match.group(1).strip()
                if symbol and symbol not in seen_symbols:
                    seen_symbols.add(symbol)
                    symbols.append(
                        {
                            "name": symbol,
                            "qualified_name": symbol,
                            "kind": "symbol",
                            "line": line_no,
                            "end_line": line_no,
                            "signature": "",
                            "docstring": "",
                            "container": "",
                        }
                    )
                break

            for match in re.finditer(r"([A-Za-z_][A-Za-z0-9_]*)\s*\(", line):
                callee = match.group(1)
                calls.append({"caller": "<module>", "callee": callee, "line": line_no})

        candidates = {item["name"] for item in symbols}
        candidates.update(name.split(".")[-1] for name in imports)
        for line_no, line in enumerate(lines, start=1):
            tokens = set(_TOKEN_RE.findall(line))
            for symbol in candidates:
                if symbol not in tokens:
                    continue
                key = (symbol.lower(), line_no, "token")
                if key in seen_refs:
                    continue
                seen_refs.add(key)
                references.append(
                    {
                        "symbol": symbol,
                        "line": line_no,
                        "kind": "token",
                        "snippet": line.strip(),
                    }
                )

        language = rel_path.rsplit(".", 1)[-1].lower() if "." in rel_path else "text"
        return {
            "language": language,
            "symbols": symbols[:200],
            "imports": sorted(dict.fromkeys(imports))[:200],
            "calls": calls[:600],
            "references": references[:900],
        }

    def _recompute_repo_cache(self) -> None:
        repo = {
            "symbol_index": {},
            "import_graph": {},
            "call_graph": {},
            "references": {},
            "definition_count": 0,
        }
        files = self._data.get("files", {})
        if not isinstance(files, dict):
            self._data["repo"] = repo
            return

        for rel_path, record in files.items():
            if not isinstance(record, dict):
                continue
            imports = record.get("imports", [])
            if isinstance(imports, list):
                repo["import_graph"][rel_path] = sorted(dict.fromkeys(str(item) for item in imports))[:200]

            symbols = record.get("symbols", [])
            if isinstance(symbols, list):
                for symbol in symbols:
                    if not isinstance(symbol, dict):
                        continue
                    normalized = {
                        "name": str(symbol.get("name", "")),
                        "qualified_name": str(symbol.get("qualified_name", symbol.get("name", ""))),
                        "kind": str(symbol.get("kind", "symbol")),
                        "line": int(symbol.get("line", 1) or 1),
                        "end_line": int(symbol.get("end_line", symbol.get("line", 1)) or 1),
                        "signature": str(symbol.get("signature", "")),
                        "docstring": str(symbol.get("docstring", "")),
                        "container": str(symbol.get("container", "")),
                        "path": rel_path,
                    }
                    for key in {normalized["name"].lower(), normalized["qualified_name"].lower()}:
                        if not key:
                            continue
                        repo["symbol_index"].setdefault(key, []).append(normalized)
                    repo["definition_count"] += 1

            calls = record.get("calls", [])
            if isinstance(calls, list):
                for call in calls:
                    if not isinstance(call, dict):
                        continue
                    caller = str(call.get("caller", "")).strip()
                    callee = str(call.get("callee", "")).strip()
                    if not caller or not callee:
                        continue
                    repo["call_graph"].setdefault(caller, []).append(
                        {
                            "callee": callee,
                            "line": int(call.get("line", 1) or 1),
                            "path": rel_path,
                        }
                    )

            references = record.get("references", [])
            if isinstance(references, list):
                for reference in references:
                    if not isinstance(reference, dict):
                        continue
                    symbol_name = str(reference.get("symbol", "")).strip()
                    if not symbol_name:
                        continue
                    repo["references"].setdefault(symbol_name.lower(), []).append(
                        {
                            "symbol": symbol_name,
                            "line": int(reference.get("line", 1) or 1),
                            "kind": str(reference.get("kind", "token")),
                            "snippet": str(reference.get("snippet", ""))[:240],
                            "path": rel_path,
                        }
                    )

        for key, values in repo["symbol_index"].items():
            repo["symbol_index"][key] = sorted(
                values,
                key=lambda item: (item["path"], item["line"], item["qualified_name"]),
            )
        for key, values in repo["references"].items():
            repo["references"][key] = sorted(
                values,
                key=lambda item: (item["path"], item["line"], item["kind"]),
            )[:500]
        self._data["repo"] = repo

    def _recompute_stats(self) -> None:
        chunks = self._data.get("chunks", {})
        if not isinstance(chunks, dict):
            chunks = {}
            self._data["chunks"] = chunks
        df: dict[str, int] = {}
        total_len = 0
        for chunk in chunks.values():
            if not isinstance(chunk, dict):
                continue
            tf = chunk.get("tf", {})
            if not isinstance(tf, dict):
                continue
            total_len += int(chunk.get("tokens_len", 0) or 0)
            for term in tf.keys():
                df[term] = df.get(term, 0) + 1
        count = max(1, len(chunks))
        self._data["df"] = df
        self._data["avg_chunk_len"] = total_len / count
        self._data["files_indexed"] = len(self._data.get("files", {}))
        self._data["chunks_indexed"] = len(chunks)
        self._recompute_repo_cache()
        self._data["updated_at"] = int(time.time())

    def _remove_file_chunks(self, rel_path: str) -> int:
        files = self._data.get("files", {})
        chunks = self._data.get("chunks", {})
        if not isinstance(files, dict) or not isinstance(chunks, dict):
            return 0
        record = files.get(rel_path)
        if not isinstance(record, dict):
            return 0
        chunk_ids = record.get("chunk_ids", [])
        removed = 0
        if isinstance(chunk_ids, list):
            for chunk_id in chunk_ids:
                if chunk_id in chunks:
                    chunks.pop(chunk_id, None)
                    removed += 1
        files.pop(rel_path, None)
        return removed

    def _index_file_path(
        self,
        path: Path,
        *,
        chunk_lines: int,
        overlap_lines: int,
    ) -> tuple[str, int]:
        try:
            stat = path.stat()
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return "", 0
        text = text[: self._max_file_chars]
        rel_path = str(path.relative_to(self.workspace_root))
        chunks = self._chunk_file(
            rel_path,
            text,
            chunk_lines=chunk_lines,
            overlap_lines=overlap_lines,
        )

        self._remove_file_chunks(rel_path)

        files = self._data.setdefault("files", {})
        all_chunks = self._data.setdefault("chunks", {})
        chunk_ids: list[str] = []
        for chunk in chunks:
            chunk_id = str(chunk["id"])
            all_chunks[chunk_id] = chunk
            chunk_ids.append(chunk_id)

        if path.suffix.lower() == ".py":
            repo_meta = self._extract_python_repo_metadata(rel_path, text)
        else:
            repo_meta = self._extract_text_repo_metadata(rel_path, text)

        files[rel_path] = {
            "size": int(stat.st_size),
            "mtime_ns": int(stat.st_mtime_ns),
            "sha256": self._hash_text(text),
            "chunk_ids": chunk_ids,
            **repo_meta,
        }
        return rel_path, len(chunks)

    def _rebuild_sync(self, chunk_lines: int, overlap_lines: int) -> str:
        chunk_lines = max(20, min(220, int(chunk_lines)))
        overlap_lines = max(5, min(chunk_lines - 1, int(overlap_lines)))
        self._data = self._default_data()
        self._data["chunk_lines"] = chunk_lines
        self._data["overlap_lines"] = overlap_lines

        files = self._iter_source_files()
        files_indexed = 0
        for path in files:
            rel_path, _count = self._index_file_path(
                path,
                chunk_lines=chunk_lines,
                overlap_lines=overlap_lines,
            )
            if rel_path:
                files_indexed += 1

        self._recompute_stats()
        self._data["built_at"] = int(time.time())
        self._save()
        self._last_refresh_ts = time.time()
        return (
            f"Incremental semantic index rebuilt: {files_indexed} files, "
            f"{self._data.get('chunks_indexed', 0)} chunks, "
            f"{self._data.get('repo', {}).get('definition_count', 0)} definitions "
            f"(chunk_lines={chunk_lines}, overlap={overlap_lines})."
        )

    def _update_incremental_sync(self) -> str:
        files = self._data.get("files", {})
        if not isinstance(files, dict):
            files = {}
            self._data["files"] = files

        chunk_lines = int(self._data.get("chunk_lines", self._default_chunk_lines))
        overlap_lines = int(self._data.get("overlap_lines", self._default_overlap))

        current: dict[str, tuple[Path, int, int]] = {}
        for path in self._iter_source_files():
            try:
                stat = path.stat()
            except OSError:
                continue
            rel_path = str(path.relative_to(self.workspace_root))
            current[rel_path] = (path, int(stat.st_size), int(stat.st_mtime_ns))

        old_paths = set(files.keys())
        new_paths = set(current.keys())
        removed = sorted(old_paths - new_paths)
        changed_or_new: list[str] = []
        for rel_path, (_path, size, mtime_ns) in current.items():
            prev = files.get(rel_path)
            if not isinstance(prev, dict):
                changed_or_new.append(rel_path)
                continue
            if int(prev.get("size", -1)) != size or int(prev.get("mtime_ns", -1)) != mtime_ns:
                changed_or_new.append(rel_path)

        removed_chunks = 0
        for rel_path in removed:
            removed_chunks += self._remove_file_chunks(rel_path)

        updated_chunks = 0
        for rel_path in changed_or_new:
            path = current[rel_path][0]
            _rel_path, count = self._index_file_path(
                path,
                chunk_lines=chunk_lines,
                overlap_lines=overlap_lines,
            )
            updated_chunks += count

        if not removed and not changed_or_new:
            self._last_refresh_ts = time.time()
            return "Index up-to-date (no file changes)."

        self._recompute_stats()
        if not int(self._data.get("built_at", 0) or 0):
            self._data["built_at"] = int(time.time())
        self._save()
        self._last_refresh_ts = time.time()
        return (
            f"Incremental update applied: changed/new files={len(changed_or_new)}, "
            f"removed files={len(removed)}, reindexed chunks={updated_chunks}, "
            f"removed chunks={removed_chunks}."
        )

    @staticmethod
    def _cosine_sparse(a: dict[str, float], b: dict[str, float]) -> float:
        if not a or not b:
            return 0.0
        if len(a) > len(b):
            a, b = b, a
        dot = 0.0
        for key, left in a.items():
            right = b.get(key)
            if right is None:
                continue
            dot += float(left) * float(right)
        return max(0.0, dot)

    def _bm25_score(self, query_terms: set[str], chunk: dict[str, Any], n_docs: int, avg_dl: float, df_map: dict[str, int]) -> float:
        tf = chunk.get("tf", {})
        if not isinstance(tf, dict):
            return 0.0
        dl = max(1, int(chunk.get("tokens_len", 0) or 1))
        k1 = 1.2
        b = 0.75
        score = 0.0
        for term in query_terms:
            freq = int(tf.get(term, 0) or 0)
            if freq <= 0:
                continue
            df = int(df_map.get(term, 0) or 0)
            idf = math.log(1.0 + (n_docs - df + 0.5) / (df + 0.5))
            denom = freq + k1 * (1.0 - b + b * (dl / max(avg_dl, 1.0)))
            score += idf * ((freq * (k1 + 1.0)) / max(1e-9, denom))
        return score

    @staticmethod
    def _decompose_query(question: str) -> list[str]:
        parts = [question.strip()]
        parts.extend(segment.strip() for segment in re.split(r"\b(?:and|then|with|plus)\b|[,;/]", question) if segment.strip())
        unique: list[str] = []
        seen: set[str] = set()
        for part in parts:
            normalized = part.lower()
            if normalized in seen:
                continue
            seen.add(normalized)
            unique.append(part)
        return unique[:6]

    def _expand_query_terms(self, question: str) -> list[str]:
        tokens = self._tokenize(question)
        expanded: list[str] = list(tokens)
        for token in tokens:
            expanded.extend(_QUERY_EXPANSIONS.get(token, []))
            if token.endswith("s") and len(token) > 4:
                expanded.append(token[:-1])
        return list(dict.fromkeys(expanded))

    @staticmethod
    def _compress_chunk_text(text: str, query_terms: set[str], max_lines: int = 10) -> str:
        lines = text.splitlines()
        if len(lines) <= max_lines:
            return text.strip()
        kept: list[str] = []
        for line in lines:
            lowered = line.lower()
            if any(term in lowered for term in query_terms):
                kept.append(line)
            elif any(pattern.search(line) for pattern in _SYMBOL_PATTERNS):
                kept.append(line)
            if len(kept) >= max_lines:
                break
        if not kept:
            kept = lines[:max_lines]
        return "\n".join(kept).strip()

    def _basic_hybrid_query(self, question: str, top_k: int = 4) -> list[dict[str, Any]]:
        chunks = self._data.get("chunks", {})
        if not isinstance(chunks, dict) or not chunks:
            return []

        query_tokens = self._tokenize(question)
        if not query_tokens:
            return []
        query_terms = list(dict.fromkeys(query_tokens))
        query_set = set(query_terms)
        sparse_query = self._vectorize(query_terms)
        lower_query = question.lower()

        n_docs = max(1, len(chunks))
        avg_dl = float(self._data.get("avg_chunk_len", 0.0) or 1.0)
        df_map = self._data.get("df", {})
        if not isinstance(df_map, dict):
            df_map = {}

        scored: list[dict[str, Any]] = []
        for chunk in chunks.values():
            if not isinstance(chunk, dict):
                continue
            bm25 = self._bm25_score(query_set, chunk, n_docs, avg_dl, df_map)
            sparse_cos = self._cosine_sparse(sparse_query, chunk.get("vec", {}))
            symbol_boost = 0.0
            symbols = chunk.get("symbols", [])
            if isinstance(symbols, list) and symbols:
                symbol_set = {str(symbol).lower() for symbol in symbols}
                if query_set & symbol_set:
                    symbol_boost = 0.15
            text = str(chunk.get("text", "")).lower()
            phrase_boost = 0.12 if lower_query and lower_query in text else 0.0
            scored.append(
                {
                    "chunk": chunk,
                    "bm25": bm25,
                    "sparse": sparse_cos,
                    "dense": 0.0,
                    "symbol_boost": symbol_boost,
                    "phrase_boost": phrase_boost,
                }
            )

        if not scored:
            return []

        max_bm25 = max(item["bm25"] for item in scored) or 1.0
        for item in scored:
            bm25_n = item["bm25"] / max_bm25
            item["score"] = 0.55 * bm25_n + 0.35 * item["sparse"] + item["symbol_boost"] + item["phrase_boost"]
            item["retrieval"] = "basic-hybrid"

        scored.sort(key=lambda item: item["score"], reverse=True)
        return scored[: max(1, top_k)]

    def _advanced_query(self, question: str, top_k: int = 4) -> list[dict[str, Any]]:
        chunks = self._data.get("chunks", {})
        if not isinstance(chunks, dict) or not chunks:
            return []

        subqueries = self._decompose_query(question)
        lower_query = question.lower()
        n_docs = max(1, len(chunks))
        avg_dl = float(self._data.get("avg_chunk_len", 0.0) or 1.0)
        df_map = self._data.get("df", {})
        if not isinstance(df_map, dict):
            df_map = {}

        candidate_map: dict[str, dict[str, Any]] = {}
        for subquery in subqueries:
            expanded_terms = self._expand_query_terms(subquery)
            if not expanded_terms:
                continue
            term_set = set(expanded_terms)
            sparse_query = self._vectorize(expanded_terms)
            dense_query = self._vectorize(self._char_ngrams(" ".join(expanded_terms)))
            for chunk in chunks.values():
                if not isinstance(chunk, dict):
                    continue
                chunk_id = str(chunk.get("id", ""))
                bm25 = self._bm25_score(term_set, chunk, n_docs, avg_dl, df_map)
                sparse_cos = self._cosine_sparse(sparse_query, chunk.get("vec", {}))
                dense_cos = self._cosine_sparse(dense_query, chunk.get("dense_vec", {}))
                path = str(chunk.get("path", "")).lower()
                text = str(chunk.get("text", "")).lower()
                symbols = chunk.get("symbols", [])
                symbol_set = {str(symbol).lower() for symbol in symbols} if isinstance(symbols, list) else set()
                symbol_boost = 0.18 if term_set & symbol_set else 0.0
                phrase_boost = 0.18 if lower_query and lower_query in text else 0.0
                path_boost = 0.08 if any(term in path for term in term_set) else 0.0

                bm25_component = bm25
                if bm25_component <= 0 and sparse_cos <= 0 and dense_cos <= 0 and symbol_boost <= 0:
                    continue

                current = candidate_map.get(chunk_id)
                if current is None:
                    current = {
                        "chunk": chunk,
                        "bm25": bm25_component,
                        "sparse": sparse_cos,
                        "dense": dense_cos,
                        "symbol_boost": symbol_boost,
                        "phrase_boost": phrase_boost,
                        "path_boost": path_boost,
                        "subqueries": [subquery],
                    }
                    candidate_map[chunk_id] = current
                else:
                    current["bm25"] = max(current["bm25"], bm25_component)
                    current["sparse"] = max(current["sparse"], sparse_cos)
                    current["dense"] = max(current["dense"], dense_cos)
                    current["symbol_boost"] = max(current["symbol_boost"], symbol_boost)
                    current["phrase_boost"] = max(current["phrase_boost"], phrase_boost)
                    current["path_boost"] = max(current["path_boost"], path_boost)
                    current["subqueries"].append(subquery)

        if not candidate_map:
            return self._basic_hybrid_query(question, top_k=top_k)

        candidates = list(candidate_map.values())
        max_bm25 = max(item["bm25"] for item in candidates) or 1.0
        for item in candidates:
            bm25_norm = item["bm25"] / max_bm25
            base_score = (
                0.4 * bm25_norm
                + 0.22 * item["sparse"]
                + 0.18 * item["dense"]
                + item["symbol_boost"]
                + item["phrase_boost"]
                + item["path_boost"]
            )
            item["score"] = base_score

        reranked = self._rerank_candidates(question, candidates)
        return reranked[: max(1, top_k)]

    def _rerank_candidates(self, question: str, candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
        query_terms = set(self._expand_query_terms(question))
        lowered_query = question.lower()
        for item in candidates:
            chunk = item["chunk"]
            text = str(chunk.get("text", ""))
            lowered_text = text.lower()
            text_terms = set(self._tokenize(text))
            coverage = len(query_terms & text_terms) / max(1, len(query_terms))
            exact_phrase = 0.12 if lowered_query and lowered_query in lowered_text else 0.0
            symbol_match = 0.12 if query_terms & {s.lower() for s in chunk.get("symbols", [])} else 0.0
            definition_bonus = 0.08 if any(pattern.search(line) for line in text.splitlines()[:4] for pattern in _SYMBOL_PATTERNS) else 0.0
            item["rerank_score"] = item["score"] + coverage * 0.35 + exact_phrase + symbol_match + definition_bonus
            item["retrieval"] = "advanced-hybrid"
        candidates.sort(key=lambda item: item["rerank_score"], reverse=True)
        return candidates

    def _ensure_index_ready(self) -> None:
        if not self.enabled:
            return
        chunks = self._data.get("chunks", {})
        if not isinstance(chunks, dict):
            chunks = {}
        now = time.time()
        if not chunks:
            self._rebuild_sync(
                chunk_lines=int(self._data.get("chunk_lines", self._default_chunk_lines)),
                overlap_lines=int(self._data.get("overlap_lines", self._default_overlap)),
            )
            return
        if now - self._last_refresh_ts >= self._refresh_interval_s:
            self._update_incremental_sync()

    def _retrieve_context_sync(self, query: str, top_k: int, max_chars: int) -> str:
        if not self.enabled:
            return ""
        question = query.strip()
        if not question:
            return ""
        self._ensure_index_ready()

        if self._advanced_retrieval:
            hits = self._advanced_query(question, top_k=max(1, top_k))
        else:
            hits = self._basic_hybrid_query(question, top_k=max(1, top_k))
        if not hits:
            return ""

        query_terms = set(self._expand_query_terms(question))
        retrieval_label = hits[0].get("retrieval", "basic-hybrid")
        parts = [f"Project context ({retrieval_label} retrieval: lexical + semantic + repository intelligence):"]
        total = len(parts[0])
        for hit in hits:
            chunk = hit["chunk"]
            path = chunk.get("path", "")
            start = int(chunk.get("start", 1))
            end = int(chunk.get("end", start))
            raw_text = str(chunk.get("text", "")).strip()
            compressed = self._compress_chunk_text(raw_text, query_terms, max_lines=10)
            symbols = chunk.get("symbols", [])
            symbol_text = ", ".join(str(symbol) for symbol in symbols[:6]) if isinstance(symbols, list) else ""
            header = (
                f"[{path}:{start}-{end}] score={hit.get('rerank_score', hit.get('score', 0.0)):.3f} "
                f"(bm25={hit.get('bm25', 0.0):.3f}, sparse={hit.get('sparse', 0.0):.3f}, dense={hit.get('dense', 0.0):.3f})"
            )
            if symbol_text:
                header += f" symbols={symbol_text}"
            snippet = f"{header}\n{compressed}"
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

    def _repo_snapshot_sync(self) -> dict[str, Any]:
        self._ensure_index_ready()
        repo = self._data.get("repo", {})
        if not isinstance(repo, dict):
            return {}
        return json.loads(json.dumps(repo))

    def _lookup_symbol_records(self, symbol: str) -> list[dict[str, Any]]:
        repo = self._data.get("repo", {})
        if not isinstance(repo, dict):
            return []
        symbol_index = repo.get("symbol_index", {})
        if not isinstance(symbol_index, dict):
            return []
        key = symbol.strip().lower()
        if not key:
            return []
        exact = symbol_index.get(key, [])
        if exact:
            return list(exact)
        fuzzy: list[dict[str, Any]] = []
        for candidate, records in symbol_index.items():
            if candidate.endswith("." + key) or key in candidate:
                fuzzy.extend(record for record in records if isinstance(record, dict))
        return fuzzy

    def _repo_symbols_text_sync(self, limit: int = 120, search: str = "") -> str:
        self._ensure_index_ready()
        repo = self._data.get("repo", {})
        if not isinstance(repo, dict):
            return "Repository symbol index is unavailable."
        symbol_index = repo.get("symbol_index", {})
        if not isinstance(symbol_index, dict) or not symbol_index:
            return "Repository symbol index is empty. Run /rag rebuild or /repo symbols again after files are indexed."

        query = search.strip().lower()
        unique: dict[tuple[str, str, int], dict[str, Any]] = {}
        for records in symbol_index.values():
            if not isinstance(records, list):
                continue
            for record in records:
                if not isinstance(record, dict):
                    continue
                qualified = str(record.get("qualified_name", record.get("name", "")))
                path = str(record.get("path", ""))
                line = int(record.get("line", 1) or 1)
                if query and query not in qualified.lower() and query not in path.lower():
                    continue
                unique[(qualified, path, line)] = record

        rows = sorted(
            unique.values(),
            key=lambda item: (str(item.get("path", "")), int(item.get("line", 1) or 1), str(item.get("qualified_name", ""))),
        )
        if not rows:
            return f"No symbols matched '{search}'."

        lines = [f"Repository symbols ({min(limit, len(rows))}/{len(rows)} shown):"]
        for record in rows[: max(1, limit)]:
            lines.append(
                f"- {record.get('kind', 'symbol')}: {record.get('qualified_name', record.get('name', ''))} "
                f"[{record.get('path', '')}:{record.get('line', 1)}]"
            )
        return "\n".join(lines)

    def _repo_graph_text_sync(self, focus: str = "", max_edges: int = 80) -> str:
        self._ensure_index_ready()
        repo = self._data.get("repo", {})
        if not isinstance(repo, dict):
            return "Repository graph is unavailable."
        import_graph = repo.get("import_graph", {})
        call_graph = repo.get("call_graph", {})
        if not isinstance(import_graph, dict):
            import_graph = {}
        if not isinstance(call_graph, dict):
            call_graph = {}

        needle = focus.strip().lower()
        lines = ["Repository graph summary:"]
        edge_count = 0

        lines.append("Import edges:")
        found_imports = False
        for path in sorted(import_graph.keys()):
            if needle and needle not in path.lower() and not any(needle in imp.lower() for imp in import_graph.get(path, [])):
                continue
            found_imports = True
            imports = import_graph.get(path, [])
            preview = ", ".join(str(item) for item in imports[:6])
            more = " ..." if len(imports) > 6 else ""
            lines.append(f"- {path} -> {preview}{more}" if preview else f"- {path} -> <none>")
            edge_count += len(imports)
            if edge_count >= max_edges:
                break
        if not found_imports:
            lines.append("- <no import edges matched>")

        lines.append("Call edges:")
        call_lines = 0
        for caller in sorted(call_graph.keys()):
            edges = call_graph.get(caller, [])
            if not isinstance(edges, list):
                continue
            visible = [edge for edge in edges if isinstance(edge, dict)]
            if needle and needle not in caller.lower() and not any(needle in str(edge.get("callee", "")).lower() for edge in visible):
                continue
            callees = ", ".join(str(edge.get("callee", "")) for edge in visible[:6])
            path = visible[0].get("path", "") if visible else ""
            more = " ..." if len(visible) > 6 else ""
            lines.append(f"- {caller} [{path}] -> {callees}{more}" if callees else f"- {caller} -> <none>")
            call_lines += 1
            if call_lines >= max_edges:
                break
        if call_lines == 0:
            lines.append("- <no call edges matched>")
        return "\n".join(lines)

    def _repo_explain_text_sync(self, symbol: str) -> str:
        self._ensure_index_ready()
        records = self._lookup_symbol_records(symbol)
        if not records:
            return f"No repository symbol named '{symbol}' was found."

        best = records[0]
        qualified = str(best.get("qualified_name", best.get("name", symbol)))
        path = str(best.get("path", ""))
        line = int(best.get("line", 1) or 1)
        end_line = int(best.get("end_line", line) or line)
        kind = str(best.get("kind", "symbol"))
        signature = str(best.get("signature", "")).strip()
        docstring = str(best.get("docstring", "")).strip()

        repo = self._data.get("repo", {})
        call_graph = repo.get("call_graph", {}) if isinstance(repo, dict) else {}
        references = repo.get("references", {}) if isinstance(repo, dict) else {}
        outgoing = call_graph.get(qualified, []) if isinstance(call_graph, dict) else []
        incoming = references.get(best.get("name", symbol).lower(), []) if isinstance(references, dict) else []

        related = self._retrieve_context_sync(symbol, top_k=2, max_chars=1200)
        lines = [f"Repository explanation for {qualified}:"]
        lines.append(f"- kind: {kind}")
        lines.append(f"- path: {path}:{line}-{end_line}")
        if signature:
            lines.append(f"- signature: {signature}")
        if best.get("container"):
            lines.append(f"- container: {best.get('container')}")
        lines.append(f"- outgoing calls: {len(outgoing) if isinstance(outgoing, list) else 0}")
        lines.append(f"- references indexed: {len(incoming) if isinstance(incoming, list) else 0}")
        if docstring:
            lines.append("Docstring:")
            lines.append(docstring)
        if isinstance(outgoing, list) and outgoing:
            lines.append("Direct callees:")
            for call in outgoing[:8]:
                lines.append(f"- {call.get('callee', '')} [{call.get('path', '')}:{call.get('line', 1)}]")
        if related:
            lines.append("Related context:")
            lines.append(related)
        return "\n".join(lines)

    def _repo_references_text_sync(self, symbol: str, limit: int = 30) -> str:
        self._ensure_index_ready()
        repo = self._data.get("repo", {})
        if not isinstance(repo, dict):
            return "Repository references are unavailable."
        references = repo.get("references", {})
        if not isinstance(references, dict):
            return "Repository references are unavailable."

        key = symbol.strip().lower()
        matches = references.get(key, [])
        if not matches:
            records = self._lookup_symbol_records(symbol)
            if records:
                alt = str(records[0].get("name", symbol)).lower()
                matches = references.get(alt, [])
        if not matches:
            return f"No indexed references found for '{symbol}'."

        lines = [f"Repository references for {symbol} ({min(limit, len(matches))}/{len(matches)} shown):"]
        for record in matches[: max(1, limit)]:
            lines.append(
                f"- {record.get('path', '')}:{record.get('line', 1)} "
                f"[{record.get('kind', 'token')}] {record.get('snippet', '').strip()}"
            )
        return "\n".join(lines)
