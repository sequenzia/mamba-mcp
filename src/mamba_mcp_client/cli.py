"""CLI entry point for mamba-mcp-client with .env file support."""

import asyncio
import json
import shlex
import sys
from enum import Enum
from pathlib import Path
from typing import Annotated, Optional

import typer
from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table

from mamba_mcp_client import __version__
from mamba_mcp_client.client import MCPTestClient
from mamba_mcp_client.config import ClientConfig
from mamba_mcp_client.tui import MCPTestApp

console = Console()
app = typer.Typer(
    name="mamba-mcp",
    help="MCP Client for testing and debugging MCP Servers",
    no_args_is_help=True,
)


# Enums for options
class OutputFormat(str, Enum):
    json = "json"
    table = "table"
    rich = "rich"


class LogLevel(str, Enum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"


# Type aliases for reusable options
StdioOpt = Annotated[
    Optional[str],
    typer.Option(
        "--stdio", "-s",
        help="Connect via stdio: 'command arg1 arg2...' (quote the entire command)",
    ),
]

SseOpt = Annotated[
    Optional[str],
    typer.Option("--sse", help="Connect via SSE to URL"),
]

HttpOpt = Annotated[
    Optional[str],
    typer.Option("--http", help="Connect via Streamable HTTP to URL"),
]

UvOpt = Annotated[
    Optional[str],
    typer.Option(
        "--uv",
        help="Connect to UV-installed MCP server (e.g., 'mcp-server-filesystem')",
    ),
]

UvLocalPathOpt = Annotated[
    Optional[Path],
    typer.Option(
        "--uv-local-path",
        help="Project path for local UV-based MCP server",
    ),
]

UvLocalNameOpt = Annotated[
    Optional[str],
    typer.Option(
        "--uv-local-name",
        help="Server name for local UV-based MCP server",
    ),
]

PythonOpt = Annotated[
    Optional[str],
    typer.Option("--python", help="Python version for UV modes (e.g., '3.11')"),
]

WithOpt = Annotated[
    Optional[list[str]],
    typer.Option("--with", help="Additional packages for UV modes (repeatable)"),
]

TimeoutOpt = Annotated[
    float,
    typer.Option("--timeout", "-t", help="Connection timeout in seconds"),
]

LogLevelOpt = Annotated[
    LogLevel,
    typer.Option("--log-level", "-l", help="Log level"),
]

OutputOpt = Annotated[
    OutputFormat,
    typer.Option("--output", "-o", help="Output format"),
]


def validate_connection_options(
    stdio: Optional[str],
    sse: Optional[str],
    http: Optional[str],
    uv: Optional[str],
    uv_local_path: Optional[Path],
    uv_local_name: Optional[str],
) -> None:
    """Ensure exactly one connection method is specified."""
    # Count connection methods
    methods = [
        stdio is not None,
        sse is not None,
        http is not None,
        uv is not None,
        uv_local_path is not None or uv_local_name is not None,
    ]
    count = sum(methods)

    if count == 0:
        raise typer.BadParameter(
            "Must specify a connection method: --stdio, --sse, --http, --uv, or --uv-local-path/--uv-local-name"
        )

    if count > 1:
        raise typer.BadParameter(
            "Only one connection method allowed: --stdio, --sse, --http, --uv, or --uv-local-path/--uv-local-name"
        )

    # Check uv-local-path and uv-local-name are used together
    if (uv_local_path is not None) != (uv_local_name is not None):
        raise typer.BadParameter(
            "--uv-local-path and --uv-local-name must be used together"
        )


def build_config(
    stdio: Optional[str],
    sse: Optional[str],
    http: Optional[str],
    uv: Optional[str],
    uv_local_path: Optional[Path],
    uv_local_name: Optional[str],
    python_version: Optional[str],
    with_packages: Optional[list[str]],
    timeout: float,
) -> ClientConfig:
    """Build a ClientConfig from parsed options."""
    if stdio:
        parts = shlex.split(stdio)
        command = parts[0]
        cmd_args = parts[1:] if len(parts) > 1 else []
        return ClientConfig.for_stdio(command=command, args=cmd_args)
    elif sse:
        return ClientConfig.for_sse(url=sse, timeout=timeout)
    elif http:
        return ClientConfig.for_http(url=http, timeout=timeout)
    elif uv:
        return ClientConfig.for_uv_installed(
            server_name=uv,
            python_version=python_version,
            with_packages=with_packages or None,
        )
    elif uv_local_path and uv_local_name:
        return ClientConfig.for_uv_local(
            project_path=str(uv_local_path),
            server_name=uv_local_name,
            python_version=python_version,
            with_packages=with_packages or None,
        )
    else:
        raise ValueError("No connection method specified")


def version_callback(value: bool) -> None:
    """Print version and exit."""
    if value:
        console.print(f"mamba-mcp-client {__version__}")
        raise typer.Exit()


@app.callback()
def main_callback(
    version: Annotated[
        bool,
        typer.Option(
            "--version",
            callback=version_callback,
            is_eager=True,
            help="Show version and exit",
        ),
    ] = False,
    env: Annotated[
        Optional[Path],
        typer.Option("--env", "-e", help="Path to .env file to load environment variables from"),
    ] = None,
) -> None:
    """MCP Client for testing and debugging MCP Servers."""
    if env and env.exists():
        load_dotenv(env)
        console.print(f"[dim]Loaded environment from {env}[/]")
    elif env:
        console.print(f"[yellow]Warning: .env file not found at {env}[/]")


@app.command()
def tui(
    stdio: StdioOpt = None,
    sse: SseOpt = None,
    http: HttpOpt = None,
    uv: UvOpt = None,
    uv_local_path: UvLocalPathOpt = None,
    uv_local_name: UvLocalNameOpt = None,
    python: PythonOpt = None,
    with_packages: WithOpt = None,
    timeout: TimeoutOpt = 30.0,
    log_level: LogLevelOpt = LogLevel.INFO,
) -> None:
    """Launch the interactive TUI."""
    validate_connection_options(stdio, sse, http, uv, uv_local_path, uv_local_name)
    config = build_config(
        stdio, sse, http, uv, uv_local_path, uv_local_name, python, with_packages, timeout
    )
    app_tui = MCPTestApp(config)
    app_tui.run()


@app.command()
def connect(
    stdio: StdioOpt = None,
    sse: SseOpt = None,
    http: HttpOpt = None,
    uv: UvOpt = None,
    uv_local_path: UvLocalPathOpt = None,
    uv_local_name: UvLocalNameOpt = None,
    python: PythonOpt = None,
    with_packages: WithOpt = None,
    timeout: TimeoutOpt = 30.0,
    log_level: LogLevelOpt = LogLevel.INFO,
    output: OutputOpt = OutputFormat.rich,
) -> None:
    """Connect and inspect server."""
    validate_connection_options(stdio, sse, http, uv, uv_local_path, uv_local_name)
    config = build_config(
        stdio, sse, http, uv, uv_local_path, uv_local_name, python, with_packages, timeout
    )
    asyncio.run(_cmd_connect(config, output))


async def _cmd_connect(config: ClientConfig, output: OutputFormat) -> None:
    """Connect and show server info."""
    client = MCPTestClient(config)

    async with client.connect():
        if client.server_info:
            info = client.server_info
            if output == OutputFormat.json:
                console.print_json(
                    json.dumps(
                        {
                            "name": info.name,
                            "version": info.version,
                            "protocol_version": info.protocol_version,
                            "instructions": info.instructions,
                            "capabilities": {
                                "tools": info.capabilities.tools if info.capabilities else False,
                                "resources": info.capabilities.resources
                                if info.capabilities
                                else False,
                                "prompts": info.capabilities.prompts
                                if info.capabilities
                                else False,
                                "logging": info.capabilities.logging
                                if info.capabilities
                                else False,
                            },
                        }
                    )
                )
            else:
                table = Table(title="Server Information")
                table.add_column("Property", style="bold")
                table.add_column("Value")

                table.add_row("Name", info.name)
                table.add_row("Version", info.version)
                table.add_row("Protocol", info.protocol_version)
                table.add_row("Instructions", info.instructions or "-")

                if info.capabilities:
                    caps = []
                    if info.capabilities.tools:
                        caps.append("tools")
                    if info.capabilities.resources:
                        caps.append("resources")
                    if info.capabilities.prompts:
                        caps.append("prompts")
                    if info.capabilities.logging:
                        caps.append("logging")
                    table.add_row("Capabilities", ", ".join(caps) or "-")

                console.print(table)


@app.command()
def tools(
    stdio: StdioOpt = None,
    sse: SseOpt = None,
    http: HttpOpt = None,
    uv: UvOpt = None,
    uv_local_path: UvLocalPathOpt = None,
    uv_local_name: UvLocalNameOpt = None,
    python: PythonOpt = None,
    with_packages: WithOpt = None,
    timeout: TimeoutOpt = 30.0,
    log_level: LogLevelOpt = LogLevel.INFO,
    output: OutputOpt = OutputFormat.rich,
) -> None:
    """List available tools."""
    validate_connection_options(stdio, sse, http, uv, uv_local_path, uv_local_name)
    config = build_config(
        stdio, sse, http, uv, uv_local_path, uv_local_name, python, with_packages, timeout
    )
    asyncio.run(_cmd_tools(config, output))


async def _cmd_tools(config: ClientConfig, output: OutputFormat) -> None:
    """List available tools."""
    client = MCPTestClient(config)

    async with client.connect():
        tools_list = await client.list_tools()

        if output == OutputFormat.json:
            console.print_json(
                json.dumps([{"name": t.name, "description": t.description} for t in tools_list])
            )
        else:
            table = Table(title="Available Tools")
            table.add_column("Name", style="bold cyan")
            table.add_column("Description")

            for tool in tools_list:
                table.add_row(tool.name, tool.description or "-")

            console.print(table)


@app.command()
def resources(
    stdio: StdioOpt = None,
    sse: SseOpt = None,
    http: HttpOpt = None,
    uv: UvOpt = None,
    uv_local_path: UvLocalPathOpt = None,
    uv_local_name: UvLocalNameOpt = None,
    python: PythonOpt = None,
    with_packages: WithOpt = None,
    timeout: TimeoutOpt = 30.0,
    log_level: LogLevelOpt = LogLevel.INFO,
    output: OutputOpt = OutputFormat.rich,
) -> None:
    """List available resources."""
    validate_connection_options(stdio, sse, http, uv, uv_local_path, uv_local_name)
    config = build_config(
        stdio, sse, http, uv, uv_local_path, uv_local_name, python, with_packages, timeout
    )
    asyncio.run(_cmd_resources(config, output))


async def _cmd_resources(config: ClientConfig, output: OutputFormat) -> None:
    """List available resources."""
    client = MCPTestClient(config)

    async with client.connect():
        resources_list = await client.list_resources()

        if output == OutputFormat.json:
            console.print_json(
                json.dumps(
                    [
                        {"name": r.name, "uri": str(r.uri), "description": r.description}
                        for r in resources_list
                    ]
                )
            )
        else:
            table = Table(title="Available Resources")
            table.add_column("Name", style="bold cyan")
            table.add_column("URI")
            table.add_column("Description")

            for resource in resources_list:
                table.add_row(resource.name, str(resource.uri), resource.description or "-")

            console.print(table)


@app.command()
def prompts(
    stdio: StdioOpt = None,
    sse: SseOpt = None,
    http: HttpOpt = None,
    uv: UvOpt = None,
    uv_local_path: UvLocalPathOpt = None,
    uv_local_name: UvLocalNameOpt = None,
    python: PythonOpt = None,
    with_packages: WithOpt = None,
    timeout: TimeoutOpt = 30.0,
    log_level: LogLevelOpt = LogLevel.INFO,
    output: OutputOpt = OutputFormat.rich,
) -> None:
    """List available prompts."""
    validate_connection_options(stdio, sse, http, uv, uv_local_path, uv_local_name)
    config = build_config(
        stdio, sse, http, uv, uv_local_path, uv_local_name, python, with_packages, timeout
    )
    asyncio.run(_cmd_prompts(config, output))


async def _cmd_prompts(config: ClientConfig, output: OutputFormat) -> None:
    """List available prompts."""
    client = MCPTestClient(config)

    async with client.connect():
        prompts_list = await client.list_prompts()

        if output == OutputFormat.json:
            console.print_json(
                json.dumps([{"name": p.name, "description": p.description} for p in prompts_list])
            )
        else:
            table = Table(title="Available Prompts")
            table.add_column("Name", style="bold cyan")
            table.add_column("Description")

            for prompt in prompts_list:
                table.add_row(prompt.name, prompt.description or "-")

            console.print(table)


@app.command()
def call(
    tool_name: Annotated[str, typer.Argument(help="Name of the tool to call")],
    stdio: StdioOpt = None,
    sse: SseOpt = None,
    http: HttpOpt = None,
    uv: UvOpt = None,
    uv_local_path: UvLocalPathOpt = None,
    uv_local_name: UvLocalNameOpt = None,
    python: PythonOpt = None,
    with_packages: WithOpt = None,
    timeout: TimeoutOpt = 30.0,
    log_level: LogLevelOpt = LogLevel.INFO,
    output: OutputOpt = OutputFormat.rich,
    args: Annotated[str, typer.Option("--args", "-a", help="Tool arguments as JSON string")] = "{}",
) -> None:
    """Call a tool."""
    validate_connection_options(stdio, sse, http, uv, uv_local_path, uv_local_name)
    config = build_config(
        stdio, sse, http, uv, uv_local_path, uv_local_name, python, with_packages, timeout
    )
    asyncio.run(_cmd_call(config, output, tool_name, args))


async def _cmd_call(
    config: ClientConfig, output: OutputFormat, tool_name: str, args: str
) -> None:
    """Call a tool."""
    client = MCPTestClient(config)

    try:
        tool_args = json.loads(args)
    except json.JSONDecodeError as e:
        console.print(f"[red]Invalid JSON arguments:[/] {e}")
        sys.exit(1)

    async with client.connect():
        result = await client.call_tool(tool_name, tool_args)

        if output == OutputFormat.json:
            output_data = {
                "tool": result.tool_name,
                "arguments": result.arguments,
                "is_error": result.is_error,
                "content": [str(c) for c in result.content],
            }
            if result.text:
                output_data["text"] = result.text
            console.print_json(json.dumps(output_data))
        else:
            if result.is_error:
                console.print("[red]Tool returned error:[/]")
            else:
                console.print("[green]Tool result:[/]")

            if result.text:
                console.print(result.text)
            else:
                for content in result.content:
                    console.print(content)


@app.command()
def read(
    uri: Annotated[str, typer.Argument(help="Resource URI to read")],
    stdio: StdioOpt = None,
    sse: SseOpt = None,
    http: HttpOpt = None,
    uv: UvOpt = None,
    uv_local_path: UvLocalPathOpt = None,
    uv_local_name: UvLocalNameOpt = None,
    python: PythonOpt = None,
    with_packages: WithOpt = None,
    timeout: TimeoutOpt = 30.0,
    log_level: LogLevelOpt = LogLevel.INFO,
    output: OutputOpt = OutputFormat.rich,
) -> None:
    """Read a resource."""
    validate_connection_options(stdio, sse, http, uv, uv_local_path, uv_local_name)
    config = build_config(
        stdio, sse, http, uv, uv_local_path, uv_local_name, python, with_packages, timeout
    )
    asyncio.run(_cmd_read(config, output, uri))


async def _cmd_read(config: ClientConfig, output: OutputFormat, uri: str) -> None:
    """Read a resource."""
    client = MCPTestClient(config)

    async with client.connect():
        result = await client.read_resource(uri)

        if output == OutputFormat.json:
            console.print_json(json.dumps(result.model_dump(), default=str))
        else:
            console.print(f"[bold]Resource:[/] {uri}\n")
            for content in result.contents:
                if hasattr(content, "text"):
                    console.print(content.text)
                else:
                    console.print(content)


@app.command()
def prompt(
    prompt_name: Annotated[str, typer.Argument(help="Name of the prompt")],
    stdio: StdioOpt = None,
    sse: SseOpt = None,
    http: HttpOpt = None,
    uv: UvOpt = None,
    uv_local_path: UvLocalPathOpt = None,
    uv_local_name: UvLocalNameOpt = None,
    python: PythonOpt = None,
    with_packages: WithOpt = None,
    timeout: TimeoutOpt = 30.0,
    log_level: LogLevelOpt = LogLevel.INFO,
    output: OutputOpt = OutputFormat.rich,
    args: Annotated[str, typer.Option("--args", "-a", help="Prompt arguments as JSON string")] = "{}",
) -> None:
    """Get a prompt."""
    validate_connection_options(stdio, sse, http, uv, uv_local_path, uv_local_name)
    config = build_config(
        stdio, sse, http, uv, uv_local_path, uv_local_name, python, with_packages, timeout
    )
    asyncio.run(_cmd_prompt(config, output, prompt_name, args))


async def _cmd_prompt(
    config: ClientConfig, output: OutputFormat, prompt_name: str, args: str
) -> None:
    """Get a prompt."""
    client = MCPTestClient(config)

    try:
        prompt_args = json.loads(args)
    except json.JSONDecodeError as e:
        console.print(f"[red]Invalid JSON arguments:[/] {e}")
        sys.exit(1)

    async with client.connect():
        result = await client.get_prompt(prompt_name, prompt_args)

        if output == OutputFormat.json:
            console.print_json(json.dumps(result.model_dump(), default=str))
        else:
            console.print(f"[bold]Prompt:[/] {prompt_name}\n")
            for message in result.messages:
                role = message.role
                console.print(f"[bold cyan]{role}:[/]")
                if hasattr(message.content, "text"):
                    console.print(message.content.text)
                else:
                    console.print(message.content)
                console.print()


def main() -> None:
    """Main entry point."""
    try:
        app()
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted[/]")
    except Exception as e:
        console.print(f"[red]Error:[/] {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
