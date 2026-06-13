"""DataProfile: named static, role-bound fixtures."""
from __future__ import annotations

from dataclasses import dataclass, field

from penpine.data.exceptions import DataError


@dataclass
class DataProfile:
    name: str
    values: dict = field(default_factory=dict)

    def get(self, key, default=None):
        return self.values.get(key, default)

    def require(self, key):
        if key not in self.values:
            raise DataError(f"data profile {self.name!r} missing key: {key!r}")
        return self.values[key]
