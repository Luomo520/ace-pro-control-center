import json
from unittest import mock

import pytest

from ace_driver.persistent_state import PersistenceError, PersistentState


def test_missing_file_loads_isolated_defaults(tmp_path):
    store = PersistentState(tmp_path / "state.json", {"current_tool": -1})
    snapshot = store.load()
    snapshot["current_tool"] = 4

    assert store.get("current_tool") == -1
    assert store.dirty is False


def test_flush_writes_atomic_json_envelope_and_reloads(tmp_path):
    path = tmp_path / "nested" / "state.json"
    store = PersistentState(path, {"current_tool": -1})
    store.set("current_tool", 5)
    store.set("endless_spool", True)

    assert store.flush() is True
    document = json.loads(path.read_text(encoding="utf-8"))
    assert document["schema_version"] == 1
    assert document["state"]["current_tool"] == 5
    assert not list(path.parent.glob(".*.tmp"))

    restored = PersistentState(path, {"new_default": "kept"})
    assert restored.load() == {
        "new_default": "kept",
        "current_tool": 5,
        "endless_spool": True,
    }


def test_clean_flush_does_not_rewrite_file(tmp_path):
    path = tmp_path / "state.json"
    store = PersistentState(path)
    store.save({"current_tool": 0})
    before = path.stat().st_mtime_ns

    assert store.flush() is False
    assert path.stat().st_mtime_ns == before


def test_malformed_or_wrong_schema_state_is_rejected(tmp_path):
    path = tmp_path / "state.json"
    path.write_text("not-json", encoding="utf-8")
    with pytest.raises(PersistenceError, match="unable to read"):
        PersistentState(path).load()

    path.write_text('{"schema_version": 99, "state": {}}', encoding="utf-8")
    with pytest.raises(PersistenceError, match="unsupported"):
        PersistentState(path).load()


def test_failed_replace_preserves_previous_file_and_dirty_state(tmp_path):
    path = tmp_path / "state.json"
    store = PersistentState(path)
    store.save({"current_tool": 1})
    original = path.read_bytes()
    store.set("current_tool", 2)

    with mock.patch("ace_driver.persistent_state.os.replace", side_effect=OSError("busy")):
        with pytest.raises(PersistenceError, match="atomically"):
            store.flush()

    assert path.read_bytes() == original
    assert store.dirty is True
    assert not list(tmp_path.glob(".*.tmp"))


def test_non_json_values_are_rejected_before_state_changes(tmp_path):
    store = PersistentState(tmp_path / "state.json", {"safe": True})
    with pytest.raises(PersistenceError, match="JSON-compatible"):
        store.set("bad", object())
    assert store.snapshot() == {"safe": True}
