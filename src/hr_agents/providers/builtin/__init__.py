"""Built-in providers."""

from hr_agents.providers.base import ProviderSpec
from hr_agents.providers.builtin.llm import LLM_SPECS
from hr_agents.providers.builtin.queue import QUEUE_SPECS
from hr_agents.providers.calendar import calendar_specs
from hr_agents.providers.email import email_specs
from hr_agents.providers.embeddings import embedding_specs
from hr_agents.providers.storage import storage_specs
from hr_agents.providers.vector import vector_specs
from hr_agents.providers.whatsapp import whatsapp_specs


def all_specs() -> list[ProviderSpec]:
    """Every built-in provider spec."""
    return [
        *QUEUE_SPECS,
        *LLM_SPECS,
        *email_specs(),
        *whatsapp_specs(),
        *calendar_specs(),
        *storage_specs(),
        *embedding_specs(),
        *vector_specs(),
    ]
