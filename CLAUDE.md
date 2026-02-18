# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Mamba MCP is a single Python package (`mamba-mcp`) with optional extras, containing MCP (Model Context Protocol) modules:

- **mamba_mcp_core** - Shared utilities (CLI helpers, error models, fuzzy matching, transport normalization)
- **mamba_mcp_client** - Testing and debugging tool for MCP servers (TUI, CLI, Python API)
- **mamba_mcp_pg** - PostgreSQL MCP Server with layered schema discovery (8 tools across 3 layers)
- **mamba_mcp_fs** - Filesystem MCP Server with local and S3 backend support (12 tools across 3 layers)
- **mamba_mcp_hana** - SAP HANA MCP Server with layered schema discovery (11 tools across 4 layers)
- **mamba_mcp_gitlab** - GitLab MCP Server for merge requests, issues, pipelines, and search (18 tools across 4 categories)

### Installation Extras

```bash
pip install mamba-mcp            # core only
pip install mamba-mcp[client]    # core + client
pip install mamba-mcp[pg]        # core + pg server
pip install mamba-mcp[fs]        # core + fs server
pip install mamba-mcp[hana]      # core + hana server
pip install mamba-mcp[gitlab]    # core + gitlab server
pip install mamba-mcp[all]       # everything
```

## Development Commands

```bash
# Install all extras and dev tools
uv sync --all-extras --group dev

# Run CLI
uv run mamba-mcp --help

# Run tests (all at once or per-module)
uv run pytest tests/
uv run pytest tests/core/
uv run pytest tests/client/
uv run pytest tests/pg/
uv run pytest tests/fs/
uv run pytest tests/hana/
uv run pytest tests/gitlab/

# Type check
uv run mypy src/

# Lint and format
uv run ruff check src/
uv run ruff format src/

# Add dev dependencies
uv add --group dev some-dev-tool
```

## Running the Client

```bash
# Interactive TUI
uv run mamba-mcp tui --stdio "python server.py"

# CLI commands
uv run mamba-mcp connect --stdio "python server.py"
uv run mamba-mcp tools --sse http://localhost:8000/sse
uv run mamba-mcp call add --args '{"a": 5, "b": 3}' --stdio "python server.py"

# UV transports
uv run mamba-mcp connect --uv @modelcontextprotocol/server-sqlite
uv run mamba-mcp connect --uv-local-path ./my-server --uv-local-name server

# Extra server arguments (-- separator)
uv run mamba-mcp connect --stdio "python server.py" -- --verbose
uv run mamba-mcp tui --sse http://localhost:8000/sse -- env=prod
```

## Repository Structure

```
mamba-mcp/
├── pyproject.toml              # Single package config with extras
├── uv.lock                     # Shared lockfile
├── src/
│   ├── mamba_mcp_core/
│   │   ├── cli.py              # validate_env_file, resolve_default_env_file, setup_logging
│   │   ├── config.py           # _env_file_path state management
│   │   ├── errors.py           # ToolError model & create_tool_error factory
│   │   ├── fuzzy.py            # Levenshtein distance & find_similar_names
│   │   └── transport.py        # normalize_transport
│   ├── mamba_mcp_client/
│   │   ├── cli.py              # Typer CLI entry point
│   │   ├── client.py           # MCPTestClient async client
│   │   ├── config.py           # Transport configs (Pydantic)
│   │   ├── logging.py          # Protocol logging
│   │   └── tui/app.py          # Textual TUI
│   ├── mamba_mcp_pg/
│   │   ├── __main__.py         # Typer CLI (test, serve)
│   │   ├── config.py           # Pydantic settings (MAMBA_MCP_PG_*)
│   │   ├── errors.py           # Error codes & fuzzy matching
│   │   ├── server.py           # FastMCP server & lifespan
│   │   ├── database/           # SQLAlchemy async services
│   │   ├── models/             # Pydantic I/O models
│   │   └── tools/              # MCP tool definitions (8 tools)
│   ├── mamba_mcp_fs/
│   │   ├── __main__.py         # Typer CLI (test, serve)
│   │   ├── config.py           # Pydantic settings (MAMBA_MCP_FS_*)
│   │   ├── content.py          # MIME detection & text/binary classification
│   │   ├── errors.py           # Error codes & fuzzy matching
│   │   ├── security.py         # Sandbox & path traversal enforcement
│   │   ├── rate_limit.py       # Sliding window rate limiter
│   │   ├── server.py           # FastMCP server & lifespan
│   │   ├── backends/           # LocalBackend, S3Backend, BackendManager
│   │   ├── models/             # Pydantic I/O models
│   │   └── tools/              # MCP tool definitions (12 tools)
│   ├── mamba_mcp_hana/
│   │   ├── __main__.py         # Typer CLI (test, serve)
│   │   ├── config.py           # Pydantic settings (MAMBA_MCP_HANA_*)
│   │   ├── errors.py           # Error codes & fuzzy matching
│   │   ├── server.py           # FastMCP server & lifespan
│   │   ├── database/           # hdbcli async services
│   │   ├── models/             # Pydantic I/O models
│   │   └── tools/              # MCP tool definitions (11 tools)
│   └── mamba_mcp_gitlab/
│       ├── __main__.py         # Typer CLI (test, serve)
│       ├── config.py           # Pydantic settings (MAMBA_MCP_GITLAB_*)
│       ├── auth.py             # PAT & OAuth 2.0 auth strategies
│       ├── errors.py           # Error codes & fuzzy matching
│       ├── rate_limit.py       # Sliding window rate limiter
│       ├── server.py           # FastMCP server & lifespan
│       ├── services/           # GitLab API service classes
│       ├── models/             # Pydantic I/O models
│       └── tools/              # MCP tool definitions (18 tools)
├── tests/
│   ├── core/
│   ├── client/
│   ├── pg/
│   ├── fs/                     # Includes test_backends/, test_tools/ subdirs
│   ├── hana/
│   └── gitlab/
├── examples/                   # Client usage examples
├── docs/                       # MkDocs documentation site
└── internal/                   # Specs & images
```

## Architecture (mamba_mcp_client)

- `ClientConfig` factory methods: `for_stdio()`, `for_sse()`, `for_http()`, `for_uv_installed()`, `for_uv_local()`
- `MCPTestClient` is an async context manager: `async with client.connect():`
- Transport types: `STDIO`, `SSE`, `HTTP`, `UV_INSTALLED`, `UV_LOCAL`
- Environment config prefix: `MAMBA_MCP_CLIENT_` (e.g., `MAMBA_MCP_CLIENT_STDIO__COMMAND`)

## Architecture (mamba_mcp_pg)

- 3-layer MCP tool architecture:
  - **Layer 1 (Schema Discovery):** `list_schemas`, `list_tables`, `describe_table`, `get_sample_rows`
  - **Layer 2 (Relationships):** `get_foreign_keys`, `find_join_path` (BFS pathfinding)
  - **Layer 3 (Query Execution):** `execute_query`, `explain_query` (read-only, parameterized)
- Database services in `database/` module (SchemaService, RelationshipService, QueryService)
- Query security: blocked keyword validation, SELECT/WITH-only enforcement
- Config via `MAMBA_MCP_PG_*` env vars or `.env` file, auto-detected from cwd
- CLI: `mamba-mcp-pg --env-file .env test` / `mamba-mcp-pg` (serve)
- Uses `mcp>=1.0.0` (FastMCP), `sqlalchemy[asyncio]`, `asyncpg`

## Architecture (mamba_mcp_fs)

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

## Architecture (mamba_mcp_hana)

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

## Architecture (mamba_mcp_gitlab)

- 4-category MCP tool architecture:
  - **Merge Requests (7 tools):** `list_mrs`, `get_mr`, `get_mr_diffs`, `get_mr_commits`, `get_mr_pipelines`, `create_mr`, `update_mr`
  - **Issues (6 tools):** `list_issues`, `get_issue`, `list_issue_comments`, `create_issue`, `update_issue`, `add_issue_comment`
  - **Pipelines (4 tools):** `list_pipelines`, `get_pipeline`, `get_pipeline_jobs`, `get_job_log`
  - **Search (1 tool):** `search` (instance/project/group scoped)
- Auth strategies: PAT (Private Access Token) and OAuth 2.0 (client credentials with token refresh)
- Services in `services/` module (GitLabService base, MergeRequestService, IssueService, PipelineService, SearchService)
- Read-only mode: runtime gating via `check_read_only()` on write tools (create/update MRs, create/update issues, add comments)
- Rate limiting: sliding window per-server-instance limiter with configurable window and max requests
- Config via `MAMBA_MCP_GITLAB_*` env vars or `mamba.env` file, auto-detected from cwd
- CLI: `mamba-mcp-gitlab --env-file mamba.env test` / `mamba-mcp-gitlab` (serve)
- Uses `mcp>=1.0.0` (FastMCP), `httpx`, `pydantic-settings`

## Dependency Graph

```
mamba-mcp (single PyPI package)
├── base deps: pydantic, typer
├── [client] extra: fastmcp, textual, httpx, ...
├── [pg] extra: mcp, sqlalchemy[asyncio], asyncpg, pydantic-settings
├── [fs] extra: mcp, fsspec, s3fs, pydantic-settings
├── [hana] extra: mcp, hdbcli, pydantic-settings
├── [gitlab] extra: mcp, httpx, pydantic-settings
└── [all] extra: all of the above
```

**Internal module relationships:**
- **Core is always available**: All modules can import from `mamba_mcp_core`
- **Client is independent**: It does not import from `mamba_mcp_core` or any server module
- **No cross-server imports**: PG, FS, HANA, and GitLab do not import from each other
- **Total MCP tools**: 49 across all servers (PG: 8, FS: 12, HANA: 11, GitLab: 18)

## Critical Files for Onboarding

When getting familiar with this codebase, read these files in order:

1. `src/mamba_mcp_pg/server.py` — The reference server implementation (HANA and FS were modeled from this)
2. `src/mamba_mcp_pg/tools/schema_tools.py` — Canonical tool handler pattern used by all 49 tools
3. `src/mamba_mcp_core/errors.py` — Shared `ToolError` model with dependency-injected suggestions
4. `src/mamba_mcp_fs/security.py` — Most security-critical file, defense-in-depth path validation
5. `src/mamba_mcp_fs/backends/base.py` — `BackendProtocol` + `BackendManager` routing pattern
6. `src/mamba_mcp_client/client.py` — `MCPTestClient` async context manager

## Creating a New MCP Server Module

Use `mamba_mcp_pg` as the template. A new server module needs:

1. `src/mamba_mcp_<name>/` — New module directory under `src/`
2. `__main__.py` — Copy PG's pattern: Typer app with `invoke_without_command=True`, bare command starts server, `test` subcommand validates connectivity
3. `server.py` — `@dataclass AppContext` + `app_lifespan()` + `mcp = FastMCP(name, lifespan=...)`
4. `config.py` — Nested Pydantic BaseSettings with `@model_validator(mode="before")` for env file bridging
5. `errors.py` — `ErrorCode` class + `ERROR_SUGGESTIONS` dict + `create_tool_error()` wrapper
6. `models/` — Input/Output model pairs with `Field(description="...")`
7. `database/` or `backends/` — Service layer classes
8. `tools/` — `@mcp.tool()` handlers following the 7-step skeleton
9. `tests/<name>/` — Class-based tests, autouse fixtures for config state reset
10. `pyproject.toml` — Add new extra in `[project.optional-dependencies]`, add entry point in `[project.scripts]`, add to `[tool.hatch.build.targets.wheel]` packages list

## Key Patterns to Follow

### Server Module Pattern (pg, fs, hana, gitlab)

When creating or modifying MCP server modules, follow these established patterns:

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
- **Test paths:** `tests/{core,client,pg,fs,hana,gitlab}/` — each module has its own test subdirectory
- **Cross-file imports:** Use `from tests.<suite>.conftest import <helper>` (e.g., `from tests.pg.conftest import create_mock_result`)
- **Parametrize:** Use `@pytest.mark.parametrize` for 3+ similar test cases
- **Autouse fixtures:** Reset module-level state (`set_env_file_path(None)`) to prevent leakage
- **Mock helpers:** `create_mock_result()` in per-suite conftest.py for SQLAlchemy row mocking
- **Async tests:** `asyncio_mode = "auto"` in root pyproject.toml — no need for `@pytest.mark.asyncio`
- **Coverage target:** Security-critical modules target 100% coverage

## Known Inconsistencies

- **Error return types:** `mamba_mcp_pg` `create_tool_error()` returns `dict[str, Any]`, `mamba_mcp_hana` returns `ToolError` model instance, `mamba_mcp_fs` uses custom exception hierarchy (`FSError` base). All share the core `ToolError` model via `mamba_mcp_core`; the wrapper functions preserve each server's existing return type contract.
- **FS error architecture:** FS intentionally keeps its custom exception hierarchy (`FSError` base + 9 subclasses) for internal backend flow control — a pattern the DB servers don't need.

### Resolved Inconsistencies

The following have been standardized:
- ~~Module name~~ — `mamba-mcp-hana` now maps to `mamba_mcp_hana` (1:1 like other modules)
- ~~Tool return types~~ — All servers now return `OutputModel | dict[str, Any]` (HANA migrated from `str`)
- ~~Fuzzy matching thresholds~~ — All servers use `mamba_mcp_core`'s scaled threshold: `max(2, min(len//2, 5))`
- ~~Transport naming~~ — All servers accept both `"http"` and `"streamable-http"`, normalized via core
- ~~Code duplication~~ — CLI helpers, config state, errors, and fuzzy matching consolidated in `mamba_mcp_core`
- ~~Package structure~~ — Consolidated from 6 separate PyPI packages into single `mamba-mcp` package with extras

## CI/CD Notes

- **Pipeline**: `.github/workflows/ci.yml` runs lint, type-check, and test jobs in parallel
- **Test matrix**: Per-suite isolation via `uv run pytest tests/${{ matrix.suite }}/` (core, client, pg, fs, hana, gitlab)
- **Client test coverage**: Minimal — only `test_client.py` exists; CLI commands and TUI lack tests

## Versioning & Release Process

Single version derived from git tags via **hatch-vcs**.

- **Version source of truth**: Git tags (e.g., `v0.1.0`)
- **Dynamic versioning**: `pyproject.toml` uses `dynamic = ["version"]` with `hatch-vcs`
- **`_version.py` file**: Auto-generated at build time at `src/mamba_mcp_core/_version.py`, gitignored — do not commit
- **Version sharing**: All 5 other modules import version from `mamba_mcp_core._version`
- **Dev version fallback**: `__init__.py` files fall back to `"0.0.0.dev0"` when `_version.py` doesn't exist (editable installs)

### How to Release

1. Update `CHANGELOG.md` — move items from `[Unreleased]` to a new version section
2. Create an annotated tag: `git tag -a v0.2.0 -m "Release v0.2.0"`
3. Push the tag: `git push origin v0.2.0`
4. GitHub Actions handles the rest: **build** → **TestPyPI** → **PyPI** → **GitHub Release**

### Release Pipeline (`.github/workflows/release.yml`)

- Triggered by `v*` tags pushed to the repository
- Builds single package with `uv build`
- Publishes to TestPyPI first (gate), then PyPI, then creates a GitHub Release
- Uses OIDC trusted publishing (no API tokens needed — configured in PyPI/TestPyPI settings)

## Code Standards

- Python 3.11+
- Line length: 100 (Ruff)
- MyPy strict mode with `mypy_path = "src"`
- pytest asyncio auto mode
- Ruff rules: E, F, I, N, W, UP
