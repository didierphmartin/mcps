# langfs — LangChain blob-provider MCP server

Read-only MCP (streamable-HTTP) server over LangChain blob loaders. Enumerates a
folder recursively with a doc-type filter and returns one document at a time as
text (base64 fallback). Holds the enumeration cursor per client.

## Run

    python3 -m venv .venv
    ./.venv/bin/pip install -r requirements.txt
    LANGFS_ROOTS=/path/to/allowed/root ./.venv/bin/python server.py

Server listens on http://127.0.0.1:8077/ (override with LANGFS_HOST/LANGFS_PORT).

## Register in gpt

Add an MCP server in gpt pointing at http://127.0.0.1:8077/ . Tools discovered:
list_providers, read_next, reset.

## Tools

- list_providers() -> {providers:[{name,kind,description,requires_credentials}]}
- read_next(provider, path, client_id, types?, format?, reset?) -> one document
- reset(client_id) -> {reset:true}

Read-only: no write/move/rename/delete.

## Providers

langfs ships four provider descriptors in `providers/`:

| Name  | Kind         | Backend                           |
|-------|--------------|-----------------------------------|
| local | filesystem   | LangChain `FileSystemBlobLoader`  |
| s3    | object_store | cloudpathlib S3Path via `_list_dir` streaming |
| gcs   | object_store | cloudpathlib GSPath via `_list_dir` streaming |
| azure | object_store | cloudpathlib AzureBlobPath via `_list_dir` streaming |

**Adding or overriding providers:** Set `LANGFS_PROVIDERS_DIR` to a directory of JSON descriptor files. Each file must match the descriptor schema (see `descriptors.py`). The built-in `providers/` directory is used by default.

**Cloud providers** require the `cloudpathlib` extras, which are already included in `requirements.txt`:

    cloudpathlib[s3]       # Amazon S3
    cloudpathlib[gs]       # Google Cloud Storage
    cloudpathlib[azure]    # Azure Blob Storage

**Credentials** are entered per-session in the loader-node form (workflow UI) and held for the duration of the session. The server opens one authenticated connection per `client_id` and reuses it for every `read_next` call until the cursor is exhausted, reset, or the TTL expires. No credentials are persisted to disk.

## Multi-user isolation

The server derives an owner token from the `Authorization` request header (SHA-256 of the raw header value). Two requests that share the same `client_id` but carry **different** `Authorization` values are treated as belonging to different owners and the second call is rejected with a `client_id_conflict` error.

To enable owner isolation in a multi-user deployment, ensure each user's requests forward their own `Authorization` header (e.g. `Bearer <user-jwt>`). Requests without an `Authorization` header share the empty-string owner bucket and therefore share a cursor namespace — suitable for single-user or trusted-local use only.
