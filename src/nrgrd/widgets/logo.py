from rich.text import Text

from nrgrd.theme.colors import GREEN

LOGO = r"""
███╗   ██╗██████╗  ██████╗ ██████╗ ██████╗    o   o   o---o
████╗  ██║██╔══██╗██╔════╝ ██╔══██╗██╔══██╗     \   /
██╔██╗ ██║██████╔╝██║  ███╗██████╔╝██║  ██║   o   O   o   o
██║╚██╗██║██╔══██╗██║   ██║██╔══██╗██║  ██║     /  \ -----
██║ ╚████║██║  ██║╚██████╔╝██║  ██║██████╔╝   o   o \ o   o
╚═╝  ╚═══╝╚═╝  ╚═╝ ╚═════╝ ╚═╝  ╚═╝╚═════╝     /     \
                                              o   o   o   o
"""


def create_logo() -> Text:
    """Return the branded logo renderable without imposing alignment."""
    return Text(
        LOGO.strip("\n"),
        style=f"bold {GREEN}",
    )
