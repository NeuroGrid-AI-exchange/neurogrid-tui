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

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

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
        return tool.execute(arguments)
