from __future__ import annotations

import asyncio
import base64
import mimetypes
import re
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

import boto3
from botocore.client import Config

from orchestrator.config.settings import StorageSettings


DATA_URL_RE = re.compile(r"^data:(image/[a-zA-Z0-9.+-]+);base64,(.+)$", re.S)


@dataclass(frozen=True)
class StoredImage:
    key: str
    image_url: str
    content_type: str
    size_bytes: int


@dataclass(frozen=True)
class StoredObject:
    key: str
    url: str
    content_type: str
    size_bytes: int


class R2ImageStore:
    def __init__(self, settings: StorageSettings) -> None:
        self.settings = settings
        self._client: Any | None = None

    @property
    def configured(self) -> bool:
        return bool(
            self.settings.r2_endpoint_url
            and self.settings.r2_bucket
            and self.settings.r2_access_key_id
            and self.settings.r2_secret_access_key
        )

    async def store_data_url(self, data_url: str, prefix: str = "input-images") -> StoredImage:
        if not self.configured:
            raise RuntimeError("R2 storage is not configured; cannot accept base64 image uploads safely")
        match = DATA_URL_RE.match(data_url.strip())
        if not match:
            raise ValueError("inputs.image_data_url must be a base64 data URL like data:image/png;base64,...")
        content_type = match.group(1)
        try:
            raw = base64.b64decode(match.group(2), validate=True)
        except Exception as exc:
            raise ValueError("inputs.image_data_url contains invalid base64 image data") from exc
        if not raw:
            raise ValueError("inputs.image_data_url is empty")
        suffix = mimetypes.guess_extension(content_type) or ".png"
        key = f"{prefix}/{uuid4().hex}{suffix}"
        await asyncio.to_thread(self._put_object, key, raw, content_type)
        return StoredImage(
            key=key,
            image_url=self._image_url(key),
            content_type=content_type,
            size_bytes=len(raw),
        )

    async def store_bytes(self, body: bytes, key: str, content_type: str) -> StoredObject:
        if not self.configured:
            raise RuntimeError("R2 storage is not configured")
        if not body:
            raise ValueError("object body is empty")
        await asyncio.to_thread(self._put_object, key, body, content_type)
        return StoredObject(
            key=key,
            url=self._image_url(key),
            content_type=content_type,
            size_bytes=len(body),
        )

    def _put_object(self, key: str, body: bytes, content_type: str) -> None:
        self._s3().put_object(
            Bucket=self.settings.r2_bucket,
            Key=key,
            Body=body,
            ContentType=content_type,
        )

    def _image_url(self, key: str) -> str:
        public_base_url = (self.settings.r2_public_base_url or "").strip()
        if public_base_url and not public_base_url.startswith("${"):
            return f"{public_base_url.rstrip('/')}/{key}"
        return self._s3().generate_presigned_url(
            "get_object",
            Params={"Bucket": self.settings.r2_bucket, "Key": key},
            ExpiresIn=604800,
        )

    def _s3(self):
        if self._client is None:
            self._client = boto3.client(
                "s3",
                endpoint_url=self.settings.r2_endpoint_url,
                aws_access_key_id=self.settings.r2_access_key_id,
                aws_secret_access_key=self.settings.r2_secret_access_key,
                region_name="auto",
                config=Config(signature_version="s3v4"),
            )
        return self._client
