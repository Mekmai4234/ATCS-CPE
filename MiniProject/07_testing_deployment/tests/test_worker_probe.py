"""Probe replay and stop-on-failure use the real persisted worker states."""

import pytest
from test_system import A, system
from test_tooling import load


def module(monkeypatch):
    from pathlib import Path

    monkeypatch.syspath_prepend(str(Path(__file__).parents[1] / "scripts"))
    return load("worker_probe")


def test_probe_rejects_invalid_cases_before_any_provider(monkeypatch):
    probe = module(monkeypatch)
    for cases in ([], [{"name": "x", "kind": "delete", "request": {}}]):
        with pytest.raises(ValueError):
            probe.validate_cases(cases)


async def test_probe_replay_reads_artifact_without_new_generation(tmp_path, monkeypatch):
    probe = module(monkeypatch)
    async with system(tmp_path / "state") as (_, worker):
        job = worker.repo.import_urls([f"https://youtu.be/{A}"])[0]
        await worker.run_once(job["job_id"])
        cases = [
            {
                "name": "quiz",
                "kind": "artifact",
                "request": {"type": "quiz", "scope": {"video_ids": [A]}},
            }
        ]
        rows = await probe.execute(worker.repo, worker.adapters, cases, "isolated-test")
        assert rows[0]["state"] == "completed"
        assert rows[0]["same_job_on_replay"]
        assert rows[0]["artifacts"][0]["content"]["questions"]
        with pytest.raises(probe.AppError, match="new explicit run key"):
            await probe.execute(worker.repo, worker.adapters, cases, "isolated-test")


async def test_probe_stops_and_cancels_retry_after_provider_failure(tmp_path, monkeypatch):
    probe = module(monkeypatch)
    async with system(tmp_path / "state") as (_, worker):
        job = worker.repo.import_urls([f"https://youtu.be/{A}"])[0]
        await worker.run_once(job["job_id"])

        async def fail(*args):
            raise probe.AppError("provider_unavailable", "Fixture unavailable", 503, True)

        monkeypatch.setattr(worker.adapters, "artifact", fail)
        case = {
            "name": "quiz",
            "kind": "artifact",
            "request": {"type": "quiz", "scope": {"video_ids": [A]}},
        }
        rows = await probe.execute(
            worker.repo, worker.adapters, [case, {**case, "name": "second"}], "failure-test"
        )
        assert len(rows) == 1
        assert rows[0]["error_code"] == "provider_unavailable"
        assert worker.repo.get_job(rows[0]["job_id"])["state"] == "cancelled"


async def test_probe_quiz_submission_uses_saved_questions_and_blank_override(tmp_path, monkeypatch):
    from youtube_backend.schemas import QuizGradeContent

    probe = module(monkeypatch)
    async with system(tmp_path / "state") as (_, worker):
        imported = worker.repo.import_urls([f"https://youtu.be/{A}"])[0]
        await worker.run_once(imported["job_id"])
        generated = await probe.execute(
            worker.repo,
            worker.adapters,
            [
                {
                    "name": "quiz",
                    "kind": "artifact",
                    "request": {"type": "quiz", "scope": {"video_ids": [A]}},
                }
            ],
            "grade-seed",
        )
        artifact = generated[0]["artifacts"][0]
        calls = []

        async def grade(request, context):
            calls.append(request)
            assert request["questions"] == artifact["content"]["questions"]
            return QuizGradeContent(
                marks=[{"correct": True, "feedback": "fixture intentionally wrong blank mark"}]
            )

        monkeypatch.setattr(worker.adapters, "grade_quiz", grade)
        rows = await probe.execute(
            worker.repo,
            worker.adapters,
            [
                {
                    "name": "grade",
                    "kind": "quiz_grade",
                    "request": {"artifact_id": artifact["artifact_id"], "answers": [""]},
                }
            ],
            "grade-once",
        )
        assert rows[0]["state"] == "completed"
        assert rows[0]["result"]["correct"] == 0
        assert len(calls) == 1
        assert rows[0]["same_job_on_replay"]
