"""Own async adapter resources in the same loop that executes their operations."""

import asyncio
import inspect

from .errors import AppError
from .integrations import UnavailableAdapters, load_adapters

METHODS = (
    "ingest",
    "index",
    "delete",
    "evidence",
    "inventory",
    "answer",
    "analyze",
    "research",
    "artifact",
)


def capabilities(adapter):
    declared = getattr(adapter, "capabilities", None)
    if isinstance(declared, dict):
        return {name: "available" if declared.get(name) else "unavailable" for name in METHODS}
    if isinstance(adapter, UnavailableAdapters):
        return {
            name: "unavailable"
            if getattr(type(adapter), name, None) is UnavailableAdapters._missing
            else "available"
            for name in METHODS
        }
    # Legacy injected/custom adapters retain the v0.1 calling contract. Presence of a
    # Python method alone is not a promise that an external provider is ready.
    return dict.fromkeys(METHODS, "unknown")


async def close_adapter(adapter):
    close = getattr(adapter, "close", None)
    if close is not None:
        result = close()
        if inspect.isawaitable(result):
            await result


class ManagedAdapters:
    def __init__(self, settings, repository, adapter=None):
        self.settings, self.repository = settings, repository
        self.adapter = adapter
        self.started = False
        self.closed = False
        self._lock = None

    async def start(self):
        if self.closed:
            raise AppError("adapter_closed", "Adapter runtime has stopped", 503)
        if self.started:
            return
        if self._lock is None:
            self._lock = asyncio.Lock()
        async with self._lock:
            if self.closed:
                raise AppError("adapter_closed", "Adapter runtime has stopped", 503)
            if self.started:
                return
            self.repository.db.check_schema()
            self.repository.check_mode()
            if self.settings.backend_full_preflight:
                from .config import Settings
                from .full import FullSettings
                from .full_pair import check_pair

                config = FullSettings(
                    _env_file=None,
                    **{name: getattr(self.settings, name) for name in Settings.model_fields},
                )
                check_pair(config)
            if self.adapter is None:
                candidate = load_adapters(self.settings, self.repository)
                self.adapter = await candidate if inspect.isawaitable(candidate) else candidate
            self.started = True

    @property
    def capabilities(self):
        return (
            capabilities(self.adapter)
            if self.adapter is not None
            else dict.fromkeys(METHODS, "unknown")
        )

    async def require(self, *names):
        await self.start()
        if any(self.capabilities[name] == "unavailable" for name in names):
            raise AppError(
                "dependency_unavailable", "This operation's adapters are not connected", 503
            )
        # Admission checks only adapter availability. Gate the actual outbound
        # operation in invoke(), so local ingestion/OCR can run before indexing.

    def gemini_gate(self, name):
        """Legacy provider adapters cannot silently bypass the project broker.

        Local operations are explicitly declared by trusted composition, never by
        request JSON. Production consumers must declare gemini-broker-v1 and wrap
        every provider HTTP call via ExecutionContext.gemini_call.
        """
        if (
            self.settings.adapter_mode == "fixture"
            or self.settings.backend_integration_profile == "offline"
        ):
            return
        if name not in {
            "index",
            "answer",
            "analyze",
            "research",
            "artifact",
            "enrich",
            "companion",
            "grade_quiz",
        }:
            return
        declared = getattr(self.adapter, "provider_operations", {})
        if isinstance(declared, dict) and declared.get(name) in {"local", "gemini-broker-v1"}:
            return
        from .quota import QuotaBroker

        model = self.settings.embedding_model if name == "index" else self.settings.llm_model
        endpoint = "embedContent" if name == "index" else "generateContent"
        QuotaBroker(self.repository).access(model, endpoint)
        raise AppError(
            "gemini_broker_required",
            "Adapter must route every Gemini call through the broker",
            503,
            pause=True,
        )

    async def close(self):
        if self._lock is None:
            self._lock = asyncio.Lock()
        async with self._lock:
            if self.closed:
                return
            self.closed = True
            if self.adapter is not None:
                await close_adapter(self.adapter)

    def __getattr__(self, name):
        if name not in METHODS and name not in {"enrich", "companion", "grade_quiz"}:
            raise AttributeError(name)

        async def invoke(*args, **kwargs):
            await self.start()
            self.gemini_gate(name)
            return await getattr(self.adapter, name)(*args, **kwargs)

        return invoke
