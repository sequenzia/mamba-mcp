# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] - 2026-02-10

### Added

- **mamba-mcp-core** - Shared utilities package for all MCP servers:
  - `ToolError` Pydantic model with `create_tool_error()` factory
  - Levenshtein distance fuzzy matching via `find_similar_names()`
  - CLI helpers: `validate_env_file()`, `resolve_default_env_file()`, `setup_logging()`
  - Module-level config state management (`set_env_file_path()` / `get_env_file_path()`)
  - Transport normalization (`"http"` / `"streamable-http"` → canonical form)
- **mamba-mcp-client** - MCP testing and debugging tool:
  - `MCPTestClient` async context manager for programmatic server testing
  - Textual-based TUI for interactive server exploration
  - Typer CLI with `connect`, `tools`, `call`, and `tui` commands
  - Transport support: STDIO, SSE, HTTP, UV installed packages, UV local paths
  - `ClientConfig` factory methods: `for_stdio()`, `for_sse()`, `for_http()`, `for_uv_installed()`, `for_uv_local()`
- **mamba-mcp-pg** - PostgreSQL MCP server (8 tools across 3 layers):
  - Layer 1 (Schema Discovery): `list_schemas`, `list_tables`, `describe_table`, `get_sample_rows`
  - Layer 2 (Relationships): `get_foreign_keys`, `find_join_path` (BFS pathfinding)
  - Layer 3 (Query Execution): `execute_query`, `explain_query` (read-only, parameterized)
  - Query security with blocked keyword validation and SELECT/WITH-only enforcement
  - SQLAlchemy async services with asyncpg driver
- **mamba-mcp-fs** - Filesystem MCP server (12 tools across 3 layers):
  - Layer 1 (Discovery): `list_directory`, `get_file_info`, `read_file`, `search_files`
  - Layer 2 (S3 Extras): `list_buckets`, `get_presigned_url`, `get_object_metadata`
  - Layer 3 (Mutation): `write_file`, `delete_file`, `move_file`, `copy_file`, `create_directory`
  - Dual backends: `LocalBackend` (fsspec) and `S3Backend` (s3fs) via `BackendManager`
  - Security: sandbox enforcement, path traversal prevention, symlink/hidden file policies
  - Sliding window rate limiter
- **mamba-mcp-hana** - SAP HANA MCP server (11 tools across 4 layers):
  - Layer 1-3: Same schema discovery, relationship, and query tools as PG
  - Layer 4 (HANA-Specific): `list_calculation_views`, `get_table_store_type`, `list_procedures`
  - Async queue-based connection pool wrapping synchronous hdbcli driver
  - Auth: user/password or hdbuserstore key; TLS auto-enabled for port 443 (HANA Cloud)
- **mamba-mcp-gitlab** - GitLab MCP server (18 tools across 4 categories):
  - Merge Requests (7): `list_mrs`, `get_mr`, `get_mr_diffs`, `get_mr_commits`, `get_mr_pipelines`, `create_mr`, `update_mr`
  - Issues (6): `list_issues`, `get_issue`, `list_issue_comments`, `create_issue`, `update_issue`, `add_issue_comment`
  - Pipelines (4): `list_pipelines`, `get_pipeline`, `get_pipeline_jobs`, `get_job_log`
  - Search (1): `search` with instance/project/group scoping
  - Auth strategies: PAT and OAuth 2.0 (client credentials with token refresh)
  - Read-only mode with runtime gating on write tools
  - Sliding window rate limiter
- CI/CD pipeline with lint, type-check, and per-package test matrix
- MkDocs documentation site

[Unreleased]: https://github.com/sequenzia/mamba-mcp/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/sequenzia/mamba-mcp/releases/tag/v0.1.0
