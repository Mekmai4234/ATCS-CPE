"""Strict feature contract gate: absent/unmerged capabilities FAIL, never skip green."""

import importlib
from types import SimpleNamespace

import pytest
from pydantic import SecretStr, ValidationError

pytestmark = pytest.mark.free_tier_contract


def contract(name):
    try:
        return importlib.import_module(name)
    except ImportError:
        pytest.fail(f"BLOCKED: actual source lacks {name}; no pinned fallback", pytrace=False)


def test_legacy_source_does_not_change_when_new_defaults_are_added():
    from youtube_backend.schemas import Source

    old_serialized = dict(video_id="NoCaption01", generation=1, transcript_version="a" * 64)
    assert Source.model_validate(old_serialized).model_dump() == old_serialized


@pytest.mark.parametrize("kind", ["ocr", "visual"])
def test_v2_snapshot_roundtrip_needs_no_fake_transcript(kind):
    v2 = contract("youtube_backend.evidence_v2")
    raw = dict(video_id="NoCaption01", generation=1, kind=kind, evidence_version="b" * 64)
    snapshot = v2.SourceSnapshotV2.model_validate(raw)
    assert snapshot.contract_version == 2
    assert "transcript_version" not in snapshot.model_dump()
    assert v2.SourceSnapshotV2.model_validate_json(snapshot.model_dump_json()) == snapshot
    # Existing serialized snapshots may omit default contract_version; comparison
    # must parse both sides, not compare the new raw JSON digest to the old digest.
    assert v2.SourceSnapshotV2.model_validate(raw) == snapshot


def test_visual_citation_is_frame_bound_and_cannot_escape_authorized_asset_route():
    v2 = contract("youtube_backend.evidence_v2")
    raw = dict(
        source=dict(video_id="NoCaption01", generation=1, kind="ocr", evidence_version="a" * 64),
        frame_id="b" * 64,
        asset_id="c" * 64,
        start_seconds=0.5,
        text="[fixture OCR] TEA",
        asset_url="/api/media/assets/" + "c" * 64,
    )
    assert v2.VisualCitationV2.model_validate(raw).start_seconds == 0.5
    for change in ({"asset_url": "https://example.invalid/private.png"}, {"start_seconds": -1}):
        with pytest.raises(ValidationError):
            v2.VisualCitationV2.model_validate(dict(raw, **change))


def test_visual_observation_requires_actual_broker_provenance():
    v2 = contract("youtube_backend.evidence_v2")
    with pytest.raises(ValidationError):
        v2.MediaEnrichment(
            sampling_version="fixture",
            ocr_version="fixture",
            prompt_version="fixture",
            source_sha256="a" * 64,
            duration_seconds=2,
            frames=[
                dict(
                    timestamp_seconds=0.5,
                    content=b"fixture-png",
                    mime="image/png",
                    visual_text="invented",
                )
            ],
        )


def test_05_real_consumer_and_02_broker_have_a_working_authorization_handoff():
    backend = contract("youtube_backend.quota")
    consumer = contract("youtube_answers.quota")
    settings = SimpleNamespace(gemini_api_key=SecretStr("synthetic-not-a-real-key"))
    broker = backend.QuotaBroker(SimpleNamespace(settings=settings))
    try:
        consumer.verified_grant(broker, settings, "fixture-not-approved", "chat")
    except AttributeError:
        pytest.fail(
            "BLOCKED: 05 authorize/async-reserve does not match "
            "02 access/execution-bound gemini_call",
            pytrace=False,
        )
    except Exception as error:
        # The unapproved key/model must fail CLOSED with the consumer's documented
        # quota error, not leak an interface exception or return a successful grant.
        assert getattr(error, "code", None) in {"quota_pending", "free_tier_unverified"}
    else:
        pytest.fail("An unverified fixture key/model unexpectedly received a grant")
