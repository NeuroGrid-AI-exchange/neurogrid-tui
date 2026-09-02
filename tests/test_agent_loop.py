from nrgrd.agent import (
    Agent,
    AgentError,
    AgentFinished,
    AgentStarted,
    PermissionManager,
    ToolCallDenied,
    ToolCallOutput,
)
from nrgrd.api.provider import ProviderError
from nrgrd.tools.registry import PermissionLevel, Tool, ToolRegistry


def registry_with(*tools: Tool) -> ToolRegistry:
    registry = ToolRegistry()
    for tool in tools:
        registry.register(tool)
    return registry


def test_plain_reply_with_no_tool_calls(fake_provider, delta):
    provider = fake_provider([[delta(content="Hello "), delta(content="there.")]])
    agent = Agent(provider, "test-model", ToolRegistry())

    events = list(agent.run([{"role": "user", "content": "hi"}]))

    assert isinstance(events[0], AgentStarted)
    assert isinstance(events[-1], AgentFinished)
    assert events[-1].text == "Hello there."
    assert len(provider.calls) == 1


def test_allowed_tool_call_executes_and_feeds_result_back(fake_provider, delta):
    read_file = Tool(
        "read_file",
        "read",
        {"type": "object", "properties": {}},
        PermissionLevel.ALLOW,
        lambda arguments: "FILE CONTENTS",
    )
    provider = fake_provider(
        [
            [delta(tool_name="read_file", tool_args="{}", tool_id="call_1")],
            [delta(content="Done.")],
        ]
    )
    agent = Agent(provider, "test-model", registry_with(read_file))
    messages = [{"role": "user", "content": "read it"}]

    events = list(agent.run(messages))

    kinds = [type(event).__name__ for event in events]
    assert kinds == [
        "AgentStarted",
        "ToolCallStarted",
        "ToolCallOutput",
        "AssistantChunk",
        "AgentFinished",
    ]
    tool_output = next(e for e in events if isinstance(e, ToolCallOutput))
    assert tool_output.result == "FILE CONTENTS"
    # The tool result must be threaded back into the conversation.
    assert messages[-1] == {
        "role": "tool",
        "tool_call_id": "call_1",
        "content": "FILE CONTENTS",
    }


def test_ask_level_tool_denied_by_permission_manager_never_executes(fake_provider, delta):
    executed = []
    shell = Tool(
        "shell",
        "run",
        {"type": "object", "properties": {}},
        PermissionLevel.ASK,
        lambda arguments: executed.append(arguments) or "should not run",
    )
    provider = fake_provider(
        [
            [delta(tool_name="shell", tool_args="{}", tool_id="call_1")],
            [delta(content="Understood.")],
        ]
    )
    permissions = PermissionManager(callback=lambda name, args: "no")
    agent = Agent(provider, "test-model", registry_with(shell), permissions=permissions)

    events = list(agent.run([{"role": "user", "content": "rm -rf /"}]))

    assert executed == []
    assert any(isinstance(event, ToolCallDenied) for event in events)
    assert not any(isinstance(event, ToolCallOutput) for event in events)


def test_provider_error_is_surfaced_with_its_detail_and_hint(fake_provider):
    class BrokenProvider(fake_provider):
        def stream_chat(self, model, messages, tools=None):
            raise ProviderError(
                "Could not reach the endpoint.",
                "Endpoint: http://fake.invalid/v1\nModel: test-model",
                "Check the URL is right.",
            )
            yield  # pragma: no cover - generator marker

    agent = Agent(BrokenProvider([]), "test-model", ToolRegistry())

    events = list(agent.run([{"role": "user", "content": "hi"}]))

    error = events[-1]
    assert isinstance(error, AgentError)
    assert error.message == "Could not reach the endpoint."
    assert "http://fake.invalid/v1" in error.detail
    assert error.hint == "Check the URL is right."


def test_unexpected_error_still_stops_the_loop(fake_provider):
    class ExplodingProvider(fake_provider):
        def stream_chat(self, model, messages, tools=None):
            raise RuntimeError("something unexpected")
            yield  # pragma: no cover - generator marker

    agent = Agent(ExplodingProvider([]), "test-model", ToolRegistry())

    events = list(agent.run([{"role": "user", "content": "hi"}]))

    assert isinstance(events[-1], AgentError)
    assert "something unexpected" in events[-1].message


def test_tool_call_limit_reached_yields_agent_error(fake_provider, delta):
    always_calls_tool = Tool(
        "shell",
        "run",
        {"type": "object", "properties": {}},
        PermissionLevel.ALLOW,
        lambda arguments: "ok",
    )
    turns = [
        [delta(tool_name="shell", tool_args="{}", tool_id=f"call_{i}")]
        for i in range(20)
    ]
    provider = fake_provider(turns)
    agent = Agent(provider, "test-model", registry_with(always_calls_tool), max_iterations=3)

    events = list(agent.run([{"role": "user", "content": "loop forever"}]))

    assert isinstance(events[-1], AgentError)
    assert "Tool call limit reached" in events[-1].message
