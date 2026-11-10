import os
import pytest
from sources.base import PathOutsideRoot, FileDescriptor
from sources.local import LocalBlobSource
from parsing.types import suffixes_for


@pytest.fixture
def tree(tmp_path):
    (tmp_path / "a.pdf").write_bytes(b"%PDF-1.4")
    (tmp_path / "b.txt").write_text("hi")
    (tmp_path / ".hidden.txt").write_text("nope")
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "c.txt").write_text("deep")
    (sub / "skip.png").write_bytes(b"x")
    return tmp_path


def test_enumerate_recursive_flatten_files_only(tree):
    src = LocalBlobSource([str(tree)])
    descs, _ = src.enumerate(None, {"path": str(tree)}, suffixes_for(None))
    names = sorted(d.name for d in descs)
    assert names == ["a.pdf", "b.txt", "c.txt"]  # recursive, dotfile + png excluded
    # ids are absolute paths
    assert all(os.path.isabs(d.id) for d in descs)


def test_enumerate_type_filter(tree):
    src = LocalBlobSource([str(tree)])
    descs, _ = src.enumerate(None, {"path": str(tree)}, suffixes_for(["text"]))
    assert sorted(d.name for d in descs) == ["b.txt", "c.txt"]


def test_enumerate_single_file(tree):
    src = LocalBlobSource([str(tree)])
    descs, _ = src.enumerate(None, {"path": str(tree / "b.txt")}, suffixes_for(None))
    assert [d.name for d in descs] == ["b.txt"]


def test_read_bytes(tree):
    src = LocalBlobSource([str(tree)])
    assert src.read_bytes(None, str(tree / "b.txt")) == b"hi"


def test_path_outside_root_rejected(tree):
    src = LocalBlobSource([str(tree / "sub")])  # only sub/ allowed
    with pytest.raises(PathOutsideRoot):
        src.enumerate(None, {"path": str(tree)}, suffixes_for(None))  # noqa: must not unpack — raises
    with pytest.raises(PathOutsideRoot):
        src.read_bytes(None, str(tree / "b.txt"))


def test_enumerate_order_is_deterministic_and_sorted(tmp_path):
    """enumerate() returns a stable sorted list regardless of filesystem order."""
    # Create files whose glob order could be non-alphabetical
    (tmp_path / "z.txt").write_text("z")
    (tmp_path / "a.txt").write_text("a")
    (tmp_path / "m.txt").write_text("m")
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "b.txt").write_text("b")
    src = LocalBlobSource([str(tmp_path)])
    descs1, _ = src.enumerate(None, {"path": str(tmp_path)}, suffixes_for(None))
    descs2, _ = src.enumerate(None, {"path": str(tmp_path)}, suffixes_for(None))
    ids1 = [d.id for d in descs1]
    ids2 = [d.id for d in descs2]
    # Both calls return identical order
    assert ids1 == ids2
    # That order equals the sorted order
    assert ids1 == sorted(ids1)


def test_enumerate_uppercase_extension_found(tmp_path):
    """Files with uppercase extensions (e.g. .PDF) are found when filtering by pdf."""
    (tmp_path / "UPPER.PDF").write_bytes(b"%PDF-1.4")
    (tmp_path / "lower.pdf").write_bytes(b"%PDF-1.4")
    (tmp_path / "other.txt").write_text("hello")
    src = LocalBlobSource([str(tmp_path)])
    descs, _ = src.enumerate(None, {"path": str(tmp_path)}, suffixes_for(["pdf"]))
    names = {d.name for d in descs}
    assert "UPPER.PDF" in names
    assert "lower.pdf" in names
    assert "other.txt" not in names


def test_connect_is_noop(tree):
    assert LocalBlobSource([str(tree)]).connect({}) is None


def test_test_connection_ok_and_outside(tree):
    src = LocalBlobSource([str(tree)])
    assert src.test_connection({}, {"path": str(tree)})["ok"] is True
    bad = src.test_connection({}, {"path": str(tree.parent / "nope")})
    assert bad["ok"] is False
