import importlib.util
from pathlib import Path

import pytest


def script():
    spec = importlib.util.spec_from_file_location(
        "service_status", Path(__file__).parents[1] / "scripts" / "service_status.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_web_up_does_not_claim_worker_provider_or_public_readiness():
    status = script().readiness(True, True, False)
    assert status["web_reachable"] is True and status["api_reachable"] is True
    assert status["local_services_ready"] is False
    ready = script().readiness(True, True, True)
    assert ready["local_services_ready"] is True
    assert ready["provider_verified"] is False and ready["semantic_acceptance"] is False
    assert ready["human_gold"] == "pending" and ready["public_deployment_ready"] is False


@pytest.mark.parametrize(
    "url",
    [
        "http://remote.invalid",
        "https://localhost",
        "http://user@localhost",
        "http://localhost/path",
        "http://localhost?key=secret",
    ],
)
def test_probe_rejects_remote_or_credential_bearing_targets(url):
    with pytest.raises(ValueError):
        script().loopback(url)
