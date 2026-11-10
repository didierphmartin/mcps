import os
from config import AppConfig


def test_from_env_reads_roots_and_ttl(monkeypatch):
    monkeypatch.setenv("LANGFS_ROOTS", "/tmp/a:/tmp/b")
    monkeypatch.setenv("LANGFS_CURSOR_TTL", "120")
    cfg = AppConfig.from_env()
    assert cfg.allowed_roots == ["/tmp/a", "/tmp/b"]
    assert cfg.cursor_ttl_seconds == 120


def test_from_env_defaults(monkeypatch):
    monkeypatch.delenv("LANGFS_ROOTS", raising=False)
    monkeypatch.delenv("LANGFS_CURSOR_TTL", raising=False)
    cfg = AppConfig.from_env()
    assert cfg.allowed_roots == []
    assert cfg.cursor_ttl_seconds == 3600
    assert cfg.port == 8077
    assert cfg.host == "127.0.0.1"
