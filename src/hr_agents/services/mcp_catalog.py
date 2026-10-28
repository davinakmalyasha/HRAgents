"""A small, honest catalog of MCP connector templates.

Nothing here contacts a vendor. The entries describe the shape of a connection
an operator can run through their own MCP gateway: which tools to expose, with
which impact, which agents may call them, the minimum data flow, and the steps
to enable it. A template is never active until the operator adds a connection
with a real endpoint; the catalog is documentation you can click.

Deliberately absent: vendor API keys, invented MCP endpoint URLs, and any tool
that changes a hiring decision. A connector may read candidates or post a
notification; it may not reject, approve, move a stage, run payroll or erase.
"""

from __future__ import annotations

from hr_agents.models.mcp import McpServerCatalogEntry, McpServerConfig

CATALOG: tuple[McpServerCatalogEntry, ...] = (
    McpServerCatalogEntry(
        id="ats",
        title="ATS connector (Greenhouse / Lever style)",
        summary=(
            "Read candidates and applications from the ATS you already use, and "
            "write a note back. Stage moves and rejections stay in HRAgents, "
            "where a named human makes them."
        ),
        data_flow=(
            "In: candidate profile, application status, job metadata. Out: one note "
            "per screening. No résumé files are forwarded; HRAgents evaluates the "
            "documents it already holds."
        ),
        scopes=["read candidates", "read applications", "write application notes"],
        auth_env="ATS_MCP_TOKEN",
        auth_hint="A gateway-scoped token that can read candidates and write notes, nothing else.",
        tools={"get_candidate": "read", "list_applications": "read", "add_note": "write"},
        allowed_agents=["screening_coordinator"],
        enable_steps=[
            "Stand up an MCP gateway in front of the ATS (the vendor's API stays unchanged).",
            "Issue a token limited to the scopes above and put it in the named "
            "environment variable.",
            "Add a connection with your gateway's MCP endpoint and the tools listed below.",
            "Run Test, then let one agent use a read tool on a real record.",
        ],
    ),
    McpServerCatalogEntry(
        id="hris",
        title="HRIS connector (Talenta / Gadjah style)",
        summary=(
            "Read employee master data and leave balances so Ask HR can answer "
            "policy questions with the person's real entitlement."
        ),
        data_flow=(
            "In: employee identity, org unit, leave balances. No salary fields, no "
            "bank details, and no writes: payroll and termination stay in HRAgents."
        ),
        scopes=["read employees", "read leave balances"],
        auth_env="HRIS_MCP_TOKEN",
        auth_hint="A read-only token for employee and leave endpoints.",
        tools={"get_employee": "read", "get_leave_balances": "read"},
        allowed_agents=["policy_assistant"],
        enable_steps=[
            "Expose the HRIS through an MCP gateway with the read scopes above.",
            "Put the token in the named environment variable; never embed it in the URL.",
            "Add the connection, list both tools as read, and allow policy_assistant.",
            "Ask one question that needs a balance and confirm the answer names the source.",
        ],
    ),
    McpServerCatalogEntry(
        id="slack",
        title="Slack notifications",
        summary="Post a message when something needs a human — never to decide anything.",
        data_flow=(
            "Out: a short message naming the queue and the reason. No candidate "
            "documents, scores or personal contact details are included."
        ),
        scopes=["post messages to one channel"],
        auth_env="SLACK_MCP_TOKEN",
        auth_hint="A bot token limited to one notification channel.",
        tools={"post_message": "write"},
        allowed_agents=["screening_coordinator"],
        enable_steps=[
            "Create a Slack app restricted to the notification channel.",
            "Put its token in the named environment variable.",
            "Add the connection with only post_message exposed.",
            "Send one test notification from a non-production record.",
        ],
    ),
    McpServerCatalogEntry(
        id="calendar",
        title="Calendar busy lookup",
        summary=(
            "Read free/busy windows for interview scheduling. Titles, attendees and "
            "event contents are not requested."
        ),
        data_flow=(
            "In: start/end busy blocks for the requested window. No event titles, "
            "descriptions or attendee lists."
        ),
        scopes=["read free/busy"],
        auth_env="CALENDAR_MCP_TOKEN",
        auth_hint="A token with free/busy scope only.",
        tools={"get_busy": "read"},
        allowed_agents=["screening_coordinator"],
        enable_steps=[
            "Expose your calendar provider through a gateway that returns free/busy only.",
            "Put the token in the named environment variable.",
            "Add the connection with get_busy as a read tool.",
            "Propose one slot and confirm no event details appear in the answer.",
        ],
    ),
)


def catalog() -> list[McpServerCatalogEntry]:
    return list(CATALOG)


def get_entry(entry_id: str) -> McpServerCatalogEntry:
    """One template by id, or ``KeyError`` for an unknown name."""
    for entry in CATALOG:
        if entry.id == entry_id:
            return entry
    raise KeyError(f"unknown connector template: {entry_id!r}")


def config_for(
    entry_id: str,
    url: str,
    *,
    name: str | None = None,
    allowed_agents: list[str] | None = None,
    tools: dict[str, str] | None = None,
) -> McpServerConfig:
    """Build an operator connection from a catalog template.

    The template supplies the token variable, the tool names with their
    impacts, and the default agent allowlist; the operator supplies the
    gateway endpoint (and optionally narrows the tools or agents). Impacts
    always come from the template: a caller may drop a tool but may not
    reclassify one, and a destructive impact is refused outright — a remote
    destructive tool has no dry-run preview contract, so the registry would
    refuse it anyway.
    """
    entry = get_entry(entry_id)
    wanted = dict(entry.tools) if tools is None else dict(tools)
    unknown = sorted(set(wanted) - set(entry.tools))
    if unknown:
        raise ValueError(f"template {entry_id!r} does not offer tool(s): {', '.join(unknown)}")
    for tool, impact in wanted.items():
        if impact != entry.tools[tool]:
            raise ValueError(
                f"tool {tool!r} is {entry.tools[tool]!r} in template {entry_id!r}, "
                f"not {impact!r}; impacts come from the template"
            )
        if impact == "destructive":
            raise ValueError(
                f"tool {tool!r} is destructive and has no preview contract; it cannot be registered"
            )
    return McpServerConfig(
        name=name or entry.id,
        url=url,
        auth_env=entry.auth_env,
        allowed_agents=(
            list(allowed_agents) if allowed_agents is not None else list(entry.allowed_agents)
        ),
        tools=wanted,  # type: ignore[arg-type]
    )
