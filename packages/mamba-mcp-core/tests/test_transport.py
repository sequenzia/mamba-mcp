"""Tests for mamba_mcp_core.transport module."""

import pytest
from mamba_mcp_core.transport import normalize_transport


class TestNormalizeTransport:
    """Tests for normalize_transport function."""

    def test_http_normalized(self) -> None:
        """'http' is normalized to 'streamable-http'."""
        assert normalize_transport("http") == "streamable-http"

    def test_streamable_http_passthrough(self) -> None:
        """'streamable-http' passes through unchanged."""
        assert normalize_transport("streamable-http") == "streamable-http"

    def test_stdio_passthrough(self) -> None:
        """'stdio' passes through unchanged."""
        assert normalize_transport("stdio") == "stdio"

    @pytest.mark.parametrize("value", ["sse", "websocket", "grpc", ""])
    def test_unknown_values_passthrough(self, value: str) -> None:
        """Unknown transport values pass through unchanged."""
        assert normalize_transport(value) == value
