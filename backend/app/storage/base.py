"""Storage protocol and shared exceptions.

The Storage Protocol defines the interface every backend must implement.
Using typing.Protocol means callers only depend on the interface — concrete
implementations (LocalStorage, MinioStorage, …) are swappable without
changing any caller code.
"""

from typing import Protocol, runtime_checkable


class StorageNotFoundError(Exception):
    """Raised by Storage.read() when a requested key does not exist."""


@runtime_checkable
class Storage(Protocol):
    """Async storage interface.  All methods are coroutines."""

    async def write(self, key: str, content: bytes) -> str:
        """Store *content* under *key*.

        Creates any necessary parent structure.
        Returns the key (possibly normalised by the backend).
        """
        ...

    async def read(self, key: str) -> bytes:
        """Return the bytes stored at *key*.

        Raises:
            StorageNotFoundError: if the key does not exist.
        """
        ...

    async def exists(self, key: str) -> bool:
        """Return ``True`` if *key* exists in this storage backend."""
        ...

    async def delete(self, key: str) -> None:
        """Delete *key*.

        Idempotent — silently succeeds if the key is already absent.
        """
        ...
