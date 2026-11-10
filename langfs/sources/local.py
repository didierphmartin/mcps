from __future__ import annotations

from pathlib import Path

from langchain_community.document_loaders.blob_loaders import FileSystemBlobLoader
from langchain_core.documents.base import Blob

from sources.base import BlobSource, FileDescriptor, PathOutsideRoot


class LocalBlobSource:
    name = "local"
    kind = "text"
    description = "Local filesystem via LangChain FileSystemBlobLoader"
    requires_credentials = False

    def __init__(self, allowed_roots: list[str]) -> None:
        self._roots = [Path(r).resolve() for r in allowed_roots]

    def _check(self, raw: str) -> Path:
        p = Path(raw).resolve()
        # No configured roots → unrestricted: this is a trusted local loader whose
        # purpose is to read any local folder. Set LANGFS_ROOTS to opt into a
        # sandbox (e.g. when exposing langfs beyond a trusted LAN).
        if not self._roots:
            return p
        for root in self._roots:
            if p == root or root in p.parents:
                return p
        raise PathOutsideRoot(f"path outside allowed roots: {raw}")

    def connect(self, credentials: dict) -> None:
        return None

    def test_connection(self, credentials: dict, scope: dict) -> dict:
        try:
            self._check(scope.get("path", ""))
            return {"ok": True}
        except PathOutsideRoot as e:
            return {"ok": False, "message": str(e)}

    def enumerate(self, connection, scope: dict, suffixes: list[str]) -> tuple[list[FileDescriptor], bool]:
        path = scope.get("path", "")
        target = self._check(path)
        if target.is_file():
            if suffixes and target.suffix.lower() not in suffixes:
                return [], False
            return [FileDescriptor(id=str(target), name=target.name)], False
        loader = FileSystemBlobLoader(str(target), glob="**/[!.]*")
        out: list[FileDescriptor] = []
        for blob in loader.yield_blobs():            # lazy; no bytes read here
            bp = Path(str(blob.path))
            if suffixes and bp.suffix.lower() not in suffixes:
                continue
            out.append(FileDescriptor(id=str(bp), name=bp.name))
        out.sort(key=lambda d: d.id)                 # deterministic order → cursor is rebuildable
        return out, False

    def read_bytes(self, connection, file_id: str) -> bytes:
        target = self._check(file_id)
        return Blob.from_path(str(target)).as_bytes()


# Static assertion that the class satisfies the protocol.
_: BlobSource = LocalBlobSource([])
