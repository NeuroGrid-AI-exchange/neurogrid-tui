"""Workspace-scoped text search, backed by ripgrep with a Python fallback."""

import json
import shutil
import subprocess
from pathlib import Path

from nrgrd.tools.registry import PermissionLevel, Tool
from nrgrd.workspace.tools import iter_workspace_files

MAX_MATCHES = 200
_TIMEOUT_SECONDS = 15

SEARCH_SCHEMA = {
    "type": "object",
    "properties": {
        "query": {"type": "string", "description": "Literal text to search for."},
        "path": {"type": "string", "default": "."},
    },
    "required": ["query"],
}


def _resolve(root: Path, user_path: str) -> Path:
    candidate = (root / user_path).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as error:
        raise OSError("Path must stay within the current workspace.") from error
    return candidate


def _search_ripgrep(root: Path, query: str, rel_path: str) -> list[str] | None:
    if shutil.which("rg") is None:
        return None
    try:
        result = subprocess.run(
            ["rg", "--line-number", "--no-heading", "--color", "never", "-m", "5", "--", query, rel_path],
            cwd=root,
            capture_output=True,
            text=True,
            errors="replace",
            timeout=_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode not in (0, 1):
        return None
    return result.stdout.splitlines()[:MAX_MATCHES]


def _search_python(root: Path, query: str, rel_path: str) -> list[str]:
    base = _resolve(root, rel_path)
    paths = [base] if base.is_file() else iter_workspace_files(root, base)
    matches: list[str] = []
    for path in paths:
        relative = path.relative_to(root)
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for line_number, line in enumerate(text.splitlines(), start=1):
            if query in line:
                matches.append(f"{relative}:{line_number}:{line.strip()}")
                if len(matches) >= MAX_MATCHES:
                    return matches
    return matches


def _execute(root: Path, arguments: str) -> str:
    try:
        payload = json.loads(arguments or "{}")
        query = payload["query"]
    except (json.JSONDecodeError, KeyError, TypeError) as error:
        return f"Invalid tool arguments: {error}"
    if not isinstance(query, str) or not query:
        return "Invalid tool arguments: query must be a non-empty string."
    rel_path = payload.get("path", ".")

    try:
        _resolve(root, rel_path)
    except OSError as error:
        return str(error)

    matches = _search_ripgrep(root, query, rel_path)
    if matches is None:
        matches = _search_python(root, query, rel_path)
    return "\n".join(matches) or "No matches found."


def build_search_tool(root: Path) -> Tool:
    return Tool(
        name="search",
        description="Search file contents in the workspace for a literal text query.",
        parameters=SEARCH_SCHEMA,
        permission=PermissionLevel.ALLOW,
        handler=lambda arguments: _execute(root, arguments),
    )
