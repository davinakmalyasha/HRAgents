# MCP server (`hragents-mcp`)

A packaged, **read-only** MCP server for external clients — Claude Desktop,
IDE agents, or anything that speaks MCP over stdio. It asks an HRAgents install
what is waiting, what happened to one application, how it was evaluated, and
what leave somebody has left. It never writes, approves, rejects or schedules.

## What it exposes

| Tool | What it answers |
|---|---|
| `queue` | Priority-ranked applications for one job (`job_id`) |
| `application_status` | Status and timeline for one application |
| `evaluation_summary` | Deterministic evaluation: score vector, evidence, rubric family/digest, flags, recommendation |
| `pending_approvals` | Approvals waiting for a human, optionally by approver role |
| `leave_balances` | Leave balances for one employee (the API applies its own rules) |

Each tool is a GET against the API. That is the authorization model: the server
holds a role-bound API key, so the API's permissions, tenant scoping and audit
chain apply exactly as they would to any other client. A key that may not read a
record receives the API's refusal, not a filtered answer. Give the MCP server a
key whose role matches what the person using the client should see.

## Install and run

The console script is installed with the package:

```bash
uv pip install hr-agents      # or run from a checkout with `uv run hragents-mcp`
```

```bash
export HRAGENTS_API_URL=http://localhost:8000   # default
export HRAGENTS_API_KEY=...                     # required; role-bound
hragents-mcp
```

The transport is stdio, which is what desktop MCP clients launch. The API key is
read from the environment — never a command-line argument, where other users on
the host could see it in a process list.

## Claude Desktop

Add the server to `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "hragents": {
      "command": "hragents-mcp",
      "env": {
        "HRAGENTS_API_URL": "http://localhost:8000",
        "HRAGENTS_API_KEY": "paste-the-role-bound-key-here"
      }
    }
  }
}
```

Restart the client. The five tools appear in its tool list. If the API is not
running, tool calls answer a readable error instead of failing the server.

## What is deliberately missing

- **No write tools.** Creating an application, requesting a document or opening
  a leave request changes state and belongs behind the product's approval
  engine and a named human; those tools are not exposed here.
- **No raw documents.** Tools return structured metadata; résumé text and file
  bytes are not sent to an MCP client.
- **No decisions.** The server cannot approve, reject, override or schedule
  anything, even with an admin key. Those routes are in the dashboard.

## Contract tests

`tests/test_mcp_server.py` connects an in-memory MCP client to the real server,
asserts the tool set, calls a tool through a mocked API, checks that every call
is a GET carrying the key, and checks that neither the key nor a refusal leaks
into the response.
