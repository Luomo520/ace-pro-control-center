#!/usr/bin/env python3
"""Upgrade managed config contracts without replacing user calibration."""

from __future__ import annotations

import argparse
import os
import re
from pathlib import Path
from typing import Dict, Iterable, Optional, Tuple


SECTION_RE = re.compile(r"(?m)^[ \t]*\[([^\]\r\n]+)\][ \t]*(?:[#;].*)?$")
OPTION_RE = re.compile(
    r"(?m)^(?P<indent>[ \t]*)(?P<key>[A-Za-z][A-Za-z0-9_]*)"
    r"(?P<separator>[ \t]*[:=][ \t]*)(?P<value>[^\r\n]*)$"
)
LEGACY_MACHINE_INCLUDE_RE = re.compile(
    r"(?im)^[ \t]*\[include[ \t]+ace_machine\.cfg\][ \t]*(?:[#;].*)?(?:\r?\n|$)"
)
LEGACY_HARDWARE_INCLUDE_RE = re.compile(
    r"(?im)^[ \t]*\[include[ \t]+ace_hardware\.cfg\][ \t]*(?:[#;].*)?(?:\r?\n|$)"
)
EMBEDDED_HARDWARE_BEGIN = "# >>> ACE DRIVER V3 HARDWARE TOPOLOGY BEGIN >>>"
EMBEDDED_HARDWARE_END = "# <<< ACE DRIVER V3 HARDWARE TOPOLOGY END <<<"
SHARED_CONFIG_END = "# <<< ACE DRIVER V3 MANAGED TEMPLATE END <<<"
LEGACY_USER_TAIL_ANCHORS = (
    "# 手动模式或自动换料未就绪时，驱动应逐次提示并忽略工具指令，不得暂停或中断打印。",
    "# V3 固定注册 T0..T15 和 TR，本文件不得定义同名工具宏；自动模式真正换料时才校验目标是否已配置。",
)
REQUIRED_HOOKS = {
    "pre_toolchange_macro",
    "cut_macro",
    "load_to_toolhead_macro",
    "unload_from_toolhead_macro",
    "wipe_nozzle_macro",
    "post_toolchange_macro",
    "pause_on_error_macro",
}
MACHINE_HOOKS = (
    "pre_toolchange_macro",
    "cut_macro",
    "load_to_toolhead_macro",
    "unload_from_toolhead_macro",
    "wipe_nozzle_macro",
    "post_toolchange_macro",
    "pause_on_error_macro",
)
MACHINE_OPTION_RE = re.compile(
    r"(?im)^(?P<indent>[ \t]*)(?P<comment>[#;][ \t]*)?"
    r"(?P<key>" + "|".join(MACHINE_HOOKS) + r")"
    r"(?P<separator>[ \t]*[:=][ \t]*)(?P<value>[^\r\n]*)$"
)
LEGACY_MACRO_NAMES = {
    "_ace_machine_pre_toolchange": "_ace_prepare_toolchange",
    "_ace_machine_cut": "_ace_cut_filament",
    "_ace_machine_load_to_toolhead": "_ace_load_filament_to_toolhead",
    "_ace_machine_unload_from_toolhead": "_ace_unload_filament_from_toolhead",
    "_ace_machine_post_toolchange": "_ace_restore_after_toolchange",
    "_ace_machine_pause_on_error": "_ace_pause_on_toolchange_error",
    "_ace_pre_toolchange": "_ace_prepare_toolchange",
    "cut_tip": "_ace_cut_filament",
    "_ace_post_toolchange": "_ace_restore_after_toolchange",
    "_ace_on_empty_error": "_ace_pause_on_toolchange_error",
}
TARGET_MACRO_DESCRIPTIONS = {
    "_ace_prepare_toolchange": "!!! 【换料前处理宏｜必用】保存位置、抬升、停车并检查温度",
    "_ace_cut_filament": "!!! 【切刀宏｜必用】移动到切刀位置并切断耗材",
    "_ace_load_filament_to_toolhead": "!!! 【送料宏｜必用】将耗材送入打印头路径",
    "_ace_unload_filament_from_toolhead": "!!! 【回料宏｜必用】从打印头路径受控回抽耗材",
    "_ace_wipe_nozzle": "!!! 【擦嘴宏｜必用】调用本机宏清理喷嘴",
    "_ace_restore_after_toolchange": "!!! 【换料后处理宏｜必用】恢复高度、运动状态和打印位置",
    "_ace_pause_on_toolchange_error": "!!! 【故障暂停宏｜必用】失败时提示并暂停活动打印",
}
TARGET_MACRO_SECTIONS = {
    "gcode_macro " + name for name in TARGET_MACRO_DESCRIPTIONS
}
REQUIRED_MACRO_SECTIONS = {
    "gcode_macro _ace_load_filament_to_toolhead",
    "gcode_macro _ace_unload_filament_from_toolhead",
    "gcode_macro _ace_pause_on_toolchange_error",
}
LEGACY_TOKEN_RE = re.compile(
    r"(?<![A-Za-z0-9_])(" + "|".join(
        sorted((re.escape(name) for name in LEGACY_MACRO_NAMES), key=len, reverse=True)
    ) + r")(?![A-Za-z0-9_])",
    re.IGNORECASE,
)
COMMENTED_MACRO_HEADER_RE = re.compile(
    r"^[ \t]*[#;][ \t]*\[gcode_macro[ \t]+([^\]]+)\][ \t]*$",
    re.IGNORECASE,
)
MACRO_TRAILER_RE = re.compile(
    r"(?m)^# (?:(?:[一二三四五六七八九十]+、)?"
    r"(?:危险宏样板|本机物理动作宏样板|工具命令归属)"
    r"|安装器保留的已注释用户宏)"
)


def _normalized(value: str) -> str:
    return " ".join(value.strip().lower().split())


def _sections(text: str) -> Dict[str, Tuple[int, int]]:
    matches = list(SECTION_RE.finditer(text))
    result: Dict[str, Tuple[int, int]] = {}
    for index, match in enumerate(matches):
        name = _normalized(match.group(1))
        if name in result:
            raise ValueError("duplicate config section [%s]" % match.group(1).strip())
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        result[name] = (match.start(), end)
    return result


def _section_span(text: str, name: str) -> Optional[Tuple[int, int]]:
    span = _sections(text).get(_normalized(name))
    if span is None:
        return None
    if _normalized(name).startswith("gcode_macro "):
        trailer = MACRO_TRAILER_RE.search(text, span[0], span[1])
        if trailer is not None:
            span = (span[0], trailer.start())
    return span


def _section_text(text: str, name: str) -> Optional[str]:
    span = _section_span(text, name)
    return None if span is None else text[span[0] : span[1]]


def _options(section: str) -> Dict[str, re.Match[str]]:
    result: Dict[str, re.Match[str]] = {}
    for match in OPTION_RE.finditer(section):
        key = match.group("key").lower()
        if key in result:
            raise ValueError("duplicate option '%s'" % key)
        result[key] = match
    return result


def _split_inline_comment(raw: str) -> Tuple[str, str, str]:
    stripped = raw.strip()
    if stripped.startswith(("#", ";")):
        return "", "", stripped
    match = re.match(r"^(.*?)([ \t]+)([#;].*)$", raw)
    if match is None:
        return stripped, "", ""
    return match.group(1).strip(), match.group(2), match.group(3)


def _active_value(raw: str) -> str:
    return _split_inline_comment(raw)[0]


def _replace_legacy_macro_tokens(text: str) -> str:
    return LEGACY_TOKEN_RE.sub(
        lambda match: LEGACY_MACRO_NAMES[match.group(0).lower()], text
    )


def _remove_unsafe_force_move(text: str) -> str:
    lines = []
    for line in text.splitlines(keepends=True):
        command = line.lstrip(" \t#;")
        normalized = re.sub(r"\s+", "", command).lower()
        if (
            normalized.startswith("force_move")
            and "stepper=extruder" in normalized
            and re.search(r"distance=-50(?:\.0+)?(?:\D|$)", normalized)
        ):
            newline = "\r\n" if line.endswith("\r\n") else "\n" if line.endswith("\n") else ""
            indent = line[: len(line) - len(line.lstrip(" \t"))]
            comment = indent + "# 旧版固定 -50 mm 强制回抽已移除；回料由 V3 路径控制器执行。"
            if line.lstrip().startswith(("#", ";")):
                comment = "# " + comment
            lines.append(comment + newline)
            continue
        lines.append(line)
    return "".join(lines)


def _ensure_macro_description(section: str, macro_name: str) -> str:
    if re.search(r"(?im)^[ \t]*description[ \t]*[:=]", section):
        return section
    lines = section.splitlines(keepends=True)
    if not lines:
        return section
    newline = "\r\n" if lines[0].endswith("\r\n") else "\n"
    description = TARGET_MACRO_DESCRIPTIONS[macro_name]
    lines.insert(1, "description: %s%s" % (description, newline))
    return "".join(lines)


def _has_nonempty_gcode(section: str) -> bool:
    match = re.search(r"(?im)^[ \t]*gcode[ \t]*[:=][ \t]*(?:[#;].*)?$", section)
    if match is None:
        return False
    for line in section[match.end() :].splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith(("#", ";")):
            return True
    return False


def _remove_section(text: str, name: str) -> str:
    span = _section_span(text, name)
    if span is None:
        return text
    before = text[: span[0]].rstrip()
    after = text[span[1] :].lstrip("\r\n")
    if before and after:
        return before + "\n\n" + after
    if before:
        return before + "\n"
    return after


def _migrate_active_machine_macros(text: str) -> str:
    result = text
    for legacy_name, target_name in LEGACY_MACRO_NAMES.items():
        legacy_section = "gcode_macro " + legacy_name
        target_section = "gcode_macro " + target_name
        current = _section_text(result, legacy_section)
        if current is None:
            continue
        migrated = _replace_legacy_macro_tokens(current)
        if target_name == "_ace_cut_filament":
            migrated = _remove_unsafe_force_move(migrated)
        migrated = _ensure_macro_description(migrated, target_name)
        existing = _section_text(result, target_section)
        if existing is not None:
            existing = _ensure_macro_description(existing, target_name)
            if migrated.strip() != existing.strip():
                raise ValueError(
                    "legacy and current machine macros conflict [%s]" % target_name
                )
            result = _remove_section(result, legacy_section)
            continue
        result = _replace_section(result, legacy_section, migrated)

    result = _replace_legacy_macro_tokens(result)
    result = _remove_unsafe_force_move(result)
    for section_name in TARGET_MACRO_SECTIONS:
        current = _section_text(result, section_name)
        if current is None:
            continue
        macro_name = section_name[len("gcode_macro ") :]
        updated = _ensure_macro_description(current, macro_name)
        result = _replace_section(result, section_name, updated)
    return result


def _machine_options(section: str) -> Dict[str, re.Match[str]]:
    result: Dict[str, re.Match[str]] = {}
    for match in MACHINE_OPTION_RE.finditer(section):
        key = match.group("key").lower()
        if key in result:
            raise ValueError("duplicate machine hook option '%s'" % key)
        result[key] = match
    return result


def _extract_commented_machine_macros(text: str) -> Tuple[str, list[str]]:
    lines = text.splitlines(keepends=True)
    kept: list[str] = []
    blocks: list[str] = []
    index = 0
    known_names = set(LEGACY_MACRO_NAMES) | set(TARGET_MACRO_DESCRIPTIONS)
    while index < len(lines):
        match = COMMENTED_MACRO_HEADER_RE.match(lines[index].rstrip("\r\n"))
        if match is None or match.group(1).strip().lower() not in known_names:
            kept.append(lines[index])
            index += 1
            continue

        block = [lines[index]]
        index += 1
        while index < len(lines):
            line = lines[index]
            if COMMENTED_MACRO_HEADER_RE.match(line.rstrip("\r\n")):
                break
            if not line.strip():
                break
            if not line.lstrip().startswith(("#", ";")):
                break
            block.append(line)
            index += 1
        migrated = _remove_unsafe_force_move(
            _replace_legacy_macro_tokens("".join(block))
        ).strip()
        blocks.append(migrated + "\n")
    return "".join(kept), blocks


def _commented_macro_signature(block: str) -> Tuple[Optional[str], str]:
    """Identify stock commented templates without depending on help text."""
    macro_name: Optional[str] = None
    body = []
    for raw_line in block.splitlines():
        stripped = raw_line.strip()
        header = COMMENTED_MACRO_HEADER_RE.match(stripped)
        if header is not None:
            macro_name = header.group(1).strip().lower()
            body.append("[gcode_macro %s]" % macro_name)
            continue
        content = re.sub(r"^[#;][ \t]?", "", stripped)
        if re.match(r"(?i)^description[ \t]*[:=]", content):
            continue
        body.append(" ".join(content.split()))
    return macro_name, "\n".join(body)


def _append_commented_machine_macros(
    result: str, blocks: Iterable[str], template: str
) -> str:
    _, template_blocks = _extract_commented_machine_macros(template)
    existing = {block.strip() for block in template_blocks}
    stock_signatures = {
        name: signature
        for name, signature in (
            _commented_macro_signature(block) for block in template_blocks
        )
        if name is not None
    }
    additions = []
    for block in blocks:
        normalized = block.strip()
        if not normalized or normalized in existing:
            continue
        name, signature = _commented_macro_signature(normalized)
        if name is not None and stock_signatures.get(name) == signature:
            continue
        existing.add(normalized)
        additions.append(normalized)
    if not additions:
        return result
    suffix = "\n\n# 安装器保留的已注释用户宏；启用前仍须按本机重新检查。\n"
    suffix += "\n\n".join(additions) + "\n"
    return result.rstrip() + suffix


def _render_template_option(source: re.Match[str], value: str) -> str:
    _, _, comment = _split_inline_comment(source.group("value"))
    separator = source.group("separator")
    if value:
        separator = separator.rstrip(" \t") + " "

    rendered = "%s%s%s%s" % (
        source.group("indent"),
        source.group("key"),
        separator,
        value,
    )
    if not comment:
        return rendered
    if value:
        comment_column = source.group(0).find(comment)
        if comment_column > len(rendered):
            rendered += " " * (comment_column - len(rendered))
        else:
            rendered += "  "
    return rendered + comment


def _append_section(text: str, section: str) -> str:
    base = text.rstrip()
    return (base + "\n\n" if base else "") + section.strip() + "\n"


def _replace_section(text: str, name: str, replacement: str) -> str:
    span = _section_span(text, name)
    if span is None:
        return _append_section(text, replacement)
    before = text[: span[0]].rstrip()
    after = text[span[1] :].lstrip("\r\n")
    merged = (before + "\n\n" if before else "") + replacement.strip() + "\n"
    if after:
        merged += "\n" + after
    return merged


def _remove_legacy_machine_include(text: str) -> str:
    return LEGACY_MACHINE_INCLUDE_RE.sub("", text)


def _embedded_hardware_span(text: str) -> Optional[Tuple[int, int]]:
    """Locate one complete installer-managed hardware block."""

    lines = text.splitlines(keepends=True)
    offsets = []
    offset = 0
    for line in lines:
        offsets.append(offset)
        offset += len(line)

    begin_lines = [
        index for index, line in enumerate(lines)
        if line.strip() == EMBEDDED_HARDWARE_BEGIN
    ]
    end_lines = [
        index for index, line in enumerate(lines)
        if line.strip() == EMBEDDED_HARDWARE_END
    ]
    begin_mentions = text.count(EMBEDDED_HARDWARE_BEGIN)
    end_mentions = text.count(EMBEDDED_HARDWARE_END)
    if not begin_mentions and not end_mentions:
        return None
    if (
        begin_mentions != 1
        or end_mentions != 1
        or len(begin_lines) != 1
        or len(end_lines) != 1
    ):
        raise ValueError(
            "embedded hardware topology must contain exactly one intact BEGIN/END pair"
        )
    if begin_lines[0] >= end_lines[0]:
        raise ValueError("embedded hardware topology boundaries are out of order")
    end = offsets[end_lines[0]] + len(lines[end_lines[0]])
    return offsets[begin_lines[0]], end


def _remove_embedded_hardware(text: str) -> Tuple[str, str]:
    span = _embedded_hardware_span(text)
    if span is None:
        return text, ""
    block = text[span[0] : span[1]]
    before = text[: span[0]].rstrip()
    after = text[span[1] :].lstrip("\r\n")
    if before and after:
        return before + "\n\n" + after, block
    if before:
        return before + "\n", block
    return after, block


def _restore_embedded_hardware(text: str, block: str) -> str:
    if not block:
        return text
    span = _embedded_hardware_span(text)
    if span is None:
        base = text.rstrip()
        return block.rstrip() + ("\n\n" + base if base else "") + "\n"
    return text[: span[0]] + block + text[span[1] :]


def _remove_legacy_includes(text: str) -> str:
    return LEGACY_HARDWARE_INCLUDE_RE.sub(
        "", _remove_legacy_machine_include(text)
    )


def _split_user_tail(text: str) -> Tuple[str, str]:
    """Separate content appended after the managed template boundary."""

    lines = text.splitlines(keepends=True)
    marker_lines = [
        index for index, line in enumerate(lines)
        if line.strip() == SHARED_CONFIG_END
    ]
    if len(marker_lines) > 1 or text.count(SHARED_CONFIG_END) != len(marker_lines):
        raise ValueError("shared config contains a damaged or duplicate end boundary")
    if marker_lines:
        cut = sum(len(line) for line in lines[: marker_lines[0] + 1])
        return text[:cut], text[cut:]

    # Configs created before the explicit boundary used these stable final
    # ownership lines. Preserve anything the user appended after them.
    for anchor in LEGACY_USER_TAIL_ANCHORS:
        matches = [
            index for index, line in enumerate(lines)
            if line.strip() == anchor
        ]
        if not matches:
            continue
        cut = sum(len(line) for line in lines[: matches[-1] + 1])
        return text[:cut], text[cut:]
    return text, ""


def _append_user_tail(text: str, tail: str) -> str:
    if not tail:
        return text
    newline = "\r\n" if "\r\n" in text else "\n"
    return text.rstrip("\r\n") + newline + tail


def _merge_options(
    text: str,
    template: str,
    section_name: str,
    *,
    fill_blank: Iterable[str] = (),
) -> str:
    target_section = _section_text(text, section_name)
    template_section = _section_text(template, section_name)
    if template_section is None:
        raise ValueError("template is missing section [%s]" % section_name)
    if target_section is None:
        return _append_section(text, template_section)

    target_options = _options(target_section)
    template_options = _options(template_section)
    fill_blank = {key.lower() for key in fill_blank}
    changed_section = target_section

    replacements = []
    for key in fill_blank:
        current = target_options.get(key)
        source = template_options.get(key)
        if current is None or source is None or _active_value(current.group("value")):
            continue
        replacements.append(
            (
                current.start(),
                current.end(),
                _render_template_option(
                    current, _active_value(source.group("value"))
                ),
            )
        )
    for start, end, replacement in sorted(replacements, reverse=True):
        changed_section = changed_section[:start] + replacement + changed_section[end:]

    missing = [
        match.group(0).strip()
        for key, match in template_options.items()
        if key not in target_options
    ]
    if missing:
        changed_section = changed_section.rstrip() + "\n\n"
        changed_section += "# ACE Pro 管理中心安装器补充的新版配置项。\n"
        changed_section += "\n".join(missing) + "\n"

    if not replacements and not missing:
        return text

    return _replace_section(text, section_name, changed_section)


def _rebase_section(
    target: str,
    template: str,
    section_name: str,
    *,
    fill_blank: Iterable[str] = (),
) -> str:
    """Render a template section while retaining every configured value."""
    target_section = _section_text(target, section_name)
    template_section = _section_text(template, section_name)
    if template_section is None:
        raise ValueError("template is missing section [%s]" % section_name)
    if target_section is None:
        return template_section

    target_options = _options(target_section)
    template_options = _options(template_section)
    fill_blank = {key.lower() for key in fill_blank}
    replacements = []
    for key, source in template_options.items():
        current = target_options.get(key)
        if current is None:
            continue
        value = _active_value(current.group("value"))
        if not value and key in fill_blank:
            value = _active_value(source.group("value"))
        replacements.append(
            (
                source.start(),
                source.end(),
                _render_template_option(source, value),
            )
        )

    result = template_section
    for start, end, replacement in sorted(replacements, reverse=True):
        result = result[:start] + replacement + result[end:]

    unknown = [
        match.group(0).strip()
        for key, match in target_options.items()
        if key not in template_options
        and not (
            _normalized(section_name) == "ace" and key.endswith("_sensor_name")
        )
    ]
    if unknown:
        result = result.rstrip() + "\n\n"
        result += "# 以下为安装器保留的用户扩展配置；升级后请确认当前驱动仍支持这些项目。\n"
        result += "\n".join(unknown) + "\n"
    return result


def _rebase_machine_section(target: str, template: str) -> str:
    target_section = _section_text(target, "ace_machine")
    template_section = _section_text(template, "ace_machine")
    if template_section is None:
        raise ValueError("template is missing section [ace_machine]")
    if target_section is None:
        return template_section

    target_options = _machine_options(target_section)
    template_options = _machine_options(template_section)
    replacements = []
    for key, source in template_options.items():
        current = target_options.get(key)
        if current is None:
            if key not in REQUIRED_HOOKS:
                continue
            value = _active_value(source.group("value"))
            comment_prefix = ""
        else:
            value = _active_value(
                _replace_legacy_macro_tokens(current.group("value"))
            )
            comment_prefix = current.group("comment") or ""
        if key in REQUIRED_HOOKS:
            comment_prefix = ""
            if not value:
                value = _active_value(source.group("value"))

        rendered = _render_template_option(source, value)
        if comment_prefix:
            indent = source.group("indent")
            rendered = indent + comment_prefix + rendered[len(indent) :]
        replacements.append((source.start(), source.end(), rendered))

    result = template_section
    for start, end, replacement in sorted(replacements, reverse=True):
        result = result[:start] + replacement + result[end:]

    active_target_options = _options(target_section)
    unknown = [
        match.group(0).strip()
        for key, match in active_target_options.items()
        if key not in template_options
    ]
    if unknown:
        result = result.rstrip() + "\n\n"
        result += "# 以下为安装器保留的用户扩展钩子；请确认当前驱动仍支持。\n"
        result += "\n".join(unknown) + "\n"
    return result


def _append_unknown_sections(result: str, target: str, template: str) -> str:
    template_sections = _sections(template)
    for name in _sections(target):
        if name in template_sections:
            continue
        incoming = _section_text(target, name)
        if incoming is None:
            continue
        existing = _section_text(result, name)
        if existing is not None:
            if existing.strip() != incoming.strip():
                raise ValueError("configuration section conflicts [%s]" % name)
            continue
        result = _append_section(result, incoming)
    return result


def _append_legacy_machine_sections(result: str, legacy: str, template: str) -> str:
    """Move user sections from the retired machine file without duplicating them."""
    template_sections = _sections(template)
    for name in _sections(legacy):
        if name in template_sections:
            continue
        incoming = _section_text(legacy, name)
        if incoming is None:
            continue
        existing = _section_text(result, name)
        if existing is not None:
            if existing.strip() != incoming.strip():
                raise ValueError(
                    "legacy machine section conflicts with shared config [%s]" % name
                )
            continue
        result = _append_section(result, incoming)
    return result


def _merge_machine_macros(
    result: str,
    shared_target: str,
    template: str,
    legacy_machine: str,
) -> str:
    """Place machine macros in ace.cfg, preferring calibrated legacy values."""
    template_sections = _sections(template)
    for name in sorted(REQUIRED_MACRO_SECTIONS):
        template_macro = _section_text(template, name)
        if template_macro is None:
            raise ValueError("template is missing section [%s]" % name)
        replacement = (
            _section_text(legacy_machine, name)
            or _section_text(shared_target, name)
            or template_macro
        )
        if not _has_nonempty_gcode(replacement):
            replacement = template_macro
        macro_name = name[len("gcode_macro ") :]
        replacement = _ensure_macro_description(replacement, macro_name)
        result = _replace_section(result, name, replacement)
    return _append_legacy_machine_sections(result, legacy_machine, template)


def upgrade_shared(text: str, template: str, legacy_machine: str = "") -> str:
    if text == template and not legacy_machine.strip():
        return text

    # ace.cfg is user-facing. Rebase its owned sections onto the current
    # Chinese template so upgrades also receive the latest grouping and help
    # text, while active calibration values remain untouched.
    shared_managed, user_tail = _split_user_tail(text)
    shared_without_hardware, embedded_hardware = _remove_embedded_hardware(
        _remove_legacy_includes(shared_managed)
    )
    shared_source, shared_commented = _extract_commented_machine_macros(
        shared_without_hardware
    )
    legacy_source, legacy_commented = _extract_commented_machine_macros(
        _remove_legacy_includes(legacy_machine)
    )
    shared_target = _migrate_active_machine_macros(shared_source)
    migrated_legacy = _migrate_active_machine_macros(legacy_source)
    result = template
    result = _replace_section(
        result,
        "ace",
        _rebase_section(shared_target, template, "ace"),
    )
    result = _replace_section(
        result,
        "ace_machine",
        _rebase_machine_section(shared_target, template),
    )
    result = _merge_machine_macros(
        result,
        shared_target,
        template,
        migrated_legacy,
    )
    result = _append_unknown_sections(result, shared_target, template)
    result = _append_commented_machine_macros(
        result, shared_commented + legacy_commented, template
    )
    result = _restore_embedded_hardware(result, embedded_hardware)
    return _append_user_tail(result, user_tail)


def upgrade_machine(text: str, template: str) -> str:
    result = _migrate_active_machine_macros(text)
    migrated_template = _migrate_active_machine_macros(template)
    template_sections = _sections(migrated_template)
    for name in sorted(TARGET_MACRO_SECTIONS):
        template_macro = _section_text(migrated_template, name)
        if template_macro is None:
            continue
        current = _section_text(result, name)
        if current is None or (
            name in REQUIRED_MACRO_SECTIONS and not _has_nonempty_gcode(current)
        ):
            result = _replace_section(
                result, name, template_macro
            )
    return result


def write_atomic(path: Path, text: str) -> None:
    temporary = path.with_name(".%s.tmp-%d" % (path.name, os.getpid()))
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(text.rstrip() + "\n")
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("kind", choices=("shared", "machine", "merged"))
    parser.add_argument("template", type=Path)
    parser.add_argument("target", type=Path)
    parser.add_argument(
        "--legacy-machine",
        type=Path,
        help="optional retired ace_machine.cfg to merge into a shared config",
    )
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    template = args.template.read_text(encoding="utf-8")
    target = args.target.read_text(encoding="utf-8")
    try:
        result = (
            upgrade_shared(
                target,
                template,
                args.legacy_machine.read_text(encoding="utf-8")
                if args.kind == "merged" and args.legacy_machine and args.legacy_machine.is_file()
                else "",
            )
            if args.kind in ("shared", "merged")
            else upgrade_machine(target, template)
        )
    except ValueError as exc:
        parser.error(str(exc))
    if not args.check and result != target:
        write_atomic(args.target, result)
    print("%s config %s" % (args.kind, "needs upgrade" if result != target else "is current"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
