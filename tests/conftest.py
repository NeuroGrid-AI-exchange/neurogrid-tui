"""Shared fakes for exercising the agent loop without a real endpoint."""

from collections.abc import Iterator, Sequence
from typing import Any

import pytest

from nrgrd.api.provider import ChatDelta, ModelProvider, ToolCallDelta


def make_delta(
    content: str | None = None,
    tool_name: str | None = None,
    tool_args: str = "",
    tool_id: str | None = None,
    index: int = 0,
) -> ChatDelta:
    """Build one normalized streaming delta."""
    calls: tuple[ToolCallDelta, ...] = ()
    if tool_name is not None:
        calls = (
            ToolCallDelta(
                index=index,
                id=tool_id,
                name=tool_name,
                arguments=tool_args,
            ),
        )
    return ChatDelta(content=content, tool_calls=calls)


class FakeProvider(ModelProvider):
    """A scripted provider.

    ``turns`` is a list of delta lists; each ``stream_chat`` call replays
    the next turn, so tests can script a multi-turn conversation.
    """

    name = "fake"
    endpoint = "http://fake.invalid/v1"

    def __init__(self, turns: list[list[ChatDelta]], models: list[str] | None = None):
        self._turns = list(turns)
        self._models = models or ["fake-model"]
        self.calls: list[dict[str, Any]] = []

    def list_models(self) -> list[str]:
        return list(self._models)

    def stream_chat(
        self,
        model: str,
        messages: Sequence[dict[str, Any]],
        tools: Sequence[dict[str, Any]] | None = None,
    ) -> Iterator[ChatDelta]:
        self.calls.append({"model": model, "messages": list(messages), "tools": tools})
        if not self._turns:
            raise AssertionError("FakeProvider ran out of scripted turns")
        yield from self._turns.pop(0)

    def complete_chat(
        self,
        model: str,
        messages: Sequence[dict[str, Any]],
    ) -> str:
        self.calls.append({"model": model, "messages": list(messages)})
        return "".join(
            delta.content or "" for delta in (self._turns.pop(0) if self._turns else [])
        )


@pytest.fixture
def fake_provider():
    return FakeProvider


@pytest.fixture
def delta():
    return make_delta
