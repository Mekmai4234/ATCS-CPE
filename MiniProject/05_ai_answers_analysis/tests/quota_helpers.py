"""Explicit OFFLINE broker double. Never imported into application startup."""

import time
from contextlib import asynccontextmanager

from youtube_answers.quota import ModelGrant


class OfflineBroker:
    def __init__(self):
        self.calls = []
        self.records = []
        self.expired = False
        self.returned = ["fixture-sdk-wire"]

    def authorize(self, *, model, purpose, credential_sha256):
        return ModelGrant(
            project_id="OFFLINE-NO-REAL-PROJECT",
            credential_sha256=credential_sha256,
            requested_model=model,
            returned_models=self.returned,
            purpose=purpose,
            free_tier_verified=True,
            image_access_verified=True,
            expires_at=time.time() + (-1 if self.expired else 60),
            max_output_tokens=1200,
            thinking_level="LOW",
        )

    @asynccontextmanager
    async def reserve(self, **kwargs):
        self.calls.append(kwargs)
        yield self

    def record(self, usage, returned_model):
        self.records.append((usage, returned_model))
