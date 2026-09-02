import math

from nrgrd.context.models import ChatMessage


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
            len(text) / 4
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
        + 4
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