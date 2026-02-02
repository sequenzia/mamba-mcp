# mamba-mcp-core

Shared utilities for Mamba MCP server packages.

## Modules

- **cli** — `validate_env_file`, `resolve_default_env_file`, `setup_logging`
- **config** — Module-level env file path state management
- **errors** — `ToolError` model and `create_tool_error` factory
- **fuzzy** — Levenshtein distance and `find_similar_names` with scaled threshold
- **transport** — `normalize_transport` for consistent transport naming
