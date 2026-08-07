#!/usr/bin/env python3
"""Create and restore self-contained installer snapshots."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


FORMAT_VERSION = 1
MANIFEST_NAME = "snapshot-manifest.json"
CHECKSUMS_NAME = "SHA256SUMS"
RESTORE_SCRIPT_NAME = "restore.py"


def _absolute(path: Path) -> Path:
    return Path(os.path.abspath(os.fspath(path)))


def _lexists(path: Path) -> bool:
    return os.path.lexists(os.fspath(path))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _checksum_files(root: Path) -> list[Path]:
    paths = [root / MANIFEST_NAME, root / RESTORE_SCRIPT_NAME]
    payload = root / "items"
    if payload.is_dir():
        paths.extend(
            path
            for path in sorted(payload.rglob("*"))
            if path.is_file() and not path.is_symlink()
        )
    return paths


def _write_checksums(root: Path) -> None:
    lines = [
        "%s  %s" % (_sha256(path), path.relative_to(root).as_posix())
        for path in _checksum_files(root)
    ]
    (root / CHECKSUMS_NAME).write_text("\n".join(lines) + "\n", encoding="utf-8")


def verify_snapshot(snapshot: Path) -> dict[str, Any]:
    snapshot = _absolute(snapshot)
    manifest_path = snapshot / MANIFEST_NAME
    checksums_path = snapshot / CHECKSUMS_NAME
    if not manifest_path.is_file() or not checksums_path.is_file():
        raise ValueError("snapshot manifest or SHA256SUMS is missing")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("format_version") != FORMAT_VERSION:
        raise ValueError("unsupported snapshot format version")
    for line in checksums_path.read_text(encoding="utf-8").splitlines():
        expected, separator, relative = line.partition("  ")
        if not separator or not expected or not relative:
            raise ValueError("invalid SHA256SUMS entry")
        path = snapshot / relative
        if not path.is_file() or _sha256(path) != expected:
            raise ValueError("snapshot checksum mismatch: %s" % relative)
    return manifest


def _copy_existing(source: Path, destination: Path) -> str:
    if source.is_symlink():
        return "symlink"
    if source.is_dir():
        shutil.copytree(source, destination, symlinks=True)
        return "directory"
    if source.is_file():
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination, follow_symlinks=False)
        return "file"
    raise ValueError("unsupported target type: %s" % source)


def create_snapshot(output: Path, targets: Iterable[Path]) -> Path:
    output = _absolute(output)
    unique: list[Path] = []
    seen: set[str] = set()
    for target in targets:
        target = _absolute(target)
        key = os.path.normcase(os.fspath(target))
        if key in seen:
            continue
        if target == Path(target.anchor):
            raise ValueError("refusing to snapshot a filesystem root")
        seen.add(key)
        unique.append(target)
    if not unique:
        raise ValueError("at least one snapshot target is required")
    if _lexists(output):
        raise ValueError("snapshot output already exists: %s" % output)

    temporary = output.with_name(".%s.tmp-%d" % (output.name, os.getpid()))
    if _lexists(temporary):
        shutil.rmtree(temporary)
    temporary.parent.mkdir(parents=True, exist_ok=True)
    temporary.mkdir(mode=0o700)
    entries: list[dict[str, Any]] = []
    try:
        for index, target in enumerate(unique):
            if target.is_dir() and not target.is_symlink():
                try:
                    output.relative_to(target)
                except ValueError:
                    pass
                else:
                    raise ValueError(
                        "snapshot output cannot be stored inside target directory: %s"
                        % target
                    )
            entry: dict[str, Any] = {"path": os.fspath(target)}
            if not _lexists(target):
                entry["state"] = "missing"
            elif target.is_symlink():
                entry.update(state="symlink", link_target=os.readlink(target))
            else:
                payload = Path("items") / ("%04d" % index)
                entry.update(
                    state=_copy_existing(target, temporary / payload),
                    payload=payload.as_posix(),
                )
            entries.append(entry)

        manifest = {
            "format_version": FORMAT_VERSION,
            "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "entries": entries,
        }
        (temporary / MANIFEST_NAME).write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        shutil.copy2(Path(__file__), temporary / RESTORE_SCRIPT_NAME)
        _write_checksums(temporary)
        temporary.rename(output)
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    verify_snapshot(output)
    return output


def _remove(path: Path) -> None:
    if not _lexists(path):
        return
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.is_dir():
        shutil.rmtree(path)
    else:
        raise ValueError("unsupported current target type: %s" % path)


def restore_snapshot(snapshot: Path, *, apply: bool) -> list[str]:
    snapshot = _absolute(snapshot)
    manifest = verify_snapshot(snapshot)
    actions: list[str] = []
    for raw_entry in manifest["entries"]:
        target = _absolute(Path(raw_entry["path"]))
        if target == Path(target.anchor):
            raise ValueError("refusing to restore a filesystem root")
        state = raw_entry["state"]
        actions.append("%s <- %s" % (target, state))
        if not apply:
            continue
        _remove(target)
        if state == "missing":
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        if state == "symlink":
            target.symlink_to(raw_entry["link_target"])
            continue
        payload = snapshot / raw_entry["payload"]
        if state == "directory":
            shutil.copytree(payload, target, symlinks=True)
        elif state == "file":
            shutil.copy2(payload, target, follow_symlinks=False)
        else:
            raise ValueError("unsupported snapshot entry state: %s" % state)
    return actions


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    create = subparsers.add_parser("create")
    create.add_argument("--output", type=Path, required=True)
    create.add_argument("--target", type=Path, action="append", default=[])
    verify = subparsers.add_parser("verify")
    verify.add_argument("snapshot", type=Path)
    restore = subparsers.add_parser("restore")
    restore.add_argument("snapshot", type=Path)
    restore.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.command == "create":
            path = create_snapshot(args.output, args.target)
            print(path)
        elif args.command == "verify":
            manifest = verify_snapshot(args.snapshot)
            print("snapshot verified: %d targets" % len(manifest["entries"]))
        else:
            actions = restore_snapshot(args.snapshot, apply=args.apply)
            for action in actions:
                print(action)
            if not args.apply:
                print("preview only; add --apply to restore", file=sys.stderr)
            else:
                print("snapshot restore complete")
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
