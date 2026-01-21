# Mamba MCP

A collection of MCP (Model Context Protocol) tools and servers.

## Packages

| Package | Description |
|---------|-------------|
| [mamba-mcp-client](packages/mamba-mcp-client/) | MCP Client for testing and debugging MCP servers |
| [mamba-mcp-core](packages/mamba-mcp-core/) | Shared utilities and types for Mamba MCP packages |

## Quick Start

```bash
# Clone and install
git clone https://github.com/sequenzia/mamba-mcp.git
cd mamba-mcp
uv sync --group dev

# Launch interactive TUI
uv run --package mamba-mcp-client mamba-mcp tui --stdio "python server.py"

# List available tools
uv run --package mamba-mcp-client mamba-mcp tools --stdio "python server.py"
```

See [packages/mamba-mcp-client/README.md](packages/mamba-mcp-client/README.md) for detailed client documentation.

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
│   └── mamba-mcp-client/       # MCP testing client
└── specs/                      # Specifications
```

## License

MIT
