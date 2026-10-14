"""Every slash command nrgrd understands, with what it does.

One list feeds /help, the completion menu, and the description line shown
under the prompt while a command is highlighted, so the three can never
drift apart.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Command:
    # What the completion menu inserts, e.g. "/session new ".
    insert: str
    # How /help writes it, arguments included, e.g. "/session new <name>".
    usage: str
    description: str


COMMANDS: tuple[Command, ...] = (
    Command("/con", "/con", "Check the configured API connection."),
    Command("/models", "/models", "List models available from the configured API."),
    Command("/models ", "/models <model>", "Select and save a model."),
    Command("/config", "/config", "Show the current configuration."),
    Command("/config edit", "/config edit", "Open the configuration file in the default editor."),
    Command("/session", "/session", "Show the active session, its storage location, and usage."),
    Command("/session clear", "/session clear", "Clear the conversation associated with the current directory."),
    Command("/session list", "/session list", "List saved sessions for this workspace."),
    Command("/session new ", "/session new <name>", "Start and switch to a new session."),
    Command("/session resume ", "/session resume <name>", "Resume a saved session."),
    Command("/session rename ", "/session rename <name>", "Rename the current session."),
    Command("/session delete ", "/session delete <name>", "Delete a saved session."),
    Command("/compact", "/compact [focus]", "Summarize older conversation and keep a recent context tail."),
    Command(
        "/goal ",
        "/goal <objective>",
        "Keep working, round after round, until the objective is done — no round limit. Ctrl+C stops.",
    ),
    Command("/attach ", "/attach <path> [path…]", "Attach images or text files to your next message."),
    Command("/attach clear", "/attach clear", "Drop the files waiting to be sent."),
    Command("/paste", "/paste", "Attach the image on your clipboard (same as Ctrl+V)."),
    Command("/graph", "/graph", "Beta: draw this session's conversation — turns, tools and files."),
    Command("/tools", "/tools", "Show the workspace coding tools available to nrgrd."),
    Command("/permissions", "/permissions", "Show how each tool is gated."),
    Command("/permissions reset", "/permissions reset", "Revoke this session's approvals."),
    Command("/diff", "/diff", "Show the working tree diff."),
    Command("/context", "/context", "Show what the next request sends and how much of the window it uses."),
    Command("/neurochat", "/neurochat", "Open NeuroChat in your browser on this endpoint and API key."),
    Command("/update", "/update", "Check PyPI for a newer nrgrd and upgrade it."),
    Command("/version", "/version", "Show the nrgrd version, its Python, and how it was installed."),
    Command("/mcp", "/mcp", "Show configured MCP servers and discovered tools."),
    Command("/mcp edit", "/mcp edit", "Show where to edit the Claude-compatible mcpServers file."),
    Command("/mcp reload", "/mcp reload", "Reconnect to configured MCP servers and refresh tools."),
    Command("/system", "/system", "Show the current system prompt."),
    Command("/system edit", "/system edit", "Open the system prompt in the default editor."),
    Command("/clear", "/clear", "Clear the terminal."),
    Command("/help", "/help", "Show every command."),
    Command("/exit", "/exit", "Exit nrgrd."),
)


def describe(text: str) -> Command | None:
    """The command the typed text is, or starts, with its arguments ignored.

    "/session new work" -> the /session new entry. The longest match wins, so
    "/mcp reload" is not mistaken for "/mcp".
    """
    typed = text.strip().lower()
    if not typed.startswith("/"):
        return None
    best: Command | None = None
    for command in COMMANDS:
        name = command.insert.strip().lower()
        if typed == name or typed.startswith(name + " "):
            if best is None or len(name) > len(best.insert.strip()):
                best = command
    return best
