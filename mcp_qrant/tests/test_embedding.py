from embedding import catalog

def test_catalog_shape():
    cat = {e["id"]: e for e in catalog()}
    assert "openai:text-embedding-3-small" in cat
    assert cat["openai:text-embedding-3-small"]["requires_credentials"] is True
    assert cat["openai:text-embedding-3-small"]["dimensions"] == 1536
    assert any(not e["requires_credentials"] for e in catalog())   # at least one local
    assert all({"id","label","provider","dimensions","requires_credentials"} <= set(e) for e in catalog())
