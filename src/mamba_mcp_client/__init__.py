"""
mamba-mcp-client - A Python-based MCP Client for testing and debugging MCP Servers.

This package provides both a programmatic Python API and a terminal TUI interface
for testing and debugging MCP (Model Context Protocol) servers.
"""

from mamba_mcp_client.client import MCPTestClient
from mamba_mcp_client.config import ClientConfig, TransportType

# Version is dynamically set by hatch-vcs during build
__version__: str
try:
    from mamba_mcp_core._version import __version__
except ImportError:
    __version__ = "0.0.0.dev0"

__all__ = ["MCPTestClient", "ClientConfig", "TransportType", "__version__"]
