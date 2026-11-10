# mcp_qrant — Vector-Store MCP Server

A Python/FastAPI MCP server (JSON-RPC 2.0) that exposes a unified interface for storing and querying vector databases. Phase 1 ships Qdrant (self-embedding, local or remote). Nine more providers are listed and will be activated in later phases.

## Quick Start

```bash
# from the project root
MCPQ_PORT=8008 ./.venv/bin/python server.py
```

The server listens on `http://127.0.0.1:8008` and handles MCP JSON-RPC at both `/` and `/mcp`.

Environment variables:

| Variable | Default | Purpose |
|---|---|---|
| `MCPQ_PORT` | `8008` | Listening port |
| `MCPQ_HOST` | `127.0.0.1` | Bind address |
| `MCPQ_PROVIDERS_DIR` | `./providers` | Directory of provider JSON descriptors |

## Tools (5)

### `list_providers`
Returns all 10 provider descriptors. Each entry includes `available` (bool), `embeds_internally` (bool), and `connection_schema` (field list for the UI form).

### `list_embeddings`
Returns the embedding-model catalog (FastEmbed BGE, HuggingFace MiniLM, OpenAI small/large). Only relevant for providers where `embeds_internally: false` — those need a model chosen from this list to embed text before upsert/search.

### `test_connection`
Validates a provider connection without writing data.

```json
{"provider": "qdrant", "connection": {"mode": "local", "path": "/tmp/mydb"}}
```

Returns `{"ok": true}` or `{"ok": false, "message": "..."}`.

### `store`
Embeds (if needed) and upserts text chunks into a collection.

```json
{
  "provider": "qdrant",
  "connection": {"mode": "local", "path": "/tmp/mydb"},
  "collection": "my_docs",
  "items": [
    {"text": "solar panels convert sunlight", "metadata": {"src": "wiki"}},
    {"text": "the cat sat on the mat",       "metadata": {"src": "test"}}
  ]
}
```

Returns `{"stored": 2, "errors": 0}`.

`embedding` is optional; Qdrant ignores it (self-embeds). Pass an `id` from `list_embeddings` for future non-self-embedding providers.

### `find`
Semantic search over a collection.

```json
{
  "provider": "qdrant",
  "connection": {"mode": "local", "path": "/tmp/mydb"},
  "collection": "my_docs",
  "query": "renewable energy",
  "limit": 3
}
```

Returns `{"results": [{"text": "...", "metadata": {...}, "score": 0.91}, ...]}`.

## Providers (10)

| Name | Label | Available | Embeds internally |
|---|---|:---:|:---:|
| `qdrant` | Qdrant | yes | yes |
| `pgvector` | PostgreSQL + pgvector | coming soon | no |
| `chroma` | Chroma | coming soon | no |
| `faiss` | FAISS | coming soon | no |
| `milvus` | Milvus | coming soon | no |
| `mongodb` | MongoDB Atlas | coming soon | no |
| `pinecone` | Pinecone | coming soon | no |
| `redis` | Redis | coming soon | no |
| `weaviate` | Weaviate | coming soon | no |
| `elasticsearch` | Elasticsearch | coming soon | no |

### `embeds_internally`

- **`true` (Qdrant):** the provider does its own embedding via `qdrant-client[fastembed]`. Pass text in `items[].text` and `query`; the `embedding` field is ignored.
- **`false` (all others, Phase 2+):** the MCP will embed text using the model you select from `list_embeddings` before upserting or searching. Pass the model `id` in the `embedding` field.

## Connection Schemas

`list_providers` returns a `connection_schema` per provider that drives the UI form. Qdrant's fields:

| Field | Type | Notes |
|---|---|---|
| `mode` | select | `local` or `remote` |
| `path` | text | required when `mode=local`; path to the on-disk Qdrant storage directory |
| `url` | text | required when `mode=remote`; e.g. `https://xyz.cloud.qdrant.io` |
| `api_key` | password | required for Qdrant Cloud; masked in UI |

## Running Tests

```bash
./.venv/bin/python -m pytest tests/ -v
```

18 tests, all green (Tasks 1–7).

## Smoke Test

```bash
cd tests && ./smoke.sh
```

Boots the server on port 8008, fires `list_providers` (10 entries), `store` 2 chunks into a temp local Qdrant path, and `find` with a semantic query — then shuts down and cleans up.

## PHP Prototype (Retired)

An earlier PHP prototype (`htdocs/vector/`) implemented `qdrant-store`/`qdrant-find` as a thin stateless translator to Qdrant Cloud REST. That work informed the tool contract but is superseded by this Python server. The PHP files will be retired at the remote-Qdrant cutover when this MCP handles both local and remote modes end-to-end.

## Architecture

```
server.py          FastAPI app + JSON-RPC router (_wrap envelope)
handlers.py        Handlers class — delegates to registry
stores/
  base.py          VectorStoreProvider protocol
  registry.py      build_registry + providers_payload
  qdrant.py        QdrantProvider (connect/test_connection/store/find)
providers/         10 JSON descriptor files (available, embeds_internally, connection_schema)
embedding.py       Embedding catalog (used by future non-self-embedding providers)
config.py          AppConfig (env-var driven)
tests/
  smoke.sh         Live boot + curl smoke (store/find against real local Qdrant)
  test_*.py        18 unit tests
```
