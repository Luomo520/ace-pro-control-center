from pathlib import Path
import unittest


CONFIG_PATH = Path(__file__).parents[1] / "ace.cfg"
STYLE_REFERENCE_PATH = (
    Path(__file__).parents[1]
    / "docs"
    / "ACE_CONFIG_DETAILED_STYLE_REFERENCE.zh-CN.md"
)
DRIVER_PATH = Path(__file__).parents[1] / "extras" / "ace.py"
SPECIFICATION_PATH = (
    Path(__file__).parents[1]
    / "docs"
    / "ACE_CONFIG_SPECIFICATION.zh-CN.md"
)
SECTION_TEMPLATE_PATH = (
    Path(__file__).parents[1]
    / "docs"
    / "templates"
    / "ace-config-section.template.ini"
)
AGENT_RULES_PATH = Path(__file__).parents[1] / "AGENTS.md"

EXPECTED_DISTRIBUTED_KEYS = {
    "ace_config_version",
    "serial",
    "baud",
    "enable_debug_rpc",
    "toolchange_retract_length",
    "toolhead_sensor_to_nozzle",
    "toolchange_load_length",
    "toolchange_feed_hard_limit",
    "toolchange_retract_hard_limit",
    "extruder_sensor_debounce_count",
    "toolhead_sensor_debounce_count",
    "feed_speed",
    "feed_fast_speed",
    "feed_approach_speed",
    "feed_approach_length",
    "intermittent_feed",
    "feed_fast_chunk_length",
    "feed_slip_compensation_length",
    "feed_slip_compensation_chunk",
    "feed_slip_compensation_speed",
    "retract_speed",
    "retract_fast_speed",
    "retract_parking_speed",
    "retract_parking_length",
    "intermittent_retract",
    "bowden_tube_length",
    "five_way_parking_margin",
    "parking_sensor_position",
    "parking_sensor_clear_move_length",
    "parking_sensor_debounce_count",
    "calibration_max_retract_length",
    "calibration_speed",
    "calibration_chunk_length",
    "calibration_final_chunk_length",
    "toolhead_feed_fast_speed",
    "toolhead_feed_slow_speed",
    "toolhead_feed_fast_length",
    "toolhead_feed_fast_step",
    "toolhead_feed_slow_step",
    "toolhead_to_nozzle_speed",
    "toolhead_sensor_max_feed_length",
    "extruder_sensor_timeout",
    "ace_ready_timeout",
    "ace_stop_ready_timeout",
    "ace_request_timeout",
    "ace_reconnect_timeout",
    "ace_reconnect_stable_time",
    "ace_motion_chunk_length",
    "ace_resume_max_retries",
    "auto_toolchange_recovery",
    "auto_toolchange_recovery_max_retries",
    "auto_resume_after_ace_reconnect",
    "max_dryer_temperature",
    "unknown_material_drying_temperature",
    "unknown_material_temperature",
    "mixed_material_drying_temperature",
    "show_material_warning",
    "endless_spool",
    "endless_spool_require_same_material",
    "runout_debounce_count",
}
EXPECTED_DISTRIBUTED_KEYS.update(
    f"material_{index}_{field}"
    for index in range(1, 8)
    for field in ("name", "drying_temperature", "temperature")
)

SENSOR_PIN_KEYS = ("extruder_sensor_pin", "toolhead_sensor_pin")
PARKING_SENSOR_PIN_KEY = "parking_sensor_pin"
def ace_section(config):
    return config.split("[ace]\n", 1)[1].split("\n[gcode_macro", 1)[0]


def active_ace_keys(config):
    keys = []
    for raw_line in ace_section(config).splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        keys.append(line.split(":", 1)[0].strip())
    return keys


def activate_commented_key(config, key):
    marker = f"#{key}:"
    replacement = f"{key}:"
    if config.count(marker) != 1:
        raise AssertionError(f"expected one commented placeholder for {key}")
    return config.replace(marker, replacement, 1)


class AceConfigLayoutTests(unittest.TestCase):
    def test_config_governance_files_are_linked_and_enforced(self):
        specification = SPECIFICATION_PATH.read_text(encoding="utf-8")
        section_template = SECTION_TEMPLATE_PATH.read_text(encoding="utf-8")
        agent_rules = AGENT_RULES_PATH.read_text(encoding="utf-8")

        for phrase in (
            "功能整体介绍",
            "☆☆☆☆☆",
            "代码回退值只用于兼容旧配置",
            "后续配置变更流程",
            "ace_config_version",
        ):
            self.assertIn(phrase, specification)

        for phrase in (
            "功能整体介绍",
            "作用：",
            "填写：",
            "依赖/互斥：",
            "风险：",
        ):
            self.assertIn(phrase, section_template)

        self.assertIn("ACE_CONFIG_SPECIFICATION.zh-CN.md", agent_rules)
        self.assertIn("ace-config-section.template.ini", agent_rules)
        self.assertIn("驱动未读取", agent_rules)

    def test_distributed_template_has_canonical_sections_and_key_count(self):
        config = CONFIG_PATH.read_text(encoding="utf-8")
        headings = (
            "核心连接",
            "机器结构、必填传感器与换料路径",
            "高速送料、慢速接近与打滑补偿",
            "高速回料与停放收尾",
            "五通传感器与自动探测料管长度",
            "挤出机送料与下方传感器",
            "ACE 通信、断联与自动恢复",
            "耗材名称、烘干温度和耗材温度",
            "无限续料与断料检测",
            "CUT_TIP 示例宏",
        )
        positions = [config.index(heading) for heading in headings]
        self.assertEqual(positions, sorted(positions))

        active_keys = active_ace_keys(config)

        self.assertEqual(len(active_keys), 81)
        self.assertEqual(len(active_keys), len(set(active_keys)))
        self.assertEqual(set(active_keys), EXPECTED_DISTRIBUTED_KEYS)
        self.assertGreaterEqual(config.count("☆☆☆☆☆"), 10)

        self.assertNotIn("disable_assist_after_toolchange", config)

    def test_sensor_placeholders_expand_the_contract_to_83_and_84_keys(self):
        config = CONFIG_PATH.read_text(encoding="utf-8")

        with_required_sensors = config
        for key in SENSOR_PIN_KEYS:
            with_required_sensors = activate_commented_key(
                with_required_sensors, key
            )
        required_sensor_keys = active_ace_keys(with_required_sensors)
        self.assertEqual(len(required_sensor_keys), 83)
        self.assertEqual(len(required_sensor_keys), len(set(required_sensor_keys)))
        self.assertEqual(
            set(required_sensor_keys),
            EXPECTED_DISTRIBUTED_KEYS.union(SENSOR_PIN_KEYS),
        )

        with_parking_sensor = activate_commented_key(
            with_required_sensors, PARKING_SENSOR_PIN_KEY
        )
        all_sensor_keys = active_ace_keys(with_parking_sensor)
        self.assertEqual(len(all_sensor_keys), 84)
        self.assertEqual(len(all_sensor_keys), len(set(all_sensor_keys)))
        self.assertEqual(
            set(all_sensor_keys),
            EXPECTED_DISTRIBUTED_KEYS
            .union(SENSOR_PIN_KEYS)
            .union({PARKING_SENSOR_PIN_KEY}),
        )

    def test_machine_specific_parameters_have_canonical_star_markers(self):
        config = CONFIG_PATH.read_text(encoding="utf-8")
        required_markers = (
            "# ☆☆☆☆☆ ACE 的串口设备路径",
            "# ☆☆☆☆☆ 换色/换料时从公共通道回收到 ACE 的总距离",
            "# ☆☆☆☆☆ 下方传感器触发后继续送到喷嘴的耗材路径长度",
            "# ☆☆☆☆☆ ACE 停放位置到上方传感器的最大送料长度",
            "# ☆☆☆☆☆ 上方耗材传感器 MCU 引脚",
            "# ☆☆☆☆☆ 下方耗材传感器 MCU 引脚",
            "# ☆☆☆☆☆ ACE 出料口到五通进料口之间的实际 PTFE 管路长度",
            "# ☆☆☆☆☆ 填写本机五通传感器 MCU 引脚",
            "# 条件 ☆☆☆☆☆ after_five_way=传感器在五通之后",
            "# 条件 ☆☆☆☆☆ 传感器解除后继续向 ACE 回抽的总距离",
            "# 条件 ☆☆☆☆☆ 必须根据本机切刀位置",
        )
        for marker in required_markers:
            self.assertIn(marker, config)

        self.assertGreaterEqual(config.count("功能整体介绍："), 8)

    def test_material_profiles_stay_inside_main_ace_section(self):
        config = CONFIG_PATH.read_text(encoding="utf-8")
        self.assertNotIn("[ace_materials]", config)
        self.assertIn("[ace]\n", config)
        self.assertIn("material_1_name: PLA", config)
        self.assertIn("max_dryer_temperature: 65", config)

    def test_template_does_not_redeclare_global_sections(self):
        config = CONFIG_PATH.read_text(encoding="utf-8")
        self.assertNotIn("[save_variables]", config)
        self.assertNotIn("[respond]", config)

    def test_default_toolchange_hooks_do_not_move_or_heat(self):
        config = CONFIG_PATH.read_text(encoding="utf-8")
        active = config.split("[gcode_macro _ACE_PRE_TOOLCHANGE]", 1)[1]
        active = active.split("[gcode_macro T0]", 1)[0]
        self.assertNotIn("G1 X", active)
        self.assertNotIn("G1 Y", active)
        self.assertNotIn("M109", active)
        self.assertNotIn("CLEAN_NOZZLE", active)

    def test_debug_rpc_is_disabled_by_default(self):
        config = CONFIG_PATH.read_text(encoding="utf-8")
        self.assertIn("enable_debug_rpc: False", config)

    def test_distance_probe_defaults_are_configurable_in_ace_section(self):
        config = CONFIG_PATH.read_text(encoding="utf-8")
        probe_region = config.split(
            "# 五通传感器与自动探测料管长度", 1
        )[1].split("# ACE 烘干允许的最高温度。", 1)[0]
        expected_entries = {
            "calibration_speed: 25": 1,
            "#calibration_feed_speed: 25": 1,
            "#calibration_retract_speed: 25": 1,
            "calibration_chunk_length: 50": 1,
            "calibration_final_chunk_length: 50": 1,
        }

        for entry, count in expected_entries.items():
            self.assertEqual(config.count(entry), count)
            self.assertIn(entry, probe_region)

        self.assertIn("calibration_* 参数只影响自动探测", probe_region)
        self.assertIn("保持注释时继承 calibration_speed", probe_region)
        self.assertIn("不改变普通换料", probe_region)
        self.assertIn("+--------------------------------", probe_region)
        self.assertIn("[五通前传感器（可选）]", probe_region)
        self.assertIn("[五通后传感器（可选）]", probe_region)
        self.assertIn("只配置其中一个", probe_region)
        self.assertIn("送料沿图中箭头移动，回抽沿反方向移动", probe_region)
        self.assertIn("parking_sensor_clear_move_length 定位停放点", probe_region)

    def test_distance_probe_reference_is_merged_with_five_way_sensor(self):
        reference = STYLE_REFERENCE_PATH.read_text(encoding="utf-8")
        merged_heading = "### 四、五通传感器与自动探测料管长度"
        merged_region = reference.split(merged_heading, 1)[1].split(
            "### 五、高速送料与接近传感器送料", 1
        )[0]

        self.assertEqual(reference.count(merged_heading), 1)
        self.assertNotIn("### 九、自动探测料管长度", reference)
        self.assertIn("`calibration_speed`", merged_region)
        self.assertIn("`calibration_feed_speed`", merged_region)
        self.assertIn("`calibration_retract_speed`", merged_region)
        self.assertIn("`calibration_chunk_length`", merged_region)
        self.assertIn("`calibration_final_chunk_length`", merged_region)
        self.assertIn("只影响自动探测", merged_region)
        self.assertIn("五通前传感器（可选）", merged_region)
        self.assertIn("五通后传感器（可选）", merged_region)
        self.assertIn("实际配置只允许", merged_region)
        self.assertIn("送料沿箭头移动，回抽沿箭头反方向移动", merged_region)
        self.assertIn("`parking_sensor_clear_move_length` 定位停放点", merged_region)

    def test_missing_save_variables_has_an_actionable_error(self):
        driver = DRIVER_PATH.read_text(encoding="utf-8")
        self.assertIn(
            "requires one global [save_variables]",
            driver,
        )


if __name__ == "__main__":
    unittest.main()
