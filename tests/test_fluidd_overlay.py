import json
from pathlib import Path

import pytest

from scripts.fluidd_overlay import (
    DASHBOARD_COMPONENT,
    DASHBOARD_COMPONENT_LEGACY,
    DASHBOARD_IMPORT,
    LAYOUT_CARD,
    NAVIGATION_BEGIN,
    NAVIGATION_BLOCK,
    NAVIGATION_BLOCK_FROM_V2,
    NAVIGATION_END,
    ROUTE_BEGIN,
    ROUTE_BLOCK,
    ROUTE_BLOCK_FROM_V2,
    ROUTE_END,
    TOOLCHANGE_CLASS,
    TOOLCHANGE_DEVICE_COUNT,
    TOOLCHANGE_GROUP,
    TOOLCHANGE_IMPORT,
    TOOLCHANGE_STYLE,
    V2_NAVIGATION,
    V2_ROUTE,
    build_guidance,
    inspect_tree,
    load_manifest,
    main,
    manifest_file_paths,
    update_tree,
)


VERSIONS = (
    ("1.34.4", "fluidd-1.34"),
    ("1.35.1", "fluidd-1.35"),
    ("1.36.4", "fluidd-1.36"),
    ("1.37.2", "fluidd-1.37"),
)

LAYOUT = """export const value = [
          { id: 'mmu-card', enabled: true, collapsed: false },
]
"""

ROUTER = """const routes = [
  {
    path: '/configure',
    name: 'configure',
    component: () => import('@/views/Configure.vue'),
    ...defaultRouteConfig,
    meta: {}
  },
  {
    path: '/settings',
    name: 'settings',
    component: () => import('@/views/Settings.vue'),
    ...defaultRouteConfig
  }
]
"""

NAVIGATION = """<template>
        <div class="nav-items">
          <app-nav-item
            icon="$codeJson"
            to="configure"
          >
            Configure
          </app-nav-item>

          <app-nav-item
            icon="$desktopTower"
            to="system"
          >
            System
          </app-nav-item>
        </div>
</template>
"""

TOOLCHANGE = """<template>
      <app-btn-group
        class="app-toolchanger-control d-flex"
        :class="{
          [$vuetify.theme.dark ? 'theme--dark': 'theme--light']: true,
        }"
      />
</template>

<script lang="ts">
import { chunk } from 'lodash-es'
import type { GcodeCommands } from '@/store/printer/types'

export default class ToolChangeCommands {
  get availableCommands (): GcodeCommands {
    return {}
  }

  get toolChangeCommandsGrouped () {
    const toolChangeCommands = this.toolChangeCommands

    const cols = Math.ceil(toolChangeCommands.length / Math.ceil(toolChangeCommands.length / 6))

    return chunk(toolChangeCommands, cols)
  }
}
</script>

<style lang="scss" scoped>
</style>
"""


def package_source(
    version: str,
    *,
    name: str = "fluidd",
    vue: str = "^2.7.16",
) -> str:
    return json.dumps(
        {
            "name": name,
            "version": version,
            "packageManager": "pnpm@9.15.4",
            "scripts": {"build": "vite build"},
            "dependencies": {
                "vue": vue,
                "vue-router": "^3.6.5",
                "vuetify": "^2.7.2",
                "vue-property-decorator": "^9.1.2",
            },
        },
        indent=2,
    )


def dashboard_source(version: str) -> str:
    minor = int(version.split(".")[1])
    optional_imports = ""
    optional_components = ""
    if minor >= 36:
        optional_imports += "import AfcCard from '@/components/widgets/afc/AfcCard.vue'\n"
        optional_components += "    AfcCard,\n"
    if minor >= 37:
        optional_imports += "import type Sortable from 'sortablejs'\n"
    return f"""<script lang="ts">
import {{ Component, Mixins }} from 'vue-property-decorator'
import StateMixin from '@/mixins/state'
import PrinterStatusCard from '@/components/widgets/status/PrinterStatusCard.vue'
{optional_imports}@Component({{
  components: {{
    PrinterStatusCard,
{optional_components}  }}
}})
export default class Dashboard extends Mixins(StateMixin) {{}}
</script>
"""


def make_tree(
    tmp_path: Path,
    version: str = "1.37.2",
    *,
    package_name: str = "fluidd",
    vue: str = "^2.7.16",
) -> Path:
    files = {
        "package.json": package_source(version, name=package_name, vue=vue),
        "src/views/Dashboard.vue": dashboard_source(version),
        "src/store/layout/state.ts": LAYOUT,
        "src/router/index.ts": ROUTER,
        "src/components/layout/AppNavDrawer.vue": NAVIGATION,
        "src/components/widgets/toolhead/ToolChangeCommands.vue": TOOLCHANGE,
    }
    for relative, source in files.items():
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, encoding="utf-8")
    return tmp_path


def tree_sources(root: Path) -> dict[str, str]:
    manifest = load_manifest()
    return {
        role: (root / relative).read_text(encoding="utf-8")
        for role, relative in manifest["patched_source_files"].items()
        if (root / relative).is_file()
    }


def install_v2_blocks(root: Path) -> None:
    router = root / "src/router/index.ts"
    router.write_text(
        router.read_text(encoding="utf-8").replace(
            "  {\n    path: '/settings',", V2_ROUTE + "\n  {\n    path: '/settings',", 1
        ),
        encoding="utf-8",
    )
    navigation = root / "src/components/layout/AppNavDrawer.vue"
    navigation.write_text(
        navigation.read_text(encoding="utf-8").replace(
            "          <app-nav-item\n            icon=\"$desktopTower\"",
            V2_NAVIGATION
            + "\n\n          <app-nav-item\n            icon=\"$desktopTower\"",
            1,
        ),
        encoding="utf-8",
    )


@pytest.mark.parametrize(("version", "profile"), VERSIONS)
def test_every_supported_profile_full_lifecycle(tmp_path, version, profile):
    root = make_tree(tmp_path, version)
    before = tree_sources(root)

    inspection = inspect_tree(root)
    assert inspection["compatible"] is True
    assert inspection["profile"] == profile
    assert all(inspection["capabilities"].values())

    check_report = update_tree(root, "check")
    assert check_report["changed_files"] == manifest_file_paths()
    assert tree_sources(root) == before

    update_tree(root, "apply")
    first_apply = tree_sources(root)
    second_report = update_tree(root, "apply")
    assert second_report["changed_files"] == []
    assert tree_sources(root) == first_apply

    assert first_apply["dashboard"].count(DASHBOARD_IMPORT) == 1
    assert first_apply["dashboard"].count(DASHBOARD_COMPONENT) == 1
    assert first_apply["layout"].count(LAYOUT_CARD) == 1
    assert first_apply["router"].count(ROUTE_BLOCK) == 1
    assert first_apply["navigation"].count(NAVIGATION_BLOCK) == 1
    assert first_apply["toolchange"].count(TOOLCHANGE_IMPORT) == 1
    assert first_apply["toolchange"].count(TOOLCHANGE_DEVICE_COUNT) == 1
    assert first_apply["toolchange"].count(TOOLCHANGE_GROUP) == 1
    assert first_apply["toolchange"].count(TOOLCHANGE_STYLE) == 1
    assert first_apply["toolchange"].count(TOOLCHANGE_CLASS) == 1

    remove_report = update_tree(root, "remove")
    assert remove_report["missing_files"] == []
    assert tree_sources(root) == before


def test_apply_normalizes_legacy_dashboard_component_without_duplicate(tmp_path):
    root = make_tree(tmp_path)
    update_tree(root, "apply")
    dashboard = root / "src/views/Dashboard.vue"
    dashboard.write_text(
        dashboard.read_text(encoding="utf-8").replace(
            DASHBOARD_COMPONENT, DASHBOARD_COMPONENT_LEGACY, 1
        ),
        encoding="utf-8",
    )

    update_tree(root, "apply")
    normalized = dashboard.read_text(encoding="utf-8")

    assert normalized.count(DASHBOARD_COMPONENT) == 1
    assert DASHBOARD_COMPONENT_LEGACY not in normalized
    assert update_tree(root, "apply")["changed_files"] == []


@pytest.mark.parametrize("version", ("1.33.9", "1.38.0", "2.0.0"))
def test_old_and_future_versions_are_rejected_before_writing(tmp_path, version):
    root = make_tree(tmp_path, version)
    before = tree_sources(root)
    report = inspect_tree(root)
    assert report["compatible"] is False
    assert report["profile"] is None
    assert any("outside supported" in reason for reason in report["reasons"])
    with pytest.raises(ValueError, match="outside supported"):
        update_tree(root, "apply")
    assert tree_sources(root) == before


@pytest.mark.parametrize(
    ("package_name", "vue", "message"),
    (("vendor-fluidd", "^2.7.16", "official Fluidd"), ("fluidd", "^3.5.0", "vue must declare major 2")),
)
def test_unknown_framework_is_rejected(tmp_path, package_name, vue, message):
    root = make_tree(tmp_path, package_name=package_name, vue=vue)
    report = inspect_tree(root)
    assert report["compatible"] is False
    assert any(message in reason for reason in report["reasons"])
    with pytest.raises(ValueError, match=message):
        update_tree(root, "check")


@pytest.mark.parametrize("package", ({}, [], "not-an-object"))
def test_missing_or_non_object_package_metadata_is_rejected(tmp_path, package):
    root = make_tree(tmp_path)
    (root / "package.json").write_text(json.dumps(package), encoding="utf-8")

    report = inspect_tree(root)

    assert report["compatible"] is False
    assert any("official Fluidd" in reason for reason in report["reasons"])
    assert any("stable major.minor.patch" in reason for reason in report["reasons"])


def test_pnpm_catalog_framework_dependency_is_resolved(tmp_path):
    root = make_tree(tmp_path, vue="catalog:")
    (root / "pnpm-workspace.yaml").write_text(
        "minimumReleaseAge: 1440\n\ncatalog:\n  vue: ^2.7.16\n  vite: ^8.1.3\n",
        encoding="utf-8",
    )
    report = inspect_tree(root)
    assert report["compatible"] is True
    assert report["framework"]["vue"]["declared"] == "catalog:"
    assert report["framework"]["vue"]["resolved"] == "^2.7.16"


def test_capability_probe_rejects_ambiguous_mmu_anchor(tmp_path):
    root = make_tree(tmp_path)
    layout = root / "src/store/layout/state.ts"
    layout.write_text(LAYOUT + LAYOUT, encoding="utf-8")
    report = inspect_tree(root)
    assert report["capabilities"]["layout_mmu_card"] is False
    with pytest.raises(ValueError, match="layout_mmu_card"):
        update_tree(root, "apply")


def test_exact_v2_route_and_navigation_are_taken_over(tmp_path):
    root = make_tree(tmp_path)
    install_v2_blocks(root)
    v2_sources = tree_sources(root)
    update_tree(root, "apply")
    sources = tree_sources(root)
    assert sources["router"].count(ROUTE_BEGIN) == 1
    assert sources["router"].count(ROUTE_END) == 1
    assert sources["navigation"].count(NAVIGATION_BEGIN) == 1
    assert sources["navigation"].count(NAVIGATION_END) == 1
    assert sources["router"].count(ROUTE_BLOCK_FROM_V2) == 1
    assert sources["navigation"].count(NAVIGATION_BLOCK_FROM_V2) == 1
    assert "componentSupport']('ace_status')" in sources["navigation"]

    update_tree(root, "remove")
    restored = tree_sources(root)
    assert restored["router"] == v2_sources["router"]
    assert restored["navigation"] == v2_sources["navigation"]


def test_remove_does_not_claim_unmarked_v2_blocks(tmp_path):
    root = make_tree(tmp_path)
    install_v2_blocks(root)
    before = tree_sources(root)
    update_tree(root, "remove")
    assert tree_sources(root) == before


def test_unknown_route_conflict_fails_before_any_write(tmp_path):
    root = make_tree(tmp_path)
    router = root / "src/router/index.ts"
    router.write_text(
        router.read_text(encoding="utf-8").replace(
            "  {\n    path: '/settings',",
            "  { path: '/acepro', name: 'vendor-ace' },\n  {\n    path: '/settings',",
            1,
        ),
        encoding="utf-8",
    )
    before = tree_sources(root)
    with pytest.raises(ValueError, match="route conflict"):
        update_tree(root, "apply")
    assert tree_sources(root) == before


def test_unknown_navigation_conflict_fails_before_any_write(tmp_path):
    root = make_tree(tmp_path)
    navigation = root / "src/components/layout/AppNavDrawer.vue"
    navigation.write_text(
        navigation.read_text(encoding="utf-8").replace(
            "          <app-nav-item\n            icon=\"$desktopTower\"",
            "          <vendor-nav to=\"acepro\" />\n"
            "          <app-nav-item\n            icon=\"$desktopTower\"",
            1,
        ),
        encoding="utf-8",
    )
    before = tree_sources(root)
    with pytest.raises(ValueError, match="navigation conflict"):
        update_tree(root, "apply")
    assert tree_sources(root) == before


def test_missing_source_is_reported_by_inspect_and_check(tmp_path):
    root = make_tree(tmp_path)
    (root / "src/router/index.ts").unlink()
    report = inspect_tree(root)
    assert report["files"]["router"]["exists"] is False
    with pytest.raises(ValueError, match="src/router/index.ts"):
        update_tree(root, "check")


def test_remove_cleans_remaining_files_after_fluidd_upgrade(tmp_path):
    root = make_tree(tmp_path)
    originals = tree_sources(root)
    update_tree(root, "apply")
    missing = root / "src/store/layout/state.ts"
    missing.unlink()
    (root / "package.json").write_text(package_source("1.38.0"), encoding="utf-8")

    report = update_tree(root, "remove")
    assert report["missing_files"] == ["src/store/layout/state.ts"]
    remaining = tree_sources(root)
    assert remaining["dashboard"] == originals["dashboard"]
    assert remaining["router"] == originals["router"]
    assert remaining["navigation"] == originals["navigation"]


def test_inspect_and_files_commands_emit_machine_readable_results(tmp_path, capsys):
    root = make_tree(tmp_path, "1.35.1")
    assert main(["inspect", str(root)]) == 0
    inspection = json.loads(capsys.readouterr().out)
    assert inspection["compatible"] is True
    assert inspection["profile"] == "fluidd-1.35"

    assert main(["files"]) == 0
    assert capsys.readouterr().out.splitlines() == manifest_file_paths()


def test_build_guidance_uses_declared_versioned_toolchain(tmp_path):
    root = make_tree(tmp_path)
    (root / "pnpm-lock.yaml").write_text("lockfileVersion: '9.0'\n", encoding="utf-8")

    report = build_guidance(root)

    assert report["toolchain"] == "pnpm@9.15.4"
    assert report["toolchain_source"] == "package.json#packageManager"
    assert report["setup_command"] == "corepack prepare pnpm@9.15.4 --activate"
    assert report["install_command"] == "pnpm install --frozen-lockfile"
    assert report["build_command"] == "pnpm run build"
    assert report["build_script_present"] is True
    assert report["dist"] == str(root / "dist")


def test_build_guidance_reports_missing_build_script(tmp_path):
    root = make_tree(tmp_path)
    package = json.loads((root / "package.json").read_text(encoding="utf-8"))
    del package["scripts"]
    (root / "package.json").write_text(json.dumps(package), encoding="utf-8")

    assert build_guidance(root)["build_script_present"] is False


def test_manifest_is_the_single_file_and_profile_contract():
    manifest = load_manifest()
    assert manifest["supported_versions"] == {
        "minimum": "1.34.0",
        "maximum_exclusive": "1.38.0",
    }
    assert [profile["name"] for profile in manifest["profiles"]] == [
        "fluidd-1.34",
        "fluidd-1.35",
        "fluidd-1.36",
        "fluidd-1.37",
    ]
    assert set(manifest["patched_source_files"]) == {
        "dashboard",
        "layout",
        "router",
        "navigation",
        "toolchange",
    }
    assert manifest_file_paths(manifest) == list(
        manifest["patched_source_files"].values()
    )


def test_overlay_page_reuses_card_in_page_mode():
    repo = Path(__file__).parents[1]
    page = (repo / "frontend/fluidd-overlay/src/views/AcePro.vue").read_text(
        encoding="utf-8"
    )
    assert "AceV3Card" in page
    assert ':show-page-link="false"' in page
    assert ':collapse-extra-functions="false"' in page

    manifest = load_manifest()
    assert manifest["page"] == "src/views/AcePro.vue"
    assert manifest["route"] == "/acepro"
    assert len(manifest["patched_source_files"]) == 5


def test_overlay_includes_vue_component_declaration():
    declaration = (
        Path(__file__).parents[1]
        / "frontend/fluidd-overlay/src/components/widgets/ace-v3/AceV3Card.vue.d.ts"
    )
    source = declaration.read_text(encoding="utf-8")
    assert "VueConstructor" in source
    assert "export default component" in source
