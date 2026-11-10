import json
import pytest
from descriptors import load_descriptors, DescriptorError, ProviderDescriptor


def _write(d, name, obj):
    (d / f"{name}.json").write_text(json.dumps(obj))


def _valid(name="s3"):
    return {
        "name": name, "label": "Amazon S3", "kind": "object_store",
        "description": "x", "enumerable": True, "recursive": True,
        "scope_schema": {"fields": [{"name": "bucket", "label": "Bucket", "required": True}]},
        "auth_method": "api_key",
        "credential_fields": [{"name": "access_key", "label": "Key", "type": "text", "required": True}],
        "default_formats": ["pdf", "text"], "pip_packages": [], "system_deps": False,
    }


def test_loads_valid_descriptors(tmp_path):
    _write(tmp_path, "s3", _valid("s3"))
    _write(tmp_path, "local", {**_valid("local"), "auth_method": "none", "credential_fields": []})
    reg = load_descriptors(str(tmp_path))
    assert set(reg) == {"s3", "local"}
    assert isinstance(reg["s3"], ProviderDescriptor)
    assert reg["s3"].kind == "object_store"
    assert reg["local"].auth_method == "none"


def test_missing_required_field_raises(tmp_path):
    bad = _valid("s3"); del bad["auth_method"]
    _write(tmp_path, "s3", bad)
    with pytest.raises(DescriptorError):
        load_descriptors(str(tmp_path))


def test_bad_kind_raises(tmp_path):
    bad = _valid("s3"); bad["kind"] = "nonsense"
    _write(tmp_path, "s3", bad)
    with pytest.raises(DescriptorError):
        load_descriptors(str(tmp_path))


def test_name_must_match_filename(tmp_path):
    _write(tmp_path, "s3", _valid("DIFFERENT"))
    with pytest.raises(DescriptorError):
        load_descriptors(str(tmp_path))


def test_invalid_json_raises(tmp_path):
    (tmp_path / "s3.json").write_text("not json {")
    with pytest.raises(DescriptorError):
        load_descriptors(str(tmp_path))
