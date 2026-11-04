import json
import sys

import pytest
from conftest import VIDEO_A, track
from pydantic import ValidationError
from requests import Response, Session
from youtube_transcript_api.proxies import GenericProxyConfig, WebshareProxyConfig

from youtube_ingestion.captions import SubprocessCaptions
from youtube_ingestion.config import IngestionSettings
from youtube_ingestion.fetch_worker import WEBSHARE_RETRIES_WHEN_BLOCKED, fetch, proxy_config
from youtube_ingestion.service import IngestionService

PROXY = "http://user:SECRET@proxy.example:8080"


def settings(**values):
    return IngestionSettings(_env_file=None, **values)


def test_no_proxy_by_default(monkeypatch):
    for name in ("YOUTUBE_PROXY_URL", "YOUTUBE_WEBSHARE_USERNAME", "YOUTUBE_WEBSHARE_PASSWORD"):
        monkeypatch.delenv(name, raising=False)
    assert settings().caption_proxy is None
    assert proxy_config(None) is None


def test_generic_and_webshare_settings():
    assert settings(youtube_proxy_url=PROXY).caption_proxy == {"kind": "generic", "url": PROXY}
    assert settings(youtube_webshare_username="u", youtube_webshare_password="p").caption_proxy == {
        "kind": "webshare",
        "username": "u",
        "password": "p",
    }


@pytest.mark.parametrize(
    "values",
    [
        dict(youtube_proxy_url="socks5://proxy.example:1080"),
        dict(youtube_proxy_url="proxy.example:8080"),
        dict(youtube_webshare_username="u"),
        dict(youtube_webshare_password="SECRET"),
        dict(youtube_proxy_url=PROXY, youtube_webshare_username="u", youtube_webshare_password="p"),
    ],
)
def test_invalid_proxy_settings_rejected_without_echoing_secret(values):
    with pytest.raises(ValidationError) as error:
        settings(**values)
    assert "SECRET" not in str(error.value)


def test_proxy_config_kinds():
    generic = proxy_config({"kind": "generic", "url": PROXY})
    assert isinstance(generic, GenericProxyConfig)
    assert generic.to_requests_dict() == {"http": PROXY, "https": PROXY}
    webshare = proxy_config({"kind": "webshare", "username": "u", "password": "p"})
    assert isinstance(webshare, WebshareProxyConfig)
    assert webshare.retries_when_blocked == WEBSHARE_RETRIES_WHEN_BLOCKED
    with pytest.raises(ValueError):
        proxy_config({"kind": "unknown"})


def test_sdk_requests_go_through_generic_proxy(monkeypatch):
    seen = []

    def send(session, request, **kwargs):
        seen.append(kwargs.get("proxies"))
        response = Response()
        response.status_code, response.encoding = 200, "utf-8"
        if request.method == "POST":
            response._content = json.dumps(
                {
                    "playabilityStatus": {"status": "OK"},
                    "captions": {
                        "playerCaptionsTracklistRenderer": {
                            "captionTracks": [
                                {
                                    "baseUrl": "https://www.youtube.com/api/timedtext?v=" + VIDEO_A,
                                    "name": {"runs": [{"text": "English"}]},
                                    "languageCode": "en",
                                }
                            ]
                        }
                    },
                }
            ).encode()
        elif "/api/timedtext" in request.url:
            response._content = b'<transcript><text start="0" dur="1">hi</text></transcript>'
        else:
            response._content = b'<html>"INNERTUBE_API_KEY":"TEST_KEY"</html>'
        return response

    monkeypatch.setattr(Session, "send", send)
    response = fetch(VIDEO_A, ["en"], 2, {"kind": "generic", "url": PROXY})
    assert response["ok"] and len(seen) == 3
    assert all(proxies["https"] == PROXY for proxies in seen)


async def test_proxy_travels_over_stdin_not_environment(monkeypatch):
    environments = []
    original = __import__("asyncio").create_subprocess_exec
    ok = json.dumps({"ok": True, "track": track()})
    code = (
        "import json, sys\n"
        "request = json.loads(sys.stdin.readline())\n"
        f"assert request['proxy'] == {{'kind': 'generic', 'url': {PROXY!r}}}\n"
        f"print({ok!r})\n"
    )

    async def create(*args, **kwargs):
        environments.append(kwargs.get("env", {}))
        assert not any("SECRET" in str(arg) for arg in args)
        return await original(sys.executable, "-c", code, **kwargs)

    monkeypatch.setattr("asyncio.create_subprocess_exec", create)
    captions = SubprocessCaptions(proxy={"kind": "generic", "url": PROXY})
    assert (await captions.fetch(VIDEO_A, ["th"], 5))["language"] == "th"
    assert not any("SECRET" in value for value in environments[0].values())
    await captions.close()


async def test_service_wires_proxy_from_settings():
    service = IngestionService(settings(youtube_proxy_url=PROXY), metadata=object())
    assert service.captions.proxy == {"kind": "generic", "url": PROXY}
    await service.captions.close()
