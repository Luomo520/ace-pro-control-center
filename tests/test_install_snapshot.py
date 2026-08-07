import json
import os
from pathlib import Path

import pytest

from scripts.install_snapshot import (
    CHECKSUMS_NAME,
    MANIFEST_NAME,
    RESTORE_SCRIPT_NAME,
    create_snapshot,
    restore_snapshot,
    verify_snapshot,
)


def test_snapshot_restores_files_directories_links_and_missing_targets(tmp_path: Path):
    targets = tmp_path / "targets"
    targets.mkdir()
    file_target = targets / "printer.cfg"
    file_target.write_text("before\n", encoding="utf-8")
    directory_target = targets / "state"
    directory_target.mkdir()
    (directory_target / "manifest").write_text("before-state\n", encoding="utf-8")
    missing_target = targets / "new-link.py"
    link_target = targets / "managed-link"
    link_supported = True
    try:
        link_target.symlink_to("printer.cfg")
    except OSError:
        link_supported = False

    selected = [file_target, directory_target, missing_target]
    if link_supported:
        selected.append(link_target)
    snapshot = create_snapshot(tmp_path / "snapshots" / "before-install", selected)

    file_target.write_text("after\n", encoding="utf-8")
    (directory_target / "manifest").write_text("after-state\n", encoding="utf-8")
    missing_target.write_text("created\n", encoding="utf-8")
    if link_supported:
        link_target.unlink()
        link_target.write_text("replaced\n", encoding="utf-8")

    restore_snapshot(snapshot, apply=True)

    assert file_target.read_text(encoding="utf-8") == "before\n"
    assert (directory_target / "manifest").read_text(encoding="utf-8") == "before-state\n"
    assert not missing_target.exists()
    if link_supported:
        assert link_target.is_symlink()
        assert os.readlink(link_target) == "printer.cfg"


def test_snapshot_is_self_contained_and_preview_does_not_modify_targets(tmp_path: Path):
    target = tmp_path / "ace.cfg"
    target.write_text("original\n", encoding="utf-8")
    snapshot = create_snapshot(tmp_path / "snapshot", [target])

    assert (snapshot / MANIFEST_NAME).is_file()
    assert (snapshot / CHECKSUMS_NAME).is_file()
    assert (snapshot / RESTORE_SCRIPT_NAME).is_file()
    manifest = verify_snapshot(snapshot)
    assert manifest["entries"][0]["path"] == str(target.absolute())

    target.write_text("changed\n", encoding="utf-8")
    actions = restore_snapshot(snapshot, apply=False)
    assert actions == [f"{target.absolute()} <- file"]
    assert target.read_text(encoding="utf-8") == "changed\n"


def test_corrupt_snapshot_is_rejected_before_restore(tmp_path: Path):
    target = tmp_path / "printer.cfg"
    target.write_text("original\n", encoding="utf-8")
    snapshot = create_snapshot(tmp_path / "snapshot", [target])
    manifest_path = snapshot / MANIFEST_NAME
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["entries"][0]["state"] = "missing"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    target.write_text("must-remain\n", encoding="utf-8")
    with pytest.raises(ValueError, match="checksum mismatch"):
        restore_snapshot(snapshot, apply=True)
    assert target.read_text(encoding="utf-8") == "must-remain\n"


def test_snapshot_rejects_output_inside_snapshotted_directory(tmp_path: Path):
    target = tmp_path / "printer_data"
    target.mkdir()
    with pytest.raises(ValueError, match="inside target directory"):
        create_snapshot(target / "snapshots" / "bad", [target])
