from config import AppConfig


def test_defaults(monkeypatch):
    monkeypatch.delenv("MCPQ_HOST", raising=False)
    monkeypatch.delenv("MCPQ_PORT", raising=False)
    monkeypatch.delenv("MCPQ_PROVIDERS_DIR", raising=False)
    cfg = AppConfig.from_env()
    assert cfg.host == "127.0.0.1"
    assert cfg.port == 8008
    assert cfg.providers_dir.endswith("providers")


def test_env_override(monkeypatch):
    monkeypatch.setenv("MCPQ_PORT", "9000")
    assert AppConfig.from_env().port == 9000
