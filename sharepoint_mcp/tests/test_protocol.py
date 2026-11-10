import json

import httpx
import pytest
from fastapi.testclient import TestClient

from auth import CREDENTIAL_HEADER
from config import AppConfig
from mock_graph import MockGraph
from server import create_app


def make(tmp_path, mock=None):
    cfg = AppConfig(client_id="cid", secret_key=AppConfig.new_secret_key(), db_path=str(tmp_path / "s.sqlite"))
    mock = mock or MockGraph()
    return TestClient(create_app(cfg, http=httpx.Client(transport=httpx.MockTransport(mock.handler)), mock=mock)), mock


def rpc(c, method, params=None, req_id=1, headers=None):
    return c.post("/mcp", json={"jsonrpc": "2.0", "id": req_id, "method": method, "params": params or {}},
                  headers=headers or {}).json()


def call(c, name, args=None, headers=None):
    return rpc(c, "tools/call", {"name": name, "arguments": args or {}}, headers=headers)["result"]


def test_initialize_and_tools_list(tmp_path):
    c, _ = make(tmp_path)
    assert rpc(c, "initialize")["result"]["serverInfo"]["name"] == "sharepoint"
    assert [t["name"] for t in rpc(c, "tools/list")["result"]["tools"]] == ["connect_start", "connect_status", "whoami", "ensure_folder", "create_subfolder", "upload_file"]


def test_unknown_method_and_tool(tmp_path):
    c, _ = make(tmp_path)
    assert rpc(c, "nope")["error"]["code"] == -32601
    assert rpc(c, "tools/call", {"name": "nope", "arguments": {}})["error"]["code"] == -32601


def test_notifications_are_acknowledged(tmp_path):
    c, _ = make(tmp_path)
    r = c.post("/mcp", json={"jsonrpc": "2.0", "method": "notifications/initialized"})
    assert r.status_code == 202 and r.content == b""


def test_from_env_requires_ids(monkeypatch):
    monkeypatch.delenv("SHAREPOINT_CLIENT_ID", raising=False)
    monkeypatch.delenv("SHAREPOINT_MOCK_GRAPH", raising=False)
    with pytest.raises(SystemExit, match="SHAREPOINT_CLIENT_ID"):
        AppConfig.from_env()


def test_from_env_reads_site_library_and_port(monkeypatch):
    for k, v in {"SHAREPOINT_CLIENT_ID": "c", "SHAREPOINT_SECRET_KEY": AppConfig.new_secret_key(),
                 "SHAREPOINT_SITE": "contoso.sharepoint.com:/sites/Team", "SHAREPOINT_LIBRARY": "Documents"}.items():
        monkeypatch.setenv(k, v)
    monkeypatch.delenv("SHAREPOINT_PORT", raising=False)
    cfg = AppConfig.from_env()
    assert (cfg.site, cfg.library, cfg.port) == ("contoso.sharepoint.com:/sites/Team", "Documents", 8771)
    assert "Sites.ReadWrite.All" in AppConfig.SCOPES and "Mail" not in AppConfig.SCOPES


def connect(c):
    s = call(c, "connect_start")["structuredContent"]
    c.app.state.clock_offset[0] += 10                    # past the device poll interval
    done = call(c, "connect_status", {"connect_id": s["connect_id"]})["structuredContent"]
    assert done["status"] == "connected" and done["credential_header"] == CREDENTIAL_HEADER == "X-SharePoint-Key"
    return done["connection_key"]


def test_connect_then_whoami(tmp_path):
    mock = MockGraph()
    mock.device_state = "connected"
    c, _ = make(tmp_path, mock)
    key = connect(c)
    r = call(c, "whoami", headers={CREDENTIAL_HEADER: key})
    assert "isError" not in r
    me = r["structuredContent"]
    assert me["account"] == "me@contoso.com" and me["tenant"] == "tid-1" and isinstance(me["connected_at"], float)
    assert any(path.startswith("/v1.0/me") for _, path in mock.requests)


def test_whoami_failure_contract(tmp_path):
    mock = MockGraph()
    mock.device_state = "connected"
    c, _ = make(tmp_path, mock)
    r = call(c, "whoami")
    assert r["isError"] is True
    assert json.loads(r["content"][0]["text"])["error"] == "not_connected"
    r = call(c, "whoami", headers={CREDENTIAL_HEADER: "bogus"})
    assert json.loads(r["content"][0]["text"])["error"] == "reconnect_needed"
    key = connect(c)
    mock.revoke_refresh()
    mock.expire_access_tokens()
    r = call(c, "whoami", headers={CREDENTIAL_HEADER: key})
    assert r["isError"] and json.loads(r["content"][0]["text"])["error"] == "reconnect_needed"


def test_folder_tools_over_rpc(tmp_path):
    mock = MockGraph()
    mock.device_state = "connected"
    mock.add_library("contoso.sharepoint.com:/sites/Team", "Documents")
    cfg = AppConfig(client_id="cid", secret_key=AppConfig.new_secret_key(), db_path=str(tmp_path / "s.sqlite"),
                    site="contoso.sharepoint.com:/sites/Team", library="Documents")
    c = TestClient(create_app(cfg, http=httpx.Client(transport=httpx.MockTransport(mock.handler)), mock=mock))
    assert call(c, "ensure_folder", {"path": "a"})["isError"]            # no connection key: not_connected
    h = {CREDENTIAL_HEADER: connect(c)}
    r = call(c, "ensure_folder", {"path": "alice"}, headers=h)["structuredContent"]
    assert r["created"] == ["alice"]
    s = call(c, "create_subfolder", {"parent": "alice", "name": "mail"}, headers=h)["structuredContent"]
    assert s["path"] == "alice/mail"
