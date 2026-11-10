import pytest
from sources.cloud import CloudBlobSource
from sources.base import FileDescriptor


def test_scope_url_s3():
    src = CloudBlobSource("s3")
    assert src._scope_url({"bucket": "b", "prefix": "docs/"}) == "s3://b/docs"
    assert src._scope_url({"bucket": "b"}) == "s3://b"


def test_scope_url_azure_scheme():
    assert CloudBlobSource("azure")._scope_url({"bucket": "c"}) == "az://c"


def test_enumerate_streams_filters_sorts_caps_and_flags_truncation():
    src = CloudBlobSource("s3", max_files=2)
    items = [("s3://b/z.txt", False), ("s3://b/a.pdf", False),
             ("s3://b/skip.png", False), ("s3://b/c.txt", False)]
    class FakeConn:
        def CloudPath(self, u): return u
        def _list_dir(self, root, recursive): return iter(items)
    out, truncated = src.enumerate(FakeConn(), {"bucket": "b"}, [".pdf", ".txt"])
    assert [d.id for d in out] == ["s3://b/a.pdf", "s3://b/z.txt"]  # z,a captured; png filtered; sorted
    assert truncated is True  # c.txt is a 3rd match beyond cap=2


def test_enumerate_not_truncated_when_under_cap():
    src = CloudBlobSource("s3", max_files=10)
    items = [("s3://b/a.txt", False), ("s3://b/sub", True), ("s3://b/b.txt", False)]
    class FakeConn:
        def CloudPath(self, u): return u
        def _list_dir(self, root, recursive): return iter(items)
    out, truncated = src.enumerate(FakeConn(), {"bucket": "b"}, [".txt"])
    assert [d.id for d in out] == ["s3://b/a.txt", "s3://b/b.txt"]  # dir skipped
    assert truncated is False


def test_unknown_provider_name_raises():
    with pytest.raises(KeyError):
        CloudBlobSource("dropbox")._scheme  # not in Phase 1 set
