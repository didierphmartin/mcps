import base64

import pytest
from config import AppConfig
from handlers import Handlers


@pytest.fixture
def tree(tmp_path):
    (tmp_path / "a.txt").write_text("alpha")
    (tmp_path / "b.txt").write_text("bravo")
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "c.txt").write_text("charlie")
    return tmp_path


@pytest.fixture
def H(tree):
    cfg = AppConfig(allowed_roots=[str(tree)])
    return Handlers(cfg)


def test_list_providers(H):
    out = H.list_providers({})
    assert "local" in [p["name"] for p in out["providers"]]


def test_read_next_walks_all_then_done(H, tree):
    args = {"provider": "local", "scope": {"path": str(tree)}, "credentials": {}, "client_id": "u:r1"}
    seen = []
    for _ in range(3):
        r = H.read_next(dict(args), owner="u")
        assert r["done"] is False
        seen.append(r["content"])
    assert sorted(seen) == ["alpha", "bravo", "charlie"]
    last = H.read_next(dict(args), owner="u")
    assert last["done"] is True
    assert "content" not in last


def test_read_next_index_and_count(H, tree):
    args = {"provider": "local", "scope": {"path": str(tree)}, "credentials": {}, "client_id": "u:r2"}
    r = H.read_next(dict(args), owner="u")
    assert r["index"] == 0 and r["count"] == 3 and r["format"] == "text"


def test_read_next_per_client_cursor(H, tree):
    a = {"provider": "local", "scope": {"path": str(tree)}, "credentials": {}, "client_id": "u:A"}
    b = {"provider": "local", "scope": {"path": str(tree)}, "credentials": {}, "client_id": "u:B"}
    H.read_next(dict(a), owner="u")            # A advances to 1
    rb = H.read_next(dict(b), owner="u")       # B independent, starts at 0
    assert rb["index"] == 0


def test_read_next_type_filter(H, tree):
    (tree / "d.pdf").write_bytes(b"%PDF-1.4")
    args = {"provider": "local", "scope": {"path": str(tree)}, "credentials": {}, "client_id": "u:r3", "types": ["text"]}
    r = H.read_next(dict(args), owner="u")
    assert r["count"] == 3  # only .txt counted


def test_read_next_unknown_provider(H, tree):
    r = H.read_next({"provider": "dropbox", "scope": {"path": str(tree)}, "credentials": {}, "client_id": "u:r4"}, owner="u")
    assert r["error"] is True and r["code"] == "unknown_provider"


def test_read_next_conflict(H, tree):
    a = {"provider": "local", "scope": {"path": str(tree)}, "credentials": {}, "client_id": "u:r5"}
    H.read_next(dict(a), owner="u")
    other = {"provider": "local", "scope": {"path": str(tree / "sub")}, "credentials": {}, "client_id": "u:r5"}
    r = H.read_next(dict(other), owner="u")
    assert r["error"] is True and r["code"] == "client_id_conflict"


def test_read_next_reset_restarts(H, tree):
    args = {"provider": "local", "scope": {"path": str(tree)}, "credentials": {}, "client_id": "u:r6"}
    H.read_next(dict(args), owner="u")
    H.read_next(dict(args), owner="u")
    r = H.read_next({**args, "reset": True}, owner="u")
    assert r["index"] == 0


def test_read_next_base64(H, tree):
    args = {"provider": "local", "scope": {"path": str(tree / "a.txt")}, "credentials": {},
            "client_id": "u:r7", "format": "base64"}
    r = H.read_next(dict(args), owner="u")
    assert base64.b64decode(r["content"]) == b"alpha"


def test_read_next_path_outside_root(H, tmp_path):
    outside = tmp_path.parent / "elsewhere"
    r = H.read_next({"provider": "local", "scope": {"path": str(outside)}, "credentials": {}, "client_id": "u:r8"}, owner="u")
    assert r["error"] is True and r["code"] == "path_outside_root"


def test_reset_tool(H, tree):
    assert H.reset({"client_id": "anything"}) == {"reset": True}


def test_test_connection_local_ok_and_bad(H, tree):
    ok = H.test_connection({"provider": "local", "scope": {"path": str(tree)}, "credentials": {}})
    assert ok["ok"] is True
    bad = H.test_connection({"provider": "local", "scope": {"path": str(tree.parent / "no")}, "credentials": {}})
    assert bad["ok"] is False


def test_connection_built_once_per_session(H, tree, monkeypatch):
    calls = {"n": 0}
    src = H.registry["local"]
    orig = src.connect
    monkeypatch.setattr(src, "connect", lambda creds: (calls.__setitem__("n", calls["n"] + 1), orig(creds))[1])
    a = {"provider": "local", "scope": {"path": str(tree)}, "credentials": {}, "client_id": "u:r9"}
    H.read_next(dict(a), owner="u"); H.read_next(dict(a), owner="u")
    assert calls["n"] == 1  # connect called once, reused


def test_done_payload_reports_truncated_false(H, tree):
    args = {"provider": "local", "scope": {"path": str(tree)}, "credentials": {}, "client_id": "u:trunc"}
    for _ in range(3):
        H.read_next(dict(args), owner="u")
    last = H.read_next(dict(args), owner="u")
    assert last["done"] is True and last["truncated"] is False


def test_list_files_local_recursive(H, tree):
    out = H.list_files({"provider": "local", "path": str(tree)})
    names = sorted(f["name"] for f in out["files"])
    assert names == ["a.txt", "b.txt", "c.txt"]          # recursive, files only
    assert all(f["type"] == "file" for f in out["files"])


def test_list_files_unknown_provider(H, tree):
    out = H.list_files({"provider": "drive", "path": str(tree)})
    assert out["error"] is True and out["code"] == "unknown_provider"


def test_list_files_path_outside_root(H, tmp_path):
    out = H.list_files({"provider": "local", "path": str(tmp_path.parent / "nope")})
    assert out["error"] is True and out["code"] == "path_outside_root"


def test_read_file_text(H, tree):
    out = H.read_file({"provider": "local", "file_id": str(tree / "a.txt")})
    assert out == {"content": "alpha", "format": "text"}


def test_read_file_base64(H, tree):
    import base64
    out = H.read_file({"provider": "local", "file_id": str(tree / "a.txt"), "format": "base64"})
    assert base64.b64decode(out["content"]) == b"alpha" and out["format"] == "base64"


def test_read_file_unknown_provider(H, tree):
    out = H.read_file({"provider": "drive", "file_id": "x"})
    assert out["error"] is True and out["code"] == "unknown_provider"
