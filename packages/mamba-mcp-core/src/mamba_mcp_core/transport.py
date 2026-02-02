"""Transport name normalization for MCP server packages.

Resolves the transport naming inconsistency where PG/HANA accepted "http"
while FS accepted "streamable-http". This module normalizes both to
"streamable-http" which is the actual FastMCP transport name.
"""


def normalize_transport(value: str) -> str:
    """Normalize transport name to the canonical FastMCP value.

    Accepts both "http" and "streamable-http" and normalizes to
    "streamable-http". Passes "stdio" and other values through unchanged.

    Args:
        value: Transport name from configuration.

    Returns:
        Normalized transport name.
    """
    if value in ("http", "streamable-http"):
        return "streamable-http"
    return value
