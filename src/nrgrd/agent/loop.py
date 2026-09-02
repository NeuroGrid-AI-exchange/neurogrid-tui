"""The nrgrd agent runtime: an iterative tool-use loop over an
OpenAI-compatible model.

This module has no dependency on Rich or Textual. It mutates the message
list it is given and yields events as they happen; it never prints or
renders. That keeps it usable headlessly (CLI, tests, future interfaces)
and testable with a mocked model provider.
"""

from collections.abc import Iterator
from typing import Any

from nrgrd.agent.events import (
    AgentError,
    AgentEvent,
    AgentFinished,
    AgentStarted,
    AssistantChunk,
    ToolCallDenied,
    ToolCallOutput,
    ToolCallStarted,
)
from nrgrd.agent.permissions import PermissionManager
from nrgrd.api.provider import ModelProvider, ProviderError
from nrgrd.tools.registry import PermissionLevel, ToolRegistry

MAX_ITERATIONS = 12


class Agent:
    def __init__(
        self,
        provider: ModelProvider,
        model: str,
        tool_registry: ToolRegistry,
        permissions: PermissionManager | None = None,
        max_iterations: int = MAX_ITERATIONS,
    ) -> None:
        self.provider = provider
        self.model = model
        self.tool_registry = tool_registry
        self.permissions = permissions or PermissionManager()
        self.max_iterations = max_iterations

    def run(self, messages: list[dict[str, Any]]) -> Iterator[AgentEvent]:
        """Run the tool-use loop, mutating ``messages`` in place."""
        yield AgentStarted()

        for _ in range(self.max_iterations):
            response_text = ""
            tool_calls: dict[int, dict[str, str]] = {}

            try:
                for delta in self.provider.stream_chat(
                    model=self.model,
                    messages=messages,
                    tools=self.tool_registry.schemas(),
                ):
                    if delta.content:
                        response_text += delta.content
                        yield AssistantChunk(delta.content, response_text)
                    for call in delta.tool_calls:
                        item = tool_calls.setdefault(
                            call.index, {"id": "", "name": "", "arguments": ""}
                        )
                        if call.id:
                            item["id"] = call.id
                        if call.name:
                            item["name"] += call.name
                        if call.arguments:
                            item["arguments"] += call.arguments
            except ProviderError as error:
                yield AgentError(error.summary, error.detail, error.hint)
                return
            except Exception as error:
                yield AgentError(str(error))
                return

            if not tool_calls:
                yield AgentFinished(response_text)
                return

            calls = list(tool_calls.values())
            messages.append(
                {
                    "role": "assistant",
                    "content": response_text or None,
                    "tool_calls": [
                        {
                            "id": call["id"],
                            "type": "function",
                            "function": {
                                "name": call["name"],
                                "arguments": call["arguments"],
                            },
                        }
                        for call in calls
                    ],
                }
            )

            for call in calls:
                name, arguments = call["name"], call["arguments"]
                tool = self.tool_registry.get(name)
                level = tool.permission if tool else PermissionLevel.ASK

                if not self.permissions.check(name, arguments, level):
                    result = "Permission denied by the user."
                    yield ToolCallDenied(name, arguments)
                else:
                    yield ToolCallStarted(name, arguments)
                    result = self.tool_registry.execute(name, arguments)
                    yield ToolCallOutput(name, result)

                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call["id"],
                        "content": result,
                    }
                )

        yield AgentError(
            "Tool call limit reached; please continue with a narrower request."
        )
