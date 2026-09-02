"""The nrgrd wordmark and the NeuroGrid emblem beside it.

The emblem is the NeuroGrid logo: a 4x4 grid of nodes with one bold central
node firing along a handful of connections. It is built from a node grid
plus named connection groups, so the startup animation can wake the nodes,
charge the centre, and fire the connections without anyone hand-aligning a
single frame.

Every glyph used here is one cell wide, which is what keeps the grid square.
"""

from random import Random

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

# Connection groups, fired in this order.
_CONNECTIONS: list[list[tuple[int, int, str]]] = [
    # Up-left and up-right, out of the centre node.
    [(1, 2, "\\"), (1, 6, "/")],
    # Down-left and down-right, out of the centre node.
    [(3, 2, "/"), (5, 1, "/"), (3, 5, "\\"), (4, 6, "\\"), (5, 7, "\\")],
    # The shallow run to the right, plus the link along the top row.
    [(3, column, "-") for column in range(7, 12)]
    + [(0, column, "-") for column in range(9, 12)],
]

# Glyphs a node flickers through while waking up, and the ones a connection
# sparks with while it is being drawn. All are a single cell wide.
_WAKING = (".", "·", "∘", "o", "+", "*", "◦")
_SPARK = (".", "·", "+", "*")
_CENTRE_PULSE = ("o", "O", "●", "O")

# Fixed so the animation is identical on every launch (and in tests).
_ANIMATION_SEED = 20260902
_WAKE_STEPS = 6

_SETTLED_NODE = "o"
_SETTLED_CENTRE = "O"


def _positions() -> list[tuple[int, int]]:
    """Node positions, ordered outward from the centre."""
    grid = [(row, column) for row in _NODE_ROWS for column in _NODE_COLUMNS]
    return sorted(
        grid,
        key=lambda spot: abs(spot[0] - _CENTRE[0]) + abs(spot[1] - _CENTRE[1]),
    )


def _emblem(
    nodes: dict[tuple[int, int], str],
    groups: int,
    sparking: int | None = None,
    rng: Random | None = None,
) -> list[str]:
    """Draw the emblem: given nodes, the first ``groups`` connections lit."""
    grid = [[" "] * _EMBLEM_COLUMNS for _ in range(_EMBLEM_ROWS)]

    for (row, column), glyph in nodes.items():
        grid[row][column] = glyph

    for index, group in enumerate(_CONNECTIONS[:groups]):
        for row, column, character in group:
            spark = index == sparking and rng is not None
            grid[row][column] = rng.choice(_SPARK) if spark else character

    return ["".join(row).rstrip() for row in grid]


def _settled_nodes() -> dict[tuple[int, int], str]:
    nodes = {spot: _SETTLED_NODE for spot in _positions()}
    nodes[_CENTRE] = _SETTLED_CENTRE
    return nodes


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
        _emblem(_settled_nodes(), len(_CONNECTIONS)),
    )


def logo_frames() -> list[Text]:
    """Return the startup animation.

    The grid wakes from the centre outward, the centre node charges, and
    then it fires along each connection group in turn. The last frame is
    identical to :func:`create_logo`, so whatever renders these can simply
    stop on it.
    """
    rng = Random(_ANIMATION_SEED)
    spots = _positions()
    frames: list[Text] = []

    # 1. The grid wakes: nodes flicker in from the centre outward.
    for step in range(_WAKE_STEPS):
        lit = (step + 1) * len(spots) // _WAKE_STEPS
        settling = step >= _WAKE_STEPS - 2
        nodes = {
            spot: (
                (_SETTLED_NODE if settling else rng.choice(_WAKING))
                if position < lit
                else " "
            )
            for position, spot in enumerate(spots)
        }
        frames.append(_compose(f"bold {MUTED}", f"bold {MUTED}", _emblem(nodes, 0)))

    # 2. The centre node charges.
    for glyph in _CENTRE_PULSE:
        nodes = {spot: _SETTLED_NODE for spot in spots}
        nodes[_CENTRE] = glyph
        frames.append(
            _compose(f"bold {MUTED}", f"bold {GREEN_BRIGHT}", _emblem(nodes, 0))
        )

    # 3. It fires: each group sparks, then settles.
    for group in range(len(_CONNECTIONS)):
        frames.append(
            _compose(
                f"bold {GREEN}",
                f"bold {GREEN_BRIGHT}",
                _emblem(_settled_nodes(), group + 1, sparking=group, rng=rng),
            )
        )
        frames.append(
            _compose(
                f"bold {GREEN}",
                f"bold {GREEN_VIVID}",
                _emblem(_settled_nodes(), group + 1),
            )
        )

    # 4. Settle on the finished logo.
    frames.append(
        _compose(
            f"bold {GREEN}",
            f"bold {GREEN_BRIGHT}",
            _emblem(_settled_nodes(), len(_CONNECTIONS)),
        )
    )
    frames.append(create_logo())
    return frames
