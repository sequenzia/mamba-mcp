"""Entry point for the GitLab MCP Server.

Provides a Typer CLI with:
- Default command: Start the MCP server (STDIO or Streamable HTTP)
- ``test`` subcommand: Verify GitLab connectivity and token validity
- ``--env-file`` option: Specify custom config file path

Uses mamba-mcp-core for shared CLI utilities, transport normalization,
and env file handling.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Annotated

import httpx
import typer
from mamba_mcp_core.cli import resolve_default_env_file, setup_logging, validate_env_file
from mamba_mcp_core.transport import normalize_transport

from mamba_mcp_gitlab.auth import AuthenticationError, detect_auth_strategy
from mamba_mcp_gitlab.config import get_settings, set_env_file_path
from mamba_mcp_gitlab.server import mcp

# Import tools to register them with the server
from mamba_mcp_gitlab.tools import (  # noqa: F401
    issue_tools,
    mr_tools,
    pipeline_tools,
    search_tools,
)

app = typer.Typer(
    name="mamba-mcp-gitlab",
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
    """GitLab MCP Server for merge requests, issues, pipelines, and search."""
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

    # Determine transport: normalize "http" -> "streamable-http"
    effective_transport = normalize_transport(settings.server.transport)

    logger.info(
        "Starting GitLab MCP Server with %s transport",
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
    """Test GitLab connectivity and token validity."""
    # env_file is set by the callback
    settings = get_settings()

    async def run_test() -> bool:
        # Detect auth strategy from settings
        try:
            auth_strategy = detect_auth_strategy(settings)
        except AuthenticationError as exc:
            typer.echo(f"Authentication configuration error: {exc}", err=True)
            return False

        # Create a temporary httpx client for validation
        base_url = settings.gitlab.url.rstrip("/")
        auth_headers = auth_strategy.get_headers()
        client = httpx.AsyncClient(
            base_url=base_url,
            headers=auth_headers,
            verify=settings.gitlab.verify_ssl,
        )

        try:
            auth_info = await auth_strategy.validate(client)
            scopes_str = ", ".join(auth_info.scopes) if auth_info.scopes else "none"
            typer.echo(
                f"Connection successful \u2014 authenticated as "
                f"{auth_info.username} with scopes: {scopes_str}"
            )
            return True
        except AuthenticationError as exc:
            typer.echo(f"Connection failed: {exc}", err=True)
            return False
        finally:
            await client.aclose()

    if asyncio.run(run_test()):
        raise typer.Exit(0)
    else:
        raise typer.Exit(1)


if __name__ == "__main__":
    app()
