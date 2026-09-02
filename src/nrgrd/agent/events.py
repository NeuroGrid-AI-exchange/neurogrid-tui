"""Events emitted by the agent loop.

The TUI (or any other interface) renders these; the agent never renders
anything itself.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class AgentStarted:
    pass


@dataclass(frozen=True)
class AssistantChunk:
    """A streamed slice of the assistant's reply."""

    delta: str
    text: str


@dataclass(frozen=True)
class ToolCallStarted:
    name: str
    arguments: str


@dataclass(frozen=True)
class ToolCallOutput:
    name: str
    result: str


@dataclass(frozen=True)
class ToolCallDenied:
    """A tool call the permission system rejected."""

    name: str
    arguments: str


@dataclass(frozen=True)
class AgentError:
    """A failure, split so the interface can render it usefully.

    ``message`` says what happened, ``detail`` shows the configuration
    involved, and ``hint`` says what to do next.
    """

    message: str
    detail: str = ""
    hint: str = ""


@dataclass(frozen=True)
class AgentCancelled:
    """The user interrupted. ``text`` is whatever had been generated."""

    text: str


@dataclass(frozen=True)
class AgentFinished:
    text: str


AgentEvent = (
    AgentStarted
    | AgentCancelled
    | AssistantChunk
    | ToolCallStarted
    | ToolCallOutput
    | ToolCallDenied
    | AgentError
    | AgentFinished
)
