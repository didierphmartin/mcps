"""Everything the server remembers, in one SQLite file. Refresh tokens are Fernet-encrypted;
connection keys are stored only as SHA-256 (the app holds the key itself)."""
from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import time
from contextlib import contextmanager

from cryptography.fernet import Fernet

SCHEMA = """
CREATE TABLE IF NOT EXISTS connections (key_id TEXT PRIMARY KEY, account TEXT, tenant TEXT,
    refresh_token TEXT, connected_at REAL);
CREATE TABLE IF NOT EXISTS connects (connect_id TEXT PRIMARY KEY, data TEXT, expires_at REAL,
    status TEXT DEFAULT 'pending', connection_key TEXT);
"""


class Store:
    def __init__(self, path: str, secret_key: str, clock=time.time):
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA busy_timeout=5000")
        self._db.executescript(SCHEMA)
        self._db.commit()
        self._fernet = Fernet(secret_key.encode() if isinstance(secret_key, str) else secret_key)
        self._lock = threading.Lock()
        self._clock = clock

    @staticmethod
    def key_id(connection_key: str) -> str:
        return hashlib.sha256(connection_key.encode()).hexdigest()

    def _x(self, sql: str, args: tuple = ()) -> list[tuple]:
        """One statement; its rows are fetched under the lock (tool calls run on worker threads)."""
        with self._lock:
            rows = self._db.execute(sql, args).fetchall()
            self._db.commit()
            return rows

    def _one(self, sql: str, args: tuple = ()) -> tuple | None:
        rows = self._x(sql, args)
        return rows[0] if rows else None

    @contextmanager
    def _tx(self):
        """Several statements under one lock and one transaction."""
        with self._lock:
            try:
                yield self._db
                self._db.commit()
            except BaseException:
                self._db.rollback()
                raise

    def _enc(self, s: str) -> str:
        return self._fernet.encrypt(s.encode()).decode()

    def _dec(self, s: str) -> str:
        return self._fernet.decrypt(s.encode()).decode()

    # connections -------------------------------------------------------------
    def save_connection(self, connection_key: str, account: str, tenant: str, refresh_token: str) -> None:
        self._x("INSERT OR REPLACE INTO connections VALUES (?, ?, ?, ?, ?)",
                (self.key_id(connection_key), account, tenant, self._enc(refresh_token), self._clock()))

    def connection(self, connection_key: str) -> dict | None:
        row = self._one("SELECT account, tenant, refresh_token, connected_at FROM connections WHERE key_id = ?",
                        (self.key_id(connection_key),))
        if not row:
            return None
        return {"account": row[0], "tenant": row[1], "refresh_token": self._dec(row[2]), "connected_at": row[3]}

    def update_refresh_token(self, connection_key: str, refresh_token: str) -> None:
        self._x("UPDATE connections SET refresh_token = ? WHERE key_id = ?",
                (self._enc(refresh_token), self.key_id(connection_key)))

    # pending connects --------------------------------------------------------
    def create_connect(self, connect_id: str, data: dict, expires_at: float) -> None:
        self._x("INSERT INTO connects (connect_id, data, expires_at) VALUES (?, ?, ?)",
                (connect_id, json.dumps(data), expires_at))

    def connect(self, connect_id: str) -> dict | None:
        row = self._one("SELECT data, expires_at, status FROM connects WHERE connect_id = ?", (connect_id,))
        return {"data": json.loads(row[0]), "expires_at": row[1], "status": row[2]} if row else None

    def update_connect(self, connect_id: str, data: dict) -> None:
        self._x("UPDATE connects SET data = ? WHERE connect_id = ?", (json.dumps(data), connect_id))

    def finish_connect(self, connect_id: str, status: str, connection_key: str | None = None) -> bool:
        """End a pending connect. False when it had already ended (a concurrent request won): a late
        failure or expiry never overwrites a connected row, nor drops its one-time key."""
        with self._tx() as db:
            return db.execute("UPDATE connects SET status = ?, connection_key = ? WHERE connect_id = ? AND status = 'pending'",
                              (status, self._enc(connection_key) if connection_key else None, connect_id)).rowcount == 1

    def reopen_connect(self, connect_id: str, data: dict, expires_at: float) -> bool:
        """An ended (not connected) connect becomes pending again, for the browser sign-in fallback."""
        with self._tx() as db:
            return db.execute("UPDATE connects SET status = 'pending', data = ?, expires_at = ? "
                              "WHERE connect_id = ? AND status != 'connected'",
                              (json.dumps(data), expires_at, connect_id)).rowcount == 1

    def take_connection_key(self, connect_id: str) -> str | None:
        """Atomic: the one-time key is handed to exactly one caller."""
        with self._tx() as db:
            row = db.execute("SELECT connection_key FROM connects WHERE connect_id = ?", (connect_id,)).fetchone()
            if not row or not row[0]:
                return None
            db.execute("UPDATE connects SET connection_key = NULL WHERE connect_id = ?", (connect_id,))
        return self._dec(row[0])

    def connect_by_state(self, state: str) -> str | None:
        for cid, data in self._x("SELECT connect_id, data FROM connects WHERE status = 'pending'"):
            if json.loads(data).get("state") == state:
                return cid
        return None
