# mamba-mcp-server-gitlab

MCP Server for GitLab API integration - merge requests, pipelines, and issues.

## Installation

```bash
uv add mamba-mcp-server-gitlab
```

## Configuration

Set the following environment variables:

- `GITLAB_URL` - GitLab instance URL (default: https://gitlab.com)
- `GITLAB_TOKEN` - Personal access token or project/group token

## Usage

```bash
# Run as STDIO server
mamba-mcp-server-gitlab
```

## Features

- Merge request management (list, get, diff, comment, approve, merge)
- Pipeline management (list, get, trigger, retry, cancel, jobs, logs)
- Issue management (list, get, create, update)

See full documentation for tool reference.
