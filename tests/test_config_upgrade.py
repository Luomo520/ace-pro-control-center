from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _load_module():
    name = "ace_v3_config_upgrade_tests"
    spec = importlib.util.spec_from_file_location(
        name, PROJECT_ROOT / "scripts" / "config_upgrade.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


upgrade = _load_module()
shared_template = (PROJECT_ROOT / "config" / "ace.cfg").read_text(encoding="utf-8")
machine_template = (PROJECT_ROOT / "config" / "ace_machine.cfg").read_text(
    encoding="utf-8"
)

NEW_REQUIRED_HOOKS = {
    "pre_toolchange_macro": "_ace_prepare_toolchange",
    "cut_macro": "_ace_cut_filament",
    "load_to_toolhead_macro": "_ace_load_filament_to_toolhead",
    "unload_from_toolhead_macro": "_ace_unload_filament_from_toolhead",
    "wipe_nozzle_macro": "_ace_wipe_nozzle",
    "post_toolchange_macro": "_ace_restore_after_toolchange",
    "pause_on_error_macro": "_ace_pause_on_toolchange_error",
}
CONFIG_OPTION_LINE_RE = re.compile(
    r"^(?:#[ \t]+)?[A-Za-z][A-Za-z0-9_]*[ \t]*[:=]"
)
INLINE_COMMENT_INDEX = 96
SENSOR_NAME_OPTION_RE = re.compile(
    r"(?m)^[#;]?[ \t]*[A-Za-z][A-Za-z0-9_]*_sensor_name[ \t]*[:=]"
)
OLD_TO_NEW = {
    "_ACE_MACHINE_PRE_TOOLCHANGE": "_ace_prepare_toolchange",
    "_ACE_MACHINE_CUT": "_ace_cut_filament",
    "_ACE_MACHINE_LOAD_TO_TOOLHEAD": "_ace_load_filament_to_toolhead",
    "_ACE_MACHINE_UNLOAD_FROM_TOOLHEAD": "_ace_unload_filament_from_toolhead",
    "_ACE_MACHINE_POST_TOOLCHANGE": "_ace_restore_after_toolchange",
    "_ACE_MACHINE_PAUSE_ON_ERROR": "_ace_pause_on_toolchange_error",
}


def _active_macro_names(text: str) -> set[str]:
    return {
        match.group(1).lower()
        for match in re.finditer(r"(?im)^\[gcode_macro\s+([^\]]+)\]", text)
    }


def _assert_inline_comment_contract(text: str) -> None:
    aligned = 0
    for line_number, line in enumerate(text.splitlines(), 1):
        option = CONFIG_OPTION_LINE_RE.match(line)
        if option is None:
            continue
        index = line.find("#", option.end())
        if index < 0 or index == 0 or not line[index - 1].isspace():
            continue
        aligned += 1
        assert index == INLINE_COMMENT_INDEX, (line_number, index + 1, line)
    assert aligned >= 50
    material_line = next(
        line for line in text.splitlines() if line.startswith("material_types:")
    )
    assert "#" not in material_line


def _assert_pin_only_sensor_options(text: str) -> None:
    assert SENSOR_NAME_OPTION_RE.search(text) is None


def _embedded_hardware_block(text: str) -> str:
    start = text.index(upgrade.EMBEDDED_HARDWARE_BEGIN)
    end = text.index(upgrade.EMBEDDED_HARDWARE_END, start)
    end += len(upgrade.EMBEDDED_HARDWARE_END)
    if text[end : end + 2] == "\r\n":
        end += 2
    elif text[end : end + 1] == "\n":
        end += 1
    return text[start:end]


def test_stale_shared_config_gains_pin_only_defaults_without_losing_calibration():
    stale = """# user header
[include ace_hardware.cfg]
[ace]
driver_version: 3
feed_speed: 91
extruder_sensor_name: upper_custom
toolhead_sensor_name: lower_custom

[ace_machine]
pre_toolchange_macro: USER_PRE
load_to_toolhead_macro:
unload_from_toolhead_macro:
"""

    result = upgrade.upgrade_shared(stale, shared_template)

    assert "toolchange_mode: manual" in result
    assert "require_cut_hook: True" in result
    assert "encoder_print_mode: off" in result
    assert "encoder_print_detection_length: 20" in result
    assert "feed_speed: 91" in result
    assert "extruder_sensor_name: upper_custom" not in result
    assert "toolhead_sensor_name: lower_custom" not in result
    assert "[include ace_hardware.cfg]" not in result
    assert result.count(upgrade.EMBEDDED_HARDWARE_BEGIN) == 1
    assert result.count(upgrade.EMBEDDED_HARDWARE_END) == 1
    _assert_pin_only_sensor_options(result)
    assert "pre_toolchange_macro: USER_PRE" in result
    assert "material_types: PLA, PLA+, PETG" in result
    assert "extruder_sensor_pin:" in result
    assert "toolhead_sensor_pin:" in result
    for key, value in NEW_REQUIRED_HOOKS.items():
        if key == "pre_toolchange_macro":
            continue
        assert f"{key}: {value}" in result
    assert "wipe_nozzle_macro: _ace_wipe_nozzle" in result
    assert "# [gcode_macro _ace_cut_filament]" in result
    assert "_ace_cut_filament" not in _active_macro_names(result)
    assert "一、路径传感器（引脚 / 去抖）" in result
    _assert_inline_comment_contract(result)
    assert upgrade.upgrade_shared(result, shared_template) == result


def test_shared_upgrade_preserves_mode_materials_and_unknown_extensions():
    stale = """[ace]
driver_version: 3
toolchange_mode: automatic
require_cut_hook: False
material_types: TPU, PLA Silk, PETG-HF
feed_speed: 72
encoder_print_mode: monitor
encoder_print_detection_length: 31
toolhead_sensor_bypass_load_length: 37
toolhead_sensor_bypass_calibrated: True
future_option: keep-me

[ace_machine]
cut_macro: USER_CUT
load_to_toolhead_macro: USER_LOAD
unload_from_toolhead_macro: USER_UNLOAD
pause_on_error_macro: USER_ERROR

[gcode_macro USER_LOAD]
gcode:
    RESPOND MSG=ready

[gcode_macro USER_CUT]
gcode:
    USER_MACHINE_CUT
"""

    result = upgrade.upgrade_shared(stale, shared_template)

    assert "toolchange_mode: automatic" in result
    assert "require_cut_hook: False" in result
    assert "material_types: TPU, PLA Silk, PETG-HF" in result
    assert "feed_speed: 72" in result
    assert "encoder_print_mode: monitor" in result
    assert "encoder_print_detection_length: 31" in result
    assert "toolhead_sensor_bypass_load_length: 37" in result
    assert "toolhead_sensor_bypass_calibrated: True" in result
    assert "future_option: keep-me" in result
    assert "cut_macro: USER_CUT" in result
    assert "load_to_toolhead_macro: USER_LOAD" in result
    assert "[gcode_macro USER_LOAD]" in result
    assert "RESPOND MSG=ready" in result
    assert "[gcode_macro USER_CUT]" in result
    assert "USER_MACHINE_CUT" in result
    _assert_inline_comment_contract(result)
    assert upgrade.upgrade_shared(result, shared_template) == result


def test_shared_upgrade_keeps_template_help_and_removes_legacy_sensor_names():
    stale = """[ace]
driver_version: 3
extruder_sensor_pin: ^toolboard:PA2
rdm_sensor_name: legacy_total_hub
rdm_sensor_pin:

[ace_machine]
load_to_toolhead_macro: USER_LOAD
unload_from_toolhead_macro: USER_UNLOAD
pause_on_error_macro: USER_ERROR
"""

    result = upgrade.upgrade_shared(stale, shared_template)

    pin_line = next(
        line for line in result.splitlines() if line.startswith("extruder_sensor_pin:")
    )
    rdm_pin_line = next(
        line for line in result.splitlines() if line.startswith("rdm_sensor_pin:")
    )
    assert "^toolboard:PA2" in pin_line
    assert "#" in pin_line
    assert "#" in rdm_pin_line
    assert "rdm_sensor_name: legacy_total_hub" not in result
    _assert_pin_only_sensor_options(result)
    _assert_inline_comment_contract(result)
    assert upgrade.upgrade_shared(result, shared_template) == result


def test_old_six_macros_migrate_to_new_names_with_user_content():
    old_sections = """
[gcode_macro _ACE_MACHINE_PRE_TOOLCHANGE]
# keep-pre-comment
variable_park_x: 289
gcode:
    SET_GCODE_VARIABLE MACRO=_ACE_MACHINE_PRE_TOOLCHANGE VARIABLE=park_x VALUE=289

[gcode_macro _ACE_MACHINE_CUT]
variable_cutter_y_hit: 350
gcode:
    USER_CUT
    FORCE_MOVE STEPPER=extruder DISTANCE=-50 VELOCITY=10

[gcode_macro _ACE_MACHINE_LOAD_TO_TOOLHEAD]
variable_user_load: 1
gcode:
    USER_LOAD TOOL={params.TOOL}

[gcode_macro _ACE_MACHINE_UNLOAD_FROM_TOOLHEAD]
gcode:
    USER_UNLOAD TOOL={params.TOOL}

[gcode_macro _ACE_MACHINE_POST_TOOLCHANGE]
gcode:
    {% set pre = printer["gcode_macro _ACE_MACHINE_PRE_TOOLCHANGE"] %}
    CLEAN_NOZZLE
    USER_RESTORE VALUE={pre.park_x}

[gcode_macro _ACE_MACHINE_PAUSE_ON_ERROR]
gcode:
    USER_ERROR
"""
    stale = """[ace]
driver_version: 3
toolchange_mode: automatic

[ace_machine]
pre_toolchange_macro: _ACE_MACHINE_PRE_TOOLCHANGE
cut_macro: _ACE_MACHINE_CUT
load_to_toolhead_macro: _ACE_MACHINE_LOAD_TO_TOOLHEAD
unload_from_toolhead_macro: _ACE_MACHINE_UNLOAD_FROM_TOOLHEAD
post_toolchange_macro: _ACE_MACHINE_POST_TOOLCHANGE
pause_on_error_macro: _ACE_MACHINE_PAUSE_ON_ERROR
""" + old_sections

    result = upgrade.upgrade_shared(stale, shared_template)
    active = _active_macro_names(result)

    for old_name, new_name in OLD_TO_NEW.items():
        assert old_name.lower() not in active
        assert new_name in active
        assert f"description: {upgrade.TARGET_MACRO_DESCRIPTIONS[new_name]}" in result
    assert "_ace_wipe_nozzle" in result
    assert "gcode_macro _ace_prepare_toolchange" in result
    assert "keep-pre-comment" in result
    assert "variable_park_x: 289" in result
    assert "variable_user_load: 1" in result
    assert "USER_LOAD TOOL={params.TOOL}" in result
    assert 'printer["gcode_macro _ace_prepare_toolchange"]' in result
    assert "FORCE_MOVE STEPPER=extruder" not in result
    assert "固定 -50 mm 强制回抽已移除" in result
    for old_name, new_name in OLD_TO_NEW.items():
        assert f": {old_name}" not in result
        assert f": {new_name}" in result
    _assert_inline_comment_contract(result)
    assert upgrade.upgrade_shared(result, shared_template) == result


def test_v2_macro_names_migrate_and_force_move_is_not_carried_forward():
    stale = """[ace]
driver_version: 3

[ace_machine]
pre_toolchange_macro: _ACE_PRE_TOOLCHANGE
cut_macro: CUT_TIP
load_to_toolhead_macro:
unload_from_toolhead_macro:
post_toolchange_macro: _ACE_POST_TOOLCHANGE
pause_on_error_macro: _ACE_ON_EMPTY_ERROR

[gcode_macro _ACE_PRE_TOOLCHANGE]
gcode:
    USER_V2_PRE

[gcode_macro CUT_TIP]
gcode:
    USER_V2_CUT
    FORCE_MOVE STEPPER=extruder DISTANCE=-50 VELOCITY=10

[gcode_macro _ACE_POST_TOOLCHANGE]
gcode:
    USER_V2_POST

[gcode_macro _ACE_ON_EMPTY_ERROR]
gcode:
    USER_V2_ERROR
"""

    result = upgrade.upgrade_shared(stale, shared_template)

    assert "[gcode_macro _ace_prepare_toolchange]" in result
    assert "[gcode_macro _ace_cut_filament]" in result
    assert "[gcode_macro _ace_restore_after_toolchange]" in result
    assert "[gcode_macro _ace_pause_on_toolchange_error]" in result
    assert "USER_V2_PRE" in result
    assert "USER_V2_CUT" in result
    assert "FORCE_MOVE STEPPER=extruder" not in result


def test_commented_dangerous_macro_remains_commented_and_customized():
    stale = """[ace]
driver_version: 3

[ace_machine]
load_to_toolhead_macro:
unload_from_toolhead_macro:
pause_on_error_macro:

# [gcode_macro _ACE_MACHINE_CUT]
# variable_user_coordinate: 347
# gcode:
#     USER_COMMENTED_CUT
"""

    result = upgrade.upgrade_shared(stale, shared_template)
    active = _active_macro_names(result)

    assert "_ace_cut_filament" not in active
    assert "# [gcode_macro _ace_cut_filament]" in result
    assert "# variable_user_coordinate: 347" in result
    assert "#     USER_COMMENTED_CUT" in result
    assert "cut_macro: _ace_cut_filament" in result
    _assert_inline_comment_contract(result)
    assert upgrade.upgrade_shared(result, shared_template) == result


def test_previous_stock_commented_templates_are_not_duplicated():
    previous = shared_template
    for macro_name, description in upgrade.TARGET_MACRO_DESCRIPTIONS.items():
        previous = previous.replace(
            f"# description: {description}",
            f"# description: 旧版说明：{macro_name}",
        )

    result = upgrade.upgrade_shared(previous, shared_template)

    for macro_name in (
        "_ace_prepare_toolchange",
        "_ace_cut_filament",
        "_ace_wipe_nozzle",
        "_ace_restore_after_toolchange",
    ):
        assert result.count(f"# [gcode_macro {macro_name}]") == 1
    assert "安装器保留的已注释用户宏" not in result
    assert upgrade.upgrade_shared(result, shared_template) == result


def test_conflicting_old_and_new_macro_names_fail_without_discarding_content():
    stale = """[ace]
driver_version: 3
[ace_machine]
load_to_toolhead_macro:
unload_from_toolhead_macro:
pause_on_error_macro:
[gcode_macro _ACE_MACHINE_CUT]
gcode:
    OLD_CUT
[gcode_macro _ace_cut_filament]
gcode:
    NEW_CUT
"""

    with pytest.raises(ValueError, match="conflict"):
        upgrade.upgrade_shared(stale, shared_template)


def test_merged_upgrade_archives_input_semantics_and_is_idempotent():
    shared = """# user shared config
[include ace_hardware.cfg]
[include ace_machine.cfg]
[ace]
driver_version: 3
toolchange_mode: automatic
[ace_machine]
pre_toolchange_macro: _ACE_MACHINE_PRE_TOOLCHANGE
load_to_toolhead_macro:
unload_from_toolhead_macro:
pause_on_error_macro:
"""
    legacy = """# user machine config
[gcode_macro _ACE_MACHINE_PRE_TOOLCHANGE]
# calibrated comment
variable_park_x: 289
gcode:
    USER_PREPARE
"""

    result = upgrade.upgrade_shared(shared, shared_template, legacy)

    assert "[include ace_hardware.cfg]" not in result
    assert "[include ace_machine.cfg]" not in result
    assert "toolchange_mode: automatic" in result
    assert "[gcode_macro _ace_prepare_toolchange]" in result
    assert "variable_park_x: 289" in result
    assert "calibrated comment" in result
    assert "USER_PREPARE" in result
    for key, value in NEW_REQUIRED_HOOKS.items():
        assert f"{key}: {value}" in result
    _assert_inline_comment_contract(result)
    assert upgrade.upgrade_shared(result, shared_template) == result


def test_shared_upgrade_preserves_existing_embedded_hardware_block_exactly():
    hardware_block = _embedded_hardware_block(shared_template).replace(
        "/dev/serial/by-id/REPLACE_WITH_STABLE_ACE1_PATH",
        "/dev/serial/by-id/user-calibrated-ace",
        1,
    ).replace("rfid_enabled: True", "rfid_enabled: False", 1)
    stale = hardware_block + """
[ace]
driver_version: 3
toolchange_mode: automatic
[ace_machine]
load_to_toolhead_macro:
unload_from_toolhead_macro:
pause_on_error_macro:
"""

    result = upgrade.upgrade_shared(stale, shared_template)

    assert _embedded_hardware_block(result) == hardware_block
    assert result.count(upgrade.EMBEDDED_HARDWARE_BEGIN) == 1
    assert result.count(upgrade.EMBEDDED_HARDWARE_END) == 1
    assert "toolchange_mode: automatic" in result
    assert upgrade.upgrade_shared(result, shared_template) == result


def test_shared_upgrade_preserves_user_content_after_managed_end_boundary():
    user_tail = """# user-calibrated-value
[gcode_macro USER_AFTER_TEMPLATE]
gcode:
    RESPOND MSG=user-tail
"""
    current = shared_template + user_tail

    result = upgrade.upgrade_shared(current, shared_template)

    assert result.endswith(user_tail)
    assert result.count(upgrade.SHARED_CONFIG_END) == 1
    assert upgrade.upgrade_shared(result, shared_template) == result


def test_shared_upgrade_preserves_tail_from_pre_boundary_template():
    old_template = shared_template.replace(
        "# 安装器管理模板到此结束；此行之后的用户附加内容在升级时原样保留。\n"
        + upgrade.SHARED_CONFIG_END
        + "\n",
        "",
    )
    stale = old_template + "# legacy-user-note\n"

    result = upgrade.upgrade_shared(stale, shared_template)

    assert upgrade.SHARED_CONFIG_END in result
    assert result.endswith("# legacy-user-note\n")
    assert upgrade.upgrade_shared(result, shared_template) == result


@pytest.mark.parametrize(
    "hardware_prefix",
    [
        upgrade.EMBEDDED_HARDWARE_BEGIN + "\n[ace_hardware]\ndevice_count: 1\n",
        (
            upgrade.EMBEDDED_HARDWARE_BEGIN
            + "\n"
            + upgrade.EMBEDDED_HARDWARE_BEGIN
            + "\n"
            + upgrade.EMBEDDED_HARDWARE_END
            + "\n"
        ),
        (
            upgrade.EMBEDDED_HARDWARE_BEGIN
            + "\n"
            + upgrade.EMBEDDED_HARDWARE_END
            + "\n"
            + upgrade.EMBEDDED_HARDWARE_END
            + "\n"
        ),
    ],
    ids=("missing-end", "duplicate-begin", "duplicate-end"),
)
def test_shared_upgrade_rejects_damaged_or_duplicate_hardware_boundaries(
    hardware_prefix: str,
):
    stale = hardware_prefix + "[ace]\ndriver_version: 3\n"

    with pytest.raises(ValueError, match="exactly one intact BEGIN/END pair"):
        upgrade.upgrade_shared(stale, shared_template)


def test_shared_upgrade_rejects_reversed_hardware_boundaries():
    stale = (
        upgrade.EMBEDDED_HARDWARE_END
        + "\n[ace_hardware]\ndevice_count: 1\n"
        + upgrade.EMBEDDED_HARDWARE_BEGIN
        + "\n[ace]\ndriver_version: 3\n"
    )

    with pytest.raises(ValueError, match="boundaries are out of order"):
        upgrade.upgrade_shared(stale, shared_template)


def test_legacy_machine_cli_migrates_names_and_preserves_nonempty_bridges():
    stale = """[gcode_macro _ACE_MACHINE_LOAD_TO_TOOLHEAD]
variable_custom: 1
gcode:
    USER_LOAD
"""

    result = upgrade.upgrade_machine(stale, machine_template)

    assert "[gcode_macro _ace_load_filament_to_toolhead]" in result
    assert "variable_custom: 1" in result
    assert "USER_LOAD" in result
    assert "[gcode_macro _ACE_MACHINE_LOAD_TO_TOOLHEAD]" not in result
