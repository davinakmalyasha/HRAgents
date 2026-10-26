# MCP connector catalog

The Connections panel can show a small catalog of **templates** for the
connectors most installations want: an ATS, an HRIS, Slack notifications and a
calendar busy lookup. A template is not a connection and is never enabled by
default; choosing one fills the form with the shape of the connection, and the
operator still supplies the gateway endpoint, saves it, and runs Test.

There are no vendor API keys or invented vendor MCP URLs in the catalog. The
entries describe capability, data flow and enablement; the endpoint belongs to
the operator's own MCP gateway.

| Template | Reads | Writes | Minimum scopes |
|---|---|---|---|
| ATS (Greenhouse / Lever style) | candidate, application and job metadata | one application note | read candidates, read applications, write notes |
| HRIS (Talenta / Gadjah style) | employee identity, org unit, leave balances | nothing | read employees, read leave balances |
| Slack notifications | nothing | one message to one channel | post to that channel |
| Calendar busy lookup | free/busy windows | nothing | read free/busy |

## The rules every template keeps

- **No decisions.** A connector cannot reject, approve, move a stage, override
  a score or schedule payroll. Those remain dashboard actions with a named
  human and, where relevant, the approval engine.
- **The smallest useful data flow.** The ATS template does not forward résumé
  files; the HRIS template does not read salary or bank fields; the calendar
  template asks for busy blocks, not event titles; the Slack template sends a
  short human-action message, not candidate documents or contact details.
- **Explicit tools only.** The template lists each remote tool and its impact.
  A tool the server adds later stays invisible until an operator names it.
- **No destructive tools.** A destructive remote tool has no preview contract,
  so it is refused by the registry, template or not.
- **The token lives in the environment.** The form stores the *name* of the
  variable, never the token, and the URL must not embed credentials.

## Enabling one

1. Stand up an MCP gateway in front of the system, with the minimum scopes in
   the table above.
2. Put the gateway token in the variable named by the template
   (`ATS_MCP_TOKEN`, `HRIS_MCP_TOKEN`, `SLACK_MCP_TOKEN`,
   `CALENDAR_MCP_TOKEN`).
3. Open **Operations → Connections → Browse catalog**, choose the template and
   fill in your gateway's endpoint; adjust the tool names to the ones your
   gateway actually offers.
4. Save, then press **Test**. The probe connects, lists the tools and
   disconnects without registering or writing anything.
5. Let one agent make a read call on a real (or seeded) record and inspect the
   audit entry.

The catalog lives in `src/hr_agents/services/mcp_catalog.py`. A guard test
keeps every entry honest: unique ids, non-empty scopes, data-flow and enable
steps, no destructive tools, and no decision words in tool names. Adding an
entry is a code change so the review can check those properties.
