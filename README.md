# Mamba MCP

A Python toolkit for testing and debugging MCP (Model Context Protocol) servers.

Testing MCP servers is difficult—debugging is painful, and there are few good tools to inspect MCP communication in detail. Mamba MCP provides an interactive terminal UI, CLI commands, and a programmatic Python API for comprehensive MCP server testing.

## Features

- **Interactive TUI** - Textual-based terminal interface for exploring servers in real-time
- **CLI Commands** - Quick one-off commands for inspection and scripting
- **Python API** - Fully async programmatic interface for test automation
- **Multi-Transport** - Supports stdio, SSE, HTTP, and UV-based transports
- **Protocol Logging** - Detailed request/response capture with timing

## Packages

| Package | Description |
|---------|-------------|
| [mamba-mcp-client](packages/mamba-mcp-client/) | MCP testing client with TUI, CLI, and Python API |
| [mamba-mcp-core](packages/mamba-mcp-core/) | Shared utilities and types for Mamba MCP packages |

## Quick Start

```bash
# Clone and install
git clone https://github.com/sequenzia/mamba-mcp.git
cd mamba-mcp
uv sync --group dev

# Launch interactive TUI
uv run --package mamba-mcp-client mamba-mcp tui --stdio "python server.py"

# Or try with the included sample server
uv run --package mamba-mcp-client mamba-mcp tui --stdio "python packages/mamba-mcp-client/examples/sample_server.py"

# CLI commands for quick inspection
uv run --package mamba-mcp-client mamba-mcp connect --stdio "python server.py"  # View server info
uv run --package mamba-mcp-client mamba-mcp tools --stdio "python server.py"    # List tools
uv run --package mamba-mcp-client mamba-mcp call add --args '{"a": 5, "b": 3}' --stdio "python server.py"
```

For detailed documentation on all CLI commands, Python API, and configuration options, see [packages/mamba-mcp-client/README.md](packages/mamba-mcp-client/README.md).

## Development

```bash
# Install all packages
uv sync --group dev

# Run CLI
uv run --package mamba-mcp-client mamba-mcp --help

# Run tests
pytest packages/

# Type check
mypy packages/

# Lint and format
ruff check packages/
ruff format packages/
```

## Repository Structure

```
mamba-mcp/
├── pyproject.toml              # Workspace configuration
├── uv.lock                     # Shared lockfile
├── packages/
│   ├── mamba-mcp-core/         # Shared utilities
│   │   └── src/mamba_mcp_core/
│   └── mamba-mcp-client/       # MCP testing client
│       ├── src/mamba_mcp_client/
│       │   ├── cli.py          # CLI entry point
│       │   ├── client.py       # MCPTestClient
│       │   ├── config.py       # Transport configs
│       │   └── tui/            # Terminal UI
│       └── examples/           # Sample server and API usage
└── specs/                      # Specifications
```

## License

MIT
