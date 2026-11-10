from __future__ import annotations

import os

from config import AppConfig
from embedding import catalog
from stores.registry import build_registry, providers_payload


class Handlers:
    def __init__(self, cfg: AppConfig) -> None:
        self.cfg = cfg
        self.registry = build_registry(cfg)

    def list_providers(self, args: dict) -> dict:
        return {"providers": providers_payload(self.cfg)}

    def list_embeddings(self, args: dict) -> dict:
        return {"embeddings": catalog()}

    def _provider(self, args: dict):
        return self.registry.get(str(args.get("provider", "")))

    def _collection(self, args: dict) -> str:
        # Collection from the call, else this server's default (like the old
        # double's COLLECTION_NAME) — so the node's Collection field is optional.
        return str(args.get("collection") or os.environ.get("MCPQ_COLLECTION") or "documents")

    def test_connection(self, args: dict) -> dict:
        p = self._provider(args)
        if p is None:
            return {"error": True, "code": "unknown_provider", "message": "unknown or unavailable provider"}
        return p.test_connection(args.get("connection") or {})

    def store(self, args: dict) -> dict:
        p = self._provider(args)
        if p is None:
            return {"error": True, "code": "unknown_provider", "message": "unknown or unavailable provider"}
        try:
            conn = p.connect(args.get("connection") or {})
            return p.store(conn, self._collection(args), list(args.get("items") or []), args.get("embedding"))
        except Exception as e:  # noqa: BLE001
            return {"error": True, "code": "store_failed", "message": str(e)}

    def find(self, args: dict) -> dict:
        p = self._provider(args)
        if p is None:
            return {"error": True, "code": "unknown_provider", "message": "unknown or unavailable provider"}
        try:
            conn = p.connect(args.get("connection") or {})
            return p.find(conn, self._collection(args), str(args.get("query", "")),
                          int(args.get("limit", 10)), args.get("embedding"))
        except Exception as e:  # noqa: BLE001
            return {"error": True, "code": "find_failed", "message": str(e)}
