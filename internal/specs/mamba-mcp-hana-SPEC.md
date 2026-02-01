# mamba-mcp-hana PRD

**Version**: 1.0
**Author**: Stephen Sequenzia
**Date**: 2026-01-31
**Status**: Draft
**Spec Type**: New feature
**Spec Depth**: Detailed specifications

---

## 1. Executive Summary

mamba-mcp-hana is a new package in the mamba-mcp monorepo that provides a Model Context Protocol (MCP) server for SAP HANA databases. It follows the same 3-layer progressive disclosure architecture established by mamba-mcp-pg (schema discovery, relationships, query execution) while adding HANA-specific tools for calculation views, column/row store type information, and stored procedure listing. The server is strictly read-only, supports both HANA Cloud and on-premise environments, and uses SAP's official `hdbcli` driver with async wrappers.

## 2. Problem Statement

### 2.1 The Problem

AI/LLM agents and users need structured, safe access to SAP HANA databases through the Model Context Protocol. Currently, no MCP server provides layered schema discovery and read-only query execution specifically designed for SAP HANA's unique architecture (in-memory column store, system views, calculation views). Users working with HANA databases must manually write queries against `SYS.*` system views or rely on SAP-specific tooling that doesn't integrate with the MCP ecosystem.

### 2.2 Current State

- The mamba-mcp monorepo has a proven architecture for database MCP servers (mamba-mcp-pg).
- No existing MCP server targets SAP HANA specifically.
- SAP HANA users rely on SAP HANA Studio, DBeaver, or raw SQL against system views for schema exploration.
- AI agents connected to HANA must navigate HANA's unique SQL dialect and system view structure without protocol-level guidance.

### 2.3 Impact Analysis

- **Missed audience**: SAP HANA is one of the most widely deployed enterprise databases, powering SAP S/4HANA, BW/4HANA, and standalone analytics. Without HANA support, the mamba-mcp ecosystem excludes a significant segment of enterprise database users.
- **Unsafe ad-hoc access**: Without a read-only MCP server, AI agents may be given broader database credentials than necessary, increasing the risk of accidental data modification.

### 2.4 Business Value

- Extends the mamba-mcp ecosystem to SAP HANA, increasing the monorepo's coverage of enterprise databases.
- Leverages the proven 3-layer architecture, reducing design risk and development effort.
- Provides a safe, structured way for AI agents to explore and query HANA databases in enterprise environments where security is paramount.

## 3. Goals & Success Metrics

### 3.1 Primary Goals

1. Deliver a fully functional MCP server for SAP HANA with 11 tools (8 mirroring postgres + 3 HANA-specific).
2. Support both SAP HANA Cloud and on-premise environments with a unified configuration system.
3. Maintain strict read-only enforcement with multi-level security (query validation + recommended restricted user).

### 3.2 Success Metrics

| Metric | Current Baseline | Target | Measurement Method | Timeline |
|--------|------------------|--------|-------------------|----------|
| Tool count | 0 | 11 tools across 3 layers + extras | Feature completion | Phase 3 |
| Test coverage | N/A | >80% unit test coverage | pytest + coverage | Each phase |
| HANA Cloud + On-Prem support | N/A | Both environments working | Integration testing | Phase 2 |
| MyPy strict compliance | N/A | 0 type errors | `mypy --strict` | Each phase |

### 3.3 Non-Goals

- **Write operations**: No INSERT, UPDATE, DELETE, CREATE, DROP, or any DDL/DML support.
- **Calculation view data access guarantees**: Calc view data requires analytic privileges; the server lists/describes them but does not guarantee data access.
- **SAP BTP integration**: No direct integration with SAP Business Technology Platform services.
- **Real-time replication or streaming**: No CDC, trigger-based, or streaming features.
- **GUI or web interface**: CLI and MCP protocol only, consistent with other mamba-mcp packages.

## 4. User Research

### 4.1 Target Users

#### Primary Persona: AI/LLM Developer

- **Role/Description**: Developers building AI agents that need to query and understand HANA databases.
- **Goals**: Connect an AI agent to HANA, discover schema structure, execute safe read-only queries.
- **Pain Points**: HANA's unique SQL dialect, lack of `information_schema`, complex system view structure.
- **Context**: Building MCP-enabled AI applications that interact with enterprise SAP data.

#### Secondary Persona: SAP Consultant/Admin

- **Role/Description**: SAP professionals managing HANA systems who want AI-assisted database exploration.
- **Goals**: Quickly explore schemas, understand table relationships, analyze query performance.
- **Pain Points**: Manual navigation of system views, explaining database structure to stakeholders.
- **Context**: Day-to-day database administration, performance tuning, and schema documentation.

#### Tertiary Persona: Data Analyst/Engineer

- **Role/Description**: Analysts who need AI help writing queries against HANA data warehouses.
- **Goals**: Understand available data, discover join paths, execute analytical queries safely.
- **Pain Points**: Complex schema structures in SAP systems, finding the right tables for reporting.
- **Context**: Building reports, dashboards, and data pipelines from HANA source systems.

### 4.2 User Journey Map

```
[Connect to HANA] --> [Discover schemas] --> [List tables in schema] --> [Describe table structure]
       |                                            |
       v                                            v
[Execute read-only query] <-- [Find join paths] <-- [Explore foreign keys]
       |
       v
[Explain query plan] --> [Optimize and re-query]
```

**Typical flow**: User connects the MCP server to their HANA instance, explores available schemas (Layer 1), discovers relationships between tables (Layer 2), and executes queries with optional plan analysis (Layer 3). HANA-specific tools provide additional context about store types, calculation views, and procedures throughout the exploration.

## 5. Functional Requirements

### 5.1 Feature: Layer 1 — Schema Discovery (4 Tools)

**Priority**: P0 (Critical)

#### Tool: `list_schemas`

**US-001**: As an AI agent, I want to list all available schemas in a HANA database so that I can understand the database organization.

**Acceptance Criteria**:
- [ ] Returns list of schemas with name, owner, and table count
- [ ] Filters out system schemas (`_SYS_*`, `SYS`, `SYSTEM`) by default
- [ ] Accepts `include_system: bool` parameter to include system schemas
- [ ] Queries `SYS.SCHEMAS` system view
- [ ] Returns structured `ListSchemasOutput` Pydantic model

**Edge Cases**:
- User has no privilege on any schema: Return empty list with informative note
- `include_system=True`: Include all schemas, clearly marked as system schemas

---

#### Tool: `list_tables`

**US-002**: As an AI agent, I want to list all tables and views in a specific schema so that I can find relevant data sources.

**Acceptance Criteria**:
- [ ] Returns tables with name, type (TABLE/VIEW), record count, column count, and store type (COLUMN/ROW)
- [ ] Accepts `schema_name`, `include_views: bool`, and `name_pattern: str | None` parameters
- [ ] Queries `SYS.TABLES` and optionally `SYS.VIEWS` system views
- [ ] `name_pattern` supports SQL LIKE filtering
- [ ] Includes `IS_COLUMN_TABLE` indicator for each table
- [ ] Returns structured `ListTablesOutput` Pydantic model

**Edge Cases**:
- Schema does not exist: Return structured error with `SCHEMA_NOT_FOUND` code and fuzzy-match suggestions
- Schema exists but user has no SELECT privilege: Return empty list with note

---

#### Tool: `describe_table`

**US-003**: As an AI agent, I want to see a table's full structure (columns, indexes, constraints) so that I can understand the data model.

**Acceptance Criteria**:
- [ ] Returns columns with name, data type, length, scale, nullability, default value, position, and comments
- [ ] Returns indexes with name, columns, uniqueness, and type
- [ ] Returns constraints with name, type (PK/UNIQUE/CHECK), and columns
- [ ] Accepts `table_name`, `schema_name`, `include_indexes: bool`, `include_constraints: bool` parameters
- [ ] Queries `SYS.TABLE_COLUMNS`, `SYS.INDEXES`, `SYS.INDEX_COLUMNS`, and `SYS.CONSTRAINTS`
- [ ] Validates table existence before querying details

**Edge Cases**:
- Table does not exist: Return `TABLE_NOT_FOUND` error with fuzzy-match suggestions
- View instead of table: Still describe columns (from `SYS.VIEW_COLUMNS`), skip indexes/constraints

---

#### Tool: `get_sample_rows`

**US-004**: As an AI agent, I want to retrieve sample rows from a table so that I can understand data patterns, formats, and values.

**Acceptance Criteria**:
- [ ] Returns sample rows with column names and values
- [ ] Accepts `table_name`, `schema_name`, `limit` (1-100), `columns` (optional list), `where_clause` (optional), `randomize: bool`
- [ ] Uses `LIMIT` clause for row limiting
- [ ] Supports column selection for wide tables
- [ ] Supports optional WHERE clause filtering
- [ ] Reports total table row count alongside returned rows

**Edge Cases**:
- Empty table: Return empty rows with `row_count: 0` and note
- Wide table with 100+ columns and no column filter: Return all columns but warn about width
- Invalid column name: Return `COLUMN_NOT_FOUND` error with suggestions

---

### 5.2 Feature: Layer 2 — Relationship Discovery (2 Tools)

**Priority**: P0 (Critical)

#### Tool: `get_foreign_keys`

**US-005**: As an AI agent, I want to discover foreign key relationships for a table so that I can understand how tables are connected.

**Acceptance Criteria**:
- [ ] Returns both outgoing (this table references others) and incoming (others reference this table) foreign keys
- [ ] Includes constraint name, source/target schema, table, columns, and delete rule
- [ ] Queries `SYS.REFERENTIAL_CONSTRAINTS` system view
- [ ] Returns separate counts for outgoing and incoming relationships

**Edge Cases**:
- Row store table: Foreign keys not supported on row store; return empty results with note explaining this HANA limitation
- Table with no foreign keys: Return empty lists with note (common in SAP operational schemas)

---

#### Tool: `find_join_path`

**US-006**: As an AI agent, I want to find possible join paths between two tables via foreign keys so that I can construct multi-table queries.

**Acceptance Criteria**:
- [ ] Uses BFS (breadth-first search) to find paths through foreign key relationships
- [ ] Accepts `from_table`, `to_table`, `from_schema`, `to_schema`, `max_depth` (1-6, default 4)
- [ ] Builds bidirectional edges for traversal in both directions
- [ ] Returns paths sorted by length (shortest first) with SQL JOIN examples
- [ ] Generates executable JOIN clause examples for each path

**Edge Cases**:
- No path exists: Return `PATH_NOT_FOUND` error with informative message (may suggest checking if tables use row store, since row store tables cannot have FKs)
- Multiple paths of same length: Return all paths, let the user/agent choose
- Tables in different schemas: Support cross-schema paths

---

### 5.3 Feature: Layer 3 — Query Execution (2 Tools)

**Priority**: P0 (Critical)

#### Tool: `execute_query`

**US-007**: As an AI agent, I want to execute read-only SQL queries with parameterized values so that I can retrieve specific data safely.

**Acceptance Criteria**:
- [ ] Accepts `sql`, `params` (named `:param` or positional `?`), `limit` (1-10000, default 1000), `timeout_ms`
- [ ] Validates query is read-only: blocks INSERT, UPDATE, DELETE, DROP, CREATE, ALTER, TRUNCATE, GRANT, REVOKE, and other write keywords
- [ ] Validates query starts with SELECT or WITH
- [ ] Auto-appends LIMIT clause if query doesn't have one
- [ ] Returns columns, rows, row count, has_more flag, execution time, and query hash
- [ ] Uses parameterized queries via hdbcli (never string interpolation)

**Edge Cases**:
- Query timeout: Return `QUERY_TIMEOUT` error with suggestion to add filters or reduce scope
- Permission denied: Return `PERMISSION_DENIED` error with guidance on required grants
- Write attempt blocked: Return `WRITE_OPERATION_DENIED` error with clear explanation

---

#### Tool: `explain_query`

**US-008**: As an AI agent, I want to see the execution plan for a query so that I can understand and optimize performance.

**Acceptance Criteria**:
- [ ] Transparent adaptation of HANA's `EXPLAIN PLAN` mechanism
- [ ] Writes plan to `EXPLAIN_PLAN_TABLE` with a unique statement name, reads results, then cleans up
- [ ] Returns plan details including operator names, execution engine, and operator details
- [ ] Accepts `sql`, `params`, and `format` ("text" or "json") parameters
- [ ] Same interface as mamba-mcp-pg `explain_query` from the caller's perspective

**Edge Cases**:
- `EXPLAIN_PLAN_TABLE` does not exist: Return clear error with guidance (table is auto-created in user's schema)
- Concurrent explain calls: Use unique statement names (UUID-based) to avoid conflicts
- Cleanup failure: Log warning but don't fail the response

---

### 5.4 Feature: HANA-Specific Tools (3 Tools)

**Priority**: P1 (High)

#### Tool: `list_calculation_views`

**US-009**: As an AI agent, I want to list calculation views available in HANA so that I can discover analytics models and reporting views.

**Acceptance Criteria**:
- [ ] Lists calculation views from `SYS.VIEWS` where `VIEW_TYPE` indicates calculation view
- [ ] Returns view name, schema, column count, and validity status
- [ ] Optionally includes column metadata (names, types) for each view
- [ ] Accepts `schema_name` and `include_columns: bool` parameters
- [ ] Notes that data access requires analytic privileges (informational, not enforced)

**Edge Cases**:
- No calculation views in schema: Return empty list with informative note
- User lacks analytic privileges: Views are listed but data access may fail (documented limitation)

---

#### Tool: `get_table_store_type`

**US-010**: As an AI agent, I want to know whether a table uses column store or row store so that I can understand query optimization characteristics and FK support.

**Acceptance Criteria**:
- [ ] Returns store type (COLUMN or ROW) for a given table
- [ ] Includes relevant metadata: partitioning info, compression status
- [ ] Queries `SYS.TABLES` for `IS_COLUMN_TABLE` and related fields
- [ ] Accepts `table_name` and `schema_name` parameters
- [ ] Notes implications: column store supports FKs and is optimized for analytics; row store is optimized for point lookups

**Edge Cases**:
- Table does not exist: Return `TABLE_NOT_FOUND` error
- View (not a table): Return informative note that views don't have a store type

---

#### Tool: `list_procedures`

**US-011**: As an AI agent, I want to list stored procedures and their parameters in a schema so that I can understand available database logic.

**Acceptance Criteria**:
- [ ] Lists procedures with name, type (SQLScript/R/L), and parameter count
- [ ] Optionally includes parameter details (name, data type, direction IN/OUT/INOUT)
- [ ] Queries `SYS.PROCEDURES` and `SYS.PROCEDURE_PARAMETERS`
- [ ] Accepts `schema_name` and `include_parameters: bool` parameters

**Edge Cases**:
- No procedures in schema: Return empty list
- Procedure with no parameters: Return procedure with empty parameter list

---

### 5.5 Feature: Configuration System

**Priority**: P0 (Critical)

#### US-012: Configuration via Environment Variables

**As a** server operator, **I want** to configure the HANA connection via environment variables **so that** I can deploy the server without hardcoding credentials.

**Acceptance Criteria**:
- [ ] Env var prefix: `MAMBA_MCP_HANA_*`
- [ ] Database settings: `DB_HOST`, `DB_PORT`, `DB_NAME` (optional, for tenant routing), `DB_USER`, `DB_PASSWORD` (SecretStr), `DB_ENCRYPT`, `DB_SSL_VALIDATE`, `DB_USERKEY` (hdbuserstore key)
- [ ] Server settings: `TRANSPORT` (stdio/http), `SERVER_HOST`, `SERVER_PORT`, `LOG_LEVEL`, `LOG_FORMAT`
- [ ] Pool settings: `POOL_SIZE`, `POOL_TIMEOUT`
- [ ] Query settings: `STATEMENT_TIMEOUT`, `DEFAULT_SCHEMA`
- [ ] Cascading env file resolution: explicit path > `./mamba.env` > `~/mamba.env`
- [ ] Auto-detect TLS encryption when port is 443 (HANA Cloud), allow manual override
- [ ] Support nested delimiter `__` for Pydantic settings (e.g., `MAMBA_MCP_HANA_DB__HOST`)

---

### 5.6 Feature: CLI Interface

**Priority**: P0 (Critical)

#### US-013: CLI with test and serve commands

**As a** server operator, **I want** a CLI with `test` and default serve commands **so that** I can verify connectivity and start the server.

**Acceptance Criteria**:
- [ ] Default (no subcommand): Start MCP server with configured transport
- [ ] `test` subcommand: Test HANA connection and exit with success/failure code
- [ ] `--env-file` option: Specify custom environment file path
- [ ] Env file validation: Check existence and file type
- [ ] Logging setup: JSON or text format, configurable level, output to stderr
- [ ] Entry point: `mamba-mcp-hana` console script

---

### 5.7 Feature: Error Handling System

**Priority**: P0 (Critical)

#### US-014: Structured errors with fuzzy matching

**As an** AI agent, **I want** structured error responses with actionable suggestions **so that** I can recover from mistakes or guide the user.

**Acceptance Criteria**:
- [ ] `ErrorCode` constants: `SCHEMA_NOT_FOUND`, `TABLE_NOT_FOUND`, `COLUMN_NOT_FOUND`, `INVALID_SQL`, `WRITE_OPERATION_DENIED`, `QUERY_TIMEOUT`, `CONNECTION_ERROR`, `PERMISSION_DENIED`, `PARAMETER_ERROR`, `PATH_NOT_FOUND`, `VIEW_NOT_FOUND`, `PROCEDURE_NOT_FOUND`
- [ ] `create_tool_error` factory function returns structured `ToolError` model
- [ ] Levenshtein distance fuzzy matching for schema/table/column name suggestions
- [ ] Default suggestions map: each error code has a helpful fallback suggestion
- [ ] Errors include code, message, suggestion, context, tool name, and input received

## 6. Non-Functional Requirements

### 6.1 Performance

- Schema discovery queries (Layer 1) should complete within 5 seconds for typical schemas (<1000 tables)
- Query execution (Layer 3) respects configurable statement timeout (default 30 seconds)
- Connection pool health checks prevent stale connection errors
- `asyncio.to_thread()` wrappers ensure the async event loop is never blocked by synchronous hdbcli calls

### 6.2 Security

- **Query validation**: Blocked keyword regex pattern (INSERT, UPDATE, DELETE, DROP, CREATE, ALTER, TRUNCATE, GRANT, REVOKE, etc.) with case-insensitive word boundary matching
- **SELECT/WITH enforcement**: Queries must start with SELECT or WITH
- **Parameterized queries**: All user-supplied values passed via hdbcli parameterized queries, never string interpolation
- **Credential protection**: `DB_PASSWORD` stored as Pydantic `SecretStr`, never logged or serialized
- **Recommended restricted user**: Documentation includes SQL templates for creating a read-only HANA user with minimal privileges

#### Recommended HANA User Setup

```sql
-- Create restricted user with minimal privileges
CREATE RESTRICTED USER mcp_reader PASSWORD "SecurePassword123";
ALTER USER mcp_reader ENABLE CLIENT CONNECT;

-- Grant metadata access (read-only, all system views)
GRANT CATALOG READ TO mcp_reader;

-- Grant SELECT on specific schemas
GRANT SELECT ON SCHEMA MY_SCHEMA TO mcp_reader;

-- For ODBC/JDBC connectivity (required for some connection methods)
GRANT RESTRICTED_USER_ODBC_ACCESS TO mcp_reader;
```

### 6.3 Scalability

- Connection pool supports 1-20 concurrent connections (configurable)
- Statement timeout prevents runaway queries
- LIMIT enforcement prevents excessive result sets
- Designed for single-instance MCP server usage (not horizontally scalable by design)

### 6.4 Reliability

- Connection pool health checks via `pool_pre_ping` equivalent (test query before use)
- Graceful shutdown: dispose all connections in lifespan cleanup
- Fail-fast on startup: test connection before accepting MCP requests
- Automatic reconnection on transient connection failures

## 7. Technical Considerations

### 7.1 Architecture Overview

The package follows the same architecture as mamba-mcp-pg with a key difference in the database layer: instead of SQLAlchemy with asyncpg, it uses hdbcli directly with `asyncio.to_thread()` wrappers for non-blocking execution.

```
MCP Protocol Layer (FastMCP)
    |
    v
Tools Layer (11 tools across 3 layers + extras)
    |
    v
Service Layer (SchemaService, RelationshipService, QueryService, HanaService)
    |
    v
Connection Pool (async queue-based, wraps hdbcli connections)
    |
    v
hdbcli (synchronous PEP 249 driver) --> SAP HANA Database
```

### 7.2 Tech Stack

- **Runtime**: Python 3.11+
- **MCP Framework**: `mcp>=1.0.0` (FastMCP)
- **Database Driver**: `hdbcli` (SAP official, synchronous PEP 249)
- **Async Bridge**: `asyncio.to_thread()` from Python standard library
- **Validation**: `pydantic>=2.0.0`, `pydantic-settings>=2.0.0`
- **CLI**: `typer>=0.12.0`
- **Type Checking**: MyPy strict mode
- **Linting**: Ruff (rules: E, F, I, N, W, UP)
- **Testing**: pytest with asyncio auto mode

### 7.3 Integration Points

| System | Integration Type | Purpose |
|--------|-----------------|---------|
| SAP HANA (Cloud) | hdbcli (port 443, TLS) | Database connectivity |
| SAP HANA (On-Prem) | hdbcli (port 3NN13/3NN15) | Database connectivity |
| hdbuserstore | Key-based auth | Secure credential storage |
| MCP Clients | stdio/HTTP transport | Protocol communication |

### 7.4 Technical Constraints

- **No native async**: hdbcli is synchronous-only; all database calls must be wrapped with `asyncio.to_thread()`
- **No `information_schema`**: HANA uses `SYS.*` system views; all schema discovery SQL is HANA-specific
- **EXPLAIN PLAN is table-based**: Writes to `EXPLAIN_PLAN_TABLE` then reads back (unlike PostgreSQL's direct return)
- **Foreign keys column-store only**: FK constraints only supported on column tables; row store tables cannot have FKs
- **Autocommit default**: hdbcli defaults to autocommit=ON (acceptable for read-only usage)
- **No RETURNING clause**: HANA does not support INSERT/UPDATE...RETURNING (not relevant for read-only but noted for completeness)
- **Port-based environment detection**: HANA Cloud uses port 443 (always TLS); on-premise uses instance-based ports (3NN13/3NN15)
- **NULL sort order**: HANA sorts NULLs FIRST in ascending (opposite of PostgreSQL's default)

### 7.5 Key SQL Differences from PostgreSQL

| Capability | mamba-mcp-pg (PostgreSQL) | mamba-mcp-hana (HANA) |
|------------|-------------------------------|---------------------------|
| Schema discovery | `pg_catalog.*`, `information_schema` | `SYS.SCHEMAS`, `SYS.TABLES`, `SYS.TABLE_COLUMNS` |
| Foreign keys | `information_schema.table_constraints` | `SYS.REFERENTIAL_CONSTRAINTS` |
| Indexes | `pg_catalog.pg_indexes` | `SYS.INDEXES`, `SYS.INDEX_COLUMNS` |
| Constraints | `pg_catalog.pg_constraint` | `SYS.CONSTRAINTS` |
| Row limiting | `LIMIT n` | `LIMIT n` (also supports `TOP n`) |
| Parameter placeholders | `$1, $2` (asyncpg) | `?` positional or `:name` named (hdbcli) |
| EXPLAIN | `EXPLAIN (FORMAT JSON) SELECT...` | `EXPLAIN PLAN SET STATEMENT_NAME = ? FOR SELECT...` + read from `EXPLAIN_PLAN_TABLE` |
| Statement timeout | `SET LOCAL statement_timeout = N` | `SET STATEMENT TIMEOUT n` (different syntax) |
| System schema filter | `pg_*`, `information_schema` | `_SYS_*`, `SYS`, `SYSTEM` |

## 8. Scope Definition

### 8.1 In Scope

- 11 MCP tools (8 core + 3 HANA-specific)
- HANA Cloud and on-premise support
- Username/password and hdbuserstore authentication
- Auto-detect TLS for HANA Cloud
- Async connection pool with health checks
- Structured error handling with fuzzy matching
- CLI with test and serve commands
- Pydantic settings with env var configuration
- Mock-based unit tests
- MyPy strict + Ruff linting compliance

### 8.2 Out of Scope

- **Write operations**: No DML/DDL support — strictly read-only
- **Calculation view data access**: Listed/described but no guarantees on data query success (requires analytic privileges)
- **X.509 / SAML authentication**: Only username/password and hdbuserstore supported initially
- **SAP BTP integration**: No direct BTP service integration
- **Shared database service interface**: Noted as future consideration but not implemented in this release
- **Real-time or streaming features**: No CDC, event-based, or streaming capabilities
- **HANA XS Advanced features**: No XSA-specific integration
- **Multi-instance pooling**: Server is single-instance; no distributed connection management

### 8.3 Future Considerations

- **Shared database service protocol**: Define a common interface/protocol across mamba-mcp-pg and mamba-mcp-hana for consistent behavior and potential code reuse
- **X.509 certificate authentication**: Add certificate-based auth for enterprise environments
- **Calculation view data access**: With analytic privilege handling and better error messaging
- **SAP HANA Cloud HDI container support**: Integration with HDI (HANA Deployment Infrastructure) schemas
- **Procedure execution** (read-only): Execute stored procedures that return result sets
- **Synonym resolution**: Resolve public synonyms to their underlying objects

## 9. Implementation Plan

### 9.1 Phase 1: Foundation

**Completion Criteria**: Package structure created, config system working, connection pool operational, CLI test command verifies connectivity.

| Deliverable | Description | Dependencies |
|-------------|-------------|--------------|
| Package scaffolding | `packages/mamba-mcp-hana/` with pyproject.toml, src layout, tests dir | Workspace pyproject.toml |
| `config.py` | Pydantic settings with `MAMBA_MCP_HANA_*` prefix, env file resolution, auto-TLS detection | pydantic-settings |
| `database/pool.py` | Async connection pool (queue-based) with configurable size, health checks, reconnection | hdbcli |
| `database/engine.py` | Connection creation, disposal, and test functions | hdbcli |
| `server.py` | FastMCP server with lifespan managing connection pool | mcp |
| `__main__.py` | Typer CLI with `--env-file`, default serve, and `test` subcommand | typer |
| `errors.py` | ErrorCode constants, create_tool_error factory, Levenshtein fuzzy matching | — |
| Unit tests | Config loading, pool behavior, error creation, CLI | pytest |

**Checkpoint Gate**: Connection pool successfully connects to a HANA instance (Cloud or on-prem), `test` command passes, config loads from env vars and env file.

---

### 9.2 Phase 2: Core Tools (Layers 1-3)

**Completion Criteria**: All 8 core tools operational, query validation enforced, EXPLAIN PLAN adapted, all tools return structured Pydantic models.

| Deliverable | Description | Dependencies |
|-------------|-------------|--------------|
| `models/schema.py` | Pydantic I/O models for Layer 1 tools | Phase 1 |
| `models/relationships.py` | Pydantic I/O models for Layer 2 tools | Phase 1 |
| `models/results.py` | Pydantic I/O models for Layer 3 tools + error models | Phase 1 |
| `database/schema.py` | SchemaService with async methods querying SYS.* views | Phase 1 pool |
| `database/relationships.py` | RelationshipService with FK discovery and BFS join path | Phase 1 pool |
| `database/queries.py` | QueryService with validation, execution, and EXPLAIN PLAN adaptation | Phase 1 pool |
| `tools/schema_tools.py` | 4 Layer 1 tools: list_schemas, list_tables, describe_table, get_sample_rows | Services + models |
| `tools/relationship_tools.py` | 2 Layer 2 tools: get_foreign_keys, find_join_path | Services + models |
| `tools/query_tools.py` | 2 Layer 3 tools: execute_query, explain_query | Services + models |
| Unit tests | Tool tests with mocked hdbcli, service tests, query validation tests | Phase 1 tests |

**Checkpoint Gate**: All 8 core tools pass unit tests, query validation blocks write operations, EXPLAIN PLAN write-read-cleanup cycle works correctly.

---

### 9.3 Phase 3: HANA Extras

**Completion Criteria**: All 3 HANA-specific tools operational, full test suite passing, MyPy strict + Ruff clean.

| Deliverable | Description | Dependencies |
|-------------|-------------|--------------|
| `models/hana.py` | Pydantic I/O models for HANA-specific tools | Phase 2 |
| `database/hana.py` | HanaService with calc view, store type, and procedure queries | Phase 1 pool |
| `tools/hana_tools.py` | 3 HANA tools: list_calculation_views, get_table_store_type, list_procedures | Services + models |
| Unit tests | HANA-specific tool tests | Phase 2 tests |
| Integration tests (optional) | Tests against real HANA instance (CI-skippable) | HANA instance |
| README.md | Package documentation with setup, usage, and tool reference | All phases |

**Checkpoint Gate**: All 11 tools pass unit tests, MyPy strict reports 0 errors, Ruff reports 0 issues, README documents all tools and configuration.

## 10. Dependencies

### 10.1 Technical Dependencies

| Dependency | Owner | Status | Risk if Delayed |
|------------|-------|--------|-----------------|
| `hdbcli` (PyPI) | SAP SE | Available (v2.27.23) | Blocks all development |
| `mcp>=1.0.0` (PyPI) | Anthropic | Available | Blocks server creation |
| `pydantic>=2.0.0` (PyPI) | Pydantic team | Available | Blocks model definitions |
| `pydantic-settings>=2.0.0` (PyPI) | Pydantic team | Available | Blocks config system |
| `typer>=0.12.0` (PyPI) | Tiangolo | Available | Blocks CLI |

### 10.2 Internal Dependencies

| Package | Dependency | Status |
|---------|-----------|--------|
| mamba-mcp-pg | Reference architecture (patterns, not code) | Complete |
| Workspace pyproject.toml | Package registration | Requires update |

## 11. Risks & Mitigations

| Risk | Impact | Likelihood | Mitigation Strategy |
|------|--------|------------|---------------------|
| SAP ecosystem complexity (calc views, analytic privileges) | Med | High | Scope calc views to metadata-only; document limitations clearly |
| hdbcli sync-only driver performance | Low | Med | `asyncio.to_thread()` with thread pool; connection pooling reduces overhead |
| HANA instance availability for testing | Med | Med | Mock-based unit tests as primary; optional integration tests marked skip-by-default |
| EXPLAIN PLAN table-based mechanism complexity | Low | Med | UUID-based statement names prevent conflicts; cleanup in finally block |
| HANA SQL dialect differences | Low | Low | Research completed; all system view queries documented in spec |
| hdbcli API changes | Low | Low | Pin to compatible version range; hdbcli has stable PEP 249 interface |

## 12. Open Questions

| # | Question | Owner | Due Date | Resolution |
|---|----------|-------|----------|------------|
| — | No open questions | — | — | All key decisions resolved during spec interview |

## 13. Appendix

### 13.1 Glossary

| Term | Definition |
|------|------------|
| MCP | Model Context Protocol — an open protocol for AI agents to interact with tools and data sources |
| FastMCP | Python framework for building MCP servers with lifespan management |
| hdbcli | SAP's official Python database driver for HANA (PEP 249 / DB-API 2.0) |
| hdbuserstore | SAP's secure credential storage that maps keys to connection details |
| Column Store | HANA's default table storage engine, optimized for analytics and in-memory columnar operations |
| Row Store | HANA's alternative table storage engine, optimized for OLTP-style point lookups |
| Calculation View | HANA's primary analytics modeling object, combining tables/views with calculations |
| Analytic Privilege | HANA row-level security mechanism that controls access to calculation view data |
| EXPLAIN PLAN TABLE | HANA system table where query execution plans are written for analysis |
| BFS | Breadth-First Search — algorithm used for finding join paths between tables |
| Levenshtein Distance | Edit distance algorithm used for fuzzy name matching in error suggestions |

### 13.2 HANA System Views Reference

| System View | Used By | Purpose |
|-------------|---------|---------|
| `SYS.SCHEMAS` | `list_schemas` | Schema enumeration |
| `SYS.TABLES` | `list_tables`, `get_table_store_type` | Table enumeration and metadata |
| `SYS.TABLE_COLUMNS` | `describe_table` | Column metadata |
| `SYS.VIEWS` | `list_tables`, `list_calculation_views` | View enumeration |
| `SYS.VIEW_COLUMNS` | `describe_table` (for views), `list_calculation_views` | View column metadata |
| `SYS.INDEXES` | `describe_table` | Index enumeration |
| `SYS.INDEX_COLUMNS` | `describe_table` | Index column details |
| `SYS.CONSTRAINTS` | `describe_table` | PK/UNIQUE constraints |
| `SYS.REFERENTIAL_CONSTRAINTS` | `get_foreign_keys`, `find_join_path` | Foreign key relationships |
| `SYS.PROCEDURES` | `list_procedures` | Procedure enumeration |
| `SYS.PROCEDURE_PARAMETERS` | `list_procedures` | Procedure parameter details |
| `EXPLAIN_PLAN_TABLE` | `explain_query` | Query execution plans |

### 13.3 Package Directory Structure

```
packages/mamba-mcp-hana/
├── pyproject.toml
├── README.md
├── src/mamba_mcp_sap_hana/
│   ├── __init__.py
│   ├── __main__.py            # Typer CLI (test, serve)
│   ├── config.py              # Pydantic settings (MAMBA_MCP_HANA_*)
│   ├── errors.py              # Error codes, factory, fuzzy matching
│   ├── server.py              # FastMCP server & lifespan
│   ├── database/
│   │   ├── __init__.py
│   │   ├── pool.py            # Async connection pool (queue-based)
│   │   ├── engine.py          # Connection creation, disposal, test
│   │   ├── schema.py          # SchemaService (SYS.* view queries)
│   │   ├── relationships.py   # RelationshipService (FK discovery, BFS)
│   │   ├── queries.py         # QueryService (validation, execution, EXPLAIN)
│   │   └── hana.py            # HanaService (calc views, store type, procedures)
│   ├── models/
│   │   ├── __init__.py
│   │   ├── schema.py          # Layer 1 I/O models
│   │   ├── relationships.py   # Layer 2 I/O models
│   │   ├── results.py         # Layer 3 I/O models + error models
│   │   └── hana.py            # HANA-specific I/O models
│   └── tools/
│       ├── __init__.py
│       ├── schema_tools.py    # 4 Layer 1 tools
│       ├── relationship_tools.py  # 2 Layer 2 tools
│       ├── query_tools.py     # 2 Layer 3 tools
│       └── hana_tools.py      # 3 HANA-specific tools
└── tests/
    ├── __init__.py
    ├── conftest.py            # Mock hdbcli fixtures
    ├── test_config.py
    ├── test_pool.py
    ├── test_schema_tools.py
    ├── test_relationship_tools.py
    ├── test_query_tools.py
    ├── test_hana_tools.py
    └── test_cli.py
```

### 13.4 Configuration Reference

| Environment Variable | Type | Default | Description |
|---------------------|------|---------|-------------|
| `MAMBA_MCP_HANA_DB_HOST` | str | `localhost` | HANA server hostname |
| `MAMBA_MCP_HANA_DB_PORT` | int | `30015` | HANA server port |
| `MAMBA_MCP_HANA_DB_NAME` | str | `None` | Tenant database name (optional) |
| `MAMBA_MCP_HANA_DB_USER` | str | *required* | Database username |
| `MAMBA_MCP_HANA_DB_PASSWORD` | SecretStr | *required* | Database password |
| `MAMBA_MCP_HANA_DB_ENCRYPT` | bool | auto-detect | Enable TLS (auto-true for port 443) |
| `MAMBA_MCP_HANA_DB_SSL_VALIDATE` | bool | `True` | Validate SSL certificate |
| `MAMBA_MCP_HANA_DB_USERKEY` | str | `None` | hdbuserstore key (alternative to user/password) |
| `MAMBA_MCP_HANA_POOL_SIZE` | int | `5` | Connection pool size (1-20) |
| `MAMBA_MCP_HANA_POOL_TIMEOUT` | float | `30.0` | Pool connection acquire timeout |
| `MAMBA_MCP_HANA_STATEMENT_TIMEOUT` | int | `30000` | Query timeout in milliseconds |
| `MAMBA_MCP_HANA_DEFAULT_SCHEMA` | str | `None` | Default schema for tool queries |
| `MAMBA_MCP_HANA_TRANSPORT` | str | `stdio` | Server transport (stdio/http) |
| `MAMBA_MCP_HANA_SERVER_HOST` | str | `0.0.0.0` | HTTP server bind host |
| `MAMBA_MCP_HANA_SERVER_PORT` | int | `8080` | HTTP server bind port |
| `MAMBA_MCP_HANA_LOG_LEVEL` | str | `INFO` | Logging level |
| `MAMBA_MCP_HANA_LOG_FORMAT` | str | `json` | Log format (json/text) |

### 13.5 References

- [hdbcli on PyPI](https://pypi.org/project/hdbcli/) — SAP HANA Python driver
- [sqlalchemy-hana on GitHub](https://github.com/SAP/sqlalchemy-hana) — SQLAlchemy dialect (reference only)
- [SAP HANA System Views Reference](https://help.sap.com/docs/SAP_HANA_PLATFORM/4fe29514fd584807ac9f2a04f6754767/20cbb10c75191014b47ba845bfe499fe.html)
- [SAP HANA SQL Reference](https://help.sap.com/doc/9b40bf74f8644b898fb07dabdd2a36ad/2.0.03/en-US/SAP_HANA_SQL_and_System_Views_Reference_en.pdf)
- [MCP Protocol Specification](https://modelcontextprotocol.io/)
- [mamba-mcp-pg](../../packages/mamba-mcp-pg/) — Reference architecture

---

*Document generated by SDD Tools*
