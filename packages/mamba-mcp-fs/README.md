# mamba-mcp-fs

Filesystem MCP Server with local and S3 backend support for AI assistants.

Provides a secure, sandboxed interface for AI assistants to browse, read, search, and modify files on local filesystems and Amazon S3 -- all via the [Model Context Protocol](https://modelcontextprotocol.io/).

## Features

- **12 MCP Tools** across 3 layers for progressive filesystem access
- **2 Backends** -- local filesystem and Amazon S3, usable side by side
- **Security-first** -- sandbox enforcement, path traversal prevention, symlink policy, extension filtering, rate limiting
- **Smart content detection** -- automatic MIME typing and text vs. binary classification
- **Chunked reading** -- offset/limit support for large files
- **Cross-backend copy** -- copy files between local and S3 in a single operation
- **Configurable** -- environment variables, `.env` files, CLI flags

### Tool Layers

| Layer | Tools | Availability |
|-------|-------|--------------|
| **Layer 1: Discovery** | `list_directory`, `get_file_info`, `read_file`, `search_files` | Always |
| **Layer 2: S3 Extras** | `list_buckets`, `get_presigned_url`, `get_object_metadata` | When S3 enabled |
| **Layer 3: Mutation** | `write_file`, `delete_file`, `move_file`, `copy_file`, `create_directory` | When `read_only=false` |

## Quick Start

### Installation

Within the mamba-mcp monorepo:

```bash
uv sync --group dev
```

### Basic Usage (Local Filesystem)

1. Set the sandbox directory:

```bash
export MAMBA_MCP_FS_LOCAL_BASE_PATH=/path/to/sandbox
```

2. Start the server (STDIO transport, default):

```bash
mamba-mcp-fs
```

3. Or test configuration first:

```bash
mamba-mcp-fs test
```

### With mamba-mcp-client

Use the companion testing client for interactive exploration:

```bash
# Interactive TUI
uv run --package mamba-mcp-client mamba-mcp tui --stdio "mamba-mcp-fs"

# List available tools
uv run --package mamba-mcp-client mamba-mcp tools --stdio "mamba-mcp-fs"

# Call a tool directly
uv run --package mamba-mcp-client mamba-mcp call list_directory \
  --args '{"path": "/data"}' \
  --stdio "mamba-mcp-fs"

# Read a file
uv run --package mamba-mcp-client mamba-mcp call read_file \
  --args '{"path": "/data/report.csv"}' \
  --stdio "mamba-mcp-fs"
```

### Using an env file

Create a `mamba.env` file in your project directory:

```env
# Server settings
MAMBA_MCP_FS_TRANSPORT=stdio
MAMBA_MCP_FS_READ_ONLY=true
MAMBA_MCP_FS_LOG_LEVEL=INFO

# Local backend
MAMBA_MCP_FS_LOCAL_ENABLED=true
MAMBA_MCP_FS_LOCAL_BASE_PATH=/home/user/projects
```

Then run:

```bash
mamba-mcp-fs --env-file mamba.env
```

If no `--env-file` is specified, the server checks for `mamba.env` in the current directory, then in the home directory (`~/mamba.env`).

## Configuration

All settings are loaded from environment variables or a `mamba.env` file.

### Server Settings

Prefix: `MAMBA_MCP_FS_`

| Variable | Description | Default |
|----------|-------------|---------|
| `MAMBA_MCP_FS_TRANSPORT` | Transport type (`stdio` or `streamable-http`) | `stdio` |
| `MAMBA_MCP_FS_SERVER_HOST` | HTTP server bind address | `0.0.0.0` |
| `MAMBA_MCP_FS_SERVER_PORT` | HTTP server port (1-65535) | `8080` |
| `MAMBA_MCP_FS_LOG_LEVEL` | Logging level (`DEBUG`, `INFO`, `WARNING`, `ERROR`) | `INFO` |
| `MAMBA_MCP_FS_LOG_FORMAT` | Log format (`json` or `text`) | `json` |
| `MAMBA_MCP_FS_READ_ONLY` | Disable mutation tools when `true` | `true` |
| `MAMBA_MCP_FS_RATE_LIMIT` | Max operations per minute, `0` = disabled | `0` |
| `MAMBA_MCP_FS_ALLOWED_EXTENSIONS` | Comma-separated allowlist of file extensions (e.g. `.py,.txt`) | *(none)* |
| `MAMBA_MCP_FS_DENIED_EXTENSIONS` | Comma-separated denylist of file extensions (e.g. `.exe,.sh`) | *(none)* |

### Local Backend Settings

Prefix: `MAMBA_MCP_FS_LOCAL_`

| Variable | Description | Default |
|----------|-------------|---------|
| `MAMBA_MCP_FS_LOCAL_ENABLED` | Enable local filesystem backend | `true` |
| `MAMBA_MCP_FS_LOCAL_BASE_PATH` | Sandbox root directory | **required** |
| `MAMBA_MCP_FS_LOCAL_MAX_FILE_SIZE` | Max file size in bytes | `10485760` (10 MB) |
| `MAMBA_MCP_FS_LOCAL_FOLLOW_SYMLINKS` | Follow symbolic links | `false` |
| `MAMBA_MCP_FS_LOCAL_SHOW_HIDDEN` | Show hidden files/dotfiles by default | `false` |

### S3 Backend Settings

Prefix: `MAMBA_MCP_FS_S3_`

| Variable | Description | Default |
|----------|-------------|---------|
| `MAMBA_MCP_FS_S3_ENABLED` | Enable S3 backend | `false` |
| `MAMBA_MCP_FS_S3_BUCKET` | Default S3 bucket name | *(none)* |
| `MAMBA_MCP_FS_S3_PREFIX` | Key prefix within bucket | *(empty)* |
| `MAMBA_MCP_FS_S3_REGION` | AWS region | `us-east-1` |
| `MAMBA_MCP_FS_S3_ENDPOINT_URL` | Custom endpoint URL (for MinIO/LocalStack) | *(none -- uses AWS)* |
| `MAMBA_MCP_FS_S3_MAX_FILE_SIZE` | Max file size in bytes | `52428800` (50 MB) |

S3 authentication uses the standard AWS credential chain (environment variables, `~/.aws/credentials`, IAM roles, etc.).

### Example: Local-Only Configuration

```env
# mamba.env -- local filesystem only
MAMBA_MCP_FS_READ_ONLY=true
MAMBA_MCP_FS_LOCAL_ENABLED=true
MAMBA_MCP_FS_LOCAL_BASE_PATH=/home/user/projects
MAMBA_MCP_FS_LOCAL_FOLLOW_SYMLINKS=false
MAMBA_MCP_FS_LOCAL_SHOW_HIDDEN=false
```

### Example: S3 with AWS

```env
# mamba.env -- S3 with AWS
MAMBA_MCP_FS_LOCAL_ENABLED=false
MAMBA_MCP_FS_S3_ENABLED=true
MAMBA_MCP_FS_S3_BUCKET=my-data-bucket
MAMBA_MCP_FS_S3_REGION=us-west-2
MAMBA_MCP_FS_READ_ONLY=true
```

### Example: S3 with LocalStack / MinIO

```env
# mamba.env -- S3 with LocalStack (local development)
MAMBA_MCP_FS_LOCAL_ENABLED=false
MAMBA_MCP_FS_S3_ENABLED=true
MAMBA_MCP_FS_S3_BUCKET=test-bucket
MAMBA_MCP_FS_S3_REGION=us-east-1
MAMBA_MCP_FS_S3_ENDPOINT_URL=http://localhost:4566
MAMBA_MCP_FS_READ_ONLY=false

# LocalStack/MinIO credentials
AWS_ACCESS_KEY_ID=test
AWS_SECRET_ACCESS_KEY=test
```

### Example: Dual Backend (Local + S3)

```env
# mamba.env -- both backends enabled
MAMBA_MCP_FS_READ_ONLY=false
MAMBA_MCP_FS_RATE_LIMIT=60

# Local backend
MAMBA_MCP_FS_LOCAL_ENABLED=true
MAMBA_MCP_FS_LOCAL_BASE_PATH=/home/user/workspace

# S3 backend
MAMBA_MCP_FS_S3_ENABLED=true
MAMBA_MCP_FS_S3_BUCKET=project-artifacts
MAMBA_MCP_FS_S3_REGION=us-east-1
```

When both backends are enabled, paths are auto-detected: `s3://` prefixed paths route to S3, all other paths route to the local backend.

## Tools Reference

### Layer 1: Discovery Tools

Discovery tools are always available. They provide read-only access for browsing and understanding filesystem structure.

#### `list_directory`

List files and directories at a given path with metadata.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `path` | `str` | *required* | Directory path (local or `s3://bucket/prefix`) |
| `backend` | `str \| null` | auto-detect | Force `"local"` or `"s3"` |
| `include_hidden` | `bool \| null` | per config | Include hidden files/dotfiles |
| `pattern` | `str \| null` | all files | Glob pattern filter (e.g. `"*.py"`) |
| `max_entries` | `int` | `1000` | Maximum entries to return (1-10000) |

```json
// Example call
{"path": "/data", "pattern": "*.csv", "max_entries": 50}

// Example response
{
  "path": "/data",
  "backend": "local",
  "entries": [
    {"name": "sales.csv", "type": "file", "size_bytes": 2048, "modified_at": "..."},
    {"name": "reports", "type": "directory", "size_bytes": null, "modified_at": "..."}
  ],
  "total_count": 2,
  "has_more": false
}
```

#### `get_file_info`

Get detailed metadata for a single file or directory, including MIME type, timestamps, symlink status, permissions, and optional SHA-256 checksum.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `path` | `str` | *required* | File or directory path |
| `backend` | `str \| null` | auto-detect | Force `"local"` or `"s3"` |
| `include_checksum` | `bool` | `false` | Calculate SHA-256 checksum |

```json
// Example call
{"path": "/data/report.csv", "include_checksum": true}

// Example response
{
  "path": "/data/report.csv",
  "backend": "local",
  "name": "report.csv",
  "type": "file",
  "size_bytes": 1024,
  "mime_type": "text/csv",
  "modified_at": "2024-01-15T10:30:00Z",
  "created_at": "2024-01-10T08:00:00Z",
  "is_hidden": false,
  "is_symlink": false,
  "permissions": "rw-r--r--",
  "checksum": "a1b2c3d4e5f6..."
}
```

#### `read_file`

Read file contents with smart content type detection. Text files return as text, binary files as base64. Supports chunked reading via offset/limit.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `path` | `str` | *required* | File path to read |
| `backend` | `str \| null` | auto-detect | Force `"local"` or `"s3"` |
| `encoding` | `str` | `"utf-8"` | Text encoding for decoding |
| `offset` | `int` | `0` | Byte offset to start reading |
| `limit` | `int \| null` | entire file | Maximum bytes to read |
| `force_text` | `bool` | `false` | Force text interpretation |
| `force_base64` | `bool` | `false` | Force base64 encoding for all content |

```json
// Example: read a text file
{"path": "/data/config.yaml"}

// Example: read a chunk of a large file
{"path": "/data/large.log", "offset": 0, "limit": 4096}

// Example response
{
  "path": "/data/config.yaml",
  "backend": "local",
  "content": "server:\n  port: 8080\n...",
  "encoding": "text",
  "mime_type": "text/yaml",
  "size_bytes": 512,
  "bytes_read": 512,
  "offset": 0,
  "has_more": false,
  "is_truncated": false
}
```

#### `search_files`

Recursively search for files by name pattern and/or content regex.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `path` | `str` | *required* | Root directory to search from |
| `backend` | `str \| null` | auto-detect | Force `"local"` or `"s3"` |
| `name_pattern` | `str \| null` | all files | Glob pattern for file names (e.g. `"*.py"`) |
| `content_pattern` | `str \| null` | name-only | Regex pattern to search file contents |
| `max_depth` | `int` | `10` | Max recursion depth (0 = current dir only) |
| `max_results` | `int` | `100` | Max results to return (1-10000) |
| `include_hidden` | `bool \| null` | per config | Include hidden files |
| `file_types` | `list[str] \| null` | all types | MIME type prefix filter (e.g. `["text/"]`) |

```json
// Example: find Python files containing "def main"
{
  "path": "/src",
  "name_pattern": "*.py",
  "content_pattern": "def main",
  "max_depth": 5
}

// Example response
{
  "path": "/src",
  "backend": "local",
  "results": [
    {
      "path": "/src/app/main.py",
      "name": "main.py",
      "type": "file",
      "size_bytes": 2048,
      "match_context": "  3: import sys\n> 4: def main():\n  5:     parser = argparse..."
    }
  ],
  "total_matches": 1,
  "search_truncated": false,
  "directories_searched": 12
}
```

### Layer 2: S3 Extras

S3-specific tools are registered only when the S3 backend is enabled (`MAMBA_MCP_FS_S3_ENABLED=true`).

#### `list_buckets`

List all accessible S3 buckets with creation dates and region.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| *(none)* | | | Uses server S3 configuration |

```json
// Example response
{
  "buckets": [
    {"name": "my-data-bucket", "creation_date": "2024-01-01T00:00:00Z", "region": "us-east-1"},
    {"name": "backups", "creation_date": "2023-06-15T00:00:00Z", "region": "us-east-1"}
  ],
  "total_count": 2
}
```

#### `get_presigned_url`

Generate a time-limited presigned URL for downloading or uploading an S3 object.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `path` | `str` | *required* | S3 object path (e.g. `s3://bucket/key`) |
| `operation` | `"download" \| "upload"` | `"download"` | URL operation type |
| `expires_in` | `int` | `3600` | Expiration in seconds (60 to 604800) |

Upload URLs require `read_only=false`. The `expires_in` value is clamped to [60, 604800] (1 minute to 7 days).

```json
// Example: download URL
{"path": "s3://my-bucket/reports/q4.pdf"}

// Example: upload URL (requires read_only=false)
{"path": "s3://my-bucket/uploads/data.csv", "operation": "upload", "expires_in": 7200}

// Example response
{
  "url": "https://my-bucket.s3.amazonaws.com/reports/q4.pdf?X-Amz-...",
  "path": "s3://my-bucket/reports/q4.pdf",
  "operation": "download",
  "expires_at": "2024-01-15T11:30:00Z"
}
```

#### `get_object_metadata`

Retrieve S3-specific metadata for an object, including storage class, ETag, encryption, tags, and version history.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `path` | `str` | *required* | S3 object path (e.g. `s3://bucket/key`) |
| `include_tags` | `bool` | `true` | Include object tags |
| `include_versions` | `bool` | `false` | Include version history |

```json
// Example call
{"path": "s3://my-bucket/data/report.csv", "include_versions": true}

// Example response
{
  "path": "s3://my-bucket/data/report.csv",
  "storage_class": "STANDARD",
  "etag": "\"d41d8cd98f00b204e9800998ecf8427e\"",
  "version_id": "abc123",
  "tags": {"department": "finance", "year": "2024"},
  "versions": [
    {"version_id": "abc123", "is_latest": true, "last_modified": "2024-01-15T10:00:00Z"}
  ],
  "server_side_encryption": "AES256",
  "content_type": "text/csv",
  "last_modified": "2024-01-15T10:00:00Z"
}
```

### Layer 3: Mutation Tools

Mutation tools are registered only when `MAMBA_MCP_FS_READ_ONLY=false`. They require write access to be enabled on the server.

#### `write_file`

Create or overwrite a file with text or base64-encoded content.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `path` | `str` | *required* | Destination file path |
| `content` | `str` | *required* | File content (text or base64 string) |
| `encoding` | `str` | `"text"` | Content encoding: `"text"` or `"base64"` |
| `backend` | `str \| null` | auto-detect | Force `"local"` or `"s3"` |
| `create_parents` | `bool` | `true` | Create parent directories if missing |
| `overwrite` | `bool` | `true` | Allow overwriting existing files |

```json
// Example: write a text file
{"path": "/data/output.txt", "content": "Hello, world!"}

// Example: write binary content
{"path": "/data/image.png", "content": "iVBORw0KGgo...", "encoding": "base64"}

// Example: prevent overwrite
{"path": "/data/config.yaml", "content": "key: value", "overwrite": false}
```

#### `delete_file`

Delete a single file. Does not support directory deletion.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `path` | `str` | *required* | File path to delete |
| `backend` | `str \| null` | auto-detect | Force `"local"` or `"s3"` |

```json
// Example
{"path": "/data/temp/output.txt"}
```

#### `move_file`

Move or rename a file within the same backend. Cross-backend moves are not supported (use `copy_file` + `delete_file` instead).

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `source` | `str` | *required* | Source file path |
| `destination` | `str` | *required* | Destination file path |
| `backend` | `str \| null` | auto-detect | Force `"local"` or `"s3"` |
| `overwrite` | `bool` | `false` | Allow overwriting destination |

```json
// Example: rename a file
{"source": "/data/old_name.txt", "destination": "/data/new_name.txt"}

// Example: move with overwrite
{"source": "/data/draft.txt", "destination": "/data/final.txt", "overwrite": true}
```

#### `copy_file`

Copy a file from source to destination. Supports cross-backend copies (local to S3, S3 to local).

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `source` | `str` | *required* | Source file path |
| `destination` | `str` | *required* | Destination file path |
| `source_backend` | `str \| null` | auto-detect | Force source backend |
| `dest_backend` | `str \| null` | auto-detect | Force destination backend |
| `overwrite` | `bool` | `false` | Allow overwriting destination |

```json
// Example: same-backend copy
{"source": "/data/report.txt", "destination": "/backup/report.txt"}

// Example: cross-backend copy (local to S3)
{"source": "/data/export.csv", "destination": "s3://my-bucket/imports/export.csv"}
```

#### `create_directory`

Create a directory. Idempotent -- returns `created: false` if it already exists. On S3, creates a prefix placeholder object.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `path` | `str` | *required* | Directory path to create |
| `backend` | `str \| null` | auto-detect | Force `"local"` or `"s3"` |
| `parents` | `bool` | `true` | Create parent directories if missing |

```json
// Example
{"path": "/data/reports/2024"}
```

## Security

The server enforces multiple layers of security to prevent unauthorized filesystem access.

### Sandbox Enforcement

All local file operations are confined to the configured `MAMBA_MCP_FS_LOCAL_BASE_PATH` directory. Path traversal attempts (`../`, URL-encoded variants, unicode normalization tricks, null byte injection) are detected and blocked before any filesystem operation occurs.

The sandbox validation process:
1. URL-decodes the path (loops until stable, catching double/triple encoding)
2. Strips null bytes
3. Normalizes unicode to NFC form
4. Resolves to absolute path
5. Verifies the resolved path starts with the sandbox base path (using trailing `/` to prevent prefix attacks like `/sandbox-evil` matching `/sandbox`)

### Symlink Policy

Controlled by `MAMBA_MCP_FS_LOCAL_FOLLOW_SYMLINKS`:

- **`false` (default)**: All symlinks are blocked. Any path that is or passes through a symlink is rejected with a `SYMLINK_BLOCKED` error.
- **`true`**: Symlinks are followed, but the resolved target must still be within the sandbox. Nested symlink chains are fully resolved via `Path.resolve()`.

### Hidden File Policy

Controlled by `MAMBA_MCP_FS_LOCAL_SHOW_HIDDEN`:

- **`false` (default)**: Hidden files (names starting with `.`) are excluded from directory listings and search results.
- **`true`**: Hidden files are included by default.

Individual tool calls can override this with the `include_hidden` parameter.

### Extension Filtering

Controlled by `MAMBA_MCP_FS_ALLOWED_EXTENSIONS` and `MAMBA_MCP_FS_DENIED_EXTENSIONS`:

- **Allowlist** (takes precedence if set): Only files with listed extensions are accessible. Example: `.py,.txt,.md`
- **Denylist**: Files with listed extensions are blocked. Example: `.exe,.sh,.bat`
- **Neither set**: All extensions are allowed.

Extension checks are applied during write operations and path validation.

### Size Limits

Each backend has an independent maximum file size:

- **Local**: `MAMBA_MCP_FS_LOCAL_MAX_FILE_SIZE` (default 10 MB)
- **S3**: `MAMBA_MCP_FS_S3_MAX_FILE_SIZE` (default 50 MB)

Full file reads that exceed the limit are rejected. Chunked reads (with `offset`/`limit`) bypass the size check, allowing AI assistants to read portions of large files.

### Rate Limiting

Controlled by `MAMBA_MCP_FS_RATE_LIMIT`:

- **`0` (default)**: Rate limiting disabled.
- **Any positive integer**: Maximum operations per 60-second sliding window.

When exceeded, the server returns a `RATE_LIMITED` error with a `retry_after` value indicating how long to wait.

## Transports

### STDIO (Default)

The default transport. The server communicates via standard input/output, suitable for direct process spawning by MCP clients.

```bash
# Start with STDIO
mamba-mcp-fs

# Or explicitly
MAMBA_MCP_FS_TRANSPORT=stdio mamba-mcp-fs
```

### Streamable HTTP

For network-accessible deployments. The server listens on a configurable host and port.

```bash
# Start with HTTP transport
MAMBA_MCP_FS_TRANSPORT=streamable-http \
MAMBA_MCP_FS_SERVER_HOST=0.0.0.0 \
MAMBA_MCP_FS_SERVER_PORT=8080 \
mamba-mcp-fs
```

Or with a CLI override:

```bash
mamba-mcp-fs --transport streamable-http
```

## Development

### Running Tests

```bash
# All mamba-mcp-fs tests
pytest packages/mamba-mcp-fs/tests/

# Specific test file
pytest packages/mamba-mcp-fs/tests/test_config.py

# Specific test class
pytest packages/mamba-mcp-fs/tests/test_tools/test_discovery.py::TestListDirectoryBasic

# With coverage
pytest packages/mamba-mcp-fs/tests/ --cov=mamba_mcp_fs
```

### Linting and Formatting

```bash
# Lint
ruff check packages/mamba-mcp-fs/

# Format
ruff format packages/mamba-mcp-fs/

# Type check
mypy packages/mamba-mcp-fs/
```

### LocalStack Setup for S3 Testing

For local S3 development and testing:

```bash
# Start LocalStack
docker run -d --name localstack \
  -p 4566:4566 \
  -e SERVICES=s3 \
  localstack/localstack

# Create a test bucket
aws --endpoint-url=http://localhost:4566 s3 mb s3://test-bucket

# Configure mamba-mcp-fs
export MAMBA_MCP_FS_S3_ENABLED=true
export MAMBA_MCP_FS_S3_BUCKET=test-bucket
export MAMBA_MCP_FS_S3_ENDPOINT_URL=http://localhost:4566
export AWS_ACCESS_KEY_ID=test
export AWS_SECRET_ACCESS_KEY=test
```

### MinIO Setup for S3 Testing

Alternatively, use MinIO:

```bash
# Start MinIO
docker run -d --name minio \
  -p 9000:9000 -p 9001:9001 \
  -e MINIO_ROOT_USER=minioadmin \
  -e MINIO_ROOT_PASSWORD=minioadmin \
  minio/minio server /data --console-address ":9001"

# Configure mamba-mcp-fs
export MAMBA_MCP_FS_S3_ENABLED=true
export MAMBA_MCP_FS_S3_ENDPOINT_URL=http://localhost:9000
export AWS_ACCESS_KEY_ID=minioadmin
export AWS_SECRET_ACCESS_KEY=minioadmin
```

## License

MIT
