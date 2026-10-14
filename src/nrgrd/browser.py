"""Open a URL in the user's browser without tying up the terminal.

The standard library's ``webbrowser.open`` starts the browser with nrgrd's
terminal as its stdout and stderr. Browsers log freely, so their output
lands on top of the prompt and the terminal looks broken until it's
cleared. Here the opener runs in its own session with every stream sent to
the null device, and nrgrd returns to the prompt at once.
"""

import os
import shutil
import subprocess
import sys
import webbrowser


def _opener() -> list[str] | None:
    if sys.platform == "darwin":
        return ["open"]
    if sys.platform.startswith("linux") or "bsd" in sys.platform:
        for candidate in ("xdg-open", "gio"):
            path = shutil.which(candidate)
            if path:
                return [path, "open"] if candidate == "gio" else [path]
    return None


def open_url(url: str) -> bool:
    """Open ``url`` in the default browser. Returns whether a browser was started."""
    if sys.platform == "win32":
        try:
            os.startfile(url)  # type: ignore[attr-defined]  # Windows only
        except OSError:
            return False
        return True

    if (
        sys.platform != "darwin"
        and not os.environ.get("DISPLAY")
        and not os.environ.get("WAYLAND_DISPLAY")
    ):
        # An SSH session or a headless box: xdg-open would "succeed" with
        # nowhere to show anything, so report it and let the caller print
        # the link instead.
        return False

    command = _opener()
    if command is None:
        # Nothing we know how to call quietly; let the standard library try.
        try:
            return webbrowser.open(url)
        except webbrowser.Error:
            return False

    try:
        subprocess.Popen(
            [*command, url],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            close_fds=True,
        )
    except OSError:
        return False
    return True
