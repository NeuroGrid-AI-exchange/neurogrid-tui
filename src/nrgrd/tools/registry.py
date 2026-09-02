"""Generic tool registry shared by native and MCP-sourced tools.

Neither this module nor anything under :mod:`nrgrd.tools` may import Rich,
Textual, or the TUI — tools are a runtime concern, not a display concern.
"""

from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from typing import Any


class PermissionLevel(Enum):
    """How a tool call should be gated before it runs."""

    ALLOW = "allow"
    ASK = "ask"
    DENY = "deny"


ToolHandler = Callable[[str], str]
"""A tool handler receives the call's raw JSON arguments and returns text."""

# Ceiling on what one tool call may add to the conversation. A directory of
# thousands of files, or a command that prints a megabyte, must not be able
# to consume the whole context window: the user should never pay for a
# context explosion caused by the size of their repository.
MAX_RESULT_CHARS = 20_000


@dataclass(frozen=True)
class Tool:
    """One callable tool plus the metadata needed to expose and gate it."""

    name: str
    description: str
    parameters: dict[str, Any]
    permission: PermissionLevel
    handler: ToolHandler

    def execute(self, arguments: str) -> str:
        return self.handler(arguments)

    @property
    def schema(self) -> dict[str, Any]:
        """The OpenAI-compatible ``tools`` entry for this tool."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


class ToolRegistry:
    """Holds the tools currently available to the agent loop.

    The agent loop never distinguishes native tools from MCP-sourced ones;
    both are registered here as plain :class:`Tool` instances.
    """

    def __init__(self, max_result_chars: int = MAX_RESULT_CHARS) -> None:
        self._tools: dict[str, Tool] = {}
        self.max_result_chars = max_result_chars

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def unregister(self, name: str) -> None:
        self._tools.pop(name, None)

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def names(self) -> list[str]:
        return sorted(self._tools)

    def schemas(self) -> list[dict[str, Any]]:
        return [tool.schema for tool in self._tools.values()]

    def execute(self, name: str, arguments: str) -> str:
        tool = self.get(name)
        if tool is None:
            return f"Unsupported tool: {name}"
        return self.truncate(tool.execute(arguments))

    def truncate(self, result: str) -> str:
        """Cap a tool result, saying so rather than silently cutting."""
        if len(result) <= self.max_result_chars:
            return result
        kept = result[: self.max_result_chars]
        dropped = len(result) - self.max_result_chars
        return (
            f"{kept}\n\n… truncated: {dropped} more characters. Narrow the "
            "request (a subdirectory, a line range, a more specific search) "
            "to see the rest."
        )
