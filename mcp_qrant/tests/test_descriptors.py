import json, pytest
from descriptors import load_descriptors, DescriptorError, ProviderDescriptor

TEN = {"qdrant","pgvector","chroma","pinecone","milvus","weaviate","faiss","redis","elasticsearch","mongodb"}


def test_loads_ten(tmp_path):
    # copy the packaged descriptors into tmp to test the loader in isolation
    import os, shutil
    src = os.path.join(os.path.dirname(__file__), "..", "providers")
    for fn in os.listdir(src):
        if fn.endswith(".json"):
            shutil.copy(os.path.join(src, fn), tmp_path / fn)
    reg = load_descriptors(str(tmp_path))
    assert set(reg) == TEN
    assert reg["qdrant"].available is True and reg["qdrant"].embeds_internally is True
    assert reg["pgvector"].available is True and reg["pgvector"].embeds_internally is False
    assert all(reg[n].available is False for n in TEN - {"qdrant", "pgvector"})


def test_missing_field_raises(tmp_path):
    (tmp_path / "x.json").write_text(json.dumps({"name": "x"}))
    with pytest.raises(DescriptorError):
        load_descriptors(str(tmp_path))
