import json
import os
import time
from pathlib import Path
from typing import Any

from rich.box import ROUNDED
from rich.align import Align
from rich.console import Console
from rich.console import Group
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.prompt import Prompt
from rich.spinner import Spinner
from rich.table import Table
from rich.text import Text

try:
    from prompt_toolkit import PromptSession
    from prompt_toolkit.completion import WordCompleter
except ImportError:  # Keep the CLI usable until optional UI dependencies are installed.
    PromptSession = None
    WordCompleter = None

from nrgrd.agent import (
    Agent,
    AgentError,
    AgentFinished,
    AssistantChunk,
    PermissionManager,
    ToolCallDenied,
    ToolCallOutput,
    ToolCallStarted,
)
from nrgrd.api import ModelProvider, OpenAICompatibleProvider, ProviderError
from nrgrd.config import (
    Config,
    get_config_path,
    load_config,
    save_config,
)
from nrgrd.config.credentials import (
    load_credential_store,
    migrate_plaintext_api_key,
)
from nrgrd.context.models import ChatMessage
from nrgrd.context.tokens import (
    estimate_messages_tokens,
    estimate_text_tokens,
)
from nrgrd.mcp import MCPClient, get_mcp_config_path
from nrgrd.screens import run_connect_screen
from nrgrd.sessions import SessionManager
from nrgrd.system import (
    load_system_prompt,
    save_system_prompt,
)
from nrgrd.theme.colors import (
    BORDER,
    ERROR,
    GREEN,
    GREEN_BRIGHT,
    GREEN_VIVID,
    MUTED,
    PINK,
    PINK_LIGHT,
    TEXT,
    WARNING,
)
from nrgrd.tools import build_default_registry, register_mcp_tools
from nrgrd.widgets.logo import create_logo, logo_frames
from nrgrd.theme.colors import BACKGROUND
from nrgrd.workspace import WorkspaceTools


DIM = MUTED

# Seconds between startup logo frames; the whole animation is ~0.3s.
LOGO_FRAME_SECONDS = 0.07


class NrgrdApp:
    def __init__(self) -> None:
        self.console = Console()

        self.working_directory = Path.cwd().resolve()

        self.config: Config = load_config()

        self.session_manager = SessionManager(
            self.working_directory
        )
        self.workspace_tools = WorkspaceTools(self.working_directory)
        self.mcp_client = MCPClient(self.working_directory)
        self.mcp_client.reload()

        self.tool_registry = build_default_registry(self.workspace_tools)
        register_mcp_tools(self.tool_registry, self.mcp_client)
        self.permissions = PermissionManager(callback=self.ask_permission)

        self.credentials = load_credential_store()
        self.migrated_api_key = migrate_plaintext_api_key(
            self.config, self.credentials
        )
        self.api_key = self.credentials.get()

        self.provider: ModelProvider | None = None

        self.create_provider()

    def create_provider(self) -> None:
        """
        Build the model provider for the configured endpoint.

        nrgrd only ever knows an endpoint, a key, and a model name; which
        service is behind them is not its business.
        """

        if not self.api_key.strip() or not self.config.base_url.strip():
            self.provider = None
            return

        self.provider = OpenAICompatibleProvider(
            endpoint=self.config.base_url.strip(),
            api_key=self.api_key.strip(),
        )

    def connect(self) -> None:
        """Run the connect screen and rebuild the provider from its result."""

        api_key = run_connect_screen(
            self.console,
            self.config,
            self.credentials,
            current_api_key=self.api_key,
        )
        if api_key is None:
            return

        self.api_key = api_key
        self.create_provider()

    def print_error_panel(self, summary: str, detail: str, hint: str) -> None:
        """Render a failure the user can actually act on."""

        body = summary
        if detail:
            body += f"\n\n[{MUTED}]{detail}[/]"
        if hint:
            body += f"\n\n{hint}"

        self.console.print(
            Panel(
                body,
                title=f"[bold {ERROR}]Model request failed[/bold {ERROR}]",
                border_style=ERROR,
                box=ROUNDED,
                padding=(0, 1),
            )
        )

    def _hex_to_rgb(self, hex_color: str) -> tuple[int, int, int]:
        hex_color = hex_color.lstrip("#")
        return tuple(int(hex_color[i:i + 2], 16) for i in (0, 2, 4))

    def _set_terminal_background(self) -> None:
        r, g, b = self._hex_to_rgb(BACKGROUND)
        self.console.file.write(f"\033[48;2;{r};{g};{b}m")

    def _reset_terminal_background(self) -> None:
        self.console.file.write("\033[0m")

    def clear_terminal(self) -> None:
        """
        Clear the terminal on Windows, Linux, or macOS.
        """

        os.system(
            "cls"
            if os.name == "nt"
            else "clear"
        )

    def print_logo(self) -> None:
        """
        Print the Nrgrd logo and current directory.
        """

        self.print_header()

        details = Table.grid(padding=(0, 1), collapse_padding=True)
        details.add_column(style=f"bold {PINK_LIGHT}", no_wrap=True)
        details.add_column(style=TEXT)
        details.add_row("Workspace", str(self.working_directory))
        details.add_row("Model", self.config.model or "Not selected")
        details.add_row("Tip", "Type /help to see available commands")

        def panel_for(logo: Text) -> Panel:
            return Panel(
                Group(logo, Text(""), Align.center(details)),
                title=f"[bold {GREEN_BRIGHT}]NRGRD[/bold {GREEN_BRIGHT}]",
                subtitle=f"[{MUTED}]interactive AI workspace[/]",
                border_style=BORDER,
                box=ROUNDED,
                padding=(1, 2),
            )

        # Play the emblem's "node fires" animation once at startup, and only
        # on a real terminal so piped or redirected output stays clean.
        if not self.console.is_terminal:
            self.console.print(panel_for(create_logo()))
            return

        frames = logo_frames()
        with Live(
            panel_for(frames[0]),
            console=self.console,
            refresh_per_second=30,
        ) as live:
            for frame in frames[1:]:
                time.sleep(LOGO_FRAME_SECONDS)
                live.update(panel_for(frame))

    def print_header(self) -> None:
        """
        Print a compact header after clearing the terminal.
        """

        header = Text()

        header.append(
            "NRGRD",
            style=f"bold {GREEN_VIVID}",
        )

        header.append(
            "  •  ",
            style=DIM,
        )

        header.append(
            "Model: ",
            style=f"bold {PINK}",
        )

        header.append(
            self.config.model,
            style=GREEN_VIVID,
        )

        header.append(
            "  •  ",
            style=DIM,
        )

        header.append(
            "Messages: ",
            style=f"bold {PINK}",
        )

        header.append(
            str(
                len(
                    self.session_manager.messages
                )
            ),
            style=GREEN_VIVID,
        )

        self.console.print(
            Panel(
                header,
                title=f"[bold {GREEN_BRIGHT}]NRGRD[/bold {GREEN_BRIGHT}]",
                border_style=BORDER,
                box=ROUNDED,
                padding=(0, 1),
            )
        )

    def run(self) -> None:
        """
        Run the main interactive loop.
        """

        self.clear_terminal()
        self._set_terminal_background()

        self.print_logo()

        if self.migrated_api_key:
            self.console.print(
                f"[{GREEN_VIVID}]● Your API key moved out of config.json "
                f"and into your {self.credentials.name}.[/]"
            )

        # First launch: nothing is configured yet, so ask rather than
        # leaving the user to discover /config edit on their own.
        if self.provider is None:
            self.connect()

        while True:
            try:
                user_input = self.ask_for_input()

            except (
                KeyboardInterrupt,
                EOFError,
            ):
                self.console.print()

                self._reset_terminal_background()

                self.console.print(
                    f"[{PINK}]Goodbye.[/]"
                )

                break

            if not user_input:
                continue

            should_exit = self.handle_input(
                user_input
            )

            if should_exit:
                self._reset_terminal_background()
                break

    def ask_for_input(self) -> str:
        """Read input with a slash-command dropdown when prompt-toolkit is present."""
        prompt = "nrgrd> "
        if PromptSession is None or WordCompleter is None:
            return Prompt.ask(f"[bold {GREEN_VIVID}]nrgrd[/bold {GREEN_VIVID}][bold {PINK}]>[/bold {PINK}]").strip()
        commands = [
            "/help", "/con", "/models", "/config", "/config edit", "/session",
            "/session clear", "/compact", "/tools", "/mcp", "/mcp edit",
            "/mcp reload", "/system", "/system edit", "/clear", "/exit",
        ]
        session = PromptSession(completer=WordCompleter(commands, sentence=True))
        return session.prompt(prompt, complete_while_typing=True).strip()

    def handle_input(
        self,
        user_input: str,
    ) -> bool:
        """
        Handle Nrgrd commands or send a normal message.
        """

        command = user_input.strip()

        normalized = command.lower()

        if normalized in {
            "/exit",
            "/quit",
            "exit",
            "quit",
        }:
            self.console.print()

            self.console.print(
                f"[{PINK}]Goodbye.[/]"
            )

            return True

        if normalized == "/help":
            self.show_help()
            return False

        if normalized == "/tools":
            self.show_tools()
            return False

        if normalized == "/mcp":
            self.show_mcp()
            return False

        if normalized == "/mcp edit":
            self.show_mcp_edit_instructions()
            return False

        if normalized == "/mcp reload":
            self.mcp_client.reload()
            register_mcp_tools(self.tool_registry, self.mcp_client)
            self.console.print(f"[{GREEN_VIVID}]● MCP servers reloaded[/]")
            self.show_mcp()
            return False

        if normalized == "/compact" or normalized.startswith("/compact "):
            instructions = command[len("/compact"):].strip()
            self.compact_conversation(instructions=instructions)
            return False

        if normalized == "/con":
            self.show_connection_information()
            return False

        if normalized == "/config":
            self.show_config()
            return False

        if normalized == "/config edit":
            self.edit_config()
            return False

        if normalized == "/models":
            self.list_models()
            return False

        if normalized.startswith("/models "):
            model = (
                command[len("/models "):]
                .strip()
                .strip('"')
                .strip("'")
            )

            self.select_model(model)

            return False

        if normalized == "/session":
            self.show_session_information()
            return False

        if normalized in {
            "/session clear",
            "/session reset",
        }:
            self.clear_session()
            return False

        if normalized == "/system":
            self.show_system_prompt()
            return False

        if normalized == "/system edit":
            self.edit_system_prompt()
            return False

        if normalized == "/clear":
            self.clear_terminal()
            self._set_terminal_background()

            self.print_header()

            return False

        self.send_message(
            user_input
        )

        return False

    def show_help(self) -> None:
        """
        Show Nrgrd's commands.
        """

        table = Table(
            title=(
                f"[bold {PINK_LIGHT}]"
                "Nrgrd Commands"
                f"[/bold {PINK_LIGHT}]"
            ),
            box=ROUNDED,
            border_style=BORDER,
            header_style=f"bold {PINK}",
            show_lines=False,
            padding=(0, 1),
            collapse_padding=True,
        )

        table.add_column(
            "Command",
            style=GREEN,
            no_wrap=True,
        )

        table.add_column(
            "Description"
        )

        table.add_row(
            "/con",
            (
                "Check the configured API connection."
            ),
        )

        table.add_row(
            "/models",
            (
                "List models available from "
                "the configured API."
            ),
        )

        table.add_row(
            "/models <model>",
            (
                "Select and save a model."
            ),
        )

        table.add_row(
            "/config",
            (
                "Show the current configuration."
            ),
        )

        table.add_row(
            "/config edit",
            (
                "Open the configuration file "
                "in the default editor."
            ),
        )

        table.add_row(
            "/session",
            (
                "Show the active session, its "
                "storage location, and usage."
            ),
        )

        table.add_row(
            "/session clear",
            (
                "Clear the conversation associated "
                "with the current directory."
            ),
        )

        table.add_row(
            "/compact [focus]",
            "Summarize older conversation and keep a recent context tail.",
        )

        table.add_row(
            "/tools",
            "Show the workspace coding tools available to Nrgrd.",
        )

        table.add_row("/mcp", "Show configured MCP servers and discovered tools.")
        table.add_row("/mcp edit", "Show where to edit the Claude-compatible mcpServers file.")
        table.add_row("/mcp reload", "Reconnect to configured MCP servers and refresh tools.")

        table.add_row(
            "/system",
            (
                "Show the current system prompt."
            ),
        )

        table.add_row(
            "/system edit",
            (
                "Open the system prompt in the "
                "default editor."
            ),
        )

        table.add_row(
            "/clear",
            (
                "Clear the terminal."
            ),
        )

        table.add_row(
            "/help",
            (
                "Show this help."
            ),
        )

        table.add_row(
            "/exit",
            (
                "Exit Nrgrd."
            ),
        )

        self.console.print(
            table
        )

    def show_tools(self) -> None:
        """Show the registered tools, their scope, and their permission level."""
        table = Table(
            title=f"[bold {PINK_LIGHT}]Tools[/bold {PINK_LIGHT}]",
            box=ROUNDED,
            border_style=PINK,
            header_style=f"bold {GREEN_VIVID}",
            padding=(0, 1),
            collapse_padding=True,
        )
        table.add_column("Tool", style=PINK_LIGHT, no_wrap=True)
        table.add_column("Description", style=TEXT)
        table.add_column("Permission", style=MUTED, no_wrap=True)
        for name in self.tool_registry.names():
            tool = self.tool_registry.get(name)
            if tool is None:
                continue
            table.add_row(tool.name, tool.description, tool.permission.value)
        self.console.print(table)
        self.console.print(
            f"[{MUTED}]Tools are scoped to the current workspace. "
            f"[bold]ask[/bold]-level tools prompt for approval before running. "
            f"MCP server: [bold {PINK_LIGHT}]nrgrd-mcp --root .[/bold {PINK_LIGHT}].[/]"
        )

    def show_mcp(self) -> None:
        """Show external MCP servers discovered from the user's registry."""
        table = Table(title=f"[bold {PINK_LIGHT}]MCP Servers[/bold {PINK_LIGHT}]", box=ROUNDED, border_style=BORDER)
        table.add_column("Server", style=GREEN)
        table.add_column("Tools / status", style=TEXT)
        servers = sorted({tool.server for tool in self.mcp_client.tools.values()} | set(self.mcp_client.errors))
        if not servers:
            table.add_row("None", "No configured servers. Use /mcp edit, then /mcp reload.")
        for server in servers:
            if server in self.mcp_client.errors:
                table.add_row(server, f"Error: {self.mcp_client.errors[server]}")
            else:
                names = [tool.name for tool in self.mcp_client.tools.values() if tool.server == server]
                table.add_row(server, ", ".join(names) or "No tools")
        self.console.print(table)
        self.console.print(f"[{MUTED}]Configuration: {get_mcp_config_path()}[/]")

    def show_mcp_edit_instructions(self) -> None:
        path = get_mcp_config_path()
        self.console.print(Panel(
            "Add trusted servers using Claude's mcpServers format, then run /mcp reload. "
            "Use ${workspace} or ${workspaceFolder} for Nrgrd's current project.\n\n"
            '{\n  "mcpServers": {\n    "filesystem": {\n      "command": "cmd",\n      "args": ["/c", "npx", "-y", "@modelcontextprotocol/server-filesystem", "${workspace}"]\n    }\n  }\n}',
            title=f"[bold {PINK_LIGHT}]Edit {path}[/bold {PINK_LIGHT}]", border_style=BORDER, box=ROUNDED,
        ))

    def show_connection_information(
        self,
    ) -> None:
        """
        Verify that the configured API is reachable.
        """
        if self.provider is None:
            self.print_missing_api_key()
            return

        spinner = Spinner(
            "dots12",
            text="Connecting…",
            style=GREEN_VIVID,
        )

        try:
            with Live(
                spinner,
                console=self.console,
                refresh_per_second=20,
            ):
                self.provider.list_models()
        except ProviderError as error:
            self.print_error_panel(error.summary, error.detail, error.hint)
            return

        self.console.print(
            f"[{GREEN_VIVID}]● Connected[/]"
        )

    def show_config(self) -> None:
        """
        Show the active configuration without exposing the API key.
        """

        config_path = get_config_path()

        api_key_status = (
            f"Configured (in your {self.credentials.name})"
            if self.api_key.strip()
            else "Not configured"
        )

        content = (
            f"[bold {GREEN}]Model:[/bold {GREEN}]\n"
            f"{self.config.model or 'Not selected'}\n"
            f"[bold {GREEN}]Endpoint:[/bold {GREEN}]\n"
            f"{self.config.base_url or 'Not configured'}\n"
            f"[bold {GREEN}]API key:[/bold {GREEN}]\n"
            f"{api_key_status}\n"
            f"[bold {GREEN}]Config path:[/bold {GREEN}]\n"
            f"{config_path}"
        )

        self.console.print(
            Panel(
                content,
                title=(
                    f"[bold {PINK_LIGHT}]"
                    "Nrgrd Configuration"
                    f"[/bold {PINK_LIGHT}]"
                ),
                border_style=BORDER,
                box=ROUNDED,
                padding=(0, 1),
            )
        )

    def edit_config(self) -> None:
        """
        Reconnect: endpoint, API key, and model, in one guided screen.
        """

        self.connect()

    def list_models(self) -> None:
        """
        Load and display the models returned by the API.
        """

        if self.provider is None:
            self.print_missing_api_key()
            return

        spinner = Spinner(
            "dots12",
            text="Loading available models…",
            style=GREEN_VIVID,
        )

        failure: ProviderError | None = None

        with Live(
            spinner,
            console=self.console,
            refresh_per_second=20,
        ):
            try:
                models = self.provider.list_models()
            except ProviderError as error:
                models = []
                failure = error

        if not models:
            if failure is not None:
                self.print_error_panel(
                    failure.summary, failure.detail, failure.hint
                )
            else:
                self.console.print(f"[{PINK}]No models were returned.[/]")
            return

        table = Table(
            title=f"[bold {GREEN_VIVID}]Available Models[/bold {GREEN_VIVID}]",
            box=ROUNDED,
            border_style=BORDER,
            header_style=f"bold {PINK_LIGHT}",
            padding=(0, 1),
            collapse_padding=True,
        )
        table.add_column("Status", no_wrap=True)
        table.add_column("Model", style=TEXT)

        for model in models:
            is_selected = model == self.config.model
            status = (
                f"[bold {PINK_LIGHT}]● Selected[/bold {PINK_LIGHT}]"
                if is_selected
                else f"[{GREEN_VIVID}]● Available[/]"
            )
            table.add_row(status, model)

        self.console.print(table)
        self.console.print(
            f"[{DIM}]Use /models \"model-name\" to select a model.[/]"
        )

    def select_model(
        self,
        model: str,
    ) -> None:
        """Select and persist a model."""

        if not model:
            self.console.print(
                f"[bold {ERROR}]Please provide a model.[/]"
            )
            return

        self.config.model = model
        save_config(self.config)
        self.console.print(
            f"[{GREEN_VIVID}]● Selected model: [bold]{model}[/bold][/]"
        )

    def show_session_information(
        self,
    ) -> None:
        """
        Show the current session and where it is stored.
        """

        session_path = (
            self.session_manager
            .get_session_path()
        )

        size_bytes = (
            self.session_manager
            .get_size_bytes()
        )

        size_kib = (
            size_bytes / 1024
        )

        content = (
            f"[bold {GREEN}]"
            "Working directory:"
            f"[/bold {GREEN}]\n"
            f"{self.working_directory}\n"
            f"[bold {GREEN}]"
            "Session file:"
            f"[/bold {GREEN}]\n"
            f"{session_path}\n"
            f"[bold {GREEN}]"
            "Stored messages:"
            f"[/bold {GREEN}]\n"
            f"{len(self.session_manager.messages)}"
            f" / 100\n"
            f"[bold {GREEN}]"
            "Session size:"
            f"[/bold {GREEN}]\n"
            f"{size_kib:.2f} KiB"
        )

        self.console.print(
            Panel(
                content,
                title=(
                    f"[bold {PINK_LIGHT}]"
                    "Nrgrd Session"
                    f"[/bold {PINK_LIGHT}]"
                ),
                border_style=BORDER,
                box=ROUNDED,
                padding=(0, 1),
            )
        )

    def clear_session(self) -> None:
        """
        Clear the session associated with the current directory.
        """

        self.session_manager.clear()

        self.console.print(
            f"[{GREEN}]"
            "The session for this directory "
            "was cleared."
            f"[/]"
        )

    def show_system_prompt(
        self,
    ) -> None:
        """
        Show only the active system prompt.
        """

        system_prompt = (
            load_system_prompt()
        )

        self.console.print(
            Panel(
                Markdown(
                    system_prompt
                ),
                title=(
                    f"[bold {GREEN}]"
                    "System Prompt"
                    f"[/bold {GREEN}]"
                ),
                border_style=BORDER,
                box=ROUNDED,
                padding=(0, 1),
            )
        )

    def edit_system_prompt(
        self,
    ) -> None:
        """
        Edit the system prompt directly in the terminal.
        """
        current_prompt = load_system_prompt()
        self.console.print(
            Panel(
                Markdown(current_prompt),
                title=f"[bold {PINK_LIGHT}]Edit System Prompt[/bold {PINK_LIGHT}]",
                border_style=BORDER,
                box=ROUNDED,
                padding=(0, 1),
            )
        )
        self.console.print(
            f"[{MUTED}]Enter replacement lines. Type /save to save or /cancel to discard.[/]"
        )
        lines: list[str] = []
        while True:
            try:
                line = Prompt.ask(
                    f"[bold {PINK}]system>[/bold {PINK}]",
                    console=self.console,
                )
            except (KeyboardInterrupt, EOFError):
                self.console.print(f"[{MUTED}]System prompt unchanged.[/]")
                return
            if line == "/cancel":
                self.console.print(f"[{MUTED}]System prompt unchanged.[/]")
                return
            if line == "/save":
                break
            lines.append(line)

        replacement = "\n".join(lines).strip()
        if not replacement:
            self.console.print(f"[{ERROR}]● System prompt cannot be empty.[/]")
            return
        save_system_prompt(replacement)
        self.console.print(f"[{PINK_LIGHT}]● System prompt saved[/]")

    def print_missing_api_key(
        self,
    ) -> None:
        """
        Display an API key error.
        """

        missing = (
            "an endpoint and an API key"
            if not self.api_key.strip() and not self.config.base_url.strip()
            else "an API key"
            if not self.api_key.strip()
            else "an endpoint"
        )

        self.console.print(
            Panel(
                (
                    f"nrgrd needs {missing} before it can reach a model.\n\n"
                    "A NeuroGrid deployment gives you an endpoint URL, an "
                    "API key, and a model name.\n\n"
                    "Run [bold]/config edit[/bold] to connect."
                ),
                title=f"[bold {ERROR}]Not connected[/bold {ERROR}]",
                border_style=ERROR,
                box=ROUNDED,
                padding=(0, 1),
            )
        )

    def compact_conversation(
        self,
        instructions: str = "",
        automatic: bool = False,
    ) -> bool:
        """Summarize older turns and retain a recent context tail."""
        if self.provider is None or not self.config.model.strip():
            if not automatic:
                self.print_missing_api_key()
            return False

        messages = self.session_manager.get_messages()
        if len(messages) < 3:
            if not automatic:
                self.console.print(f"[{MUTED}]Not enough conversation to compact.[/]")
            return False

        keep_budget = min(
            self.config.compact_keep_recent_tokens,
            max(512, self.config.context_window_tokens // 2),
        )
        tail_tokens = 0
        split_index = len(messages)
        for index in range(len(messages) - 1, -1, -1):
            message_tokens = estimate_text_tokens(messages[index].content) + 4
            if tail_tokens + message_tokens > keep_budget and index < len(messages) - 1:
                split_index = index + 1
                break
            tail_tokens += message_tokens

        # Keep user/assistant turns together when possible.
        if split_index % 2:
            split_index -= 1
        older_messages = messages[:split_index]
        recent_messages = messages[split_index:]
        if not older_messages:
            if not automatic:
                self.console.print(f"[{MUTED}]Conversation is already compact.[/]")
            return False

        transcript = "\n\n".join(
            f"{message.role.upper()}:\n{message.content}"
            for message in older_messages
        )
        focus = (
            f"Focus especially on: {instructions}\n\n"
            if instructions
            else ""
        )
        prompt = (
            "Create a concise, durable conversation summary for a future AI "
            "assistant. Preserve user goals, decisions, constraints, key facts, "
            "open questions, and unfinished work. Do not include chatter or "
            "claim actions that were not completed.\n\n"
            f"{focus}Conversation to summarize:\n{transcript}"
        )
        spinner = Spinner("dots12", text="Compacting conversation…", style=PINK_LIGHT)
        try:
            with Live(spinner, console=self.console, refresh_per_second=20):
                summary = self.provider.complete_chat(
                    model=self.config.model,
                    messages=[
                        {
                            "role": "system",
                            "content": "You create reliable context summaries.",
                        },
                        {"role": "user", "content": prompt},
                    ],
                )
        except ProviderError as error:
            if not automatic:
                self.print_error_panel(error.summary, error.detail, error.hint)
            return False

        if not summary.strip():
            if not automatic:
                self.console.print(f"[{ERROR}]● Compaction returned no summary.[/]")
            return False

        compacted = ChatMessage(
            role="system",
            content=f"Conversation summary:\n{summary.strip()}",
        )
        self.session_manager.archive_messages(messages)
        self.session_manager.replace_messages([compacted, *recent_messages])
        label = "Auto-compacted" if automatic else "Conversation compacted"
        self.console.print(f"[{PINK_LIGHT}]● {label}[/]")
        return True

    def should_auto_compact(self, user_input: str) -> bool:
        """Return whether the next request would exceed the safe token budget."""
        current_tokens = estimate_messages_tokens(self.session_manager.get_messages())
        incoming_tokens = estimate_text_tokens(user_input) + 4
        reserve_tokens = max(1024, self.config.context_window_tokens // 8)
        threshold = self.config.context_window_tokens - reserve_tokens
        return current_tokens + incoming_tokens >= threshold

    def ask_permission(self, name: str, arguments: str) -> str:
        """Prompt the user to approve an ``ask``-level tool call.

        Returns ``"yes"``, ``"no"``, or ``"always"`` for the rest of the
        session, per :class:`~nrgrd.agent.permissions.PermissionManager`.
        """
        try:
            payload = json.loads(arguments or "{}")
        except json.JSONDecodeError:
            payload = {}

        if name == "shell":
            detail = str(payload.get("command", arguments))
        elif isinstance(payload, dict) and "path" in payload:
            detail = str(payload["path"])
        else:
            detail = arguments

        self.console.print(
            Panel(
                detail,
                title=f"[bold {WARNING}]Nrgrd wants to run: {name}[/bold {WARNING}]",
                border_style=WARNING,
                box=ROUNDED,
                padding=(0, 1),
            )
        )

        try:
            choice = Prompt.ask(
                f"[bold {PINK}]Allow?[/bold {PINK}] "
                f"[y] Yes  [n] No  [a] Always allow this tool this session",
                choices=["y", "n", "a"],
                default="n",
                console=self.console,
            )
        except (KeyboardInterrupt, EOFError):
            return "no"

        return {"y": "yes", "n": "no", "a": "always"}[choice]

    def run_coding_agent(self, messages: list[dict[str, Any]]) -> str:
        """Drive the agent runtime, rendering its events as it works."""
        agent = Agent(
            self.provider,
            self.config.model,
            self.tool_registry,
            permissions=self.permissions,
        )

        live: Live | None = None

        def open_thinking_panel() -> Live:
            panel = Panel(
                Group(Spinner("dots12", text="Nrgrd is thinking…", style=PINK_LIGHT)),
                title=f"[bold {GREEN_VIVID}]Nrgrd[/bold {GREEN_VIVID}]",
                border_style=GREEN_VIVID,
                box=ROUNDED,
                padding=(0, 1),
            )
            instance = Live(panel, console=self.console, refresh_per_second=20)
            instance.start()
            return instance

        def close_live() -> None:
            nonlocal live
            if live is not None:
                live.stop()
                live = None

        try:
            for event in agent.run(messages):
                if isinstance(event, AssistantChunk):
                    if live is None:
                        live = open_thinking_panel()
                    live.update(
                        Panel(
                            Markdown(event.text),
                            title=f"[bold {GREEN_VIVID}]Nrgrd[/bold {GREEN_VIVID}]",
                            border_style=GREEN_VIVID,
                            box=ROUNDED,
                            padding=(0, 1),
                        )
                    )
                elif isinstance(event, ToolCallStarted):
                    close_live()
                elif isinstance(event, ToolCallOutput):
                    is_mcp = event.name.startswith("mcp__")
                    self.console.print(
                        Panel(
                            f"[bold {PINK_LIGHT}]{event.name}[/bold {PINK_LIGHT}]\n"
                            f"[{MUTED}]{event.result[:500]}[/]",
                            title=f"[bold {PINK}]{'MCP Tool' if is_mcp else 'Tool'}[/bold {PINK}]",
                            border_style=PINK,
                            box=ROUNDED,
                            padding=(0, 1),
                        )
                    )
                elif isinstance(event, ToolCallDenied):
                    close_live()
                    self.console.print(
                        Panel(
                            f"[{MUTED}]Denied by user; the agent was told and will "
                            "adjust its approach.[/]",
                            title=f"[bold {ERROR}]{event.name} — Permission Denied[/bold {ERROR}]",
                            border_style=ERROR,
                            box=ROUNDED,
                            padding=(0, 1),
                        )
                    )
                elif isinstance(event, AgentFinished):
                    close_live()
                    return event.text
                elif isinstance(event, AgentError):
                    close_live()
                    self.print_error_panel(
                        event.message, event.detail, event.hint
                    )
                    return ""
        finally:
            close_live()

        raise RuntimeError("Agent loop ended without a final response.")

    def send_message(
        self,
        user_input: str,
    ) -> None:
        """
        Send a message and stream the response.
        """

        if self.provider is None:
            self.print_missing_api_key()
            return

        if not self.config.model.strip():
            self.console.print(
                Panel(
                    "Choose a model with /models <model> before sending a message.",
                    title=f"[bold {ERROR}]Model Required[/bold {ERROR}]",
                    border_style=ERROR,
                    box=ROUNDED,
                )
            )
            return

        if self.should_auto_compact(user_input):
            self.compact_conversation(automatic=True)

        self.console.print(
            Panel(
                Markdown(user_input),
                title=f"[bold {ERROR}]User[/bold {ERROR}]",
                border_style=ERROR,
                box=ROUNDED,
                padding=(0, 1),
            )
        )

        system_prompt = (
            load_system_prompt()
        )

        messages: list[
            dict[str, Any]
        ] = [
            {
                "role": "system",
                "content": (
                    system_prompt
                    + "\n\n"
                    "Current working directory:\n"
                    f"{self.working_directory}"
                    + "\n\nYou are a coding assistant. Search and read files before "
                    "editing them. Keep changes scoped to the user's request, report "
                    "what you changed, and never claim a file or command action "
                    "unless a tool confirmed it. Use git_status/git_diff to check "
                    "your work and, when practical, run relevant tests or builds "
                    "with the shell tool to validate a change. Use only the exact "
                    "tool names declared in this request; never infer or invent a "
                    "tool such as delete_file. Some tools require the user's "
                    "explicit approval before they run and may be denied — if one "
                    "is denied, do not retry it; explain the limitation and adjust "
                    "your approach. If the requested operation has no declared "
                    "tool, state that limitation clearly."
                ),
            }
        ]

        messages.extend(
            message.model_dump()
            for message in self.session_manager.get_messages()
        )

        messages.append(
            {
                "role": "user",
                "content": user_input,
            }
        )

        try:
            response_text = self.run_coding_agent(messages)
        except KeyboardInterrupt:
            self.console.print(f"[{PINK}]Generation interrupted; nothing was saved.[/]")
            return
        except Exception as error:
            self.console.print(
                Panel(
                    str(error),
                    title=f"[bold {ERROR}]Request Error[/bold {ERROR}]",
                    border_style=ERROR,
                    box=ROUNDED,
                    padding=(0, 1),
                )
            )
            return

        if response_text.strip():
            self.session_manager.add_message("user", user_input)
            self.session_manager.add_message("assistant", response_text)


def main() -> None:
    application = NrgrdApp()

    application.run()
