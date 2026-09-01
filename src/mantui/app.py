import os
import random
import shutil
from pathlib import Path
from typing import Any

from openai import OpenAI
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

from mantui.config import (
    Config,
    get_config_path,
    load_config,
    save_config,
)
from mantui.context.models import ChatMessage
from mantui.context.tokens import (
    estimate_messages_tokens,
    estimate_text_tokens,
)
from mantui.mcp import MCPClient, get_mcp_config_path
from mantui.sessions import SessionManager
from mantui.system import (
    load_system_prompt,
    save_system_prompt,
)
from mantui.theme.colors import (
    BORDER,
    ERROR,
    GREEN,
    GREEN_BRIGHT,
    GREEN_VIVID,
    MUTED,
    PINK,
    PINK_LIGHT,
    TEXT,
)
from mantui.widgets.logo import create_logo
from mantui.theme.colors import BACKGROUND
from mantui.widgets.random_mantis import (
    MANTIS_ART,
    MANTIS_FACTS,
)
from mantui.workspace import FILE_TOOLS, WorkspaceTools


DIM = MUTED


class MantuiApp:
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

        self.client: OpenAI | None = None

        self.create_client()

    def create_client(self) -> None:
        """
        Create the OpenAI-compatible client using the active config.
        """

        if not self.config.api_key.strip():
            self.client = None
            return

        self.client = OpenAI(
            api_key=self.config.api_key.strip(),
            base_url=self.config.base_url.strip(),
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
        Print the Mantui logo and current directory.
        """

        self.print_header()

        details = Table.grid(padding=(0, 1), collapse_padding=True)
        details.add_column(style=f"bold {PINK_LIGHT}", no_wrap=True)
        details.add_column(style=TEXT)
        details.add_row("Workspace", str(self.working_directory))
        details.add_row("Model", self.config.model or "Not selected")
        details.add_row("Tip", "Type /help to see available commands")
        self.console.print(
            Panel(
                Group(create_logo(), Text(""), Align.center(details)),
                title=f"[bold {GREEN_BRIGHT}]MANTUI[/bold {GREEN_BRIGHT}]",
                subtitle=f"[{MUTED}]interactive AI workspace[/]",
                border_style=BORDER,
                box=ROUNDED,
                padding=(1, 2),
            )
        )

    def print_header(self) -> None:
        """
        Print a compact header after clearing the terminal.
        """

        header = Text()

        header.append(
            "MANTUI",
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
                title=f"[bold {GREEN_BRIGHT}]MANTUI[/bold {GREEN_BRIGHT}]",
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
        prompt = "mantui> "
        if PromptSession is None or WordCompleter is None:
            return Prompt.ask(f"[bold {GREEN_VIVID}]mantui[/bold {GREEN_VIVID}][bold {PINK}]>[/bold {PINK}]").strip()
        commands = [
            "/help", "/con", "/models", "/config", "/config edit", "/session",
            "/session clear", "/compact", "/tools", "/mcp", "/mcp edit",
            "/mcp reload", "/system", "/system edit", "/random", "/clear", "/exit",
        ]
        session = PromptSession(completer=WordCompleter(commands, sentence=True))
        return session.prompt(prompt, complete_while_typing=True).strip()

    def handle_input(
        self,
        user_input: str,
    ) -> bool:
        """
        Handle Mantui commands or send a normal message.
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

        if normalized == "/random":
            self.show_random_mantis()
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
        Show Mantui's commands.
        """

        table = Table(
            title=(
                f"[bold {PINK_LIGHT}]"
                "Mantui Commands"
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
            "Show the workspace coding tools available to Mantui.",
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
            "/random",
            (
                "Show the Mantui mascot and "
                "a random mantis fact."
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
                "Exit Mantui."
            ),
        )

        self.console.print(
            table
        )

    def show_tools(self) -> None:
        """Show the coding tools and their workspace-only scope."""
        table = Table(
            title=f"[bold {PINK_LIGHT}]Workspace Tools[/bold {PINK_LIGHT}]",
            box=ROUNDED,
            border_style=PINK,
            header_style=f"bold {GREEN_VIVID}",
            padding=(0, 1),
            collapse_padding=True,
        )
        table.add_column("Tool", style=PINK_LIGHT, no_wrap=True)
        table.add_column("What Mantui can do", style=TEXT)
        table.add_row("list_files", "Inspect project files and directories")
        table.add_row("read_file", "Read UTF-8 text files")
        table.add_row("write_file", "Create or replace text files")
        table.add_row("edit_file", "Make one precise text replacement")
        self.console.print(table)
        self.console.print(
            f"[{MUTED}]Tools are limited to the current workspace; no shell, network, or delete access. MCP server: [bold {PINK_LIGHT}]mantui-mcp --root .[/bold {PINK_LIGHT}].[/]"
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
            "Use ${workspace} or ${workspaceFolder} for Mantui's current project.\n\n"
            '{\n  "mcpServers": {\n    "filesystem": {\n      "command": "cmd",\n      "args": ["/c", "npx", "-y", "@modelcontextprotocol/server-filesystem", "${workspace}"]\n    }\n  }\n}',
            title=f"[bold {PINK_LIGHT}]Edit {path}[/bold {PINK_LIGHT}]", border_style=BORDER, box=ROUNDED,
        ))

    def show_connection_information(
        self,
    ) -> None:
        """
        Verify that the configured API is reachable.
        """
        if self.client is None:
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
                self.client.models.list()
        except Exception as error:
            self.console.print(
                f"[{ERROR}]● Connection failed: {error}[/]"
            )
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
            "Configured"
            if self.config.api_key.strip()
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
                    "Mantui Configuration"
                    f"[/bold {PINK_LIGHT}]"
                ),
                border_style=BORDER,
                box=ROUNDED,
                padding=(0, 1),
            )
        )

    def edit_config(self) -> None:
        """
        Edit configuration directly in the terminal.
        """
        self.console.print(
            Panel(
                f"[{MUTED}]Press Enter to keep the current value. "
                "Leave the API key blank to keep it unchanged.[/]",
                title=f"[bold {GREEN_VIVID}]Edit Configuration[/bold {GREEN_VIVID}]",
                border_style=BORDER,
                box=ROUNDED,
                padding=(0, 1),
            )
        )

        try:
            api_key = Prompt.ask(
                f"[bold {PINK}]API key[/bold {PINK}]",
                password=True,
                default="",
                console=self.console,
            ).strip()
            base_url = Prompt.ask(
                f"[bold {PINK}]Endpoint[/bold {PINK}]",
                default=self.config.base_url,
                console=self.console,
            ).strip()
            model = Prompt.ask(
                f"[bold {PINK}]Model[/bold {PINK}]",
                default=self.config.model,
                console=self.console,
            ).strip()
        except (KeyboardInterrupt, EOFError):
            self.console.print(f"[{MUTED}]Configuration unchanged.[/]")
            return

        if api_key:
            self.config.api_key = api_key
        self.config.base_url = base_url
        self.config.model = model
        save_config(self.config)
        self.create_client()

        self.console.print(
            f"[{GREEN_VIVID}]● Configuration saved[/]"
        )

    def list_models(self) -> None:
        """
        Load and display the models returned by the API.
        """

        if self.client is None:
            self.print_missing_api_key()
            return

        spinner = Spinner(
            "dots12",
            text="Loading available models…",
            style=GREEN_VIVID,
        )

        error_message: str | None = None

        with Live(
            spinner,
            console=self.console,
            refresh_per_second=20,
        ):
            try:
                response = self.client.models.list()
                models = sorted(item.id for item in response.data)
            except Exception as error:
                models = []
                error_message = str(error)

        if not models:
            if error_message:
                self.console.print(
                    Panel(
                        error_message,
                        title=f"[bold {ERROR}]Could not load models[/bold {ERROR}]",
                        border_style=ERROR,
                        box=ROUNDED,
                        padding=(0, 1),
                    )
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
                    "Mantui Session"
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

    def show_random_mantis(
        self,
    ) -> None:
        """
        Show the mascot and a random mantis fact.
        """

        title, fact = random.choice(
            MANTIS_FACTS
        )

        art = Text(
            MANTIS_ART,
            style=f"bold {GREEN}",
        )

        terminal_width = (
            shutil.get_terminal_size(
                fallback=(120, 40)
            )
            .columns
        )

        fact_panel = Panel(
            (
                f"[bold {PINK}]"
                f"{title}"
                f"[/]\n\n"
                f"{fact}"
            ),
            title=(
                f"[bold {GREEN}]"
                "Mantis fact"
                f"[/bold {GREEN}]"
            ),
            border_style=BORDER,
            box=ROUNDED,
            width=42,
            padding=(0, 1),
        )

        self.console.print()

        if terminal_width >= 120:
            layout = Table.grid(
                padding=(0, 1),
                collapse_padding=True,
            )

            layout.add_column(
                justify="left"
            )

            layout.add_column(
                justify="left"
            )

            layout.add_row(
                art,
                fact_panel,
            )

            self.console.print(layout)

        else:
            self.console.print(art)

            self.console.print()

            self.console.print(
                fact_panel
            )

        self.console.print()

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

        self.console.print(
            Panel(
                (
                    "No API key is configured.\n\n"
                    "Use [bold]/config edit[/bold] "
                    "to open the configuration file."
                ),
                title=(
                    "[bold red]"
                    "API Key Required"
                    "[/bold red]"
                ),
                border_style=ERROR,
            )
        )

    def compact_conversation(
        self,
        instructions: str = "",
        automatic: bool = False,
    ) -> bool:
        """Summarize older turns and retain a recent context tail."""
        if self.client is None or not self.config.model.strip():
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
                response = self.client.chat.completions.create(
                    model=self.config.model,
                    messages=[
                        {
                            "role": "system",
                            "content": "You create reliable context summaries.",
                        },
                        {"role": "user", "content": prompt},
                    ],
                    stream=False,
                )
            summary = response.choices[0].message.content or ""
        except Exception as error:
            if not automatic:
                self.console.print(f"[{ERROR}]● Compaction failed: {error}[/]")
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

    def run_coding_agent(self, messages: list[dict[str, Any]]) -> str:
        """Stream tokens while processing a bounded, visible tool loop."""
        mcp_client = getattr(self, "mcp_client", None)
        mcp_tools = mcp_client.openai_tools() if mcp_client else []
        for _ in range(12):
            response_text = ""
            tool_calls: dict[int, dict[str, str]] = {}
            panel = Panel(
                Group(Spinner("dots12", text="Mantui is thinking…", style=PINK_LIGHT)),
                title=f"[bold {GREEN_VIVID}]Mantui[/bold {GREEN_VIVID}]",
                border_style=GREEN_VIVID,
                box=ROUNDED,
                padding=(0, 1),
            )
            with Live(panel, console=self.console, refresh_per_second=20) as live:
                stream = self.client.chat.completions.create(
                    model=self.config.model,
                    messages=messages,
                    tools=[*FILE_TOOLS, *mcp_tools],
                    tool_choice="auto",
                    stream=True,
                )
                for chunk in stream:
                    if not chunk.choices:
                        continue
                    delta = chunk.choices[0].delta
                    if delta.content:
                        response_text += delta.content
                        live.update(
                            Panel(
                                Markdown(response_text),
                                title=f"[bold {GREEN_VIVID}]Mantui[/bold {GREEN_VIVID}]",
                                border_style=GREEN_VIVID,
                                box=ROUNDED,
                                padding=(0, 1),
                            )
                        )
                    for call in delta.tool_calls or []:
                        item = tool_calls.setdefault(
                            call.index,
                            {"id": "", "name": "", "arguments": ""},
                        )
                        if call.id:
                            item["id"] = call.id
                        if call.function and call.function.name:
                            item["name"] += call.function.name
                        if call.function and call.function.arguments:
                            item["arguments"] += call.function.arguments

            if not tool_calls:
                return response_text

            calls = list(tool_calls.values())
            messages.append(
                {
                    "role": "assistant",
                    "content": response_text or None,
                    "tool_calls": [
                        {
                            "id": call["id"],
                            "type": "function",
                            "function": {
                                "name": call["name"],
                                "arguments": call["arguments"],
                            },
                        }
                        for call in calls
                    ],
                }
            )
            for tool_call in calls:
                name = tool_call["name"]
                mcp_client = getattr(self, "mcp_client", None)
                result = (
                    mcp_client.execute(name, tool_call["arguments"])
                    if name.startswith("mcp__") and mcp_client is not None
                    else self.workspace_tools.execute(name, tool_call["arguments"])
                )
                self.console.print(
                    Panel(
                        f"[bold {PINK_LIGHT}]{name}[/bold {PINK_LIGHT}]\n"
                        f"[{MUTED}]{result[:500]}[/]",
                        title=f"[bold {PINK}]{'MCP Tool' if name.startswith('mcp__') else 'Workspace Tool'}[/bold {PINK}]",
                        border_style=PINK,
                        box=ROUNDED,
                        padding=(0, 1),
                    )
                )
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call["id"],
                        "content": result,
                    }
                )

        raise RuntimeError("Tool call limit reached; please continue with a narrower request.")

    def send_message(
        self,
        user_input: str,
    ) -> None:
        """
        Send a message and stream the response.
        """

        if self.client is None:
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
                    + "\n\nYou are a coding assistant. Use the workspace tools to "
                    "inspect files before editing them. Keep changes scoped to the "
                    "user's request, report what you changed, and never claim a file "
                    "action unless a tool completed it. Use only the exact tool names "
                    "declared in this request; never infer or invent a tool such as "
                    "delete_file. If the requested operation has no declared tool, "
                    "state that limitation clearly."
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
    application = MantuiApp()

    application.run()
