import json
import math
from collections.abc import Sequence
from typing import Any

from nrgrd.context.models import ChatMessage

# About four characters per token is a fair average for English and code.
CHARS_PER_TOKEN = 4

# What each message's role and framing cost on top of its text.
MESSAGE_OVERHEAD_TOKENS = 4

# A typical cost for one image sent to a vision model.
IMAGE_TOKENS = 800


def estimate_text_tokens(
    text: str,
) -> int:
    """
    Estimate token usage.

    This is intentionally approximate. A tokenizer can be
    added later for model-specific counting.
    """

    if not text:
        return 0

    return max(
        1,
        math.ceil(
            len(text) / CHARS_PER_TOKEN
        ),
    )


def estimate_message_tokens(
    message: ChatMessage,
) -> int:
    """
    Estimate tokens used by one chat message.

    The extra tokens approximate message metadata.
    """

    return (
        estimate_text_tokens(
            message.content
        )
        + MESSAGE_OVERHEAD_TOKENS
    )


def estimate_messages_tokens(
    messages: list[ChatMessage],
) -> int:
    """Estimate tokens used by a list of messages."""

    return sum(
        estimate_message_tokens(
            message
        )
        for message
        in messages
    )


def estimate_request_tokens(
    messages: Sequence[dict[str, Any]],
    tools: Sequence[dict[str, Any]] | None = None,
) -> int:
    """
    Estimate the prompt a chat request actually sends.

    Counts everything that goes over the wire, not just the saved
    conversation: the system prompt, every message, the tool calls an
    assistant message carries, and the tool definitions, which ride along
    with every request.
    """

    characters = 0
    overhead = 0

    for message in messages:
        overhead += MESSAGE_OVERHEAD_TOKENS
        content = message.get("content")
        if isinstance(content, str):
            characters += len(content)
        elif isinstance(content, list):
            for part in content:
                if not isinstance(part, dict):
                    continue
                if isinstance(part.get("text"), str):
                    characters += len(part["text"])
                elif part.get("type") == "image_url":
                    overhead += IMAGE_TOKENS
        for call in message.get("tool_calls") or []:
            function = call.get("function") or {}
            characters += len(function.get("name") or "")
            characters += len(function.get("arguments") or "")

    if tools:
        characters += len(json.dumps(list(tools)))

    return overhead + math.ceil(characters / CHARS_PER_TOKEN)
