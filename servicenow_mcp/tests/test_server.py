import json
import shutil

import pytest
from fastapi.testclient import TestClient

import guard
from config import Config
from conftest import ROOT
from fixture_backend import FixtureBackend
from jobs import JobsToolset
from rpc import CallLog, Server
from server import build_server, create_app

JSON = {"Content-Type": "application/json"}


def rpc(method, params=None, req_id=1):
    return {"jsonrpc": "2.0", "id": req_id, "method": method, **({"params": params} if params is not None else {})}


@pytest.fixture
def app_dir(tmp_path):
    """A server folder with the real fixture: mock state and the call log land here, not in the repo."""
    (tmp_path / "fixtures").mkdir()
    shutil.copy(ROOT / "fixtures" / "mock.json", tmp_path / "fixtures" / "mock.json")
    return tmp_path


@pytest.fixture
def server(data, tmp_path):
    return Server(JobsToolset(Config.mock(), FixtureBackend(data)), CallLog(tmp_path / "calls.jsonl"))


# --- JSON-RPC ---------------------------------------------------------------------------------------------------

def test_initialize(server):
    r = server.handle(rpc("initialize"))
    assert r["id"] == 1
    assert r["result"]["protocolVersion"] == "2025-11-25"
    assert r["result"]["serverInfo"] == {"name": "servicenow", "version": "0.1.0"}
    assert json.dumps(r["result"]["capabilities"]["tools"]) == "{}"


def test_notifications_get_no_response(server):
    assert server.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None


def test_tools_list(server):
    r = server.handle(rpc("tools/list", req_id=7))
    assert r["id"] == 7
    assert [t["name"] for t in r["result"]["tools"]] == ["poll_jobs", "wait_for_jobs", "claim_job", "add_note",
                                                         "complete_job", "hand_back", "describe_item"]


def test_tool_call_success_and_call_log(server):
    r = server.handle(rpc("tools/call", {"name": "poll_jobs", "arguments": {"tag": "okta-reset"}}))
    assert r["result"]["isError"] is False
    assert r["result"]["structuredContent"]["job"]["number"] == "SCTASK0000001"
    assert r["result"]["structuredContent"] == json.loads(r["result"]["content"][0]["text"])
    log = server.call_log.read()
    assert log[0]["tool"] == "poll_jobs" and log[0]["args"] == {"tag": "okta-reset"}


def test_tool_error_is_a_tool_result(server):
    r = server.handle(rpc("tools/call", {"name": "complete_job", "arguments": {"task": "SCTASK0000001", "notes": "x"}}))
    assert r["result"]["isError"] is True
    assert r["result"]["structuredContent"]["error"]["code"] == "not_claimed"
    assert r["result"]["content"][0]["text"].startswith("not_claimed: ")


def test_unexpected_failure_hides_details():
    class Broken:
        def tools(self):
            return []

        def call(self, name, args):
            raise RuntimeError("secret detail")
    r = Server(Broken()).handle(rpc("tools/call", {"name": "x", "arguments": {}}))
    assert r["result"]["isError"] is True
    assert r["result"]["structuredContent"]["error"]["code"] == "internal_error"
    assert "secret detail" not in json.dumps(r)


def test_protocol_errors(server):
    assert server.handle(rpc("resources/list"))["error"]["code"] == -32601
    assert server.handle({"id": 3, "method": "tools/list"})["error"]["code"] == -32600
    assert server.handle({"id": 3, "method": "tools/list"})["id"] == 3


# --- build_server -----------------------------------------------------------------------------------------------

def test_build_server_mock_jobs(app_dir):
    s = build_server(Config.mock(), "jobs", app_dir)
    r = s.handle(rpc("tools/call", {"name": "poll_jobs", "arguments": {}}))
    assert r["result"]["structuredContent"]["job"]["number"] == "SCTASK0000101"


def test_build_server_deploy_for_a_dev_instance(app_dir):
    s = build_server(Config.mock(), "deploy", app_dir)
    assert [t["name"] for t in s.handle(rpc("tools/list"))["result"]["tools"]] == ["install_app"]
    r = s.handle(rpc("tools/call", {"name": "install_app", "arguments": {}}))
    assert r["result"]["structuredContent"]["error"]["code"] == "not_allowed"


def test_deploy_calls_are_never_logged_but_mock_job_calls_are(app_dir):
    build_server(Config.mock(), "deploy", app_dir).handle(rpc("tools/call", {"name": "install_app", "arguments": {}}))
    assert not (app_dir / "log" / "calls.jsonl").exists()
    build_server(Config.mock(), "jobs", app_dir).handle(rpc("tools/call", {"name": "poll_jobs", "arguments": {}}))
    assert (app_dir / "log" / "calls.jsonl").exists()


# --- request guard ----------------------------------------------------------------------------------------------

@pytest.mark.parametrize("method,origin,ctype,expected", [
    ("POST", None, "application/json", None),
    ("POST", "", "application/json; charset=utf-8", None),
    ("POST", "http://localhost:5173", "application/json", None),
    ("POST", "http://127.0.0.1", "application/json", None),
    ("POST", "http://[::1]:3000", "application/json", None),
    ("GET", None, "application/json", 405),
    ("POST", "https://evil.example", "application/json", 403),
    ("POST", "null", "application/json", 403),
    ("POST", None, "text/plain", 415),
    ("POST", None, None, 415),
])
def test_request_guard(method, origin, ctype, expected):
    r = guard.check(method, origin, ctype)
    assert (r[0] if r else None) == expected


# --- HTTP -------------------------------------------------------------------------------------------------------

@pytest.fixture
def client(app_dir):
    return TestClient(create_app({"SN_INSTANCE": "mock"}, app_dir))


@pytest.mark.parametrize("path", ["/", "/mcp", "/jobs", "/jobs/mcp"])
def test_mock_jobs_over_http(client, path):
    r = client.post(path, json=rpc("tools/call", {"name": "poll_jobs", "arguments": {}}))
    assert r.status_code == 200
    assert r.json()["result"]["structuredContent"]["job"]["number"] == "SCTASK0000101"


def test_mock_remembers_a_claim_across_requests_until_reset(client, app_dir):
    client.post("/mcp", json=rpc("tools/call", {"name": "claim_job", "arguments": {"task": "SCTASK0000101"}}))
    nxt = client.post("/mcp", json=rpc("tools/call", {"name": "poll_jobs", "arguments": {}})).json()
    assert nxt["result"]["structuredContent"]["job"]["number"] == "SCTASK0000102"
    FixtureBackend.reset_state(app_dir / "var" / "mock-state.json")
    again = client.post("/mcp", json=rpc("tools/call", {"name": "poll_jobs", "arguments": {}})).json()
    assert again["result"]["structuredContent"]["job"]["number"] == "SCTASK0000101"


def test_deploy_route(client):
    r = client.post("/deploy/mcp", json=rpc("tools/list"))
    assert [t["name"] for t in r.json()["result"]["tools"]] == ["install_app"]


def test_notification_is_accepted_without_a_body(client):
    r = client.post("/mcp", json={"jsonrpc": "2.0", "method": "notifications/initialized"})
    assert r.status_code == 202 and r.content == b""


def test_http_refusals(client):
    assert client.get("/mcp").status_code == 405
    assert client.post("/mcp", json=rpc("ping"), headers={"Origin": "https://evil.example"}).status_code == 403
    assert client.post("/mcp", content=json.dumps(rpc("ping")), headers={"Content-Type": "text/plain"}).status_code == 415
    r = client.post("/mcp", content="not json", headers=JSON)
    assert r.json()["error"]["code"] == -32700
    assert client.post("/mcp", content="[1]", headers=JSON).json()["error"]["code"] == -32600


def test_a_bad_setting_is_answered_on_every_request(app_dir):
    c = TestClient(create_app({"SN_INSTANCE": "https://x.service-now.com"}, app_dir))
    r = c.post("/mcp", json=rpc("initialize", req_id=9)).json()
    assert r["id"] == 9 and r["error"]["code"] == -32000
    assert r["error"]["message"].startswith("bad_config: missing SN_CLIENT_ID")


def test_deploy_reads_the_bearer_token_from_the_request(app_dir):
    c = TestClient(create_app({"SN_INSTANCE": "mock", "SN_DEPLOY_TOKEN": "tok"}, app_dir))
    body = rpc("tools/call", {"name": "install_app", "arguments": {"scope": "x_1_a", "files": {"package.json": "{}"}}})
    no = c.post("/deploy", json=body).json()["result"]["structuredContent"]["error"]
    assert no["code"] == "not_allowed" and "Bearer" in no["message"]
    yes = c.post("/deploy", json=body, headers={"Authorization": "Bearer tok"}).json()["result"]["structuredContent"]["error"]
    assert yes["code"] == "not_allowed" and "SN_INSTALL_USER" in yes["message"]   # past the token: the mock has no install user
