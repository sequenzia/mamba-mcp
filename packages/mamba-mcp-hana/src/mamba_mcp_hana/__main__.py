"""Entry point for the SAP HANA MCP Server.

Provides a Typer CLI with:
- Default command: Start the MCP server (STDIO or Streamable HTTP)
- `test` subcommand: Verify database connectivity
- `--env-file` option: Specify custom config file path

Uses mamba-mcp-core for shared CLI utilities, transport normalization,
and env file handling.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Annotated

import typer
from mamba_mcp_core.cli import resolve_default_env_file, setup_logging, validate_env_file
from mamba_mcp_core.transport import normalize_transport

from mamba_mcp_hana.config import get_settings, set_env_file_path
from mamba_mcp_hana.database.connection import create_pool
from mamba_mcp_hana.server import mcp

app = typer.Typer(
    name="mamba-mcp-hana",
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
    """SAP HANA MCP Server for database access via Model Context Protocol."""
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

    # Determine transport: normalize "http" → "streamable-http"
    effective_transport = normalize_transport(settings.server.transport)

    logger.info(
        "Starting SAP HANA MCP Server with %s transport",
        effective_transport,
    )

    # Run with appropriate transport
    if effective_transport == "stdio":
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
        pool = await create_pool(settings.database)
        try:
            await pool.test_connection()
            return True
        except Exception as e:
            typer.echo(f"Connection failed: {e}", err=True)
            return False
        finally:
            await pool.close()

    if asyncio.run(run_test()):
        typer.echo("Connection successful")
        raise typer.Exit(0)
    else:
        raise typer.Exit(1)


if __name__ == "__main__":
    app()
