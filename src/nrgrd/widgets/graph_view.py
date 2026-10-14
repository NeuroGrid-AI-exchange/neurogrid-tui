"""Draw a conversation graph in the terminal.

The turns run down the left, joined in order. Every file the session touched
is a lane: a vertical line that starts at the first turn touching the file
and ends at the file's name at the bottom. A turn reaches across to the lanes
of the files it used, so a file shared by several turns shows up as one line
those turns all connect to — the cross-links a tree can't draw::

     1 ● fix the failing test ───●──○
       │ read_file ×2 · edit_file   │  │
     2 ● update the docs ────────┼──○──●
       │ edit_file                │  │  │
                                  │  │  └─ README.md        ✎1
                                  │  └──── tests/test_app.py ○2
                                  └─────── src/app.py       ✎1 ○1

● wrote · ○ read · ◇ used some other way. Each lane has its own color.
"""

from collections import Counter

from rich.cells import cell_len, set_cell_size
from rich.text import Text

from nrgrd.sessions.graph import ConversationGraph
from nrgrd.theme.colors import (
    BORDER,
    ERROR,
    GREEN_BRIGHT,
    GREEN_VIVID,
    MUTED,
    PINK,
    PINK_LIGHT,
    TEXT,
    WARNING,
)

LANE_COLORS = (GREEN_VIVID, PINK_LIGHT, WARNING, GREEN_BRIGHT, PINK, "#34D399", "#F472B6", "#22D3EE")
MARKS = {"wrote": "●", "read": "○", "used": "◇"}
# A turn that touched a file both ways is drawn as the stronger one.
STRENGTH = {"used": 0, "read": 1, "wrote": 2}
OUTCOME_COLORS = {"finished": GREEN_VIVID, "cancelled": WARNING, "limit": WARNING, "error": ERROR}

NUMBER_WIDTH = 3
LANE_GAP = 3


def fit(text: str, width: int) -> str:
    """Cut ``text`` to ``width`` terminal cells, marking the cut with "…"."""
    text = " ".join(text.split())
    if cell_len(text) <= width:
        return text
    return set_cell_size(text, width - 1).rstrip(" ·") + "…"


class Canvas:
    """A grid of cells; a cell holds one character, or a label spanning several."""

    def __init__(self) -> None:
        self.rows: list[dict[int, tuple[str, str]]] = []

    def put(self, row: int, column: int, text: str, style: str = "") -> None:
        while len(self.rows) <= row:
            self.rows.append({})
        self.rows[row][column] = (text, style)

    def get(self, row: int, column: int) -> str | None:
        if row >= len(self.rows):
            return None
        cell = self.rows[row].get(column)
        return cell[0] if cell else None

    def render(self) -> Text:
        out = Text()
        for index, row in enumerate(self.rows):
            column = 0
            for start in sorted(row):
                if start < column:
                    continue  # covered by a wider label to its left
                out.append(" " * (start - column))
                text, style = row[start]
                out.append(text, style=style)
                column = start + cell_len(text)
            if index < len(self.rows) - 1:
                out.append("\n")
        return out


def _links(graph: ConversationGraph, turn_id: str) -> dict[str, str]:
    """file path -> strongest way this turn touched it."""
    links: dict[str, str] = {}
    for tool in graph.tools_of(turn_id):
        touched = graph.file_of(tool["id"])
        if not touched:
            continue
        path, kind = touched
        if path not in links or STRENGTH[kind] > STRENGTH[links[path]]:
            links[path] = kind
    return links


def _tools_line(graph: ConversationGraph, turn_id: str) -> str:
    tools = graph.tools_of(turn_id)
    counts = Counter(tool["label"] for tool in tools)
    denied = {tool["label"] for tool in tools if tool.get("status") == "denied"}
    parts = [
        f"{name}{f' ×{count}' if count > 1 else ''}{' ✗' if name in denied else ''}"
        for name, count in counts.items()
    ]
    return " · ".join(parts)


def render_graph(graph: ConversationGraph, width: int, max_turns: int = 30) -> Text:
    turns = graph.turns()
    shown = turns[-max_turns:]
    links = {turn["id"]: _links(graph, turn["id"]) for turn in shown}

    # Lanes in order of first use, so they open from left to right as the
    # session goes on. If they don't all fit, the busiest files keep a lane.
    order: list[str] = []
    uses: Counter[str] = Counter()
    for turn in shown:
        for path in links[turn["id"]]:
            uses[path] += 1
            if path not in order:
                order.append(path)

    label_width = max(16, min(40, width // 3))
    gutter = NUMBER_WIDTH + 3 + label_width + 2
    name_room = 24
    fits = max(0, (width - gutter - name_room) // LANE_GAP)
    hidden = 0
    if len(order) > fits:
        keep = {path for path, _ in uses.most_common(fits)}
        hidden = len(order) - len(keep)
        order = [path for path in order if path in keep]
    lane_x = {path: gutter + 1 + LANE_GAP * index for index, path in enumerate(order)}
    lane_color = {path: LANE_COLORS[index % len(LANE_COLORS)] for index, path in enumerate(order)}

    canvas = Canvas()
    line = BORDER
    first_row: dict[str, int] = {}

    for index, turn in enumerate(shown):
        row = index * 2
        turn_links = {path: kind for path, kind in links[turn["id"]].items() if path in lane_x}
        number = turn["id"].split(":")[1]

        canvas.put(row, 0, number.rjust(NUMBER_WIDTH), MUTED)
        canvas.put(row, NUMBER_WIDTH + 1, "●", OUTCOME_COLORS.get(turn.get("outcome", ""), MUTED))
        label = fit(turn["label"], label_width)
        canvas.put(row, NUMBER_WIDTH + 3, label, TEXT)

        if turn_links:
            reach = max(lane_x[path] for path in turn_links)
            text_end = NUMBER_WIDTH + 3 + cell_len(label) + 1
            for column in range(text_end, reach):
                canvas.put(row, column, "─", line)
            for path in order:
                x = lane_x[path]
                if x > reach:
                    break
                if path in turn_links:
                    canvas.put(row, x, MARKS[turn_links[path]], f"bold {lane_color[path]}")
                    first_row.setdefault(path, row)
                elif path in first_row:
                    canvas.put(row, x, "┼", lane_color[path])

        tools = _tools_line(graph, turn["id"])
        last = index == len(shown) - 1
        if not last:
            canvas.put(row + 1, NUMBER_WIDTH + 1, "│", line)
        if tools:
            canvas.put(row + 1, NUMBER_WIDTH + 3, fit(tools, label_width), MUTED)

    # Each lane ends at its file name, the rightmost lane first, so the
    # elbows never cross another lane.
    base = len(shown) * 2
    name_x = gutter + 1 + LANE_GAP * len(order) + 1
    for offset, path in enumerate(reversed(order)):
        row = base + offset
        x = lane_x[path]
        color = lane_color[path]
        for r in range(first_row[path] + 1, row):
            if canvas.get(r, x) is None:
                canvas.put(r, x, "│", color)
        canvas.put(row, x, "└", color)
        for column in range(x + 1, name_x - 1):
            canvas.put(row, column, "─", color)
        reads = sum(1 for turn in shown if links[turn["id"]].get(path) == "read")
        writes = sum(1 for turn in shown if links[turn["id"]].get(path) == "wrote")
        counts = " ".join(part for part in (f"✎{writes}" if writes else "", f"○{reads}" if reads else "") if part)
        room = max(8, width - name_x - cell_len(counts) - 2)
        name = path if cell_len(path) <= room else "…" + path[-(room - 1):]
        canvas.put(row, name_x, name, f"bold {color}")
        canvas.put(row, name_x + cell_len(name) + 1, counts, MUTED)

    out = Text()
    if len(turns) > len(shown):
        out.append(f"… {len(turns) - len(shown)} earlier turns\n", style=MUTED)
    out.append_text(canvas.render())
    footer = "● wrote · ○ read · ◇ used"
    if hidden:
        footer += f"\n{hidden} more file{'s' if hidden > 1 else ''} not drawn (too narrow)"
    out.append("\n\n" + footer, style=MUTED)
    return out
