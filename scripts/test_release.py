#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import configparser
import json
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


hardware = load_module("hardware_config", SCRIPT_DIR / "hardware_config.py")
blocks = load_module("managed_block", SCRIPT_DIR / "managed_block.py")
release = load_module("validate_release", SCRIPT_DIR / "validate_release.py")
preflight = load_module("config_preflight", SCRIPT_DIR / "config_preflight.py")
packaging = load_module("package_release", SCRIPT_DIR / "package_release.py")


class HardwareConfigTests(unittest.TestCase):
    def test_all_requested_two_device_model_combinations(self):
        combinations = [
            (
                hardware.Device("ace1", "/dev/serial/by-id/a"),
                hardware.Device("ace1", "/dev/serial/by-id/b"),
            ),
            (
                hardware.Device("ace1", "/dev/serial/by-id/a"),
                hardware.Device("ace2", "/dev/serial/by-id/b", "bus0", "uid-b"),
            ),
            (
                hardware.Device("ace2", "/dev/serial/by-id/a", "bus0", "uid-a"),
                hardware.Device("ace2", "/dev/serial/by-id/a", "bus0", "uid-b"),
            ),
        ]
        for devices in combinations:
            with self.subTest(models=[device.model for device in devices]):
                self.assertEqual(hardware.validate_devices(devices), [])

    def test_four_device_mapping_order_and_ace2_read_only(self):
        devices = [
            hardware.Device("ace1", "/dev/serial/by-id/a"),
            hardware.Device("ace2", "/dev/serial/by-id/b", "bus0", "uid-b"),
            hardware.Device("ace1", "/dev/serial/by-id/c"),
            hardware.Device("ace2", "/dev/serial/by-id/d", "bus1", "uid-d"),
        ]
        text = hardware.render(devices)
        self.assertLess(text.index("[ace_device ace0]"), text.index("[ace_device ace3]"))
        self.assertEqual(text.count("physical_actions_enabled: True"), 0)
        self.assertEqual(text.count("physical_actions_enabled: False"), 4)

    def test_unselected_devices_are_commented(self):
        text = hardware.render(
            [hardware.Device("ace1", "/dev/serial/by-id/ace-one")]
        )
        self.assertIn("device_count: 1", text)
        self.assertIn("# [ace_device ace1]", text)
        self.assertNotIn("\n[ace_device ace1]", text)

    def test_mixed_ace1_ace2_is_valid(self):
        devices = [
            hardware.Device("ace1", "/dev/serial/by-id/one"),
            hardware.Device("ace2", "/dev/serial/by-id/two", "bus0", "uid-two"),
        ]
        self.assertEqual(hardware.validate_devices(devices), [])

    def test_two_ace2_can_share_bus_with_explicit_uids(self):
        devices = [
            hardware.Device("ace2", "/dev/serial/by-id/bus", "bus0", "uid-1"),
            hardware.Device("ace2", "/dev/serial/by-id/bus", "bus0", "uid-2"),
        ]
        self.assertEqual(hardware.validate_devices(devices), [])

    def test_shared_ace2_bus_rejects_auto_uid(self):
        devices = [
            hardware.Device("ace2", "/dev/serial/by-id/bus", "bus0", "auto"),
            hardware.Device("ace2", "/dev/serial/by-id/bus", "bus0", "uid-2"),
        ]
        self.assertTrue(
            any("explicit UID" in error for error in hardware.validate_devices(devices))
        )

    def test_ace1_serial_cannot_be_shared(self):
        devices = [
            hardware.Device("ace1", "/dev/serial/by-id/same"),
            hardware.Device("ace1", "/dev/serial/by-id/same"),
        ]
        errors = hardware.validate_devices(devices)
        self.assertTrue(any("must be unique" in error for error in errors))

    def test_generated_file_round_trip(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "ace_hardware.cfg"
            path.write_text(
                hardware.render(
                    [hardware.Device("ace1", "/dev/serial/by-id/one")]
                ),
                encoding="utf-8",
            )
            self.assertEqual(hardware.validate_file(path), [])

    def test_validator_rejects_ace2_physical_actions(self):
        text = hardware.render(
            [hardware.Device("ace2", "/dev/serial/by-id/two", "bus0", "uid-two")]
        ).replace("physical_actions_enabled: False", "physical_actions_enabled: True")
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "ace_hardware.cfg"
            path.write_text(text, encoding="utf-8")
            self.assertTrue(
                any("ACE2 physical actions" in error for error in hardware.validate_file(path))
            )


class ManagedBlockTests(unittest.TestCase):
    def test_ensure_is_idempotent_and_remove_preserves_user_text(self):
        start, end, body = blocks.MARKERS["printer"]
        original = "# user setting\n[virtual_sdcard]\npath: ~/gcodes\n"
        once = blocks.replace_block(original, start, end, body)
        twice = blocks.replace_block(once, start, end, body)
        self.assertEqual(once, twice)
        self.assertEqual(once.count(start), 1)
        removed = blocks.replace_block(twice, start, end, None)
        self.assertEqual(removed, original)

    def test_malformed_boundary_is_rejected(self):
        start, end, body = blocks.MARKERS["moonraker"]
        with self.assertRaises(ValueError):
            blocks.replace_block(start + "\n", start, end, body)

    def test_existing_compatible_line_is_adopted_by_managed_block(self):
        start, end, body = blocks.MARKERS["printer"]
        original = "[virtual_sdcard]\npath: ~/gcodes\n[include ace.cfg]\n"
        without_legacy = blocks.COMPATIBLE_LINES["printer"].sub("", original)
        result = blocks.replace_block(without_legacy, start, end, body)
        self.assertEqual(result.count("[include ace.cfg]"), 1)
        self.assertIn(start, result)

    def test_printer_block_stays_before_save_config_tail(self):
        start, end, body = blocks.MARKERS["printer"]
        tail = (
            "#*# <---------------------- SAVE_CONFIG ---------------------->\n"
            "#*# DO NOT EDIT THIS BLOCK OR BELOW. The contents are auto-generated.\n"
            "#*# [bed_mesh default]\n"
            "#*# version = 1\n"
        )
        original = "[virtual_sdcard]\npath: ~/gcodes\n\n" + tail
        once = blocks.replace_block(
            original,
            start,
            end,
            body,
            insert_before=blocks.SAVE_CONFIG_MARKER,
        )
        twice = blocks.replace_block(
            once,
            start,
            end,
            body,
            insert_before=blocks.SAVE_CONFIG_MARKER,
        )
        self.assertEqual(once, twice)
        self.assertLess(once.index(start), once.index("SAVE_CONFIG"))
        self.assertTrue(once.endswith(tail))
        removed = blocks.replace_block(
            once,
            start,
            end,
            None,
            insert_before=blocks.SAVE_CONFIG_MARKER,
        )
        self.assertEqual(removed, original)


class ConfigPreflightTests(unittest.TestCase):
    def test_active_tool_macro_conflict_is_reported_through_include(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "printer.cfg").write_text("[include macros.cfg]\n", encoding="utf-8")
            (root / "macros.cfg").write_text("[gcode_macro T5]\ngcode:\n  G4 P1\n", encoding="utf-8")
            conflicts = preflight.find_conflicts(root / "printer.cfg")
            self.assertEqual(len(conflicts), 1)
            self.assertIn("[T5]", conflicts[0])

    def test_commented_tool_macro_does_not_conflict(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "printer.cfg"
            path.write_text("# [gcode_macro T0]\n", encoding="utf-8")
            self.assertEqual(preflight.find_conflicts(path), [])

    def test_conflict_scope_matches_full_registered_tool_range(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "printer.cfg"
            path.write_text(
                "[gcode_macro T3]\ngcode:\n  G4 P1\n"
                "[gcode_macro T4]\ngcode:\n  G4 P1\n"
                "[gcode_macro T15]\ngcode:\n  G4 P1\n",
                encoding="utf-8",
            )
            conflicts = preflight.find_conflicts(path, device_count=1)
            self.assertEqual(len(conflicts), 3)
            self.assertIn("[T3]", conflicts[0])
            self.assertIn("[T4]", conflicts[1])
            self.assertIn("[T15]", conflicts[2])

    def test_wildcard_include_can_match_no_files(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "printer.cfg"
            path.write_text("[include optional/*.cfg]\n", encoding="utf-8")
            self.assertEqual(list(preflight.active_config_files(path)), [path.resolve()])

    def test_recursive_include_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "printer.cfg"
            path.write_text("[include printer.cfg]\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Recursive include"):
                list(preflight.active_config_files(path))


class ReleaseValidationTests(unittest.TestCase):
    def test_release_tree_rejects_retired_hardware_config_variants(self):
        retired = (
            "config/ace_hardware.cfg",
            "config/ace_hardware.example.cfg",
            "config/examples/ACE-HARDWARE-template.CFG",
            "config/ace_hardware_local.cfg",
        )
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            for relative in retired:
                path = repo / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("# retired\n", encoding="utf-8")
            errors = release.validate_retired_hardware_configs(repo)

        self.assertEqual(
            errors,
            [
                f"release tree contains retired hardware config: {relative}"
                for relative in sorted(retired)
            ],
        )

    def test_retired_hardware_contract_is_scoped_to_release_config(self):
        self.assertFalse(
            release.is_retired_hardware_config_path("ace_hardware.cfg")
        )
        self.assertFalse(
            release.is_retired_hardware_config_path(
                "scripts/hardware_config.py"
            )
        )
        self.assertFalse(
            release.is_retired_hardware_config_path(
                "tests/fixtures/ace_hardware.example.cfg"
            )
        )
        self.assertTrue(
            release.is_retired_hardware_config_path(
                "config/ace_hardware.example.cfg"
            )
        )

    def test_all_klipper_wrapper_contracts(self):
        project = SCRIPT_DIR.parent
        self.assertEqual(
            release.KLIPPER_WRAPPER_FUNCTIONS,
            {
                "ace_hardware.py": "load_config",
                "ace_device.py": "load_config_prefix",
                "ace_machine.py": "load_config",
                "ace_encoder.py": "load_config_prefix",
            },
        )
        self.assertEqual(release.validate_klipper_wrappers(project), [])
        self.assertEqual(release.validate_installer_wrapper_contract(project), [])

    def test_installer_and_test_wrapper_lists_cannot_omit_encoder(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            (repo / "installer").mkdir()
            (repo / "scripts").mkdir()
            declaration = (
                "declare -ar KLIPPER_WRAPPERS="
                "(ace_hardware ace_device ace_machine)\n"
            )
            (repo / "installer" / "install.sh").write_text(
                declaration, encoding="utf-8"
            )
            (repo / "scripts" / "test_installer.sh").write_text(
                declaration, encoding="utf-8"
            )
            errors = release.validate_installer_wrapper_contract(repo)
            self.assertEqual(len(errors), 2)
            self.assertTrue(all("ace_encoder" in error for error in errors))

    def test_encoder_wrapper_is_required(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            extras = repo / "klipper_extras"
            extras.mkdir()
            for filename, function in release.KLIPPER_WRAPPER_FUNCTIONS.items():
                if filename == "ace_encoder.py":
                    continue
                (extras / filename).write_text(
                    f"def {function}(config):\n    return object()\n",
                    encoding="utf-8",
                )
            errors = release.validate_klipper_wrappers(repo)
            self.assertEqual(len(errors), 1)
            self.assertIn("ace_encoder.py", errors[0])

    def test_encoder_wrapper_requires_prefix_loader(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            extras = repo / "klipper_extras"
            extras.mkdir()
            for filename, function in release.KLIPPER_WRAPPER_FUNCTIONS.items():
                if filename == "ace_encoder.py":
                    function = "load_config"
                (extras / filename).write_text(
                    f"def {function}(config):\n    return object()\n",
                    encoding="utf-8",
                )
            errors = release.validate_klipper_wrappers(repo)
            self.assertEqual(errors, ["ace_encoder.py must expose top-level load_config_prefix(config)"])

    def test_current_shared_config_contract(self):
        path = SCRIPT_DIR.parent / "config" / "ace.cfg"
        self.assertEqual(hardware.validate_embedded_file(path), [])
        errors = release.validate_shared_config(path)
        self.assertEqual(errors, [])

    def test_shared_config_rejects_legacy_hardware_include(self):
        source = (SCRIPT_DIR.parent / "config" / "ace.cfg").read_text(
            encoding="utf-8"
        )
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "ace.cfg"
            path.write_text(
                "[include ace_hardware.cfg]\n" + source,
                encoding="utf-8",
            )
            errors = release.validate_shared_config(path)
        self.assertIn(
            "shared config still includes retired ace_hardware.cfg",
            errors,
        )

    def test_shared_config_rejects_malformed_embedded_hardware_boundaries(self):
        source = (SCRIPT_DIR.parent / "config" / "ace.cfg").read_text(
            encoding="utf-8"
        )
        malformed = source.replace(hardware.EMBEDDED_HARDWARE_END, "", 1)
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "ace.cfg"
            path.write_text(malformed, encoding="utf-8")
            errors = release.validate_shared_config(path)
        self.assertTrue(
            any("hardware topology" in error for error in errors),
            errors,
        )

    def test_current_machine_macro_contract(self):
        errors = release.validate_machine_config(
            SCRIPT_DIR.parent / "config" / "ace_machine.cfg"
        )
        self.assertEqual(errors, [])

    def test_template_and_generated_hardware_parse_in_driver_core(self):
        project = SCRIPT_DIR.parent
        sys.path.insert(0, str(project))
        try:
            from ace_driver.config import parse_config
        finally:
            sys.path.pop(0)
        shared_parser = configparser.ConfigParser(
            delimiters=(":", "="),
            interpolation=None,
            inline_comment_prefixes=("#", ";"),
        )
        shared_parser.read(project / "config" / "ace.cfg", encoding="utf-8")
        self.assertEqual(
            hardware.validate_embedded_file(project / "config" / "ace.cfg"),
            [],
        )
        self.assertEqual(dict(shared_parser["ace_hardware"])["device_count"], "1")
        self.assertEqual(dict(shared_parser["ace_device ace0"])["model"], "ace1")
        hardware_parser = configparser.ConfigParser(
            delimiters=(":", "="),
            interpolation=None,
            inline_comment_prefixes=("#", ";"),
        )
        hardware_parser.read_string(
            hardware.render(
                [
                    hardware.Device("ace1", "/dev/serial/by-id/one"),
                    hardware.Device(
                        "ace2", "/dev/serial/by-id/two", "bus0", "uid-two"
                    ),
                ]
            )
        )
        sections = {
            "ace": dict(shared_parser["ace"]),
            "ace_machine": dict(shared_parser["ace_machine"]),
            "ace_hardware": dict(hardware_parser["ace_hardware"]),
        }
        for section in hardware_parser.sections():
            if section.startswith("ace_device "):
                sections[section] = dict(hardware_parser[section])
        parsed = parse_config(sections)
        self.assertEqual(parsed.device_count, 2)
        self.assertEqual(parsed.shared.toolchange_mode, "manual")
        self.assertIsNone(parsed.shared.extruder_sensor_name)
        self.assertIsNone(parsed.shared.toolhead_sensor_name)
        self.assertIsNone(parsed.shared.rdm_sensor_name)
        self.assertIsNone(parsed.shared.encoder_sensor_name)
        self.assertEqual(
            {
                "pre_toolchange_macro": parsed.machine.pre_toolchange_macro,
                "cut_macro": parsed.machine.cut_macro,
                "load_to_toolhead_macro": parsed.machine.load_to_toolhead_macro,
                "unload_from_toolhead_macro": parsed.machine.unload_from_toolhead_macro,
                "wipe_nozzle_macro": parsed.machine.wipe_nozzle_macro,
                "post_toolchange_macro": parsed.machine.post_toolchange_macro,
                "pause_on_error_macro": parsed.machine.pause_on_error_macro,
            },
            {
                "pre_toolchange_macro": "_ace_prepare_toolchange",
                "cut_macro": "_ace_cut_filament",
                "load_to_toolhead_macro": "_ace_load_filament_to_toolhead",
                "unload_from_toolhead_macro": "_ace_unload_filament_from_toolhead",
                "wipe_nozzle_macro": "_ace_wipe_nozzle",
                "post_toolchange_macro": "_ace_restore_after_toolchange",
                "pause_on_error_macro": "_ace_pause_on_toolchange_error",
            },
        )
        self.assertTrue(parsed.devices[0].rfid_enabled)
        self.assertTrue(parsed.devices[1].rfid_enabled)
        self.assertFalse(parsed.devices[0].physical_actions_enabled)
        self.assertFalse(parsed.devices[1].physical_actions_enabled)

    def test_release_metadata_versions_come_from_build_inputs(self):
        project = SCRIPT_DIR.parent
        self.assertEqual(packaging._driver_version(project), "V2.5ahpha")
        self.assertEqual(packaging.SOURCE_NAME, "ace-pro-control-center")
        self.assertEqual(
            packaging.SOURCE_ARCHIVE_NAME, "Ace-Pro-Control-Center.tar.gz"
        )
        with tempfile.TemporaryDirectory() as temp:
            dist = Path(temp)
            (dist / ".version").write_text("v9.8.7\n", encoding="utf-8")
            self.assertEqual(packaging._fluidd_version(dist), "9.8.7")

    def test_release_package_uses_product_artifact_identity(self):
        project = SCRIPT_DIR.parent
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            dist = root / "fluidd"
            assets = dist / "assets"
            output = root / "release"
            assets.mkdir(parents=True)
            (dist / "index.html").write_text("<html></html>\n", encoding="utf-8")
            (dist / ".version").write_text("v9.8.7\n", encoding="utf-8")
            (assets / "AceV3Card-test.js").write_text(
                "acepro-slot-card__spool\n", encoding="utf-8"
            )
            (assets / "AcePro-test.js").write_text("ready\n", encoding="utf-8")

            manifest_path = packaging.package_release(
                project,
                dist,
                output,
                "20260804_120000",
                "product rename test",
                {"unit": "passed"},
            )
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

            self.assertTrue((output / "Ace-Pro-Control-Center.tar.gz").is_file())
            self.assertFalse((output / "ACE-Driver-V3.tar.gz").exists())
            self.assertEqual(manifest["source"], "ace-pro-control-center")
            self.assertEqual(manifest["driver"], "V2.5ahpha")
            with tarfile.open(output / "Ace-Pro-Control-Center.tar.gz", "r:gz") as archive:
                members = archive.getnames()
                self.assertIn("scripts/install_snapshot.py", members)
                self.assertIn("wiki/Home.md", members)
                self.assertIn("wiki/Beginner-Tutorial.md", members)

    def test_release_archive_uses_linux_installable_permissions(self):
        directory = tarfile.TarInfo("installer")
        directory.type = tarfile.DIRTYPE
        directory.mode = 0o777
        install_script = tarfile.TarInfo("installer/install.sh")
        install_script.mode = 0o666
        regular_file = tarfile.TarInfo("README.md")
        regular_file.mode = 0o666

        self.assertEqual(packaging._archive_filter(directory).mode, 0o755)
        self.assertEqual(packaging._archive_filter(install_script).mode, 0o755)
        self.assertEqual(packaging._archive_filter(regular_file).mode, 0o644)

    def test_release_archive_filter_rejects_retired_hardware_configs(self):
        for name in (
            "config/ace_hardware.cfg",
            "config/ace_hardware.example.cfg",
            "config/examples/ACE-HARDWARE-template.CFG",
        ):
            with self.subTest(name=name):
                with self.assertRaisesRegex(
                    ValueError,
                    "refusing retired hardware config",
                ):
                    packaging._archive_filter(tarfile.TarInfo(name))

    def test_source_archive_member_contract_rejects_retired_config(self):
        with tempfile.TemporaryDirectory() as temp:
            archive_path = Path(temp) / "source.tar.gz"
            with tarfile.open(archive_path, "w:gz") as archive:
                archive.addfile(tarfile.TarInfo("config/ace.cfg"))
                archive.addfile(
                    tarfile.TarInfo("config/ace_hardware.example.cfg")
                )
            with self.assertRaisesRegex(
                ValueError,
                "source archive contains retired hardware config",
            ):
                packaging._validate_source_archive_members(archive_path)

    def test_current_config_archive_has_no_retired_members(self):
        project = SCRIPT_DIR.parent
        with tempfile.TemporaryDirectory() as temp:
            archive_path = Path(temp) / "source.tar.gz"
            with tarfile.open(archive_path, "w:gz") as archive:
                archive.add(
                    project / "config",
                    arcname="config",
                    recursive=True,
                    filter=packaging._archive_filter,
                )
            packaging._validate_source_archive_members(archive_path)
            with tarfile.open(archive_path, "r:gz") as archive:
                members = {member.name for member in archive.getmembers()}

        self.assertIn("config/ace.cfg", members)
        self.assertFalse(
            any(
                release.is_retired_hardware_config_path(member)
                for member in members
            )
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
