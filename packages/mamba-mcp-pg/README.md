# mamba-mcp-pg

PostgreSQL MCP Server with layered schema discovery for AI assistants.

## Features

- **Layer 1: Schema Discovery** — List schemas, tables, describe columns, sample rows
- **Layer 2: Relationship Discovery** — Foreign keys, join path finding (BFS)
- **Layer 3: Query Execution** — Read-only SQL with parameterized queries and EXPLAIN support

## Usage

```bash
# Test database connection
mamba-mcp-pg --env-file mamba.env test

# Run the MCP server
mamba-mcp-pg --env-file mamba.env
```

## Configuration

Set via environment variables (prefix: `MAMBA_MCP_PG_`) or `mamba.env` file.

Default file locations (checked in order):
1. `./mamba.env` (project-local)
2. `~/mamba.env` (global fallback)

| Variable | Description | Default |
|----------|-------------|---------|
| `MAMBA_MCP_PG_DB_HOST` | PostgreSQL host | `localhost` |
| `MAMBA_MCP_PG_DB_PORT` | PostgreSQL port | `5432` |
| `MAMBA_MCP_PG_DB_NAME` | Database name | *required* |
| `MAMBA_MCP_PG_DB_USER` | Database user | *required* |
| `MAMBA_MCP_PG_DB_PASSWORD` | Database password | *required* |
| `MAMBA_MCP_PG_LOG_LEVEL` | Log level | `INFO` |
