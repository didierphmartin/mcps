from __future__ import annotations

from typing import Protocol, runtime_checkable


class StoreError(Exception):
    """A vector-store operation failed."""


@runtime_checkable
class VectorStoreProvider(Protocol):
    name: str
    embeds_internally: bool

    def connect(self, connection: dict) -> object: ...
    def test_connection(self, connection: dict) -> dict: ...
    def store(self, conn: object, collection: str, items: list[dict], embedding: str | None) -> dict: ...
    def find(self, conn: object, collection: str, query: str, limit: int, embedding: str | None) -> dict: ...
