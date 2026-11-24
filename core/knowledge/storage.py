"""Safe managed-file storage for original Knowledge sources."""
from __future__ import annotations

import hashlib
import os
import re
import tempfile
from pathlib import Path
from uuid import uuid4


class ManagedFileStorageError(ValueError):
    """Raised when a managed file operation is invalid or cannot be completed."""


class ManagedFileStorage:
    """Stores originals under opaque keys; user filenames never become filesystem paths."""

    def __init__(self, root: str | Path | None = None, *, max_bytes: int = 25 * 1024 * 1024) -> None:
        configured = root or os.getenv("LOCAL_AI_KNOWLEDGE_DIR", "data/knowledge")
        self.root = Path(configured).expanduser().resolve()
        self.max_bytes = max_bytes
        if max_bytes <= 0:
            raise ValueError("max_bytes must be positive")
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, storage_key: str) -> Path:
        if not re.fullmatch(r"[a-f0-9]{32}", storage_key or ""):
            raise ManagedFileStorageError("Invalid managed storage key")
        path = (self.root / storage_key).resolve()
        if self.root not in path.parents:
            raise ManagedFileStorageError("Managed storage path escaped its root")
        return path

    def store(self, content: bytes) -> tuple[str, int, str]:
        if not isinstance(content, bytes):
            raise ManagedFileStorageError("File content must be bytes")
        if not content or len(content) > self.max_bytes:
            raise ManagedFileStorageError("File is empty or exceeds the configured size limit")
        storage_key = uuid4().hex
        destination = self._path(storage_key)
        temporary_path: str | None = None
        try:
            with tempfile.NamedTemporaryFile(mode="wb", dir=self.root, prefix=".upload-", delete=False) as handle:
                temporary_path = handle.name
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_path, destination)
            return storage_key, len(content), hashlib.sha256(content).hexdigest()
        except OSError as exc:
            raise ManagedFileStorageError("Unable to persist managed file") from exc
        finally:
            if temporary_path and os.path.exists(temporary_path):
                try:
                    os.unlink(temporary_path)
                except OSError:
                    pass

    def read(self, storage_key: str) -> bytes:
        try:
            return self._path(storage_key).read_bytes()
        except FileNotFoundError as exc:
            raise ManagedFileStorageError("Managed file does not exist") from exc
        except OSError as exc:
            raise ManagedFileStorageError("Unable to read managed file") from exc

    def delete(self, storage_key: str) -> None:
        try:
            self._path(storage_key).unlink(missing_ok=True)
        except OSError as exc:
            raise ManagedFileStorageError("Unable to delete managed file") from exc
