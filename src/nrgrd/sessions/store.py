import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from platformdirs import user_data_dir

from nrgrd.context.models import ChatMessage


APP_NAME = "nrgrd"
APP_AUTHOR = "neurogrid"

MAX_MESSAGES = 100
MAX_SESSION_BYTES = 5 * 1024 * 1024


class WorkspaceSessionStore:
    """
    Stores one conversation session for each workspace.

    The workspace is the directory where Nrgrd was started.

    Sessions are stored outside the project directory in the
    operating system's application data directory.
    """

    def __init__(
        self,
        workspace_path: Path,
    ) -> None:
        self.workspace_path = (
            workspace_path.resolve()
        )

        self.sessions_directory = Path(
            user_data_dir(
                appname=APP_NAME,
                appauthor=APP_AUTHOR,
            )
        ) / "sessions"

        self.sessions_directory.mkdir(
            parents=True,
            exist_ok=True,
        )

        self.workspace_id = (
            self.create_workspace_id()
        )

        self.session_path = (
            self.sessions_directory
            / f"{self.workspace_id}.json"
        )

        self.history_path = (
            self.sessions_directory
            / f"{self.workspace_id}.history.jsonl"
        )

    def create_workspace_id(
        self,
    ) -> str:
        """
        Create a stable identifier from the absolute workspace path.

        The same directory always generates the same session ID.
        """

        normalized_path = str(
            self.workspace_path
        ).lower()

        path_hash = hashlib.sha256(
            normalized_path.encode(
                "utf-8"
            )
        ).hexdigest()

        return path_hash[:24]

    def get_session_path(
        self,
    ) -> Path:
        """
        Return the JSON file used for this workspace.
        """

        return self.session_path

    def load_messages(
        self,
    ) -> list[ChatMessage]:
        """
        Load messages from the workspace session.
        """

        if not self.session_path.exists():
            return []

        try:
            raw_data = (
                self.session_path
                .read_text(
                    encoding="utf-8"
                )
            )

            data = json.loads(
                raw_data
            )

            messages_data = (
                data.get(
                    "messages",
                    [],
                )
            )

            return [
                ChatMessage.model_validate(
                    message
                )
                for message
                in messages_data
            ]

        except (
            OSError,
            json.JSONDecodeError,
            ValueError,
        ):
            """
            Do not prevent Nrgrd from starting if a
            session file is damaged.
            """

            return []

    def save_messages(
        self,
        messages: list[ChatMessage],
    ) -> None:
        """
        Save messages to the workspace session.
        """

        limited_messages = (
            messages[
                -MAX_MESSAGES:
            ]
        )

        payload = {
            "workspace_path": str(
                self.workspace_path
            ),
            "messages": [
                message.model_dump()
                for message
                in limited_messages
            ],
        }

        serialized = json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
        )

        encoded = (
            serialized.encode(
                "utf-8"
            )
        )

        while (
            len(encoded)
            > MAX_SESSION_BYTES
            and limited_messages
        ):
            limited_messages.pop(0)

            payload["messages"] = [
                message.model_dump()
                for message
                in limited_messages
            ]

            serialized = json.dumps(
                payload,
                ensure_ascii=False,
                indent=2,
            )

            encoded = (
                serialized.encode(
                    "utf-8"
                )
            )

        self.session_path.write_text(
            serialized,
            encoding="utf-8",
        )

    def add_message(
        self,
        message: ChatMessage,
    ) -> None:
        """
        Add a message and persist the session.
        """

        messages = (
            self.load_messages()
        )

        messages.append(
            message
        )

        self.save_messages(
            messages
        )

    def archive_messages(
        self,
        messages: list[ChatMessage],
    ) -> None:
        """Append a pre-compaction transcript snapshot for recovery."""
        snapshot = {
            "compacted_at": datetime.now(UTC).isoformat(),
            "messages": [message.model_dump() for message in messages],
        }
        with self.history_path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(snapshot, ensure_ascii=False) + "\n")

    def clear(
        self,
    ) -> None:
        """
        Delete the session for the current workspace.
        """

        if self.session_path.exists():
            self.session_path.unlink()

    def get_size_bytes(
        self,
    ) -> int:
        """
        Return the current session file size.
        """

        if not self.session_path.exists():
            return 0

        return (
            self.session_path
            .stat()
            .st_size
        )
