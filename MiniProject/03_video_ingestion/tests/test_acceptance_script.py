import importlib.util
import json
from pathlib import Path

import pytest
from conftest import VIDEO_A, track


@pytest.fixture
def acceptance():
    path = Path(__file__).resolve().parents[1] / "scripts" / "acceptance_check.py"
    spec = importlib.util.spec_from_file_location("ingestion_acceptance_check", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def test_acceptance_script_checks_pipeline_and_labels_fixture_vectors(
    acceptance, tmp_path, config, monkeypatch
):
    async def captions(*args):
        return track()

    monkeypatch.setattr(acceptance.SubprocessCaptions, "fetch", captions)
    # Explicitly disable metadata HTTP for the offline script regression.
    monkeypatch.setattr(acceptance, "IngestionSettings", lambda **kwargs: config)
    state = tmp_path / "acceptance"
    result = await acceptance.check(state, [VIDEO_A])
    assert result["passed"] and result["embedding_provider"] == "fixture"
    assert not result["gemini_called"] and not result["semantic_quality_evaluated"]
    assert result["authentication_enabled"]
    assert result["identity_provider"] == "fixture-google-verifier"
    assert not result["real_google_login_evaluated"]
    case = result["cases"][0]
    assert case["stage"] == "ready" and case["timestamps_match_provider"]
    assert case["duplicate_reuses_job"] and case["caption_fetches"] == 1
    assert json.loads((state / "report.json").read_text()) == result


async def test_acceptance_script_refuses_existing_data(acceptance, tmp_path):
    marker = tmp_path / "existing.txt"
    marker.write_text("keep", encoding="utf-8")
    with pytest.raises(ValueError, match="new empty"):
        await acceptance.check(tmp_path, [VIDEO_A])
    assert marker.read_text() == "keep"
    assert not (tmp_path / "app.db").exists()
