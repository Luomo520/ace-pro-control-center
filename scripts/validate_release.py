#!/usr/bin/env python3
"""Static release checks that do not import Klipper or Moonraker."""

from __future__ import annotations

import argparse
import ast
import configparser
import re
import sys
from pathlib import Path, PurePosixPath

import hardware_config


KLIPPER_WRAPPER_FUNCTIONS = {
    "ace_hardware.py": "load_config",
    "ace_device.py": "load_config_prefix",
    "ace_machine.py": "load_config",
    "ace_encoder.py": "load_config_prefix",
}
WRAPPER_LIST_PATTERN = re.compile(
    r"(?m)^declare[ \t]+-ar[ \t]+KLIPPER_WRAPPERS=\(([^)]*)\)"
)
SHARED_INLINE_COMMENT_INDEX = 96
RETIRED_HARDWARE_CONFIG_NAME_RE = re.compile(
    r"^ace[-_]hardware(?:[._-].+)?\.cfg$",
    re.IGNORECASE,
)
CONFIG_OPTION_LINE_PATTERN = re.compile(
    r"^(?:#[ \t]+)?[A-Za-z][A-Za-z0-9_]*[ \t]*[:=]"
)
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


def _inline_comment_index(line: str) -> int | None:
    option = CONFIG_OPTION_LINE_PATTERN.match(line)
    if option is None:
        return None
    index = line.find("#", option.end())
    if index < 0 or index == 0 or not line[index - 1].isspace():
        return None
    return index


def _section_text(text: str, name: str) -> str | None:
    match = re.search(
        r"(?ms)^\[%s\][^\r\n]*(?:\r?\n)(.*?)(?=^\[[^\]\r\n]+\]|\Z)"
        % re.escape(name),
        text,
    )
    return None if match is None else match.group(1)


def _commented_macro_is_fully_commented(text: str, name: str) -> bool:
    lines = text.splitlines()
    header = re.compile(
        r"^[ \t]*#[ \t]*\[gcode_macro[ \t]+%s\][ \t]*$" % re.escape(name),
        re.IGNORECASE,
    )
    any_macro_header = re.compile(
        r"^[ \t]*(?:#[ \t]*)?\[gcode_macro[ \t]+[^\]]+\][ \t]*$",
        re.IGNORECASE,
    )
    start = next((index for index, line in enumerate(lines) if header.match(line)), None)
    if start is None:
        return False
    for line in lines[start + 1 :]:
        if any_macro_header.match(line):
            break
        if line.strip() and not line.lstrip().startswith("#"):
            return False
    return True


def _macro_description(text: str, name: str) -> str | None:
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
    start = next((index for index, line in enumerate(lines) if header.match(line)), None)
    if start is None:
        return None
    for line in lines[start + 1 :]:
        if any_macro_header.match(line):
            break
        normalized = line.lstrip()
        if normalized.startswith("#"):
            normalized = normalized[1:].lstrip()
        if normalized.lower().startswith("description:"):
            return normalized.split(":", 1)[1].strip()
    return None


def _validate_machine_hook_labels(text: str) -> list[str]:
    section = _section_text(text, "ace_machine")
    if section is None:
        return []
    errors: list[str] = []
    for key, (macro, label, status, active) in MACHINE_HOOK_CONTRACT.items():
        match = re.search(
            r"(?m)^(?P<comment>#[ \t]+)?%s[ \t]*:[ \t]*%s[ \t]+#(?P<help>[^\r\n]*)$"
            % (re.escape(key), re.escape(macro)),
            section,
        )
        if match is None:
            errors.append(f"ace_machine {key} must bind {macro} with inline help")
            continue
        is_active = match.group("comment") is None
        if is_active != active:
            state = "active" if active else "commented"
            errors.append(f"ace_machine {key} must be {state} by default")
        expected_label = f"【{label}｜{status}】"
        if expected_label not in match.group("help"):
            errors.append(f"ace_machine {key} must contain label {expected_label}")
        help_text = match.group("help")
        if status == "必用" and f"!!! {expected_label}" not in help_text:
            errors.append(f"ace_machine {key} must mark required hook with !!!")
        if status != "必用" and "!!!" in help_text:
            errors.append(f"ace_machine {key} must not mark {status} hook with !!!")

        description = _macro_description(text, macro)
        if description is None:
            errors.append(f"machine macro {macro} is missing description")
        elif status == "必用" and "!!!" not in description:
            errors.append(f"machine macro {macro} description must contain !!!")
        elif status != "必用" and "!!!" in description:
            errors.append(f"machine macro {macro} description must not contain !!!")
    return errors


def _validate_shared_inline_comments(text: str) -> list[str]:
    errors: list[str] = []
    material_lines = []
    for line_number, line in enumerate(text.splitlines(), 1):
        if re.match(r"^material_types[ \t]*[:=]", line):
            material_lines.append((line_number, line))
        index = _inline_comment_index(line)
        if index is not None and index != SHARED_INLINE_COMMENT_INDEX:
            errors.append(
                "shared config inline comment on line %d must start at column 97"
                % line_number
            )
    for line_number, line in material_lines:
        if _inline_comment_index(line) is not None:
            errors.append(
                "shared config material_types on line %d must not use inline help"
                % line_number
            )
    return errors


def _validate_pin_only_sensor_template(text: str) -> list[str]:
    errors: list[str] = []
    for line_number, line in enumerate(text.splitlines(), 1):
        match = re.match(
            r"^[#;]?[ \t]*(?P<key>[A-Za-z][A-Za-z0-9_]*_sensor_name)"
            r"[ \t]*[:=]",
            line,
        )
        if match is not None:
            errors.append(
                "shared config line %d must omit legacy sensor name option %s"
                % (line_number, match.group("key"))
            )
    return errors


def parse_python(path: Path) -> ast.Module:
    try:
        return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, SyntaxError, UnicodeError) as exc:
        raise ValueError(f"invalid Python source {path}: {exc}") from exc


def has_top_level_function(tree: ast.Module, name: str) -> bool:
    return any(
        isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == name
        for node in tree.body
    )


def is_retired_hardware_config_path(path: str | Path) -> bool:
    """Return whether a release member is a retired standalone ACE config."""
    normalized = str(path).replace("\\", "/")
    parts = tuple(
        part
        for part in PurePosixPath(normalized).parts
        if part not in ("", ".", "/")
    )
    if not parts or not any(part.casefold() == "config" for part in parts[:-1]):
        return False
    return RETIRED_HARDWARE_CONFIG_NAME_RE.fullmatch(parts[-1]) is not None


def validate_retired_hardware_configs(repo: Path) -> list[str]:
    config = repo / "config"
    if not config.is_dir():
        return []
    errors: list[str] = []
    for path in sorted(config.rglob("*")):
        if not (path.is_file() or path.is_symlink()):
            continue
        relative = path.relative_to(repo).as_posix()
        if is_retired_hardware_config_path(relative):
            errors.append(
                f"release tree contains retired hardware config: {relative}"
            )
    return errors


def validate_klipper_wrappers(repo: Path) -> list[str]:
    errors: list[str] = []
    for filename, function in KLIPPER_WRAPPER_FUNCTIONS.items():
        wrapper = repo / "klipper_extras" / filename
        if not wrapper.is_file():
            errors.append(f"missing stock Klipper section wrapper: {wrapper}")
            continue
        try:
            if not has_top_level_function(parse_python(wrapper), function):
                errors.append(f"{filename} must expose top-level {function}(config)")
        except ValueError as exc:
            errors.append(str(exc))
    return errors


def validate_installer_wrapper_contract(repo: Path) -> list[str]:
    errors: list[str] = []
    expected = [Path(filename).stem for filename in KLIPPER_WRAPPER_FUNCTIONS]
    for relative in (Path("installer/install.sh"), Path("scripts/test_installer.sh")):
        path = repo / relative
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            errors.append(f"installer wrapper contract cannot be read from {path}: {exc}")
            continue
        match = WRAPPER_LIST_PATTERN.search(text)
        if match is None:
            errors.append(f"missing KLIPPER_WRAPPERS declaration: {path}")
            continue
        configured = re.findall(r"[A-Za-z_][A-Za-z0-9_]*", match.group(1))
        if configured != expected:
            errors.append(
                f"{relative.as_posix()} KLIPPER_WRAPPERS must be "
                + " ".join(expected)
            )
    return errors


def validate_shared_config(path: Path) -> list[str]:
    parser = configparser.ConfigParser(
        delimiters=(":", "="),
        interpolation=None,
        strict=True,
        inline_comment_prefixes=("#", ";"),
    )
    try:
        parser.read(path, encoding="utf-8")
    except configparser.Error as exc:
        return [f"invalid shared config {path}: {exc}"]
    required = {"ace", "ace_machine"}
    missing = sorted(required.difference(parser.sections()))
    errors = [f"missing section [{section}]" for section in missing]
    required_macros = {
        "_ace_load_filament_to_toolhead",
        "_ace_unload_filament_from_toolhead",
        "_ace_pause_on_toolchange_error",
    }
    present_macros = {
        section[len("gcode_macro ") :]
        for section in parser.sections()
        if section.lower().startswith("gcode_macro ")
    }
    errors.extend(
        f"shared config is missing machine macro [{name}]"
        for name in sorted(required_macros - present_macros)
    )
    legacy_macros = {
        "_ACE_MACHINE_PRE_TOOLCHANGE",
        "_ACE_MACHINE_CUT",
        "_ACE_MACHINE_LOAD_TO_TOOLHEAD",
        "_ACE_MACHINE_UNLOAD_FROM_TOOLHEAD",
        "_ACE_MACHINE_POST_TOOLCHANGE",
        "_ACE_MACHINE_PAUSE_ON_ERROR",
    }
    errors.extend(
        f"shared config still registers legacy machine macro [{name}]"
        for name in sorted(legacy_macros & present_macros)
    )
    duplicate_commands = [
        section
        for section in parser.sections()
        if section == "gcode_macro TR"
        or section.startswith("gcode_macro T")
        and section[len("gcode_macro T") :].isdigit()
    ]
    errors.extend(
        f"duplicate driver-owned command section [{section}]"
        for section in duplicate_commands
    )
    text = path.read_text(encoding="utf-8")
    errors.extend(
        f"shared config hardware topology: {error}"
        for error in hardware_config.validate_embedded_text(text)
    )
    if hardware_config.LEGACY_HARDWARE_INCLUDE_RE.search(text):
        errors.append("shared config still includes retired ace_hardware.cfg")
    if parser.has_section("ace") and parser["ace"].get("toolchange_mode") != "manual":
        errors.append("new-install shared config must default toolchange_mode to manual")
    if parser.has_section("ace") and parser["ace"].get("require_cut_hook") != "True":
        errors.append("new-install shared config must default require_cut_hook to True")
    expected_hooks = {
        "pre_toolchange_macro": "_ace_prepare_toolchange",
        "cut_macro": "_ace_cut_filament",
        "load_to_toolhead_macro": "_ace_load_filament_to_toolhead",
        "unload_from_toolhead_macro": "_ace_unload_filament_from_toolhead",
        "wipe_nozzle_macro": "_ace_wipe_nozzle",
        "post_toolchange_macro": "_ace_restore_after_toolchange",
        "pause_on_error_macro": "_ace_pause_on_toolchange_error",
    }
    if parser.has_section("ace_machine"):
        machine = parser["ace_machine"]
        for key, value in expected_hooks.items():
            if machine.get(key) != value:
                errors.append(f"ace_machine {key} must be {value}")
    machine_template_macros = {
        "_ace_prepare_toolchange",
        "_ace_cut_filament",
        "_ace_wipe_nozzle",
        "_ace_restore_after_toolchange",
    }
    for name in sorted(machine_template_macros & present_macros):
        errors.append(
            f"shared config machine movement macro [{name}] must be commented by default"
        )
    errors.extend(_validate_machine_hook_labels(text))
    errors.extend(_validate_shared_inline_comments(text))
    errors.extend(_validate_pin_only_sensor_template(text))
    for name in (
        "_ace_prepare_toolchange",
        "_ace_cut_filament",
        "_ace_wipe_nozzle",
        "_ace_restore_after_toolchange",
    ):
        if not re.search(
            r"(?im)^#[ \t]*\[gcode_macro[ \t]+%s\][ \t]*$" % re.escape(name),
            text,
        ):
            errors.append(f"shared config is missing commented macro template [{name}]")
    for name in sorted(machine_template_macros):
        if not _commented_macro_is_fully_commented(text, name):
            errors.append(
                f"shared config machine movement macro template [{name}] "
                "must be fully commented"
            )
    if not re.search(r"(?im)^#.*ACE Pro.*Klipper.*$", text[:1200]):
        errors.append(
            "shared config does not contain the Ace Pro Control Center ownership header"
        )
    if re.search(r"(?im)^\s*\[include\s+ace_machine\.cfg\]\s*$", text):
        errors.append("shared config still includes retired ace_machine.cfg")
    topology_fragments = (
        "[ACE0 槽0..3] --> [总五通传感器]",
        "[ACE0 槽0..3] --> [ace0 一级五通传感器]",
        "[总五通] --> [编码器（可选）]",
        "[上方传感器] --> [挤出机] --> [下方传感器] --> [喷嘴]",
    )
    normalized_path_text = text.replace(">>> ", "").replace(" <<<", "")
    if any(fragment not in normalized_path_text for fragment in topology_fragments):
        errors.append("shared config is missing the current external filament path")
    if "一级五通传感器（仅 2 至 4 台 ACE）" not in text:
        errors.append("shared config must mark first-stage hubs as multi-device only")
    if "缓冲器" in text:
        errors.append("shared config still exposes a standalone buffer concept")
    return errors


def validate_machine_config(path: Path) -> list[str]:
    """Validate the retired machine-macro template used only for migration."""
    if not path.is_file():
        return [f"missing machine macro config: {path}"]
    text = path.read_text(encoding="utf-8")
    required = {
        "_ACE_MACHINE_PRE_TOOLCHANGE",
        "_ACE_MACHINE_CUT",
        "_ACE_MACHINE_LOAD_TO_TOOLHEAD",
        "_ACE_MACHINE_UNLOAD_FROM_TOOLHEAD",
        "_ACE_MACHINE_POST_TOOLCHANGE",
        "_ACE_MACHINE_PAUSE_ON_ERROR",
    }
    present = set(re.findall(r"^\[gcode_macro\s+([^\]]+)\]", text, re.MULTILINE))
    errors = [f"missing machine macro [{name}]" for name in sorted(required - present)]
    if "旧版机器动作宏迁移模板" not in text:
        errors.append("machine macro template is not marked as legacy migration input")
    if "不再由新安装创建" not in text:
        errors.append("machine macro template does not state that new installs omit it")
    if re.search(r"^\[gcode_macro\s+(?:TR|T\d+)\]", text, re.MULTILINE | re.IGNORECASE):
        errors.append("machine config duplicates a driver-owned T command")
    if "ACE_CHANGE_TOOL" in text:
        errors.append("machine config recursively calls ACE_CHANGE_TOOL")
    if "ACE_PATH_LOAD_TO_TOOLHEAD" not in text or "ACE_PATH_UNLOAD_STEP" not in text:
        errors.append("machine config does not delegate sensor loops to the V3 path controller")
    return errors


def validate_frontend_cache(repo: Path) -> list[str]:
    errors: list[str] = []
    dashboard = repo / "frontend" / "dashboard"
    index = dashboard / "index.html"
    app = dashboard / "app.js"
    if not index.is_file() or not app.is_file():
        return errors
    html = index.read_text(encoding="utf-8")
    script = app.read_text(encoding="utf-8")
    versions = {
        "styles.css": re.search(r"styles\.css\?v=([^\"']+)", html),
        "app.js": re.search(r"app\.js\?v=([^\"']+)", html),
        "ace-core.js": re.search(r"ace-core\.js\?v=([^\"']+)", script),
    }
    for asset, match in versions.items():
        if match is None:
            errors.append(f"standalone dashboard asset lacks cache version: {asset}")
    values = {match.group(1) for match in versions.values() if match is not None}
    if len(values) > 1:
        errors.append("standalone dashboard cache versions do not match")
    return errors


def validate_frontend_terminology(repo: Path) -> list[str]:
    errors: list[str] = []
    user_facing_sources = (
        Path("frontend/dashboard/app.js"),
        Path("frontend/simulator/app.js"),
        Path("frontend/shared/ace-core.js"),
        Path("frontend/fluidd-overlay/src/components/widgets/ace-v3/ace-core.js"),
        Path("frontend/fluidd-overlay/src/components/widgets/ace-v3/AceV3Card.vue"),
    )
    for relative in user_facing_sources:
        path = repo / relative
        if not path.is_file():
            continue
        if "缓冲器" in path.read_text(encoding="utf-8"):
            errors.append(
                f"user-facing frontend still exposes a standalone buffer: {relative}"
            )
    return errors


def validate_repo(repo: Path, require_frontend: bool) -> list[str]:
    errors: list[str] = []
    errors.extend(validate_retired_hardware_configs(repo))
    package = repo / "ace_driver"
    entry = package / "__init__.py"
    if not package.is_dir():
        errors.append(f"missing Klipper package: {package}")
    elif not entry.is_file():
        errors.append(f"missing Klipper package entry: {entry}")
    else:
        try:
            tree = parse_python(entry)
            if not has_top_level_function(tree, "load_config"):
                errors.append(
                    "ace_driver/__init__.py must expose top-level load_config(config)"
                )
        except ValueError as exc:
            errors.append(str(exc))
        for path in sorted(package.rglob("*.py")):
            try:
                parse_python(path)
            except ValueError as exc:
                errors.append(str(exc))

    moonraker = repo / "moonraker" / "ace_status.py"
    if not moonraker.is_file():
        errors.append(f"missing Moonraker component: {moonraker}")
    else:
        try:
            tree = parse_python(moonraker)
            if not has_top_level_function(tree, "load_component"):
                errors.append(
                    "moonraker/ace_status.py must expose top-level load_component(config)"
                )
        except ValueError as exc:
            errors.append(str(exc))

    errors.extend(validate_klipper_wrappers(repo))
    errors.extend(validate_installer_wrapper_contract(repo))

    errors.extend(validate_shared_config(repo / "config" / "ace.cfg"))
    errors.extend(validate_machine_config(repo / "config" / "ace_machine.cfg"))

    if require_frontend:
        errors.extend(validate_frontend_cache(repo))
        errors.extend(validate_frontend_terminology(repo))
        dashboard = repo / "frontend" / "dashboard"
        if not dashboard.is_dir() or not (dashboard / "index.html").is_file():
            errors.append(f"missing standalone dashboard entry: {dashboard / 'index.html'}")
        shared = repo / "frontend" / "shared"
        if not shared.is_dir() or not (shared / "ace-core.js").is_file():
            errors.append(f"missing shared frontend core: {shared / 'ace-core.js'}")
        overlay = repo / "frontend" / "fluidd-overlay"
        if not overlay.is_dir() or not any(overlay.rglob("*")):
            errors.append(f"missing Fluidd source overlay: {overlay}")
        else:
            card = overlay / "src/components/widgets/ace-v3/AceV3Card.vue"
            slot_card = overlay / "src/components/widgets/ace-v3/AceV3SlotCard.vue"
            page = overlay / "src/views/AcePro.vue"
            for required in (card, slot_card, page):
                if not required.is_file():
                    errors.append(f"missing required Fluidd overlay file: {required}")
            if card.is_file():
                card_source = card.read_text(encoding="utf-8")
                if "import AceV3SlotCard from './AceV3SlotCard.vue'" not in card_source:
                    errors.append("AceV3Card.vue must import AceV3SlotCard.vue")
                if "<ace-v3-slot-card" not in card_source:
                    errors.append("AceV3Card.vue must render AceV3SlotCard")
            overlay_core = overlay / "src/components/widgets/ace-v3/ace-core.js"
            shared_core = shared / "ace-core.js"
            if overlay_core.is_file() and shared_core.is_file():
                if overlay_core.read_bytes() != shared_core.read_bytes():
                    errors.append("Fluidd overlay ace-core.js differs from the shared frontend core")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--require-frontend", action="store_true")
    args = parser.parse_args()
    errors = validate_repo(args.repo.resolve(), args.require_frontend)
    if errors:
        for error in errors:
            print(f"release validation error: {error}", file=sys.stderr)
        return 2
    print(f"valid release tree: {args.repo.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
