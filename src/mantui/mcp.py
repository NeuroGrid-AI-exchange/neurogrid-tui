"""MCP stdio client and Claude-compatible server configuration."""

import json
import os
import queue
import re
import subprocess
import threading
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mantui.config import get_config_directory


@dataclass(frozen=True)
class MCPTool:
    """An OpenAI tool plus the server and original MCP name behind it."""

    server: str
    name: str
    function_name: str
    definition: dict[str, Any]


def get_mcp_config_path() -> Path:
    """Return the user-editable MCP server registry."""
    return get_config_directory() / "mcp.json"


def load_mcp_servers() -> dict[str, dict[str, Any]]:
    """Load ``mcpServers`` in the same shape used by Claude configuration."""
    path = get_mcp_config_path()
    if not path.exists():
        path.write_text('{\n    "mcpServers": {}\n}\n', encoding="utf-8")
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        servers = data.get("mcpServers", {})
        if not isinstance(servers, dict):
            raise ValueError("mcpServers must be an object")
        return {
            name: server
            for name, server in servers.items()
            if isinstance(name, str) and isinstance(server, dict)
        }
    except (OSError, ValueError, json.JSONDecodeError):
        return {}


class MCPClient:
    """Discover and call tools from trusted, locally configured MCP servers."""

    def __init__(self, workspace: Path | None = None) -> None:
        self.tools: dict[str, MCPTool] = {}
        self.errors: dict[str, str] = {}
        self._http_sessions: dict[str, str] = {}
        self.workspace = (workspace or Path.cwd()).resolve()

    def reload(self) -> None:
        self.tools = {}
        self.errors = {}
        self._http_sessions = {}
        for server, config in load_mcp_servers().items():
            try:
                for tool in self._list_tools(server, config):
                    self.tools[tool.function_name] = tool
            except Exception as error:
                self.errors[server] = str(error)

    def openai_tools(self) -> list[dict[str, Any]]:
        return [tool.definition for tool in self.tools.values()]

    def available_tool_names(self) -> list[str]:
        """Return the exact MCP function names available in this session."""
        return sorted(self.tools)

    def execute(self, function_name: str, arguments: str) -> str:
        tool = self.tools.get(function_name)
        if tool is None:
            available = ", ".join(self.available_tool_names()) or "none"
            return (
                f"MCP tool '{function_name}' is not available. Do not retry it or "
                f"invent another tool name. Available MCP tools: {available}."
            )
        try:
            payload = json.loads(arguments or "{}")
            if not isinstance(payload, dict):
                return "Invalid MCP tool arguments: expected an object."
            result = self._request(
                load_mcp_servers()[tool.server],
                "tools/call",
                {"name": tool.name, "arguments": payload},
                session_key=tool.server,
            )
            content = result.get("content", [])
            text = "\n".join(
                item.get("text", json.dumps(item, ensure_ascii=False))
                for item in content
                if isinstance(item, dict)
            )
            return text or "MCP tool completed without text output."
        except Exception as error:
            return f"MCP tool error: {error}"

    def _list_tools(self, server: str, config: dict[str, Any]) -> list[MCPTool]:
        result = self._request(config, "tools/list", {}, session_key=server)
        raw_tools = result.get("tools", [])
        if not isinstance(raw_tools, list):
            raise ValueError("tools/list returned an invalid tools value")
        discovered: list[MCPTool] = []
        for raw in raw_tools:
            if not isinstance(raw, dict) or not isinstance(raw.get("name"), str):
                continue
            function_name = self._function_name(server, raw["name"])
            schema = raw.get("inputSchema", {"type": "object", "properties": {}})
            discovered.append(
                MCPTool(
                    server=server,
                    name=raw["name"],
                    function_name=function_name,
                    definition={
                        "type": "function",
                        "function": {
                            "name": function_name,
                            "description": f"MCP server '{server}': {raw.get('description', raw['name'])}",
                            "parameters": schema,
                        },
                    },
                )
            )
        return discovered

    @staticmethod
    def _function_name(server: str, tool: str) -> str:
        safe_server = re.sub(r"[^a-zA-Z0-9_-]", "_", server)
        safe_tool = re.sub(r"[^a-zA-Z0-9_-]", "_", tool)
        return f"mcp__{safe_server}__{safe_tool}"[:64]

    def _request(
        self,
        config: dict[str, Any],
        method: str,
        params: dict[str, Any],
        session_key: str | None = None,
    ) -> dict[str, Any]:
        if isinstance(config.get("url"), str):
            return self._http_request(config, method, params, session_key)
        command = config.get("command")
        if not isinstance(command, str) or not command.strip():
            raise ValueError("server requires a command")
        args = config.get("args", [])
        env = config.get("env")
        if not isinstance(args, list) or not all(isinstance(arg, str) for arg in args):
            raise ValueError("server args must be a list of strings")
        if env is not None and (not isinstance(env, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in env.items())):
            raise ValueError("server env must be an object of string values")
        expanded_args = [self._expand_workspace(arg) for arg in args]
        process = subprocess.Popen(
            [self._expand_workspace(command), *expanded_args], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, encoding="utf-8",
            env={**os.environ, **env} if env else None,
        )
        assert process.stdin and process.stdout
        lines: queue.Queue[str | None] = queue.Queue()
        threading.Thread(target=lambda: self._read_lines(process.stdout, lines), daemon=True).start()
        try:
            self._send(process, 1, "initialize", {"protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "mantui", "version": "0.1.0"}})
            self._receive(lines, 1)
            process.stdin.write(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n")
            process.stdin.flush()
            self._send(process, 2, method, params)
            return self._receive(lines, 2)
        finally:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()

    def _expand_workspace(self, value: str) -> str:
        """Expand common MCP workspace placeholders without shell evaluation."""
        workspace = str(self.workspace)
        return value.replace("${workspace}", workspace).replace("${workspaceFolder}", workspace)

    def _http_request(
        self,
        config: dict[str, Any],
        method: str,
        params: dict[str, Any],
        session_key: str | None,
    ) -> dict[str, Any]:
        """Use MCP's Streamable HTTP transport for a remote ``url`` server."""
        url = config["url"]
        headers = config.get("headers", {})
        if not isinstance(headers, dict) or not all(
            isinstance(key, str) and isinstance(value, str)
            for key, value in headers.items()
        ):
            raise ValueError("server headers must be an object of string values")
        key = session_key or url
        if key not in self._http_sessions:
            response, response_headers = self._http_post(
                url,
                1,
                "initialize",
                {
                    "protocolVersion": "2025-03-26",
                    "capabilities": {},
                    "clientInfo": {"name": "mantui", "version": "0.1.0"},
                },
                headers,
                None,
            )
            session_id = response_headers.get("Mcp-Session-Id")
            if session_id:
                self._http_sessions[key] = session_id
            self._http_notification(url, "notifications/initialized", headers, self._http_sessions.get(key))
        response, _ = self._http_post(
            url, 2, method, params, headers, self._http_sessions.get(key)
        )
        return response

    @staticmethod
    def _http_notification(
        url: str, method: str, headers: dict[str, str], session_id: str | None
    ) -> None:
        request_headers = {**headers, "Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
        if session_id:
            request_headers["Mcp-Session-Id"] = session_id
        request = urllib.request.Request(
            url,
            data=json.dumps({"jsonrpc": "2.0", "method": method}).encode("utf-8"),
            headers=request_headers,
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=20):
            pass

    @staticmethod
    def _http_post(
        url: str,
        request_id: int,
        method: str,
        params: dict[str, Any],
        headers: dict[str, str],
        session_id: str | None,
    ) -> tuple[dict[str, Any], Any]:
        request_headers = {**headers, "Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
        if session_id:
            request_headers["Mcp-Session-Id"] = session_id
        request = urllib.request.Request(
            url,
            data=json.dumps({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}).encode("utf-8"),
            headers=request_headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                body = response.read().decode("utf-8")
                response_headers = response.headers
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"HTTP {error.code}: {detail[:300]}") from error
        payload = MCPClient._decode_http_message(body)
        if "error" in payload:
            raise RuntimeError(payload["error"].get("message", "MCP error"))
        result = payload.get("result")
        if not isinstance(result, dict):
            raise ValueError("server returned an invalid result")
        return result, response_headers

    @staticmethod
    def _decode_http_message(body: str) -> dict[str, Any]:
        """Decode either a JSON response or the first JSON-RPC SSE event."""
        if any(line.startswith("data:") for line in body.splitlines()):
            data_lines = [line[5:].strip() for line in body.splitlines() if line.startswith("data:")]
            body = "\n".join(data_lines)
        payload = json.loads(body)
        if not isinstance(payload, dict):
            raise ValueError("server returned a non-object response")
        return payload

    @staticmethod
    def _read_lines(stream: Any, lines: queue.Queue[str | None]) -> None:
        for line in stream:
            lines.put(line)
        lines.put(None)

    @staticmethod
    def _send(process: subprocess.Popen[str], request_id: int, method: str, params: dict[str, Any]) -> None:
        assert process.stdin
        process.stdin.write(json.dumps({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}) + "\n")
        process.stdin.flush()

    @staticmethod
    def _receive(lines: queue.Queue[str | None], request_id: int) -> dict[str, Any]:
        while True:
            try:
                line = lines.get(timeout=20)
            except queue.Empty as error:
                raise TimeoutError("server did not respond within 20 seconds") from error
            if line is None:
                raise RuntimeError("server closed its output")
            message = json.loads(line)
            if message.get("id") != request_id:
                continue
            if "error" in message:
                raise RuntimeError(message["error"].get("message", "MCP error"))
            result = message.get("result")
            if not isinstance(result, dict):
                raise ValueError("server returned an invalid result")
            return result
