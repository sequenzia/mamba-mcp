"""Tests for mamba_mcp_core.config module."""

import pytest
from mamba_mcp_core.config import get_env_file_path, set_env_file_path


@pytest.fixture(autouse=True)
def reset_env_file_path() -> None:
    """Reset module-level state between tests."""
    set_env_file_path(None)


class TestEnvFilePathState:
    """Tests for env file path state management."""

    def test_default_is_none(self) -> None:
        """Default env file path is None."""
        assert get_env_file_path() is None

    def test_set_and_get(self) -> None:
        """Set and retrieve env file path."""
        set_env_file_path("/path/to/mamba.env")
        assert get_env_file_path() == "/path/to/mamba.env"

    def test_set_none_resets(self) -> None:
        """Setting None resets the path."""
        set_env_file_path("/some/path")
        set_env_file_path(None)
        assert get_env_file_path() is None

    def test_overwrite(self) -> None:
        """Setting a new path overwrites the previous one."""
        set_env_file_path("/first/path")
        set_env_file_path("/second/path")
        assert get_env_file_path() == "/second/path"
