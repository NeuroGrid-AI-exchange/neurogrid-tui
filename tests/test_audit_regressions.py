"""Regression tests for defects found in the pre-release audit.

Each test reproduces a bug that existed before the fix.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from nrgrd.agent import (
    Agent,
    PermissionManager,
    PermissionRequested,
    ToolCallOutput,
)
from nrgrd.tools import build_default_registry
from nrgrd.tools.registry import PermissionLevel, Tool, ToolRegistry
from nrgrd.tools.search import _search_python
from nrgrd.workspace.tools import WorkspaceTools, iter_workspace_files


def tool(name: str, handler, permission=PermissionLevel.ALLOW) -> Tool:
    return Tool(name, "test tool", {"type": "object", "properties": {}}, permission, handler)


# --- agent loop -----------------------------------------------------------


def test_an_unknown_tool_is_reported_without_asking_the_user(fake_provider, delta):
    asked: list[str] = []
    provider = fake_provider(
        [
            [delta(tool_name="delete_file", tool_args="{}", tool_id="c1")],
            [delta(content="ok")],
        ]
    )
    permissions = PermissionManager(callback=lambda name, args: asked.append(name) or "no")
    messages = [{"role": "user", "content": "x"}]

    events = list(Agent(provider, "m", ToolRegistry(), permissions).run(messages))

    assert asked == [], "the user was asked to approve a tool that does not exist"
    output = next(event for event in events if isinstance(event, ToolCallOutput))
    assert "Unsupported tool" in output.result


def test_tool_calls_without_index_or_id_stay_separate(fake_provider, delta):
    """Some compatible servers send whole calls with no index and no id."""
    seen: list[str] = []
    registry = ToolRegistry()
    registry.register(tool("read_file", lambda arguments: seen.append(arguments) or "ok"))
    provider = fake_provider(
        [
            [
                delta(tool_name="read_file", tool_args='{"path":"a"}', tool_id=None, index=None),
                delta(tool_name="read_file", tool_args='{"path":"b"}', tool_id=None, index=None),
            ],
            [delta(content="done")],
        ]
    )
    messages = [{"role": "user", "content": "x"}]

    list(Agent(provider, "m", registry).run(messages))

    assert seen == ['{"path":"a"}', '{"path":"b"}']
    ids = [message["tool_call_id"] for message in messages if message["role"] == "tool"]
    assert all(ids) and len(set(ids)) == 2, f"tool call ids must be present and unique: {ids}"


def test_permission_is_announced_before_the_user_is_asked(fake_provider, delta):
    """The interface needs the event first, to stop live rendering."""
    order: list[str] = []
    registry = ToolRegistry()
    registry.register(tool("shell", lambda arguments: "ran", PermissionLevel.ASK))
    provider = fake_provider(
        [
            [delta(tool_name="shell", tool_args="{}", tool_id="c1")],
            [delta(content="ok")],
        ]
    )
    permissions = PermissionManager(callback=lambda name, args: order.append("asked") or "yes")

    for event in Agent(provider, "m", registry, permissions).run([{"role": "user", "content": "x"}]):
        if isinstance(event, PermissionRequested):
            order.append("announced")

    assert order == ["announced", "asked"]


def test_allowed_tools_are_not_announced_as_needing_permission(fake_provider, delta):
    registry = ToolRegistry()
    registry.register(tool("read_file", lambda arguments: "ok", PermissionLevel.ALLOW))
    provider = fake_provider(
        [
            [delta(tool_name="read_file", tool_args="{}", tool_id="c1")],
            [delta(content="ok")],
        ]
    )

    events = list(Agent(provider, "m", registry).run([{"role": "user", "content": "x"}]))

    assert not any(isinstance(event, PermissionRequested) for event in events)


# --- tool execution -------------------------------------------------------


def test_a_crashing_tool_becomes_an_error_result_not_a_dead_turn(fake_provider, delta):
    def explode(arguments: str) -> str:
        raise ValueError("tool blew up")

    registry = ToolRegistry()
    registry.register(tool("boom", explode))
    provider = fake_provider(
        [
            [delta(tool_name="boom", tool_args="{}", tool_id="c1")],
            [delta(content="recovered")],
        ]
    )

    events = list(Agent(provider, "m", registry).run([{"role": "user", "content": "x"}]))

    output = next(event for event in events if isinstance(event, ToolCallOutput))
    assert "tool blew up" in output.result
    assert events[-1].text == "recovered"


def test_containing_tool_errors_does_not_swallow_ctrl_c():
    def interrupted(arguments: str) -> str:
        raise KeyboardInterrupt

    registry = ToolRegistry()
    registry.register(tool("slow", interrupted))

    with pytest.raises(KeyboardInterrupt):
        registry.execute("slow", "{}")


def test_shell_output_that_is_not_valid_text_does_not_crash(tmp_path: Path):
    registry = build_default_registry(WorkspaceTools(tmp_path))
    # Raw bytes 0xFF 0xFE are invalid UTF-8, the way a binary or a
    # mis-encoded build log would be.
    command = f'"{sys.executable}" -c "import sys; sys.stdout.buffer.write(bytes([255, 254]) + b\'tail\')"'

    result = registry.execute("shell", json.dumps({"command": command}))

    assert "tail" in result


# --- workspace walking ----------------------------------------------------


def _symlink_or_skip(target: Path, link: Path) -> None:
    try:
        os.symlink(target, link)
    except (OSError, NotImplementedError):
        pytest.skip("this platform or account cannot create symlinks")


def test_search_does_not_read_through_a_symlink_out_of_the_workspace(tmp_path: Path):
    """A cloned repo with notes.txt -> ~/.aws/credentials must not leak it."""
    outside = tmp_path / "outside"
    workspace = tmp_path / "workspace"
    outside.mkdir()
    workspace.mkdir()
    (outside / "credentials").write_text("AWS_SECRET=hunter2\n", encoding="utf-8")
    _symlink_or_skip(outside / "credentials", workspace / "notes.txt")

    matches = _search_python(workspace.resolve(), "AWS_SECRET", ".")

    assert matches == []


def test_listing_skips_dependency_directories(tmp_path: Path):
    for index in range(50):
        (tmp_path / "node_modules" / f"pkg{index}").mkdir(parents=True)
        (tmp_path / "node_modules" / f"pkg{index}" / "index.js").write_text("x")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.js").write_text("x")

    listing = WorkspaceTools(tmp_path).list_files(".")

    assert "node_modules" not in listing
    assert str(Path("src") / "app.js") in listing


def test_listing_honours_gitignore(tmp_path: Path):
    def git(*arguments: str) -> None:
        subprocess.run(["git", *arguments], cwd=tmp_path, check=True, capture_output=True)

    try:
        git("init")
    except (OSError, subprocess.CalledProcessError):
        pytest.skip("git is not available")
    (tmp_path / ".gitignore").write_text("secrets/\n*.log\n", encoding="utf-8")
    (tmp_path / "secrets").mkdir()
    (tmp_path / "secrets" / "token.txt").write_text("x")
    (tmp_path / "debug.log").write_text("x")
    (tmp_path / "main.py").write_text("x")

    files = {path.name for path in iter_workspace_files(tmp_path.resolve(), tmp_path.resolve())}

    assert "main.py" in files
    assert "token.txt" not in files
    assert "debug.log" not in files
