"""Chinese user-facing messages for console and API boundaries."""

from __future__ import annotations

import re
from typing import Any, Mapping, Optional


_CHINESE_RE = re.compile(r"[\u3400-\u9fff]")

_CODE_MESSAGES = {
    "ace_error": "ACE 操作未完成。",
    "invalid_config": "ACE 配置无效，请检查 ace.cfg。",
    "invalid_parameter": "参数无效，请检查本次操作填写的内容。",
    "path_busy": "共享耗材路径正忙，请等待当前操作完成。",
    "capability_unavailable": "当前 ACE 设备不支持或未启用此操作。",
    "device_offline": "目标 ACE 设备未连接。",
    "safety_rejected": "安全检查拒绝了此操作。",
    "transport_error": "ACE 通信失败，请检查连接后重试。",
    "physical_state_unknown": "ACE 物理动作结果未确认，请先检查耗材路径并执行恢复。",
    "encoder_calibration_failed": "共享编码器校准未完成。",
    "encoder_calibration_active": "共享编码器正在校准，当前 ACE 动作已阻止。",
    "encoder_motion_fault": "共享编码器未确认耗材移动。",
    "encoder_not_ready": "共享编码器保护尚未就绪。",
    "encoder_unavailable": "共享编码器尚未收到有效计数样本。",
    "encoder_no_motion": "共享编码器未确认耗材移动。",
    "encoder_tracking_low": "共享编码器检测到的移动比例低于配置的挤出机跟踪比例。",
    "encoder_finish_failed": "共享编码器无法完成耗材移动监测。",
    "encoder_status_failed": "共享编码器状态暂时无法读取。",
    "upper_sensor_feed_timeout": "送料超时前上方传感器始终未触发。",
    "path_state_unknown": "耗材路径状态未知，请检查传感器并执行恢复。",
    "connect_failed": "ACE 连接失败，请检查串口、供电和接线。",
    "request_failed": "ACE 通信请求失败，请检查连接后重试。",
    "invalid_response": "ACE 返回了无法识别的数据。",
    "device_rejected": "ACE 设备拒绝了本次请求。",
    "execution_failed": "Klipper 未能完成 ACE 操作。",
}

_EXACT_MESSAGES = {
    "Shared filament encoder is not configured": "共享编码器未配置。",
    "Shared filament encoder does not support calibration": "当前共享编码器不支持校准。",
    "Shared filament encoder calibration could not start": "共享编码器校准无法开始。",
    "Shared filament encoder calibration could not finish": "共享编码器校准无法完成。",
    "Shared filament encoder calibration could not be cancelled": "共享编码器校准无法取消。",
    "Shared filament encoder does not support calibration cancellation": "当前共享编码器不支持取消校准。",
    "Encoder calibration length must be between 0.01 and 2000 mm": "编码器校准长度必须在 0.01 到 2000 mm 之间。",
    "Shared filament encoder protection is not ready": "共享编码器保护尚未就绪。",
    "Shared filament encoder cannot monitor ACE motion": "共享编码器无法监测 ACE 动作。",
    "Shared filament encoder could not start motion tracking": "共享编码器无法开始动作监测。",
    "Shared filament encoder cannot finish motion tracking": "共享编码器无法完成动作监测。",
    "Shared filament encoder could not finish motion tracking": "共享编码器动作监测未能完成。",
    "Shared filament encoder did not confirm ACE motion": "共享编码器未确认 ACE 耗材移动。",
    "The shared filament path is busy": "共享耗材路径正忙。",
    "The shared filament path requires manual recovery": "共享耗材路径需要人工检查并恢复。",
    "ACE motion is blocked while encoder calibration is in progress": "共享编码器校准期间禁止执行 ACE 动作。",
    "The loaded filament path has no known owning tool": "已装载耗材没有对应的工具通道。",
    "The filament path and current tool state are inconsistent": "耗材路径与当前工具状态不一致。",
    "Another tool owns the shared filament path": "共享耗材路径正由其他工具通道占用。",
    "Target slot is not ready": "目标槽位尚未就绪。",
    "Upper filament sensor did not trigger before the ACE feed timeout": "送料超时前上方传感器始终未触发。",
    "Return-path sensor did not clear within the configured retract limit": "在设定回抽范围内五通传感器仍未解除触发。",
    "Dryer temperature exceeds the configured maximum": "烘干温度超过配置允许的上限。",
    "Endless spool is disabled": "无限续料尚未启用。",
    "No current tool is available for endless spool": "当前没有可用于无限续料的工具通道。",
    "Physical actions are disabled for this ACE device": "此 ACE 设备的物理动作未启用。",
    "The selected ACE device is offline": "所选 ACE 设备未连接。",
    "The selected ACE device does not support this action": "所选 ACE 设备不支持此操作。",
    "This action requires explicit confirmation": "此操作需要明确确认。",
    "The printer state blocks this physical action": "当前打印机状态禁止执行此物理动作。",
    "Manual ACE motion is blocked while printing": "打印期间禁止手动执行 ACE 运动。",
    "The printer state is not safe for this physical action": "当前打印机状态不适合执行此物理动作。",
    "ACE2 is read-only until its physical protocol is validated": "ACE2 物理协议完成真机验证前仅允许读取状态。",
    "Protocol returned a non-object response": "ACE 协议返回了无法识别的数据。",
    "Slot must be in range 0..3": "槽位必须在 0 到 3 之间。",
    "Length and speed must be positive": "移动长度和速度必须大于零。",
    "Dryer temperature and duration must be positive": "烘干温度和持续时间必须大于零。",
    "feed assist requires TOOL or DEVICE and SLOT": "辅助送料必须指定 TOOL，或同时指定 DEVICE 与 SLOT。",
}

_PATTERN_MESSAGES = (
    (re.compile(r"^(ace\d+) is offline$", re.I), lambda match: "%s 未连接。" % match.group(1)),
    (
        re.compile(r"^(ace\d+) has not passed UID verification$", re.I),
        lambda match: "%s 尚未通过 UID 验证。" % match.group(1),
    ),
    (
        re.compile(r"^Physical action '([^']+)' is disabled for (ace\d+)$", re.I),
        lambda match: "%s 的物理动作 %s 未启用。" % (match.group(2), match.group(1)),
    ),
    (
        re.compile(r"^(ace\d+) did not confirm motion completion$", re.I),
        lambda match: "%s 未确认动作已经完成。" % match.group(1),
    ),
    (
        re.compile(r"^(ace\d+) entered state '([^']+)' while waiting for motion$", re.I),
        lambda match: "%s 等待动作完成时进入异常状态 %s。" % (match.group(1), match.group(2)),
    ),
    (
        re.compile(r"^Required filament sensor '([^']+)' is not configured$", re.I),
        lambda match: "必需的耗材传感器 %s 未配置。" % match.group(1),
    ),
    (
        re.compile(r"^ACE filament sensor '([^']+)' is not registered$", re.I),
        lambda match: "ACE 耗材传感器 %s 未注册。" % match.group(1),
    ),
    (
        re.compile(r"^ACE filament sensor '([^']+)' has no detected state$", re.I),
        lambda match: "ACE 耗材传感器 %s 没有可读取的检测状态。" % match.group(1),
    ),
    (
        re.compile(r"^Tool must be .+$", re.I),
        lambda _match: "工具号必须位于当前已配置的 T 通道范围内，或使用 TR 卸载。",
    ),
    (
        re.compile(r"^Unsupported ACE action: (.+)$", re.I),
        lambda match: "不支持的 ACE 操作：%s。" % match.group(1),
    ),
)


def localize_message(
    message: Any,
    *,
    code: Optional[str] = None,
    details: Optional[Mapping[str, Any]] = None,
) -> str:
    """Return a Chinese message without exposing untranslated UI text."""

    text = str(message or "").strip()
    if text and _CHINESE_RE.search(text):
        return text
    if text in _EXACT_MESSAGES:
        return _EXACT_MESSAGES[text]
    for pattern, formatter in _PATTERN_MESSAGES:
        match = pattern.fullmatch(text)
        if match is not None:
            return formatter(match)

    normalized_code = str(code or "").strip().lower()
    if normalized_code in _CODE_MESSAGES:
        return _CODE_MESSAGES[normalized_code]
    if details and details.get("device_id"):
        return "%s 操作未完成，请检查连接和诊断信息。" % details["device_id"]
    if text:
        return "ACE 操作未完成，请检查参数、设备连接和诊断信息。"
    return "发生未知 ACE 错误，请检查诊断信息。"


def localize_exception(exc: BaseException) -> str:
    code = getattr(exc, "code", None)
    details = getattr(exc, "details", None)
    if isinstance(exc, (ValueError, KeyError)) and not code:
        code = "invalid_parameter"
    return localize_message(exc, code=code, details=details)


__all__ = ["localize_exception", "localize_message"]
