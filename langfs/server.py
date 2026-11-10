from __future__ import annotations

import hashlib
import json

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from config import AppConfig
from handlers import Handlers

PROTOCOL_VERSION = "2025-06-18"

TOOLS = [
    {
        "name": "list_providers",
        "description": "List available blob/text providers.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "read_next",
        "description": (
            "Return the next document for this client's recursive enumeration of "
            "(provider, scope, types), advancing a server-held per-client cursor. "
            "Returns extracted text by default (base64 fallback). done=true when exhausted."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "provider": {"type": "string", "description": "Provider name, e.g. 'local'."},
                "scope": {"type": "object", "description": "Provider-specific scope, e.g. {\"path\": \"/foo\"}."},
                "credentials": {"type": "object", "description": "Provider-specific credentials."},
                "client_id": {"type": "string", "description": "Caller-named id, e.g. '{userId}:{runId}'."},
                "types": {"type": "array", "items": {"type": "string"},
                          "description": "Doc-type filter: pdf,word,text,csv,html. Empty = all."},
                "format": {"type": "string", "enum": ["text", "base64"], "description": "Default 'text'."},
                "reset": {"type": "boolean", "description": "Re-enumerate from item 0."},
            },
            "required": ["provider", "scope", "client_id"],
        },
    },
    {
        "name": "test_connection",
        "description": "Validate a provider's credentials + scope before a run.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "provider": {"type": "string"},
                "credentials": {"type": "object"},
                "scope": {"type": "object"},
            },
            "required": ["provider"],
        },
    },
    {
        "name": "reset",
        "description": "Drop a client's enumeration cursor.",
        "inputSchema": {
            "type": "object",
            "properties": {"client_id": {"type": "string"}},
            "required": ["client_id"],
        },
    },
    {
        "name": "list_files",
        "description": "Enumerate files under a path for a provider (recursive, files only). Stateless.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "provider": {"type": "string"},
                "path": {"type": "string"},
                "types": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["provider", "path"],
        },
    },
    {
        "name": "read_file",
        "description": "Read one file's extracted text (or base64 raw bytes). Stateless.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "provider": {"type": "string"},
                "file_id": {"type": "string"},
                "format": {"type": "string", "enum": ["text", "base64"]},
            },
            "required": ["provider", "file_id"],
        },
    },
]


def _owner_from_request(request: Request) -> str:
    auth = request.headers.get("authorization", "")
    if not auth:
        return ""
    return hashlib.sha256(auth.encode("utf-8")).hexdigest()


def _wrap(payload: dict) -> dict:
    """Wrap a handler payload in the MCP text-content envelope gpt expects."""
    return {"content": [{"type": "text", "text": json.dumps(payload)}]}


def create_app(cfg: AppConfig) -> FastAPI:
    app = FastAPI(title="langfs")
    handlers = Handlers(cfg)

    def ok(req_id, result):
        return JSONResponse({"jsonrpc": "2.0", "id": req_id, "result": result})

    def err(req_id, code, message):
        return JSONResponse(
            {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}
        )

    @app.post("/")
    @app.post("/mcp")
    async def rpc(request: Request):
        body = await request.json()
        req_id = body.get("id")
        method = body.get("method")
        params = body.get("params") or {}

        if method == "initialize":
            return ok(req_id, {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "langfs", "version": "0.1.0"},
            })
        if method is not None and method.startswith("notifications/"):
            return JSONResponse({"jsonrpc": "2.0", "id": req_id, "result": {}})
        if method == "ping":
            return ok(req_id, {})
        if method == "tools/list":
            return ok(req_id, {"tools": TOOLS})
        if method == "tools/call":
            name = params.get("name")
            args = params.get("arguments") or {}
            if name == "list_providers":
                return ok(req_id, _wrap(handlers.list_providers(args)))
            if name == "read_next":
                owner = _owner_from_request(request)
                return ok(req_id, _wrap(handlers.read_next(args, owner)))
            if name == "reset":
                return ok(req_id, _wrap(handlers.reset(args)))
            if name == "test_connection":
                return ok(req_id, _wrap(handlers.test_connection(args)))
            if name == "list_files":
                return ok(req_id, _wrap(handlers.list_files(args)))
            if name == "read_file":
                return ok(req_id, _wrap(handlers.read_file(args)))
            return err(req_id, -32601, f"unknown tool '{name}'")

        return err(req_id, -32601, f"unknown method '{method}'")

    return app


def main() -> None:  # pragma: no cover
    import uvicorn

    cfg = AppConfig.from_env()
    uvicorn.run(create_app(cfg), host=cfg.host, port=cfg.port)


if __name__ == "__main__":  # pragma: no cover
    main()
