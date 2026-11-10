import pytest
from config import AppConfig
from handlers import Handlers


@pytest.fixture
def H(tmp_path):
    return Handlers(AppConfig()), tmp_path


def test_list_providers(H):
    h, _ = H
    assert len(h.list_providers({})["providers"]) == 10


def test_list_embeddings(H):
    h, _ = H
    assert any(e["id"] == "openai:text-embedding-3-small" for e in h.list_embeddings({})["embeddings"])


def test_unknown_provider(H):
    h, _ = H
    assert h.store({"provider": "pinecone", "connection": {}, "collection": "c", "items": []})["code"] == "unknown_provider"


def test_qdrant_store_find_roundtrip(H, tmp_path):
    h, _ = H
    conn = {"mode": "local", "path": str(tmp_path / "qd")}
    s = h.store({"provider": "qdrant", "connection": conn, "collection": "t",
                 "items": [{"text": "the cat sat on the mat", "metadata": {"source": "a"}}]})
    assert s["stored"] == 1
    r = h.find({"provider": "qdrant", "connection": conn, "collection": "t", "query": "where did the cat sit", "limit": 3})
    assert r["results"] and "cat" in r["results"][0]["text"]


def test_collection_defaults(H, monkeypatch):
    # blank collection -> env default; env default -> built-in "documents".
    h, _ = H
    monkeypatch.setenv("MCPQ_COLLECTION", "my_default")
    assert h._collection({}) == "my_default"
    assert h._collection({"collection": "explicit"}) == "explicit"  # call value wins
    monkeypatch.delenv("MCPQ_COLLECTION", raising=False)
    assert h._collection({}) == "documents"
