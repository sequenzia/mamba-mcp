"""Sample MCP server for testing mamba-mcp-client.

Run with: python examples/sample_server.py
"""

from fastmcp import FastMCP

# Create the server
mcp = FastMCP(
    name="sample-server",
    instructions="A sample MCP server for testing mamba-mcp-client",
)


@mcp.tool
def add(a: int, b: int) -> int:
    """Add two numbers together."""
    return a + b


@mcp.tool
def multiply(a: int, b: int) -> int:
    """Multiply two numbers together."""
    return a * b


@mcp.tool
def greet(name: str, greeting: str = "Hello") -> str:
    """Greet someone by name."""
    return f"{greeting}, {name}!"


@mcp.tool
def get_info() -> dict:
    """Get information about the server."""
    return {
        "name": "sample-server",
        "version": "1.0.0",
        "description": "A sample MCP server for testing",
    }


@mcp.resource("config://version")
def get_version() -> str:
    """Get the server version."""
    return "1.0.0"


@mcp.resource("config://settings")
def get_settings() -> str:
    """Get server settings as JSON."""
    import json

    return json.dumps(
        {
            "debug": True,
            "log_level": "INFO",
            "max_connections": 10,
        }
    )


@mcp.prompt
def code_review(language: str = "python") -> str:
    """Generate a prompt for code review."""
    return f"""Please review the following {language} code:

{{code}}

Focus on:
1. Code style and readability
2. Potential bugs or issues
3. Performance considerations
4. Best practices"""


@mcp.prompt
def summarize() -> str:
    """Generate a prompt for summarization."""
    return """Please summarize the following text:

{text}

Provide a concise summary in 2-3 sentences."""


if __name__ == "__main__":
    mcp.run()
