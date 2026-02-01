# Execution Context

## Project Patterns
- Tool pattern: `tools/relationship_tools.py` defines MCP tools using `@mcp.tool()` decorator imported from `server.py`; each tool extracts pool via `ctx.request_context.lifespan_context.pool`, creates service instance, calls async method, checks `isinstance(result, ToolError)`, returns `model_dump_json()`
- Tool pattern: Tools are registered by importing the module in `tools/__init__.py` (e.g., `from mamba_mcp_sap_hana.tools import relationship_tools`)
- Tool pattern: Tool return type is `str` (JSON-serialized), not the Pydantic model directly -- matches MCP's string return convention
- Tool pattern: `find_join_path` defaults `to_schema` to `from_schema` when `None`; `max_depth` clamped with `max(1, min(6, val))`
- Test pattern for tools: Patch `RelationshipService` at the tools module level (`mamba_mcp_sap_hana.tools.relationship_tools.RelationshipService`), use `AsyncMock` for async service methods, `_make_mock_ctx()` helper for FastMCP context mock, `json.loads()` result for assertions
- Test pattern for tools: `TestToolRegistration` class verifies tools are registered by inspecting `server._tool_manager._tools.values()`
- Server pattern: `server.py` follows mamba-mcp-postgres pattern: `AppContext` dataclass + `app_lifespan` async context manager + module-level `mcp = FastMCP(name, lifespan=app_lifespan)`
- Server pattern: `AppContext` fields are `pool` (HanaConnectionPool) and `settings` (Settings), accessible to tools via `ctx.request_context.lifespan_context`
- Server pattern: Lifespan calls `get_settings()` -> `create_pool(settings.database)` -> `pool.test_connection()` -> yield -> `pool.close()`
- Server pattern: Pool creation and connection test failures raise `SystemExit(1)` for clean exit; shutdown errors are caught and logged as warnings
- Server pattern: `SERVER_NAME` constant and `__version__` import used for log messages during initialization
- FastMCP note: In mcp>=1.0.0, lifespan is not stored as `_lifespan` attribute on FastMCP; it's wrapped internally. Access via `mcp._mcp_server.lifespan` for testing
- UV workspace monorepo with `members = ["packages/*"]` glob pattern
- Package pyproject.toml follows consistent structure: hatchling build backend, `src/` layout, `[tool.hatch.build.targets.wheel]` for package path
- Ruff and MyPy config live at workspace root pyproject.toml only; individual packages inherit (no local tool config)
- `__init__.py` docstrings follow pattern: `"""Description for X MCP Server."""`
- Root `__init__.py` includes `__version__ = "0.1.0"`
- Sub-package `__init__.py` files have only docstrings initially; imports added later as modules are created
- Package-level `tests/__init__.py` has a brief docstring
- Each package requires a `README.md` file for hatchling build to succeed (referenced in pyproject.toml)
- Config pattern: module-level `_env_file_path` state with `set_env_file_path()`/`get_env_file_path()` functions
- Config pattern: Sub-settings classes (DatabaseSettings, ServerSettings) with `env_prefix="MAMBA_MCP_HANA_"`, root Settings uses `env_nested_delimiter="__"`
- Config pattern: Root Settings uses `model_validator(mode="before")` to instantiate sub-settings with `_env_file` kwarg
- Test pattern: `conftest.py` with autouse fixture to reset `_env_file_path` between tests
- Test pattern: Use `_env_file=None` when constructing settings in tests to avoid picking up real env files
- Test pattern: Use `monkeypatch.setenv()` for env var testing, `monkeypatch.chdir()` for cwd-dependent tests
- Error pattern: `ErrorCode` class with string constants (not enum) for error codes; `ToolError` flat Pydantic model (code, message, suggestion, context, tool_name, input_received)
- Error pattern: `ERROR_SUGGESTIONS` dict maps each ErrorCode to a default suggestion string; `create_tool_error` factory uses fallback from map when no custom suggestion provided
- Error pattern: `_levenshtein_distance` private function for edit distance; `suggest_similar` public function with threshold-based filtering (threshold scales with name length)
- Connection pattern: Queue-based async pool (`asyncio.Queue`) wrapping synchronous hdbcli connections with `asyncio.to_thread` for non-blocking operation
- Connection pattern: `build_connection_params()` builds hdbcli param dict from DatabaseSettings; user/password takes precedence over userkey
- Connection pattern: Health checks via `SELECT 1 FROM DUMMY` (HANA's equivalent of `SELECT 1`)
- Connection pattern: `_create_connection`, `_check_connection_health`, `_close_connection` are module-level private functions (easy to mock in tests)
- Connection pattern: Pool uses `asyncio.Lock` for thread-safe creation count management
- Test pattern: Helper functions `_make_mock_connection(healthy=True)` and `_make_pool()` for test setup
- Test pattern: Use `unittest.mock.patch` on module-level private functions for pool testing without real hdbcli
- Model pattern: Layer models in `models/schema.py`, `models/relationships.py`, `models/query.py`, `models/hana.py` -- one file per layer
- Model pattern: Input models use `Field(default=...)` for optional params, `Field(ge=, le=)` for numeric ranges, `Literal[...]` for enum-like values
- Model pattern: Output models use `default_factory=list` for optional list fields (indexes, constraints)
- Model pattern: All models exported via `models/__init__.py` with `__all__` list organized by layer comments
- Test pattern: Model tests organized as one `TestXxx` class per model, covering instantiation, serialization (dict + JSON), validation rejection, and edge cases
- Query model pattern: Input models use `min_length=1` + `max_length=MAX_SQL_LENGTH` on SQL field, plus `field_validator` to reject whitespace-only strings
- Query model pattern: `params` typed as `list[Any] | dict[str, Any] | None` to support HANA's `?` positional and `:name` named parameters
- Query model pattern: `QueryResult` is a separate model from `ExecuteQueryOutput` -- output wraps result with `query_hash` for caching
- QueryService pattern: Module-level private functions (`_validate_sql_readonly`, `_generate_query_hash`, `_strip_comments_and_strings`, `_execute_query_sync`, `_explain_query_sync`) for testability without full async setup
- QueryService pattern: Returns `ExecuteQueryOutput | ToolError` union type (not raising exceptions) -- callers check `isinstance(result, ToolError)` to handle errors
- QueryService pattern: Comment/string stripping before blocked keyword detection prevents bypass via `-- INSERT` comments or `'DELETE'` string literals
- QueryService pattern: HANA EXPLAIN PLAN uses `EXPLAIN PLAN SET STATEMENT_NAME = '{uuid}' FOR {sql}` then reads from `EXPLAIN_PLAN_TABLE`; cleanup via DELETE with unique statement name
- QueryService pattern: `asyncio.wait_for` wraps `asyncio.to_thread` for timeout enforcement at the async level; statement timeout also set via `conn.setclientinfo("SESSIONVARIABLE:STATEMENT_TIMEOUT", ...)`
- QueryService pattern: Truncation detected by fetching `max_rows + 1` rows then slicing back to `max_rows`
- HANA model pattern: `CalcViewInfo` and `ProcedureInfo` use `default_factory=list` for nested details (columns/parameters) that are conditionally populated by input `include_columns`/`include_parameters` flags
- HANA model pattern: `ProcedureParameterInfo.direction` uses `Literal["IN", "OUT", "INOUT"]` for HANA's three parameter directions
- HANA model pattern: `DescribeCalcViewOutput.parameters` uses `list[dict[str, Any]]` for flexible calc view input parameter structure
- HanaService pattern: Class-based service with `__init__(self, pool)` matching SchemaService/RelationshipService pattern. Uses `_verify_schema_exists` internal method taking an active connection (not acquiring its own) for efficiency
- HanaService pattern: `list_calculation_views` queries SYS.VIEWS with VIEW_TYPE IN ('CALC', 'JOIN', 'OLAP') for calc view filtering. Column metadata fetched per-view when `include_columns=True`
- HanaService pattern: `get_table_store_type` checks for views first (returns PARAMETER_ERROR for views), then queries SYS.TABLES. IS_PRELOAD used as compression indicator. Partition count fetched from SYS.TABLE_PARTITIONS only when HAS_PARTITIONS is TRUE
- HanaService pattern: Implications text is module-level constant strings (COLUMN_STORE_IMPLICATIONS, ROW_STORE_IMPLICATIONS) for testability and consistency
- HanaService pattern: `list_procedures` queries SYS.PROCEDURES with parameter count subquery, fetches SYS.PROCEDURE_PARAMETERS per-procedure when `include_parameters=True`
- HanaService pattern: All three methods use `fnmatch.fnmatchcase` for name_pattern filtering after converting SQL LIKE (% -> *, _ -> ?) -- same pattern as SchemaService
- HanaService model addition: `StoreTypeInfo`, `GetTableStoreTypeInput`, `GetTableStoreTypeOutput` added to models/hana.py (15 total models now, up from 12)
- RelationshipService pattern: Queries `SYS.REFERENTIAL_CONSTRAINTS` for FK discovery; rows grouped by CONSTRAINT_NAME for composite FK support
- RelationshipService pattern: BFS graph uses bidirectional adjacency list with `direction` ("outgoing"/"incoming") on each edge for JoinStep output
- RelationshipService pattern: `_verify_table_exists` uses UNION ALL (SYS.TABLES + SYS.VIEWS) in a single query, then fuzzy matching on TABLES_IN_SCHEMA_SQL if not found
- RelationshipService pattern: Module-level private functions (`_execute_query`, `_group_fk_rows`, `_build_fk_graph`, `_bfs_find_paths`, `_generate_sql_join`, `_path_to_join_steps`) for unit testing without async setup
- RelationshipService pattern: ALL_FK_SQL returns 7 columns (no DELETE_RULE); OUTGOING/INCOMING FK queries return 8 columns (with DELETE_RULE)
- CLI pattern: `__main__.py` with Typer `app`, `validate_env_file` callback, `resolve_default_env_file`, `setup_logging`, `main` callback (serve), `test` command
- CLI pattern: `app.callback(invoke_without_command=True)` routes to serve when no subcommand; sets `env_file_path` for subcommands
- Tool pattern: All MCP tools return `str` (JSON-serialized via `model_dump_json()`). Tools extract pool from `ctx.request_context.lifespan_context`, construct service, call async method, check `isinstance(result, ToolError)`, serialize. Tools validate input ranges at tool layer before service calls (e.g., limit range validation returns PARAMETER_ERROR).
- Tool pattern: Tool registration via `tools/__init__.py` importing each tool module triggers `@mcp.tool()` decorators at import time
- Tool test pattern: `_make_mock_ctx()` helper creates `MagicMock` with `request_context.lifespan_context.pool`. Patch `SchemaService` (or `RelationshipService`, `QueryService`) at tools module level. Use `AsyncMock` for async service methods, `json.loads()` for result assertions.
- CLI pattern: Test command uses `create_pool` + `pool.test_connection()` + `pool.close()` in async `run_test` wrapped with `asyncio.run`
- CLI pattern: HTTP transport uses `mcp.run(transport="streamable-http")` (not "http") matching FastMCP API
- Test pattern: CLI tests use `typer.testing.CliRunner` with `patch("mamba_mcp_sap_hana.__main__.create_pool")` and `AsyncMock` pool

## Key Decisions
- Package name: `mamba-mcp-hana` (PyPI/CLI), import name: `mamba_mcp_sap_hana` (Python)
- Added `mamba-mcp-hana = { workspace = true }` to root `[tool.uv.sources]` for workspace resolution
- Created minimal README.md placeholder since hatchling build fails without it (full README is Task #22)
- Connection pool in `database/connection.py` (spec calls for separate pool.py and engine.py, but task description specifies connection.py -- combined approach is cleaner for hdbcli's simpler API vs SQLAlchemy)
- Used `asyncio.Queue` (not thread pool executor) for pool management; `asyncio.to_thread` wraps individual sync calls
- Health check uses `SELECT 1 FROM DUMMY` (HANA-specific); stale connections are detected and replaced transparently during acquire

## Known Issues
- Pre-existing test collection errors in workspace: pytest fails collecting tests for mamba-mcp-client, mamba-mcp-fs, and mamba-mcp-postgres due to import resolution issues (ModuleNotFoundError for conftest modules). These are not related to mamba-mcp-hana.
- Console script entry point (`mamba-mcp-hana`) now resolves to `mamba_mcp_sap_hana.__main__:app` (Task #6 complete)
- Pre-existing ruff F401 lint errors in `models/__init__.py` (3 unused imports: GetTableStoreTypeInput, GetTableStoreTypeOutput, StoreTypeInfo) -- not related to CLI task, will be resolved when tools layer imports these models
- Previous 4 test failures in test_query_service.py and test_relationship_service.py from concurrent tasks have been resolved; all 558 tests now pass

## File Map
- `/Users/sequenzia/dev/repos/mamba-mcp/pyproject.toml` - Workspace root config (Ruff, MyPy, pytest settings)
- `/Users/sequenzia/dev/repos/mamba-mcp/packages/mamba-mcp-hana/pyproject.toml` - Package metadata, deps, entry point
- `/Users/sequenzia/dev/repos/mamba-mcp/packages/mamba-mcp-hana/src/mamba_mcp_sap_hana/__init__.py` - Package root
- `/Users/sequenzia/dev/repos/mamba-mcp/packages/mamba-mcp-hana/src/mamba_mcp_sap_hana/config.py` - Pydantic settings configuration (DatabaseSettings, ServerSettings, Settings)
- `/Users/sequenzia/dev/repos/mamba-mcp/packages/mamba-mcp-hana/src/mamba_mcp_sap_hana/database/__init__.py` - Database layer
- `/Users/sequenzia/dev/repos/mamba-mcp/packages/mamba-mcp-hana/src/mamba_mcp_sap_hana/models/__init__.py` - Pydantic models
- `/Users/sequenzia/dev/repos/mamba-mcp/packages/mamba-mcp-hana/src/mamba_mcp_sap_hana/tools/__init__.py` - MCP tools
- `/Users/sequenzia/dev/repos/mamba-mcp/packages/mamba-mcp-hana/tests/__init__.py` - Test package
- `/Users/sequenzia/dev/repos/mamba-mcp/packages/mamba-mcp-hana/tests/conftest.py` - Test fixtures (env file path reset)
- `/Users/sequenzia/dev/repos/mamba-mcp/packages/mamba-mcp-hana/src/mamba_mcp_sap_hana/errors.py` - Error handling: ErrorCode, ToolError, create_tool_error, Levenshtein, suggest_similar
- `/Users/sequenzia/dev/repos/mamba-mcp/packages/mamba-mcp-hana/tests/test_config.py` - Config unit tests (34 tests)
- `/Users/sequenzia/dev/repos/mamba-mcp/packages/mamba-mcp-hana/tests/test_errors.py` - Error handling unit tests (55 tests)
- `/Users/sequenzia/dev/repos/mamba-mcp/packages/mamba-mcp-hana/src/mamba_mcp_sap_hana/database/connection.py` - Async connection pool (HanaConnectionPool, build_connection_params, create_pool)
- `/Users/sequenzia/dev/repos/mamba-mcp/packages/mamba-mcp-hana/tests/test_connection.py` - Connection pool unit tests (27 tests)
- `/Users/sequenzia/dev/repos/mamba-mcp/packages/mamba-mcp-postgres/src/mamba_mcp_postgres/config.py` - Reference config (patterns)
- `/Users/sequenzia/dev/repos/mamba-mcp/packages/mamba-mcp-postgres/src/mamba_mcp_postgres/errors.py` - Reference errors (patterns)
- `/Users/sequenzia/dev/repos/mamba-mcp/packages/mamba-mcp-fs/src/mamba_mcp_fs/config.py` - Reference config (patterns)
- `/Users/sequenzia/dev/repos/mamba-mcp/packages/mamba-mcp-hana/src/mamba_mcp_sap_hana/models/schema.py` - Layer 1 Pydantic I/O models (13 models for schema discovery tools)
- `/Users/sequenzia/dev/repos/mamba-mcp/packages/mamba-mcp-hana/tests/test_models_schema.py` - Layer 1 model unit tests (66 tests)
- `/Users/sequenzia/dev/repos/mamba-mcp/packages/mamba-mcp-hana/src/mamba_mcp_sap_hana/models/relationships.py` - Layer 2 Pydantic I/O models (7 models for relationship discovery tools)
- `/Users/sequenzia/dev/repos/mamba-mcp/packages/mamba-mcp-hana/tests/test_models_relationships.py` - Layer 2 model unit tests (35 tests)
- `/Users/sequenzia/dev/repos/mamba-mcp/packages/mamba-mcp-hana/src/mamba_mcp_sap_hana/models/query.py` - Layer 3 Pydantic I/O models (6 models for query execution tools)
- `/Users/sequenzia/dev/repos/mamba-mcp/packages/mamba-mcp-hana/tests/test_query_models.py` - Layer 3 model unit tests (55 tests)
- `/Users/sequenzia/dev/repos/mamba-mcp/packages/mamba-mcp-hana/src/mamba_mcp_sap_hana/models/hana.py` - Layer 4 HANA-specific I/O models (12 models for calc views and procedures)
- `/Users/sequenzia/dev/repos/mamba-mcp/packages/mamba-mcp-hana/tests/test_models_hana.py` - Layer 4 model unit tests (77 tests)
- `/Users/sequenzia/dev/repos/mamba-mcp/packages/mamba-mcp-hana/src/mamba_mcp_sap_hana/server.py` - FastMCP server with lifespan (AppContext, app_lifespan, mcp instance)
- `/Users/sequenzia/dev/repos/mamba-mcp/packages/mamba-mcp-hana/tests/test_server.py` - Server unit tests (11 tests)
- `/Users/sequenzia/dev/repos/mamba-mcp/packages/mamba-mcp-hana/src/mamba_mcp_sap_hana/database/query_service.py` - QueryService for Layer 3 query execution (execute_query, explain_query, SQL validation)
- `/Users/sequenzia/dev/repos/mamba-mcp/packages/mamba-mcp-hana/tests/test_query_service.py` - QueryService unit tests (70 tests)
- `/Users/sequenzia/dev/repos/mamba-mcp/packages/mamba-mcp-hana/src/mamba_mcp_sap_hana/database/schema_service.py` - SchemaService (Layer 1 schema discovery: list_schemas, list_tables, describe_table, get_sample_rows)
- `/Users/sequenzia/dev/repos/mamba-mcp/packages/mamba-mcp-hana/tests/test_schema_service.py` - SchemaService unit tests (38 tests)
- `/Users/sequenzia/dev/repos/mamba-mcp/packages/mamba-mcp-hana/src/mamba_mcp_sap_hana/database/relationship_service.py` - RelationshipService (Layer 2 FK discovery, BFS join path)
- `/Users/sequenzia/dev/repos/mamba-mcp/packages/mamba-mcp-hana/tests/test_relationship_service.py` - RelationshipService unit tests (45 tests)
- `/Users/sequenzia/dev/repos/mamba-mcp/packages/mamba-mcp-hana/src/mamba_mcp_sap_hana/__main__.py` - Typer CLI (test, serve commands)
- `/Users/sequenzia/dev/repos/mamba-mcp/packages/mamba-mcp-hana/tests/test_cli.py` - CLI unit tests (27 tests)
- `/Users/sequenzia/dev/repos/mamba-mcp/packages/mamba-mcp-hana/src/mamba_mcp_sap_hana/tools/relationship_tools.py` - Layer 2 MCP tools (get_foreign_keys, find_join_path)
- `/Users/sequenzia/dev/repos/mamba-mcp/packages/mamba-mcp-hana/tests/test_relationship_tools.py` - Layer 2 tool unit tests (18 tests)
- `/Users/sequenzia/dev/repos/mamba-mcp/packages/mamba-mcp-hana/src/mamba_mcp_sap_hana/tools/query_tools.py` - Layer 3 MCP tools (execute_query, explain_query)
- `/Users/sequenzia/dev/repos/mamba-mcp/packages/mamba-mcp-hana/tests/test_query_tools.py` - Layer 3 tool unit tests (29 tests)
- `/Users/sequenzia/dev/repos/mamba-mcp/packages/mamba-mcp-hana/src/mamba_mcp_sap_hana/tools/schema_tools.py` - Layer 1 MCP tools (4 tools: list_schemas, list_tables, describe_table, get_sample_rows)
- `/Users/sequenzia/dev/repos/mamba-mcp/packages/mamba-mcp-hana/tests/test_schema_tools.py` - Layer 1 MCP tool unit tests (32 tests)
- `/Users/sequenzia/dev/repos/mamba-mcp/packages/mamba-mcp-hana/src/mamba_mcp_sap_hana/database/hana.py` - HanaService (Layer 4: list_calculation_views, get_table_store_type, list_procedures)
- `/Users/sequenzia/dev/repos/mamba-mcp/packages/mamba-mcp-hana/tests/test_hana_service.py` - HanaService unit tests (37 tests)
- `/Users/sequenzia/dev/repos/mamba-mcp/packages/mamba-mcp-hana/src/mamba_mcp_sap_hana/tools/hana_tools.py` - Layer 4 MCP tools (3 tools: list_calculation_views, get_table_store_type, list_procedures)
- `/Users/sequenzia/dev/repos/mamba-mcp/packages/mamba-mcp-hana/tests/test_hana_tools.py` - Layer 4 MCP tool unit tests (28 tests)
- `/Users/sequenzia/dev/repos/mamba-mcp/internal/specs/mamba-mcp-hana-SPEC.md` - Full spec document

## Task History
### Task [1]: Scaffold mamba-mcp-hana package - PASS
- Files modified: Created packages/mamba-mcp-hana/ directory tree (pyproject.toml, README.md, 5 __init__.py files, 4 directories), edited root pyproject.toml
- Key learnings: Hatchling build requires README.md to exist when referenced in pyproject.toml. UV workspace glob `packages/*` auto-discovers new packages. Ruff/MyPy inherit from root config.
- Issues encountered: Initial build failure due to missing README.md; resolved by creating minimal placeholder.

### Task [2]: Implement Pydantic settings configuration system - PASS
- Files modified: Created `config.py`, `tests/conftest.py`, `tests/test_config.py`
- Key learnings: Pydantic-settings `_env_file=None` suppresses env file loading in tests. `model_validator(mode="after")` needed for cross-field validation (auth + TLS auto-detect). `object.__setattr__` needed to mutate fields in model validators. `SecretStr | None` pattern allows optional secrets with hdbuserstore auth fallback. `resolve_env_file()` function extracted for reuse by CLI (Task #6).
- Issues encountered: None. All 34 tests pass, ruff lint and format clean.

### Task [4]: Implement error handling system with fuzzy matching - PASS
- Files modified: Created `src/mamba_mcp_sap_hana/errors.py`, `tests/test_errors.py`
- Key learnings: HANA package uses a flat ToolError model (unlike postgres's nested ErrorDetail/ToolError pattern) with all 6 fields at top level. 12 error codes (postgres has 10) -- added VIEW_NOT_FOUND and PROCEDURE_NOT_FOUND for HANA-specific tools. Levenshtein threshold scales with name length: `max(2, min(len(name) // 2, 5))` to avoid false positives on short names. The `suggest_similar` function name differs from postgres's `find_similar_names`.
- Issues encountered: None. All 55 error tests pass plus 34 config tests (89 total), ruff lint and format clean.

### Task [8]: Create Layer 1 Pydantic I/O models - PASS
- Files modified: Created `src/mamba_mcp_sap_hana/models/schema.py`, `tests/test_models_schema.py`; updated `src/mamba_mcp_sap_hana/models/__init__.py`
- Key learnings: HANA Layer 1 models differ from postgres in several HANA-specific ways: `TableInfo.store_type` uses `Literal["COLUMN", "ROW"] | None` (None for views), `TableInfo.is_column_table` bool flag for COLUMN store indicator, `ConstraintInfo.constraint_type` uses `Literal["PRIMARY KEY", "UNIQUE", "CHECK"]` (no FOREIGN KEY -- FKs are in relationship layer). `DescribeTableOutput.is_view` flag for view-specific behavior (views skip indexes/constraints). `ColumnInfo` uses `length`/`scale` (HANA terms) instead of postgres's `character_maximum_length`/`numeric_precision`/`numeric_scale`. Models `__init__.py` accumulates imports from parallel tasks (Layer 2 relationships, Layer 3 queries added by other tasks).
- Issues encountered: Ruff import sorting (I001) required `--fix` on both files. Models `__init__.py` was concurrently modified by other tasks adding relationship and query models; schema imports integrated cleanly alongside them.

### Task [3]: Implement async connection pool and engine - PASS
- Files modified: Created `src/mamba_mcp_sap_hana/database/connection.py`, `tests/test_connection.py`; updated `src/mamba_mcp_sap_hana/database/__init__.py`
- Key learnings: hdbcli uses `address` (not `host`) and `databaseName` (not `database`) as connect param names. `asyncio.Queue` with `maxsize=pool_size` provides natural backpressure. Ruff UP041 rule requires using builtin `TimeoutError` instead of `asyncio.TimeoutError`. HANA's `SELECT 1 FROM DUMMY` is the standard health check (HANA has no implicit `SELECT 1` without FROM). Module-level private functions (`_create_connection`, `_check_connection_health`, `_close_connection`) make mocking straightforward for pool tests without needing hdbcli installed.
- Issues encountered: Initial ruff lint caught 3 issues (UP041 asyncio.TimeoutError alias, unused asyncio import in tests, line length). All fixed in single pass.

### Task [9]: Create Layer 2 Pydantic I/O models - PASS
- Files modified: Created `src/mamba_mcp_sap_hana/models/relationships.py`, `tests/test_models_relationships.py`; `models/__init__.py` was updated by concurrent tasks (Layer 1, Layer 3) which already included relationship imports
- Key learnings: HANA Layer 2 models differ from postgres: `ForeignKeyInfo` uses `source_schema`/`source_table`/`source_columns` and `target_schema`/`target_table`/`target_columns` naming (vs postgres's `from_`/`to_` naming), plus `delete_rule` (single field, vs postgres's `on_update`/`on_delete` pair -- HANA SYS.REFERENTIAL_CONSTRAINTS only reports DELETE_RULE). `JoinStep` has `direction: Literal["outgoing", "incoming"]` field (not in postgres model). `ForeignKeysOutput` uses `ForeignKeyInfo` (not `ForeignKeyRelation`). `FindJoinPathOutput` uses `path_count` (not `paths_found`) and `length` (not `depth`). No default schema values -- HANA requires explicit schema specification. 7 models total: GetForeignKeysInput, ForeignKeyInfo, ForeignKeysOutput, FindJoinPathInput, JoinStep, JoinPath, FindJoinPathOutput.
- Issues encountered: None. All 35 new tests pass, 217 total tests pass across hana package, ruff lint and format clean on new files.

### Task [10]: Create Layer 3 Pydantic I/O models - PASS
- Files modified: Created `src/mamba_mcp_sap_hana/models/query.py`, `tests/test_query_models.py`; updated `src/mamba_mcp_sap_hana/models/__init__.py`
- Key learnings: HANA Layer 3 models differ from postgres: `QueryResult` is a separate model embedded in `ExecuteQueryOutput` (postgres uses flat `ExecuteQueryOutput` with all fields at top level). Uses `truncated: bool` + `warning: str | None` instead of postgres's `has_more: bool`. Input models use `field_validator` for whitespace-only rejection (Pydantic's `min_length=1` catches empty string, but allows whitespace-only). HANA supports both positional `?` and named `:param` parameters, so `params` is typed `list[Any] | dict[str, Any] | None`. `ExplainPlanNode` models HANA's `EXPLAIN_PLAN_TABLE` structure with operator, table_name, schema_name, cost, cardinality, details. Format limited to "text" and "json" (no "yaml" like postgres -- HANA doesn't support YAML explain output). `MAX_SQL_LENGTH = 100_000` exported as module constant for reuse by query validation services.
- Issues encountered: Ruff E501 line length (103 chars) on one description string; fixed by splitting into parenthesized string concatenation. Ruff format required on 2 files (quote normalization). All 272 tests pass (55 new + 217 existing), ruff clean.

### Task [5]: Implement FastMCP server with lifespan management - PASS
- Files modified: Created `src/mamba_mcp_sap_hana/server.py`, `tests/test_server.py`
- Key learnings: FastMCP in mcp>=1.0.0 wraps lifespan internally (not accessible as `_lifespan`); use `mcp._mcp_server.lifespan` to verify in tests. HANA server pattern follows postgres closely but uses `HanaConnectionPool` + `create_pool()` instead of SQLAlchemy engine. `pool.test_connection()` method already exists on the pool (acquire + release) so no separate `test_connection` function needed. Shutdown error handling uses nested try/except in finally block to ensure errors are logged as warnings without crashing.
- Issues encountered: Initial test used `mcp._lifespan` which doesn't exist in the FastMCP API; fixed to `mcp._mcp_server.lifespan`. Ruff format required on test file (line length adjustments). All 283 tests pass (11 new + 272 existing), ruff lint and format clean.

### Task [18]: Create HANA-specific Pydantic I/O models - PASS
- Files modified: Created `src/mamba_mcp_sap_hana/models/hana.py`, `tests/test_models_hana.py`; updated `src/mamba_mcp_sap_hana/models/__init__.py`
- Key learnings: Layer 4 (HANA-specific) models follow the same patterns as Layers 1-3 but model objects unique to SAP HANA: calculation views (_SYS_BIC schema) and stored procedures with IN/OUT/INOUT parameter directions. 12 models total across 4 tool operations: `ListCalcViewsInput/Output`, `CalcViewInfo`, `CalcViewColumnInfo`, `DescribeCalcViewInput/Output`, `ListProceduresInput/Output`, `ProcedureInfo`, `ProcedureParameterInfo`, `DescribeProcedureInput/Output`. `ProcedureParameterInfo.direction` uses `Literal["IN", "OUT", "INOUT"]` for type-safe direction validation. `DescribeCalcViewOutput.parameters` uses `list[dict[str, Any]]` (flexible dict structure) since calculation view input parameters vary in structure. Both `CalcViewInfo.columns` and `ProcedureInfo.parameters` use `default_factory=list` with populated-on-request pattern (controlled by `include_columns`/`include_parameters` input flags). Input models include `name_pattern` for SQL LIKE filtering, consistent with Layer 1's `ListTablesInput`.
- Issues encountered: Ruff import sorting (I001) on test file required `--fix`. Ruff format needed on 2 files (hana.py and test file). All 398 tests pass (77 new + 321 existing), ruff lint and format clean.

### Task [13]: Implement QueryService for Layer 3 database operations - PASS
- Files modified: Created `src/mamba_mcp_sap_hana/database/query_service.py`, `tests/test_query_service.py`; updated `src/mamba_mcp_sap_hana/database/__init__.py`
- Key learnings: QueryService follows the module-level private function pattern from connection.py for testability. SQL validation uses a 3-step process: (1) strip comments and string literals via regex, (2) check for blocked keywords with word boundary regex, (3) verify query starts with SELECT/WITH. HANA's EXPLAIN PLAN mechanism is fundamentally different from PostgreSQL -- writes to EXPLAIN_PLAN_TABLE with a unique statement name, requires reading results back, then cleanup. Uses UUID-based statement names to avoid concurrent explain conflicts. Truncation detection via `fetchmany(max_rows + 1)` is cleaner than separate count query. Both `execute_query` and `explain_query` return union types (`Output | ToolError`) rather than raising exceptions. 20 blocked keywords cover HANA's DML, DDL, permissions, session, and administrative operations. The `asyncio.wait_for` wrapping `asyncio.to_thread` provides dual-layer timeout enforcement (async + HANA session variable). `conn.setclientinfo("SESSIONVARIABLE:STATEMENT_TIMEOUT", str(ms))` is the HANA-specific way to set statement timeout per connection.
- Issues encountered: Initial ruff lint caught an unnecessary f-string on `SET TRANSACTION` SQL. Test for cursor-closed-on-error had wrong `side_effect` count (3 instead of 2 -- `setclientinfo` is on `conn`, not `cursor`). Both fixed quickly. All 513 tests pass (70 new + 443 existing), ruff lint and format clean.

### Task [12]: Implement RelationshipService for Layer 2 database operations - PASS
- Files modified: Created `src/mamba_mcp_sap_hana/database/relationship_service.py`, `tests/test_relationship_service.py`; updated `src/mamba_mcp_sap_hana/database/__init__.py`
- Key learnings: RelationshipService queries `SYS.REFERENTIAL_CONSTRAINTS` for FK discovery. HANA's `SYS.REFERENTIAL_CONSTRAINTS` returns one row per column in a composite FK (POSITION ordering) with columns: CONSTRAINT_NAME, SCHEMA_NAME, TABLE_NAME, COLUMN_NAME, REFERENCED_SCHEMA_NAME, REFERENCED_TABLE_NAME, REFERENCED_COLUMN_NAME, DELETE_RULE. Rows must be grouped by constraint name for composite FKs. The ALL_FK_SQL query for BFS graph building omits DELETE_RULE (7 columns) while OUTGOING/INCOMING queries include it (8 columns) -- test data fixtures must match the appropriate column count. BFS graph uses bidirectional edges with explicit `direction` field ("outgoing"/"incoming") to track traversal direction for JoinStep output. SQL JOIN generation handles composite FKs by joining multiple ON conditions with AND. The `_verify_table_exists` method uses a single UNION ALL query (SYS.TABLES + SYS.VIEWS) for table existence check -- mock tests need only 1 fetchall for existence check (not 2 separate queries). Each service method acquires/releases its own connection, so `_verify_table_exists` uses a different acquire/release cycle than the main query in `get_foreign_keys` and `find_join_path`. Self-referencing FKs (same source and target table) are handled correctly: BFS returns empty for start==end, and the FK appears in both outgoing and incoming lists.
- Issues encountered: Initial 4 test failures due to: (1) graph test data used 8-column FK rows but `_build_fk_graph` expects 7-column (no DELETE_RULE) -- fixed by creating separate `_self_ref_graph_fk_rows()` fixture; (2) TABLE_EXISTS_SQL is a single UNION ALL query returning 1 fetchall call, not 2 separate calls -- fixed mock expectations; (3) connection error mocking needed fetchall-based side effects instead of execute-based ones. All 45 new tests pass, 513 total pass, ruff lint and format clean.

### Task [11]: Implement SchemaService for Layer 1 database operations - PASS
- Files modified: Created `src/mamba_mcp_sap_hana/database/schema_service.py`, `tests/test_schema_service.py`; updated `src/mamba_mcp_sap_hana/database/__init__.py`
- Key learnings: SchemaService uses module-level private functions (`_execute_query`, `_execute_query_with_description`, `_is_system_schema`) for testability -- similar pattern to connection.py's `_create_connection`. HANA SYS.* system views queried: SYS.SCHEMAS, SYS.TABLES, SYS.VIEWS, SYS.TABLE_COLUMNS, SYS.VIEW_COLUMNS, SYS.INDEXES + SYS.INDEX_COLUMNS, SYS.CONSTRAINTS. Index/constraint results require grouping by name since each column in a multi-column index/constraint returns a separate row. Ternary operator precedence is a bug-trap: `x == "TRUE" if isinstance(x, str) else bool(x)` parses as `x == ("TRUE" if ... else ...)`, not `(x == "TRUE") if ...` -- always use explicit parentheses. `fnmatch.fnmatchcase` used for name pattern matching after converting SQL LIKE patterns (% -> *, _ -> ?). Views skip index/constraint queries in describe_table (is_view flag). Connection always released in finally block (even on error). Mock test pattern: `_setup_cursor_responses()` helper that configures sequential description + fetchall results on a mock cursor, enabling multi-query test scenarios. System schema filtering: `_SYS_*` prefix + `SYS`/`SYSTEM` exact matches.
- Issues encountered: Ruff format reformatted ternary expressions removing parentheses, exposing operator precedence bugs. Fixed with explicit `(x == "TRUE") if isinstance(x, str) else bool(x)` syntax. Unused variable `original_execute` caught by ruff F841. 4 pre-existing test failures in test_query_service.py and test_relationship_service.py (from concurrent tasks); not related to schema_service. All 38 new tests pass, 310 total pass (excluding unrelated failures), ruff lint and format clean.

### Task [6]: Implement Typer CLI with test and serve commands - PASS
- Files modified: Created `src/mamba_mcp_sap_hana/__main__.py`, `tests/test_cli.py`
- Key learnings: CLI pattern follows mamba-mcp-postgres closely. Key difference from postgres: HANA uses `create_pool()` + `pool.test_connection()` + `pool.close()` instead of postgres's `create_engine()` + `test_connection(engine)` + `dispose_engine(engine)`. The `app.callback(invoke_without_command=True)` pattern handles both default serve and subcommand routing. `validate_env_file` is a Typer callback on the `--env-file` option that validates before any subcommand runs. `resolve_default_env_file` provides cascading fallback (explicit > ./mamba.env > ~/mamba.env). For HTTP transport, `mcp.run(transport="streamable-http")` is used (not "http") matching the FastMCP API. Test pattern uses `typer.testing.CliRunner` with `patch("mamba_mcp_sap_hana.__main__.create_pool")` to mock the pool without real hdbcli. Mock pool setup requires `AsyncMock()` for `test_connection` and `close` methods. Ruff format needed on test file for line length adjustments.
- Issues encountered: Ruff format reformatted one line in test_cli.py (long `side_effect=ConnectionError(...)` line). All 27 new tests pass, 558 total pass, ruff lint and format clean on new files (pre-existing F401 in models/__init__.py is unrelated).

### Task [15]: Implement Layer 2 relationship discovery MCP tools - PASS
- Files modified: Created `src/mamba_mcp_sap_hana/tools/relationship_tools.py`, `tests/test_relationship_tools.py`; updated `src/mamba_mcp_sap_hana/tools/__init__.py`
- Key learnings: MCP tools use `@mcp.tool()` decorator (no `ToolAnnotations` needed for HANA -- simpler than postgres pattern). Tools return `str` (JSON-serialized via `model_dump_json()`) not Pydantic models directly. Context extraction: `ctx.request_context.lifespan_context.pool` to get pool, then construct service. Service returns union type (`Output | ToolError`) so tools check `isinstance(result, ToolError)` before serializing. `find_join_path` handles `to_schema` defaulting to `from_schema` with `resolved_to_schema = to_schema if to_schema is not None else from_schema`. `max_depth` clamped with `max(1, min(6, max_depth))`. Test pattern: patch `RelationshipService` at tools module level, use `AsyncMock` for service methods, `_make_mock_ctx()` helper, `json.loads()` for result assertions. Tool registration verified via `server._tool_manager._tools.values()` inspection. 18 new tests covering both tools (outgoing/incoming FKs, error handling, no context, service params, pool instantiation, default schema, depth clamping, multiple paths, empty paths, tool registration).
- Issues encountered: Ruff import sorting (I001) required `--fix` on test file. Unused `ToolError` import caught by F401. Ruff format needed on test file. All fixed in single pass. All 587 tests pass (18 new + 569 existing), ruff lint and format clean on new files.

### Task [16]: Implement Layer 3 query execution MCP tools - PASS
- Files modified: Created `src/mamba_mcp_sap_hana/tools/query_tools.py`, `tests/test_query_tools.py`; updated `src/mamba_mcp_sap_hana/tools/__init__.py` (added `query_tools` import)
- Key learnings: Layer 3 query tools follow the same pattern as relationship_tools (Task #15): `@mcp.tool()` decorator, extract pool from context, construct QueryService with pool + statement_timeout from settings, call async method, check `isinstance(result, ToolError)`, return `model_dump_json()`. Key difference from postgres: HANA's QueryService returns union type (`Output | ToolError`) not raising exceptions, so error handling is an isinstance check rather than try/except for validation errors. `execute_query` supports both `dict` (named `:param`) and `list` (positional `?`) params -- the tool signature uses `dict[str, Any] | list[Any] | None` matching the service signature. `limit` clamped at tool level with `max(1, min(10000, limit))` before passing to service as `max_rows`. `timeout_ms=None` passed through to service which falls back to its configured `statement_timeout`. `explain_query` format validated at tool level (fallback to "text" for invalid values). Tools `__init__.py` must import each tool module to trigger `@mcp.tool()` registration at import time.
- Issues encountered: Ruff import sorting (I001) and unused import (F401 for `ToolError`) on test file required `--fix`. Ruff format needed on test file. Pre-existing I001 lint error in `test_schema_tools.py` (from another task, not related). All 29 new tests pass, 619 total pass, ruff lint and format clean on new files.

### Task [14]: Implement Layer 1 schema discovery MCP tools - PASS
- Files modified: Created `src/mamba_mcp_sap_hana/tools/schema_tools.py`, `tests/test_schema_tools.py`; updated `src/mamba_mcp_sap_hana/tools/__init__.py`
- Key learnings: Layer 1 schema tools follow the same pattern established by Task #15 (relationship_tools): `@mcp.tool()` decorator with `ToolAnnotations`, extract pool from `ctx.request_context.lifespan_context`, construct `SchemaService(pool)`, call async method, check `isinstance(result, ToolError)`, return `model_dump_json()`. HANA SchemaService returns union types (`Output | ToolError`) so tools use isinstance checks. `get_sample_rows` validates `limit` range (1-100) at the tool layer before calling the service, returning `PARAMETER_ERROR` for out-of-range values. `get_sample_rows` uses `idempotentHint=False` (randomize option makes it non-idempotent). All other tools use `idempotentHint=True`. Tool registration: importing the tools module triggers `@mcp.tool()` decorators via `tools/__init__.py`. Test pattern: `_make_mock_ctx()` helper, patch SchemaService at tools module level, `AsyncMock` for async service methods, `json.loads()` for result assertions. Test helper gotcha: `rows or default` treats empty list as falsy -- use `rows if rows is not None else default` instead.
- Issues encountered: Ruff import sorting (I001) and unused `ToolError` import (F401) on test file required `--fix`. Ruff format needed on both new files. Test helper `_make_sample_rows_output` used `or` instead of `is not None` check, causing empty-list test to use default data. All 32 new tests pass, 619 total pass, ruff lint and format clean on new files.

### Task [19]: Implement HanaService for HANA-specific database operations - PASS
- Files modified: Created `src/mamba_mcp_sap_hana/database/hana.py`, `tests/test_hana_service.py`; updated `src/mamba_mcp_sap_hana/database/__init__.py`, `src/mamba_mcp_sap_hana/models/hana.py`, `src/mamba_mcp_sap_hana/models/__init__.py`
- Key learnings: HanaService follows the class-based service pattern (SchemaService, RelationshipService) with `__init__(self, pool)` and per-method connection acquire/release in finally blocks. Three service methods (`list_calculation_views`, `get_table_store_type`, `list_procedures`) cover HANA-specific objects not in postgres. Internal `_verify_schema_exists` method takes an active connection (shared with caller's conn) for efficiency -- different from RelationshipService's `_verify_table_exists` which acquires its own connection. `get_table_store_type` checks for views first and returns PARAMETER_ERROR (not VIEW_NOT_FOUND) since it's a parameter misuse, not a missing object. Added 3 new Pydantic models (`StoreTypeInfo`, `GetTableStoreTypeInput`, `GetTableStoreTypeOutput`) to hana.py -- now 15 models total. Implications text uses module-level constant strings. Partition count queries SYS.TABLE_PARTITIONS only when HAS_PARTITIONS is TRUE. IS_PRELOAD used as compression indicator from SYS.TABLES. Test assertion on implications text: check for "analytical" not "analytics" (the text says "analytical queries" and "analytical workloads").
- Issues encountered: Missing `asyncio` import in test file caught by ruff F821. Test assertion checked for "analytics" but implications text uses "analytical" -- fixed assertion. Ruff format needed on 2 files (hana.py and test_hana_service.py). All 37 new tests pass, 656 total pass, ruff lint and format clean.

### Task [20]: Implement HANA-specific MCP tools - PASS
- Files modified: Created `src/mamba_mcp_sap_hana/tools/hana_tools.py`, `tests/test_hana_tools.py`; updated `src/mamba_mcp_sap_hana/tools/__init__.py`
- Key learnings: HANA tools (Layer 4) follow the same pattern as schema_tools, relationship_tools, and query_tools: `@mcp.tool()` decorator, extract pool from `ctx.request_context.lifespan_context`, construct `HanaService(pool)`, call async method, check `isinstance(result, ToolError)`, return `model_dump_json()`. Unlike relationship_tools which have `ToolAnnotations` or schema_tools, the HANA tools use the simpler `@mcp.tool()` decorator without annotations (matching the relationship_tools pattern). No tool-level parameter validation needed for these 3 tools (unlike `get_sample_rows` which validates limit range) -- parameter validation is handled by the service layer. The `list_calculation_views` docstring specifically notes analytic privilege requirements per spec. The `get_table_store_type` docstring explains column vs row store implications per spec. Tool registration via `tools/__init__.py` import order: `hana_tools`, `query_tools`, `relationship_tools`, `schema_tools` (alphabetical). Total tool count confirmed at 11 (4 schema + 2 relationship + 2 query + 3 HANA).
- Issues encountered: Ruff format needed on test file (line length adjustments in `with patch()` blocks). All 28 new tests pass, 702 total pass, ruff lint and format clean on new files.

### Task [7]: Add Phase 1 unit tests - PASS
- Files modified: Enhanced `tests/conftest.py` (added 4 reusable fixtures), enhanced `tests/test_connection.py` (added 4 new test classes with 19 new tests), enhanced `tests/test_config.py` (added 2 new test classes with 9 new tests), enhanced `tests/test_cli.py` (added 2 new test classes with 4 new tests)
- Key learnings: Phase 1 coverage improved from 93% to 97% overall. connection.py improved from 82% to 94% by directly testing module-level private functions (`_create_connection`, `_check_connection_health`, `_close_connection`) and adding pool recovery tests (multiple stale connections, post-wait stale replacement). Remaining uncovered lines are defensive `QueueEmpty`/`QueueFull` catches that are race-condition guards difficult to trigger in unit tests. The `conftest.py` fixtures (`mock_cursor`, `mock_hdbcli_connection`, `mock_pool`, `hana_config`) provide reusable mocks for all future tool/service tests. Userkey config edge cases (hdbuserstore with custom host/port/pool settings, password-only without user) now covered.
- Issues encountered: Ruff format needed on 2 files (test_config.py, test_connection.py). No test failures during development. All 710 tests pass (54 new + 656 existing), ruff lint and format clean.

### Task [21]: Add Phase 3 unit tests for HANA-specific tools - PASS
- Files modified: Enhanced `tests/test_hana_tools.py` (added 29 new tests: 6 new test classes with additional tests across tool-level and service-integration categories)
- Key learnings: Phase 3 coverage achieved 100% on both `tools/hana_tools.py` and `database/hana.py`. Added 6 new calc view tool tests (analytic privilege docstring check, multiple view types, column exclusion, default param, multiple columns metadata), 6 new store type tool tests (compression metadata, row store no compression, column without partitions, docstring implications, view error suggestion), 6 new procedure tool tests (SQLScript/R/L types, mixed IN/OUT/INOUT directions, default param, multiple procs with params, read-only status), and 4+4+5=13 HanaService integration tests via mocked cursor data covering calc views (all types with columns, empty schema, privilege note constant, inactive detection), store type (partitions+compression, row detection, view error, table not found), and procedures (all types, empty, no params, mixed directions, exclude params). Pre-existing ruff format issues in 3 other test files (test_query_tools.py, test_relationship_tools.py, test_schema_tools.py) are unrelated to this task. The `_setup_cursor_responses` helper pattern from test_hana_service.py was reused in the integration test section of test_hana_tools.py.
- Issues encountered: Ruff format needed on test file (one pass). No test failures during development. All 766 tests pass (29 new + 737 existing), ruff lint clean.

### Task [17]: Add Phase 2 unit tests for core tools - PASS
- Files modified: Enhanced `tests/test_schema_tools.py` (added 4 new test classes with 17 new tests), enhanced `tests/test_relationship_tools.py` (added 3 new test classes with 10 new tests), enhanced `tests/test_query_tools.py` (added 5 new test classes with 28 new tests)
- Key learnings: Phase 2 tool test coverage expanded from 79 to 134 tests across 3 files. Schema tools extended with system schema handling, view inclusion, name pattern filtering, column selection, WHERE clause, randomize, fuzzy match suggestions. Relationship tools extended with composite FK output, multiple outgoing FKs, self-referencing FKs, cross-schema paths, multi-hop step details, SQL examples. Query tools extended with comprehensive write keyword blocking (all 20 BLOCKED_KEYWORDS tested), auto-LIMIT clamping (0, negative, >10000, boundaries), EXPLAIN PLAN lifecycle (end-to-end, empty plan, params, write blocked, missing table), execution time/hash output, parameterized queries, connection errors, timeouts. IMPORTANT: `_make_execute_output` helper uses `rows or [default]` which treats empty list as falsy -- must construct `ExecuteQueryOutput` directly when testing empty result sets. Relationship tools (get_foreign_keys, find_join_path) do NOT wrap service exceptions in error JSON (unlike schema tools) -- they let exceptions propagate from the service layer.
- Issues encountered: Ruff format needed on 3 test files (one pass). One test failure initially: `test_empty_result_set` in TestExecuteQueryExtended failed because `_make_execute_output(rows=[])` defaulted to non-empty rows via `rows or [default]` pattern. Fixed by constructing `ExecuteQueryOutput` directly. All 794 tests pass (84 new + 710 existing), ruff lint and format clean.

### Task [22]: Create README.md with setup, usage, and tool reference - PASS
- Files modified: Overwrote `packages/mamba-mcp-hana/README.md` (placeholder replaced with ~610 lines of comprehensive documentation)
- Key learnings: README follows the mamba-mcp-postgres README format but is significantly more detailed due to HANA-specific sections (Cloud vs On-Premise, hdbuserstore auth, store type implications, analytic privilege notes). All 17 env vars from spec Section 13.4 documented in configuration table. All 11 tools documented with parameter tables and JSON example outputs. Security section includes the recommended HANA user setup SQL from spec Section 6.2. Architecture diagram matches spec Section 7.1.
- Issues encountered: None. No code changes needed, only documentation. All 766 existing tests still pass.
