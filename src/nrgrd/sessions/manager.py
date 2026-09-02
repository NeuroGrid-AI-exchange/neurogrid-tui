from pathlib import Path

from nrgrd.context.models import ChatMessage
from nrgrd.sessions.store import (
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
    ) -> None:
        self.workspace_path = (
            workspace_path.resolve()
        )

        self.store = (
            WorkspaceSessionStore(
                self.workspace_path
            )
        )

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
