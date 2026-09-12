"""Canonical inventory of governed tool names.

Workspace packs declare tool scopes and tests validate both directions against
this catalog, so pack drift (a typo'd or stale tool name) fails the gate instead
of silently granting or hiding a tool. Add a name here in the same change that
introduces a new tool factory.
"""

from __future__ import annotations

TOOL_NAMES: frozenset[str] = frozenset(
    {
        "analyze_repo_ast",
        "canonicalize_skill",
        "capture_consent",
        "detect_frameworks",
        "escalate_to_human",
        "get_candidate_profile",
        "get_evaluation_breakdown",
        "github_profile",
        "lookup_publication",
        "record_availability",
        "repo_metrics",
        "search_knowledge",
        "verify_credential",
    }
)
