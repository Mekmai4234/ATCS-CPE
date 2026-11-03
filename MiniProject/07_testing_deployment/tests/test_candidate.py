import io
import json
import sys
import zipfile

import pytest
from test_tooling import load

MODULES = [
    "01_web_app",
    "02_api_backend",
    "03_video_ingestion",
    "04_rag_knowledge",
    "05_ai_answers_analysis",
    "06_research_learning_agent",
]
SHA = "a" * 40


def setup(tmp_path, monkeypatch):
    candidate = load("candidate")
    for name in MODULES:
        (tmp_path / name).mkdir()
    module = tmp_path / "07_testing_deployment"
    module.mkdir()
    (module / "uv.lock").write_text("committed-lock")
    monkeypatch.setattr(candidate, "ROOT", tmp_path)
    monkeypatch.setattr(candidate, "MODULE", module)
    manifest = module / "integration.json"
    manifest.write_text(json.dumps(dict(base=SHA, modules={m: SHA for m in MODULES})))

    def git(*args):
        if args[0] == "archive":
            buffer = io.BytesIO()
            with zipfile.ZipFile(buffer, "w") as files:
                files.writestr(args[-1] + "/pyproject.toml", "fixture")
            return buffer.getvalue()
        if args[0] == "status":
            return b""
        return SHA.encode()

    monkeypatch.setattr(candidate, "git", git)
    monkeypatch.setattr(sys, "argv", ["candidate", "--manifest", str(manifest)])
    return candidate, module, manifest


def test_candidate_keeps_committed_lock_pins_and_excludes_secrets(tmp_path, monkeypatch):
    candidate, module, _ = setup(tmp_path, monkeypatch)
    (module / ".env").write_text("SECRET")
    (module / ".env.production").write_text("SECRET")
    (module / ".venv").mkdir()
    (module / ".venv/token").write_text("SECRET")
    candidate.main()
    output = next((module / "runtime").glob("candidate-*"))
    copied = output / module.name
    assert (copied / "uv.lock").read_text() == "committed-lock"
    assert not any((copied / name).exists() for name in (".env", ".env.production", ".venv"))
    record = json.loads((output / "candidate.json").read_text())
    assert set(record["modules"]) == set(MODULES)
    assert len(record["tooling_sha256"]) == len(record["lock_sha256"]) == 64


@pytest.mark.parametrize("defect", ["mutable_ref", "missing_module"])
def test_manifest_cannot_claim_exact_candidate_with_incomplete_or_mutable_pins(
    tmp_path, monkeypatch, defect
):
    candidate, module, manifest = setup(tmp_path, monkeypatch)
    record = json.loads(manifest.read_text())
    if defect == "mutable_ref":
        record["modules"][MODULES[0]] = "origin/moving"
    else:
        record["modules"].pop(MODULES[0])
    manifest.write_text(json.dumps(record))
    with pytest.raises(SystemExit) as error:
        candidate.main()
    assert error.value.code == 2
    assert not (module / "runtime").exists()
