from __future__ import annotations

import os

from stores.base import StoreError

# Embedding models the store node may offer (used only by providers whose
# descriptor has embeds_internally=false; Qdrant self-embeds and ignores this).
# The factory that turns an id into a LangChain Embeddings lands in Phase 2.
EMBEDDING_CATALOG: list[dict] = [
    {"id": "fastembed:bge-small-en-v1.5", "label": "FastEmbed BGE small (local)",
     "provider": "fastembed", "dimensions": 384, "requires_credentials": False},
    {"id": "hf:all-MiniLM-L6-v2", "label": "HuggingFace all-MiniLM-L6-v2 (local)",
     "provider": "huggingface", "dimensions": 384, "requires_credentials": False},
    {"id": "openai:text-embedding-3-small", "label": "OpenAI text-embedding-3-small",
     "provider": "openai", "dimensions": 1536, "requires_credentials": True},
    {"id": "openai:text-embedding-3-large", "label": "OpenAI text-embedding-3-large",
     "provider": "openai", "dimensions": 3072, "requires_credentials": True},
]


def catalog() -> list[dict]:
    return list(EMBEDDING_CATALOG)


_OPENAI_MODELS = {
    "openai:text-embedding-3-small": "text-embedding-3-small",
    "openai:text-embedding-3-large": "text-embedding-3-large",
}


def _openai_embeddings(model: str, api_key: str):
    # Lazy import so catalog() works without langchain_openai installed, and so
    # unit tests can monkeypatch this helper.
    from langchain_openai import OpenAIEmbeddings

    return OpenAIEmbeddings(model=model, api_key=api_key)


def make_embeddings(embedding_id: str):
    """Build a LangChain Embeddings for a catalog id. Phase 2 wires the OpenAI
    ids; the local ids (fastembed/hf) stay listed but are not wired yet."""
    if embedding_id in _OPENAI_MODELS:
        key = os.environ.get("MCPQ_OPENAI_API_KEY")
        if not key:
            raise StoreError("OpenAI key not configured (set MCPQ_OPENAI_API_KEY)")
        return _openai_embeddings(_OPENAI_MODELS[embedding_id], key)
    if embedding_id.startswith("fastembed:") or embedding_id.startswith("hf:"):
        raise StoreError(f"embedding '{embedding_id}' is not wired in Phase 2")
    raise StoreError(f"unknown embedding '{embedding_id}'")
