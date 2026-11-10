from __future__ import annotations

import hashlib
import os
import threading
import time
from dataclasses import dataclass
from typing import Callable

from sources.base import FileDescriptor


class ClientIdConflict(Exception):
    """client_id reused for a different owner or source."""


@dataclass
class Entry:
    owner: str
    fingerprint: str
    descriptors: list[FileDescriptor]
    cursor: int
    updated_at: float
    connection: object | None = None
    truncated: bool = False


class CursorStore:
    def __init__(
        self,
        ttl_seconds: int,
        *,
        clock: Callable[[], float] = time.monotonic,
        close_fn: Callable[[object], None] | None = None,
    ) -> None:
        self._ttl = ttl_seconds
        self._clock = clock
        self._close_fn = close_fn
        self._lock = threading.Lock()
        self._entries: dict[str, Entry] = {}

    @staticmethod
    def fingerprint(
        owner: str,
        provider: str,
        path: str,
        types: list[str] | None,
        account: str = "",
    ) -> str:
        norm_path = os.path.normpath(path)
        norm_types = ",".join(sorted(types or []))
        raw = "\x00".join([owner, provider, norm_path, norm_types, account])
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _expired(self, e: Entry) -> bool:
        return (self._clock() - e.updated_at) > self._ttl

    def _close(self, entry: Entry) -> None:
        if self._close_fn is not None and entry.connection is not None:
            try:
                self._close_fn(entry.connection)
            except Exception:
                pass

    def get_or_create(
        self,
        client_id: str,
        owner: str,
        fingerprint: str,
        build: Callable[[], tuple[object | None, list[FileDescriptor], bool]],
        reset: bool,
    ) -> Entry:
        with self._lock:
            e = self._entries.get(client_id)
            if e is not None and self._expired(e):
                self._close(e); e = None
            if e is not None and not reset:
                if e.owner != owner or e.fingerprint != fingerprint:
                    raise ClientIdConflict(
                        f"client_id '{client_id}' already in use for a different owner/source"
                    )
                e.updated_at = self._clock()
                return e
            if e is not None:           # reset over an existing entry
                self._close(e)
            connection, descriptors, truncated = build()
            entry = Entry(
                owner=owner,
                fingerprint=fingerprint,
                connection=connection,
                descriptors=descriptors,
                cursor=0,
                updated_at=self._clock(),
                truncated=truncated,
            )
            self._entries[client_id] = entry
            return entry

    def advance(self, client_id: str) -> None:
        with self._lock:
            e = self._entries.get(client_id)
            if e is not None:
                e.cursor += 1
                e.updated_at = self._clock()

    def reset(self, client_id: str) -> None:
        with self._lock:
            e = self._entries.pop(client_id, None)
        if e is not None:
            self._close(e)
