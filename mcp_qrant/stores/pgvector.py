from __future__ import annotations

import os

from embedding import make_embeddings
from stores.base import StoreError, VectorStoreProvider

_DEFAULT_EMBEDDING = "openai:text-embedding-3-small"


def _make_store(embeddings, collection: str, dsn: str):
    # Lazy import so the module is importable (and unit-testable by monkeypatching
    # this helper) without langchain_postgres installed.
    from langchain_postgres import PGVector

    return PGVector(embeddings=embeddings, collection_name=collection, connection=dsn, use_jsonb=True)


class PgVectorProvider:
    name = "pgvector"
    embeds_internally = False  # the MCP computes embeddings (OpenAI in Phase 2)

    def _dsn(self, connection: dict) -> str:
        connection = connection or {}
        dsn = connection.get("dsn") or os.environ.get("MCPQ_PGVECTOR_DSN")
        if not dsn:
            raise StoreError("pgvector needs a Postgres DSN (connection.dsn or MCPQ_PGVECTOR_DSN)")
        return dsn

    def _embedding_id(self, embedding: str | None) -> str:
        return embedding or os.environ.get("MCPQ_EMBEDDING") or _DEFAULT_EMBEDDING

    def connect(self, connection: dict) -> str:
        # The "connection" handle is just the resolved dsn; a PGVector instance is
        # built per call (bound to its collection + embeddings).
        return self._dsn(connection)

    def test_connection(self, connection: dict) -> dict:
        try:
            dsn = self._dsn(connection)
            _make_store(make_embeddings(self._embedding_id(None)), "mcpq_healthcheck", dsn)
            return {"ok": True}
        except Exception as e:  # noqa: BLE001 — surface to the UI
            return {"ok": False, "message": str(e)}

    def store(self, conn: str, collection: str, items: list[dict], embedding: str | None) -> dict:
        texts = [str(i.get("text", "")) for i in items if str(i.get("text", "")).strip()]
        metas = [dict(i.get("metadata") or {}) for i in items if str(i.get("text", "")).strip()]
        if not texts:
            return {"stored": 0, "errors": 0}
        store = _make_store(make_embeddings(self._embedding_id(embedding)), collection, conn)
        store.add_texts(texts=texts, metadatas=metas)
        return {"stored": len(texts), "errors": 0}

    def find(self, conn: str, collection: str, query: str, limit: int, embedding: str | None) -> dict:
        store = _make_store(make_embeddings(self._embedding_id(embedding)), collection, conn)
        hits = store.similarity_search_with_score(query, k=limit)
        return {"results": [
            {"text": getattr(doc, "page_content", None),
             "metadata": getattr(doc, "metadata", {}) or {},
             "score": float(score) if score is not None else None}
            for doc, score in hits
        ]}


_: VectorStoreProvider = PgVectorProvider()
