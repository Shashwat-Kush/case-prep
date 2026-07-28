"""Piper text-to-speech with sentence-level streaming (02_ARCHITECTURE §3, T-053).

Piper is a local subprocess: text in on stdin, WAV out on stdout. To hit the
~0.3s start target we synthesize as soon as the FIRST complete sentence is
available (`drain_sentences` peels finished sentences off the growing reply while
the LLM is still streaming the rest). Any failure — Piper missing, non-zero exit,
timeout — returns None so the turn degrades to text only and never blocks (04 §5).
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import tempfile
from collections.abc import Callable, Iterable, Iterator
from pathlib import Path

log = logging.getLogger(__name__)

# A sentence ends on ., !, or ? (repeated), optional closing quote/bracket, then
# whitespace. Requiring trailing whitespace keeps decimals ("3.5") and mid-word
# dots intact while streaming; the final remainder is flushed at end-of-stream.
_SENT = re.compile(r'[.!?]+["\')\]]*\s+')


def drain_sentences(buf: str) -> tuple[list[str], str]:
    """Peel every COMPLETE sentence off the buffer, returning them plus the
    still-incomplete remainder (kept for the next token)."""
    out: list[str] = []
    while (m := _SENT.search(buf)) is not None:
        out.append(buf[: m.end()].strip())
        buf = buf[m.end() :]
    return out, buf


def split_sentences(text: str) -> list[str]:
    sents, rem = drain_sentences(text)
    if rem.strip():
        sents.append(rem.strip())
    return sents


def iter_sentences(tokens: Iterable[str]) -> Iterator[str]:
    """Yield each sentence of a token stream as its boundary is crossed, then the
    trailing remainder — so synthesis can start on the first complete sentence."""
    buf = ""
    for tok in tokens:
        buf += tok
        sents, buf = drain_sentences(buf)
        yield from sents
    if buf.strip():
        yield buf.strip()


class PiperTTS:
    def __init__(
        self,
        voice: str,
        *,
        piper: str | None = None,
        timeout_s: float = 10.0,
        run: Callable[..., subprocess.CompletedProcess] = subprocess.run,
    ):
        # `piper` may be an explicit path; otherwise look it up once. Absent -> the
        # synth degrades to None on every call (text only), never raising.
        self._piper = piper if piper is not None else shutil.which("piper")
        self._model = voice if voice.endswith(".onnx") else f"{voice}.onnx"
        self._timeout = timeout_s
        self._run = run

    def synthesize(self, text: str) -> bytes | None:
        text = text.strip()
        if not text or not self._piper:
            return None
        try:
            proc = self._run(
                [self._piper, "-m", self._model, "-f", "-"],
                input=text.encode(),
                capture_output=True,
                timeout=self._timeout,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            log.warning("Piper synthesis failed: %s — text only", exc)
            return None
        if proc.returncode != 0 or not proc.stdout:
            log.warning("Piper exited %s — text only", proc.returncode)
            return None
        return proc.stdout


class SystemTTS:
    """macOS `say` fallback, used when Piper is not installed. `say` writes a WAV
    to a file (not stdout), so we synthesize to a temp file and return its bytes.
    Same contract as PiperTTS.synthesize: None on any failure -> text only."""

    def __init__(
        self,
        *,
        say: str | None = None,
        timeout_s: float = 10.0,
        run: Callable[..., subprocess.CompletedProcess] = subprocess.run,
    ):
        self._say = say if say is not None else shutil.which("say")
        self._timeout = timeout_s
        self._run = run

    def synthesize(self, text: str) -> bytes | None:
        text = text.strip()
        if not text or not self._say:
            return None
        fd, path = tempfile.mkstemp(suffix=".wav")
        os.close(fd)
        try:
            proc = self._run(
                [self._say, "-o", path, "--data-format=LEI16@22050", text],
                capture_output=True,
                timeout=self._timeout,
            )
            code = getattr(proc, "returncode", 1)
            if code != 0:
                log.warning("say exited %s — text only", code)
                return None
            data = Path(path).read_bytes()
            return data or None
        except (OSError, subprocess.SubprocessError) as exc:
            log.warning("say synthesis failed: %s — text only", exc)
            return None
        finally:
            Path(path).unlink(missing_ok=True)


def build_tts(voice: str, *, piper: str | None = None, say: str | None = None):
    """Pick the best available local TTS: Piper if its binary is on PATH, else
    macOS `say`, else a no-op Piper (text only). `piper`/`say` may be passed
    explicitly (tests); otherwise they are looked up on PATH."""
    resolved_piper = piper if piper is not None else shutil.which("piper")
    if resolved_piper:
        return PiperTTS(voice, piper=resolved_piper)
    resolved_say = say if say is not None else shutil.which("say")
    if resolved_say:
        log.info("Piper not found; using system `say` for TTS")
        return SystemTTS(say=resolved_say)
    return PiperTTS(voice, piper="")  # no-op -> text only
