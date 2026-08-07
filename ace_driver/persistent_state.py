"""Atomic JSON persistence for Ace Pro Control Center runtime state."""

from __future__ import annotations

import copy
import json
import os
import tempfile
import threading
from pathlib import Path
from typing import Any, Dict, Mapping, Optional


SCHEMA_VERSION = 1


class PersistenceError(RuntimeError):
    pass


def _json_object(value: Mapping[str, Any]) -> Dict[str, Any]:
    data = copy.deepcopy(dict(value))
    try:
        encoded = json.dumps(data, ensure_ascii=True, allow_nan=False)
        decoded = json.loads(encoded)
    except (TypeError, ValueError) as exc:
        raise PersistenceError("state must contain only JSON-compatible values") from exc
    if not isinstance(decoded, dict):
        raise PersistenceError("persistent state must be a JSON object")
    return decoded


class PersistentState:
    """Thread-safe in-memory state with explicit atomic flushes.

    Mutations only mark the store dirty.  Callers choose a safe point to call
    ``flush()``, keeping filesystem I/O out of time-critical Klipper callbacks.
    """

    def __init__(self, path: Any, defaults: Optional[Mapping[str, Any]] = None):
        self.path = Path(path)
        self._defaults = _json_object(defaults or {})
        self._state = copy.deepcopy(self._defaults)
        self._dirty = False
        self._loaded = False
        self._lock = threading.RLock()

    @property
    def dirty(self) -> bool:
        with self._lock:
            return self._dirty

    def load(self) -> Dict[str, Any]:
        with self._lock:
            if not self.path.exists():
                self._state = copy.deepcopy(self._defaults)
                self._dirty = False
                self._loaded = True
                return self.snapshot()
            try:
                with self.path.open("r", encoding="utf-8") as handle:
                    document = json.load(handle)
            except (OSError, ValueError) as exc:
                raise PersistenceError(
                    "unable to read persistent state '%s': %s" % (self.path, exc)
                ) from exc
            if not isinstance(document, dict):
                raise PersistenceError("persistent state document must be a JSON object")
            version = document.get("schema_version")
            if version != SCHEMA_VERSION:
                raise PersistenceError(
                    "unsupported persistent state schema %r; expected %d"
                    % (version, SCHEMA_VERSION)
                )
            state = document.get("state")
            if not isinstance(state, dict):
                raise PersistenceError("persistent state document is missing object 'state'")
            merged = copy.deepcopy(self._defaults)
            merged.update(_json_object(state))
            self._state = merged
            self._dirty = False
            self._loaded = True
            return self.snapshot()

    def _ensure_loaded(self) -> None:
        if not self._loaded:
            self.load()

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            return copy.deepcopy(self._state)

    def get(self, key: str, default: Any = None) -> Any:
        with self._lock:
            self._ensure_loaded()
            return copy.deepcopy(self._state.get(key, default))

    def set(self, key: str, value: Any) -> None:
        if not isinstance(key, str) or not key:
            raise PersistenceError("state key must be a non-empty string")
        validated = _json_object({key: value})[key]
        with self._lock:
            self._ensure_loaded()
            if self._state.get(key, _MISSING) != validated:
                self._state[key] = validated
                self._dirty = True

    def update(self, values: Mapping[str, Any]) -> None:
        validated = _json_object(values)
        with self._lock:
            self._ensure_loaded()
            for key, value in validated.items():
                if not isinstance(key, str) or not key:
                    raise PersistenceError("state key must be a non-empty string")
                if self._state.get(key, _MISSING) != value:
                    self._state[key] = value
                    self._dirty = True

    def delete(self, key: str) -> bool:
        with self._lock:
            self._ensure_loaded()
            if key not in self._state:
                return False
            del self._state[key]
            self._dirty = True
            return True

    def replace(self, state: Mapping[str, Any]) -> None:
        validated = _json_object(state)
        with self._lock:
            self._ensure_loaded()
            if self._state != validated:
                self._state = validated
                self._dirty = True

    def flush(self, force: bool = False) -> bool:
        """Atomically persist state, returning whether a write occurred."""

        with self._lock:
            self._ensure_loaded()
            if not self._dirty and not force:
                return False
            document = {
                "schema_version": SCHEMA_VERSION,
                "state": copy.deepcopy(self._state),
            }
            payload = json.dumps(
                document,
                ensure_ascii=True,
                allow_nan=False,
                indent=2,
                sort_keys=True,
            ) + "\n"
            parent = self.path.parent
            try:
                parent.mkdir(parents=True, exist_ok=True)
                fd, temporary = tempfile.mkstemp(
                    prefix=".%s." % self.path.name,
                    suffix=".tmp",
                    dir=str(parent),
                )
            except OSError as exc:
                raise PersistenceError("unable to create state temporary file: %s" % exc) from exc
            try:
                with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                    handle.write(payload)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temporary, str(self.path))
            except OSError as exc:
                try:
                    os.unlink(temporary)
                except OSError:
                    pass
                raise PersistenceError("unable to atomically persist state: %s" % exc) from exc
            self._dirty = False
            return True

    def save(self, state: Mapping[str, Any]) -> None:
        self.replace(state)
        self.flush(force=True)


_MISSING = object()
AtomicJSONStore = PersistentState


__all__ = [
    "AtomicJSONStore",
    "PersistenceError",
    "PersistentState",
    "SCHEMA_VERSION",
]
