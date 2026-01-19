# Mamba MCP Client

A Python-based MCP (Model Context Protocol) Client for testing and debugging MCP Servers.

Testing MCP servers is difficult—debugging is painful, and there are few good tools to inspect MCP communication in detail. Mamba MCP provides both an interactive terminal UI and a programmatic Python API for comprehensive MCP server testing.

## Features

- **Interactive TUI** - Textual-based terminal interface with real-time updates
- **CLI Commands** - Quick one-off commands for inspection and testing
- **Python API** - Fully async programmatic interface for automation
- **Multi-Transport** - Supports stdio, SSE, HTTP, UV-installed, and UV-local transports
- **Protocol Logging** - Detailed request/response capture with timing
- **Rich Output** - Syntax highlighting and formatted tables

## Installation

Requires Python 3.11+.

```bash
# Using pip
pip install mamba-mcp-client

# Using uv
uv add mamba-mcp-client

# From source
git clone https://github.com/sequenzia/mamba-mcp.git
cd mamba-mcp
uv install
```

## Quick Start

### Interactive TUI

Launch the interactive terminal UI to explore your MCP server:

```bash
# Connect via stdio (quote the entire command)
mamba-mcp tui --stdio "python path/to/server.py"

# Connect via SSE
mamba-mcp tui --sse http://localhost:8000/sse

# Connect via HTTP
mamba-mcp tui --http http://localhost:8000/mcp

# Connect to UV-installed MCP server
mamba-mcp tui --uv @modelcontextprotocol/server-sqlite

# Connect to local UV-based project
mamba-mcp tui --uv-local-path ./my-mcp-server --uv-local-name server
```

The TUI provides:
- Tree view of tools, resources, and prompts
- Interactive tool calling with argument input
- Request/response log viewer
- Keyboard shortcuts: `q` quit, `r` refresh, `l` logs, `p` ping, `c` clear

### CLI Commands

Quick inspection without the full TUI:

```bash
# View server info and capabilities
mamba-mcp connect --stdio "python server.py"

# List available tools
mamba-mcp tools --stdio "python server.py"

# List resources
mamba-mcp resources --sse http://localhost:8000/sse

# List prompts
mamba-mcp prompts --stdio "python server.py"

# Call a tool with arguments
mamba-mcp call add --args '{"a": 5, "b": 3}' --stdio "python server.py"

# Read a resource
mamba-mcp read "config://version" --stdio "python server.py"

# Get a prompt
mamba-mcp prompt code_review --args '{"language": "python"}' --stdio "python server.py"
```

### Python API

For programmatic testing and automation:

```python
import asyncio
from mamba_mcp_client import MCPTestClient, ClientConfig

async def main():
    # Configure connection
    config = ClientConfig.for_stdio(
        command="python",
        args=["path/to/server.py"],
    )

    # Create client and connect
    client = MCPTestClient(config)

    async with client.connect():
        # Get server info
        print(f"Connected to: {client.server_info.name}")

        # List and call tools
        tools = await client.list_tools()
        for tool in tools:
            print(f"  - {tool.name}: {tool.description}")

        result = await client.call_tool("add", {"a": 5, "b": 3})
        print(f"Result: {result.text}")

        # List and read resources
        resources = await client.list_resources()
        content = await client.read_resource("config://version")

        # List and get prompts
        prompts = await client.list_prompts()
        prompt = await client.get_prompt("code_review", {"language": "python"})

        # View request/response log
        client.print_log_summary()

if __name__ == "__main__":
    asyncio.run(main())
```

## Configuration

### Transport Options

**Stdio** - Spawn a subprocess and communicate via stdin/stdout:
```bash
# Quote the entire command string
mamba-mcp connect --stdio "python server.py arg1 arg2"

# Short form
mamba-mcp connect -s "python server.py"
```

**SSE** - Connect to an SSE endpoint:
```bash
mamba-mcp connect --sse http://localhost:8000/sse
```

**HTTP** - Connect via Streamable HTTP:
```bash
mamba-mcp connect --http http://localhost:8000/mcp
```

**UV-installed** - Connect to MCP servers installed via UV:
```bash
# Connect to a UV-installed server
mamba-mcp connect --uv @modelcontextprotocol/server-sqlite

# Specify Python version and additional packages
mamba-mcp connect --uv my-mcp-server --python 3.11 --with requests --with pandas
```

**UV-local** - Connect to local UV-based projects (requires both path and name):
```bash
# Connect to a local UV project
mamba-mcp connect --uv-local-path ./my-mcp-server --uv-local-name server

# With additional options
mamba-mcp connect --uv-local-path /path/to/project --uv-local-name myserver --python 3.12
```

### Common Options

```bash
--stdio, -s       Connect via stdio (command as quoted string)
--timeout, -t     Connection timeout in seconds (default: 30)
--log-level, -l   Log level: DEBUG, INFO, WARNING, ERROR (default: INFO)
--output, -o      Output format: json, table, rich (default: rich)
--args, -a        Arguments as JSON string (for call/prompt commands)
--env, -e         Path to .env file for environment variables
--python          Python version for UV transports (e.g., 3.11, 3.12)
--with            Additional packages for UV transports (can be used multiple times)
```

### Environment Variables

Configure via environment variables with the `MAMBA_MCP_` prefix:

```bash
export MAMBA_MCP_STDIO__COMMAND=python
export MAMBA_MCP_STDIO__ARGS='["server.py"]'
export MAMBA_MCP_LOG__ENABLED=true
```

Or use a `.env` file:

```bash
mamba-mcp --env /path/to/.env connect --stdio "python server.py"
```

### Programmatic Configuration

```python
from mamba_mcp_client import ClientConfig

# Stdio transport
config = ClientConfig.for_stdio(
    command="python",
    args=["server.py"],
    env={"DEBUG": "1"},
)

# SSE transport
config = ClientConfig.for_sse(
    url="http://localhost:8000/sse",
    headers={"Authorization": "Bearer token"},
    timeout=60.0,
)

# HTTP transport
config = ClientConfig.for_http(
    url="http://localhost:8000/mcp",
    timeout=30.0,
)

# UV-installed transport
config = ClientConfig.for_uv_installed(
    server_name="@modelcontextprotocol/server-sqlite",
    args=["--db-path", "./data.db"],
    python_version="3.11",
    with_packages=["requests", "pandas"],
)

# UV-local transport (requires both project_path and server_name)
config = ClientConfig.for_uv_local(
    project_path="./my-mcp-server",
    server_name="myserver",
    python_version="3.12",
    env={"DEBUG": "1"},
)
```

## API Reference

### MCPTestClient

The main client class providing async methods for all MCP operations.

**Connection:**
- `connect()` - Async context manager for connection lifecycle
- `ping()` - Send a ping to verify connection
- `get_capabilities()` - Get server capabilities
- `get_instructions()` - Get server instructions

**Tools:**
- `list_tools()` - List available tools
- `call_tool(name, arguments)` - Call a tool with arguments

**Resources:**
- `list_resources()` - List available resources
- `read_resource(uri)` - Read a resource by URI
- `subscribe_resource(uri)` - Subscribe to resource updates
- `unsubscribe_resource(uri)` - Unsubscribe from resource

**Prompts:**
- `list_prompts()` - List available prompts
- `get_prompt(name, arguments)` - Get a prompt with arguments

**Logging:**
- `get_log_entries()` - Get all log entries
- `print_log_summary()` - Print formatted log table
- `export_logs(path)` - Export logs to JSON file
- `clear_logs()` - Clear log entries

### ClientConfig

Configuration class with factory methods for each transport type.

```python
ClientConfig.for_stdio(command, args=None, env=None)
ClientConfig.for_sse(url, headers=None, timeout=30.0)
ClientConfig.for_http(url, headers=None, timeout=30.0)
ClientConfig.for_uv_installed(server_name, args=None, python_version=None, with_packages=None, env=None)
ClientConfig.for_uv_local(project_path, server_name, args=None, python_version=None, with_packages=None, env=None)
```

## Examples

The `examples/` directory contains:

- `sample_server.py` - A sample MCP server with tools, resources, and prompts
- `api_usage.py` - Complete programmatic API usage example

Run the sample server with the TUI:

```bash
mamba-mcp tui --stdio "python examples/sample_server.py"
```

## Development

```bash
# Clone the repository
git clone https://github.com/sequenzia/mamba-mcp.git
cd mamba-mcp

# Install with dev dependencies
uv install --all-extras

# Run tests
pytest

# Type checking
mypy src/

# Linting
ruff check src/
```

## License

MIT License - see LICENSE for details.
