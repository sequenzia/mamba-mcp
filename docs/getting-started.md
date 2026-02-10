# Getting Started

This guide walks you through installing Mamba MCP, configuring a server, and running your first MCP tool call.

## Prerequisites

- **Python 3.11+**
- **[UV](https://docs.astral.sh/uv/)** package manager (recommended for monorepo development)

## Installation

### From the Monorepo (Development)

Clone the repository and install all packages with dev dependencies:

```bash
git clone https://github.com/sequenzia/mamba-mcp.git
cd mamba-mcp
uv sync --group dev
```

This installs all 6 packages in development mode with shared dev tools (pytest, ruff, mypy).

### Individual Packages (Production)

Install only the packages you need:

=== "PostgreSQL Server"

    ```bash
    pip install mamba-mcp-pg
    ```

=== "Filesystem Server"

    ```bash
    pip install mamba-mcp-fs
    ```

=== "SAP HANA Server"

    ```bash
    pip install mamba-mcp-hana
    ```

=== "GitLab Server"

    ```bash
    pip install mamba-mcp-gitlab
    ```

=== "MCP Client"

    ```bash
    pip install mamba-mcp-client
    ```

## Quick Start: PostgreSQL Server

### 1. Create an env file

```title="mamba.env"
MAMBA_MCP_PG_DB_HOST=localhost
MAMBA_MCP_PG_DB_PORT=5432
MAMBA_MCP_PG_DB_NAME=mydb
MAMBA_MCP_PG_DB_USER=myuser
MAMBA_MCP_PG_DB_PASSWORD=mypassword
```

### 2. Test the connection

```bash
mamba-mcp-pg --env-file mamba.env test
```

### 3. Start the server

```bash
mamba-mcp-pg --env-file mamba.env
```

The server starts in stdio mode by default. See the [PostgreSQL Server docs](servers/pg.md) for HTTP transport and full configuration.

## Quick Start: Filesystem Server

### 1. Create an env file

```title="mamba.env"
MAMBA_MCP_FS_ROOT_PATH=/path/to/serve
MAMBA_MCP_FS_READ_ONLY=true
```

### 2. Test the connection

```bash
mamba-mcp-fs --env-file mamba.env test
```

### 3. Start the server

```bash
mamba-mcp-fs --env-file mamba.env
```

See the [Filesystem Server docs](servers/fs.md) for S3 backend support and security configuration.

## Quick Start: GitLab Server

### 1. Create an env file

```title="mamba.env"
MAMBA_MCP_GITLAB_URL=https://gitlab.com
MAMBA_MCP_GITLAB_TOKEN=glpat-xxxxxxxxxxxxxxxxxxxx
```

### 2. Test the connection

```bash
mamba-mcp-gitlab --env-file mamba.env test
```

### 3. Start the server

```bash
mamba-mcp-gitlab --env-file mamba.env
```

See the [GitLab Server docs](servers/gitlab.md) for OAuth 2.0 auth and full tool reference.

## Using the MCP Client

The `mamba-mcp-client` package lets you test and debug any MCP server — including the ones in this monorepo and third-party servers.

### Interactive TUI

```bash
mamba-mcp tui --stdio "mamba-mcp-pg --env-file mamba.env"
```

The TUI provides a visual interface to browse server capabilities, call tools, and inspect results.

### CLI Commands

```bash
# Connect and show server info
mamba-mcp connect --stdio "mamba-mcp-pg --env-file mamba.env"

# List available tools
mamba-mcp tools --stdio "mamba-mcp-pg --env-file mamba.env"

# Call a specific tool
mamba-mcp call list_schemas --args '{"include_system": false}' \
  --stdio "mamba-mcp-pg --env-file mamba.env"
```

### Python API

```python
import asyncio
from mamba_mcp_client import ClientConfig, MCPTestClient

async def main():
    config = ClientConfig.for_stdio(
        command="mamba-mcp-pg",
        args=["--env-file", "mamba.env"],
    )
    client = MCPTestClient(config)

    async with client.connect():
        tools = await client.list_tools()
        for tool in tools:
            print(f"  {tool.name}: {tool.description}")

        result = await client.call_tool("list_schemas", {"include_system": False})
        print(result.text)

asyncio.run(main())
```

See the [MCP Client docs](packages/client.md) for the full API reference and all transport types.

## Common CLI Pattern

All four servers follow the same CLI pattern:

```bash
# Start the server (default: stdio transport)
mamba-mcp-{pg,fs,hana,gitlab} [--env-file mamba.env]

# Test connectivity and exit
mamba-mcp-{pg,fs,hana,gitlab} [--env-file mamba.env] test

# Use HTTP transport
MAMBA_MCP_{PG,FS,HANA,GITLAB}_TRANSPORT=streamable-http \
  mamba-mcp-{pg,fs,hana,gitlab} [--env-file mamba.env]
```

!!! tip "Env file auto-discovery"
    If you omit `--env-file`, the server checks for `./mamba.env` in the current directory, then falls back to `~/mamba.env`.

## Integrating with AI Assistants

MCP servers are designed to be connected to AI assistants that support the Model Context Protocol. Each server exposes its tools through the protocol, allowing assistants to discover and call them.

### Claude Desktop

Add a server to your Claude Desktop configuration:

```json title="claude_desktop_config.json"
{
  "mcpServers": {
    "postgres": {
      "command": "mamba-mcp-pg",
      "args": ["--env-file", "/path/to/mamba.env"]
    }
  }
}
```

### Stdio Transport

For stdio-based integrations, the server reads from stdin and writes to stdout:

```bash
mamba-mcp-pg --env-file mamba.env
```

### HTTP Transport

For network-based integrations, start the server with HTTP transport:

```bash
MAMBA_MCP_PG_TRANSPORT=streamable-http \
MAMBA_MCP_PG_SERVER_PORT=8080 \
  mamba-mcp-pg --env-file mamba.env
```

The server will listen on `http://0.0.0.0:8080/mcp`.

## Next Steps

- **[Architecture](architecture.md)** — Understand the system design and shared patterns
- **Server docs** — Deep-dive into each server's configuration and tool reference:
    - [PostgreSQL](servers/pg.md) | [Filesystem](servers/fs.md) | [SAP HANA](servers/hana.md) | [GitLab](servers/gitlab.md)
- **[Development Guide](development.md)** — Contributing, testing, and creating new server packages
