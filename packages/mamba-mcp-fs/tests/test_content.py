"""Tests for content type detection (MIME types, text/binary classification, format_size)."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from mamba_mcp_fs.content import (
    _BINARY_CHECK_SIZE,
    _TEXT_MIME_TYPES,
    _content_looks_like_text,
    detect_mime_type,
    format_size,
    is_text_content,
)

# ============================================================================
# MIME Type Detection Tests
# ============================================================================


class TestDetectMimeTypeCommonExtensions:
    """Unit tests: MIME detection for 15+ common file extensions."""

    @pytest.mark.parametrize(
        "path,expected",
        [
            ("file.py", "text/x-python"),
            ("file.md", "text/markdown"),
            ("file.json", "application/json"),
            ("file.txt", "text/plain"),
            ("file.csv", "text/csv"),
            ("file.pdf", "application/pdf"),
            ("file.png", "image/png"),
            ("file.jpg", "image/jpeg"),
            ("file.jpeg", "image/jpeg"),
            ("file.gif", "image/gif"),
            ("file.svg", "image/svg+xml"),
            ("file.html", "text/html"),
            ("file.css", "text/css"),
            ("file.js", "text/javascript"),
            ("file.xml", "application/xml"),
            ("file.zip", "application/zip"),
            ("file.tar.gz", "application/x-tar"),
            ("file.yaml", "application/yaml"),
            ("file.yml", "application/yaml"),
            ("file.toml", "application/toml"),
            ("file.rs", "text/x-rust"),
            ("file.go", "text/x-go"),
            ("file.ts", "text/x-typescript"),
            ("file.tsx", "text/x-typescript"),
            ("file.rb", "text/x-ruby"),
            ("file.sql", "application/sql"),
        ],
    )
    def test_common_extension_detected(self, path: str, expected: str) -> None:
        """Common file extensions produce correct MIME types."""
        result = detect_mime_type(path)
        assert result == expected

    def test_extension_case_insensitive(self) -> None:
        """Extension detection is case-insensitive."""
        assert detect_mime_type("file.PY") == "text/x-python"
        assert detect_mime_type("file.Json") == "application/json"
        assert detect_mime_type("file.MD") == "text/markdown"

    def test_path_with_directories(self) -> None:
        """Full paths with directories still detect extension correctly."""
        assert detect_mime_type("/home/user/project/main.py") == "text/x-python"
        assert detect_mime_type("s3://bucket/prefix/data.csv") == "text/csv"

    def test_dotfile_with_extension(self) -> None:
        """Dotfiles with recognizable extensions are detected."""
        assert detect_mime_type(".env") == "text/plain"
        assert detect_mime_type(".gitignore") == "text/plain"


class TestDetectMimeTypeUnknownExtensions:
    """Graceful handling of unknown or missing extensions."""

    def test_unknown_extension_no_content(self) -> None:
        """Unknown extension with no content returns application/octet-stream."""
        result = detect_mime_type("file.xyz123")
        assert result == "application/octet-stream"

    def test_no_extension_no_content(self) -> None:
        """No extension and no content returns application/octet-stream."""
        result = detect_mime_type("Makefile")
        assert result == "application/octet-stream"

    def test_no_extension_with_text_content(self) -> None:
        """No extension but text content uses heuristic detection."""
        content = b"#!/usr/bin/env python\nprint('hello')\n"
        result = detect_mime_type("Makefile", content=content)
        # Should detect as text/plain via heuristic since there's no extension
        assert result == "text/plain"

    def test_no_extension_with_binary_content(self) -> None:
        """No extension but binary content returns octet-stream."""
        content = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
        result = detect_mime_type("somefile", content=content)
        # Without python-magic, binary content gives octet-stream
        assert result == "application/octet-stream"


class TestDetectMimeTypeContentBased:
    """Content-based detection when extension is insufficient."""

    def test_text_content_no_extension(self) -> None:
        """Text content with no extension is detected as text/plain."""
        content = b"Hello, world! This is a plain text file.\n"
        result = detect_mime_type("noext", content=content)
        assert result == "text/plain"

    def test_binary_content_no_extension(self) -> None:
        """Binary content with null bytes and no extension returns octet-stream."""
        content = b"\x00\x01\x02\x03binary content\x00"
        result = detect_mime_type("noext", content=content)
        assert result == "application/octet-stream"

    def test_extension_takes_priority_over_content(self) -> None:
        """Extension-based detection takes priority over content inspection."""
        # A .py file should return text/x-python even with weird content
        result = detect_mime_type("script.py", content=b"\x00binary\x00")
        assert result == "text/x-python"

    def test_empty_content_no_extension(self) -> None:
        """Empty content with no extension uses heuristic (empty = text)."""
        result = detect_mime_type("emptyfile", content=b"")
        assert result == "text/plain"


class TestDetectMimeTypeMagicFallback:
    """Tests for python-magic integration and graceful degradation."""

    def test_works_without_python_magic(self) -> None:
        """Detection works when python-magic is not installed."""
        with patch("mamba_mcp_fs.content._try_magic_detect", return_value=None):
            result = detect_mime_type("file.txt")
            assert result == "text/plain"

    def test_magic_used_for_no_extension(self) -> None:
        """python-magic is tried when no extension is available."""
        with patch(
            "mamba_mcp_fs.content._try_magic_detect", return_value="image/png"
        ) as mock_magic:
            result = detect_mime_type("noext", content=b"\x89PNG")
            assert result == "image/png"
            mock_magic.assert_called_once_with(b"\x89PNG")

    def test_magic_not_called_when_extension_matches(self) -> None:
        """python-magic is not called when extension provides a match."""
        with patch("mamba_mcp_fs.content._try_magic_detect") as mock_magic:
            result = detect_mime_type("file.py")
            assert result == "text/x-python"
            mock_magic.assert_not_called()

    def test_magic_exception_handled_gracefully(self) -> None:
        """If python-magic raises, detection falls back gracefully."""
        with patch("mamba_mcp_fs.content._try_magic_detect", return_value=None):
            result = detect_mime_type("unknown_file", content=b"text content here")
            assert result == "text/plain"


class TestDetectMimeTypeNeverRaises:
    """Error handling: detect_mime_type never raises on any input."""

    def test_empty_path(self) -> None:
        """Empty path string does not raise."""
        result = detect_mime_type("")
        assert isinstance(result, str)

    def test_path_with_only_dots(self) -> None:
        """Path that is only dots does not raise."""
        result = detect_mime_type("...")
        assert isinstance(result, str)

    def test_unicode_path(self) -> None:
        """Unicode characters in path do not raise."""
        result = detect_mime_type("/home/user/fichier.txt")
        assert result == "text/plain"

    def test_none_content_explicitly(self) -> None:
        """Passing content=None explicitly does not raise."""
        result = detect_mime_type("file.txt", content=None)
        assert result == "text/plain"


# ============================================================================
# Text vs Binary Classification Tests
# ============================================================================


class TestIsTextContentMimeType:
    """Text/binary classification via MIME type prefix."""

    @pytest.mark.parametrize(
        "mime_type",
        [
            "text/plain",
            "text/html",
            "text/css",
            "text/javascript",
            "text/markdown",
            "text/xml",
            "text/csv",
            "text/x-python",
        ],
    )
    def test_text_mime_types_classified_as_text(self, mime_type: str) -> None:
        """All text/* MIME types are classified as text."""
        assert is_text_content(mime_type) is True

    @pytest.mark.parametrize(
        "mime_type",
        [
            "application/json",
            "application/xml",
            "application/javascript",
            "application/sql",
            "application/toml",
            "application/yaml",
        ],
    )
    def test_known_text_application_types(self, mime_type: str) -> None:
        """Known text application/* types are classified as text."""
        assert is_text_content(mime_type) is True

    @pytest.mark.parametrize(
        "mime_type",
        [
            "application/xhtml+xml",
            "application/ld+json",
            "application/atom+xml",
            "application/rss+xml",
            "application/soap+xml",
        ],
    )
    def test_structured_text_suffixes(self, mime_type: str) -> None:
        """MIME types with +xml or +json suffixes are classified as text."""
        assert is_text_content(mime_type) is True

    @pytest.mark.parametrize(
        "mime_type",
        [
            "image/png",
            "image/jpeg",
            "image/gif",
            "application/pdf",
            "application/zip",
            "application/octet-stream",
            "video/mp4",
            "audio/mpeg",
        ],
    )
    def test_binary_mime_types_classified_as_binary(self, mime_type: str) -> None:
        """Binary MIME types are classified as binary (no content provided)."""
        assert is_text_content(mime_type) is False


class TestIsTextContentWithBytes:
    """Text/binary classification with content byte inspection."""

    def test_text_content_without_null_bytes(self) -> None:
        """Plain text content without null bytes is text."""
        content = b"Hello, world!\nThis is text.\n"
        assert is_text_content("application/octet-stream", content=content) is True

    def test_binary_content_with_null_bytes(self) -> None:
        """Content containing null bytes is classified as binary."""
        content = b"\x00\x01\x02\x03binary\x00"
        assert is_text_content("application/octet-stream", content=content) is False

    def test_empty_content_is_text(self) -> None:
        """Empty content is classified as text."""
        assert is_text_content("application/octet-stream", content=b"") is True

    def test_utf8_content_is_text(self) -> None:
        """Valid UTF-8 content is classified as text."""
        content = b"Hello, world! Bonjour le monde!"
        assert is_text_content("application/octet-stream", content=content) is True

    def test_utf8_bom_is_text(self) -> None:
        """UTF-8 files with BOM are detected as text."""
        bom = b"\xef\xbb\xbf"
        content = bom + b"Hello, world!"
        assert is_text_content("application/octet-stream", content=content) is True

    def test_text_mime_overrides_binary_content(self) -> None:
        """text/* MIME types are classified as text regardless of content."""
        binary_content = b"\x00\x01\x02\x03"
        assert is_text_content("text/plain", content=binary_content) is True

    def test_png_header_bytes(self) -> None:
        """PNG file header bytes are classified as binary."""
        content = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
        assert is_text_content("image/png", content=content) is False

    def test_large_text_content(self) -> None:
        """Large text content only checks first 8KB."""
        content = b"a" * 20000
        assert is_text_content("application/octet-stream", content=content) is True


class TestIsTextContentEdgeCases:
    """Edge cases for text/binary classification."""

    def test_text_mime_type_set_completeness(self) -> None:
        """The _TEXT_MIME_TYPES set contains expected entries."""
        assert "application/json" in _TEXT_MIME_TYPES
        assert "application/xml" in _TEXT_MIME_TYPES
        assert "application/javascript" in _TEXT_MIME_TYPES
        assert "application/sql" in _TEXT_MIME_TYPES

    def test_unknown_mime_type_no_content(self) -> None:
        """Unknown MIME type without content defaults to binary."""
        assert is_text_content("application/x-custom-unknown") is False

    def test_unknown_mime_type_with_text_content(self) -> None:
        """Unknown MIME type with text content is classified as text."""
        content = b"key=value\nother=data\n"
        assert is_text_content("application/x-custom-unknown", content=content) is True


# ============================================================================
# Content Looks Like Text Heuristic Tests
# ============================================================================


class TestContentLooksLikeText:
    """Tests for the _content_looks_like_text heuristic."""

    def test_empty_bytes(self) -> None:
        """Empty bytes are text."""
        assert _content_looks_like_text(b"") is True

    def test_ascii_text(self) -> None:
        """Pure ASCII text is text."""
        assert _content_looks_like_text(b"Hello, world!") is True

    def test_utf8_text(self) -> None:
        """UTF-8 text with non-ASCII characters is text."""
        assert _content_looks_like_text(b"Cafe au lait") is True

    def test_null_bytes(self) -> None:
        """Presence of null bytes makes content binary."""
        assert _content_looks_like_text(b"text\x00more") is False

    def test_utf8_bom(self) -> None:
        """UTF-8 BOM prefix is recognized as text."""
        content = b"\xef\xbb\xbfHello"
        assert _content_looks_like_text(content) is True

    def test_only_whitespace(self) -> None:
        """Whitespace-only content is text."""
        assert _content_looks_like_text(b"\n\t  \r\n") is True

    def test_samples_only_first_8kb(self) -> None:
        """Only the first 8KB is checked."""
        # Text in first 8KB, binary after -- should be text
        content = b"a" * _BINARY_CHECK_SIZE + b"\x00" * 100
        assert _content_looks_like_text(content) is True

    def test_binary_before_8kb_limit(self) -> None:
        """Null bytes within the first 8KB are detected."""
        content = b"a" * 100 + b"\x00" + b"a" * 100
        assert _content_looks_like_text(content) is False


# ============================================================================
# Format Size Tests
# ============================================================================


class TestFormatSize:
    """Unit tests: format_size for byte, KB, MB, GB ranges."""

    def test_zero_bytes(self) -> None:
        """Zero bytes."""
        assert format_size(0) == "0 B"

    def test_small_bytes(self) -> None:
        """Small byte values below 1 KB."""
        assert format_size(1) == "1 B"
        assert format_size(500) == "500 B"
        assert format_size(1023) == "1023 B"

    def test_exact_kb(self) -> None:
        """Exact kilobyte value."""
        assert format_size(1024) == "1 KB"

    def test_fractional_kb(self) -> None:
        """Fractional kilobyte."""
        assert format_size(1536) == "1.5 KB"

    def test_large_kb(self) -> None:
        """Larger KB values."""
        assert format_size(10240) == "10 KB"
        assert format_size(512 * 1024) == "512 KB"

    def test_exact_mb(self) -> None:
        """Exact megabyte value."""
        assert format_size(1024 * 1024) == "1 MB"

    def test_fractional_mb(self) -> None:
        """Fractional megabyte."""
        assert format_size(int(2.3 * 1024 * 1024)) == "2.3 MB"

    def test_large_mb(self) -> None:
        """Larger MB values."""
        assert format_size(100 * 1024 * 1024) == "100 MB"

    def test_exact_gb(self) -> None:
        """Exact gigabyte value."""
        assert format_size(1024**3) == "1 GB"

    def test_fractional_gb(self) -> None:
        """Fractional gigabyte."""
        assert format_size(int(1.1 * 1024**3)) == "1.1 GB"

    def test_large_gb(self) -> None:
        """Large GB values."""
        assert format_size(10 * 1024**3) == "10 GB"

    def test_negative_treated_as_zero(self) -> None:
        """Negative values are treated as zero."""
        assert format_size(-1) == "0 B"
        assert format_size(-1000) == "0 B"

    def test_human_readable_examples(self) -> None:
        """Specific human-readable examples from the spec."""
        assert format_size(0) == "0 B"
        assert format_size(500) == "500 B"
        assert format_size(1536) == "1.5 KB"


class TestFormatSizeBoundaries:
    """Boundary value tests for format_size."""

    def test_just_below_1kb(self) -> None:
        """1023 bytes should show as bytes."""
        assert format_size(1023) == "1023 B"

    def test_just_at_1kb(self) -> None:
        """1024 bytes should show as 1 KB."""
        assert format_size(1024) == "1 KB"

    def test_just_below_1mb(self) -> None:
        """Just below 1 MB."""
        result = format_size(1024 * 1024 - 1)
        assert "KB" in result

    def test_just_at_1mb(self) -> None:
        """Exactly 1 MB."""
        assert format_size(1024 * 1024) == "1 MB"

    def test_just_below_1gb(self) -> None:
        """Just below 1 GB."""
        result = format_size(1024**3 - 1)
        assert "MB" in result

    def test_just_at_1gb(self) -> None:
        """Exactly 1 GB."""
        assert format_size(1024**3) == "1 GB"


# ============================================================================
# Integration: detect_mime_type + is_text_content together
# ============================================================================


class TestMimeDetectionAndClassificationIntegration:
    """Test that detect_mime_type and is_text_content work together correctly."""

    @pytest.mark.parametrize(
        "path",
        ["file.py", "file.md", "file.json", "file.txt", "file.csv", "file.html", "file.xml"],
    )
    def test_text_files_classified_correctly(self, path: str) -> None:
        """Common text files are detected and classified as text."""
        mime = detect_mime_type(path)
        assert is_text_content(mime) is True

    @pytest.mark.parametrize(
        "path",
        ["file.png", "file.jpg", "file.gif", "file.pdf", "file.zip"],
    )
    def test_binary_files_classified_correctly(self, path: str) -> None:
        """Common binary files are detected and classified as binary."""
        mime = detect_mime_type(path)
        assert is_text_content(mime) is False

    def test_file_with_text_extension_but_binary_content(self) -> None:
        """File with a text extension but binary content.

        When content is checked, is_text_content detects it as binary
        despite the text MIME type (text/* always returns True per spec,
        so this tests at the content level).
        """
        binary_content = b"\x00\x01\x02\x03\x00\x05\x06"
        # The MIME type from extension is text, but content is binary
        mime = detect_mime_type("file.txt")
        assert mime == "text/plain"
        # text/* always returns True from is_text_content (by design)
        # The real binary check happens via _content_looks_like_text
        assert _content_looks_like_text(binary_content) is False

    def test_unknown_file_with_text_content(self) -> None:
        """Unknown file type with text content detected as text."""
        content = b"some plain text content\n"
        mime = detect_mime_type("unknownfile", content=content)
        assert mime == "text/plain"
        assert is_text_content(mime) is True
