# Mamba MCP

A Python monorepo of MCP (Model Context Protocol) tools — a testing client and production MCP servers.

## Packages

| Package | Description |
|---------|-------------|
| [mamba-mcp-client](packages/mamba-mcp-client/) | MCP testing client with interactive TUI, CLI, and Python API |
| [mamba-mcp-postgres](packages/mamba-mcp-postgres/) | PostgreSQL MCP server with layered schema discovery |
| [mamba-mcp-fs](packages/mamba-mcp-fs/) | Filesystem MCP server with local and S3 backend support |

### mamba-mcp-client

Testing and debugging tool for MCP servers. Supports stdio, SSE, HTTP, and UV-based transports.

#### Mamba MCP Client TUI

![Mamba MCP Client](./internal/images/mcp-client-01.png)


- **Interactive TUI** — Textual-based terminal interface for exploring servers in real-time
- **CLI Commands** — Quick one-off commands for inspection and scripting
- **Python API** — Fully async programmatic interface for test automation
- **Protocol Logging** — Detailed request/response capture with timing

```bash
# Launch interactive TUI
mamba-mcp tui --stdio "python server.py"

# CLI inspection
mamba-mcp tools --stdio "python server.py"
mamba-mcp call add --args '{"a": 5, "b": 3}' --stdio "python server.py"
```

### mamba-mcp-postgres

PostgreSQL MCP server with a 3-layer tool architecture for AI assistants.

- **Layer 1: Schema Discovery** — List schemas, tables, describe columns, sample rows
- **Layer 2: Relationship Discovery** — Foreign keys, join path finding (BFS)
- **Layer 3: Query Execution** — Read-only SQL with parameterized queries and EXPLAIN support

```bash
# Test database connection
mamba-mcp-postgres --env-file mamba.env test

# Run the MCP server
mamba-mcp-postgres --env-file mamba.env
```

### mamba-mcp-fs

Filesystem MCP server with local and S3 backends for AI assistants.

- **Layer 1: Discovery** — List directories, read files, get metadata, search by name/content
- **Layer 2: S3 Extras** — List buckets, presigned URLs, object metadata (when S3 enabled)
- **Layer 3: Mutation** — Write, delete, move, copy files, create directories (when read-write)

```bash
# Test configuration and backend connectivity
mamba-mcp-fs --env-file mamba.env test

# Run the MCP server
mamba-mcp-fs --env-file mamba.env
```

## Configuration

All packages use `mamba.env` for environment-based configuration. Default file locations (checked in order):

1. `./mamba.env` (project-local)
2. `~/mamba.env` (global fallback)

## Development

```bash
# Install all packages
uv sync --group dev

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
│   ├── mamba-mcp-client/       # MCP testing client
│   │   ├── src/mamba_mcp_client/
│   │   └── examples/
│   ├── mamba-mcp-postgres/     # PostgreSQL MCP server
│   │   ├── src/mamba_mcp_postgres/
│   │   └── tests/
│   └── mamba-mcp-fs/           # Filesystem MCP server
│       ├── src/mamba_mcp_fs/
│       └── tests/
└── internal/                   # Specs & images
```

## License

MIT
