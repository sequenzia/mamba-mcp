"""Entry point for the PostgreSQL MCP Server."""

import asyncio
import logging
import os
import sys
from pathlib import Path
from typing import Annotated

import typer

from mamba_mcp_pg.config import get_settings, set_env_file_path
from mamba_mcp_pg.database.engine import create_engine, dispose_engine, test_connection
from mamba_mcp_pg.server import mcp

# Import tools to register them with the server
from mamba_mcp_pg.tools import query_tools, relationship_tools, schema_tools  # noqa: F401

app = typer.Typer(
    name="mamba-mcp-pg",
    no_args_is_help=False,
)


def validate_env_file(ctx: typer.Context, value: str | None) -> str | None:
    """Validate that the specified env file exists.

    Args:
        ctx: Typer context for handling shell completion.
        value: Path to env file, or None if not specified.

    Returns:
        Resolved absolute path to the env file, or None if not specified.

    Raises:
        typer.BadParameter: If the file doesn't exist or is not a file.
    """
    # Skip validation during shell completion
    if ctx.resilient_parsing:
        return None

    if value is None:
        return None

    env_path = Path(value)
    if not env_path.exists():
        raise typer.BadParameter(f"Environment file not found: {value}")
    if not env_path.is_file():
        raise typer.BadParameter(f"Path is not a file: {value}")
    return str(env_path.resolve())


def resolve_default_env_file(env_file: str | None) -> str | None:
    """Resolve default env file if --env-file not specified.

    Checks for mamba.env in the current directory first, then in the
    user's home directory as a global fallback.

    Args:
        env_file: Explicitly provided env file path, or None.

    Returns:
        The provided path if set, otherwise the resolved path to
        mamba.env if found in cwd or home directory, or None.
    """
    if env_file is not None:
        return env_file

    # Check project-local first, then home directory
    candidates = [
        Path.cwd() / "mamba.env",
        Path.home() / "mamba.env",
    ]
    for candidate in candidates:
        if candidate.exists() and candidate.is_file():
            return str(candidate.resolve())
    return None


def setup_logging(level: str, format_type: str) -> None:
    """Configure logging based on settings.

    Args:
        level: Logging level (DEBUG, INFO, WARNING, ERROR).
        format_type: Log format type ('json' or 'text').
    """
    if format_type == "json":
        log_format = (
            '{"time": "%(asctime)s", "name": "%(name)s", '
            '"level": "%(levelname)s", "message": "%(message)s"}'
        )
    else:
        log_format = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

    logging.basicConfig(
        level=level.upper(),
        format=log_format,
        stream=sys.stderr,  # MCP stdio uses stdout, so log to stderr
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
    if settings.server.transport == "stdio":
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
