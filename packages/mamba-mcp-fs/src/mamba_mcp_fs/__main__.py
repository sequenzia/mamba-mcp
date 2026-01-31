"""Entry point for the Filesystem MCP Server.

Provides a Typer CLI with:
- Default command: Start the MCP server (STDIO or Streamable HTTP)
- `test` subcommand: Verify configuration and backend connectivity
- `--env-file` option: Specify custom config file path
- `--transport` option: Override transport setting

Based on spec Section 7.1, 7.3, 5.4 -- following the mamba-mcp-postgres pattern.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import Annotated

import typer

from mamba_mcp_fs.config import get_settings, set_env_file_path
from mamba_mcp_fs.server import _register_tools, mcp

app = typer.Typer(
    name="mamba-mcp-fs",
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
    transport: Annotated[
        str | None,
        typer.Option(
            "--transport",
            help="Override transport (stdio or streamable-http)",
            metavar="TRANSPORT",
        ),
    ] = None,
) -> None:
    """Filesystem MCP Server for file access via Model Context Protocol."""
    # Resolve default .env file if not explicitly provided
    resolved_env_file = resolve_default_env_file(env_file)

    # If a subcommand is being invoked, just set env_file and return
    if ctx.invoked_subcommand is not None:
        set_env_file_path(resolved_env_file)
        return

    # No subcommand -- start the server
    set_env_file_path(resolved_env_file)

    settings = get_settings()

    setup_logging(settings.server.log_level, settings.server.log_format)

    logger = logging.getLogger(__name__)

    # Register tool modules based on configuration
    registered = _register_tools(mcp, settings)
    logger.info("Registered tool modules: %s", registered)

    # Determine transport: CLI flag overrides config
    effective_transport = transport if transport is not None else settings.server.transport

    logger.info(
        "Starting Filesystem MCP Server with %s transport",
        effective_transport,
    )

    # Run with appropriate transport
    if effective_transport == "stdio":
        mcp.run(transport="stdio")
    else:
        # Set host/port for the HTTP server
        os.environ.setdefault("UVICORN_HOST", settings.server.server_host)
        os.environ.setdefault("UVICORN_PORT", str(settings.server.server_port))
        mcp.run(transport="streamable-http")


@app.command()
def test() -> None:
    """Test configuration and backend connectivity."""
    version = "0.1.0"
    has_error = False
    issues: list[str] = []

    # Load settings -- catch config errors so we can report them gracefully
    try:
        settings = get_settings()
    except Exception as e:
        typer.echo(f"mamba-mcp-fs v{version}")
        typer.echo("=" * 40)
        typer.echo(f"Configuration error: {e}")
        typer.echo("")
        typer.echo("Status: FAIL")
        raise typer.Exit(1) from None

    # Header
    typer.echo(f"mamba-mcp-fs v{version}")
    typer.echo("=" * 40)

    mode = "read-only" if settings.server.read_only else "read-write"
    typer.echo(f"Transport: {settings.server.transport}")
    typer.echo(f"Mode: {mode}")
    typer.echo("")

    # --- Local Backend ---
    if settings.local.enabled:
        typer.echo("Local Backend: ENABLED")
        typer.echo(f"  Base path: {settings.local.base_path}")

        base = Path(settings.local.base_path)

        # Check: exists
        if not base.exists():
            typer.echo("  Exists: FAIL (path does not exist)")
            issues.append(f"Local base_path does not exist: {settings.local.base_path}")
            has_error = True
        elif not base.is_dir():
            typer.echo("  Exists: FAIL (path is not a directory)")
            issues.append(f"Local base_path is not a directory: {settings.local.base_path}")
            has_error = True
        else:
            typer.echo("  Exists: OK")

            # Check: readable
            if os.access(base, os.R_OK):
                typer.echo("  Readable: OK")
            else:
                typer.echo("  Readable: FAIL")
                issues.append(f"Local base_path is not readable: {settings.local.base_path}")
                has_error = True

            # Check: writable (only if not read_only)
            if not settings.server.read_only:
                if os.access(base, os.W_OK):
                    typer.echo("  Writable: OK")
                else:
                    typer.echo("  Writable: FAIL")
                    issues.append(f"Local base_path is not writable: {settings.local.base_path}")
                    has_error = True

            # Count entries
            try:
                file_count = 0
                dir_count = 0
                for entry in base.iterdir():
                    if entry.is_dir():
                        dir_count += 1
                    else:
                        file_count += 1
                typer.echo(f"  Entries: {file_count} files, {dir_count} directories")
            except PermissionError:
                typer.echo("  Entries: FAIL (permission denied)")
                issues.append(f"Cannot list entries in base_path: {settings.local.base_path}")
                has_error = True
    else:
        typer.echo("Local Backend: DISABLED")
    typer.echo("")

    # --- S3 Backend ---
    if settings.s3.enabled:
        typer.echo("S3 Backend: ENABLED")
        typer.echo(f"  Region: {settings.s3.region}")
        endpoint_display = settings.s3.endpoint_url if settings.s3.endpoint_url else "(default AWS)"
        typer.echo(f"  Endpoint: {endpoint_display}")

        # Verify S3 connectivity
        try:
            from botocore.exceptions import (
                ClientError,
                EndpointConnectionError,
                NoCredentialsError,
            )

            from mamba_mcp_fs.backends.s3 import S3Backend

            s3_backend = S3Backend(settings.s3)

            # Check authentication by listing buckets
            try:
                buckets = s3_backend.fs.ls("", detail=False)
                bucket_count = len(buckets)
                typer.echo("  Authentication: OK")
                typer.echo(f"  Buckets accessible: {bucket_count}")
            except NoCredentialsError:
                typer.echo("  Authentication: FAIL (no credentials found)")
                issues.append(
                    "S3 credentials not found. Configure AWS_ACCESS_KEY_ID and "
                    "AWS_SECRET_ACCESS_KEY, use an IAM role, or set up an AWS CLI profile."
                )
                has_error = True
                bucket_count = -1
            except EndpointConnectionError:
                typer.echo("  Authentication: FAIL (cannot connect to endpoint)")
                issues.append(
                    f"Cannot connect to S3 endpoint: {endpoint_display}. "
                    "Check network connectivity and endpoint URL."
                )
                has_error = True
                bucket_count = -1
            except ClientError as e:
                error_code = e.response.get("Error", {}).get("Code", "Unknown")
                error_msg = e.response.get("Error", {}).get("Message", str(e))
                typer.echo(f"  Authentication: FAIL ({error_code})")
                issues.append(f"S3 authentication failed: {error_code} - {error_msg}")
                has_error = True
                bucket_count = -1
            except OSError as e:
                typer.echo("  Authentication: FAIL (connection error)")
                issues.append(f"S3 connection error: {e}")
                has_error = True
                bucket_count = -1

            # Check default bucket if configured and auth succeeded
            if settings.s3.bucket and bucket_count >= 0:
                try:
                    bucket_exists = s3_backend.fs.exists(settings.s3.bucket)
                    if bucket_exists:
                        typer.echo(f"  Default bucket: {settings.s3.bucket} (accessible: OK)")
                    else:
                        typer.echo(
                            f"  Default bucket: {settings.s3.bucket} (accessible: FAIL "
                            "- bucket not found)"
                        )
                        issues.append(
                            f"Default S3 bucket '{settings.s3.bucket}' does not exist or "
                            "is not accessible with the current credentials."
                        )
                        has_error = True
                except NoCredentialsError:
                    typer.echo(
                        f"  Default bucket: {settings.s3.bucket} (accessible: FAIL "
                        "- no credentials)"
                    )
                    issues.append("Cannot verify default bucket: S3 credentials not found.")
                    has_error = True
                except EndpointConnectionError:
                    typer.echo(
                        f"  Default bucket: {settings.s3.bucket} (accessible: FAIL "
                        "- connection error)"
                    )
                    issues.append(
                        f"Cannot verify default bucket: cannot connect to "
                        f"S3 endpoint {endpoint_display}."
                    )
                    has_error = True
                except (ClientError, OSError) as e:
                    typer.echo(f"  Default bucket: {settings.s3.bucket} (accessible: FAIL)")
                    issues.append(f"Cannot verify default bucket '{settings.s3.bucket}': {e}")
                    has_error = True
            elif settings.s3.bucket and bucket_count < 0:
                typer.echo(f"  Default bucket: {settings.s3.bucket} (skipped - auth failed)")

        except ImportError:
            typer.echo("  Connectivity: FAIL (s3fs/botocore not installed)")
            issues.append("S3 dependencies not installed. Install s3fs and botocore.")
            has_error = True
    else:
        typer.echo("S3 Backend: DISABLED")
    typer.echo("")

    # --- Security ---
    typer.echo("Security:")
    typer.echo(f"  Follow symlinks: {str(settings.local.follow_symlinks).lower()}")
    typer.echo(f"  Show hidden: {str(settings.local.show_hidden).lower()}")
    typer.echo(f"  Allowed extensions: {settings.server.allowed_extensions or '(none)'}")
    typer.echo(f"  Denied extensions: {settings.server.denied_extensions or '(none)'}")
    rate = f"{settings.server.rate_limit}/min" if settings.server.rate_limit > 0 else "disabled"
    typer.echo(f"  Rate limit: {rate}")
    typer.echo("")

    # Check that at least one backend is enabled
    if not settings.local.enabled and not settings.s3.enabled:
        issues.append("No backends enabled. Enable at least one of: local, s3")
        has_error = True

    # Print issues if any
    if issues:
        typer.echo("Issues:")
        for issue in issues:
            typer.echo(f"  - {issue}")
        typer.echo("")

    # Summary
    if has_error:
        typer.echo("Status: FAIL")
        raise typer.Exit(1)
    else:
        typer.echo("Status: PASS")
        raise typer.Exit(0)


if __name__ == "__main__":
    app()
