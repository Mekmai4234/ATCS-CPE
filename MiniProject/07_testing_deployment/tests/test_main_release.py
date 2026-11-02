import hashlib
from pathlib import Path

import pytest
from test_tooling import load


def inputs(tmp_path):
    gate = load("main_release")
    source = dict(mode="checkout", dirty=False, revision="a" * 40, source_sha256="b" * 64)
    manifest = gate.template(source)
    (tmp_path / "evidence.json").write_text("synthetic test evidence", encoding="utf-8")
    reference = dict(
        path="evidence.json",
        sha256=hashlib.sha256((tmp_path / "evidence.json").read_bytes()).hexdigest(),
    )
    for item in manifest["checks"].values():
        item.update(status="passed", evidence=[reference])
    ci = dict(
        headSha=source["revision"],
        status="completed",
        conclusion="success",
        jobs=[dict(name=name, status="completed", conclusion="success") for name in gate.JOBS],
    )
    return gate, source, manifest, ci


@pytest.mark.parametrize(
    "failure", [None, "stale_ci", "gold", "topic", "tamper", "escape", "public"]
)
def test_release_requires_current_source_quality_and_immutable_evidence(
    tmp_path, monkeypatch, failure
):
    monkeypatch.syspath_prepend(str(Path(__file__).parents[1] / "scripts"))
    gate, source, manifest, ci = inputs(tmp_path)
    if failure == "stale_ci":
        ci["headSha"] = "c" * 40
    if failure == "gold":
        manifest["checks"]["human_quality"]["status"] = "pending"
    if failure == "topic":
        manifest["checks"]["topic_fallback_owner_regression_http"]["status"] = "pending"
    if failure == "tamper":
        (tmp_path / "evidence.json").write_text("changed")
    if failure == "escape":
        manifest["checks"]["runbook"]["evidence"] = [dict(path="../outside", sha256="a" * 64)]
    if failure == "public":
        manifest["public_enabled"] = True
        manifest["checks"]["public_auth_tls"]["status"] = "pending"
    report = gate.check(source, manifest, ci, evidence_root=tmp_path)
    assert report["stable_main_ready"] is (failure is None)
    assert report["provider_calls"] == 0 and report["deployed"] is False
    assert report["evidence_meaning_independently_verified"] is False


def test_template_keeps_every_acceptance_pending(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).parents[1] / "scripts"))
    gate, source, _, ci = inputs(tmp_path)
    report = gate.check(source, gate.template(source), ci, evidence_root=tmp_path)
    assert "human_quality_pending" in report["blockers"]
    assert "time_fallback_owner_regression_http_pending" in report["blockers"]
    assert not report["stable_main_ready"]
