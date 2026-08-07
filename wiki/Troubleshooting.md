# 故障排查

先确认打印机当前没有正在执行的换料、切刀、送料或回料动作。打印期间不要为了排障重启 Klipper、Moonraker 或 Fluidd，也不要反复提交物理命令。

## 自动换料未配置，T 指令被忽略

提示示例：

```text
ACE 自动换料未配置，已忽略 T0。当前无法进行多色打印，仅可使用已启用的 ACE 内置辅助送料。
```

这是手动模式或自动换料未通过就绪检查时的保护行为。`T0-T15` 和 `TR` 会逐条提示，但不会暂停或拒绝当前打印。

如果只使用 ACE 内置辅助送料，可以保持：

```ini
[ace]
toolchange_mode: manual
```

此时应让单色切片避免输出不必要的 `Tn`，或接受每次工具指令的提醒。

要启用自动换料，需要同时满足：

1. 在 `ace.cfg` 的 `[ace]` 中设置 `toolchange_mode: automatic`。
2. 目标 ACE1 已在线，并明确设置 `physical_actions_enabled: True`。
3. `[ace_machine]` 已绑定七个必用宏。
4. `_ace_prepare_toolchange`、`_ace_cut_filament`、`_ace_load_filament_to_toolhead`、`_ace_unload_filament_from_toolhead`、`_ace_wipe_nozzle`、`_ace_restore_after_toolchange`、`_ace_pause_on_toolchange_error` 均已有适合本机的实现。
5. 切刀、擦嘴、送料和回料坐标已经在低风险条件下逐项验证。
6. 单 ACE 或多 ACE 的五通传感器、盲回退距离及共享路径清空方案满足配置要求。
7. 使用 `encoder_mode: protect` 时，共享编码器必须已配置、可用并完成校准。

修改后重启 Klipper，再用 `ACE_GET_STATUS` 或 `GET /server/ace/capabilities` 检查 `toolchange_mode`、`toolchange_ready` 和 `toolchange_blocked_reason`。不要仅为了消除提示就直接开启自动模式。

## 单 ACE 却显示了更多工具号

后端固定注册 `T0-T15`，这是正常的切片兼容行为；单 ACE 的 Fluidd 界面只能显示 `T0-T3`。

按以下顺序检查：

1. 执行 `ACE_GET_STATUS`，确认 `device_count` 为 `1`，且只有 `ace0` 处于配置列表。
2. 检查 `ace.cfg`，确认未误启用 `ace1-ace3`。
3. 如果 `/ace-v3/` 正常而 Fluidd 工具区仍显示 16 个按钮，重新构建并部署打过补丁的 Fluidd `dist`。
4. 清除浏览器站点缓存或强制刷新，避免继续使用旧 JavaScript。
5. 检查 Moonraker 是否加载 `ace_status`。ACE 状态缺失或格式错误时，工具区会保留 Fluidd 上游分组，不会自行猜测设备数。

如果 Dashboard 同时出现 V2 和 V3 两张 ACE 卡片，转到[V2 冲突](#v2-驱动宏或-fluidd-界面冲突)处理。

## ACE 设备离线

典型表现为 `connected: false`、界面显示“离线”，或 API 返回 `device_offline`。

检查项目：

- ACE 电源、USB 或总线连接是否稳定。
- ACE1 是否使用稳定的 `/dev/serial/by-id/...` 路径，而不是可能变化的短设备名。
- Klipper 运行用户是否具有串口访问权限。
- 多台 ACE1 是否误用了同一串口路径。
- ACE2 的总线、`bus_id` 和 `device_uid` 是否唯一且与实物一致。
- 设备型号是否填写正确；ACE1 与 ACE2 不能互换协议配置。

连接恢复后先执行：

```gcode
ACE_RECONNECT DEVICE=ace0
ACE_REFRESH DEVICE=ace0
ACE_GET_STATUS
```

设备重新在线不等于物理动作已验证。先完成只读状态、槽位和传感器检查，再决定是否启用物理动作。

## 传感器显示“未配置”或状态不正确

新配置只要求填写引脚，不要求用户填写传感器名称。以下字段留空即表示未启用：

```ini
extruder_sensor_pin:
toolhead_sensor_pin:
rdm_sensor_pin:
ace0_hub_sensor_pin:
ace1_hub_sensor_pin:
ace2_hub_sensor_pin:
ace3_hub_sensor_pin:
```

- `extruder_sensor_pin`：挤出机上方传感器。
- `toolhead_sensor_pin`：挤出机下方传感器。
- `rdm_sensor_pin`：全局总五通传感器。
- `aceN_hub_sensor_pin`：多 ACE 的设备一级五通传感器。

单 ACE 不需要一级五通，因此 `ace0_hub_sensor_pin` 留空且界面隐藏一级五通是正常状态。只有两台至四台 ACE 才使用一级五通。

已填写引脚但仍显示“未配置”时，检查 Klipper 实际加载的是否为当前 `ace.cfg`，以及该行是否被注释。显示电平相反时，按 Klipper 引脚语法校正上拉和反相标记；不要在未确认线路电平前让换料流程依赖该传感器。

“无料”应只来自已配置传感器的真实低/高电平。“未提供”表示驱动没有收到相应字段，通常需要检查驱动是否为当前版本及 Moonraker 状态是否刷新。

## 下方传感器偶发不触发

下方传感器不是通用安装必需项。默认 `toolhead_sensor_bypass: True` 时仅监测，偶发不触发不会阻止自动换料；确认其稳定后可显式设为 `False` 恢复下方闭环。

- 希望继续观察：保留 `toolhead_sensor_pin`，检查机械拨片、接线、供电、反相和 `toolhead_sensor_debounce_count`；界面仍显示真实原始状态。
- 不再需要观察：将 `toolhead_sensor_pin` 留空，重启后显示“未配置”即可。
- 默认旁路时自动换料未就绪：检查上方传感器、入口到喷嘴距离、`upper_sensor_feed_timeout`、必用宏和五通路径；关闭旁路时还要检查下方闭环配置。

兼容键 `toolhead_sensor_bypass_load_length` 只表示上方传感器交接点到喷嘴的挤出机标定距离，与下方传感器是否接线无关。模板 `25 mm` 是未校准样板，需要按本机低速重复测量并保存校准状态；它不是 ACE 的送料距离，非零也不代表已经校准。

## 上方传感器未在最大送料时间内触发

精确报错：

```text
Ace Pro Control Center: Upper filament sensor did not trigger within the configured load limit
```

旧版本可能仍使用 `configured load limit` 文案；当前版本使用 `before the ACE feed timeout`。两者都表示“达到最大送料时间仍未稳定触发”，不是已经精确送料了某个毫米数。

这里的上方传感器是驱动创建的固定 Klipper 对象 `extruder_sensor`，用户配置项是：

```ini
[ace]
extruder_sensor_pin: <实际引脚>
```

ACE Pro 使用直流电机，`toolchange_load_length` 和 `feed_slip_compensation_length` 只供固件参考，不能相加成真实送料距离。当前驱动以最长约 `2` 秒的受限窗口持续寻找 `extruder_sensor`：主参考量和补偿参考量耗尽后仍会低速分段送料，以上方传感器稳定触发作为唯一成功终点；编码器只判断每个窗口是否有进展，`upper_sensor_feed_timeout` 负责最终硬停止。

不要把增大两个距离参考量作为首选处理。先在打印机空闲、不会碰撞且不会把耗材强行顶入热端的条件下，验证传感器本身：

```gcode
QUERY_FILAMENT_SENSOR SENSOR=extruder_sensor
```

分别在无耗材和手动插入耗材时查询，状态必须可靠翻转：

1. 查询提示对象不存在：检查 `extruder_sensor_pin` 是否留空、被注释或没有随当前 `ace.cfg` 加载，修正后执行 Klipper `RESTART`。
2. 插入和抽出耗材时状态不变化：检查引脚、接线、供电、传感器安装位置和机械拨片，不要继续自动送料。
3. 状态能够变化但有料/无料含义相反：在 `extruder_sensor_pin` 中按 Klipper 引脚语法修正 `!` 反相标记，再重复空料与有料测试。
4. 传感器工作正常且编码器无脉冲：检查空槽、耗材是否进入正确通道、ACE 是否咬住耗材、编码器接线、PTFE 折弯、五通卡料和送料轮打滑。
5. 编码器持续有脉冲但仍超时：说明耗材可能仍在缓慢前进，也可能上方传感器未触发；最大送料时间仍必须停止。先检查路径长度、摩擦和传感器，再决定是否调整时间，不得取消硬超时。
6. 上方已触发但挤出机接管后编码器无脉冲：检查耗材是否真正进入挤出齿轮、齿轮压力、入口卡料和编码器本身。`monitor` 只提示，`protect` 会中止并禁止标记已装载。

如果日志显示固件已提前完成一个送料窗口，驱动仍会在总超时内等待传感器宽限，这是正常行为。总截止时间后的迟到触发不会把超时改判为成功；传感器读取异常时驱动也会先停止 ACE。不要在异常后立即重复提交送料，应先确认电机已经停止并检查路径状态。

每次修改参考量或最大送料时间后，先做低速、可观察的单槽测试。若耗材在达到传感器前已经顶住或弯折，应立即停止，不能依靠更大的参考量或更长时间继续尝试。

## 共享编码器不可用或无法校准

未安装编码器时保持：

```ini
encoder_sensor_pin:
encoder_mode: off
encoder_print_mode: off
```

已配置但显示“未校准”时，先确认手动推动耗材能够增加脉冲计数：

```gcode
ACE_ENCODER_STATUS
```

人工校准流程：

```gcode
ACE_ENCODER_CALIBRATE START=1
# 默认重复三段：每段手动准确移动 150 mm 后分别提交
ACE_ENCODER_CALIBRATE LENGTH=150
```

校准被拒绝时，通常是以下原因之一：

- 打印机正在打印或状态未知。
- 当前仍有已装载工具。
- 共享耗材路径不是 `empty`。
- 辅助送料仍处于启用状态。
- 另一个路径事务正在执行。
- 编码器未配置、不可用或校准已经开始。
- 任一校准段脉冲不足，或三段分辨率最大偏差超过 `10%`。

使用 `ACE_ENCODER_CALIBRATE CANCEL=1` 可以退出未完成校准。无脉冲不等于无料，常见原因还包括引脚、电平、接线、编码轮压力不足或耗材没有实际经过编码轮。

在真实脉冲和检测距离完成验证前，保持 `encoder_mode: off` 或 `monitor`，并保持 `encoder_print_mode: off` 或 `monitor`。不要直接启用 `protect` 或 `pause`。

选择 `protect` 后界面显示黄色“保护 · 未启用”，表示编码器尚未 armed，通常应检查 `available`、`calibrated` 和最近故障。短于 `encoder_detection_length` 的动作仍要求至少一个脉冲，达到该长度的动作至少要求两个有效脉冲；该参数不是送料到位距离。自动换料还要求挤出机接管段的保证运动距离不短于 `encoder_detection_length`，否则会在物理动作前拒绝，并返回普通 G-code 错误。

三段校准最大偏差在 `5%` 到 `10%` 之间时先检查编码轮压紧、弹簧、耗材打滑、测量起止点和输入电平，再决定是否确认保存；超过 `10%` 不应通过。不要把校准段长 `150 mm` 写入运行时检测长度，运行时必须保留短窗口以尽早发现卡料或未咬料。

## Dashboard 卡片或 `#/acepro` 不可用

先直接打开：

```text
http://printer.local/ace-v3/
```

如果备用页正常，说明 Klipper、Moonraker 和静态页面大体可用，问题通常位于 Fluidd 源码集成或构建产物。

常见原因：

- 安装时使用了 `standalone` 模式。
- `auto` 模式检测到不兼容的 Fluidd 版本或源码锚点，主动回退备用页。
- Fluidd 源码已打补丁，但没有重新构建并部署 `dist`。
- 浏览器仍缓存旧的 Fluidd 资源。
- `/acepro` 路由或侧栏存在未托管冲突，安装器为保护用户源码而拒绝覆盖。

当前原生源码集成面向官方 Fluidd `1.34.x-1.37.x`，但版本号匹配仍必须通过实际源码能力检查。`/ace-v3/` 是正式备用入口，不是必须移除的测试页面。

前端不得在 API 失败时回退到原始 G-code。若界面提示 API 不可用，应检查 Moonraker 的 `ace_status` 组件和三个 `/server/ace/...` 端点，而不是添加控制台绕过逻辑。

## V2 驱动、宏或 Fluidd 界面冲突

V2 与 V3 不能同时注册相同命令或各自维护同一个 `/acepro` 页面。安装前应备份配置，并确认运行链只有：

```text
printer.cfg -> ace.cfg
```

重点检查：

- `printer.cfg` 或其他 include 中仍有 V2 驱动配置。
- 活动配置中仍定义 `T0-T15`、`TR` 或 V3 已拥有的 `ACE_*` 命令。
- 仍在 include `ace_hardware.cfg` 或 `ace_machine.cfg`。
- Fluidd 源码中存在未托管的第二个 `/acepro` 路由或 ACE Pro 侧栏项。
- 旧 Fluidd `dist` 或浏览器缓存仍显示 V2 卡片。

V3 安装器会拒绝活动命令冲突。旧 `ace_hardware.cfg` 只作为一次迁移输入，合并后应从运行链移除并归档；旧 `ace_machine.cfg` 也不应继续被 include。不要通过重复定义同名宏覆盖驱动命令。

已知 V2 路由可由源码集成迁移并在卸载 V3 时恢复；额外的未知 `/acepro` 冲突会导致 `source` 模式失败，`auto` 模式则保留 `/ace-v3/`。

## 常见 API 错误

| 错误码 | 含义 | 处理 |
| --- | --- | --- |
| `ace_not_loaded` | Klipper 没有公开 ACE 状态对象 | 检查 `ace.cfg` include、Klipper 启动日志和驱动链接 |
| `confirmation_required` | 危险动作没有显式确认 | 在确认目标和风险后发送 `confirm: true` |
| `toolchange_unavailable` | 手动模式或自动换料未就绪 | 检查 `toolchange_blocked_reason`，不要强行绕过 |
| `print_state_blocked` | 当前打印状态不允许动作 | 等待空闲；不要在暂停或未知状态下重试物理动作 |
| `path_busy` | 共享耗材路径已有事务 | 等待事务结束；必要时先诊断，不要重复提交 |
| `physical_actions_disabled` | 目标设备未授权物理动作 | 完成真机验证后再修改配置 |
| `ace2_read_only` | 请求了 ACE2 物理动作 | 当前版本只允许 ACE2 连接和只读状态 |
| `device_offline` | 目标 ACE 离线 | 检查连接后重连和刷新；该错误通常可重试 |
| `capability_unavailable` | 驱动或设备未声明该能力 | 读取 capabilities 中的 `reason` |
| `invalid_device` / `invalid_tool` | 目标不存在或超出配置范围 | 使用实际设备和工具映射 |

排障时优先保存 `request_id`、`error.code`、`details`、Klipper 日志和 Moonraker 日志。不要只截取界面上的最后一句提示。
