"""Read-only git inspection tools."""

import subprocess
from pathlib import Path

from nrgrd.tools.registry import PermissionLevel, Tool

_TIMEOUT_SECONDS = 20
_EMPTY_SCHEMA = {"type": "object", "properties": {}}


def _run_git(root: Path, args: list[str]) -> str:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        return f"Failed to run git: {error}"
    if result.returncode != 0:
        return result.stderr.strip() or f"git exited with code {result.returncode}"
    return result.stdout.strip() or "(no changes)"


def build_git_tools(root: Path) -> list[Tool]:
    return [
        Tool(
            name="git_status",
            description="Show the working tree status (git status --short).",
            parameters=_EMPTY_SCHEMA,
            permission=PermissionLevel.ALLOW,
            handler=lambda arguments, _root=root: _run_git(_root, ["status", "--short"]),
        ),
        Tool(
            name="git_diff",
            description="Show unstaged and staged changes (git diff HEAD).",
            parameters=_EMPTY_SCHEMA,
            permission=PermissionLevel.ALLOW,
            handler=lambda arguments, _root=root: _run_git(_root, ["diff", "HEAD"]),
        ),
    ]
