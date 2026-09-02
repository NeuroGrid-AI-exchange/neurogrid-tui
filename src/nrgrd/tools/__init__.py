from nrgrd.mcp import MCPClient
from nrgrd.tools.filesystem import build_filesystem_tools
from nrgrd.tools.git import build_git_tools
from nrgrd.tools.registry import PermissionLevel, Tool, ToolRegistry
from nrgrd.tools.search import build_search_tool
from nrgrd.tools.shell import build_shell_tool
from nrgrd.workspace.tools import WorkspaceTools

_MCP_PREFIX = "mcp__"


def build_default_registry(workspace_tools: WorkspaceTools) -> ToolRegistry:
    """Build the registry of native tools available to every session."""
    registry = ToolRegistry()
    for tool in build_filesystem_tools(workspace_tools):
        registry.register(tool)
    registry.register(build_search_tool(workspace_tools.root))
    registry.register(build_shell_tool(workspace_tools.root))
    for tool in build_git_tools(workspace_tools.root):
        registry.register(tool)
    return registry


def register_mcp_tools(registry: ToolRegistry, mcp_client: MCPClient) -> None:
    """Sync MCP-discovered tools into ``registry``.

    Safe to call repeatedly (e.g. after ``/mcp reload``): existing
    ``mcp__*`` entries are dropped and rebuilt from the client's current
    tool list, without touching native tools.
    """
    for name in registry.names():
        if name.startswith(_MCP_PREFIX):
            registry.unregister(name)

    for tool in mcp_client.tools.values():
        function = tool.definition["function"]
        registry.register(
            Tool(
                name=tool.function_name,
                description=function["description"],
                parameters=function["parameters"],
                permission=PermissionLevel.ASK,
                handler=lambda arguments, _name=tool.function_name, _client=mcp_client: (
                    _client.execute(_name, arguments)
                ),
            )
        )


__all__ = [
    "PermissionLevel",
    "Tool",
    "ToolRegistry",
    "build_default_registry",
    "register_mcp_tools",
]
