"""Typed, least-privilege agent tools with audited execution.

No shell tools. No generic URL fetchers. Every tool is scoped to explicit agent
allowlists and every call is recorded on the audit chain by argument hash.
"""

from hr_agents.tools.knowledge import make_search_knowledge_tool
from hr_agents.tools.portfolio import (
    make_analyze_repo_ast_tool,
    make_detect_frameworks_tool,
    make_github_profile_tool,
    make_lookup_publication_tool,
    make_repo_metrics_tool,
    make_verify_credential_tool,
)
from hr_agents.tools.registry import (
    AuditSink,
    ToolDefinition,
    ToolNotFoundError,
    ToolPermissionError,
    ToolRegistry,
)
from hr_agents.tools.screening import (
    make_capture_consent_tool,
    make_escalate_to_human_tool,
    make_get_candidate_profile_tool,
    make_record_availability_tool,
)
from hr_agents.tools.taxonomy import make_canonicalize_skill_tool

__all__ = [
    "AuditSink",
    "ToolDefinition",
    "ToolNotFoundError",
    "ToolPermissionError",
    "ToolRegistry",
    "make_analyze_repo_ast_tool",
    "make_canonicalize_skill_tool",
    "make_capture_consent_tool",
    "make_detect_frameworks_tool",
    "make_escalate_to_human_tool",
    "make_get_candidate_profile_tool",
    "make_github_profile_tool",
    "make_lookup_publication_tool",
    "make_record_availability_tool",
    "make_repo_metrics_tool",
    "make_search_knowledge_tool",
    "make_verify_credential_tool",
]
