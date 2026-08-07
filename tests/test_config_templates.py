from __future__ import annotations

import configparser
import importlib.util
import re
import sys
import tempfile
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SHARED_CONFIG = PROJECT_ROOT / "config" / "ace.cfg"
MACHINE_CONFIG = PROJECT_ROOT / "config" / "ace_machine.cfg"

EXPECTED_SHARED = {
    "driver_version": "3",
    "toolchange_mode": "manual",
    "material_types": "PLA, PLA+, PETG, PETG-CF, PETCF, ABS, ABSCF, ASA, TPU, PA, PA-CF, PAHTCF, PET-CF, PC, PBT-CF, PEEK, PVA, HIPS",
    "extruder_sensor_pin": "",
    "toolhead_sensor_pin": "",
    "toolhead_sensor_bypass": "True",
    "toolhead_sensor_bypass_calibrated": "False",
    "rdm_sensor_pin": "",
    "ace0_hub_sensor_pin": "",
    "ace1_hub_sensor_pin": "",
    "ace2_hub_sensor_pin": "",
    "ace3_hub_sensor_pin": "",
    "extruder_sensor_debounce_count": "2",
    "toolhead_sensor_debounce_count": "2",
    "rdm_sensor_debounce_count": "3",
    "ace_hub_sensor_debounce_count": "3",
    "encoder_sensor_pin": "",
    "encoder_resolution": "0",
    "encoder_detection_length": "20",
    "encoder_min_tracking_ratio": "0.6",
    "encoder_mode": "off",
    "encoder_print_mode": "off",
    "encoder_print_detection_length": "20",
    "feed_speed": "80",
    "feed_fast_speed": "160",
    "feed_slip_compensation_length": "400",
    "feed_slip_compensation_speed": "25",
    "retract_speed": "80",
    "retract_fast_speed": "120",
    "retract_parking_speed": "25",
    "retract_parking_length": "200",
    "toolchange_load_length": "630",
    "upper_sensor_feed_timeout": "30",
    "toolchange_retract_length": "150",
    "bowden_tube_length": "1000",
    "toolhead_sensor_to_nozzle": "50",
    "toolhead_sensor_bypass_load_length": "25",
    "toolhead_feed_fast_speed": "10",
    "toolhead_feed_slow_speed": "5",
    "toolhead_feed_fast_length": "10",
    "toolhead_feed_fast_step": "5",
    "toolhead_feed_slow_step": "1",
    "toolhead_to_nozzle_speed": "8",
    "toolhead_sensor_max_feed_length": "200",
    "toolhead_unload_step_length": "50",
    "toolhead_unload_speed": "10",
    "toolhead_unload_max_attempts": "10",
    "ace_unload_step_length": "100",
    "rdm_clear_move_length": "100",
    "ace0_hub_retract_length": "0",
    "ace0_hub_clear_move_length": "0",
    "ace1_hub_retract_length": "0",
    "ace1_hub_clear_move_length": "0",
    "ace2_hub_retract_length": "0",
    "ace2_hub_clear_move_length": "0",
    "ace3_hub_retract_length": "0",
    "ace3_hub_clear_move_length": "0",
    "sensor_trigger_grace_time": "3",
    "connection_supervision": "True",
    "max_dryer_temperature": "55",
    "endless_spool": "False",
    "endless_spool_match_mode": "exact",
    "require_path_hooks": "True",
    "require_cut_hook": "True",
}
EXPECTED_MACHINE = {
    "pre_toolchange_macro": "_ace_prepare_toolchange",
    "cut_macro": "_ace_cut_filament",
    "load_to_toolhead_macro": "_ace_load_filament_to_toolhead",
    "unload_from_toolhead_macro": "_ace_unload_filament_from_toolhead",
    "wipe_nozzle_macro": "_ace_wipe_nozzle",
    "post_toolchange_macro": "_ace_restore_after_toolchange",
    "pause_on_error_macro": "_ace_pause_on_toolchange_error",
}
LEGACY_MACHINE_MACROS = {
    "_ACE_MACHINE_PRE_TOOLCHANGE",
    "_ACE_MACHINE_CUT",
    "_ACE_MACHINE_LOAD_TO_TOOLHEAD",
    "_ACE_MACHINE_UNLOAD_FROM_TOOLHEAD",
    "_ACE_MACHINE_POST_TOOLCHANGE",
    "_ACE_MACHINE_PAUSE_ON_ERROR",
}
ACTIVE_MACHINE_MACROS = {
    "_ace_load_filament_to_toolhead",
    "_ace_unload_filament_from_toolhead",
    "_ace_pause_on_toolchange_error",
}
COMMENTED_MACHINE_MACROS = {
    "_ace_prepare_toolchange",
    "_ace_cut_filament",
    "_ace_wipe_nozzle",
    "_ace_restore_after_toolchange",
}
MACHINE_HOOK_CONTRACT = {
    "pre_toolchange_macro": (
        "_ace_prepare_toolchange",
        "换料前处理宏",
        "必用",
        True,
    ),
    "cut_macro": ("_ace_cut_filament", "切刀宏", "必用", True),
    "load_to_toolhead_macro": (
        "_ace_load_filament_to_toolhead",
        "送料宏",
        "必用",
        True,
    ),
    "unload_from_toolhead_macro": (
        "_ace_unload_filament_from_toolhead",
        "回料宏",
        "必用",
        True,
    ),
    "wipe_nozzle_macro": ("_ace_wipe_nozzle", "擦嘴宏", "必用", True),
    "post_toolchange_macro": (
        "_ace_restore_after_toolchange",
        "换料后处理宏",
        "必用",
        True,
    ),
    "pause_on_error_macro": (
        "_ace_pause_on_toolchange_error",
        "故障暂停宏",
        "必用",
        True,
    ),
}
EXPECTED_HARDWARE_ROOT = {
    "driver_version": "3",
    "device_count": "1",
    "topology_mode": "configured",
}
EXPECTED_EXAMPLE_ACE0 = {
    "model": "ace1",
    "transport": "serial",
    "serial": "/dev/serial/by-id/REPLACE_WITH_STABLE_ACE1_PATH",
    "enabled": "True",
    "rfid_enabled": "True",
    "physical_actions_enabled": "False",
}
ACTIVE_OPTION_RE = re.compile(r"^[a-z][a-z0-9_]*\s*:")
CONFIG_OPTION_LINE_RE = re.compile(
    r"^(?:#[ \t]+)?[A-Za-z][A-Za-z0-9_]*[ \t]*[:=]"
)
INLINE_COMMENT_INDEX = 96


def _load_hardware_module():
    name = "ace_v3_hardware_config_contract"
    spec = importlib.util.spec_from_file_location(
        name, PROJECT_ROOT / "scripts" / "hardware_config.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


hardware = _load_hardware_module()


def _parse_ini_text(text: str) -> configparser.ConfigParser:
    parser = configparser.ConfigParser(
        delimiters=(":", "="),
        interpolation=None,
        strict=True,
        inline_comment_prefixes=("#", ";"),
    )
    parser.read_string(text)
    return parser


def _read_ini(path: Path) -> configparser.ConfigParser:
    return _parse_ini_text(path.read_text(encoding="utf-8"))


def _assert_active_options_have_inline_chinese_help(
    text: str,
    allowed_sections: set[str] | None = None,
    without_inline_help: set[str] | None = None,
) -> None:
    without_inline_help = without_inline_help or set()
    active_options = 0
    section = ""
    for line in text.splitlines():
        section_match = re.match(r"^\[([^\]]+)\]", line)
        if section_match:
            section = section_match.group(1)
            continue
        if allowed_sections is not None and section not in allowed_sections:
            continue
        if not ACTIVE_OPTION_RE.match(line):
            continue
        active_options += 1
        option = line.split(":", 1)[0]
        if option in without_inline_help:
            assert "#" not in line, option
            continue
        assert "#" in line, option
        comment = line.split("#", 1)[1]
        assert re.search(r"[\u4e00-\u9fff]", comment), option
    assert active_options > 0


def _inline_comment_index(line: str) -> int | None:
    option = CONFIG_OPTION_LINE_RE.match(line)
    if option is None:
        return None
    index = line.find("#", option.end())
    if index < 0 or index == 0 or not line[index - 1].isspace():
        return None
    return index


def _commented_macro_block(text: str, name: str) -> list[str]:
    lines = text.splitlines()
    header = re.compile(
        r"^[ \t]*#[ \t]*\[gcode_macro[ \t]+%s\][ \t]*$" % re.escape(name),
        re.IGNORECASE,
    )
    any_macro_header = re.compile(
        r"^[ \t]*(?:#[ \t]*)?\[gcode_macro[ \t]+[^\]]+\][ \t]*$",
        re.IGNORECASE,
    )
    start = next(index for index, line in enumerate(lines) if header.match(line))
    block = [lines[start]]
    for line in lines[start + 1 :]:
        if any_macro_header.match(line):
            break
        block.append(line)
    return block


def _macro_description(text: str, name: str) -> str:
    lines = text.splitlines()
    header = re.compile(
        r"^[ \t]*(?:#[ \t]*)?\[gcode_macro[ \t]+%s\][ \t]*$"
        % re.escape(name),
        re.IGNORECASE,
    )
    any_macro_header = re.compile(
        r"^[ \t]*(?:#[ \t]*)?\[gcode_macro[ \t]+[^\]]+\][ \t]*$",
        re.IGNORECASE,
    )
    start = next(index for index, line in enumerate(lines) if header.match(line))
    for line in lines[start + 1 :]:
        if any_macro_header.match(line):
            break
        normalized = line.lstrip()
        if normalized.startswith("#"):
            normalized = normalized[1:].lstrip()
        if normalized.lower().startswith("description:"):
            return normalized.split(":", 1)[1].strip()
    raise AssertionError(f"macro {name} has no description")


def _assert_active_options_have_detailed_comments(text: str) -> None:
    lines = text.splitlines()
    active_options = 0
    for index, line in enumerate(lines):
        if not ACTIVE_OPTION_RE.match(line):
            continue
        active_options += 1
        comments = []
        cursor = index - 1
        while cursor >= 0 and lines[cursor].lstrip().startswith("#"):
            comments.append(lines[cursor].strip())
            cursor -= 1
        option = line.split(":", 1)[0]
        assert any(comment.startswith("# 作用：") for comment in comments), option
        assert any(comment.startswith("# 填写：") for comment in comments), option
        assert any(comment.startswith("# 单位：") for comment in comments), option
    assert active_options > 0


def _assert_chinese_template_style(text: str) -> None:
    assert re.search(r"^#.*一、", text, re.MULTILINE)
    assert re.search(r"^#.*二、", text, re.MULTILINE)
    assert re.search(r"^#.*三、", text, re.MULTILINE)
    assert "路径图" in text or "送丝方向" in text
    assert "☆☆☆☆☆" in text


def test_shared_template_preserves_exact_v3_active_contract():
    parser = _read_ini(SHARED_CONFIG)

    assert set(parser.sections()) == {
        "ace_hardware",
        "ace_device ace0",
        "ace",
        "ace_machine",
        "gcode_macro _ace_load_filament_to_toolhead",
        "gcode_macro _ace_unload_filament_from_toolhead",
        "gcode_macro _ace_pause_on_toolchange_error",
    }
    assert dict(parser["ace_hardware"]) == EXPECTED_HARDWARE_ROOT
    assert dict(parser["ace_device ace0"]) == EXPECTED_EXAMPLE_ACE0
    assert dict(parser["ace"]) == EXPECTED_SHARED
    assert dict(parser["ace_machine"]) == EXPECTED_MACHINE


def test_shared_template_uses_pin_only_sensor_configuration():
    text = SHARED_CONFIG.read_text(encoding="utf-8")
    assert "███████╗" in text
    assert "引脚 / 去抖" in text
    assert not re.search(
        r"(?m)^[#;]?[ \t]*[A-Za-z][A-Za-z0-9_]*_sensor_name[ \t]*[:=]",
        text,
    )

    active_keys = [
        line.split(":", 1)[0]
        for line in text.splitlines()
        if ACTIVE_OPTION_RE.match(line)
    ]
    for group in (
        (
            "extruder_sensor_pin",
            "extruder_sensor_debounce_count",
        ),
        (
            "toolhead_sensor_pin",
            "toolhead_sensor_debounce_count",
            "toolhead_sensor_bypass",
            "toolhead_sensor_bypass_load_length",
            "toolhead_sensor_bypass_calibrated",
        ),
        ("rdm_sensor_pin", "rdm_sensor_debounce_count"),
    ):
        start = active_keys.index(group[0])
        assert active_keys[start : start + len(group)] == list(group)

    hub_group = ["ace%d_hub_sensor_pin" % index for index in range(4)] + [
        "ace_hub_sensor_debounce_count"
    ]
    start = active_keys.index(hub_group[0])
    assert active_keys[start : start + len(hub_group)] == hub_group


def test_shared_template_documents_multilevel_hubs_and_shared_encoder():
    text = SHARED_CONFIG.read_text(encoding="utf-8")
    active_keys = [
        line.split(":", 1)[0]
        for line in text.splitlines()
        if ACTIVE_OPTION_RE.match(line)
    ]

    encoder_group = [
        "encoder_sensor_pin",
        "encoder_resolution",
        "encoder_detection_length",
        "encoder_min_tracking_ratio",
        "encoder_mode",
        "encoder_print_mode",
        "encoder_print_detection_length",
    ]
    start = active_keys.index(encoder_group[0])
    assert active_keys[start : start + len(encoder_group)] == encoder_group

    assert "一级五通传感器（仅 2 至 4 台 ACE）" in text
    assert "单 ACE 不安装一级五通" in text
    assert "只安装总五通传感器" in text
    assert "rdm_sensor_debounce_count" in text
    assert "多 ACE 一级五通共用" in text
    normalized_path_text = text.replace(">>> ", "").replace(" <<<", "")
    for fragment in (
        "[ACE0 槽0..3] --> [总五通传感器]",
        "[ACE0 槽0..3] --> [ace0 一级五通传感器]",
        "[总五通] --> [编码器（可选）]",
        "[上方传感器] --> [挤出机] --> [下方传感器] --> [喷嘴]",
    ):
        assert fragment in normalized_path_text
    assert "缓冲器" not in text
    assert "ACE 直流电机阶段只用编码器确认" in text
    assert "挤出机步进电机接管" in text
    assert "编码器不会自动追加送料" in text
    assert "monitor 读取显示但不作为依据" in text
    assert "bypass 只屏蔽控制依据，不屏蔽状态读取" in text
    assert "toolhead_sensor_bypass_load_length" in text
    assert "ACE_ENCODER_CALIBRATE START=1" in text
    assert "ACE_ENCODER_CALIBRATE LENGTH=150" in text
    assert "段间偏差 <=5% 通过" in text
    assert ">10% 拒绝保存" in text
    assert "ACE_ENCODER_CALIBRATE CANCEL=1" in text
    assert "encoder_print_mode 与上面的 encoder_mode 相互独立" in text
    assert "未配置编码器时静默停用" in text


def test_machine_macro_template_keeps_v2_actions_without_recursive_tool_commands():
    text = MACHINE_CONFIG.read_text(encoding="utf-8")
    assert "旧版机器动作宏迁移模板" in text
    assert "不再由新安装创建" in text
    assert "ace_machine.cfg.legacy" in text
    for name in LEGACY_MACHINE_MACROS:
        assert "[gcode_macro %s]" % name in text
    assert not re.search(r"\[gcode_macro\s+(?:T\d+|TR)\]", text, re.IGNORECASE)
    assert "ACE_CHANGE_TOOL" not in text
    cut_section = text.split("[gcode_macro _ACE_MACHINE_CUT]", 1)[1].split(
        "[gcode_macro", 1
    )[0]
    assert "FORCE_MOVE" not in cut_section
    assert cut_section.count("G1 X{cutter_x} Y{cutter_y_hit} F600") == 2
    assert "variable_park_x: -1" in text
    assert "variable_park_y: -1" in text
    assert "variable_purge_temp_min: 240" in text
    assert "SAVE_GCODE_STATE NAME=ACE_V3_TOOLCHANGE" in text
    assert "CLEAN_NOZZLE" in text
    assert "RESTORE_GCODE_STATE NAME=ACE_V3_TOOLCHANGE" in text
    assert "printer.print_stats.state" in text
    for legacy_name in (
        "CUT_TIP",
        "_ACE_PRE_TOOLCHANGE",
        "_ACE_POST_TOOLCHANGE",
        "_ACE_ON_EMPTY_ERROR",
    ):
        assert f"[gcode_macro {legacy_name}]" not in text
    assert "ACE_PATH_LOAD_TO_TOOLHEAD" in text
    assert "ACE_PATH_UNLOAD_STEP" in text


def test_shared_template_contains_machine_macro_implementations():
    text = SHARED_CONFIG.read_text(encoding="utf-8")
    for name in ACTIVE_MACHINE_MACROS:
        assert f"[gcode_macro {name}]" in text
        section = text.split(f"[gcode_macro {name}]", 1)[1].split(
            "[gcode_macro", 1
        )[0]
        assert "description:" in section
        assert re.search(r"(?m)^gcode:\s*$", section)
        assert re.search(r"(?m)^    \S", section)
    for name in COMMENTED_MACHINE_MACROS:
        assert f"# [gcode_macro {name}]" in text
        assert f"[gcode_macro {name}]" not in {
            f"[gcode_macro {section[len('gcode_macro '):]}]"
            for section in _read_ini(SHARED_CONFIG).sections()
            if section.startswith("gcode_macro ")
        }
    assert "[include ace_machine.cfg]" not in text
    assert "variable_park_x: 289" in text
    assert "variable_park_y: 350" in text
    assert "variable_purge_temp_min: 240" in text
    assert "variable_cutter_x: 10" in text
    assert "variable_cutter_y_start: 330" in text
    assert "variable_cutter_y_hit: 350" in text
    assert "CLEAN_NOZZLE" in text
    assert "严重警告" in text
    assert "FORCE_MOVE STEPPER=extruder" not in text

    cut_block = _commented_macro_block(text, "_ace_cut_filament")
    assert all(not line.strip() or line.lstrip().startswith("#") for line in cut_block)
    assert any("variable_cutter_x" in line for line in cut_block)
    assert any("G1 X{cutter_x} Y{cutter_y_hit}" in line for line in cut_block)


def test_shared_template_machine_hooks_have_clear_names_and_statuses():
    text = SHARED_CONFIG.read_text(encoding="utf-8")
    machine = text.split("[ace_machine]", 1)[1].split("[gcode_macro", 1)[0]

    for key, (macro, label, status, active) in MACHINE_HOOK_CONTRACT.items():
        match = re.search(
            r"(?m)^(?P<comment>#[ \t]+)?%s[ \t]*:[ \t]*%s[ \t]+#(?P<help>[^\r\n]*)$"
            % (re.escape(key), re.escape(macro)),
            machine,
        )
        assert match is not None, key
        assert (match.group("comment") is None) is active, key
        expected_label = f"【{label}｜{status}】"
        help_text = match.group("help")
        assert expected_label in help_text, key
        description = _macro_description(text, macro)
        if status == "必用":
            assert f"!!! {expected_label}" in help_text, key
            assert "!!!" in description, key
        else:
            assert "!!!" not in help_text, key
            assert "!!!" not in description, key


def test_manual_mode_loads_with_bound_hooks_and_commented_machine_templates():
    parser = _read_ini(SHARED_CONFIG)

    assert parser["ace"]["toolchange_mode"] == "manual"
    assert dict(parser["ace_machine"]) == EXPECTED_MACHINE
    assert {
        section for section in parser.sections() if section.startswith("gcode_macro ")
    } == {
        "gcode_macro _ace_load_filament_to_toolhead",
        "gcode_macro _ace_unload_filament_from_toolhead",
        "gcode_macro _ace_pause_on_toolchange_error",
    }
    text = SHARED_CONFIG.read_text(encoding="utf-8")
    for name in COMMENTED_MACHINE_MACROS:
        block = _commented_macro_block(text, name)
        assert all(
            not line.strip() or line.lstrip().startswith("#") for line in block
        ), name


def test_shared_template_inline_comments_start_at_column_97():
    text = SHARED_CONFIG.read_text(encoding="utf-8")
    aligned = []
    for line_number, line in enumerate(text.splitlines(), 1):
        index = _inline_comment_index(line)
        if index is None:
            continue
        aligned.append(line_number)
        assert index == INLINE_COMMENT_INDEX, (line_number, index + 1, line)

    assert len(aligned) >= 50
    material_line = next(
        line for line in text.splitlines() if line.startswith("material_types:")
    )
    assert _inline_comment_index(material_line) is None
    assert "#" not in material_line


def test_feed_assist_printing_contract_is_explained_without_false_prohibition():
    text = SHARED_CONFIG.read_text(encoding="utf-8")
    assert "打印中允许启用辅助送料，但必须由用户显式确认" in text
    assert "停用辅助送料随时允许，不需要确认" in text
    assert "打印中禁止启用辅助送料" not in text


def test_all_tool_commands_are_registered_independent_of_device_count():
    text = SHARED_CONFIG.read_text(encoding="utf-8")
    assert "固定注册 T0..T15 和 TR" in text
    assert "自动模式真正换料时才校验目标是否已配置" in text
    assert "已配置范围内的 T0..T15" not in text


def test_shared_template_uses_chinese_detailed_style():
    text = SHARED_CONFIG.read_text(encoding="utf-8")
    _assert_chinese_template_style(text)
    assert len(re.findall(r"^#.*-{40,}$", text, re.MULTILINE)) >= 5
    assert len(re.findall(r"^#.*[█╗╔╝╚║═].*$", text, re.MULTILINE)) >= 20
    _assert_active_options_have_inline_chinese_help(
        text,
        {"ace", "ace_machine"},
        without_inline_help={"material_types"},
    )


@pytest.mark.parametrize(
    "devices",
    [
        [hardware.Device("ace1", "/dev/serial/by-id/ace-one")],
        [
            hardware.Device("ace1", "/dev/serial/by-id/ace-one"),
            hardware.Device("ace1", "/dev/serial/by-id/ace-two"),
        ],
        [
            hardware.Device("ace1", "/dev/serial/by-id/ace-one"),
            hardware.Device(
                "ace2", "/dev/serial/by-id/ace-two", "bus-one", "uid-two"
            ),
        ],
        [
            hardware.Device(
                "ace2", "/dev/serial/by-id/ace2-bus", "bus-zero", "uid-zero"
            ),
            hardware.Device(
                "ace2", "/dev/serial/by-id/ace2-bus", "bus-zero", "uid-one"
            ),
        ],
        [
            hardware.Device("ace1", "/dev/serial/by-id/ace-zero"),
            hardware.Device(
                "ace2", "/dev/serial/by-id/ace2-one", "bus-one", "uid-one"
            ),
            hardware.Device("ace1", "/dev/serial/by-id/ace-two"),
        ],
        [
            hardware.Device("ace1", "/dev/serial/by-id/ace-zero"),
            hardware.Device(
                "ace2", "/dev/serial/by-id/ace2-one", "bus-one", "uid-one"
            ),
            hardware.Device("ace1", "/dev/serial/by-id/ace-two"),
            hardware.Device(
                "ace2", "/dev/serial/by-id/ace2-three", "bus-three", "uid-three"
            ),
        ],
    ],
    ids=[
        "one",
        "ace1-plus-ace1",
        "ace1-plus-ace2",
        "ace2-plus-ace2",
        "three",
        "four",
    ],
)
def test_generator_supports_topologies_and_preserves_active_keys(devices):
    text = hardware.render(devices)
    parser = _parse_ini_text(text)

    assert dict(parser["ace_hardware"]) == {
        "driver_version": "3",
        "device_count": str(len(devices)),
        "topology_mode": "configured",
    }
    assert parser.sections() == ["ace_hardware"] + [
        f"ace_device ace{index}" for index in range(len(devices))
    ]
    for index, device in enumerate(devices):
        values = dict(parser[f"ace_device ace{index}"])
        expected_keys = {
            "model",
            "transport",
            "serial",
            "enabled",
            "rfid_enabled",
            "physical_actions_enabled",
        }
        if device.model == "ace2":
            expected_keys.update({"bus_id", "device_uid"})
        assert set(values) == expected_keys
        assert values["model"] == device.model
        assert values["serial"] == device.serial
        assert values["rfid_enabled"] == "True"
        assert values["physical_actions_enabled"] == "False"

    assert text.count("# rfid_enabled: True") == 4 - len(devices)
    for index in range(4):
        state = "已启用" if index < len(devices) else "未启用"
        assert (
            f"【ACE {index + 1}】逻辑编号 ace{index} | "
            f"工具 T{index * 4}..T{index * 4 + 3} | {state}"
            in text
        )
    assert text.count("公共字段速查（以下未启用设备共用，只说明一次）") == 1

    with tempfile.TemporaryDirectory() as temp:
        output = Path(temp) / "ace_hardware.cfg"
        output.write_text(text, encoding="utf-8")
        assert hardware.validate_file(output) == []
    _assert_chinese_template_style(text)
    assert "mmu_parameters.cfg" in text
    assert "██████" in text
    _assert_active_options_have_inline_chinese_help(text)


def test_hardware_reformat_preserves_user_device_switches(tmp_path: Path):
    source = tmp_path / "ace_hardware.cfg"
    output = tmp_path / "ace_hardware.reformatted.cfg"
    device = hardware.Device(
        "ace1",
        "/dev/serial/by-id/ace-one",
        enabled=False,
        rfid_enabled=False,
        physical_actions_enabled=False,
    )
    source.write_text(hardware.render([device]), encoding="utf-8")

    original = source.read_bytes()
    result = hardware.main(
        ["reformat", str(source), "--output", str(output)]
    )
    reformatted = output.read_text(encoding="utf-8")
    parser = _parse_ini_text(reformatted)

    assert result == 0
    assert source.read_bytes() == original
    assert hardware.read_configured_devices(output) == [device]
    assert hardware.EMBEDDED_HARDWARE_BEGIN not in reformatted
    assert hardware.EMBEDDED_HARDWARE_END not in reformatted
    assert parser.sections() == ["ace_hardware", "ace_device ace0"]
    assert parser["ace_device ace0"]["enabled"] == "False"
    assert parser["ace_device ace0"]["rfid_enabled"] == "False"
    assert parser["ace_device ace0"]["physical_actions_enabled"] == "False"
    assert "一、拓扑总表" in reformatted
    assert "# 填写：" in reformatted


@pytest.mark.parametrize("use_output", [False, True])
def test_hardware_reformat_complete_ace_cfg_only_replaces_managed_region(
    tmp_path: Path, use_output: bool
):
    source = tmp_path / "ace.cfg"
    output = tmp_path / "ace.reformatted.cfg"
    device = hardware.Device(
        "ace1",
        "/dev/serial/by-id/ace-one",
        enabled=False,
        rfid_enabled=False,
        physical_actions_enabled=False,
    )
    prefix = "\ufeff# user header\r\n# keep trailing spaces   \r\n"
    suffix = (
        "\r\n[ace]\r\n"
        "driver_version: 3\r\n"
        "[ace_machine]\r\n"
        "cut_macro: _ace_cut_filament\r\n"
        "[gcode_macro USER_TEST]\r\n"
        "gcode:\r\n"
        "    {% set message = \"keep exactly\" %}\r\n"
        "    RESPOND MSG=\"{message}\"  \r\n"
    )
    managed = hardware.render_embedded([device]).replace(
        hardware.EMBEDDED_HARDWARE_BEGIN + "\n",
        hardware.EMBEDDED_HARDWARE_BEGIN + "\n# remove during reformat\n",
        1,
    )
    source.write_bytes((prefix + managed.replace("\n", "\r\n") + suffix).encode())
    original = source.read_bytes()

    command = ["reformat", str(source)]
    target = source
    if use_output:
        command.extend(["--output", str(output)])
        target = output
    result = hardware.main(command)

    assert result == 0
    if use_output:
        assert source.read_bytes() == original
    reformatted = target.read_bytes()
    begin_marker = hardware.EMBEDDED_HARDWARE_BEGIN.encode()
    end_marker = hardware.EMBEDDED_HARDWARE_END.encode()
    begin_index = reformatted.index(begin_marker)
    end_line_index = reformatted.index(b"\r\n", reformatted.index(end_marker)) + 2
    assert reformatted[:begin_index] == prefix.encode()
    assert reformatted[end_line_index:] == suffix.encode()
    assert b"remove during reformat" not in reformatted
    assert hardware.validate_embedded_file(target) == []
    assert hardware.read_configured_devices(target) == [device]


@pytest.mark.parametrize("use_output", [False, True])
def test_hardware_reformat_rejects_damaged_complete_ace_cfg_without_writing(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    use_output: bool,
):
    source = tmp_path / "ace.cfg"
    output = tmp_path / "ace.reformatted.cfg"
    source.write_text(
        "# header\n"
        + hardware.EMBEDDED_HARDWARE_BEGIN
        + "\n"
        + hardware.render(
            [hardware.Device("ace1", "/dev/serial/by-id/ace-one")]
        )
        + "\n[ace]\ndriver_version: 3\n",
        encoding="utf-8",
    )
    original = source.read_bytes()
    command = ["reformat", str(source)]
    if use_output:
        command.extend(["--output", str(output)])

    result = hardware.main(command)

    assert result == 2
    assert source.read_bytes() == original
    assert not output.exists()
    assert "hardware configuration error:" in capsys.readouterr().err


def test_hardware_regeneration_preserves_switches_by_stable_identity():
    existing = [
        hardware.Device(
            "ace1",
            "/dev/serial/by-id/ace-one",
            enabled=False,
            rfid_enabled=False,
            physical_actions_enabled=False,
        ),
        hardware.Device(
            "ace2",
            "/dev/serial/by-id/ace-two",
            "bus0",
            "uid-two",
            rfid_enabled=False,
            physical_actions_enabled=False,
        ),
    ]
    requested = [
        hardware.Device(
            "ace2",
            "/dev/serial/by-id/ace-two",
            "bus0",
            "uid-two",
        ),
        hardware.Device("ace1", "/dev/serial/by-id/ace-one"),
    ]

    regenerated = hardware.preserve_device_settings(requested, existing)

    assert [device.enabled for device in regenerated] == [True, False]
    assert [device.rfid_enabled for device in regenerated] == [False, False]
    assert [device.physical_actions_enabled for device in regenerated] == [False, False]


def test_hardware_regeneration_does_not_transfer_enabled_to_new_device():
    existing = [
        hardware.Device(
            "ace1",
            "/dev/serial/by-id/removed",
            enabled=False,
        ),
        hardware.Device(
            "ace1",
            "/dev/serial/by-id/retained",
            enabled=False,
        ),
    ]
    requested = [
        hardware.Device("ace1", "/dev/serial/by-id/retained", enabled=True),
        hardware.Device("ace1", "/dev/serial/by-id/new", enabled=True),
    ]

    regenerated = hardware.preserve_device_settings(requested, existing)

    assert [device.enabled for device in regenerated] == [False, True]


def test_hardware_generate_preserves_disabled_device_on_reinstall(tmp_path: Path):
    source = tmp_path / "ace_hardware.cfg"
    output = tmp_path / "ace_hardware.new.cfg"
    source.write_text(
        hardware.render(
            [
                hardware.Device(
                    "ace1",
                    "/dev/serial/by-id/ace-one",
                    enabled=False,
                    rfid_enabled=False,
                    physical_actions_enabled=True,
                )
            ]
        ),
        encoding="utf-8",
    )

    result = hardware.main(
        [
            "generate",
            "--device",
            "ace1|/dev/serial/by-id/ace-one",
            "--preserve-from",
            str(source),
            "--output",
            str(output),
        ]
    )

    assert result == 0
    assert hardware.validate_file(output) == []
    regenerated = hardware.read_configured_devices(output)
    assert regenerated == [
        hardware.Device(
            "ace1",
            "/dev/serial/by-id/ace-one",
            enabled=False,
            rfid_enabled=False,
            physical_actions_enabled=True,
        )
    ]


def test_replaced_device_fails_closed_for_physical_actions():
    existing = [
        hardware.Device(
            "ace1",
            "/dev/serial/by-id/old",
            physical_actions_enabled=True,
        )
    ]
    requested = [hardware.Device("ace1", "/dev/serial/by-id/replacement")]

    regenerated = hardware.preserve_device_settings(requested, existing)

    assert regenerated[0].physical_actions_enabled is False


@pytest.mark.parametrize(
    ("section", "option"),
    [
        ("ace_hardware", "future_topology_option"),
        ("ace_device ace0", "future_device_option"),
    ],
)
def test_hardware_reformat_rejects_unknown_active_options(
    tmp_path: Path, section: str, option: str
):
    source = tmp_path / "ace_hardware.cfg"
    text = hardware.render(
        [hardware.Device("ace1", "/dev/serial/by-id/ace-one")]
    )
    marker = f"[{section}]\n"
    text = text.replace(marker, f"{marker}{option}: keep-me\n", 1)
    source.write_text(text, encoding="utf-8")

    with pytest.raises(hardware.ConfigError, match="unexpected option"):
        hardware.read_configured_devices(source)


def test_embedded_merge_migrates_exact_legacy_include_atomically(tmp_path: Path):
    ace_config = tmp_path / "ace.cfg"
    ace_config.write_text(
        "# user configuration\n"
        "[include ace_hardware.cfg]\n\n"
        "[ace]\n"
        "driver_version: 3\n"
        "[gcode_macro USER_TEST]\n"
        "gcode:\n"
        "    { this is intentionally not parsed by hardware validation }\n",
        encoding="utf-8",
    )

    result = hardware.main(
        [
            "merge",
            str(ace_config),
            "--device",
            "ace1|/dev/serial/by-id/ace-one",
        ]
    )

    assert result == 0
    text = ace_config.read_text(encoding="utf-8")
    assert "[include ace_hardware.cfg]" not in text
    assert text.count(hardware.EMBEDDED_HARDWARE_BEGIN) == 1
    assert text.count(hardware.EMBEDDED_HARDWARE_END) == 1
    assert text.index(hardware.EMBEDDED_HARDWARE_BEGIN) < text.index("[ace]")
    assert hardware.validate_embedded_file(ace_config) == []
    assert hardware.main(["validate-embedded", str(ace_config)]) == 0
    assert hardware.read_configured_devices(ace_config) == [
        hardware.Device(
            "ace1",
            "/dev/serial/by-id/ace-one",
            physical_actions_enabled=False,
        )
    ]
    assert not list(tmp_path.glob(".ace.cfg.tmp-*"))


def test_embedded_merge_is_idempotent(tmp_path: Path):
    ace_config = tmp_path / "ace.cfg"
    ace_config.write_text(
        "# header\n[include ace_hardware.cfg]\n\n[ace]\ndriver_version: 3\n",
        encoding="utf-8",
    )
    command = [
        "merge",
        str(ace_config),
        "--device",
        "ace1|/dev/serial/by-id/ace-one",
    ]

    assert hardware.main(command) == 0
    first = ace_config.read_bytes()
    assert hardware.main(command) == 0

    assert ace_config.read_bytes() == first


@pytest.mark.parametrize("source_kind", ["standalone", "embedded"])
def test_merge_preserve_from_reads_old_file_or_complete_ace_cfg(
    tmp_path: Path, source_kind: str
):
    existing = hardware.Device(
        "ace1",
        "/dev/serial/by-id/ace-one",
        enabled=False,
        rfid_enabled=False,
        physical_actions_enabled=True,
    )
    preserve_from = tmp_path / f"preserve-{source_kind}.cfg"
    if source_kind == "standalone":
        preserved_text = hardware.render([existing])
    else:
        preserved_text = (
            "# complete ace.cfg\n"
            + hardware.render_embedded([existing])
            + "\n[ace]\ndriver_version: 3\n"
        )
    preserve_from.write_text(preserved_text, encoding="utf-8")
    ace_config = tmp_path / "ace.cfg"
    ace_config.write_text("[include ace_hardware.cfg]\n", encoding="utf-8")

    result = hardware.main(
        [
            "merge",
            str(ace_config),
            "--device",
            "ace1|/dev/serial/by-id/ace-one",
            "--preserve-from",
            str(preserve_from),
        ]
    )

    assert result == 0
    assert hardware.read_configured_devices(ace_config) == [existing]


@pytest.mark.parametrize("device_count", range(1, 5))
def test_embedded_merge_supports_one_through_four_devices(
    tmp_path: Path, device_count: int
):
    devices = [
        hardware.Device("ace1", f"/dev/serial/by-id/ace-{index}")
        for index in range(device_count)
    ]
    ace_config = tmp_path / f"ace-{device_count}.cfg"
    ace_config.write_text("# ace main configuration\n", encoding="utf-8")

    merged = hardware.merge_hardware_topology(
        ace_config.read_text(encoding="utf-8"), devices
    )
    ace_config.write_text(merged, encoding="utf-8")

    assert hardware.validate_embedded_file(ace_config) == []
    assert len(hardware.read_configured_devices(ace_config)) == device_count
    parser = _parse_ini_text(
        merged.split(hardware.EMBEDDED_HARDWARE_BEGIN, 1)[1].split(
            hardware.EMBEDDED_HARDWARE_END, 1
        )[0]
    )
    assert parser["ace_hardware"]["device_count"] == str(device_count)
    assert parser.sections() == ["ace_hardware"] + [
        f"ace_device ace{index}" for index in range(device_count)
    ]


@pytest.mark.parametrize(
    "damage",
    ["missing-end", "duplicate-begin", "reversed", "duplicate-section"],
)
def test_embedded_validation_rejects_duplicate_or_damaged_boundaries(
    tmp_path: Path, damage: str, capsys: pytest.CaptureFixture[str]
):
    hardware_text = hardware.render(
        [hardware.Device("ace1", "/dev/serial/by-id/ace-one")]
    )
    if damage == "missing-end":
        text = hardware.EMBEDDED_HARDWARE_BEGIN + "\n" + hardware_text
    elif damage == "duplicate-begin":
        text = (
            hardware.EMBEDDED_HARDWARE_BEGIN
            + "\n"
            + hardware.EMBEDDED_HARDWARE_BEGIN
            + "\n"
            + hardware_text
            + hardware.EMBEDDED_HARDWARE_END
            + "\n"
        )
    elif damage == "reversed":
        text = (
            hardware.EMBEDDED_HARDWARE_END
            + "\n"
            + hardware_text
            + hardware.EMBEDDED_HARDWARE_BEGIN
            + "\n"
        )
    else:
        duplicate = hardware_text + "\n[ace_device ace0]\nenabled: False\n"
        text = (
            hardware.EMBEDDED_HARDWARE_BEGIN
            + "\n"
            + duplicate
            + hardware.EMBEDDED_HARDWARE_END
            + "\n"
        )
    ace_config = tmp_path / f"{damage}.cfg"
    ace_config.write_text(text, encoding="utf-8")

    errors = hardware.validate_embedded_file(ace_config)

    assert errors
    assert hardware.main(["validate-embedded", str(ace_config)]) == 2
    assert "hardware configuration error:" in capsys.readouterr().err
    with pytest.raises(hardware.ConfigError):
        hardware.merge_hardware_topology(
            text, [hardware.Device("ace1", "/dev/serial/by-id/ace-one")]
        )


@pytest.mark.parametrize(
    "outside_section", ["[ace_hardware]", "[ace_device ace3]"]
)
def test_embedded_validation_rejects_active_hardware_sections_outside_boundaries(
    outside_section: str,
):
    devices = [hardware.Device("ace1", "/dev/serial/by-id/ace-one")]
    text = hardware.render_embedded(devices) + f"\n{outside_section}\n"

    errors = hardware.validate_embedded_text(text)

    assert any("outside managed boundaries" in error for error in errors)
    with pytest.raises(hardware.ConfigError, match="outside managed boundaries"):
        hardware.merge_hardware_topology(text, devices)


def test_render_remains_a_pure_standalone_hardware_document():
    text = hardware.render(
        [hardware.Device("ace1", "/dev/serial/by-id/ace-one")]
    )

    assert hardware.EMBEDDED_HARDWARE_BEGIN not in text
    assert hardware.EMBEDDED_HARDWARE_END not in text
    assert dict(_parse_ini_text(text)["ace_hardware"]) == EXPECTED_HARDWARE_ROOT
