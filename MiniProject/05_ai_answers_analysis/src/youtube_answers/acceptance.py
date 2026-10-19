"""Opt-in HTTP acceptance and claim review packets for actual imported transcripts.

Structural checks are automatic. Semantic correctness always starts as pending human
review; a model must never certify its own claims as correct.
"""

import argparse
import asyncio
import json
import re
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit
from uuid import uuid4

import httpx
from pydantic import Field, model_validator
from youtube_backend.schemas import AnalysisRequest, AnswerResult, ChatRequest, Schema
from youtube_backend.urls import canonical_url, normalize_url

from .models import error

REQUIRED_CATEGORIES = {
    "supported",
    "unsupported",
    "followup",
    "contradiction",
    "long_summary",
    "multi_summary",
}


class AcceptanceCase(Schema):
    id: str = Field(min_length=1, max_length=100)
    category: Literal[
        "supported",
        "unsupported",
        "followup",
        "contradiction",
        "long_summary",
        "multi_summary",
    ]
    kind: Literal["chat", "analysis"]
    request: dict
    conversation_from: str | None = None
    expected_status: Literal["answered", "insufficient_evidence"] = "answered"
    expected_complete: bool | None = None
    min_processed_chunks: int = Field(default=0, ge=0)
    review_criteria: str = Field(min_length=1, max_length=4000)

    @model_validator(mode="after")
    def request_contract(self):
        schema = ChatRequest if self.kind == "chat" else AnalysisRequest
        self.request = schema.model_validate(self.request).model_dump(mode="json")
        if self.conversation_from and self.kind != "chat":
            raise ValueError("Only chat cases can continue a conversation")
        return self


class AcceptancePlan(Schema):
    videos: list[str] = Field(min_length=2, max_length=20)
    expected_model: str = Field(min_length=1, max_length=200)
    cases: list[AcceptanceCase] = Field(min_length=1, max_length=40)

    @model_validator(mode="after")
    def references(self):
        videos = [normalize_url(url) for url in self.videos]
        if len(set(videos)) != len(videos):
            raise ValueError("Import distinct videos")
        seen = set()
        for case in self.cases:
            if case.id in seen or (case.conversation_from and case.conversation_from not in seen):
                raise ValueError("Case IDs must be unique and follow earlier conversations")
            if set(case.request["scope"]["video_ids"]) - set(videos):
                raise ValueError("Case scope must use videos in this plan")
            seen.add(case.id)
        return self


class AcceptanceRunner:
    def __init__(self, client, *, poll_timeout=300, poll_interval=1):
        self.client = client
        self.poll_timeout, self.poll_interval = poll_timeout, poll_interval
        self.transcripts = {}

    async def _request(self, method, path, **kwargs):
        try:
            response = await self.client.request(method, path, **kwargs)
            response.raise_for_status()
            return response.json()
        except (httpx.HTTPError, ValueError):
            # Do not echo raw provider/server bodies, headers or request credentials.
            raise error("acceptance_http_error", "Acceptance HTTP request failed") from None

    async def _result(self, value):
        if "job_id" not in value:
            raise error("acceptance_invalid_response", "Response has no job ID")
        deadline = time.monotonic() + self.poll_timeout
        while time.monotonic() < deadline:
            job = await self._request("GET", f"/api/jobs/{value['job_id']}")
            if job["state"] in {"completed", "partial"}:
                if not isinstance(job.get("result"), dict):
                    raise error("acceptance_invalid_response", "Completed job has no result")
                return job["result"]
            if job["state"] not in {"queued", "running"}:
                raise error("acceptance_job_failed", "Acceptance job did not complete")
            await asyncio.sleep(self.poll_interval)
        raise error("acceptance_poll_timeout", "Worker did not finish before polling deadline")

    async def _import(self, plan):
        result = await self._request("POST", "/api/videos/import", json={"urls": plan.videos})
        items = result["jobs"]
        if len(items) != len(plan.videos):
            raise error("acceptance_import_failed", "Import results do not match requested URLs")
        for item in items:
            if item["outcome"] == "rejected" or not item.get("job_id"):
                raise error("acceptance_import_failed", "A planned video was rejected")
            value = await self._result(item)
            if "source" not in value:
                raise error("acceptance_import_failed", "Import did not produce an index receipt")
            job = await self._request("GET", f"/api/jobs/{item['job_id']}")
            if job.get("stage") != "ready":
                raise error("acceptance_import_failed", "Video is not ready")

    async def _sources(self, plan):
        wanted = {normalize_url(url) for url in plan.videos}
        videos, offset = {}, 0
        while True:
            page = await self._request(
                "GET", "/api/videos", params={"limit": 100, "offset": offset}
            )
            for video in page["items"]:
                if video["video_id"] in wanted:
                    videos[video["video_id"]] = video
            offset += len(page["items"])
            if wanted <= set(videos) or offset >= page["total"]:
                break
            if not page["items"]:
                raise error("acceptance_invalid_response", "Video pagination did not advance")
        if set(videos) != wanted or any(v["status"] != "ready" for v in videos.values()):
            raise error("acceptance_import_failed", "Selected videos are not ready")
        for video_id in wanted:
            segments, offset, version = [], 0, None
            while True:
                page = await self._request(
                    "GET",
                    f"/api/videos/{video_id}/transcript",
                    params={"limit": 100, "offset": offset},
                )
                if page.get("source") not in {
                    "youtube_captions:manual",
                    "youtube_captions:generated",
                }:
                    raise error(
                        "acceptance_synthetic_source", "Use transcripts imported by module 03"
                    )
                if version is not None and page["transcript_version"] != version:
                    raise error("source_changed", "Transcript changed during acceptance")
                version = page["transcript_version"]
                segments.extend(page["segments"])
                offset += len(page["segments"])
                if len(segments) > 100000:
                    raise error("acceptance_budget_exceeded", "Transcript review limit exceeded")
                if offset >= page["total"]:
                    break
                if not page["segments"]:
                    raise error(
                        "acceptance_invalid_response", "Transcript pagination did not advance"
                    )
            if version != videos[video_id]["transcript_version"]:
                raise error("source_changed", "Video version and transcript differ")
            self.transcripts[video_id] = segments
        return videos

    def _review(self, case, value, videos, expected_model):
        result = AnswerResult.model_validate({k: value[k] for k in AnswerResult.model_fields})
        checks = {
            "expected_status": result.status == case.expected_status,
            "live_provider_or_no_generation": result.provider_metadata.provider == "gemini"
            or (
                result.provider_metadata.provider == "none"
                and result.status == "insufficient_evidence"
                and not result.citations
                and not result.coverage.processed_chunks
            ),
            "requested_model": result.provider_metadata.requested_model == expected_model,
            "expected_coverage": case.expected_complete is None
            or result.coverage.complete == case.expected_complete,
            "minimum_processing": case.min_processed_chunks == 0
            or (result.coverage.processed_chunks or 0) >= case.min_processed_chunks,
            "coverage_scope": result.coverage.expected_videos
            == len(case.request["scope"]["video_ids"]),
            "partial_explained": result.coverage.complete or bool(result.coverage.notes),
            "citation_identity": True,
        }
        scoped = set(case.request["scope"]["video_ids"])
        references = {}
        for citation in result.citations:
            segments = [
                s
                for s in self.transcripts.get(citation.video_id, [])
                if s["start_seconds"] < citation.end_seconds
                and s["start_seconds"] + s["duration_seconds"] > citation.start_seconds
            ]
            video = videos.get(citation.video_id, {})
            valid = (
                citation.video_id in scoped
                and bool(segments)
                and (video.get("title") or f"YouTube {citation.video_id}") == citation.title
                and citation.start_seconds >= min(s["start_seconds"] for s in segments)
                and citation.end_seconds
                <= max(s["start_seconds"] + s["duration_seconds"] for s in segments)
                and citation.end_seconds > citation.start_seconds
                and citation.url
                == f"{canonical_url(citation.video_id)}&t={int(citation.start_seconds)}s"
            )
            checks["citation_identity"] &= valid
            references[citation.citation_id] = {
                "citation": citation.model_dump(),
                "transcript_segments": segments,
                "transcript_version": video.get("transcript_version"),
            }
        checks["citation_identity"] &= len(references) == len(result.citations)
        if result.status == "answered":
            checks["citation_identity"] &= bool(references)
            if case.kind == "analysis" and result.coverage.complete:
                checks["citation_identity"] &= {c.video_id for c in result.citations} == scoped
        claims = []
        for paragraph in result.answer.split("\n\n"):
            if paragraph.startswith("ข้อจำกัด / Limitations:"):
                continue
            ids = list(dict.fromkeys(re.findall(r"\[([^\[\]]+)\]", paragraph)))
            known = [cid for cid in ids if cid in references]
            if result.status == "answered":
                checks["citation_identity"] &= bool(known) and not (set(ids) - references.keys())
                claims.append(
                    {
                        "claim": paragraph,
                        "sources": [references[cid] for cid in known],
                        "semantic_support": "pending_human_review",
                        "reviewer_notes": "",
                    }
                )
        return {
            "case_id": case.id,
            "category": case.category,
            "structural_checks": checks,
            "structural_checks_passed": all(checks.values()),
            "result": value,
            "claim_reviews": claims,
            "review_criteria": case.review_criteria,
            "semantic_review": "pending_human_review",
        }

    async def run(self, plan):
        health = await self._request("GET", "/health")
        capabilities = health.get("capabilities", {})
        if (
            health.get("mode") != "custom"
            or health.get("synthetic_data") is not False
            or health.get("integration_profile") != "live"
            or any(
                capabilities.get(name) != "available"
                for name in (
                    "ingest",
                    "index",
                    "answer",
                    "analyze",
                    "evidence",
                    "inventory",
                )
            )
        ):
            raise error("acceptance_wrong_runtime", "Use the live full-team runtime, not fixtures")
        await self._import(plan)
        videos = await self._sources(plan)
        results, conversations = [], {}
        for case in plan.cases:
            request = dict(case.request)
            started = time.monotonic()
            try:
                if case.conversation_from:
                    if case.conversation_from not in conversations:
                        raise error(
                            "acceptance_invalid_response", "Follow-up conversation is unavailable"
                        )
                    request["conversation_id"] = conversations[case.conversation_from]
                response = await self._request(
                    "POST",
                    f"/api/{'chat' if case.kind == 'chat' else 'analysis'}",
                    json=request,
                    headers={"Idempotency-Key": f"acceptance05-{uuid4().hex}"},
                )
                value = response if "answer" in response else await self._result(response)
                if value.get("conversation_id"):
                    conversations[case.id] = value["conversation_id"]
                current = await self._sources(plan)
                if any(
                    (current[v]["transcript_version"], current[v].get("title"))
                    != (videos[v]["transcript_version"], videos[v].get("title"))
                    for v in videos
                ):
                    raise error("source_changed", "Sources changed during acceptance")
                report = self._review(case, value, current, plan.expected_model)
            except Exception as exc:
                report = {
                    "case_id": case.id,
                    "structural_checks_passed": False,
                    "error_code": getattr(exc, "code", "acceptance_invalid_response"),
                    "semantic_review": "not_run",
                }
            report["wall_latency_ms"] = (time.monotonic() - started) * 1000
            results.append(report)
        missing = sorted(REQUIRED_CATEGORIES - {c.category for c in plan.cases})
        return {
            "run_kind": "live_http_acceptance",
            "executed_at": datetime.now(UTC).isoformat(),
            "structural_checks_passed": all(r["structural_checks_passed"] for r in results),
            "missing_acceptance_categories": missing,
            "semantic_acceptance": "pending_human_review",
            "health": health,
            "results": results,
        }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument(
        "--live", action="store_true", help="Allow imports and paid provider requests"
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not args.live:
        parser.error("Pass --live to allow importing videos and paid generation/embedding requests")
    url = urlsplit(args.base_url)
    if (
        url.scheme not in {"http", "https"}
        or not url.hostname
        or url.username
        or url.password
        or url.query
        or url.fragment
    ):
        parser.error("Provide a server URL without credentials, query or fragment")

    async def run():
        plan = AcceptancePlan.model_validate_json(args.plan.read_text("utf-8"))
        async with httpx.AsyncClient(base_url=args.base_url, timeout=30) as client:
            return await AcceptanceRunner(client).run(plan)

    try:
        report = asyncio.run(run())
    except Exception as exc:
        report = {
            "run_kind": "live_http_acceptance",
            "structural_checks_passed": False,
            "error_code": getattr(exc, "code", "acceptance_configuration_error"),
            "semantic_acceptance": "not_run",
        }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Saved acceptance report to {args.output}; semantic review remains manual.")
    return 0 if report["structural_checks_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
