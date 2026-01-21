"""
mamba-mcp-client - A Python-based MCP Client for testing and debugging MCP Servers.

This package provides both a programmatic Python API and a terminal TUI interface
for testing and debugging MCP (Model Context Protocol) servers.
"""

from mamba_mcp_client.client import MCPTestClient
from mamba_mcp_client.config import ClientConfig, TransportType

__version__ = "1.0.0"
__all__ = ["MCPTestClient", "ClientConfig", "TransportType"]
