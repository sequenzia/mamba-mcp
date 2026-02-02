# mamba-mcp-pg

PostgreSQL MCP Server with layered schema discovery for AI assistants.

Provides a 3-layer tool architecture designed for incremental database exploration — AI agents start with broad schema discovery, then explore relationships, and finally execute targeted queries.

## Features

- **8 MCP Tools** across 3 layers for progressive database exploration
- **Read-Only Enforcement** — Only SELECT/WITH queries allowed, 23 keyword categories blocked
- **Parameterized Queries** — Use `$1`, `$2` placeholders to prevent SQL injection
- **Fuzzy Matching** — "Did you mean?" suggestions for misspelled schema/table/column names
- **BFS Join Pathfinding** — Automatically discovers join paths between tables via foreign keys
- **Query Plans** — EXPLAIN support with optional ANALYZE for real execution timing
- **Connection Pooling** — SQLAlchemy async engine with configurable pool size and timeouts
- **Structured Errors** — Typed error codes with actionable suggestions

## Installation

Requires Python 3.11+.

```bash
pip install mamba-mcp-pg
```

## Quick Start

```bash
# Test database connection
mamba-mcp-pg --env-file mamba.env test

# Run the MCP server (stdio transport)
mamba-mcp-pg --env-file mamba.env

# Run with HTTP transport
MAMBA_MCP_PG_TRANSPORT=streamable-http mamba-mcp-pg --env-file mamba.env
```

## Configuration

Set via environment variables (prefix: `MAMBA_MCP_PG_`) or `mamba.env` file.

Default file locations (checked in order):
1. `./mamba.env` (project-local)
2. `~/mamba.env` (global fallback)

### Database Settings

| Variable | Description | Default |
|----------|-------------|---------|
| `MAMBA_MCP_PG_DB_HOST` | PostgreSQL host | `localhost` |
| `MAMBA_MCP_PG_DB_PORT` | PostgreSQL port | `5432` |
| `MAMBA_MCP_PG_DB_NAME` | Database name | *required* |
| `MAMBA_MCP_PG_DB_USER` | Database user | *required* |
| `MAMBA_MCP_PG_DB_PASSWORD` | Database password | *required* |
| `MAMBA_MCP_PG_POOL_SIZE` | Connection pool size | `5` |
| `MAMBA_MCP_PG_POOL_TIMEOUT` | Pool checkout timeout (seconds) | `30.0` |
| `MAMBA_MCP_PG_STATEMENT_TIMEOUT` | Query timeout (milliseconds) | `30000` |
| `MAMBA_MCP_PG_DEFAULT_SCHEMA` | Default schema for tools | `public` |

### Server Settings

| Variable | Description | Default |
|----------|-------------|---------|
| `MAMBA_MCP_PG_TRANSPORT` | Transport type (`stdio`, `http`, `streamable-http`) | `stdio` |
| `MAMBA_MCP_PG_SERVER_HOST` | HTTP server bind address | `0.0.0.0` |
| `MAMBA_MCP_PG_SERVER_PORT` | HTTP server port | `8080` |
| `MAMBA_MCP_PG_LOG_LEVEL` | Log level (DEBUG, INFO, WARNING, ERROR) | `INFO` |
| `MAMBA_MCP_PG_LOG_FORMAT` | Log format (`json`, `text`) | `json` |

## Tools

### Layer 1: Schema Discovery

#### `list_schemas`

List available database schemas.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `include_system` | bool | `false` | Include system schemas (`pg_*`, `information_schema`) |

#### `list_tables`

List tables and views in a schema.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `schema_name` | string | `"public"` | Schema to list tables from |
| `include_views` | bool | `true` | Include views in the listing |
| `name_pattern` | string \| null | `null` | LIKE pattern to filter names (e.g., `"user%"`) |

#### `describe_table`

Get detailed column, index, and constraint information for a table.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `table_name` | string | *required* | Table to describe |
| `schema_name` | string | `"public"` | Schema containing the table |
| `include_indexes` | bool | `true` | Include index information |
| `include_constraints` | bool | `true` | Include constraint information |

#### `get_sample_rows`

Preview data from a table with optional filtering.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `table_name` | string | *required* | Table to sample |
| `schema_name` | string | `"public"` | Schema containing the table |
| `limit` | int | `5` | Number of rows (1-100) |
| `columns` | list[string] \| null | `null` | Specific columns to include |
| `where_clause` | string \| null | `null` | WHERE clause without the `WHERE` keyword |
| `randomize` | bool | `false` | Randomize row selection |

### Layer 2: Relationship Discovery

#### `get_foreign_keys`

Get incoming and outgoing foreign key relationships for a table.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `table_name` | string | *required* | Table to inspect |
| `schema_name` | string | `"public"` | Schema containing the table |

#### `find_join_path`

Discover join paths between two tables using BFS traversal of foreign keys.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `from_table` | string | *required* | Starting table |
| `to_table` | string | *required* | Target table |
| `from_schema` | string | `"public"` | Schema of starting table |
| `to_schema` | string | `"public"` | Schema of target table |
| `max_depth` | int | `4` | Maximum joins to traverse (1-6) |

Returns join paths with example SQL JOIN clauses.

### Layer 3: Query Execution

#### `execute_query`

Execute a read-only SQL query with parameterized inputs.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `sql` | string | *required* | SQL SELECT query (use `$1`, `$2` for parameters) |
| `params` | list \| null | `null` | Parameter values matching `$1`, `$2`, etc. |
| `limit` | int | `1000` | Maximum rows to return (1-10,000) |
| `timeout_ms` | int \| null | `null` | Query timeout in milliseconds |

#### `explain_query`

Get the execution plan for a query.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `sql` | string | *required* | SQL query to explain |
| `params` | list \| null | `null` | Parameter values for accurate estimates |
| `analyze` | bool | `false` | Execute query for real timings |
| `format` | string | `"text"` | Output format (`text`, `json`, `yaml`) |
| `verbose` | bool | `false` | Include additional detail |
| `buffers` | bool | `false` | Include buffer statistics (requires `analyze`) |

## Query Security

All queries are validated before execution:

- **Allowed:** `SELECT` and `WITH ... SELECT` statements only
- **Blocked:** `INSERT`, `UPDATE`, `DELETE`, `CREATE`, `ALTER`, `DROP`, `TRUNCATE`, `GRANT`, `REVOKE`, and other mutation keywords
- **Parameterized:** Use `$1`, `$2` placeholders instead of string interpolation
- **Timeouts:** Configurable statement timeout with per-query override

## License

MIT
