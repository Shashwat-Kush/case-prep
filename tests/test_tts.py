"""Piper TTS: sentence splitting/streaming + degrade path (T-053). Piper itself is
not installed in tests, so synthesis is exercised through an injected `run`."""

import subprocess
from pathlib import Path
from types import SimpleNamespace

from app.speech.tts import (
    PiperTTS,
    SystemTTS,
    build_tts,
    drain_sentences,
    iter_sentences,
    split_sentences,
)

# --- sentence splitting -----------------------------------------------------


def test_split_sentences_on_terminal_punctuation():
    assert split_sentences("Hello world. How are you? I'm fine!") == [
        "Hello world.",
        "How are you?",
        "I'm fine!",
    ]


def test_decimals_do_not_split():
    # the dot in 3.5 is not followed by whitespace, so it is not a boundary
    text = "It costs 3.5 crore rupees."
    assert split_sentences(text) == [text]


def test_drain_keeps_incomplete_remainder():
    done, rem = drain_sentences("First one. Second half without")
    assert done == ["First one."]
    assert rem == "Second half without"


def test_iter_sentences_streams_first_sentence_before_the_rest():
    # tokens arrive split mid-sentence; the first full sentence yields as soon as
    # its boundary is crossed, well before the stream ends.
    tokens = ["The ", "market ", "is ", "large. ", "We ", "should ", "enter."]
    assert list(iter_sentences(tokens)) == ["The market is large.", "We should enter."]


def test_iter_sentences_flushes_unterminated_tail():
    assert list(iter_sentences(["no ", "period ", "here"])) == ["no period here"]


# --- synthesis + degrade ----------------------------------------------------


def _ok_run(*a, **k):
    return SimpleNamespace(returncode=0, stdout=b"RIFFfakewav")


def test_synthesize_returns_wav_bytes_on_success():
    tts = PiperTTS("en_US-lessac-medium", piper="/usr/bin/piper", run=_ok_run)
    assert tts.synthesize("Hello.") == b"RIFFfakewav"


def test_missing_piper_degrades_to_none():
    tts = PiperTTS("voice", piper="")  # not found -> no binary
    assert tts.synthesize("Hello.") is None


def test_nonzero_exit_degrades_to_none():
    def bad_run(*a, **k):
        return SimpleNamespace(returncode=1, stdout=b"")

    tts = PiperTTS("voice", piper="/usr/bin/piper", run=bad_run)
    assert tts.synthesize("Hello.") is None


def test_subprocess_error_degrades_without_raising():
    def boom(*a, **k):
        raise subprocess.TimeoutExpired(cmd="piper", timeout=10)

    tts = PiperTTS("voice", piper="/usr/bin/piper", run=boom)
    assert tts.synthesize("Hello.") is None


def test_empty_text_is_not_synthesized():
    tts = PiperTTS("voice", piper="/usr/bin/piper", run=_ok_run)
    assert tts.synthesize("   ") is None


# --- macOS `say` fallback + backend selection -------------------------------


def _say_run_writing(data):
    """Fake `say`: writes `data` to the -o output path, like the real command."""

    def run(cmd, **k):
        Path(cmd[cmd.index("-o") + 1]).write_bytes(data)
        return SimpleNamespace(returncode=0, stdout=b"")

    return run


def test_system_tts_returns_wav_bytes_from_temp_file():
    tts = SystemTTS(say="/usr/bin/say", run=_say_run_writing(b"RIFFsaywav"))
    assert tts.synthesize("Hello.") == b"RIFFsaywav"


def test_system_tts_missing_say_degrades_to_none():
    assert SystemTTS(say="").synthesize("Hello.") is None


def test_system_tts_nonzero_exit_degrades_to_none():
    def bad(cmd, **k):
        return SimpleNamespace(returncode=1, stdout=b"")

    assert SystemTTS(say="/usr/bin/say", run=bad).synthesize("Hi.") is None


def test_build_tts_prefers_piper_when_present():
    assert isinstance(build_tts("voice", piper="/usr/bin/piper"), PiperTTS)


def test_build_tts_falls_back_to_say_when_no_piper():
    assert isinstance(build_tts("voice", piper="", say="/usr/bin/say"), SystemTTS)


def test_build_tts_noop_when_nothing_available():
    tts = build_tts("voice", piper="", say="")
    assert isinstance(tts, PiperTTS) and tts.synthesize("Hi.") is None
