"""Logging infrastructure for comprehensive MCP protocol message capture."""

import json
import logging
import sys
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table


class MessageDirection(str, Enum):
    """Direction of MCP message."""

    REQUEST = "request"
    RESPONSE = "response"
    NOTIFICATION = "notification"


@dataclass
class MCPLogEntry:
    """A single MCP protocol log entry."""

    timestamp: datetime
    direction: MessageDirection
    method: str
    data: dict[str, Any]
    duration_ms: float | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "timestamp": self.timestamp.isoformat(),
            "direction": self.direction.value,
            "method": self.method,
            "data": self.data,
            "duration_ms": self.duration_ms,
            "error": self.error,
        }


@dataclass
class MCPLogger:
    """Logger for MCP protocol messages with rich console output."""

    name: str = "mamba-mcp"
    level: str = "INFO"
    log_file: str | None = None
    log_requests: bool = True
    log_responses: bool = True
    entries: list[MCPLogEntry] = field(default_factory=list)
    console: Console = field(default_factory=Console)
    _logger: logging.Logger | None = field(default=None, init=False)

    def __post_init__(self) -> None:
        """Set up the Python logger."""
        self._logger = logging.getLogger(self.name)
        self._logger.setLevel(getattr(logging, self.level.upper()))

        # Clear existing handlers
        self._logger.handlers.clear()

        # Console handler
        console_handler = logging.StreamHandler(sys.stderr)
        console_handler.setLevel(getattr(logging, self.level.upper()))
        formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
        console_handler.setFormatter(formatter)
        self._logger.addHandler(console_handler)

        # File handler if specified
        if self.log_file:
            file_handler = logging.FileHandler(self.log_file)
            file_handler.setLevel(getattr(logging, self.level.upper()))
            file_handler.setFormatter(formatter)
            self._logger.addHandler(file_handler)

    def log_request(
        self,
        method: str,
        params: dict[str, Any] | None = None,
    ) -> MCPLogEntry:
        """Log an outgoing MCP request."""
        entry = MCPLogEntry(
            timestamp=datetime.now(),
            direction=MessageDirection.REQUEST,
            method=method,
            data=params or {},
        )
        self.entries.append(entry)

        if self.log_requests and self._logger:
            self._logger.debug(f"REQUEST: {method} - {json.dumps(params or {})}")

        return entry

    def log_response(
        self,
        method: str,
        result: Any,
        request_entry: MCPLogEntry | None = None,
        error: str | None = None,
    ) -> MCPLogEntry:
        """Log an incoming MCP response."""
        duration_ms = None
        if request_entry:
            duration = datetime.now() - request_entry.timestamp
            duration_ms = duration.total_seconds() * 1000

        # Convert result to dict if possible
        if hasattr(result, "model_dump"):
            data = result.model_dump()
        elif hasattr(result, "__dict__"):
            data = {"result": str(result)}
        elif isinstance(result, dict):
            data = result
        else:
            data = {"result": result}

        entry = MCPLogEntry(
            timestamp=datetime.now(),
            direction=MessageDirection.RESPONSE,
            method=method,
            data=data,
            duration_ms=duration_ms,
            error=error,
        )
        self.entries.append(entry)

        if self.log_responses and self._logger:
            if error:
                self._logger.error(f"RESPONSE ERROR: {method} - {error}")
            elif duration_ms is not None:
                self._logger.debug(f"RESPONSE: {method} ({duration_ms:.2f}ms)")
            else:
                self._logger.debug(f"RESPONSE: {method}")

        return entry

    def log_notification(self, method: str, params: dict[str, Any] | None = None) -> MCPLogEntry:
        """Log an MCP notification."""
        entry = MCPLogEntry(
            timestamp=datetime.now(),
            direction=MessageDirection.NOTIFICATION,
            method=method,
            data=params or {},
        )
        self.entries.append(entry)

        if self._logger:
            self._logger.debug(f"NOTIFICATION: {method}")

        return entry

    def get_entries(
        self,
        direction: MessageDirection | None = None,
        method: str | None = None,
        limit: int | None = None,
    ) -> list[MCPLogEntry]:
        """Get log entries with optional filtering."""
        result = self.entries

        if direction:
            result = [e for e in result if e.direction == direction]

        if method:
            result = [e for e in result if e.method == method]

        if limit:
            result = result[-limit:]

        return result

    def clear(self) -> None:
        """Clear all log entries."""
        self.entries.clear()

    def export_json(self) -> str:
        """Export all log entries as JSON."""
        return json.dumps([e.to_dict() for e in self.entries], indent=2)

    def print_entry(self, entry: MCPLogEntry) -> None:
        """Print a log entry with rich formatting."""
        direction_color = {
            MessageDirection.REQUEST: "blue",
            MessageDirection.RESPONSE: "green",
            MessageDirection.NOTIFICATION: "yellow",
        }

        title = f"[{direction_color[entry.direction]}]{entry.direction.value.upper()}[/] - {entry.method}"
        if entry.duration_ms:
            title += f" ({entry.duration_ms:.2f}ms)"

        json_str = json.dumps(entry.data, indent=2)
        syntax = Syntax(json_str, "json", theme="monokai", line_numbers=False)

        panel = Panel(
            syntax,
            title=title,
            subtitle=entry.timestamp.strftime("%H:%M:%S.%f")[:-3],
            border_style=direction_color[entry.direction],
        )
        self.console.print(panel)

    def print_summary(self) -> None:
        """Print a summary of all logged requests/responses."""
        table = Table(title="MCP Protocol Log Summary")
        table.add_column("Time", style="dim")
        table.add_column("Direction", style="bold")
        table.add_column("Method")
        table.add_column("Duration (ms)", justify="right")
        table.add_column("Status")

        for entry in self.entries:
            direction_style = {
                MessageDirection.REQUEST: "blue",
                MessageDirection.RESPONSE: "green",
                MessageDirection.NOTIFICATION: "yellow",
            }

            status = "[red]ERROR[/]" if entry.error else "[green]OK[/]"
            duration = f"{entry.duration_ms:.2f}" if entry.duration_ms else "-"

            table.add_row(
                entry.timestamp.strftime("%H:%M:%S"),
                f"[{direction_style[entry.direction]}]{entry.direction.value}[/]",
                entry.method,
                duration,
                status,
            )

        self.console.print(table)
