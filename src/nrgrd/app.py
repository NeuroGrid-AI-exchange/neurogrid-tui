import argparse
import itertools
import json
import os
import shlex
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote

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
from rich.style import Style
from rich.text import Text

try:
    from prompt_toolkit import PromptSession
    from prompt_toolkit.completion import WordCompleter
    from prompt_toolkit.application import get_app, run_in_terminal
    from prompt_toolkit.formatted_text import ANSI
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.keys import Keys
    from prompt_toolkit.styles import Style as PromptStyle
except ImportError:  # Keep the CLI usable until optional UI dependencies are installed.
    PromptSession = None
    WordCompleter = None
    ANSI = None

from nrgrd import __version__
from nrgrd.agent import (
    Agent,
    AgentCancelled,
    AgentError,
    AgentFinished,
    AssistantChunk,
    PermissionManager,
    PermissionRequested,
    ToolCallDenied,
    ToolCallOutput,
    ToolCallStarted,
)
from nrgrd.api import ModelProvider, OpenAICompatibleProvider, ProviderError
from nrgrd.attachments import (
    Attachment,
    AttachmentError,
    ClipboardUnavailable,
    build_user_content,
    clipboard_image,
    clipboard_text,
    display_name,
    image_attachment,
    load_attachment,
    pasted_paths,
)
from nrgrd.browser import open_url
from nrgrd.commands import COMMANDS, describe
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
    estimate_request_tokens,
    estimate_text_tokens,
)
from nrgrd.mcp import MCPClient, get_mcp_config_path
from nrgrd.screens import run_connect_screen
from nrgrd.sessions import SessionManager
from nrgrd.sessions.graph import ConversationGraph
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
from nrgrd.updates import (
    PYPI_PAGE_URL,
    cached_latest_version,
    fetch_latest_version,
    is_newer,
    update_check_disabled,
    upgrade_command,
)
from nrgrd.widgets.logo import create_logo, logo_frames
from nrgrd.widgets.graph_view import render_graph
from nrgrd.widgets.stream import StreamTail
from nrgrd.theme.colors import BACKGROUND
from nrgrd.workspace import WorkspaceTools, discover


DIM = MUTED

# Seconds between startup logo frames; the whole animation is ~1.4s.
LOGO_FRAME_SECONDS = 0.08

# Width of the context bar's meter, in terminal cells. It shrinks on narrow
# terminals so the bar stays on one line.
CONTEXT_BAR_CELLS = 24
CONTEXT_BAR_MIN_CELLS = 6

# Instructions sent after the system prompt and workspace summary on every
# request.
CODING_INSTRUCTIONS = (
    "You are a coding assistant. Search and read files before "
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
)


# /goal: the lines the agent ends a reply with to say it's done or can't go
# on alone. There is no round limit; Ctrl+C stops it.
GOAL_DONE = "GOAL ACHIEVED"
GOAL_BLOCKED = "GOAL BLOCKED"
GOAL_START = (
    "Goal: {goal}\n\n"
    "Work on this until it is fully achieved. After each reply you'll be asked "
    "to continue, so keep going step by step rather than stopping to ask, unless "
    "you truly need the user. Verify the result — run the tests or the build "
    "when practical. When the goal is achieved and verified, end your reply "
    f"with a final line that says exactly {GOAL_DONE}. If it can't be achieved "
    "without the user (missing information, a denied permission, something "
    f"outside the workspace), end with a final line `{GOAL_BLOCKED}: <reason>`."
)
GOAL_CONTINUE = (
    "Continue working toward the goal: {goal}\n\n"
    "Pick up where you left off. End with "
    f"{GOAL_DONE} once it's achieved and verified, or `{GOAL_BLOCKED}: <reason>` "
    "if you can't go on without the user."
)

# /graph draws the most recent turns.
GRAPH_MAX_TURNS = 30


def goal_verdict(reply: str) -> tuple[str, str]:
    """("done" | "blocked" | "continue", reason) from the end of a /goal reply."""
    for line in reversed(reply.strip().splitlines()):
        line = line.strip().strip("*`_#>- ").strip()
        if not line:
            continue
        upper = line.upper()
        if upper.startswith(GOAL_DONE):
            return "done", ""
        if upper.startswith(GOAL_BLOCKED):
            return "blocked", line[len(GOAL_BLOCKED):].lstrip(" :—-").strip()
        return "continue", ""
    return "continue", ""


# NeuroChat, the browser chat app. /neurochat opens it on this connection.
NEUROCHAT_URL = "https://chat.neurogrid.cc/"


def neurochat_link(base_url: str, api_key: str) -> str:
    """A NeuroChat link that connects to this endpoint with this key.

    The same format NeuroChat's own share links use (lib/connectionLink.ts):
    details go in the #fragment, which browsers never send to the server
    hosting NeuroChat, and NeuroChat strips them from the address bar as
    soon as it reads them.
    """

    def encode(value: str) -> str:
        # Keep ':' and '/' readable, as NeuroChat does; escape the rest
        # (a '+' or '&' in a key would otherwise break the link).
        return quote(value.strip(), safe=":/")

    parts = [f"endpoint={encode(base_url)}"]
    if api_key.strip():
        parts.append(f"token={encode(api_key)}")
    return f"{NEUROCHAT_URL}#{'&'.join(parts)}"


def format_tokens(count: int) -> str:
    """12345 -> "12.3k", 131072 -> "131k", 950 -> "950"."""
    if count >= 100_000:
        return f"{count / 1000:.0f}k"
    if count >= 1000:
        return f"{count / 1000:.1f}k"
    return str(count)


class NrgrdApp:
    def __init__(self) -> None:
        self.console = Console()

        self.working_directory = Path.cwd().resolve()

        self.config: Config = load_config()

        self.session_manager = SessionManager(
            self.working_directory
        )
        self.workspace = discover(self.working_directory)
        self.workspace_tools = WorkspaceTools(self.working_directory)
        self.mcp_client = MCPClient(self.working_directory)
        self.mcp_client.reload()

        self.tool_registry = build_default_registry(self.workspace_tools)
        register_mcp_tools(self.tool_registry, self.mcp_client)
        # Set by CLI mode; approves permission-gated tools without asking.
        self.approve_all = False
        # How the last turn ended: "finished", "cancelled" or "error".
        self.last_outcome = "finished"
        self._prompt_session: Any = None
        # Files waiting to go with the next message (/attach, paste, Ctrl+V).
        self.pending_attachments: list[Attachment] = []
        # The conversation graph and turn being recorded while a reply runs.
        self._graph_turn: tuple[ConversationGraph, str] | None = None
        # Set by the background PyPI check when a newer release exists.
        self.update_available: str | None = None
        self._update_notice_shown = False
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

        if self.provider is not None and self.config.model.strip():
            used = self.context_breakdown()["total"]
            window, _ = self.context_window()
            header.append("  •  ", style=DIM)
            header.append("Context: ", style=f"bold {PINK}")
            header.append(
                f"≈{format_tokens(used)} / {format_tokens(window)}",
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

    def run_once(self, prompt: str, approve_all: bool = False) -> int:
        """Answer one prompt without the TUI, then exit.

        Shares the whole runtime with interactive mode — same agent, tools,
        permissions and session — so scripts and CI behave like the TUI.
        Returns a process exit code.
        """
        self.approve_all = approve_all

        if self.provider is None:
            self.print_missing_api_key()
            return 1

        if not self.config.model.strip():
            self.console.print(
                f"[{ERROR}]● No model configured. Use --model or /config edit.[/]"
            )
            return 1

        self.send_message(prompt)
        # 130 is the conventional status for a run stopped by Ctrl+C.
        return {"finished": 0, "cancelled": 130}.get(self.last_outcome, 1)

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

        self.start_update_check()

        while True:
            self.show_update_notice()
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
        """Read input with a slash-command dropdown when prompt-toolkit is present.

        The context bar sits on the line above the input, so how full the
        context is stays in view while typing the next message.
        """
        bar = self.context_bar() if self.provider is not None and self.config.model.strip() else None
        if PromptSession is None or WordCompleter is None or ANSI is None:
            if bar is not None:
                self.console.print(bar)
            return Prompt.ask(f"[bold {GREEN_VIVID}]nrgrd[/bold {GREEN_VIVID}][bold {PINK}]>[/bold {PINK}]").strip()
        prompt: Any = "nrgrd> "
        if bar is not None:
            with self.console.capture() as captured:
                self.console.print(bar)
            prompt = ANSI(captured.get() + "nrgrd> ")
        if self._prompt_session is None:
            # Created once and reused: a fresh session per prompt would
            # start with empty history, so up-arrow would recall nothing.
            self._prompt_session = self.create_prompt_session()
        return self._prompt_session.prompt(prompt, complete_while_typing=True).strip()

    def create_prompt_session(self) -> Any:
        """The input line: command menu, description bar, and paste handling."""
        by_insert = {command.insert: command for command in COMMANDS}
        completer = WordCompleter(
            [command.insert for command in COMMANDS],
            display_dict={command.insert: command.usage for command in COMMANDS},
            sentence=True,
        )

        def toolbar() -> list[tuple[str, str]]:
            # What the highlighted command does, or the one being typed.
            # With the menu open and nothing highlighted yet, the first
            # entry: it's the one Tab or ↓ would pick.
            buffer = get_app().current_buffer
            state = buffer.complete_state
            current = None
            if state:
                current = state.current_completion or (state.completions[0] if state.completions else None)
            command = by_insert.get(current.text) if current else describe(buffer.text)
            parts: list[tuple[str, str]] = []
            if command:
                parts += [("class:toolbar.command", f" {command.usage} "), ("", f" {command.description}")]
            else:
                parts.append(("class:toolbar.hint", " / for commands · Ctrl+V pastes an image · /attach adds files"))
            if self.pending_attachments:
                names = ", ".join(item.name for item in self.pending_attachments)
                parts.append(("class:toolbar.files", f"   📎 {names}"))
            return parts

        bindings = KeyBindings()

        @bindings.add("c-v")
        def _paste(event: Any) -> None:
            self.paste_into(event.current_buffer)

        @bindings.add(Keys.BracketedPaste)
        def _paste_or_drop(event: Any) -> None:
            self.paste_text_into(event.current_buffer, event.data)

        style = PromptStyle.from_dict(
            {
                "bottom-toolbar": f"noreverse bg:default {MUTED}",
                "bottom-toolbar.text": f"noreverse bg:default {MUTED}",
                "toolbar.command": f"bold {GREEN_VIVID}",
                "toolbar.hint": MUTED,
                "toolbar.files": GREEN_VIVID,
            }
        )
        return PromptSession(
            completer=completer,
            bottom_toolbar=toolbar,
            key_bindings=bindings,
            style=style,
        )

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

        if normalized == "/permissions":
            self.show_permissions()
            return False

        if normalized == "/permissions reset":
            self.permissions.revoke_session_grants()
            self.console.print(
                f"[{GREEN_VIVID}]● Session approvals revoked; "
                f"gated tools will ask again.[/]"
            )
            return False

        if normalized == "/diff":
            self.show_diff()
            return False

        if normalized == "/context":
            self.show_context()
            return False

        if normalized == "/neurochat":
            self.open_neurochat()
            return False

        if normalized == "/goal" or normalized.startswith("/goal "):
            self.run_goal(command[len("/goal"):])
            return False

        if normalized == "/attach":
            self.show_attachments()
            return False

        if normalized == "/attach clear":
            self.pending_attachments.clear()
            self.console.print(f"[{MUTED}]Attachments cleared.[/]")
            return False

        if normalized.startswith("/attach "):
            self.attach_paths(command[len("/attach "):])
            return False

        if normalized == "/paste":
            self.attach_clipboard_image()
            return False

        if normalized == "/graph":
            self.show_graph()
            return False

        if normalized == "/update":
            self.run_update()
            return False

        if normalized in {"/session list", "/sessions"}:
            self.show_sessions()
            return False

        for verb, action in (
            ("/session new ", self.new_session),
            ("/session resume ", self.resume_session),
            ("/session rename ", self.rename_session),
            ("/session delete ", self.delete_session),
        ):
            if normalized.startswith(verb):
                action(command[len(verb):].strip().strip("\"'"))
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

        for entry in COMMANDS:
            # Text, not markup: "[focus]" in a usage would be read as a style.
            table.add_row(Text(entry.usage), Text(entry.description))

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

    def show_permissions(self) -> None:
        """Show how each tool is gated, and what was approved this session."""
        table = Table(
            title=f"[bold {PINK_LIGHT}]Permissions[/bold {PINK_LIGHT}]",
            box=ROUNDED,
            border_style=BORDER,
            header_style=f"bold {PINK}",
            padding=(0, 1),
        )
        table.add_column("Tool", style=PINK_LIGHT, no_wrap=True)
        table.add_column("Policy", style=TEXT, no_wrap=True)
        table.add_column("This session", style=MUTED)

        grants = set(self.permissions.session_grants)
        for name in self.tool_registry.names():
            tool = self.tool_registry.get(name)
            if tool is None:
                continue
            table.add_row(
                tool.name,
                tool.permission.value,
                "always allowed" if tool.name in grants else "",
            )
        self.console.print(table)
        self.console.print(
            f"[{MUTED}]allow = runs freely · ask = prompts first. "
            f"/permissions reset clears this session's approvals.[/]"
        )

    def show_diff(self) -> None:
        """Show what has changed in the working tree."""
        diff = self.tool_registry.execute("git_diff", "{}")
        self.console.print(
            Panel(
                diff,
                title=f"[bold {GREEN_BRIGHT}]Working tree diff[/bold {GREEN_BRIGHT}]",
                border_style=BORDER,
                box=ROUNDED,
                padding=(0, 1),
            )
        )

    def system_message(self) -> dict[str, Any]:
        """The system message every request starts with."""
        return {
            "role": "system",
            "content": (
                load_system_prompt()
                + "\n\n"
                + self.workspace.summary()
                + "\n\n"
                + CODING_INSTRUCTIONS
            ),
        }

    def build_request_messages(self, user_input: str | None = None) -> list[dict[str, Any]]:
        """The messages a chat request sends: system, history, then the new input."""
        messages = [self.system_message()]
        messages.extend(
            message.model_dump()
            for message in self.session_manager.get_messages()
        )
        if user_input is not None:
            messages.append({"role": "user", "content": user_input})
        return messages

    def context_window(self) -> tuple[int, bool]:
        """The model's context window, and whether the endpoint reported it.

        The endpoint's own figure wins; the configured value is only the
        fallback for servers that don't publish one.
        """
        if self.provider is not None and self.config.model.strip():
            reported = self.provider.context_window(self.config.model)
            if reported:
                return reported, True
        return self.config.context_window_tokens, False

    def context_breakdown(self) -> dict[str, int]:
        """Estimated tokens the next request uses, by where they come from.

        Counts what is actually sent — system prompt, tool definitions and
        the conversation — not just the saved messages.
        """
        system = estimate_request_tokens([self.system_message()])
        tools = estimate_request_tokens([], self.tool_registry.schemas())
        conversation = estimate_request_tokens(
            [message.model_dump() for message in self.session_manager.get_messages()]
        )
        return {
            "system": system,
            "tools": tools,
            "conversation": conversation,
            "total": system + tools + conversation,
        }

    def compact_threshold(self, window: int) -> int:
        """Tokens above which the conversation is compacted automatically.

        The rest of the window is left for the reply.
        """
        return window - max(1024, window // 8)

    def context_bar(self) -> Text:
        """One line: a meter of the context used, then the numbers."""
        used = self.context_breakdown()["total"]
        window, reported = self.context_window()
        ratio = min(1.0, used / window) if window else 0.0
        color = ERROR if ratio >= 0.9 else WARNING if ratio >= 0.75 else GREEN_VIVID

        numbers = Text()
        numbers.append(f" ≈{format_tokens(used)} / {format_tokens(window)}", style=TEXT)
        numbers.append(f" · {ratio * 100:.0f}%", style=color)
        if not reported:
            numbers.append(" · window from config", style=MUTED)

        label = "context "
        cells = min(
            CONTEXT_BAR_CELLS,
            max(CONTEXT_BAR_MIN_CELLS, self.console.width - len(label) - numbers.cell_len - 1),
        )
        filled = max(1, round(ratio * cells)) if used else 0

        bar = Text()
        bar.append(label, style=MUTED)
        bar.append("━" * filled, style=color)
        bar.append("─" * (cells - filled), style=BORDER)
        bar.append_text(numbers)
        return bar

    def show_context(self) -> None:
        """Show how much of the context window the next request uses."""
        parts = self.context_breakdown()
        window, reported = self.context_window()
        messages = self.session_manager.get_messages()
        tool_count = len(self.tool_registry.schemas())

        content = Text()
        content.append_text(self.context_bar())
        content.append("\n\n")
        rows = [
            ("System prompt", parts["system"]),
            (f"Tool definitions ({tool_count})", parts["tools"]),
            (f"Conversation ({len(messages)} messages)", parts["conversation"]),
        ]
        for label, tokens in rows:
            content.append(f"{label:<28}", style=f"bold {GREEN}")
            content.append(f"{tokens:>9,}\n", style=TEXT)
        content.append(f"{'Next request':<28}", style=f"bold {PINK_LIGHT}")
        content.append(f"{parts['total']:>9,}\n", style=f"bold {TEXT}")
        content.append(f"{'Context window':<28}", style=f"bold {GREEN}")
        content.append(f"{window:>9,}", style=TEXT)
        content.append(
            "  reported by the endpoint" if reported else "  from config (endpoint doesn't say)",
            style=MUTED,
        )
        content.append(f"\n{'Auto-compacts above':<28}", style=f"bold {GREEN}")
        content.append(f"{self.compact_threshold(window):>9,}", style=TEXT)

        self.console.print(
            Panel(
                content,
                title=f"[bold {PINK_LIGHT}]Context · {self.session_manager.name}[/bold {PINK_LIGHT}]",
                border_style=BORDER,
                box=ROUNDED,
                padding=(0, 1),
            )
        )
        self.console.print(
            f"[{MUTED}]Estimates, not billing: tokens are counted locally at about "
            f"four characters each. /compact to summarise now.[/]"
        )

    def show_sessions(self) -> None:
        """List every saved session for this workspace."""
        sessions = self.session_manager.list_sessions()
        table = Table(
            title=f"[bold {PINK_LIGHT}]Sessions[/bold {PINK_LIGHT}]",
            box=ROUNDED,
            border_style=BORDER,
            header_style=f"bold {PINK}",
            padding=(0, 1),
        )
        table.add_column("", style=GREEN_VIVID, no_wrap=True)
        table.add_column("Session", style=TEXT)
        table.add_column("Messages", justify="right", style=MUTED)
        table.add_column("Updated", style=MUTED)

        if not sessions:
            table.add_row("", "No saved sessions yet", "", "")
        for session in sessions:
            active = session.name == self.session_manager.name
            table.add_row(
                "●" if active else "",
                session.name,
                str(session.messages),
                session.updated_at or "—",
            )
        self.console.print(table)
        self.console.print(
            f"[{MUTED}]/session new <name>, /session resume <name>, "
            f"/session rename <name>, /session delete <name>[/]"
        )

    def new_session(self, name: str) -> None:
        if not name:
            self.console.print(f"[{ERROR}]● Give the session a name.[/]")
            return
        self.session_manager.start(name)
        self.console.print(
            f"[{GREEN_VIVID}]● Started session[/] [bold {TEXT}]{name}[/]"
        )
        self.print_header()

    def resume_session(self, name: str) -> None:
        if not name:
            self.console.print(f"[{ERROR}]● Name the session to resume.[/]")
            return
        known = {session.name for session in self.session_manager.list_sessions()}
        if name not in known:
            self.console.print(
                f"[{ERROR}]● No session called[/] [bold]{name}[/]. "
                f"[{MUTED}]Use /session list to see them.[/]"
            )
            return
        self.session_manager.switch(name)
        self.console.print(
            f"[{GREEN_VIVID}]● Resumed[/] [bold {TEXT}]{name}[/] "
            f"[{MUTED}]({len(self.session_manager.get_messages())} messages)[/]"
        )
        self.print_header()

    def rename_session(self, name: str) -> None:
        if not name:
            self.console.print(f"[{ERROR}]● Give the session a new name.[/]")
            return
        previous = self.session_manager.name
        if not self.session_manager.rename(name):
            self.console.print(
                f"[{ERROR}]● A session called[/] [bold]{name}[/] "
                f"[{ERROR}]already exists.[/]"
            )
            return
        self.console.print(
            f"[{GREEN_VIVID}]● Renamed[/] [{MUTED}]{previous}[/] → "
            f"[bold {TEXT}]{name}[/]"
        )

    def delete_session(self, name: str) -> None:
        if not name:
            self.console.print(f"[{ERROR}]● Name the session to delete.[/]")
            return
        if not self.session_manager.delete(name):
            self.console.print(f"[{ERROR}]● No session called[/] [bold]{name}[/]")
            return
        self.console.print(
            f"[{GREEN_VIVID}]● Deleted[/] [{MUTED}]{name}[/]. "
            f"[{MUTED}]Now on {self.session_manager.name}.[/]"
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

    def open_neurochat(self) -> None:
        """Open NeuroChat in the default browser, connected like nrgrd is."""
        if not self.config.base_url.strip() or not self.api_key.strip():
            self.print_missing_api_key()
            return

        link = neurochat_link(self.config.base_url, self.api_key)
        # A clickable label rather than the raw URL: the link carries the
        # API key, and this way it never lands in the scrollback.
        clickable = Text(
            "Open NeuroChat ↗",
            style=Style(color=GREEN_VIVID, bold=True, underline=True, link=link),
        )

        if open_url(link):
            self.console.print(
                Text.assemble(
                    ("● Opened NeuroChat in your browser on this connection. ", GREEN_VIVID),
                    ("It starts a new chat; this conversation stays here.", MUTED),
                )
            )
            self.console.print(Text.assemble(("  ", ""), clickable))
            return

        # No browser here (an SSH session, a headless box): hand over the
        # link instead. It carries the API key, so say so.
        self.console.print(
            Panel(
                Group(
                    clickable,
                    Text(""),
                    Text(link, style=TEXT),
                    Text(""),
                    Text(
                        "This link contains your API key. Open it yourself and don't share it.",
                        style=WARNING,
                    ),
                ),
                title=f"[bold {PINK_LIGHT}]Couldn't open a browser[/bold {PINK_LIGHT}]",
                border_style=BORDER,
                box=ROUNDED,
                padding=(0, 1),
            )
        )

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

        window, _ = self.context_window()
        keep_budget = min(
            self.config.compact_keep_recent_tokens,
            max(512, window // 2),
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

    def should_auto_compact(self, incoming_tokens: int) -> bool:
        """Return whether the next request would exceed the safe token budget."""
        current_tokens = self.context_breakdown()["total"]
        window, _ = self.context_window()
        return current_tokens + incoming_tokens >= self.compact_threshold(window)

    def ask_permission(self, name: str, arguments: str) -> str:
        """Prompt the user to approve an ``ask``-level tool call.

        Returns ``"yes"``, ``"no"``, or ``"always"`` for the rest of the
        session, per :class:`~nrgrd.agent.permissions.PermissionManager`.
        """
        if self.approve_all:
            return "always"

        try:
            payload = json.loads(arguments or "{}")
        except json.JSONDecodeError:
            payload = {}
        if not isinstance(payload, dict):
            # The model decides the arguments; a list or bare string here
            # must fall back to showing them raw, not crash the prompt.
            payload = {}

        if name == "shell":
            detail = str(payload.get("command", arguments))
        elif "path" in payload:
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

        if not self.console.is_terminal:
            self.console.print(
                f"[{MUTED}]No terminal to ask on; denying. "
                f"Re-run with --yes to approve automatically.[/]"
            )
            return "no"

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
        # The whole reply so far. The Live display only shows its newest
        # lines (see StreamTail); this is what gets printed once it stops.
        reply: Panel | None = None

        def reply_panel(text: str) -> Panel:
            return Panel(
                Markdown(text),
                title=f"[bold {GREEN_VIVID}]Nrgrd[/bold {GREEN_VIVID}]",
                border_style=GREEN_VIVID,
                box=ROUNDED,
                padding=(0, 1),
            )

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
            nonlocal live, reply
            if live is not None:
                if reply is not None:
                    # Stopping redraws once, uncropped: hand it the whole
                    # reply so the scrollback keeps every line of it.
                    live.update(reply, refresh=False)
                live.stop()
                live = None
            reply = None

        try:
            for event in agent.run(messages):
                if isinstance(event, AssistantChunk):
                    if live is None:
                        live = open_thinking_panel()
                    reply = reply_panel(event.text)
                    # Only the newest lines, so a reply taller than the
                    # screen keeps scrolling instead of freezing.
                    live.update(StreamTail(reply))
                elif isinstance(event, (PermissionRequested, ToolCallStarted)):
                    # A running Live display redraws over anything printed
                    # beneath it, including the permission prompt.
                    close_live()
                    if isinstance(event, ToolCallStarted):
                        self._record_tool(event.name, event.arguments, "ran")
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
                    self._record_tool(event.name, event.arguments, "denied")
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
                elif isinstance(event, AgentCancelled):
                    close_live()
                    self.last_outcome = "cancelled"
                    self.console.print(
                        f"[{WARNING}]● Interrupted.[/] "
                        f"[{MUTED}]Any partial reply above was kept.[/]"
                    )
                    return event.text
                elif isinstance(event, AgentFinished):
                    close_live()
                    self.last_outcome = "finished"
                    return event.text
                elif isinstance(event, AgentError):
                    close_live()
                    self.last_outcome = "limit" if event.limit_reached else "error"
                    self.print_error_panel(
                        event.message, event.detail, event.hint
                    )
                    return ""
        finally:
            close_live()

        raise RuntimeError("Agent loop ended without a final response.")

    def ready_to_send(self) -> bool:
        """Whether a model can be reached; explains what's missing if not."""
        if self.provider is None:
            self.print_missing_api_key()
            return False

        if not self.config.model.strip():
            self.console.print(
                Panel(
                    "Choose a model with /models <model> before sending a message.",
                    title=f"[bold {ERROR}]Model Required[/bold {ERROR}]",
                    border_style=ERROR,
                    box=ROUNDED,
                )
            )
            return False
        return True

    def send_message(
        self,
        user_input: str,
        echo: bool = True,
        label: str | None = None,
    ) -> str:
        """
        Send a message and stream the response.

        Files waiting in /attach go with it. ``echo`` shows the message in a
        User panel; ``label`` names the turn in the conversation graph
        (/goal sends its own wording but files the turn under the goal).
        Returns the reply, empty when there is none.
        """

        # Pessimistic until the agent reports otherwise: every early return
        # below is a failure as far as a script calling nrgrd is concerned.
        self.last_outcome = "error"

        if not self.ready_to_send():
            return ""

        attachments = list(self.pending_attachments)
        content, saved_text = build_user_content(user_input, attachments)

        incoming = estimate_request_tokens([{"role": "user", "content": content}])
        if self.should_auto_compact(incoming):
            self.compact_conversation(automatic=True)

        if echo:
            body: Any = Markdown(user_input)
            if attachments:
                body = Group(
                    body,
                    Text(
                        "📎 " + " · ".join(f"{item.name} ({item.size_label})" for item in attachments),
                        style=MUTED,
                    ),
                )
            self.console.print(
                Panel(
                    body,
                    title=f"[bold {ERROR}]User[/bold {ERROR}]",
                    border_style=ERROR,
                    box=ROUNDED,
                    padding=(0, 1),
                )
            )

        messages = self.build_request_messages()
        messages.append({"role": "user", "content": content})

        graph = self._open_graph()
        turn = graph.start_turn(label or user_input) if graph else None
        self._graph_turn = (graph, turn) if graph and turn else None

        response_text = ""
        try:
            response_text = self.run_coding_agent(messages)
        except KeyboardInterrupt:
            self.last_outcome = "cancelled"
            self.console.print(f"[{PINK}]Generation interrupted; nothing was saved.[/]")
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
        finally:
            self._graph_turn = None
            if graph and turn:
                graph.finish_turn(turn, response_text, self.last_outcome)
                self._save_graph(graph)

        if response_text.strip():
            self.session_manager.add_message("user", saved_text)
            self.session_manager.add_message("assistant", response_text)
            self.pending_attachments.clear()
        elif attachments:
            self.console.print(
                f"[{MUTED}]Your attachments are still attached; they go with your next message.[/]"
            )
        return response_text

    # --- conversation graph (beta) -----------------------------------------

    def _open_graph(self) -> ConversationGraph | None:
        try:
            return ConversationGraph(self.session_manager.get_graph_path())
        except OSError:
            return None

    def _save_graph(self, graph: ConversationGraph) -> None:
        try:
            graph.save()
        except OSError:
            pass  # The graph is a nicety; a full disk must not fail the turn.

    def _record_tool(self, name: str, arguments: str, status: str) -> None:
        if self._graph_turn is not None:
            graph, turn = self._graph_turn
            graph.add_tool(turn, name, arguments, status)

    def show_graph(self) -> None:
        """Draw this session's turns, the tools each used, and the files they touched."""
        graph = self._open_graph()
        turns = graph.turns() if graph else []
        if not graph or not turns:
            self.console.print(
                f"[{MUTED}]No graph yet for this session — it fills in as you chat. (beta)[/]"
            )
            return

        tool_count = sum(1 for node in graph.nodes if node["type"] == "tool")
        files = graph.file_summary()
        self.console.print(
            Panel(
                render_graph(graph, self.console.width - 4, GRAPH_MAX_TURNS),
                title=f"[bold {PINK_LIGHT}]Conversation graph · beta[/bold {PINK_LIGHT}]",
                subtitle=(
                    f"[{MUTED}]{self.session_manager.name} · {len(turns)} turns · "
                    f"{tool_count} tool calls · {len(files)} files[/]"
                ),
                border_style=BORDER,
                box=ROUNDED,
                padding=(0, 1),
            )
        )
        self.console.print(f"[{MUTED}]Saved as JSON: {graph.path}[/]")

    # --- /goal ---------------------------------------------------------------

    def run_goal(self, goal: str) -> None:
        """Keep the agent working, round after round, until the goal is met."""
        goal = goal.strip()
        if not goal:
            self.console.print(
                f"[{MUTED}]Usage: /goal <objective> — nrgrd keeps working until it's done. "
                "Ctrl+C stops it.[/]"
            )
            return
        if not self.ready_to_send():
            return

        self.console.print(
            Panel(
                Markdown(goal),
                title=f"[bold {PINK}]Goal[/bold {PINK}]",
                subtitle=f"[{MUTED}]runs until it's done · Ctrl+C stops[/]",
                border_style=PINK,
                box=ROUNDED,
                padding=(0, 1),
            )
        )

        try:
            for round_number in itertools.count(1):
                if round_number == 1:
                    prompt = GOAL_START.format(goal=goal)
                    label = f"Goal: {goal}"
                else:
                    prompt = GOAL_CONTINUE.format(goal=goal)
                    label = f"Goal · round {round_number}"
                    self.console.print(
                        f"[{PINK_LIGHT}]● Goal · round {round_number}[/] "
                        f"[{MUTED}]not there yet, continuing…[/]"
                    )

                reply = self.send_message(prompt, echo=False, label=label)

                if self.last_outcome == "cancelled":
                    self.console.print(f"[{WARNING}]● Goal stopped.[/]")
                    return
                if self.last_outcome == "error":
                    self.console.print(f"[{ERROR}]● Goal stopped: the last request failed.[/]")
                    return

                verdict, reason = goal_verdict(reply)
                if verdict == "done":
                    self.console.print(
                        f"[bold {GREEN_VIVID}]● Goal achieved[/] "
                        f"[{MUTED}]after {round_number} round{'s' if round_number > 1 else ''}.[/]"
                    )
                    return
                if verdict == "blocked":
                    self.console.print(
                        f"[{WARNING}]● Goal blocked:[/] {reason or 'the agent needs your input.'}"
                    )
                    return
        except KeyboardInterrupt:
            self.console.print(f"[{WARNING}]● Goal stopped.[/]")

    # --- attachments -------------------------------------------------------

    def add_attachment(self, item: Attachment) -> None:
        self.pending_attachments.append(item)
        self.console.print(
            f"[{GREEN_VIVID}]📎 Attached {item.name}[/] [{MUTED}]({item.size_label}) — "
            "goes with your next message.[/]"
        )

    def attach_paths(self, raw: str) -> None:
        """/attach <path> [path…]"""
        try:
            tokens = shlex.split(raw, posix=sys.platform != "win32")
        except ValueError:
            tokens = raw.split()
        for token in tokens:
            path = Path(os.path.expanduser(token.strip('"')))
            if not path.is_absolute():
                path = self.working_directory / path
            try:
                item = load_attachment(path, display_name(path, self.working_directory))
            except AttachmentError as error:
                self.console.print(f"[{ERROR}]● {error}[/]")
                continue
            self.add_attachment(item)

    def show_attachments(self) -> None:
        if not self.pending_attachments:
            self.console.print(
                f"[{MUTED}]Nothing attached. /attach <path>, paste or drag a file in, "
                "or Ctrl+V an image.[/]"
            )
            return
        for item in self.pending_attachments:
            self.console.print(f"[{GREEN_VIVID}]📎 {item.name}[/] [{MUTED}]({item.size_label})[/]")
        self.console.print(f"[{MUTED}]They go with your next message. /attach clear drops them.[/]")

    def attach_clipboard_image(self) -> bool:
        """/paste: attach the clipboard's image. Returns whether one was attached."""
        try:
            image = clipboard_image()
        except ClipboardUnavailable as error:
            self.console.print(f"[{WARNING}]● {error}[/]")
            return False
        if not image:
            self.console.print(f"[{MUTED}]There's no image on the clipboard.[/]")
            return False
        count = sum(1 for item in self.pending_attachments if item.name.startswith("clipboard-"))
        try:
            self.add_attachment(image_attachment(f"clipboard-{count + 1}.png", image))
        except AttachmentError as error:
            self.console.print(f"[{ERROR}]● {error}[/]")
            return False
        return True

    def paste_into(self, buffer: Any) -> None:
        """Ctrl+V: an image on the clipboard is attached; text is typed in."""
        try:
            has_image = bool(clipboard_image())
            problem = None
        except ClipboardUnavailable as error:
            has_image, problem = False, str(error)

        if has_image:
            run_in_terminal(self.attach_clipboard_image)
            return
        text = clipboard_text()
        if text:
            self.paste_text_into(buffer, text)
        elif problem:
            run_in_terminal(lambda: self.console.print(f"[{WARNING}]● {problem}[/]"))

    def paste_text_into(self, buffer: Any, text: str) -> None:
        """Paste or drop: a paste that is only file paths attaches those files."""
        paths = pasted_paths(text, self.working_directory)
        if paths:
            run_in_terminal(lambda: self.attach_paths(" ".join(shlex.quote(str(p)) for p in paths)))
            return
        buffer.insert_text(text.replace("\r\n", "\n").replace("\r", "\n"))

    # --- updates -----------------------------------------------------------

    def start_update_check(self) -> None:
        """Ask PyPI, in the background, whether a newer nrgrd exists."""
        if update_check_disabled():
            return
        cache = get_config_path().parent / "update-check.json"

        def check() -> None:
            latest = cached_latest_version(cache)
            if latest and is_newer(latest, __version__):
                self.update_available = latest

        threading.Thread(target=check, name="nrgrd-update-check", daemon=True).start()

    def show_update_notice(self) -> None:
        if self.update_available and not self._update_notice_shown:
            self._update_notice_shown = True
            self.console.print(
                f"[{GREEN_VIVID}]● nrgrd {self.update_available} is available[/] "
                f"[{MUTED}](you have {__version__}). Run /update to upgrade.[/]"
            )

    def run_update(self) -> None:
        """/update: compare with PyPI and offer to upgrade in place."""
        with Live(
            Spinner("dots12", text="Checking PyPI…", style=PINK_LIGHT),
            console=self.console,
            transient=True,
        ):
            latest = fetch_latest_version()

        if latest is None:
            self.console.print(
                f"[{ERROR}]● Couldn't reach PyPI.[/] [{MUTED}]Check {PYPI_PAGE_URL} yourself.[/]"
            )
            return
        if not is_newer(latest, __version__):
            self.console.print(
                f"[{GREEN_VIVID}]● You're on the latest nrgrd[/] "
                f"[{MUTED}]({__version__}; PyPI has {latest}).[/]"
            )
            return

        command = upgrade_command()
        how = (
            f"[bold]{shlex.join(command)}[/bold]"
            if command
            else "[bold]git pull[/bold] in your nrgrd checkout (you're running from source)"
        )
        self.console.print(
            Panel(
                f"nrgrd [bold {GREEN_VIVID}]{latest}[/bold {GREEN_VIVID}] is out — you have "
                f"{__version__}.\n\nTo upgrade this installation: {how}\n\n"
                f"[{MUTED}]Installed another way? uv tool upgrade nrgrd · pipx upgrade nrgrd · "
                f"pip install --upgrade nrgrd\nWhat's new: {PYPI_PAGE_URL}[/]",
                title=f"[bold {PINK_LIGHT}]Update available[/bold {PINK_LIGHT}]",
                border_style=BORDER,
                box=ROUNDED,
                padding=(0, 1),
            )
        )
        if command is None:
            return
        if sys.platform == "win32":
            # Windows locks a running program's files, so the upgrade can't
            # replace nrgrd while it's open.
            self.console.print(f"[{MUTED}]Exit nrgrd first, then run the command above.[/]")
            return
        try:
            answer = Prompt.ask("Upgrade now?", choices=["y", "n"], default="y", console=self.console)
        except (KeyboardInterrupt, EOFError):
            return
        if answer != "y":
            return
        try:
            result = subprocess.run(command, stdin=subprocess.DEVNULL)
        except OSError as error:
            self.console.print(f"[{ERROR}]● Couldn't run {command[0]}: {error}[/]")
            return
        if result.returncode == 0:
            self.console.print(
                f"[{GREEN_VIVID}]● Upgraded to {latest}.[/] [{MUTED}]Restart nrgrd to use it.[/]"
            )
        else:
            self.console.print(f"[{ERROR}]● The upgrade failed (exit code {result.returncode}).[/]")


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="nrgrd",
        description=(
            "Terminal AI coding agent for OpenAI-compatible inference "
            "endpoints, including NeuroGrid deployments."
        ),
    )
    parser.add_argument(
        "prompt",
        nargs="*",
        help="Run a single prompt and exit instead of opening the TUI.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    parser.add_argument(
        "--model",
        default="",
        help="Use this model for the run instead of the configured one.",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Approve permission-gated tools automatically (for scripts and CI).",
    )
    arguments = parser.parse_args()

    application = NrgrdApp()
    if arguments.model:
        application.config.model = arguments.model

    if arguments.prompt:
        raise SystemExit(
            application.run_once(" ".join(arguments.prompt), approve_all=arguments.yes)
        )

    application.run()
