"""Core MCP test client implementation wrapping FastMCP Client."""

from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, AsyncIterator

from fastmcp import Client
from fastmcp.client.transports import StdioTransport
from mcp import types as mcp_types
from pydantic import AnyUrl

from mamba_mcp_client.config import ClientConfig, TransportType
from mamba_mcp_client.logging import MCPLogger


@dataclass
class ServerCapabilities:
    """Parsed server capabilities from initialization."""

    tools: bool = False
    resources: bool = False
    prompts: bool = False
    logging: bool = False
    experimental: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_init_result(cls, result: mcp_types.InitializeResult) -> "ServerCapabilities":
        """Parse capabilities from InitializeResult."""
        caps = result.capabilities
        return cls(
            tools=caps.tools is not None if caps else False,
            resources=caps.resources is not None if caps else False,
            prompts=caps.prompts is not None if caps else False,
            logging=caps.logging is not None if caps else False,
            experimental=caps.experimental or {} if caps else {},
        )


@dataclass
class ServerInfo:
    """Server information from initialization."""

    name: str
    version: str
    protocol_version: str
    instructions: str | None = None
    capabilities: ServerCapabilities | None = None

    @classmethod
    def from_init_result(cls, result: mcp_types.InitializeResult) -> "ServerInfo":
        """Parse server info from InitializeResult."""
        return cls(
            name=result.serverInfo.name,
            version=result.serverInfo.version,
            protocol_version=result.protocolVersion,
            instructions=result.instructions,
            capabilities=ServerCapabilities.from_init_result(result),
        )


@dataclass
class ToolCallResult:
    """Result from calling a tool."""

    tool_name: str
    arguments: dict[str, Any]
    content: list[Any]
    is_error: bool = False
    raw_result: mcp_types.CallToolResult | None = None

    @property
    def text(self) -> str | None:
        """Get the first text content if available."""
        for item in self.content:
            if hasattr(item, "text"):
                return item.text
        return None

    @property
    def data(self) -> Any:
        """Get the data from the result."""
        if self.raw_result and hasattr(self.raw_result, "data"):
            return self.raw_result.data
        return None


class MCPTestClient:
    """
    MCP test client for testing and debugging MCP servers.

    Provides a high-level API for interacting with MCP servers with
    comprehensive logging and support for all MCP capabilities.
    """

    def __init__(self, config: ClientConfig) -> None:
        """Initialize the test client with configuration."""
        self.config = config
        self.logger = MCPLogger(
            name=config.client_name,
            level=config.logging.level,
            log_file=str(config.logging.log_file) if config.logging.log_file else None,
            log_requests=config.logging.log_requests,
            log_responses=config.logging.log_responses,
        )
        self._client: Client | None = None
        self._server_info: ServerInfo | None = None
        self._connected: bool = False

    @property
    def connected(self) -> bool:
        """Check if client is connected."""
        return self._connected

    @property
    def server_info(self) -> ServerInfo | None:
        """Get server information (available after connect)."""
        return self._server_info

    def _create_transport(self) -> str | StdioTransport:
        """Create the appropriate transport based on configuration."""
        if self.config.transport_type == TransportType.STDIO:
            if not self.config.stdio:
                raise ValueError("Stdio configuration required for stdio transport")
            return StdioTransport(
                command=self.config.stdio.command,
                args=self.config.stdio.args,
                env=self.config.stdio.env or None,
            )
        elif self.config.transport_type == TransportType.UV_INSTALLED:
            if not self.config.uv_installed:
                raise ValueError("UV-installed configuration required for uv_installed transport")
            from fastmcp.client.transports import UvStdioTransport

            cfg = self.config.uv_installed
            return UvStdioTransport(
                command=cfg.server_name,
                args=cfg.args or None,
                python_version=cfg.python_version,
                with_packages=cfg.with_packages or None,
                env_vars=cfg.env or None,
            )
        elif self.config.transport_type == TransportType.UV_LOCAL:
            if not self.config.uv_local:
                raise ValueError("UV-local configuration required for uv_local transport")
            from fastmcp.client.transports import UvxStdioTransport

            cfg = self.config.uv_local
            return UvxStdioTransport(
                tool_name=cfg.server_name,
                tool_args=cfg.args or None,
                from_package=cfg.project_path,
                python_version=cfg.python_version,
                with_packages=cfg.with_packages or None,
                env_vars=cfg.env or None,
            )
        elif self.config.transport_type in (TransportType.SSE, TransportType.HTTP):
            if not self.config.http:
                raise ValueError("HTTP configuration required for SSE/HTTP transport")
            return self.config.http.url
        else:
            raise ValueError(f"Unknown transport type: {self.config.transport_type}")

    @asynccontextmanager
    async def connect(self) -> AsyncIterator["MCPTestClient"]:
        """Connect to the MCP server as a context manager."""
        transport = self._create_transport()

        async with Client(transport) as client:
            self._client = client
            self._connected = True

            # Parse server info from initialization result
            if client.initialize_result:
                self._server_info = ServerInfo.from_init_result(client.initialize_result)
                self.logger.log_response(
                    "initialize",
                    client.initialize_result,
                )

            try:
                yield self
            finally:
                self._connected = False
                self._client = None
                self._server_info = None

    def _ensure_connected(self) -> Client:
        """Ensure client is connected and return the underlying client."""
        if not self._client or not self._connected:
            raise RuntimeError("Client is not connected. Use 'async with client.connect():'")
        return self._client

    # ==================== Resources ====================

    async def list_resources(self) -> list[mcp_types.Resource]:
        """List all resources available on the server."""
        client = self._ensure_connected()
        request_entry = self.logger.log_request("resources/list")

        try:
            resources = await client.list_resources()
            self.logger.log_response("resources/list", {"resources": resources}, request_entry)
            return resources
        except Exception as e:
            self.logger.log_response("resources/list", {}, request_entry, error=str(e))
            raise

    async def read_resource(self, uri: str) -> mcp_types.ReadResourceResult:
        """Read a specific resource by URI."""
        client = self._ensure_connected()
        request_entry = self.logger.log_request("resources/read", {"uri": uri})

        try:
            result = await client.read_resource_mcp(AnyUrl(uri))
            self.logger.log_response("resources/read", result, request_entry)
            return result
        except Exception as e:
            self.logger.log_response("resources/read", {}, request_entry, error=str(e))
            raise

    async def subscribe_resource(self, uri: str) -> None:
        """Subscribe to resource updates."""
        client = self._ensure_connected()
        request_entry = self.logger.log_request("resources/subscribe", {"uri": uri})

        try:
            await client.subscribe_resource(AnyUrl(uri))
            self.logger.log_response("resources/subscribe", {"subscribed": True}, request_entry)
        except Exception as e:
            self.logger.log_response("resources/subscribe", {}, request_entry, error=str(e))
            raise

    async def unsubscribe_resource(self, uri: str) -> None:
        """Unsubscribe from resource updates."""
        client = self._ensure_connected()
        request_entry = self.logger.log_request("resources/unsubscribe", {"uri": uri})

        try:
            await client.unsubscribe_resource(AnyUrl(uri))
            self.logger.log_response(
                "resources/unsubscribe", {"unsubscribed": True}, request_entry
            )
        except Exception as e:
            self.logger.log_response("resources/unsubscribe", {}, request_entry, error=str(e))
            raise

    # ==================== Prompts ====================

    async def list_prompts(self) -> list[mcp_types.Prompt]:
        """List all prompts available on the server."""
        client = self._ensure_connected()
        request_entry = self.logger.log_request("prompts/list")

        try:
            prompts = await client.list_prompts()
            self.logger.log_response("prompts/list", {"prompts": prompts}, request_entry)
            return prompts
        except Exception as e:
            self.logger.log_response("prompts/list", {}, request_entry, error=str(e))
            raise

    async def get_prompt(
        self, name: str, arguments: dict[str, str] | None = None
    ) -> mcp_types.GetPromptResult:
        """Get a specific prompt by name with optional arguments."""
        client = self._ensure_connected()
        request_entry = self.logger.log_request(
            "prompts/get", {"name": name, "arguments": arguments}
        )

        try:
            result = await client.get_prompt_mcp(name, arguments)
            self.logger.log_response("prompts/get", result, request_entry)
            return result
        except Exception as e:
            self.logger.log_response("prompts/get", {}, request_entry, error=str(e))
            raise

    # ==================== Tools ====================

    async def list_tools(self) -> list[mcp_types.Tool]:
        """List all tools available on the server."""
        client = self._ensure_connected()
        request_entry = self.logger.log_request("tools/list")

        try:
            tools = await client.list_tools()
            self.logger.log_response("tools/list", {"tools": tools}, request_entry)
            return tools
        except Exception as e:
            self.logger.log_response("tools/list", {}, request_entry, error=str(e))
            raise

    async def call_tool(
        self, name: str, arguments: dict[str, Any] | None = None
    ) -> ToolCallResult:
        """Call a tool with the given arguments."""
        client = self._ensure_connected()
        args = arguments or {}
        request_entry = self.logger.log_request("tools/call", {"name": name, "arguments": args})

        try:
            result = await client.call_tool(name, args)
            self.logger.log_response("tools/call", result, request_entry)

            # FastMCP uses snake_case (is_error), MCP spec uses camelCase (isError)
            is_error = getattr(result, "is_error", getattr(result, "isError", False)) or False

            return ToolCallResult(
                tool_name=name,
                arguments=args,
                content=list(result.content) if result.content else [],
                is_error=is_error,
                raw_result=result,
            )
        except Exception as e:
            self.logger.log_response("tools/call", {}, request_entry, error=str(e))
            raise

    # ==================== Discovery ====================

    async def ping(self) -> bool:
        """Ping the server to check connectivity."""
        client = self._ensure_connected()
        request_entry = self.logger.log_request("ping")

        try:
            await client.ping()
            self.logger.log_response("ping", {"success": True}, request_entry)
            return True
        except Exception as e:
            self.logger.log_response("ping", {"success": False}, request_entry, error=str(e))
            return False

    def get_capabilities(self) -> ServerCapabilities | None:
        """Get server capabilities (available after connect)."""
        return self._server_info.capabilities if self._server_info else None

    def get_instructions(self) -> str | None:
        """Get server instructions (available after connect)."""
        return self._server_info.instructions if self._server_info else None

    # ==================== Sampling ====================

    async def create_message(
        self,
        messages: list[mcp_types.SamplingMessage],
        max_tokens: int = 1000,
        **kwargs: Any,
    ) -> mcp_types.CreateMessageResult:
        """
        Request the server to create a message via sampling.

        Note: This is for testing server-initiated sampling. The server must
        support sampling capability.
        """
        client = self._ensure_connected()
        request_entry = self.logger.log_request(
            "sampling/createMessage",
            {"messages": [m.model_dump() for m in messages], "max_tokens": max_tokens, **kwargs},
        )

        try:
            # Note: FastMCP client may not expose this directly
            # This is a placeholder for when the API is available
            if hasattr(client, "create_message"):
                result = await client.create_message(messages, max_tokens=max_tokens, **kwargs)
                self.logger.log_response("sampling/createMessage", result, request_entry)
                return result
            else:
                raise NotImplementedError("Sampling not directly supported by this client")
        except Exception as e:
            self.logger.log_response("sampling/createMessage", {}, request_entry, error=str(e))
            raise

    # ==================== Roots ====================

    async def list_roots(self) -> list[mcp_types.Root]:
        """List root directories."""
        client = self._ensure_connected()
        request_entry = self.logger.log_request("roots/list")

        try:
            if hasattr(client, "list_roots"):
                roots = await client.list_roots()
                self.logger.log_response("roots/list", {"roots": roots}, request_entry)
                return roots
            else:
                self.logger.log_response(
                    "roots/list", {}, request_entry, error="Roots not supported"
                )
                return []
        except Exception as e:
            self.logger.log_response("roots/list", {}, request_entry, error=str(e))
            raise

    # ==================== Logging ====================

    def get_log_entries(self) -> list:
        """Get all MCP protocol log entries."""
        return self.logger.get_entries()

    def export_logs(self) -> str:
        """Export logs as JSON."""
        return self.logger.export_json()

    def print_log_summary(self) -> None:
        """Print a summary of logged requests/responses."""
        self.logger.print_summary()

    def clear_logs(self) -> None:
        """Clear all log entries."""
        self.logger.clear()
