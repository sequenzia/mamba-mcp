# Product Requirements Document: mamba-mcp-server-gitlab

**Version:** 1.0
**Author:** Stephen Sequenzia
**Date:** 2025-01-21
**Status:** Draft

---

## Executive Summary

mamba-mcp-server-gitlab is a new MCP (Model Context Protocol) server package that enables AI agents and development tools to interact with GitLab instances programmatically. The server exposes GitLab operations as MCP tools, allowing AI-assisted development workflows such as automated merge request reviews, CI/CD pipeline management, and issue tracking.

The primary use case is enabling AI agents (such as Claude Code) to perform automated code reviews on merge requests, reducing context switching for developers and enabling seamless GitLab integration within AI-powered development environments.

---

## Problem Statement

### Current Pain Points

1. **Context Switching**: Developers using AI-assisted tools must leave their IDE to perform GitLab operations (reviewing MRs, checking pipeline status, managing issues), disrupting their workflow.

2. **Manual MR Reviews**: Code reviews are time-consuming and require developers to manually navigate GitLab's interface to read diffs, add comments, and approve changes.

3. **CI/CD Visibility**: Checking pipeline status and job logs requires navigating away from the development environment.

4. **No Standardized AI Integration**: AI agents lack a standardized protocol to interact with GitLab, preventing automation of repetitive tasks.

### Opportunity

By implementing an MCP server for GitLab, AI agents can:
- Perform complete MR review workflows autonomously
- Monitor and manage CI/CD pipelines
- Create and update issues without human intervention
- Reduce developer context switching by 60-80% for GitLab-related tasks

---

## Goals & Success Metrics

### Primary Goals

1. Enable AI agents to perform complete MR review workflows
2. Provide comprehensive CI/CD pipeline management capabilities
3. Support full issue lifecycle management
4. Integrate seamlessly with existing mamba-mcp ecosystem

### Success Metrics

| Metric | Target | Measurement |
|--------|--------|-------------|
| MR Review Completion | AI can complete full review workflow | End-to-end test passes |
| API Coverage | 100% of specified GitLab operations | Tool count vs. requirements |
| Response Time | < 2s for typical operations | Performance benchmarks |
| Error Clarity | Actionable error messages | User feedback |

---

## Target Users

### Primary Users

1. **AI-Assisted Development Tools**
   - Claude Code, GitHub Copilot, and similar AI coding assistants
   - Need: Programmatic access to GitLab operations via MCP protocol
   - Workflow: Automated code review, issue creation from code analysis

2. **Developers**
   - Software engineers performing code reviews and managing MRs
   - Need: Reduced context switching, faster reviews
   - Workflow: Review MRs without leaving IDE, get AI assistance on reviews

3. **DevOps Engineers**
   - Engineers managing CI/CD pipelines and deployments
   - Need: Quick pipeline status checks, easy job log access
   - Workflow: Monitor and manage pipelines from AI tools

---

## Functional Requirements

### FR1: Merge Request Operations (MVP Priority)

| ID | Requirement | Priority | Acceptance Criteria |
|----|-------------|----------|---------------------|
| FR1.1 | List merge requests | P0 | - Filter by state (opened, closed, merged, all) <br> - Filter by author, assignee, labels <br> - Paginate results <br> - Return MR metadata (title, description, source/target branch) |
| FR1.2 | Get merge request details | P0 | - Return full MR metadata <br> - Include commit list <br> - Include approval status <br> - Include pipeline status |
| FR1.3 | Get merge request diff | P0 | - Return file changes with context <br> - Support diff format (unified) <br> - Include old/new file paths <br> - Handle binary files gracefully |
| FR1.4 | Add MR comment (general) | P0 | - Post discussion comment on MR <br> - Support markdown formatting <br> - Return created comment ID |
| FR1.5 | Add MR comment (line) | P0 | - Post comment on specific line of diff <br> - Specify old/new line position <br> - Associate with specific commit <br> - Return created comment ID |
| FR1.6 | Approve merge request | P0 | - Add current user's approval <br> - Return updated approval status <br> - Handle already-approved case |
| FR1.7 | Unapprove merge request | P0 | - Remove current user's approval <br> - Return updated approval status |
| FR1.8 | Merge merge request | P1 | - Execute merge operation <br> - Support squash option <br> - Support delete source branch option <br> - Handle merge conflicts gracefully |
| FR1.9 | List MR discussions | P1 | - Return all discussion threads <br> - Include resolved status <br> - Include replies |

### FR2: CI/CD Operations

| ID | Requirement | Priority | Acceptance Criteria |
|----|-------------|----------|---------------------|
| FR2.1 | List pipelines | P0 | - Filter by ref, status, source <br> - Return pipeline metadata <br> - Paginate results |
| FR2.2 | Get pipeline status | P0 | - Return current status <br> - Include job breakdown <br> - Include duration and timestamps |
| FR2.3 | Get job logs | P0 | - Return full job log output <br> - Handle large logs (truncate with indicator) <br> - Support specific job ID |
| FR2.4 | Trigger pipeline | P1 | - Trigger new pipeline on ref <br> - Support variables <br> - Return pipeline ID |
| FR2.5 | Retry pipeline | P1 | - Retry failed pipeline <br> - Return new pipeline status |
| FR2.6 | Cancel pipeline | P1 | - Cancel running pipeline <br> - Return confirmation |
| FR2.7 | List pipeline jobs | P1 | - Return jobs for pipeline <br> - Include status, duration, stage |
| FR2.8 | Get job artifacts | P2 | - Download job artifacts <br> - Return artifact metadata <br> - Handle missing artifacts |

### FR3: Issue Management

| ID | Requirement | Priority | Acceptance Criteria |
|----|-------------|----------|---------------------|
| FR3.1 | List issues | P1 | - Filter by state, labels, assignee, milestone <br> - Search by title/description <br> - Paginate results |
| FR3.2 | Get issue details | P1 | - Return full issue data <br> - Include labels, assignees, milestone <br> - Include related MRs |
| FR3.3 | Create issue | P1 | - Set title, description, labels <br> - Set assignee, milestone <br> - Return created issue ID |
| FR3.4 | Update issue | P1 | - Update any issue field <br> - Support partial updates <br> - Return updated issue |
| FR3.5 | Add issue comment | P1 | - Post comment on issue <br> - Support markdown <br> - Return comment ID |
| FR3.6 | Close issue | P1 | - Change issue state to closed <br> - Return confirmation |
| FR3.7 | Reopen issue | P2 | - Change issue state to opened <br> - Return confirmation |
| FR3.8 | List issue comments | P2 | - Return all comments <br> - Include author and timestamps |

### FR4: Project Operations

| ID | Requirement | Priority | Acceptance Criteria |
|----|-------------|----------|---------------------|
| FR4.1 | List projects | P1 | - Filter by visibility, membership <br> - Search by name <br> - Return project metadata |
| FR4.2 | Get project details | P1 | - Return full project info <br> - Include default branch <br> - Include visibility settings |

---

## Technical Specifications

### TS1: Package Structure

```
packages/mamba-mcp-server-gitlab/
├── pyproject.toml
├── README.md
├── src/
│   └── mamba_mcp_server_gitlab/
│       ├── __init__.py
│       ├── server.py          # MCP server entry point
│       ├── config.py          # Configuration (Pydantic)
│       ├── tools/
│       │   ├── __init__.py
│       │   ├── merge_requests.py
│       │   ├── pipelines.py
│       │   ├── issues.py
│       │   └── projects.py
│       ├── gitlab_client.py   # python-gitlab wrapper
│       └── errors.py          # Structured error handling
└── tests/
    ├── conftest.py
    ├── test_config.py
    ├── test_merge_requests.py
    ├── test_pipelines.py
    └── test_issues.py
```

### TS2: Dependencies

| Dependency | Version | Purpose |
|------------|---------|---------|
| python-gitlab | >=4.0.0 | Official GitLab API client |
| mcp | >=1.0.0 | MCP Python SDK |
| mamba-mcp-core | workspace | Shared utilities |
| pydantic | >=2.0.0 | Configuration validation |
| pydantic-settings | >=2.0.0 | Environment configuration |
| httpx | >=0.27.0 | HTTP client (if needed) |

### TS3: Configuration

**Environment Variables:**
```bash
# Required
GITLAB_URL=https://gitlab.example.com  # GitLab instance URL
GITLAB_TOKEN=glpat-xxxx                # Access token

# Optional
GITLAB_TOKEN_TYPE=private              # private|project|group
GITLAB_SSL_VERIFY=true                 # SSL verification
GITLAB_TIMEOUT=30                      # Request timeout (seconds)
GITLAB_DEFAULT_PROJECT=group/project   # Default project for operations
```

**Config File (gitlab-mcp.yaml):**
```yaml
gitlab:
  url: https://gitlab.example.com
  token_type: private
  ssl_verify: true
  timeout: 30
  default_project: group/project

server:
  transport: stdio  # stdio | streamable-http
  host: 127.0.0.1   # for streamable-http
  port: 8000        # for streamable-http
```

**Configuration Priority (highest to lowest):**
1. CLI arguments
2. Environment variables
3. Config file
4. Default values

### TS4: Authentication

| Token Type | Scope | Use Case |
|------------|-------|----------|
| Personal Access Token | User-level | General development use |
| Project Access Token | Project-level | CI/CD, project-specific automation |
| Group Access Token | Group-level | Cross-project operations within group |

**Required Token Scopes:**
- `api` - Full API access
- `read_api` - Read-only operations (alternative for restricted use)
- `read_repository` - For repository-related operations
- `write_repository` - For merge operations

### TS5: MCP Tool Design

**Naming Convention:** `gitlab_{resource}_{action}`

**Examples:**
- `gitlab_mr_list` - List merge requests
- `gitlab_mr_get` - Get MR details
- `gitlab_mr_diff` - Get MR diff
- `gitlab_mr_comment` - Add comment to MR
- `gitlab_mr_approve` - Approve MR
- `gitlab_pipeline_status` - Get pipeline status
- `gitlab_issue_create` - Create issue

**Tool Response Format:**
```python
class ToolResponse(BaseModel):
    success: bool
    data: dict | list | None
    error: ErrorDetail | None

class ErrorDetail(BaseModel):
    code: str           # e.g., "GITLAB_NOT_FOUND", "GITLAB_FORBIDDEN"
    message: str        # Human-readable message
    details: dict | None  # Additional context
```

### TS6: Error Handling

| Error Code | HTTP Status | Description |
|------------|-------------|-------------|
| GITLAB_UNAUTHORIZED | 401 | Invalid or expired token |
| GITLAB_FORBIDDEN | 403 | Insufficient permissions |
| GITLAB_NOT_FOUND | 404 | Resource not found |
| GITLAB_CONFLICT | 409 | Merge conflict or state conflict |
| GITLAB_RATE_LIMITED | 429 | Rate limit exceeded |
| GITLAB_SERVER_ERROR | 5xx | GitLab server error |
| CONFIG_INVALID | - | Invalid configuration |
| VALIDATION_ERROR | - | Invalid input parameters |

### TS7: Transport Protocols

**STDIO Transport:**
- Primary transport for local IDE integration
- Command: `mamba-mcp-server-gitlab`
- Suitable for Claude Code, VS Code extensions

**Streamable HTTP Transport:**
- For remote/networked access
- Configurable host and port
- Suitable for shared team servers

---

## Implementation Phases

### Phase 1: MVP - MR Review Workflow

**Scope:**
- Core MCP server infrastructure
- STDIO and Streamable HTTP transports
- Configuration system (env vars, config file, CLI)
- Authentication (PAT, Project token, Group token)
- MR tools: list, get, diff, comment, approve, unapprove, merge
- Structured error handling
- Unit tests with mocked GitLab API
- README with setup instructions

**Deliverables:**
- Working MCP server with MR review capabilities
- Full test coverage for MR operations
- Documentation for setup and tool reference

**Exit Criteria:**
- [ ] AI agent can list MRs in a project
- [ ] AI agent can read MR diff and add line comments
- [ ] AI agent can approve and merge an MR
- [ ] All MR tools have unit tests
- [ ] README documents all MR tools

### Phase 2: CI/CD Operations

**Scope:**
- Pipeline tools: list, get_status, trigger, retry, cancel
- Job tools: list_jobs, get_logs, get_artifacts
- Expanded test coverage
- Updated documentation

**Deliverables:**
- Complete CI/CD tool suite
- Integration with MR workflow (pipeline status in MR details)

**Exit Criteria:**
- [ ] AI agent can check pipeline status for an MR
- [ ] AI agent can read job logs
- [ ] AI agent can trigger and cancel pipelines
- [ ] All CI/CD tools have unit tests

### Phase 3: Issue Management

**Scope:**
- Issue tools: list, search, get, create, update, close, reopen
- Comment tools: list_comments, add_comment
- Project tools: list_projects, get_project
- Full documentation with use case examples

**Deliverables:**
- Complete issue management suite
- Project discovery capabilities
- Comprehensive documentation

**Exit Criteria:**
- [ ] AI agent can create issues from code analysis
- [ ] AI agent can update and close issues
- [ ] AI agent can discover and list projects
- [ ] Full tool reference documentation complete

### Phase 4: Future Enhancements

**Planned Features:**
- Repository operations (file browsing, code search, branch management)
- MCP Resources support (expose data as browsable resources)
- Webhooks support (react to GitLab events in real-time)
- OAuth authentication (interactive auth flow)

---

## Testing Strategy

### Unit Tests

- Mock all GitLab API responses using `pytest-mock` or `responses`
- Test each tool in isolation
- Cover success paths and error scenarios
- Maintain >80% code coverage

**Example Test Structure:**
```python
@pytest.fixture
def mock_gitlab():
    """Create a mocked GitLab client."""
    with patch('gitlab.Gitlab') as mock:
        yield mock

async def test_gitlab_mr_list_success(mock_gitlab):
    """Test listing merge requests successfully."""
    mock_gitlab.return_value.projects.get.return_value.mergerequests.list.return_value = [
        MagicMock(iid=1, title="Test MR", state="opened")
    ]

    result = await gitlab_mr_list(project_id=123, state="opened")

    assert result.success
    assert len(result.data) == 1
    assert result.data[0]["iid"] == 1
```

### Integration Tests (Optional)

- Run against real GitLab instance (self-hosted test instance)
- Gated behind environment variable `RUN_INTEGRATION_TESTS=true`
- Used for validation, not CI

---

## Documentation Requirements

### README.md

1. Overview and features
2. Installation instructions
3. Configuration guide (env vars, config file)
4. Quick start examples
5. Tool reference (all tools with parameters)
6. Troubleshooting common errors

### Tool Reference

For each tool, document:
- Tool name and description
- Input parameters with types and constraints
- Output format with examples
- Error cases and codes
- Usage examples

---

## Dependencies & Risks

### Dependencies

| Dependency | Risk Level | Mitigation |
|------------|------------|------------|
| python-gitlab library | Low | Well-maintained, official library |
| GitLab API stability | Low | Use versioned API endpoints |
| MCP SDK | Medium | Pin version, monitor for updates |
| mamba-mcp-core | Low | Internal dependency, controlled |

### Risks

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|------------|
| GitLab API rate limits | Medium | High | Document limits, consider caching |
| Breaking API changes | Low | Medium | Pin API version, monitor changelog |
| Token scope confusion | Medium | Medium | Clear documentation, validation |
| Large diff handling | Medium | Medium | Truncation with indicators |

---

## Out of Scope (MVP)

The following are explicitly excluded from the MVP:

1. **Repository Operations** - File browsing, code search, branch management (Phase 4)
2. **MCP Resources** - All interactions via tools only
3. **OAuth Authentication** - Token-based auth only
4. **CI Job Token** - Not supported for authentication
5. **Automatic Retry** - No automatic retry on rate limits
6. **GitLab GraphQL API** - REST API only
7. **Webhooks** - No event-driven capabilities (Phase 4)
8. **Caching** - No response caching

---

## Appendix

### A. MCP Tool Reference (MVP)

| Tool Name | Description | Parameters |
|-----------|-------------|------------|
| `gitlab_mr_list` | List merge requests | project_id, state?, author?, labels? |
| `gitlab_mr_get` | Get MR details | project_id, mr_iid |
| `gitlab_mr_diff` | Get MR diff | project_id, mr_iid |
| `gitlab_mr_comment` | Add comment to MR | project_id, mr_iid, body, position? |
| `gitlab_mr_approve` | Approve MR | project_id, mr_iid |
| `gitlab_mr_unapprove` | Remove approval | project_id, mr_iid |
| `gitlab_mr_merge` | Merge MR | project_id, mr_iid, squash?, delete_branch? |
| `gitlab_pipeline_list` | List pipelines | project_id, ref?, status? |
| `gitlab_pipeline_get` | Get pipeline details | project_id, pipeline_id |
| `gitlab_pipeline_jobs` | List pipeline jobs | project_id, pipeline_id |
| `gitlab_job_logs` | Get job logs | project_id, job_id |
| `gitlab_pipeline_trigger` | Trigger pipeline | project_id, ref, variables? |
| `gitlab_pipeline_retry` | Retry pipeline | project_id, pipeline_id |
| `gitlab_pipeline_cancel` | Cancel pipeline | project_id, pipeline_id |

### B. Example Workflows

**Automated MR Review:**
```
1. gitlab_mr_list(project_id=123, state="opened")
2. gitlab_mr_get(project_id=123, mr_iid=42)
3. gitlab_mr_diff(project_id=123, mr_iid=42)
4. gitlab_mr_comment(project_id=123, mr_iid=42, body="...", position={...})
5. gitlab_mr_approve(project_id=123, mr_iid=42)
```

**CI/CD Monitoring:**
```
1. gitlab_pipeline_list(project_id=123, ref="main", status="failed")
2. gitlab_pipeline_jobs(project_id=123, pipeline_id=456)
3. gitlab_job_logs(project_id=123, job_id=789)
4. gitlab_pipeline_retry(project_id=123, pipeline_id=456)
```
