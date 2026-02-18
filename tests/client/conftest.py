"""Shared test fixtures for mamba-mcp-client."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, PropertyMock

import pytest
from mamba_mcp_client.config import ClientConfig
from mcp import types as mcp_types


@pytest.fixture()
def stdio_config() -> ClientConfig:
    """Create a stdio ClientConfig for testing."""
    return ClientConfig.for_stdio(command="python", args=["server.py"])


@pytest.fixture()
def mock_initialize_result() -> mcp_types.InitializeResult:
    """Create a mock InitializeResult matching MCP spec."""
    return mcp_types.InitializeResult(
        protocolVersion="2024-11-05",
        capabilities=mcp_types.ServerCapabilities(
            tools=mcp_types.ToolsCapability(),
            resources=mcp_types.ResourcesCapability(),
            prompts=mcp_types.PromptsCapability(),
        ),
        serverInfo=mcp_types.Implementation(
            name="test-server",
            version="1.0.0",
        ),
        instructions="Test server instructions",
    )


@pytest.fixture()
def mock_fastmcp_client(mock_initialize_result: mcp_types.InitializeResult) -> AsyncMock:
    """Create a mock FastMCP Client as an async context manager."""
    mock = AsyncMock()
    mock.initialize_result = mock_initialize_result

    # Configure async context manager protocol
    mock.__aenter__ = AsyncMock(return_value=mock)
    mock.__aexit__ = AsyncMock(return_value=None)

    # Configure default return values for MCP operations
    mock.list_tools = AsyncMock(return_value=[])
    mock.list_resources = AsyncMock(return_value=[])
    mock.list_prompts = AsyncMock(return_value=[])
    mock.ping = AsyncMock(return_value=None)

    return mock


@pytest.fixture()
def mock_client_class(mock_fastmcp_client: AsyncMock) -> MagicMock:
    """Create a mock for the fastmcp.Client class constructor."""
    mock_cls = MagicMock()
    # When Client(transport) is called, return the mock client
    mock_cls.return_value = mock_fastmcp_client
    # Support `async with Client(transport) as client:`
    mock_fastmcp_client.__aenter__ = AsyncMock(return_value=mock_fastmcp_client)
    mock_fastmcp_client.__aexit__ = AsyncMock(return_value=None)
    return mock_cls


@pytest.fixture()
def sample_tool() -> mcp_types.Tool:
    """Create a sample MCP Tool."""
    return mcp_types.Tool(
        name="test_tool",
        description="A test tool for testing",
        inputSchema={
            "type": "object",
            "properties": {
                "param1": {"type": "string", "description": "First param"},
                "param2": {"type": "integer", "description": "Second param"},
            },
            "required": ["param1"],
        },
    )


@pytest.fixture()
def sample_tool_result() -> MagicMock:
    """Create a sample MCP CallToolResult."""
    mock_result = MagicMock()
    mock_result.content = [mcp_types.TextContent(type="text", text="Tool result text")]
    mock_result.is_error = False
    mock_result.isError = False
    return mock_result


@pytest.fixture()
def sample_resource() -> mcp_types.Resource:
    """Create a sample MCP Resource."""
    return mcp_types.Resource(
        uri="file:///test.txt",
        name="Test Resource",
        description="A test resource",
        mimeType="text/plain",
    )


@pytest.fixture()
def sample_prompt() -> mcp_types.Prompt:
    """Create a sample MCP Prompt."""
    return mcp_types.Prompt(
        name="test_prompt",
        description="A test prompt",
        arguments=[
            mcp_types.PromptArgument(
                name="topic",
                description="The topic to discuss",
                required=True,
            ),
        ],
    )


@pytest.fixture()
def sample_get_prompt_result() -> mcp_types.GetPromptResult:
    """Create a sample GetPromptResult."""
    return mcp_types.GetPromptResult(
        messages=[
            mcp_types.PromptMessage(
                role="user",
                content=mcp_types.TextContent(type="text", text="Tell me about testing"),
            ),
        ],
    )


@pytest.fixture()
def mock_no_initialize_result() -> AsyncMock:
    """Create a mock FastMCP Client without initialize_result."""
    mock = AsyncMock()

    # Use PropertyMock to return None for initialize_result
    type(mock).initialize_result = PropertyMock(return_value=None)

    mock.__aenter__ = AsyncMock(return_value=mock)
    mock.__aexit__ = AsyncMock(return_value=None)

    return mock
