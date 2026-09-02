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

- **Immersive TUI** — Keyboard navigation with `textual` and custom widgets.
- **Persistent sessions** — Saves conversation context and history locally.
- **OpenAI-compatible endpoint** — Points at any OpenAI-compatible API, including a NeuroGrid deployment.
- **Built-in MCP** — Run and connect MCP servers straight from the terminal.
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
│   ├── app.py            # Main entry point
│   ├── api/               # HTTP client for the OpenAI-compatible API
│   ├── config/            # Configuration and tokens
│   ├── context/           # Application state and models
│   ├── screens/           # TUI screens
│   ├── sessions/          # Session handling and storage
│   ├── system/            # System prompts
│   ├── theme/             # Color palette and styles
│   ├── widgets/           # Custom visual components
│   └── workspace/         # Tools, identity, and MCP
├── docs/                  # Reports and documentation
└── pyproject.toml         # Dependencies and project metadata
```

## Development

```bash
# Install in editable mode
uv sync --dev

# Run linters / checks (if applicable)
uv run ruff check src/
uv run mypy src/
```

## License

MIT
