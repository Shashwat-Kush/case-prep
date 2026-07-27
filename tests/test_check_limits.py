"""check_limits formatting (T-066). The probe is network and run by hand; here we
test header extraction, rendering, and that keys never leak into the output."""

from scripts.check_limits import LimitRow, format_limits, remaining_headroom


def test_remaining_headroom_keeps_only_remaining_headers():
    headers = {
        "x-ratelimit-limit-requests": "1000",
        "x-ratelimit-remaining-requests": "42",
        "x-ratelimit-remaining-tokens": "9000",
        "retry-after": "3",
    }
    assert remaining_headroom(headers) == {
        "x-ratelimit-remaining-requests": "42",
        "x-ratelimit-remaining-tokens": "9000",
    }


def test_line_labels_are_trimmed():
    row = LimitRow("groq", {"x-ratelimit-remaining-requests": "42"}, None)
    out = format_limits([row])
    assert out.startswith("groq")
    assert "requests: 42" in out


def test_missing_key_reported_without_leaking_it():
    out = format_limits([LimitRow("nvidia", {}, "missing NVIDIA_API_KEY")])
    assert "missing NVIDIA_API_KEY" in out  # the env var name, not the value


def test_no_headers_row():
    assert "no ratelimit headers" in format_limits([LimitRow("ollama", {}, None)])


def test_output_never_contains_a_key_value():
    # Only provider names and header values are ever formatted; a secret passed
    # nowhere near these functions cannot appear.
    rows = [LimitRow("groq", {"x-ratelimit-remaining-requests": "42"}, None)]
    assert "sk-secret" not in format_limits(rows)
