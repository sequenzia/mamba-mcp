"""Tests for the MCPLogger and MCPLogEntry."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

from mamba_mcp_client.logging import MCPLogEntry, MCPLogger, MessageDirection


class TestMessageDirection:
    """Tests for MessageDirection enum."""

    def test_values(self) -> None:
        """Test all direction values match expected strings."""
        assert MessageDirection.REQUEST.value == "request"
        assert MessageDirection.RESPONSE.value == "response"
        assert MessageDirection.NOTIFICATION.value == "notification"


class TestMCPLogEntry:
    """Tests for MCPLogEntry dataclass."""

    def test_to_dict(self) -> None:
        """Test serialization to dictionary."""
        logger = MCPLogger(name="test", level="DEBUG")
        entry = logger.log_request("tools/list", {"key": "value"})

        result = entry.to_dict()
        assert result["direction"] == "request"
        assert result["method"] == "tools/list"
        assert result["data"] == {"key": "value"}
        assert result["duration_ms"] is None
        assert result["error"] is None
        assert "timestamp" in result

    def test_to_dict_with_error(self) -> None:
        """Test serialization includes error field."""
        logger = MCPLogger(name="test", level="DEBUG")
        req = logger.log_request("tools/call")
        resp = logger.log_response("tools/call", {}, req, error="Connection lost")

        result = resp.to_dict()
        assert result["error"] == "Connection lost"

    def test_to_dict_with_duration(self) -> None:
        """Test serialization includes duration from request-response pair."""
        logger = MCPLogger(name="test", level="DEBUG")
        req = logger.log_request("ping")
        resp = logger.log_response("ping", {"success": True}, req)

        result = resp.to_dict()
        assert result["duration_ms"] is not None
        assert result["duration_ms"] >= 0


class TestMCPLoggerInit:
    """Tests for MCPLogger initialization."""

    def test_default_init(self) -> None:
        """Test logger initializes with defaults."""
        logger = MCPLogger()
        assert logger.name == "mamba-mcp"
        assert logger.level == "INFO"
        assert logger.log_file is None
        assert logger.log_requests is True
        assert logger.log_responses is True
        assert logger.entries == []

    def test_custom_init(self) -> None:
        """Test logger initializes with custom values."""
        logger = MCPLogger(
            name="custom-client",
            level="DEBUG",
            log_requests=False,
            log_responses=False,
        )
        assert logger.name == "custom-client"
        assert logger.level == "DEBUG"
        assert logger.log_requests is False
        assert logger.log_responses is False

    def test_post_init_creates_python_logger(self) -> None:
        """Test that __post_init__ creates underlying Python logger."""
        logger = MCPLogger(name="test-logger", level="DEBUG")
        assert logger._logger is not None
        assert logger._logger.name == "test-logger"


class TestLogRequest:
    """Tests for MCPLogger.log_request()."""

    def test_log_request_basic(self) -> None:
        """Test basic request logging."""
        logger = MCPLogger(name="test", level="DEBUG")
        entry = logger.log_request("tools/list")

        assert entry.direction == MessageDirection.REQUEST
        assert entry.method == "tools/list"
        assert entry.data == {}
        assert entry.duration_ms is None
        assert entry.error is None

    def test_log_request_with_params(self) -> None:
        """Test request logging with parameters."""
        logger = MCPLogger(name="test", level="DEBUG")
        entry = logger.log_request("tools/call", {"name": "add", "arguments": {"a": 1}})

        assert entry.data == {"name": "add", "arguments": {"a": 1}}

    def test_log_request_appends_to_entries(self) -> None:
        """Test that log_request adds entry to entries list."""
        logger = MCPLogger(name="test", level="DEBUG")
        assert len(logger.entries) == 0

        logger.log_request("ping")
        assert len(logger.entries) == 1

        logger.log_request("tools/list")
        assert len(logger.entries) == 2

    def test_log_request_returns_entry(self) -> None:
        """Test that log_request returns the created entry."""
        logger = MCPLogger(name="test", level="DEBUG")
        entry = logger.log_request("ping")

        assert isinstance(entry, MCPLogEntry)
        assert entry is logger.entries[0]


class TestLogResponse:
    """Tests for MCPLogger.log_response()."""

    def test_log_response_basic(self) -> None:
        """Test basic response logging."""
        logger = MCPLogger(name="test", level="DEBUG")
        entry = logger.log_response("tools/list", {"tools": []})

        assert entry.direction == MessageDirection.RESPONSE
        assert entry.method == "tools/list"
        assert entry.data == {"tools": []}

    def test_log_response_with_duration(self) -> None:
        """Test response logging computes duration from request entry."""
        logger = MCPLogger(name="test", level="DEBUG")
        req = logger.log_request("ping")
        resp = logger.log_response("ping", {"success": True}, req)

        assert resp.duration_ms is not None
        assert resp.duration_ms >= 0

    def test_log_response_without_request_entry(self) -> None:
        """Test response logging without paired request has no duration."""
        logger = MCPLogger(name="test", level="DEBUG")
        entry = logger.log_response("ping", {"success": True})

        assert entry.duration_ms is None

    def test_log_response_with_error(self) -> None:
        """Test response logging with error string."""
        logger = MCPLogger(name="test", level="DEBUG")
        req = logger.log_request("tools/call")
        entry = logger.log_response("tools/call", {}, req, error="Tool not found")

        assert entry.error == "Tool not found"

    def test_log_response_with_pydantic_model(self) -> None:
        """Test response logging handles Pydantic model_dump."""
        logger = MCPLogger(name="test", level="DEBUG")
        mock_result = MagicMock()
        mock_result.model_dump.return_value = {"status": "ok"}

        entry = logger.log_response("test", mock_result)
        assert entry.data == {"status": "ok"}

    def test_log_response_with_dict(self) -> None:
        """Test response logging passes dicts through."""
        logger = MCPLogger(name="test", level="DEBUG")
        entry = logger.log_response("test", {"key": "value"})
        assert entry.data == {"key": "value"}

    def test_log_response_with_other_object(self) -> None:
        """Test response logging wraps unknown objects in string."""
        logger = MCPLogger(name="test", level="DEBUG")
        entry = logger.log_response("test", 42)
        assert entry.data == {"result": 42}


class TestLogNotification:
    """Tests for MCPLogger.log_notification()."""

    def test_log_notification(self) -> None:
        """Test notification logging."""
        logger = MCPLogger(name="test", level="DEBUG")
        entry = logger.log_notification("progress", {"percent": 50})

        assert entry.direction == MessageDirection.NOTIFICATION
        assert entry.method == "progress"
        assert entry.data == {"percent": 50}

    def test_log_notification_no_params(self) -> None:
        """Test notification logging without parameters."""
        logger = MCPLogger(name="test", level="DEBUG")
        entry = logger.log_notification("heartbeat")

        assert entry.data == {}


class TestGetEntries:
    """Tests for MCPLogger.get_entries() filtering."""

    def test_get_all_entries(self) -> None:
        """Test getting all entries without filters."""
        logger = MCPLogger(name="test", level="DEBUG")
        logger.log_request("a")
        logger.log_request("b")
        logger.log_response("a", {})

        entries = logger.get_entries()
        assert len(entries) == 3

    def test_filter_by_direction(self) -> None:
        """Test filtering entries by direction."""
        logger = MCPLogger(name="test", level="DEBUG")
        logger.log_request("tools/list")
        logger.log_response("tools/list", {})
        logger.log_notification("progress")

        requests = logger.get_entries(direction=MessageDirection.REQUEST)
        assert len(requests) == 1
        assert requests[0].method == "tools/list"

        notifications = logger.get_entries(direction=MessageDirection.NOTIFICATION)
        assert len(notifications) == 1

    def test_filter_by_method(self) -> None:
        """Test filtering entries by method name."""
        logger = MCPLogger(name="test", level="DEBUG")
        logger.log_request("tools/list")
        logger.log_request("tools/call")
        logger.log_response("tools/list", {})

        entries = logger.get_entries(method="tools/list")
        assert len(entries) == 2  # request + response

    def test_filter_by_limit(self) -> None:
        """Test limiting number of returned entries (last N)."""
        logger = MCPLogger(name="test", level="DEBUG")
        for i in range(5):
            logger.log_request(f"method_{i}")

        entries = logger.get_entries(limit=2)
        assert len(entries) == 2
        assert entries[0].method == "method_3"
        assert entries[1].method == "method_4"

    def test_combined_filters(self) -> None:
        """Test combining direction and method filters."""
        logger = MCPLogger(name="test", level="DEBUG")
        logger.log_request("tools/list")
        logger.log_response("tools/list", {})
        logger.log_request("tools/call")
        logger.log_response("tools/call", {})

        entries = logger.get_entries(direction=MessageDirection.RESPONSE, method="tools/call")
        assert len(entries) == 1
        assert entries[0].method == "tools/call"
        assert entries[0].direction == MessageDirection.RESPONSE


class TestClear:
    """Tests for MCPLogger.clear()."""

    def test_clear_removes_all_entries(self) -> None:
        """Test that clear empties the entries list."""
        logger = MCPLogger(name="test", level="DEBUG")
        logger.log_request("a")
        logger.log_request("b")
        assert len(logger.entries) == 2

        logger.clear()
        assert len(logger.entries) == 0


class TestExportJson:
    """Tests for MCPLogger.export_json()."""

    def test_export_empty(self) -> None:
        """Test exporting empty log."""
        logger = MCPLogger(name="test", level="DEBUG")
        result = logger.export_json()
        assert json.loads(result) == []

    def test_export_with_entries(self) -> None:
        """Test exporting log entries as valid JSON."""
        logger = MCPLogger(name="test", level="DEBUG")
        logger.log_request("tools/list", {"filter": "all"})
        logger.log_response("tools/list", {"tools": []})

        result = logger.export_json()
        parsed = json.loads(result)
        assert len(parsed) == 2
        assert parsed[0]["direction"] == "request"
        assert parsed[0]["method"] == "tools/list"
        assert parsed[1]["direction"] == "response"


class TestPrintEntry:
    """Tests for MCPLogger.print_entry() rich output."""

    def test_print_entry_does_not_raise(self) -> None:
        """Test that print_entry executes without error."""
        logger = MCPLogger(name="test", level="DEBUG")
        entry = logger.log_request("tools/list", {"key": "value"})
        # Should not raise — we're testing it doesn't crash
        logger.print_entry(entry)

    def test_print_entry_with_duration(self) -> None:
        """Test that print_entry handles entries with duration."""
        logger = MCPLogger(name="test", level="DEBUG")
        req = logger.log_request("ping")
        resp = logger.log_response("ping", {"ok": True}, req)
        logger.print_entry(resp)


class TestPrintSummary:
    """Tests for MCPLogger.print_summary() rich output."""

    def test_print_summary_empty(self) -> None:
        """Test that print_summary works with no entries."""
        logger = MCPLogger(name="test", level="DEBUG")
        logger.print_summary()

    def test_print_summary_with_entries(self) -> None:
        """Test that print_summary works with mixed entries."""
        logger = MCPLogger(name="test", level="DEBUG")
        req = logger.log_request("tools/list")
        logger.log_response("tools/list", {}, req)
        logger.log_response("tools/call", {}, error="Failed")
        logger.log_notification("progress")
        logger.print_summary()
