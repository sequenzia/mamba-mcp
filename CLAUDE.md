# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Mamba MCP is a UV workspace monorepo containing MCP (Model Context Protocol) packages:

- **mamba-mcp-client** - Testing and debugging tool for MCP servers (TUI, CLI, Python API)
- **mamba-mcp-postgres** - PostgreSQL MCP Server with layered schema discovery (8 tools across 3 layers)

## Development Commands

```bash
# Install all packages
uv sync --group dev

# Run CLI
uv run --package mamba-mcp-client mamba-mcp --help

# Run tests
pytest packages/
pytest packages/mamba-mcp-client/tests/test_client.py::TestClientConfig

# Type check
mypy packages/

# Lint and format
ruff check packages/
ruff format packages/

# Add dependencies
uv add --package mamba-mcp-client some-library
uv add --group dev some-dev-tool
```

## Running the Client

```bash
# Interactive TUI
uv run --package mamba-mcp-client mamba-mcp tui --stdio "python server.py"

# CLI commands
uv run --package mamba-mcp-client mamba-mcp connect --stdio "python server.py"
uv run --package mamba-mcp-client mamba-mcp tools --sse http://localhost:8000/sse
uv run --package mamba-mcp-client mamba-mcp call add --args '{"a": 5, "b": 3}' --stdio "python server.py"

# UV transports
uv run --package mamba-mcp-client mamba-mcp connect --uv @modelcontextprotocol/server-sqlite
uv run --package mamba-mcp-client mamba-mcp connect --uv-local-path ./my-server --uv-local-name server

# Extra server arguments (-- separator)
uv run --package mamba-mcp-client mamba-mcp connect --stdio "python server.py" -- --verbose
uv run --package mamba-mcp-client mamba-mcp tui --sse http://localhost:8000/sse -- env=prod
```

## Repository Structure

```
mamba-mcp/
├── pyproject.toml              # Workspace configuration
├── uv.lock                     # Shared lockfile
├── packages/
│   ├── mamba-mcp-client/
│   │   ├── pyproject.toml
│   │   ├── src/mamba_mcp_client/
│   │   │   ├── cli.py          # Typer CLI entry point
│   │   │   ├── client.py       # MCPTestClient async client
│   │   │   ├── config.py       # Transport configs (Pydantic)
│   │   │   ├── logging.py      # Protocol logging
│   │   │   └── tui/app.py      # Textual TUI
│   │   ├── tests/
│   │   └── examples/
│   └── mamba-mcp-postgres/
│       ├── pyproject.toml
│       ├── src/mamba_mcp_postgres/
│       │   ├── __main__.py     # Typer CLI (test, serve)
│       │   ├── config.py       # Pydantic settings (MAMBA_MCP_POSTGRES_*)
│       │   ├── errors.py       # Error codes & fuzzy matching
│       │   ├── server.py       # FastMCP server & lifespan
│       │   ├── database/       # SQLAlchemy async services
│       │   ├── models/         # Pydantic I/O models
│       │   └── tools/          # MCP tool definitions (8 tools)
│       └── tests/
└── specs/
```

## Architecture (mamba-mcp-client)

- `ClientConfig` factory methods: `for_stdio()`, `for_sse()`, `for_http()`, `for_uv_installed()`, `for_uv_local()`
- `MCPTestClient` is an async context manager: `async with client.connect():`
- Transport types: `STDIO`, `SSE`, `HTTP`, `UV_INSTALLED`, `UV_LOCAL`
- Environment config prefix: `MAMBA_MCP_CLIENT_` (e.g., `MAMBA_MCP_CLIENT_STDIO__COMMAND`)

## Architecture (mamba-mcp-postgres)

- 3-layer MCP tool architecture:
  - **Layer 1 (Schema Discovery):** `list_schemas`, `list_tables`, `describe_table`, `get_sample_rows`
  - **Layer 2 (Relationships):** `get_foreign_keys`, `find_join_path` (BFS pathfinding)
  - **Layer 3 (Query Execution):** `execute_query`, `explain_query` (read-only, parameterized)
- Database services in `database/` module (SchemaService, RelationshipService, QueryService)
- Query security: blocked keyword validation, SELECT/WITH-only enforcement
- Config via `MAMBA_MCP_POSTGRES_*` env vars or `.env` file, auto-detected from cwd
- CLI: `mamba-mcp-postgres --env-file .env test` / `mamba-mcp-postgres` (serve)
- Uses `mcp>=1.0.0` (FastMCP), `sqlalchemy[asyncio]`, `asyncpg`

## Code Standards

- Python 3.11+
- Line length: 100 (Ruff)
- MyPy strict mode
- pytest asyncio auto mode
- Ruff rules: E, F, I, N, W, UP
