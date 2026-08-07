# 命令与 API

Ace Pro Control Center 同时提供 Klipper G-code 命令和 Moonraker HTTP API。Fluidd 使用 HTTP API；切片文件通常只需要输出 `T0-T15`。

> **安全提示：** 送料、回料、换料、卸载、烘干和辅助送料可能引发真实机械动作。确认耗材路径、喷嘴温度、切刀坐标和打印状态后再执行。ACE2 在当前版本中只读，物理动作会被拒绝。

## 工具命令

| 命令 | 说明 |
| --- | --- |
| `T0` 至 `T15` | 选择全局工具；每台 ACE 固定占四个工具号 |
| `TR` | 卸载当前工具 |

驱动固定注册 `T0-T15` 和 `TR`，不随设备数量变化。自动换料已启用并通过就绪检查时，命令会执行换料或卸载；处于手动模式或自动换料未就绪时，命令会被忽略并产生提示，但不会暂停或拒绝当前打印。

单 ACE 的有效工具范围仍是 `T0-T3`。自动换料就绪时，超出已配置设备范围的工具号会被拒绝。

`ACE_CHANGE_TOOL` 与切片使用的 `Tn` 行为不同：它是显式控制命令，自动换料未就绪时会直接报错，不会静默忽略。

## Klipper G-code 命令

### 状态与连接

| 命令 | 参数 | 说明 |
| --- | --- | --- |
| `ACE_GET_STATUS` | 无 | 输出完整 ACE 状态 JSON |
| `ACE_REFRESH` | `DEVICE` 可选 | 刷新全部设备或指定 `ace0-ace3` 的硬件缓存 |
| `ACE_RECONNECT` | `DEVICE` 可选 | 重连全部设备或指定设备 |
| `ACE_ENCODER_STATUS` | 无 | 输出共享编码器状态 |

示例：

```gcode
ACE_GET_STATUS
ACE_REFRESH DEVICE=ace0
ACE_RECONNECT DEVICE=ace0
ACE_ENCODER_STATUS
```

### 换料与手动运动

| 命令 | 必需参数 | 可选参数 | 说明 |
| --- | --- | --- | --- |
| `ACE_CHANGE_TOOL` | `TOOL=Tn` 或 `TOOL=TR` | 无 | 显式换入工具或卸载当前工具 |
| `ACE_FEED` | `TOOL`、`LENGTH` | `SPEED=80` | 指定槽位手动送料 |
| `ACE_RETRACT` | `TOOL`、`LENGTH` | `SPEED=80` | 指定槽位手动回料 |
| `ACE_ENABLE_FEED_ASSIST` | `TOOL`，或 `DEVICE` 与 `SLOT` | `CONFIRM=0/1` | 启用 ACE 内置辅助送料 |
| `ACE_DISABLE_FEED_ASSIST` | 无 | `TOOL`，或 `DEVICE` 与 `SLOT` | 停用指定或当前活动的辅助送料 |

`LENGTH` 和 `SPEED` 必须大于 0。打印中启用辅助送料必须明确传入 `CONFIRM=1`；停用不需要确认。整个单打印头拓扑同时只能有一个活动辅助送料槽位。

```gcode
ACE_FEED TOOL=T0 LENGTH=100 SPEED=80
ACE_RETRACT TOOL=T0 LENGTH=80 SPEED=60
ACE_ENABLE_FEED_ASSIST TOOL=T0 CONFIRM=1
ACE_DISABLE_FEED_ASSIST
```

### 烘干与库存

| 命令 | 必需参数 | 可选参数 | 说明 |
| --- | --- | --- | --- |
| `ACE_START_DRYING` | `TEMP` | `DEVICE=ace0`、`DURATION=240` | 启动 ACE1 烘干；时长单位为分钟 |
| `ACE_STOP_DRYING` | 无 | `DEVICE=ace0` | 停止指定设备烘干 |
| `ACE_SET_SLOT` | `SLOT=0..3` | `DEVICE=ace0`、`MATERIAL`、`COLOR`、`TEMP`、`RFID`、`STATUS` | 更新槽位库存元数据 |
| `ACE_SET_ENDLESS_SPOOL` | `ENABLE=0/1` | `MATCH_MODE=exact/material` | 设置全局无限续料策略 |
| `ACE_HANDLE_RUNOUT` | 无 | 无 | 触发已配置的无限续料处理，通常由断料流程调用 |

`ACE_START_DRYING` 的 `TEMP` 必须为正整数，并且不能超过 `max_dryer_temperature`；`DURATION` 必须至少为 1 分钟。无限续料是单打印头共享设置；启用前自动换料必须已经就绪，关闭则始终允许。

### 共享编码器校准

`ACE_ENCODER_CALIBRATE` 每次必须且只能提供下列一个参数：

| 参数 | 说明 |
| --- | --- |
| `START=1` | 开始人工校准并记录起始脉冲 |
| `LENGTH=0.01..2000` | 使用手动推动耗材的实测毫米数完成校准 |
| `CANCEL=1` | 取消本次校准 |

```gcode
ACE_ENCODER_CALIBRATE START=1
ACE_ENCODER_CALIBRATE LENGTH=150
ACE_ENCODER_CALIBRATE CANCEL=1
```

校准不会自动驱动 ACE 或挤出机。默认连续提交 `3` 段 `150 mm`，每段独立记录脉冲和分辨率；最大段间偏差 `<=5%` 通过，`>5%` 且 `<=10%` 警告后允许保存，`>10%` 或任一段脉冲不足拒绝保存。开始和完成要求：打印机不在打印、没有已装载工具、共享路径状态为 `empty`、辅助送料已关闭。执行 `START=1` 后，控制台只在脉冲增加时同步输出本段新增、本段累计和硬件累计；每移动一段执行一次 `LENGTH=<实测长度>`，完成或取消后停止输出。取消只退出校准状态，不代表校准成功。

## Moonraker HTTP API

### 端点

| 方法 | 端点 | 说明 |
| --- | --- | --- |
| `GET` | `/server/ace/status` | 返回归一化 ACE 状态及 `print_state` |
| `GET` | `/server/ace/capabilities` | 返回动作可用性、参数、确认要求和打印门禁 |
| `POST` | `/server/ace/action` | 提交固定白名单动作 |

动作请求只允许四个顶层字段：

```json
{
  "action": "select_tool",
  "params": { "tool": "T1" },
  "confirm": true,
  "client": "fluidd-card"
}
```

- `action` 必须是下表中的白名单动作。
- `params` 必须是 JSON 对象，未知参数会被拒绝。
- `confirm` 必须是布尔值，不能使用 `1` 或字符串代替 `true`。
- `client` 为 1 至 64 个字符的客户端标识，省略时为 `unknown`。
- API 不接受原始 G-code、串口数据或任意命令字段。

### 动作白名单

| `action` | 必需参数 | 可选参数 | 需确认 | 打印中允许 |
| --- | --- | --- | --- | --- |
| `refresh` | 无 | `device` | 否 | 是 |
| `diagnose` | 无 | `device`、`slot` | 否 | 是 |
| `select_tool` | `tool` | 无 | 是 | 否 |
| `unload` | 无 | 无 | 是 | 否 |
| `feed` | `device`、`length` | `slot`、`speed` | 是 | 否 |
| `retract` | `device`、`length` | `slot`、`speed` | 是 | 否 |
| `enable_feed_assist` | `tool`，或 `device` 与 `slot` | 无 | 是 | 是 |
| `disable_feed_assist` | `tool`，或 `device` 与 `slot` | 无 | 否 | 是 |
| `start_drying` | `device`、`temperature`、`duration` | 无 | 是 | 是 |
| `stop_drying` | `device` | 无 | 否 | 是 |
| `set_slot` | `device`、`slot` | `material`、`color`、`temperature`、`rfid`、`status` | 否 | 是 |
| `set_endless_spool` | `enabled` | `device`、`match_mode` | 否 | 是 |
| `encoder_calibration_start` | 无 | 无 | 否 | 否 |
| `encoder_calibration_finish` | `length` | 无 | 否 | 否 |
| `encoder_calibration_cancel` | 无 | 无 | 否 | 否 |
| `calibrate` | `device`、`mode` | `slot` | 是 | 否 |
| `recover` | `device` | 无 | 是 | 否 |

`calibrate` 是预留的通用机器校准动作。当前 Klipper 命令层没有公开对应的 `ACE_CALIBRATE` 实现，正常能力响应应将其标记为不可用；用户界面不应尝试调用。`recover` 当前转换为 `ACE_RECONNECT DEVICE=...`。

`set_endless_spool` 是全局设置。兼容字段 `device` 可以被请求校验接受，但不会把无限续料变成每设备独立设置。

API 的 `feed` 和 `retract` 始终要求 `device` 与 `length`。省略 `slot` 时，当前已装载工具必须属于该设备，否则后端无法安全确定目标并拒绝请求；维护工具建议明确发送 `slot`。

### 参数范围

| 参数 | 允许值 |
| --- | --- |
| `device` | `ace0` 至 `ace3`，且必须已配置 |
| `tool` | `T0` 至 `T15`，且不能超出实际设备范围 |
| `slot` | 整数 `0..3` |
| `length` | 有限数值 `0.01..2000` mm |
| `speed` | 有限数值 `0.01..1000` |
| `temperature` | 有限数值 `0..100` |
| `duration` | 整数 `1..1440` 分钟 |
| `enabled` | JSON 布尔值 `true` 或 `false` |
| `match_mode` | `exact` 或 `material` |
| `color` | `#RRGGBB` |
| `material`、`rfid` | 最多 64 个字符 |
| `status` | `unknown`、`empty`、`ready`、`feeding`、`retracting`、`identifying`、`error` |
| `mode` | `probe`、`save`、`cancel`；仅用于预留的 `calibrate` 动作 |

兼容别名包括 `device_id -> device`、`duration_minutes -> duration`、`target_temperature -> temperature`；辅助送料还接受 `tool_id -> tool`、`index -> slot`。新客户端应使用规范字段名。

### 确认、打印状态与路径门禁

即使前端已禁用按钮，Moonraker 仍会重新校验请求：

1. 需要确认的动作必须发送 `"confirm": true`。
2. 只有 `idle`、`standby`、`complete`、`ready` 被视为空闲状态。表中标记“打印中允许”的动作不受此项限制；其他状态，包括 `printing`、`paused` 和 `unknown`，都会阻止非安全动作。
3. 共享路径繁忙时，只允许 `refresh`、`diagnose`、`disable_feed_assist` 和 `encoder_calibration_cancel`。
4. `select_tool`、`unload` 和启用无限续料要求 `toolchange_mode: automatic` 且 `toolchange_ready: true`。
5. 物理动作要求目标设备在线、启用 `physical_actions_enabled`、声明相应能力，并且必须是已验证的 ACE1。ACE2 物理动作始终拒绝。

### 请求示例

```bash
curl http://printer.local/server/ace/status
curl http://printer.local/server/ace/capabilities
curl -X POST http://printer.local/server/ace/action \
  -H 'Content-Type: application/json' \
  -d '{"action":"feed","params":{"device":"ace0","slot":0,"length":100,"speed":80},"confirm":true,"client":"maintenance"}'
```

启用打印中的辅助送料：

```bash
curl -X POST http://printer.local/server/ace/action \
  -H 'Content-Type: application/json' \
  -d '{"action":"enable_feed_assist","params":{"tool":"T0"},"confirm":true,"client":"fluidd-page"}'
```

### 响应格式

成功响应：

```json
{
  "ok": true,
  "api_version": 3,
  "request_id": "ace-v3-...",
  "action": "refresh",
  "state": "completed",
  "retryable": false,
  "result": {}
}
```

拒绝或执行失败：

```json
{
  "ok": false,
  "api_version": 3,
  "request_id": "ace-v3-...",
  "action": "select_tool",
  "state": "rejected",
  "retryable": false,
  "error": {
    "code": "confirmation_required",
    "message": "This ACE action requires explicit confirmation.",
    "reason": "This ACE action requires explicit confirmation.",
    "retryable": false,
    "source": "moonraker",
    "timestamp": "2026-08-04T00:00:00+00:00",
    "details": {}
  }
}
```

客户端应依据 `ok`、`error.code` 和 `retryable` 处理结果，不要解析英文错误句子决定流程。
