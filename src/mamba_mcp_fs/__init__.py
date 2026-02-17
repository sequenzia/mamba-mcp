"""Filesystem MCP Server with local and S3 backend support."""

# Version is dynamically set by hatch-vcs during build
__version__: str
try:
    from mamba_mcp_core._version import __version__
except ImportError:
    __version__ = "0.0.0.dev0"
