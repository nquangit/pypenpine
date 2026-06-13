"""Context: a thread-safe key/value bus shared across identities."""
from __future__ import annotations

import threading

from penpine.data.exceptions import DataError


class Context:
    def __init__(self, initial: dict | None = None):
        self._data = dict(initial or {})
        self._lock = threading.Lock()

    def get(self, key, default=None):
        with self._lock:
            return self._data.get(key, default)

    def set(self, key, value) -> None:
        with self._lock:
            self._data[key] = value

    def has(self, key) -> bool:
        with self._lock:
            return key in self._data

    def require(self, key):
        with self._lock:
            if key not in self._data:
                raise DataError(f"context key not found: {key!r}")
            return self._data[key]

    def update(self, mapping) -> None:
        with self._lock:
            self._data.update(mapping)

    def keys(self) -> list:
        with self._lock:
            return list(self._data.keys())

    def to_dict(self) -> dict:
        with self._lock:
            return dict(self._data)

    def namespace(self, prefix: str) -> "NamespacedView":
        return NamespacedView(self, prefix)


class NamespacedView:
    def __init__(self, context: Context, prefix: str):
        self._ctx = context
        self._prefix = prefix

    def _key(self, key: str) -> str:
        return f"{self._prefix}.{key}"

    def get(self, key, default=None):
        return self._ctx.get(self._key(key), default)

    def set(self, key, value) -> None:
        self._ctx.set(self._key(key), value)

    def has(self, key) -> bool:
        return self._ctx.has(self._key(key))

    def require(self, key):
        return self._ctx.require(self._key(key))
