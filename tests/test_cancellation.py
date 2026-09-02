from nrgrd.agent import Agent, AgentCancelled, PermissionManager
from nrgrd.tools.registry import PermissionLevel, Tool, ToolRegistry


def interrupting_tool(name: str, executed: list[str]) -> Tool:
    def handler(arguments: str) -> str:
        executed.append(name)
        raise KeyboardInterrupt

    return Tool(
        name,
        "interrupts",
        {"type": "object", "properties": {}},
        PermissionLevel.ALLOW,
        handler,
    )


def plain_tool(name: str, executed: list[str]) -> Tool:
    return Tool(
        name,
        "runs",
        {"type": "object", "properties": {}},
        PermissionLevel.ALLOW,
        lambda arguments: executed.append(name) or "ok",
    )


def test_interrupt_while_streaming_keeps_the_partial_reply(fake_provider, delta):
    class Interrupting(fake_provider):
        def stream_chat(self, model, messages, tools=None):
            yield delta(content="Partial answer so far")
            raise KeyboardInterrupt

    agent = Agent(Interrupting([]), "m", ToolRegistry())

    events = list(agent.run([{"role": "user", "content": "hi"}]))

    cancelled = events[-1]
    assert isinstance(cancelled, AgentCancelled)
    assert cancelled.text == "Partial answer so far"


def test_interrupting_a_tool_stops_the_rest_of_the_batch(fake_provider, delta):
    """Ctrl+C during a tool must not let the remaining tools run."""
    executed: list[str] = []
    registry = ToolRegistry()
    registry.register(interrupting_tool("first", executed))
    registry.register(plain_tool("second", executed))

    class TwoCalls(fake_provider):
        def stream_chat(self, model, messages, tools=None):
            yield delta(tool_name="first", tool_args="{}", tool_id="c1", index=0)
            yield delta(tool_name="second", tool_args="{}", tool_id="c2", index=1)

    agent = Agent(TwoCalls([]), "m", registry)
    messages = [{"role": "user", "content": "do both"}]

    events = list(agent.run(messages))

    assert executed == ["first"], "the second tool ran after the interrupt"
    assert isinstance(events[-1], AgentCancelled)


def test_cancellation_still_answers_every_tool_call(fake_provider, delta):
    """An unanswered tool_call would be rejected on the next request."""
    executed: list[str] = []
    registry = ToolRegistry()
    registry.register(interrupting_tool("first", executed))
    registry.register(plain_tool("second", executed))

    class TwoCalls(fake_provider):
        def stream_chat(self, model, messages, tools=None):
            yield delta(tool_name="first", tool_args="{}", tool_id="c1", index=0)
            yield delta(tool_name="second", tool_args="{}", tool_id="c2", index=1)

    agent = Agent(TwoCalls([]), "m", registry)
    messages = [{"role": "user", "content": "do both"}]

    list(agent.run(messages))

    requested = {
        call["id"]
        for message in messages
        if message.get("role") == "assistant"
        for call in message.get("tool_calls", [])
    }
    answered = {
        message["tool_call_id"]
        for message in messages
        if message.get("role") == "tool"
    }
    assert requested == answered == {"c1", "c2"}


def test_permission_denial_is_not_cancellation(fake_provider, delta):
    """A denied tool lets the agent continue; only Ctrl+C stops the run."""
    registry = ToolRegistry()
    registry.register(
        Tool(
            "shell",
            "runs",
            {"type": "object", "properties": {}},
            PermissionLevel.ASK,
            lambda arguments: "should not run",
        )
    )
    provider = fake_provider(
        [
            [delta(tool_name="shell", tool_args="{}", tool_id="c1")],
            [delta(content="Understood.")],
        ]
    )
    agent = Agent(
        provider,
        "m",
        registry,
        permissions=PermissionManager(callback=lambda name, args: "no"),
    )

    events = list(agent.run([{"role": "user", "content": "run it"}]))

    assert not any(isinstance(event, AgentCancelled) for event in events)
