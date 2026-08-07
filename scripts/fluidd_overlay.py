#!/usr/bin/env python3
"""Inspect, register, or remove the Ace Pro Control Center Fluidd integration."""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import sys
from pathlib import Path
from typing import Any


MANIFEST_PATH = (
    Path(__file__).resolve().parents[1]
    / "frontend"
    / "fluidd-overlay"
    / "manifest.json"
)

DASHBOARD_IMPORT = (
    "import AceV3Card from '@/components/widgets/ace-v3/AceV3Card.vue' "
    "// ACE Driver V3 managed import"
)
DASHBOARD_COMPONENT = "    'ace-v3-card': AceV3Card, // ACE Driver V3 managed component"
DASHBOARD_COMPONENT_LEGACY = "    'ace-v3-card': AceV3Card // ACE Driver V3 managed component"
LAYOUT_CARD = "          { id: 'ace-v3-card', enabled: true, collapsed: false }, // ACE Driver V3 managed card"

ROUTE_BEGIN = "  // >>> ACE Driver V3 managed route >>>"
ROUTE_END = "  // <<< ACE Driver V3 managed route <<<"
ROUTE_RESTORE_V2 = "  // ACE Driver V3 restore V2 route on removal"
V2_ROUTE = """  {
    path: '/acepro',
    name: 'acepro',
    component: () => import('@/views/AcePro.vue'),
    ...defaultRouteConfig
  },"""
ROUTE_BLOCK = f"{ROUTE_BEGIN}\n{V2_ROUTE}\n{ROUTE_END}"
ROUTE_BLOCK_FROM_V2 = (
    f"{ROUTE_BEGIN}\n{ROUTE_RESTORE_V2}\n{V2_ROUTE}\n{ROUTE_END}"
)
ROUTE_ANCHOR = """  {
    path: '/settings',
    name: 'settings',"""

NAVIGATION_BEGIN = "          <!-- >>> ACE Driver V3 managed navigation >>> -->"
NAVIGATION_END = "          <!-- <<< ACE Driver V3 managed navigation <<< -->"
NAVIGATION_RESTORE_V2 = (
    "          <!-- ACE Driver V3 restore V2 navigation on removal -->"
)
V2_NAVIGATION = """          <app-nav-item
            v-if="supportsAcePro"
            icon="$mmu"
            to="acepro"
          >
            ACE Pro
          </app-nav-item>"""
V3_NAVIGATION = """          <app-nav-item
            v-if="$typedGetters['server/componentSupport']('ace_status')"
            icon="$mmu"
            to="acepro"
          >
            ACE Pro
          </app-nav-item>"""
NAVIGATION_BLOCK = f"{NAVIGATION_BEGIN}\n{V3_NAVIGATION}\n{NAVIGATION_END}"
NAVIGATION_BLOCK_FROM_V2 = (
    f"{NAVIGATION_BEGIN}\n{NAVIGATION_RESTORE_V2}\n"
    f"{V3_NAVIGATION}\n{NAVIGATION_END}"
)
NAVIGATION_ANCHOR = """          <app-nav-item
            icon="$desktopTower"
            to="system"""  # Insert beside Fluidd's other primary navigation items.

DASHBOARD_COMPONENT_ANCHOR = re.compile(r"(?m)^  components:\s*\{\s*$")
DASHBOARD_IMPORT_ANCHOR = re.compile(r"(?m)^import [^\r\n]+$")
LAYOUT_MMU_ANCHOR = re.compile(
    r"(?m)^\s*\{ id: ['\"]mmu-card['\"], enabled: (?:true|false), "
    r"collapsed: (?:true|false) \},?\s*$"
)

TOOLCHANGE_IMPORT_BEGIN = "// >>> ACE Driver V3 managed tool grid import >>>"
TOOLCHANGE_IMPORT_END = "// <<< ACE Driver V3 managed tool grid import <<<"
TOOLCHANGE_IMPORT = f"""{TOOLCHANGE_IMPORT_BEGIN}
import {{
  getAceDeviceCount,
  getAceToolCommandGroups,
}} from './ace-tool-commands.js'
{TOOLCHANGE_IMPORT_END}"""
TOOLCHANGE_DEVICE_COUNT_BEGIN = "  // >>> ACE Driver V3 managed device count >>>"
TOOLCHANGE_DEVICE_COUNT_END = "  // <<< ACE Driver V3 managed device count <<<"
TOOLCHANGE_DEVICE_COUNT = f"""{TOOLCHANGE_DEVICE_COUNT_BEGIN}
  get aceDeviceCount (): number | null {{
    return getAceDeviceCount(this.$typedState.printer.printer)
  }}

{TOOLCHANGE_DEVICE_COUNT_END}"""
TOOLCHANGE_GROUP_BEGIN = "    // >>> ACE Driver V3 managed tool grouping >>>"
TOOLCHANGE_GROUP_END = "    // <<< ACE Driver V3 managed tool grouping <<<"
TOOLCHANGE_GROUP = f"""{TOOLCHANGE_GROUP_BEGIN}
    const aceGroups = getAceToolCommandGroups(
      toolChangeCommands,
      this.aceDeviceCount
    )
    if (aceGroups !== null) return aceGroups
{TOOLCHANGE_GROUP_END}"""
TOOLCHANGE_STYLE_BEGIN = "  /* >>> ACE Driver V3 managed tool grid >>> */"
TOOLCHANGE_STYLE_END = "  /* <<< ACE Driver V3 managed tool grid <<< */"
TOOLCHANGE_STYLE = f"""{TOOLCHANGE_STYLE_BEGIN}
  .app-toolchanger-control--ace {{
    display: grid !important;
    grid-template-columns: repeat(4, minmax(0, 1fr));
    gap: 2px;
    width: 100%;

    > :deep(.v-btn) {{
      width: 100%;
      min-width: 0 !important;
      margin-right: 0 !important;
    }}
  }}
{TOOLCHANGE_STYLE_END}"""
TOOLCHANGE_CLASS = (
    "          'app-toolchanger-control--ace': aceDeviceCount !== null, "
    "// ACE Driver V3 managed class"
)
TOOLCHANGE_IMPORT_ANCHOR = "import { chunk } from 'lodash-es'"
TOOLCHANGE_CLASS_ANCHOR = (
    "          [$vuetify.theme.dark ? 'theme--dark': 'theme--light']: true,"
)
TOOLCHANGE_GETTER_ANCHOR = "  get availableCommands (): GcodeCommands {"
TOOLCHANGE_GROUP_ANCHOR = "    const toolChangeCommands = this.toolChangeCommands"
TOOLCHANGE_STYLE_ANCHOR = "</style>"


def load_manifest(path: Path = MANIFEST_PATH) -> dict[str, Any]:
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("Fluidd overlay manifest cannot be read: %s" % exc) from exc

    files = manifest.get("patched_source_files")
    if not isinstance(files, dict) or not files:
        raise ValueError("Fluidd overlay manifest patched_source_files must be an object")
    if not all(isinstance(role, str) and isinstance(value, str) for role, value in files.items()):
        raise ValueError("Fluidd overlay manifest file roles and paths must be strings")
    if len(set(files.values())) != len(files):
        raise ValueError("Fluidd overlay manifest contains duplicate source paths")
    return manifest


def manifest_file_paths(manifest: dict[str, Any] | None = None) -> list[str]:
    data = manifest or load_manifest()
    return list(data["patched_source_files"].values())


def _parse_version(value: str) -> tuple[int, int, int] | None:
    match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)", value)
    if match is None:
        return None
    return tuple(int(part) for part in match.groups())  # type: ignore[return-value]


def _profile_for_version(
    version: tuple[int, int, int], manifest: dict[str, Any]
) -> dict[str, Any] | None:
    for profile in manifest.get("profiles", []):
        minimum = _parse_version(profile.get("minimum", ""))
        maximum = _parse_version(profile.get("maximum_exclusive", ""))
        if minimum is not None and maximum is not None and minimum <= version < maximum:
            return profile
    return None


def _dependency_major(specification: object) -> int | None:
    if not isinstance(specification, str):
        return None
    match = re.search(r"(?:^|\|\|)\s*[~^<>= ]*(\d+)(?:\.|$)", specification)
    return int(match.group(1)) if match else None


def _catalog_dependency(root: Path, dependency: str) -> str | None:
    workspace = root / "pnpm-workspace.yaml"
    if not workspace.is_file():
        return None
    source = workspace.read_text(encoding="utf-8")
    catalog = re.search(r"(?ms)^catalog:\s*\n(?P<body>(?:^[ \t]+.*(?:\n|$))*)", source)
    if catalog is None:
        return None
    entry = re.search(
        r"(?m)^[ \t]+%s:\s*['\"]?(?P<value>[^'\"#\r\n]+)"
        % re.escape(dependency),
        catalog.group("body"),
    )
    return entry.group("value").strip() if entry else None


def _source_capabilities(sources: dict[str, str]) -> dict[str, bool]:
    dashboard = sources.get("dashboard", "")
    layout = sources.get("layout", "")
    router = sources.get("router", "")
    navigation = sources.get("navigation", "")
    toolchange = sources.get("toolchange", "")
    return {
        "dashboard_typescript_class_component": (
            '<script lang="ts">' in dashboard
            and dashboard.count("@Component({") == 1
            and len(DASHBOARD_COMPONENT_ANCHOR.findall(dashboard)) == 1
            and bool(DASHBOARD_IMPORT_ANCHOR.search(dashboard))
        ),
        "layout_mmu_card": len(LAYOUT_MMU_ANCHOR.findall(layout)) == 1,
        "router_settings_route": router.count(ROUTE_ANCHOR) == 1,
        "navigation_system_item": navigation.count(NAVIGATION_ANCHOR) == 1,
        "toolchange_ace_grid": (
            toolchange.count(TOOLCHANGE_IMPORT_ANCHOR) == 1
            and toolchange.count(TOOLCHANGE_CLASS_ANCHOR) == 1
            and toolchange.count(TOOLCHANGE_GETTER_ANCHOR) == 1
            and toolchange.count(TOOLCHANGE_GROUP_ANCHOR) == 1
            and toolchange.count(TOOLCHANGE_STYLE_ANCHOR) == 1
            and toolchange.count("export default class ToolChangeCommands") == 1
        ),
    }


def inspect_tree(root: Path) -> dict[str, Any]:
    root = root.resolve()
    manifest = load_manifest()
    reasons: list[str] = []
    package_path = root / "package.json"
    package: dict[str, Any] = {}
    if package_path.is_file():
        try:
            loaded_package = json.loads(package_path.read_text(encoding="utf-8"))
            if isinstance(loaded_package, dict):
                package = loaded_package
            else:
                reasons.append("package.json root must be a JSON object")
        except (OSError, json.JSONDecodeError) as exc:
            reasons.append("package.json is not valid JSON: %s" % exc)
    else:
        reasons.append("Fluidd source tree lacks package.json")

    package_name = package.get("name")
    version_text = package.get("version")
    parsed_version = _parse_version(version_text) if isinstance(version_text, str) else None
    profile = _profile_for_version(parsed_version, manifest) if parsed_version else None
    if package_name != manifest["framework"]["package_name"]:
        reasons.append("package.json is not the official Fluidd package")
    if parsed_version is None:
        reasons.append("Fluidd version must use stable major.minor.patch format")
    elif profile is None:
        supported = manifest["supported_versions"]
        reasons.append(
            "Fluidd %s is outside supported source-overlay range %s to <%s"
            % (version_text, supported["minimum"], supported["maximum_exclusive"])
        )

    dependencies = package.get("dependencies", {}) if isinstance(package, dict) else {}
    framework_result: dict[str, Any] = {}
    for dependency, expected_major in manifest["framework"]["dependencies"].items():
        actual_spec = dependencies.get(dependency) if isinstance(dependencies, dict) else None
        resolved_spec = (
            _catalog_dependency(root, dependency)
            if actual_spec == "catalog:"
            else actual_spec
        )
        actual_major = _dependency_major(resolved_spec)
        valid = actual_major == expected_major
        framework_result[dependency] = {
            "required_major": expected_major,
            "declared": actual_spec,
            "resolved": resolved_spec,
            "compatible": valid,
        }
        if not valid:
            reasons.append(
                "Fluidd framework dependency %s must declare major %s"
                % (dependency, expected_major)
            )

    file_entries = manifest["patched_source_files"]
    file_result: dict[str, Any] = {}
    sources: dict[str, str] = {}
    for role, relative in file_entries.items():
        path = root / relative
        exists = path.is_file()
        file_result[role] = {"path": relative, "exists": exists}
        if exists:
            sources[role] = path.read_text(encoding="utf-8")
        else:
            reasons.append("Fluidd source tree lacks required file: %s" % relative)

    capabilities = _source_capabilities(sources)
    required_features = profile.get("required_features", []) if profile else []
    for feature in required_features:
        if not capabilities.get(feature, False):
            reasons.append("Fluidd source capability is missing or ambiguous: %s" % feature)

    return {
        "compatible": not reasons,
        "root": str(root),
        "fluidd": {"name": package_name, "version": version_text},
        "profile": profile.get("name") if profile else None,
        "supported_versions": manifest["supported_versions"],
        "framework": framework_result,
        "capabilities": capabilities,
        "files": file_result,
        "reasons": reasons,
    }


def build_guidance(root: Path) -> dict[str, Any]:
    """Describe checkout-specific commands required after source patching."""
    root = root.resolve()
    package_path = root / "package.json"
    try:
        package = json.loads(package_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("Fluidd package.json cannot be read: %s" % exc) from exc
    if not isinstance(package, dict):
        raise ValueError("Fluidd package.json root must be an object")

    declared = package.get("packageManager")
    manager = ""
    version = ""
    source = "package.json#packageManager"
    if isinstance(declared, str) and re.fullmatch(
        r"(?:npm|pnpm|yarn)@[A-Za-z0-9._+\-]+", declared
    ):
        manager, version = declared.split("@", 1)
    else:
        source = "lockfile"
        if (root / "pnpm-lock.yaml").is_file():
            manager = "pnpm"
        elif (root / "yarn.lock").is_file():
            manager = "yarn"
        elif (root / "package-lock.json").is_file() or (
            root / "npm-shrinkwrap.json"
        ).is_file():
            manager = "npm"
        else:
            source = "fallback"
            manager = "npm"

    setup_command = None
    if version and manager in {"pnpm", "yarn"}:
        setup_command = "corepack prepare %s@%s --activate" % (manager, version)
    if manager == "npm":
        has_lock = (root / "package-lock.json").is_file() or (
            root / "npm-shrinkwrap.json"
        ).is_file()
        install_command = "npm ci" if has_lock else "npm install"
    elif manager == "pnpm":
        install_command = (
            "pnpm install --frozen-lockfile"
            if (root / "pnpm-lock.yaml").is_file()
            else "pnpm install"
        )
    else:
        major = int(version.split(".", 1)[0]) if version[:1].isdigit() else None
        if (root / "yarn.lock").is_file():
            flag = "--frozen-lockfile" if major == 1 else "--immutable"
            install_command = "yarn install %s" % flag
        else:
            install_command = "yarn install"

    scripts = package.get("scripts") if isinstance(package.get("scripts"), dict) else {}
    build_script_present = isinstance(scripts.get("build"), str) and bool(
        scripts.get("build", "").strip()
    )
    build_command = "%s run build" % manager
    return {
        "root": str(root),
        "toolchain": "%s@%s" % (manager, version) if version else manager,
        "toolchain_source": source,
        "setup_command": setup_command,
        "install_command": install_command,
        "build_command": build_command,
        "build_script_present": build_script_present,
        "dist": str(root / "dist"),
        "shell_steps": [
            "cd -- %s" % shlex.quote(str(root)),
            *([setup_command] if setup_command else []),
            install_command,
            build_command,
        ],
    }


def _insert_once(text: str, line: str, anchor: str, *, after: bool) -> str:
    if line in text:
        return text
    count = text.count(anchor)
    if count != 1:
        raise ValueError(
            "Fluidd compatibility anchor must occur exactly once (%d found): %s"
            % (count, anchor)
        )
    if after:
        return text.replace(anchor, anchor + "\n" + line, 1)
    return text.replace(anchor, line + "\n" + anchor, 1)


def _marker_state(text: str, begin: str, end: str, label: str) -> bool:
    begin_count = text.count(begin)
    end_count = text.count(end)
    if begin_count == 0 and end_count == 0:
        return False
    if begin_count != 1 or end_count != 1 or text.index(begin) > text.index(end):
        raise ValueError("Fluidd %s managed markers are malformed or duplicated" % label)
    return True


def _remove_marked_block(text: str, begin: str, end: str, label: str) -> str:
    if not _marker_state(text, begin, end, label):
        return text
    start = text.index(begin)
    finish = text.index(end, start) + len(end)
    if text[finish : finish + 2] == "\r\n":
        finish += 2
    elif text[finish : finish + 1] == "\n":
        finish += 1
    return text[:start] + text[finish:]


def _has_route_conflict(text: str) -> bool:
    patterns = (
        r"\bpath\s*:\s*['\"]\/acepro['\"]",
        r"\bname\s*:\s*['\"]acepro['\"]",
        r"@/views/AcePro\.vue",
    )
    return any(re.search(pattern, text) for pattern in patterns)


def _has_navigation_conflict(text: str) -> bool:
    return bool(re.search(r"\bto\s*=\s*['\"]acepro['\"]", text))


def _remove_managed_lines(text: str, managed: tuple[str, ...]) -> str:
    return "".join(
        line
        for line in text.splitlines(keepends=True)
        if line.rstrip("\r\n") not in managed
    )


def patch_dashboard(text: str) -> str:
    if DASHBOARD_IMPORT not in text:
        imports = list(DASHBOARD_IMPORT_ANCHOR.finditer(text))
        if not imports:
            raise ValueError("Fluidd Dashboard has no compatible import block")
        anchor = imports[-1]
        text = text[: anchor.end()] + "\n" + DASHBOARD_IMPORT + text[anchor.end() :]

    # Older V3 builds omitted the comma because this entry was last in the
    # object. Normalize both forms so upgrading remains idempotent.
    text = _remove_managed_lines(
        text, (DASHBOARD_COMPONENT, DASHBOARD_COMPONENT_LEGACY)
    )
    anchors = list(DASHBOARD_COMPONENT_ANCHOR.finditer(text))
    if len(anchors) != 1:
        raise ValueError(
            "Fluidd Dashboard components anchor must occur exactly once (%d found)"
            % len(anchors)
        )
    anchor = anchors[0]
    text = text[: anchor.end()] + "\n" + DASHBOARD_COMPONENT + text[anchor.end() :]
    return text


def patch_layout(text: str) -> str:
    if LAYOUT_CARD in text:
        return text
    anchors = list(LAYOUT_MMU_ANCHOR.finditer(text))
    if len(anchors) != 1:
        raise ValueError(
            "Fluidd layout mmu-card anchor must occur exactly once (%d found)"
            % len(anchors)
        )
    anchor = anchors[0]
    return text[: anchor.end()] + "\n" + LAYOUT_CARD + text[anchor.end() :]


def patch_router(text: str) -> str:
    if _marker_state(text, ROUTE_BEGIN, ROUTE_END, "route"):
        managed_count = text.count(ROUTE_BLOCK) + text.count(ROUTE_BLOCK_FROM_V2)
        if managed_count != 1:
            raise ValueError("Fluidd managed /acepro route was changed outside the installer")
        unmanaged = _remove_marked_block(text, ROUTE_BEGIN, ROUTE_END, "route")
        if _has_route_conflict(unmanaged):
            raise ValueError("Fluidd has an additional unmanaged /acepro route conflict")
        return text

    v2_count = text.count(V2_ROUTE)
    if v2_count:
        if v2_count != 1:
            raise ValueError("Fluidd has duplicate V2 /acepro routes")
        unmanaged = text.replace(V2_ROUTE, "", 1)
        if _has_route_conflict(unmanaged):
            raise ValueError("Fluidd has an additional unmanaged /acepro route conflict")
        return text.replace(V2_ROUTE, ROUTE_BLOCK_FROM_V2, 1)

    if _has_route_conflict(text):
        raise ValueError("Fluidd has an unmanaged /acepro route conflict")
    return _insert_once(text, ROUTE_BLOCK, ROUTE_ANCHOR, after=False)


def patch_navigation(text: str) -> str:
    if _marker_state(text, NAVIGATION_BEGIN, NAVIGATION_END, "navigation"):
        managed_count = text.count(NAVIGATION_BLOCK) + text.count(
            NAVIGATION_BLOCK_FROM_V2
        )
        if managed_count != 1:
            raise ValueError("Fluidd managed ACE Pro navigation was changed outside the installer")
        unmanaged = _remove_marked_block(
            text, NAVIGATION_BEGIN, NAVIGATION_END, "navigation"
        )
        if _has_navigation_conflict(unmanaged):
            raise ValueError("Fluidd has an additional unmanaged ACE Pro navigation conflict")
        return text

    v2_count = text.count(V2_NAVIGATION)
    if v2_count:
        if v2_count != 1:
            raise ValueError("Fluidd has duplicate V2 ACE Pro navigation items")
        unmanaged = text.replace(V2_NAVIGATION, "", 1)
        if _has_navigation_conflict(unmanaged):
            raise ValueError("Fluidd has an additional unmanaged ACE Pro navigation conflict")
        return text.replace(V2_NAVIGATION, NAVIGATION_BLOCK_FROM_V2, 1)

    if _has_navigation_conflict(text):
        raise ValueError("Fluidd has an unmanaged ACE Pro navigation conflict")
    return _insert_once(text, NAVIGATION_BLOCK, NAVIGATION_ANCHOR, after=False)


def _toolchange_marker_states(text: str) -> tuple[bool, ...]:
    return (
        _marker_state(
            text, TOOLCHANGE_IMPORT_BEGIN, TOOLCHANGE_IMPORT_END, "tool grid import"
        ),
        _marker_state(
            text,
            TOOLCHANGE_DEVICE_COUNT_BEGIN,
            TOOLCHANGE_DEVICE_COUNT_END,
            "tool grid device count",
        ),
        _marker_state(
            text, TOOLCHANGE_GROUP_BEGIN, TOOLCHANGE_GROUP_END, "tool grid grouping"
        ),
        _marker_state(
            text, TOOLCHANGE_STYLE_BEGIN, TOOLCHANGE_STYLE_END, "tool grid style"
        ),
    )


def _validate_managed_toolchange(text: str) -> None:
    blocks = (
        TOOLCHANGE_IMPORT,
        TOOLCHANGE_DEVICE_COUNT,
        TOOLCHANGE_GROUP,
        TOOLCHANGE_STYLE,
        TOOLCHANGE_CLASS,
    )
    if any(text.count(block) != 1 for block in blocks):
        raise ValueError("Fluidd managed ACE tool grid was changed outside the installer")


def patch_toolchange(text: str) -> str:
    states = _toolchange_marker_states(text)
    if any(states):
        if not all(states):
            raise ValueError("Fluidd managed ACE tool grid is incomplete")
        _validate_managed_toolchange(text)
        return text
    if TOOLCHANGE_CLASS in text:
        raise ValueError("Fluidd managed ACE tool grid class has no matching markers")

    text = _insert_once(
        text, TOOLCHANGE_IMPORT, TOOLCHANGE_IMPORT_ANCHOR, after=True
    )
    text = _insert_once(
        text, TOOLCHANGE_CLASS, TOOLCHANGE_CLASS_ANCHOR, after=True
    )
    text = _insert_once(
        text, TOOLCHANGE_DEVICE_COUNT, TOOLCHANGE_GETTER_ANCHOR, after=False
    )
    text = _insert_once(
        text, TOOLCHANGE_GROUP, TOOLCHANGE_GROUP_ANCHOR, after=True
    )
    return _insert_once(
        text, TOOLCHANGE_STYLE, TOOLCHANGE_STYLE_ANCHOR, after=False
    )


def remove_dashboard_managed(text: str) -> str:
    return _remove_managed_lines(
        text,
        (DASHBOARD_IMPORT, DASHBOARD_COMPONENT, DASHBOARD_COMPONENT_LEGACY),
    )


def remove_layout_managed(text: str) -> str:
    return _remove_managed_lines(text, (LAYOUT_CARD,))


def remove_router_managed(text: str) -> str:
    if not _marker_state(text, ROUTE_BEGIN, ROUTE_END, "route"):
        return text
    if text.count(ROUTE_BLOCK_FROM_V2) == 1:
        return text.replace(ROUTE_BLOCK_FROM_V2, V2_ROUTE, 1)
    if text.count(ROUTE_BLOCK) != 1:
        raise ValueError("Fluidd managed /acepro route was changed outside the installer")
    return _remove_marked_block(text, ROUTE_BEGIN, ROUTE_END, "route")


def remove_navigation_managed(text: str) -> str:
    if not _marker_state(text, NAVIGATION_BEGIN, NAVIGATION_END, "navigation"):
        return text
    if text.count(NAVIGATION_BLOCK_FROM_V2) == 1:
        return text.replace(NAVIGATION_BLOCK_FROM_V2, V2_NAVIGATION, 1)
    if text.count(NAVIGATION_BLOCK) != 1:
        raise ValueError("Fluidd managed ACE Pro navigation was changed outside the installer")
    return _remove_marked_block(
        text, NAVIGATION_BEGIN, NAVIGATION_END, "navigation"
    )


def remove_toolchange_managed(text: str) -> str:
    states = _toolchange_marker_states(text)
    if not any(states):
        if TOOLCHANGE_CLASS in text:
            raise ValueError("Fluidd managed ACE tool grid class has no matching markers")
        return text
    if not all(states):
        raise ValueError("Fluidd managed ACE tool grid is incomplete")
    _validate_managed_toolchange(text)
    text = _remove_managed_lines(text, (TOOLCHANGE_CLASS,))
    for begin, end, label in (
        (TOOLCHANGE_IMPORT_BEGIN, TOOLCHANGE_IMPORT_END, "tool grid import"),
        (
            TOOLCHANGE_DEVICE_COUNT_BEGIN,
            TOOLCHANGE_DEVICE_COUNT_END,
            "tool grid device count",
        ),
        (TOOLCHANGE_GROUP_BEGIN, TOOLCHANGE_GROUP_END, "tool grid grouping"),
        (TOOLCHANGE_STYLE_BEGIN, TOOLCHANGE_STYLE_END, "tool grid style"),
    ):
        text = _remove_marked_block(text, begin, end, label)
    return text


PATCHERS = {
    "dashboard": patch_dashboard,
    "layout": patch_layout,
    "router": patch_router,
    "navigation": patch_navigation,
    "toolchange": patch_toolchange,
}
REMOVERS = {
    "dashboard": remove_dashboard_managed,
    "layout": remove_layout_managed,
    "router": remove_router_managed,
    "navigation": remove_navigation_managed,
    "toolchange": remove_toolchange_managed,
}


def _write_atomic(path: Path, text: str) -> None:
    temporary = path.with_name(".%s.ace-v3-%d" % (path.name, os.getpid()))
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _validate_manifest_roles(files: dict[str, str]) -> None:
    expected = set(PATCHERS)
    actual = set(files)
    if actual != expected:
        raise ValueError(
            "Fluidd overlay manifest roles must be exactly: %s"
            % ", ".join(sorted(expected))
        )


def update_tree(root: Path, action: str) -> dict[str, Any]:
    if action not in {"check", "apply", "remove"}:
        raise ValueError("unsupported Fluidd overlay action: %s" % action)
    root = root.resolve()
    manifest = load_manifest()
    files: dict[str, str] = manifest["patched_source_files"]
    _validate_manifest_roles(files)

    if action in {"check", "apply"}:
        inspection = inspect_tree(root)
        if not inspection["compatible"]:
            raise ValueError("; ".join(inspection["reasons"]))
        selected = files
        transforms = PATCHERS
    else:
        selected = {
            role: relative
            for role, relative in files.items()
            if (root / relative).is_file()
        }
        transforms = REMOVERS

    current = {
        role: (root / relative).read_text(encoding="utf-8")
        for role, relative in selected.items()
    }
    updated = {role: transforms[role](source) for role, source in current.items()}
    changed = [files[role] for role in selected if updated[role] != current[role]]

    if action in {"apply", "remove"}:
        for role, relative in selected.items():
            if updated[role] != current[role]:
                _write_atomic(root / relative, updated[role])

    missing = [
        relative for role, relative in files.items() if role not in selected
    ] if action == "remove" else []
    return {
        "action": action,
        "changed_files": changed,
        "processed_files": [files[role] for role in selected],
        "missing_files": missing,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "action",
        choices=("inspect", "files", "build-guide", "check", "apply", "remove"),
    )
    parser.add_argument("root", nargs="?", type=Path)
    args = parser.parse_args(argv)

    if args.action == "files":
        if args.root is not None:
            parser.error("files does not accept a Fluidd source root")
        for path in manifest_file_paths():
            print(path)
        return 0
    if args.root is None:
        parser.error("%s requires a Fluidd source root" % args.action)

    if args.action == "inspect":
        report = inspect_tree(args.root)
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
        return 0 if report["compatible"] else 1
    if args.action == "build-guide":
        try:
            report = build_guidance(args.root)
        except ValueError as exc:
            parser.error(str(exc))
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
        return 0

    try:
        report = update_tree(args.root, args.action)
    except ValueError as exc:
        parser.error(str(exc))
    if args.action == "remove":
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
