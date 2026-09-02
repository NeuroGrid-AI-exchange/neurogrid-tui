from typing import Literal

from pydantic import BaseModel


class ChatMessage(BaseModel):
    """
    A single message stored in a Nrgrd session.
    """

    role: Literal[
        "system",
        "user",
        "assistant",
    ]

    content: str
