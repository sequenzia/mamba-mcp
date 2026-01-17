"""CLI entry point for mamba-mcp-client with .env file support."""

import argparse
import asyncio
import json
import sys
from pathlib import Path

from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table

from mamba_mcp_client import __version__
from mamba_mcp_client.client import MCPTestClient
from mamba_mcp_client.config import ClientConfig, TransportType
from mamba_mcp_client.tui import MCPTestApp

console = Console()


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        prog="mamba-mcp",
        description="MCP Client for testing and debugging MCP Servers",
    )

    parser.add_argument(
        "--version",
        action="version",
        version=f"mamba-mcp-client {__version__}",
    )

    parser.add_argument(
        "--env",
        "-e",
        type=Path,
        help="Path to .env file to load environment variables from",
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # TUI command
    tui_parser = subparsers.add_parser("tui", help="Launch the interactive TUI")
    add_connection_args(tui_parser)

    # Connect command (for quick inspection)
    connect_parser = subparsers.add_parser("connect", help="Connect and inspect server")
    add_connection_args(connect_parser)

    # List tools command
    tools_parser = subparsers.add_parser("tools", help="List available tools")
    add_connection_args(tools_parser)

    # List resources command
    resources_parser = subparsers.add_parser("resources", help="List available resources")
    add_connection_args(resources_parser)

    # List prompts command
    prompts_parser = subparsers.add_parser("prompts", help="List available prompts")
    add_connection_args(prompts_parser)

    # Call tool command
    call_parser = subparsers.add_parser("call", help="Call a tool")
    add_connection_args(call_parser)
    call_parser.add_argument("tool_name", help="Name of the tool to call")
    call_parser.add_argument(
        "--args",
        "-a",
        type=str,
        default="{}",
        help="Tool arguments as JSON string",
    )

    # Read resource command
    read_parser = subparsers.add_parser("read", help="Read a resource")
    add_connection_args(read_parser)
    read_parser.add_argument("uri", help="Resource URI to read")

    # Get prompt command
    prompt_parser = subparsers.add_parser("prompt", help="Get a prompt")
    add_connection_args(prompt_parser)
    prompt_parser.add_argument("prompt_name", help="Name of the prompt")
    prompt_parser.add_argument(
        "--args",
        "-a",
        type=str,
        default="{}",
        help="Prompt arguments as JSON string",
    )

    return parser.parse_args()


def add_connection_args(parser: argparse.ArgumentParser) -> None:
    """Add connection arguments to a parser."""
    group = parser.add_mutually_exclusive_group(required=True)

    group.add_argument(
        "--stdio",
        "-s",
        nargs="+",
        metavar=("COMMAND", "ARG"),
        help="Connect via stdio: command [args...]",
    )

    group.add_argument(
        "--sse",
        type=str,
        metavar="URL",
        help="Connect via SSE to URL",
    )

    group.add_argument(
        "--http",
        type=str,
        metavar="URL",
        help="Connect via Streamable HTTP to URL",
    )

    group.add_argument(
        "--uv",
        type=str,
        metavar="SERVER_NAME",
        help="Connect to UV-installed MCP server (e.g., 'mcp-server-filesystem')",
    )

    group.add_argument(
        "--uv-local",
        nargs=2,
        metavar=("PROJECT_PATH", "SERVER_NAME"),
        help="Connect to local UV-based MCP server (e.g., './my-server my-mcp')",
    )

    # UV-specific options
    parser.add_argument(
        "--python",
        type=str,
        metavar="VERSION",
        help="Python version for UV modes (e.g., '3.11')",
    )

    parser.add_argument(
        "--with",
        dest="with_packages",
        action="append",
        default=[],
        metavar="PACKAGE",
        help="Additional packages for UV modes (repeatable)",
    )

    parser.add_argument(
        "--timeout",
        "-t",
        type=float,
        default=30.0,
        help="Connection timeout in seconds (default: 30)",
    )

    parser.add_argument(
        "--log-level",
        "-l",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default="INFO",
        help="Log level (default: INFO)",
    )

    parser.add_argument(
        "--output",
        "-o",
        choices=["json", "table", "rich"],
        default="rich",
        help="Output format (default: rich)",
    )


def build_config(args: argparse.Namespace) -> ClientConfig:
    """Build a ClientConfig from parsed arguments."""
    if args.stdio:
        command = args.stdio[0]
        cmd_args = args.stdio[1:] if len(args.stdio) > 1 else []
        return ClientConfig.for_stdio(
            command=command,
            args=cmd_args,
        )
    elif args.sse:
        return ClientConfig.for_sse(
            url=args.sse,
            timeout=args.timeout,
        )
    elif args.http:
        return ClientConfig.for_http(
            url=args.http,
            timeout=args.timeout,
        )
    elif args.uv:
        return ClientConfig.for_uv_installed(
            server_name=args.uv,
            python_version=getattr(args, "python", None),
            with_packages=getattr(args, "with_packages", None) or None,
        )
    elif args.uv_local:
        project_path, server_name = args.uv_local
        return ClientConfig.for_uv_local(
            project_path=project_path,
            server_name=server_name,
            python_version=getattr(args, "python", None),
            with_packages=getattr(args, "with_packages", None) or None,
        )
    else:
        raise ValueError("No connection method specified")


async def cmd_connect(config: ClientConfig, args: argparse.Namespace) -> None:
    """Connect and show server info."""
    client = MCPTestClient(config)

    async with client.connect():
        if client.server_info:
            info = client.server_info
            if args.output == "json":
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


async def cmd_tools(config: ClientConfig, args: argparse.Namespace) -> None:
    """List available tools."""
    client = MCPTestClient(config)

    async with client.connect():
        tools = await client.list_tools()

        if args.output == "json":
            console.print_json(
                json.dumps([{"name": t.name, "description": t.description} for t in tools])
            )
        else:
            table = Table(title="Available Tools")
            table.add_column("Name", style="bold cyan")
            table.add_column("Description")

            for tool in tools:
                table.add_row(tool.name, tool.description or "-")

            console.print(table)


async def cmd_resources(config: ClientConfig, args: argparse.Namespace) -> None:
    """List available resources."""
    client = MCPTestClient(config)

    async with client.connect():
        resources = await client.list_resources()

        if args.output == "json":
            console.print_json(
                json.dumps(
                    [
                        {"name": r.name, "uri": str(r.uri), "description": r.description}
                        for r in resources
                    ]
                )
            )
        else:
            table = Table(title="Available Resources")
            table.add_column("Name", style="bold cyan")
            table.add_column("URI")
            table.add_column("Description")

            for resource in resources:
                table.add_row(resource.name, str(resource.uri), resource.description or "-")

            console.print(table)


async def cmd_prompts(config: ClientConfig, args: argparse.Namespace) -> None:
    """List available prompts."""
    client = MCPTestClient(config)

    async with client.connect():
        prompts = await client.list_prompts()

        if args.output == "json":
            console.print_json(
                json.dumps([{"name": p.name, "description": p.description} for p in prompts])
            )
        else:
            table = Table(title="Available Prompts")
            table.add_column("Name", style="bold cyan")
            table.add_column("Description")

            for prompt in prompts:
                table.add_row(prompt.name, prompt.description or "-")

            console.print(table)


async def cmd_call(config: ClientConfig, args: argparse.Namespace) -> None:
    """Call a tool."""
    client = MCPTestClient(config)

    try:
        tool_args = json.loads(args.args)
    except json.JSONDecodeError as e:
        console.print(f"[red]Invalid JSON arguments:[/] {e}")
        sys.exit(1)

    async with client.connect():
        result = await client.call_tool(args.tool_name, tool_args)

        if args.output == "json":
            output = {
                "tool": result.tool_name,
                "arguments": result.arguments,
                "is_error": result.is_error,
                "content": [str(c) for c in result.content],
            }
            if result.text:
                output["text"] = result.text
            console.print_json(json.dumps(output))
        else:
            if result.is_error:
                console.print(f"[red]Tool returned error:[/]")
            else:
                console.print(f"[green]Tool result:[/]")

            if result.text:
                console.print(result.text)
            else:
                for content in result.content:
                    console.print(content)


async def cmd_read(config: ClientConfig, args: argparse.Namespace) -> None:
    """Read a resource."""
    client = MCPTestClient(config)

    async with client.connect():
        result = await client.read_resource(args.uri)

        if args.output == "json":
            console.print_json(json.dumps(result.model_dump(), default=str))
        else:
            console.print(f"[bold]Resource:[/] {args.uri}\n")
            for content in result.contents:
                if hasattr(content, "text"):
                    console.print(content.text)
                else:
                    console.print(content)


async def cmd_prompt(config: ClientConfig, args: argparse.Namespace) -> None:
    """Get a prompt."""
    client = MCPTestClient(config)

    try:
        prompt_args = json.loads(args.args)
    except json.JSONDecodeError as e:
        console.print(f"[red]Invalid JSON arguments:[/] {e}")
        sys.exit(1)

    async with client.connect():
        result = await client.get_prompt(args.prompt_name, prompt_args)

        if args.output == "json":
            console.print_json(json.dumps(result.model_dump(), default=str))
        else:
            console.print(f"[bold]Prompt:[/] {args.prompt_name}\n")
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
    args = parse_args()

    # Load .env file if specified
    if args.env:
        env_path = args.env.resolve()
        if env_path.exists():
            load_dotenv(env_path)
            console.print(f"[dim]Loaded environment from {env_path}[/]")
        else:
            console.print(f"[yellow]Warning: .env file not found at {env_path}[/]")

    # Handle no command
    if not args.command:
        console.print("Usage: mamba-mcp [--env FILE] <command> [options]")
        console.print("\nCommands:")
        console.print("  tui        Launch interactive TUI")
        console.print("  connect    Connect and show server info")
        console.print("  tools      List available tools")
        console.print("  resources  List available resources")
        console.print("  prompts    List available prompts")
        console.print("  call       Call a tool")
        console.print("  read       Read a resource")
        console.print("  prompt     Get a prompt")
        console.print("\nRun 'mamba-mcp <command> --help' for more info")
        sys.exit(0)

    # Build config
    try:
        config = build_config(args)
    except ValueError as e:
        console.print(f"[red]Configuration error:[/] {e}")
        sys.exit(1)

    # Run command
    if args.command == "tui":
        app = MCPTestApp(config)
        app.run()
    else:
        # Map commands to async functions
        commands = {
            "connect": cmd_connect,
            "tools": cmd_tools,
            "resources": cmd_resources,
            "prompts": cmd_prompts,
            "call": cmd_call,
            "read": cmd_read,
            "prompt": cmd_prompt,
        }

        cmd_func = commands.get(args.command)
        if cmd_func:
            try:
                asyncio.run(cmd_func(config, args))
            except KeyboardInterrupt:
                console.print("\n[yellow]Interrupted[/]")
            except Exception as e:
                console.print(f"[red]Error:[/] {e}")
                sys.exit(1)
        else:
            console.print(f"[red]Unknown command:[/] {args.command}")
            sys.exit(1)


if __name__ == "__main__":
    main()
