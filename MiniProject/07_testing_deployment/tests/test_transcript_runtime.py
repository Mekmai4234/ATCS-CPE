import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from test_tooling import load
from youtube_backend.full import FullSettings


@pytest.fixture(autouse=True)
def restore_launcher_environment():
    with patch.dict(os.environ):
        yield


def configuration(tmp_path):
    return FullSettings(
        _env_file=None,
        app_env="test",
        auth_enabled=False,
        database_url=f"sqlite:///{(tmp_path / 'app.db').as_posix()}",
        chroma_persist_dir=str(tmp_path / "chroma"),
    )


def test_fresh_docker_pair_initializes_before_opening_sqlite_and_replays(tmp_path, monkeypatch):
    runtime = load("transcript_runtime")
    settings = configuration(tmp_path)
    monkeypatch.setattr(runtime, "FullSettings", lambda **kwargs: settings)
    monkeypatch.setattr(sys, "argv", ["transcript_runtime", "migrate"])
    runtime.main()
    assert Path(tmp_path / "app.db").is_file()
    first = runtime.check_pair(settings)
    runtime.main()
    assert runtime.check_pair(settings) == first


def test_unbound_existing_database_is_not_silently_adopted(tmp_path, monkeypatch):
    import sqlite3

    runtime = load("transcript_runtime")
    settings = configuration(tmp_path)
    with sqlite3.connect(tmp_path / "app.db") as connection:
        connection.execute("create table private_data(value text)")
    monkeypatch.setattr(runtime, "FullSettings", lambda **kwargs: settings)
    monkeypatch.setattr(sys, "argv", ["transcript_runtime", "migrate"])
    with pytest.raises(ValueError, match="unbound"):
        runtime.main()
