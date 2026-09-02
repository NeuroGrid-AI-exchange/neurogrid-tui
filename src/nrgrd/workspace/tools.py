"""Safe, workspace-scoped tools exposed to the coding assistant."""

import json
from pathlib import Path
from typing import Any


MAX_FILE_BYTES = 200_000
MAX_RESULTS = 200
IGNORED_DIRECTORIES = {".git", ".venv", "__pycache__", ".mypy_cache"}


FILE_TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "list_files",
            "description": "List files and directories below a workspace-relative path.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string", "default": "."}},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read a UTF-8 text file inside the workspace.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Create or replace a UTF-8 text file inside the workspace.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "edit_file",
            "description": "Replace one exact, unique text block in a workspace file.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "old_text": {"type": "string"},
                    "new_text": {"type": "string"},
                },
                "required": ["path", "old_text", "new_text"],
            },
        },
    },
]

# MCP uses the same JSON Schemas under ``inputSchema``. The OpenAI-compatible
# adapter above is deliberately derived from this public MCP tool catalog.
MCP_TOOLS: list[dict[str, Any]] = [
    {
        "name": tool["function"]["name"],
        "description": tool["function"]["description"],
        "inputSchema": tool["function"]["parameters"],
    }
    for tool in FILE_TOOLS
]


class WorkspaceTools:
    """Execute coding tools without allowing access outside the project root."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def execute(self, name: str, arguments: str) -> str:
        try:
            payload = json.loads(arguments or "{}")
        except json.JSONDecodeError as error:
            return f"Invalid tool arguments: {error}"

        try:
            if name == "list_files":
                return self.list_files(payload.get("path", "."))
            if name == "read_file":
                return self.read_file(payload["path"])
            if name == "write_file":
                return self.write_file(payload["path"], payload["content"])
            if name == "edit_file":
                return self.edit_file(
                    payload["path"], payload["old_text"], payload["new_text"]
                )
        except (KeyError, TypeError) as error:
            return f"Invalid tool arguments: {error}"
        except OSError as error:
            return f"Filesystem error: {error}"

        return f"Unsupported tool: {name}"

    def resolve(self, user_path: str) -> Path:
        candidate = (self.root / user_path).resolve()
        try:
            candidate.relative_to(self.root)
        except ValueError as error:
            raise OSError("Path must stay within the current workspace.") from error
        return candidate

    def list_files(self, user_path: str) -> str:
        directory = self.resolve(user_path)
        if not directory.is_dir():
            return "Path is not a directory."
        entries: list[str] = []
        for path in directory.rglob("*"):
            relative = path.relative_to(self.root)
            if any(part in IGNORED_DIRECTORIES for part in relative.parts):
                continue
            entries.append(f"{'DIR ' if path.is_dir() else 'FILE'} {relative}")
            if len(entries) >= MAX_RESULTS:
                entries.append("… results truncated")
                break
        return "\n".join(entries) or "Directory is empty."

    def read_file(self, user_path: str) -> str:
        path = self.resolve(user_path)
        if not path.is_file():
            return "File does not exist."
        if path.stat().st_size > MAX_FILE_BYTES:
            return f"File exceeds {MAX_FILE_BYTES} byte read limit."
        return path.read_text(encoding="utf-8")

    def write_file(self, user_path: str, content: str) -> str:
        path = self.resolve(user_path)
        if len(content.encode("utf-8")) > MAX_FILE_BYTES:
            return f"Content exceeds {MAX_FILE_BYTES} byte write limit."
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return f"Wrote {path.relative_to(self.root)}."

    def edit_file(self, user_path: str, old_text: str, new_text: str) -> str:
        path = self.resolve(user_path)
        if not path.is_file():
            return "File does not exist."
        if path.stat().st_size > MAX_FILE_BYTES:
            return f"File exceeds {MAX_FILE_BYTES} byte read limit."
        content = path.read_text(encoding="utf-8")
        occurrences = content.count(old_text)
        if occurrences != 1:
            return f"Expected one exact match; found {occurrences}."
        updated = content.replace(old_text, new_text, 1)
        return self.write_file(user_path, updated)
