import importlib.util
from pathlib import Path


def script():
    spec = importlib.util.spec_from_file_location(
        "local_preflight", Path(__file__).parents[1] / "scripts" / "local_preflight.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_hardware_and_installed_model_do_not_attest_quality_or_capacity():
    result = script().assess(
        memory_bytes=16 * 1024**3,
        free_disk_bytes=20 * 1024**3,
        models=[{"name": "tiny", "digest": "a" * 64}],
        required_models={"tiny": "a" * 64},
    )
    assert result["host_minimum_probe_ready"] and result["pinned_models_installed"]
    assert result["human_gold"] == "pending"
    for key in ("semantic_acceptance", "whole_web_local_ready", "capacity_verified"):
        assert result[key] is False
    assert result["provider_calls"] == 0


def test_wrong_digest_and_low_resources_keep_gate_closed():
    result = script().assess(
        memory_bytes=1024,
        free_disk_bytes=1024,
        models=[{"name": "tiny", "digest": "b" * 64}],
        required_models={"tiny": "a" * 64},
    )
    assert not result["host_minimum_probe_ready"]
    assert not result["pinned_models_installed"]
