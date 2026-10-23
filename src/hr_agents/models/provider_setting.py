"""One operator-managed provider selection, per capability.

The capability is stored as a string rather than the provider layer's enum: the
provider layer imports these models, so the enum cannot be imported back into
them. The service validates the value against the registry before it is saved.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

from pydantic import Field

from hr_agents.models.common import UtcDateTime, Versioned, utc_now


class ProviderSetting(Versioned):
    """A provider selection and its raw configuration, as the operator entered it.

    ``config`` holds plaintext only in memory. The database adapter seals it
    before writing, and the API masks anything named as a secret. It is never
    written to the audit chain.
    """

    id: UUID = Field(default_factory=uuid4)
    capability: str = Field(min_length=1, max_length=32)
    provider_id: str = Field(min_length=1, max_length=120)
    config: dict[str, Any] = Field(default_factory=dict)
    updated_by: str = Field(min_length=1, max_length=200)
    updated_at: UtcDateTime = Field(default_factory=utc_now)
