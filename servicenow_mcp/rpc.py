"""MCP over JSON-RPC 2.0: initialize, notifications, ping, tools/list, tools/call."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from errors import ConnectorError

VERSION = "0.1.0"
PROTOCOL = "2025-11-25"
log = logging.getLogger("servicenow_mcp")


def error_response(req_id, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}


class CallLog:
    """Append-only JSONL log of tool calls (mock instance only), so tests can check what a playbook did."""

    def __init__(self, path: Path):
        self.path = Path(path)

    def append(self, tool: str, args: dict) -> None:
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        line = json.dumps({"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"), "tool": tool, "args": args},
                          ensure_ascii=False)
        with open(self.path, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")

    def read(self) -> list[dict]:
        if not self.path.is_file():
            return []
        out = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if isinstance(row, dict):
                out.append(row)
        return out


class Server:
    def __init__(self, toolset, call_log: CallLog | None = None):
        self.toolset = toolset
        self.call_log = call_log

    def handle(self, rpc: dict) -> dict | None:
        """The response to one JSON-RPC message, or None for a notification."""
        req_id = rpc.get("id")
        method = rpc.get("method")
        if rpc.get("jsonrpc") != "2.0" or not isinstance(method, str):
            return error_response(req_id, -32600, "Invalid Request")
        if method.startswith("notifications/"):
            return None
        match method:
            case "initialize":
                return _result(req_id, {"protocolVersion": PROTOCOL, "capabilities": {"tools": {}},
                                        "serverInfo": {"name": "servicenow", "version": VERSION}})
            case "ping":
                return _result(req_id, {})
            case "tools/list":
                return _result(req_id, {"tools": self.toolset.tools()})
            case "tools/call":
                params = rpc.get("params")
                return _result(req_id, self._call_tool(params if isinstance(params, dict) else {}))
            case _:
                return error_response(req_id, -32601, f"Method not found: {method}")

    def _call_tool(self, params: dict) -> dict:
        name = params.get("name") if isinstance(params.get("name"), str) else ""
        args = params.get("arguments") if isinstance(params.get("arguments"), dict) else {}
        if self.call_log is not None:
            self.call_log.append(name, args)
        try:
            result = self.toolset.call(name, args)
        except ConnectorError as e:
            return _tool_error(e.code, str(e))
        except Exception:  # noqa: BLE001 -- details go to the server log, never to the client
            log.exception("unexpected error in tool %s", name)
            return _tool_error("internal_error", "unexpected error in the connector (see the server log)")
        return {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}],
                "structuredContent": result, "isError": False}


def _tool_error(code: str, message: str) -> dict:
    return {"content": [{"type": "text", "text": f"{code}: {message}"}],
            "structuredContent": {"error": {"code": code, "message": message}}, "isError": True}


def _result(req_id, result: dict) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "result": result}
