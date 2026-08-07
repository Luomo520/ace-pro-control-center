#!/usr/bin/env python3
"""Validate Klipper includes before installing Ace Pro Control Center."""

from __future__ import annotations

import argparse
import glob
import re
from pathlib import Path
from typing import Iterable, Optional, Sequence, Set


INCLUDE_RE = re.compile(r"^\s*\[include\s+([^\]]+)\]\s*$", re.IGNORECASE)
MACRO_RE = re.compile(r"^\s*\[gcode_macro\s+(TR|T(?:[0-9]|1[0-5]))\]\s*$", re.IGNORECASE)
LEGACY_HARDWARE_CONFIG = "ace_hardware.cfg"
MIGRATION_SHARED_CONFIG = "ace.cfg"


def _is_legacy_hardware_path(path: Path) -> bool:
    return path.name.casefold() == LEGACY_HARDWARE_CONFIG


def _migration_include_is_allowed(
    source: Optional[Path], pattern: Optional[str], target: Path
) -> bool:
    if source is None or pattern != LEGACY_HARDWARE_CONFIG:
        return False
    if source.name != MIGRATION_SHARED_CONFIG:
        return False
    source_directory = source.parent.resolve()
    resolved_target = target.resolve()
    return (
        resolved_target.name.casefold() == LEGACY_HARDWARE_CONFIG
        and resolved_target.parent == source_directory
    )


def _validate_legacy_hardware_entry(
    source: Optional[Path],
    pattern: Optional[str],
    requested_target: Path,
    resolved_target: Path,
    allow_legacy_hardware_migration: bool,
) -> None:
    if not (
        _is_legacy_hardware_path(requested_target)
        or _is_legacy_hardware_path(resolved_target)
    ):
        return
    if allow_legacy_hardware_migration and _migration_include_is_allowed(
        source, pattern, resolved_target
    ):
        return
    if source is None:
        route = str(requested_target)
    else:
        route = "%s includes %r" % (source, pattern)
    raise ValueError(
        "Retired ACE hardware config is active in the Klipper include graph: %s. "
        "Strict preflight rejects ace_hardware.cfg. Before a one-time migration, "
        "--allow-legacy-hardware-migration permits only the exact "
        "[include ace_hardware.cfg] form from a same-directory ace.cfg."
        % route
    )


def active_config_files(
    root: Path, *, allow_legacy_hardware_migration: bool = False
) -> Iterable[Path]:
    """Yield the active include graph while enforcing the legacy-file policy.

    Strict rejection is the default. The migration exception is deliberately
    narrow: only ``ace.cfg`` may include its sibling ``ace_hardware.cfg``, and
    the include token must be exactly ``ace_hardware.cfg``.
    """
    active: Set[Path] = set()

    def walk(
        requested_path: Path,
        included_from: Optional[Path] = None,
        include_pattern: Optional[str] = None,
    ) -> Iterable[Path]:
        path = requested_path.resolve()
        _validate_legacy_hardware_entry(
            included_from,
            include_pattern,
            requested_path,
            path,
            allow_legacy_hardware_migration,
        )
        if path in active:
            raise ValueError("Recursive include of Klipper config file: %s" % path)
        if not path.is_file():
            raise ValueError("Klipper config file does not exist: %s" % path)
        active.add(path)
        try:
            yield path
            for raw in path.read_text(encoding="utf-8").splitlines():
                line = raw.split("#", 1)[0].strip()
                match = INCLUDE_RE.match(line)
                if not match:
                    continue
                pattern = match.group(1).strip()
                include_glob = str(path.parent / pattern)
                if not glob.has_magic(include_glob):
                    requested_target = path.parent / pattern
                    _validate_legacy_hardware_entry(
                        path,
                        pattern,
                        requested_target,
                        requested_target.resolve(),
                        allow_legacy_hardware_migration,
                    )
                matches = sorted(glob.glob(include_glob))
                if not matches and not glob.has_magic(include_glob):
                    raise ValueError(
                        "Klipper include file does not exist: %s (%s)" % (pattern, path)
                    )
                for item in matches:
                    yield from walk(Path(item), path, pattern)
        finally:
            active.remove(path)

    yield from walk(root)


def find_conflicts(
    root: Path,
    device_count: int = 4,
    *,
    allow_legacy_hardware_migration: bool = False,
) -> list[str]:
    if device_count < 1 or device_count > 4:
        raise ValueError("device_count must be between 1 and 4")
    conflicts = []
    for path in active_config_files(
        root,
        allow_legacy_hardware_migration=allow_legacy_hardware_migration,
    ):
        for line_number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            line = raw.split("#", 1)[0].strip()
            match = MACRO_RE.match(line)
            if not match:
                continue
            command = match.group(1).upper()
            conflicts.append("%s:%d [%s]" % (path, line_number, command))
    return conflicts


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate Klipper includes and Ace Pro Control Center command ownership."
    )
    parser.add_argument("printer_cfg", type=Path)
    parser.add_argument("--device-count", type=int, default=4)
    parser.add_argument(
        "--allow-legacy-hardware-migration",
        action="store_true",
        help=(
            "before migration only, allow ace.cfg to include its sibling "
            "ace_hardware.cfg using the exact legacy include form"
        ),
    )
    args = parser.parse_args(argv)
    try:
        conflicts = find_conflicts(
            args.printer_cfg,
            args.device_count,
            allow_legacy_hardware_migration=args.allow_legacy_hardware_migration,
        )
    except (OSError, UnicodeError, ValueError) as exc:
        parser.error(str(exc))
    if conflicts:
        parser.error(
            "Ace Pro Control Center command conflicts were found; remove or rename these active macros before installation:\n"
            + "\n".join(conflicts)
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
