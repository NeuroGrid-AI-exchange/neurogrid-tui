"""Tell the user when PyPI has a newer nrgrd, and how to upgrade.

The check runs in the background at startup and at most once a day (the
answer is cached), with a short timeout, so a slow or missing network never
delays the prompt. NRGRD_NO_UPDATE_CHECK=1 turns it off.
"""

import json
import os
import re
import sys
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path

PACKAGE = "nrgrd"
PYPI_JSON_URL = f"https://pypi.org/pypi/{PACKAGE}/json"
PYPI_PAGE_URL = f"https://pypi.org/project/{PACKAGE}/"
CHECK_INTERVAL = timedelta(days=1)
TIMEOUT_SECONDS = 3.0
DISABLE_ENV = "NRGRD_NO_UPDATE_CHECK"


def fetch_latest_version(timeout: float = TIMEOUT_SECONDS) -> str | None:
    """The newest release on PyPI, or None if PyPI can't be reached."""
    request = urllib.request.Request(
        PYPI_JSON_URL, headers={"Accept": "application/json", "User-Agent": PACKAGE}
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = json.load(response)
    except Exception:  # Offline, blocked, or PyPI having a bad day: no news.
        return None
    version = (data.get("info") or {}).get("version")
    return version if isinstance(version, str) and version.strip() else None


def _parse(version: str) -> tuple[tuple[int, ...], bool]:
    """(release numbers, is a pre-release or dev build)."""
    match = re.match(r"\s*v?(\d+(?:\.\d+)*)(.*)", version)
    if not match:
        return (), True
    numbers = tuple(int(part) for part in match.group(1).split("."))
    # Trailing zeros don't matter: 0.2 == 0.2.0.
    while len(numbers) > 1 and numbers[-1] == 0:
        numbers = numbers[:-1]
    rest = match.group(2).lower()
    return numbers, bool(re.match(r"[.\-_]?(a|b|rc|alpha|beta|pre|preview|dev)", rest))


def is_newer(candidate: str, current: str) -> bool:
    """Whether release ``candidate`` is newer than the running ``current``.

    A dev build of 0.2.0 (0.2.0.dev3+g…, what a source checkout reports) is
    older than the 0.2.0 release.
    """
    new, new_pre = _parse(candidate)
    old, old_pre = _parse(current)
    if not new or not old:
        return False
    if new != old:
        return new > old
    return old_pre and not new_pre


def cached_latest_version(cache_path: Path, now: datetime | None = None) -> str | None:
    """The latest version, from a cache younger than a day or else from PyPI."""
    now = now or datetime.now(UTC)
    try:
        cached = json.loads(cache_path.read_text(encoding="utf-8"))
        checked = datetime.fromisoformat(cached["checked_at"])
        if now - checked < CHECK_INTERVAL and cached.get("latest"):
            return cached["latest"]
    except (OSError, ValueError, KeyError, TypeError):
        pass

    latest = fetch_latest_version()
    if latest:
        try:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(
                json.dumps({"checked_at": now.isoformat(), "latest": latest}), encoding="utf-8"
            )
        except OSError:
            pass
    return latest


def update_check_disabled() -> bool:
    return os.environ.get(DISABLE_ENV, "").strip().lower() in {"1", "true", "yes", "on"}


def running_from_source() -> bool:
    """Whether this is a git checkout (src/nrgrd inside a project folder)."""
    return Path(__file__).resolve().parents[2].joinpath("pyproject.toml").exists()


def upgrade_command(
    prefix: str | None = None, from_source: bool | None = None
) -> list[str] | None:
    """The command that upgrades this installation, judged by where it lives.

    None for a source checkout, which updates with git rather than a
    package manager.
    """
    location = (prefix or sys.prefix).replace("\\", "/").lower()
    # uv keeps tools in …/uv/tools (Linux, macOS) or …\uv\data\tools (Windows).
    if re.search(r"/uv/(data/)?tools/", location + "/"):
        return ["uv", "tool", "upgrade", PACKAGE]
    if "/pipx/" in location + "/":
        return ["pipx", "upgrade", PACKAGE]
    if running_from_source() if from_source is None else from_source:
        return None
    return [sys.executable, "-m", "pip", "install", "--upgrade", PACKAGE]
