"""Tests for the error framework (error codes, suggestions, responses, exceptions)."""

import pytest
from mamba_mcp_fs.errors import (
    ERROR_SUGGESTIONS,
    BackendError,
    BackendNotConfiguredError,
    ContentDecodeError,
    ErrorCode,
    FileTooLargeError,
    FSError,
    InvalidOperationError,
    PathNotFoundError,
    PathOutsideSandboxError,
    PermissionDeniedError,
    RateLimitedError,
    SymlinkBlockedError,
    create_error_response,
    create_tool_error,
    find_similar_names,
)

# All 10 error codes and their expected constant values
ALL_ERROR_CODES = [
    ("PATH_NOT_FOUND", ErrorCode.PATH_NOT_FOUND),
    ("PATH_OUTSIDE_SANDBOX", ErrorCode.PATH_OUTSIDE_SANDBOX),
    ("PERMISSION_DENIED", ErrorCode.PERMISSION_DENIED),
    ("FILE_TOO_LARGE", ErrorCode.FILE_TOO_LARGE),
    ("BACKEND_NOT_CONFIGURED", ErrorCode.BACKEND_NOT_CONFIGURED),
    ("BACKEND_ERROR", ErrorCode.BACKEND_ERROR),
    ("INVALID_OPERATION", ErrorCode.INVALID_OPERATION),
    ("RATE_LIMITED", ErrorCode.RATE_LIMITED),
    ("SYMLINK_BLOCKED", ErrorCode.SYMLINK_BLOCKED),
    ("CONTENT_DECODE_ERROR", ErrorCode.CONTENT_DECODE_ERROR),
]

# Mapping from error code to its expected exception subclass
EXCEPTION_MAP: list[tuple[str, type[FSError]]] = [
    (ErrorCode.PATH_NOT_FOUND, PathNotFoundError),
    (ErrorCode.PATH_OUTSIDE_SANDBOX, PathOutsideSandboxError),
    (ErrorCode.PERMISSION_DENIED, PermissionDeniedError),
    (ErrorCode.FILE_TOO_LARGE, FileTooLargeError),
    (ErrorCode.BACKEND_NOT_CONFIGURED, BackendNotConfiguredError),
    (ErrorCode.BACKEND_ERROR, BackendError),
    (ErrorCode.INVALID_OPERATION, InvalidOperationError),
    (ErrorCode.RATE_LIMITED, RateLimitedError),
    (ErrorCode.SYMLINK_BLOCKED, SymlinkBlockedError),
    (ErrorCode.CONTENT_DECODE_ERROR, ContentDecodeError),
]


class TestErrorCodes:
    """Tests for ErrorCode constants."""

    @pytest.mark.parametrize("expected_value,code", ALL_ERROR_CODES)
    def test_error_code_value(self, expected_value: str, code: str) -> None:
        """Each error code constant matches its string name."""
        assert code == expected_value

    def test_all_10_error_codes_defined(self) -> None:
        """Exactly 10 error codes are defined on the ErrorCode class."""
        codes = [
            attr
            for attr in dir(ErrorCode)
            if not attr.startswith("_") and isinstance(getattr(ErrorCode, attr), str)
        ]
        assert len(codes) == 10


class TestErrorSuggestions:
    """Tests for ERROR_SUGGESTIONS mapping."""

    @pytest.mark.parametrize("expected_value,code", ALL_ERROR_CODES)
    def test_each_code_has_suggestion(self, expected_value: str, code: str) -> None:
        """Every error code has a corresponding suggestion."""
        assert code in ERROR_SUGGESTIONS
        assert isinstance(ERROR_SUGGESTIONS[code], str)
        assert len(ERROR_SUGGESTIONS[code]) > 0

    def test_suggestions_count_matches_codes(self) -> None:
        """The suggestion mapping has exactly 10 entries."""
        assert len(ERROR_SUGGESTIONS) == 10

    def test_specific_suggestions(self) -> None:
        """Spot-check a few suggestion values for correctness."""
        assert "list_directory" in ERROR_SUGGESTIONS[ErrorCode.PATH_NOT_FOUND]
        assert "base path" in ERROR_SUGGESTIONS[ErrorCode.PATH_OUTSIDE_SANDBOX]
        assert "read-only" in ERROR_SUGGESTIONS[ErrorCode.PERMISSION_DENIED]
        assert "offset/limit" in ERROR_SUGGESTIONS[ErrorCode.FILE_TOO_LARGE]
        assert "force_base64" in ERROR_SUGGESTIONS[ErrorCode.CONTENT_DECODE_ERROR]
        assert "follow_symlinks" in ERROR_SUGGESTIONS[ErrorCode.SYMLINK_BLOCKED]


class TestCreateErrorResponse:
    """Tests for the create_error_response helper function."""

    @pytest.mark.parametrize("expected_value,code", ALL_ERROR_CODES)
    def test_produces_correct_structure_for_each_code(self, expected_value: str, code: str) -> None:
        """create_error_response returns the expected keys for every known code."""
        result = create_error_response(code, f"Test message for {code}")

        assert result["error_code"] == code
        assert result["message"] == f"Test message for {code}"
        assert result["suggestion"] == ERROR_SUGGESTIONS[code]
        assert "details" not in result

    def test_with_details(self) -> None:
        """Details dict is included in the response when provided."""
        details = {"path": "/foo/bar", "size": 1024}
        result = create_error_response(ErrorCode.FILE_TOO_LARGE, "File too large", details=details)

        assert result["details"] == details
        assert result["error_code"] == ErrorCode.FILE_TOO_LARGE
        assert result["message"] == "File too large"

    def test_without_details(self) -> None:
        """Details key is absent when details is None."""
        result = create_error_response(ErrorCode.PATH_NOT_FOUND, "Not found")
        assert "details" not in result

    def test_details_none_explicit(self) -> None:
        """Explicitly passing details=None behaves the same as omitting it."""
        result = create_error_response(ErrorCode.PATH_NOT_FOUND, "Not found", details=None)
        assert "details" not in result

    def test_unknown_error_code_gets_generic_suggestion(self) -> None:
        """An unrecognized error code gets a generic fallback suggestion."""
        result = create_error_response("TOTALLY_UNKNOWN_CODE", "Something went wrong")

        assert result["error_code"] == "TOTALLY_UNKNOWN_CODE"
        assert result["message"] == "Something went wrong"
        assert result["suggestion"] == "An unexpected error occurred"
        assert "details" not in result

    def test_empty_details_dict_included(self) -> None:
        """An empty details dict is still included (not suppressed)."""
        result = create_error_response(ErrorCode.BACKEND_ERROR, "Err", details={})
        assert result["details"] == {}

    def test_response_is_plain_dict(self) -> None:
        """The response is a plain dict, not a Pydantic model or special type."""
        result = create_error_response(ErrorCode.RATE_LIMITED, "Too fast")
        assert type(result) is dict


class TestFSError:
    """Tests for the FSError base exception class."""

    def test_base_exception_code(self) -> None:
        """FSError base class has UNKNOWN_ERROR as its code."""
        err = FSError("something broke")
        assert err.code == "UNKNOWN_ERROR"

    def test_base_exception_message(self) -> None:
        """FSError stores the message attribute."""
        err = FSError("test message")
        assert err.message == "test message"

    def test_base_exception_str(self) -> None:
        """FSError string representation matches the message."""
        err = FSError("readable message")
        assert str(err) == "readable message"

    def test_base_exception_is_exception(self) -> None:
        """FSError is a subclass of Exception."""
        assert issubclass(FSError, Exception)

    def test_can_be_raised_and_caught(self) -> None:
        """FSError can be raised and caught normally."""
        with pytest.raises(FSError) as exc_info:
            raise FSError("test raise")
        assert exc_info.value.message == "test raise"
        assert exc_info.value.code == "UNKNOWN_ERROR"


class TestExceptionSubclasses:
    """Tests for all 10 custom exception subclasses."""

    @pytest.mark.parametrize("code,exc_class", EXCEPTION_MAP)
    def test_subclass_code(self, code: str, exc_class: type[FSError]) -> None:
        """Each exception subclass has the correct error code."""
        err = exc_class("test")
        assert err.code == code

    @pytest.mark.parametrize("code,exc_class", EXCEPTION_MAP)
    def test_subclass_message(self, code: str, exc_class: type[FSError]) -> None:
        """Each exception subclass stores its message."""
        err = exc_class("my message")
        assert err.message == "my message"

    @pytest.mark.parametrize("code,exc_class", EXCEPTION_MAP)
    def test_subclass_inherits_from_fserror(self, code: str, exc_class: type[FSError]) -> None:
        """Each exception subclass inherits from FSError."""
        assert issubclass(exc_class, FSError)
        assert issubclass(exc_class, Exception)

    @pytest.mark.parametrize("code,exc_class", EXCEPTION_MAP)
    def test_subclass_catchable_as_fserror(self, code: str, exc_class: type[FSError]) -> None:
        """Each exception subclass can be caught as FSError."""
        with pytest.raises(FSError):
            raise exc_class("catch me")

    @pytest.mark.parametrize("code,exc_class", EXCEPTION_MAP)
    def test_subclass_str(self, code: str, exc_class: type[FSError]) -> None:
        """Each exception subclass string representation matches message."""
        err = exc_class("string repr test")
        assert str(err) == "string repr test"

    def test_all_10_exception_classes_exist(self) -> None:
        """All 10 expected exception subclasses are defined."""
        assert len(EXCEPTION_MAP) == 10


class TestErrorFrameworkRobustness:
    """Tests that the error framework itself never raises unexpected exceptions."""

    def test_create_error_response_with_empty_message(self) -> None:
        """Empty message string does not cause an error."""
        result = create_error_response(ErrorCode.PATH_NOT_FOUND, "")
        assert result["message"] == ""
        assert result["error_code"] == ErrorCode.PATH_NOT_FOUND

    def test_create_error_response_with_special_characters(self) -> None:
        """Special characters in message and details do not cause errors."""
        details = {"path": "/foo/bar/../../../etc/passwd", "unicode": "\u2603"}
        result = create_error_response(
            ErrorCode.PATH_OUTSIDE_SANDBOX,
            "Path traversal attempt: ../../../etc/passwd",
            details=details,
        )
        assert result["error_code"] == ErrorCode.PATH_OUTSIDE_SANDBOX
        assert "details" in result

    def test_exception_with_empty_message(self) -> None:
        """Exception with empty message does not cause problems."""
        err = PathNotFoundError("")
        assert err.message == ""
        assert err.code == ErrorCode.PATH_NOT_FOUND
        assert str(err) == ""

    def test_exception_with_long_message(self) -> None:
        """Exception with very long message is handled correctly."""
        long_msg = "x" * 10000
        err = FileTooLargeError(long_msg)
        assert err.message == long_msg
        assert len(str(err)) == 10000


class TestCreateToolError:
    """Tests for the core-aligned create_tool_error function."""

    def test_returns_dict(self) -> None:
        """create_tool_error returns a plain dict for backward compatibility."""
        result = create_tool_error(
            code=ErrorCode.PATH_NOT_FOUND,
            message="File not found",
            tool_name="read_file",
        )
        assert type(result) is dict

    def test_uses_core_tool_error_fields(self) -> None:
        """Result contains all core ToolError fields."""
        result = create_tool_error(
            code=ErrorCode.BACKEND_ERROR,
            message="Connection failed",
            tool_name="list_directory",
            context={"path": "/data"},
            input_received={"path": "/data", "backend": "s3"},
        )
        assert result["code"] == ErrorCode.BACKEND_ERROR
        assert result["message"] == "Connection failed"
        assert result["tool_name"] == "list_directory"
        assert result["context"] == {"path": "/data"}
        assert result["input_received"] == {"path": "/data", "backend": "s3"}

    def test_injects_fs_error_suggestions(self) -> None:
        """FS ERROR_SUGGESTIONS map is used for suggestion lookup."""
        result = create_tool_error(
            code=ErrorCode.FILE_TOO_LARGE,
            message="Too big",
            tool_name="read_file",
        )
        assert result["suggestion"] == ERROR_SUGGESTIONS[ErrorCode.FILE_TOO_LARGE]

    def test_explicit_suggestion_overrides_map(self) -> None:
        """An explicit suggestion parameter overrides the ERROR_SUGGESTIONS lookup."""
        result = create_tool_error(
            code=ErrorCode.PATH_NOT_FOUND,
            message="Not found",
            tool_name="read_file",
            suggestion="Custom suggestion here",
        )
        assert result["suggestion"] == "Custom suggestion here"

    def test_unknown_code_returns_none_suggestion(self) -> None:
        """An unrecognized error code gets None suggestion (no generic fallback)."""
        result = create_tool_error(
            code="TOTALLY_UNKNOWN",
            message="Unknown error",
            tool_name="test_tool",
        )
        assert result["suggestion"] is None

    @pytest.mark.parametrize("expected_value,code", ALL_ERROR_CODES)
    def test_all_codes_produce_valid_response(self, expected_value: str, code: str) -> None:
        """create_tool_error produces valid output for every known error code."""
        result = create_tool_error(
            code=code,
            message=f"Test for {code}",
            tool_name="test_tool",
        )
        assert result["code"] == code
        assert result["message"] == f"Test for {code}"
        assert result["tool_name"] == "test_tool"
        assert result["suggestion"] == ERROR_SUGGESTIONS[code]

    def test_context_defaults_to_none(self) -> None:
        """Context is None when not provided."""
        result = create_tool_error(
            code=ErrorCode.RATE_LIMITED,
            message="Too fast",
            tool_name="write_file",
        )
        assert result["context"] is None

    def test_input_received_defaults_to_none(self) -> None:
        """Input received is None when not provided."""
        result = create_tool_error(
            code=ErrorCode.RATE_LIMITED,
            message="Too fast",
            tool_name="write_file",
        )
        assert result["input_received"] is None


class TestFindSimilarNames:
    """Tests for find_similar_names re-exported from core."""

    def test_finds_close_match(self) -> None:
        """find_similar_names returns close matches."""
        candidates = ["local", "s3"]
        result = find_similar_names("lcal", candidates)
        assert "local" in result

    def test_no_match_for_unrelated_input(self) -> None:
        """find_similar_names returns empty for unrelated strings."""
        candidates = ["local", "s3"]
        result = find_similar_names("zzzzzzzzz", candidates)
        assert result == []

    def test_empty_candidates(self) -> None:
        """find_similar_names handles empty candidate list."""
        result = find_similar_names("test", [])
        assert result == []

    def test_exact_match_included(self) -> None:
        """find_similar_names includes exact matches."""
        candidates = ["report.csv", "output.txt", "data.json"]
        result = find_similar_names("report.csv", candidates)
        assert "report.csv" in result


class TestBackendFuzzyMatching:
    """Tests for fuzzy matching integration in BackendManager."""

    def test_unknown_backend_suggests_similar(self) -> None:
        """Typo in backend name produces 'Did you mean?' suggestion."""
        from unittest.mock import MagicMock

        from mamba_mcp_fs.backends.base import BackendManager
        from mamba_mcp_fs.errors import BackendNotConfiguredError

        settings = MagicMock()
        security = MagicMock()
        manager = BackendManager(settings, security)

        with pytest.raises(BackendNotConfiguredError, match="Did you mean") as exc_info:
            manager.get_backend("/test/path", backend="locl")
        assert "local" in str(exc_info.value)

    def test_unknown_backend_no_suggestion_for_unrelated(self) -> None:
        """Completely unrelated backend name does not suggest alternatives."""
        from unittest.mock import MagicMock

        from mamba_mcp_fs.backends.base import BackendManager
        from mamba_mcp_fs.errors import BackendNotConfiguredError

        settings = MagicMock()
        security = MagicMock()
        manager = BackendManager(settings, security)

        with pytest.raises(BackendNotConfiguredError) as exc_info:
            manager.get_backend("/test/path", backend="zzzzzzzzz")
        assert "Did you mean" not in str(exc_info.value)

    def test_disabled_backend_shows_enabled_alternatives(self) -> None:
        """Disabled backend error message lists enabled backends."""
        from unittest.mock import MagicMock

        from mamba_mcp_fs.backends.base import BackendManager
        from mamba_mcp_fs.errors import BackendNotConfiguredError

        settings = MagicMock()
        settings.local.enabled = True
        settings.s3.enabled = False
        security = MagicMock()
        manager = BackendManager(settings, security)

        with pytest.raises(BackendNotConfiguredError, match="Enabled backends") as exc_info:
            manager.get_backend("s3://bucket/key", backend="s3")
        assert "local" in str(exc_info.value)
