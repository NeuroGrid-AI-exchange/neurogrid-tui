"""Registry adapter around the existing workspace filesystem tools.

Reuses :class:`~nrgrd.workspace.tools.WorkspaceTools` and ``FILE_TOOLS`` as
the single source of truth for schemas and execution, so the standalone
``nrgrd-mcp`` server and the agent runtime never fall out of sync.
"""

from nrgrd.tools.registry import PermissionLevel, Tool
from nrgrd.workspace.tools import FILE_TOOLS, WorkspaceTools

_PERMISSIONS = {
    "list_files": PermissionLevel.ALLOW,
    "read_file": PermissionLevel.ALLOW,
    "write_file": PermissionLevel.ASK,
    "edit_file": PermissionLevel.ASK,
}


def build_filesystem_tools(workspace_tools: WorkspaceTools) -> list[Tool]:
    tools = []
    for schema in FILE_TOOLS:
        function = schema["function"]
        name = function["name"]
        tools.append(
            Tool(
                name=name,
                description=function["description"],
                parameters=function["parameters"],
                permission=_PERMISSIONS.get(name, PermissionLevel.ASK),
                handler=lambda arguments, _name=name: workspace_tools.execute(
                    _name, arguments
                ),
            )
        )
    return tools
