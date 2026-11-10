from __future__ import annotations

TYPE_SUFFIXES: dict[str, list[str]] = {
    "pdf": [".pdf"],
    "word": [".docx", ".doc"],
    "text": [".txt"],
    "csv": [".csv"],
    "html": [".html", ".htm"],
}

ALL_SUFFIXES: list[str] = [s for sl in TYPE_SUFFIXES.values() for s in sl]


def suffixes_for(types: list[str] | None) -> list[str]:
    """Map ticked doc-types to file suffixes. Empty/None → all supported."""
    if not types:
        return list(ALL_SUFFIXES)
    out: list[str] = []
    for t in types:
        out.extend(TYPE_SUFFIXES.get(t, []))
    return out
