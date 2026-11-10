from __future__ import annotations

import json
import os
from dataclasses import dataclass

VALID_KINDS = {"object_store", "drive", "web", "knowledge_store"}
VALID_AUTH = {"none", "api_key", "connection_string", "oauth2", "service_account_json"}

_REQUIRED = [
    "name", "label", "kind", "description", "enumerable", "recursive",
    "scope_schema", "auth_method", "credential_fields", "default_formats",
    "pip_packages", "system_deps",
]


class DescriptorError(Exception):
    """A provider descriptor is malformed."""


@dataclass
class ProviderDescriptor:
    name: str
    label: str
    kind: str
    description: str
    enumerable: bool
    recursive: bool
    scope_schema: dict
    auth_method: str
    credential_fields: list[dict]
    default_formats: list[str]
    pip_packages: list[str]
    system_deps: bool


def _validate(obj: dict, filename: str) -> ProviderDescriptor:
    missing = [k for k in _REQUIRED if k not in obj]
    if missing:
        raise DescriptorError(f"{filename}: missing fields {missing}")
    if obj["kind"] not in VALID_KINDS:
        raise DescriptorError(f"{filename}: invalid kind '{obj['kind']}'")
    if obj["auth_method"] not in VALID_AUTH:
        raise DescriptorError(f"{filename}: invalid auth_method '{obj['auth_method']}'")
    expected = os.path.splitext(os.path.basename(filename))[0]
    if obj["name"] != expected:
        raise DescriptorError(f"{filename}: name '{obj['name']}' must equal filename '{expected}'")
    return ProviderDescriptor(**{k: obj[k] for k in _REQUIRED})


def load_descriptors(dir_path: str) -> dict[str, ProviderDescriptor]:
    out: dict[str, ProviderDescriptor] = {}
    for fn in sorted(os.listdir(dir_path)):
        if not fn.endswith(".json"):
            continue
        path = os.path.join(dir_path, fn)
        try:
            with open(path, encoding="utf-8") as fh:
                obj = json.load(fh)
        except json.JSONDecodeError as e:
            raise DescriptorError(f"{fn}: invalid JSON: {e}") from e
        desc = _validate(obj, fn)
        out[desc.name] = desc
    return out
