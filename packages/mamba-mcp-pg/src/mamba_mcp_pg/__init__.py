"""PostgreSQL MCP Server with layered schema discovery."""

# Version is dynamically set by hatch-vcs during build
__version__: str
try:
    from mamba_mcp_pg._version import __version__
except ImportError:
    __version__ = "0.0.0.dev0"
