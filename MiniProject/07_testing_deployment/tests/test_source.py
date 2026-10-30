import json
import subprocess
import sys

import pytest
from test_tooling import load


def test_default_policy_fails_if_pinned_source_selection_returns():
    source = load("source")
    source.validate_checkout_workflow("uv run python scripts/check.py")
    with pytest.raises(ValueError, match="cannot replace source"):
        source.validate_checkout_workflow("uv run python scripts/candidate.py --manifest old.json")


def test_source_changed_after_pin_is_tested_and_old_provenance_rejected(tmp_path):
    source = load("source")
    root = tmp_path / "MiniProject"
    app = root / "01_web_app"
    app.mkdir(parents=True)
    marker = app / "marker.py"
    marker.write_text("print('OLD PIN PASSES')\n")

    def git(*args):
        return subprocess.run(["git", "-C", str(tmp_path), *args], check=True, capture_output=True)

    git("init")
    git("config", "user.email", "fixture@example.invalid")
    git("config", "user.name", "Fixture")
    git("add", ".")
    git("commit", "-m", "old pin")
    old_pin = source.capture(root)
    marker.write_text("raise RuntimeError('NEW CHECKOUT MUST FAIL')\n")
    git("add", ".")
    git("commit", "-m", "change after pin")
    current = source.capture(root)
    assert current["revision"] != old_pin["revision"]
    assert current["source_sha256"] != old_pin["source_sha256"]
    result = subprocess.run([sys.executable, str(marker)], capture_output=True)
    assert result.returncode != 0 and b"NEW CHECKOUT MUST FAIL" in result.stderr
    with pytest.raises(ValueError, match="provenance changed"):
        source.verify(old_pin, root)
    assert source.verify(current, root)["mode"] == "checkout"
    # A mutation after the recorded run starts must also be rejected, even without a commit.
    marker.write_text("print('mutated during run')\n")
    with pytest.raises(ValueError):
        source.verify(current, root)


def test_source_record_excludes_ignored_runtime_and_never_reads_pin(tmp_path):
    source = load("source")
    root = tmp_path / "MiniProject"
    module = root / "07_testing_deployment"
    module.mkdir(parents=True)
    (module / "marker.txt").write_text("checkout")
    (module / ".gitignore").write_text("runtime/\n")
    subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(tmp_path), "add", "."], check=True)
    for key, value in (("user.email", "fixture@example.invalid"), ("user.name", "Fixture")):
        subprocess.run(["git", "-C", str(tmp_path), "config", key, value], check=True)
    subprocess.run(
        ["git", "-C", str(tmp_path), "commit", "-m", "fixture"], check=True, capture_output=True
    )
    (module / "runtime").mkdir()
    (module / "runtime/report.json").write_text(json.dumps({"secret": "not-source"}))
    (root / "candidate.json").write_text("invalid stale pin")
    record = source.capture(root)
    assert len(record["files"]) == 2
    assert all("runtime" not in path for path in record["files"])
