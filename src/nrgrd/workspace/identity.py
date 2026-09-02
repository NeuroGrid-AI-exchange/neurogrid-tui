import hashlib
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class WorkspaceIdentity:
    """
    Stable identity for the current working directory.

    The normalized path is hashed so it can safely be used
    as a storage directory name.
    """

    path: Path
    normalized_path: str
    workspace_id: str

    @classmethod
    def from_path(
        cls,
        path: Path,
    ) -> "WorkspaceIdentity":
        resolved_path = (
            path
            .resolve()
        )

        normalized_path = (
            str(
                resolved_path
            )
            .replace(
                "\\",
                "/",
            )
            .casefold()
        )

        workspace_id = (
            hashlib
            .sha256(
                normalized_path.encode(
                    "utf-8"
                )
            )
            .hexdigest()
        )

        return cls(
            path=resolved_path,
            normalized_path=(
                normalized_path
            ),
            workspace_id=(
                workspace_id
            ),
        )