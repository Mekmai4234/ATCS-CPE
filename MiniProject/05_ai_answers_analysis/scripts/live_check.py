"""Opt-in Free Tier Gemini evaluation; a trusted shared broker is still required."""

import argparse
import asyncio
import json
from pathlib import Path

from youtube_backend.errors import AppError

from youtube_answers.config import AnswerSettings
from youtube_answers.gemini import GeminiModel
from youtube_answers.prompts import payload


async def evaluate(output, env_file=None, *, broker=None):
    config = AnswerSettings(_env_file=env_file) if env_file else AnswerSettings(_env_file=None)
    model = GeminiModel(config, broker=broker)
    dataset = json.loads(
        (Path(__file__).parents[1] / "fixtures/evaluation.json").read_text("utf-8")
    )
    results, catalog = [], None
    try:
        try:
            catalog = await model.check_access(config.llm_timeout_seconds)
        except AppError as exc:
            # An alias may generate successfully even when catalog lookup is unavailable.
            catalog = {"error_code": exc.code, "generation_verified": False}
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
                "run_kind": "live_synthetic_generation",
                "model_catalog_check": catalog,
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
    parser.add_argument(
        "--live", action="store_true", help="Opt in; verified Free Tier broker required"
    )
    parser.add_argument("--output", type=Path, default=Path("runtime/answers05/live-check.json"))
    parser.add_argument("--env-file", type=Path, help="Only this env file plus process variables")
    args = parser.parse_args()
    if not args.live:
        parser.error("Pass --live to explicitly enable Gemini requests")
    if args.env_file and not args.env_file.is_file():
        parser.error("The selected env file does not exist")
    try:
        return asyncio.run(evaluate(args.output, args.env_file))
    except AppError as exc:
        print(f"Live evaluation unavailable: {exc.code}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
