"""Storage helpers for saving slide keyframe images."""

from __future__ import annotations

import os
import pathlib
import uuid
from dataclasses import dataclass
from typing import Optional

try:
    import boto3
    from botocore.exceptions import BotoCoreError, ClientError
except ImportError:  # pragma: no cover - boto3 optional at runtime
    boto3 = None
    BotoCoreError = ClientError = Exception  # type: ignore[assignment]


@dataclass
class StorageResult:
    url: str
    storage_key: str


class SlideStorage:
    """Persist slide keyframes either to S3 or the local filesystem."""

    def __init__(
        self,
        mode: str,
        base_url: str,
        local_dir: Optional[pathlib.Path] = None,
        s3_bucket: Optional[str] = None,
        s3_region: Optional[str] = None,
        s3_prefix: str = "slides",
    ) -> None:
        self.mode = mode
        self.base_url = base_url.rstrip("/")
        self.local_dir = local_dir
        self.s3_bucket = s3_bucket
        self.s3_region = s3_region
        self.s3_prefix = s3_prefix.strip("/")

        if self.mode == "local" and self.local_dir is not None:
            self.local_dir.mkdir(parents=True, exist_ok=True)

        if self.mode == "s3" and boto3 is None:
            raise RuntimeError("boto3 is required for S3 storage mode but is not installed.")

    @classmethod
    def from_env(cls) -> "SlideStorage":
        bucket = os.getenv("SLIDE_STORAGE_S3_BUCKET")
        if bucket:
            prefix = os.getenv("SLIDE_STORAGE_S3_PREFIX", "slides")
            region = os.getenv("SLIDE_STORAGE_S3_REGION")
            base_url = os.getenv("SLIDE_STORAGE_BASE_URL")
            if not base_url:
                if region:
                    base_url = f"https://{bucket}.s3.{region}.amazonaws.com/{prefix.strip('/') }"
                else:
                    base_url = f"https://{bucket}.s3.amazonaws.com/{prefix.strip('/') }"

            return cls(
                mode="s3",
                base_url=base_url,
                s3_bucket=bucket,
                s3_region=region,
                s3_prefix=prefix,
            )

        # Default to local directory under backend/slide_storage
        root = pathlib.Path(os.getenv("SLIDE_STORAGE_LOCAL_PATH", "slide_storage"))
        base_url = os.getenv("SLIDE_STORAGE_BASE_URL", root.resolve().as_uri())
        return cls(mode="local", base_url=base_url, local_dir=root)

    def store_image(self, payload: bytes, *, extension: str = "jpg", key: Optional[str] = None) -> StorageResult:
        storage_key = key or f"{uuid.uuid4().hex}.{extension}"

        if self.mode == "local":
            assert self.local_dir is not None  # for mypy
            destination = self.local_dir / storage_key
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(payload)
            url = f"{self.base_url}/{storage_key}"
            return StorageResult(url=url, storage_key=str(destination))

        if self.mode == "s3":
            assert boto3 is not None
            if not self.s3_bucket:
                raise RuntimeError("S3 bucket not configured for slide storage.")
            key_path = f"{self.s3_prefix}/{storage_key}" if self.s3_prefix else storage_key
            session_kwargs = {}
            if self.s3_region:
                session_kwargs["region_name"] = self.s3_region
            s3_client = boto3.client("s3", **session_kwargs)
            try:
                s3_client.put_object(
                    Bucket=self.s3_bucket,
                    Key=key_path,
                    Body=payload,
                    ContentType="image/jpeg" if extension.lower() in {"jpg", "jpeg"} else "image/png",
                    ACL="public-read",
                )
            except (ClientError, BotoCoreError) as exc:  # pragma: no cover - difficult to simulate
                raise RuntimeError(f"Failed to upload keyframe to S3: {exc}") from exc

            url = f"{self.base_url}/{storage_key}" if self.base_url else key_path
            return StorageResult(url=url, storage_key=key_path)

        raise RuntimeError(f"Unsupported storage mode: {self.mode}")
