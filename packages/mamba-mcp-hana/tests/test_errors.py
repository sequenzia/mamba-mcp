"""Tests for error handling system with fuzzy matching."""

import pytest
from mamba_mcp_hana.errors import (
    ERROR_SUGGESTIONS,
    ErrorCode,
    ToolError,
    _levenshtein_distance,
    create_tool_error,
    suggest_similar,
)

# All 12 error codes for parametrized tests
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
    ("VIEW_NOT_FOUND", "VIEW_NOT_FOUND"),
    ("PROCEDURE_NOT_FOUND", "PROCEDURE_NOT_FOUND"),
]


class TestErrorCode:
    """Tests for ErrorCode constants."""

    @pytest.mark.parametrize("attr,expected", ALL_ERROR_CODES)
    def test_error_code_resolves_to_expected_string(self, attr: str, expected: str) -> None:
        """Each error code constant should resolve to its expected string value."""
        assert getattr(ErrorCode, attr) == expected

    def test_all_12_error_codes_defined(self) -> None:
        """ErrorCode class should define exactly 12 constants."""
        codes = [
            name
            for name in dir(ErrorCode)
            if not name.startswith("_") and isinstance(getattr(ErrorCode, name), str)
        ]
        assert len(codes) == 12

    def test_error_codes_are_uppercase_strings(self) -> None:
        """All error code values should be uppercase strings."""
        codes = [
            getattr(ErrorCode, name)
            for name in dir(ErrorCode)
            if not name.startswith("_") and isinstance(getattr(ErrorCode, name), str)
        ]
        for code in codes:
            assert code == code.upper()
            assert isinstance(code, str)


class TestToolError:
    """Tests for ToolError Pydantic model."""

    def test_creates_with_all_fields(self) -> None:
        """ToolError should accept all specified fields."""
        error = ToolError(
            code="TABLE_NOT_FOUND",
            message="Table USERS not found",
            suggestion="Check table name spelling",
            context={"schema": "PUBLIC"},
            tool_name="describe_table",
            input_received={"schema": "PUBLIC", "table": "USERS"},
        )
        assert error.code == "TABLE_NOT_FOUND"
        assert error.message == "Table USERS not found"
        assert error.suggestion == "Check table name spelling"
        assert error.context == {"schema": "PUBLIC"}
        assert error.tool_name == "describe_table"
        assert error.input_received == {"schema": "PUBLIC", "table": "USERS"}

    def test_optional_fields_default_to_none(self) -> None:
        """Optional fields should default to None."""
        error = ToolError(
            code="CONNECTION_ERROR",
            message="Connection failed",
            tool_name="list_schemas",
        )
        assert error.suggestion is None
        assert error.context is None
        assert error.input_received is None

    def test_model_dump_includes_all_fields(self) -> None:
        """model_dump should include all fields."""
        error = ToolError(
            code="INVALID_SQL",
            message="Blocked keyword detected",
            tool_name="execute_query",
        )
        dumped = error.model_dump()
        assert "code" in dumped
        assert "message" in dumped
        assert "suggestion" in dumped
        assert "context" in dumped
        assert "tool_name" in dumped
        assert "input_received" in dumped


class TestCreateToolError:
    """Tests for create_tool_error factory function."""

    def test_creates_tool_error_with_all_fields(self) -> None:
        """Factory should produce a ToolError with all provided fields."""
        error = create_tool_error(
            code=ErrorCode.TABLE_NOT_FOUND,
            message="Table ORDERS not found in schema PUBLIC",
            tool_name="describe_table",
            input_received={"schema": "PUBLIC", "table": "ORDERS"},
            context={"available_tables": ["USERS", "PRODUCTS"]},
            suggestion="Did you mean USERS or PRODUCTS?",
        )
        assert isinstance(error, ToolError)
        assert error.code == "TABLE_NOT_FOUND"
        assert error.message == "Table ORDERS not found in schema PUBLIC"
        assert error.tool_name == "describe_table"
        assert error.input_received == {"schema": "PUBLIC", "table": "ORDERS"}
        assert error.context == {"available_tables": ["USERS", "PRODUCTS"]}
        assert error.suggestion == "Did you mean USERS or PRODUCTS?"

    def test_uses_default_suggestion_when_none_provided(self) -> None:
        """Factory should use default suggestion from ERROR_SUGGESTIONS map."""
        error = create_tool_error(
            code=ErrorCode.SCHEMA_NOT_FOUND,
            message="Schema MISSING not found",
            tool_name="list_tables",
        )
        assert error.suggestion == ERROR_SUGGESTIONS[ErrorCode.SCHEMA_NOT_FOUND]

    def test_custom_suggestion_overrides_default(self) -> None:
        """Custom suggestion should override the default from the map."""
        custom = "Try using schema SAP_HANA"
        error = create_tool_error(
            code=ErrorCode.SCHEMA_NOT_FOUND,
            message="Schema not found",
            tool_name="list_tables",
            suggestion=custom,
        )
        assert error.suggestion == custom

    def test_handles_none_optional_fields(self) -> None:
        """Factory should handle None for all optional fields."""
        error = create_tool_error(
            code=ErrorCode.CONNECTION_ERROR,
            message="Connection refused",
            tool_name="list_schemas",
            input_received=None,
            context=None,
            suggestion=None,
        )
        assert isinstance(error, ToolError)
        assert error.input_received is None
        assert error.context is None
        # When suggestion is None, default from map is used
        assert error.suggestion == ERROR_SUGGESTIONS[ErrorCode.CONNECTION_ERROR]

    def test_unknown_code_without_suggestion_gets_none(self) -> None:
        """Unknown error code with no suggestion should result in None suggestion."""
        error = create_tool_error(
            code="UNKNOWN_CODE",
            message="Something unknown happened",
            tool_name="some_tool",
        )
        assert error.suggestion is None


class TestLevenshteinDistance:
    """Tests for Levenshtein distance calculation."""

    def test_identical_strings(self) -> None:
        """Identical strings should have distance 0."""
        assert _levenshtein_distance("kitten", "kitten") == 0

    def test_empty_strings(self) -> None:
        """Empty strings should have distance equal to the other string's length."""
        assert _levenshtein_distance("", "") == 0
        assert _levenshtein_distance("abc", "") == 3
        assert _levenshtein_distance("", "xyz") == 3

    def test_classic_kitten_sitting(self) -> None:
        """Classic example: kitten -> sitting = 3."""
        assert _levenshtein_distance("kitten", "sitting") == 3

    def test_single_insertion(self) -> None:
        """One character insertion should give distance 1."""
        assert _levenshtein_distance("cat", "cats") == 1

    def test_single_deletion(self) -> None:
        """One character deletion should give distance 1."""
        assert _levenshtein_distance("cats", "cat") == 1

    def test_single_substitution(self) -> None:
        """One character substitution should give distance 1."""
        assert _levenshtein_distance("cat", "car") == 1

    def test_completely_different(self) -> None:
        """Completely different strings should have high distance."""
        assert _levenshtein_distance("abc", "xyz") == 3

    def test_symmetric(self) -> None:
        """Distance should be symmetric: d(a,b) == d(b,a)."""
        assert _levenshtein_distance("abc", "def") == _levenshtein_distance("def", "abc")

    def test_known_pairs(self) -> None:
        """Known edit distance pairs for common schema names."""
        # USERS -> USER = 1 (deletion)
        assert _levenshtein_distance("USERS", "USER") == 1
        # ORDERS -> ORDER = 1 (deletion)
        assert _levenshtein_distance("ORDERS", "ORDER") == 1
        # PUBLIC -> PUBILC = 2 (transposition = 2 in levenshtein)
        assert _levenshtein_distance("PUBLIC", "PUBILC") == 2


class TestSuggestSimilar:
    """Tests for suggest_similar fuzzy matching."""

    def test_returns_top_n_matches(self) -> None:
        """Should return up to max_suggestions closest matches."""
        candidates = ["USERS", "USER_ROLES", "ORDERS", "PRODUCTS", "USER_LOGS"]
        result = suggest_similar("USERS", candidates, max_suggestions=3)
        assert len(result) <= 3
        assert "USERS" in result  # Exact match

    def test_exact_match_returned_first(self) -> None:
        """Exact match should be the first result."""
        candidates = ["ORDERS", "USERS", "PRODUCTS"]
        result = suggest_similar("USERS", candidates)
        assert result[0] == "USERS"

    def test_close_matches_sorted_by_distance(self) -> None:
        """Results should be sorted by edit distance, closest first."""
        candidates = ["USER", "USERS", "USXRS"]
        result = suggest_similar("USERS", candidates)
        assert result[0] == "USERS"  # distance 0
        assert result[1] == "USER"  # distance 1

    def test_empty_candidates_returns_empty(self) -> None:
        """Empty candidate list should return empty list."""
        result = suggest_similar("USERS", [])
        assert result == []

    def test_all_candidates_high_distance_returns_empty(self) -> None:
        """When all candidates exceed the threshold, return empty list."""
        candidates = ["COMPLETELY_DIFFERENT_NAME", "ANOTHER_LONG_UNRELATED_NAME"]
        result = suggest_similar("XY", candidates)
        assert result == []

    def test_case_insensitive_matching(self) -> None:
        """Matching should be case-insensitive."""
        candidates = ["USERS", "orders", "Products"]
        result = suggest_similar("users", candidates)
        assert "USERS" in result

    def test_max_suggestions_respected(self) -> None:
        """Should not return more than max_suggestions items."""
        candidates = ["USER", "USERS", "USAR", "USDR", "USKR"]
        result = suggest_similar("USERS", candidates, max_suggestions=2)
        assert len(result) <= 2

    def test_schema_name_typo_suggestions(self) -> None:
        """Realistic scenario: typo in schema name gets corrected."""
        candidates = ["SYS", "PUBLIC", "SAP_HANA", "_SYS_BIC"]
        result = suggest_similar("PUBILC", candidates)
        assert "PUBLIC" in result

    def test_single_candidate_within_threshold(self) -> None:
        """Single candidate within threshold should be returned."""
        result = suggest_similar("USERS", ["USER"])
        assert result == ["USER"]

    def test_single_candidate_beyond_threshold(self) -> None:
        """Single candidate beyond threshold should not be returned."""
        result = suggest_similar("AB", ["ZYXWVUTSRQ"])
        assert result == []


class TestErrorSuggestionsMap:
    """Tests for the default ERROR_SUGGESTIONS map."""

    def test_has_entry_for_each_error_code(self) -> None:
        """ERROR_SUGGESTIONS should have an entry for every ErrorCode."""
        codes = [
            getattr(ErrorCode, name)
            for name in dir(ErrorCode)
            if not name.startswith("_") and isinstance(getattr(ErrorCode, name), str)
        ]
        for code in codes:
            assert code in ERROR_SUGGESTIONS, f"Missing suggestion for {code}"

    def test_suggestions_are_non_empty_strings(self) -> None:
        """All suggestions should be non-empty strings."""
        for code, suggestion in ERROR_SUGGESTIONS.items():
            assert isinstance(suggestion, str), f"Suggestion for {code} is not a string"
            assert len(suggestion) > 0, f"Suggestion for {code} is empty"

    @pytest.mark.parametrize("attr,_", ALL_ERROR_CODES)
    def test_each_code_has_suggestion(self, attr: str, _: str) -> None:
        """Each individual error code should have a corresponding suggestion."""
        code_value = getattr(ErrorCode, attr)
        assert code_value in ERROR_SUGGESTIONS
