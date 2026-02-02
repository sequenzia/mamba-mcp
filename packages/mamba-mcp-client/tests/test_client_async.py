"""Async tests for MCPTestClient connection and MCP operations."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from mamba_mcp_client.client import MCPTestClient, ServerCapabilities, ServerInfo, ToolCallResult
from mamba_mcp_client.config import ClientConfig
from mcp import types as mcp_types


class TestConnect:
    """Tests for MCPTestClient.connect() context manager."""

    async def test_connect_sets_connected_state(
        self, stdio_config: ClientConfig, mock_fastmcp_client: AsyncMock
    ) -> None:
        """Test that connect() sets connected state and cleans up."""
        client = MCPTestClient(stdio_config)

        with patch("mamba_mcp_client.client.Client", return_value=mock_fastmcp_client):
            async with client.connect():
                assert client.connected
                assert client.server_info is not None

            # After exiting context manager
            assert not client.connected
            assert client.server_info is None

    async def test_connect_parses_server_info(
        self, stdio_config: ClientConfig, mock_fastmcp_client: AsyncMock
    ) -> None:
        """Test that server info is parsed from InitializeResult."""
        client = MCPTestClient(stdio_config)

        with patch("mamba_mcp_client.client.Client", return_value=mock_fastmcp_client):
            async with client.connect():
                info = client.server_info
                assert info is not None
                assert info.name == "test-server"
                assert info.version == "1.0.0"
                assert info.protocol_version == "2024-11-05"
                assert info.instructions == "Test server instructions"

    async def test_connect_parses_capabilities(
        self, stdio_config: ClientConfig, mock_fastmcp_client: AsyncMock
    ) -> None:
        """Test that capabilities are parsed from InitializeResult."""
        client = MCPTestClient(stdio_config)

        with patch("mamba_mcp_client.client.Client", return_value=mock_fastmcp_client):
            async with client.connect():
                caps = client.get_capabilities()
                assert caps is not None
                assert caps.tools is True
                assert caps.resources is True
                assert caps.prompts is True

    async def test_connect_without_initialize_result(
        self, stdio_config: ClientConfig, mock_no_initialize_result: AsyncMock
    ) -> None:
        """Test connect when server returns no InitializeResult."""
        client = MCPTestClient(stdio_config)

        with patch("mamba_mcp_client.client.Client", return_value=mock_no_initialize_result):
            async with client.connect():
                assert client.connected
                assert client.server_info is None

    async def test_connect_cleans_up_on_exception(
        self, stdio_config: ClientConfig, mock_fastmcp_client: AsyncMock
    ) -> None:
        """Test that connect cleans up state even when exception occurs."""
        client = MCPTestClient(stdio_config)

        with patch("mamba_mcp_client.client.Client", return_value=mock_fastmcp_client):
            with pytest.raises(ValueError, match="test error"):
                async with client.connect():
                    assert client.connected
                    raise ValueError("test error")

            assert not client.connected
            assert client.server_info is None


class TestListTools:
    """Tests for MCPTestClient.list_tools()."""

    async def test_list_tools_returns_tools(
        self,
        stdio_config: ClientConfig,
        mock_fastmcp_client: AsyncMock,
        sample_tool: mcp_types.Tool,
    ) -> None:
        """Test listing tools from server."""
        mock_fastmcp_client.list_tools = AsyncMock(return_value=[sample_tool])

        client = MCPTestClient(stdio_config)
        with patch("mamba_mcp_client.client.Client", return_value=mock_fastmcp_client):
            async with client.connect():
                tools = await client.list_tools()
                assert len(tools) == 1
                assert tools[0].name == "test_tool"
                assert tools[0].description == "A test tool for testing"

    async def test_list_tools_empty(
        self, stdio_config: ClientConfig, mock_fastmcp_client: AsyncMock
    ) -> None:
        """Test listing tools when server has none."""
        client = MCPTestClient(stdio_config)
        with patch("mamba_mcp_client.client.Client", return_value=mock_fastmcp_client):
            async with client.connect():
                tools = await client.list_tools()
                assert tools == []

    async def test_list_tools_logs_request_and_response(
        self,
        stdio_config: ClientConfig,
        mock_fastmcp_client: AsyncMock,
        sample_tool: mcp_types.Tool,
    ) -> None:
        """Test that list_tools logs both request and response."""
        mock_fastmcp_client.list_tools = AsyncMock(return_value=[sample_tool])

        client = MCPTestClient(stdio_config)
        with patch("mamba_mcp_client.client.Client", return_value=mock_fastmcp_client):
            async with client.connect():
                await client.list_tools()
                # Initial connect logs a response, then list_tools logs req + resp
                entries = client.get_log_entries()
                tools_entries = [e for e in entries if e.method == "tools/list"]
                assert len(tools_entries) == 2  # request + response

    async def test_list_tools_raises_when_not_connected(self, stdio_config: ClientConfig) -> None:
        """Test that list_tools raises when not connected."""
        client = MCPTestClient(stdio_config)
        with pytest.raises(RuntimeError, match="not connected"):
            await client.list_tools()

    async def test_list_tools_propagates_server_error(
        self, stdio_config: ClientConfig, mock_fastmcp_client: AsyncMock
    ) -> None:
        """Test that server errors are propagated."""
        mock_fastmcp_client.list_tools = AsyncMock(side_effect=Exception("Server error"))

        client = MCPTestClient(stdio_config)
        with patch("mamba_mcp_client.client.Client", return_value=mock_fastmcp_client):
            async with client.connect():
                with pytest.raises(Exception, match="Server error"):
                    await client.list_tools()


class TestCallTool:
    """Tests for MCPTestClient.call_tool()."""

    async def test_call_tool_success(
        self,
        stdio_config: ClientConfig,
        mock_fastmcp_client: AsyncMock,
        sample_tool_result: MagicMock,
    ) -> None:
        """Test successful tool call."""
        mock_fastmcp_client.call_tool = AsyncMock(return_value=sample_tool_result)

        client = MCPTestClient(stdio_config)
        with patch("mamba_mcp_client.client.Client", return_value=mock_fastmcp_client):
            async with client.connect():
                result = await client.call_tool("test_tool", {"param1": "value"})

                assert isinstance(result, ToolCallResult)
                assert result.tool_name == "test_tool"
                assert result.arguments == {"param1": "value"}
                assert not result.is_error
                assert result.text == "Tool result text"
                assert result.raw_result is sample_tool_result

    async def test_call_tool_with_no_arguments(
        self,
        stdio_config: ClientConfig,
        mock_fastmcp_client: AsyncMock,
        sample_tool_result: MagicMock,
    ) -> None:
        """Test calling a tool with no arguments defaults to empty dict."""
        mock_fastmcp_client.call_tool = AsyncMock(return_value=sample_tool_result)

        client = MCPTestClient(stdio_config)
        with patch("mamba_mcp_client.client.Client", return_value=mock_fastmcp_client):
            async with client.connect():
                result = await client.call_tool("test_tool")
                assert result.arguments == {}
                mock_fastmcp_client.call_tool.assert_called_once_with("test_tool", {})

    async def test_call_tool_error_result(
        self,
        stdio_config: ClientConfig,
        mock_fastmcp_client: AsyncMock,
    ) -> None:
        """Test handling tool error responses."""
        error_result = MagicMock()
        error_result.content = [mcp_types.TextContent(type="text", text="Error message")]
        error_result.is_error = True
        error_result.isError = True
        mock_fastmcp_client.call_tool = AsyncMock(return_value=error_result)

        client = MCPTestClient(stdio_config)
        with patch("mamba_mcp_client.client.Client", return_value=mock_fastmcp_client):
            async with client.connect():
                result = await client.call_tool("failing_tool", {"bad": "input"})
                assert result.is_error
                assert result.text == "Error message"

    async def test_call_tool_propagates_exception(
        self,
        stdio_config: ClientConfig,
        mock_fastmcp_client: AsyncMock,
    ) -> None:
        """Test that call_tool propagates transport exceptions."""
        mock_fastmcp_client.call_tool = AsyncMock(side_effect=ConnectionError("Transport failed"))

        client = MCPTestClient(stdio_config)
        with patch("mamba_mcp_client.client.Client", return_value=mock_fastmcp_client):
            async with client.connect():
                with pytest.raises(ConnectionError, match="Transport failed"):
                    await client.call_tool("test_tool")


class TestListResources:
    """Tests for MCPTestClient.list_resources()."""

    async def test_list_resources_returns_resources(
        self,
        stdio_config: ClientConfig,
        mock_fastmcp_client: AsyncMock,
        sample_resource: mcp_types.Resource,
    ) -> None:
        """Test listing resources from server."""
        mock_fastmcp_client.list_resources = AsyncMock(return_value=[sample_resource])

        client = MCPTestClient(stdio_config)
        with patch("mamba_mcp_client.client.Client", return_value=mock_fastmcp_client):
            async with client.connect():
                resources = await client.list_resources()
                assert len(resources) == 1
                assert resources[0].name == "Test Resource"

    async def test_list_resources_raises_when_not_connected(
        self, stdio_config: ClientConfig
    ) -> None:
        """Test that list_resources raises when not connected."""
        client = MCPTestClient(stdio_config)
        with pytest.raises(RuntimeError, match="not connected"):
            await client.list_resources()


class TestListPrompts:
    """Tests for MCPTestClient.list_prompts()."""

    async def test_list_prompts_returns_prompts(
        self,
        stdio_config: ClientConfig,
        mock_fastmcp_client: AsyncMock,
        sample_prompt: mcp_types.Prompt,
    ) -> None:
        """Test listing prompts from server."""
        mock_fastmcp_client.list_prompts = AsyncMock(return_value=[sample_prompt])

        client = MCPTestClient(stdio_config)
        with patch("mamba_mcp_client.client.Client", return_value=mock_fastmcp_client):
            async with client.connect():
                prompts = await client.list_prompts()
                assert len(prompts) == 1
                assert prompts[0].name == "test_prompt"


class TestGetPrompt:
    """Tests for MCPTestClient.get_prompt()."""

    async def test_get_prompt_success(
        self,
        stdio_config: ClientConfig,
        mock_fastmcp_client: AsyncMock,
        sample_get_prompt_result: mcp_types.GetPromptResult,
    ) -> None:
        """Test getting a prompt by name."""
        mock_fastmcp_client.get_prompt_mcp = AsyncMock(return_value=sample_get_prompt_result)

        client = MCPTestClient(stdio_config)
        with patch("mamba_mcp_client.client.Client", return_value=mock_fastmcp_client):
            async with client.connect():
                result = await client.get_prompt("test_prompt", {"topic": "testing"})
                assert len(result.messages) == 1
                mock_fastmcp_client.get_prompt_mcp.assert_called_once_with(
                    "test_prompt", {"topic": "testing"}
                )


class TestPing:
    """Tests for MCPTestClient.ping()."""

    async def test_ping_success(
        self, stdio_config: ClientConfig, mock_fastmcp_client: AsyncMock
    ) -> None:
        """Test successful ping."""
        client = MCPTestClient(stdio_config)
        with patch("mamba_mcp_client.client.Client", return_value=mock_fastmcp_client):
            async with client.connect():
                result = await client.ping()
                assert result is True

    async def test_ping_failure(
        self, stdio_config: ClientConfig, mock_fastmcp_client: AsyncMock
    ) -> None:
        """Test ping returns False on failure."""
        mock_fastmcp_client.ping = AsyncMock(side_effect=ConnectionError("No connection"))

        client = MCPTestClient(stdio_config)
        with patch("mamba_mcp_client.client.Client", return_value=mock_fastmcp_client):
            async with client.connect():
                result = await client.ping()
                assert result is False


class TestDiscoveryMethods:
    """Tests for get_capabilities and get_instructions."""

    async def test_get_capabilities_when_connected(
        self, stdio_config: ClientConfig, mock_fastmcp_client: AsyncMock
    ) -> None:
        """Test get_capabilities returns parsed capabilities."""
        client = MCPTestClient(stdio_config)
        with patch("mamba_mcp_client.client.Client", return_value=mock_fastmcp_client):
            async with client.connect():
                caps = client.get_capabilities()
                assert caps is not None
                assert isinstance(caps, ServerCapabilities)

    def test_get_capabilities_when_not_connected(self, stdio_config: ClientConfig) -> None:
        """Test get_capabilities returns None when not connected."""
        client = MCPTestClient(stdio_config)
        assert client.get_capabilities() is None

    async def test_get_instructions_when_connected(
        self, stdio_config: ClientConfig, mock_fastmcp_client: AsyncMock
    ) -> None:
        """Test get_instructions returns server instructions."""
        client = MCPTestClient(stdio_config)
        with patch("mamba_mcp_client.client.Client", return_value=mock_fastmcp_client):
            async with client.connect():
                instructions = client.get_instructions()
                assert instructions == "Test server instructions"

    def test_get_instructions_when_not_connected(self, stdio_config: ClientConfig) -> None:
        """Test get_instructions returns None when not connected."""
        client = MCPTestClient(stdio_config)
        assert client.get_instructions() is None


class TestToolCallResult:
    """Tests for ToolCallResult dataclass."""

    def test_text_property_with_text_content(self) -> None:
        """Test text property extracts first text content."""
        content = mcp_types.TextContent(type="text", text="Hello world")
        result = ToolCallResult(tool_name="test", arguments={}, content=[content], raw_result=None)
        assert result.text == "Hello world"

    def test_text_property_no_text_content(self) -> None:
        """Test text property returns None when no text content."""
        result = ToolCallResult(tool_name="test", arguments={}, content=[], raw_result=None)
        assert result.text is None

    def test_data_property_with_raw_result(self) -> None:
        """Test data property extracts data from raw_result."""
        raw = MagicMock()
        raw.data = {"key": "value"}
        result = ToolCallResult(tool_name="test", arguments={}, content=[], raw_result=raw)
        assert result.data == {"key": "value"}

    def test_data_property_no_raw_result(self) -> None:
        """Test data property returns None with no raw_result."""
        result = ToolCallResult(tool_name="test", arguments={}, content=[], raw_result=None)
        assert result.data is None


class TestServerInfoParsing:
    """Tests for ServerInfo and ServerCapabilities from_init_result."""

    def test_server_info_from_init_result(
        self, mock_initialize_result: mcp_types.InitializeResult
    ) -> None:
        """Test parsing ServerInfo from InitializeResult."""
        info = ServerInfo.from_init_result(mock_initialize_result)
        assert info.name == "test-server"
        assert info.version == "1.0.0"
        assert info.protocol_version == "2024-11-05"
        assert info.instructions == "Test server instructions"

    def test_capabilities_from_init_result(
        self, mock_initialize_result: mcp_types.InitializeResult
    ) -> None:
        """Test parsing ServerCapabilities from InitializeResult."""
        caps = ServerCapabilities.from_init_result(mock_initialize_result)
        assert caps.tools is True
        assert caps.resources is True
        assert caps.prompts is True
        assert caps.logging is False

    def test_capabilities_with_no_capabilities(self) -> None:
        """Test parsing capabilities when server returns None."""
        result = mcp_types.InitializeResult(
            protocolVersion="2024-11-05",
            capabilities=mcp_types.ServerCapabilities(),
            serverInfo=mcp_types.Implementation(name="bare", version="0.1.0"),
        )
        caps = ServerCapabilities.from_init_result(result)
        assert caps.tools is False
        assert caps.resources is False
        assert caps.prompts is False


class TestTransportCreation:
    """Tests for MCPTestClient._create_transport() across transport types."""

    def test_create_transport_sse(self) -> None:
        """Test SSE transport returns URL string."""
        config = ClientConfig.for_sse(url="http://localhost:8000/sse")
        client = MCPTestClient(config)
        transport = client._create_transport()
        assert isinstance(transport, str)
        assert transport == "http://localhost:8000/sse"

    def test_create_transport_http(self) -> None:
        """Test HTTP transport returns URL string."""
        config = ClientConfig.for_http(url="http://localhost:8000/mcp")
        client = MCPTestClient(config)
        transport = client._create_transport()
        assert isinstance(transport, str)
        assert transport == "http://localhost:8000/mcp"

    def test_create_transport_sse_with_extra_args(self) -> None:
        """Test SSE transport appends extra_args as query params."""
        config = ClientConfig.for_sse(
            url="http://localhost:8000/sse",
            extra_args=["env=prod", "debug"],
        )
        client = MCPTestClient(config)
        transport = client._create_transport()
        assert isinstance(transport, str)
        assert "env=prod" in transport
        assert "debug=true" in transport

    def test_create_transport_stdio_missing_config(self) -> None:
        """Test stdio transport raises when config is missing."""
        config = ClientConfig(transport_type="stdio", stdio=None)
        client = MCPTestClient(config)
        with pytest.raises(ValueError, match="Stdio configuration required"):
            client._create_transport()

    def test_create_transport_http_missing_config(self) -> None:
        """Test HTTP transport raises when config is missing."""
        config = ClientConfig(transport_type="sse", http=None)
        client = MCPTestClient(config)
        with pytest.raises(ValueError, match="HTTP configuration required"):
            client._create_transport()


class TestLoggingIntegration:
    """Tests for MCPTestClient logging during operations."""

    async def test_log_entries_cleared(
        self, stdio_config: ClientConfig, mock_fastmcp_client: AsyncMock
    ) -> None:
        """Test that clear_logs removes all entries."""
        client = MCPTestClient(stdio_config)
        with patch("mamba_mcp_client.client.Client", return_value=mock_fastmcp_client):
            async with client.connect():
                await client.list_tools()
                assert len(client.get_log_entries()) > 0

                client.clear_logs()
                assert len(client.get_log_entries()) == 0

    async def test_export_logs_returns_json(
        self, stdio_config: ClientConfig, mock_fastmcp_client: AsyncMock
    ) -> None:
        """Test that export_logs returns valid JSON."""
        import json

        client = MCPTestClient(stdio_config)
        with patch("mamba_mcp_client.client.Client", return_value=mock_fastmcp_client):
            async with client.connect():
                await client.list_tools()
                exported = client.export_logs()
                parsed = json.loads(exported)
                assert isinstance(parsed, list)
                assert len(parsed) > 0

    async def test_error_logged_on_failure(
        self, stdio_config: ClientConfig, mock_fastmcp_client: AsyncMock
    ) -> None:
        """Test that errors are logged when operations fail."""
        mock_fastmcp_client.list_tools = AsyncMock(side_effect=Exception("Boom"))

        client = MCPTestClient(stdio_config)
        with patch("mamba_mcp_client.client.Client", return_value=mock_fastmcp_client):
            async with client.connect():
                with pytest.raises(Exception, match="Boom"):
                    await client.list_tools()

                # Check that error was logged in the response entry
                entries = client.get_log_entries()
                error_entries = [e for e in entries if e.error is not None]
                assert len(error_entries) >= 1
                assert "Boom" in error_entries[-1].error
