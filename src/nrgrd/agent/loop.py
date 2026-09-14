"""The nrgrd agent runtime: an iterative tool-use loop over an
OpenAI-compatible model.

This module has no dependency on Rich or Textual. It mutates the message
list it is given and yields events as they happen; it never prints or
renders. That keeps it usable headlessly (CLI, tests, future interfaces)
and testable with a mocked model provider.
"""

import itertools
from collections.abc import Iterator
from typing import Any

from nrgrd.agent.events import (
    AgentCancelled,
    AgentError,
    AgentEvent,
    AgentFinished,
    AgentStarted,
    AssistantChunk,
    PermissionRequested,
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
        self._call_ids = itertools.count(1)

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
                    for fragment in delta.tool_calls:
                        # Some compatible servers omit ``index`` and send
                        # each call whole in one chunk. Keying those on
                        # None would glue separate calls into one garbled
                        # call, so give each its own slot instead.
                        slot = (
                            fragment.index
                            if fragment.index is not None
                            else len(tool_calls)
                        )
                        item = tool_calls.setdefault(
                            slot, {"id": "", "name": "", "arguments": ""}
                        )
                        if fragment.id:
                            item["id"] = fragment.id
                        if fragment.name:
                            item["name"] += fragment.name
                        if fragment.arguments:
                            item["arguments"] += fragment.arguments
            except KeyboardInterrupt:
                # Keep the partial reply: it is context the user may still
                # want, and dropping it mid-turn loses their work.
                yield AgentCancelled(response_text)
                return
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
            for call in calls:
                # Tool results are matched to calls by id, and a blank id
                # is rejected. Servers that do not send ids get stable,
                # unique ones.
                if not call["id"]:
                    call["id"] = f"call_{next(self._call_ids)}"

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

            cancelled = False
            for call in calls:
                name, arguments = call["name"], call["arguments"]
                tool = self.tool_registry.get(name)

                if cancelled:
                    # Interrupted earlier in this batch: run nothing further,
                    # but still answer the call. An assistant message whose
                    # tool_calls are not all answered is rejected by the
                    # endpoint, so a half-filled batch would poison the
                    # conversation rather than simply end it.
                    result = "Cancelled by the user."
                elif tool is None:
                    # Nothing would run, so there is nothing to approve:
                    # asking "allow delete_file?" for a tool that does not
                    # exist only confuses the user. Tell the model instead.
                    yield ToolCallStarted(name, arguments)
                    result = self.tool_registry.execute(name, arguments)
                    yield ToolCallOutput(name, result)
                else:
                    level = tool.permission

                    if level is PermissionLevel.ASK:
                        # Yielded before asking, so an interface can stop
                        # any live rendering first; otherwise a refreshing
                        # stream panel draws over the prompt.
                        yield PermissionRequested(name, arguments)

                    if not self.permissions.check(name, arguments, level):
                        result = "Permission denied by the user."
                        yield ToolCallDenied(name, arguments)
                    else:
                        yield ToolCallStarted(name, arguments)
                        try:
                            result = self.tool_registry.execute(name, arguments)
                        except KeyboardInterrupt:
                            cancelled = True
                            result = "Cancelled by the user."
                        else:
                            yield ToolCallOutput(name, result)

                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call["id"],
                        "content": result,
                    }
                )

            if cancelled:
                yield AgentCancelled(response_text)
                return

        yield AgentError(
            "Tool call limit reached; please continue with a narrower request."
        )
