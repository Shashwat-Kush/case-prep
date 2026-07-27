"""Smoke-script output formatting (T-003). The checks are network and run by
hand; only the pass/fail rendering and exit code are unit-tested."""

from scripts.smoke import CHECKLIST, CheckResult, exit_code, format_results


def test_pass_line_shows_name_and_latency():
    line = format_results([CheckResult("groq chat", True, 412.0, None)])
    assert line.startswith("PASS")
    assert "groq chat" in line and "412 ms" in line


def test_fail_line_names_provider_and_error_class():
    line = format_results(
        [CheckResult("nvidia chat", False, 88.0, "LLMError: 401 unauthorized")]
    )
    assert line.startswith("FAIL")
    assert "nvidia chat" in line and "LLMError: 401 unauthorized" in line


def test_skip_line_when_check_not_run():
    line = format_results([CheckResult("groq whisper (stt)", None, None, "no audio")])
    assert line.startswith("SKIP")
    assert "—" in line  # no latency


def test_exit_code_zero_when_all_pass_or_skip():
    results = [
        CheckResult("groq chat", True, 1.0, None),
        CheckResult("groq whisper (stt)", None, None, "no audio"),
    ]
    assert exit_code(results) == 0


def test_exit_code_nonzero_on_any_failure():
    results = [
        CheckResult("groq chat", True, 1.0, None),
        CheckResult("piper (tts)", False, 5.0, "no audio"),
    ]
    assert exit_code(results) == 1


def test_checklist_points_to_decisions_and_names_providers():
    assert "docs/decisions.md" in CHECKLIST
    for name in ("Groq chat", "Nvidia chat", "Groq Whisper", "Piper"):
        assert name in CHECKLIST
