from nrgrd.agent import (
    Agent,
    AgentError,
    AgentFinished,
    AgentStarted,
    PermissionManager,
    ToolCallDenied,
    ToolCallOutput,
)
from nrgrd.tools.registry import PermissionLevel, Tool, ToolRegistry


def registry_with(*tools: Tool) -> ToolRegistry:
    registry = ToolRegistry()
    for tool in tools:
        registry.register(tool)
    return registry


def test_plain_reply_with_no_tool_calls(fake_client, chunk):
    client = fake_client([[chunk(content="Hello "), chunk(content="there.")]])
    agent = Agent(client, "test-model", ToolRegistry())

    events = list(agent.run([{"role": "user", "content": "hi"}]))

    assert isinstance(events[0], AgentStarted)
    assert isinstance(events[-1], AgentFinished)
    assert events[-1].text == "Hello there."
    assert len(client.calls) == 1


def test_allowed_tool_call_executes_and_feeds_result_back(fake_client, chunk):
    read_file = Tool(
        "read_file",
        "read",
        {"type": "object", "properties": {}},
        PermissionLevel.ALLOW,
        lambda arguments: "FILE CONTENTS",
    )
    client = fake_client(
        [
            [chunk(tool_name="read_file", tool_args="{}", tool_id="call_1")],
            [chunk(content="Done.")],
        ]
    )
    agent = Agent(client, "test-model", registry_with(read_file))
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


def test_ask_level_tool_denied_by_permission_manager_never_executes(fake_client, chunk):
    executed = []
    shell = Tool(
        "shell",
        "run",
        {"type": "object", "properties": {}},
        PermissionLevel.ASK,
        lambda arguments: executed.append(arguments) or "should not run",
    )
    client = fake_client(
        [
            [chunk(tool_name="shell", tool_args="{}", tool_id="call_1")],
            [chunk(content="Understood.")],
        ]
    )
    permissions = PermissionManager(callback=lambda name, args: "no")
    agent = Agent(client, "test-model", registry_with(shell), permissions=permissions)

    events = list(agent.run([{"role": "user", "content": "rm -rf /"}]))

    assert executed == []
    assert any(isinstance(event, ToolCallDenied) for event in events)
    assert not any(isinstance(event, ToolCallOutput) for event in events)


def test_provider_error_yields_agent_error_and_stops():
    class BrokenCompletions:
        def create(self, **kwargs):
            raise RuntimeError("endpoint unreachable")

    class BrokenClient:
        def __init__(self) -> None:
            self.chat = type("Chat", (), {"completions": BrokenCompletions()})()

    agent = Agent(BrokenClient(), "test-model", ToolRegistry())

    events = list(agent.run([{"role": "user", "content": "hi"}]))

    assert isinstance(events[-1], AgentError)
    assert "endpoint unreachable" in events[-1].message


def test_tool_call_limit_reached_yields_agent_error(fake_client, chunk):
    always_calls_tool = Tool(
        "shell",
        "run",
        {"type": "object", "properties": {}},
        PermissionLevel.ALLOW,
        lambda arguments: "ok",
    )
    turns = [
        [chunk(tool_name="shell", tool_args="{}", tool_id=f"call_{i}")]
        for i in range(20)
    ]
    client = fake_client(turns)
    agent = Agent(client, "test-model", registry_with(always_calls_tool), max_iterations=3)

    events = list(agent.run([{"role": "user", "content": "loop forever"}]))

    assert isinstance(events[-1], AgentError)
    assert "Tool call limit reached" in events[-1].message
