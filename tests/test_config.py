import pytest

from app.config import Config, ConfigError, load_config

VALID = """
offline: false
host: 127.0.0.1
port: 8000
providers:
  - name: groq
    base_url: https://api.groq.com/openai/v1
    model: llama-3.3-70b-versatile
    api_key_env: GROQ_API_KEY
stt:
  base_url: https://api.groq.com/openai/v1
  model: whisper-large-v3
  api_key_env: GROQ_API_KEY
voice: en_US-lessac-medium
"""


def test_repo_config_parses():
    cfg = load_config("config.yaml")
    assert isinstance(cfg, Config)
    assert cfg.providers[0].name == "groq"
    assert cfg.ladder.graduation_min_avg == 3.0


def test_valid_config_parses(tmp_path):
    p = tmp_path / "config.yaml"
    p.write_text(VALID)
    cfg = load_config(p)
    assert cfg.provider("groq").model == "llama-3.3-70b-versatile"
    assert cfg.retry.max_retries == 2  # default applied


def test_missing_required_key_fails(tmp_path):
    p = tmp_path / "config.yaml"
    p.write_text(VALID.replace("voice: en_US-lessac-medium", ""))
    with pytest.raises(ConfigError) as exc:
        load_config(p)
    assert "voice" in str(exc.value)


def test_malformed_yaml_names_file(tmp_path):
    p = tmp_path / "broken.yaml"
    p.write_text("providers: [unterminated\n")
    with pytest.raises(ConfigError) as exc:
        load_config(p)
    assert "broken.yaml" in str(exc.value)


def test_api_key_resolves_from_env(tmp_path, monkeypatch):
    p = tmp_path / "config.yaml"
    p.write_text(VALID)
    monkeypatch.setenv("GROQ_API_KEY", "secret-value")
    cfg = load_config(p)
    assert cfg.provider("groq").api_key() == "secret-value"
    assert "secret-value" not in repr(cfg)  # key never stored on the model
