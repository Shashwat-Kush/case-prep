"""Latency benchmark aggregation math (T-054). The run path is network and run by
hand; here we test summarize/percentile/gap on fixture samples."""

from scripts.bench_latency import TurnSample, load_samples, percentile, summarize


def _s(provider, stt, ft, full, tts):
    return {
        "provider": provider,
        "stt_ms": stt,
        "first_token_ms": ft,
        "full_response_ms": full,
        "tts_start_ms": tts,
    }


def test_gap_is_stt_plus_first_token_plus_tts():
    s = TurnSample("groq", 800, 400, 2000, 250)
    assert s.gap_ms == 1450  # full_response is NOT part of the gap


def test_percentile_nearest_rank():
    xs = [10, 20, 30, 40, 50]
    assert percentile(xs, 0.5) == 30
    assert percentile(xs, 0.9) == 50
    assert percentile([], 0.9) == 0.0


def test_summarize_medians_per_provider_and_gap():
    samples = [
        _s("groq", 800, 400, 2000, 200),  # gap 1400
        _s("groq", 900, 500, 2200, 300),  # gap 1700
        _s("nvidia", 800, 700, 2500, 400),  # gap 1900
    ]
    out = summarize(samples)
    assert out["n"] == 3
    assert out["providers"]["groq"]["n"] == 2
    assert out["providers"]["groq"]["first_token_ms"]["median"] == 450
    assert out["providers"]["groq"]["gap_ms"]["median"] == 1550
    assert out["providers"]["nvidia"]["gap_ms"]["median"] == 1900


def test_gate_passes_under_3s_median_gap():
    # median gap 1550 ms -> well under the 3s gate
    out = summarize([_s("groq", 800, 400, 2000, 200), _s("groq", 900, 500, 2200, 300)])
    assert out["median_gap_ms"] == 1550
    assert out["passes_gate"] is True


def test_gate_fails_when_median_gap_over_3s():
    slow = [_s("groq", 1500, 1200, 4000, 800), _s("groq", 1600, 1300, 4200, 900)]
    out = summarize(slow)  # gaps 3500 / 3800
    assert out["passes_gate"] is False


def test_empty_samples_do_not_pass_gate():
    out = summarize([])
    assert out["n"] == 0 and out["passes_gate"] is False


def test_load_samples_reads_jsonl(tmp_path):
    p = tmp_path / "history.jsonl"
    p.write_text(
        '{"provider": "groq", "stt_ms": 800, "first_token_ms": 400, '
        '"full_response_ms": 2000, "tts_start_ms": 200}\n\n'
    )
    rows = load_samples(p)
    assert len(rows) == 1 and rows[0]["provider"] == "groq"
    assert load_samples(tmp_path / "missing.jsonl") == []
