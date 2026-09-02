from pathlib import Path

from platformdirs import user_config_dir
from pydantic import BaseModel, Field


APP_NAME = "nrgrd"
APP_AUTHOR = "neurogrid"


class Config(BaseModel):
    """
    Nrgrd's persistent configuration.
    """

    api_key: str = Field(
        default="",
        description=(
            "Legacy plaintext API key. Kept only so an existing config can "
            "be migrated into the credential store on startup; it is blanked "
            "once moved and never written back. See config/credentials.py."
        ),
    )

    base_url: str = Field(
        default="",
        description=(
            "Endpoint of the OpenAI-compatible API: the deploy URL from the "
            "NeuroGrid console, or a local vLLM/Ollama/LM Studio server. "
            "Usually ends in /v1."
        ),
    )

    model: str = Field(
        default="",
        description="Currently selected model.",
    )

    context_window_tokens: int = Field(
        default=16000,
        ge=2048,
        description="Estimated model context window used for auto-compaction.",
    )

    compact_keep_recent_tokens: int = Field(
        default=4000,
        ge=512,
        description="Estimated recent conversation tokens retained after compaction.",
    )


def get_config_directory() -> Path:
    """
    Return Nrgrd's configuration directory.

    On Windows, this will normally be inside AppData.
    """

    directory = Path(
        user_config_dir(
            appname=APP_NAME,
            appauthor=APP_AUTHOR,
        )
    )

    directory.mkdir(
        parents=True,
        exist_ok=True,
    )

    return directory


def get_config_path() -> Path:
    """
    Return the complete path to Nrgrd's config.json file.
    """

    return (
        get_config_directory()
        / "config.json"
    )


def load_config() -> Config:
    """
    Load the configuration from disk.

    If the configuration file does not exist,
    create it using the default values.
    """

    config_path = get_config_path()

    if not config_path.exists():
        config = Config()

        save_config(config)

        return config

    try:
        content = config_path.read_text(
            encoding="utf-8",
        )

        return Config.model_validate_json(
            content
        )

    except Exception:
        """
        If the config file is invalid, return a
        default configuration instead of crashing.
        """

        config = Config()

        save_config(config)

        return config


def save_config(
    config: Config,
) -> Path:
    """
    Save the configuration to disk.
    """

    config_path = get_config_path()

    config_path.write_text(
        config.model_dump_json(
            indent=4,
        ),
        encoding="utf-8",
    )

    return config_path

