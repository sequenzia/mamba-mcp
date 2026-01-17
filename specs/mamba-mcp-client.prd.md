# Product Requirements Document: mamba-mcp-client

## Overview

**Project Name:** mamba-mcp-client
**Version:** 1.0.0
**Created:** 2026-01-16
**Status:** Draft

### Summary

A Python-based MCP Client specialized for testing and debugging MCP Servers, featuring both a programmatic Python API and a terminal TUI interface.

---

## Problem Statement

Testing MCP servers is hard and debugging is painful. No good tools currently exist to test MCP server implementations, and it's difficult to inspect what's happening during MCP communication.

### Affected Users

- MCP server developers
- QA engineers
- DevOps/Platform teams

---

## Goals

### Primary Goals

1. Provide a reliable way to test MCP server capabilities
2. Enable detailed inspection of MCP protocol communication
3. Support both interactive debugging and programmatic testing

### Non-Goals

- Production MCP client for end-user applications
- AI/LLM integration (this is for testing servers, not using them)

### Success Metrics

- Can connect to and test any MCP server via stdio, SSE, or Streamable HTTP
- All 8 MCP capabilities (Resources, Prompts, Tools, Discovery, Sampling, Roots, Elicitation, Instructions) are testable
- Request/response logging captures full protocol details

---

## User Stories

### MCP Server Developer

> As an MCP server developer, I want to quickly test my server's tool implementations so I can verify they work correctly.

### QA Engineer

> As a QA engineer, I want to validate server responses against expected schemas so I can catch regressions.

### DevOps Engineer

> As a DevOps engineer, I want to verify server connectivity and capabilities so I can troubleshoot deployment issues.

---

## Functional Requirements

### P0 - Must Have

| Feature | Description |
|---------|-------------|
| **Capability Inspection** | List and inspect server capabilities (tools, resources, prompts) |
| **Interactive Tool Calling** | Execute tool calls and see responses with full request/response details |
| **Connection Management** | Connect to servers via stdio, SSE, and Streamable HTTP transports |
| **Request/Response Logging** | Detailed logging of all MCP protocol messages |
| **.env File Support** | Load environment variables from .env file via CLI argument |
| **Python API** | Use directly in Python code for programmatic testing |
| **TUI Interface** | Terminal UI using Textual for interactive debugging |
| **Full MCP Capability Support** | Resources, Prompts, Tools, Discovery, Sampling, Roots, Elicitation, Instructions |

### P1 - Should Have

| Feature | Description |
|---------|-------------|
| **Response Validation** | Validate responses against expected schemas/values |

### P2 - Nice to Have

None specified.

---

## MCP Capabilities

The client must support testing all 8 MCP capabilities:

1. **Resources** - List, read, and subscribe to server resources
2. **Prompts** - List and get prompt templates from server
3. **Tools** - List and call tools exposed by the server
4. **Discovery** - Discover server capabilities and metadata
5. **Sampling** - Test server-initiated sampling requests
6. **Roots** - Manage root directories exposed to the server
7. **Elicitation** - Handle server requests for additional user input
8. **Instructions** - Retrieve server instructions/system prompts

---

## Non-Functional Requirements

### Priority NFRs

| Requirement | Target |
|-------------|--------|
| **Comprehensive Logging** | Full protocol message capture with timestamps |
| **Clear Error Messages** | User-friendly errors that help identify issues |
| **Fast Startup Time** | < 1 second to launch |

---

## Technical Constraints

| Constraint | Details |
|------------|---------|
| **Language** | Python |
| **Package Manager** | UV |
| **Configuration** | pydantic and pydantic_settings |
| **MCP Framework** | FastMCP Client |
| **TUI Framework** | Textual |

---

## Architecture

### Interfaces

The client provides two interfaces:

1. **Python API** - Programmatic access for scripted testing and automation
2. **Terminal TUI** - Interactive interface for manual debugging and exploration

### Transport Support

- **stdio** - Launch servers as subprocess, communicate via stdin/stdout
- **SSE** - Server-Sent Events for HTTP-based servers
- **Streamable HTTP** - Newer HTTP streaming transport

---

## Edge Cases

- Server returns malformed responses
- Connection timeout during long operations
- Server crashes mid-request

---

## Acceptance Criteria

- [ ] Can connect to MCP server via all 3 transport types (stdio, SSE, Streamable HTTP)
- [ ] Can list and call tools, resources, and prompts
- [ ] Logs show complete request/response cycle
- [ ] TUI provides interactive capability browsing and testing
- [ ] Python API allows scripted testing
- [ ] .env file can be passed via CLI argument

---

## Risks & Open Questions

| Risk | Mitigation |
|------|------------|
| MCP spec changes may break compatibility | Monitor MCP spec updates, maintain abstraction layer over protocol details |

---

## Appendix

### Related Documents

- `specs/overview.md` - Initial project overview

### Technology References

- [FastMCP](https://github.com/jlowin/fastmcp) - MCP framework
- [Textual](https://textual.textualize.io/) - TUI framework
- [pydantic](https://docs.pydantic.dev/) - Data validation
- [UV](https://github.com/astral-sh/uv) - Python package manager
