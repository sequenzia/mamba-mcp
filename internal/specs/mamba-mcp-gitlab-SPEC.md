# mamba-mcp-gitlab PRD

**Version**: 1.0
**Author**: Stephen Sequenzia
**Date**: 2026-02-02
**Status**: Draft
**Spec Type**: New feature
**Spec Depth**: Detailed specifications
**Description**: A Python-based MCP Server for self-hosted enterprise GitLab, providing AI coding assistants with tools to manage Merge Requests, Issues, Pipelines, and Search via GitLab REST API v4.

---

## 1. Executive Summary

mamba-mcp-gitlab is a new MCP server package for the mamba-mcp monorepo that enables AI coding assistants (Claude, Copilot, etc.) to interact with self-hosted enterprise GitLab instances. The MVP provides 17 MCP tools across four resource categories — Merge Requests, Issues, Pipelines, and Search — with dual authentication (PAT + OAuth 2.0), a read-only mode, and client-side rate limiting. The server follows the established mamba-mcp patterns (FastMCP, layered architecture, Pydantic settings) for consistency across the monorepo.

## 2. Problem Statement

### 2.1 The Problem

Developers using AI coding assistants need to interact with their GitLab instance during development workflows — reviewing merge requests, managing issues, checking pipeline status, and searching for relevant context. Currently, there is no MCP-compatible server in the mamba-mcp ecosystem that supports self-hosted enterprise GitLab instances. GitLab's official MCP server requires Premium/Ultimate tier and uses their hosted `/api/v4/mcp` endpoint, which may not be available or suitable for all enterprise deployments.

### 2.2 Current State

- GitLab's official MCP server (beta, GitLab 18.6+) requires Premium/Ultimate tier and OAuth 2.0 Dynamic Client Registration
- No open-source MCP server exists that targets self-hosted GitLab with simple PAT authentication
- Developers must manually switch between their AI assistant and GitLab's web UI for MR reviews, issue management, and pipeline checks
- The mamba-mcp monorepo already has patterns for PG, FS, and HANA servers but no source control / project management server

### 2.3 Impact Analysis

Without this server:
- AI-assisted development workflows are incomplete when the team's source control is GitLab
- Developers lose context switching between AI tools and GitLab's UI
- Enterprise teams with self-hosted GitLab and restricted tiers cannot use GitLab's official MCP server
- The mamba-mcp ecosystem lacks coverage for source control management, a core developer workflow

### 2.4 Business Value

- Completes the developer workflow coverage in the mamba-mcp ecosystem (database + filesystem + source control)
- Enables AI-assisted code review, issue triage, and pipeline monitoring for enterprise GitLab teams
- Provides a self-hosted alternative that works with any GitLab tier (Community, Premium, Ultimate)
- Follows established monorepo patterns, reducing development and maintenance overhead

## 3. Goals & Success Metrics

### 3.1 Primary Goals

1. Provide a fully functional MCP server for self-hosted enterprise GitLab with 17 tools across MRs, Issues, Pipelines, and Search
2. Support dual authentication (PAT for simplicity, OAuth 2.0 for enterprise SSO) with auto-detection
3. Follow all established mamba-mcp patterns (layered architecture, AppContext lifespan, Pydantic settings, error triad)

### 3.2 Success Metrics

| Metric | Current Baseline | Target | Measurement Method | Timeline |
|--------|------------------|--------|-------------------|----------|
| MCP tool coverage | 0 GitLab tools | 17 tools across 4 categories | Tool registration count | Phase 2 |
| Auth methods supported | N/A | 2 (PAT + OAuth 2.0) | Integration test | Phase 1 |
| Test coverage | N/A | >80% for service layer, 100% for error handling | pytest coverage report | Phase 3 |
| API response latency | N/A | <500ms P95 for single-resource queries | Tool handler timing logs | Phase 3 |

### 3.3 Non-Goals

- This is NOT a replacement for GitLab's official MCP server — it targets a different deployment model (self-hosted, any tier)
- This does NOT aim to replicate all 14 tools from GitLab's official MCP server — the tool set is tailored for AI-assisted developer workflows
- This does NOT support GitLab.com SaaS-specific features (GitLab Duo, Duo Chat integration)
- This does NOT implement WebSocket/real-time event subscriptions — tools are request/response only

## 4. User Research

### 4.1 Target Users

#### Primary Persona: AI-Assisted Developer

- **Role/Description**: Software developer using AI coding assistants (Claude Code, GitHub Copilot, etc.) connected via MCP
- **Goals**: Review merge requests, manage issues, check pipeline status, and search for context — all without leaving their AI assistant
- **Pain Points**: Constant context switching between AI tools and GitLab UI; inability to have AI assistants directly interact with GitLab resources
- **Context**: During development workflows — code review, bug triage, feature planning, CI/CD monitoring

#### Secondary Persona: DevOps/Platform Engineer

- **Role/Description**: Engineer responsible for configuring and maintaining developer tooling and MCP server infrastructure
- **Goals**: Deploy and configure the GitLab MCP server for the team with appropriate security controls
- **Pain Points**: Complex auth setup, lack of read-only mode for safe deployments, poor error messages when misconfigured

### 4.2 User Journey Map

```
[Developer starts AI session]
  --> [AI assistant connects to mamba-mcp-gitlab via MCP]
  --> [Server authenticates with GitLab (PAT or OAuth)]
  --> [Developer asks AI to "review the latest MR on project X"]
  --> [AI calls list_mrs → get_mr → get_mr_diffs]
  --> [AI presents review with context from diffs]
  --> [Developer asks AI to "create an issue for this bug"]
  --> [AI calls create_issue with structured data]
  --> [Developer asks "is the pipeline passing?"]
  --> [AI calls get_mr_pipelines → get_pipeline_jobs]
  --> [AI reports pipeline status with job details]
```

## 5. Functional Requirements

### 5.1 Feature: Merge Request Tools

**Priority**: P0 (Critical)

#### User Stories

**US-001**: As a developer, I want to list and view merge requests so that my AI assistant can help me review code changes.

**Acceptance Criteria**:
- [ ] `list_mrs` returns paginated list of MRs for a project with state filter (opened/closed/merged/all)
- [ ] `get_mr` returns full MR details including title, description, author, assignees, labels, state, and URLs
- [ ] `get_mr_diffs` returns file-level diff information for an MR
- [ ] `get_mr_commits` returns the list of commits in an MR with pagination
- [ ] All tools respect optional project/group scope from config
- [ ] All tools return structured Pydantic output models

**US-002**: As a developer, I want to create and update merge requests so that my AI assistant can help me manage MRs.

**Acceptance Criteria**:
- [ ] `create_mr` creates an MR with title, source_branch, target_branch, description, assignees, reviewers, labels
- [ ] `update_mr` updates MR fields (title, description, assignees, reviewers, labels, state_event)
- [ ] Mutation tools are NOT registered when `read_only=true`
- [ ] Both tools validate required parameters and return structured errors for invalid input

**Edge Cases**:
- MR with no diff (empty MR): Return empty diffs list with appropriate message
- Project not found: Return NOT_FOUND error with fuzzy project name suggestions
- Branch not found for create: Return BRANCH_NOT_FOUND error with available branches suggestion

**MCP Tool Definitions**:

| Tool | Type | Parameters | Returns |
|------|------|-----------|---------|
| `list_mrs` | Read | `project_id`, `state?`, `page?`, `per_page?` | `ListMergeRequestsOutput` |
| `get_mr` | Read | `project_id`, `mr_iid` | `MergeRequestDetail` |
| `get_mr_diffs` | Read | `project_id`, `mr_iid`, `page?`, `per_page?` | `MergeRequestDiffsOutput` |
| `get_mr_commits` | Read | `project_id`, `mr_iid`, `page?`, `per_page?` | `MergeRequestCommitsOutput` |
| `create_mr` | Write | `project_id`, `title`, `source_branch`, `target_branch`, `description?`, `assignee_ids?`, `reviewer_ids?`, `labels?` | `MergeRequestDetail` |
| `update_mr` | Write | `project_id`, `mr_iid`, `title?`, `description?`, `assignee_ids?`, `reviewer_ids?`, `labels?`, `state_event?` | `MergeRequestDetail` |

---

### 5.2 Feature: Issue Tools

**Priority**: P0 (Critical)

#### User Stories

**US-003**: As a developer, I want to list, view, and search issues so that my AI assistant can help me triage and reference relevant issues.

**Acceptance Criteria**:
- [ ] `list_issues` returns paginated list of issues for a project with state/label/assignee filters
- [ ] `get_issue` returns full issue details including title, description, author, assignees, labels, state, and comments count
- [ ] `list_issue_comments` returns paginated comments (notes) for an issue
- [ ] All tools respect optional project/group scope from config

**US-004**: As a developer, I want to create, update, and comment on issues so that my AI assistant can help me manage project issues.

**Acceptance Criteria**:
- [ ] `create_issue` creates an issue with title, description, assignee_ids, labels, milestone_id
- [ ] `update_issue` updates issue fields (title, description, assignees, labels, state_event)
- [ ] `add_issue_comment` adds a comment (note) to an existing issue
- [ ] Mutation tools are NOT registered when `read_only=true`

**Edge Cases**:
- Issue not found: Return NOT_FOUND error with issue IID and project context
- Invalid label name: Return validation error with available labels suggestion
- Comment on closed issue: Allow by default (GitLab permits this)

**MCP Tool Definitions**:

| Tool | Type | Parameters | Returns |
|------|------|-----------|---------|
| `list_issues` | Read | `project_id`, `state?`, `labels?`, `assignee_id?`, `page?`, `per_page?` | `ListIssuesOutput` |
| `get_issue` | Read | `project_id`, `issue_iid` | `IssueDetail` |
| `list_issue_comments` | Read | `project_id`, `issue_iid`, `page?`, `per_page?` | `IssueCommentsOutput` |
| `create_issue` | Write | `project_id`, `title`, `description?`, `assignee_ids?`, `labels?`, `milestone_id?` | `IssueDetail` |
| `update_issue` | Write | `project_id`, `issue_iid`, `title?`, `description?`, `assignee_ids?`, `labels?`, `state_event?` | `IssueDetail` |
| `add_issue_comment` | Write | `project_id`, `issue_iid`, `body` | `IssueComment` |

---

### 5.3 Feature: Pipeline Tools

**Priority**: P1 (High)

#### User Stories

**US-005**: As a developer, I want to view pipeline status and job details so that my AI assistant can help me understand CI/CD results.

**Acceptance Criteria**:
- [ ] `list_pipelines` returns paginated list of pipelines for a project with status/ref filters
- [ ] `get_pipeline` returns full pipeline details including status, stages, duration, and trigger info
- [ ] `get_pipeline_jobs` returns job-level details (name, stage, status, duration, runner info) for a pipeline
- [ ] `get_job_log` returns the text log output of a specific job (truncated if exceeding size limit)
- [ ] All pipeline tools are always registered (read-only — no mutation tools for pipelines in MVP)

**Edge Cases**:
- Pipeline not found: Return NOT_FOUND error
- Job log too large: Truncate to configurable max size (default 100KB) with truncation notice
- Pipeline still running: Return current status with in-progress job details

**MCP Tool Definitions**:

| Tool | Type | Parameters | Returns |
|------|------|-----------|---------|
| `list_pipelines` | Read | `project_id`, `status?`, `ref?`, `page?`, `per_page?` | `ListPipelinesOutput` |
| `get_pipeline` | Read | `project_id`, `pipeline_id` | `PipelineDetail` |
| `get_pipeline_jobs` | Read | `project_id`, `pipeline_id`, `page?`, `per_page?` | `PipelineJobsOutput` |
| `get_job_log` | Read | `project_id`, `job_id`, `max_bytes?` | `JobLogOutput` |

---

### 5.4 Feature: Search

**Priority**: P1 (High)

#### User Stories

**US-006**: As a developer, I want to search across GitLab resources so that my AI assistant can find relevant issues, MRs, and projects.

**Acceptance Criteria**:
- [ ] `search` performs instance-wide or project-scoped searches across issues, merge_requests, and projects
- [ ] Supports scope parameter to filter search type (issues, merge_requests, projects)
- [ ] Returns paginated results with relevant metadata for each result type
- [ ] Respects project/group scope from config when set

**Edge Cases**:
- Empty search results: Return empty list with search metadata (query, scope)
- Invalid scope: Return validation error with available scopes
- Search rate limited by GitLab: Return RATE_LIMITED error with retry suggestion

**MCP Tool Definitions**:

| Tool | Type | Parameters | Returns |
|------|------|-----------|---------|
| `search` | Read | `query`, `scope` (issues/merge_requests/projects), `project_id?`, `group_id?`, `page?`, `per_page?` | `SearchOutput` |

---

### 5.5 Feature: Authentication & Authorization

**Priority**: P0 (Critical)

#### User Stories

**US-007**: As a developer, I want the server to authenticate with my GitLab instance using my preferred method so that I can use it with my enterprise setup.

**Acceptance Criteria**:
- [ ] Server supports Personal Access Token (PAT) authentication via `MAMBA_MCP_GITLAB_TOKEN` env var
- [ ] Server supports OAuth 2.0 authentication via `MAMBA_MCP_GITLAB_OAUTH_*` env vars
- [ ] Auth strategy is auto-detected: if PAT is configured, use PAT; if OAuth credentials are configured, use OAuth
- [ ] If both are configured, PAT takes precedence (simpler, faster)
- [ ] Token/credentials are validated at startup in `app_lifespan()` before yielding AppContext
- [ ] PAT validation calls `/api/v4/personal_access_tokens/self` to verify token validity and scopes
- [ ] Clear error messages if auth fails at startup (invalid token, missing scopes, unreachable GitLab)

**Edge Cases**:
- Neither PAT nor OAuth configured: Server refuses to start with clear error message
- PAT expired: Return AUTH_FAILED error with expiration detail and renewal suggestion
- GitLab instance unreachable: Return CONNECTION_ERROR with URL and network troubleshooting suggestion
- Insufficient token scopes: Warn at startup, log required vs. actual scopes

---

### 5.6 Feature: Read-Only Mode

**Priority**: P1 (High)

#### User Stories

**US-008**: As a platform engineer, I want to deploy the server in read-only mode so that AI assistants can read GitLab data without risk of unintended mutations.

**Acceptance Criteria**:
- [ ] `read_only` config flag (default: `false`) controls whether mutation tools are registered
- [ ] When `read_only=true`: `create_mr`, `update_mr`, `create_issue`, `update_issue`, `add_issue_comment` are NOT registered
- [ ] When `read_only=false`: All 17 tools are registered
- [ ] Read-only mode is logged at startup for visibility
- [ ] Discovery and pipeline tools (12 total) are always available regardless of mode

---

### 5.7 Feature: Project/Group Scoping

**Priority**: P2 (Medium)

#### User Stories

**US-009**: As a platform engineer, I want to optionally restrict the server to a specific project or group so that AI assistants only access authorized resources.

**Acceptance Criteria**:
- [ ] Optional `default_project_id` config filters all project-scoped tools to that project
- [ ] Optional `default_group_id` config filters search and listing tools to that group
- [ ] When set, tools that accept `project_id` use the default if no project_id is explicitly passed
- [ ] When not set, tools require explicit `project_id` parameters
- [ ] Both can be set simultaneously (group for search/listing, project for MR/Issue/Pipeline tools)

## 6. Non-Functional Requirements

### 6.1 Performance

- API response latency: <500ms P95 for single-resource queries (get_mr, get_issue, get_pipeline)
- List queries: <1s P95 for paginated list operations (per_page default: 20)
- Job log retrieval: <2s P95 for logs up to 100KB
- Connection pooling: Reuse TCP connections via `httpx.AsyncClient` in AppContext

### 6.2 Security

- Token storage: PAT stored as `SecretStr` in Pydantic settings, never logged in plaintext
- Token scope validation: Verify required scopes at startup via `/api/v4/personal_access_tokens/self`
- Required scopes for full access: `api` (or `read_api` for read-only mode)
- OAuth credentials: Client secret stored as `SecretStr`
- No raw token in error responses or logs
- HTTPS enforced for GitLab API connections (configurable for development with `verify_ssl` flag)

### 6.3 Scalability

- Single-server deployment model (matches other mamba-mcp servers)
- Client-side sliding window rate limiter to respect GitLab API limits
- Connection pool limits configurable via settings (default: 10 max connections)
- Pagination exposed to callers to manage data volume

### 6.4 Reliability

- Structured error responses for all failure modes (auth, network, API errors, validation)
- Graceful handling of GitLab API downtime (connection errors return structured error, not stack traces)
- Retry-safe: All read operations are idempotent; write operations are not automatically retried

## 7. Technical Considerations

### 7.1 Architecture Overview

The server follows the established mamba-mcp layered architecture:

```
mamba-mcp-gitlab/
├── __main__.py          # Typer CLI entry point
├── server.py            # FastMCP + AppContext + app_lifespan()
├── config.py            # Nested Pydantic settings (MAMBA_MCP_GITLAB_*)
├── errors.py            # ErrorCode + ERROR_SUGGESTIONS + create_tool_error()
├── auth.py              # Auth strategy (PAT/OAuth) auto-detection and token management
├── rate_limit.py        # Sliding window rate limiter (or reuse from mamba-mcp-fs)
├── models/              # Pydantic I/O models per resource
│   ├── __init__.py
│   ├── merge_requests.py
│   ├── issues.py
│   ├── pipelines.py
│   └── search.py
├── services/            # GitLab API service layer (one service per resource)
│   ├── __init__.py
│   ├── base.py          # Base service with shared httpx client logic
│   ├── merge_request_service.py
│   ├── issue_service.py
│   ├── pipeline_service.py
│   └── search_service.py
├── tools/               # MCP tool handlers (7-step skeleton)
│   ├── __init__.py
│   ├── mr_tools.py      # 6 MR tools
│   ├── issue_tools.py   # 6 Issue tools
│   ├── pipeline_tools.py # 4 Pipeline tools
│   └── search_tools.py  # 1 Search tool
└── tests/
    ├── conftest.py       # Mock fixtures (httpx MockTransport / respx)
    ├── test_config.py
    ├── test_errors.py
    ├── test_auth.py
    ├── test_services/
    └── test_tools/
```

### 7.2 Tech Stack

- **Runtime**: Python 3.11+
- **MCP Framework**: `mcp>=1.0.0` (FastMCP)
- **Web Server**: FastAPI + Uvicorn (via FastMCP's streamable-http transport)
- **HTTP Client**: `httpx>=0.27.0` (async, connection pooling)
- **Configuration**: `pydantic>=2.0.0`, `pydantic-settings>=2.0.0`
- **CLI**: `typer>=0.12.0`
- **Shared Core**: `mamba-mcp-core` (CLI helpers, error model, fuzzy matching, transport normalization)
- **Testing**: `pytest`, `pytest-asyncio`, `respx` (or `httpx` MockTransport)

### 7.3 Integration Points

| System | Integration Type | Purpose |
|--------|-----------------|---------|
| GitLab REST API v4 | HTTP REST | All MR, Issue, Pipeline, and Search operations |
| GitLab OAuth 2.0 | HTTP OAuth flow | Enterprise SSO authentication |
| mamba-mcp-core | Python package | CLI helpers, error model, fuzzy matching, config state |
| MCP Protocol | stdio / streamable-http | Transport for AI assistant connections |

### 7.4 Technical Constraints

- Must follow all mamba-mcp monorepo patterns (see CLAUDE.md §Key Patterns to Follow)
- GitLab REST API v4 only — no GraphQL in MVP
- No cross-server dependencies — must not import from mamba-mcp-pg, mamba-mcp-fs, or mamba-mcp-hana
- Config env prefix must be `MAMBA_MCP_GITLAB_*`
- All tools must return `OutputModel | dict[str, Any]` (structured Pydantic model or error dict)
- Error handling must use the error triad pattern (ErrorCode + ERROR_SUGGESTIONS + create_tool_error)

### 7.5 AppContext & Lifespan

```python
@dataclass
class AppContext:
    """Application context with shared resources."""
    client: httpx.AsyncClient      # Shared HTTP client with connection pooling
    settings: Settings             # Server configuration
    rate_limiter: RateLimiter      # Client-side rate limiter
    auth_info: AuthInfo            # Validated auth details (token type, scopes, user)

@asynccontextmanager
async def app_lifespan(server: FastMCP) -> AsyncIterator[AppContext]:
    settings = get_settings()

    # 1. Detect auth strategy (PAT vs OAuth)
    # 2. Create httpx.AsyncClient with base_url and auth headers
    # 3. Validate token/credentials against GitLab API
    # 4. Initialize rate limiter
    # 5. Yield AppContext
    # 6. Close httpx client on shutdown
```

### 7.6 Configuration Structure

```
MAMBA_MCP_GITLAB_URL=https://gitlab.example.com
MAMBA_MCP_GITLAB_TOKEN=glpat-xxxxxxxxxxxxxxxxxxxx
MAMBA_MCP_GITLAB_VERIFY_SSL=true
MAMBA_MCP_GITLAB_DEFAULT_PROJECT_ID=
MAMBA_MCP_GITLAB_DEFAULT_GROUP_ID=
MAMBA_MCP_GITLAB_READ_ONLY=false

# OAuth (optional, alternative to TOKEN)
MAMBA_MCP_GITLAB_OAUTH_CLIENT_ID=
MAMBA_MCP_GITLAB_OAUTH_CLIENT_SECRET=
MAMBA_MCP_GITLAB_OAUTH_REDIRECT_URI=

# Server settings
MAMBA_MCP_GITLAB_SERVER__TRANSPORT=stdio
MAMBA_MCP_GITLAB_SERVER__HOST=127.0.0.1
MAMBA_MCP_GITLAB_SERVER__PORT=8004
MAMBA_MCP_GITLAB_SERVER__LOG_LEVEL=INFO
MAMBA_MCP_GITLAB_SERVER__LOG_FORMAT=text

# Rate limiting
MAMBA_MCP_GITLAB_RATE_LIMIT__MAX_REQUESTS=100
MAMBA_MCP_GITLAB_RATE_LIMIT__WINDOW_SECONDS=60
```

### 7.7 Error Codes

| Error Code | HTTP Status | Suggestion |
|-----------|-------------|------------|
| `AUTH_FAILED` | 401 | "Check your GitLab token or OAuth credentials. Verify the token hasn't expired." |
| `FORBIDDEN` | 403 | "Your token lacks required scopes. Required: `api` (or `read_api` for read-only)." |
| `NOT_FOUND` | 404 | "Resource not found. Check the project_id and resource IID." |
| `PROJECT_NOT_FOUND` | 404 | "Project not found. Use `search` to find the correct project." |
| `MERGE_REQUEST_NOT_FOUND` | 404 | "Merge request not found. Use `list_mrs` to see available MRs." |
| `ISSUE_NOT_FOUND` | 404 | "Issue not found. Use `list_issues` to see available issues." |
| `PIPELINE_NOT_FOUND` | 404 | "Pipeline not found. Use `list_pipelines` to see available pipelines." |
| `RATE_LIMITED` | 429 | "GitLab API rate limit reached. Wait before retrying." |
| `VALIDATION_ERROR` | 400 | "Invalid input parameters. Check the tool's parameter requirements." |
| `CONNECTION_ERROR` | N/A | "Cannot reach GitLab at the configured URL. Check network and URL settings." |
| `API_ERROR` | 500 | "GitLab API returned an unexpected error. Check GitLab server status." |
| `BRANCH_NOT_FOUND` | 404 | "Branch not found. Check branch name and project." |

## 8. Scope Definition

### 8.1 In Scope

- 17 MCP tools across Merge Requests (6), Issues (6), Pipelines (4), Search (1)
- Dual authentication: PAT + OAuth 2.0 with auto-detection
- Read-only configuration mode
- Optional project/group scoping
- Client-side rate limiting
- Structured error responses with fuzzy suggestions
- Token scope validation at startup
- Connection pooling via httpx.AsyncClient
- Full test suite with httpx mock transport
- CLI entry point matching monorepo patterns (`mamba-mcp-gitlab` / `mamba-mcp-gitlab test`)

### 8.2 Out of Scope

- **GitLab GraphQL API**: REST API v4 only for MVP — GraphQL may be added in a future version for complex relationship queries
- **WebSocket/real-time events**: No live event subscriptions — tools are request/response only
- **Git operations**: No git clone, push, or pull operations — this is an API-level server, not a git client
- **Code review comments**: No inline code review comments on MR diffs — may be added post-MVP
- **GitLab CI/CD mutations**: No triggering pipelines, retrying jobs, or cancelling jobs — read-only pipeline access only
- **Wiki/Snippets/Releases**: Not part of the core developer workflow targeted by MVP
- **Multi-instance**: Single GitLab instance per server deployment
- **GitLab.com SaaS features**: No GitLab Duo integration, no SaaS-specific endpoints

### 8.3 Future Considerations

- **MR review comments**: Add `add_mr_comment`, `list_mr_discussions` tools for inline code review
- **Pipeline mutations**: Add `trigger_pipeline`, `retry_job`, `cancel_pipeline` tools
- **Labels/Milestones management**: CRUD tools for project labels and milestones
- **GraphQL integration**: Use GraphQL for complex queries (e.g., cross-project search, relationship traversal)
- **Group-level tools**: `list_group_projects`, `list_group_members`
- **Webhook support**: Register webhooks for event-driven workflows
- **Multi-instance**: Support connecting to multiple GitLab instances simultaneously

## 9. Implementation Plan

### 9.1 Phase 1: Foundation

**Completion Criteria**: Server starts, authenticates with GitLab, passes `test` command, and registers at least one tool.

| Deliverable | Description | Dependencies |
|-------------|-------------|--------------|
| Package scaffolding | `pyproject.toml`, directory structure, `__init__.py` files | UV workspace config |
| Configuration (`config.py`) | Nested Pydantic settings with `MAMBA_MCP_GITLAB_*` prefix | `mamba-mcp-core` |
| Authentication (`auth.py`) | PAT + OAuth strategy auto-detection, token validation | `httpx` |
| Error handling (`errors.py`) | Error codes, suggestions map, `create_tool_error()` wrapper | `mamba-mcp-core` |
| Server core (`server.py`) | `AppContext`, `app_lifespan()`, `mcp` instance | `mcp`, `httpx` |
| CLI entry point (`__main__.py`) | Typer app with `test` subcommand, transport handling | `typer`, `mamba-mcp-core` |
| Service base (`services/base.py`) | Base service class with shared httpx client logic | `httpx` |
| Smoke test | Basic test validating config loading and server startup | `pytest` |

**Checkpoint Gate**: Server starts successfully with PAT auth, `mamba-mcp-gitlab test` validates connectivity to a GitLab instance, and at least one placeholder tool is registered.

---

### 9.2 Phase 2: Core Tools

**Completion Criteria**: All 17 tools are implemented, tested with mock responses, and follow the 7-step handler skeleton.

| Deliverable | Description | Dependencies |
|-------------|-------------|--------------|
| MR service + models | `MergeRequestService`, input/output Pydantic models | Phase 1 service base |
| MR tools (6) | `list_mrs`, `get_mr`, `get_mr_diffs`, `get_mr_commits`, `create_mr`, `update_mr` | MR service + models |
| Issue service + models | `IssueService`, input/output Pydantic models | Phase 1 service base |
| Issue tools (6) | `list_issues`, `get_issue`, `list_issue_comments`, `create_issue`, `update_issue`, `add_issue_comment` | Issue service + models |
| Pipeline service + models | `PipelineService`, input/output Pydantic models | Phase 1 service base |
| Pipeline tools (4) | `list_pipelines`, `get_pipeline`, `get_pipeline_jobs`, `get_job_log` | Pipeline service + models |
| Search service + model | `SearchService`, search output model | Phase 1 service base |
| Search tool (1) | `search` with scope, project/group filtering | Search service + model |
| Read-only mode | Conditional tool registration based on `read_only` config | All tools |
| Project/group scoping | Default project/group injection into tool parameters | All tools |
| Mock test fixtures | `conftest.py` with httpx MockTransport for all GitLab API responses | `respx` / `httpx` |
| Tool tests | Test coverage for all 17 tools (happy path + error cases) | Mock fixtures |

**Checkpoint Gate**: All 17 tools pass tests with mock responses, read-only mode correctly hides mutation tools, and project/group scoping works as expected.

---

### 9.3 Phase 3: Polish

**Completion Criteria**: Rate limiting active, error messages polished, documentation complete, CI integration ready.

| Deliverable | Description | Dependencies |
|-------------|-------------|--------------|
| Rate limiter | Sliding window rate limiter for GitLab API calls | Phase 2 |
| Error polish | Fuzzy suggestions for project/branch names, improved error messages | Phase 2 |
| OAuth flow | Complete OAuth 2.0 implementation with token refresh | Phase 1 auth base |
| Pagination refinement | Consistent pagination params across all list tools, keyset pagination support | Phase 2 |
| Documentation | README with setup, configuration, and tool reference | Phase 2 |
| CI integration | Add to `.github/workflows/ci.yml` test matrix | All phases |
| CLAUDE.md update | Update monorepo CLAUDE.md with mamba-mcp-gitlab architecture section | All phases |
| Coverage report | Ensure >80% service layer coverage, 100% error handling coverage | All phases |

## 10. Dependencies

### 10.1 Technical Dependencies

| Dependency | Owner | Status | Risk if Delayed |
|------------|-------|--------|-----------------|
| `mamba-mcp-core` | Monorepo | Available | None — already published |
| `mcp>=1.0.0` | Anthropic | Available | None — stable release |
| `httpx>=0.27.0` | Encode | Available | None — stable release |
| `pydantic-settings>=2.0.0` | Pydantic | Available | None — stable release |
| `typer>=0.12.0` | Tiangolo | Available | None — stable release |
| `respx` (dev) | lundberg | Available | Low — testing only |
| GitLab REST API v4 | GitLab | Stable | None — well-established API |

### 10.2 Cross-Team Dependencies

| Team | Dependency | Status |
|------|------------|--------|
| GitLab Admin | Access to self-hosted GitLab for integration testing | Required for Phase 3 |
| GitLab Admin | PAT with `api` scope for development/testing | Required for Phase 1 |

## 11. Risks & Mitigations

| Risk | Impact | Likelihood | Mitigation Strategy |
|------|--------|------------|---------------------|
| GitLab API rate limits too restrictive | Medium | Medium | Client-side rate limiter, configurable limits, expose rate limit headers |
| OAuth 2.0 flow complexity for self-hosted | High | Medium | Prioritize PAT auth, defer OAuth to Phase 3, document OAuth setup clearly |
| GitLab API breaking changes | Medium | Low | Pin to REST API v4, test against specific GitLab versions |
| Large job logs cause memory issues | Medium | Medium | Configurable max_bytes parameter with default 100KB truncation |
| Token scope differences across GitLab editions | Low | Medium | Document required scopes per edition, validate at startup |

## 12. Open Questions

| # | Question | Owner | Due Date | Resolution |
|---|----------|-------|----------|------------|
| 1 | What specific OAuth 2.0 flow is best for self-hosted GitLab (authorization code vs. client credentials)? | Developer | Phase 3 | To be researched during OAuth implementation |
| 2 | Should `get_job_log` support streaming for very large logs, or is truncation sufficient? | Developer | Phase 2 | Start with truncation, evaluate streaming need |
| 3 | What GitLab version is the minimum supported target? | Stephen | Phase 1 | Needs confirmation based on enterprise GitLab version |
| 4 | Should the rate limiter be shared with mamba-mcp-fs (extract to core) or independent? | Developer | Phase 3 | Evaluate code overlap during implementation |

## 13. Appendix

### 13.1 Glossary

| Term | Definition |
|------|------------|
| MR | Merge Request — GitLab's equivalent of a Pull Request |
| IID | Internal ID — GitLab's project-scoped identifier for issues, MRs, etc. |
| PAT | Personal Access Token — GitLab's token-based authentication method |
| MCP | Model Context Protocol — standard for AI assistant tool integration |
| FastMCP | Python MCP framework used by all mamba-mcp servers |
| AppContext | Dataclass holding shared resources (httpx client, settings, etc.) yielded from lifespan |

### 13.2 References

- [GitLab MCP Server Documentation](https://docs.gitlab.com/user/gitlab_duo/model_context_protocol/mcp_server/)
- [GitLab MCP Server Tools](https://docs.gitlab.com/user/gitlab_duo/model_context_protocol/mcp_server_tools/)
- [GitLab REST API v4 Documentation](https://docs.gitlab.com/ee/api/rest/)
- [GitLab Personal Access Tokens API](https://docs.gitlab.com/ee/api/personal_access_tokens.html)
- [GitLab Merge Requests API](https://docs.gitlab.com/ee/api/merge_requests.html)
- [GitLab Issues API](https://docs.gitlab.com/ee/api/issues.html)
- [GitLab Pipelines API](https://docs.gitlab.com/ee/api/pipelines.html)
- [GitLab Search API](https://docs.gitlab.com/ee/api/search.html)
- [mamba-mcp CLAUDE.md](../CLAUDE.md) — Monorepo patterns and conventions

### 13.3 Agent Recommendations (Accepted)

*The following recommendations were suggested based on industry best practices and accepted during the interview:*

1. **Security — Token Scope Validation**: Validate PAT scopes at startup via `/api/v4/personal_access_tokens/self` to catch permission issues early, preventing confusing 403 errors during tool execution.

2. **API Design — Connection Pooling**: Create `httpx.AsyncClient` in `app_lifespan()` with base_url, auth headers, and connection limits. All service classes receive the shared client instance for TCP connection reuse.

3. **Testing — Mock HTTP Transport**: Use `httpx.MockTransport` or `respx` library for testing GitLab API interactions without a real GitLab instance. Create `conftest.py` fixtures with pre-configured mock responses.

---

*Document generated by SDD Tools*
