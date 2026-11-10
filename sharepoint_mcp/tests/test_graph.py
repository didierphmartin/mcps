import httpx
import pytest

from auth import Auth
from graph import GraphClient, GraphError, StaticToken, TokenSource
from store import Store


def connected(mock, http, cfg):
    """A stored connection whose refresh token the mock knows."""
    tokens = mock._tokens_response().json()
    store = Store(cfg.db_path, cfg.secret_key)
    store.save_connection("key-1", mock.account, mock.tenant, tokens["refresh_token"])
    return store, TokenSource(Auth(http, cfg), store, "key-1")


def test_get_with_static_token(mock, http, cfg):
    token = mock._tokens_response().json()["access_token"]
    me = GraphClient(http, cfg.graph_base, StaticToken(token)).get("/me")
    assert me["mail"] == "me@contoso.com"


def test_token_source_refreshes_and_rotates(mock, http, cfg):
    store, ts = connected(mock, http, cfg)
    old_rt = store.connection("key-1")["refresh_token"]
    g = GraphClient(http, cfg.graph_base, ts)
    assert g.get("/me")["mail"] == "me@contoso.com"
    assert store.connection("key-1")["refresh_token"] != old_rt   # rotated token saved


def test_401_refreshes_once(mock, http, cfg):
    _, ts = connected(mock, http, cfg)
    g = GraphClient(http, cfg.graph_base, ts)
    g.get("/me")
    mock.expire_access_tokens()
    assert g.get("/me")["mail"] == "me@contoso.com"


def test_revoked_refresh_is_reconnect_needed(mock, http, cfg):
    _, ts = connected(mock, http, cfg)
    mock.revoke_refresh()
    with pytest.raises(GraphError) as e:
        GraphClient(http, cfg.graph_base, ts).get("/me")
    assert e.value.code == "reconnect_needed"


def test_unknown_connection_is_reconnect_needed(mock, http, cfg):
    ts = TokenSource(Auth(http, cfg), Store(cfg.db_path, cfg.secret_key), "never-connected")
    with pytest.raises(GraphError, match="reconnect_needed"):
        GraphClient(http, cfg.graph_base, ts).get("/me")


def test_429_waits_once_then_throttled(mock, http, cfg):
    token = mock._tokens_response().json()["access_token"]
    slept = []
    g = GraphClient(http, cfg.graph_base, StaticToken(token), sleep=slept.append)
    mock.throttle_next = 1
    assert g.get("/me")["mail"]
    assert slept == [2.0]
    mock.throttle_next = 2
    with pytest.raises(GraphError, match="throttled"):
        g.get("/me")



def test_put_bytes_sends_the_content_and_headers(mock, http, cfg):
    seen = []
    def handler(request):
        seen.append((request.method, request.content, request.headers.get("content-range"), request.headers.get("authorization")))
        return httpx.Response(200, json={"id": "item-1"}) if request.method == "PUT" else mock.handler(request)
    g = GraphClient(httpx.Client(transport=httpx.MockTransport(handler)), cfg.graph_base, StaticToken("tok"))
    out = g.put_bytes("https://upload.example/session", b"abc", {"Content-Range": "bytes 0-2/3"})
    assert out == {"id": "item-1"}
    assert seen == [("PUT", b"abc", "bytes 0-2/3", "Bearer tok")]


def test_403_names_the_permission(mock, http, cfg):
    token = mock._tokens_response().json()["access_token"]
    mock.forbid = True
    with pytest.raises(GraphError) as e:
        GraphClient(http, cfg.graph_base, StaticToken(token)).get("/me")
    assert e.value.code == "forbidden" and "Sites.ReadWrite.All" in e.value.message
