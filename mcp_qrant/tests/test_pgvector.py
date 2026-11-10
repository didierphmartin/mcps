import pytest

import stores.pgvector as pg
from stores.base import StoreError
from stores.pgvector import PgVectorProvider


class FakeDoc:
    def __init__(self, content, meta):
        self.page_content, self.metadata = content, meta


class FakeStore:
    last = None

    def __init__(self, embeddings, collection, dsn):
        self.embeddings, self.collection, self.dsn = embeddings, collection, dsn
        self.added = []
        FakeStore.last = self

    def add_texts(self, texts, metadatas=None, **kw):
        self.added.append((list(texts), metadatas))
        return ["id"]

    def similarity_search_with_score(self, query, k=4, **kw):
        return [(FakeDoc("solar power", {"source": "e.txt"}), 0.12)]


@pytest.fixture(autouse=True)
def patch(monkeypatch):
    # Mock the langchain seam + the embedding factory so no DB/key/libs are needed.
    monkeypatch.setattr(pg, "_make_store", lambda embeddings, collection, dsn: FakeStore(embeddings, collection, dsn))
    monkeypatch.setattr(pg, "make_embeddings", lambda i: f"emb::{i}")
    FakeStore.last = None


def test_flags():
    p = PgVectorProvider()
    assert p.name == "pgvector" and p.embeds_internally is False


def test_connect_dsn_required(monkeypatch):
    monkeypatch.delenv("MCPQ_PGVECTOR_DSN", raising=False)
    with pytest.raises(StoreError, match="needs a Postgres DSN"):
        PgVectorProvider().connect({})


def test_connect_call_dsn_overrides_env(monkeypatch):
    monkeypatch.setenv("MCPQ_PGVECTOR_DSN", "env-dsn")
    assert PgVectorProvider().connect({"dsn": "call-dsn"}) == "call-dsn"


def test_store_embeds_and_adds_skipping_blanks(monkeypatch):
    monkeypatch.setenv("MCPQ_PGVECTOR_DSN", "postgresql+psycopg://x")
    p = PgVectorProvider()
    conn = p.connect({})
    out = p.store(conn, "docs",
                  [{"text": "a", "metadata": {"source": "s"}},
                   {"text": "   ", "metadata": {}}],
                  "openai:text-embedding-3-small")
    assert out == {"stored": 1, "errors": 0}
    assert FakeStore.last.collection == "docs"
    assert FakeStore.last.dsn == "postgresql+psycopg://x"
    assert FakeStore.last.embeddings == "emb::openai:text-embedding-3-small"
    assert FakeStore.last.added[0][0] == ["a"]
    assert FakeStore.last.added[0][1] == [{"source": "s"}]


def test_store_empty_is_noop(monkeypatch):
    monkeypatch.setenv("MCPQ_PGVECTOR_DSN", "postgresql+psycopg://x")
    p = PgVectorProvider()
    out = p.store(p.connect({}), "docs", [{"text": "  "}], None)
    assert out == {"stored": 0, "errors": 0}
    assert FakeStore.last is None  # no store built when nothing to write


def test_store_blank_embedding_uses_default(monkeypatch):
    monkeypatch.setenv("MCPQ_PGVECTOR_DSN", "postgresql+psycopg://x")
    monkeypatch.delenv("MCPQ_EMBEDDING", raising=False)
    p = PgVectorProvider()
    p.store(p.connect({}), "docs", [{"text": "a"}], None)
    assert FakeStore.last.embeddings == "emb::openai:text-embedding-3-small"


def test_find_maps_results(monkeypatch):
    monkeypatch.setenv("MCPQ_PGVECTOR_DSN", "postgresql+psycopg://x")
    p = PgVectorProvider()
    out = p.find(p.connect({}), "docs", "q", 5, "openai:text-embedding-3-small")
    r = out["results"][0]
    assert r["text"] == "solar power"
    assert r["metadata"]["source"] == "e.txt"
    assert r["score"] == 0.12
