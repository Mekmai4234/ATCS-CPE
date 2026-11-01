import hashlib
from types import SimpleNamespace

import pytest
from pydantic import SecretStr
from test_tooling import load


@pytest.mark.parametrize(
    "failure", [None, "trial_scope", "ledger_scope", "credential", "role", "revoked"]
)
async def test_trial_embedding_never_dispatches_outside_both_lease_scopes(monkeypatch, failure):
    from pathlib import Path

    monkeypatch.syspath_prepend(str(Path(__file__).parents[1] / "scripts"))
    probe = load("trial_embedding")
    video = "B-zaXo-skGo"
    trial_row = {"kind": "import", "video_id": "foreign" if failure == "trial_scope" else video}
    ledger_row = {
        "payload": {"sources": [{"video_id": "foreign" if failure == "ledger_scope" else video}]}
    }
    sent = []

    def check():
        if failure == "revoked":
            raise probe.AppError("permission_revoked", "Fixture revoked", 403)

    trial = SimpleNamespace(
        check=check,
        context=SimpleNamespace(
            repository=SimpleNamespace(check_execution=lambda *args: trial_row),
            job_id="trial",
            lease_token="lease",
        ),
    )

    async def gemini_call(callback, **kwargs):
        sent.append(kwargs)
        return await callback()

    ledger = SimpleNamespace(
        check=lambda: None,
        repository=SimpleNamespace(check_execution=lambda *args: ledger_row),
        job_id="audit",
        lease_token="lease",
        settings=SimpleNamespace(gemini_api_key=SecretStr("fixture-key")),
        gemini_call=gemini_call,
    )
    execution = probe.LedgerExecution(trial, ledger, video, lambda: None)

    async def callback():
        return "fixture-vector"

    request = {
        "endpoint": "embedContent",
        "role": "agent" if failure == "role" else "embedding",
        "credential_sha256": "invalid"
        if failure == "credential"
        else hashlib.sha256(b"fixture-key").hexdigest(),
    }
    if failure:
        with pytest.raises(probe.AppError):
            await execution.gemini_call(callback, **request)
        assert sent == []
    else:
        assert await execution.gemini_call(callback, **request) == "fixture-vector"
        assert len(sent) == 1 and "credential_sha256" not in sent[0]
