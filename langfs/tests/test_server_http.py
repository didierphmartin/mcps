import json
import pytest
from fastapi.testclient import TestClient
from config import AppConfig
from server import create_app


@pytest.fixture
def client(tmp_path):
    (tmp_path / "a.txt").write_text("alpha")
    (tmp_path / "b.txt").write_text("bravo")
    cfg = AppConfig(allowed_roots=[str(tmp_path)])
    return TestClient(create_app(cfg)), tmp_path


def rpc(method, params=None, id=1):
    return {"jsonrpc": "2.0", "id": id, "method": method, "params": params or {}}


def _payload(resp):
    """Unwrap the MCP content envelope back to the handler's dict."""
    body = resp.json()
    text = body["result"]["content"][0]["text"]
    return json.loads(text)


def test_tools_list_advertises_six_tools(client):
    c, _ = client
    body = c.post("/", json=rpc("tools/list")).json()
    names = {t["name"] for t in body["result"]["tools"]}
    assert names == {"list_providers", "read_next", "reset", "test_connection",
                     "list_files", "read_file"}


def test_tools_call_list_then_read_file(client):
    c, tree = client          # fixture writes a.txt="alpha", b.txt="bravo"
    listed = _payload(c.post("/", json=rpc("tools/call",
        {"name": "list_files", "arguments": {"provider": "local", "path": str(tree)}})))
    ids = sorted(f["id"] for f in listed["files"])
    got = _payload(c.post("/", json=rpc("tools/call",
        {"name": "read_file", "arguments": {"provider": "local", "file_id": ids[0]}})))
    assert got["format"] == "text" and got["content"] in ("alpha", "bravo")


def test_initialize_ok(client):
    c, _ = client
    body = c.post("/", json=rpc("initialize")).json()
    assert body["result"]["serverInfo"]["name"] == "langfs"


def test_mcp_path_is_served(client):
    # gpt's MCP client posts to <url>/mcp; the same handler must answer there too.
    c, _ = client
    resp = c.post("/mcp", json=rpc("initialize"))
    assert resp.status_code == 200
    assert resp.json()["result"]["serverInfo"]["name"] == "langfs"
    body = c.post("/mcp", json=rpc("tools/list")).json()
    assert {t["name"] for t in body["result"]["tools"]} == {
        "list_providers", "read_next", "reset", "test_connection",
        "list_files", "read_file"}


def test_tools_call_list_providers(client):
    c, _ = client
    resp = c.post("/", json=rpc("tools/call",
                  {"name": "list_providers", "arguments": {}}))
    payload = _payload(resp)
    names = {p["name"] for p in payload["providers"]}
    assert "local" in names


def test_tools_call_read_next_returns_text(client):
    c, tree = client
    args = {"provider": "local", "scope": {"path": str(tree)}, "credentials": {}, "client_id": "u:r1"}
    payload = _payload(c.post("/", json=rpc("tools/call",
                       {"name": "read_next", "arguments": args})))
    assert payload["content"] in ("alpha", "bravo")
    assert payload["count"] == 2 and payload["done"] is False


def test_tools_call_unknown_tool_is_jsonrpc_error(client):
    c, _ = client
    body = c.post("/", json=rpc("tools/call",
                  {"name": "nope", "arguments": {}})).json()
    assert "error" in body and body["error"]["code"] == -32601


def test_ping_ok(client):
    c, _ = client
    body = c.post("/", json=rpc("ping")).json()
    assert body["result"] == {}


def test_read_next_owner_isolation_conflict(client):
    """Same client_id + same path but different Authorization → client_id_conflict."""
    c, tree = client
    args = {"provider": "local", "scope": {"path": str(tree)}, "credentials": {}, "client_id": "shared:r1"}
    # First call establishes the owner binding for "shared:r1"
    resp1 = c.post("/", json=rpc("tools/call", {"name": "read_next", "arguments": args}),
                   headers={"Authorization": "Bearer tokenA"})
    payload1 = _payload(resp1)
    assert payload1.get("error") is not True, f"first call unexpectedly errored: {payload1}"
    # Second call reuses the same client_id with a different token → conflict
    resp2 = c.post("/", json=rpc("tools/call", {"name": "read_next", "arguments": args}),
                   headers={"Authorization": "Bearer tokenB"})
    payload2 = _payload(resp2)
    assert payload2["code"] == "client_id_conflict"


def test_tools_call_test_connection(client):
    c, tree = client
    payload = _payload(c.post("/", json=rpc("tools/call", {
        "name": "test_connection",
        "arguments": {"provider": "local", "scope": {"path": str(tree)}, "credentials": {}}})))
    assert payload["ok"] is True
