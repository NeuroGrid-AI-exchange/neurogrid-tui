import pytest
from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AuthenticationError,
    NotFoundError,
    RateLimitError,
)

from nrgrd.api import OpenAICompatibleProvider, ProviderError

ENDPOINT = "https://deployment.example/v1"
API_KEY = "secret-key-value"


class FakeCompletions:
    def __init__(self, error: Exception | None = None, chunks=None):
        self._error = error
        self._chunks = chunks or []

    def create(self, **kwargs):
        self.last_request = kwargs
        if self._error is not None:
            raise self._error
        return iter(self._chunks)


class FakeClient:
    def __init__(self, error: Exception | None = None, chunks=None):
        self.completions = FakeCompletions(error, chunks)
        self.chat = self
        self.models = self

    def list(self):
        if self.completions._error is not None:
            raise self.completions._error
        return type("Response", (), {"data": []})()


def provider_raising(error: Exception) -> OpenAICompatibleProvider:
    return OpenAICompatibleProvider(ENDPOINT, API_KEY, client=FakeClient(error))


def sdk_error(cls, **attributes):
    """Build an SDK exception without needing a real HTTP response.

    The provider only inspects the exception's type (and status code), so
    bypassing __init__ keeps these tests off the SDK's HTTP internals.
    """
    error = cls.__new__(cls)
    Exception.__init__(error, "boom")
    for name, value in attributes.items():
        setattr(error, name, value)
    return error


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (sdk_error(AuthenticationError), "rejected the API key"),
        (sdk_error(NotFoundError), "404"),
        (sdk_error(RateLimitError), "rate limiting"),
        (sdk_error(APITimeoutError), "timed out"),
        (sdk_error(APIConnectionError), "Could not reach the endpoint"),
        (sdk_error(APIStatusError, status_code=503, message=""), "HTTP 503"),
    ],
)
def test_transport_failures_become_actionable_errors(error, expected):
    provider = provider_raising(error)

    with pytest.raises(ProviderError) as raised:
        provider.list_models()

    assert expected in raised.value.summary
    # Every failure says which endpoint it was talking to.
    assert ENDPOINT in raised.value.detail
    assert raised.value.hint


def test_a_non_api_endpoint_is_explained_rather_than_dumped():
    """Pointing at a web page (wrong port, a UI, a proxy page) is common.

    The SDK fails deep inside its parser with an unreadable message, so the
    provider has to name the actual problem.
    """
    parser_failure = AttributeError(
        "'str' object has no attribute '_set_private_attributes'"
    )
    provider = provider_raising(parser_failure)

    with pytest.raises(ProviderError) as raised:
        provider.list_models()

    assert "not an OpenAI-compatible API response" in raised.value.summary
    assert "/v1" in raised.value.hint
    # The internal gibberish must not reach the user.
    assert "_set_private_attributes" not in raised.value.hint


def rendered(error: ProviderError) -> str:
    return " ".join([error.summary, error.detail, error.hint])


def test_a_leaky_server_message_is_redacted_not_echoed():
    """An upstream message is shown, so it must be scrubbed first."""
    leaky = sdk_error(
        APIStatusError,
        status_code=400,
        message=f"rejected token {API_KEY} for this route",
    )
    provider = provider_raising(leaky)

    with pytest.raises(ProviderError) as raised:
        provider.list_models()

    assert API_KEY not in rendered(raised.value)
    assert "***" in raised.value.hint


def test_an_unexpected_failure_never_leaks_the_api_key():
    leaky = RuntimeError(f"request failed with Authorization: Bearer {API_KEY}")
    provider = provider_raising(leaky)

    with pytest.raises(ProviderError) as raised:
        provider.list_models()

    assert API_KEY not in rendered(raised.value)


def test_stream_chat_omits_tools_when_there_are_none():
    client = FakeClient(chunks=[])
    provider = OpenAICompatibleProvider(ENDPOINT, API_KEY, client=client)

    list(provider.stream_chat("a-model", [{"role": "user", "content": "hi"}]))

    assert "tools" not in client.completions.last_request
    assert client.completions.last_request["stream"] is True


def test_stream_chat_normalizes_chunks_into_deltas():
    def chunk(content=None, name=None, arguments=None):
        function = (
            type("Function", (), {"name": name, "arguments": arguments})()
            if name is not None or arguments is not None
            else None
        )
        calls = (
            [type("Call", (), {"index": 0, "id": "call_1", "function": function})()]
            if function
            else None
        )
        delta = type("Delta", (), {"content": content, "tool_calls": calls})()
        return type("Chunk", (), {"choices": [type("C", (), {"delta": delta})()]})()

    client = FakeClient(
        chunks=[
            chunk(content="Hello"),
            chunk(name="search", arguments='{"q":'),
            type("Empty", (), {"choices": []})(),
        ]
    )
    provider = OpenAICompatibleProvider(ENDPOINT, API_KEY, client=client)

    deltas = list(provider.stream_chat("a-model", [], tools=[{"type": "function"}]))

    assert deltas[0].content == "Hello"
    assert deltas[1].tool_calls[0].name == "search"
    assert deltas[1].tool_calls[0].arguments == '{"q":'
    # The empty chunk carried nothing and must not produce a delta.
    assert len(deltas) == 2
