from __future__ import annotations

import logging
from pathlib import PurePosixPath

from cloudpathlib import AzureBlobClient, GSClient, S3Client

from sources.base import BlobSource, FileDescriptor

logger = logging.getLogger(__name__)

_SCHEME = {"s3": "s3", "gcs": "gs", "azure": "az"}


class CloudBlobSource:
    kind = "object_store"
    requires_credentials = True

    def __init__(self, name: str, *, description: str = "", max_files: int = 10_000) -> None:
        self.name = name
        self.description = description or f"{name} via cloudpathlib (paginated streaming)"
        self._scheme = _SCHEME[name]          # KeyError for non-Phase-1 providers
        self._max_files = max_files

    def _make_client(self, credentials: dict):
        if self._scheme == "s3":
            boto3_session = None
            if credentials.get("region"):
                import boto3
                boto3_session = boto3.Session(region_name=credentials["region"])
            return S3Client(
                aws_access_key_id=credentials.get("access_key"),
                aws_secret_access_key=credentials.get("secret_key"),
                aws_session_token=credentials.get("session_token") or None,
                endpoint_url=credentials.get("endpoint_url") or None,
                boto3_session=boto3_session,
            )
        if self._scheme == "gs":
            return GSClient(
                application_credentials=credentials.get("service_account_json") or None,
                project=credentials.get("project") or None,
            )
        if self._scheme == "az":
            return AzureBlobClient(
                connection_string=credentials.get("connection_string") or None,
                account_url=credentials.get("account_url") or None,
            )
        raise ValueError(f"unsupported scheme {self._scheme}")

    def _scope_url(self, scope: dict) -> str:
        bucket = str(scope["bucket"]).strip("/")
        prefix = str(scope.get("prefix") or "").strip("/")
        return f"{self._scheme}://{bucket}/{prefix}" if prefix else f"{self._scheme}://{bucket}"

    def connect(self, credentials: dict):
        return self._make_client(credentials)

    def test_connection(self, credentials: dict, scope: dict) -> dict:
        try:
            client = self._make_client(credentials)
            client.CloudPath(self._scope_url(scope)).exists()
            return {"ok": True}
        except Exception as e:  # noqa: BLE001 — surface any auth/scope failure to the UI
            return {"ok": False, "message": str(e)}

    def enumerate(self, connection, scope: dict, suffixes: list[str]) -> tuple[list[FileDescriptor], bool]:
        root = connection.CloudPath(self._scope_url(scope))
        wanted = {s.lower() for s in suffixes}
        out: list[FileDescriptor] = []
        truncated = False
        # _list_dir is cloudpathlib's paginated lister (yields (CloudPath, is_dir));
        # iterating + breaking early keeps memory/network bounded for huge buckets,
        # unlike CloudBlobLoader/CloudPath.glob which materializes the whole prefix.
        for path, is_dir in connection._list_dir(root, recursive=True):
            if is_dir:
                continue
            uri = str(path)
            name = PurePosixPath(uri).name
            if name.startswith("."):
                continue
            if wanted and PurePosixPath(name).suffix.lower() not in wanted:
                continue
            if len(out) >= self._max_files:
                truncated = True
                logger.warning(
                    "enumerate cap reached (%d) for %s; results truncated",
                    self._max_files, self._scope_url(scope),
                )
                break
            out.append(FileDescriptor(id=uri, name=name))
        out.sort(key=lambda d: d.id)
        return out, truncated

    def read_bytes(self, connection, file_id: str) -> bytes:
        return connection.CloudPath(file_id).read_bytes()


# Structural conformance check.
_: BlobSource = CloudBlobSource("s3")
