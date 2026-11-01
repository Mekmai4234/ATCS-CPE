"""Real team composition/worker and storage; scripted semantics, never live acceptance."""

import importlib.util
from pathlib import Path

import pytest
from youtube_agent.models import Generated
from youtube_backend.errors import AppError


def domain():
    spec = importlib.util.spec_from_file_location(
        "matrix_domain", Path(__file__).with_name("test_system.py")
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("kind", ["quiz", "flashcards", "study_plan"])
async def test_team_learning_artifact_fresh_job_and_restart_readback(tmp_path, monkeypatch, kind):
    system = domain()
    calls = []

    async def generate(self, request, records, schema, timeout):
        calls.append(request)
        cid = records[0].chunk_id
        content = {
            "quiz": {
                "questions": [
                    {
                        "question": "What?",
                        "answer": "Evidence",
                        "explanation": "From source",
                        "citations": [cid],
                    }
                ]
            },
            "flashcards": {
                "cards": [
                    {"front": "RAG evidence", "back": "Retrieved transcript", "citations": [cid]}
                ]
            },
            "study_plan": {
                "days": [
                    {"day": i, "topic": f"Study evidence {i}", "citations": [cid]}
                    for i in range(1, request["days"] + 1)
                ]
            },
        }[kind]
        return Generated(schema.model_validate(content), system.metadata())

    monkeypatch.setattr(system.ResearchModel, "generate", generate)
    async with system.system(tmp_path / "state") as (client, worker):
        imported = (
            await client.post("/api/videos/import", json={"urls": [f"https://youtu.be/{system.A}"]})
        ).json()
        await worker.run_once(imported["jobs"][0]["job_id"])
        result = await system.finish(
            client,
            worker,
            "/api/learning-artifacts",
            {"type": kind, "days": 2, "scope": {"video_ids": [system.A]}},
        )
        job_id = result["job_id"]
        artifact_id = result["result"]["artifact_ids"][0]
        original = (await client.get(f"/api/learning-artifacts/{artifact_id}")).json()
        fresh = await client.post(
            f"/api/jobs/{job_id}/regenerate", headers={"Idempotency-Key": "intentional"}
        )
        assert fresh.status_code == 202, fresh.text
        await worker.run_once(fresh.json()["job_id"])
        assert (await client.get("/api/jobs/" + fresh.json()["job_id"])).json()[
            "state"
        ] == "completed"
        assert len(calls) == 2
    async with system.system(tmp_path / "state") as (client, worker):
        assert (await client.get(f"/api/learning-artifacts/{artifact_id}")).json() == original
        assert (await client.get(f"/api/jobs/{job_id}")).json()["result"] == result["result"]
        assert len(calls) == 2


@pytest.mark.parametrize(
    "answer,correct",
    [("Evidence", True), ("ข้อมูลหลักฐาน", True), ("wrong", False), ("", True), ("ambiguous", False)],
)
async def test_team_grading_totals_blank_guard_and_idempotency(
    tmp_path, monkeypatch, answer, correct
):
    system = domain()
    calls = []

    async def grade(self, request, timeout, *, context):
        calls.append(request)
        assert request["questions"][0]["answer"] == "Evidence"
        return {"marks": [{"correct": correct, "feedback": "scripted rubric"}]}

    monkeypatch.setattr(system.ResearchModel, "grade_quiz", grade, raising=False)
    async with system.system(tmp_path / "state") as (client, worker):
        imported = (
            await client.post("/api/videos/import", json={"urls": [f"https://youtu.be/{system.A}"]})
        ).json()
        await worker.run_once(imported["jobs"][0]["job_id"])
        quiz = await system.finish(
            client,
            worker,
            "/api/learning-artifacts",
            {"type": "quiz", "scope": {"video_ids": [system.A]}},
        )
        artifact = quiz["result"]["artifact_ids"][0]
        endpoint = f"/api/learning-artifacts/{artifact}/submit"
        submission = await client.post(
            endpoint, json={"answers": [answer]}, headers={"Idempotency-Key": "submission"}
        )
        await worker.run_once(submission.json()["job_id"])
        saved = (await client.get("/api/jobs/" + submission.json()["job_id"])).json()
        assert saved["state"] == "completed"
        assert saved["result"]["correct"] == int(correct and bool(answer.strip()))
        assert saved["result"]["total"] == 1
        replay = await client.post(
            endpoint, json={"answers": [answer]}, headers={"Idempotency-Key": "submission"}
        )
        assert replay.json()["job_id"] == submission.json()["job_id"] and len(calls) == 1


async def test_grader_provider_failure_does_not_publish_wrong_answer_score(tmp_path, monkeypatch):
    system = domain()

    async def unavailable(self, request, timeout, *, context):
        raise AppError("quota_wait", "scripted daily wait", 429, True, retry_after_seconds=3600)

    monkeypatch.setattr(system.ResearchModel, "grade_quiz", unavailable, raising=False)
    async with system.system(tmp_path / "state") as (client, worker):
        imported = (
            await client.post("/api/videos/import", json={"urls": [f"https://youtu.be/{system.A}"]})
        ).json()
        await worker.run_once(imported["jobs"][0]["job_id"])
        quiz = await system.finish(
            client,
            worker,
            "/api/learning-artifacts",
            {"type": "quiz", "scope": {"video_ids": [system.A]}},
        )
        artifact = quiz["result"]["artifact_ids"][0]
        submission = await client.post(
            f"/api/learning-artifacts/{artifact}/submit", json={"answers": ["Evidence"]}
        )
        await worker.run_once(submission.json()["job_id"])
        saved = (await client.get("/api/jobs/" + submission.json()["job_id"])).json()
        assert saved["state"] == "paused" and saved["result"] is None
        assert saved["error_code"] == "quota_wait"
