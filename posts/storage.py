"""Object storage for post bodies and images (S3 or any S3-compatible service)."""

import logging
import mimetypes
from pathlib import Path

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

logger = logging.getLogger(__name__)


class StorageError(Exception):
    pass


class NotFound(StorageError):
    pass


class MemoryStorage:
    """In-process store used by the test suite."""

    def __init__(self):
        self.objects = {}

    def put(self, key, data, content_type):
        self.objects[key] = (data, content_type)

    def get(self, key):
        try:
            return self.objects[key]
        except KeyError:
            raise NotFound(key)

    def delete(self, key):
        self.objects.pop(key, None)


class LocalStorage:
    """Plain files under LOCAL_STORAGE_PATH. Content type is derived from the key on read."""

    def __init__(self):
        self.root = Path(settings.LOCAL_STORAGE_PATH).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key):
        path = (self.root / key).resolve()
        if not path.is_relative_to(self.root):
            raise StorageError("invalid key")
        return path

    def put(self, key, data, content_type):
        path = self._path(key)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_name(path.name + ".tmp")
            tmp.write_bytes(data)
            tmp.replace(path)  # atomic, so readers never see a half-written post
        except OSError as exc:
            raise StorageError(str(exc)) from exc

    def get(self, key):
        path = self._path(key)
        try:
            data = path.read_bytes()
        except FileNotFoundError:
            raise NotFound(key)
        except OSError as exc:
            raise StorageError(str(exc)) from exc
        return data, mimetypes.guess_type(key)[0] or "application/octet-stream"

    def delete(self, key):
        try:
            self._path(key).unlink(missing_ok=True)
        except OSError as exc:
            raise StorageError(str(exc)) from exc


class S3Storage:
    def __init__(self):
        import boto3
        from botocore.config import Config

        self.bucket = settings.S3_BUCKET
        self._bucket_ready = False
        self.client = boto3.client(
            "s3",
            endpoint_url=settings.S3_ENDPOINT_URL,
            region_name=settings.S3_REGION,
            aws_access_key_id=settings.S3_ACCESS_KEY or None,
            aws_secret_access_key=settings.S3_SECRET_KEY or None,
            config=Config(
                signature_version="s3v4",
                s3={"addressing_style": "path"},
                connect_timeout=5,
                read_timeout=15,
                retries={"max_attempts": 2},
            ),
        )

    def _ensure_bucket(self):
        """Create the bucket on first write so a fresh S3-compatible server needs no setup."""
        from botocore.exceptions import ClientError

        if self._bucket_ready:
            return
        try:
            self.client.head_bucket(Bucket=self.bucket)
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") not in ("404", "NoSuchBucket", "NotFound"):
                raise
            self.client.create_bucket(Bucket=self.bucket)
        self._bucket_ready = True

    def put(self, key, data, content_type):
        from botocore.exceptions import BotoCoreError, ClientError

        try:
            self._ensure_bucket()
            self.client.put_object(Bucket=self.bucket, Key=key, Body=data, ContentType=content_type)
        except (BotoCoreError, ClientError) as exc:
            raise StorageError(str(exc)) from exc

    def get(self, key):
        from botocore.exceptions import BotoCoreError, ClientError

        try:
            obj = self.client.get_object(Bucket=self.bucket, Key=key)
            return obj["Body"].read(), obj.get("ContentType", "application/octet-stream")
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in ("NoSuchKey", "404"):
                raise NotFound(key) from exc
            raise StorageError(str(exc)) from exc
        except BotoCoreError as exc:
            raise StorageError(str(exc)) from exc

    def delete(self, key):
        from botocore.exceptions import BotoCoreError, ClientError

        try:
            self.client.delete_object(Bucket=self.bucket, Key=key)
        except (BotoCoreError, ClientError) as exc:
            raise StorageError(str(exc)) from exc


_instance = None


def get_storage():
    global _instance
    if _instance is None:
        backends = {"s3": S3Storage, "local": LocalStorage, "memory": MemoryStorage}
        try:
            _instance = backends[settings.STORAGE_BACKEND]()
        except KeyError:
            raise ImproperlyConfigured(f"STORAGE_BACKEND must be one of {', '.join(backends)}")
    return _instance


def get_body(post):
    try:
        return get_storage().get(post.body_key)[0].decode("utf-8")
    except NotFound:
        logger.warning("Body object missing for post %s (%s)", post.pk, post.body_key)
        return ""


def put_body(post, body):
    get_storage().put(post.body_key, body.encode("utf-8"), "text/markdown; charset=utf-8")
