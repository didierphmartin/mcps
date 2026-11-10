import pytest
from sources.base import FileDescriptor
from cursors import CursorStore, ClientIdConflict


def descs(n):
    return [FileDescriptor(id=f"/x/{i}.txt", name=f"{i}.txt") for i in range(n)]


def fp(store, owner="u", provider="local", path="/x", types=None):
    return store.fingerprint(owner, provider, path, types)


def test_create_then_advance():
    s = CursorStore(ttl_seconds=100)
    e = s.get_or_create("c1", "u", fp(s), lambda: (None, descs(3), False), reset=False)
    assert e.cursor == 0 and len(e.descriptors) == 3
    s.advance("c1")
    e2 = s.get_or_create("c1", "u", fp(s), lambda: (None, descs(3), False), reset=False)
    assert e2.cursor == 1  # same entry, cursor advanced, NOT rebuilt


def test_build_called_once_when_continuing():
    s = CursorStore(ttl_seconds=100)
    calls = {"n": 0}

    def build():
        calls["n"] += 1
        return (None, descs(2), False)

    s.get_or_create("c1", "u", fp(s), build, reset=False)
    s.get_or_create("c1", "u", fp(s), build, reset=False)
    assert calls["n"] == 1  # cached, not re-enumerated


def test_owner_mismatch_conflicts():
    s = CursorStore(ttl_seconds=100)
    s.get_or_create("c1", "alice", fp(s, owner="alice"), lambda: (None, descs(1), False), reset=False)
    with pytest.raises(ClientIdConflict):
        s.get_or_create("c1", "bob", fp(s, owner="bob"), lambda: (None, descs(1), False), reset=False)


def test_fingerprint_mismatch_conflicts():
    s = CursorStore(ttl_seconds=100)
    s.get_or_create("c1", "u", fp(s, path="/x"), lambda: (None, descs(1), False), reset=False)
    with pytest.raises(ClientIdConflict):
        s.get_or_create("c1", "u", fp(s, path="/y"), lambda: (None, descs(1), False), reset=False)


def test_reset_overrides_conflict():
    s = CursorStore(ttl_seconds=100)
    s.get_or_create("c1", "u", fp(s, path="/x"), lambda: (None, descs(1), False), reset=False)
    e = s.get_or_create("c1", "u", fp(s, path="/y"), lambda: (None, descs(5), False), reset=True)
    assert e.cursor == 0 and len(e.descriptors) == 5


def test_ttl_eviction_rebuilds():
    t = {"now": 0.0}
    s = CursorStore(ttl_seconds=10, clock=lambda: t["now"])
    s.get_or_create("c1", "u", fp(s), lambda: (None, descs(3), False), reset=False)
    s.advance("c1")
    t["now"] = 100.0  # past TTL
    calls = {"n": 0}

    def build():
        calls["n"] += 1
        return (None, descs(3), False)

    e = s.get_or_create("c1", "u", fp(s), build, reset=False)
    assert calls["n"] == 1 and e.cursor == 0  # expired → rebuilt fresh


def test_build_returns_connection_and_descriptors():
    closed = []
    s = CursorStore(ttl_seconds=100, close_fn=lambda c: closed.append(c))
    e = s.get_or_create("c1", "u", s.fingerprint("u", "s3", "/x", None, account="bkt"),
                        lambda: ("CONN", descs(2), False), reset=False)
    assert e.connection == "CONN" and len(e.descriptors) == 2


def test_reset_closes_connection():
    closed = []
    s = CursorStore(ttl_seconds=100, close_fn=lambda c: closed.append(c))
    s.get_or_create("c1", "u", s.fingerprint("u", "s3", "/x", None),
                    lambda: ("CONN", descs(1), False), reset=False)
    s.reset("c1")
    assert closed == ["CONN"]


def test_ttl_eviction_closes_old_connection():
    t = {"now": 0.0}; closed = []
    s = CursorStore(ttl_seconds=10, clock=lambda: t["now"], close_fn=lambda c: closed.append(c))
    s.get_or_create("c1", "u", s.fingerprint("u", "s3", "/x", None),
                    lambda: ("OLD", descs(1), False), reset=False)
    t["now"] = 100.0
    s.get_or_create("c1", "u", s.fingerprint("u", "s3", "/x", None),
                    lambda: ("NEW", descs(1), False), reset=False)
    assert closed == ["OLD"]


def test_account_in_fingerprint_distinguishes():
    s = CursorStore(ttl_seconds=100)
    assert s.fingerprint("u", "s3", "/x", None, account="a") != s.fingerprint("u", "s3", "/x", None, account="b")


def test_close_error_does_not_break_store():
    def boom(_conn):
        raise RuntimeError("close failed")
    s = CursorStore(ttl_seconds=100, close_fn=boom)
    s.get_or_create("c1", "u", s.fingerprint("u", "s3", "/x", None),
                    lambda: ("CONN", descs(1), False), reset=False)
    s.reset("c1")  # close raises internally; must be swallowed
    # store still works afterward
    e = s.get_or_create("c1", "u", s.fingerprint("u", "s3", "/x", None),
                        lambda: ("CONN2", descs(2), False), reset=False)
    assert e.connection == "CONN2" and len(e.descriptors) == 2


def test_get_or_create_reset_closes_displaced_connection():
    closed = []
    s = CursorStore(ttl_seconds=100, close_fn=lambda c: closed.append(c))
    s.get_or_create("c1", "u", s.fingerprint("u", "s3", "/x", None),
                    lambda: ("OLD", descs(1), False), reset=False)
    s.get_or_create("c1", "u", s.fingerprint("u", "s3", "/y", None),
                    lambda: ("NEW", descs(1), False), reset=True)
    assert closed == ["OLD"]
