# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Mamba MCP Client is a Python-based testing and debugging tool for MCP (Model Context Protocol) servers. It provides three interfaces:
- **Interactive TUI** - Textual-based terminal UI for exploration
- **CLI Commands** - Quick one-off inspection and testing
- **Python API** - Async programmatic interface for automation

## Development Commands

```bash
# Install with dev dependencies (uses UV package manager)
uv install --all-extras

# Run all tests
pytest

# Run single test file
pytest tests/test_client.py

# Run specific test class or function
pytest tests/test_client.py::TestClientConfig
pytest tests/test_client.py::TestClientConfig::test_for_stdio

# Type checking (strict mode enabled)
mypy src/

# Linting
ruff check src/

# Format code
ruff format src/
```

## Running the Application

```bash
# Launch interactive TUI with sample server (quote the command string)
mamba-mcp tui --stdio "python examples/sample_server.py"

# CLI commands
mamba-mcp connect --stdio "python server.py"
mamba-mcp tools --sse http://localhost:8000/sse
mamba-mcp call add --args '{"a": 5, "b": 3}' --stdio "python server.py"

# UV-local requires both path and name
mamba-mcp connect --uv-local-path ./my-server --uv-local-name server

# Pass extra arguments to server using -- separator
# For stdio/UV: extra args become command-line arguments
mamba-mcp connect --stdio "python server.py" -- --verbose --port 8080

# For SSE/HTTP: extra args become query parameters
mamba-mcp tui --sse http://localhost:8000/sse -- env=prod debug=true
# Results in: http://localhost:8000/sse?env=prod&debug=true
```

## Architecture

```
src/mamba_mcp_client/
├── cli.py          # Typer-based CLI entry point, all commands defined here
├── client.py       # MCPTestClient - core async client wrapping FastMCP
├── config.py       # Pydantic models for transport configs (Stdio, SSE, HTTP, UV)
├── logging.py      # MCPLogger - protocol-level request/response capture
└── tui/
    └── app.py      # Textual app with ServerInfoPanel, CapabilityTree, ToolCallDialog
```

**Key patterns:**
- `ClientConfig` uses factory methods: `for_stdio()`, `for_sse()`, `for_http()`, `for_uv_installed()`, `for_uv_local(project_path, server_name)`
- `MCPTestClient` is an async context manager - use `async with client.connect():`
- Transport types: `STDIO`, `SSE`, `HTTP`, `UV_INSTALLED`, `UV_LOCAL`
- All MCP operations are async methods on `MCPTestClient`
- CLI `--stdio` takes a quoted command string that gets shell-parsed

**Configuration via environment:**
- Prefix: `MAMBA_MCP_`
- Pydantic Settings nested with double underscore: `MAMBA_MCP_STDIO__COMMAND`

## Code Standards

- Python 3.11+ required
- Line length: 100 characters (Ruff)
- MyPy strict mode enabled
- pytest with asyncio auto mode
- Ruff lint rules: E, F, I, N, W, UP

## Dependencies

Core: `fastmcp`, `pydantic`, `pydantic-settings`, `textual`, `rich`, `typer`, `httpx`, `anyio`

Note: `pg-mcp-server` is an editable local dependency from `../pg-mcp-server`
