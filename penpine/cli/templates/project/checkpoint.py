"""Resumable checkpoint: record completed work items to a JSON file.

Used by main.py to skip work already done on a rerun. Generic — key items
however you like (attack name, request id, flow name, ...).
"""

from __future__ import annotations

import json
from pathlib import Path


class Checkpoint:
    def __init__(self, path, *, resume=True):
        self._path = Path(path)
        self._done = set()
        if not resume:
            self._path.unlink(missing_ok=True)  # start fresh / overwrite
        elif self._path.exists():
            try:
                self._done = set(json.loads(self._path.read_text()).get("done", []))
            except (ValueError, OSError):
                self._done = set()

    def is_done(self, item) -> bool:
        return str(item) in self._done

    def mark_done(self, item) -> None:
        self._done.add(str(item))
        # Flush immediately so an interrupt leaves a valid checkpoint.
        self._path.write_text(json.dumps({"done": sorted(self._done)}, indent=2))
