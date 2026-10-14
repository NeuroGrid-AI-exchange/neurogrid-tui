"""Images and files sent along with a message.

Text files are inlined into the message as ``<file name="…">`` blocks, so
any model can read them and they stay in the saved conversation. Images go
as OpenAI-style ``image_url`` parts carrying a data URI; only models with
vision can read them, and the saved conversation keeps a short note in
their place rather than megabytes of base64.

Attachments arrive three ways: ``/attach <path>``, pasting a file path or
dragging a file onto the terminal (which pastes its path), and Ctrl+V or
``/paste`` for an image on the clipboard.
"""

import base64
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal
from urllib.parse import unquote, urlparse

IMAGE_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
}

# Larger images are rejected by most endpoints anyway.
MAX_IMAGE_BYTES = 10 * 1024 * 1024

# A text file longer than this is cut, with a note, so one attachment
# can't swallow the context window on its own.
MAX_TEXT_CHARS = 100_000

CLIPBOARD_TIMEOUT_SECONDS = 5


class AttachmentError(Exception):
    """A file that can't be attached, with a reason fit to show the user."""


@dataclass(frozen=True)
class Attachment:
    name: str
    kind: Literal["image", "text"]
    mime: str
    # The text itself, or the image as base64.
    data: str

    @property
    def size_label(self) -> str:
        if self.kind == "image":
            size = len(self.data) * 3 // 4
            return f"{size / 1024:.0f} KB" if size < 1024 * 1024 else f"{size / 1024 / 1024:.1f} MB"
        return f"{len(self.data.splitlines())} lines"


def image_attachment(name: str, content: bytes, mime: str = "image/png") -> Attachment:
    if len(content) > MAX_IMAGE_BYTES:
        raise AttachmentError(f"{name} is larger than {MAX_IMAGE_BYTES // 1024 // 1024} MB.")
    return Attachment(name, "image", mime, base64.b64encode(content).decode("ascii"))


def load_attachment(path: Path, name: str | None = None) -> Attachment:
    """Read a file from disk as an attachment."""
    label = name or path.name
    if not path.exists():
        raise AttachmentError(f"{path} doesn't exist.")
    if path.is_dir():
        raise AttachmentError(f"{path} is a folder; attach the files inside it.")

    mime = IMAGE_TYPES.get(path.suffix.lower())
    try:
        if mime:
            if path.stat().st_size > MAX_IMAGE_BYTES:
                raise AttachmentError(
                    f"{label} is larger than {MAX_IMAGE_BYTES // 1024 // 1024} MB."
                )
            return image_attachment(label, path.read_bytes(), mime)
        content = path.read_bytes()
    except OSError as error:
        raise AttachmentError(f"Couldn't read {path}: {error.strerror or error}.") from error

    if b"\x00" in content[:8192]:
        raise AttachmentError(
            f"{label} is a binary file. Attach images (PNG, JPEG, GIF, WebP) or text files."
        )
    text = content.decode("utf-8", errors="replace")
    if len(text) > MAX_TEXT_CHARS:
        text = text[:MAX_TEXT_CHARS] + f"\n… (cut at {MAX_TEXT_CHARS:,} characters)"
    return Attachment(label, "text", "text/plain", text)


def display_name(path: Path, workspace: Path) -> str:
    """The path relative to the workspace when it's inside it."""
    try:
        return str(path.resolve().relative_to(workspace.resolve()))
    except ValueError:
        return path.name


def _split_paths(text: str) -> list[str]:
    tokens: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if sys.platform == "win32":
            # shlex would eat Windows backslashes; drag-and-drop on Windows
            # quotes each path with double quotes instead.
            tokens.extend(part.strip('"') for part in line.split('" "'))
            continue
        try:
            tokens.extend(shlex.split(line))
        except ValueError:
            tokens.append(line)
    return tokens


def pasted_paths(text: str, workspace: Path) -> list[Path] | None:
    """The files a paste names, if the paste is nothing but file paths.

    Copying a file in a file manager, or dragging one onto the terminal,
    pastes its path (sometimes as a file:// URI, quoted or with escaped
    spaces). A paste that is anything more than paths returns None and is
    treated as ordinary text, so mentioning a path in a sentence never
    attaches it.
    """
    tokens = _split_paths(text)
    if not tokens:
        return None
    paths: list[Path] = []
    for token in tokens:
        if token.startswith("file://"):
            token = unquote(urlparse(token).path)
            if sys.platform == "win32" and token.startswith("/") and token[2:3] == ":":
                token = token[1:]
        path = Path(os.path.expanduser(token))
        if not path.is_absolute():
            path = workspace / path
        if not path.is_file():
            return None
        paths.append(path)
    return paths


def build_user_content(
    text: str, attachments: list[Attachment]
) -> tuple[str | list[dict[str, Any]], str]:
    """The user message to send, and the text to keep in the saved conversation."""
    files = "".join(
        f'\n\n<file name="{item.name}">\n{item.data}\n</file>'
        for item in attachments
        if item.kind == "text"
    )
    images = [item for item in attachments if item.kind == "image"]
    sent_text = text + files
    saved = sent_text + "".join(f"\n\n[image attached: {item.name}]" for item in images)
    if not images:
        return sent_text, saved
    parts: list[dict[str, Any]] = [{"type": "text", "text": sent_text}]
    parts.extend(
        {"type": "image_url", "image_url": {"url": f"data:{item.mime};base64,{item.data}"}}
        for item in images
    )
    return parts, saved


# --- clipboard ------------------------------------------------------------


class ClipboardUnavailable(Exception):
    """No way to read the clipboard here; the message says what to install."""


def _run(command: list[str]) -> bytes | None:
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            timeout=CLIPBOARD_TIMEOUT_SECONDS,
            stdin=subprocess.DEVNULL,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return result.stdout if result.returncode == 0 else None


def clipboard_image() -> bytes | None:
    """The PNG image on the clipboard, None if it holds no image.

    Raises ClipboardUnavailable when this system has no tool to read it.
    """
    if sys.platform == "darwin":
        if shutil.which("pngpaste"):
            return _run(["pngpaste", "-"]) or None
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "clipboard.png"
            script = (
                f'set f to (open for access POSIX file "{target}" with write permission)\n'
                "try\n"
                "  write (the clipboard as «class PNGf») to f\n"
                "end try\n"
                "close access f"
            )
            _run(["osascript", "-e", script])
            return target.read_bytes() if target.exists() and target.stat().st_size else None

    if sys.platform == "win32":
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "clipboard.png"
            script = (
                "Add-Type -AssemblyName System.Windows.Forms, System.Drawing; "
                "$image = [Windows.Forms.Clipboard]::GetImage(); "
                f"if ($image) {{ $image.Save('{target}', [Drawing.Imaging.ImageFormat]::Png) }}"
            )
            _run(["powershell", "-NoProfile", "-STA", "-Command", script])
            return target.read_bytes() if target.exists() else None

    if os.environ.get("WAYLAND_DISPLAY") and shutil.which("wl-paste"):
        types = (_run(["wl-paste", "--list-types"]) or b"").decode(errors="replace").split()
        if "image/png" not in types:
            return None
        return _run(["wl-paste", "--type", "image/png"]) or None
    if shutil.which("xclip"):
        targets = (_run(["xclip", "-selection", "clipboard", "-t", "TARGETS", "-o"]) or b"")
        if b"image/png" not in targets:
            return None
        return _run(["xclip", "-selection", "clipboard", "-t", "image/png", "-o"]) or None

    raise ClipboardUnavailable(
        "Reading images from the clipboard needs wl-clipboard (Wayland) or xclip (X11) — "
        "e.g. `sudo apt install xclip`. Meanwhile, /attach <path> works."
    )


def clipboard_text() -> str | None:
    """The text on the clipboard, if this system can read it."""
    if sys.platform == "darwin":
        content = _run(["pbpaste"])
    elif sys.platform == "win32":
        content = _run(["powershell", "-NoProfile", "-Command", "Get-Clipboard -Raw"])
    elif os.environ.get("WAYLAND_DISPLAY") and shutil.which("wl-paste"):
        content = _run(["wl-paste", "--no-newline"])
    elif shutil.which("xclip"):
        content = _run(["xclip", "-selection", "clipboard", "-o"])
    elif shutil.which("xsel"):
        content = _run(["xsel", "--clipboard", "--output"])
    else:
        content = None
    return content.decode("utf-8", errors="replace") if content else None
