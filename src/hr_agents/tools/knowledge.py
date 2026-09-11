"""Knowledge retrieval tool factory.

``search_knowledge`` is the only way agents read the knowledge base. It enforces
the calling agent's namespace scope, caps result counts, and always returns
citation metadata — answers without a citation are a bug, not a style choice.
"""

from __future__ import annotations

from collections.abc import Sequence

from hr_agents.knowledge.retriever import KnowledgeRetriever, NamespaceAccessError
from hr_agents.tools.registry import ToolDefinition

DEFAULT_LIMIT = 5
MAX_LIMIT = 10


def make_search_knowledge_tool(
    retriever: KnowledgeRetriever,
    *,
    namespaces: Sequence[str],
    name: str = "search_knowledge",
) -> ToolDefinition:
    """Build the ``search_knowledge`` tool bound to a retriever and scope."""
    scope = tuple(namespaces)

    async def search_knowledge(query: str, limit: int = DEFAULT_LIMIT) -> dict[str, object]:
        """Search the knowledge base; returns passages with mandatory citations."""
        if not query.strip():
            return {"error": "query must not be empty", "results": []}
        if limit <= 0:
            return {"error": "limit must be positive", "results": []}
        effective_limit = min(limit, MAX_LIMIT)

        try:
            hits = await retriever.retrieve(query, namespaces=list(scope), limit=effective_limit)
        except NamespaceAccessError as exc:
            return {"error": str(exc), "results": []}

        return {
            "query": query,
            "results": [
                {
                    "doc_id": hit.doc_id,
                    "title": hit.title,
                    "namespace": hit.namespace,
                    "heading_path": hit.heading_path,
                    "text": hit.text,
                    "score": hit.score,
                    "citation": hit.citation(),
                }
                for hit in hits
            ],
            "count": len(hits),
        }

    return ToolDefinition(
        name=name,
        description=(
            "Search the company knowledge base for policies, rubrics, and process "
            "documentation. Returns passages with citations; cite the source in every "
            "answer. If nothing relevant is returned, escalate instead of guessing."
        ),
        allowed_agents=frozenset(
            {
                "resume_deconstructor",
                "code_portfolio",
                "screening_coordinator",
                "feedback_writer",
                "policy_assistant",
            }
        ),
        handler=search_knowledge,
        tags=frozenset({"knowledge", "read"}),
    )
