"""Permission gating for tool calls.

``ALLOW`` and ``DENY`` are decided without user interaction. ``ASK`` defers
to a callback supplied by the interface (TUI or CLI); the manager never
silently downgrades ``ASK`` to allowed just because no callback was given.
"""

from collections.abc import Callable

from nrgrd.tools.registry import PermissionLevel

PermissionCallback = Callable[[str, str], str]
"""Given a tool name and its raw JSON arguments, return "yes", "no", or "always"."""


class PermissionManager:
    def __init__(self, callback: PermissionCallback | None = None) -> None:
        self.callback = callback
        self._always_allowed: set[str] = set()

    @property
    def session_grants(self) -> list[str]:
        """Tools the user chose to always allow for this session."""
        return sorted(self._always_allowed)

    def revoke_session_grants(self) -> None:
        """Forget every "always allow", so those tools ask again."""
        self._always_allowed.clear()

    def check(self, name: str, arguments: str, level: PermissionLevel) -> bool:
        if level == PermissionLevel.ALLOW:
            return True
        if level == PermissionLevel.DENY:
            return False
        if name in self._always_allowed:
            return True
        if self.callback is None:
            return False
        decision = self.callback(name, arguments)
        if decision == "always":
            self._always_allowed.add(name)
            return True
        return decision == "yes"
