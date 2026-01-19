"""Main Textual TUI application for MCP testing."""

import json
from typing import Any

from rich.syntax import Syntax
from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, ScrollableContainer, Vertical
from textual.message import Message
from textual.widgets import (
    Button,
    Footer,
    Header,
    Input,
    Label,
    RichLog,
    Static,
    TabbedContent,
    TabPane,
    Tree,
)
from textual.widgets.tree import TreeNode

from mamba_mcp_client.client import MCPTestClient
from mamba_mcp_client.config import ClientConfig


class ServerInfoPanel(Static):
    """Panel showing server information."""

    def update_info(self, client: MCPTestClient) -> None:
        """Update the panel with server info."""
        if client.server_info:
            info = client.server_info
            text = f"""[bold]Server:[/] {info.name} v{info.version}
[bold]Protocol:[/] {info.protocol_version}
[bold]Instructions:[/] {info.instructions or 'None'}

[bold]Capabilities:[/]
  Tools: {'Yes' if info.capabilities and info.capabilities.tools else 'No'}
  Resources: {'Yes' if info.capabilities and info.capabilities.resources else 'No'}
  Prompts: {'Yes' if info.capabilities and info.capabilities.prompts else 'No'}
  Logging: {'Yes' if info.capabilities and info.capabilities.logging else 'No'}"""
            self.update(text)
        else:
            self.update("[dim]Not connected[/]")


class CapabilityTree(Tree[dict]):
    """Tree widget for displaying MCP capabilities."""

    def __init__(self, label: str = "Capabilities", **kwargs: Any) -> None:
        super().__init__(label, **kwargs)
        self.root.expand()

    def clear_tree(self) -> None:
        """Clear all nodes from the tree."""
        self.root.remove_children()

    def add_tools(self, tools: list[Any]) -> None:
        """Add tools to the tree."""
        tools_node = self.root.add("Tools", expand=True)
        for tool in tools:
            tool_node = tools_node.add(f"[bold]{tool.name}[/]", data={"type": "tool", "item": tool})
            if tool.description:
                tool_node.add_leaf(f"[dim]{tool.description}[/]")
            if tool.inputSchema:
                schema_node = tool_node.add("Input Schema", expand=False)
                props = tool.inputSchema.get("properties", {})
                for prop_name, prop_info in props.items():
                    required = prop_name in tool.inputSchema.get("required", [])
                    req_marker = "[red]*[/]" if required else ""
                    prop_type = prop_info.get("type", "any")
                    schema_node.add_leaf(f"{prop_name}{req_marker}: {prop_type}")

    def add_resources(self, resources: list[Any]) -> None:
        """Add resources to the tree."""
        res_node = self.root.add("Resources", expand=True)
        for resource in resources:
            r_node = res_node.add(
                f"[bold]{resource.name}[/]", data={"type": "resource", "item": resource}
            )
            r_node.add_leaf(f"URI: {resource.uri}")
            if resource.description:
                r_node.add_leaf(f"[dim]{resource.description}[/]")
            if resource.mimeType:
                r_node.add_leaf(f"Type: {resource.mimeType}")

    def add_prompts(self, prompts: list[Any]) -> None:
        """Add prompts to the tree."""
        prompts_node = self.root.add("Prompts", expand=True)
        for prompt in prompts:
            p_node = prompts_node.add(
                f"[bold]{prompt.name}[/]", data={"type": "prompt", "item": prompt}
            )
            if prompt.description:
                p_node.add_leaf(f"[dim]{prompt.description}[/]")
            if prompt.arguments:
                args_node = p_node.add("Arguments", expand=False)
                for arg in prompt.arguments:
                    required = arg.required if hasattr(arg, "required") else False
                    req_marker = "[red]*[/]" if required else ""
                    args_node.add_leaf(f"{arg.name}{req_marker}")


class ResultPanel(ScrollableContainer):
    """Panel for displaying results."""

    BINDINGS = [
        Binding("y", "copy_all", "Copy"),
    ]

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._log = RichLog(highlight=True, markup=True)
        self._plain_content: list[str] = []

    def compose(self) -> ComposeResult:
        yield self._log

    def clear(self) -> None:
        """Clear the result panel."""
        self._log.clear()
        self._plain_content.clear()

    def write_json(self, data: Any, title: str = "") -> None:
        """Write JSON data to the panel."""
        if title:
            self._log.write(f"[bold blue]{title}[/]\n")
            self._plain_content.append(f"--- {title} ---")

        if hasattr(data, "model_dump"):
            data = data.model_dump()

        json_str = json.dumps(data, indent=2, default=str)
        syntax = Syntax(json_str, "json", theme="monokai", line_numbers=False, word_wrap=True)
        self._log.write(syntax)
        self._log.write("")
        self._plain_content.append(json_str)
        self._plain_content.append("")

    def write_error(self, error: str) -> None:
        """Write an error message."""
        self._log.write(f"[bold red]Error:[/] {error}\n")
        self._plain_content.append(f"Error: {error}")
        self._plain_content.append("")

    def write_info(self, message: str) -> None:
        """Write an info message."""
        self._log.write(f"[bold green]Info:[/] {message}\n")
        self._plain_content.append(f"Info: {message}")
        self._plain_content.append("")

    def action_copy_all(self) -> None:
        """Copy all content to clipboard."""
        text = "\n".join(self._plain_content).strip()
        if not text:
            self.app.notify("Nothing to copy", severity="warning")
            return
        try:
            import pyperclip  # type: ignore[import-untyped]

            pyperclip.copy(text)
            self.app.notify("Copied to clipboard")
        except Exception:
            self.app.copy_to_clipboard(text)
            self.app.notify("Copied (OSC 52)")


class ToolCallDialog(Container):
    """Dialog for entering tool call arguments."""

    class DialogDismissed(Message):
        """Sent when dialog should close."""

        pass

    class ToolCallRequested(Message):
        """Sent when user submits the tool call."""

        def __init__(self, tool_name: str, arguments: dict[str, Any]) -> None:
            self.tool_name = tool_name
            self.arguments = arguments
            super().__init__()

    BINDINGS = [
        Binding("escape", "cancel", "Cancel", show=False),
    ]

    def __init__(self, tool_name: str, schema: dict[str, Any], **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.tool_name = tool_name
        self.schema = schema
        self.inputs: dict[str, Input] = {}
        self._call_button: Button | None = None

    def compose(self) -> ComposeResult:
        yield Label(f"[bold]Call Tool: {self.tool_name}[/]", id="dialog-title")

        props = self.schema.get("properties", {})
        required = self.schema.get("required", [])

        with Vertical(id="dialog-inputs"):
            for prop_name, prop_info in props.items():
                is_required = prop_name in required
                label = f"{prop_name}{'*' if is_required else ''}"
                placeholder = prop_info.get("description", prop_info.get("type", ""))

                yield Label(label)
                input_widget = Input(placeholder=placeholder, id=f"input-{prop_name}")
                self.inputs[prop_name] = input_widget
                yield input_widget

        with Horizontal(id="dialog-buttons"):
            self._call_button = Button("Call", variant="primary", id="btn-call")
            yield self._call_button
            yield Button("Cancel", variant="default", id="btn-cancel")

    def get_arguments(self) -> dict[str, Any]:
        """Get the entered arguments."""
        args = {}
        props = self.schema.get("properties", {})

        for prop_name, input_widget in self.inputs.items():
            value = input_widget.value
            if value:
                # Try to parse as JSON for complex types
                prop_type = props.get(prop_name, {}).get("type", "string")
                if prop_type in ("object", "array"):
                    try:
                        args[prop_name] = json.loads(value)
                    except json.JSONDecodeError:
                        args[prop_name] = value
                elif prop_type == "integer":
                    try:
                        args[prop_name] = int(value)
                    except ValueError:
                        args[prop_name] = value
                elif prop_type == "number":
                    try:
                        args[prop_name] = float(value)
                    except ValueError:
                        args[prop_name] = value
                elif prop_type == "boolean":
                    args[prop_name] = value.lower() in ("true", "1", "yes")
                else:
                    args[prop_name] = value

        return args

    def action_cancel(self) -> None:
        """Cancel the dialog."""
        self.post_message(self.DialogDismissed())

    def set_loading(self, loading: bool) -> None:
        """Set the loading state of the dialog."""
        if self._call_button:
            self._call_button.disabled = loading
            self._call_button.label = "Calling..." if loading else "Call"

    @on(Input.Submitted)
    def handle_input_submitted(self, event: Input.Submitted) -> None:
        """Handle Enter key in input fields - submit the form."""
        event.stop()
        arguments = self.get_arguments()
        self.post_message(self.ToolCallRequested(self.tool_name, arguments))


class MCPTestApp(App[None]):
    """Main TUI application for MCP server testing."""

    CSS = """
    Screen {
        layout: grid;
        grid-size: 2 1;
        grid-columns: 1fr 2fr;
        layers: base dialog;
    }

    #left-panel {
        height: 100%;
        border: solid $primary;
    }

    #right-panel {
        height: 100%;
    }

    #server-info {
        height: auto;
        padding: 1;
        border-bottom: solid $surface;
    }

    #capability-tree {
        height: 1fr;
    }

    ResultPanel {
        height: 1fr;
        border: solid $surface;
    }

    ToolCallDialog {
        align: center middle;
        width: 60;
        height: auto;
        max-height: 80%;
        padding: 1 2;
        background: $surface;
        border: solid $primary;
        layer: dialog;
    }

    #dialog-title {
        text-align: center;
        padding-bottom: 1;
    }

    #dialog-inputs {
        height: auto;
        padding: 1 0;
    }

    #dialog-buttons {
        height: auto;
        align: center middle;
        padding-top: 1;
    }

    #dialog-buttons Button {
        margin: 0 1;
    }

    #status-bar {
        dock: bottom;
        height: 1;
        background: $surface;
        padding: 0 1;
    }

    #quick-actions {
        height: auto;
        padding: 1;
        border-bottom: solid $surface;
    }

    #quick-actions Button {
        margin: 0 1 0 0;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("r", "refresh", "Refresh"),
        Binding("l", "show_logs", "Logs"),
        Binding("p", "ping", "Ping"),
        Binding("x", "clear", "Clear"),
        Binding("t", "call_tool", "Call Tool"),
        Binding("enter", "call_tool", "Call Tool", show=False),
        Binding("escape", "close_dialog", "Close", show=False),
    ]

    def __init__(self, config: ClientConfig, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.config = config
        self.client = MCPTestClient(config)
        self._current_tool: dict[str, Any] | None = None
        self._tool_dialog: ToolCallDialog | None = None

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)

        with Container(id="left-panel"):
            yield ServerInfoPanel(id="server-info")
            with Container(id="quick-actions"):
                yield Button("Refresh", id="btn-refresh", variant="primary")
                yield Button("Ping", id="btn-ping")
                yield Button("Logs", id="btn-logs")
            yield CapabilityTree(id="capability-tree")

        with Container(id="right-panel"):
            with TabbedContent(id="tabs"):
                with TabPane("Results", id="tab-results"):
                    yield ResultPanel(id="result-panel")
                with TabPane("Logs", id="tab-logs"):
                    yield RichLog(id="log-panel", highlight=True, markup=True)

        yield Footer()

    async def on_mount(self) -> None:
        """Handle app mount - connect to server."""
        self.connect_to_server()

    @work(exclusive=True)
    async def connect_to_server(self) -> None:
        """Connect to the MCP server and load capabilities."""
        result_panel = self.query_one("#result-panel", ResultPanel)
        result_panel.write_info("Connecting to server...")

        try:
            async with self.client.connect():
                # Update server info panel
                info_panel = self.query_one("#server-info", ServerInfoPanel)
                info_panel.update_info(self.client)

                server_name = (
                    self.client.server_info.name if self.client.server_info else "server"
                )
                result_panel.write_info(f"Connected to {server_name}")

                # Load capabilities
                self.load_capabilities()

                # Keep connection alive
                while True:
                    await self.sleep(1)

        except Exception as e:
            result_panel.write_error(f"Connection failed: {e}")

    async def sleep(self, seconds: float) -> None:
        """Async sleep helper."""
        import asyncio

        await asyncio.sleep(seconds)

    @work(exclusive=False)
    async def load_capabilities(self) -> None:
        """Load server capabilities into the tree."""
        tree = self.query_one("#capability-tree", CapabilityTree)
        tree.clear_tree()

        try:
            # Load tools
            tools = await self.client.list_tools()
            tree.add_tools(tools)

            # Load resources
            try:
                resources = await self.client.list_resources()
                tree.add_resources(resources)
            except Exception:
                pass  # Resources might not be supported

            # Load prompts
            try:
                prompts = await self.client.list_prompts()
                tree.add_prompts(prompts)
            except Exception:
                pass  # Prompts might not be supported

        except Exception as e:
            result_panel = self.query_one("#result-panel", ResultPanel)
            result_panel.write_error(f"Failed to load capabilities: {e}")

    @on(Tree.NodeSelected)
    async def handle_tree_selection(self, event: Tree.NodeSelected[dict]) -> None:
        """Handle tree node selection."""
        node: TreeNode[dict] = event.node
        if node.data:
            item_type = node.data.get("type")
            item = node.data.get("item")

            result_panel = self.query_one("#result-panel", ResultPanel)

            if item_type == "tool":
                result_panel.write_json(
                    {
                        "name": item.name,
                        "description": item.description,
                        "inputSchema": item.inputSchema,
                    },
                    title=f"Tool: {item.name}",
                )
                # Store for potential call
                self._current_tool = {
                    "name": item.name,
                    "schema": item.inputSchema or {},
                }

            elif item_type == "resource":
                result_panel.write_json(
                    {
                        "name": item.name,
                        "uri": str(item.uri),
                        "description": item.description,
                        "mimeType": item.mimeType,
                    },
                    title=f"Resource: {item.name}",
                )
                # Read the resource
                await self.read_selected_resource(str(item.uri))

            elif item_type == "prompt":
                result_panel.write_json(
                    {
                        "name": item.name,
                        "description": item.description,
                        "arguments": [a.model_dump() for a in item.arguments]
                        if item.arguments
                        else [],
                    },
                    title=f"Prompt: {item.name}",
                )

    @work(exclusive=False)
    async def read_selected_resource(self, uri: str) -> None:
        """Read a selected resource."""
        result_panel = self.query_one("#result-panel", ResultPanel)
        try:
            result = await self.client.read_resource(uri)
            result_panel.write_json(result, title=f"Resource Content: {uri}")
        except Exception as e:
            result_panel.write_error(f"Failed to read resource: {e}")

    @on(Button.Pressed, "#btn-refresh")
    def handle_refresh(self) -> None:
        """Handle refresh button."""
        self.action_refresh()

    @on(Button.Pressed, "#btn-ping")
    def handle_ping(self) -> None:
        """Handle ping button."""
        self.action_ping()

    @on(Button.Pressed, "#btn-logs")
    def handle_logs(self) -> None:
        """Handle logs button."""
        self.action_show_logs()

    def action_refresh(self) -> None:
        """Refresh capabilities."""
        self.load_capabilities()

    @work(exclusive=False)
    async def action_ping(self) -> None:
        """Ping the server."""
        result_panel = self.query_one("#result-panel", ResultPanel)
        try:
            success = await self.client.ping()
            if success:
                result_panel.write_info("Ping successful!")
            else:
                result_panel.write_error("Ping failed")
        except Exception as e:
            result_panel.write_error(f"Ping error: {e}")

    def action_show_logs(self) -> None:
        """Show the logs tab."""
        tabs = self.query_one("#tabs", TabbedContent)
        tabs.active = "tab-logs"

        log_panel = self.query_one("#log-panel", RichLog)
        log_panel.clear()

        for entry in self.client.get_log_entries():
            direction_color = {
                "request": "blue",
                "response": "green",
                "notification": "yellow",
            }
            color = direction_color.get(entry.direction.value, "white")

            log_panel.write(
                f"[{color}]{entry.timestamp.strftime('%H:%M:%S')} "
                f"{entry.direction.value.upper()} {entry.method}[/]"
            )
            if entry.duration_ms:
                log_panel.write(f"  Duration: {entry.duration_ms:.2f}ms")
            if entry.error:
                log_panel.write(f"  [red]Error: {entry.error}[/]")

    def action_clear(self) -> None:
        """Clear the result panel."""
        result_panel = self.query_one("#result-panel", ResultPanel)
        result_panel.clear()

    def action_call_tool(self) -> None:
        """Open the tool call dialog for the selected tool."""
        if self._tool_dialog is not None:
            # Dialog already open, don't open another
            return

        if not self._current_tool:
            result_panel = self.query_one("#result-panel", ResultPanel)
            result_panel.write_error("No tool selected. Select a tool from the tree first.")
            return

        tool_name = self._current_tool["name"]
        schema = self._current_tool["schema"]

        self._tool_dialog = ToolCallDialog(tool_name, schema)
        self.mount(self._tool_dialog)

        # Focus the first input field after mounting
        self.call_later(self._focus_dialog_input)

    def _focus_dialog_input(self) -> None:
        """Focus the first input in the dialog."""
        if self._tool_dialog and self._tool_dialog.inputs:
            first_input = next(iter(self._tool_dialog.inputs.values()), None)
            if first_input:
                first_input.focus()

    def action_close_dialog(self) -> None:
        """Close the tool call dialog if open."""
        if self._tool_dialog is not None:
            self._tool_dialog.remove()
            self._tool_dialog = None

    @on(Button.Pressed, "#btn-call")
    def handle_call_button(self, event: Button.Pressed) -> None:
        """Handle the Call button press in the dialog."""
        if self._tool_dialog is not None:
            arguments = self._tool_dialog.get_arguments()
            tool_name = self._tool_dialog.tool_name
            self._tool_dialog.set_loading(True)
            self.execute_tool_call(tool_name, arguments)

    @on(Button.Pressed, "#btn-cancel")
    def handle_cancel_button(self, event: Button.Pressed) -> None:
        """Handle the Cancel button press in the dialog."""
        self.action_close_dialog()

    @work(exclusive=False)
    async def execute_tool_call(self, tool_name: str, arguments: dict[str, Any]) -> None:
        """Execute a tool call and display the result."""
        result_panel = self.query_one("#result-panel", ResultPanel)

        try:
            result = await self.client.call_tool(tool_name, arguments)
            result_panel.write_json(
                {"tool": tool_name, "arguments": arguments, "result": result},
                title=f"Tool Call: {tool_name}",
            )
        except Exception as e:
            result_panel.write_error(f"Tool call failed: {e}")
        finally:
            # Close the dialog
            self.action_close_dialog()

    def on_tree_node_activated(self, event: Any) -> None:
        """Handle double-click on tree node to open tool dialog."""
        node: TreeNode[dict[str, Any]] = event.node
        if node.data:
            item_type = node.data.get("type")
            if item_type == "tool":
                # Store the tool and open the dialog
                item = node.data.get("item")
                if item is not None:
                    self._current_tool = {
                        "name": item.name,
                        "schema": item.inputSchema or {},
                    }
                    self.action_call_tool()

    @on(ToolCallDialog.DialogDismissed)
    def handle_dialog_dismissed(self, event: ToolCallDialog.DialogDismissed) -> None:
        """Handle dialog dismissal."""
        self.action_close_dialog()

    @on(ToolCallDialog.ToolCallRequested)
    def handle_tool_call_requested(self, event: ToolCallDialog.ToolCallRequested) -> None:
        """Handle tool call request from dialog."""
        if self._tool_dialog:
            self._tool_dialog.set_loading(True)
        self.execute_tool_call(event.tool_name, event.arguments)


def run_tui(config: ClientConfig) -> None:
    """Run the TUI application."""
    app = MCPTestApp(config)
    app.run()
