import pytest

import embedding
from stores.base import StoreError


def test_make_embeddings_openai_maps_model_and_key(monkeypatch):
    captured = {}

    def fake(model, api_key):
        captured["model"] = model
        captured["key"] = api_key
        return ("EMB", model)

    monkeypatch.setattr(embedding, "_openai_embeddings", fake)
    monkeypatch.setenv("MCPQ_OPENAI_API_KEY", "sk-test")

    out = embedding.make_embeddings("openai:text-embedding-3-small")
    assert out == ("EMB", "text-embedding-3-small")
    assert captured == {"model": "text-embedding-3-small", "key": "sk-test"}


def test_make_embeddings_large_id(monkeypatch):
    monkeypatch.setattr(embedding, "_openai_embeddings", lambda model, api_key: model)
    monkeypatch.setenv("MCPQ_OPENAI_API_KEY", "sk-test")
    assert embedding.make_embeddings("openai:text-embedding-3-large") == "text-embedding-3-large"


def test_make_embeddings_missing_key(monkeypatch):
    monkeypatch.setattr(embedding, "_openai_embeddings", lambda model, api_key: model)
    monkeypatch.delenv("MCPQ_OPENAI_API_KEY", raising=False)
    with pytest.raises(StoreError, match="OpenAI key not configured"):
        embedding.make_embeddings("openai:text-embedding-3-small")


def test_make_embeddings_local_not_wired():
    with pytest.raises(StoreError, match="not wired in Phase 2"):
        embedding.make_embeddings("fastembed:bge-small-en-v1.5")
    with pytest.raises(StoreError, match="not wired in Phase 2"):
        embedding.make_embeddings("hf:all-MiniLM-L6-v2")


def test_make_embeddings_unknown():
    with pytest.raises(StoreError, match="unknown embedding"):
        embedding.make_embeddings("nope:whatever")
