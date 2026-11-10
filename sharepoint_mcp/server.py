"""SharePoint MCP server: JSON-RPC over HTTP, the shape gpt's MCP client and langfs use."""
from __future__ import annotations

import html
import json
import time

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from starlette.concurrency import run_in_threadpool

from auth import CREDENTIAL_HEADER
from config import AppConfig

PROTOCOL_VERSION = "2025-06-18"

# The tools fail as MCP tool errors (isError); the error text is the JSON object below.
_FAILS = (" On failure: a tool error (isError) whose text is {\"error\": code, \"message\": ...}; codes include "
          "not_connected, reconnect_needed, throttled, not_found, forbidden, network_error, graph_error, "
          "invalid_argument, internal_error.")
_STR = {"type": "string"}
TOOLS = [
    {"name": "connect_start",
     "description": ("Start connecting a SharePoint account. Returns a code the user enters at verification_uri (device sign-in); "
                     "when the server has a public URL, also redirect_url: a browser sign-in for the same connect_id."),
     "inputSchema": {"type": "object", "properties": {"method": {"type": "string", "enum": ["device"]}}},
     "outputSchema": {"type": "object", "properties": {
         "connect_id": {"type": "string", "description": "Pass to connect_status"},
         "verification_uri": {"type": "string", "description": "The sign-in page"},
         "user_code": {"type": "string", "description": "The code to enter there"},
         "expires_in": {"type": "integer", "description": "Seconds the code stays valid"},
         "redirect_url": {"type": "string", "description": "A browser sign-in to use instead of the code (only with a public URL)"}},
         "required": ["connect_id", "verification_uri", "user_code", "expires_in"]}},
    {"name": "connect_status",
     "description": ("Status of a connect_start: pending, connected (with connection_key, once), expired, denied, "
                     "failed (with message), policy_blocked, or unknown. When the server has a public URL, policy_blocked, "
                     "expired, denied and failed also carry redirect_url: a browser sign-in to try instead."),
     "inputSchema": {"type": "object", "properties": {"connect_id": {"type": "string"}}, "required": ["connect_id"]},
     "outputSchema": {"type": "object", "properties": {
         "status": {"type": "string", "enum": ["pending", "connected", "expired", "denied", "failed", "policy_blocked", "unknown"]},
         "message": {"type": "string", "description": "Why it failed or is blocked"},
         "redirect_url": {"type": ["string", "null"], "description": "A browser sign-in to try instead"},
         "account": {"type": "string", "description": "The account, when connected (first answer only)"},
         "connection_key": {"type": "string", "description": "The connection's key, when connected (first answer only)"},
         "credential_header": {"type": "string", "description": "The request header the key goes in"}},
         "required": ["status"]}},
    {"name": "whoami", "description": "The account this connection acts as, once Microsoft has confirmed its sign-in still works "
                                   "(otherwise reconnect_needed)." + _FAILS,
     "inputSchema": {"type": "object", "properties": {}},
     "outputSchema": {"type": "object", "properties": {
         "account": {"type": "string", "description": "The account address"}, "tenant": _STR,
         "connected_at": {"type": "number", "description": "When it was connected, Unix seconds"}},
         "required": ["account", "tenant", "connected_at"]}},
    {"name": "ensure_folder",
     "description": ("Make sure a folder path exists in the team document library: every missing segment is created, existing "
                     "ones (matched without regard to case) are reused. Names are made SharePoint-safe. site and library "
                     "default to the server's SHAREPOINT_SITE / SHAREPOINT_LIBRARY." + _FAILS),
     "inputSchema": {"type": "object", "properties": {
         "path": {"type": "string", "description": "Folder path in the library, segments separated by /"},
         "site": {"type": "string", "description": "Overrides SHAREPOINT_SITE, e.g. contoso.sharepoint.com:/sites/Team"},
         "library": {"type": "string", "description": "Overrides SHAREPOINT_LIBRARY, a document library name"}},
         "required": ["path"]},
     "outputSchema": {"type": "object", "properties": {
         "path": {"type": "string", "description": "The folder path, after name cleaning"},
         "id": {"type": "string", "description": "The folder's driveItem id"},
         "created": {"type": "array", "items": _STR, "description": "Paths this call created, outermost first"}},
         "required": ["path", "id", "created"]}},
    {"name": "create_subfolder",
     "description": ("Create a new folder under parent, never reusing one: on a name clash it appends ' (2)', ' (3)'... "
                     "The parent must exist (empty parent = library root). site and library default to the server's "
                     "SHAREPOINT_SITE / SHAREPOINT_LIBRARY." + _FAILS),
     "inputSchema": {"type": "object", "properties": {
         "parent": {"type": "string", "description": "Existing folder path; empty for the library root"},
         "name": {"type": "string", "description": "Wanted folder name (made SharePoint-safe)"},
         "site": {"type": "string", "description": "Overrides SHAREPOINT_SITE"},
         "library": {"type": "string", "description": "Overrides SHAREPOINT_LIBRARY"}},
         "required": ["parent", "name"]},
     "outputSchema": {"type": "object", "properties": {
         "path": {"type": "string", "description": "The new folder's path, with any (n) suffix"},
         "id": {"type": "string", "description": "The folder's driveItem id"}},
         "required": ["path", "id"]}},
    {"name": "upload_file",
     "description": ("Upload a file (base64) into a folder of the team document library; missing folders on the path are "
                     "created. Up to 4 MiB in one request, larger files through a chunked upload session. On a name clash "
                     "conflict='rename' keeps both (the new file gets 'name 1.ext'), 'fail' returns graph_error (409). "
                     "site and library default to the server's SHAREPOINT_SITE / SHAREPOINT_LIBRARY." + _FAILS),
     "inputSchema": {"type": "object", "properties": {
         "folder": {"type": "string", "description": "Folder path in the library; empty for the library root"},
         "name": {"type": "string", "description": "File name, e.g. report.pdf (made SharePoint-safe)"},
         "base64": {"type": "string", "description": "The file's content, base64-encoded"},
         "conflict": {"type": "string", "enum": ["rename", "fail"], "description": "On a name clash; default rename"},
         "site": {"type": "string", "description": "Overrides SHAREPOINT_SITE"},
         "library": {"type": "string", "description": "Overrides SHAREPOINT_LIBRARY"}},
         "required": ["folder", "name", "base64"]},
     "outputSchema": {"type": "object", "properties": {
         "path": {"type": "string", "description": "The file's path in the library, with any rename"},
         "id": {"type": "string", "description": "The file's driveItem id"},
         "web_url": {"type": "string", "description": "Link that opens the file in SharePoint"},
         "size": {"type": "number", "description": "Bytes stored"}},
         "required": ["path", "id", "web_url", "size"]}},
]


def _wrap(payload) -> dict:
    """A tool payload as an MCP tool result: {"error": ...} is a tool error (isError); anything else is the
    structured result, also serialized as text for clients that read content only."""
    text = [{"type": "text", "text": json.dumps(payload, ensure_ascii=False)}]
    if isinstance(payload, dict) and "error" in payload:
        return {"content": text, "isError": True}
    return {"content": text, "structuredContent": payload}


def create_app(cfg: AppConfig, http: httpx.Client | None = None, mock=None, clock=time.time, sleep=time.sleep) -> FastAPI:
    from auth import Auth, AuthError, Connector
    from graph import GraphClient, TokenSource
    from drive import DriveService
    from store import Store

    if http is None and cfg.mock_graph:
        from mock_graph import MockGraph
        mock = MockGraph()
        mock.device_state = "connected"
    if http is None:
        http = httpx.Client(transport=httpx.MockTransport(mock.handler)) if mock else httpx.Client()

    app = FastAPI(title="sharepoint_mcp")
    app.state.cfg = cfg
    app.state.clock_offset = [0.0]                     # tests move time forward
    now = lambda: clock() + app.state.clock_offset[0]
    store = Store(cfg.db_path, cfg.secret_key, clock=now)
    auth = Auth(http, cfg)
    connector = Connector(auth, store, http, cfg, clock=now)
    graph_for = lambda key: GraphClient(http, cfg.graph_base, TokenSource(auth, store, key, clock=now), sleep=sleep)
    drive = DriveService(graph_for, store, cfg)

    def ok(req_id, result):
        return JSONResponse({"jsonrpc": "2.0", "id": req_id, "result": result})

    def err(req_id, code, message):
        return JSONResponse({"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}})

    def run_tool(name: str, args: dict, account_key: str):
        match name:
            case "connect_start":
                return connector.start(args.get("method") or "device")
            case "connect_status":
                return connector.status(str(args.get("connect_id") or ""))
            case "whoami" | "ensure_folder" | "create_subfolder" | "upload_file":
                if (failed := connection_error(account_key)) is not None:
                    return failed
                return getattr(drive, name)(account_key, args)
            case _:
                return None

    def connection_error(account_key: str) -> dict | None:
        if not account_key:
            return {"error": "not_connected", "message": f"missing {CREDENTIAL_HEADER} header: connect an account first"}
        if store.connection(account_key) is None:
            return {"error": "reconnect_needed", "message": "unknown or removed connection"}
        return None

    def call_tool(name: str, args: dict, account_key: str):
        """A tool's payload; a failure (sign-in service, the post-sign-in /me lookup, ...) is an error result."""
        try:
            return run_tool(name, args, account_key)
        except AuthError as e:
            return {"error": e.code, "message": e.description or e.code}
        except Exception as e:  # noqa: BLE001 -- a tool never answers with a 500
            return DriveService._failure(e)

    @app.post("/")
    @app.post("/mcp")
    async def rpc(request: Request):
        try:
            body = json.loads(await request.body())
        except ValueError:
            return err(None, -32700, "parse error: the body is not JSON")
        if not isinstance(body, dict):
            return err(None, -32600, "invalid request: expected one JSON-RPC object (batches are not supported)")
        if "id" not in body:
            return Response(status_code=202)               # a notification: accepted, no response body
        req_id, method, params = body.get("id"), body.get("method") or "", body.get("params") or {}
        if not isinstance(params, dict) or not isinstance(params.get("arguments") or {}, dict):
            return err(req_id, -32602, "invalid params: params and params.arguments must be objects")
        match method:
            case "initialize":
                return ok(req_id, {"protocolVersion": PROTOCOL_VERSION, "capabilities": {"tools": {}},
                                   "serverInfo": {"name": "sharepoint", "version": "0.1.0"}})
            case "ping":
                return ok(req_id, {})
            case "tools/list":
                return ok(req_id, {"tools": TOOLS})
            case "tools/call":
                # Tools block (sync httpx, up to 10 s Retry-After): a worker thread, so one slow call
                # does not stall every other call on the event loop.
                payload = await run_in_threadpool(call_tool, params.get("name") or "", params.get("arguments") or {},
                                                  request.headers.get(CREDENTIAL_HEADER, ""))
                if payload is None:
                    return err(req_id, -32601, f"unknown tool '{params.get('name')}'")
                return ok(req_id, _wrap(payload))
            case _:
                return err(req_id, -32601, f"unknown method '{method}'")

    @app.get("/auth/start")
    def auth_start(connect_id: str = ""):
        try:
            return RedirectResponse(connector.redirect_start(connect_id))
        except AuthError as e:
            return _page(f"Cannot start sign-in: {e.description or e.code}", status=400)

    @app.get("/auth/callback")
    def auth_callback(state: str = "", code: str = "", error_description: str = ""):
        if not code:
            return _page(f"Sign-in failed: {error_description or 'no code'}")
        try:
            return _page(connector.redirect_callback(state, code))
        except Exception as e:  # noqa: BLE001 -- the code only: messages may echo service responses
            return _page(f"Sign-in failed ({getattr(e, 'code', type(e).__name__)}). Start again from the app.")

    if mock is not None and cfg.mock_graph:
        @app.post("/mock/device")
        async def mock_device(request: Request):
            mock.device_state = (await request.json()).get("state", "connected")
            return {"state": mock.device_state}

    return app


def _page(message: str, status: int = 200) -> HTMLResponse:
    """A short human page for the browser sign-in steps."""
    return HTMLResponse(f"<!doctype html><meta charset=utf-8><p style='font:16px system-ui'>{html.escape(message)}</p>",
                        status_code=status)


def main() -> None:  # pragma: no cover
    import uvicorn
    cfg = AppConfig.from_env()
    uvicorn.run(create_app(cfg), host=cfg.host, port=cfg.port)


if __name__ == "__main__":  # pragma: no cover
    main()
