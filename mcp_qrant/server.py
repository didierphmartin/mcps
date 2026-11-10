from __future__ import annotations

import json

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from config import AppConfig
from handlers import Handlers

PROTOCOL_VERSION = "2025-06-18"


def _obj(props, required):
    return {"type": "object", "properties": props, "required": required}


TOOLS = [
    {"name": "list_providers", "description": "List available vector-DB providers.",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "list_embeddings", "description": "List embedding models the store node may offer.",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "test_connection", "description": "Validate a provider connection.",
     "inputSchema": _obj({"provider": {"type": "string"}, "connection": {"type": "object"}}, ["provider"])},
    {"name": "store", "description": "Embed (unless the provider self-embeds) + upsert chunks.",
     "inputSchema": _obj({"provider": {"type": "string"}, "connection": {"type": "object"},
                          "collection": {"type": "string"},
                          "items": {"type": "array", "items": {"type": "object"}},
                          "embedding": {"type": "string"}}, ["provider", "collection", "items"])},
    {"name": "find", "description": "Semantic search.",
     "inputSchema": _obj({"provider": {"type": "string"}, "connection": {"type": "object"},
                          "collection": {"type": "string"}, "query": {"type": "string"},
                          "limit": {"type": "integer"}, "embedding": {"type": "string"}},
                         ["provider", "collection", "query"])},
]


def _wrap(payload: dict) -> dict:
    return {"content": [{"type": "text", "text": json.dumps(payload)}]}


def create_app(cfg: AppConfig) -> FastAPI:
    app = FastAPI(title="mcp_qrant")
    h = Handlers(cfg)

    def ok(i, r): return JSONResponse({"jsonrpc": "2.0", "id": i, "result": r})
    def err(i, c, m): return JSONResponse({"jsonrpc": "2.0", "id": i, "error": {"code": c, "message": m}})

    @app.post("/")
    @app.post("/mcp")
    @app.post("/mcp/")
    async def rpc(request: Request):
        body = await request.json()
        i, method, params = body.get("id"), body.get("method"), body.get("params") or {}
        if method == "initialize":
            return ok(i, {"protocolVersion": PROTOCOL_VERSION, "capabilities": {"tools": {}},
                          "serverInfo": {"name": "mcp_qrant", "version": "0.1.0"}})
        if method is not None and method.startswith("notifications/"):
            return JSONResponse({"jsonrpc": "2.0", "id": i, "result": {}})
        if method == "ping":
            return ok(i, {})
        if method == "tools/list":
            return ok(i, {"tools": TOOLS})
        if method == "tools/call":
            name = params.get("name"); args = params.get("arguments") or {}
            fn = {"list_providers": h.list_providers, "list_embeddings": h.list_embeddings,
                  "test_connection": h.test_connection, "store": h.store, "find": h.find}.get(name)
            if fn is None:
                return err(i, -32601, f"unknown tool '{name}'")
            return ok(i, _wrap(fn(args)))
        return err(i, -32601, f"unknown method '{method}'")

    return app


def main() -> None:  # pragma: no cover
    import uvicorn
    cfg = AppConfig.from_env()
    uvicorn.run(create_app(cfg), host=cfg.host, port=cfg.port)


if __name__ == "__main__":  # pragma: no cover
    main()
