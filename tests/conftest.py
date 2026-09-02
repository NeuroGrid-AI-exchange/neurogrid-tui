"""Shared fakes for exercising the agent loop without a real model provider."""

from types import SimpleNamespace
from typing import Any

import pytest


def make_chunk(
    content: str | None = None,
    tool_name: str | None = None,
    tool_args: str = "",
    tool_id: str | None = None,
    index: int = 0,
) -> SimpleNamespace:
    """Build one OpenAI-shaped streaming chunk."""
    delta = SimpleNamespace(content=content, tool_calls=None)
    if tool_name is not None:
        function = SimpleNamespace(name=tool_name, arguments=tool_args)
        delta.tool_calls = [SimpleNamespace(index=index, id=tool_id, function=function)]
    return SimpleNamespace(choices=[SimpleNamespace(delta=delta)])


class FakeStream:
    def __init__(self, chunks: list[SimpleNamespace]) -> None:
        self._chunks = chunks

    def __iter__(self):
        return iter(self._chunks)


class FakeClient:
    """A minimal stand-in for the OpenAI client the agent loop depends on.

    ``turns`` is a list of chunk lists; each call to ``create`` returns the
    next turn's stream, so tests can script a multi-turn conversation.
    """

    def __init__(self, turns: list[list[SimpleNamespace]]) -> None:
        self._turns = list(turns)
        self.calls: list[dict[str, Any]] = []
        self.chat = SimpleNamespace(completions=self)

    def create(self, **kwargs: Any) -> FakeStream:
        self.calls.append(kwargs)
        if not self._turns:
            raise AssertionError("FakeClient received more calls than scripted turns")
        return FakeStream(self._turns.pop(0))


@pytest.fixture
def fake_client():
    return FakeClient


@pytest.fixture
def chunk():
    return make_chunk
