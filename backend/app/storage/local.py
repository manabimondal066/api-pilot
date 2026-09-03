"""Local filesystem storage implementation.

Files are stored under a configurable base directory.  The storage key is
used verbatim as a relative path beneath that directory.

Key format (callers are responsible for following this convention):
    {workspace_id}/{type}/{uuid}.{ext}
    e.g. 00000000-0000-0000-0000-000000000001/specs/abc123.json

Path safety: keys containing ``..`` segments or starting with an absolute
path prefix (``/`` or ``\\``) are rejected with ValueError.
"""

from __future__ import annotations

from pathlib import Path

import aiofiles
import aiofiles.os

from app.storage.base import StorageNotFoundError


class LocalStorage:
    """Stores files on the local filesystem under *base_dir*."""

    def __init__(self, base_dir: Path) -> None:
        self._base_dir = Path(base_dir)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _resolve(self, key: str) -> Path:
        """Map a storage key to an absolute path.

        Raises:
            ValueError: if the key contains ``..`` traversal segments or
                        starts with an absolute path prefix.
        """
        # Normalise path separators for the safety check
        normalised = key.replace("\\", "/")
        parts = normalised.split("/")

        if ".." in parts:
            raise ValueError(
                f"Unsafe storage key contains '..' traversal segment: {key!r}"
            )
        if key.startswith("/") or key.startswith("\\"):
            raise ValueError(
                f"Unsafe storage key is an absolute path: {key!r}"
            )
        return self._base_dir / key

    # ------------------------------------------------------------------
    # Storage interface
    # ------------------------------------------------------------------

    async def write(self, key: str, content: bytes) -> str:
        """Write *content* to storage under *key*.

        Parent directories are created automatically.
        Returns *key* unchanged.
        """
        path = self._resolve(key)
        await aiofiles.os.makedirs(str(path.parent), exist_ok=True)
        async with aiofiles.open(path, "wb") as fh:
            await fh.write(content)
        return key

    async def read(self, key: str) -> bytes:
        """Read and return bytes stored at *key*.

        Raises:
            StorageNotFoundError: if the key does not exist.
        """
        path = self._resolve(key)
        if not path.exists():
            raise StorageNotFoundError(f"Storage key not found: {key!r}")
        async with aiofiles.open(path, "rb") as fh:
            return await fh.read()

    async def exists(self, key: str) -> bool:
        """Return ``True`` if *key* exists on disk."""
        path = self._resolve(key)
        return path.exists()

    async def delete(self, key: str) -> None:
        """Delete *key* from disk.  Silently succeeds if already absent."""
        path = self._resolve(key)
        try:
            path.unlink()
        except FileNotFoundError:
            pass
