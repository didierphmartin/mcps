from __future__ import annotations

import json
import os
from dataclasses import dataclass

_REQUIRED = ["name", "label", "description", "available", "embeds_internally", "connection_schema"]


class DescriptorError(Exception):
    """A provider descriptor is malformed."""


@dataclass
class ProviderDescriptor:
    name: str
    label: str
    description: str
    available: bool
    embeds_internally: bool
    connection_schema: dict


def _validate(obj: dict, fn: str) -> ProviderDescriptor:
    missing = [k for k in _REQUIRED if k not in obj]
    if missing:
        raise DescriptorError(f"{fn}: missing fields {missing}")
    expected = os.path.splitext(os.path.basename(fn))[0]
    if obj["name"] != expected:
        raise DescriptorError(f"{fn}: name '{obj['name']}' must equal filename '{expected}'")
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
        d = _validate(obj, fn)
        out[d.name] = d
    return out
