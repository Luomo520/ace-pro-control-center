# ACE Pro 管理中心详细配置样式参考

> 状态：已确认的设计基线
> 整理日期：2026-07-28
> 用途：保存 `ace.cfg` 的完整分区、注释和迁移规则，避免依赖历史对话。
> 注意：本文是设计与重建依据，不应直接作为打印机配置上传。

## 一、历史结论

这份样式来自项目历史对话中已经确认的决定。核心要求如下：

1. `ace.cfg` 保持为一个文件，不拆成多个配置文件。
2. 默认参数、机器必填参数和可选功能必须分区，不再堆放在一起。
3. 每个功能区使用明显的分隔线、中文编号和足够的空行。
4. 每个配置项至少说明用途；需要用户调整的项目还要说明填写方法、单位、建议范围和风险。
5. 使用 `☆☆☆☆☆` 标记必须根据本机接线或机械结构确认的参数。
6. 五通传感器、五通停放和受其影响的自动探测参数必须放在同一功能区。
7. 统一称为“五通传感器”，不能称为“PC0 传感器”。`PC0` 只是某一台打印机的实际引脚。
8. 通用安装模板不得预填上方、下方或五通传感器引脚，也不得预填切刀坐标。
9. 当前打印机的升级配置必须保留已经确认的实际引脚、距离、速度和宏，不能被通用模板默认值覆盖。
10. 工具宏不需要逐项参数说明；通用模板中的切刀宏必须保持注释并说明风险。
11. `serial` 使用项目已经确认的 ACE USB by-id 路径。
12. “标定”面向用户的名称统一为“自动探测料管长度”。
13. 材料配置必须同时包含耗材名称、ACE 烘干温度和推荐喷嘴温度。
14. `[save_variables]`、`[respond]` 和 `[force_move]` 属于 Klipper 全局配置，安装器必须先检查是否已有同名节，禁止重复声明。

## 二、文件顶部样式

配置文件顶部应包含：

- 项目名称：`ACE Pro 管理中心 DIY 配置文件`。
- `☆☆☆☆☆` 的含义。
- 送料与回料路径图。
- 速度单位为 `mm/s`、距离单位为 `mm`、温度单位为摄氏度、超时单位为秒。
- 通用模板与当前打印机配置的区别。

建议路径图：

```text
送料：
ACE 料槽 -> ACE 出料口 -> 五通 -> 五通传感器（可选）
         -> 上方传感器 -> 挤出机 -> 下方传感器 -> 喷嘴

回料：
喷嘴 <- 下方传感器 <- 挤出机 <- 上方传感器
     <- 五通传感器（可选） <- 五通 <- ACE 料槽
```

## 三、单项注释格式

必须调整或存在明显风险的参数使用以下格式：

```ini
# ☆☆☆☆☆ 参数中文名称。
#
# 作用：
# 说明驱动在什么流程中读取该参数，以及它影响哪一段物理动作。
#
# 填写：
# 说明单位、测量起点和终点、推荐初始值、允许范围及过大或过小的风险。
#
parameter_name: value
```

无需用户调整的安全默认值可以简化，但仍须说明作用和单位：

```ini
# 参数中文名称。
#
# 作用：
# 说明该默认值影响的行为。
#
parameter_name: value
```

## 四、最终分区顺序

### 一、Klipper 前置配置

- `[save_variables]`
- `[respond]`
- `[force_move] enable_force_move: True` 只做依赖说明，不在已有配置中重复声明。

### 二、ACE 核心连接配置

- `serial`
- `baud`
- `enable_debug_rpc`

`enable_debug_rpc` 日常必须为 `False`。只有协议开发或故障排查时才允许开启原始 RPC 调试入口。

### 三、安装后必须确认的机器结构参数

- `extruder_sensor_pin`：上方耗材传感器引脚。
- `toolhead_sensor_pin`：下方耗材传感器引脚。
- `toolchange_load_length`：ACE 内部停放点到上方传感器的最大送料距离。
- `toolchange_retract_length`：换料时释放公共通道所需的总回料距离。
- `toolhead_sensor_to_nozzle`：下方传感器到喷嘴的耗材路径长度。
- `bowden_tube_length`：ACE 出料口到五通进料口的 PTFE 管长度。

### 四、五通传感器与五通停放

- `parking_sensor_pin`
- `parking_sensor_position`
- `parking_sensor_clear_move_length`
- `parking_sensor_debounce_count`
- `five_way_parking_margin`

规则：

- `parking_sensor_pin` 注释表示不启用五通传感器。
- `after_five_way` 表示传感器位于五通之后、靠挤出机一侧。
- `before_five_way` 表示传感器位于五通之前、靠 ACE 一侧。
- `parking_sensor_clear_move_length` 已包含安全余量时，不再叠加 `five_way_parking_margin`。
- 通用模板不得出现 `^PC0` 等真实引脚。

### 五、高速送料与接近传感器送料

- `feed_speed`
- `feed_fast_speed`
- `feed_approach_speed`
- `feed_approach_length`
- `intermittent_feed`
- `feed_fast_chunk_length`
- `feed_slip_compensation_length`
- `feed_slip_compensation_chunk`
- `feed_slip_compensation_speed`

说明重点：

- `False` 连续送料用于取消每 100 mm 的停顿。
- 快速阶段接近预计触发位置后切换到慢速。
- 正常送料结束仍未触发上方传感器时，才进入有限打滑补偿。
- 达到送料上限后必须暂停并报告，不允许无限磨料。

### 六、回料速度与断续回抽

- `retract_speed`
- `retract_fast_speed`
- `retract_parking_speed`
- `retract_parking_length`
- `intermittent_retract`

`False` 表示快速回料段和慢速停放段各发送一次连续请求；不能解释为取消末端慢速保护。

### 七、挤出机送料与下方传感器

- `toolhead_feed_fast_speed`
- `toolhead_feed_slow_speed`
- `toolhead_feed_fast_length`
- `toolhead_feed_fast_step`
- `toolhead_feed_slow_step`
- `toolhead_to_nozzle_speed`
- `toolhead_sensor_max_feed_length`
- `extruder_sensor_timeout`

这一组控制上方传感器触发后，由挤出机把耗材送到下方传感器，再送到喷嘴的过程。

### 八、ACE 通信与断联保护

- `ace_ready_timeout`
- `ace_stop_ready_timeout`
- `ace_request_timeout`
- `ace_reconnect_timeout`
- `ace_reconnect_stable_time`
- `ace_motion_chunk_length`
- `ace_resume_max_retries`
- `auto_toolchange_recovery`
- `auto_toolchange_recovery_max_retries`
- `auto_resume_after_ace_reconnect`

说明重点：

- 断联后不能盲目重放结果不确定的送料、回料或切刀动作。
- 自动恢复必须以传感器状态和已确认阶段为依据。
- 打印过程中的恢复应尽量自动完成，无法确认安全状态时暂停打印。

### 九、自动探测料管长度

- `calibration_max_retract_length`
- `calibration_speed`
- `calibration_chunk_length`
- `calibration_final_chunk_length`

界面完成后应按模式显示：

- 启用五通传感器：上方传感器到五通传感器、上方传感器到五通停放点。
- 未启用五通传感器：上方传感器到内部停放点。
- 所有结果使用 `mm`。
- 执行送料或回料动作前必须由用户确认。

### 十、烘干功能

- `max_dryer_temperature`

材料实际烘干温度由第十二节材料档案决定，但不得超过该安全上限。

### 十一、无限续料

历史摘录缺失的完整内容如下：

```ini
# 是否默认启用无限续料。
# False：断料后暂停打印。
# True：满足条件时允许切换备用料槽。
endless_spool: False

# 是否要求备用槽材料名称与当前材料相同。
# True 为推荐值，无法匹配时暂停打印。
endless_spool_require_same_material: True

# 断料传感器连续确认次数。
# 驱动轮询周期约 50 ms，3 次约 150 ms。
runout_debounce_count: 3
```

### 十二、耗材名称、烘干温度和耗材温度

历史摘录生成之后新增的完整配置如下。所有项目必须保留在 `[ace]` 内，不能创建无法被 Klipper 识别的独立 `[ace_materials]` 节。

```ini
material_1_name: PLA
material_1_drying_temperature: 45
material_1_temperature: 210

material_2_name: ABS
material_2_drying_temperature: 60
material_2_temperature: 260

material_3_name: PETG
material_3_drying_temperature: 60
material_3_temperature: 250

material_4_name: ABSCF
material_4_drying_temperature: 60
material_4_temperature: 260

material_5_name: PAHTCF
material_5_drying_temperature: 60
material_5_temperature: 270

material_6_name: PETCF
material_6_drying_temperature: 60
material_6_temperature: 270

material_7_name: PEEK
material_7_drying_temperature: 60
material_7_temperature: 360

unknown_material_drying_temperature: 45
unknown_material_temperature: 0
mixed_material_drying_temperature: 50
show_material_warning: True
```

字段含义：

- `material_*_name`：界面显示和槽位材料匹配名称。
- `material_*_drying_temperature`：ACE 烘干温度。
- `material_*_temperature`：推荐喷嘴打印温度，不用于控制烘干。
- 未知材料使用 45°C，并提示烘干效果可能受限。
- PLA 与其他材料混装时使用 50°C，提示其他材料烘干效果可能受限。

### 十三、工具、换料和切刀宏

通用安装模板：

- `TR`、`T0`、`T1`、`T2`、`T3` 可以默认提供。
- `_ACE_PRE_TOOLCHANGE` 和 `_ACE_POST_TOOLCHANGE` 默认只能输出提示，不能移动 XY/Z、加热或调用其他机器专属宏。
- `CUT_TIP` 必须保持注释，直到用户填写本机切刀坐标。

当前打印机升级：

- 必须原样保留现有 `CUT_TIP`。
- 必须原样保留 `_ACE_PRE_TOOLCHANGE` 和 `_ACE_POST_TOOLCHANGE`。
- 必须原样保留 `_ACE_ON_EMPTY_ERROR`、`TR`、`T0` 至 `T3`。
- 不能用通用模板的空操作宏覆盖已经验证的本机宏。

当前打印机的宏行为记录：

- `CUT_TIP` 使用 `X10`、`Y330/Y350`，并执行挤出机 `FORCE_MOVE -50 mm`。
- 换料前处理保存 `TOOLCHANGE` 状态、抬升 Z、移动到 `X289 Y350`，最低喷嘴温度为 240°C。
- 换料后处理下降 Z、执行 `CLEAN_NOZZLE`，并按打印状态恢复位置。

## 五、当前打印机必须保留的值

将当前打印机配置转换为详细样式时，以下值不能改成通用模板默认值：

```ini
serial: /dev/serial/by-id/usb-ANYCUBIC_ACE_1-if00
baud: 115200
enable_debug_rpc: False

extruder_sensor_pin: ^TGL36:PA2
toolhead_sensor_pin: ^TGL36:PA5
parking_sensor_pin: ^PC0
parking_sensor_position: after_five_way
parking_sensor_clear_move_length: 75
parking_sensor_debounce_count: 3
five_way_parking_margin: 20

toolchange_load_length: 1200
toolchange_retract_length: 800
toolhead_sensor_to_nozzle: 80
bowden_tube_length: 190

feed_speed: 80
feed_fast_speed: 160
feed_approach_speed: 25
feed_approach_length: 200
intermittent_feed: False
feed_fast_chunk_length: 1000
feed_slip_compensation_length: 400
feed_slip_compensation_chunk: 50
feed_slip_compensation_speed: 25

retract_speed: 80
retract_fast_speed: 120
retract_parking_speed: 25
retract_parking_length: 200
intermittent_retract: False
```

其余通信、挤出机、自动探测、材料和无限续料参数也必须从当前生效配置读取，不能仅依赖本文示例。

## 六、通用模板与本机配置的边界

| 项目 | 通用安装模板 | 当前打印机升级 |
| --- | --- | --- |
| ACE 串口 | 使用项目确认的 by-id 路径或由向导确认 | 保留当前路径 |
| 上方/下方传感器 | 注释占位，不预填 | 保留 `^TGL36:PA2`、`^TGL36:PA5` |
| 五通传感器 | 注释占位，不预填 | 保留 `^PC0` |
| 结构距离 | 明确要求实测 | 保留当前实测值 |
| 切刀宏 | 注释示例 | 保留当前实际宏 |
| 换料前后处理 | 无运动安全提示宏 | 保留当前实际宏 |
| 材料档案 | 提供安全默认值 | 保留当前值 |

## 七、迁移验证要求

仅调整注释和顺序时，必须执行以下审计：

1. 迁移前后 `[ace]` 活跃参数键集合完全一致。
2. 当前 79 个参数值逐项一致。
3. `CUT_TIP` 起始的所有宏文本逐字一致。
4. `[save_variables]`、`[respond]` 在活动 include 树中各只有一份。
5. 文件使用 UTF-8 和 Linux LF。
6. 上传前、替换前分别确认打印机不是 `printing` 或 `paused`。
7. 重载后确认 Klipper `ready`、打印机 `standby`、ACE `connected/ready`、Fluidd HTTP 200。
8. 检查启动日志无无效选项、重复节、配置解析错误或 MCU shutdown。
9. 不使用送料、回料、切刀、加热或自动探测作为安装验证动作。
10. 所有远程写入必须遵守项目的变更前和变更后备份规则。

## 八、参数完整性清单

最终 `[ace]` 配置必须包含 79 个活动参数：

- 核心连接：3 个。
- 机器结构：6 个。
- 五通传感器：5 个。
- 送料：9 个。
- 回料：5 个。
- 挤出机与下方传感器：8 个。
- 通信与断联保护：10 个。
- 自动探测料管长度：4 个。
- 烘干上限：1 个。
- 无限续料：3 个。
- 材料档案：25 个。

任何后续新增参数都必须同步更新本清单、详细注释版配置、安装模板和配置布局测试。
