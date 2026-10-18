"""Opt-in paid Gemini smoke/evaluation on public synthetic fixtures, without DB writes."""

import argparse
import asyncio
import json
from pathlib import Path

from youtube_backend.errors import AppError

from youtube_answers.config import AnswerSettings
from youtube_answers.gemini import GeminiModel
from youtube_answers.prompts import payload


async def evaluate(output):
    config = AnswerSettings()
    model = GeminiModel(config)
    dataset = json.loads(
        (Path(__file__).parents[1] / "fixtures/evaluation.json").read_text("utf-8")
    )
    results = []
    try:
        for case in dataset["cases"]:
            try:
                result = await model.generate(
                    payload(
                        case["task"],
                        case["request"],
                        case["evidence"],
                        case.get("history", []),
                    ),
                    config.llm_timeout_seconds,
                )
                allowed = {c for n in case["evidence"] for c in n["citation_ids"]}
                cited = {c for s in result.content.statements for c in s.citation_ids}
                structural = (
                    result.content.status == case["expected_status"] and not cited - allowed
                )
                if case["task"] == "compare" and result.content.status == "answered":
                    structural = structural and all(
                        set(item["citation_ids"]) & cited for item in case["evidence"]
                    )
                results.append(
                    {
                        "case_id": case["id"],
                        "structural_checks_passed": structural,
                        "output": result.content.model_dump(),
                        "metadata": result.metadata.model_dump(),
                        "manual_review": case["review"],
                    }
                )
            except AppError as exc:
                results.append({"case_id": case["id"], "error_code": exc.code})
    finally:
        await model.close()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(
            {
                "synthetic_fixture_only": True,
                "semantic_quality_requires_manual_review": True,
                "results": results,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"Wrote {len(results)} synthetic evaluation results to {output}")
    return 0 if all(r.get("structural_checks_passed") for r in results) else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="Explicitly allow paid Gemini calls")
    parser.add_argument("--output", type=Path, default=Path("runtime/answers05/live-check.json"))
    args = parser.parse_args()
    if not args.live:
        parser.error("Pass --live to explicitly enable Gemini requests")
    try:
        return asyncio.run(evaluate(args.output))
    except AppError as exc:
        print(f"Live evaluation unavailable: {exc.code}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
