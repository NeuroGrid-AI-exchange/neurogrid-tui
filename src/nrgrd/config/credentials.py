"""Where the API key lives — deliberately not in ``config.json``.

The key is a bearer credential for a rented deployment, so it is kept in
the operating system's credential store when one is usable. Headless Linux
boxes frequently have no keyring daemon, so there is a file fallback with
0600 permissions. The fallback is *not* encrypted, and
:attr:`CredentialStore.name` says so, because a key encrypted under a key
sitting beside it would only look secure.
"""

import json
import os
import stat
from pathlib import Path

from nrgrd.config.config import Config, get_config_directory, save_config

SERVICE = "nrgrd"
USERNAME = "api-key"
CREDENTIALS_FILENAME = "credentials.json"


class CredentialStore:
    """Stores exactly one secret: the API key for the configured endpoint."""

    name = "credential store"

    def get(self) -> str:
        raise NotImplementedError

    def set(self, api_key: str) -> None:
        raise NotImplementedError

    def delete(self) -> None:
        raise NotImplementedError


class KeyringStore(CredentialStore):
    name = "system keyring"

    def get(self) -> str:
        import keyring

        try:
            return keyring.get_password(SERVICE, USERNAME) or ""
        except Exception:
            return ""

    def set(self, api_key: str) -> None:
        import keyring

        keyring.set_password(SERVICE, USERNAME, api_key)

    def delete(self) -> None:
        import keyring

        try:
            keyring.delete_password(SERVICE, USERNAME)
        except Exception:
            pass


class FileStore(CredentialStore):
    """Fallback for machines without a usable keyring."""

    name = "local file (owner-only)"

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or (get_config_directory() / CREDENTIALS_FILENAME)

    def get(self) -> str:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return ""
        key = data.get("api_key", "")
        return key if isinstance(key, str) else ""

    def set(self, api_key: str) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Create the file before writing so the key never briefly exists
        # with default, world-readable permissions.
        self.path.touch(mode=stat.S_IRUSR | stat.S_IWUSR, exist_ok=True)
        try:
            os.chmod(self.path, stat.S_IRUSR | stat.S_IWUSR)
        except OSError:
            pass  # Windows and some filesystems do not support this.
        self.path.write_text(
            json.dumps({"api_key": api_key}, indent=4),
            encoding="utf-8",
        )

    def delete(self) -> None:
        self.path.unlink(missing_ok=True)


def keyring_is_usable() -> bool:
    """Report whether a real keyring backend will actually answer.

    Importing ``keyring`` always succeeds; it is the *backend* that may be
    missing, so probe it rather than trusting the import.
    """
    try:
        import keyring
        from keyring.backends.fail import Keyring as FailingKeyring
    except Exception:
        return False

    try:
        if isinstance(keyring.get_keyring(), FailingKeyring):
            return False
        keyring.get_password(SERVICE, "availability-probe")
    except Exception:
        return False
    return True


def load_credential_store() -> CredentialStore:
    return KeyringStore() if keyring_is_usable() else FileStore()


def migrate_plaintext_api_key(config: Config, store: CredentialStore) -> bool:
    """Move a key still sitting in ``config.json`` into ``store``.

    Returns whether a migration happened, so the caller can tell the user
    their key moved.
    """
    api_key = config.api_key.strip()
    if not api_key:
        return False

    store.set(api_key)
    config.api_key = ""
    save_config(config)
    return True
