import pathlib
import unittest


ROOT = pathlib.Path(__file__).parents[1]


class ReleaseDocumentationTests(unittest.TestCase):
    def test_v110_documents_auto_drying_safety_rules(self):
        self.assertEqual(
            (ROOT / "VERSION").read_text(encoding="utf-8").strip(),
            "1.1.0",
        )
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        for phrase in (
            "szkrisz/ACEPROSV08",
            "不兼容 `Kobra-S1/ACEPRO`",
            "自动跟随打印",
            "全部 PLA：45°C",
            "PLA 与其他材料混装：50°C",
            "未知材料：45°C",
            "高温材料：60°C",
            "手动启动的烘干不会被自动停止",
            "AUTO_DRYING_FLOW.zh-CN.md",
            "--rollback-latest",
        ):
            self.assertIn(phrase, readme)

    def test_driver_and_changelog_report_v110(self):
        driver = (ROOT / "extras" / "ace.py").read_text(encoding="utf-8")
        changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        self.assertIn('ACEPROSV08_DRIVER_VERSION = "1.1.0-luomo"', driver)
        self.assertIn("## [1.1.0]", changelog)

    def test_calibration_and_preload_workflow_is_documented(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        driver_guide = (
            ROOT / "docs" / "DRIVER-v1.1.0.zh-CN.md"
        ).read_text(encoding="utf-8")
        config = (ROOT / "ace.cfg").read_text(encoding="utf-8")
        changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")

        for term in (
            "bowden_tube_length",
            "ACE 出料口到五通进料口",
            "ACE_PRELOAD",
            "ACE_CALIBRATE_FEED",
            "ACE_CALIBRATE_RETRACT",
            "ACE_CALIBRATION_SAVE",
            "ACE_FULL_UNLOAD",
            "preload_parked_estimated",
            "普通 T0-T3 始终送入喷嘴",
            "上下传感器必须均无料",
        ):
            self.assertIn(term, readme)
            self.assertIn(term, driver_guide)

        self.assertIn("ACE 出料口到五通进料口", config)
        self.assertNotIn(
            "ACE 停放位置到分料器/汇合点之间的实际管路长度",
            config,
        )
        self.assertIn("标定", changelog)
        self.assertIn("旧版位置状态", readme)
        self.assertIn("Fluidd v1.37.2", readme)
        self.assertIn("安装前归档", readme)


if __name__ == "__main__":
    unittest.main()
