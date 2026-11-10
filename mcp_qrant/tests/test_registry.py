from config import AppConfig
from stores.registry import build_registry, providers_payload

def test_payload_lists_ten():
    payload = {p["name"]: p for p in providers_payload(AppConfig())}
    assert len(payload) == 10
    assert payload["qdrant"]["available"] is True and payload["qdrant"]["embeds_internally"] is True
    assert payload["pgvector"]["available"] is True and payload["pgvector"]["embeds_internally"] is False

def test_registry_only_functional():
    reg = build_registry(AppConfig())
    assert set(reg) == {"qdrant", "pgvector"}   # both implemented + available
