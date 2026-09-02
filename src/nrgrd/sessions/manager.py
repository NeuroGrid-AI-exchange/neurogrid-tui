from pathlib import Path

from nrgrd.context.models import ChatMessage
from nrgrd.sessions.store import (
    DEFAULT_SESSION,
    SessionInfo,
    WorkspaceSessionStore,
)


class SessionManager:
    """
    High-level session API used by Nrgrd.

    Each working directory gets one persistent session.
    """

    def __init__(
        self,
        workspace_path: Path,
        name: str = DEFAULT_SESSION,
    ) -> None:
        self.workspace_path = (
            workspace_path.resolve()
        )

        self.store = (
            WorkspaceSessionStore(
                self.workspace_path,
                name,
            )
        )

    @property
    def name(self) -> str:
        """The session currently in use."""
        return self.store.name

    def list_sessions(self) -> list[SessionInfo]:
        return self.store.list_sessions()

    def switch(self, name: str) -> None:
        """Resume another session in this workspace."""
        self.store.switch(name)

    def start(self, name: str) -> None:
        """Switch to a session and persist it, so it exists even when empty."""
        self.store.switch(name)
        self.store.ensure_exists()

    def rename(self, new_name: str) -> bool:
        return self.store.rename(new_name)

    def delete(self, name: str) -> bool:
        """Delete a session; switches back to the default if it was active."""
        deleted = self.store.delete(name)
        if deleted and name.strip() == self.store.name:
            self.store.switch(DEFAULT_SESSION)
        return deleted

    @property
    def messages(
        self,
    ) -> list[ChatMessage]:
        """
        Return the messages in the current session.
        """

        return self.get_messages()

    def get_messages(
        self,
    ) -> list[ChatMessage]:
        """
        Load all messages for the current workspace.
        """

        return (
            self.store
            .load_messages()
        )

    def add_message(
        self,
        role: str,
        content: str,
    ) -> None:
        """
        Add a message to the current workspace session.
        """

        message = ChatMessage(
            role=role,
            content=content,
        )

        self.store.add_message(
            message
        )

    def clear(
        self,
    ) -> None:
        """
        Clear the current workspace session.
        """

        self.store.clear()

    def replace_messages(
        self,
        messages: list[ChatMessage],
    ) -> None:
        """Atomically replace the persisted conversation messages."""
        self.store.save_messages(messages)

    def archive_messages(
        self,
        messages: list[ChatMessage],
    ) -> None:
        """Preserve a transcript snapshot before context compaction."""
        self.store.archive_messages(messages)

    def get_session_path(
        self,
    ) -> Path:
        """
        Return the path where the session is stored.
        """

        return (
            self.store
            .get_session_path()
        )

    def get_size_bytes(
        self,
    ) -> int:
        """
        Return the session size in bytes.
        """

        return (
            self.store
            .get_size_bytes()
        )
