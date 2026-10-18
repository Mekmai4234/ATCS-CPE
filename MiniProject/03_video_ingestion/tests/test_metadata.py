import asyncio

import httpx
import pytest
from conftest import VIDEO_A
from youtube_backend.errors import AppError

from youtube_ingestion.config import IngestionSettings
from youtube_ingestion.metadata import YouTubeMetadata


async def test_oembed_has_no_guessed_date_or_channel_id():
    def handle(request):
        assert request.url.host == "www.youtube.com"
        assert request.url.params["url"] == f"https://www.youtube.com/watch?v={VIDEO_A}"
        return httpx.Response(
            200,
            json={
                "title": "Thai lesson",
                "author_name": "Channel",
                "author_url": "https://www.youtube.com/@handle",
                "thumbnail_url": "https://i.ytimg.com/vi/" + VIDEO_A + "/hqdefault.jpg",
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        adapter = YouTubeMetadata(
            IngestionSettings(_env_file=None, youtube_api_key=""), client=client
        )
        result = await adapter.fetch(VIDEO_A, 1)
        assert result.title == "Thai lesson" and result.channel_title == "Channel"
        assert result.channel_id is None and result.published_at is None
        await adapter.close()
        assert not client.is_closed


async def test_data_api_metadata_exact_video_and_key_not_in_url(caplog):
    def handle(request):
        assert request.url.host == "www.googleapis.com"
        assert request.headers["X-Goog-Api-Key"] == "TEST_SECRET"
        assert "TEST_SECRET" not in str(request.url)
        assert request.url.params["id"] == VIDEO_A
        return httpx.Response(
            200,
            json={
                "items": [
                    {
                        "id": VIDEO_A,
                        "snippet": {
                            "title": "Lesson",
                            "channelId": "channel-a",
                            "channelTitle": "Channel",
                            "publishedAt": "2026-01-02T01:00:00Z",
                            "thumbnails": {"high": {"url": "https://i.ytimg.com/image.jpg"}},
                        },
                    }
                ]
            },
        )

    config = IngestionSettings(_env_file=None, youtube_api_key="TEST_SECRET")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        result = await YouTubeMetadata(config, client=client).fetch(VIDEO_A, 1)
        assert result.published_at.isoformat() == "2026-01-02"
        assert result.channel_id == "channel-a"
        assert "TEST_SECRET" not in caplog.text


@pytest.mark.parametrize(
    "payload",
    [
        {"items": []},
        {"items": [{"id": "wrong"}]},
        {"items": [{"id": VIDEO_A, "snippet": {"publishedAt": "not-a-date"}}]},
        {"items": [{"id": VIDEO_A, "snippet": {"publishedAt": "2026-01-01"}}]},
    ],
)
async def test_invalid_data_api_metadata_is_classified(payload):
    config = IngestionSettings(
        _env_file=None, metadata_provider="youtube_api", youtube_api_key="SECRET"
    )
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload))
    ) as client:
        with pytest.raises(AppError) as error:
            await YouTubeMetadata(config, client=client).fetch(VIDEO_A, 1)
        assert error.value.code == "metadata_unavailable"
        assert "SECRET" not in error.value.message


@pytest.mark.parametrize("status", [302, 403, 404, 429, 500])
async def test_failed_metadata_never_follows_redirects(status):
    calls = []

    def handle(request):
        calls.append(str(request.url))
        return httpx.Response(status, headers={"Location": "https://evil.example/"})

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handle), follow_redirects=True
    ) as client:
        adapter = YouTubeMetadata(
            IngestionSettings(_env_file=None, metadata_provider="oembed"), client=client
        )
        with pytest.raises(AppError):
            await adapter.fetch(VIDEO_A, 1)
    assert len(calls) == 1


async def test_transport_error_redacted_and_no_hidden_retries():
    calls = []

    def handle(request):
        calls.append(request)
        raise httpx.ConnectError("SECRET", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        adapter = YouTubeMetadata(IngestionSettings(_env_file=None), client=client)
        with pytest.raises(AppError) as error:
            await adapter.fetch(VIDEO_A, 1)
        assert "SECRET" not in error.value.message and len(calls) == 1


async def test_none_provider_never_calls_network_and_owned_client_closes():
    adapter = YouTubeMetadata(IngestionSettings(_env_file=None, metadata_provider="none"))
    assert (await adapter.fetch(VIDEO_A, 1)).title is None
    await adapter.close()
    assert adapter.client.is_closed


async def test_metadata_propagates_cancellation():
    async def handle(request):
        await asyncio.sleep(5)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        adapter = YouTubeMetadata(IngestionSettings(_env_file=None), client=client)
        task = asyncio.create_task(adapter.fetch(VIDEO_A, 1))
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
