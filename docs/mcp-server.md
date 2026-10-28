# MCP server (`hragents-mcp`)

A packaged MCP server for external clients — Claude Desktop, IDE agents, or
anything that speaks MCP over stdio. By default it is read-only: it asks an
HRAgents install what is waiting, what happened to one application, how it was
evaluated, and what leave somebody has left.

Three write tools can be enabled (`HRAGENTS_MCP_WRITES=1`) for intake and
requests. Even then it never approves, rejects, moves stages, overrides
decisions, schedules payroll or erases records — those remain in the dashboard
behind a named human.

## What it exposes

| Tool | What it answers |
|---|---|
| `queue` | Priority-ranked applications for one job (`job_id`) |
| `application_status` | Status and timeline for one application |
| `evaluation_summary` | Deterministic evaluation: score vector, evidence, rubric family/digest, flags, recommendation |
| `pending_approvals` | Approvals waiting for a human, optionally by approver role |
| `leave_balances` | Leave balances for one employee (the API applies its own rules) |

Write tools, off unless `HRAGENTS_MCP_WRITES=1`:

| Tool | What it does | Permission |
|---|---|---|
| `create_application` | Ingests one application from an external ATS; the caller supplies the consent it captured — the server never infers consent | `recruiting:write` |
| `start_onboarding_plan` | Opens a plan from a template | `people:write` |
| `open_leave_request` | Files a leave request, which enters the human approval queue | `self_service` (or `people:write`) |
| `request_document` | Asks an employee for a document; creates an approval, never a demand — nothing is asked until a human approves | `people:write` |

The write tools are still just API calls: the key's role is the authorization,
and audit records the actor behind the key. `open_leave_request` cannot decide
the request it files, and `request_document` cannot demand anything;
approving is a dashboard action.

Each tool carries MCP annotations: the five reads set `readOnlyHint`, so a
client can treat them as safe to call without confirmation, and the write tools
set `readOnlyHint=false` with `destructiveHint=false`. The instructions the
server sends to the client switch from "read-only access" to "read and write
access" when writes are enabled, so an agent is told what it actually holds.

## Exposing fewer tools

`HRAGENTS_MCP_TOOLS` narrows the surface to a comma-separated allowlist, so one
client can see the queue without also seeing leave balances:

```bash
export HRAGENTS_MCP_TOOLS=queue,application_status
hragents-mcp
```

Unset or empty means every tool the mode allows. Startup fails on an unknown
name, and a write tool listed without `HRAGENTS_MCP_WRITES=1` is a configuration
error rather than a silently missing tool. The allowlist does not add
authorization — the API key's role still decides every call.

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
export HRAGENTS_MCP_WRITES=1                    # optional; enables the write tools
export HRAGENTS_MCP_TOOLS=queue,leave_balances  # optional; expose only these tools
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
        "HRAGENTS_API_KEY": "paste-the-role-bound-key-here",
        "HRAGENTS_MCP_WRITES": "1"
      }
    }
  }
}
```

Restart the client. The tools appear in its tool list. If the API is not
running, tool calls answer a readable error instead of failing the server.

## What is deliberately missing

- **No decisions.** The server cannot approve, reject, override, move a stage or
  schedule anything, even with an admin key. Those routes are in the dashboard.
- **No payroll, erasure or rejection execution.** Payroll stays prepare/verify/
  export; erasure stays a human-run compliance action; rejections require the
  merit floor and a named sign-off.
- **No raw documents.** Tools return structured metadata; résumé text and file
  bytes are not sent to an MCP client.
- **No document requests yet.** Asking an employee for a missing document has no
  API route, so there is no tool for it; adding one needs an approval-backed
  request, not a bypass.

## Contract tests

`tests/test_mcp_server.py` connects an in-memory MCP client to the real server,
asserts the read-only default and the opt-in tool set, runs a write through a
mocked API, checks that an intake body carries the caller's consent unchanged,
checks that no decision tool exists, and checks that neither the key nor a
refusal leaks into the response.
