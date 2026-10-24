"""05 consumer contract for a trusted project-wide broker, not a local quota counter."""

import hashlib
import time
from typing import Literal, Protocol

from pydantic import Field
from youtube_backend.schemas import Schema

from .models import error


class ModelGrant(Schema):
    project_id: str = Field(min_length=1)
    credential_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    requested_model: str = Field(min_length=1)
    returned_models: list[str] = Field(min_length=1)
    purpose: Literal["chat", "vision"]
    free_tier_verified: Literal[True]
    expires_at: float
    image_access_verified: bool = False
    max_output_tokens: int = Field(ge=128, le=32000)
    thinking_level: Literal["LOW", "MINIMAL"] | None = None


class QuotaBroker(Protocol):
    """02 supplies one broker shared by all workers/providers in the project.

    authorize binds externally verified billing, role allowlists, actual API capability,
    credential/project and alias versions. A catalog lookup alone is insufficient.
    reserve is an async context manager: atomically reserve requests/tokens/concurrency,
    debit failures/cancellation and expose record(usage, returned_model) on its lease.
    It must never retry the callback or select another model/key/provider.
    """

    def authorize(self, *, model, purpose, credential_sha256) -> ModelGrant: ...

    def reserve(self, *, grant, operation, input_tokens, output_tokens): ...


def verified_grant(broker, settings, model, purpose):
    if broker is None:
        raise error("quota_pending", "Verified shared Free Tier broker is required", status=503)
    fingerprint = hashlib.sha256(settings.gemini_api_key.get_secret_value().encode()).hexdigest()
    try:
        grant = ModelGrant.model_validate(
            broker.authorize(model=model, purpose=purpose, credential_sha256=fingerprint)
        )
    except ValueError:
        raise error("quota_pending", "Verified Free Tier grant is required", status=503) from None
    if (
        grant.requested_model != model
        or grant.purpose != purpose
        or grant.credential_sha256 != fingerprint
        or grant.expires_at <= time.time()
        or (purpose == "vision" and not grant.image_access_verified)
    ):
        raise error(
            "quota_pending", "Free Tier/model verification is missing or expired", status=503
        )
    return grant
