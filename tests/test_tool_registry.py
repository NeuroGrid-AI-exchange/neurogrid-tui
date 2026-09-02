from nrgrd.tools.registry import PermissionLevel, Tool, ToolRegistry


def make_tool(name: str, permission: PermissionLevel = PermissionLevel.ALLOW) -> Tool:
    return Tool(
        name=name,
        description=f"{name} description",
        parameters={"type": "object", "properties": {}},
        permission=permission,
        handler=lambda arguments: f"{name} ran with {arguments}",
    )


def test_register_and_execute():
    registry = ToolRegistry()
    registry.register(make_tool("read_file"))

    assert registry.names() == ["read_file"]
    assert registry.execute("read_file", "{}") == 'read_file ran with {}'


def test_unregister_removes_tool():
    registry = ToolRegistry()
    registry.register(make_tool("shell"))
    registry.unregister("shell")

    assert registry.get("shell") is None
    assert registry.names() == []


def test_execute_unknown_tool_returns_message_not_error():
    registry = ToolRegistry()
    assert registry.execute("does_not_exist", "{}") == "Unsupported tool: does_not_exist"


def test_schemas_are_openai_shaped():
    registry = ToolRegistry()
    registry.register(make_tool("search"))

    [schema] = registry.schemas()
    assert schema["type"] == "function"
    assert schema["function"]["name"] == "search"
    assert schema["function"]["description"] == "search description"
