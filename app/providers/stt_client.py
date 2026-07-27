"""Speech-to-text client (Groq Whisper; 02_ARCHITECTURE §3, T-051).

OpenAI-compatible /audio/transcriptions: POST multipart {file, model}. Per the
04 §5 Degrade row, an STT failure never raises into the session — transcribe()
returns a result whose `ok` is False so the caller falls back to typed input.
Latency is recorded on every attempt (success or degrade) and logged.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass

import httpx

from app.config import SttConfig

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Transcription:
    ok: bool
    text: str | None
    latency_ms: float
    error: str | None = None


class SttClient:
    def __init__(
        self,
        stt: SttConfig,
        *,
        timeout_s: float = 30.0,
        client: httpx.Client | None = None,
        now: Callable[[], float] = time.monotonic,
    ):
        self._stt = stt
        self._client = client or httpx.Client(timeout=timeout_s)
        self._now = now

    def transcribe(
        self, audio: bytes, *, filename: str = "audio.webm"
    ) -> Transcription:
        start = self._now()
        headers = {}
        key = self._stt.api_key()
        if key:
            headers["Authorization"] = f"Bearer {key}"
        url = f"{self._stt.base_url}/audio/transcriptions"
        try:
            resp = self._client.post(
                url,
                headers=headers,
                data={"model": self._stt.model},
                files={"file": (filename, audio, "application/octet-stream")},
            )
            resp.raise_for_status()
            text = (resp.json().get("text") or "").strip()
        except (httpx.HTTPError, ValueError, KeyError) as exc:
            ms = (self._now() - start) * 1000
            log.warning("STT failed after %.0fms: %s — degrade to typed", ms, exc)
            return Transcription(False, None, ms, str(exc))
        ms = (self._now() - start) * 1000
        log.info("STT ok in %.0fms (%d chars)", ms, len(text))
        return Transcription(True, text, ms)
