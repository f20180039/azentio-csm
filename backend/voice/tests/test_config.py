import os

import pytest

from app.config import load_settings
from app.llm_chain import ChainConfigError

CHAIN_VARS = ("GROQ_API_KEY", "GEMINI_API_KEY", "MISTRAL_API_KEY", "GEMINI_MODEL", "MISTRAL_MODEL", "VOICE_LLM_CHAIN")


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for k in CHAIN_VARS:
        monkeypatch.delenv(k, raising=False)


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
    assert [l.name for l in s.llm_chain] == ["ollama:llama3.2"]  # no cloud keys: only the local fallback
    assert s.api_base == "http://localhost:8080/api/v1"
    assert s.groq_api_key == ""


def test_default_chain_from_env_file(tmp_path):
    env_file = tmp_path / "voice.env"
    env_file.write_text("GROQ_API_KEY=g\nGEMINI_API_KEY=ge\nMISTRAL_API_KEY=mi\nGEMINI_MODEL=gemini-x\n")
    s = load_settings(env_file)
    assert [l.name for l in s.llm_chain] == [
        "groq:openai/gpt-oss-120b", "gemini:gemini-x", "groq:openai/gpt-oss-20b", "mistral:mistral-small-latest", "ollama:llama3.2"]
    assert [l.api_key for l in s.llm_chain] == ["g", "ge", "g", "mi", "local"]


def test_chain_override_and_anthropic_rejected(tmp_path, monkeypatch):
    env_file = tmp_path / "voice.env"
    env_file.write_text("GROQ_API_KEY=g\nMISTRAL_API_KEY=mi\n")
    monkeypatch.setenv("VOICE_LLM_CHAIN", "mistral:ministral-14b-latest, gemini:g")
    assert [l.name for l in load_settings(env_file).llm_chain] == ["mistral:ministral-14b-latest"]
    monkeypatch.setenv("VOICE_LLM_CHAIN", "anthropic:claude-x")
    with pytest.raises(ChainConfigError, match="anthropic"):
        load_settings(env_file)
