"""SharePoint tools over Microsoft Graph: whoami, the failure contract, library lookup, folders."""
from __future__ import annotations

import base64
import binascii
import re
from urllib.parse import quote

import httpx
from cryptography.fernet import InvalidToken

from auth import AuthError
from config import AppConfig
from graph import GraphError


SIMPLE_UPLOAD_MAX = 4 * 1024 * 1024           # Graph's limit for a single PUT
CHUNK = 10 * 320 * 1024                        # upload-session chunks must be multiples of 320 KiB
_FORBIDDEN = re.compile(r'["*:<>?/\\|]|[\x00-\x1f\x7f]')


def safe_name(s: str) -> str:
    """A SharePoint-safe file or folder name: forbidden characters removed, spaces collapsed, no trailing
    dots/spaces, at most 120 characters, never empty."""
    s = re.sub(r" +", " ", _FORBIDDEN.sub("", s)).strip()
    return s[:120].rstrip(". ") or "_"


class DriveService:
    def __init__(self, graph_for, store, cfg: AppConfig):
        self._graph, self.store, self.cfg = graph_for, store, cfg
        self._drives: dict[tuple[str, str], str] = {}        # (site, library) lower-cased -> drive id

    @staticmethod
    def _failure(e: Exception) -> dict:
        """Any failure -> the {"error": code, "message": ...} every tool returns."""
        match e:
            case GraphError():
                return {"error": e.code, "message": e.message}
            case AuthError():
                g = GraphError.from_auth(e)
                return {"error": g.code, "message": g.message}
            case httpx.HTTPError():
                return {"error": "network_error", "message": f"{type(e).__name__}: {e}"[:200]}
            case InvalidToken():                                    # SHAREPOINT_SECRET_KEY changed since the sign-in
                return {"error": "reconnect_needed",
                        "message": "the stored sign-in cannot be decrypted (server key changed): connect again"}
            case ValueError():                                      # a non-JSON answer from Graph
                return {"error": "graph_error", "message": str(e)[:200]}
            case _:
                return {"error": "internal_error", "message": f"{type(e).__name__}: {e}"[:200]}

    def whoami(self, key: str, args: dict | None = None) -> dict:
        try:
            conn = self.store.connection(key)
            if conn is None:
                raise GraphError("reconnect_needed", "unknown or removed connection")
            # Ask Microsoft too: a sign-in it now refuses is reconnect_needed here, not only at the next call.
            self._graph(key).get("/me", {"$select": "id"})
            return {"account": conn["account"], "tenant": conn["tenant"], "connected_at": conn["connected_at"]}
        except Exception as e:
            return self._failure(e)

    # library, names, folders -----------------------------------------------------
    def _drive_id(self, graph, site: str, library: str) -> str:
        """The drive id of a document library: site -> its drives -> the one named `library` (any case). Cached."""
        ck = (site.lower(), library.lower())
        if ck not in self._drives:
            site_id = graph.get("/sites/" + quote(site, safe=":/"))["id"]
            for d in graph.get(f"/sites/{site_id}/drives").get("value", []):
                if str(d.get("name", "")).lower() == library.lower():
                    self._drives[ck] = d["id"]
                    break
            else:
                raise GraphError("not_found", f"document library '{library}' not found in site '{site}'")
        return self._drives[ck]

    def _target(self, key: str, args: dict) -> tuple:
        """(graph, drive id) for the site/library in args, else the SHAREPOINT_SITE / SHAREPOINT_LIBRARY defaults."""
        site, library = args.get("site") or self.cfg.site, args.get("library") or self.cfg.library
        if not site:
            raise GraphError("invalid_argument", "no site: pass site or set SHAREPOINT_SITE")
        if not library:
            raise GraphError("invalid_argument", "no library: pass library or set SHAREPOINT_LIBRARY")
        graph = self._graph(key)
        return graph, self._drive_id(graph, site, library)

    @staticmethod
    def _segments(path) -> list[str]:
        if not isinstance(path, str):
            raise GraphError("invalid_argument", "path must be a string")
        return [safe_name(s) for s in path.split("/") if s.strip()]

    @staticmethod
    def _item_url(drive_id: str, segments: list[str]) -> str:
        return f"/drives/{drive_id}/root:/" + "/".join(quote(s, safe="") for s in segments)

    @staticmethod
    def _create(graph, drive_id: str, parent: list[str], name: str) -> dict:
        children = (f"/drives/{drive_id}/root:/" + "/".join(quote(s, safe="") for s in parent) + ":/children"
                    if parent else f"/drives/{drive_id}/root/children")
        return graph.post(children, {"name": name, "folder": {}, "@microsoft.graph.conflictBehavior": "fail"})

    def _find(self, graph, drive_id: str, segments: list[str]) -> dict | None:
        """The folder at `segments`, None when absent; a file of that name is an error, never reused as a folder."""
        try:
            item = graph.get(self._item_url(drive_id, segments))
        except GraphError as e:
            if e.code == "not_found":
                return None
            raise
        if "folder" not in item:
            raise GraphError("invalid_argument", f"'{'/'.join(segments)}' exists as a file, not a folder")
        return item

    def ensure_folder(self, key: str, args: dict) -> dict:
        try:
            segments = self._segments(args.get("path"))
            if not segments:
                raise GraphError("invalid_argument", "path is empty")
            graph, drive_id = self._target(key, args)
            created, item = [], None
            for i in range(len(segments)):
                item = self._find(graph, drive_id, segments[:i + 1])
                if item is None:
                    try:
                        item = self._create(graph, drive_id, segments[:i], segments[i])
                        created.append("/".join(segments[:i + 1]))
                    except GraphError as e:
                        if e.status != 409:
                            raise
                        item = self._find(graph, drive_id, segments[:i + 1])   # made by someone else meanwhile
                        if item is None:
                            raise
            return {"path": "/".join(segments), "id": item["id"], "created": created}
        except Exception as e:
            return self._failure(e)

    def create_subfolder(self, key: str, args: dict) -> dict:
        try:
            parent, name = self._segments(args.get("parent") or ""), safe_name(str(args.get("name") or ""))
            if not args.get("name"):
                raise GraphError("invalid_argument", "name is required")
            graph, drive_id = self._target(key, args)
            if parent and self._find(graph, drive_id, parent) is None:
                raise GraphError("not_found", "parent folder '" + "/".join(parent) + "' does not exist")
            for n in range(1, 100):
                suffix = "" if n == 1 else f" ({n})"
                # The suffix must survive safe_name's 120-character cap, which upload_file applies to each
                # segment again: a cut-off "(2)" would put the retry's files in the first attempt's folder.
                candidate = (name[:120 - len(suffix)].rstrip(". ") or "_") + suffix
                try:
                    item = self._create(graph, drive_id, parent, candidate)
                except GraphError as e:
                    if e.status != 409:
                        raise
                    continue
                return {"path": "/".join([*parent, candidate]), "id": item["id"]}
            raise GraphError("graph_error", f"no free name for '{name}' up to ({99})")
        except Exception as e:
            return self._failure(e)

    def upload_file(self, key: str, args: dict) -> dict:
        try:
            conflict = args.get("conflict") or "rename"
            if conflict not in ("rename", "fail"):
                raise GraphError("invalid_argument", "conflict must be 'rename' or 'fail'")
            if not args.get("name"):
                raise GraphError("invalid_argument", "name is required")
            try:
                if not isinstance(args.get("base64"), str):
                    raise ValueError
                data = base64.b64decode(args["base64"], validate=True)
            except (ValueError, binascii.Error):
                raise GraphError("invalid_argument", "base64 is not valid base64 text") from None
            folder, name = self._segments(args.get("folder") or ""), safe_name(str(args["name"]))
            graph, drive_id = self._target(key, args)
            target = self._item_url(drive_id, [*folder, name])
            if len(data) <= SIMPLE_UPLOAD_MAX:
                item = graph.put_bytes(f"{target}:/content?@microsoft.graph.conflictBehavior={conflict}", data)
            else:
                session = graph.post(f"{target}:/createUploadSession",
                                     {"item": {"@microsoft.graph.conflictBehavior": conflict}})
                item = {}
                for start in range(0, len(data), CHUNK):
                    chunk = data[start:start + CHUNK]
                    item = graph.put_bytes(session["uploadUrl"], chunk, auth=False, headers={
                        "Content-Range": f"bytes {start}-{start + len(chunk) - 1}/{len(data)}"})
            if "id" not in item:
                raise GraphError("graph_error", "the upload finished without a driveItem")
            return {"path": "/".join([*folder, item.get("name", name)]), "id": item["id"],
                    "web_url": item.get("webUrl", ""), "size": item.get("size", len(data))}
        except Exception as e:
            return self._failure(e)
