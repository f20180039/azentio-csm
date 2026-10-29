import os

from app.config import load_settings


def test_anthropic_key_never_loaded(tmp_path, monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "ambient")
    env_file = tmp_path / "voice.env"
    env_file.write_text("ANTHROPIC_API_KEY=x\nGROQ_API_KEY=g\n")
    s = load_settings(env_file)
    assert s.groq_api_key == "g"
    assert "ANTHROPIC_API_KEY" not in os.environ


def test_defaults(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    s = load_settings(None)
    assert s.llm_model == "openai/gpt-oss-120b"
    assert s.api_base == "http://localhost:8080/api/v1"
    assert s.groq_api_key == ""
