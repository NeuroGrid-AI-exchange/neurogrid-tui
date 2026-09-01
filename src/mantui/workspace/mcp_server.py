"""Minimal stdio MCP server exposing Mantui's workspace file tools."""

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from mantui.workspace.tools import MCP_TOOLS, WorkspaceTools


def response(request_id: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def error(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": code, "message": message},
    }


def handle(request: dict[str, Any], tools: WorkspaceTools) -> dict[str, Any] | None:
    request_id = request.get("id")
    method = request.get("method")
    if method == "notifications/initialized":
        return None
    if method == "initialize":
        return response(
            request_id,
            {
                "protocolVersion": request.get("params", {}).get(
                    "protocolVersion", "2025-03-26"
                ),
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "mantui-workspace", "version": "0.1.0"},
            },
        )
    if method == "tools/list":
        return response(request_id, {"tools": MCP_TOOLS})
    if method == "tools/call":
        params = request.get("params", {})
        name = params.get("name")
        arguments = params.get("arguments", {})
        if not isinstance(name, str) or not isinstance(arguments, dict):
            return error(request_id, -32602, "tools/call requires name and arguments.")
        result = tools.execute(name, json.dumps(arguments))
        is_error = result.startswith(("Invalid", "Unsupported", "Filesystem", "Path ", "File ", "Expected"))
        return response(
            request_id,
            {"content": [{"type": "text", "text": result}], "isError": is_error},
        )
    return error(request_id, -32601, f"Method not found: {method}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".", help="Workspace root exposed by the server")
    args = parser.parse_args()
    tools = WorkspaceTools(Path(args.root))
    for line in sys.stdin:
        try:
            request = json.loads(line)
            result = handle(request, tools)
            if result is not None:
                print(json.dumps(result), flush=True)
        except (json.JSONDecodeError, TypeError) as exc:
            print(json.dumps(error(None, -32700, str(exc))), flush=True)


if __name__ == "__main__":
    main()
