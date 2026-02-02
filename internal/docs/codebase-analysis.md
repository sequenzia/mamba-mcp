# Codebase Analysis Report

**Analysis Context**: General codebase understanding of the Mamba MCP monorepo
**Codebase Path**: `/Users/sequenzia/dev/repos/mamba-mcp`
**Date**: 2026-02-01

---

## Executive Summary

Mamba MCP is a well-structured UV workspace monorepo containing four Python packages -- one MCP **client** for testing/debugging and three MCP **servers** (PostgreSQL, Filesystem, SAP HANA) -- all following a remarkably consistent "template by convention" architecture. The most important architectural insight is the **layered tool system** shared across all servers, where tools progress from discovery -> relationships/extras -> execution/mutation. The primary risk is **growing code duplication** across the three server packages (config scaffolding, error handling, Levenshtein fuzzy matching, CLI boilerplate) -- which is manageable today at 4 packages but will compound if more servers are added.

---

## Architecture Overview

The monorepo uses **UV workspace mode** with no root package -- all functionality lives in four self-contained packages under `packages/`. The design philosophy is pragmatically layered: each package owns its entire stack (CLI -> config -> server -> tools -> services -> models) with **no cross-package runtime dependencies**. Instead of a shared library, patterns are replicated via convention.

**The two package categories:**

| Category | Package | Role |
|----------|---------|------|
| **Client** | `mamba-mcp-client` (v1.0.0) | Testing tool with TUI, CLI, and Python API -- connects to *any* MCP server |
| **Server** | `mamba-mcp-pg` (v0.1.0) | PostgreSQL schema discovery + read-only query execution (8 tools, 3 layers) |
| **Server** | `mamba-mcp-fs` (v0.1.0) | Filesystem operations with local + S3 backends (12 tools, 3 layers) |
| **Server** | `mamba-mcp-hana` (v0.1.0) | SAP HANA schema discovery + HANA-specific features (11 tools, 4 layers) |

**Tech stack:** Python 3.11+, FastMCP (server SDK), Pydantic/Pydantic-Settings, Typer (CLI), Textual (TUI), SQLAlchemy+asyncpg (PostgreSQL), hdbcli (HANA), fsspec+s3fs (Filesystem). Quality enforced via Ruff (linting), MyPy strict (typing), pytest with asyncio auto mode.

---

## Critical Files

| File | Purpose | Relevance |
|------|---------|-----------|
| `pyproject.toml` (root) | UV workspace config, shared dev deps, Ruff/MyPy/pytest settings | High |
| `packages/mamba-mcp-client/src/mamba_mcp_client/client.py` | `MCPTestClient` -- async context manager wrapping fastmcp.Client | High |
| `packages/mamba-mcp-client/src/mamba_mcp_client/config.py` | `ClientConfig` with 5 factory methods for transport types | High |
| `packages/mamba-mcp-client/src/mamba_mcp_client/cli.py` | Typer CLI with 8 commands (tui, connect, tools, call, etc.) | High |
| `packages/mamba-mcp-pg/src/mamba_mcp_pg/server.py` | FastMCP + AppContext + lifespan (SQLAlchemy engine lifecycle) | High |
| `packages/mamba-mcp-pg/src/mamba_mcp_pg/config.py` | Nested Pydantic Settings blueprint (DatabaseSettings + ServerSettings) | High |
| `packages/mamba-mcp-pg/src/mamba_mcp_pg/database/queries.py` | QueryService: SQL validation, parameter conversion, timeout enforcement | High |
| `packages/mamba-mcp-fs/src/mamba_mcp_fs/server.py` | FastMCP + conditional tool registration via `_register_tools()` | High |
| `packages/mamba-mcp-fs/src/mamba_mcp_fs/security.py` | SecurityValidator: sandbox, path traversal, symlinks, extensions | High |
| `packages/mamba-mcp-fs/src/mamba_mcp_fs/backends/base.py` | BackendProtocol + BackendManager routing with security validation | High |
| `packages/mamba-mcp-hana/src/mamba_mcp_hana/database/connection.py` | HanaConnectionPool: async Queue wrapper around synchronous hdbcli | High |

### File Details

#### `client.py` -- The MCP Test Client

- **Key exports:** `MCPTestClient`, `ServerInfo`, `ToolCallResult`
- **Core logic:** `connect()` async context manager wraps `fastmcp.Client`. `_create_transport()` dispatches config to the correct transport. Each MCP operation follows: `_ensure_connected() -> log_request -> await client.method() -> log_response -> return`
- **Connections:** Used by `cli.py` (all commands), `tui/app.py` (interactive mode). Depends on `config.py` and `logging.py`

#### `server.py` (mamba-mcp-pg) -- The Server Blueprint

- **Key exports:** `mcp` (FastMCP instance), `AppContext` dataclass, `app_lifespan()` async context manager
- **Core logic:** Lifespan creates `AsyncEngine`, tests connection, yields `AppContext(engine, settings)`, disposes on shutdown
- **Connections:** Tool modules import `mcp` and register via `@mcp.tool()` decorators. `__main__.py` triggers registration via side-effect imports

#### `security.py` (mamba-mcp-fs) -- The Security Gate

- **Key exports:** `SecurityValidator`, `_sanitize_path()`
- **Core logic:** Three-stage path sanitization (URL decode -> strip null bytes -> NFC normalize). `validate_local_path()` resolves against sandbox base with trailing `/` prefix check
- **Connections:** Called by `BackendManager` for every filesystem operation. Tested with 50+ path traversal vectors (100% coverage)

#### `connection.py` (mamba-mcp-hana) -- The Async Pool Adapter

- **Key exports:** `HanaConnectionPool`, `create_pool()`, `build_connection_params()`
- **Core logic:** Manual async connection pool using `asyncio.Queue` + `asyncio.to_thread()` because hdbcli has no async driver. Health checks on every acquire
- **Connections:** Created in `app_lifespan()`, passed to all database services

---

## Patterns & Conventions

### Code Patterns

- **Layered Tool Architecture:** Tools organized into numbered layers (discovery -> relationships -> execution -> platform-specific). Layer 1 always registered; higher layers conditional on config.
- **AppContext via Lifespan:** All servers use `@dataclass class AppContext` yielded from `app_lifespan()`. Tools access via `ctx.request_context.lifespan_context`.
- **Module-level Config State:** Global `_env_file_path` bridges CLI arg parsing to config loading without threading the value through the call chain.
- **Nested Pydantic Settings:** Root `Settings` uses `@model_validator(mode="before")` to instantiate nested classes with the `_env_file` parameter.
- **Error Handling Triad:** Each server has: (a) `ErrorCode` string constants, (b) `ERROR_SUGGESTIONS` mapping, (c) `create_tool_error()` factory + Levenshtein fuzzy matching.
- **Tool Handler Skeleton:** Every tool: timing -> null-check ctx -> extract app_ctx -> open connection -> delegate to service -> convert to Pydantic output -> catch exceptions -> return structured error.
- **ToolAnnotations Metadata:** All tools declare `ToolAnnotations(readOnlyHint, destructiveHint, idempotentHint, openWorldHint)` for MCP client introspection.

### Naming Conventions

- `snake_case` for functions/variables/modules, `PascalCase` for classes, `UPPER_SNAKE` for constants
- Files: `snake_case.py` (e.g., `schema_tools.py`, `test_content.py`)
- Packages: hyphens in pyproject (`mamba-mcp-fs`), underscores in imports (`mamba_mcp_fs`)
- All packages use 1:1 name mapping (e.g., `mamba-mcp-hana` -> `mamba_mcp_hana`)

### Project Structure

- Imports follow 3-section ordering: stdlib -> third-party -> local (enforced by Ruff `I` rule)
- Tests: class-based organization, descriptive names, one-line docstrings on every test
- Models: centralized `__init__.py` with `__all__`, Input/Output pairs per tool

---

## Relationship Map

### Server Package Internal Flow (all three servers)

```
__main__.py (Typer CLI)
  --> imports server.mcp (triggers FastMCP instance creation)
  --> imports tools/* modules (triggers @mcp.tool() registration via side-effects)
  --> calls set_env_file_path() for config resolution
  --> either starts mcp.run() or runs test command

server.py (FastMCP + Lifespan)
  --> app_lifespan() reads config via get_settings()
  --> creates database/backend resources
  --> yields AppContext dataclass to tool handlers

tools/*_tools.py (MCP Tool Handlers)
  --> @mcp.tool() decorator registers with module-level mcp instance
  --> extracts AppContext via ctx.request_context.lifespan_context
  --> delegates to database/ service classes
  --> returns models/ Pydantic output or errors.create_tool_error() dict

database/*.py or backends/*.py (Service Layer)
  --> receives connection/pool from tool handler
  --> executes SQL or filesystem operations
  --> returns raw data for tool layer to convert to Pydantic models

models/*.py (I/O Contracts)
  --> Input models: Field validation, constraints, defaults
  --> Output models: serialized to JSON for MCP responses
```

### Cross-Package Relationships

```
mamba-mcp-client --> (no runtime dependency on server packages)
    Uses fastmcp.Client to connect to ANY MCP server via transport

mamba-mcp-pg, mamba-mcp-fs, mamba-mcp-hana --> (no cross-dependencies)
    All three are independent server packages sharing only patterns

pyproject.toml (root) --> ALL packages (shared dev tooling config)
```

---

## Challenges & Risks

| Challenge | Severity | Status |
|-----------|----------|--------|
| **Inconsistent error return types** | Medium | ✅ Resolved — All servers share core `ToolError` model via `mamba-mcp-core`; wrapper functions preserve each server's return type contract. |
| **Inconsistent tool return types** | Medium | ✅ Resolved — All servers now return `OutputModel \| dict[str, Any]` (HANA migrated from `str`). |
| **Code duplication across servers** | Medium | ✅ Resolved — CLI helpers, config state, errors, and fuzzy matching consolidated in `mamba-mcp-core`. |
| **Missing test coverage (mamba-mcp-pg)** | Medium | ✅ Resolved — PG now has 271 tests (was 66). Added test_config, test_errors, test_server, test_models. |
| **No CI/CD configuration** | Medium | ✅ Resolved — GitHub Actions CI with lint, type-check, and per-package test matrix. |
| **Fuzzy matching threshold inconsistency** | Low | ✅ Resolved — All servers use core's scaled threshold: `max(2, min(len//2, 5))`. |
| **Transport naming inconsistency** | Low | ✅ Resolved — All servers accept both `"http"` and `"streamable-http"`, normalized via core. |
| **Module name asymmetry** | Low | ✅ Resolved — `mamba-mcp-hana` now maps to `mamba_mcp_hana` (1:1 like other packages). |

### Remaining Considerations

- **FS error architecture:** FS intentionally keeps its custom exception hierarchy (`FSError` base + 9 subclasses) for internal backend flow control. This is a deliberate design choice, not an inconsistency.
- **Error return type contracts:** PG returns `dict[str, Any]`, HANA returns `ToolError` model. Both use the shared core model internally. Full unification would be a breaking change.

---

## Recommendations

All original recommendations have been addressed:

1. ~~Standardize error/response format~~ — Done via `mamba-mcp-core` shared model.
2. ~~Add CI/CD pipeline~~ — Done via `.github/workflows/ci.yml`.
3. ~~Increase mamba-mcp-pg test coverage~~ — Done, PG now at 271 tests.
4. ~~Shared utilities package~~ — Done, `mamba-mcp-core` created.
5. ~~Normalize transport naming~~ — Done via `normalize_transport()` in core.

---

## Analysis Methodology

- **Exploration agents**: 3 agents with focus areas: (1) Application structure, entry points, core logic; (2) Data models, tools, database services, backends, security; (3) Configuration, testing, documentation, conventions
- **Synthesis**: Findings merged via synthesizer agent with in-depth file reads of critical modules
- **Scope**: All 4 packages analyzed -- source code, tests, configuration, documentation. Excluded: `uv.lock`, `internal/images/`
