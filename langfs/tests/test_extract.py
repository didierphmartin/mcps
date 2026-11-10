import pytest
from parsing.extract import extract_text, UnsupportedType


def test_txt_passthrough():
    assert extract_text("a.txt", b"hello world") == "hello world"


def test_csv_passthrough():
    assert extract_text("a.csv", b"x,y\n1,2") == "x,y\n1,2"


def test_html_to_text():
    out = extract_text("a.html", b"<h1>Title</h1><p>Body</p><script>x=1</script>")
    assert "Title" in out and "Body" in out
    assert "x=1" not in out  # script stripped


def test_docx_extracts_text(tmp_path):
    # build a minimal .docx with python (docx2txt reads the zip)
    import docx
    p = tmp_path / "d.docx"
    document = docx.Document()
    document.add_paragraph("Hello from docx")
    document.save(p)
    assert "Hello from docx" in extract_text("d.docx", p.read_bytes())


def test_unsupported_raises():
    with pytest.raises(UnsupportedType):
        extract_text("a.png", b"\x89PNG")


def test_htm_extension_extracts_text():
    out = extract_text("a.htm", b"<p>Hi</p>")
    assert "Hi" in out


def test_no_extension_raises_unsupported():
    with pytest.raises(UnsupportedType):
        extract_text("noext", b"data")


def test_mime_used_when_no_suffix():
    assert extract_text("noext", b"hello", mime="text/plain") == "hello"
    assert "Hi" in extract_text("page", b"<p>Hi</p>", mime="text/html")


def test_mime_ignored_when_suffix_present():
    # suffix wins; a .txt with an html mime is still treated as text
    assert extract_text("a.txt", b"<p>x</p>", mime="text/html") == "<p>x</p>"


def test_no_suffix_no_mime_raises():
    with pytest.raises(UnsupportedType):
        extract_text("noext", b"data")
