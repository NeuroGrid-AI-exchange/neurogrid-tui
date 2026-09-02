# nrgrd

![Python](https://img.shields.io/badge/python-3.14%2B-blue)
![License](https://img.shields.io/badge/license-MIT-green)
![Status](https://img.shields.io/badge/status-alpha-orange)

**nrgrd** is [NeuroGrid](https://neurogrid.cc)'s Terminal User Interface (TUI)
for interacting with AI models from your terminal, Claude Code style. Built
on `rich` and `prompt-toolkit`, it points at any OpenAI-compatible
inference endpoint — including a NeuroGrid Marketplace deployment (the URL +
API key of the host you rented) — to chat, manage sessions, and run MCP
tools.

## Features

- **Coding agent** — An iterative tool-use loop (`nrgrd.agent`) that reads, searches, edits, and runs commands in your repository until the task is done.
- **Workspace aware** — Detects git, language, package manager, and test framework at startup, so the agent doesn't waste turns rediscovering your project.
- **Interruptible** — Ctrl+C stops generation or a running tool without corrupting the conversation, keeping whatever was produced.
- **Named sessions** — Several conversations per project: list, resume, rename, delete.
- **CLI mode** — `nrgrd "fix the failing tests"` runs headless on the same runtime, for scripts and CI.
- **Native tools** — `list_files`, `read_file`, `write_file`, `edit_file`, `search`, `shell`, `git_status`, `git_diff`.
- **Permissions** — Read-only tools run automatically; file writes, shell commands, and MCP tools ask for approval first (or "always allow" for the session).
- **Immersive TUI** — Rich-rendered panels, streaming output, and slash-command completion.
- **Persistent sessions** — Saves conversation context and history locally.
- **Any compatible endpoint** — Behind a `ModelProvider` abstraction: a NeuroGrid deployment, vLLM, Ollama, LM Studio, or anything else speaking the same API. All nrgrd needs is a URL, a key, and a model name.
- **Keys kept out of the config file** — The API key lives in your OS credential store, and never appears in errors or logs.
- **Errors you can act on** — Failures name the endpoint and model involved and say what to change.
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

Once published, the intended install is a single command:

```bash
uv tool install nrgrd
nrgrd
```

## Usage

```bash
nrgrd                              # interactive TUI
nrgrd "explain this repository"    # one prompt, then exit
nrgrd --model qwen3-coder "fix the failing tests"
nrgrd --yes "run the tests"        # approve gated tools automatically (CI)
```

### Commands

| Command | What it does |
|---|---|
| `/help` | List every command |
| `/config`, `/config edit` | Show or change the connection |
| `/con`, `/models` | Check the endpoint, list its models |
| `/tools`, `/permissions` | Show tools and how each is gated |
| `/session list`, `/session new\|resume\|rename\|delete <name>` | Manage sessions |
| `/diff`, `/context`, `/compact` | Review changes, context usage, summarise |
| `/mcp`, `/mcp edit`, `/mcp reload` | Manage MCP servers |

## Configuration

The first time you run `nrgrd` it opens a **Connect to a model** screen and
asks for the three things a NeuroGrid deployment hands you:

```
Endpoint   https://<your-deployment>/v1
API key    ••••••••••••
Model      qwen3-coder
```

It then queries the endpoint and lets you pick from the models it actually
serves. Run `/config edit` to change any of this later.

The endpoint and model are saved to `config.json` in the application's
config directory. **The API key is not** — it goes to your operating
system's credential store (Keychain, Windows Credential Manager, or a
Secret Service keyring). On machines with no usable keyring it falls back
to an owner-only (`0600`) file, and `/config` tells you which is in use. A
key left over in an older plaintext `config.json` is migrated out
automatically on startup.

No environment variables are involved.

## Project structure

```
nrgrd/
├── src/nrgrd/
│   ├── app.py         # TUI entry point (rendering only)
│   ├── agent/         # Agent runtime: loop, events, permissions — no TUI dependency
│   ├── tools/         # Tool registry: filesystem, search, shell, git, MCP adapter
│   ├── api/           # ModelProvider abstraction + the OpenAI-compatible one
│   ├── config/        # Configuration and credential storage
│   ├── context/       # Application state, models, token estimates
│   ├── screens/       # The connect / onboarding screen
│   ├── sessions/      # Session handling and storage
│   ├── system/        # System prompts
│   ├── theme/         # Color palette and styles
│   ├── widgets/       # Custom visual components
│   └── workspace/     # Filesystem tools, project discovery, MCP client
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
