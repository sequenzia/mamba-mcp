"""Tests for structured error handling module."""

import pytest
from mamba_mcp_pg.errors import (
    ERROR_SUGGESTIONS,
    ErrorCode,
    create_tool_error,
    find_similar_names,
)

# All 10 error codes as (attr_name, expected_value) pairs for parametrize
ALL_ERROR_CODES = [
    ("SCHEMA_NOT_FOUND", "SCHEMA_NOT_FOUND"),
    ("TABLE_NOT_FOUND", "TABLE_NOT_FOUND"),
    ("COLUMN_NOT_FOUND", "COLUMN_NOT_FOUND"),
    ("INVALID_SQL", "INVALID_SQL"),
    ("WRITE_OPERATION_DENIED", "WRITE_OPERATION_DENIED"),
    ("QUERY_TIMEOUT", "QUERY_TIMEOUT"),
    ("CONNECTION_ERROR", "CONNECTION_ERROR"),
    ("PERMISSION_DENIED", "PERMISSION_DENIED"),
    ("PARAMETER_ERROR", "PARAMETER_ERROR"),
    ("PATH_NOT_FOUND", "PATH_NOT_FOUND"),
]


class TestErrorCode:
    """Tests for ErrorCode class constants."""

    @pytest.mark.parametrize(("attr", "expected"), ALL_ERROR_CODES)
    def test_error_code_value(self, attr: str, expected: str) -> None:
        """Test that each error code constant resolves to its expected string value."""
        assert getattr(ErrorCode, attr) == expected

    def test_exactly_ten_error_codes_defined(self) -> None:
        """Test that ErrorCode defines exactly 10 public constants."""
        public_attrs = [a for a in dir(ErrorCode) if not a.startswith("_")]
        assert len(public_attrs) == 10

    @pytest.mark.parametrize(("attr", "_expected"), ALL_ERROR_CODES)
    def test_error_codes_are_uppercase_strings(self, attr: str, _expected: str) -> None:
        """Test that each error code value is a non-empty uppercase string."""
        value = getattr(ErrorCode, attr)
        assert isinstance(value, str)
        assert value == value.upper()
        assert len(value) > 0


class TestErrorSuggestions:
    """Tests for ERROR_SUGGESTIONS mapping."""

    @pytest.mark.parametrize(("attr", "expected"), ALL_ERROR_CODES)
    def test_suggestion_exists_for_error_code(self, attr: str, expected: str) -> None:
        """Test that ERROR_SUGGESTIONS has an entry for each error code."""
        assert expected in ERROR_SUGGESTIONS

    @pytest.mark.parametrize(("attr", "expected"), ALL_ERROR_CODES)
    def test_suggestion_is_non_empty_string(self, attr: str, expected: str) -> None:
        """Test that each suggestion is a non-empty string."""
        suggestion = ERROR_SUGGESTIONS[expected]
        assert isinstance(suggestion, str)
        assert len(suggestion) > 0

    def test_suggestions_count_matches_error_codes(self) -> None:
        """Test that suggestion count matches the number of error codes."""
        public_attrs = [a for a in dir(ErrorCode) if not a.startswith("_")]
        assert len(ERROR_SUGGESTIONS) == len(public_attrs)


class TestCreateToolError:
    """Tests for create_tool_error wrapper function."""

    def test_creates_error_with_all_fields(self) -> None:
        """Test that create_tool_error returns a dict with all expected fields populated."""
        result = create_tool_error(
            code=ErrorCode.TABLE_NOT_FOUND,
            message="Table 'orders' not found in schema 'public'",
            tool_name="describe_table",
            input_received={"schema": "public", "table": "orders"},
            context={"available_tables": ["users", "products"]},
            suggestion="Check table name spelling",
        )

        assert isinstance(result, dict)
        assert result["code"] == "TABLE_NOT_FOUND"
        assert result["message"] == "Table 'orders' not found in schema 'public'"
        assert result["tool_name"] == "describe_table"
        assert result["input_received"] == {"schema": "public", "table": "orders"}
        assert result["context"] == {"available_tables": ["users", "products"]}
        assert result["suggestion"] == "Check table name spelling"

    def test_uses_default_suggestion_when_none_provided(self) -> None:
        """Test that the default suggestion from ERROR_SUGGESTIONS is used when not overridden."""
        result = create_tool_error(
            code=ErrorCode.SCHEMA_NOT_FOUND,
            message="Schema not found",
            tool_name="list_tables",
        )

        assert result["suggestion"] == ERROR_SUGGESTIONS[ErrorCode.SCHEMA_NOT_FOUND]

    def test_custom_suggestion_overrides_default(self) -> None:
        """Test that an explicit suggestion overrides the default from ERROR_SUGGESTIONS."""
        custom = "Try running list_schemas first"
        result = create_tool_error(
            code=ErrorCode.SCHEMA_NOT_FOUND,
            message="Schema not found",
            tool_name="list_tables",
            suggestion=custom,
        )

        assert result["suggestion"] == custom
        assert result["suggestion"] != ERROR_SUGGESTIONS[ErrorCode.SCHEMA_NOT_FOUND]

    def test_handles_none_optional_fields(self) -> None:
        """Test that optional fields default to None when not provided."""
        result = create_tool_error(
            code=ErrorCode.INVALID_SQL,
            message="Syntax error",
            tool_name="execute_query",
        )

        assert result["input_received"] is None
        assert result["context"] is None

    def test_unknown_code_gets_none_suggestion(self) -> None:
        """Test that an unrecognized error code results in a None suggestion."""
        result = create_tool_error(
            code="UNKNOWN_CODE",
            message="Something went wrong",
            tool_name="some_tool",
        )

        assert result["suggestion"] is None


class TestFindSimilarNames:
    """Smoke tests for find_similar_names re-export (core has comprehensive tests)."""

    def test_exact_match_returned(self) -> None:
        """Test that an exact match is included in results."""
        result = find_similar_names("users", ["users", "orders", "products"])
        assert "users" in result

    def test_close_typo_found(self) -> None:
        """Test that a close misspelling is found among candidates."""
        result = find_similar_names("usres", ["users", "orders", "products"])
        assert "users" in result

    def test_empty_candidates_returns_empty(self) -> None:
        """Test that empty candidate list returns empty results."""
        result = find_similar_names("users", [])
        assert result == []

    def test_case_insensitive_matching(self) -> None:
        """Test that matching is case-insensitive."""
        result = find_similar_names("USERS", ["users", "orders"])
        assert "users" in result
