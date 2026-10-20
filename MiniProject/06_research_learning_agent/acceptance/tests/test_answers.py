"""Real 05-service acceptance checks, isolated from the public agent manifest."""

import asyncio

from conftest import VIDEO_A, VIDEO_B, ScriptedModel, metadata
from test_integration import integrated as shared_integrated

from youtube_agent.models import ModelReply

integrated = shared_integrated  # Register the existing core pytest fixture in this module.


class AnalysisModel:
    """Only the provider response is fake; module 05's analysis service is real."""

    def __init__(self):
        self.payloads = []

    async def generate(self, data, timeout):
        from youtube_answers.models import Generated, GeneratedAnswer

        self.payloads.append(data)
        refs = list(
            dict.fromkeys(
                cid for item in data["untrusted_evidence"] for cid in item["citation_ids"]
            )
        )
        return Generated(
            GeneratedAnswer(
                status="answered",
                statements=[
                    {
                        "text": "[FIXTURE 05] Both transcripts explain evidence-based answers.",
                        "citation_ids": refs,
                    }
                ],
            ),
            metadata(),
        )


class ComparisonModel(ScriptedModel):
    async def decide(self, history, timeout):
        self.history.append(list(history))
        observations = [h for h in history if h["role"] == "tool"]
        if not observations:
            return ModelReply(
                "compare_videos",
                {"video_ids": [VIDEO_A, VIDEO_B], "instruction": "เปรียบเทียบหลักฐาน"},
                metadata(),
            )
        return ModelReply(
            "finish_research",
            {
                "content": "[FIXTURE] Comparison from the selected videos.",
                "citation_ids": [e["chunk_id"] for e in observations[-1]["result"]["evidence"]],
            },
            metadata(),
        )


async def test_actual_05_comparison_shares_rag_scope_and_maps_reference_labels(integrated):
    from youtube_answers.config import AnswerSettings
    from youtube_answers.service import AnswerService

    env = integrated
    analysis_model = AnalysisModel()
    answers = AnswerService(
        AnswerSettings(_env_file=None), analysis_model, env.adapters.agent.knowledge
    )
    env.adapters.agent.analyzer = answers.analyze
    model = ComparisonModel()
    env.adapters.agent.model = model
    assert answers.knowledge.rag is env.adapters.agent.knowledge.rag
    body = {"goal": "เปรียบเทียบแนวคิดจากสองคลิป", "scope": {"video_ids": [VIDEO_A, VIDEO_B]}}
    response = await env.client.post("/api/research", json=body)
    job_id = response.json()["run_id"]
    await env.worker.run_once(job_id)
    job = env.repo.get_job(job_id)
    assert job["state"] == "completed", job
    observation = next(h["result"] for h in model.history[-1] if h["role"] == "tool")
    assert observation["coverage"]["complete"]
    mapping = {c["citation_id"]: c["chunk_id"] for c in observation["citations"]}
    assert "1" in mapping and mapping["1"] in {e["chunk_id"] for e in observation["evidence"]}
    assert "[1]" in observation["answer"]
    assert len(analysis_model.payloads) >= 3  # Per-video batches and final comparison.
    first = (await env.client.get(f"/api/research/{job_id}?limit=1")).json()["events"]
    rest = (
        await env.client.get(
            f"/api/research/{job_id}?after_event_id={first[0]['event_id']}&limit=200"
        )
    ).json()["events"]
    events = first + rest
    assert [e["step"] for e in events] == sorted(e["step"] for e in events)
    assert events[-1]["tool_name"] == "run_controller"
    assert events[-1]["state"] == job["state"]
    assert len({e["event_id"] for e in events}) == len(events)


async def test_cancellation_inside_actual_05_analysis_prevents_output(integrated):
    from youtube_answers.config import AnswerSettings
    from youtube_answers.service import AnswerService

    env = integrated
    started = asyncio.Event()
    analysis_model = AnalysisModel()
    original = analysis_model.generate

    async def slow(data, timeout):
        started.set()
        await asyncio.sleep(0.03)
        return await original(data, timeout)

    analysis_model.generate = slow
    answers = AnswerService(
        AnswerSettings(_env_file=None), analysis_model, env.adapters.agent.knowledge
    )
    env.adapters.agent.analyzer = answers.analyze
    env.adapters.agent.model = ComparisonModel()
    job = env.repo.enqueue(
        "research", {"goal": "Compare RAG lessons", "scope": {"video_ids": [VIDEO_A, VIDEO_B]}}
    )
    task = asyncio.create_task(env.worker.run_once(job["job_id"]))
    await asyncio.wait_for(started.wait(), 10)
    env.repo.cancel(job["job_id"])
    await task
    result = env.repo.get_job(job["job_id"])
    assert result["state"] == "cancelled" and result["result"] is None
