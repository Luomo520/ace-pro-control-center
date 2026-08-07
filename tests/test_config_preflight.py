from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "config_preflight.py"
SPEC = importlib.util.spec_from_file_location("ace_v3_config_preflight", SCRIPT_PATH)
assert SPEC and SPEC.loader
preflight = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(preflight)


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _migration_tree(root: Path, hardware_include: str = "ace_hardware.cfg") -> Path:
    printer = _write(root / "printer.cfg", "[include ace.cfg]\n")
    _write(root / "ace.cfg", "[include %s]\n" % hardware_include)
    _write(root / "ace_hardware.cfg", "[ace_hardware]\ndevice_count: 1\n")
    return printer


@pytest.mark.parametrize(
    "include_pattern",
    [
        "ace_hardware.cfg",
        "./ace_hardware.cfg",
        ".ace-driver-v3/legacy/ace_hardware.cfg",
    ],
)
def test_strict_mode_rejects_direct_legacy_include_forms(
    tmp_path: Path, include_pattern: str
) -> None:
    printer = _write(tmp_path / "printer.cfg", "[include %s]\n" % include_pattern)
    _write(
        tmp_path / include_pattern,
        "[ace_hardware]\ndevice_count: 1\n",
    )

    with pytest.raises(ValueError, match="Retired ACE hardware config"):
        list(preflight.active_config_files(printer))


def test_strict_mode_rejects_exact_legacy_include_from_ace_cfg(
    tmp_path: Path,
) -> None:
    printer = _migration_tree(tmp_path)

    with pytest.raises(ValueError, match="Strict preflight rejects"):
        list(preflight.active_config_files(printer))


def test_migration_mode_allows_only_exact_sibling_include_from_ace_cfg(
    tmp_path: Path,
) -> None:
    printer = _migration_tree(tmp_path)

    files = list(
        preflight.active_config_files(
            printer, allow_legacy_hardware_migration=True
        )
    )

    assert files == [
        (tmp_path / "printer.cfg").resolve(),
        (tmp_path / "ace.cfg").resolve(),
        (tmp_path / "ace_hardware.cfg").resolve(),
    ]


def test_migration_mode_rejects_direct_printer_include(tmp_path: Path) -> None:
    printer = _write(tmp_path / "printer.cfg", "[include ace_hardware.cfg]\n")
    _write(tmp_path / "ace_hardware.cfg", "[ace_hardware]\ndevice_count: 1\n")

    with pytest.raises(ValueError, match="permits only the exact"):
        list(
            preflight.active_config_files(
                printer, allow_legacy_hardware_migration=True
            )
        )


@pytest.mark.parametrize(
    ("source_name", "include_pattern"),
    [
        ("ACE.cfg", "ace_hardware.cfg"),
        ("ace.cfg", "./ace_hardware.cfg"),
        ("ace.cfg", ".ace-driver-v3/legacy/ace_hardware.cfg"),
    ],
)
def test_migration_mode_rejects_every_noncanonical_form(
    tmp_path: Path, source_name: str, include_pattern: str
) -> None:
    printer = _write(tmp_path / "printer.cfg", "[include %s]\n" % source_name)
    _write(tmp_path / source_name, "[include %s]\n" % include_pattern)
    _write(
        tmp_path / include_pattern,
        "[ace_hardware]\ndevice_count: 1\n",
    )

    with pytest.raises(ValueError, match="permits only the exact"):
        list(
            preflight.active_config_files(
                printer, allow_legacy_hardware_migration=True
            )
        )


@pytest.mark.parametrize("allow_migration", [False, True])
def test_wildcard_matching_archived_hardware_is_always_rejected(
    tmp_path: Path, allow_migration: bool
) -> None:
    printer = _write(
        tmp_path / "printer.cfg",
        "[include .ace-driver-v3/legacy/*.cfg]\n",
    )
    _write(
        tmp_path / ".ace-driver-v3" / "legacy" / "ace_hardware.cfg",
        "[ace_hardware]\ndevice_count: 1\n",
    )

    with pytest.raises(ValueError, match="Retired ACE hardware config"):
        list(
            preflight.active_config_files(
                printer,
                allow_legacy_hardware_migration=allow_migration,
            )
        )


def test_cli_flag_enables_the_narrow_migration_exception(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    printer = _migration_tree(tmp_path)

    with pytest.raises(SystemExit) as strict_exit:
        preflight.main([str(printer)])
    assert strict_exit.value.code == 2
    assert "Retired ACE hardware config" in capsys.readouterr().err

    assert (
        preflight.main(
            [str(printer), "--allow-legacy-hardware-migration"]
        )
        == 0
    )


def test_macro_conflicts_are_still_reported_through_includes(
    tmp_path: Path,
) -> None:
    printer = _write(tmp_path / "printer.cfg", "[include macros.cfg]\n")
    _write(tmp_path / "macros.cfg", "[gcode_macro T5]\ngcode:\n  G4 P1\n")

    conflicts = preflight.find_conflicts(printer)

    assert len(conflicts) == 1
    assert "[T5]" in conflicts[0]


def test_unmatched_optional_wildcard_remains_valid(tmp_path: Path) -> None:
    printer = _write(tmp_path / "printer.cfg", "[include optional/*.cfg]\n")

    assert list(preflight.active_config_files(printer)) == [printer.resolve()]


def test_recursive_include_is_still_rejected(tmp_path: Path) -> None:
    printer = _write(tmp_path / "printer.cfg", "[include printer.cfg]\n")

    with pytest.raises(ValueError, match="Recursive include"):
        list(preflight.active_config_files(printer))
