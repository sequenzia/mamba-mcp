# Mamba MCP

A Python monorepo of MCP (Model Context Protocol) tools — a testing client and production MCP servers.

## Packages

| Package | Description |
|---------|-------------|
| [mamba-mcp-core](packages/mamba-mcp-core/) | Shared utilities (error models, fuzzy matching, CLI helpers, transport normalization) |
| [mamba-mcp-client](packages/mamba-mcp-client/) | MCP testing client with interactive TUI, CLI, and Python API |
| [mamba-mcp-pg](packages/mamba-mcp-pg/) | PostgreSQL MCP server — 8 tools across 3 layers |
| [mamba-mcp-fs](packages/mamba-mcp-fs/) | Filesystem MCP server with local and S3 backends — 12 tools across 3 layers |
| [mamba-mcp-hana](packages/mamba-mcp-hana/) | SAP HANA MCP server — 11 tools across 4 layers |

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

### mamba-mcp-pg

PostgreSQL MCP server with a 3-layer tool architecture for AI assistants.

- **Layer 1: Schema Discovery** — List schemas, tables, describe columns, sample rows
- **Layer 2: Relationship Discovery** — Foreign keys, join path finding (BFS)
- **Layer 3: Query Execution** — Read-only SQL with parameterized queries and EXPLAIN support

```bash
# Test database connection
mamba-mcp-pg --env-file mamba.env test

# Run the MCP server
mamba-mcp-pg --env-file mamba.env
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

### mamba-mcp-hana

SAP HANA MCP server with a 4-layer tool architecture for AI assistants.

- **Layer 1: Schema Discovery** — List schemas, tables, describe columns, sample rows
- **Layer 2: Relationship Discovery** — Foreign keys, join path finding (BFS)
- **Layer 3: Query Execution** — Read-only SQL with parameterized queries and EXPLAIN support
- **HANA-Specific Tools** — Calculation views, column/row store type, stored procedures

```bash
# Test database connection
mamba-mcp-hana --env-file mamba.env test

# Run the MCP server
mamba-mcp-hana --env-file mamba.env
```

## Architecture

All three MCP server packages follow a consistent internal architecture built on **FastMCP** with a **layered tool system**:

```
__main__.py (Typer CLI)
  → server.py (FastMCP + lifespan resource management)
    → tools/ (MCP tool handlers, organized by layer)
      → database/ or backends/ (service layer)
        → models/ (Pydantic I/O contracts)
```

**Shared patterns across servers:**

- **Layered Tools** — Tools progress from discovery → relationships → execution, designed for incremental exploration by AI agents
- **AppContext via Lifespan** — Resources (DB engines, connection pools, backends) initialized at startup, cleaned up on shutdown
- **Pydantic Settings** — Environment-based configuration with `MAMBA_MCP_{PKG}_*` prefix and `mamba.env` file auto-discovery
- **Error Framework** — Structured error codes with fuzzy name matching ("did you mean?") suggestions
- **Service Layer** — Thin tool handlers delegate to service classes that encapsulate domain logic

**Tech stack:** Python 3.11+, FastMCP, Pydantic, Typer, Textual, SQLAlchemy+asyncpg, hdbcli, fsspec+s3fs

The three server packages share `mamba-mcp-core` for common utilities (error models, fuzzy matching, CLI helpers, transport normalization). The client package is fully independent.

## Configuration

All packages use `mamba.env` for environment-based configuration. Default file locations (checked in order):

1. `./mamba.env` (project-local)
2. `~/mamba.env` (global fallback)

## Development

```bash
# Install all packages
uv sync --group dev

# Run tests (per-package to avoid cross-package import conflicts)
uv run --package mamba-mcp-core pytest packages/mamba-mcp-core/
uv run --package mamba-mcp-pg pytest packages/mamba-mcp-pg/
uv run --package mamba-mcp-fs pytest packages/mamba-mcp-fs/
uv run --package mamba-mcp-hana pytest packages/mamba-mcp-hana/
uv run --package mamba-mcp-client pytest packages/mamba-mcp-client/

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
│   │   ├── src/mamba_mcp_core/
│   │   └── tests/
│   ├── mamba-mcp-client/       # MCP testing client
│   │   ├── src/mamba_mcp_client/
│   │   ├── tests/
│   │   └── examples/
│   ├── mamba-mcp-pg/           # PostgreSQL MCP server
│   │   ├── src/mamba_mcp_pg/
│   │   └── tests/
│   ├── mamba-mcp-fs/           # Filesystem MCP server
│   │   ├── src/mamba_mcp_fs/
│   │   └── tests/
│   └── mamba-mcp-hana/         # SAP HANA MCP server
│       ├── src/mamba_mcp_hana/
│       └── tests/
└── internal/                   # Specs & images
```

## License

MIT
