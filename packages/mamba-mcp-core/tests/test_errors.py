"""Tests for mamba_mcp_core.errors module."""

from mamba_mcp_core.errors import ToolError, create_tool_error


class TestToolError:
    """Tests for ToolError model."""

    def test_minimal_fields(self) -> None:
        """ToolError with required fields only."""
        error = ToolError(code="TEST", message="test msg", tool_name="test_tool")
        assert error.code == "TEST"
        assert error.message == "test msg"
        assert error.tool_name == "test_tool"
        assert error.suggestion is None
        assert error.context is None
        assert error.input_received is None

    def test_all_fields(self) -> None:
        """ToolError with all fields populated."""
        error = ToolError(
            code="ERROR_CODE",
            message="Something went wrong",
            suggestion="Try again",
            context={"key": "value"},
            tool_name="my_tool",
            input_received={"param": 42},
        )
        assert error.code == "ERROR_CODE"
        assert error.suggestion == "Try again"
        assert error.context == {"key": "value"}
        assert error.input_received == {"param": 42}

    def test_model_dump(self) -> None:
        """ToolError serializes to dict correctly."""
        error = ToolError(code="TEST", message="msg", tool_name="tool")
        data = error.model_dump()
        assert data["code"] == "TEST"
        assert data["message"] == "msg"
        assert data["tool_name"] == "tool"

    def test_model_dump_json(self) -> None:
        """ToolError serializes to JSON string."""
        error = ToolError(code="TEST", message="msg", tool_name="tool")
        json_str = error.model_dump_json()
        assert '"code":"TEST"' in json_str or '"code": "TEST"' in json_str


class TestCreateToolError:
    """Tests for create_tool_error factory."""

    def test_basic_error(self) -> None:
        """Creates error with code, message, and tool_name."""
        error = create_tool_error(code="NOT_FOUND", message="Not found", tool_name="list_schemas")
        assert isinstance(error, ToolError)
        assert error.code == "NOT_FOUND"
        assert error.message == "Not found"
        assert error.tool_name == "list_schemas"

    def test_suggestion_from_map(self) -> None:
        """Looks up suggestion from suggestions_map when not provided."""
        suggestions = {"NOT_FOUND": "Try list_schemas first"}
        error = create_tool_error(
            code="NOT_FOUND",
            message="Not found",
            tool_name="tool",
            suggestions_map=suggestions,
        )
        assert error.suggestion == "Try list_schemas first"

    def test_explicit_suggestion_overrides_map(self) -> None:
        """Explicit suggestion takes priority over suggestions_map."""
        suggestions = {"NOT_FOUND": "From map"}
        error = create_tool_error(
            code="NOT_FOUND",
            message="Not found",
            tool_name="tool",
            suggestion="Explicit suggestion",
            suggestions_map=suggestions,
        )
        assert error.suggestion == "Explicit suggestion"

    def test_no_suggestion_when_code_not_in_map(self) -> None:
        """Returns None suggestion when code not in map and no explicit."""
        suggestions = {"OTHER_CODE": "Some suggestion"}
        error = create_tool_error(
            code="UNKNOWN",
            message="Unknown error",
            tool_name="tool",
            suggestions_map=suggestions,
        )
        assert error.suggestion is None

    def test_no_suggestion_without_map(self) -> None:
        """Returns None suggestion when no map provided."""
        error = create_tool_error(code="ERR", message="Error", tool_name="tool")
        assert error.suggestion is None

    def test_with_input_and_context(self) -> None:
        """Passes input_received and context through."""
        error = create_tool_error(
            code="ERR",
            message="Error",
            tool_name="tool",
            input_received={"schema": "public"},
            context={"elapsed_ms": 42.5},
        )
        assert error.input_received == {"schema": "public"}
        assert error.context == {"elapsed_ms": 42.5}
