"""Read-only host inventory and optional Ollama health check; no prompts or downloads."""

import argparse
import json
import platform
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import httpx
from youtube_backend.local_inference import private_url


def assess(*, memory_bytes, free_disk_bytes, models, required_models):
    installed = {item.get("name"): item.get("digest") for item in models if isinstance(item, dict)}
    return {
        "host_minimum_probe_ready": memory_bytes >= 8 * 1024**3 and free_disk_bytes >= 10 * 1024**3,
        "pinned_models_installed": bool(required_models)
        and all(installed.get(name) == digest for name, digest in required_models.items()),
        "semantic_acceptance": False,
        "human_gold": "pending",
        "whole_web_local_ready": False,
        "capacity_verified": False,
        "provider_calls": 0,
    }


def inventory(disk):
    memory = 0
    gpu = []
    if platform.system() == "Windows":
        command = "[string](Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory"
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", command],
            capture_output=True,
            text=True,
            timeout=15,
            check=True,
        )
        memory = int(result.stdout.strip())
    else:
        path = Path("/proc/meminfo")
        if path.is_file():
            line = next(
                line for line in path.read_text().splitlines() if line.startswith("MemTotal:")
            )
            memory = int(line.split()[1]) * 1024
    if shutil.which("nvidia-smi"):
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if result.returncode == 0:
            gpu = result.stdout.strip().splitlines()
    return {
        "platform": platform.platform(),
        "memory_bytes": memory,
        "free_disk_bytes": shutil.disk_usage(disk).free,
        "gpu": gpu,
    }


async def probe(url):
    try:
        async with httpx.AsyncClient(
            base_url=private_url(url), trust_env=False, follow_redirects=False, timeout=3
        ) as client:
            async with client.stream("GET", "/api/tags") as response:
                response.raise_for_status()
                data = bytearray()
                async for part in response.aiter_bytes():
                    data.extend(part)
                    if len(data) > 1_000_000:
                        raise ValueError("Oversized model list")
                models = json.loads(data).get("models")
                if not isinstance(models, list):
                    raise ValueError("Invalid model list")
                return {
                    "status": "reachable",
                    "models": [
                        {"name": item.get("name"), "digest": item.get("digest")}
                        for item in models
                        if isinstance(item, dict)
                    ],
                }
    except (httpx.HTTPError, ValueError):
        return {"status": "unavailable", "models": []}


def main():
    import asyncio

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--disk", type=Path, default=Path.cwd())
    parser.add_argument("--probe", action="store_true")
    parser.add_argument("--url", default="http://127.0.0.1:11434")
    parser.add_argument("--models", type=Path, help="Reviewed JSON mapping of model name to digest")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    hardware = inventory(args.disk)
    health = asyncio.run(probe(args.url)) if args.probe else {"status": "not_run", "models": []}
    required = json.loads(args.models.read_text(encoding="utf-8")) if args.models else {}
    report = {
        "observed_at": datetime.now(UTC).isoformat(),
        "hardware": hardware,
        "health": health,
        "acceptance": assess(
            memory_bytes=hardware["memory_bytes"],
            free_disk_bytes=hardware["free_disk_bytes"],
            models=health["models"],
            required_models=required,
        ),
        "model_downloaded": False,
        "billing_changed": False,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
