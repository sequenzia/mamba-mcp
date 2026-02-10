"""Tests for fuzzy suggestion helpers, pagination clamping, and enhanced error context.

Covers Spec Section 9.3 error UX improvements: project name fuzzy suggestions,
branch name fuzzy suggestions, error context enrichment, and pagination clamping.
"""

from __future__ import annotations

from unittest.mock import patch

from mamba_mcp_gitlab.errors import (
    ERROR_SUGGESTIONS,
    PAGINATION_DEFAULT_PER_PAGE,
    PAGINATION_MAX_PER_PAGE,
    PAGINATION_MIN_PER_PAGE,
    ErrorCode,
    build_error_context,
    clamp_pagination,
    create_tool_error,
    suggest_branch_names,
    suggest_project_names,
)

# ---------------------------------------------------------------------------
# Project name fuzzy suggestions
# ---------------------------------------------------------------------------


class TestSuggestProjectNames:
    """Tests for suggest_project_names helper."""

    def test_exact_match_included(self) -> None:
        """Test that an exact project name match yields a suggestion."""
        result = suggest_project_names("my-project", ["my-project", "other-proj"])
        assert "my-project" in result
        assert "Did you mean" in result

    def test_close_typo_found(self) -> None:
        """Test that a close typo produces a suggestion with the correct name."""
        result = suggest_project_names("my-proejct", ["my-project", "other-project", "sample"])
        assert "my-project" in result
        assert "Did you mean" in result

    def test_multiple_similar_names_listed(self) -> None:
        """Test that multiple similar project names appear in suggestion."""
        result = suggest_project_names(
            "gitlab-c", ["gitlab-ce", "gitlab-ci", "gitlab-ee", "unrelated"]
        )
        assert "Did you mean" in result
        assert "gitlab-ce" in result

    def test_no_similar_names_returns_default(self) -> None:
        """Test that no matches returns the default PROJECT_NOT_FOUND suggestion."""
        result = suggest_project_names("zzz", ["alpha", "beta", "gamma"])
        assert result == ERROR_SUGGESTIONS[ErrorCode.PROJECT_NOT_FOUND]

    def test_empty_candidates_returns_default(self) -> None:
        """Test that an empty candidate list returns the default suggestion."""
        result = suggest_project_names("my-project", [])
        assert result == ERROR_SUGGESTIONS[ErrorCode.PROJECT_NOT_FOUND]

    def test_case_insensitive_matching(self) -> None:
        """Test that project name matching is case-insensitive."""
        result = suggest_project_names("MY-PROJECT", ["my-project", "other-proj"])
        assert "my-project" in result
        assert "Did you mean" in result

    def test_suggestion_includes_search_tool_reference(self) -> None:
        """Test that the suggestion references the search tool for discovery."""
        result = suggest_project_names("my-proejct", ["my-project"])
        assert "search" in result

    def test_short_name_two_chars(self) -> None:
        """Test fuzzy matching with a very short name (2 chars)."""
        result = suggest_project_names("ab", ["ac", "ad", "xy", "long-project-name"])
        # With 2-char name, threshold is max(2, min(1, 5))=2, so close matches may appear
        assert isinstance(result, str)
        assert len(result) > 0

    def test_short_name_one_char(self) -> None:
        """Test fuzzy matching with a single character name."""
        result = suggest_project_names("a", ["b", "c", "abc", "def"])
        assert isinstance(result, str)
        assert len(result) > 0

    def test_single_candidate_match(self) -> None:
        """Test suggestion with exactly one matching candidate."""
        result = suggest_project_names("my-proejct", ["my-project"])
        assert "my-project" in result
        assert "Did you mean" in result

    def test_defensively_handles_exception(self) -> None:
        """Test that fuzzy search exceptions are caught and default suggestion returned."""
        with patch(
            "mamba_mcp_gitlab.errors.find_similar_names",
            side_effect=RuntimeError("unexpected"),
        ):
            result = suggest_project_names("my-project", ["my-project"])
        assert result == ERROR_SUGGESTIONS[ErrorCode.PROJECT_NOT_FOUND]

    def test_suggestion_format_with_quotes(self) -> None:
        """Test that similar names are quoted in the suggestion string."""
        result = suggest_project_names("my-proejct", ["my-project"])
        assert "'my-project'" in result


# ---------------------------------------------------------------------------
# Branch name fuzzy suggestions
# ---------------------------------------------------------------------------


class TestSuggestBranchNames:
    """Tests for suggest_branch_names helper."""

    def test_exact_match_included(self) -> None:
        """Test that an exact branch name match yields a suggestion."""
        result = suggest_branch_names("main", ["main", "develop", "staging"])
        assert "main" in result
        assert "Did you mean" in result

    def test_close_typo_found(self) -> None:
        """Test that a branch name typo produces a suggestion."""
        result = suggest_branch_names("mian", ["main", "develop", "feature/auth"])
        assert "main" in result
        assert "Did you mean" in result

    def test_feature_branch_typo(self) -> None:
        """Test fuzzy matching on feature branch names."""
        branches = ["feature/auth", "feature/api", "feature/search", "main"]
        result = suggest_branch_names("feature/atuh", branches)
        assert "feature/auth" in result

    def test_no_similar_names_returns_default(self) -> None:
        """Test that no matches returns the default BRANCH_NOT_FOUND suggestion."""
        result = suggest_branch_names("zzzzzzz-branch", ["main", "develop"])
        assert result == ERROR_SUGGESTIONS[ErrorCode.BRANCH_NOT_FOUND]

    def test_empty_candidates_returns_default(self) -> None:
        """Test that an empty candidate list returns the default suggestion."""
        result = suggest_branch_names("main", [])
        assert result == ERROR_SUGGESTIONS[ErrorCode.BRANCH_NOT_FOUND]

    def test_case_insensitive_matching(self) -> None:
        """Test that branch name matching is case-insensitive."""
        result = suggest_branch_names("MAIN", ["main", "develop"])
        assert "main" in result
        assert "Did you mean" in result

    def test_short_branch_name(self) -> None:
        """Test fuzzy matching with a short branch name (< 3 chars)."""
        result = suggest_branch_names("mn", ["main", "dev", "staging"])
        assert isinstance(result, str)
        assert len(result) > 0

    def test_defensively_handles_exception(self) -> None:
        """Test that fuzzy search exceptions are caught and default suggestion returned."""
        with patch(
            "mamba_mcp_gitlab.errors.find_similar_names",
            side_effect=ValueError("bad input"),
        ):
            result = suggest_branch_names("main", ["main"])
        assert result == ERROR_SUGGESTIONS[ErrorCode.BRANCH_NOT_FOUND]

    def test_suggestion_format_with_quotes(self) -> None:
        """Test that similar branch names are quoted in the suggestion string."""
        result = suggest_branch_names("mian", ["main"])
        assert "'main'" in result

    def test_multiple_similar_branches(self) -> None:
        """Test that multiple similar branches appear in the suggestion."""
        branches = ["release/1.0", "release/1.1", "release/2.0", "main"]
        result = suggest_branch_names("release/1.0", branches)
        assert "Did you mean" in result
        assert "release/1.0" in result


# ---------------------------------------------------------------------------
# Enhanced error context builder
# ---------------------------------------------------------------------------


class TestBuildErrorContext:
    """Tests for build_error_context helper."""

    def test_all_fields_present(self) -> None:
        """Test that all provided fields appear in the context dict."""
        ctx = build_error_context(
            elapsed_ms=123.456,
            endpoint="/projects/1/merge_requests",
            status_code=404,
        )
        assert ctx["elapsed_ms"] == 123.46
        assert ctx["endpoint"] == "/projects/1/merge_requests"
        assert ctx["status_code"] == 404

    def test_elapsed_ms_rounded(self) -> None:
        """Test that elapsed_ms is rounded to 2 decimal places."""
        ctx = build_error_context(elapsed_ms=99.9999)
        assert ctx["elapsed_ms"] == 100.0

    def test_none_fields_excluded(self) -> None:
        """Test that None values are not included in the context dict."""
        ctx = build_error_context(elapsed_ms=50.0)
        assert "elapsed_ms" in ctx
        assert "endpoint" not in ctx
        assert "status_code" not in ctx

    def test_empty_context_when_all_none(self) -> None:
        """Test that an empty dict is returned when no fields are provided."""
        ctx = build_error_context()
        assert ctx == {}

    def test_extra_fields_merged(self) -> None:
        """Test that extra dict entries are merged into the context."""
        ctx = build_error_context(
            elapsed_ms=10.0,
            extra={"project_id": 123, "resource": "merge_requests"},
        )
        assert ctx["elapsed_ms"] == 10.0
        assert ctx["project_id"] == 123
        assert ctx["resource"] == "merge_requests"

    def test_extra_overrides_nothing_when_empty(self) -> None:
        """Test that an empty extra dict doesn't affect the result."""
        ctx = build_error_context(elapsed_ms=10.0, extra={})
        assert ctx == {"elapsed_ms": 10.0}

    def test_only_endpoint(self) -> None:
        """Test context with only endpoint specified."""
        ctx = build_error_context(endpoint="/projects/1/issues")
        assert ctx == {"endpoint": "/projects/1/issues"}

    def test_only_status_code(self) -> None:
        """Test context with only status code specified."""
        ctx = build_error_context(status_code=500)
        assert ctx == {"status_code": 500}

    def test_elapsed_ms_zero(self) -> None:
        """Test that zero elapsed_ms is included (not treated as falsy)."""
        ctx = build_error_context(elapsed_ms=0.0)
        assert ctx["elapsed_ms"] == 0.0

    def test_status_code_zero(self) -> None:
        """Test that zero status_code is included (not treated as falsy)."""
        ctx = build_error_context(status_code=0)
        assert ctx["status_code"] == 0


# ---------------------------------------------------------------------------
# Integration: error context flows through create_tool_error
# ---------------------------------------------------------------------------


class TestErrorContextIntegration:
    """Integration tests for enhanced error context flowing through create_tool_error."""

    def test_error_with_timing_context(self) -> None:
        """Test that error responses include request timing in context."""
        ctx = build_error_context(elapsed_ms=150.5, endpoint="/projects/99/issues")
        result = create_tool_error(
            code=ErrorCode.ISSUE_NOT_FOUND,
            message="Issue #42 not found",
            tool_name="get_issue",
            context=ctx,
        )
        assert result["context"]["elapsed_ms"] == 150.5
        assert result["context"]["endpoint"] == "/projects/99/issues"

    def test_error_with_status_code_context(self) -> None:
        """Test that error responses include HTTP status code in context."""
        ctx = build_error_context(status_code=404, endpoint="/projects/1/merge_requests/999")
        result = create_tool_error(
            code=ErrorCode.MERGE_REQUEST_NOT_FOUND,
            message="MR !999 not found",
            tool_name="get_mr",
            context=ctx,
        )
        assert result["context"]["status_code"] == 404
        assert result["context"]["endpoint"] == "/projects/1/merge_requests/999"

    def test_error_with_fuzzy_project_suggestion(self) -> None:
        """Test that project fuzzy suggestions integrate with create_tool_error."""
        suggestion = suggest_project_names("my-proejct", ["my-project", "other-project"])
        ctx = build_error_context(elapsed_ms=80.0, status_code=404)
        result = create_tool_error(
            code=ErrorCode.PROJECT_NOT_FOUND,
            message="Project 'my-proejct' not found",
            tool_name="list_mrs",
            input_received={"project_id": "my-proejct"},
            context=ctx,
            suggestion=suggestion,
        )
        assert "my-project" in result["suggestion"]
        assert result["context"]["elapsed_ms"] == 80.0

    def test_error_with_fuzzy_branch_suggestion(self) -> None:
        """Test that branch fuzzy suggestions integrate with create_tool_error."""
        suggestion = suggest_branch_names("mian", ["main", "develop"])
        ctx = build_error_context(elapsed_ms=55.0, status_code=404)
        result = create_tool_error(
            code=ErrorCode.BRANCH_NOT_FOUND,
            message="Branch 'mian' not found",
            tool_name="create_mr",
            input_received={"source_branch": "mian"},
            context=ctx,
            suggestion=suggestion,
        )
        assert "main" in result["suggestion"]
        assert result["context"]["status_code"] == 404

    def test_full_error_payload_structure(self) -> None:
        """Test complete error payload has all expected fields."""
        suggestion = suggest_project_names("gitlab-c", ["gitlab-ce", "gitlab-ee"])
        ctx = build_error_context(
            elapsed_ms=200.0,
            endpoint="/projects/gitlab-c/merge_requests",
            status_code=404,
            extra={"method": "GET"},
        )
        result = create_tool_error(
            code=ErrorCode.PROJECT_NOT_FOUND,
            message="Project 'gitlab-c' not found",
            tool_name="list_mrs",
            input_received={"project_id": "gitlab-c"},
            context=ctx,
            suggestion=suggestion,
        )
        assert set(result.keys()) == {
            "code",
            "message",
            "suggestion",
            "context",
            "tool_name",
            "input_received",
        }
        assert result["code"] == "PROJECT_NOT_FOUND"
        assert "gitlab-ce" in result["suggestion"]
        assert result["context"]["elapsed_ms"] == 200.0
        assert result["context"]["endpoint"] == "/projects/gitlab-c/merge_requests"
        assert result["context"]["status_code"] == 404
        assert result["context"]["method"] == "GET"


# ---------------------------------------------------------------------------
# Pagination clamping
# ---------------------------------------------------------------------------


class TestClampPagination:
    """Tests for clamp_pagination helper."""

    def test_defaults_when_none(self) -> None:
        """Test that default values are applied when arguments are None."""
        page, per_page = clamp_pagination()
        assert page == 1
        assert per_page == PAGINATION_DEFAULT_PER_PAGE

    def test_valid_values_unchanged(self) -> None:
        """Test that valid page and per_page values pass through unchanged."""
        page, per_page = clamp_pagination(page=3, per_page=50)
        assert page == 3
        assert per_page == 50

    def test_per_page_clamped_to_max(self) -> None:
        """Test that per_page is clamped to the maximum of 100."""
        _, per_page = clamp_pagination(per_page=200)
        assert per_page == PAGINATION_MAX_PER_PAGE

    def test_per_page_clamped_to_min(self) -> None:
        """Test that per_page is clamped to the minimum of 1."""
        _, per_page = clamp_pagination(per_page=0)
        assert per_page == PAGINATION_MIN_PER_PAGE

    def test_per_page_negative_clamped_to_min(self) -> None:
        """Test that negative per_page is clamped to 1."""
        _, per_page = clamp_pagination(per_page=-5)
        assert per_page == PAGINATION_MIN_PER_PAGE

    def test_page_zero_defaults_to_one(self) -> None:
        """Test that page=0 is corrected to 1."""
        page, _ = clamp_pagination(page=0)
        assert page == 1

    def test_page_negative_defaults_to_one(self) -> None:
        """Test that negative page is corrected to 1."""
        page, _ = clamp_pagination(page=-3)
        assert page == 1

    def test_per_page_exactly_one(self) -> None:
        """Test that per_page=1 is a valid minimum value."""
        _, per_page = clamp_pagination(per_page=1)
        assert per_page == 1

    def test_per_page_exactly_one_hundred(self) -> None:
        """Test that per_page=100 is a valid maximum value."""
        _, per_page = clamp_pagination(per_page=100)
        assert per_page == 100

    def test_page_one_is_valid(self) -> None:
        """Test that page=1 passes through unchanged."""
        page, _ = clamp_pagination(page=1)
        assert page == 1

    def test_large_page_number_unchanged(self) -> None:
        """Test that a large page number is not clamped."""
        page, _ = clamp_pagination(page=999)
        assert page == 999

    def test_per_page_none_uses_default(self) -> None:
        """Test that per_page=None uses the default of 20."""
        _, per_page = clamp_pagination(per_page=None)
        assert per_page == 20

    def test_page_none_defaults_to_one(self) -> None:
        """Test that page=None defaults to 1."""
        page, _ = clamp_pagination(page=None)
        assert page == 1


class TestPaginationConstants:
    """Tests for pagination constant values."""

    def test_default_per_page_is_twenty(self) -> None:
        """Test that the default per_page constant is 20."""
        assert PAGINATION_DEFAULT_PER_PAGE == 20

    def test_min_per_page_is_one(self) -> None:
        """Test that the minimum per_page constant is 1."""
        assert PAGINATION_MIN_PER_PAGE == 1

    def test_max_per_page_is_one_hundred(self) -> None:
        """Test that the maximum per_page constant is 100."""
        assert PAGINATION_MAX_PER_PAGE == 100

    def test_min_less_than_max(self) -> None:
        """Test that min < default < max for pagination constants."""
        assert PAGINATION_MIN_PER_PAGE < PAGINATION_DEFAULT_PER_PAGE < PAGINATION_MAX_PER_PAGE


# ---------------------------------------------------------------------------
# Defensive error handling: fuzzy search never propagates exceptions
# ---------------------------------------------------------------------------


class TestFuzzyDefensiveness:
    """Tests that fuzzy suggestion helpers never propagate exceptions."""

    def test_project_suggestion_survives_type_error(self) -> None:
        """Test that TypeError in fuzzy matching returns default suggestion."""
        with patch(
            "mamba_mcp_gitlab.errors.find_similar_names",
            side_effect=TypeError("bad type"),
        ):
            result = suggest_project_names("test", ["test"])
        assert result == ERROR_SUGGESTIONS[ErrorCode.PROJECT_NOT_FOUND]

    def test_branch_suggestion_survives_type_error(self) -> None:
        """Test that TypeError in fuzzy matching returns default suggestion."""
        with patch(
            "mamba_mcp_gitlab.errors.find_similar_names",
            side_effect=TypeError("bad type"),
        ):
            result = suggest_branch_names("test", ["test"])
        assert result == ERROR_SUGGESTIONS[ErrorCode.BRANCH_NOT_FOUND]

    def test_project_suggestion_survives_attribute_error(self) -> None:
        """Test that AttributeError in fuzzy matching returns default suggestion."""
        with patch(
            "mamba_mcp_gitlab.errors.find_similar_names",
            side_effect=AttributeError("no attr"),
        ):
            result = suggest_project_names("test", ["test"])
        assert result == ERROR_SUGGESTIONS[ErrorCode.PROJECT_NOT_FOUND]

    def test_branch_suggestion_survives_attribute_error(self) -> None:
        """Test that AttributeError in fuzzy matching returns default suggestion."""
        with patch(
            "mamba_mcp_gitlab.errors.find_similar_names",
            side_effect=AttributeError("no attr"),
        ):
            result = suggest_branch_names("test", ["test"])
        assert result == ERROR_SUGGESTIONS[ErrorCode.BRANCH_NOT_FOUND]

    def test_project_suggestion_survives_memory_error(self) -> None:
        """Test that MemoryError in fuzzy matching returns default suggestion."""
        with patch(
            "mamba_mcp_gitlab.errors.find_similar_names",
            side_effect=MemoryError("out of memory"),
        ):
            result = suggest_project_names("test", ["test"])
        assert result == ERROR_SUGGESTIONS[ErrorCode.PROJECT_NOT_FOUND]

    def test_branch_suggestion_survives_memory_error(self) -> None:
        """Test that MemoryError in fuzzy matching returns default suggestion."""
        with patch(
            "mamba_mcp_gitlab.errors.find_similar_names",
            side_effect=MemoryError("out of memory"),
        ):
            result = suggest_branch_names("test", ["test"])
        assert result == ERROR_SUGGESTIONS[ErrorCode.BRANCH_NOT_FOUND]

    def test_project_suggestion_with_none_like_input(self) -> None:
        """Test that unusual but valid inputs produce a string result."""
        # Empty string name - should not crash
        result = suggest_project_names("", ["alpha", "beta"])
        assert isinstance(result, str)

    def test_branch_suggestion_with_none_like_input(self) -> None:
        """Test that unusual but valid inputs produce a string result."""
        result = suggest_branch_names("", ["main", "develop"])
        assert isinstance(result, str)
