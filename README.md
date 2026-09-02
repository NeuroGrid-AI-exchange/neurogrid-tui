# nrgrd

![Python](https://img.shields.io/badge/python-3.14%2B-blue)
![License](https://img.shields.io/badge/license-MIT-green)
![Status](https://img.shields.io/badge/status-alpha-orange)

**nrgrd** is [NeuroGrid](https://neurogrid.cc)'s Terminal User Interface (TUI)
for interacting with AI models from your terminal, Claude Code style. Built
on `textual`, `rich`, and `asciimatics`, it points at any OpenAI-compatible
inference endpoint — including a NeuroGrid Marketplace deployment (the URL +
API key of the host you rented) — to chat, manage sessions, and run MCP
tools.

## Features

- **Coding agent** — An iterative tool-use loop (`nrgrd.agent`) that reads, searches, edits, and runs commands in your repository until the task is done.
- **Native tools** — `list_files`, `read_file`, `write_file`, `edit_file`, `search`, `shell`, `git_status`, `git_diff`.
- **Permissions** — Read-only tools run automatically; file writes, shell commands, and MCP tools ask for approval first (or "always allow" for the session).
- **Immersive TUI** — Keyboard navigation with `textual` and custom widgets.
- **Persistent sessions** — Saves conversation context and history locally.
- **OpenAI-compatible endpoint** — Points at any OpenAI-compatible API, including a NeuroGrid deployment.
- **Built-in MCP** — Run and connect MCP servers straight from the terminal; their tools go through the same permission system.
- **CLI + TUI** — Use `nrgrd` for the interactive interface or `nrgrd-mcp` for the MCP server.

## Requirements

- Python >= 3.14
- `uv` (recommended package manager)

## Installation

```bash
# Clone the repository
git clone https://github.com/<your-user>/nrgrd.git
cd nrgrd

# Install dependencies
uv sync

# Run the TUI
uv run nrgrd

# Run the MCP server
uv run nrgrd-mcp
```

## Configuration

`nrgrd` doesn't read environment variables for the connection: use
`/config edit` inside the TUI to save the endpoint URL, the model, and the
API key (for example, the URL and API key of a NeuroGrid Marketplace
inference deployment). Configuration is persisted to `config.json` in the
application's config directory.

## Project structure

```
nrgrd/
├── src/nrgrd/
│   ├── app.py         # TUI entry point (rendering only)
│   ├── agent/         # Agent runtime: loop, events, permissions — no TUI dependency
│   ├── tools/         # Tool registry: filesystem, search, shell, git, MCP adapter
│   ├── api/           # HTTP client for the OpenAI-compatible API
│   ├── config/        # Configuration and tokens
│   ├── context/       # Application state and models
│   ├── screens/       # TUI screens
│   ├── sessions/      # Session handling and storage
│   ├── system/        # System prompts
│   ├── theme/         # Color palette and styles
│   ├── widgets/       # Custom visual components
│   └── workspace/     # Filesystem tools, identity, and the MCP client
├── docs/              # Reports and documentation
├── tests/             # Agent/tool/permission tests (no TUI, no live endpoint needed)
└── pyproject.toml     # Dependencies and project metadata
```

The agent runtime never imports Rich or Textual — the TUI drives it by
iterating `agent.run(messages)` and rendering the events it yields. That
keeps the agent testable headlessly and reusable from a future CLI mode.

## Development

```bash
# Install in editable mode, including dev dependencies
uv sync --dev

# Run the test suite
uv run pytest tests/

# Run linters / checks (if applicable)
uv run ruff check src/
uv run mypy src/
```

## License

MIT
