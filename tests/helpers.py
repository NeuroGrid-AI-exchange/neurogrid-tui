"""Test doubles shared across modules."""

from nrgrd.config.credentials import CredentialStore


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
