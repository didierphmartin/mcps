from config import AppConfig
from sources.registry import build_registry, providers_payload
from sources.local import LocalBlobSource
from sources.cloud import CloudBlobSource


def _cfg(tmp_path):
    return AppConfig(allowed_roots=[str(tmp_path)])  # providers_dir defaults to packaged dir


def test_registry_builds_all_descriptor_providers(tmp_path):
    reg = build_registry(_cfg(tmp_path))
    assert set(reg) == {"local", "s3", "gcs", "azure"}
    assert isinstance(reg["local"], LocalBlobSource)
    assert isinstance(reg["s3"], CloudBlobSource)


def test_payload_carries_schema_for_ui(tmp_path):
    payload = {p["name"]: p for p in providers_payload(_cfg(tmp_path))}
    s3 = payload["s3"]
    assert s3["auth_method"] == "api_key"
    assert any(f["name"] == "access_key" for f in s3["credential_fields"])
    assert s3["scope_schema"]["fields"][0]["name"] == "bucket"
    assert s3["requires_credentials"] is True
    assert payload["local"]["requires_credentials"] is False
    assert s3["available"] is True  # cloudpathlib installed


def test_payload_lists_all_ten_providers(tmp_path):
    payload = {p["name"]: p for p in providers_payload(_cfg(tmp_path))}
    assert set(payload) == {"local", "s3", "gcs", "azure",
                            "drive", "onedrive", "sharepoint", "dropbox", "box", "github"}
    # the six not-yet-implemented providers are listed but unavailable
    for name in ("drive", "onedrive", "sharepoint", "dropbox", "box", "github"):
        assert payload[name]["available"] is False
    assert payload["local"]["available"] is True


def test_registry_builds_only_functional(tmp_path):
    reg = build_registry(_cfg(tmp_path))
    assert set(reg) == {"local", "s3", "gcs", "azure"}  # descriptor-only skipped, no raise
