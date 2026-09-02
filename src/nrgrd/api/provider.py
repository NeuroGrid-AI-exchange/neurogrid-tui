"""The model provider interface the agent runtime talks to.

The agent never learns which service is behind the endpoint. A provider owns
HTTP communication, authentication, streaming, and turning wire-level
failures into :class:`ProviderError`s a user can act on; the agent owns
context, tools, permissions, and iteration.
"""

from abc import ABC, abstractmethod
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ToolCallDelta:
    """A slice of one streamed tool call.

    Providers stream tool calls in fragments: the name arrives in one
    chunk, the arguments across several more. ``index`` identifies which
    call a fragment belongs to.
    """

    index: int
    id: str | None = None
    name: str | None = None
    arguments: str | None = None


@dataclass(frozen=True)
class ChatDelta:
    """One streamed step of a reply: text, tool-call fragments, or both."""

    content: str | None = None
    tool_calls: tuple[ToolCallDelta, ...] = ()


class ProviderError(Exception):
    """A model request failed, described in terms the user can act on.

    ``summary`` says what happened, ``detail`` shows the configuration the
    request used, and ``hint`` says what to do about it. None of them may
    ever contain the API key.
    """

    def __init__(self, summary: str, detail: str = "", hint: str = "") -> None:
        super().__init__(summary)
        self.summary = summary
        self.detail = detail
        self.hint = hint


class ModelProvider(ABC):
    """Any endpoint the agent can talk to."""

    name: str = "model provider"
    endpoint: str = ""

    @abstractmethod
    def list_models(self) -> list[str]:
        """Return the model ids the endpoint exposes."""

    @abstractmethod
    def stream_chat(
        self,
        model: str,
        messages: Sequence[dict[str, Any]],
        tools: Sequence[dict[str, Any]] | None = None,
    ) -> Iterator[ChatDelta]:
        """Stream a reply, yielding normalized deltas as they arrive."""

    @abstractmethod
    def complete_chat(
        self,
        model: str,
        messages: Sequence[dict[str, Any]],
    ) -> str:
        """Return a complete reply in one shot (used for compaction)."""
