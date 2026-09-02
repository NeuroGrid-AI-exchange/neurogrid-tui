"""Shell command execution, scoped to the workspace root.

This is a deliberately powerful and potentially dangerous tool. It defaults
to :data:`PermissionLevel.ASK` and must never bypass the permission system.
"""

import json
import subprocess
from pathlib import Path

from nrgrd.tools.registry import PermissionLevel, Tool

MAX_OUTPUT_CHARS = 8000
TIMEOUT_SECONDS = 60

SHELL_SCHEMA = {
    "type": "object",
    "properties": {
        "command": {"type": "string", "description": "Shell command to run."},
    },
    "required": ["command"],
}


def _execute(root: Path, arguments: str) -> str:
    try:
        payload = json.loads(arguments or "{}")
        command = payload["command"]
    except (json.JSONDecodeError, KeyError, TypeError) as error:
        return f"Invalid tool arguments: {error}"
    if not isinstance(command, str) or not command.strip():
        return "Invalid tool arguments: command must be a non-empty string."

    try:
        result = subprocess.run(
            command,
            shell=True,
            cwd=root,
            capture_output=True,
            text=True,
            timeout=TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        return f"Command timed out after {TIMEOUT_SECONDS}s."
    except OSError as error:
        return f"Failed to run command: {error}"

    output = (result.stdout + result.stderr).strip() or "(no output)"
    if len(output) > MAX_OUTPUT_CHARS:
        output = output[:MAX_OUTPUT_CHARS] + "\n… output truncated"
    return f"exit code {result.returncode}\n{output}"


def build_shell_tool(root: Path) -> Tool:
    return Tool(
        name="shell",
        description="Run a shell command inside the workspace root and return its output.",
        parameters=SHELL_SCHEMA,
        permission=PermissionLevel.ASK,
        handler=lambda arguments: _execute(root, arguments),
    )
