"""Unit tests for LocalStorage.

All tests use pytest's tmp_path fixture for full isolation — no shared
state, no cleanup required.  The asyncio_mode = "auto" setting in
pyproject.toml means async test functions run automatically.
"""

from pathlib import Path

import pytest

from app.storage.base import StorageNotFoundError
from app.storage.local import LocalStorage


@pytest.fixture
def storage(tmp_path: Path) -> LocalStorage:
    """Return a LocalStorage instance rooted at a fresh temp directory."""
    return LocalStorage(base_dir=tmp_path)


# ---------------------------------------------------------------------------
# Happy-path tests
# ---------------------------------------------------------------------------


async def test_write_then_read(storage: LocalStorage) -> None:
    """Round-trip: what we write we should read back verbatim."""
    key = "workspace1/specs/abc.json"
    payload = b'{"hello": "world"}'

    returned_key = await storage.write(key, payload)
    assert returned_key == key

    data = await storage.read(key)
    assert data == payload


async def test_exists_true_and_false(storage: LocalStorage) -> None:
    """exists() returns False before write, True after."""
    key = "ws/uploads/file.bin"
    assert await storage.exists(key) is False

    await storage.write(key, b"\x00\x01\x02")
    assert await storage.exists(key) is True


async def test_delete_is_idempotent(storage: LocalStorage) -> None:
    """Deleting an existing key works; deleting it again does not raise."""
    key = "to_delete.txt"
    await storage.write(key, b"bye")

    await storage.delete(key)                 # first delete — key existed
    assert await storage.exists(key) is False

    await storage.delete(key)                 # second delete — key already gone
    # no exception raised ✓


async def test_creates_parent_dirs(storage: LocalStorage, tmp_path: Path) -> None:
    """write() must create arbitrarily deep parent directories."""
    key = "a/b/c/deeply_nested/file.bin"
    await storage.write(key, b"nested content")

    expected_path = tmp_path / "a" / "b" / "c" / "deeply_nested" / "file.bin"
    assert expected_path.exists()
    assert expected_path.read_bytes() == b"nested content"


# ---------------------------------------------------------------------------
# Error / safety tests
# ---------------------------------------------------------------------------


async def test_read_missing_raises(storage: LocalStorage) -> None:
    """Reading a key that was never written raises StorageNotFoundError."""
    with pytest.raises(StorageNotFoundError):
        await storage.read("does/not/exist.json")


async def test_rejects_dotdot_in_key(storage: LocalStorage) -> None:
    """Keys containing '..' traversal segments are rejected with ValueError."""
    with pytest.raises(ValueError, match=r"\.\."):
        await storage.write("a/../secret.txt", b"evil")


async def test_rejects_absolute_key(storage: LocalStorage) -> None:
    """Keys that start with '/' or '\\' are rejected with ValueError."""
    with pytest.raises(ValueError):
        await storage.write("/etc/passwd", b"evil")
