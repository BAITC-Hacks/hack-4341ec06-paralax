"""Small in-memory draft store for a five-hour local demo."""

from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from threading import RLock
from typing import Any


class RunNotFound(Exception):
    """A run ID was not found in the current server process."""


class RunStore:
    def __init__(self) -> None:
        self._runs: dict[str, dict[str, Any]] = {}
        self._lock = RLock()

    def create(self, run: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            run_id = run["run_id"]
            if run_id in self._runs:
                raise ValueError("duplicate run_id")
            self._runs[run_id] = deepcopy(run)
            return deepcopy(run)

    def get(self, run_id: str) -> dict[str, Any]:
        with self._lock:
            try:
                return deepcopy(self._runs[run_id])
            except KeyError as error:
                raise RunNotFound(run_id) from error

    def update(
        self, run_id: str, change: Callable[[dict[str, Any]], dict[str, Any]]
    ) -> dict[str, Any]:
        with self._lock:
            current = self.get(run_id)
            updated = change(current)
            self._runs[run_id] = deepcopy(updated)
            return deepcopy(updated)
