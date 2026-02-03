# Execution Context

## Project Patterns
- All server packages use hatchling build backend with `packages = ["src/<package_name>"]`
- pyproject.toml requires `readme = "README.md"` -- hatchling will fail build without it
- Root workspace uses glob `members = ["packages/*"]` so new packages auto-discovered
- Must also add explicit entry in `[tool.uv.sources]` for workspace resolution
- All `__init__.py` files follow pattern: docstring + `__version__ = "0.1.0"`
- Placeholder modules need only a docstring (no imports or code needed)
- Tests use class-based organization: `class TestFeatureName:` with docstrings on every test
- mypy overrides needed for tools modules (`disallow_untyped_decorators = false`)
- Config pattern: each nested settings class has its own `env_prefix`; root `Settings` uses `env_nested_delimiter="__"` and `@model_validator(mode="before")` to instantiate sub-settings with `_env_file` parameter
- Autouse fixture `reset_env_file_path` in conftest.py resets `set_env_file_path(None)` before and after each test
- `_env_file=None` passed to sub-settings in tests to avoid loading actual env files from disk
- GitLab models use `models/common.py` for shared types (Author, PaginatedOutput) imported by all resource modules
- Paginated outputs inherit from `PaginatedOutput` and add an `items` field with the specific list type
- Detail models extend Summary models (e.g., MergeRequestDetail(MergeRequestSummary)) for field reuse
- Date fields stored as `str` not `datetime` for flexible ISO 8601 format acceptance
- Auth module uses `@runtime_checkable Protocol` for AuthStrategy so `isinstance()` checks work at runtime
- OAuth strategy uses `time.monotonic()` for token expiry tracking (not `time.time()`) to avoid wall-clock jumps
- OAuth token refresh has 3-level fallback: try refresh_token -> fall back to client_credentials -> raise AuthenticationError
- OAuth `ensure_valid_token()` includes 30-second buffer before expiry to avoid race conditions
- `httpx.MockTransport` is the cleanest way to mock HTTP responses for async tests (no external mocking lib needed)
- Auth errors use `AuthenticationError` exception (not tool error dicts) since auth happens at startup, not in tool handlers
- Base service uses `respx` (not `httpx.MockTransport`) for mocking HTTP in tests -- `@respx.mock` decorator + `respx.get/post/put().respond()` pattern
- `GitLabAPIError` exception carries `error_code` and `status_code` for structured error propagation from service layer to tool handlers
- `_safe_int()` module-level helper safely parses pagination header values (returns 0 for None/invalid)
- `_parse_json_body()` safely handles empty/non-JSON response bodies by returning `{}`
- Settings can be constructed inline for tests by passing dicts: `Settings(gitlab={"url": "...", "token": "..."}, oauth={}, server={}, rate_limit={})`
- Server `app_lifespan()` follows PG pattern: `@asynccontextmanager` yielding `AppContext` dataclass. Auth validation happens before yield; cleanup (`client.aclose()`) in `finally` block.
- httpx connection limits are tested via `patch.object(httpx.AsyncClient, "__init__", capture_fn)` pattern to capture kwargs without relying on private attributes
- httpx verify kwarg captured similarly via patched `__init__` to avoid relying on internal SSL context attributes
- When mocking objects with mixed sync/async methods, use `MagicMock` + selective `strategy.validate = AsyncMock()` -- do NOT use `AsyncMock()` for the whole object as it makes all methods async
- CLI tests use `typer.testing.CliRunner` with `runner.invoke(app, [...])` pattern; `strip_ansi()` helper removes ANSI codes before assertions

## Key Decisions
- GitLab `create_tool_error()` returns `dict[str, Any]` (PG pattern, not HANA's ToolError model)
- Added `respx.*` to mypy `ignore_missing_imports` since gitlab package uses it for test mocking
- Added `mamba_mcp_gitlab.tools.*` to mypy untyped decorators override (consistent with pg/fs/hana)
- Created minimal README.md to satisfy hatchling build requirement
- `respx>=0.22.0` added as dev dependency to root pyproject.toml for httpx mocking

## Known Issues
- hatchling build fails if `readme = "README.md"` is in pyproject.toml but file doesn't exist
- First `uv sync` after adding a new package may uninstall/reinstall all packages (normal behavior)

## File Map
- `/Users/sequenzia/dev/repos/mamba-mcp/packages/mamba-mcp-gitlab/pyproject.toml` - Package metadata, deps, entry point
- `/Users/sequenzia/dev/repos/mamba-mcp/packages/mamba-mcp-gitlab/src/mamba_mcp_gitlab/__init__.py` - Package root with version
- `/Users/sequenzia/dev/repos/mamba-mcp/packages/mamba-mcp-gitlab/src/mamba_mcp_gitlab/__main__.py` - CLI entry point (Typer app with test subcommand, env-file option, tool imports)
- `/Users/sequenzia/dev/repos/mamba-mcp/packages/mamba-mcp-gitlab/tests/test_cli.py` - CLI tests (19 tests across 7 test classes)
- `/Users/sequenzia/dev/repos/mamba-mcp/packages/mamba-mcp-gitlab/src/mamba_mcp_gitlab/server.py` - FastMCP server with AppContext, app_lifespan, and mcp instance
- `/Users/sequenzia/dev/repos/mamba-mcp/packages/mamba-mcp-gitlab/tests/test_server.py` - Server core tests (33 tests across 8 test classes)
- `/Users/sequenzia/dev/repos/mamba-mcp/packages/mamba-mcp-gitlab/src/mamba_mcp_gitlab/config.py` - 5 nested Pydantic settings classes (GitLabSettings, OAuthSettings, ServerSettings, RateLimitSettings, Settings)
- `/Users/sequenzia/dev/repos/mamba-mcp/packages/mamba-mcp-gitlab/src/mamba_mcp_gitlab/errors.py` - Error handling triad (12 codes, suggestions, create_tool_error) + fuzzy suggestion helpers (suggest_project_names, suggest_branch_names), build_error_context, clamp_pagination, pagination constants
- `/Users/sequenzia/dev/repos/mamba-mcp/packages/mamba-mcp-gitlab/tests/test_fuzzy_suggestions.py` - Fuzzy suggestions, pagination clamping, error context tests (62 tests across 8 test classes)
- `/Users/sequenzia/dev/repos/mamba-mcp/packages/mamba-mcp-gitlab/tests/test_errors.py` - Error handling tests (93 tests across 9 test classes)
- `/Users/sequenzia/dev/repos/mamba-mcp/packages/mamba-mcp-gitlab/src/mamba_mcp_gitlab/auth.py` - Auth strategies (AuthenticationError, AuthInfo, AuthStrategy protocol, PATAuthStrategy, OAuthAuthStrategy, detect_auth_strategy)
- `/Users/sequenzia/dev/repos/mamba-mcp/packages/mamba-mcp-gitlab/tests/test_auth.py` - PAT auth tests (44 tests across 8 test classes)
- `/Users/sequenzia/dev/repos/mamba-mcp/packages/mamba-mcp-gitlab/tests/test_oauth.py` - OAuth auth tests (57 tests across 11 test classes)
- `/Users/sequenzia/dev/repos/mamba-mcp/packages/mamba-mcp-gitlab/src/mamba_mcp_gitlab/rate_limit.py` - RateLimiter + RateLimitError (sliding window, configurable window_seconds, asyncio.Lock)
- `/Users/sequenzia/dev/repos/mamba-mcp/packages/mamba-mcp-gitlab/tests/test_rate_limit.py` - Rate limiter tests (55 tests across 12 test classes)
- `/Users/sequenzia/dev/repos/mamba-mcp/packages/mamba-mcp-gitlab/tests/test_config.py` - Config tests (52 tests across 8 test classes)
- `/Users/sequenzia/dev/repos/mamba-mcp/packages/mamba-mcp-gitlab/tests/conftest.py` - Shared test fixtures: autouse env reset, settings factories, MockAppContext, HTTP mock helpers
- `/Users/sequenzia/dev/repos/mamba-mcp/packages/mamba-mcp-gitlab/src/mamba_mcp_gitlab/models/common.py` - Shared Author and PaginatedOutput base models
- `/Users/sequenzia/dev/repos/mamba-mcp/packages/mamba-mcp-gitlab/src/mamba_mcp_gitlab/models/merge_requests.py` - MR models (9 classes)
- `/Users/sequenzia/dev/repos/mamba-mcp/packages/mamba-mcp-gitlab/src/mamba_mcp_gitlab/models/issues.py` - Issue models (6 classes)
- `/Users/sequenzia/dev/repos/mamba-mcp/packages/mamba-mcp-gitlab/src/mamba_mcp_gitlab/models/pipelines.py` - Pipeline models (6 classes)
- `/Users/sequenzia/dev/repos/mamba-mcp/packages/mamba-mcp-gitlab/src/mamba_mcp_gitlab/models/search.py` - Search models (2 classes)
- `/Users/sequenzia/dev/repos/mamba-mcp/packages/mamba-mcp-gitlab/src/mamba_mcp_gitlab/models/__init__.py` - Centralized exports (__all__ with 25 models)
- `/Users/sequenzia/dev/repos/mamba-mcp/packages/mamba-mcp-gitlab/tests/test_models.py` - Model tests (71 tests across 22 test classes)
- `/Users/sequenzia/dev/repos/mamba-mcp/packages/mamba-mcp-gitlab/src/mamba_mcp_gitlab/services/base.py` - GitLabService base class, GitLabAPIError, HTTP methods, pagination, URL helpers, error mapping
- `/Users/sequenzia/dev/repos/mamba-mcp/packages/mamba-mcp-gitlab/tests/test_base_service.py` - Base service tests (76 tests across 12 test classes)
- `/Users/sequenzia/dev/repos/mamba-mcp/packages/mamba-mcp-gitlab/src/mamba_mcp_gitlab/services/merge_request_service.py` - MergeRequestService with 6 methods (list_mrs, get_mr, get_mr_diffs, get_mr_commits, create_mr, update_mr)
- `/Users/sequenzia/dev/repos/mamba-mcp/packages/mamba-mcp-gitlab/tests/test_merge_request_service.py` - MR service tests (49 tests across 7 test classes)
- `/Users/sequenzia/dev/repos/mamba-mcp/packages/mamba-mcp-gitlab/src/mamba_mcp_gitlab/tools/mr_tools.py` - MR tool handlers (6 tools: list_mrs, get_mr, get_mr_diffs, get_mr_commits, create_mr, update_mr)
- `/Users/sequenzia/dev/repos/mamba-mcp/packages/mamba-mcp-gitlab/tests/test_mr_tools.py` - MR tool handler tests (37 tests across 7 test classes)
- `/Users/sequenzia/dev/repos/mamba-mcp/packages/mamba-mcp-gitlab/src/mamba_mcp_gitlab/services/issue_service.py` - IssueService with 6 methods (list, get, comments, create, update, add_comment)
- `/Users/sequenzia/dev/repos/mamba-mcp/packages/mamba-mcp-gitlab/tests/test_issue_service.py` - Issue service tests (42 tests across 8 test classes)
- `/Users/sequenzia/dev/repos/mamba-mcp/packages/mamba-mcp-gitlab/src/mamba_mcp_gitlab/services/search_service.py` - SearchService with search method (instance/project/group routing, scope validation)
- `/Users/sequenzia/dev/repos/mamba-mcp/packages/mamba-mcp-gitlab/tests/test_search_service.py` - Search service tests (26 tests across 8 test classes)
- `/Users/sequenzia/dev/repos/mamba-mcp/packages/mamba-mcp-gitlab/src/mamba_mcp_gitlab/tools/search_tools.py` - Search tool handler (7-step skeleton, always registered read-only)
- `/Users/sequenzia/dev/repos/mamba-mcp/packages/mamba-mcp-gitlab/tests/test_search_tools.py` - Search tool tests (16 tests across 6 test classes)
- `/Users/sequenzia/dev/repos/mamba-mcp/packages/mamba-mcp-gitlab/src/mamba_mcp_gitlab/tools/issue_tools.py` - Issue tool handlers (6 tools: list_issues, get_issue, list_issue_comments, create_issue, update_issue, add_issue_comment)
- `/Users/sequenzia/dev/repos/mamba-mcp/packages/mamba-mcp-gitlab/tests/test_issue_tools.py` - Issue tool tests (44 tests across 8 test classes)
- `/Users/sequenzia/dev/repos/mamba-mcp/packages/mamba-mcp-gitlab/src/mamba_mcp_gitlab/tools/pipeline_tools.py` - Pipeline tool handlers (4 tools: list_pipelines, get_pipeline, get_pipeline_jobs, get_job_log)
- `/Users/sequenzia/dev/repos/mamba-mcp/packages/mamba-mcp-gitlab/tests/test_pipeline_tools.py` - Pipeline tool tests (38 tests across 7 test classes)
- `/Users/sequenzia/dev/repos/mamba-mcp/pyproject.toml` - Root workspace config (updated with gitlab source + mypy overrides + respx dev dep)

## Task History

### Task [1]: Scaffold mamba-mcp-gitlab package structure - PASS
- Files modified: 24 files created (pyproject.toml, README.md, 20 Python modules, 2 test files)
- Root pyproject.toml updated (sources, mypy overrides)
- Key learnings: hatchling needs README.md to exist; workspace glob auto-discovers but sources need explicit entry
- Issues encountered: Build failed without README.md -- created minimal one to unblock

### Task [2]: Implement mamba-mcp-gitlab configuration - PASS
- Files modified: `config.py` (implemented 5 settings classes), `test_config.py` (52 tests), `conftest.py` (autouse fixture)
- Key learnings: GitLab config differs from PG/HANA in having 4 nested groups (gitlab, oauth, server, rate_limit) vs 2 (database, server). ServerSettings uses `MAMBA_MCP_GITLAB_SERVER_` prefix (not `MAMBA_MCP_GITLAB_`). Empty string handling via `field_validator(mode="before")` for optional int/str fields.
- Issues encountered: Import ordering in test_config.py needed `import mamba_mcp_gitlab` before `from` imports per isort rules. Ruff auto-formatted some line breaks.

### Task [3]: Implement mamba-mcp-gitlab error handling - PASS
- Files modified: `errors.py` (implemented), `test_errors.py` (created with 66 tests)
- Key learnings: GitLab errors follow PG pattern (dict return type via `.model_dump()`); ruff auto-formats parenthesized strings differently than written; error suggestions from spec Section 7.7 reference tool names like `search`, `list_mrs`, `list_issues`, `list_pipelines`
- Issues encountered: Minor ruff formatting adjustment on one line (auto-fixed)

### Task [9]: Create Pydantic I/O models for all resources - PASS
- Files modified: `models/common.py` (created), `models/merge_requests.py`, `models/issues.py`, `models/pipelines.py`, `models/search.py`, `models/__init__.py`, `tests/test_models.py` (created with 71 tests)
- Key learnings: Shared `Author` and `PaginatedOutput` models go in `models/common.py` and are imported by all resource modules. Summary/Detail inheritance pattern (e.g., MergeRequestDetail extends MergeRequestSummary) keeps fields DRY. Date fields stored as `str` (not datetime) for flexibility with ISO 8601 formats. `from __future__ import annotations` must be in a separate import block per ruff isort rules (not grouped with third-party imports).
- Issues encountered: Ruff isort (I001) flagged `from __future__ import annotations` grouped with third-party imports -- auto-fixed with `ruff check --fix`. Ruff format also required reformatting of 5 files -- applied with `ruff format`.

### Task [4]: Implement PAT authentication strategy - PASS
- Files modified: `auth.py` (implemented from placeholder), `tests/test_auth.py` (created with 44 tests across 8 test classes)
- Key learnings: `AuthStrategy` uses `@runtime_checkable Protocol` so `isinstance()` checks work. `httpx.MockTransport` is the cleanest way to mock HTTP responses for async validation tests (no need for respx for this pattern). `from __future__ import annotations` must always be in its own import block (ruff I001). `detect_auth_strategy()` factory function named per spec (not `get_auth_strategy` as in initial task description -- the detailed task #4 description uses `detect_auth_strategy` matching the spec). Token format validation (`_validate_token_format`) runs at construction time, not deferred to `validate()`.
- Issues encountered: Ruff isort (I001) on test file needed `from __future__ import annotations` separated. Ruff format reformatted 2 files. Unused imports (ErrorCode, create_tool_error) removed from auth.py since auth module uses AuthenticationError directly, not tool error dicts.

### Task [5]: Implement base service class - PASS
- Files modified: `services/base.py` (implemented from placeholder), `tests/test_base_service.py` (created with 75 tests across 12 test classes)
- Key learnings: `respx` is the preferred httpx mocking library for async tests (`@respx.mock` decorator pattern). `GitLabAPIError` exception with `error_code` and `status_code` fields is the clean way to propagate API errors from service layer. Settings can be constructed inline for tests by passing nested dicts. `_parse_json_body()` and `_safe_int()` are module-level helpers that handle edge cases (empty body, non-JSON, missing headers). `_build_project_url` uses `urllib.parse.quote(safe="")` to URL-encode string project paths. Auth headers are configured at `httpx.AsyncClient` level (via headers param), not injected per-request by the base service.
- Issues encountered: `respx` was not installed as a dev dependency -- added via `uv add --group dev respx`. Ruff format needed to be applied after writing both files (2 files reformatted). `ruff` command not on PATH directly -- must use `uv run ruff`.

### Task [10]: Implement MergeRequestService - PASS
- Files modified: `services/merge_request_service.py` (implemented from placeholder), `tests/test_merge_request_service.py` (created with 49 tests across 7 test classes)
- Key learnings: MergeRequestService follows exact same pattern as IssueService: inherits from GitLabService, uses `_resolve_project_id`, `_build_project_url`, `_get`, `_get_paginated`, `_post`, `_put`. Error remapping: 404 on list -> PROJECT_NOT_FOUND, 404 on get/diffs/commits/update -> MERGE_REQUEST_NOT_FOUND, 404 on create with "branch"/"source" in message -> BRANCH_NOT_FOUND, else PROJECT_NOT_FOUND. Labels are converted with `",".join(labels)` for GitLab API comma-separated format. `update_mr` only sends fields that are not None (empty dict if nothing provided). `_make_service()` and `_make_settings()` helper functions are duplicated per test file (not shared) -- consistent with project pattern.
- Issues encountered: One line exceeded 100-char limit (E501) in branch-not-found error message -- fixed by splitting into multi-line parenthesized f-string. Ruff format reformatted 2 files after initial write.

### Task [12]: Implement IssueService - PASS
- Files modified: `services/issue_service.py` (implemented from placeholder), `tests/test_issue_service.py` (created with 42 tests across 8 test classes)
- Key learnings: Service classes inherit from `GitLabService` and use `_resolve_project_id`, `_build_project_url`, `_get`, `_get_paginated`, `_post`, `_put` from the base class. Error remapping pattern: catch `GitLabAPIError`, check `status_code`, re-raise with domain-specific error code (e.g., 404 -> `ISSUE_NOT_FOUND`, 400 -> `VALIDATION_ERROR`). Paginated methods return dict with `items`, `page`, `per_page`, `total`, `total_pages` keys. Labels are passed as comma-separated strings (not lists) per GitLab API convention. Import blocks in test files need third-party and local imports in the same block (no blank line between `import respx` and `from mamba_mcp_gitlab...`) per ruff isort rules for this project.
- Issues encountered: Ruff isort (I001) flagged blank line between third-party and local imports in test file. Ruff format reformatted 1 file. Both resolved by removing blank line and running `ruff format`.

### Task [14]: Implement PipelineService - PASS
- Files modified: `services/pipeline_service.py` (implemented from placeholder), `tests/test_pipeline_service.py` (created with 38 tests across 6 test classes)
- Key learnings: For endpoints returning plain text (not JSON), added a `_get_text()` method on the service subclass rather than modifying the base class. This method follows the same error handling pattern as `_request()` but returns `response.text` instead of parsed JSON. Truncation logic: encode to bytes, slice at max_bytes, decode with `errors="ignore"` for safe boundary handling. The `_map_status_to_error_code` function is importable from `services.base` for use by subclass text methods. Error remapping: pipeline 404 -> `PIPELINE_NOT_FOUND`, job 404 -> `NOT_FOUND` (different codes for different resources). Ruff UP032 rule: prefer f-strings over `.format()`.
- Issues encountered: Ruff UP032 flagged `.format()` call -- converted to f-string. Ruff isort (I001) flagged import block in test file -- auto-fixed. Ruff format reformatted 2 files. Pre-existing test failures in other modules (test_errors.py, test_server.py) from unimplemented features in parallel tasks -- not related to this task.

### Task [21]: Polish error messages with fuzzy suggestions - PASS
- Files modified: `errors.py` (added 4 new functions + 3 pagination constants), `tests/test_fuzzy_suggestions.py` (created with 62 tests across 8 test classes), `tests/test_errors.py` (restored imports for new symbols used by tests added by concurrent tasks)
- Key learnings: `suggest_project_names()` and `suggest_branch_names()` wrap `find_similar_names()` defensively with bare `except Exception` to catch all errors including MemoryError. `build_error_context()` uses keyword-only args and only includes non-None values in context dict. `clamp_pagination()` returns a tuple of (page, per_page) with defaults (1, 20) and per_page clamped to [1, 100]. Pagination constants exported as `PAGINATION_DEFAULT_PER_PAGE`, `PAGINATION_MIN_PER_PAGE`, `PAGINATION_MAX_PER_PAGE`. The `__all__` list in errors.py was updated to include all new exports (11 total). `test_errors.py` was already modified by concurrent tasks to include tests for the new helpers, so imports needed to be kept in sync.
- Issues encountered: `test_errors.py` had been extended by concurrent tasks (8, 10, 12, 14) with test classes for the new functions but originally had unused import warnings. Required careful import management -- restored all imports that the file's test classes actually use. Ruff isort (I001) needed `from __future__ import annotations` in separate block in test_fuzzy_suggestions.py -- fixed with `ruff check --fix`. Ruff format reformatted 2 test files.

### Task [6]: Implement server core with AppContext and lifespan - PASS
- Files modified: `server.py` (implemented from placeholder), `config.py` (added `max_connections` field to ServerSettings), `tests/test_server.py` (created with 33 tests across 8 test classes)
- Key learnings: httpx internal attributes changed across versions -- `_pool` is not directly on `AsyncClient`, it is at `_transport._pool`. To avoid relying on private attributes, use `patch.object(httpx.AsyncClient, "__init__", capture_fn)` pattern to capture kwargs (limits, verify) passed to the constructor. Similarly, SSL context verification uses the same capture pattern rather than inspecting internal `_ssl_context` attribute. `sys.exit(1)` is the correct error path for startup failures (not raising SystemExit directly via `raise`). Rate limiter is a placeholder (stores `RateLimitSettings | None`) until Task #19 implements the actual `RateLimiter` class. `ruff check --fix` auto-handles isort (I001) and unused import (F401) issues.
- Issues encountered: Initial tests failed because httpx `_pool` attribute access path was wrong. SSL context check also failed because httpx creates an SSLContext even with `verify=False`. Both fixed by switching to constructor capture pattern. `FastMCP` not imported in test file caused NameError. Unused `Any` import in server.py flagged by ruff (F401). All resolved in second iteration.

### Task [8]: Add Phase 1 foundation smoke tests - PASS
- Files modified: `tests/conftest.py` (enhanced with shared fixtures), `tests/test_errors.py` (added 27 new tests for suggest/context/pagination), `tests/test_base_service.py` (added 1 new test for _get_paginated HTTPError), `pyproject.toml` (added asyncio_mode = "auto")
- Key learnings: conftest.py now provides `make_settings()` factory function, `MockAppContext` dataclass, `mock_settings`/`mock_app_context` fixtures, `make_gitlab_api_response()` and `make_paginated_headers()` helpers. Task #21 added `suggest_project_names`, `suggest_branch_names`, `build_error_context`, `clamp_pagination` to errors.py -- these needed test coverage added in test_errors.py. `_get_paginated` generic HTTPError path needed one more test for 100% coverage on base.py. `asyncio_mode = "auto"` is in root pyproject.toml (applies globally) but also added to package pyproject.toml for explicitness.
- Issues encountered: Ruff auto-formatter reverted imports in test_errors.py during concurrent test runs -- resolved by re-reading the file and letting the auto-fix apply. Pre-existing linter errors in server.py, test_server.py (from task #6) are not related to this task.
- Coverage results: config.py 100%, errors.py 100%, auth.py 100%, services/base.py 100%. Total 336 foundation tests pass.

### Task [16]: Implement SearchService and search tool - PASS
- Files modified: `services/search_service.py` (implemented from placeholder), `tools/search_tools.py` (implemented from placeholder), `tests/test_search_service.py` (created with 26 tests across 8 test classes), `tests/test_search_tools.py` (created with 16 tests across 6 test classes)
- Key learnings: SearchService does NOT use `_resolve_project_id()` or `_build_project_url()` from the base class because search has a 3-tier routing model (instance/project/group) instead of the project-only pattern used by MR/Issue/Pipeline services. Custom `_resolve_search_path()` method handles the priority chain: explicit project_id > explicit group_id > default_project_id > default_group_id > instance-wide. The `VALID_SCOPES` set is module-level for easy import and testing. Rate limit (429) errors are explicitly remapped in the service layer. Tool handler tests use `FakeContext`/`FakeRequestContext` dataclasses to simulate MCP context without FastMCP runtime. Error dict keys from `create_tool_error()` use `code` (not `error_code`) because it calls `ToolError.model_dump()` and the Pydantic model field is named `code`.
- Issues encountered: Initial tool tests failed because assertions used `result["error_code"]` instead of `result["code"]`. Fixed by updating all error assertions. Unused imports flagged by ruff F401 -- removed. Ruff format reformatted 3 of 4 files.

### Task [20]: Implement OAuth 2.0 authentication flow - PASS
- Files modified: `auth.py` (added OAuthAuthStrategy class + updated detect_auth_strategy), `tests/test_auth.py` (updated 1 test for OAuth integration), `tests/test_oauth.py` (created with 57 tests across 11 test classes)
- Key learnings: OAuth client credentials flow: POST `{gitlab_url}/oauth/token` with `grant_type=client_credentials`, `client_id`, `client_secret`. Token response includes `access_token`, optional `refresh_token`, and `expires_in` (seconds). Validation via `GET /api/v4/user` with Bearer header (different from PAT which uses `/api/v4/personal_access_tokens/self`). Token expiry tracked with `time.monotonic()` (not `time.time()`) for robustness. 30-second buffer before actual expiry. Refresh flow has 3-level fallback: refresh_token grant -> client_credentials re-obtain -> raise error. `__all__` in auth.py updated with `OAuthAuthStrategy`. Existing test `test_oauth_only_raises_not_implemented` needed update to `test_oauth_only_returns_oauth_strategy`.
- Issues encountered: One test (`test_refresh_falls_back_on_non_200_status`) initially failed because the fallback `_obtain_token` response included a refresh_token that overwrote the cleared state. Fixed by making the fallback mock response exclude `refresh_token`. Ruff format reformatted both files after initial write.

### Task [7]: Implement CLI entry point with test subcommand - PASS
- Files modified: `__main__.py` (implemented from placeholder), `tests/test_cli.py` (created with 19 tests across 7 test classes)
- Key learnings: When mocking an auth strategy that has both sync methods (`get_headers()`) and async methods (`validate()`), use `MagicMock` for the strategy object and set `strategy.validate = AsyncMock()` separately. Using `AsyncMock()` for the whole object makes ALL methods async, causing `get_headers()` to return a coroutine instead of a dict, which triggers `TypeError("'coroutine' object is not iterable")`. The GitLab test subcommand differs from PG/HANA: it validates auth via `detect_auth_strategy()` + `auth_strategy.validate()` against the GitLab API, rather than testing a database connection. Success message follows spec format: `"Connection successful -- authenticated as {username} with scopes: {scopes}"`. Tool modules are imported for side-effect registration even though they are currently placeholders.
- Issues encountered: Initial tests had 9 failures due to `AsyncMock` making `get_headers()` async. Fixed by switching to `MagicMock` + selective `AsyncMock` for `validate`. Pre-existing failures in test_mr_tools.py (19 failures from concurrent task #11) and test_server.py (1 failure from concurrent task #19) are unrelated.

### Task [13]: Implement Issue tool handlers (6 tools) - PASS
- Files modified: `tools/issue_tools.py` (implemented from placeholder with 6 tools), `tests/test_issue_tools.py` (created with 44 tests across 8 test classes)
- Key learnings: `create_tool_error()` returns a dict with key `code` (not `error_code`) -- the ToolError model from mamba-mcp-core uses `code` as the field name. Tool handler tests use `patch("...IssueService", return_value=mock_service)` pattern to mock service construction. Mock MCP context built with `FakeAppContext` + `FakeRequestContext` dataclasses + `MagicMock`. `asyncio.iscoroutinefunction` deprecated in Python 3.14+ -- use `inspect.iscoroutinefunction`. Tool annotations: read tools `readOnlyHint=True, idempotentHint=True`, write tools `readOnlyHint=False, idempotentHint=False`. Pagination clamping via `clamp_pagination()` in tool handler before service delegation. Error context built with `build_error_context(elapsed_ms=..., status_code=...)`.
- Issues encountered: Initial 19 test failures from `result["error_code"]` instead of `result["code"]`. Ruff removed unused `pytest` import. Ruff reformatted both files.

### Task [11]: Implement MR tool handlers (6 tools) - PASS
- Files modified: `tools/mr_tools.py` (implemented 6 tools from placeholder), `tests/test_mr_tools.py` (created with 37 tests across 7 test classes)
- Key learnings: Tool handler pattern for GitLab follows 7-step skeleton: start_time, ctx None check, extract app_ctx, create service, delegate, convert to Pydantic output, catch exceptions. `create_tool_error().model_dump()` produces dict with key `code` (not `error_code`) -- the ToolError Pydantic model field is named `code`. `MergeRequestService(app_ctx.client, app_ctx.settings)` -- base service takes only (http_client, settings), NOT (http_client, auth, settings) as task description initially suggested. Auth headers are already configured on the httpx.AsyncClient in app_lifespan. `clamp_pagination()` should be called before passing page/per_page to service methods. `mcp._tool_manager._tools.keys()` provides synchronous access to registered tool names (since `mcp.list_tools()` is async). Ruff N806 rule requires `mock_service` not `MockService` for `with patch(...) as` variables. Concurrent Task #23 added `get_mr_pipelines` tool and pipeline model imports to mr_tools.py.
- Issues encountered: Initial tests used `result["error_code"]` but correct key is `result["code"]` (from ToolError.model_dump()). Tool registration test initially used `mcp.list_tools()` which is async coroutine -- fixed by using `mcp._tool_manager._tools.keys()` synchronously. Ruff N806 flagged `MockService` as uppercase variable name -- renamed to `mock_service` across all 30 occurrences. Ruff auto-fixed 2 unused imports added by concurrent Task #23 (`ListPipelinesOutput`, `get_mr_pipelines`).

### Task [23]: Add MR tools to get_mr_pipelines endpoint - PASS
- Files modified: `services/merge_request_service.py` (added get_mr_pipelines as method #7), `tools/mr_tools.py` (added get_mr_pipelines tool handler + pipeline model imports, updated docstring to 7 tools), `tests/test_merge_request_service.py` (added TestGetMrPipelines with 9 tests), `tests/test_mr_tools.py` (added TestGetMrPipelines with 9 tests, updated imports + registration test to 7 tools)
- Key learnings: Cross-resource query pattern: `get_mr_pipelines` lives in MergeRequestService (not PipelineService) because the API endpoint is `/projects/{id}/merge_requests/{mr_iid}/pipelines` -- scoped under MRs. The tool reuses `ListPipelinesOutput` from `models/pipelines.py` (same pagination format as `list_pipelines`). When adding a method to a service already implemented, append at the end of the class. When adding a tool to a tools module already implemented, insert in the logical section (read tools section, before write tools) and update the module docstring. Tool registration test needs updating to include the new tool name. MergeRequestService now has 7 methods. Total MR tools: 7 (was 6).
- Issues encountered: Ruff auto-formatting on save caused repeated edit failures (file modified since read). Resolved by re-reading after each linter cycle. No test failures -- 870 total tests pass.

### Task [19]: Implement sliding window rate limiter - PASS
- Files modified: `rate_limit.py` (implemented from placeholder), `server.py` (replaced RateLimitSettings placeholder with actual RateLimiter), `services/base.py` (added rate_limiter param + _check_rate_limit method), `tests/test_rate_limit.py` (created with 55 tests across 12 test classes), `tests/test_server.py` (updated 3 AppContext tests + 1 lifespan test for RateLimiter type)
- Key learnings: GitLab rate limiter differs from FS version: (1) configurable window_seconds (not hardcoded 60s), (2) uses asyncio.Lock for thread safety, (3) combined acquire() method (check + record in one call), (4) raises RateLimitError with retry_after/max_requests/window_seconds attributes (not FS's RateLimitedError exception). Rate limiter integrates into base service via optional `rate_limiter` parameter -- existing services without rate limiter are unaffected (None default). `_check_rate_limit()` catches `RateLimitError` and wraps it as `GitLabAPIError(error_code=RATE_LIMITED)` for consistent error propagation to tool handlers. Server's `AppContext.rate_limiter` field changed from `RateLimitSettings | None` to `RateLimiter` -- required updating test_server.py tests that referenced the old placeholder type.
- Issues encountered: One pre-existing server test (`test_rate_limiter_placeholder_set`) failed because it asserted `isinstance(ctx.rate_limiter, RateLimitSettings)` -- updated to assert `isinstance(ctx.rate_limiter, RateLimiter)` with correct attribute checks. Two other AppContext tests passed `rate_limiter=None` which no longer matches the `RateLimiter` type annotation -- updated to pass `RateLimiter(max_requests=0)`. All 164 combined tests (server + base service + rate limit) pass.

### Task [15]: Implement Pipeline tool handlers (4 tools) - PASS
- Files modified: `tools/pipeline_tools.py` (implemented from placeholder), `tests/test_pipeline_tools.py` (created with 38 tests across 7 test classes)
- Key learnings: Tool handler tests use `MagicMock` for context and `patch("mamba_mcp_gitlab.tools.pipeline_tools.PipelineService")` to mock the service class. Error dicts from `create_tool_error()` use key `"code"` (not `"error_code"`) because the core `ToolError` Pydantic model field is named `code` and `.model_dump()` preserves field names. Ruff N806 rule disallows uppercase variable names in functions -- use `mock_svc` not `MockService` when patching classes. Pagination params use `clamp_pagination()` from errors module for consistent validation. `max_bytes` for job logs clamped to [1024, 1048576] range with 102400 (100KB) default. All pipeline tools are read-only (always registered, no conditional gating). `VALID_PIPELINE_STATUSES` frozenset exported for documentation and testing.
- Issues encountered: Initial tests failed with `KeyError: 'error_code'` because assertions used `result["error_code"]` instead of `result["code"]`. Fixed by updating all error key references. Ruff N806 flagged `MockService` variable name -- renamed to `mock_svc` globally. Ruff I001 and F401 auto-fixed on first pass. Ruff format reformatted test file.

### Task [17]: Implement read-only mode and project/group scoping - PASS
- Files modified: `errors.py` (added READ_ONLY error code, WRITE_TOOL_NAMES constant, check_read_only helper), `tools/mr_tools.py` (added read-only gate to create_mr, update_mr), `tools/issue_tools.py` (added read-only gate to create_issue, update_issue, add_issue_comment), `tests/test_read_only.py` (created with 53 tests across 11 test classes), `tests/test_errors.py` (updated ALL_ERROR_CODES list from 12 to 13, updated count test), `tests/test_issue_tools.py` (updated _make_ctx to provide default settings)
- Key learnings: Runtime read-only gating (checking settings inside tool handler at call time) is the cleanest approach since FastMCP registers tools at import time via `@mcp.tool()` decorators before settings are available. The `check_read_only(read_only, tool_name) -> dict | None` pattern returns None to proceed or error dict to short-circuit -- simple and testable. Adding new ErrorCode constants requires updating test_errors.py (ALL_ERROR_CODES list + count assertion). When adding runtime checks that access `app_ctx.settings`, existing tests using FakeAppContext with `settings=None` will break -- must update those test fixtures to provide `make_settings()` defaults. The `WRITE_TOOL_NAMES` frozenset is exported for documentation and testing purposes. Project/group scoping was already fully implemented in base service and search service -- just needed test coverage.
- Issues encountered: Adding `check_read_only` to write tool handlers caused 17 existing test_issue_tools.py failures because FakeAppContext had `settings=None` and the check accesses `settings.gitlab.read_only`. Fixed by updating `_make_ctx()` to default to `make_settings()`. Also 1 test_errors.py failure because error code count increased from 12 to 13 -- updated test assertion. Ruff removed 6 unused imports from test_read_only.py (imported pipeline/MR tools not directly tested). Ruff isort reformatted import blocks.

### Task [18]: Add comprehensive tool tests with mock transport - PASS
- Files modified: `tests/test_coverage_gaps.py` (created with 140 tests across 13 test classes)
- Key learnings: The existing 927-test suite already had good per-tool coverage but was missing systematic HTTP error code testing across all tools. Using `@pytest.mark.parametrize` with a shared `HTTP_ERROR_CASES` list (5 status codes x all tools) is the most efficient way to verify error propagation. PipelineService truncation at multi-byte character boundaries works correctly via `errors="ignore"` in `.decode()`. Error response dicts from `create_tool_error()` always include `code`, `message`, `tool_name`, `suggestion`, `input_received`, and `context` keys. The `_map_status_to_error_code` function maps unmapped 4xx codes to `API_ERROR` (not just 5xx). MR tools construct `MergeRequestService(app_ctx.client, app_ctx.settings)` (positional args), while issue/pipeline tools use `IssueService(http_client=..., settings=...)` (keyword args) -- both work but the assertion pattern differs in tests.
- Issues encountered: Two f-strings without placeholders flagged by ruff F541 in respx URL strings -- fixed by removing `f` prefix. Ruff format reformatted the file after lint fixes. Total test suite: 1067 tests (927 original + 140 new), all passing.

### Task [22]: Add CI integration and update CLAUDE.md - PASS
- Files modified: `.github/workflows/ci.yml` (added mamba-mcp-gitlab to test matrix), `CLAUDE.md` (7 updates: Project Overview, Development Commands, Repository Structure, Architecture section, Dependency Graph, tool count, CI/CD Notes)
- Key learnings: CI workflow already runs lint (`ruff check packages/`) and type-check (`mypy packages/`) on the entire `packages/` directory, so those steps automatically include any new package. Only the test matrix needed an explicit entry since it uses per-package `uv run --package` isolation. The `fail-fast: false` strategy ensures one package's test failure does not cancel other packages' test runs. CLAUDE.md had a stale note saying mamba-mcp-client was "not in the CI test matrix" when it actually was -- fixed during this update. GitLab package has 18 tools (MR: 7, Issue: 6, Pipeline: 4, Search: 1), bringing the total across all servers from 31 to 49.
- Issues encountered: None. All changes were straightforward documentation/config updates.

### Task [24]: Generate coverage report and verify targets - PASS
- Files modified: `tests/test_merge_request_service.py` (added 7 tests in TestNon404ErrorReRaise class for non-404 error re-raise paths)
- Key learnings: Coverage report command: `uv run --package mamba-mcp-gitlab pytest packages/mamba-mcp-gitlab/ --cov=mamba_mcp_gitlab --cov-report=term-missing -v`. Initial coverage was 99% overall (1067 tests, 8 missed lines). 7 of 8 missed lines were bare `raise` statements in `merge_request_service.py` (non-404 error re-raise paths in all 7 methods). The remaining 1 missed line is `__main__.py:135` (`app()` inside `if __name__ == "__main__"`) which is standard and unreachable in pytest. After adding 7 tests for the non-404 re-raise paths, coverage reached 99% (1 line remaining) with 1074 tests all passing.
- Coverage results: errors.py 100%, auth.py 100%, all services/ 100%, all tools/ 100%, all models/ 100%, config.py 100%, server.py 100%, rate_limit.py 100%. Only __main__.py at 98% (1 unreachable line). Total: 1485 stmts, 1 miss, 99% coverage.
