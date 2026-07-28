from pathlib import Path
import unittest


CONFIG_PATH = Path(__file__).parents[1] / "ace.cfg"
DRIVER_PATH = Path(__file__).parents[1] / "extras" / "ace.py"


class AceConfigLayoutTests(unittest.TestCase):
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

    def test_distance_probe_defaults_use_fast_coarse_motion(self):
        config = CONFIG_PATH.read_text(encoding="utf-8")
        self.assertIn("calibration_feed_speed: 160", config)
        self.assertIn("calibration_retract_speed: 120", config)
        self.assertIn("calibration_chunk_length: 100", config)
        self.assertIn("calibration_final_chunk_length: 100", config)
        self.assertNotIn("\ncalibration_speed:", config)

    def test_missing_save_variables_has_an_actionable_error(self):
        driver = DRIVER_PATH.read_text(encoding="utf-8")
        self.assertIn(
            "requires one global [save_variables]",
            driver,
        )


if __name__ == "__main__":
    unittest.main()
