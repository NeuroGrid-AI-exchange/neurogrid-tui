"""A provider for endpoints that speak the OpenAI HTTP API.

This is not OpenAI. It is the *wire format*: a NeuroGrid deployment, vLLM,
Ollama, LM Studio, or anything else that serves ``/v1/chat/completions``
works here, because all nrgrd is given is a URL, a key, and a model name.
"""

from collections.abc import Iterator, Sequence
from typing import Any

from openai import (
    APIConnectionError,
    APIError,
    APIStatusError,
    APITimeoutError,
    AuthenticationError,
    NotFoundError,
    OpenAI,
    PermissionDeniedError,
    RateLimitError,
)

from nrgrd.api.provider import ChatDelta, ModelProvider, ProviderError, ToolCallDelta

DEFAULT_TIMEOUT_SECONDS = 120.0

# Looking up the context window is a nicety shown before every prompt, so it
# gets a short leash: a slow endpoint must never hold up the input line.
CONTEXT_LOOKUP_TIMEOUT_SECONDS = 5.0

# Where OpenAI-compatible servers put a model's context window in GET
# /models — vLLM: max_model_len · OpenRouter: context_length · LM Studio:
# max_context_length. The official OpenAI API publishes none of them.
CONTEXT_WINDOW_FIELDS = (
    "max_model_len",
    "context_length",
    "max_context_length",
    "context_window",
)


def _context_window_of(item: Any) -> int | None:
    for field in CONTEXT_WINDOW_FIELDS:
        value = item.get(field) if isinstance(item, dict) else getattr(item, field, None)
        if isinstance(value, int) and not isinstance(value, bool) and value > 0:
            return value
    return None


class OpenAICompatibleProvider(ModelProvider):
    name = "OpenAI-compatible"

    def __init__(
        self,
        endpoint: str,
        api_key: str,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        client: Any | None = None,
    ) -> None:
        self.endpoint = endpoint.strip()
        self._api_key = api_key.strip()
        self._client = client or OpenAI(
            base_url=self.endpoint,
            api_key=self._api_key,
            timeout=timeout,
            max_retries=1,
        )
        # model id -> context window (None when the server doesn't say).
        # Filled once per provider; a new endpoint or key builds a new one.
        self._context_windows: dict[str, int | None] | None = None

    def list_models(self) -> list[str]:
        try:
            response = self._client.models.list()
        except Exception as error:
            raise self._describe(error, model=None) from error
        self._remember_context_windows(response.data)
        return sorted(item.id for item in response.data)

    def context_window(self, model: str) -> int | None:
        if self._context_windows is None:
            client = self._client
            if hasattr(client, "with_options"):
                client = client.with_options(
                    timeout=CONTEXT_LOOKUP_TIMEOUT_SECONDS, max_retries=0
                )
            try:
                response = client.models.list()
            except Exception:
                # Only informational: remember the miss rather than asking
                # again before every prompt.
                self._context_windows = {}
            else:
                self._remember_context_windows(response.data)
        return self._context_windows.get(model)

    def _remember_context_windows(self, items: Any) -> None:
        self._context_windows = {
            str(item.get("id") if isinstance(item, dict) else item.id): _context_window_of(item)
            for item in items
        }

    def stream_chat(
        self,
        model: str,
        messages: Sequence[dict[str, Any]],
        tools: Sequence[dict[str, Any]] | None = None,
    ) -> Iterator[ChatDelta]:
        request: dict[str, Any] = {
            "model": model,
            "messages": list(messages),
            "stream": True,
        }
        # Some compatible servers reject an empty tools array, so only send
        # the key when there is something to send.
        if tools:
            request["tools"] = list(tools)
            request["tool_choice"] = "auto"

        try:
            stream = self._client.chat.completions.create(**request)
            for chunk in stream:
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta
                calls = tuple(
                    ToolCallDelta(
                        index=call.index,
                        id=call.id,
                        name=call.function.name if call.function else None,
                        arguments=call.function.arguments if call.function else None,
                    )
                    for call in (delta.tool_calls or [])
                )
                if delta.content or calls:
                    yield ChatDelta(content=delta.content, tool_calls=calls)
        except ProviderError:
            raise
        except Exception as error:
            raise self._describe(error, model=model) from error

    def complete_chat(
        self,
        model: str,
        messages: Sequence[dict[str, Any]],
    ) -> str:
        try:
            response = self._client.chat.completions.create(
                model=model,
                messages=list(messages),
                stream=False,
            )
        except Exception as error:
            raise self._describe(error, model=model) from error
        return response.choices[0].message.content or ""

    def _redact(self, text: str) -> str:
        """Strip the API key out of anything on its way to the user."""
        if self._api_key and self._api_key in text:
            return text.replace(self._api_key, "***")
        return text

    def _configuration(self, model: str | None) -> str:
        lines = [f"Endpoint: {self.endpoint or '(not set)'}"]
        if model:
            lines.append(f"Model: {model}")
        return "\n".join(lines)

    def _describe(self, error: Exception, model: str | None) -> ProviderError:
        """Turn a transport-level failure into something actionable."""
        detail = self._configuration(model)
        change = "Run /config edit to change the configuration."

        if isinstance(error, AuthenticationError):
            return ProviderError(
                "The endpoint rejected the API key.",
                detail,
                f"Check the key issued with this deployment. {change}",
            )
        if isinstance(error, PermissionDeniedError):
            return ProviderError(
                "The endpoint refused this request (HTTP 403).",
                detail,
                f"The key may not cover this model or route. {change}",
            )
        if isinstance(error, NotFoundError):
            return ProviderError(
                "The endpoint returned HTTP 404 (not found).",
                detail,
                "Check the endpoint path (it usually ends in /v1) and that "
                f"the model name exists. {change}",
            )
        if isinstance(error, RateLimitError):
            return ProviderError(
                "The endpoint is rate limiting requests (HTTP 429).",
                detail,
                "Wait a moment and try again.",
            )
        if isinstance(error, APITimeoutError):
            return ProviderError(
                "The endpoint timed out.",
                detail,
                "The deployment may be loading the model or overloaded. "
                "Try again shortly.",
            )
        if isinstance(error, APIConnectionError):
            return ProviderError(
                "Could not reach the endpoint.",
                detail,
                "Check the URL is right, the deployment is still running, "
                f"and that you are online. {change}",
            )
        if isinstance(error, APIStatusError):
            return ProviderError(
                f"The endpoint returned HTTP {error.status_code}.",
                detail,
                self._redact(str(getattr(error, "message", "")).strip()) or change,
            )
        if not isinstance(error, APIError):
            # The request itself went through, but the reply could not be
            # read as an API response. Almost always the URL points at
            # something that is not an OpenAI-compatible API — a web UI, a
            # proxy error page, or simply the wrong port.
            return ProviderError(
                "The endpoint replied with something that is not an "
                "OpenAI-compatible API response.",
                detail,
                "Check the URL points at the API itself (it usually ends "
                f"in /v1) rather than a web page. {change}",
            )
        return ProviderError(
            "The model request failed.",
            detail,
            self._redact(str(error)),
        )
