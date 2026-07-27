"""Piper TTS: sentence splitting/streaming + degrade path (T-053). Piper itself is
not installed in tests, so synthesis is exercised through an injected `run`."""

import subprocess
from types import SimpleNamespace

from app.speech.tts import PiperTTS, drain_sentences, iter_sentences, split_sentences

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
