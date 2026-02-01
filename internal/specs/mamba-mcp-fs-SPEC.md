# Spec: mamba-mcp-fs

**Version**: 1.0
**Author**: Stephen Sequenzia
**Date**: 2026-01-30
**Status**: Draft

---

## 1. Executive Summary

`mamba-mcp-fs` is a new MCP (Model Context Protocol) server package for the `mamba-mcp` monorepo that provides AI assistants with secure, sandboxed access to local and remote filesystems. For the MVP, it supports local filesystem and Amazon S3 backends through a unified `fsspec`-based abstraction layer. The server exposes 12 MCP tools organized in 3 layers (Discovery, S3 Extras, Mutation), with configurable read-only or read-write permissions and comprehensive security controls including path traversal prevention, symlink policies, and rate limiting.

The server supports both STDIO and Streamable HTTP transports for local CLI usage and remote networked deployment scenarios.

## 2. Problem Statement

### 2.1 The Problem

AI assistants and LLMs interacting through the Model Context Protocol currently lack a standardized, secure way to browse, read, and manage files on local and remote filesystems. While the `mamba-mcp` ecosystem provides database access via `mamba-mcp-pg`, there is no equivalent for filesystem operations -- a fundamental capability for many AI assistant workflows.

### 2.2 Current State

Users who need LLMs to interact with files must either:
- Build custom one-off solutions for each use case
- Grant overly broad filesystem access without proper sandboxing
- Manually copy-paste file contents into prompts, losing context and workflow efficiency

### 2.3 Impact Analysis

Without a proper filesystem MCP server:
- AI assistants cannot autonomously explore file structures to understand project layouts or data organization
- Cloud-stored data in S3 remains inaccessible to AI workflows without manual intervention
- Security risks increase when ad-hoc filesystem access is granted without sandboxing
- Developer productivity suffers from manual file-to-prompt workflows

### 2.4 Business Value

Completing the `mamba-mcp` ecosystem with filesystem capabilities alongside the existing postgres server enables AI assistants to work with files the same way they work with databases -- through a secure, well-defined protocol. The `fsspec`-based architecture also positions the server for easy extension to additional backends (GCS, Azure Blob, SFTP) in future releases.

## 3. Goals & Success Metrics

### 3.1 Primary Goals

1. Provide secure, sandboxed filesystem access to AI assistants via MCP
2. Support both local filesystem and S3 through a unified tool interface
3. Offer configurable permission levels (read-only vs read-write) for different deployment scenarios
4. Follow established `mamba-mcp` monorepo patterns for consistency

### 3.2 Success Metrics

| Metric | Target | Measurement Method |
|--------|--------|-------------------|
| Tool coverage | All 12 MCP tools pass acceptance criteria | Automated test suite |
| Backend parity | Core operations work identically on local and S3 | Integration tests against both backends |
| Security | Zero path traversal or sandbox escape vectors | Security-focused unit tests + manual review |
| Client compatibility | All tools callable via mamba-mcp-client (TUI + CLI) | End-to-end testing |
| Transport support | Both STDIO and Streamable HTTP transports functional | Transport integration tests |

### 3.3 Non-Goals

- Supporting filesystems beyond local and S3 in the MVP (though architecture should allow it)
- File watching or change notification systems
- File format conversion or transformation
- File versioning beyond S3's native versioning
- Compression or decompression tools

## 4. User Research

### 4.1 Target Users

#### Primary Persona: AI Assistant Developer

- **Role/Description**: Developer integrating AI assistants with local or cloud-based file storage
- **Goals**: Enable their AI assistant to browse, read, and optionally modify files in a sandboxed environment
- **Pain Points**: No standardized MCP server for filesystem operations; building custom solutions is time-consuming and error-prone
- **Context**: Uses mamba-mcp-client for testing MCP servers; deploys servers via STDIO or HTTP for production

#### Secondary Persona: Data Analyst with AI Tools

- **Role/Description**: Analyst using AI assistants to explore and analyze data stored in S3 or local directories
- **Goals**: Point an AI assistant at a data directory or S3 bucket and have it explore, read, and summarize files
- **Pain Points**: Manually downloading and pasting file contents into AI prompts is tedious; loses directory context

### 4.2 User Journey Map

```
[Configure Server] --> [Start MCP Server] --> [AI Browses Files] --> [AI Reads Content] --> [AI Takes Action]
     |                       |                       |                       |
     v                       v                       v                       v
  Set base path,        STDIO or HTTP         list_directory,         read_file with
  S3 creds,             transport             get_file_info,          smart content
  permissions                                 search_files            detection
```

## 5. Functional Requirements

### 5.1 Layer 1: Discovery Tools (Read-Only, Always Available)

---

#### REQ-001: list_directory

**Priority**: P0 (Critical)

**Description**: List files and directories at a given path, returning metadata for each entry.

**User Story**: As an AI assistant, I want to list the contents of a directory so that I can understand the file structure and navigate to relevant files.

**Tool Parameters**:
- `path` (str, required): Directory path to list. Supports local paths and `s3://bucket/prefix` paths.
- `backend` (str, optional): Force a specific backend (`local` or `s3`). Default: auto-detect from path.
- `include_hidden` (bool, optional): Include hidden files/dotfiles. Default: per server config.
- `pattern` (str, optional): Glob pattern to filter entries (e.g., `*.py`). Default: None (all files).
- `max_entries` (int, optional): Maximum entries to return (1-10000). Default: 1000.

**Response Fields**:
- `path`: The listed directory path
- `backend`: Which backend served this request (`local` or `s3`)
- `entries`: List of `FileEntry` objects (name, path, type [file/directory], size_bytes, modified_at, is_hidden)
- `total_count`: Number of entries returned
- `has_more`: Whether more entries exist beyond max_entries

**Acceptance Criteria**:
- [ ] Lists files and directories with correct metadata (name, size, type, modified date)
- [ ] Respects the configured base path sandbox for local backend
- [ ] Supports S3 prefix listing when S3 backend is configured
- [ ] Filters entries by glob pattern when `pattern` is provided
- [ ] Respects hidden file policy from server configuration
- [ ] Returns `BACKEND_NOT_CONFIGURED` error when targeting a disabled backend
- [ ] Returns `PATH_NOT_FOUND` error for non-existent directories
- [ ] Returns `PATH_OUTSIDE_SANDBOX` error for path traversal attempts

**Edge Cases**:
- Empty directory: Returns empty entries list with `total_count: 0`
- Path traversal attempt (e.g., `../../etc/passwd`): Blocked with `PATH_OUTSIDE_SANDBOX`
- S3 "directory" (prefix with no objects): Returns empty list
- Very large directories: Truncated at `max_entries` with `has_more: true`

---

#### REQ-002: get_file_info

**Priority**: P0 (Critical)

**Description**: Retrieve detailed metadata for a single file or directory.

**User Story**: As an AI assistant, I want to inspect a file's metadata so that I can decide whether to read it (check size, type) before retrieving content.

**Tool Parameters**:
- `path` (str, required): Path to the file or directory.
- `backend` (str, optional): Force backend. Default: auto-detect.
- `include_checksum` (bool, optional): Calculate and include file checksum. Default: false.

**Response Fields**:
- `path`: Full path to the file
- `backend`: Which backend served this request
- `name`: File name
- `type`: `file` or `directory`
- `size_bytes`: File size in bytes
- `size_pretty`: Human-readable size (e.g., "1.2 MB")
- `mime_type`: Detected MIME type (e.g., `text/plain`, `application/pdf`)
- `modified_at`: Last modified timestamp (ISO 8601)
- `created_at`: Creation timestamp if available (ISO 8601, null if unavailable)
- `is_hidden`: Whether file is hidden/dotfile
- `is_symlink`: Whether file is a symbolic link (local only)
- `permissions`: File permissions string (local only, e.g., `rw-r--r--`)
- `checksum`: SHA-256 checksum if requested

**Acceptance Criteria**:
- [ ] Returns correct metadata for files and directories on both backends
- [ ] Detects MIME type accurately for common file types
- [ ] Calculates SHA-256 checksum when requested
- [ ] Identifies symlinks on local filesystem
- [ ] Returns `PATH_NOT_FOUND` for non-existent paths
- [ ] Returns `PATH_OUTSIDE_SANDBOX` for path traversal attempts
- [ ] Returns `SYMLINK_BLOCKED` when symlink policy is set to reject and target is a symlink

---

#### REQ-003: read_file

**Priority**: P0 (Critical)

**Description**: Read the contents of a file with smart content type detection. Text files are returned as text, binary files as base64-encoded content.

**User Story**: As an AI assistant, I want to read file contents so that I can analyze, summarize, or work with the data.

**Tool Parameters**:
- `path` (str, required): Path to the file to read.
- `backend` (str, optional): Force backend. Default: auto-detect.
- `encoding` (str, optional): Text encoding to use. Default: `utf-8`.
- `offset` (int, optional): Byte offset to start reading from. Default: 0.
- `limit` (int, optional): Maximum bytes to read. Default: entire file up to size limit.
- `force_text` (bool, optional): Force text interpretation even for binary-detected files. Default: false.
- `force_base64` (bool, optional): Force base64 encoding for all content. Default: false.

**Response Fields**:
- `path`: Path to the file read
- `backend`: Which backend served this request
- `content`: File content (text string or base64-encoded string)
- `encoding`: The encoding used (`text` or `base64`)
- `mime_type`: Detected MIME type
- `size_bytes`: Total file size
- `bytes_read`: Number of bytes actually read (may differ from size if chunked)
- `offset`: Byte offset this chunk starts at
- `has_more`: Whether more content exists beyond what was read
- `is_truncated`: Whether content was truncated due to size limit

**Acceptance Criteria**:
- [ ] Reads text files and returns content as text with correct encoding
- [ ] Reads binary files and returns content as base64 with MIME type
- [ ] Auto-detects content type (text vs binary) using MIME detection
- [ ] Supports chunked reading via offset/limit parameters
- [ ] Enforces configured file size limit; returns `FILE_TOO_LARGE` for files exceeding the limit when no offset/limit specified
- [ ] Allows reading portions of large files via offset/limit even if total file exceeds size limit
- [ ] Returns `PATH_NOT_FOUND` for non-existent files
- [ ] Returns `CONTENT_DECODE_ERROR` when text decoding fails and `force_text` is true

**Edge Cases**:
- Empty file: Returns empty content string with `size_bytes: 0`
- Binary file without `force_base64`: Auto-detected and returned as base64
- UTF-8 file with BOM: Handled correctly
- File larger than size limit with offset/limit: Allowed (only the requested chunk is read)
- File modified during read: Best-effort, no guarantees on consistency

---

#### REQ-004: search_files

**Priority**: P1 (High)

**Description**: Search for files by name pattern (glob) and/or content (regex), with recursive directory traversal and configurable depth.

**User Story**: As an AI assistant, I want to search for files by name or content so that I can find relevant files without manually browsing every directory.

**Tool Parameters**:
- `path` (str, required): Root directory to search from.
- `backend` (str, optional): Force backend. Default: auto-detect.
- `name_pattern` (str, optional): Glob pattern for file names (e.g., `*.py`, `README*`).
- `content_pattern` (str, optional): Regex pattern to search within file contents.
- `max_depth` (int, optional): Maximum directory depth to recurse (0 = current dir only). Default: 10.
- `max_results` (int, optional): Maximum number of results to return. Default: 100.
- `include_hidden` (bool, optional): Include hidden files in search. Default: per server config.
- `file_types` (list[str], optional): Filter by MIME type prefixes (e.g., `["text/"]`). Default: None.

**Response Fields**:
- `path`: The root search path
- `backend`: Which backend served this request
- `results`: List of `SearchResult` objects (path, name, type, size_bytes, modified_at, match_context)
- `total_matches`: Number of results returned
- `search_truncated`: Whether results were truncated at max_results
- `directories_searched`: Number of directories traversed

**Acceptance Criteria**:
- [ ] Finds files matching glob name patterns recursively
- [ ] Finds files containing regex content patterns
- [ ] Supports combined name + content search (both must match)
- [ ] Respects max_depth limit on recursion
- [ ] Content search only applies to text files (skips binary)
- [ ] Returns match context (surrounding lines) for content matches
- [ ] Respects sandbox boundaries -- cannot search outside base path
- [ ] Respects hidden file and symlink policies
- [ ] Returns results sorted by path

**Edge Cases**:
- No matches: Returns empty results list
- Content pattern on S3: Works but may be slow for large numbers of objects (noted in tool description)
- Search in empty directory: Returns empty results
- Regex syntax error: Returns `INVALID_OPERATION` with suggestion

---

### 5.2 Layer 2: S3 Extras (Read-Only, Available When S3 Configured)

---

#### REQ-005: list_buckets

**Priority**: P1 (High)

**Description**: List available S3 buckets accessible with the configured credentials.

**User Story**: As an AI assistant, I want to see which S3 buckets are available so that I can navigate to the right data.

**Tool Parameters**:
- None required. This tool uses the configured S3 credentials.

**Response Fields**:
- `buckets`: List of `BucketInfo` objects (name, creation_date, region)
- `total_count`: Number of buckets

**Acceptance Criteria**:
- [ ] Lists all accessible S3 buckets
- [ ] Returns bucket name, creation date, and region for each bucket
- [ ] Returns `BACKEND_NOT_CONFIGURED` if S3 backend is not enabled
- [ ] Returns `BACKEND_ERROR` for credential or connectivity issues

---

#### REQ-006: get_presigned_url

**Priority**: P2 (Medium)

**Description**: Generate a presigned URL for downloading or uploading an S3 object.

**User Story**: As an AI assistant, I want to generate shareable links to S3 objects so that users can access files directly without going through the MCP server.

**Tool Parameters**:
- `path` (str, required): S3 object path (e.g., `s3://bucket/key`).
- `operation` (str, optional): `download` or `upload`. Default: `download`.
- `expires_in` (int, optional): URL expiration time in seconds. Default: 3600 (1 hour). Max: 604800 (7 days).

**Response Fields**:
- `url`: The presigned URL
- `path`: The S3 object path
- `operation`: download or upload
- `expires_at`: ISO 8601 timestamp when URL expires

**Acceptance Criteria**:
- [ ] Generates valid presigned download URLs
- [ ] Generates valid presigned upload URLs (only when write mode enabled)
- [ ] Respects expiration time parameter
- [ ] Returns `PERMISSION_DENIED` for upload URLs when in read-only mode
- [ ] Returns `BACKEND_NOT_CONFIGURED` if S3 is not enabled
- [ ] Returns `PATH_NOT_FOUND` for non-existent objects (download only)

---

#### REQ-007: get_object_metadata

**Priority**: P2 (Medium)

**Description**: Retrieve S3-specific metadata for an object that goes beyond what `get_file_info` provides.

**User Story**: As an AI assistant, I want to see S3-specific metadata (storage class, tags, versions) to understand how data is stored and managed.

**Tool Parameters**:
- `path` (str, required): S3 object path.
- `include_tags` (bool, optional): Include object tags. Default: true.
- `include_versions` (bool, optional): Include version history if versioning is enabled. Default: false.

**Response Fields**:
- `path`: S3 object path
- `storage_class`: S3 storage class (STANDARD, GLACIER, etc.)
- `etag`: Object ETag
- `version_id`: Current version ID (if versioning enabled)
- `tags`: Dict of object tags (if requested)
- `versions`: List of version info (if requested and versioning enabled)
- `server_side_encryption`: Encryption type if applicable
- `content_type`: S3 content type header
- `last_modified`: Last modified timestamp

**Acceptance Criteria**:
- [ ] Returns correct S3-specific metadata
- [ ] Includes object tags when requested
- [ ] Includes version history when requested and bucket has versioning
- [ ] Returns `BACKEND_NOT_CONFIGURED` if S3 is not enabled
- [ ] Returns `PATH_NOT_FOUND` for non-existent objects

---

### 5.3 Layer 3: Mutation Tools (Only When Write Mode Enabled)

---

#### REQ-008: write_file

**Priority**: P1 (High)

**Description**: Create a new file or overwrite an existing file with provided content.

**User Story**: As an AI agent, I want to write files so that I can save generated content, configurations, or data outputs.

**Tool Parameters**:
- `path` (str, required): Destination file path.
- `content` (str, required): File content (text string or base64-encoded for binary).
- `encoding` (str, optional): Content encoding -- `text` or `base64`. Default: `text`.
- `backend` (str, optional): Force backend. Default: auto-detect.
- `create_parents` (bool, optional): Create parent directories if they don't exist. Default: true.
- `overwrite` (bool, optional): Allow overwriting existing files. Default: true.

**Response Fields**:
- `path`: Path of the written file
- `backend`: Which backend served this request
- `size_bytes`: Size of the written file
- `created`: Whether a new file was created (vs overwritten)

**Acceptance Criteria**:
- [ ] Creates new files with provided text content
- [ ] Creates new files with base64-decoded binary content
- [ ] Overwrites existing files when `overwrite` is true
- [ ] Returns `PERMISSION_DENIED` when `overwrite` is false and file exists
- [ ] Creates parent directories when `create_parents` is true
- [ ] Returns `PERMISSION_DENIED` when server is in read-only mode
- [ ] Returns `FILE_TOO_LARGE` when content exceeds configured size limit
- [ ] Returns `PATH_OUTSIDE_SANDBOX` for path traversal attempts

---

#### REQ-009: delete_file

**Priority**: P1 (High)

**Description**: Delete a file at the specified path.

**User Story**: As an AI agent, I want to delete files so that I can clean up temporary outputs or remove outdated data.

**Tool Parameters**:
- `path` (str, required): Path of the file to delete.
- `backend` (str, optional): Force backend. Default: auto-detect.

**Response Fields**:
- `path`: Path of the deleted file
- `backend`: Which backend served this request
- `deleted`: Boolean confirming deletion

**Acceptance Criteria**:
- [ ] Deletes files on both local and S3 backends
- [ ] Returns `PERMISSION_DENIED` when server is in read-only mode
- [ ] Returns `PATH_NOT_FOUND` for non-existent files
- [ ] Returns `PATH_OUTSIDE_SANDBOX` for path traversal attempts
- [ ] Does NOT support directory deletion (only files) -- returns `INVALID_OPERATION` for directories

**Edge Cases**:
- Deleting a symlink: Deletes the symlink, not the target (if symlinks are allowed)
- S3 delete marker: Handled by S3 natively if versioning is enabled

---

#### REQ-010: move_file

**Priority**: P1 (High)

**Description**: Move or rename a file from one path to another within the same backend.

**User Story**: As an AI agent, I want to move or rename files to organize outputs or restructure data.

**Tool Parameters**:
- `source` (str, required): Source file path.
- `destination` (str, required): Destination file path.
- `backend` (str, optional): Force backend. Default: auto-detect from source.
- `overwrite` (bool, optional): Allow overwriting destination. Default: false.

**Response Fields**:
- `source`: Original path
- `destination`: New path
- `backend`: Which backend served this request
- `overwritten`: Whether an existing file was overwritten

**Acceptance Criteria**:
- [ ] Moves/renames files within local filesystem
- [ ] Moves/renames objects within S3 (copy + delete)
- [ ] Returns `PERMISSION_DENIED` when server is in read-only mode
- [ ] Returns `PERMISSION_DENIED` when `overwrite` is false and destination exists
- [ ] Returns `PATH_NOT_FOUND` for non-existent source
- [ ] Returns `INVALID_OPERATION` for cross-backend moves (use copy_file + delete_file instead)
- [ ] Returns `PATH_OUTSIDE_SANDBOX` for path traversal attempts on either path

---

#### REQ-011: copy_file

**Priority**: P1 (High)

**Description**: Copy a file, including cross-backend copies (e.g., local to S3 or S3 to local).

**User Story**: As an AI agent, I want to copy files between local and S3 so that I can sync data or create backups.

**Tool Parameters**:
- `source` (str, required): Source file path.
- `destination` (str, required): Destination file path.
- `source_backend` (str, optional): Force source backend. Default: auto-detect.
- `dest_backend` (str, optional): Force destination backend. Default: auto-detect.
- `overwrite` (bool, optional): Allow overwriting destination. Default: false.

**Response Fields**:
- `source`: Source path
- `destination`: Destination path
- `source_backend`: Source backend used
- `dest_backend`: Destination backend used
- `size_bytes`: Size of the copied file
- `cross_backend`: Whether this was a cross-backend copy

**Acceptance Criteria**:
- [ ] Copies files within local filesystem
- [ ] Copies objects within S3
- [ ] Copies files from local to S3 (cross-backend)
- [ ] Copies files from S3 to local (cross-backend)
- [ ] Returns `PERMISSION_DENIED` when server is in read-only mode
- [ ] Returns `PERMISSION_DENIED` when `overwrite` is false and destination exists
- [ ] Returns `FILE_TOO_LARGE` when file exceeds destination backend's size limit
- [ ] Returns `PATH_OUTSIDE_SANDBOX` for path traversal on either path

---

#### REQ-012: create_directory

**Priority**: P2 (Medium)

**Description**: Create a directory (local) or prefix placeholder (S3).

**User Story**: As an AI agent, I want to create directories to organize files before writing them.

**Tool Parameters**:
- `path` (str, required): Directory path to create.
- `backend` (str, optional): Force backend. Default: auto-detect.
- `parents` (bool, optional): Create parent directories as needed. Default: true.

**Response Fields**:
- `path`: Path of the created directory
- `backend`: Which backend served this request
- `created`: Whether the directory was newly created (vs already existed)

**Acceptance Criteria**:
- [ ] Creates directories on local filesystem
- [ ] Creates S3 prefix placeholder (empty object with trailing `/`)
- [ ] Creates parent directories when `parents` is true
- [ ] Returns `PERMISSION_DENIED` when server is in read-only mode
- [ ] Returns `PATH_OUTSIDE_SANDBOX` for path traversal attempts
- [ ] Does not error if directory already exists (idempotent)

---

### 5.4 Transport Support

#### REQ-013: Dual Transport Support

**Priority**: P0 (Critical)

**Description**: The MCP server must support both STDIO and Streamable HTTP transports for different deployment scenarios.

**Acceptance Criteria**:
- [ ] STDIO transport works for local/CLI usage (default)
- [ ] Streamable HTTP transport works for remote/networked deployment
- [ ] Transport is configurable via `MAMBA_MCP_FS_TRANSPORT` env var (`stdio` or `streamable-http`)
- [ ] CLI supports selecting transport mode
- [ ] HTTP transport respects `MAMBA_MCP_FS_SERVER_HOST` and `MAMBA_MCP_FS_SERVER_PORT` settings
- [ ] Both transports expose the same set of tools with identical behavior

---

## 6. Non-Functional Requirements

### 6.1 Performance

- File listing operations should complete in under 500ms for directories with fewer than 1000 entries (local)
- File reading should be I/O-bound, not CPU-bound (no unnecessary processing)
- S3 operations should use connection pooling via aiobotocore
- Content search on local filesystem should handle directories with 10,000+ files

### 6.2 Security

**REQ-SEC-001: Path Traversal Prevention**
- All file paths MUST be resolved to absolute paths and validated against the configured sandbox base path
- Relative path components (`..`, `.`) must be resolved before validation
- URL-encoded path components must be decoded before validation
- Any path resolving outside the sandbox returns `PATH_OUTSIDE_SANDBOX`

**REQ-SEC-002: Symlink Policy**
- Configurable via `MAMBA_MCP_FS_LOCAL_FOLLOW_SYMLINKS` (default: `false`)
- When `false`: symlinks are identified but not followed; accessing a symlink target returns `SYMLINK_BLOCKED`
- When `true`: symlinks are followed, but the resolved target must still be within the sandbox

**REQ-SEC-003: Hidden Files Policy**
- Configurable via `MAMBA_MCP_FS_LOCAL_SHOW_HIDDEN` (default: `false`)
- When `false`: dotfiles/hidden files are excluded from listing and search results
- When `true`: all files are visible
- Individual tool calls can override this via `include_hidden` parameter

**REQ-SEC-004: File Type Restrictions**
- Optional allowlist: `MAMBA_MCP_FS_ALLOWED_EXTENSIONS` (comma-separated, e.g., `.py,.md,.txt,.json`)
- Optional denylist: `MAMBA_MCP_FS_DENIED_EXTENSIONS` (comma-separated, e.g., `.exe,.sh,.bat`)
- Allowlist takes precedence over denylist if both are set
- When no restrictions are set, all file types are accessible

**REQ-SEC-005: Size Limits**
- Per-backend configurable max file size (`MAMBA_MCP_FS_LOCAL_MAX_FILE_SIZE`, `MAMBA_MCP_FS_S3_MAX_FILE_SIZE`)
- Default: 10MB for local, 50MB for S3
- Applied on read operations (full file reads) and write operations
- Chunked reads with explicit offset/limit bypass the total file size limit (only the chunk is loaded into memory)

**REQ-SEC-006: Rate Limiting**
- Optional rate limiting via `MAMBA_MCP_FS_RATE_LIMIT` (operations per minute, 0 = disabled)
- Default: 0 (disabled)
- When enabled, returns `RATE_LIMITED` error with retry-after information
- Applied per-server instance (not per-backend)

### 6.3 Scalability

- The server handles one MCP session at a time (standard MCP server model)
- S3 operations should be efficient for buckets with millions of objects (use prefix listing, not full bucket scans)
- Local filesystem operations should handle directory trees with 100,000+ files

### 6.4 Reliability

- All operations should be idempotent where possible (especially create_directory)
- Network errors to S3 should produce clear `BACKEND_ERROR` responses with actionable information
- The server should not crash on unexpected file types, encoding issues, or permission errors

## 7. Technical Considerations

### 7.1 Architecture Overview

The server follows the same architectural pattern as `mamba-mcp-pg`:

```
CLI (__main__.py)
  |
  v
FastMCP Server (server.py) with lifespan context
  |
  v
Tool Functions (tools/) registered with @mcp.tool
  |
  v
Backend Manager (backends/) -- routes to appropriate fsspec filesystem
  |
  +--> LocalBackend (fsspec LocalFileSystem)
  +--> S3Backend (s3fs S3FileSystem)
  |
Security Layer (security.py) -- validates all paths before backend operations
```

**Key Design Decision (Agent Recommendation -- Accepted)**: Use `fsspec` as both the abstraction layer and the I/O layer. `s3fs` is natively an `fsspec` implementation, and `fsspec` includes a local filesystem implementation. This eliminates the need for a separate `aiofiles` dependency and provides a truly unified interface. The backend manager wraps `fsspec` filesystems with security validation and configuration.

### 7.2 Tech Stack

- **Runtime**: Python 3.11+
- **MCP Framework**: `mcp>=1.0.0` (FastMCP)
- **Filesystem Abstraction**: `fsspec` (local) + `s3fs` (S3 backend, built on `fsspec` + `aiobotocore`)
- **Configuration**: `pydantic>=2.0.0` + `pydantic-settings>=2.0.0`
- **CLI**: `typer>=0.12.0`
- **Content Detection**: `python-magic` or stdlib `mimetypes` (TBD during implementation)
- **Linting**: Ruff (line length 100)
- **Type Checking**: MyPy strict mode
- **Testing**: pytest with asyncio auto mode

### 7.3 Package Structure

```
packages/mamba-mcp-fs/
  pyproject.toml
  README.md
  src/mamba_mcp_fs/
    __init__.py
    __main__.py          # Typer CLI entry point
    config.py            # Pydantic settings (MAMBA_MCP_FS_*)
    server.py            # FastMCP server & lifespan
    security.py          # Path validation, sandboxing, policy enforcement
    errors.py            # Error codes & structured error responses
    backends/
      __init__.py
      base.py            # Backend manager, fsspec wrapper
      local.py           # Local filesystem backend
      s3.py              # S3 backend via s3fs
    models/
      __init__.py
      files.py           # Pydantic models for file entries, metadata
      responses.py       # Tool response models
    tools/
      __init__.py
      discovery_tools.py # Layer 1: list_directory, get_file_info, read_file, search_files
      s3_tools.py        # Layer 2: list_buckets, get_presigned_url, get_object_metadata
      mutation_tools.py  # Layer 3: write_file, delete_file, move_file, copy_file, create_directory
  tests/
    __init__.py
    conftest.py          # Shared fixtures (mock backends, temp dirs)
    test_config.py
    test_security.py
    test_backends/
      test_local.py
      test_s3.py
    test_tools/
      test_discovery.py
      test_s3_extras.py
      test_mutation.py
    test_cli.py
```

### 7.4 Configuration Schema

```python
class LocalSettings(BaseSettings):
    """Local filesystem backend configuration."""
    model_config = SettingsConfigDict(
        env_prefix="MAMBA_MCP_FS_LOCAL_",
        env_file="mamba.env",
    )

    enabled: bool = True
    base_path: str = Field(..., description="Sandbox root directory")
    max_file_size: int = Field(default=10_485_760, description="Max file size in bytes (10MB)")
    follow_symlinks: bool = Field(default=False, description="Follow symbolic links")
    show_hidden: bool = Field(default=False, description="Show hidden files/dotfiles")


class S3Settings(BaseSettings):
    """S3 backend configuration."""
    model_config = SettingsConfigDict(
        env_prefix="MAMBA_MCP_FS_S3_",
        env_file="mamba.env",
    )

    enabled: bool = False
    bucket: str | None = Field(default=None, description="Default S3 bucket")
    prefix: str = Field(default="", description="Key prefix within bucket")
    region: str = Field(default="us-east-1", description="AWS region")
    endpoint_url: str | None = Field(default=None, description="Custom endpoint (MinIO, LocalStack)")
    max_file_size: int = Field(default=52_428_800, description="Max file size in bytes (50MB)")


class ServerSettings(BaseSettings):
    """MCP server configuration."""
    model_config = SettingsConfigDict(
        env_prefix="MAMBA_MCP_FS_",
        env_file="mamba.env",
    )

    transport: str = Field(default="stdio", pattern="^(stdio|streamable-http)$")
    server_host: str = Field(default="0.0.0.0")
    server_port: int = Field(default=8080, ge=1, le=65535)
    log_level: str = Field(default="INFO")
    log_format: str = Field(default="json", pattern="^(json|text)$")
    read_only: bool = Field(default=True, description="Disable mutation tools")
    rate_limit: int = Field(default=0, ge=0, description="Ops per minute, 0=disabled")
    allowed_extensions: str | None = Field(default=None, description="Comma-separated allowlist")
    denied_extensions: str | None = Field(default=None, description="Comma-separated denylist")
```

### 7.5 Integration Points

| System | Integration Type | Purpose |
|--------|-----------------|---------|
| `mamba-mcp-client` | MCP Protocol | Testing and debugging via TUI/CLI |
| AWS S3 | S3 API via s3fs | Cloud storage backend |
| Local OS | Filesystem via fsspec | Local file access |
| AWS IAM / Env vars | Credentials | S3 authentication |

### 7.6 Error Handling

Following the `mamba-mcp-pg` pattern with structured error responses:

```python
class ErrorCode:
    PATH_NOT_FOUND = "PATH_NOT_FOUND"
    PATH_OUTSIDE_SANDBOX = "PATH_OUTSIDE_SANDBOX"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    FILE_TOO_LARGE = "FILE_TOO_LARGE"
    BACKEND_NOT_CONFIGURED = "BACKEND_NOT_CONFIGURED"
    BACKEND_ERROR = "BACKEND_ERROR"
    INVALID_OPERATION = "INVALID_OPERATION"
    RATE_LIMITED = "RATE_LIMITED"
    SYMLINK_BLOCKED = "SYMLINK_BLOCKED"
    CONTENT_DECODE_ERROR = "CONTENT_DECODE_ERROR"

ERROR_SUGGESTIONS: dict[str, str] = {
    ErrorCode.PATH_NOT_FOUND: "Check the path exists with list_directory",
    ErrorCode.PATH_OUTSIDE_SANDBOX: "All paths must be within the configured base path",
    ErrorCode.PERMISSION_DENIED: "Server is in read-only mode or operation not allowed",
    ErrorCode.FILE_TOO_LARGE: "Use offset/limit for chunked reading, or increase max_file_size",
    ErrorCode.BACKEND_NOT_CONFIGURED: "Enable the backend in server configuration",
    ErrorCode.BACKEND_ERROR: "Check backend connectivity and credentials",
    ErrorCode.INVALID_OPERATION: "Review the operation parameters",
    ErrorCode.RATE_LIMITED: "Wait before retrying; reduce operation frequency",
    ErrorCode.SYMLINK_BLOCKED: "Symlinks are disabled; set follow_symlinks=true to allow",
    ErrorCode.CONTENT_DECODE_ERROR: "Try reading as binary (force_base64=true)",
}
```

## 8. Scope Definition

### 8.1 In Scope

- Local filesystem backend with full sandbox security
- S3 backend via s3fs/fsspec with credential support
- 12 MCP tools across 3 layers (Discovery, S3 Extras, Mutation)
- Configurable read-only vs read-write permissions
- Smart content type detection (text vs binary)
- Chunked file reading for large files
- Recursive file search (name + content)
- Comprehensive security measures (path traversal, symlinks, hidden files, extensions, size limits, rate limiting)
- STDIO and Streamable HTTP transports
- Typer CLI with `test` command for connectivity verification
- Full test suite with mocked backends and LocalStack integration

### 8.2 Out of Scope

- **Remote filesystems beyond S3**: GCS, Azure Blob, SFTP, etc. (fsspec makes these easy to add later)
- **File watching / change notifications**: No event-driven features
- **File versioning**: Beyond S3's native versioning support
- **Compression/decompression**: No zip/tar/gzip tools
- **File format conversion**: No CSV-to-JSON, image resizing, etc.
- **Directory deletion**: Only file deletion in MVP (safety measure)
- **Concurrent multi-session support**: Standard single-session MCP model
- **Authentication/authorization layer**: Relies on deployment-level security (who can connect to the MCP server)

### 8.3 Future Considerations

- Additional fsspec backends (GCS via `gcsfs`, Azure via `adlfs`, SFTP)
- File watching / change event notifications
- Directory deletion with recursive option
- Batch operations (multi-file copy, move, delete)
- File preview generation (thumbnails, text summaries)
- Compression/archive tools
- Shared utility extraction across mamba-mcp packages

## 9. Implementation Plan

### 9.1 Phase 1: Foundation

**Completion Criteria**: Package scaffolding is complete, configuration loads correctly, security layer blocks all path traversal attempts, error framework produces structured responses, and the server starts (even with no tools registered).

| Deliverable | Description | Dependencies |
|-------------|-------------|--------------|
| Package scaffolding | `pyproject.toml`, module structure, CLI skeleton | None |
| Configuration system | Pydantic settings with `MAMBA_MCP_FS_*` env vars, mamba.env support | None |
| Security layer | Path validation, sandbox enforcement, symlink policy, hidden file policy, extension filtering | Configuration |
| Error framework | Error codes, structured responses, suggestion mapping | None |
| FastMCP server | Server initialization with lifespan, backend manager in AppContext | Configuration |
| Backend manager | fsspec integration, backend registry, path routing | Security layer |

**Checkpoint Gate**: Security layer review -- verify all path traversal vectors are blocked before proceeding to tool implementation.

---

### 9.2 Phase 2: Core Features (Local Backend)

**Completion Criteria**: All Layer 1 tools work correctly against the local filesystem, are callable via mamba-mcp-client, handle all specified edge cases, and pass acceptance criteria.

| Deliverable | Description | Dependencies |
|-------------|-------------|--------------|
| Local backend | fsspec LocalFileSystem wrapper with security integration | Phase 1 |
| `list_directory` tool | Directory listing with metadata, filtering, pagination | Local backend |
| `get_file_info` tool | File metadata with MIME detection, checksum | Local backend |
| `read_file` tool | Content reading with smart text/binary detection, chunking | Local backend |
| `search_files` tool | Recursive name + content search | Local backend |
| Content detection | MIME type detection, text vs binary classification | None |
| Unit tests | Mocked fsspec tests for all Layer 1 tools | Tools |
| CLI `test` command | Verify local path access and configuration | Phase 1 |

**Checkpoint Gate**: Tool API review -- verify all tool signatures, response schemas, and error handling before proceeding to S3 backend.

---

### 9.3 Phase 3: S3 Backend

**Completion Criteria**: S3 backend works via s3fs/fsspec, all Layer 1 tools work against S3, Layer 2 S3-specific tools work, and cross-backend path routing is correct. LocalStack integration tests pass.

| Deliverable | Description | Dependencies |
|-------------|-------------|--------------|
| S3 backend | s3fs S3FileSystem wrapper with security integration | Phase 1 |
| Layer 1 on S3 | All discovery tools work against S3 backend | S3 backend, Phase 2 tools |
| `list_buckets` tool | List available S3 buckets | S3 backend |
| `get_presigned_url` tool | Generate presigned URLs | S3 backend |
| `get_object_metadata` tool | S3-specific metadata retrieval | S3 backend |
| Cross-backend routing | Path-based auto-detection (`s3://` prefix) | Both backends |
| Integration tests | LocalStack-based S3 tests | S3 backend |
| CLI `test` command (S3) | Verify S3 connectivity and bucket access | S3 backend |

**Checkpoint Gate**: Integration test review -- verify S3 operations work correctly with LocalStack before proceeding to mutation tools.

---

### 9.4 Phase 4: Write Operations + Polish

**Completion Criteria**: All Layer 3 tools work on both backends (when write mode enabled), cross-backend copy works, rate limiting functions correctly, documentation is complete, and all tests pass.

| Deliverable | Description | Dependencies |
|-------------|-------------|--------------|
| `write_file` tool | Create/overwrite files on both backends | Phase 2, Phase 3 |
| `delete_file` tool | Delete files on both backends | Phase 2, Phase 3 |
| `move_file` tool | Move/rename within same backend | Phase 2, Phase 3 |
| `copy_file` tool | Copy including cross-backend (local <-> S3) | Phase 2, Phase 3 |
| `create_directory` tool | Create directories/prefixes | Phase 2, Phase 3 |
| Rate limiting | Operations-per-minute enforcement | Phase 1 |
| Read-only enforcement | Verify Layer 3 tools blocked when `read_only=true` | Configuration |
| README and documentation | Package README, tool documentation | All tools |
| Full test suite | Complete unit + integration tests for all tools | All tools |

**Checkpoint Gate**: Final review -- verify all 12 tools, both transports, security measures, and test coverage before release.

## 10. Dependencies

### 10.1 Technical Dependencies

| Dependency | Version | Purpose | Risk if Unavailable |
|------------|---------|---------|---------------------|
| `mcp` | >=1.0.0 | FastMCP framework | Blocking -- core framework |
| `fsspec` | Latest | Filesystem abstraction | Blocking -- core abstraction |
| `s3fs` | Latest | S3 backend (fsspec impl) | Blocks S3 features only |
| `pydantic` | >=2.0.0 | Models and validation | Blocking -- configuration |
| `pydantic-settings` | >=2.0.0 | Environment variable config | Blocking -- configuration |
| `typer` | >=0.12.0 | CLI interface | Blocking -- CLI |

### 10.2 Development Dependencies

| Dependency | Purpose |
|------------|---------|
| `pytest` | Test framework |
| `pytest-asyncio` | Async test support |
| `moto` or `localstack` | S3 mocking for tests |
| `ruff` | Linting and formatting |
| `mypy` | Static type checking |

## 11. Risks & Mitigations

| Risk | Impact | Likelihood | Mitigation Strategy |
|------|--------|------------|---------------------|
| fsspec async support limitations | High | Medium | Evaluate fsspec async capabilities early in Phase 1; fall back to `asyncio.to_thread` wrapping if needed |
| Path traversal vulnerability | Critical | Low | Comprehensive security unit tests; manual security review at Phase 1 checkpoint |
| S3 credential management complexity | Medium | Medium | Leverage standard AWS credential chain (env vars, IAM roles, profiles); document clearly |
| Large file memory pressure | High | Medium | Enforce size limits; chunked reading prevents loading entire files into memory |
| fsspec API changes | Low | Low | Pin major version; test against specific versions |
| Content detection accuracy | Low | Medium | Use multiple detection strategies (magic bytes + extension); allow user override via `force_text`/`force_base64` |

## 12. Testing Strategy

### 12.1 Unit Tests

- **Security layer tests**: Exhaustive path traversal attack vectors, symlink handling, extension filtering
- **Backend tests**: Mocked fsspec filesystems for both local and S3
- **Tool tests**: Each tool tested with mocked backends for all success paths, error paths, and edge cases
- **Configuration tests**: Env var loading, validation, defaults

### 12.2 Integration Tests

- **Local filesystem**: Real temp directories (`tmp_path` pytest fixture) for end-to-end local operations
- **S3 backend**: LocalStack-based tests for real S3 API interaction
- **Cross-backend**: Copy operations between temp directories and LocalStack S3
- **CLI tests**: Verify `test` command output for both connected and disconnected states
- **Transport tests**: Verify both STDIO and Streamable HTTP serve the same tools

### 12.3 Test Infrastructure

```python
# conftest.py fixtures
@pytest.fixture
def mock_local_backend() -> MockLocalBackend:
    """Mocked fsspec local filesystem for unit tests."""

@pytest.fixture
def mock_s3_backend() -> MockS3Backend:
    """Mocked fsspec S3 filesystem for unit tests."""

@pytest.fixture
def temp_sandbox(tmp_path) -> Path:
    """Real temp directory with test files for integration tests."""

@pytest.fixture
def localstack_s3() -> S3Client:
    """LocalStack S3 client for integration tests."""
```

### 12.4 Coverage Targets

- Security layer: >95% coverage (critical path)
- Backend operations: >85% coverage
- Tool functions: >85% coverage
- Overall package: >80% coverage

## 13. Human Checkpoint Gates

| Gate | Phase | Reviewers | Criteria |
|------|-------|-----------|----------|
| **Security Review** | After Phase 1 | Author + peer | All path traversal tests pass; symlink policy enforced; no sandbox escape vectors |
| **Tool API Review** | After Phase 2 | Author | Tool signatures match spec; response schemas are consistent; error handling is complete |
| **S3 Integration Review** | After Phase 3 | Author | LocalStack tests pass; credential handling works; cross-backend routing is correct |
| **Final Review** | After Phase 4 | Author + peer | All 12 tools work; both transports functional; all tests pass; docs complete |

## 14. Open Questions

| # | Question | Status |
|---|----------|--------|
| 1 | Should `python-magic` (libmagic wrapper) or stdlib `mimetypes` be used for content detection? | Decide during Phase 2 implementation -- `python-magic` is more accurate but adds a system dependency |
| 2 | Should fsspec async operations use native async or `asyncio.to_thread` wrapping? | Evaluate during Phase 1 -- depends on fsspec's async support quality for each backend |

## 15. Appendix

### 15.1 Glossary

| Term | Definition |
|------|------------|
| MCP | Model Context Protocol -- standard protocol for AI assistant tool integration |
| FastMCP | Python framework for building MCP servers |
| fsspec | Filesystem Spec -- Python library providing a unified interface to various filesystem backends |
| s3fs | S3 filesystem implementation for fsspec, built on aiobotocore |
| Sandbox | The configured base directory that all file operations are restricted to |
| Backend | A filesystem implementation (local or S3) that handles actual I/O operations |
| Layer | A group of related MCP tools with shared permission requirements |

### 15.2 References

- [MCP Protocol Specification](https://modelcontextprotocol.io/)
- [FastMCP Documentation](https://github.com/jlowin/fastmcp)
- [fsspec Documentation](https://filesystem-spec.readthedocs.io/)
- [s3fs Documentation](https://s3fs.readthedocs.io/)
- [mamba-mcp-pg](../../packages/mamba-mcp-pg/) -- Reference implementation for patterns
- [Pydantic Settings](https://docs.pydantic.dev/latest/concepts/pydantic_settings/)

### 15.3 Agent Recommendations Incorporated

The following recommendations were suggested by the spec interview agent and accepted by the author:

1. **fsspec All-the-Way Architecture**: Use `fsspec` as both the abstraction layer and the I/O layer, rather than combining fsspec with separate `aiofiles` and `s3fs` libraries independently. Since `s3fs` is natively an fsspec backend and fsspec includes a local filesystem, this provides a unified interface without redundant dependencies.

---

*Document generated by SDD Tools*
