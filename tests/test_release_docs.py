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


if __name__ == "__main__":
    unittest.main()
