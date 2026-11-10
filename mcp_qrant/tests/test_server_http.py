import json, pytest
from fastapi.testclient import TestClient
from config import AppConfig
from server import create_app


@pytest.fixture
def client():
    return TestClient(create_app(AppConfig()))


def rpc(method, params=None, id=1):
    return {"jsonrpc": "2.0", "id": id, "method": method, "params": params or {}}


def _payload(resp):
    return json.loads(resp.json()["result"]["content"][0]["text"])


def test_tools_list_five(client):
    body = client.post("/mcp", json=rpc("tools/list")).json()
    assert {t["name"] for t in body["result"]["tools"]} == {
        "list_providers", "list_embeddings", "test_connection", "store", "find"}


def test_initialize_and_root_alias(client):
    assert client.post("/", json=rpc("initialize")).json()["result"]["serverInfo"]["name"] == "mcp_qrant"
    assert client.post("/mcp", json=rpc("initialize")).status_code == 200


def test_list_providers_call(client):
    payload = _payload(client.post("/mcp", json=rpc("tools/call",
        {"name": "list_providers", "arguments": {}})))
    assert len(payload["providers"]) == 10


def test_unknown_tool_jsonrpc_error(client):
    body = client.post("/mcp", json=rpc("tools/call", {"name": "nope", "arguments": {}})).json()
    assert body["error"]["code"] == -32601


def test_trailing_slash_served_directly_not_307(client):
    # /mcp/ must be served directly (200), NOT 307-redirected — gpt's ingestion
    # store path does not follow redirects, so a 307 silently breaks writes
    # (store returns 0, no error). follow_redirects=False asserts no redirect.
    resp = client.post("/mcp/", json=rpc("initialize"), follow_redirects=False)
    assert resp.status_code == 200
    assert resp.json()["result"]["serverInfo"]["name"] == "mcp_qrant"
