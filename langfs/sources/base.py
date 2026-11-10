from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass
class FileDescriptor:
    id: str
    name: str


class PathOutsideRoot(Exception):
    """A requested path resolves outside every allowed root."""


@runtime_checkable
class BlobSource(Protocol):
    name: str
    kind: str
    description: str
    requires_credentials: bool

    def connect(self, credentials: dict) -> object | None: ...

    def test_connection(self, credentials: dict, scope: dict) -> dict: ...

    def enumerate(self, connection: object | None, scope: dict,
                  suffixes: list[str]) -> tuple[list["FileDescriptor"], bool]: ...

    def read_bytes(self, connection: object | None, file_id: str) -> bytes: ...
