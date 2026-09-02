from collections.abc import Iterator
from typing import Any

from openai import OpenAI


class NrgrdClient:
    """OpenAI-compatible API client."""

    def __init__(
        self,
        base_url: str,
        api_key: str,
    ) -> None:
        self.client = OpenAI(
            base_url=base_url,
            api_key=api_key,
        )

    def list_models(
        self,
    ) -> list[str]:
        """Return all models exposed by the API."""

        response = (
            self.client
            .models
            .list()
        )

        return sorted(
            model.id
            for model
            in response.data
        )

    def stream_message(
        self,
        model: str,
        messages: list[
            dict[str, Any]
        ],
    ) -> Iterator[str]:
        """
        Send messages and yield generated text as it arrives.
        """

        stream = (
            self.client
            .chat
            .completions
            .create(
                model=model,
                messages=messages,
                stream=True,
            )
        )

        for chunk in stream:

            if not chunk.choices:
                continue

            content = (
                chunk
                .choices[0]
                .delta
                .content
            )

            if content:
                yield content

    def complete_message(
        self,
        model: str,
        messages: list[
            dict[str, Any]
        ],
    ) -> str:
        """
        Send a non-streaming request.

        This is used for context compaction.
        """

        response = (
            self.client
            .chat
            .completions
            .create(
                model=model,
                messages=messages,
                stream=False,
            )
        )

        content = (
            response
            .choices[0]
            .message
            .content
        )

        return (
            content
            or ""
        )