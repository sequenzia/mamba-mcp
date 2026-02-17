"""Content type detection utilities for MIME types and text vs binary classification.

Used by read_file and get_file_info tools to determine how to handle file content.
Supports stdlib mimetypes as primary detection, with optional python-magic fallback.

Based on spec Sections 5.1 and 7.2.
"""

from __future__ import annotations

import mimetypes
from pathlib import PurePosixPath

# Initialize mimetypes database once at module load
if not mimetypes.inited:
    mimetypes.init()

# Number of bytes to sample when checking for binary content
_BINARY_CHECK_SIZE = 8192

# MIME types that are considered text even though they don't start with "text/"
_TEXT_MIME_TYPES: frozenset[str] = frozenset(
    {
        "application/json",
        "application/xml",
        "application/javascript",
        "application/ecmascript",
        "application/x-sh",
        "application/x-python-code",
        "application/xhtml+xml",
        "application/sql",
        "application/graphql",
        "application/ld+json",
        "application/manifest+json",
        "application/x-httpd-php",
        "application/x-ruby",
        "application/x-perl",
        "application/toml",
        "application/yaml",
        "application/x-yaml",
    }
)

# Additional extension-to-MIME mappings not always present in the stdlib database
_EXTRA_MIME_MAP: dict[str, str] = {
    ".py": "text/x-python",
    ".pyi": "text/x-python",
    ".rs": "text/x-rust",
    ".go": "text/x-go",
    ".ts": "text/x-typescript",
    ".tsx": "text/x-typescript",
    ".jsx": "text/javascript",
    ".vue": "text/x-vue",
    ".svelte": "text/x-svelte",
    ".toml": "application/toml",
    ".yaml": "application/yaml",
    ".yml": "application/yaml",
    ".md": "text/markdown",
    ".mdx": "text/markdown",
    ".rst": "text/x-rst",
    ".csv": "text/csv",
    ".tsv": "text/tab-separated-values",
    ".log": "text/plain",
    ".cfg": "text/plain",
    ".ini": "text/plain",
    ".env": "text/plain",
    ".gitignore": "text/plain",
    ".dockerignore": "text/plain",
    ".editorconfig": "text/plain",
    ".lock": "text/plain",
    ".sql": "application/sql",
    ".graphql": "application/graphql",
    ".gql": "application/graphql",
    ".jsonl": "application/json",
    ".ipynb": "application/json",
    ".tf": "text/plain",
    ".tfvars": "text/plain",
    ".proto": "text/plain",
    ".gradle": "text/plain",
    ".bat": "text/plain",
    ".ps1": "text/plain",
    ".r": "text/x-r",
    ".R": "text/x-r",
    ".swift": "text/x-swift",
    ".kt": "text/x-kotlin",
    ".kts": "text/x-kotlin",
    ".scala": "text/x-scala",
    ".dart": "text/x-dart",
    ".lua": "text/x-lua",
    ".pl": "text/x-perl",
    ".pm": "text/x-perl",
    ".rb": "text/x-ruby",
    ".erb": "text/x-ruby",
    ".ex": "text/x-elixir",
    ".exs": "text/x-elixir",
    ".erl": "text/x-erlang",
    ".hs": "text/x-haskell",
    ".clj": "text/x-clojure",
    ".lisp": "text/x-lisp",
    ".el": "text/x-lisp",
    ".vim": "text/plain",
    ".fish": "text/plain",
    ".zsh": "text/plain",
}

# Size unit labels in ascending order
_SIZE_UNITS: list[tuple[float, str]] = [
    (1024**3, "GB"),
    (1024**2, "MB"),
    (1024, "KB"),
]


def _try_magic_detect(content: bytes) -> str | None:
    """Attempt MIME detection via python-magic if available.

    Returns the detected MIME type string, or None if python-magic
    is not installed or detection fails.
    """
    try:
        import magic  # type: ignore[import-untyped]

        return str(magic.from_buffer(content, mime=True))
    except Exception:  # noqa: BLE001
        return None


def detect_mime_type(path: str, content: bytes | None = None) -> str:
    """Detect the MIME type of a file from its path extension and/or content bytes.

    Detection strategy:
    1. Check extra mappings for extension or dotfile name (e.g. ``.py``, ``.env``)
    2. Fall back to stdlib mimetypes for extension-based detection
    3. If no extension match and content is available, try python-magic
    4. If still unknown but content is available, use text heuristic
    5. Default to ``application/octet-stream`` for unknown types

    Args:
        path: File path (used for extension-based detection).
        content: Optional raw bytes for content-based detection.

    Returns:
        A MIME type string, e.g. ``"text/plain"`` or ``"application/pdf"``.
        Never raises; returns ``"application/octet-stream"`` for unknown types.
    """
    parsed = PurePosixPath(path)
    ext = parsed.suffix.lower()

    # Check our extra mappings first (more specific for code files)
    if ext in _EXTRA_MIME_MAP:
        return _EXTRA_MIME_MAP[ext]

    # For dotfiles with no extension (e.g. ".env", ".gitignore"),
    # check the filename itself against the extra map
    filename = parsed.name
    if not ext and filename.startswith(".") and filename in _EXTRA_MIME_MAP:
        return _EXTRA_MIME_MAP[filename]

    # Then try stdlib mimetypes
    mime_type, _ = mimetypes.guess_type(path, strict=False)
    if mime_type is not None:
        return mime_type

    # If no extension match and content is available, try magic bytes
    if content is not None:
        magic_result = _try_magic_detect(content)
        if magic_result is not None:
            return magic_result

    # No extension and no content -- unknown type
    if not ext and content is None:
        return "application/octet-stream"

    # Extension present but not recognized, or no extension with content
    if content is not None:
        # Content available but magic didn't work or isn't installed
        # Try heuristic: if the content looks like text, call it text/plain
        if _content_looks_like_text(content):
            return "text/plain"

    return "application/octet-stream"


def _content_looks_like_text(content: bytes) -> bool:
    """Heuristic check whether raw bytes look like text content.

    Checks for null bytes in the first 8KB and attempts UTF-8 decode.
    """
    if len(content) == 0:
        return True

    sample = content[:_BINARY_CHECK_SIZE]

    # Null bytes are a strong indicator of binary content
    if b"\x00" in sample:
        return False

    # Try UTF-8 decode
    try:
        sample.decode("utf-8")
        return True
    except UnicodeDecodeError:
        pass

    # Try ASCII decode (more lenient check: allow high bytes if mostly printable)
    try:
        sample.decode("ascii")
        return True
    except UnicodeDecodeError:
        pass

    # Check if most bytes are in the printable + whitespace range
    text_chars = set(range(32, 127)) | {9, 10, 13}  # printable + tab, newline, CR
    text_count = sum(1 for b in sample if b in text_chars)
    return text_count / len(sample) > 0.85


def is_text_content(mime_type: str, content: bytes | None = None) -> bool:
    """Determine whether content is text or binary based on MIME type and content bytes.

    Classification strategy:
    1. If MIME type starts with ``text/`` -> text
    2. If MIME type is in the known text MIME types set -> text
    3. If MIME type contains ``+xml`` or ``+json`` suffix -> text
    4. For unknown MIME types with content: check first ~8KB for null bytes
    5. Empty content is classified as text

    Args:
        mime_type: The MIME type string (e.g. ``"text/plain"``).
        content: Optional raw bytes for heuristic binary detection.

    Returns:
        ``True`` if content is classified as text, ``False`` if binary.
    """
    # text/* MIME types are always text
    if mime_type.startswith("text/"):
        return True

    # Known text application/* types
    if mime_type in _TEXT_MIME_TYPES:
        return True

    # Structured text types with +xml or +json suffixes
    if "+xml" in mime_type or "+json" in mime_type:
        return True

    # For unknown types, inspect content if available
    if content is not None:
        return _content_looks_like_text(content)

    # No content to inspect -- assume binary for non-text MIME types
    return False


def format_size(size_bytes: int) -> str:
    """Format a byte count as a human-readable string.

    Uses binary units (1 KB = 1024 bytes). Examples:
    - ``0`` -> ``"0 B"``
    - ``500`` -> ``"500 B"``
    - ``1536`` -> ``"1.5 KB"``
    - ``2411724`` -> ``"2.3 MB"``
    - ``1181116006`` -> ``"1.1 GB"``

    Args:
        size_bytes: Non-negative byte count.

    Returns:
        Human-readable size string with appropriate unit.
    """
    if size_bytes < 0:
        size_bytes = 0

    for threshold, unit in _SIZE_UNITS:
        if size_bytes >= threshold:
            value = size_bytes / threshold
            # Use 1 decimal place; drop trailing zero for whole numbers
            if value == int(value):
                return f"{int(value)} {unit}"
            return f"{value:.1f} {unit}"

    return f"{size_bytes} B"
