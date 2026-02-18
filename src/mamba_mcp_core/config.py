"""Shared configuration state management for MCP server packages.

Provides the module-level env file path state that bridges CLI arg parsing
to Pydantic settings loading. Each server package imports these functions
instead of maintaining its own global state.
"""

# Module-level state for env file path
_env_file_path: str | None = None


def set_env_file_path(path: str | None) -> None:
    """Set the env file path for settings to use.

    Args:
        path: Path to .env file, or None to use default (mamba.env in current directory).
    """
    global _env_file_path
    _env_file_path = path


def get_env_file_path() -> str | None:
    """Get the currently configured env file path.

    Returns:
        The configured env file path, or None if using default.
    """
    return _env_file_path
