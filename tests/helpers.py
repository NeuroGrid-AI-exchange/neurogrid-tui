"""Test doubles shared across modules."""

import io

from rich.console import Console

from nrgrd.config.credentials import CredentialStore


def quiet_console() -> Console:
    """A console whose output goes nowhere.

    Writes into a buffer rather than a null device: there is no portable
    path for that ("/dev/null" does not exist on Windows), and this leaks
    no file handle.
    """
    return Console(file=io.StringIO(), force_terminal=False)


class MemoryStore(CredentialStore):
    """A credential store that keeps the key in memory only."""

    name = "memory"

    def __init__(self) -> None:
        self.value = ""

    def get(self) -> str:
        return self.value

    def set(self, api_key: str) -> None:
        self.value = api_key

    def delete(self) -> None:
        self.value = ""
