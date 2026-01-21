"""Example demonstrating programmatic usage of mamba-mcp-client.

This script shows how to use the Python API for testing MCP servers.
"""

import asyncio

from mamba_mcp_client import MCPTestClient, ClientConfig


async def main() -> None:
    """Main example function."""
    # Create configuration for stdio transport
    config = ClientConfig.for_stdio(
        command="python",
        args=["examples/sample_server.py"],
    )

    # Create the client
    client = MCPTestClient(config)

    # Connect and use the client
    async with client.connect():
        # Print server info
        if client.server_info:
            print(f"Connected to: {client.server_info.name} v{client.server_info.version}")
            print(f"Instructions: {client.server_info.instructions}")
            print()

        # List and display tools
        print("=== Tools ===")
        tools = await client.list_tools()
        for tool in tools:
            print(f"  - {tool.name}: {tool.description}")
        print()

        # Call a tool
        print("=== Calling 'add' tool ===")
        result = await client.call_tool("add", {"a": 5, "b": 3})
        print(f"  Result: {result.text}")
        print()

        # Call another tool
        print("=== Calling 'greet' tool ===")
        result = await client.call_tool("greet", {"name": "World", "greeting": "Hello"})
        print(f"  Result: {result.text}")
        print()

        # List resources
        print("=== Resources ===")
        resources = await client.list_resources()
        for resource in resources:
            print(f"  - {resource.name}: {resource.uri}")
        print()

        # Read a resource
        print("=== Reading 'config://version' resource ===")
        content = await client.read_resource("config://version")
        for c in content.contents:
            if hasattr(c, "text"):
                print(f"  Content: {c.text}")
        print()

        # List prompts
        print("=== Prompts ===")
        prompts = await client.list_prompts()
        for prompt in prompts:
            print(f"  - {prompt.name}: {prompt.description}")
        print()

        # Get a prompt
        print("=== Getting 'code_review' prompt ===")
        prompt_result = await client.get_prompt("code_review", {"language": "python"})
        for msg in prompt_result.messages:
            if hasattr(msg.content, "text"):
                print(f"  [{msg.role}] {msg.content.text[:100]}...")
        print()

        # Print log summary
        print("=== Request/Response Log Summary ===")
        client.print_log_summary()


if __name__ == "__main__":
    asyncio.run(main())
