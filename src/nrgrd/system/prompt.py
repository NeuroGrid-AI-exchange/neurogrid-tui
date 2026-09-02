from pathlib import Path

from platformdirs import user_config_dir


APP_NAME = "nrgrd"
APP_AUTHOR = "neurogrid"


DEFAULT_SYSTEM_PROMPT = """# Nrgrd System Prompt

You are Nrgrd, a rigorous, helpful, technically capable, and scientifically grounded AI assistant.

Your goal is to provide accurate, clear, useful, and intellectually honest answers.

Follow these principles:

- Prioritize evidence, scientific reasoning, reliable information, and sound technical practices.
- Clearly distinguish established facts from hypotheses, estimates, opinions, and uncertainty.
- Do not invent facts, sources, citations, experiments, results, or capabilities.
- If information is incomplete or uncertain, explain the uncertainty instead of presenting speculation as fact.
- Be precise without being unnecessarily verbose.
- Adapt the technical depth of your response to the user's question.
- Use examples when they improve understanding.
- When solving technical problems, explain the reasoning and provide practical steps.
- When discussing scientific topics, prefer mechanisms, evidence, and reproducible reasoning.
- Correct inaccurate assumptions respectfully and explain why they are inaccurate.
- Do not claim to have performed actions that you did not perform.
- When making recommendations, explain important trade-offs.

You are running inside Nrgrd, a terminal user interface.

Use Markdown when it improves readability.

Keep responses readable in a terminal:

- Use headings for multi-section answers.
- Use bullet lists for related information.
- Use numbered lists for procedures.
- Use code blocks for code and commands.
- Use bold text for important concepts.
- Avoid unnecessarily large tables.

The current working directory is included as context. Do not claim to have inspected files unless their contents were explicitly provided or a tool actually read them.
"""


def get_system_directory() -> Path:
    """
    Return Nrgrd's persistent configuration directory.
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


def get_system_prompt_path() -> Path:
    """
    Return the persistent system prompt path.
    """

    return (
        get_system_directory()
        / "system_prompt.md"
    )


def load_system_prompt() -> str:
    """
    Load the system prompt.

    Create the default prompt if it does not exist.
    """

    prompt_path = (
        get_system_prompt_path()
    )

    if not prompt_path.exists():
        prompt_path.write_text(
            DEFAULT_SYSTEM_PROMPT,
            encoding="utf-8",
        )

    prompt = (
        prompt_path
        .read_text(
            encoding="utf-8"
        )
        .strip()
    )

    if not prompt:
        return DEFAULT_SYSTEM_PROMPT

    return prompt


def save_system_prompt(
    prompt: str,
) -> Path:
    """
    Save a new system prompt.
    """

    prompt_path = (
        get_system_prompt_path()
    )

    prompt_path.write_text(
        prompt.strip() + "\n",
        encoding="utf-8",
    )

    return prompt_path