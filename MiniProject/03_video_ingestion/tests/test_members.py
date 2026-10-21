from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest
from conftest import VIDEO_A, VIDEO_B
from member_backend_double import MemberBackendDouble
from youtube_backend.errors import AppError
from youtube_backend.repository import Repository

from youtube_ingestion.member_adapters import create_member_adapters
from youtube_ingestion.members import MemberIngestion, MemberSettings


@pytest.fixture
def members():
    backend = MemberBackendDouble()
    return backend, MemberIngestion(backend, MemberSettings(_env_file=None))


def add(service, context, video_id=VIDEO_A):
    return service.add({"urls": [f"https://youtu.be/{video_id}"]}, context).items[0]


def test_two_accounts_share_source_but_never_private_job_ids(members):
    backend, service = members
    a, b = add(service, backend.a), add(service, backend.b)
    assert a.job_id != b.job_id and backend.source_jobs == 1
    backend.finish(VIDEO_A)
    assert service.job(a.job_id, backend.a).state == "completed"
    assert service.job(b.job_id, backend.b).state == "completed"
    for context, job in [(backend.a, b), (backend.b, a), (backend.admin, a)]:
        for operation in ("job", "retry", "cancel"):
            with pytest.raises(AppError) as error:
                service.job(job.job_id, context, operation=operation)
            assert error.value.status_code == 404


def test_ready_source_admission_does_not_create_new_shared_work(members):
    backend, service = members
    add(service, backend.a)
    backend.finish(VIDEO_A)
    result = add(service, backend.b)
    assert result.outcome == "added" and result.status == "ready"
    assert backend.source_jobs == 1
    assert add(service, backend.b).job_id == result.job_id


def test_removal_does_not_remove_other_accounts_source(members):
    backend, service = members
    add(service, backend.a)
    add(service, backend.b)
    backend.finish(VIDEO_A)
    assert not service.remove(VIDEO_A, backend.a).gc_scheduled
    assert service.transcript(VIDEO_A, backend.b).segments
    with pytest.raises(AppError) as error:
        service.transcript(VIDEO_A, backend.a)
    assert error.value.status_code == 404
    assert service.remove(VIDEO_A, backend.b).gc_scheduled


def test_cancelling_a_private_job_keeps_b_shared_work_active(members):
    backend, service = members
    a, b = add(service, backend.a), add(service, backend.b)
    assert service.job(a.job_id, backend.a, operation="cancel").state == "cancelled"
    assert backend.sources[VIDEO_A]["active"]
    backend.finish(VIDEO_A)
    assert service.job(b.job_id, backend.b).stage == "ready"
    assert service.job(a.job_id, backend.a).state == "cancelled"


@pytest.mark.parametrize("injected", ["user_id", "owner_id", "role"])
def test_client_identity_fields_cannot_authorize_import(members, injected):
    backend, service = members
    with pytest.raises(AppError) as validation:
        service.add({"urls": [f"https://youtu.be/{VIDEO_A}"], injected: "admin"}, backend.a)
    assert validation.value.status_code == 422
    assert backend.source_jobs == 0
    with pytest.raises(AppError) as error:
        service.add({"urls": [f"https://youtu.be/{VIDEO_A}"]}, SimpleNamespace(user_id="member-a"))
    assert error.value.status_code == 401


def test_unauthenticated_never_sees_a_job_or_transcript(members):
    backend, service = members
    item = add(service, backend.a)
    for call in [
        lambda: add(service, None),
        lambda: service.job(item.job_id, None),
        lambda: service.transcript(VIDEO_A, None),
        lambda: service.remove(VIDEO_A, None),
    ]:
        with pytest.raises(AppError) as error:
            call()
        assert error.value.status_code == 401


def test_concurrent_cross_member_add_reuses_one_source(members):
    backend, service = members
    contexts = [backend.a, backend.b] * 10
    with ThreadPoolExecutor(max_workers=8) as pool:
        values = list(pool.map(lambda context: add(service, context), contexts))
    assert len({v.job_id for v in values}) == 2 and backend.source_jobs == 1
    assert backend.refs[VIDEO_A] == {"member-a", "member-b"}


def test_quotas_are_separate_per_member_and_duplicate_does_not_spend_twice(members):
    backend, _ = members
    service = MemberIngestion(backend, MemberSettings(_env_file=None, pending_import_limit=1))
    first = add(service, backend.a)
    assert add(service, backend.a).job_id == first.job_id
    rejected = add(service, backend.a, VIDEO_B)
    assert rejected.status == "rejected" and rejected.job_id is None
    assert rejected.error_code == "member_pending_limit"
    assert add(service, backend.b, VIDEO_B).status == "importing"
    assert backend.commands[-1][3]["running_import_limit"] == 2


def test_normalized_batch_retains_indices_and_deduplicates_source_admission(members):
    backend, service = members
    result = service.add(
        {
            "urls": [
                f"https://youtu.be/{VIDEO_A}",
                "https://evil.example",
                f"https://www.youtube.com/watch?v={VIDEO_A}",
            ]
        },
        backend.a,
    )
    assert [x.input_index for x in result.items] == [0, 1, 2]
    assert result.items[1].error_code == "invalid_youtube_url"
    assert result.items[0].job_id == result.items[2].job_id
    assert backend.commands[-1][2] == {"video_ids": [VIDEO_A]}


def test_disabled_or_legacy_backend_fails_closed():
    for backend in [None, object(), Repository(object(), object())]:
        with pytest.raises(AppError) as error:
            MemberIngestion(backend)
        assert error.value.code == "member_contract_unavailable"


async def test_member_factory_refuses_missing_02_contract_before_constructing_clients(monkeypatch):
    import youtube_ingestion.member_adapters as module

    async def must_not_start(**kwargs):
        pytest.fail("Legacy clients must not be constructed")

    monkeypatch.setattr(module, "create_adapters", must_not_start)
    with pytest.raises(AppError) as error:
        await create_member_adapters(settings=object(), repository=Repository(object(), object()))
    assert error.value.code == "member_contract_unavailable"


def test_member_limits_load_from_environment_without_changing_legacy_fields(monkeypatch):
    from youtube_ingestion.config import IngestionSettings

    monkeypatch.setenv("MEMBER_IMPORT_MAX_URLS", "3")
    monkeypatch.setenv("MEMBER_PENDING_IMPORT_LIMIT", "5")
    monkeypatch.setenv("MEMBER_RUNNING_IMPORT_LIMIT", "1")
    limits = MemberSettings(_env_file=None)
    assert limits.model_dump() == dict(
        import_max_urls=3, pending_import_limit=5, running_import_limit=1
    )
    assert "pending_import_limit" not in IngestionSettings.model_fields


def test_no_caption_and_transient_error_codes_are_preserved_on_private_jobs(members):
    backend, service = members
    item = add(service, backend.a)
    job = backend.jobs[item.job_id]
    job.update(state="completed", stage="no_transcript", error_code="no_transcript")
    result = service.job(item.job_id, backend.a)
    assert result.stage == "no_transcript" and not result.retryable
    with pytest.raises(AppError) as error:
        service.job(item.job_id, backend.a, operation="retry")
    assert error.value.code == "retry_not_allowed"
    job.update(state="failed", stage="failed", error_code="ingest_timeout", retryable=True)
    assert service.job(item.job_id, backend.a).retryable
    assert service.job(item.job_id, backend.a, operation="retry").state == "queued"


@pytest.mark.parametrize(
    "value",
    [
        [],
        [{"video_id": VIDEO_B, "job_id": "other-user-job", "outcome": "added", "status": "ready"}],
        [
            {
                "video_id": VIDEO_A,
                "job_id": "private-job",
                "outcome": "added",
                "status": "ready",
                "owner_id": "other-user",
            }
        ],
    ],
)
def test_unscoped_or_extra_backend_response_fields_are_not_exposed(members, monkeypatch, value):
    backend, service = members
    monkeypatch.setattr(backend, "execute_member", lambda *args: value)
    with pytest.raises(AppError) as error:
        add(service, backend.a)
    assert error.value.code == "member_contract_invalid_output"
    assert "other-user" not in error.value.message


def test_member_import_batch_limit_is_applied_before_admission(members):
    backend, _ = members
    service = MemberIngestion(backend, MemberSettings(_env_file=None, import_max_urls=1))
    with pytest.raises(AppError) as error:
        service.add({"urls": [f"https://youtu.be/{VIDEO_A}"] * 2}, backend.a)
    assert error.value.code == "member_import_limit" and not backend.commands


def test_source_grant_contract_requires_atomic_gc_guarantee(members):
    backend, _ = members
    backend.guarantees = backend.guarantees - {"atomic_source_fence"}
    with pytest.raises(AppError) as error:
        MemberIngestion(backend)
    assert error.value.code == "member_contract_unavailable"
