"""Tests for structured error handling module."""

from unittest.mock import patch

import pytest
from mamba_mcp_gitlab.errors import (
    ERROR_SUGGESTIONS,
    PAGINATION_DEFAULT_PER_PAGE,
    PAGINATION_MAX_PER_PAGE,
    PAGINATION_MIN_PER_PAGE,
    ErrorCode,
    build_error_context,
    clamp_pagination,
    create_tool_error,
    find_similar_names,
    suggest_branch_names,
    suggest_project_names,
)

# All 13 error codes as (attr_name, expected_value) pairs for parametrize
ALL_ERROR_CODES = [
    ("AUTH_FAILED", "AUTH_FAILED"),
    ("FORBIDDEN", "FORBIDDEN"),
    ("NOT_FOUND", "NOT_FOUND"),
    ("PROJECT_NOT_FOUND", "PROJECT_NOT_FOUND"),
    ("MERGE_REQUEST_NOT_FOUND", "MERGE_REQUEST_NOT_FOUND"),
    ("ISSUE_NOT_FOUND", "ISSUE_NOT_FOUND"),
    ("PIPELINE_NOT_FOUND", "PIPELINE_NOT_FOUND"),
    ("RATE_LIMITED", "RATE_LIMITED"),
    ("VALIDATION_ERROR", "VALIDATION_ERROR"),
    ("CONNECTION_ERROR", "CONNECTION_ERROR"),
    ("API_ERROR", "API_ERROR"),
    ("BRANCH_NOT_FOUND", "BRANCH_NOT_FOUND"),
    ("READ_ONLY", "READ_ONLY"),
]


class TestErrorCode:
    """Tests for ErrorCode class constants."""

    @pytest.mark.parametrize(("attr", "expected"), ALL_ERROR_CODES)
    def test_error_code_value(self, attr: str, expected: str) -> None:
        """Test that each error code constant resolves to its expected string value."""
        assert getattr(ErrorCode, attr) == expected

    def test_exactly_thirteen_error_codes_defined(self) -> None:
        """Test that ErrorCode defines exactly 13 public constants."""
        public_attrs = [a for a in dir(ErrorCode) if not a.startswith("_")]
        assert len(public_attrs) == 13

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

    def test_suggestions_reference_tool_names(self) -> None:
        """Test that resource-specific suggestions reference available tool names."""
        tool_references = {
            ErrorCode.PROJECT_NOT_FOUND: "search",
            ErrorCode.MERGE_REQUEST_NOT_FOUND: "list_mrs",
            ErrorCode.ISSUE_NOT_FOUND: "list_issues",
            ErrorCode.PIPELINE_NOT_FOUND: "list_pipelines",
        }
        for code, tool_name in tool_references.items():
            assert tool_name in ERROR_SUGGESTIONS[code], (
                f"Suggestion for {code} should reference tool '{tool_name}'"
            )


class TestCreateToolError:
    """Tests for create_tool_error wrapper function."""

    def test_creates_error_with_all_fields(self) -> None:
        """Test that create_tool_error returns a dict with all expected fields populated."""
        result = create_tool_error(
            code=ErrorCode.PROJECT_NOT_FOUND,
            message="Project 'my-proj' not found",
            tool_name="get_project",
            input_received={"project_id": "my-proj"},
            context={"searched_namespaces": ["group-a", "group-b"]},
            suggestion="Double-check project path",
        )

        assert isinstance(result, dict)
        assert result["code"] == "PROJECT_NOT_FOUND"
        assert result["message"] == "Project 'my-proj' not found"
        assert result["tool_name"] == "get_project"
        assert result["input_received"] == {"project_id": "my-proj"}
        assert result["context"] == {"searched_namespaces": ["group-a", "group-b"]}
        assert result["suggestion"] == "Double-check project path"

    def test_uses_default_suggestion_when_none_provided(self) -> None:
        """Test that the default suggestion from ERROR_SUGGESTIONS is used when not overridden."""
        result = create_tool_error(
            code=ErrorCode.AUTH_FAILED,
            message="Authentication failed",
            tool_name="list_mrs",
        )

        assert result["suggestion"] == ERROR_SUGGESTIONS[ErrorCode.AUTH_FAILED]

    def test_custom_suggestion_overrides_default(self) -> None:
        """Test that an explicit suggestion overrides the default from ERROR_SUGGESTIONS."""
        custom = "Try regenerating your PAT with api scope"
        result = create_tool_error(
            code=ErrorCode.AUTH_FAILED,
            message="Authentication failed",
            tool_name="list_mrs",
            suggestion=custom,
        )

        assert result["suggestion"] == custom
        assert result["suggestion"] != ERROR_SUGGESTIONS[ErrorCode.AUTH_FAILED]

    def test_handles_none_optional_fields(self) -> None:
        """Test that optional fields default to None when not provided."""
        result = create_tool_error(
            code=ErrorCode.VALIDATION_ERROR,
            message="Invalid parameter",
            tool_name="create_mr",
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

    def test_returns_dict_type(self) -> None:
        """Test that return type is dict, not ToolError model."""
        result = create_tool_error(
            code=ErrorCode.API_ERROR,
            message="Server error",
            tool_name="list_issues",
        )

        assert isinstance(result, dict)
        assert not hasattr(result, "model_dump")

    def test_dict_has_all_expected_keys(self) -> None:
        """Test that returned dict contains exactly the expected keys."""
        result = create_tool_error(
            code=ErrorCode.RATE_LIMITED,
            message="Rate limited",
            tool_name="search",
        )

        expected_keys = {"code", "message", "suggestion", "context", "tool_name", "input_received"}
        assert set(result.keys()) == expected_keys

    def test_never_raises_on_valid_input(self) -> None:
        """Test that create_tool_error does not raise for any valid error code."""
        for attr, code_value in ALL_ERROR_CODES:
            result = create_tool_error(
                code=code_value,
                message=f"Error for {attr}",
                tool_name="test_tool",
            )
            assert isinstance(result, dict)

    def test_never_raises_on_unknown_code(self) -> None:
        """Test that create_tool_error does not raise for unknown error codes."""
        result = create_tool_error(
            code="COMPLETELY_FAKE_CODE",
            message="This code does not exist",
            tool_name="test_tool",
        )
        assert isinstance(result, dict)
        assert result["code"] == "COMPLETELY_FAKE_CODE"


class TestFindSimilarNames:
    """Smoke tests for find_similar_names re-export (core has comprehensive tests)."""

    def test_exact_match_returned(self) -> None:
        """Test that an exact match is included in results."""
        result = find_similar_names("my-project", ["my-project", "other-proj", "sample"])
        assert "my-project" in result

    def test_close_typo_found(self) -> None:
        """Test that a close misspelling is found among candidates."""
        result = find_similar_names("my-proejct", ["my-project", "other-proj", "sample"])
        assert "my-project" in result

    def test_empty_candidates_returns_empty(self) -> None:
        """Test that empty candidate list returns empty results."""
        result = find_similar_names("my-project", [])
        assert result == []

    def test_case_insensitive_matching(self) -> None:
        """Test that matching is case-insensitive."""
        result = find_similar_names("MY-PROJECT", ["my-project", "other-proj"])
        assert "my-project" in result

    def test_fuzzy_match_for_project_name_typo(self) -> None:
        """Test fuzzy matching provides relevant suggestions for project name typos."""
        projects = ["gitlab-ce", "gitlab-ee", "gitlab-runner", "pages"]
        result = find_similar_names("gitlab-c", projects)
        assert "gitlab-ce" in result

    def test_fuzzy_match_for_branch_name_typo(self) -> None:
        """Test fuzzy matching provides relevant suggestions for branch name typos."""
        branches = ["main", "develop", "feature/auth", "feature/api"]
        result = find_similar_names("mian", branches)
        assert "main" in result


class TestSuggestProjectNames:
    """Tests for suggest_project_names helper function."""

    def test_returns_suggestion_with_similar_names(self) -> None:
        """Test that similar project names are included in the suggestion."""
        result = suggest_project_names("my-proejct", ["my-project", "other-proj"])
        assert "Did you mean" in result
        assert "'my-project'" in result
        assert "search" in result

    def test_returns_default_when_no_similar_names(self) -> None:
        """Test that the default suggestion is used when no similar names are found."""
        result = suggest_project_names("zzzzzzzzz", ["alpha", "beta"])
        assert result == ERROR_SUGGESTIONS[ErrorCode.PROJECT_NOT_FOUND]

    def test_returns_default_on_empty_candidates(self) -> None:
        """Test that the default suggestion is used with an empty candidates list."""
        result = suggest_project_names("my-project", [])
        assert result == ERROR_SUGGESTIONS[ErrorCode.PROJECT_NOT_FOUND]

    def test_returns_default_on_exception(self) -> None:
        """Test that exceptions in find_similar_names are caught gracefully."""
        with patch("mamba_mcp_gitlab.errors.find_similar_names", side_effect=RuntimeError("boom")):
            result = suggest_project_names("test", ["a", "b"])
        assert result == ERROR_SUGGESTIONS[ErrorCode.PROJECT_NOT_FOUND]


class TestSuggestBranchNames:
    """Tests for suggest_branch_names helper function."""

    def test_returns_suggestion_with_similar_names(self) -> None:
        """Test that similar branch names are included in the suggestion."""
        result = suggest_branch_names("mian", ["main", "develop"])
        assert "Did you mean" in result
        assert "'main'" in result

    def test_returns_default_when_no_similar_names(self) -> None:
        """Test that the default suggestion is used when no similar names are found."""
        result = suggest_branch_names("zzzzzzzzz", ["main", "develop"])
        assert result == ERROR_SUGGESTIONS[ErrorCode.BRANCH_NOT_FOUND]

    def test_returns_default_on_empty_candidates(self) -> None:
        """Test that the default suggestion is used with an empty candidates list."""
        result = suggest_branch_names("main", [])
        assert result == ERROR_SUGGESTIONS[ErrorCode.BRANCH_NOT_FOUND]

    def test_returns_default_on_exception(self) -> None:
        """Test that exceptions in find_similar_names are caught gracefully."""
        with patch("mamba_mcp_gitlab.errors.find_similar_names", side_effect=RuntimeError("boom")):
            result = suggest_branch_names("test", ["a", "b"])
        assert result == ERROR_SUGGESTIONS[ErrorCode.BRANCH_NOT_FOUND]


class TestBuildErrorContext:
    """Tests for build_error_context helper function."""

    def test_all_fields_populated(self) -> None:
        """Test that all fields are included when provided."""
        ctx = build_error_context(
            elapsed_ms=123.456,
            endpoint="/projects/1/merge_requests",
            status_code=404,
            extra={"project_id": 1},
        )
        assert ctx["elapsed_ms"] == 123.46
        assert ctx["endpoint"] == "/projects/1/merge_requests"
        assert ctx["status_code"] == 404
        assert ctx["project_id"] == 1

    def test_empty_when_no_args(self) -> None:
        """Test that an empty dict is returned when no args are provided."""
        ctx = build_error_context()
        assert ctx == {}

    def test_omits_none_values(self) -> None:
        """Test that None values are omitted from the context."""
        ctx = build_error_context(elapsed_ms=50.0)
        assert "elapsed_ms" in ctx
        assert "endpoint" not in ctx
        assert "status_code" not in ctx

    def test_rounds_elapsed_ms(self) -> None:
        """Test that elapsed_ms is rounded to 2 decimal places."""
        ctx = build_error_context(elapsed_ms=123.45678)
        assert ctx["elapsed_ms"] == 123.46

    def test_extra_merges_into_context(self) -> None:
        """Test that extra dict entries are merged into the context."""
        ctx = build_error_context(extra={"key1": "val1", "key2": "val2"})
        assert ctx["key1"] == "val1"
        assert ctx["key2"] == "val2"

    def test_extra_none_is_ignored(self) -> None:
        """Test that extra=None does not add entries."""
        ctx = build_error_context(elapsed_ms=10.0, extra=None)
        assert ctx == {"elapsed_ms": 10.0}

    def test_extra_empty_dict_is_ignored(self) -> None:
        """Test that an empty extra dict does not add entries."""
        ctx = build_error_context(elapsed_ms=10.0, extra={})
        assert ctx == {"elapsed_ms": 10.0}


class TestClampPagination:
    """Tests for clamp_pagination helper function."""

    def test_defaults_when_none(self) -> None:
        """Test that defaults are applied when both parameters are None."""
        page, per_page = clamp_pagination()
        assert page == 1
        assert per_page == PAGINATION_DEFAULT_PER_PAGE

    def test_valid_values_pass_through(self) -> None:
        """Test that valid values are returned as-is."""
        page, per_page = clamp_pagination(page=3, per_page=50)
        assert page == 3
        assert per_page == 50

    def test_negative_page_clamped_to_one(self) -> None:
        """Test that negative page numbers are clamped to 1."""
        page, per_page = clamp_pagination(page=-5)
        assert page == 1

    def test_zero_page_clamped_to_one(self) -> None:
        """Test that page=0 is clamped to 1."""
        page, per_page = clamp_pagination(page=0)
        assert page == 1

    def test_per_page_below_minimum_clamped(self) -> None:
        """Test that per_page below minimum is clamped to 1."""
        _, per_page = clamp_pagination(per_page=0)
        assert per_page == PAGINATION_MIN_PER_PAGE

    def test_per_page_above_maximum_clamped(self) -> None:
        """Test that per_page above maximum is clamped to 100."""
        _, per_page = clamp_pagination(per_page=500)
        assert per_page == PAGINATION_MAX_PER_PAGE

    def test_per_page_at_maximum_boundary(self) -> None:
        """Test that per_page=100 is accepted (boundary)."""
        _, per_page = clamp_pagination(per_page=100)
        assert per_page == 100

    def test_per_page_at_minimum_boundary(self) -> None:
        """Test that per_page=1 is accepted (boundary)."""
        _, per_page = clamp_pagination(per_page=1)
        assert per_page == 1

    def test_negative_per_page_clamped(self) -> None:
        """Test that negative per_page is clamped to minimum."""
        _, per_page = clamp_pagination(per_page=-10)
        assert per_page == PAGINATION_MIN_PER_PAGE


class TestPaginationConstants:
    """Tests for pagination constant values."""

    def test_default_per_page(self) -> None:
        """Test that the default per_page is 20."""
        assert PAGINATION_DEFAULT_PER_PAGE == 20

    def test_min_per_page(self) -> None:
        """Test that the minimum per_page is 1."""
        assert PAGINATION_MIN_PER_PAGE == 1

    def test_max_per_page(self) -> None:
        """Test that the maximum per_page is 100."""
        assert PAGINATION_MAX_PER_PAGE == 100
