"""Chaos-check reachability formatting (T-071). The probe is network; here we test
the pure rendering and that probe() reports failures key-free via an injected get."""

from scripts.chaos_check import Reach, format_reachability, probe


def test_format_marks_up_and_down():
    out = format_reachability(
        [Reach("groq", True, "HTTP 200"), Reach("ollama", False, "ConnectError")]
    )
    assert "UP  " in out and "groq" in out
    assert "DOWN" in out and "ConnectError" in out


def test_probe_reports_unreachable_as_error_class():
    def boom(url):
        raise ConnectionError("no route")

    r = probe("nvidia", "https://x", get=boom)
    assert r.reachable is False and r.detail == "ConnectionError"


def test_probe_reachable_reports_status():
    class Resp:
        status_code = 204

    r = probe("groq", "https://x", get=lambda u: Resp())
    assert r.reachable is True and r.detail == "HTTP 204"
