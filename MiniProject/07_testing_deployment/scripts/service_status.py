"""Read-only loopback web/API/worker health; never starts services or changes config."""

import argparse
import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

import httpx


def loopback(url):
    parsed = urlsplit(url)
    if (
        parsed.scheme != "http"
        or parsed.hostname not in {"localhost", "127.0.0.1", "::1"}
        or parsed.username
        or parsed.password
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("Use an HTTP loopback origin without credentials or a path")
    return url.rstrip("/")


def readiness(web, api, worker):
    return {
        "web_reachable": web,
        "api_reachable": api,
        "worker_ready": worker,
        "local_services_ready": bool(web and api and worker),
        "provider_verified": False,
        "semantic_acceptance": False,
        "public_deployment_ready": False,
        "human_gold": "pending",
    }


async def inspect(api_url, web_url):
    api_url, web_url = loopback(api_url), loopback(web_url)
    web, api, worker = False, False, False
    health = {}
    async with httpx.AsyncClient(timeout=3, trust_env=False, follow_redirects=False) as client:
        try:
            response = await client.get(web_url)
            web = response.status_code == 200
        except httpx.HTTPError:
            pass
        try:
            response = await client.get(api_url + "/health")
            if response.status_code == 200 and len(response.content) <= 1_000_000:
                value = response.json()
                api = value.get("status") == "ok"
                worker = value.get("worker", {}).get("ready") is True
                health = {
                    key: value.get(key)
                    for key in (
                        "schema_revision",
                        "mode",
                        "authentication_required",
                        "integration_profile",
                        "synthetic_data",
                        "capabilities",
                    )
                }
        except (httpx.HTTPError, ValueError, AttributeError):
            pass
    return {
        "observed_at": datetime.now(UTC).isoformat(),
        "api": api_url,
        "web": web_url,
        "health": health,
        "readiness": readiness(web, api, worker),
        "model_calls": 0,
        "services_started": False,
        "configuration_changed": False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api", default="http://127.0.0.1:8000")
    parser.add_argument("--web", default="http://127.0.0.1:3000")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = asyncio.run(inspect(args.api, args.web))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
