# GitLab MCP Server

The GitLab MCP Server (`mamba-mcp-gitlab`) exposes 18 MCP tools for interacting with GitLab merge requests, issues, CI/CD pipelines, and search. It connects to any GitLab instance (self-managed or GitLab.com) using either a Personal Access Token or OAuth 2.0 client credentials, with optional read-only mode and client-side rate limiting.

## Overview

```mermaid
graph LR
    A[MCP Client] -->|stdio / streamable-http| B[mamba-mcp-gitlab]
    B -->|httpx async| C[GitLab API v4]
    B --- D[Rate Limiter]
    B --- E[Auth Strategy]
    E -->|PAT| C
    E -->|OAuth 2.0| C
```

| Feature | Details |
|---|---|
| **Tools** | 18 across 4 categories |
| **Authentication** | Personal Access Token (PAT) or OAuth 2.0 client credentials |
| **Read-only mode** | Runtime gating on 5 write tools |
| **Rate limiting** | Sliding window, configurable requests/window |
| **HTTP client** | `httpx` async with connection pooling |
| **Transport** | `stdio` (default), `streamable-http` |

## Installation

```bash
pip install mamba-mcp-gitlab
```

Or within the monorepo workspace:

```bash
uv sync --group dev
```

??? info "Dependencies"
    | Package | Version | Purpose |
    |---|---|---|
    | `mamba-mcp-core` | workspace | Shared CLI, errors, fuzzy matching |
    | `mcp` | `>=1.0.0` | FastMCP server framework |
    | `httpx` | `>=0.27.0` | Async HTTP client |
    | `pydantic` | `>=2.0.0` | Data models and validation |
    | `pydantic-settings` | `>=2.0.0` | Environment-based configuration |
    | `typer` | `>=0.12.0` | CLI framework |

## Quick Start

### 1. Create a configuration file

=== "Personal Access Token"

    ```env title="mamba.env"
    MAMBA_MCP_GITLAB_URL=https://gitlab.example.com
    MAMBA_MCP_GITLAB_TOKEN=glpat-xxxxxxxxxxxxxxxxxxxx
    MAMBA_MCP_GITLAB_DEFAULT_PROJECT_ID=123
    ```

=== "OAuth 2.0"

    ```env title="mamba.env"
    MAMBA_MCP_GITLAB_URL=https://gitlab.example.com
    MAMBA_MCP_GITLAB_OAUTH_CLIENT_ID=your-client-id
    MAMBA_MCP_GITLAB_OAUTH_CLIENT_SECRET=your-client-secret
    ```

### 2. Test connectivity

```bash
mamba-mcp-gitlab --env-file mamba.env test
```

A successful test prints the authenticated username and token scopes:

```
Connection successful — authenticated as myuser with scopes: api
```

### 3. Start the server

```bash
# STDIO transport (default)
mamba-mcp-gitlab --env-file mamba.env

# Streamable HTTP transport
MAMBA_MCP_GITLAB_SERVER_TRANSPORT=streamable-http mamba-mcp-gitlab
```

### 4. Connect with mamba-mcp-client

```bash
uv run --package mamba-mcp-client mamba-mcp tools --stdio "mamba-mcp-gitlab"
uv run --package mamba-mcp-client mamba-mcp call list_mrs \
  --args '{"project_id": 123, "state": "opened"}' \
  --stdio "mamba-mcp-gitlab"
```

## Configuration

Configuration is loaded from environment variables or a `mamba.env` file (auto-discovered in the current directory or `~/mamba.env`). Use `--env-file` to specify a custom path.

### GitLab Settings

Prefix: `MAMBA_MCP_GITLAB_`

| Variable | Type | Default | Description |
|---|---|---|---|
| `URL` | `str` | **required** | GitLab instance URL (e.g., `https://gitlab.example.com`) |
| `TOKEN` | `SecretStr` | `None` | Personal Access Token for PAT authentication |
| `VERIFY_SSL` | `bool` | `true` | Whether to verify SSL certificates |
| `DEFAULT_PROJECT_ID` | `int` | `None` | Default project scope when `project_id` is omitted |
| `DEFAULT_GROUP_ID` | `int` | `None` | Default group scope for search operations |
| `READ_ONLY` | `bool` | `false` | Block write tools at runtime |

### OAuth Settings

Prefix: `MAMBA_MCP_GITLAB_OAUTH_`

| Variable | Type | Default | Description |
|---|---|---|---|
| `CLIENT_ID` | `str` | `None` | OAuth 2.0 application client ID |
| `CLIENT_SECRET` | `SecretStr` | `None` | OAuth 2.0 application client secret |
| `REDIRECT_URI` | `str` | `None` | OAuth 2.0 redirect URI |

### Server Settings

Prefix: `MAMBA_MCP_GITLAB_SERVER_`

| Variable | Type | Default | Description |
|---|---|---|---|
| `TRANSPORT` | `str` | `stdio` | Transport type: `stdio`, `http`, or `streamable-http` |
| `SERVER_HOST` | `str` | `127.0.0.1` | HTTP server bind address |
| `SERVER_PORT` | `int` | `8004` | HTTP server bind port (1--65535) |
| `LOG_LEVEL` | `str` | `INFO` | Logging level |
| `LOG_FORMAT` | `str` | `text` | Log format: `json` or `text` |
| `MAX_CONNECTIONS` | `int` | `10` | Maximum concurrent HTTP connections to GitLab (1--100) |

!!! tip "Transport normalization"
    Both `http` and `streamable-http` are accepted as transport values. The server normalizes `http` to `streamable-http` internally via `mamba-mcp-core`.

### Rate Limit Settings

Prefix: `MAMBA_MCP_GITLAB_RATE_LIMIT_`

| Variable | Type | Default | Description |
|---|---|---|---|
| `MAX_REQUESTS` | `int` | `100` | Maximum requests per time window (0 disables) |
| `WINDOW_SECONDS` | `int` | `60` | Sliding window duration in seconds |

## Tool Reference

All 18 tools are organized into four categories. Every tool returns a structured Pydantic output model on success or a structured `ToolError` dict on failure. Pagination parameters (`page`, `per_page`) are automatically clamped to valid ranges (page >= 1, per_page in 1--100, default 20).

!!! info "Project ID resolution"
    When `project_id` is omitted from a tool call, the server falls back to the configured `MAMBA_MCP_GITLAB_DEFAULT_PROJECT_ID`. If neither is set, a `VALIDATION_ERROR` is returned.

### Merge Requests (7 tools)

#### `list_mrs`

List merge requests for a GitLab project. Use this as the entry point for discovering available MRs.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `project_id` | `int \| str` | No | Project ID or URL-encoded path. Falls back to default. |
| `state` | `str` | No | Filter: `opened`, `closed`, `merged`, `all` |
| `page` | `int` | No | Page number (1-based). Default: 1. |
| `per_page` | `int` | No | Items per page (1--100). Default: 20. |

**Returns:** `ListMergeRequestsOutput` -- paginated list of `MergeRequestSummary` items with `id`, `iid`, `title`, `state`, `author`, `source_branch`, `target_branch`, `web_url`, and timestamps.

---

#### `get_mr`

Get full details of a single merge request, including description, assignees, reviewers, labels, merge status, diff refs, and pipeline.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `project_id` | `int \| str` | No | Project ID or URL-encoded path |
| `mr_iid` | `int` | Yes | Merge request IID (project-level identifier) |

**Returns:** `MergeRequestDetail` -- extends summary with `description`, `assignees`, `reviewers`, `labels`, `merge_status`, `diff_refs`, and `pipeline`.

---

#### `get_mr_diffs`

Get file-level diffs for a merge request. Each diff includes old/new paths and unified diff content. Useful for code review.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `project_id` | `int \| str` | No | Project ID or URL-encoded path |
| `mr_iid` | `int` | Yes | Merge request IID |
| `page` | `int` | No | Page number. Default: 1. |
| `per_page` | `int` | No | Items per page. Default: 20. |

**Returns:** `MergeRequestDiffsOutput` -- paginated list of `MergeRequestDiff` items with `old_path`, `new_path`, `diff`, `new_file`, `renamed_file`, `deleted_file`.

---

#### `get_mr_commits`

Get the list of commits included in a merge request.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `project_id` | `int \| str` | No | Project ID or URL-encoded path |
| `mr_iid` | `int` | Yes | Merge request IID |
| `page` | `int` | No | Page number. Default: 1. |
| `per_page` | `int` | No | Items per page. Default: 20. |

**Returns:** `MergeRequestCommitsOutput` -- paginated list of `MergeRequestCommit` items with `id` (full SHA), `short_id`, `title`, `author_name`, `authored_date`, `message`.

---

#### `get_mr_pipelines`

Get pipelines associated with a merge request. Use this to check whether CI is passing before merging.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `project_id` | `int \| str` | No | Project ID or URL-encoded path |
| `mr_iid` | `int` | Yes | Merge request IID |
| `page` | `int` | No | Page number. Default: 1. |
| `per_page` | `int` | No | Items per page. Default: 20. |

**Returns:** `ListPipelinesOutput` -- paginated list of `PipelineSummary` items.

---

#### `create_mr` :material-pencil:{ title="Write tool" }

!!! warning "Write Tool"
    Blocked when `MAMBA_MCP_GITLAB_READ_ONLY=true`. Returns a `READ_ONLY` error.

Create a new merge request from a source branch to a target branch.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `project_id` | `int \| str` | No | Project ID or URL-encoded path |
| `title` | `str` | Yes | Merge request title |
| `source_branch` | `str` | Yes | Source branch name |
| `target_branch` | `str` | Yes | Target branch name |
| `description` | `str` | No | MR description (Markdown) |
| `assignee_ids` | `list[int]` | No | User IDs to assign |
| `reviewer_ids` | `list[int]` | No | User IDs to request review from |
| `labels` | `list[str]` | No | Label names to apply |

**Returns:** `MergeRequestDetail` -- the full details of the created merge request.

---

#### `update_mr` :material-pencil:{ title="Write tool" }

!!! warning "Write Tool"
    Blocked when `MAMBA_MCP_GITLAB_READ_ONLY=true`. Returns a `READ_ONLY` error.

Update fields on an existing merge request. Only provided fields are modified.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `project_id` | `int \| str` | No | Project ID or URL-encoded path |
| `mr_iid` | `int` | Yes | Merge request IID |
| `title` | `str` | No | New title |
| `description` | `str` | No | New description (Markdown) |
| `assignee_ids` | `list[int]` | No | New assignee user IDs |
| `reviewer_ids` | `list[int]` | No | New reviewer user IDs |
| `labels` | `list[str]` | No | New label names |
| `state_event` | `str` | No | State transition: `close` or `reopen` |

**Returns:** `MergeRequestDetail` -- the updated merge request.

---

### Issues (6 tools)

#### `list_issues`

List issues for a project with optional filters for state, labels, and assignee.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `project_id` | `int \| str` | Yes | Project ID or URL-encoded path |
| `state` | `str` | No | Filter: `opened`, `closed`, `all` |
| `labels` | `str` | No | Comma-separated label names (e.g., `"bug,urgent"`) |
| `assignee_id` | `int` | No | Filter by a single assignee user ID |
| `page` | `int` | No | Page number. Default: 1. |
| `per_page` | `int` | No | Items per page. Default: 20. |

**Returns:** `ListIssuesOutput` -- paginated list of `IssueSummary` items with `id`, `iid`, `title`, `state`, `author`, `assignees`, `labels`, `web_url`, and timestamps.

---

#### `get_issue`

Get full details of a single issue by its project-level IID.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `project_id` | `int \| str` | Yes | Project ID or URL-encoded path |
| `issue_iid` | `int` | Yes | Project-level issue IID |

**Returns:** `IssueDetail` -- extends summary with `description`, `milestone`, `user_notes_count`, `upvotes`, `downvotes`.

---

#### `list_issue_comments`

List comments (notes) on a specific issue, including both user and system-generated notes.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `project_id` | `int \| str` | Yes | Project ID or URL-encoded path |
| `issue_iid` | `int` | Yes | Project-level issue IID |
| `page` | `int` | No | Page number. Default: 1. |
| `per_page` | `int` | No | Items per page. Default: 20. |

**Returns:** `IssueCommentsOutput` -- paginated list of `IssueComment` items with `id`, `body`, `author`, `created_at`, `updated_at`, `system`.

---

#### `create_issue` :material-pencil:{ title="Write tool" }

!!! warning "Write Tool"
    Blocked when `MAMBA_MCP_GITLAB_READ_ONLY=true`. Returns a `READ_ONLY` error.

Create a new issue in a GitLab project.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `project_id` | `int \| str` | Yes | Project ID or URL-encoded path |
| `title` | `str` | Yes | Issue title |
| `description` | `str` | No | Issue description (Markdown) |
| `assignee_ids` | `list[int]` | No | User IDs to assign |
| `labels` | `str` | No | Comma-separated label names |
| `milestone_id` | `int` | No | Milestone ID to associate |

**Returns:** `IssueDetail` -- the full details of the created issue.

---

#### `update_issue` :material-pencil:{ title="Write tool" }

!!! warning "Write Tool"
    Blocked when `MAMBA_MCP_GITLAB_READ_ONLY=true`. Returns a `READ_ONLY` error.

Update fields on an existing issue. Only provided fields are modified. Labels replace the full set when provided.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `project_id` | `int \| str` | Yes | Project ID or URL-encoded path |
| `issue_iid` | `int` | Yes | Issue IID to update |
| `title` | `str` | No | New title |
| `description` | `str` | No | New description (Markdown) |
| `assignee_ids` | `list[int]` | No | New assignee user IDs |
| `labels` | `str` | No | New comma-separated label names |
| `state_event` | `str` | No | State transition: `close` or `reopen` |

**Returns:** `IssueDetail` -- the updated issue.

---

#### `add_issue_comment` :material-pencil:{ title="Write tool" }

!!! warning "Write Tool"
    Blocked when `MAMBA_MCP_GITLAB_READ_ONLY=true`. Returns a `READ_ONLY` error.

Add a comment (note) to an existing issue. Supports Markdown formatting.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `project_id` | `int \| str` | Yes | Project ID or URL-encoded path |
| `issue_iid` | `int` | Yes | Issue IID to comment on |
| `body` | `str` | Yes | Comment text (Markdown) |

**Returns:** `IssueComment` -- the newly created comment with `id`, `body`, `author`, `created_at`, `system`.

---

### Pipelines (4 tools)

All pipeline tools are read-only and always available regardless of the `READ_ONLY` setting.

#### `list_pipelines`

List CI/CD pipelines for a project with optional status and ref filters.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `project_id` | `int \| str` | Yes | Project ID or URL-encoded path |
| `status` | `str` | No | Filter: `running`, `pending`, `success`, `failed`, `canceled`, `skipped` |
| `ref` | `str` | No | Filter by git ref (branch or tag name) |
| `page` | `int` | No | Page number. Default: 1. |
| `per_page` | `int` | No | Items per page. Default: 20. |

**Returns:** `ListPipelinesOutput` -- paginated list of `PipelineSummary` items with `id`, `iid`, `status`, `ref`, `sha`, `web_url`, and timestamps.

---

#### `get_pipeline`

Get full details of a single pipeline, including duration, coverage, and trigger user.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `project_id` | `int \| str` | Yes | Project ID or URL-encoded path |
| `pipeline_id` | `int` | Yes | Pipeline ID |

**Returns:** `PipelineDetail` -- extends summary with `duration`, `started_at`, `finished_at`, `coverage`, `user`.

---

#### `get_pipeline_jobs`

Get the list of jobs within a specific pipeline.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `project_id` | `int \| str` | Yes | Project ID or URL-encoded path |
| `pipeline_id` | `int` | Yes | Pipeline ID |
| `page` | `int` | No | Page number. Default: 1. |
| `per_page` | `int` | No | Items per page. Default: 20. |

**Returns:** `PipelineJobsOutput` -- paginated list of `PipelineJob` items with `id`, `name`, `stage`, `status`, `duration`, `runner`, `web_url`.

---

#### `get_job_log`

Get the text log output of a specific CI/CD job. Large logs are automatically truncated.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `project_id` | `int \| str` | Yes | Project ID or URL-encoded path |
| `job_id` | `int` | Yes | Job ID |
| `max_bytes` | `int` | No | Max log size in bytes (1,024--1,048,576). Default: 102,400 (100KB). |

**Returns:** `JobLogOutput` -- `content` (log text), `truncated` (bool), `byte_count` (total bytes before truncation).

---

### Search (1 tool)

#### `search`

Search across GitLab resources at the instance, project, or group level.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `query` | `str` | Yes | Search query string |
| `scope` | `str` | Yes | Resource scope: `issues`, `merge_requests`, `projects`, `milestones`, etc. |
| `project_id` | `int \| str` | No | Project ID for project-scoped search |
| `group_id` | `int` | No | Group ID for group-scoped search |
| `page` | `int` | No | Page number. Default: 1. |
| `per_page` | `int` | No | Items per page. Default: 20. |

!!! info "Scope resolution priority"
    1. Explicit `project_id` parameter
    2. Explicit `group_id` parameter
    3. Configured `DEFAULT_PROJECT_ID`
    4. Configured `DEFAULT_GROUP_ID`
    5. Instance-wide search (no scope)

**Returns:** `SearchOutput` -- paginated list of `SearchResult` items. Each result has a `type` (the scope) and a `data` dict containing the resource-specific payload from the GitLab API.

## Authentication

The server supports two authentication strategies. PAT is simpler; OAuth 2.0 is better suited for service accounts and automated environments.

### Personal Access Token (PAT)

The server sends a `PRIVATE-TOKEN` header with each API request. On startup, it validates the token by calling `GET /api/v4/personal_access_tokens/self` and checks that the token is:

- Active (not expired)
- Not revoked
- Has at least one of the required scopes: `api` or `read_api`

=== "Configuration"

    ```env title="mamba.env"
    MAMBA_MCP_GITLAB_URL=https://gitlab.example.com
    MAMBA_MCP_GITLAB_TOKEN=glpat-xxxxxxxxxxxxxxxxxxxx
    ```

=== "Generating a Token"

    1. Navigate to **GitLab > User Settings > Access Tokens**
    2. Set a descriptive name (e.g., `mamba-mcp`)
    3. Select the `api` scope (or `read_api` for read-only usage)
    4. Set an expiration date
    5. Copy the token value into your `mamba.env`

### OAuth 2.0 (Client Credentials)

The server obtains a Bearer token via `POST /oauth/token` with `grant_type=client_credentials`. The token is automatically refreshed 30 seconds before expiry. Validation is performed against `GET /api/v4/user`.

=== "Configuration"

    ```env title="mamba.env"
    MAMBA_MCP_GITLAB_URL=https://gitlab.example.com
    MAMBA_MCP_GITLAB_OAUTH_CLIENT_ID=your-client-id
    MAMBA_MCP_GITLAB_OAUTH_CLIENT_SECRET=your-client-secret
    ```

=== "Creating an OAuth Application"

    1. Navigate to **GitLab > Admin > Applications** (instance-level) or **User Settings > Applications**
    2. Set the name and callback URL
    3. Enable `client_credentials` grant type
    4. Select the required scopes (`api` or `read_api`)
    5. Save and copy the client ID and secret

### Comparison

| Feature | PAT | OAuth 2.0 |
|---|---|---|
| **Setup complexity** | Simple -- single token | Moderate -- requires OAuth app setup |
| **Auth header** | `PRIVATE-TOKEN: {token}` | `Authorization: Bearer {token}` |
| **Token rotation** | Manual | Automatic (30s pre-expiry refresh) |
| **User binding** | Tied to a specific user | Tied to an OAuth application |
| **Scope control** | Token-level scopes | OAuth application scopes |
| **Best for** | Development, personal use | CI/CD, service accounts, production |

!!! tip "Auth priority"
    If both `TOKEN` and `OAUTH_CLIENT_ID`/`OAUTH_CLIENT_SECRET` are configured, PAT takes precedence. Clear `MAMBA_MCP_GITLAB_TOKEN` to use OAuth instead.

## Read-Only Mode

Setting `MAMBA_MCP_GITLAB_READ_ONLY=true` disables all write operations at runtime. The 5 affected tools are:

| Tool | Category |
|---|---|
| `create_mr` | Merge Requests |
| `update_mr` | Merge Requests |
| `create_issue` | Issues |
| `update_issue` | Issues |
| `add_issue_comment` | Issues |

When a write tool is called in read-only mode, the server returns a structured error:

```json
{
  "error": true,
  "code": "READ_ONLY",
  "message": "Tool 'create_mr' is disabled in read-only mode",
  "tool_name": "create_mr",
  "suggestion": "This server is running in read-only mode. Set MAMBA_MCP_GITLAB_READ_ONLY=false to enable write operations."
}
```

!!! tip "Read-only with `read_api` scope"
    When running in read-only mode, a token with only the `read_api` scope is sufficient. This reduces the blast radius of a compromised token.

All 13 read tools (list, get, and search operations) remain fully functional in read-only mode.

## Rate Limiting

The server implements client-side rate limiting using a sliding window algorithm to prevent overwhelming the GitLab API.

### How it works

1. Each API request records a timestamp in a sliding window
2. Before each request, timestamps older than `WINDOW_SECONDS` are pruned
3. If the number of timestamps in the window reaches `MAX_REQUESTS`, the request is rejected
4. The rejection includes a `retry_after` value indicating when the next request will be allowed

### Configuration

```env title="mamba.env"
# 100 requests per 60-second window (default)
MAMBA_MCP_GITLAB_RATE_LIMIT_MAX_REQUESTS=100
MAMBA_MCP_GITLAB_RATE_LIMIT_WINDOW_SECONDS=60

# Disable rate limiting
MAMBA_MCP_GITLAB_RATE_LIMIT_MAX_REQUESTS=0
```

### Error response

When the rate limit is exceeded, the tool returns:

```json
{
  "error": true,
  "code": "RATE_LIMITED",
  "message": "Rate limit exceeded: 100 requests per 60s window. Try again in 12.3 seconds.",
  "tool_name": "list_mrs",
  "suggestion": "GitLab API rate limit reached. Wait before retrying."
}
```

!!! note "Client-side only"
    This is a client-side limiter protecting the GitLab instance. GitLab's own server-side rate limits still apply. If the GitLab API returns HTTP 429, the server maps it to a `RATE_LIMITED` error with the same structured format.

## Service Architecture

The server follows a layered architecture separating tool handlers from API communication.

```mermaid
graph TD
    subgraph "MCP Tool Handlers"
        MR["mr_tools.py<br/>(7 tools)"]
        IS["issue_tools.py<br/>(6 tools)"]
        PL["pipeline_tools.py<br/>(4 tools)"]
        SE["search_tools.py<br/>(1 tool)"]
    end

    subgraph "Service Layer"
        MRS["MergeRequestService"]
        ISS["IssueService"]
        PLS["PipelineService"]
        SES["SearchService"]
    end

    BASE["GitLabService (base)"]

    MR --> MRS
    IS --> ISS
    PL --> PLS
    SE --> SES
    MRS --> BASE
    ISS --> BASE
    PLS --> BASE
    SES --> BASE
    BASE -->|httpx| GL["GitLab API v4"]

    subgraph "Shared Infrastructure"
        RL["RateLimiter"]
        AUTH["AuthStrategy"]
        CFG["Settings"]
    end

    BASE --> RL
    BASE --> CFG
```

### `GitLabService` (base class)

All four service classes inherit from `GitLabService`, which provides:

- **HTTP methods:** `_get()`, `_post()`, `_put()` for GitLab API calls
- **Pagination:** `_get_paginated()` extracts `x-total` and `x-total-pages` headers
- **URL construction:** `_build_project_url()` handles both integer IDs and URL-encoded paths
- **Project ID resolution:** `_resolve_project_id()` falls back to the configured default
- **Error mapping:** HTTP status codes are mapped to `ErrorCode` constants (401 to `AUTH_FAILED`, 403 to `FORBIDDEN`, 404 to `NOT_FOUND`, 429 to `RATE_LIMITED`, 5xx to `API_ERROR`)
- **Rate limiting:** Every request checks the rate limiter before execution

### Tool handler pattern

Every tool handler follows the same 7-step skeleton:

```python title="Tool handler skeleton"
@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, ...))
async def tool_name(params, ctx=None):
    # 1. Start timer
    start_time = time.perf_counter()

    # 2. Null-check context
    if ctx is None:
        return create_tool_error(...)

    # 3. Extract AppContext from lifespan
    app_ctx = ctx.request_context.lifespan_context

    # 4. (Write tools only) Check read-only mode
    # 5. Create service, delegate to service method
    # 6. Convert result to Pydantic output model
    # 7. Catch GitLabAPIError → structured error; catch Exception → CONNECTION_ERROR
```

### Error codes

| Code | HTTP Status | Description |
|---|---|---|
| `AUTH_FAILED` | 401 | Token is invalid or expired |
| `FORBIDDEN` | 403 | Token lacks required scopes |
| `NOT_FOUND` | 404 | Resource not found |
| `PROJECT_NOT_FOUND` | -- | Project does not exist |
| `MERGE_REQUEST_NOT_FOUND` | -- | MR IID not found in project |
| `ISSUE_NOT_FOUND` | -- | Issue IID not found in project |
| `PIPELINE_NOT_FOUND` | -- | Pipeline ID not found |
| `BRANCH_NOT_FOUND` | -- | Branch does not exist |
| `RATE_LIMITED` | 429 | Rate limit exceeded (client or server) |
| `VALIDATION_ERROR` | 400 | Invalid input parameters |
| `CONNECTION_ERROR` | -- | Cannot reach GitLab |
| `API_ERROR` | 5xx | GitLab server error |
| `READ_ONLY` | -- | Write tool blocked in read-only mode |

Each error code has a default suggestion message. Errors involving resource names (projects, branches) include fuzzy matching via Levenshtein distance to suggest similar names.

## CLI Reference

```bash
# Start server (default: stdio transport)
mamba-mcp-gitlab [--env-file PATH]

# Test connectivity and token validity
mamba-mcp-gitlab [--env-file PATH] test
```

The CLI auto-discovers `mamba.env` in the current directory or `~/mamba.env` if `--env-file` is not specified.
