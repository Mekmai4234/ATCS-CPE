"""Opt-in real local models, synthetic captions/identity, disposable actual API/worker/RAG.

This is a mechanism probe, not human-gold or real-YouTube semantic acceptance.
"""

import argparse
import asyncio
import importlib.util
import json
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx
import sqlalchemy as sa
from youtube_agent.config import AgentSettings
from youtube_agent.local import LocalModel
from youtube_backend import database as db
from youtube_backend.local_inference import private_url
from youtube_rag.config import RagSettings
from youtube_rag.embeddings import OllamaEmbedder
from youtube_rag.manifest import Manifest
from youtube_rag.service import RagService


async def run(url, generation, embedding, research_chunks=0):
    url = private_url(url)
    async with httpx.AsyncClient(base_url=url, trust_env=False, timeout=5) as http:
        tags = (await http.get("/api/tags")).json()["models"]
    models = {item["name"]: item["digest"] for item in tags}
    if generation not in models or embedding not in models:
        raise ValueError("Install both reviewed models before this opt-in probe")
    spec = importlib.util.spec_from_file_location(
        "probe_domain", Path(__file__).parents[1] / "tests" / "test_system.py"
    )
    domain = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(domain)
    if research_chunks:

        async def captions(self, video_id, languages, timeout):
            return dict(
                video_id=video_id,
                language="en",
                is_generated=False,
                segments=[
                    dict(text=f"Fact {i}: RAG uses evidence.", start=i * 3.0, duration=3.0)
                    for i in range(research_chunks)
                ],
            )

        domain.CaptionProvider.fetch = captions
    results, apps = [], []
    with tempfile.TemporaryDirectory(prefix="video-buddy-local-probe-") as directory:
        async with domain.system(
            Path(directory) / "state", auth=True, configure_app=apps.append
        ) as (client, worker):
            settings = worker.repo.settings
            settings.generation_provider = "ollama"
            settings.local_model, settings.local_model_digest = generation, models[generation]
            settings.embedding_provider = "ollama"
            settings.embedding_model = settings.local_embedding_model = embedding
            settings.local_embedding_digest = models[embedding]
            settings.local_base_url = url
            settings.local_context_tokens = 8192
            settings.local_max_output_tokens = 1024
            settings.llm_timeout_seconds = 120
            settings.job_timeout_seconds = 600
            # Qwen3-Embedding 0.6B output dimension; mismatches fail vector validation.
            settings.embedding_dimensions = 1024
            rag_settings = RagSettings(
                _env_file=None,
                **{
                    **worker.adapters.answers.rag.settings.model_dump(),
                    "embedding_provider": "ollama",
                    "embedding_model": embedding,
                    "local_embedding_model": embedding,
                    "local_embedding_digest": models[embedding],
                    "embedding_dimensions": 1024,
                    **(
                        {"chunk_target_tokens": 32, "chunk_overlap_tokens": 0}
                        if research_chunks
                        else {}
                    ),
                },
            )
            old = worker.adapters.answers.rag
            await old.close()
            rag = RagService(rag_settings, Manifest(worker.repo.db), OllamaEmbedder(rag_settings))
            worker.adapters.answers.rag = rag
            worker.adapters.answers.answers.knowledge.rag = rag
            worker.adapters.agent.knowledge = domain.RagKnowledge(rag)
            config = AgentSettings.from_backend(settings)
            worker.adapters.agent.settings = config
            worker.adapters.agent.model = LocalModel(config)
            app = apps[0]
            challenge = (await client.get("/api/auth/challenge")).json()
            app.state.auth.verifier = lambda credential, audience: dict(
                sub="local-probe-fixture",
                aud=audience,
                iss="https://accounts.google.com",
                exp=time.time() + 300,
                nonce=challenge["nonce"],
            )
            login = await client.post(
                "/api/auth/google",
                headers={"Origin": "http://localhost:3000"},
                json={"credential": "fixture", "csrf_token": challenge["csrf_token"]},
            )
            login.raise_for_status()
            client.headers.update(
                {"Origin": "http://localhost:3000", "X-CSRF-Token": login.json()["csrf_token"]}
            )
            imported = await client.post(
                "/api/videos/import", json={"urls": [f"https://youtu.be/{domain.A}"]}
            )
            imported.raise_for_status()
            started = time.monotonic()
            import_id = imported.json()["jobs"][0]["job_id"]
            await worker.run_once(import_id)
            status = (await client.get("/api/jobs/" + import_id)).json()
            results.append(
                {
                    "operation": "local_index_synthetic_transcript",
                    "state": status["state"],
                    "elapsed_ms": (time.monotonic() - started) * 1000,
                    "error_code": status.get("error_code"),
                }
            )
            if status["state"] == "completed":
                if research_chunks:
                    settings.local_context_tokens = 32768
                    worker.adapters.agent.settings = AgentSettings.from_backend(settings)
                    worker.adapters.agent.model = LocalModel(worker.adapters.agent.settings)
                    start = time.monotonic()
                    response = await client.post(
                        "/api/research",
                        json={"goal": "Summarize RAG facts", "scope": {"video_ids": [domain.A]}},
                        headers={"Idempotency-Key": "probe-multipage-research"},
                    )
                    response.raise_for_status()
                    job_id = response.json()["run_id"]
                    await worker.run_once(job_id)
                    research = (await client.get("/api/jobs/" + job_id)).json()
                    results.append(
                        {
                            "operation": "multi_page_local_research",
                            "state": research["state"],
                            "elapsed_ms": (time.monotonic() - start) * 1000,
                            "error_code": research.get("error_code"),
                            "result": research.get("result"),
                            "default_model_call_budget": config.agent_max_model_calls,
                            "default_step_budget": worker.adapters.agent.settings.agent_max_steps,
                        }
                    )
                for kind in () if research_chunks else ("flashcards", "quiz", "study_plan"):
                    started = time.monotonic()
                    body = {
                        "type": kind,
                        "topic": "RAG",
                        "days": 2,
                        "scope": {"video_ids": [domain.A]},
                    }
                    headers = {"Idempotency-Key": "probe-" + kind}
                    response = await client.post(
                        "/api/learning-artifacts", json=body, headers=headers
                    )
                    response.raise_for_status()
                    job_id = response.json()["job_id"]
                    await worker.run_once(job_id)
                    status = (await client.get("/api/jobs/" + job_id)).json()
                    item = {
                        "operation": kind,
                        "state": status["state"],
                        "elapsed_ms": (time.monotonic() - started) * 1000,
                        "error_code": status.get("error_code"),
                    }
                    replay = await client.post(
                        "/api/learning-artifacts", json=body, headers=headers
                    )
                    item["idempotent_replay"] = replay.json().get("job_id") == job_id
                    if status["state"] == "completed":
                        artifact_id = status["result"]["artifact_ids"][0]
                        artifact = (
                            await client.get("/api/learning-artifacts/" + artifact_id)
                        ).json()
                        item["provider_metadata"] = artifact["provider_metadata"]
                    results.append(item)
            with worker.repo.db.read() as c:
                reservations = [
                    dict(row) for row in c.execute(sa.select(db.v2["reservations"])).mappings()
                ]
            counts = {
                endpoint: sum(
                    row["endpoint"] == endpoint and row["state"] != "cancelled"
                    for row in reservations
                )
                for endpoint in ("embed", "chat")
            }
    return {
        "observed_at": datetime.now(UTC).isoformat(),
        "fixture_identity_and_captions": True,
        "real_local_models": True,
        "models": {name: models[name] for name in (generation, embedding)},
        "results": results,
        "outbound_model_attempts": counts,
        "gemini_calls": 0,
        "human_gold": "pending",
        "semantic_acceptance": False,
        "public_deployment_ready": False,
        "disposable_state_removed": True,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:11434")
    parser.add_argument("--generation-model", required=True)
    parser.add_argument("--embedding-model", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--research-chunks", type=int, choices=range(32, 129), default=0)
    args = parser.parse_args()
    report = asyncio.run(
        run(args.url, args.generation_model, args.embedding_model, args.research_chunks)
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
