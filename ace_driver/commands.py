"""Small, explicit Klipper G-code surface for Ace Pro Control Center."""

from __future__ import annotations

import json
import math
from typing import Any, Callable, Dict

from . import PRODUCT_NAME_ZH
from .i18n import localize_exception
from .models import SLOTS_PER_DEVICE
from .tool_map import MAX_DEVICES


class AceCommands:
    def __init__(self, manager: Any, gcode: Any) -> None:
        self.manager = manager
        self.gcode = gcode

    def register(self) -> None:
        commands = {
            "ACE_CHANGE_TOOL": (self.cmd_change_tool, "更换耗材：TOOL=T5；卸载使用 TOOL=TR"),
            "ACE_GET_STATUS": (self.cmd_get_status, "显示 ACE Pro 管理中心状态"),
            "ACE_REFRESH": (self.cmd_refresh, "刷新 ACE 设备状态"),
            "ACE_FEED": (self.cmd_feed, "手动送入指定工具通道的耗材"),
            "ACE_RETRACT": (self.cmd_retract, "手动回抽指定工具通道的耗材"),
            "ACE_ENABLE_FEED_ASSIST": (
                self.cmd_enable_feed_assist,
                "启用辅助送料；打印中使用时必须添加 CONFIRM=1",
            ),
            "ACE_DISABLE_FEED_ASSIST": (
                self.cmd_disable_feed_assist,
                "停用 ACE 辅助送料",
            ),
            "ACE_START_DRYING": (self.cmd_start_drying, "启动 ACE1 烘干"),
            "ACE_STOP_DRYING": (self.cmd_stop_drying, "停止 ACE1 烘干"),
            "ACE_SET_SLOT": (self.cmd_set_slot, "更新槽位耗材资料"),
            "ACE_SET_ENDLESS_SPOOL": (self.cmd_set_endless, "启用或停用无限续料"),
            "ACE_RECONNECT": (self.cmd_reconnect, "重新连接一个或全部 ACE 设备"),
            "ACE_HANDLE_RUNOUT": (self.cmd_handle_runout, "执行已配置的无限续料换料"),
            "ACE_ENCODER_STATUS": (
                self.cmd_encoder_status,
                "显示共享编码器状态",
            ),
            "ACE_ENCODER_CALIBRATE": (
                self.cmd_encoder_calibrate,
                "三段校准编码器：START=1、LENGTH=毫米或 CANCEL=1",
            ),
        }
        for name, (handler, description) in commands.items():
            self.gcode.register_command(name, self._guard(handler), desc=description)
        # Keep every slicer-facing tool command available in manual mode so an
        # unconfigured multi-colour file can be warned about without stopping.
        for tool in range(MAX_DEVICES * SLOTS_PER_DEVICE):
            self.gcode.register_command("T%d" % tool, self._tool_handler(tool), desc="选择 ACE 工具 T%d" % tool)
        self.gcode.register_command("TR", self._tool_handler("TR"), desc="卸载当前 ACE 耗材")

    def _guard(self, handler: Callable[[Any], Any]) -> Callable[[Any], Any]:
        def guarded(gcmd: Any) -> Any:
            try:
                return handler(gcmd)
            except Exception as exc:
                raise gcmd.error("%s：%s" % (PRODUCT_NAME_ZH, localize_exception(exc)))
        return guarded

    def _tool_handler(self, tool: Any) -> Callable[[Any], Any]:
        def handler(gcmd: Any) -> None:
            result = self.manager.handle_tool_command(tool)
            notice = result.get("notice") if isinstance(result, dict) else None
            if isinstance(notice, dict) and notice.get("message"):
                gcmd.respond_info(str(notice["message"]))
            else:
                gcmd.respond_info(
                    "%s：操作完成；%s" % (PRODUCT_NAME_ZH, json.dumps(result, ensure_ascii=False))
                )
        return self._guard(handler)

    def cmd_change_tool(self, gcmd: Any) -> None:
        tool = gcmd.get("TOOL")
        result = self.manager.change_tool(tool, confirmed=True, source="gcode")
        gcmd.respond_info(
            "%s：换料操作完成；%s" % (PRODUCT_NAME_ZH, json.dumps(result, ensure_ascii=False))
        )

    def cmd_get_status(self, gcmd: Any) -> None:
        gcmd.respond_info(
            "%s：当前状态\n%s"
            % (PRODUCT_NAME_ZH, json.dumps(self.manager.get_status(), ensure_ascii=False, sort_keys=True))
        )

    def cmd_refresh(self, gcmd: Any) -> None:
        device = gcmd.get("DEVICE", None)
        result = self.manager.refresh(device)
        gcmd.respond_info(
            "%s：已刷新 %d 台设备。" % (PRODUCT_NAME_ZH, result["device_count"])
        )

    def cmd_feed(self, gcmd: Any) -> None:
        params = self._motion_params(gcmd)
        self.manager.perform_action("feed", params, confirmed=True, source="gcode")
        gcmd.respond_info("%s：已完成 %s 手动送料。" % (PRODUCT_NAME_ZH, params["tool"]))

    def cmd_retract(self, gcmd: Any) -> None:
        params = self._motion_params(gcmd)
        self.manager.perform_action("retract", params, confirmed=True, source="gcode")
        gcmd.respond_info("%s：已完成 %s 手动回料。" % (PRODUCT_NAME_ZH, params["tool"]))

    def cmd_enable_feed_assist(self, gcmd: Any) -> None:
        params = self._feed_assist_params(gcmd)
        confirmed = bool(gcmd.get_int("CONFIRM", 0, minval=0, maxval=1))
        result = self.manager.perform_action(
            "enable_feed_assist", params, confirmed=confirmed, source="gcode"
        )
        gcmd.respond_info(
            "%s：辅助送料已启用；%s"
            % (PRODUCT_NAME_ZH, json.dumps(result, ensure_ascii=False))
        )

    def cmd_disable_feed_assist(self, gcmd: Any) -> None:
        params = self._feed_assist_params(gcmd, required=False)
        result = self.manager.perform_action(
            "disable_feed_assist", params, confirmed=True, source="gcode"
        )
        gcmd.respond_info(
            "%s：辅助送料已停用；%s"
            % (PRODUCT_NAME_ZH, json.dumps(result, ensure_ascii=False))
        )

    def cmd_start_drying(self, gcmd: Any) -> None:
        params = {
            "device": gcmd.get("DEVICE", "ace0"),
            "temperature": gcmd.get_int("TEMP", minval=1),
            "duration": gcmd.get_int("DURATION", 240, minval=1),
        }
        self.manager.perform_action("start_drying", params, confirmed=True, source="gcode")

    def cmd_stop_drying(self, gcmd: Any) -> None:
        self.manager.perform_action(
            "stop_drying", {"device": gcmd.get("DEVICE", "ace0")}, confirmed=True, source="gcode"
        )

    def cmd_set_slot(self, gcmd: Any) -> None:
        params: Dict[str, Any] = {
            "device": gcmd.get("DEVICE", "ace0"),
            "slot": gcmd.get_int("SLOT", minval=0, maxval=3),
        }
        for key in ("MATERIAL", "COLOR", "RFID", "STATUS"):
            value = gcmd.get(key, None)
            if value is not None:
                params[key.lower()] = value
        temperature = gcmd.get_int("TEMP", None)
        if temperature is not None:
            params["temperature"] = temperature
        self.manager.perform_action("set_slot", params, source="gcode")

    def cmd_set_endless(self, gcmd: Any) -> None:
        enabled = gcmd.get_int("ENABLE", minval=0, maxval=1)
        match_mode = gcmd.get("MATCH_MODE", None)
        params = {"enabled": enabled}
        if match_mode is not None:
            params["match_mode"] = match_mode
        self.manager.perform_action("set_endless_spool", params, source="gcode")

    def cmd_reconnect(self, gcmd: Any) -> None:
        self.manager.perform_action("reconnect", {"device": gcmd.get("DEVICE", None)}, source="gcode")

    def cmd_handle_runout(self, gcmd: Any) -> None:
        result = self.manager.perform_action("endless_spool_change", source="runout")
        gcmd.respond_info(
            "%s：无限续料处理完成；%s"
            % (PRODUCT_NAME_ZH, json.dumps(result, ensure_ascii=False))
        )

    def cmd_encoder_status(self, gcmd: Any) -> None:
        gcmd.respond_info(
            "%s：共享编码器状态：%s"
            % (
                PRODUCT_NAME_ZH,
                json.dumps(self.manager.encoder_status(), ensure_ascii=False, sort_keys=True),
            )
        )

    def cmd_encoder_calibrate(self, gcmd: Any) -> None:
        start = gcmd.get_int("START", None, minval=0, maxval=1)
        length = gcmd.get_float("LENGTH", None, minval=0.01, maxval=2000.0)
        cancel = gcmd.get_int("CANCEL", None, minval=0, maxval=1)
        segments = gcmd.get_int("SEGMENTS", None, minval=1, maxval=10)
        segment_length = gcmd.get_float(
            "SEGMENT_LENGTH", None, minval=0.01, maxval=2000.0
        )
        provided = sum(
            value is not None for value in (start, length, cancel)
        )
        if provided != 1:
            raise ValueError(
                "START=1、LENGTH=<实际移动毫米数>、CANCEL=1 三者必须且只能填写一项"
            )
        if start is None and (segments is not None or segment_length is not None):
            raise ValueError("SEGMENTS 和 SEGMENT_LENGTH 只能与 START=1 同时使用")
        if start is not None:
            if start != 1:
                raise ValueError("开始编码器校准时 START 必须为 1")
            options = {}
            if segments is not None:
                options["segments"] = segments
            if segment_length is not None:
                if not math.isfinite(float(segment_length)):
                    raise ValueError("每段目标长度必须是 0.01 到 2000 mm 之间的有限数值")
                options["segment_length"] = segment_length
            result = self.manager.start_encoder_calibration(**options)
            gcmd.respond_info(
                "%s：共享编码器校准已开始，共 %d 段，每段目标 %.3f mm；当前为第 1 段，起始累计计数为 %d。请手动移动耗材；控制台将在脉冲变化时实时输出计数。"
                % (
                    PRODUCT_NAME_ZH,
                    int(result.get("required_segments", 3)),
                    float(result.get("segment_length", 150.0)),
                    int(result.get("start_counts", 0)),
                )
            )
            return
        elif length is not None:
            if not math.isfinite(float(length)):
                raise ValueError(
                    "编码器校准长度必须是 0.01 到 2000 mm 之间的有限数值"
                )
            result = self.manager.finish_encoder_calibration(length)
            if not result.get("calibrated"):
                segment = result.get("segment") or {}
                gcmd.respond_info(
                    "%s：编码器校准第 %d/%d 段已记录；实际移动 %.3f mm，%d 个脉冲，%.6f mm/脉冲。请继续第 %d 段。"
                    % (
                        PRODUCT_NAME_ZH,
                        int(segment.get("index", result.get("completed_segments", 0))),
                        int(result.get("required_segments", 3)),
                        float(segment.get("measured_length", length)),
                        int(segment.get("pulses", 0)),
                        float(segment.get("mm_per_pulse", 0.0)),
                        int(result.get("current_segment", 1)),
                    )
                )
                return
            quality_text = "通过"
            if result.get("quality") == "warning":
                quality_text = "警告后保存"
            gcmd.respond_info(
                "%s：共享编码器校准完成（%s）；共移动 %.3f mm，累计 %d 个脉冲，分辨率 %.6f mm/脉冲，段间最大偏差 %.2f%%。%s"
                % (
                    PRODUCT_NAME_ZH,
                    quality_text,
                    float(result.get("measured_length", length)),
                    int(result.get("pulses", 0)),
                    float(result.get("resolution", 0.0)),
                    float(result.get("max_deviation_percent", 0.0)),
                    str(result.get("warning") or ""),
                )
            )
            return
        else:
            if cancel != 1:
                raise ValueError("取消编码器校准时 CANCEL 必须为 1")
            result = self.manager.cancel_encoder_calibration()
            gcmd.respond_info(
                "%s：共享编码器校准%s。"
                % (PRODUCT_NAME_ZH, "已取消" if result.get("cancelled") else "当前未在进行")
            )

    @staticmethod
    def _motion_params(gcmd: Any) -> Dict[str, Any]:
        return {
            "tool": gcmd.get("TOOL"),
            "length": gcmd.get_float("LENGTH", minval=0.001),
            "speed": gcmd.get_float("SPEED", 80.0, minval=0.001),
        }

    @staticmethod
    def _feed_assist_params(gcmd: Any, *, required: bool = True) -> Dict[str, Any]:
        params: Dict[str, Any] = {}
        tool = gcmd.get("TOOL", None)
        device = gcmd.get("DEVICE", None)
        slot = gcmd.get("SLOT", None)
        if tool is not None:
            params["tool"] = tool
        if device is not None:
            params["device"] = device
        if slot is not None:
            params["slot"] = slot
        if required and not params:
            raise ValueError("辅助送料必须指定 TOOL，或同时指定 DEVICE 与 SLOT")
        return params
