# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Mamba MCP is a UV workspace monorepo containing MCP (Model Context Protocol) packages:

- **mamba-mcp-core** - Shared utilities (CLI helpers, error models, fuzzy matching, transport normalization)
- **mamba-mcp-client** - Testing and debugging tool for MCP servers (TUI, CLI, Python API)
- **mamba-mcp-pg** - PostgreSQL MCP Server with layered schema discovery (8 tools across 3 layers)
- **mamba-mcp-fs** - Filesystem MCP Server with local and S3 backend support (12 tools across 3 layers)
- **mamba-mcp-hana** - SAP HANA MCP Server with layered schema discovery (11 tools across 4 layers)

## Development Commands

```bash
# Install all packages
uv sync --group dev

# Run CLI
uv run --package mamba-mcp-client mamba-mcp --help

# Run tests (per-package to avoid cross-package import conflicts)
uv run --package mamba-mcp-pg pytest packages/mamba-mcp-pg/
uv run --package mamba-mcp-hana pytest packages/mamba-mcp-hana/
uv run --package mamba-mcp-core pytest packages/mamba-mcp-core/
uv run --package mamba-mcp-fs pytest packages/mamba-mcp-fs/
uv run --package mamba-mcp-client pytest packages/mamba-mcp-client/

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
│   ├── mamba-mcp-core/
│   │   ├── pyproject.toml
│   │   ├── src/mamba_mcp_core/
│   │   │   ├── cli.py          # validate_env_file, resolve_default_env_file, setup_logging
│   │   │   ├── config.py       # _env_file_path state management
│   │   │   ├── errors.py       # ToolError model & create_tool_error factory
│   │   │   ├── fuzzy.py        # Levenshtein distance & find_similar_names
│   │   │   └── transport.py    # normalize_transport
│   │   └── tests/
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
│   ├── mamba-mcp-pg/
│   │   ├── pyproject.toml
│   │   ├── src/mamba_mcp_pg/
│   │   │   ├── __main__.py     # Typer CLI (test, serve)
│   │   │   ├── config.py       # Pydantic settings (MAMBA_MCP_PG_*)
│   │   │   ├── errors.py       # Error codes & fuzzy matching
│   │   │   ├── server.py       # FastMCP server & lifespan
│   │   │   ├── database/       # SQLAlchemy async services
│   │   │   ├── models/         # Pydantic I/O models
│   │   │   └── tools/          # MCP tool definitions (8 tools)
│   │   └── tests/
│   ├── mamba-mcp-fs/
│   │   ├── pyproject.toml
│   │   ├── src/mamba_mcp_fs/
│   │   │   ├── __main__.py     # Typer CLI (test, serve)
│   │   │   ├── config.py       # Pydantic settings (MAMBA_MCP_FS_*)
│   │   │   ├── content.py      # MIME detection & text/binary classification
│   │   │   ├── errors.py       # Error codes & fuzzy matching
│   │   │   ├── security.py     # Sandbox & path traversal enforcement
│   │   │   ├── rate_limit.py   # Sliding window rate limiter
│   │   │   ├── server.py       # FastMCP server & lifespan
│   │   │   ├── backends/       # LocalBackend, S3Backend, BackendManager
│   │   │   ├── models/         # Pydantic I/O models
│   │   │   └── tools/          # MCP tool definitions (12 tools)
│   │   └── tests/
│   └── mamba-mcp-hana/
│       ├── pyproject.toml
│       ├── src/mamba_mcp_hana/
│       │   ├── __main__.py     # Typer CLI (test, serve)
│       │   ├── config.py       # Pydantic settings (MAMBA_MCP_HANA_*)
│       │   ├── errors.py       # Error codes & fuzzy matching
│       │   ├── server.py       # FastMCP server & lifespan
│       │   ├── database/       # hdbcli async services
│       │   ├── models/         # Pydantic I/O models
│       │   └── tools/          # MCP tool definitions (11 tools)
│       └── tests/
└── internal/                   # Specs & images
```

## Architecture (mamba-mcp-client)

- `ClientConfig` factory methods: `for_stdio()`, `for_sse()`, `for_http()`, `for_uv_installed()`, `for_uv_local()`
- `MCPTestClient` is an async context manager: `async with client.connect():`
- Transport types: `STDIO`, `SSE`, `HTTP`, `UV_INSTALLED`, `UV_LOCAL`
- Environment config prefix: `MAMBA_MCP_CLIENT_` (e.g., `MAMBA_MCP_CLIENT_STDIO__COMMAND`)

## Architecture (mamba-mcp-pg)

- 3-layer MCP tool architecture:
  - **Layer 1 (Schema Discovery):** `list_schemas`, `list_tables`, `describe_table`, `get_sample_rows`
  - **Layer 2 (Relationships):** `get_foreign_keys`, `find_join_path` (BFS pathfinding)
  - **Layer 3 (Query Execution):** `execute_query`, `explain_query` (read-only, parameterized)
- Database services in `database/` module (SchemaService, RelationshipService, QueryService)
- Query security: blocked keyword validation, SELECT/WITH-only enforcement
- Config via `MAMBA_MCP_PG_*` env vars or `.env` file, auto-detected from cwd
- CLI: `mamba-mcp-pg --env-file .env test` / `mamba-mcp-pg` (serve)
- Uses `mcp>=1.0.0` (FastMCP), `sqlalchemy[asyncio]`, `asyncpg`

## Architecture (mamba-mcp-fs)

- 3-layer MCP tool architecture:
  - **Layer 1 (Discovery):** `list_directory`, `get_file_info`, `read_file`, `search_files` (always registered)
  - **Layer 2 (S3 Extras):** `list_buckets`, `get_presigned_url`, `get_object_metadata` (when S3 enabled)
  - **Layer 3 (Mutation):** `write_file`, `delete_file`, `move_file`, `copy_file`, `create_directory` (when `read_only=false`)
- Backends: `LocalBackend` (fsspec), `S3Backend` (s3fs) via `BackendManager` abstraction
- Security: sandbox enforcement, path traversal prevention, symlink/hidden file policies, extension filtering
- Rate limiting: sliding window per-server-instance limiter
- Config via `MAMBA_MCP_FS_*` env vars or `mamba.env` file, auto-detected from cwd
- CLI: `mamba-mcp-fs --env-file mamba.env test` / `mamba-mcp-fs` (serve)
- Uses `mcp>=1.0.0` (FastMCP), `fsspec`, `s3fs`, `pydantic-settings`

## Architecture (mamba-mcp-hana)

- 4-layer MCP tool architecture:
  - **Layer 1 (Schema Discovery):** `list_schemas`, `list_tables`, `describe_table`, `get_sample_rows`
  - **Layer 2 (Relationships):** `get_foreign_keys`, `find_join_path` (BFS pathfinding)
  - **Layer 3 (Query Execution):** `execute_query`, `explain_query` (read-only, parameterized)
  - **HANA-Specific:** `list_calculation_views`, `get_table_store_type`, `list_procedures`
- Database services in `database/` module (HanaConnectionPool, SchemaService, RelationshipService, QueryService, HanaService)
- Connection pool: async queue-based wrapper around synchronous hdbcli driver (`asyncio.to_thread()`)
- Query security: blocked keyword validation, SELECT/WITH-only enforcement
- Config via `MAMBA_MCP_HANA_*` env vars or `mamba.env` file, auto-detected from cwd
- Auth: user/password or hdbuserstore key; TLS auto-enabled for port 443 (HANA Cloud)
- CLI: `mamba-mcp-hana --env-file mamba.env test` / `mamba-mcp-hana` (serve)
- Uses `mcp>=1.0.0` (FastMCP), `hdbcli`, `pydantic-settings`

## Key Patterns to Follow

### Server Package Pattern (pg, fs, hana)

When creating or modifying MCP server packages, follow these established patterns:

1. **AppContext via Lifespan** — All servers use `@dataclass class AppContext` yielded from an `app_lifespan()` async context manager. Tools access it via `ctx.request_context.lifespan_context`. Resources (engines, pools, backends) init at startup, cleanup on shutdown.

2. **Tool Handler Skeleton** — Every `@mcp.tool()` function follows: timing (`time.perf_counter()`) → null-check `ctx` → extract `app_ctx` → open connection/acquire pool → delegate to service → convert to Pydantic output → catch exceptions → return structured error with elapsed time logging.

3. **Error Handling Triad** — Each server's `errors.py` contains: (a) `ErrorCode` class with string constants, (b) `ERROR_SUGGESTIONS` dict mapping codes to user-facing messages, (c) `create_tool_error()` factory function + Levenshtein-based fuzzy matching (`find_similar_names()` / `suggest_similar()`).

4. **Module-level Config State** — A global `_env_file_path` variable set by `set_env_file_path()` bridges CLI arg parsing (`__main__.py`) to config loading (`config.py`). Tests must use autouse fixtures to reset this state.

5. **Nested Pydantic Settings** — Root `Settings` uses `@model_validator(mode="before")` to instantiate nested settings classes (`DatabaseSettings`, `ServerSettings`) with the `_env_file` parameter. Each nested class has its own `env_prefix`.

6. **CLI Entry Point** — Typer app with `invoke_without_command=True` callback. Running bare starts the server; `test` subcommand validates connectivity. Uses `validate_env_file()` callback and `resolve_default_env_file()` for auto-discovery.

7. **Tool Registration via Import Side-Effects** — Tool modules import the module-level `mcp` instance from `server.py` and register via `@mcp.tool()` decorators. `__main__.py` triggers this with `from package.tools import ... # noqa: F401`.

### Layered Tool Architecture

- **Layer 1 (Discovery):** Always registered, read-only. Schema listing, table description, file browsing.
- **Layer 2 (Relationships/Extras):** Foreign keys, join paths (DB servers); S3-specific tools (FS server). May be conditional.
- **Layer 3 (Execution/Mutation):** Query execution (DB); file write/delete/move (FS). Conditional on `read_only` config.
- **Layer 4 (Platform-Specific):** HANA only — calculation views, store types, procedures.

### Pydantic Model Conventions

- Input/Output pairs per tool: `ListSchemasInput` + `ListSchemasOutput`
- All fields use `Field(description="...")` for MCP tool parameter documentation
- Validation via `Field(ge=1, le=100)`, `pattern=`, `min_length`/`max_length`
- Computed fields with `@computed_field` decorator for derived data
- Type hints: `str | None` (not `Optional[str]`)
- Centralized exports in `models/__init__.py` with `__all__`

## Testing Conventions

- **Class-based organization:** `class TestFeatureName:` groups related tests
- **Descriptive names:** `test_for_stdio()`, `test_unknown_extension_no_content()`
- **One-line docstrings:** Every test has a docstring explaining what it tests
- **File naming:** `test_<module>.py` mirrors source structure
- **Parametrize:** Use `@pytest.mark.parametrize` for 3+ similar test cases
- **Autouse fixtures:** Reset module-level state (`set_env_file_path(None)`) to prevent leakage
- **Mock helpers:** `create_mock_result()` in conftest.py for SQLAlchemy row mocking
- **Async tests:** `asyncio_mode = "auto"` in root pyproject.toml — no need for `@pytest.mark.asyncio`
- **Coverage target:** Security-critical modules target 100% coverage

## Known Inconsistencies

- **Error return types:** `mamba-mcp-pg` `create_tool_error()` returns `dict[str, Any]`, `mamba-mcp-hana` returns `ToolError` model instance, `mamba-mcp-fs` uses custom exception hierarchy (`FSError` base). All share the core `ToolError` model via `mamba-mcp-core`; the wrapper functions preserve each server's existing return type contract.
- **FS error architecture:** FS intentionally keeps its custom exception hierarchy (`FSError` base + 9 subclasses) for internal backend flow control — a pattern the DB servers don't need.

### Resolved Inconsistencies

The following have been standardized:
- ~~Module name~~ — `mamba-mcp-hana` now maps to `mamba_mcp_hana` (1:1 like other packages)
- ~~Tool return types~~ — All servers now return `OutputModel | dict[str, Any]` (HANA migrated from `str`)
- ~~Fuzzy matching thresholds~~ — All servers use `mamba-mcp-core`'s scaled threshold: `max(2, min(len//2, 5))`
- ~~Transport naming~~ — All servers accept both `"http"` and `"streamable-http"`, normalized via core
- ~~Code duplication~~ — CLI helpers, config state, errors, and fuzzy matching consolidated in `mamba-mcp-core`

## Code Standards

- Python 3.11+
- Line length: 100 (Ruff)
- MyPy strict mode
- pytest asyncio auto mode
- Ruff rules: E, F, I, N, W, UP
