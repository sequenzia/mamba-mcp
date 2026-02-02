"""Shared CLI utilities for MCP server entry points.

Provides common Typer callbacks and helpers used by all server packages:
- validate_env_file: Typer callback for --env-file option validation
- resolve_default_env_file: Cascading env file discovery (cwd > home)
- setup_logging: Configures logging with json or text format to stderr
"""

import logging
import sys
from pathlib import Path

import typer


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
