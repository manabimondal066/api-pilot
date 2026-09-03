"""Storage factory — returns a configured Storage instance.

Usage::

    from app.storage.factory import get_storage

    storage = get_storage()
    await storage.write("ws/specs/file.json", content)

The function is cached with ``functools.lru_cache`` so tests can
monkeypatch the environment and then clear the cache::

    import os
    from app.storage.factory import get_storage

    os.environ["STORAGE_LOCAL_DIR"] = str(tmp_path)
    get_storage.cache_clear()
    storage = get_storage()
"""

from __future__ import annotations

import functools
import os
from pathlib import Path

from app.storage.base import Storage
from app.storage.local import LocalStorage


@functools.lru_cache(maxsize=1)
def get_storage() -> Storage:
    """Return the configured :class:`~app.storage.base.Storage` implementation.

    Environment variables
    ----------------------
    STORAGE_BACKEND
        Which backend to use.  Currently only ``"local"`` is supported.
        Default: ``"local"``
    STORAGE_LOCAL_DIR
        Base directory for :class:`~app.storage.local.LocalStorage`.
        Relative paths are resolved against the current working directory
        (typically ``backend/`` when running the server or tests).
        Default: ``"storage"``

    Raises:
        ValueError: for an unknown STORAGE_BACKEND value.
    """
    backend = os.getenv("STORAGE_BACKEND", "local")

    if backend == "local":
        local_dir = Path(os.getenv("STORAGE_LOCAL_DIR", "storage"))
        return LocalStorage(base_dir=local_dir)

    raise ValueError(
        f"Unknown STORAGE_BACKEND {backend!r}. Supported values: 'local'"
    )
