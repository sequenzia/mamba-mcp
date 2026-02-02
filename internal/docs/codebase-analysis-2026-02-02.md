# Codebase Analysis Report

**Analysis Context**: General codebase understanding
**Codebase Path**: `/Users/sequenzia/dev/repos/mamba-mcp`
**Date**: 2026-02-02

---

## Executive Summary

Mamba MCP is an exceptionally well-architected UV workspace monorepo where three MCP servers (PostgreSQL, SAP HANA, Filesystem) share a common structural template -- same lifespan pattern, same tool handler skeleton, same config approach -- with intentional divergences only where domain requirements demand it. The most critical finding is a **test coverage gap in the client package**: the primary user-facing tool (`mamba-mcp-client`) has minimal tests and is excluded from CI entirely, while the server packages are thoroughly tested. The strongest architectural achievement is the consistent **7-step tool handler skeleton** used across all 31 MCP tools, making it trivial to add new tools to any server.

---

## Architecture Overview

The monorepo follows a **hub-and-spokes model** with `mamba-mcp-core` as the shared hub and three server packages as spokes. The client stands fully independent.

```
                    +--------------------+
                    |  mamba-mcp-core    |
                    |  (shared utils)    |
                    +--------+-----------+
                 +-----------+-----------+
                 v           v           v
          +----------+ +----------+ +----------+
          | mamba-   | | mamba-   | | mamba-   |
          | mcp-pg   | | mcp-fs   | | mcp-hana |
          +----------+ +----------+ +----------+

          +----------------+
          | mamba-mcp-     |
          | client         |
          | (independent)  |
          +----------------+
```

**Design Philosophy**: All three servers follow an identical internal layering:

```
__main__.py (Typer CLI)
  -> server.py (FastMCP + AppContext lifespan)
    -> tools/ (MCP tool handlers by layer)
      -> database/ or backends/ (service layer)
        -> models/ (Pydantic I/O contracts)
```

The **layered tool architecture** is designed for AI agent exploration -- tools progress from discovery (Layer 1) to relationships (Layer 2) to execution/mutation (Layer 3) to platform-specific (Layer 4, HANA only). This guides an AI assistant from broad understanding to targeted actions.

**Key technologies**: Python 3.11+, FastMCP (MCP SDK), Pydantic/Pydantic-Settings, Typer, SQLAlchemy async (PG), hdbcli (HANA), fsspec/s3fs (FS), Textual (client TUI).

---

## Critical Files

| File | Purpose | Relevance |
|------|---------|-----------|
| `pyproject.toml` (root) | Workspace config, shared tooling (ruff, mypy, pytest) | High |
| `packages/mamba-mcp-core/src/mamba_mcp_core/errors.py` | Shared `ToolError` model + factory with suggestion injection | High |
| `packages/mamba-mcp-core/src/mamba_mcp_core/config.py` | Module-level env file path state bridge | High |
| `packages/mamba-mcp-core/src/mamba_mcp_core/fuzzy.py` | Levenshtein distance + `find_similar_names()` | High |
| `packages/mamba-mcp-pg/src/mamba_mcp_pg/server.py` | PG FastMCP server -- the *template* other servers were built from | High |
| `packages/mamba-mcp-pg/src/mamba_mcp_pg/tools/schema_tools.py` | Canonical tool handler pattern (all 31 tools follow this) | High |
| `packages/mamba-mcp-fs/src/mamba_mcp_fs/security.py` | Path validation, sandbox enforcement -- most security-critical file | High |
| `packages/mamba-mcp-fs/src/mamba_mcp_fs/backends/base.py` | `BackendProtocol` + `BackendManager` routing | High |
| `packages/mamba-mcp-hana/src/mamba_mcp_hana/database/connection.py` | Custom async pool wrapping sync hdbcli (~313 lines) | Medium |
| `packages/mamba-mcp-client/src/mamba_mcp_client/client.py` | `MCPTestClient` async context manager | High |

### File Details

#### `packages/mamba-mcp-core/src/mamba_mcp_core/errors.py`
- **Key exports**: `ToolError` (Pydantic BaseModel), `create_tool_error()` factory
- **Core logic**: Factory accepts a `suggestions_map` dict -- each server injects its own `ERROR_SUGGESTIONS` without the core knowing about specific error codes
- **Connections**: PG `errors.py` wraps it and returns `dict[str, Any]` via `.model_dump()`, HANA `errors.py` wraps and returns `ToolError` directly

#### `packages/mamba-mcp-pg/src/mamba_mcp_pg/server.py`
- **Key exports**: `AppContext` dataclass, `app_lifespan()`, `mcp` instance
- **Core logic**: Lifespan creates SQLAlchemy async engine, tests connectivity, yields context, disposes on shutdown. Failure causes `SystemExit(1)`.
- **Connections**: This is the *template* -- HANA and FS server.py files were explicitly modeled after this

#### `packages/mamba-mcp-fs/src/mamba_mcp_fs/security.py`
- **Key exports**: `SecurityValidator` with `validate_local_path()`, `check_extension()`, `check_file_size()`, `check_symlink()`, `filter_hidden()`
- **Core logic**: Defense-in-depth path sanitization pipeline: repeated URL decode -> null byte strip -> unicode normalize -> resolve -> sandbox prefix check with trailing `/` to prevent `/sandbox-other` matching `/sandbox`
- **Connections**: Called by `LocalBackend` on every file operation, targets 100% test coverage

---

## Patterns & Conventions

### Code Patterns

- **AppContext via Lifespan**: `@dataclass AppContext` + `@asynccontextmanager app_lifespan()` + `FastMCP(name, lifespan=...)`. Used identically across all three servers.
- **7-Step Tool Handler**: `time.perf_counter()` -> null-check `ctx` -> extract `app_ctx` -> acquire connection -> delegate to service -> wrap in Pydantic output -> catch exception and return structured error. All 31 tools follow this.
- **Nested Pydantic Settings**: Root `Settings` uses `@model_validator(mode="before")` to instantiate nested classes with `_env_file` parameter. Each nested class has its own `env_prefix`.
- **Error Handling Triad**: `ErrorCode` constants + `ERROR_SUGGESTIONS` dict + `create_tool_error()` wrapper per server.
- **Input/Output Model Pairs**: Every tool has `XInput` + `XOutput` Pydantic models with `Field(description="...")`.

### Naming Conventions

- **Packages**: `mamba-mcp-{name}` -> `mamba_mcp_{name}` (1:1 mapping)
- **Settings env prefixes**: `MAMBA_MCP_PG_`, `MAMBA_MCP_FS_`, `MAMBA_MCP_HANA_`
- **Models**: `ListSchemasInput/Output`, `DescribeTableInput/Output` (verb + noun + Input/Output)
- **Error codes**: `SCREAMING_SNAKE_CASE` string constants

### Intentional Divergences

| Area | PG/HANA Pattern | FS Pattern | Reason |
|------|-----------------|------------|--------|
| Tool registration | Import side-effects (`# noqa: F401`) | Explicit `_register_tools(mcp, settings)` | FS needs conditional registration (S3 enabled? read-only?) |
| Error handling | Core `ToolError` model + wrapper | Custom exception hierarchy (`FSError` + 9 subclasses) | FS uses try/except for internal flow control in backends |
| Error return type | PG: `dict[str, Any]`, HANA: `ToolError` | `dict[str, Any]` (different shape) | Historical; documented as intentional |
| Async driver | asyncpg (native async) / hdbcli + `asyncio.to_thread()` | fsspec (synchronous, but fast) | Driver availability dictates pattern |

---

## Relationship Map

**Data flow within each server (request handling):**
```
Client request
  -> FastMCP routes to @mcp.tool() handler
    -> Handler extracts AppContext from ctx.request_context.lifespan_context
      -> Handler opens connection (engine.connect() or pool.acquire())
        -> Handler delegates to Service class (SchemaService, QueryService, etc.)
          -> Service executes query/operation
        -> Handler wraps result in Pydantic OutputModel
      -> Handler catches errors, returns structured ToolError
    -> FastMCP serializes response back to client
```

**Config flow at startup:**
```
CLI --env-file arg -> validate_env_file() (core) -> set_env_file_path() (core)
  -> get_settings() reads get_env_file_path() -> passes _env_file to nested settings
    -> Pydantic reads .env file + environment variables -> validates all settings
      -> app_lifespan() uses settings to create engine/pool/backends
```

**Core's connections to servers:**
```
core.config    --- set/get_env_file_path() ---> all server config.py
core.cli       --- validate_env_file() -------> all server __main__.py
core.cli       --- setup_logging() -----------> all server __main__.py
core.errors    --- create_tool_error() -------> PG errors.py, HANA errors.py
core.fuzzy     --- find_similar_names() ------> PG errors.py, HANA errors.py (re-exported)
core.transport --- normalize_transport() -----> all server __main__.py
```

---

## Challenges & Risks

| Challenge | Severity | Impact |
|-----------|----------|--------|
| **Client package excluded from CI** | Medium | `mamba-mcp-client` is not in the CI test matrix -- regressions in the primary user-facing tool go undetected |
| **Minimal client test coverage** | Medium | Only `test_client.py` exists; no tests for 8 CLI commands, TUI, or protocol logging |
| **Module-level config state** | Medium | `_env_file_path` global requires autouse fixtures for test isolation; forgetting the fixture in a new test file causes intermittent failures |
| **FS error responses differ structurally** | Low | FS error dicts lack `tool_name` and `input_received` fields that PG/HANA include; could affect clients consuming multiple server types |
| **Repeated CLI options in client** | Low | 10+ transport options duplicated across 8 commands (~400 lines of boilerplate); adding a new transport requires updating all 8 |

---

## Recommendations

1. **Add `mamba-mcp-client` to the CI test matrix**: A one-line change in `.github/workflows/ci.yml` to add `mamba-mcp-client` to the `matrix.package` list.

2. **Write CLI tests for the client**: The `validate_connection_options()` and `build_config()` functions in `cli.py` are pure functions that are straightforward to unit test without MCP server connections.

3. **Standardize PG tool registration**: Move PG's tool imports from `__main__.py` into `tools/__init__.py` (like HANA already does). Consistent and more predictable across servers.

4. **Consider extracting shared CLI option group in client**: The repeated transport options across 8 commands could be refactored into a shared Typer callback or decorator.

5. **Add `--cov-fail-under` to CI**: The CLAUDE.md mentions security modules target 100% coverage, but CI doesn't enforce thresholds.

---

## Analysis Methodology

- **Exploration agents**: 3 agents with focus areas: (1) application structure & entry points, (2) data models & database layers, (3) utilities & infrastructure
- **Synthesis**: Findings merged by an Opus-class synthesizer agent that read critical files in depth
- **Scope**: All 5 packages analyzed including source code, tests, CI configuration, and documentation
