"""Report storage: Replit Object Storage in production, a local folder in development."""

from pathlib import Path
from typing import Protocol

from .config import Settings


class ReportStore(Protocol):
    def put_text(self, key: str, text: str) -> None: ...
    def get_text(self, key: str) -> str: ...
    def delete(self, key: str) -> None: ...


class LocalStore:
    def __init__(self, root: Path):
        self.root = root.resolve()

    def _path(self, key: str) -> Path:
        path = (self.root / key).resolve()
        if self.root not in path.parents:
            raise ValueError("invalid storage key")
        return path

    def put_text(self, key: str, text: str) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def get_text(self, key: str) -> str:
        return self._path(key).read_text(encoding="utf-8")

    def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)


class ReplitStore:
    def __init__(self, bucket_id: str | None = None):
        from replit.object_storage import Client

        self.client = Client(bucket_id=bucket_id) if bucket_id else Client()

    def put_text(self, key: str, text: str) -> None:
        self.client.upload_from_text(key, text)

    def get_text(self, key: str) -> str:
        return self.client.download_as_text(key)

    def delete(self, key: str) -> None:
        self.client.delete(key, ignore_not_found=True)


_store: ReportStore | None = None


def get_store(settings: Settings) -> ReportStore:
    global _store
    if _store is None:
        if settings.storage_mode == "replit":
            _store = ReplitStore(settings.storage_bucket)
        else:
            _store = LocalStore(settings.local_storage_dir)
    return _store


def set_store(store: ReportStore) -> None:
    global _store
    _store = store


def report_key(user_id: str, run_id: int) -> str:
    safe_user = "".join(ch for ch in user_id if ch.isalnum() or ch in "-_") or "user"
    return f"reports/{safe_user}/{run_id}.csv"
