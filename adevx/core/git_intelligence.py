"""Git-aware repository analysis helpers for AdevX."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any


class GitIntelligence:
    def __init__(self, workspace_root: Path | str) -> None:
        self.workspace_root = Path(workspace_root).resolve()

    def _git(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", *args],
            cwd=self.workspace_root,
            text=True,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )

    def _is_repo(self) -> bool:
        proc = self._git("rev-parse", "--is-inside-work-tree")
        return proc.returncode == 0 and proc.stdout.strip() == "true"

    def analyze(self, revision_range: str = "") -> str:
        if not self._is_repo():
            return "Current workspace is not a git repository."

        status = self._git("status", "--short", "--branch")
        remotes = self._git("remote", "-v")
        recent = self._git("log", "--oneline", "-5")
        changed = self._git("diff", "--name-only", revision_range) if revision_range else self._git("status", "--porcelain")

        lines = ["Git repository analysis:"]
        branch_line = status.stdout.splitlines()[0].strip() if status.stdout.strip() else "<unknown branch>"
        lines.append(f"- branch: {branch_line}")

        remote_lines = []
        for line in remotes.stdout.splitlines():
            line = line.strip()
            if line and line not in remote_lines:
                remote_lines.append(line)
        lines.append("- remotes:")
        if remote_lines:
            for line in remote_lines[:6]:
                lines.append(f"  {line}")
        else:
            lines.append("  <none>")

        changed_lines = [line.strip() for line in changed.stdout.splitlines() if line.strip()]
        if not changed_lines and changed.returncode == 0 and not revision_range:
            changed_lines = [line.strip() for line in status.stdout.splitlines()[1:] if line.strip()]
        lines.append(f"- changed entries: {len(changed_lines)}")
        for line in changed_lines[:12]:
            lines.append(f"  {line}")

        lines.append("- recent commits:")
        if recent.stdout.strip():
            for line in recent.stdout.splitlines():
                lines.append(f"  {line.strip()}")
        else:
            lines.append("  <none>")
        return "\n".join(lines)

    def summarize(self, revision: str = "HEAD") -> str:
        if not self._is_repo():
            return "Current workspace is not a git repository."
        proc = self._git("show", "--stat", "--format=%H%n%an%n%ad%n%s", revision)
        if proc.returncode != 0:
            message = proc.stderr.strip() or proc.stdout.strip() or "unknown git error"
            return f"Unable to summarize revision '{revision}': {message}"
        lines = [line.rstrip() for line in proc.stdout.splitlines()]
        if len(lines) < 4:
            return proc.stdout.strip() or f"No summary available for {revision}."
        commit_hash, author, authored_at, subject = lines[:4]
        body = lines[4:]
        summary = [
            f"Commit summary for {revision}:",
            f"- commit: {commit_hash}",
            f"- author: {author}",
            f"- date: {authored_at}",
            f"- subject: {subject}",
        ]
        body_lines = [line.strip() for line in body if line.strip()]
        if body_lines:
            summary.append("- stats:")
            for line in body_lines[:12]:
                summary.append(f"  {line}")
        return "\n".join(summary)

    def impact(self, target: str = "", repo_snapshot: dict[str, Any] | None = None) -> str:
        if not self._is_repo():
            return "Current workspace is not a git repository."

        changed_files = self._resolve_changed_files(target)
        if not changed_files:
            return "No changed files were found for impact analysis."

        impacted = set(changed_files)
        import_impacts = self._import_impacts(changed_files, repo_snapshot or {})
        reference_impacts = self._reference_impacts(changed_files, repo_snapshot or {})
        impacted.update(import_impacts)
        impacted.update(reference_impacts)

        lines = ["Git change impact analysis:"]
        lines.append("- changed files:")
        for path in changed_files[:20]:
            lines.append(f"  {path}")
        if import_impacts:
            lines.append("- impacted by imports:")
            for path in sorted(import_impacts)[:20]:
                lines.append(f"  {path}")
        if reference_impacts:
            lines.append("- impacted by symbol references:")
            for path in sorted(reference_impacts)[:20]:
                lines.append(f"  {path}")
        lines.append(f"- total impacted files: {len(impacted)}")
        return "\n".join(lines)

    def _resolve_changed_files(self, target: str) -> list[str]:
        raw = target.strip()
        if raw:
            if ".." in raw:
                proc = self._git("diff", "--name-only", raw)
                if proc.returncode == 0:
                    return [line.strip() for line in proc.stdout.splitlines() if line.strip()]
            candidate = (self.workspace_root / raw).resolve()
            if candidate.exists():
                try:
                    rel = str(candidate.relative_to(self.workspace_root))
                except ValueError:
                    rel = raw
                return [rel.replace("\\", "/")]
            proc = self._git("show", "--name-only", "--format=", raw)
            if proc.returncode == 0:
                return [line.strip() for line in proc.stdout.splitlines() if line.strip()]

        diff = self._git("diff", "--name-only", "HEAD")
        changed = [line.strip() for line in diff.stdout.splitlines() if line.strip()]
        if changed:
            return changed

        status = self._git("status", "--porcelain")
        return [line[3:].strip() for line in status.stdout.splitlines() if len(line) > 3]

    @staticmethod
    def _module_aliases(path: str) -> set[str]:
        clean = path.replace("\\", "/")
        base = clean.rsplit("/", 1)[-1]
        stem = base.rsplit(".", 1)[0]
        dotted = clean.rsplit(".", 1)[0].replace("/", ".")
        return {clean.lower(), base.lower(), stem.lower(), dotted.lower()}

    def _import_impacts(self, changed_files: list[str], repo_snapshot: dict[str, Any]) -> set[str]:
        impacted: set[str] = set()
        import_graph = repo_snapshot.get("import_graph", {}) if isinstance(repo_snapshot, dict) else {}
        if not isinstance(import_graph, dict):
            return impacted
        alias_map = {path: self._module_aliases(path) for path in changed_files}
        for path, imports in import_graph.items():
            if path in changed_files or not isinstance(imports, list):
                continue
            lowered_imports = [str(item).lower() for item in imports]
            for aliases in alias_map.values():
                if any(any(alias in imported for alias in aliases) for imported in lowered_imports):
                    impacted.add(path)
                    break
        return impacted

    def _reference_impacts(self, changed_files: list[str], repo_snapshot: dict[str, Any]) -> set[str]:
        impacted: set[str] = set()
        if not isinstance(repo_snapshot, dict):
            return impacted
        symbol_index = repo_snapshot.get("symbol_index", {})
        references = repo_snapshot.get("references", {})
        if not isinstance(symbol_index, dict) or not isinstance(references, dict):
            return impacted

        changed_symbols: set[str] = set()
        for records in symbol_index.values():
            if not isinstance(records, list):
                continue
            for record in records:
                if not isinstance(record, dict):
                    continue
                if str(record.get("path", "")) in changed_files:
                    changed_symbols.add(str(record.get("name", "")).lower())

        for symbol in changed_symbols:
            for reference in references.get(symbol, []):
                if not isinstance(reference, dict):
                    continue
                path = str(reference.get("path", ""))
                if path and path not in changed_files:
                    impacted.add(path)
        return impacted
