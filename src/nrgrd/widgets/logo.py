"""The nrgrd wordmark and the NeuroGrid emblem beside it.

The emblem is the NeuroGrid logo: a 4x4 grid of nodes with one bold central
node firing along a handful of connections. It is built from a node grid
plus named connection groups so the startup animation can reveal the
connections in order instead of duplicating hand-aligned ASCII per frame.
"""

from rich.text import Text

from nrgrd.theme.colors import GREEN, GREEN_BRIGHT, GREEN_VIVID, MUTED

LETTER_ROWS = [
    "███╗   ██╗██████╗  ██████╗ ██████╗ ██████╗",
    "████╗  ██║██╔══██╗██╔════╝ ██╔══██╗██╔══██╗",
    "██╔██╗ ██║██████╔╝██║  ███╗██████╔╝██║  ██║",
    "██║╚██╗██║██╔══██╗██║   ██║██╔══██╗██║  ██║",
    "██║ ╚████║██║  ██║╚██████╔╝██║  ██║██████╔╝",
    "╚═╝  ╚═══╝╚═╝  ╚═╝ ╚═════╝ ╚═╝  ╚═╝╚═════╝",
    "",
]
_LETTERS_WIDTH = max(len(row) for row in LETTER_ROWS)
_GAP = "   "

_EMBLEM_ROWS = 7
_EMBLEM_COLUMNS = 13

# The 4x4 node grid; the centre node is the one that fires.
_NODE_ROWS = (0, 2, 4, 6)
_NODE_COLUMNS = (0, 4, 8, 12)
_CENTRE = (2, 4)

# Connection groups, revealed in this order by the startup animation.
_CONNECTIONS: list[list[tuple[int, int, str]]] = [
    # Up-left and up-right, out of the centre node.
    [(1, 2, "\\"), (1, 6, "/")],
    # Down-left and down-right, out of the centre node.
    [(3, 2, "/"), (5, 1, "/"), (3, 5, "\\"), (4, 6, "\\"), (5, 7, "\\")],
    # The shallow run to the right, plus the link along the top row.
    [(3, column, "-") for column in range(7, 12)]
    + [(0, column, "-") for column in range(9, 12)],
]


def _emblem_rows(connections: int, charged: bool) -> list[str]:
    """Render the emblem with the first ``connections`` groups revealed."""
    grid = [[" "] * _EMBLEM_COLUMNS for _ in range(_EMBLEM_ROWS)]

    for row in _NODE_ROWS:
        for column in _NODE_COLUMNS:
            grid[row][column] = "o"
    grid[_CENTRE[0]][_CENTRE[1]] = "O" if charged else "o"

    for group in _CONNECTIONS[:connections]:
        for row, column, character in group:
            grid[row][column] = character

    return ["".join(row).rstrip() for row in grid]


def _compose(letters_style: str, emblem_style: str, emblem: list[str]) -> Text:
    text = Text()
    for index, letters in enumerate(LETTER_ROWS):
        text.append(letters.ljust(_LETTERS_WIDTH), style=letters_style)
        text.append(_GAP)
        text.append(emblem[index], style=emblem_style)
        if index < len(LETTER_ROWS) - 1:
            text.append("\n")
    return text


def create_logo() -> Text:
    """Return the finished logo, without imposing alignment."""
    return _compose(
        f"bold {GREEN}",
        f"bold {GREEN}",
        _emblem_rows(len(_CONNECTIONS), charged=True),
    )


def logo_frames() -> list[Text]:
    """Return the startup animation: the centre node charging, then firing.

    The last frame is identical to :func:`create_logo`, so whatever renders
    these can simply stop on it.
    """
    schedule = [
        (MUTED, MUTED, 0, False),
        (MUTED, GREEN_BRIGHT, 0, True),
        (GREEN, GREEN_VIVID, 1, True),
        (GREEN, GREEN_VIVID, 2, True),
        (GREEN, GREEN, 3, True),
    ]
    return [
        _compose(
            f"bold {letters}",
            f"bold {emblem}",
            _emblem_rows(connections, charged=charged),
        )
        for letters, emblem, connections, charged in schedule
    ]
