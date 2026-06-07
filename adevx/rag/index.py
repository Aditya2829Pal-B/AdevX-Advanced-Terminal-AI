"""Incremental semantic workspace index with hybrid retrieval.

This replaces the previous monolith wrapper and provides:
- incremental file change detection
- semantic-ish sparse embeddings (hash-based vectors)
- BM25 lexical scoring
- hybrid ranking (BM25 + cosine + symbol boosts)
"""

from __future__ import annotations

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
        self._last_refresh_ts = 0.0

        self._skip_dirs = {
            ".git",
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
            "version": 2,
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

    def _status_text_sync(self) -> str:
        built_at = int(self._data.get("built_at", 0) or 0)
        updated_at = int(self._data.get("updated_at", 0) or 0)
        built_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(built_at)) if built_at else "never"
        updated_str = (
            time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(updated_at)) if updated_at else "never"
        )
        return (
            f"RAG enabled: {self.enabled}\n"
            f"Files indexed: {self._data.get('files_indexed', 0)}\n"
            f"Chunks indexed: {self._data.get('chunks_indexed', 0)}\n"
            f"Last full build: {built_str}\n"
            f"Last incremental update: {updated_str}\n"
            f"Chunk lines: {self._data.get('chunk_lines', self._default_chunk_lines)}\n"
            f"Overlap lines: {self._data.get('overlap_lines', self._default_overlap)}"
        )

    def _iter_source_files(self) -> list[Path]:
        files: list[Path] = []
        for path in self.workspace_root.rglob("*"):
            if not path.is_file():
                continue
            if any(part in self._skip_dirs for part in path.parts):
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
    def _extract_symbols(text: str) -> list[str]:
        symbols: list[str] = []
        for line in text.splitlines():
            for pattern in _SYMBOL_PATTERNS:
                m = pattern.search(line)
                if not m:
                    continue
                sym = m.group(1).strip()
                if sym and sym not in symbols:
                    symbols.append(sym)
                break
            if len(symbols) >= 24:
                break
        return symbols

    def _vectorize(self, tokens: list[str]) -> dict[str, float]:
        if not tokens:
            return {}
        counts: dict[int, float] = {}
        for tok in tokens:
            h = int(hashlib.sha1(tok.encode("utf-8", errors="ignore")).hexdigest()[:8], 16)
            idx = h % self._vector_dim
            counts[idx] = counts.get(idx, 0.0) + 1.0
        norm = math.sqrt(sum(v * v for v in counts.values()))
        if norm <= 0:
            return {}
        return {str(k): round(v / norm, 6) for k, v in counts.items()}

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
        for i, line in enumerate(lines):
            if any(p.search(line) for p in _SYMBOL_PATTERNS):
                starts.add(max(0, i - 2))
        for i in range(0, len(lines), step):
            starts.add(i)

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
            for t in tokens:
                tf[t] = tf.get(t, 0) + 1
            symbols = self._extract_symbols(block)
            vec = self._vectorize(tokens)
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
                    "vec": vec,
                }
            )
        return chunks

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
        self._data["updated_at"] = int(time.time())

    def _remove_file_chunks(self, rel_path: str) -> int:
        files = self._data.get("files", {})
        chunks = self._data.get("chunks", {})
        if not isinstance(files, dict) or not isinstance(chunks, dict):
            return 0
        rec = files.get(rel_path)
        if not isinstance(rec, dict):
            return 0
        chunk_ids = rec.get("chunk_ids", [])
        removed = 0
        if isinstance(chunk_ids, list):
            for cid in chunk_ids:
                if cid in chunks:
                    chunks.pop(cid, None)
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

        # Replace old chunks for this file.
        self._remove_file_chunks(rel_path)

        files = self._data.setdefault("files", {})
        all_chunks = self._data.setdefault("chunks", {})
        chunk_ids: list[str] = []
        for chunk in chunks:
            cid = str(chunk["id"])
            all_chunks[cid] = chunk
            chunk_ids.append(cid)
        files[rel_path] = {
            "size": int(stat.st_size),
            "mtime_ns": int(stat.st_mtime_ns),
            "sha256": self._hash_text(text),
            "chunk_ids": chunk_ids,
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
            rel, n = self._index_file_path(path, chunk_lines=chunk_lines, overlap_lines=overlap_lines)
            if rel:
                files_indexed += 1
            _ = n

        self._recompute_stats()
        self._data["built_at"] = int(time.time())
        self._save()
        self._last_refresh_ts = time.time()
        return (
            f"Incremental semantic index rebuilt: {files_indexed} files, "
            f"{self._data.get('chunks_indexed', 0)} chunks "
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
            rel = str(path.relative_to(self.workspace_root))
            current[rel] = (path, int(stat.st_size), int(stat.st_mtime_ns))

        old_rel = set(files.keys())
        new_rel = set(current.keys())
        removed = sorted(old_rel - new_rel)
        changed_or_new: list[str] = []
        for rel, (_path, size, mtime_ns) in current.items():
            prev = files.get(rel)
            if not isinstance(prev, dict):
                changed_or_new.append(rel)
                continue
            if int(prev.get("size", -1)) != size or int(prev.get("mtime_ns", -1)) != mtime_ns:
                changed_or_new.append(rel)

        removed_chunks = 0
        for rel in removed:
            removed_chunks += self._remove_file_chunks(rel)

        updated_chunks = 0
        for rel in changed_or_new:
            path = current[rel][0]
            _rel, n = self._index_file_path(path, chunk_lines=chunk_lines, overlap_lines=overlap_lines)
            updated_chunks += n

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
        for key, av in a.items():
            bv = b.get(key)
            if bv is None:
                continue
            dot += float(av) * float(bv)
        return max(0.0, dot)

    def _query_hybrid(self, question: str, top_k: int = 4) -> list[dict[str, Any]]:
        chunks = self._data.get("chunks", {})
        if not isinstance(chunks, dict) or not chunks:
            return []

        q_tokens = self._tokenize(question)
        if not q_tokens:
            return []
        q_terms = list(dict.fromkeys(q_tokens))
        q_set = set(q_terms)
        q_vec = self._vectorize(q_terms)
        q_lower = question.lower()

        n_docs = max(1, len(chunks))
        avg_dl = float(self._data.get("avg_chunk_len", 0.0) or 1.0)
        df_map = self._data.get("df", {})
        if not isinstance(df_map, dict):
            df_map = {}

        k1 = 1.2
        b = 0.75
        scored: list[dict[str, Any]] = []
        for chunk in chunks.values():
            if not isinstance(chunk, dict):
                continue
            tf = chunk.get("tf", {})
            if not isinstance(tf, dict):
                continue
            dl = max(1, int(chunk.get("tokens_len", 0) or 1))

            bm25 = 0.0
            for term in q_set:
                freq = int(tf.get(term, 0) or 0)
                if freq <= 0:
                    continue
                df = int(df_map.get(term, 0) or 0)
                idf = math.log(1.0 + (n_docs - df + 0.5) / (df + 0.5))
                denom = freq + k1 * (1.0 - b + b * (dl / avg_dl))
                bm25 += idf * ((freq * (k1 + 1.0)) / max(1e-9, denom))

            cos = self._cosine_sparse(q_vec, chunk.get("vec", {}))
            symbol_boost = 0.0
            symbols = chunk.get("symbols", [])
            if isinstance(symbols, list) and symbols:
                symbol_set = {str(s).lower() for s in symbols}
                if q_set & symbol_set:
                    symbol_boost = 0.15

            text = str(chunk.get("text", "")).lower()
            phrase_boost = 0.12 if q_lower and q_lower in text else 0.0

            scored.append(
                {
                    "chunk": chunk,
                    "bm25": bm25,
                    "cos": cos,
                    "symbol_boost": symbol_boost,
                    "phrase_boost": phrase_boost,
                }
            )

        if not scored:
            return []

        max_bm25 = max(item["bm25"] for item in scored) or 1.0
        for item in scored:
            bm25_n = item["bm25"] / max_bm25
            item["score"] = 0.55 * bm25_n + 0.35 * item["cos"] + item["symbol_boost"] + item["phrase_boost"]

        scored.sort(key=lambda x: x["score"], reverse=True)
        return scored[: max(1, top_k)]

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
        q = query.strip()
        if not q:
            return ""
        self._ensure_index_ready()

        hits = self._query_hybrid(q, top_k=max(1, top_k))
        if not hits:
            return ""

        parts = ["Project context (hybrid retrieval: lexical + semantic + symbol):"]
        total = len(parts[0])
        for hit in hits:
            chunk = hit["chunk"]
            path = chunk.get("path", "")
            start = int(chunk.get("start", 1))
            end = int(chunk.get("end", start))
            text = str(chunk.get("text", "")).strip()
            symbols = chunk.get("symbols", [])
            sym_text = ", ".join(str(s) for s in symbols[:6]) if isinstance(symbols, list) else ""
            header = (
                f"[{path}:{start}-{end}] score={hit['score']:.3f} "
                f"(bm25={hit['bm25']:.3f}, cos={hit['cos']:.3f})"
            )
            if sym_text:
                header += f" symbols={sym_text}"
            snippet = f"{header}\n{text}"
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
