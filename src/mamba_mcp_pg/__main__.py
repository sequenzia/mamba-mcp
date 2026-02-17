"""Entry point for the PostgreSQL MCP Server."""

import asyncio
import logging
import os
from typing import Annotated

import typer

from mamba_mcp_core.cli import resolve_default_env_file, setup_logging, validate_env_file
from mamba_mcp_core.transport import normalize_transport
from mamba_mcp_pg.config import get_settings, set_env_file_path
from mamba_mcp_pg.database.engine import create_engine, dispose_engine, test_connection
from mamba_mcp_pg.server import mcp

# Import tools to register them with the server
from mamba_mcp_pg.tools import query_tools, relationship_tools, schema_tools  # noqa: F401

app = typer.Typer(
    name="mamba-mcp-pg",
    no_args_is_help=False,
)


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    env_file: Annotated[
        str | None,
        typer.Option(
            "--env-file",
            help="Path to .env file (default: ./mamba.env or ~/mamba.env)",
            callback=validate_env_file,
            metavar="PATH",
        ),
    ] = None,
) -> None:
    """PostgreSQL MCP Server for database access via Model Context Protocol."""
    # Resolve default .env file if not explicitly provided
    resolved_env_file = resolve_default_env_file(env_file)

    # If a subcommand is being invoked, just set env_file and return
    if ctx.invoked_subcommand is not None:
        set_env_file_path(resolved_env_file)
        return

    # No subcommand - start the server
    set_env_file_path(resolved_env_file)

    settings = get_settings()

    setup_logging(settings.server.log_level, settings.server.log_format)

    logger = logging.getLogger(__name__)
    logger.info(f"Starting PostgreSQL MCP Server with {settings.server.transport} transport")

    # Run with appropriate transport
    transport = normalize_transport(settings.server.transport)
    if transport == "stdio":
        mcp.run(transport="stdio")
    else:
        # Set host/port via environment variables for uvicorn
        os.environ.setdefault("UVICORN_HOST", settings.server.server_host)
        os.environ.setdefault("UVICORN_PORT", str(settings.server.server_port))
        mcp.run(transport="streamable-http")


@app.command()
def test() -> None:
    """Test database connection and exit."""
    # env_file is set by the callback
    settings = get_settings()

    async def run_test() -> bool:
        engine = await create_engine(settings.database)
        try:
            await test_connection(engine)
            return True
        except Exception as e:
            typer.echo(f"Connection failed: {e}", err=True)
            return False
        finally:
            await dispose_engine(engine)

    if asyncio.run(run_test()):
        typer.echo("Connection successful")
        raise typer.Exit(0)
    else:
        raise typer.Exit(1)


if __name__ == "__main__":
    app()
