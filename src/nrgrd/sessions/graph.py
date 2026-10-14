"""A graph of what happened in a session (beta).

Nodes are the turns of the conversation, the tool calls each turn made, and
the files those calls touched. Edges say how they connect: one turn leads to
the next, a turn calls a tool, a tool reads or writes a file. It is a record
of the work, not part of the model's context, so compaction leaves it alone.

Stored as JSON next to the session (``sessions/graphs/<session>.json``) so
other tools can read it too.
"""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

GRAPH_VERSION = 1

# How a tool relates to the file it names.
READS = {"read_file", "list_files", "search"}
WRITES = {"write_file", "edit_file"}

# Argument names that hold a path, across built-in and MCP tools.
PATH_KEYS = ("path", "file_path", "file", "filename", "directory")

LABEL_CHARS = 80


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _short(text: str, limit: int = LABEL_CHARS) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


class ConversationGraph:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.nodes: list[dict[str, Any]] = []
        self.edges: list[dict[str, str]] = []
        self.load()

    # --- storage --------------------------------------------------------

    def load(self) -> None:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return  # Missing or damaged: start a fresh graph rather than fail a turn.
        self.nodes = list(data.get("nodes") or [])
        self.edges = list(data.get("edges") or [])

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = {"version": GRAPH_VERSION, "nodes": self.nodes, "edges": self.edges}
        self.path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    # --- recording ------------------------------------------------------

    def _node(self, node_id: str) -> dict[str, Any] | None:
        return next((node for node in self.nodes if node["id"] == node_id), None)

    def turns(self) -> list[dict[str, Any]]:
        return [node for node in self.nodes if node["type"] == "turn"]

    def start_turn(self, prompt: str) -> str:
        previous = self.turns()
        turn_id = f"turn:{len(previous) + 1}"
        self.nodes.append(
            {"id": turn_id, "type": "turn", "label": _short(prompt), "at": _now(), "outcome": "running"}
        )
        if previous:
            self.edges.append({"from": previous[-1]["id"], "to": turn_id, "kind": "next"})
        return turn_id

    def add_tool(self, turn_id: str, name: str, arguments: str, status: str = "ran") -> None:
        count = sum(1 for node in self.nodes if node["type"] == "tool")
        tool_id = f"tool:{count + 1}"
        try:
            parsed = json.loads(arguments) if arguments.strip() else {}
        except json.JSONDecodeError:
            parsed = {}
        if not isinstance(parsed, dict):
            parsed = {}

        detail = parsed.get("command") or parsed.get("query") or ""
        self.nodes.append(
            {
                "id": tool_id,
                "type": "tool",
                "label": name,
                "detail": _short(str(detail)) if detail else "",
                "status": status,
            }
        )
        self.edges.append({"from": turn_id, "to": tool_id, "kind": "called"})

        for key in PATH_KEYS:
            value = parsed.get(key)
            if not isinstance(value, str) or not value.strip():
                continue
            file_id = f"file:{value.strip()}"
            if self._node(file_id) is None:
                self.nodes.append({"id": file_id, "type": "file", "label": value.strip()})
            kind = "wrote" if name in WRITES else "read" if name in READS else "used"
            self.edges.append({"from": tool_id, "to": file_id, "kind": kind})
            break

    def finish_turn(self, turn_id: str, reply: str, outcome: str) -> None:
        node = self._node(turn_id)
        if node is None:
            return
        node["outcome"] = outcome
        node["reply"] = _short(reply)

    # --- reading --------------------------------------------------------

    def tools_of(self, turn_id: str) -> list[dict[str, Any]]:
        ids = [edge["to"] for edge in self.edges if edge["from"] == turn_id and edge["kind"] == "called"]
        return [node for node in self.nodes if node["id"] in ids]

    def file_of(self, tool_id: str) -> tuple[str, str] | None:
        for edge in self.edges:
            if edge["from"] == tool_id and edge["to"].startswith("file:"):
                return edge["to"][len("file:"):], edge["kind"]
        return None

    def file_summary(self) -> list[tuple[str, int, int]]:
        """(path, reads, writes) for every file touched, busiest first."""
        counts: dict[str, list[int]] = {}
        for edge in self.edges:
            if not edge["to"].startswith("file:"):
                continue
            entry = counts.setdefault(edge["to"][len("file:"):], [0, 0])
            entry[1 if edge["kind"] == "wrote" else 0] += 1
        return sorted(
            ((path, reads, writes) for path, (reads, writes) in counts.items()),
            key=lambda item: (-(item[1] + item[2]), item[0]),
        )
