# mamba-mcp-hana

SAP HANA MCP Server with layered schema discovery for AI assistants.

## Features

- **Layer 1: Schema Discovery** -- List schemas, tables, describe columns, sample rows
- **Layer 2: Relationship Discovery** -- Foreign keys, join path finding (BFS)
- **Layer 3: Query Execution** -- Read-only SQL with parameterized queries and EXPLAIN support
- **HANA-Specific Tools** -- Calculation views, column/row store type, stored procedures

## Overview

mamba-mcp-hana provides a Model Context Protocol (MCP) server for SAP HANA databases. It follows a 3-layer progressive disclosure architecture with additional HANA-specific tools, giving AI agents structured, safe, read-only access to SAP HANA databases.

**11 tools** across 4 layers:
- 4 schema discovery tools (Layer 1)
- 2 relationship discovery tools (Layer 2)
- 2 query execution tools (Layer 3)
- 3 HANA-specific tools

Supports both **SAP HANA Cloud** and **on-premise** environments with a unified configuration system.

## Installation

### From the monorepo (development)

```bash
uv sync --group dev
```

### As a standalone package

```bash
uv add mamba-mcp-hana
```

### Dependencies

- `hdbcli` -- SAP's official Python driver for HANA
- `mcp>=1.0.0` -- Model Context Protocol (FastMCP)
- `pydantic>=2.0.0` / `pydantic-settings>=2.0.0` -- Configuration and validation
- `typer>=0.12.0` -- CLI framework

## Configuration

Set via environment variables (prefix: `MAMBA_MCP_HANA_`) or a `mamba.env` file.

Default file locations (checked in order):
1. `./mamba.env` (project-local)
2. `~/mamba.env` (global fallback)

### Environment Variable Reference

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `MAMBA_MCP_HANA_DB_HOST` | str | `localhost` | HANA server hostname |
| `MAMBA_MCP_HANA_DB_PORT` | int | `30015` | HANA server port |
| `MAMBA_MCP_HANA_DB_NAME` | str | -- | Tenant database name (optional, for tenant routing) |
| `MAMBA_MCP_HANA_DB_USER` | str | *required** | Database username |
| `MAMBA_MCP_HANA_DB_PASSWORD` | SecretStr | *required** | Database password |
| `MAMBA_MCP_HANA_DB_ENCRYPT` | bool | auto-detect | Enable TLS encryption (auto-true for port 443) |
| `MAMBA_MCP_HANA_DB_SSL_VALIDATE` | bool | `true` | Validate SSL certificate |
| `MAMBA_MCP_HANA_DB_USERKEY` | str | -- | hdbuserstore key (alternative to user/password) |
| `MAMBA_MCP_HANA_POOL_SIZE` | int | `5` | Connection pool size (1-20) |
| `MAMBA_MCP_HANA_POOL_TIMEOUT` | float | `30.0` | Pool connection acquire timeout in seconds |
| `MAMBA_MCP_HANA_STATEMENT_TIMEOUT` | int | `30000` | Query timeout in milliseconds |
| `MAMBA_MCP_HANA_DEFAULT_SCHEMA` | str | -- | Default schema for tool queries |
| `MAMBA_MCP_HANA_TRANSPORT` | str | `stdio` | Server transport (`stdio` or `http`) |
| `MAMBA_MCP_HANA_SERVER_HOST` | str | `0.0.0.0` | HTTP server bind host |
| `MAMBA_MCP_HANA_SERVER_PORT` | int | `8080` | HTTP server bind port |
| `MAMBA_MCP_HANA_LOG_LEVEL` | str | `INFO` | Logging level |
| `MAMBA_MCP_HANA_LOG_FORMAT` | str | `json` | Log output format (`json` or `text`) |

*\*Authentication: Provide either `DB_USER` + `DB_PASSWORD`, or `DB_USERKEY` for hdbuserstore authentication. When both are provided, user/password takes precedence.*

## Quick Start

### HANA Cloud

```env
# mamba.env
MAMBA_MCP_HANA_DB_HOST=your-instance.hana.trial-us10.hanacloud.ondemand.com
MAMBA_MCP_HANA_DB_PORT=443
MAMBA_MCP_HANA_DB_USER=mcp_reader
MAMBA_MCP_HANA_DB_PASSWORD=SecurePassword123
# TLS is auto-enabled for port 443
```

```bash
# Test the connection
mamba-mcp-hana --env-file mamba.env test

# Start the MCP server
mamba-mcp-hana --env-file mamba.env
```

### HANA On-Premise

```env
# mamba.env
MAMBA_MCP_HANA_DB_HOST=hana-server.local
MAMBA_MCP_HANA_DB_PORT=30015
MAMBA_MCP_HANA_DB_USER=mcp_reader
MAMBA_MCP_HANA_DB_PASSWORD=SecurePassword123
MAMBA_MCP_HANA_DB_ENCRYPT=false
```

```bash
mamba-mcp-hana --env-file mamba.env test
mamba-mcp-hana --env-file mamba.env
```

### Using hdbuserstore

If SAP hdbuserstore is configured on the system, you can authenticate with a stored key instead of user/password:

```env
# mamba.env
MAMBA_MCP_HANA_DB_USERKEY=MY_HANA_KEY
```

```bash
mamba-mcp-hana --env-file mamba.env test
```

## CLI Usage

```bash
# Start the MCP server (default: stdio transport)
mamba-mcp-hana

# Start with a specific env file
mamba-mcp-hana --env-file mamba.env

# Test database connection and exit
mamba-mcp-hana test
mamba-mcp-hana --env-file mamba.env test

# Start with HTTP transport (configure via env vars)
MAMBA_MCP_HANA_TRANSPORT=http mamba-mcp-hana
```

### Using with mamba-mcp-client

```bash
# Interactive TUI
uv run --package mamba-mcp-client mamba-mcp tui --stdio "mamba-mcp-hana --env-file mamba.env"

# Direct CLI
uv run --package mamba-mcp-client mamba-mcp tools --stdio "mamba-mcp-hana --env-file mamba.env"
uv run --package mamba-mcp-client mamba-mcp call list_schemas --stdio "mamba-mcp-hana --env-file mamba.env"
```

## Tool Reference

### Layer 1: Schema Discovery

#### `list_schemas`

List all database schemas in the SAP HANA instance.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `include_system` | bool | `false` | Include system schemas (`_SYS_*`, `SYS`, `SYSTEM`) |

```json
{
  "schemas": [
    {
      "name": "MY_SCHEMA",
      "owner": "SYSTEM",
      "table_count": 42
    }
  ],
  "count": 1
}
```

---

#### `list_tables`

List all tables and views in a specific SAP HANA schema.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `schema_name` | str | *required* | Schema to list tables from |
| `include_views` | bool | `true` | Include views in the listing |
| `name_pattern` | str \| null | `null` | SQL LIKE pattern to filter names (e.g., `USER%`) |

```json
{
  "tables": [
    {
      "name": "ORDERS",
      "type": "TABLE",
      "record_count": 15000,
      "column_count": 12,
      "store_type": "COLUMN",
      "is_column_table": true
    }
  ],
  "schema_name": "MY_SCHEMA",
  "count": 15
}
```

---

#### `describe_table`

Get detailed structure of a SAP HANA table or view including columns, indexes, and constraints.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `table_name` | str | *required* | Name of the table or view |
| `schema_name` | str | *required* | Schema containing the table |
| `include_indexes` | bool | `true` | Include index information |
| `include_constraints` | bool | `true` | Include constraint information |

```json
{
  "table_name": "ORDERS",
  "schema_name": "MY_SCHEMA",
  "is_view": false,
  "columns": [
    {
      "name": "ORDER_ID",
      "data_type": "INTEGER",
      "length": null,
      "scale": null,
      "nullable": false,
      "default_value": null,
      "position": 1,
      "comment": "Primary key"
    }
  ],
  "indexes": [...],
  "constraints": [...]
}
```

---

#### `get_sample_rows`

Retrieve sample rows from a SAP HANA table.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `table_name` | str | *required* | Name of the table to sample |
| `schema_name` | str | *required* | Schema containing the table |
| `limit` | int | `10` | Number of rows to retrieve (1-100) |
| `columns` | list[str] \| null | `null` | Specific columns to include (null for all) |
| `where_clause` | str \| null | `null` | WHERE clause without the `WHERE` keyword |
| `randomize` | bool | `false` | Randomize row selection via `ORDER BY RAND()` |

```json
{
  "table_name": "ORDERS",
  "schema_name": "MY_SCHEMA",
  "columns": ["ORDER_ID", "CUSTOMER_ID", "ORDER_DATE", "TOTAL"],
  "rows": [
    [1001, 42, "2025-01-15", 299.99],
    [1002, 17, "2025-01-16", 149.50]
  ],
  "row_count": 2,
  "total_count": 15000
}
```

---

### Layer 2: Relationship Discovery

#### `get_foreign_keys`

Get foreign key relationships for a table (both outgoing and incoming).

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `table_name` | str | *required* | Name of the table to inspect |
| `schema_name` | str | *required* | Schema containing the table |

**Note:** SAP HANA row store tables do not support foreign key constraints. If the table uses row store, results may be empty.

```json
{
  "table_name": "ORDERS",
  "schema_name": "SALES",
  "outgoing": [
    {
      "constraint_name": "FK_ORDER_CUSTOMER",
      "source_schema": "SALES",
      "source_table": "ORDERS",
      "source_columns": ["CUSTOMER_ID"],
      "target_schema": "SALES",
      "target_table": "CUSTOMERS",
      "target_columns": ["ID"],
      "delete_rule": "RESTRICT"
    }
  ],
  "incoming": [...],
  "outgoing_count": 1,
  "incoming_count": 2
}
```

---

#### `find_join_path`

Find join paths between two tables via foreign key relationships using BFS.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `from_table` | str | *required* | Starting table name |
| `to_table` | str | *required* | Target table name |
| `from_schema` | str | *required* | Schema of the starting table |
| `to_schema` | str \| null | `null` | Schema of the target table (defaults to `from_schema`) |
| `max_depth` | int | `4` | Maximum number of joins to traverse (1-6) |

```json
{
  "from_table": "ORDER_ITEMS",
  "to_table": "CUSTOMERS",
  "paths": [
    {
      "steps": [
        {
          "from_schema": "SALES",
          "from_table": "ORDER_ITEMS",
          "to_schema": "SALES",
          "to_table": "ORDERS",
          "join_columns": {"ITEM_ORDER_ID": "ORDER_ID"},
          "direction": "outgoing"
        },
        {
          "from_schema": "SALES",
          "from_table": "ORDERS",
          "to_schema": "SALES",
          "to_table": "CUSTOMERS",
          "join_columns": {"CUSTOMER_ID": "ID"},
          "direction": "outgoing"
        }
      ],
      "length": 2,
      "sql_join": "SELECT ... FROM \"SALES\".\"ORDER_ITEMS\" JOIN ..."
    }
  ],
  "path_count": 1
}
```

---

### Layer 3: Query Execution

#### `execute_query`

Execute a read-only SQL query against SAP HANA.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `sql` | str | *required* | SQL SELECT query (use `?` for positional or `:name` for named params) |
| `params` | dict \| list \| null | `null` | Bind parameter values |
| `limit` | int | `1000` | Maximum rows to return (1-10000) |
| `timeout_ms` | int \| null | `null` | Query timeout in milliseconds (uses server default if not set) |

**Security:** Only `SELECT` and `WITH...SELECT` queries are allowed. `INSERT`, `UPDATE`, `DELETE`, `DROP`, `CREATE`, `ALTER`, `TRUNCATE`, `GRANT`, `REVOKE`, and other write operations are blocked.

```json
{
  "result": {
    "columns": ["ORDER_ID", "TOTAL"],
    "rows": [[1001, 299.99], [1002, 149.50]],
    "row_count": 2,
    "truncated": false,
    "warning": null,
    "execution_time_ms": 45.2
  },
  "query_hash": "a1b2c3d4"
}
```

---

#### `explain_query`

Get the execution plan for a SQL query using HANA's EXPLAIN PLAN mechanism.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `sql` | str | *required* | SQL query to explain (SELECT/WITH only) |
| `params` | dict \| list \| null | `null` | Bind parameter values for accurate cost estimates |
| `format` | str | `"text"` | Output format (`"text"` or `"json"`) |

This tool transparently handles HANA's write-read-cleanup cycle for EXPLAIN_PLAN_TABLE.

```json
{
  "plan": [
    {
      "operator_name": "COLUMN TABLE SCAN",
      "table_name": "ORDERS",
      "schema_name": "SALES",
      "cost": 150.0,
      "cardinality": 15000,
      "details": "FILTER CONDITION: TOTAL > 100"
    }
  ],
  "format": "text"
}
```

---

### HANA-Specific Tools

#### `list_calculation_views`

List calculation views (CALC, JOIN, OLAP types) in a SAP HANA schema.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `schema_name` | str | *required* | Schema to list calculation views from |
| `include_columns` | bool | `false` | Include column metadata for each view |

**Note:** Accessing data through calculation views may require analytic privileges. Views are listed based on metadata visibility, but data queries may fail without the required privileges.

```json
{
  "views": [
    {
      "name": "CV_SALES_ANALYSIS",
      "view_type": "CALC",
      "is_valid": true,
      "column_count": 8,
      "columns": []
    }
  ],
  "schema_name": "MY_SCHEMA",
  "count": 5
}
```

---

#### `get_table_store_type`

Get the storage type (COLUMN or ROW) for a SAP HANA table.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `table_name` | str | *required* | Name of the table to check |
| `schema_name` | str | *required* | Schema containing the table |

Returns store type with partitioning information, compression status, and implications explaining how the store type affects query optimization and feature support.

```json
{
  "store_info": {
    "table_name": "ORDERS",
    "schema_name": "SALES",
    "store_type": "COLUMN",
    "is_partitioned": true,
    "partition_count": 4,
    "is_compressed": true,
    "implications": "Column store: Optimized for analytical queries, aggregations, and large scans. Supports foreign key constraints. Data is compressed by default."
  }
}
```

---

#### `list_procedures`

List stored procedures in a SAP HANA schema.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `schema_name` | str | *required* | Schema to list procedures from |
| `include_parameters` | bool | `false` | Include parameter details for each procedure |

```json
{
  "procedures": [
    {
      "name": "CALCULATE_TOTALS",
      "procedure_type": "SQLSCRIPT",
      "is_read_only": true,
      "parameter_count": 3,
      "parameters": []
    }
  ],
  "schema_name": "MY_SCHEMA",
  "count": 3
}
```

When `include_parameters=true`, each procedure includes parameter details:

```json
{
  "parameters": [
    {
      "name": "IN_SCHEMA",
      "data_type": "NVARCHAR",
      "direction": "IN"
    },
    {
      "name": "OUT_RESULT",
      "data_type": "TABLE",
      "direction": "OUT"
    }
  ]
}
```

---

## Security

### Read-Only Enforcement

mamba-mcp-hana enforces read-only access at multiple levels:

1. **Query validation**: All SQL is checked against a blocked keyword list (INSERT, UPDATE, DELETE, DROP, CREATE, ALTER, TRUNCATE, GRANT, REVOKE, etc.) using case-insensitive word boundary matching.
2. **SELECT/WITH enforcement**: Queries must start with `SELECT` or `WITH`.
3. **Comment/string stripping**: SQL comments and string literals are stripped before keyword detection to prevent bypass via `-- INSERT` comments or `'DELETE'` string literals.
4. **Parameterized queries**: All user-supplied values are passed via hdbcli parameterized queries, never string interpolation.
5. **Credential protection**: `DB_PASSWORD` is stored as Pydantic `SecretStr`, never logged or serialized.

### Recommended HANA User Setup

Create a restricted database user with minimal privileges for the MCP server:

```sql
-- Create restricted user with minimal privileges
CREATE RESTRICTED USER mcp_reader PASSWORD 'SecurePassword123';
ALTER USER mcp_reader ENABLE CLIENT CONNECT;

-- Grant metadata access (read-only, all system views)
GRANT CATALOG READ TO mcp_reader;

-- Grant SELECT on specific schemas
GRANT SELECT ON SCHEMA MY_SCHEMA TO mcp_reader;

-- For ODBC/JDBC connectivity (required for some connection methods)
GRANT RESTRICTED_USER_ODBC_ACCESS TO mcp_reader;
```

**Key points:**
- `RESTRICTED USER` prevents any DDL or DML operations at the database level
- `CATALOG READ` grants read-only access to system views (needed for schema discovery)
- Grant `SELECT` only on schemas that the AI agent should be able to query
- Replace `MY_SCHEMA` with your actual schema names; repeat for each schema

## HANA Cloud vs On-Premise

| Aspect | HANA Cloud | On-Premise |
|--------|------------|------------|
| Default port | `443` | `3NN15` (e.g., `30015` for instance 00) |
| TLS encryption | Always required (auto-detected) | Optional (configurable) |
| Connection | Public endpoint | Private network |
| hdbuserstore | Not typically used | Common for automated access |
| Configuration example | `DB_PORT=443` (TLS auto-enabled) | `DB_PORT=30015`, `DB_ENCRYPT=false` |

**Port convention for on-premise**: The port follows the pattern `3<instance_number>15` for the indexserver. For example:
- Instance 00: port `30015`
- Instance 01: port `30115`
- Instance 02: port `30215`

**TLS auto-detection**: When `DB_PORT=443`, TLS encryption is automatically enabled without setting `DB_ENCRYPT=true`. For on-premise with TLS, set `DB_ENCRYPT=true` explicitly.

## Architecture

```
MCP Protocol Layer (FastMCP)
    |
    v
Tools Layer (11 tools across 4 layers)
    |-- Layer 1: list_schemas, list_tables, describe_table, get_sample_rows
    |-- Layer 2: get_foreign_keys, find_join_path
    |-- Layer 3: execute_query, explain_query
    |-- HANA:    list_calculation_views, get_table_store_type, list_procedures
    |
    v
Service Layer
    |-- SchemaService      (SYS.SCHEMAS, SYS.TABLES, SYS.VIEWS, SYS.TABLE_COLUMNS, ...)
    |-- RelationshipService (SYS.REFERENTIAL_CONSTRAINTS, BFS pathfinding)
    |-- QueryService       (SQL validation, execution, EXPLAIN PLAN)
    |-- HanaService        (SYS.VIEWS calc views, SYS.TABLES store type, SYS.PROCEDURES)
    |
    v
Connection Pool (async queue-based, wraps hdbcli connections)
    |
    v
hdbcli (synchronous PEP 249 driver) --> SAP HANA Database
```

### Key Design Decisions

- **hdbcli + asyncio.to_thread()**: SAP's official `hdbcli` driver is synchronous. All database calls are wrapped with `asyncio.to_thread()` for non-blocking async execution.
- **Queue-based pool**: Uses `asyncio.Queue` for connection management with health checks via `SELECT 1 FROM DUMMY`.
- **No SQLAlchemy**: Unlike mamba-mcp-postgres, HANA uses hdbcli directly because `sqlalchemy-hana` adds complexity without benefit for read-only system view queries.
- **Service-per-layer**: Each tool layer has a dedicated service class that encapsulates database query logic and error handling.
- **Union return types**: Services return `Output | ToolError` rather than raising exceptions, enabling clean error handling at the tool layer.
