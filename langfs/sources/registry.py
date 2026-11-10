from __future__ import annotations

import importlib.util

from config import AppConfig
from descriptors import ProviderDescriptor, load_descriptors
from sources.base import BlobSource
from sources.cloud import CloudBlobSource
from sources.local import LocalBlobSource

_CLOUD = {"s3", "gcs", "azure"}
_FUNCTIONAL = {"local"} | _CLOUD  # providers that have a source implementation


def _available(desc: ProviderDescriptor) -> bool:
    if desc.name not in _FUNCTIONAL:
        return False  # descriptor-only (default package, source lands in a later phase)
    if desc.name in _CLOUD:
        return importlib.util.find_spec("cloudpathlib") is not None
    return True  # local


def _build_one(desc: ProviderDescriptor, cfg: AppConfig) -> BlobSource:
    if desc.name == "local":
        return LocalBlobSource(cfg.allowed_roots)
    if desc.name in _CLOUD:
        return CloudBlobSource(desc.name, description=desc.description)
    raise ValueError(f"no source implementation for provider '{desc.name}'")


def build_registry(cfg: AppConfig) -> dict[str, BlobSource]:
    descs = load_descriptors(cfg.providers_dir)
    return {name: _build_one(d, cfg) for name, d in descs.items() if _available(d)}


def providers_payload(cfg: AppConfig) -> list[dict]:
    descs = load_descriptors(cfg.providers_dir)
    out = []
    for d in descs.values():
        out.append({
            "name": d.name, "label": d.label, "kind": d.kind, "description": d.description,
            "auth_method": d.auth_method, "credential_fields": d.credential_fields,
            "scope_schema": d.scope_schema, "default_formats": d.default_formats,
            "requires_credentials": d.auth_method != "none",
            "available": _available(d),
        })
    return out
