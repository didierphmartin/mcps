from __future__ import annotations

import os

from qdrant_client import QdrantClient

from stores.base import StoreError, VectorStoreProvider


class QdrantProvider:
    name = "qdrant"
    embeds_internally = True  # qdrant_client[fastembed] embeds text on add/query

    def connect(self, connection: dict) -> QdrantClient:
        # Per-call connection (from the node's Connection box) takes priority;
        # when a field is blank we fall back to this server's own env config
        # (MCPQ_QDRANT_*), so a server can own its Qdrant like the old double
        # while other DBs / instances are still reachable per call.
        connection = connection or {}
        mode = connection.get("mode") or os.environ.get("MCPQ_QDRANT_MODE") or "local"
        if mode == "remote":
            url = connection.get("url") or os.environ.get("MCPQ_QDRANT_URL")
            if not url:
                raise StoreError("qdrant remote mode needs a 'url' (connection.url or MCPQ_QDRANT_URL)")
            api_key = connection.get("api_key") or os.environ.get("MCPQ_QDRANT_API_KEY") or None
            return QdrantClient(url=url, api_key=api_key)
        path = connection.get("path") or os.environ.get("MCPQ_QDRANT_PATH")
        if not path:
            raise StoreError("qdrant local mode needs a 'path' (connection.path or MCPQ_QDRANT_PATH)")
        return QdrantClient(path=path)

    def test_connection(self, connection: dict) -> dict:
        try:
            self.connect(connection).get_collections()
            return {"ok": True}
        except Exception as e:  # noqa: BLE001 — surface to the UI
            return {"ok": False, "message": str(e)}

    def store(self, conn: QdrantClient, collection: str, items: list[dict], embedding: str | None) -> dict:
        docs = [str(i.get("text", "")) for i in items if str(i.get("text", "")).strip()]
        metas = [dict(i.get("metadata") or {}) for i in items if str(i.get("text", "")).strip()]
        if not docs:
            return {"stored": 0, "errors": 0}
        conn.add(collection_name=collection, documents=docs, metadata=metas)
        return {"stored": len(docs), "errors": 0}

    def find(self, conn: QdrantClient, collection: str, query: str, limit: int, embedding: str | None) -> dict:
        hits = conn.query(collection_name=collection, query_text=query, limit=limit)
        return {"results": [
            {"text": getattr(h, "document", None), "metadata": getattr(h, "metadata", {}) or {},
             "score": getattr(h, "score", None)}
            for h in hits
        ]}


_: VectorStoreProvider = QdrantProvider()
