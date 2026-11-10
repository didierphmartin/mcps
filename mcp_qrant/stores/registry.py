from __future__ import annotations

from config import AppConfig
from descriptors import load_descriptors
from stores.base import VectorStoreProvider
from stores.pgvector import PgVectorProvider
from stores.qdrant import QdrantProvider

# provider name -> factory (only implemented providers; others are descriptor-only)
_IMPL = {
    "qdrant": lambda d: QdrantProvider(),
    "pgvector": lambda d: PgVectorProvider(),
}


def build_registry(cfg: AppConfig) -> dict[str, VectorStoreProvider]:
    descs = load_descriptors(cfg.providers_dir)
    out: dict[str, VectorStoreProvider] = {}
    for name, d in descs.items():
        if d.available and name in _IMPL:
            out[name] = _IMPL[name](d)
    return out


def providers_payload(cfg: AppConfig) -> list[dict]:
    descs = load_descriptors(cfg.providers_dir)
    return [{
        "name": d.name, "label": d.label, "description": d.description,
        "available": d.available, "embeds_internally": d.embeds_internally,
        "connection_schema": d.connection_schema,
    } for d in descs.values()]
