import pathlib
import unittest


ROOT = pathlib.Path(__file__).parents[1]


class ReleaseDocumentationTests(unittest.TestCase):
    def test_project_handoff_documents_are_present_and_linked(self):
        required_docs = {
            "PROJECT_MEMORY.zh-CN.md": ("ACE Pro 管理中心项目记忆", "DECISIONS.zh-CN.md"),
            "DECISIONS.zh-CN.md": ("ACE Pro 管理中心决策记录", "ADR-010"),
            "PRODUCT_BACKLOG.zh-CN.md": ("ACE Pro 管理中心产品待办", "ACE-P0-001"),
            "DEVELOPMENT.zh-CN.md": ("ACE Pro 管理中心开发手册", "manifest.sha256"),
            "DOCUMENTATION_INDEX.zh-CN.md": ("ACE Pro 管理中心文档索引", "WORK_ORDER_TEMPLATE.zh-CN.md"),
            "WORK_ORDER_TEMPLATE.zh-CN.md": ("ACE Pro 管理中心工作单模板", "验收标准"),
        }
        for filename, phrases in required_docs.items():
            content = (ROOT / "docs" / filename).read_text(encoding="utf-8")
            for phrase in phrases:
                self.assertIn(phrase, content, f"{filename} missing {phrase}")

        agent_rules = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        for filename in required_docs:
            self.assertIn(filename, agent_rules)
            self.assertIn(filename, readme)

        manifest = (ROOT / "manifest.sha256").read_text(encoding="utf-8")
        self.assertNotIn("__pycache__", manifest)
        self.assertNotIn(".pyc", manifest)
        self.assertNotIn(".pyo", manifest)
        self.assertNotIn("release-assets-v", manifest)

    def test_v120_documents_auto_drying_safety_rules(self):
        self.assertEqual(
            (ROOT / "VERSION").read_text(encoding="utf-8").strip(),
            "1.2.0",
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

    def test_driver_and_changelog_report_current_project(self):
        driver = (ROOT / "extras" / "ace.py").read_text(encoding="utf-8")
        changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        self.assertIn(
            'ACE_PRO_CONTROL_CENTER_DRIVER_VERSION = "1.2.0"', driver)
        self.assertIn("Ace Pro Control Center", changelog)

    def test_v120_major_release_guide_is_complete(self):
        guide = (
            ROOT / "docs" / "RELEASE-v1.2.0.zh-CN.md"
        ).read_text(encoding="utf-8")
        for phrase in (
            "Ace Pro Control Center",
            "Luomo520/ace-pro-control-center",
            "全新安装",
            "从旧版本升级",
            "安装后配置",
            "首次验证顺序",
            "回滚与卸载",
            "已知边界",
            "--rollback-latest",
            "--uninstall-driver",
            "THIRD_PARTY_NOTICES.md",
        ):
            self.assertIn(phrase, guide)

    def test_release_licenses_and_saved_defaults_are_distributable(self):
        self.assertEqual(
            (ROOT / "LICENSE").read_bytes(),
            (ROOT / "LICENSE.md").read_bytes(),
        )
        vue_license = (
            ROOT / "licenses" / "Vue-MIT.txt"
        ).read_text(encoding="utf-8")
        notices = (ROOT / "THIRD_PARTY_NOTICES.md").read_text(
            encoding="utf-8")
        self.assertIn("The MIT License", vue_license)
        self.assertIn("Vue-MIT.txt", notices)

        defaults = (ROOT / "saved_variables.cfg").read_text(encoding="utf-8")
        self.assertIn("ace_endless_spool_enabled = False", defaults)
        self.assertIn("ace_auto_drying_enabled = False", defaults)
        self.assertNotIn("'status': 'ready'", defaults)
        self.assertNotIn("ace_endless_spool_enabled = True", defaults)

    def test_calibration_and_preload_workflow_is_documented(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        driver_guide = (
            ROOT / "docs" / "DRIVER-v1.2.0.zh-CN.md"
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
