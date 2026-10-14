"""Keep a streaming reply's newest lines on screen.

Rich's Live display can only redraw what fits in the terminal. Once a reply
grows taller than the screen it crops the bottom, so the text appears to
stop until generation ends and the whole reply is printed at once.

:class:`StreamTail` renders only the bottom of a renderable — as many lines
as fit — so the reply scrolls up as it grows. Swap the full renderable back
into the Live display before stopping it, and the finished reply is printed
whole into the scrollback.
"""

from rich.console import Console, ConsoleOptions, RenderableType, RenderResult
from rich.segment import Segment


class StreamTail:
    def __init__(self, renderable: RenderableType, reserve_lines: int = 1) -> None:
        self.renderable = renderable
        # Lines left free below the tail, for the cursor Live parks there.
        self.reserve_lines = reserve_lines

    def __rich_console__(self, console: Console, options: ConsoleOptions) -> RenderResult:
        visible = max(1, console.size.height - self.reserve_lines)
        lines = console.render_lines(self.renderable, options.update(height=None), pad=False)
        new_line = Segment.line()
        for line in lines[-visible:]:
            yield from line
            yield new_line
