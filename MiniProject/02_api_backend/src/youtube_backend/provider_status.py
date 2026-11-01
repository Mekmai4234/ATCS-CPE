"""Authenticated, sanitized configuration/health evidence. Never a model admission grant."""

import json
import re
import time

import httpx
import sqlalchemy as sa

from . import database as db
from .errors import AppError
from .local_inference import execution_identity, private_url, public_execution
from .repository import iso


async def installed(settings, *, transport=None):
    try:
        async with httpx.AsyncClient(
            base_url=private_url(settings.local_base_url),
            timeout=2,
            transport=transport,
            trust_env=False,
            follow_redirects=False,
        ) as client:
            async with client.stream("GET", "/api/tags") as response:
                if response.status_code != 200:
                    return None
                data = bytearray()
                async for part in response.aiter_bytes():
                    data.extend(part)
                    if len(data) > 1_000_000:
                        return None
                models = json.loads(data).get("models")
                return models if isinstance(models, list) else None
    except (httpx.HTTPError, ValueError, AppError):
        return None


async def provider_status(repo, runtime, *, transport=None):
    with repo.db.read() as c:
        repo._actor(c)
        table = db.v2["reservations"]
        active = c.scalar(
            sa.select(sa.func.count())
            .select_from(table)
            .where(
                table.c.project == "local:ollama",
                table.c.state.in_(["held", "sent", "uncertain"]),
                table.c.expires_at > time.time(),
            )
        )
    settings = repo.settings
    identity = execution_identity(settings)
    synthetic = (
        settings.adapter_mode == "fixture" or settings.backend_integration_profile == "offline"
    )
    declared = getattr(runtime.adapter, "provider_operations", {}) or {}
    operations = {}
    for operation in ("index", "answer", "analyze", "research", "artifact", "grade_quiz"):
        provider = identity["embedding_provider"] if operation == "index" else identity["provider"]
        available = callable(getattr(runtime.adapter, operation, None))
        if operation in runtime.capabilities:
            available &= runtime.capabilities[operation] != "unavailable"
        mounted = available and declared.get(operation) == (
            "local" if provider == "ollama" else "gemini-broker-v1"
        )
        operations[operation] = {
            "provider": provider,
            "mounted": bool(mounted),
            "state": "synthetic" if synthetic else "configured" if mounted else "unsupported",
        }
    local = {"state": "not_selected", "reason": None}
    if "ollama" in {identity["provider"], identity["embedding_provider"]}:
        pins = []
        if identity["provider"] == "ollama":
            pins.append((identity["model"], identity["version"]))
        if identity["embedding_provider"] == "ollama":
            pins.append((identity["embedding_model"], identity["embedding_version"]))
        if any(
            not model or "cloud" in model.lower() or not re.fullmatch(r"[a-f0-9]{64}", digest or "")
            for model, digest in pins
        ):
            local = {"state": "unverified", "reason": "local_configuration"}
        else:
            models = await installed(settings, transport=transport)
            if models is None:
                local = {"state": "unavailable", "reason": "local_unavailable"}
            elif not all(
                any(
                    item.get("name") == model and item.get("digest") == digest
                    for item in models
                    if isinstance(item, dict)
                )
                for model, digest in pins
            ):
                local = {"state": "unavailable", "reason": "local_model_changed"}
            else:
                local = {
                    "state": "busy" if active >= settings.local_max_concurrent else "ready",
                    "reason": "local_busy" if active >= settings.local_max_concurrent else None,
                }
    return {
        "selection": "server_configuration",
        "execution": public_execution(identity),
        "observed_at": iso(time.time()),
        "operations": operations,
        "local": local,
        "synthetic": synthetic,
        "admission_guaranteed": False,
        "model_calls": 0,
        "loading_observed": False,
        "loading_note": "Model loading is not inferred from installed tags",
        "history_reads_generate": False,
        "regenerate": sorted(
            set(getattr(runtime.adapter, "fresh_generation", ())) & {"artifact", "research"}
        ),
        "trial_reindex": settings.trial_reindex_enabled
        and settings.auth_enabled
        and settings.app_env in {"test", "development"},
    }
