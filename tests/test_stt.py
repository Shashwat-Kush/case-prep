"""STT client + router STT arm (T-051). Mocked transport, no network. The Degrade
row (04 §5) means a failed transcription returns ok=False, never raises."""

from types import SimpleNamespace

import httpx

from app.config import SttConfig
from app.providers.router import Router
from app.providers.stt_client import SttClient, Transcription

STT = SttConfig(base_url="http://stt/v1", model="whisper-large-v3", api_key_env="K")


def _clock():
    t = {"v": 0.0}

    def now():
        t["v"] += 0.05
        return t["v"]

    return now


def _client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_transcribe_happy_path_returns_text_and_latency(monkeypatch):
    monkeypatch.setenv("K", "secret")
    seen = {}

    def handler(request):
        seen["auth"] = request.headers.get("authorization")
        seen["url"] = str(request.url)
        return httpx.Response(200, json={"text": "  revenue is falling  "})

    stt = SttClient(STT, client=_client(handler), now=_clock())
    r = stt.transcribe(b"audio-bytes")
    assert r.ok and r.text == "revenue is falling"
    assert r.latency_ms > 0
    assert seen["auth"] == "Bearer secret"
    assert seen["url"].endswith("/audio/transcriptions")


def test_transcribe_http_error_degrades_without_raising():
    stt = SttClient(STT, client=_client(lambda req: httpx.Response(500, json={"e": 1})))
    r = stt.transcribe(b"audio")
    assert r.ok is False and r.text is None and r.error
    assert r.latency_ms >= 0  # latency recorded even on failure


def test_transcribe_connection_error_degrades():
    def boom(request):
        raise httpx.ConnectError("refused", request=request)

    stt = SttClient(STT, client=_client(boom))
    r = stt.transcribe(b"audio")
    assert r.ok is False and r.text is None


def _router(*, offline=False, stt_result=None):
    calls = {"n": 0}

    class FakeStt:
        def transcribe(self, audio, **kw):
            calls["n"] += 1
            return stt_result

    cfg = SimpleNamespace(providers=[SimpleNamespace(api_key_env="K")], stt=STT)
    router = Router(cfg, stt_factory=lambda _cfg: FakeStt())
    router._offline = offline
    return router, calls


def test_router_transcribe_delegates_to_stt_client():
    ok = Transcription(True, "hi", 5.0)
    router, calls = _router(stt_result=ok)
    assert router.transcribe(b"a") is ok and calls["n"] == 1


def test_router_offline_skips_cloud_stt_without_calling_it():
    router, calls = _router(offline=True, stt_result=Transcription(True, "hi", 5.0))
    r = router.transcribe(b"a")
    assert r.ok is False and calls["n"] == 0  # network never touched offline
