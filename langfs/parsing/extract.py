from __future__ import annotations

import io
import os
import tempfile


class UnsupportedType(Exception):
    """Raised when a file's suffix has no text extractor."""


def _suffix(name: str) -> str:
    dot = name.rfind(".")
    return name[dot:].lower() if dot != -1 else ""


def _pdf(data: bytes) -> str:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    return "\n\n".join((page.extract_text() or "") for page in reader.pages).strip()


def _docx(data: bytes) -> str:
    import docx2txt

    # docx2txt needs a real path; write to a temp file.
    fd, path = tempfile.mkstemp(suffix=".docx")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        return (docx2txt.process(path) or "").strip()
    finally:
        os.unlink(path)


def _html(data: bytes) -> str:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(data, "html.parser")
    for tag in soup(["script", "style"]):
        tag.decompose()
    return soup.get_text(" ", strip=True)


def _plain(data: bytes) -> str:
    return data.decode("utf-8", errors="replace")


_DISPATCH = {
    ".pdf": _pdf,
    ".docx": _docx,
    ".doc": _docx,
    ".html": _html,
    ".htm": _html,
    ".txt": _plain,
    ".csv": _plain,
}


_MIME_SUFFIX = {
    "application/pdf": ".pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "text/html": ".html",
    "text/plain": ".txt",
    "text/csv": ".csv",
}


def extract_text(name: str, data: bytes, mime: str | None = None) -> str:
    suffix = _suffix(name)
    fn = _DISPATCH.get(suffix)
    if fn is None and mime:
        fn = _DISPATCH.get(_MIME_SUFFIX.get(mime, ""))
    if fn is None:
        raise UnsupportedType(f"no text extractor for '{name}' (mime={mime})")
    return fn(data)
