from __future__ import annotations

import base64

from config import AppConfig
from cursors import ClientIdConflict, CursorStore
from parsing.extract import UnsupportedType, extract_text  # noqa: F401 (UnsupportedType used in except)
from parsing.types import suffixes_for
from sources.base import PathOutsideRoot
from sources.registry import build_registry, providers_payload


def _close_connection(conn) -> None:
    close = getattr(conn, "close", None)
    if callable(close):
        try:
            close()
        except Exception:  # noqa: BLE001 — best-effort cleanup
            pass


class Handlers:
    def __init__(self, cfg: AppConfig) -> None:
        self.cfg = cfg
        self.registry = build_registry(cfg)
        self.store = CursorStore(cfg.cursor_ttl_seconds, close_fn=_close_connection)

    def list_providers(self, args: dict) -> dict:
        return {"providers": providers_payload(self.cfg)}

    def reset(self, args: dict) -> dict:
        self.store.reset(str(args.get("client_id", "")))
        return {"reset": True}

    def test_connection(self, args: dict) -> dict:
        source = self.registry.get(str(args.get("provider", "")))
        if source is None:
            return {"error": True, "code": "unknown_provider", "message": "unknown provider"}
        return source.test_connection(args.get("credentials") or {}, args.get("scope") or {})

    def read_next(self, args: dict, owner: str) -> dict:
        provider = str(args.get("provider", ""))
        scope = args.get("scope") or {}
        credentials = args.get("credentials") or {}
        client_id = str(args.get("client_id", ""))
        types = args.get("types") or None
        fmt = str(args.get("format", "text"))
        reset = bool(args.get("reset", False))

        source = self.registry.get(provider)
        if source is None:
            return {"error": True, "code": "unknown_provider", "message": f"unknown provider '{provider}'"}
        if not client_id:
            return {"error": True, "code": "missing_client_id", "message": "client_id is required"}

        suffixes = suffixes_for(types)
        account = str(scope.get("bucket") or scope.get("path") or "")
        fingerprint = self.store.fingerprint(owner, provider, "", types, account=account)

        def build():
            conn = source.connect(credentials)
            descriptors, truncated = source.enumerate(conn, scope, suffixes)
            return conn, descriptors, truncated

        try:
            entry = self.store.get_or_create(client_id, owner, fingerprint, build=build, reset=reset)
        except ClientIdConflict as e:
            return {"error": True, "code": "client_id_conflict", "message": str(e)}
        except PathOutsideRoot as e:
            return {"error": True, "code": "path_outside_root", "message": str(e)}

        count = len(entry.descriptors)
        idx = entry.cursor
        if idx >= count:
            return {"index": idx, "count": count, "done": True, "truncated": entry.truncated}

        desc = entry.descriptors[idx]
        self.store.advance(client_id)
        try:
            data = source.read_bytes(entry.connection, desc.id)
            content = base64.b64encode(data).decode("ascii") if fmt == "base64" else extract_text(desc.name, data)
        except Exception as e:  # noqa: BLE001 — one bad file must not stall the run
            return {"index": idx, "count": count, "source": desc.id,
                    "error": True, "message": str(e), "done": False}
        return {"index": idx, "count": count, "source": desc.id, "name": desc.name,
                "format": fmt, "content": content, "done": False}

    def list_files(self, args: dict) -> dict:
        source = self.registry.get(str(args.get("provider", "")))
        if source is None:
            return {"error": True, "code": "unknown_provider", "message": "unknown provider"}
        path = str(args.get("path", ""))
        suffixes = suffixes_for(args.get("types") or None)
        try:
            conn = source.connect(args.get("credentials") or {})
            descriptors, _truncated = source.enumerate(conn, {"path": path}, suffixes)
        except PathOutsideRoot as e:
            return {"error": True, "code": "path_outside_root", "message": str(e)}
        return {"files": [{"id": d.id, "name": d.name, "type": "file"} for d in descriptors]}

    def read_file(self, args: dict) -> dict:
        source = self.registry.get(str(args.get("provider", "")))
        if source is None:
            return {"error": True, "code": "unknown_provider", "message": "unknown provider"}
        file_id = str(args.get("file_id", ""))
        fmt = str(args.get("format", "text"))
        try:
            conn = source.connect(args.get("credentials") or {})
            data = source.read_bytes(conn, file_id)
            if fmt == "base64":
                content = base64.b64encode(data).decode("ascii")
            else:
                name = file_id.rsplit("/", 1)[-1]
                content = extract_text(name, data)
        except PathOutsideRoot as e:
            return {"error": True, "code": "path_outside_root", "message": str(e)}
        except Exception as e:  # noqa: BLE001 — surface parse/read failure as a tool error
            return {"error": True, "message": str(e)}
        return {"content": content, "format": fmt}
