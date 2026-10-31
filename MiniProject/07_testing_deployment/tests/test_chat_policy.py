"""A versioned synthetic corpus; passing these rules is not semantic acceptance."""

import json
from pathlib import Path

import pytest
from youtube_backend.moderation import POLICY_VERSION, classify, normalize

CORPUS = json.loads(
    (Path(__file__).parents[1] / "fixtures/chat_policy_th_en.json").read_text(encoding="utf-8")
)


@pytest.mark.parametrize("case", CORPUS["cases"], ids=lambda case: case["kind"])
def test_chat_policy_regression(case):
    assert POLICY_VERSION == CORPUS["policy_version"]
    assert classify(case["text"])[0] == case["decision"]
    assert normalize("ป่า ป้า ป๊า ป๋า") == "ป่า ป้า ป๊า ป๋า"
