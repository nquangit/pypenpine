"""Ordered, case-preserving, multi-valued HTTP headers (immutable)."""
from __future__ import annotations

from typing import Iterable, Iterator


class Headers:
    __slots__ = ("_items",)

    def __init__(self, items: Iterable[tuple[str, str]] | None = None):
        self._items: tuple[tuple[str, str], ...] = tuple(items or ())

    def items(self) -> Iterator[tuple[str, str]]:
        return iter(self._items)

    def names(self) -> list[str]:
        return [n for n, _ in self._items]

    def get(self, name: str, default=None):
        low = name.lower()
        for n, v in self._items:
            if n.lower() == low:
                return v
        return default

    def get_all(self, name: str) -> list[str]:
        low = name.lower()
        return [v for n, v in self._items if n.lower() == low]

    def __getitem__(self, name: str) -> str:
        v = self.get(name, _MISSING)
        if v is _MISSING:
            raise KeyError(name)
        return v

    def __contains__(self, name: str) -> bool:
        return self.get(name, _MISSING) is not _MISSING

    def __iter__(self) -> Iterator[tuple[str, str]]:
        return iter(self._items)

    def __len__(self) -> int:
        return len(self._items)

    def __eq__(self, other) -> bool:
        return isinstance(other, Headers) and self._items == other._items

    def add(self, name: str, value: str) -> "Headers":
        return Headers([*self._items, (name, value)])

    def set(self, name: str, value: str) -> "Headers":
        low = name.lower()
        kept = [(n, v) for n, v in self._items if n.lower() != low]
        return Headers([*kept, (name, value)])

    def remove(self, name: str) -> "Headers":
        low = name.lower()
        return Headers([(n, v) for n, v in self._items if n.lower() != low])

    def __repr__(self) -> str:
        return f"Headers({list(self._items)!r})"


_MISSING = object()
