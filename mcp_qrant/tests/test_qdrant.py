import pytest

from stores.base import StoreError
from stores.qdrant import QdrantProvider


class FakeHit:
    def __init__(self, doc, meta, score): self.document, self.metadata, self.score = doc, meta, score


class FakeClient:
    def __init__(self): self.added = []
    def add(self, collection_name, documents, metadata=None, **kw):
        self.added.append((collection_name, list(documents), metadata)); return ["id1"]
    def query(self, collection_name, query_text, limit=10, **kw):
        return [FakeHit("hello world", {"source": "a.txt"}, 0.91)]
    def get_collections(self): return type("R", (), {"collections": []})()


def test_flags():
    p = QdrantProvider()
    assert p.name == "qdrant" and p.embeds_internally is True


def test_store_passes_text():
    p = QdrantProvider()
    c = FakeClient()
    out = p.store(c, "learn_docs", [{"text": "hello", "metadata": {"source": "a.txt"}}], None)
    assert out == {"stored": 1, "errors": 0}
    assert c.added[0][0] == "learn_docs" and c.added[0][1] == ["hello"]


def test_find_maps_hits():
    p = QdrantProvider()
    out = p.find(FakeClient(), "learn_docs", "hi", 5, None)
    assert out["results"][0]["text"] == "hello world"
    assert out["results"][0]["metadata"]["source"] == "a.txt"
    assert out["results"][0]["score"] == 0.91


def test_connect_local_falls_back_to_env_path(monkeypatch, tmp_path):
    # Blank connection + server env => use the env path (server owns its Qdrant).
    monkeypatch.delenv("MCPQ_QDRANT_MODE", raising=False)
    monkeypatch.setenv("MCPQ_QDRANT_PATH", str(tmp_path / "q"))
    c = QdrantProvider().connect({})
    assert c.get_collections() is not None  # a real, openable local client
    c.close()


def test_connect_connection_path_overrides_env(monkeypatch, tmp_path):
    # A path in the call wins over the env default.
    monkeypatch.setenv("MCPQ_QDRANT_PATH", str(tmp_path / "env"))
    override = tmp_path / "override"
    c = QdrantProvider().connect({"path": str(override)})
    c.close()
    assert override.exists() and not (tmp_path / "env").exists()


def test_connect_local_requires_path_or_env(monkeypatch):
    # No connection and no env => explicit error (no silent default).
    monkeypatch.delenv("MCPQ_QDRANT_MODE", raising=False)
    monkeypatch.delenv("MCPQ_QDRANT_PATH", raising=False)
    with pytest.raises(StoreError):
        QdrantProvider().connect({})
