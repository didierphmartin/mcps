import base64

from graph import GraphClient
from tests.test_folders import SITE, service


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


def upload(svc, folder="Alice/mail1", name="a.pdf", data=b"%PDF-1", **kw):
    return svc.upload_file("key-1", {"folder": folder, "name": name, "base64": b64(data), **kw})


def test_small_upload_single_put(mock, http, cfg):
    drive = mock.add_library(SITE, "Documents")
    r = upload(service(mock, http, cfg), data=b"hello")
    assert r["path"] == "Alice/mail1/a.pdf" and r["size"] == 5 and r["id"] and r["web_url"]
    assert mock.files(drive) == {"Alice/mail1/a.pdf": b"hello"}
    puts = [p for m, p in mock.requests if m == "PUT"]
    assert len(puts) == 1 and puts[0].endswith("/Alice/mail1/a.pdf:/content?@microsoft.graph.conflictBehavior=rename")


def test_large_upload_uses_session_in_chunks(mock, http, cfg):
    drive = mock.add_library(SITE, "Documents")
    data = bytes(i % 251 for i in range(5 * 1024 * 1024))
    r = upload(service(mock, http, cfg), data=data)
    assert r["path"] == "Alice/mail1/a.pdf" and r["size"] == len(data)
    assert mock.files(drive)["Alice/mail1/a.pdf"] == data
    assert any(m == "POST" and p.endswith(":/createUploadSession") for m, p in mock.requests)
    chunks = [h for (m, p), h in zip(mock.requests, mock.headers) if m == "PUT" and "upload" in p]
    assert len(chunks) == 2
    assert all("authorization" not in h for h in chunks)
    assert chunks[0]["content-range"] == f"bytes 0-3276799/{len(data)}"
    assert chunks[1]["content-range"] == f"bytes 3276800-{len(data) - 1}/{len(data)}"
    assert mock.session_conflicts == ["rename"]


def test_exactly_4_mib_is_a_single_put(mock, http, cfg):
    mock.add_library(SITE, "Documents")
    upload(service(mock, http, cfg), data=b"x" * (4 * 1024 * 1024))
    assert not any(p.endswith(":/createUploadSession") for _, p in mock.requests)


def test_conflict_rename_keeps_both(mock, http, cfg):
    drive = mock.add_library(SITE, "Documents")
    svc = service(mock, http, cfg)
    first, second = upload(svc, data=b"one"), upload(svc, data=b"two")
    assert first["path"] == "Alice/mail1/a.pdf" and second["path"] == "Alice/mail1/a 1.pdf"
    assert mock.files(drive) == {"Alice/mail1/a.pdf": b"one", "Alice/mail1/a 1.pdf": b"two"}


def test_conflict_fail_reports_error_and_keeps_original(mock, http, cfg):
    drive = mock.add_library(SITE, "Documents")
    svc = service(mock, http, cfg)
    upload(svc, data=b"one")
    r = upload(svc, data=b"two", conflict="fail")
    assert r["error"] == "graph_error" and "409" in r["message"]
    assert mock.files(drive) == {"Alice/mail1/a.pdf": b"one"}


def test_large_conflict_fail_sends_fail_in_session(mock, http, cfg):
    mock.add_library(SITE, "Documents")
    svc = service(mock, http, cfg)
    big = b"y" * (4 * 1024 * 1024 + 1)
    upload(svc, data=big)
    assert upload(svc, data=big, conflict="fail")["error"] == "graph_error"
    assert mock.session_conflicts == ["rename", "fail"]


def test_bad_base64_is_invalid_argument(mock, http, cfg):
    mock.add_library(SITE, "Documents")
    svc = service(mock, http, cfg)
    for bad in ("not base64!!", 12):
        assert svc.upload_file("key-1", {"folder": "a", "name": "x", "base64": bad})["error"] == "invalid_argument"
    assert svc.upload_file("key-1", {"folder": "a", "name": "x", "base64": "AAAA", "conflict": "replace"})["error"] == "invalid_argument"
    assert svc.upload_file("key-1", {"folder": "a", "base64": "AAAA"})["error"] == "invalid_argument"
    assert not any(m == "PUT" for m, _ in mock.requests)


def test_name_is_made_safe_and_root_folder_allowed(mock, http, cfg):
    drive = mock.add_library(SITE, "Documents")
    r = upload(service(mock, http, cfg), folder="", name="a/b: c.txt", data=b"z")
    assert r["path"] == "ab c.txt" and mock.files(drive) == {"ab c.txt": b"z"}


def test_403_is_forbidden(mock, http, cfg):
    mock.add_library(SITE, "Documents")
    svc = service(mock, http, cfg)
    mock.forbid = True
    assert upload(svc)["error"] == "forbidden"


BIG = b"b" * (5 * 1024 * 1024)


def test_chunk_failures_are_sanitized_and_store_nothing(mock, http, cfg):
    drive = mock.add_library(SITE, "Documents")
    svc = service(mock, http, cfg)
    for status in (404, 416):
        mock.chunk_fault, mock._chunks = (2, status), 0
        r = upload(svc, data=BIG)
        assert r["error"] == "graph_error" and f"HTTP {status}" in r["message"]
        assert "upload.mock" not in r["message"] and "session-" not in r["message"]
        assert mock.files(drive) == {}


def test_chunk_401_is_graph_error_without_token_refresh(mock, http, cfg):
    mock.add_library(SITE, "Documents")
    svc = service(mock, http, cfg)
    mock.chunk_fault = (1, 401)
    before = len([p for _, p in mock.requests if p.endswith("/token")])
    r = upload(svc, data=BIG)
    assert r["error"] == "graph_error" and "HTTP 401" in r["message"]
    assert len([p for _, p in mock.requests if p.endswith("/token")]) == before + 1   # graph_for builds a fresh TokenSource per tool call: one fetch; a 401 refresh would add a second
    assert len([1 for (m, p) in mock.requests if m == "PUT" and "/upload/" in p]) == 1


def test_exact_multiple_of_chunk_round_trips(mock, http, cfg):
    drive = mock.add_library(SITE, "Documents")
    data = bytes(i % 241 for i in range(2 * 3276800))
    r = upload(service(mock, http, cfg), data=data)
    assert r["size"] == len(data) and mock.files(drive)["Alice/mail1/a.pdf"] == data


def test_chunk_429_then_success_completes(mock, http, cfg):
    drive = mock.add_library(SITE, "Documents")
    mock.chunk_fault = (1, 429)
    r = upload(service(mock, http, cfg), data=BIG)
    assert r["size"] == len(BIG) and mock.files(drive)["Alice/mail1/a.pdf"] == BIG


def test_chunk_repeated_429_is_throttled_without_url(mock, http, cfg):
    drive = mock.add_library(SITE, "Documents")
    mock.chunk_fault = (1, 429, 2)
    r = upload(service(mock, http, cfg), data=BIG)
    assert r["error"] == "throttled" and "upload.mock" not in r["message"] and "session-" not in r["message"]
    assert mock.files(drive) == {}
