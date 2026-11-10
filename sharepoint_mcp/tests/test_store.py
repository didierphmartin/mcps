import sqlite3
import threading

from config import AppConfig
from store import Store


def make(tmp_path, clock=lambda: 1000.0):
    return Store(str(tmp_path / "s.sqlite"), AppConfig.new_secret_key(), clock=clock)


def test_refresh_token_is_encrypted_at_rest(tmp_path):
    s = make(tmp_path)
    s.save_connection("key-1", "me@contoso.com", "tid", "RT-SECRET")
    assert s.connection("key-1")["refresh_token"] == "RT-SECRET"
    raw = sqlite3.connect(tmp_path / "s.sqlite").execute("SELECT * FROM connections").fetchall()
    assert "RT-SECRET" not in repr(raw) and "key-1" not in repr(raw)


def test_unknown_connection(tmp_path):
    assert make(tmp_path).connection("nope") is None


def test_connection_key_is_handed_out_once(tmp_path):
    s = make(tmp_path)
    s.create_connect("c1", {"device_code": "dc"}, expires_at=2000)
    s.finish_connect("c1", "connected", "key-1")
    assert s.take_connection_key("c1") == "key-1"
    assert s.take_connection_key("c1") is None
    assert s.connect("c1")["status"] == "connected"


def test_concurrent_take_connection_key_has_one_winner(tmp_path):
    s = make(tmp_path)
    s.create_connect("c1", {}, expires_at=2000)
    s.finish_connect("c1", "connected", "key-1")
    results, barrier = [], threading.Barrier(8)

    def worker():
        barrier.wait()
        results.append(s.take_connection_key("c1"))

    threads = [threading.Thread(target=worker) for _ in range(8)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert results.count("key-1") == 1 and results.count(None) == 7


def test_late_failure_does_not_overwrite_connected(tmp_path):
    s = make(tmp_path)
    s.create_connect("c1", {}, expires_at=2000)
    assert s.finish_connect("c1", "connected", "key-1") is True
    assert s.finish_connect("c1", "failed") is False       # a concurrent poll lost the race
    assert s.finish_connect("c1", "expired") is False
    assert s.connect("c1")["status"] == "connected"
    assert s.take_connection_key("c1") == "key-1"          # the key was not nulled


def test_x_returns_rows_fetched_under_the_lock(tmp_path):
    s = make(tmp_path)
    s.create_connect("c1", {}, expires_at=2000)
    assert s._x("SELECT connect_id FROM connects") == [("c1",)]
