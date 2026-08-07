#!/usr/bin/env python3
"""Generate and validate Ace Pro Control Center hardware configuration."""

from __future__ import annotations

import argparse
import configparser
import io
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional, Sequence


DEVICE_SECTION_RE = re.compile(r"^ace_device (ace[0-3])$")
ACTIVE_HARDWARE_SECTION_RE = re.compile(
    r"^[ \t]*\[(?:ace_hardware|ace_device(?:[ \t]+[^\]]+)?)\][ \t]*"
    r"(?:[#;].*)?$",
    re.IGNORECASE,
)
LEGACY_HARDWARE_INCLUDE_RE = re.compile(
    r"^[ \t]*\[include[ \t]+ace_hardware\.cfg\][ \t]*(?:\r?\n|$)",
    re.IGNORECASE | re.MULTILINE,
)
EMBEDDED_HARDWARE_BEGIN = "# >>> ACE DRIVER V3 HARDWARE TOPOLOGY BEGIN >>>"
EMBEDDED_HARDWARE_END = "# <<< ACE DRIVER V3 HARDWARE TOPOLOGY END <<<"
INLINE_COMMENT_INDEX = 96
ALLOWED_MODELS = {"ace1", "ace2", "auto"}
ROOT_OPTIONS = {"driver_version", "device_count", "topology_mode"}
DEVICE_OPTIONS = {
    "model",
    "transport",
    "serial",
    "enabled",
    "rfid_enabled",
    "physical_actions_enabled",
}
ACE2_OPTIONS = {"bus_id", "device_uid"}

ACE_WORDMARK = (
    " █████╗  ██████╗███████╗",
    "██╔══██╗██╔════╝██╔════╝",
    "███████║██║     █████╗  ",
    "██╔══██║██║     ██╔══╝  ",
    "██║  ██║╚██████╗███████╗",
    "╚═╝  ╚═╝ ╚═════╝╚══════╝",
)
DEVICE_NUMBER_WORDMARKS = {
    1: (
        "   ██╗",
        "  ███║",
        "  ╚██║",
        "   ██║",
        "   ██║",
        "   ╚═╝",
    ),
    2: (
        " ██████╗",
        " ╚════██╗",
        "  █████╔╝",
        " ██╔═══╝ ",
        " ███████╗",
        " ╚══════╝",
    ),
    3: (
        " ██████╗",
        " ╚════██╗",
        "  █████╔╝",
        "  ╚═══██╗",
        " ██████╔╝",
        " ╚═════╝ ",
    ),
    4: (
        " ██╗  ██╗",
        " ██║  ██║",
        " ███████║",
        " ╚════██║",
        "      ██║",
        "      ╚═╝",
    ),
}


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class Device:
    model: str
    serial: str
    bus_id: str = ""
    uid: str = ""
    enabled: bool = True
    rfid_enabled: bool = True
    physical_actions_enabled: Optional[bool] = None


@dataclass(frozen=True)
class EmbeddedRegion:
    start: int
    content_start: int
    content_end: int
    end: int
    begin_line: int
    end_line: int

    def content(self, text: str) -> str:
        return text[self.content_start : self.content_end]


def parse_bool(value: str, field: str) -> bool:
    lowered = value.strip().lower()
    if lowered in {"1", "true", "yes", "on"}:
        return True
    if lowered in {"0", "false", "no", "off"}:
        return False
    raise ConfigError(f"{field} must be True or False")


def parse_device_spec(spec: str) -> Device:
    fields = spec.split("|")
    if not 2 <= len(fields) <= 4:
        raise ConfigError(
            "device must be MODEL|SERIAL[|BUS_ID|UID]"
        )
    fields.extend([""] * (4 - len(fields)))
    return Device(*(field.strip() for field in fields))


def device_identity(device: Device) -> tuple[str, ...]:
    if device.model == "ace2":
        return (device.model, device.serial, device.bus_id, device.uid)
    return (device.model, device.serial)


def preserve_device_settings(
    devices: Sequence[Device], existing: Sequence[Device]
) -> list[Device]:
    """Carry user safety switches only across a stable hardware identity."""

    existing_by_identity = {device_identity(device): device for device in existing}
    preserved: list[Device] = []
    for index, device in enumerate(devices):
        previous = existing_by_identity.get(device_identity(device))
        if previous is not None:
            enabled = previous.enabled
            rfid_enabled = previous.rfid_enabled
            physical_actions_enabled = previous.physical_actions_enabled
        elif index < len(existing):
            # Replacing an occupied logical position is a new trust boundary.
            enabled = device.enabled
            rfid_enabled = existing[index].rfid_enabled
            physical_actions_enabled = False
        else:
            enabled = device.enabled
            rfid_enabled = device.rfid_enabled
            physical_actions_enabled = device.physical_actions_enabled
        preserved.append(
            Device(
                model=device.model,
                serial=device.serial,
                bus_id=device.bus_id,
                uid=device.uid,
                enabled=enabled,
                rfid_enabled=rfid_enabled,
                physical_actions_enabled=physical_actions_enabled,
            )
        )
    return preserved


def validate_devices(devices: Sequence[Device]) -> list[str]:
    errors: list[str] = []
    if not 1 <= len(devices) <= 4:
        errors.append("device_count must be between 1 and 4")

    ace1_serials: set[str] = set()
    serial_owners: dict[str, list[tuple[int, Device]]] = {}
    bus_serials: dict[str, str] = {}
    uid_owners: set[tuple[str, str]] = set()

    for index, device in enumerate(devices):
        label = f"ace{index}"
        if device.model not in ALLOWED_MODELS:
            errors.append(f"{label}: unsupported model {device.model!r}")
        if not device.serial or not device.serial.startswith("/"):
            errors.append(f"{label}: serial must be an absolute device path")
        serial_owners.setdefault(device.serial, []).append((index, device))

        if device.model == "ace1":
            if device.serial in ace1_serials:
                errors.append(f"{label}: ACE1 serial paths must be unique")
            ace1_serials.add(device.serial)
            if device.bus_id or device.uid:
                errors.append(f"{label}: ACE1 must not define bus_id or device_uid")
        elif device.model == "ace2":
            if not device.bus_id:
                errors.append(f"{label}: ACE2 requires bus_id")
            if not device.uid:
                errors.append(f"{label}: ACE2 requires an explicit device_uid")
            elif device.uid.lower() == "auto":
                errors.append(
                    f"{label}: ACE2 device_uid=auto is unavailable until persistent discovery is implemented"
                )
            previous_serial = bus_serials.setdefault(device.bus_id, device.serial)
            if previous_serial != device.serial:
                errors.append(
                    f"{label}: ACE2 bus {device.bus_id!r} uses multiple serial paths"
                )
            if device.uid and device.uid != "auto":
                identity = (device.bus_id, device.uid)
                if identity in uid_owners:
                    errors.append(f"{label}: duplicate ACE2 UID on shared bus")
                uid_owners.add(identity)
        elif device.model == "auto" and (device.bus_id or device.uid):
            errors.append(f"{label}: auto model cannot predeclare ACE2 identity")

    for serial, owners in serial_owners.items():
        if len(owners) < 2:
            continue
        if any(device.model != "ace2" for _, device in owners):
            errors.append(
                f"serial {serial!r} may be shared only by ACE2 devices"
            )
            continue
        buses = {device.bus_id for _, device in owners}
        if len(buses) != 1:
            errors.append(
                f"serial {serial!r} is shared across different ACE2 bus_id values"
            )
        if any(device.uid == "auto" for _, device in owners):
            errors.append(
                f"serial {serial!r} is shared; every ACE2 requires an explicit UID"
            )
    return errors


def _append_option(
    lines: list[str],
    name: str,
    value: object,
    *,
    purpose: str,
    filling: str,
    unit: str,
    risk: str = "",
    commented: bool = False,
) -> None:
    """Append a compact Happy Hare-style option with Chinese inline help."""

    lines.append(f"# {purpose}")
    if risk:
        lines.append(f"# {risk}")
    prefix = "# " if commented else ""
    filling = filling.rstrip("。；; ")
    unit = unit.rstrip("。；; ")
    option = f"{prefix}{name}: {value}"
    if len(option) < INLINE_COMMENT_INDEX:
        option += " " * (INLINE_COMMENT_INDEX - len(option))
    else:
        option += "  "
    lines.append(f"{option}# 填写：{filling}；单位：{unit}")


def _append_device_banner(lines: list[str], index: int, *, active: bool) -> None:
    display_number = index + 1
    first_tool = index * 4
    last_tool = first_tool + 3
    state = "已启用" if active else "未启用"
    lines.append("# " + "=" * 118)
    for ace_line, number_line in zip(
        ACE_WORDMARK, DEVICE_NUMBER_WORDMARKS[display_number]
    ):
        lines.append(f"# {ace_line}    {number_line}")
    lines.extend(
        [
            f"# 【ACE {display_number}】逻辑编号 ace{index} | 工具 T{first_tool}..T{last_tool} | {state}",
            "# " + "=" * 118,
        ]
    )


def _append_active_device(lines: list[str], index: int, device: Device) -> None:
    _append_device_banner(lines, index, active=True)
    lines.extend(
        [
            f"[ace_device ace{index}]",
            "",
        ]
    )
    _append_option(
        lines,
        "model",
        device.model,
        purpose=f"声明 ace{index} 使用的硬件协议型号。",
        filling="ACE Pro 1 填 ace1；ACE Pro 2 填 ace2；无法确认时可填 auto。",
        unit="枚举值（ace1/ace2/auto）。",
        risk="安装 ☆☆☆☆☆：型号决定协议和能力，禁止凭外观猜测。",
    )
    _append_option(
        lines,
        "transport",
        "serial",
        purpose="声明该设备使用的通信传输类型。",
        filling="当前版本固定为 serial。",
        unit="枚举值（serial）。",
    )
    serial_rule = (
        "填写 /dev/serial/by-id/ 下的完整绝对路径；同一 ACE2 总线可以共享。"
        if device.model == "ace2"
        else "填写 /dev/serial/by-id/ 下的完整绝对路径；ACE1 必须独占。"
    )
    _append_option(
        lines,
        "serial",
        device.serial,
        purpose=f"绑定 ace{index} 的稳定串口或 ACE2 总线路径。",
        filling=serial_rule,
        unit="Linux 设备路径（无物理单位）。",
        risk="安装 ☆☆☆☆☆：路径必须存在，且不能依赖 /dev/ttyUSB* 枚举顺序。",
    )
    if device.model == "ace2":
        _append_option(
            lines,
            "bus_id",
            device.bus_id,
            purpose="为 ACE2 所在总线指定稳定的逻辑名称。",
            filling="共享同一串口的 ACE2 必须填写相同 bus_id。",
            unit="总线标识（无物理单位）。",
        )
        _append_option(
            lines,
            "device_uid",
            device.uid,
            purpose="在 ACE2 总线上唯一识别这一台设备。",
            filling="填写发现并确认的明确 UID；当前版本禁止填写 auto。",
            unit="设备标识（无物理单位）。",
            risk="安装 ☆☆☆☆☆：同一 bus_id 内每台 ACE2 的 UID 必须唯一。",
        )
    _append_option(
        lines,
        "enabled",
        str(device.enabled),
        purpose="决定驱动是否加载并监管该活动设备。",
        filling="安装器生成的活动设备固定为 True；移除设备请重新运行安装器。",
        unit="布尔值（True/False）。",
    )
    _append_option(
        lines,
        "rfid_enabled",
        str(device.rfid_enabled),
        purpose="决定驱动是否采纳并展示该设备上报的 RFID 耗材元数据。",
        filling="默认填写 True；如需完全使用手工库存并忽略硬件 RFID 元数据，可改为 False。",
        unit="布尔值（True/False）。",
        risk="配置提示：False 仍保留槽位运行状态，但材质、颜色、温度等库存资料以手工配置为准。",
    )
    physical_enabled = device.physical_actions_enabled
    if physical_enabled is None:
        physical_enabled = False
    physical_rule = (
        "新安装保持 False；完成接线、路径和动作检查后才可手工改为 True。"
        if device.model == "ace1"
        else "ACE2 和 auto 在 Ace Pro Control Center 中固定为 False。"
    )
    _append_option(
        lines,
        "physical_actions_enabled",
        str(physical_enabled),
        purpose="决定该设备是否具备送料、回抽、烘干和换料等物理动作能力。",
        filling=physical_rule,
        unit="布尔值（True/False）。",
        risk=(
            "安全提示：True 只解除设备动作门禁，不代表自动换料和机器宏已经配置完成。"
            if device.model == "ace1"
            else "安装 ☆☆☆☆☆：只读型号不得手工改为 True。"
        ),
    )
    lines.append("")


def _append_inactive_device(lines: list[str], index: int) -> None:
    _append_device_banner(lines, index, active=False)
    display_number = index + 1
    lines.extend(
        [
            f"# [ace_device ace{index}]",
            "# model: ace1",
            "# transport: serial",
            f"# serial: /dev/serial/by-id/REPLACE_WITH_ACE_DEVICE_{display_number}_SERIAL_PATH",
            "# enabled: False",
            "# rfid_enabled: True",
            "# physical_actions_enabled: False",
            "# 提示：该段仅用于识别字段；新增设备请重新运行安装器。",
            "",
        ]
    )


def render(devices: Sequence[Device]) -> str:
    errors = validate_devices(devices)
    if errors:
        raise ConfigError("\n".join(errors))

    lines = [
        "########################################################################################################################",
        "# ACE Pro 管理中心 - 硬件拓扑配置（安装器生成）",
        "# 多 ACE 设备 / 单打印头工具映射",
        "#",
        "# 排版层级参考 Happy Hare 的 mmu_parameters.cfg；这里只参考格式，不引入 MMU 参数或硬件假设。",
        "########################################################################################################################",
        "",
        "# 一、拓扑总表 ---------------------------------------------------------------------------------------------------------",
        "# ████████╗ ██████╗ ██████╗  ██████╗ ██╗      ██████╗  ██████╗  ███████╗",
        "# ╚══██╔══╝██╔═══██╗██╔══██╗██╔═══██╗██║     ██╔═══██╗██╔══██╗ ██╔════╝",
        "#    ██║   ██║   ██║██████╔╝██║   ██║██║     ██║   ██║██████╔╝ █████╗  ",
        "#    ██║   ██║   ██║██╔═══╝ ██║   ██║██║     ██║   ██║██╔═══╝  ██╔══╝  ",
        "#    ██║   ╚██████╔╝██║     ╚██████╔╝███████╗╚██████╔╝██║      ███████╗",
        "#    ╚═╝    ╚═════╝ ╚═╝      ╚═════╝ ╚══════╝ ╚═════╝ ╚═╝      ╚══════╝",
        "#",
        "# 本管理区只保存设备数量、逻辑顺序、型号、串口、ACE2 总线和 UID；共享速度、距离、传感器和机器宏位于同一 ace.cfg 的其他区域。",
        "# 支持 1..4 台设备以及 ACE1+ACE1、ACE1+ACE2、ACE2+ACE2 等组合；增删设备必须重新运行安装命令。",
        "#",
        "# 逻辑设备与工具路径图：",
        "# [ace0 槽1..4] -> [T0..T3]   \\",
        "# [ace1 槽1..4] -> [T4..T7]    \\",
        "# [ace2 槽1..4] -> [T8..T11]    > [共享耗材路径] -> [单打印头]",
        "# [ace3 槽1..4] -> [T12..T15]  /",
        "#",
        "# 风险标记：安装 ☆☆☆☆☆ = 重启 Klipper 前核对；动作 ☆☆☆☆☆ = 首次物理动作前核对。",
        "",
        "[ace_hardware]",
        "",
    ]
    _append_option(
        lines,
        "driver_version",
        "3",
        purpose="要求驱动按第三代硬件拓扑契约解析本文件。",
        filling="固定为 3。",
        unit="无。",
    )
    _append_option(
        lines,
        "device_count",
        len(devices),
        purpose="声明连续启用的 ace_device 节数量，并确定自动模式可换料的目标范围。",
        filling="填写 1..4，且必须与从 ace0 开始的连续活动设备节数量相同。",
        unit="台。",
        risk="安装 ☆☆☆☆☆：数量与活动设备节不一致时，Klipper 会拒绝加载。",
    )
    _append_option(
        lines,
        "topology_mode",
        "configured",
        purpose="固定以配置顺序确定 ace0..ace3 和 T0..T15，不随 USB 枚举变化。",
        filling="固定为 configured。",
        unit="枚举值（configured）。",
    )
    lines.extend(
        [
            "# 二、活动设备明细 -----------------------------------------------------------------------------------------------",
            "# ██████╗ ███████╗██╗   ██╗██╗ ██████╗███████╗███████╗",
            "# ██╔══██╗██╔════╝██║   ██║██║██╔════╝██╔════╝██╔════╝",
            "# ██║  ██║█████╗  ██║   ██║██║██║     █████╗  ███████╗",
            "# ██║  ██║██╔══╝  ╚██╗ ██╔╝██║██║     ██╔══╝  ╚════██║",
            "# ██████╔╝███████╗ ╚████╔╝ ██║╚██████╗███████╗███████║",
            "# ╚═════╝ ╚══════╝  ╚═══╝  ╚═╝ ╚═════╝╚══════╝╚══════╝",
            "#",
            "# ACE1 必须使用独立串口；ACE2 可在同一 bus_id 下共享串口，",
            "# 但同一总线上的每台 ACE2 必须填写不同且明确的 device_uid。",
            "",
        ]
    )
    for index, device in enumerate(devices):
        _append_active_device(lines, index, device)

    lines.extend(
        [
            "# 三、未启用设备模板（全部保持注释） -------------------------------------------------------------------------------",
            "# !!! 不要手动取消占位段注释。增删设备必须重新运行安装器，以生成连续的活动设备节。",
            "# 公共字段速查（以下未启用设备共用，只说明一次）：",
            "#   model = 协议型号（ace1 / ace2 / auto）；transport = 固定 serial。",
            "#   serial = /dev/serial/by-id/ 稳定路径；enabled = 是否加载设备。",
            "#   rfid_enabled = 是否采用 RFID 元数据；physical_actions_enabled = 物理动作门禁。",
            "#   ACE2 启用后还会由安装器生成 bus_id 和唯一 device_uid。",
            "",
        ]
    )
    for index in range(len(devices), 4):
        _append_inactive_device(lines, index)
    lines.extend(
        [
            "# 四、组合填写规则 -----------------------------------------------------------------------------------------------",
            "# ██████╗ █████╗ ██╗     ███████╗███████╗",
            "# ██╔══██╗██╔══██╗██║     ██╔════╝██╔════╝",
            "# ██████╔╝███████║██║     █████╗  ███████╗",
            "# ██╔══██╗██╔══██║██║     ██╔══╝  ╚════██║",
            "# ██████╔╝██║  ██║███████╗███████╗███████║",
            "# ╚═════╝ ╚═╝  ╚═╝╚══════╝╚══════╝╚══════╝",
            "#",
            "# ACE1+ACE1：每台使用不同 serial，不填写 bus_id 或 device_uid。",
            "# ACE1+ACE2：ACE1 独占 serial；ACE2 另填 serial、bus_id、device_uid。",
            "# ACE2+ACE2：可分总线；也可共享 serial 和 bus_id，但 UID 必须不同。",
            "# 3..4 台：继续按相同规则生成连续 ace2、ace3，配置顺序固定工具号。",
        ]
    )
    return "\n".join(lines) + "\n"


def render_embedded(devices: Sequence[Device]) -> str:
    """Render the hardware-only document inside explicit managed boundaries."""

    return (
        f"{EMBEDDED_HARDWARE_BEGIN}\n"
        f"{render(devices)}"
        f"{EMBEDDED_HARDWARE_END}\n"
    )


def _find_embedded_region(
    text: str, *, require: bool
) -> tuple[Optional[EmbeddedRegion], list[str]]:
    lines = text.splitlines(keepends=True)
    starts: list[int] = []
    offset = 0
    for line in lines:
        starts.append(offset)
        offset += len(line)

    begin_lines = [
        index
        for index, line in enumerate(lines)
        if line.strip() == EMBEDDED_HARDWARE_BEGIN
    ]
    end_lines = [
        index
        for index, line in enumerate(lines)
        if line.strip() == EMBEDDED_HARDWARE_END
    ]
    begin_mentions = sum(line.count(EMBEDDED_HARDWARE_BEGIN) for line in lines)
    end_mentions = sum(line.count(EMBEDDED_HARDWARE_END) for line in lines)

    errors: list[str] = []
    if begin_mentions != len(begin_lines) or end_mentions != len(end_lines):
        errors.append("damaged embedded hardware boundary marker")
    if len(begin_lines) > 1 or len(end_lines) > 1:
        errors.append("duplicate embedded hardware boundaries")
    if not begin_lines and not end_lines:
        if require:
            errors.append("missing embedded hardware BEGIN/END boundaries")
        return None, errors
    if len(begin_lines) != 1 or len(end_lines) != 1:
        errors.append(
            "incomplete embedded hardware boundaries: exactly one BEGIN and END are required"
        )
        return None, list(dict.fromkeys(errors))
    if begin_lines[0] >= end_lines[0]:
        errors.append("embedded hardware boundaries are out of order")
        return None, list(dict.fromkeys(errors))
    if errors:
        return None, list(dict.fromkeys(errors))

    begin_line = begin_lines[0]
    end_line = end_lines[0]
    begin_start = starts[begin_line]
    content_start = begin_start + len(lines[begin_line])
    content_end = starts[end_line]
    region_end = content_end + len(lines[end_line])
    return (
        EmbeddedRegion(
            start=begin_start,
            content_start=content_start,
            content_end=content_end,
            end=region_end,
            begin_line=begin_line,
            end_line=end_line,
        ),
        [],
    )


def _hardware_sections_outside_region(
    text: str, region: Optional[EmbeddedRegion]
) -> list[str]:
    errors: list[str] = []
    for index, line in enumerate(text.splitlines()):
        if not ACTIVE_HARDWARE_SECTION_RE.fullmatch(line):
            continue
        if region is not None and region.begin_line < index < region.end_line:
            continue
        errors.append(
            f"active hardware section {line.strip()} outside managed boundaries "
            f"at line {index + 1}"
        )
    return errors


def validate_embedded_text(text: str) -> list[str]:
    """Validate only the managed hardware block and its placement in ace.cfg."""

    region, errors = _find_embedded_region(text, require=True)
    errors.extend(_hardware_sections_outside_region(text, region))
    if region is not None and not errors:
        errors.extend(validate_hardware_text(region.content(text)))
    return list(dict.fromkeys(errors))


def validate_embedded_file(path: Path) -> list[str]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return [f"cannot read {path}: {exc}"]
    return validate_embedded_text(text)


def merge_hardware_topology(text: str, devices: Sequence[Device]) -> str:
    """Insert or replace the managed hardware block in an ace.cfg document."""

    region, boundary_errors = _find_embedded_region(text, require=False)
    placement_errors = _hardware_sections_outside_region(text, region)
    if boundary_errors or placement_errors:
        raise ConfigError("\n".join(boundary_errors + placement_errors))
    if region is not None:
        current_errors = validate_embedded_text(text)
        if current_errors:
            raise ConfigError("\n".join(current_errors))

    legacy_includes = list(LEGACY_HARDWARE_INCLUDE_RE.finditer(text))
    if len(legacy_includes) > 1:
        raise ConfigError("duplicate [include ace_hardware.cfg] entries")

    newline = "\r\n" if "\r\n" in text else "\n"
    embedded = render_embedded(devices)
    if newline != "\n":
        embedded = embedded.replace("\n", newline)

    if region is not None:
        merged = text[: region.start] + embedded + text[region.end :]
        merged = LEGACY_HARDWARE_INCLUDE_RE.sub("", merged)
    elif legacy_includes:
        merged = LEGACY_HARDWARE_INCLUDE_RE.sub(embedded, text, count=1)
    elif not text:
        merged = embedded
    else:
        separator = "" if text.endswith(("\n\n", "\r\n\r\n")) else newline
        if not text.endswith(("\n", "\r")):
            separator = newline + newline
        merged = text + separator + embedded

    errors = validate_embedded_text(merged)
    if errors:
        raise ConfigError("\n".join(errors))
    return merged


def reformat_hardware_document(
    text: str, source: object = "<hardware configuration>"
) -> str:
    """Reformat standalone hardware text or only the managed ace.cfg region."""

    region, boundary_errors = _find_embedded_region(text, require=False)
    if boundary_errors:
        raise ConfigError("\n".join(boundary_errors))

    if region is None:
        return render(_configured_devices_from_text(text, source))

    errors = validate_embedded_text(text)
    if errors:
        raise ConfigError("\n".join(errors))
    devices = _configured_devices_from_text(region.content(text), source)

    embedded = render_embedded(devices)
    if "\r\n" in text[region.start : region.end]:
        embedded = embedded.replace("\n", "\r\n")
    return text[: region.start] + embedded + text[region.end :]


def _new_parser() -> configparser.ConfigParser:
    parser = configparser.ConfigParser(
        delimiters=(":", "="),
        interpolation=None,
        strict=True,
        inline_comment_prefixes=("#", ";"),
    )
    parser.optionxform = str.lower
    return parser


def load_config_text(
    text: str, source: object = "<hardware configuration>"
) -> configparser.ConfigParser:
    parser = _new_parser()
    try:
        parser.read_file(io.StringIO(text), source=str(source))
    except configparser.Error as exc:
        raise ConfigError(f"cannot parse {source}: {exc}") from exc
    return parser


def load_config(path: Path) -> configparser.ConfigParser:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"cannot parse {path}: {exc}") from exc
    return load_config_text(text, path)


def _validate_parser(parser: configparser.ConfigParser) -> list[str]:
    errors: list[str] = []
    if not parser.has_section("ace_hardware"):
        return ["missing [ace_hardware] section"]
    root = parser["ace_hardware"]
    for option in sorted(set(root) - ROOT_OPTIONS):
        errors.append(f"ace_hardware: unexpected option {option!r}")
    try:
        count = int(root.get("device_count", ""))
    except ValueError:
        return ["device_count must be an integer"]
    if root.get("driver_version") != "3":
        errors.append("driver_version must be 3")
    if root.get("topology_mode", "configured") != "configured":
        errors.append("topology_mode must be configured")

    section_names = []
    for section in parser.sections():
        match = DEVICE_SECTION_RE.match(section)
        if match:
            section_names.append(match.group(1))
        elif section != "ace_hardware":
            errors.append(f"unexpected section [{section}]")
    expected_names = [f"ace{index}" for index in range(count)]
    if section_names != expected_names:
        errors.append(
            "active device sections must be continuous and ordered: "
            + ", ".join(expected_names)
        )

    devices: list[Device] = []
    for index, name in enumerate(expected_names):
        section_name = f"ace_device {name}"
        if not parser.has_section(section_name):
            continue
        section = parser[section_name]
        model = section.get("model", "").lower()
        allowed_options = DEVICE_OPTIONS | (ACE2_OPTIONS if model == "ace2" else set())
        for option in sorted(set(section) - allowed_options):
            errors.append(f"{name}: unexpected option {option!r}")
        if section.get("transport", "") != "serial":
            errors.append(f"{name}: transport must be serial")
        try:
            enabled = parse_bool(section.get("enabled", ""), f"{name}.enabled")
            rfid_enabled = parse_bool(
                section.get("rfid_enabled", "True"),
                f"{name}.rfid_enabled",
            )
            physical = parse_bool(
                section.get("physical_actions_enabled", ""),
                f"{name}.physical_actions_enabled",
            )
            devices.append(
                Device(
                    model=model,
                    serial=section.get("serial", ""),
                    bus_id=section.get("bus_id", ""),
                    uid=section.get("device_uid", ""),
                    enabled=enabled,
                    rfid_enabled=rfid_enabled,
                    physical_actions_enabled=physical,
                )
            )
            if model == "ace2" and physical:
                errors.append(f"{name}: ACE2 physical actions must be False")
            if model != "ace1" and physical:
                errors.append(f"{name}: unverified models cannot enable physical actions")
        except ConfigError as exc:
            errors.append(str(exc))
    errors.extend(validate_devices(devices))
    return list(dict.fromkeys(errors))


def validate_hardware_text(
    text: str, source: object = "<hardware configuration>"
) -> list[str]:
    try:
        parser = load_config_text(text, source)
    except ConfigError as exc:
        return [str(exc)]
    return _validate_parser(parser)


def validate_file(path: Path) -> list[str]:
    try:
        parser = load_config(path)
    except ConfigError as exc:
        return [str(exc)]
    return _validate_parser(parser)


def _configured_devices_from_text(text: str, source: object) -> list[Device]:
    errors = validate_hardware_text(text, source)
    if errors:
        raise ConfigError("\n".join(errors))
    parser = load_config_text(text, source)
    count = int(parser["ace_hardware"]["device_count"])
    devices: list[Device] = []
    for index in range(count):
        section = parser[f"ace_device ace{index}"]
        devices.append(
            Device(
                model=section["model"].lower(),
                serial=section["serial"],
                bus_id=section.get("bus_id", ""),
                uid=section.get("device_uid", ""),
                enabled=parse_bool(section["enabled"], f"ace{index}.enabled"),
                rfid_enabled=parse_bool(
                    section.get("rfid_enabled", "True"),
                    f"ace{index}.rfid_enabled",
                ),
                physical_actions_enabled=parse_bool(
                    section["physical_actions_enabled"],
                    f"ace{index}.physical_actions_enabled",
                ),
            )
        )
    return devices


def read_configured_devices(path: Path) -> list[Device]:
    """Read hardware devices from a standalone file or a complete ace.cfg."""

    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"cannot read {path}: {exc}") from exc

    region, boundary_errors = _find_embedded_region(text, require=False)
    if boundary_errors:
        raise ConfigError("\n".join(boundary_errors))
    if region is None:
        return _configured_devices_from_text(text, path)

    errors = validate_embedded_text(text)
    if errors:
        raise ConfigError("\n".join(errors))
    return _configured_devices_from_text(region.content(text), path)


def write_atomic(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate, merge, and validate Ace Pro Control Center hardware topology."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    generate = subparsers.add_parser("generate")
    generate.add_argument("--device", action="append", required=True)
    generate.add_argument("--output", type=Path)
    generate.add_argument("--preserve-from", type=Path)
    merge = subparsers.add_parser(
        "merge", help="atomically insert or replace hardware topology in ace.cfg"
    )
    merge.add_argument("path", type=Path, help="ace.cfg to update in place")
    merge.add_argument("--device", action="append", required=True)
    merge.add_argument("--preserve-from", type=Path)
    validate = subparsers.add_parser("validate")
    validate.add_argument("path", type=Path)
    validate_embedded = subparsers.add_parser(
        "validate-embedded", help="validate only the managed hardware block in ace.cfg"
    )
    validate_embedded.add_argument("path", type=Path)
    reformat = subparsers.add_parser("reformat")
    reformat.add_argument("path", type=Path)
    reformat.add_argument("--output", type=Path)
    return parser


def main(argv: Optional[Iterable[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "generate":
        try:
            devices = [parse_device_spec(spec) for spec in args.device]
            if args.preserve_from and args.preserve_from.exists():
                devices = preserve_device_settings(
                    devices, read_configured_devices(args.preserve_from)
                )
            content = render(devices)
            if args.output:
                write_atomic(args.output, content)
            else:
                sys.stdout.write(content)
        except ConfigError as exc:
            print(f"hardware configuration error: {exc}", file=sys.stderr)
            return 2
        return 0

    if args.command == "merge":
        try:
            text = args.path.read_text(encoding="utf-8")
            devices = [parse_device_spec(spec) for spec in args.device]
            preserve_from = None
            if args.preserve_from and args.preserve_from.exists():
                preserve_from = args.preserve_from
            else:
                region, boundary_errors = _find_embedded_region(text, require=False)
                if boundary_errors:
                    raise ConfigError("\n".join(boundary_errors))
                if region is not None:
                    preserve_from = args.path
            if preserve_from is not None:
                devices = preserve_device_settings(
                    devices, read_configured_devices(preserve_from)
                )
            write_atomic(args.path, merge_hardware_topology(text, devices))
        except (ConfigError, OSError) as exc:
            print(f"hardware configuration error: {exc}", file=sys.stderr)
            return 2
        print(f"merged: {args.path}")
        return 0

    if args.command == "reformat":
        try:
            with args.path.open("r", encoding="utf-8", newline="") as handle:
                source_text = handle.read()
            content = reformat_hardware_document(source_text, args.path)
            write_atomic(args.output or args.path, content)
        except (ConfigError, OSError) as exc:
            print(f"hardware configuration error: {exc}", file=sys.stderr)
            return 2
        return 0


    if args.command == "validate-embedded":
        errors = validate_embedded_file(args.path)
        if errors:
            for error in errors:
                print(f"hardware configuration error: {error}", file=sys.stderr)
            return 2
        print(f"valid embedded hardware: {args.path}")
        return 0

    errors = validate_file(args.path)
    if errors:
        for error in errors:
            print(f"hardware configuration error: {error}", file=sys.stderr)
        return 2
    print(f"valid: {args.path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
