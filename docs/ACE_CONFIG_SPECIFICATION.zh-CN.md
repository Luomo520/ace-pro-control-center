# ACE Pro 管理中心配置文件规范

> 版本：1.3
>
> 适用项目：Ace Pro Control Center
>
> 适用驱动：`extras/ace.py` 1.2.0
>
> 本文规定 `ace.cfg` 的功能分区、五星必填标记、逐项说明格式和验收标准。
> 它是规范文档，不是可以直接复制到打印机的完整配置文件。

### 文档权威层级

1. 根目录 `ace.cfg` 是仓库唯一可安装配置模板，也是发布默认值、活动参数和
   示例材料档案的唯一来源。
2. 本规范只规定结构、语义、依赖、安全边界和维护流程，不复制一套可运行值。
3. `docs/templates/ace-config-section.template.ini` 只供维护者编写新功能区和注释，
   不是安装输入，不得复制为第二份完整配置。
4. `docs/ACE_CONFIG_DETAILED_STYLE_REFERENCE.zh-CN.md` 保留历史设计依据；与本规范
   或根 `ace.cfg` 冲突时，以本规范的治理规则和根 `ace.cfg` 的实际内容为准。

## 1. 功能整体介绍

`ace.cfg` 是 Ace Pro 管理中心在 Klipper 中的唯一主配置文件，负责连接
ACE 四料槽、五通管路、上方和下方耗材传感器、挤出机、切刀宏、烘干机以及
Fluidd/Moonraker 控制接口。

当前功能包括：

- ACE 串口连接、料槽状态读取和耗材名称/温度资料管理。
- 自动换料、手动送料、手动回料、切料以及挤出机到喷嘴的后续送料。
- 上方、下方和可选五通传感器的状态联锁。
- 配置结构版本识别、上下传感器独立消抖和送料/回料绝对硬上限。
- 连续或断续送料、慢速接近、有限打滑补偿、快速回料和停放收尾。
- 使用送料和回料自动探测料管长度并保存结果。
- ACE 断联检测、传感器约束的换料恢复和安全自动继续打印。
- 按 ACE 内耗材类型决定烘干温度，处理 PLA 混装和未知材料提示。
- 无限续料、材料匹配和 Fluidd 卡片/备用页面状态显示。

本配置不替代 `printer.cfg` 的全局 Klipper 配置，不允许前端执行任意 G-code，
也不会自动猜测传感器引脚、切刀坐标或机械距离。

## 2. 文件结构和标记规则

`ace.cfg` 必须保持为一个文件，不拆成多个 ACE 配置文件。推荐顺序为：

1. 顶部说明、五星必填项和耗材路径图。
2. 核心连接。
3. 机器结构和传感器。
4. 送料与打滑补偿。
5. 回料与 ACE 停放。
6. 五通传感器与自动探测料管长度。
7. 挤出机和下方传感器。
8. 通信、断联和恢复保护。
9. 烘干、材料档案和无限续料。
10. 工具宏、切刀宏和换料钩子。

### 2.1 五星标记

`☆☆☆☆☆` 表示必须根据本机实际接线、机械结构或实测路径填写的项目。
五星符号不变，但必须同时标注执行时点：

- `安装 ☆☆☆☆☆`：重启 Klipper 前必须完成。
- `动作 ☆☆☆☆☆`：首次送料、回料、换料、探测或切刀动作前必须完成。
- `条件 ☆☆☆☆☆`：启用对应可选功能前必须完成，功能关闭时保持安全注释或默认值。

通用安装模板不得预填其他用户的真实 MCU 引脚或切刀坐标。未完成安装五星时
不要重启 Klipper；未完成动作或条件五星时不要执行对应机械功能。

只有两个传感器引脚是驱动启动时硬性检查的项目；其他五星项目虽然有代码回退值，
仍必须在首次机械动作前实测，不能把回退值当成已校准值。

配置是否完整不以文档中固定的参数总数判断。参数数量会随功能演进变化，必须
由根 `ace.cfg`、驱动读取项和配置布局测试动态核对。默认保持注释的条件项和
覆盖项只有在取消注释后才属于活动配置。

### 2.2 单位

| 类型 | 单位 | 填写规则 |
| --- | --- | --- |
| 速度 | `mm/s` | 正数；过高可能打滑，过低会延长等待 |
| 距离 | `mm` | 沿实际耗材路径测量，可留少量余量，不得用超大值掩盖打滑 |
| 温度 | `°C` | 烘干温度不能超过 `max_dryer_temperature`；耗材温度为 1 到 500 |
| 时间 | `s` | 正数；过短会误报，过长会延迟故障处理 |

## 3. 耗材路径和传感器关系

```text
送料方向：
[ACE 内部停放点] -> [ACE 出料口] -> [五通前传感器（可选）]
    -> [五通] -> [五通后传感器（可选）] -> [上方传感器]
    -> [挤出机齿轮] -> [下方传感器] -> [喷嘴]

回料方向：
[喷嘴] <- [下方传感器] <- [挤出机齿轮] <- [上方传感器]
    <- [五通后/前传感器] <- [五通] <- [ACE 出料口]
    <- [ACE 内部停放点]
```

五通传感器只允许配置一个：`before_five_way` 表示传感器在五通靠 ACE 一侧，
`after_five_way` 表示传感器在五通靠挤出机一侧。送料时上方传感器先确认耗材
进入挤出机入口，再由挤出机继续送过下方传感器；回料时传感器解除后按
`parking_sensor_clear_move_length` 回到 ACE 停放位置。状态不确定时不得猜测位置。

## 4. 安装前检查和五星项目

主配置中必须已有且只能有一份 `[save_variables]`。`[respond]` 和 `[force_move]`
也是全局配置，驱动只依赖它们，不在 `ace.cfg` 中重复声明。冷态预装载需要：

```ini
[force_move]
enable_force_move: True
```

| 标记 | 参数或宏 | 如何填写 | 不填写的后果 |
| --- | --- | --- | --- |
| 安装 `☆☆☆☆☆` | `serial` | 本机 ACE 的 `/dev/serial/by-id/...` 路径 | ACE 无法连接 |
| 安装 `☆☆☆☆☆` | `extruder_sensor_pin` | 挤出机上方传感器实际 MCU 引脚 | Klipper 启动失败 |
| 安装 `☆☆☆☆☆` | `toolhead_sensor_pin` | 挤出机下方传感器实际 MCU 引脚 | Klipper 启动失败 |
| 动作 `☆☆☆☆☆` | `toolchange_load_length` | ACE 停放点到上方传感器，略加打滑余量 | 送料过短或过度送料 |
| 动作 `☆☆☆☆☆` | `toolchange_retract_length` | 换料时释放公共通道所需回料长度 | 旧料可能未停放 |
| 动作 `☆☆☆☆☆` | `toolhead_sensor_to_nozzle` | 下方传感器到喷嘴的耗材路径 | 耗材可能未到喷嘴 |
| 动作 `☆☆☆☆☆` | `bowden_tube_length` | ACE 出料口到五通进料口的 PTFE 管长 | 探测初始估算不准 |
| 条件 `☆☆☆☆☆` | `parking_sensor_pin` | 有五通传感器才填写实际引脚，没有则保持注释 | 启用功能会启动失败或误判 |
| 条件 `☆☆☆☆☆` | `parking_sensor_position` | 按实际安装位置二选一 | 探测方向和停放点可能错误 |
| 条件 `☆☆☆☆☆` | `parking_sensor_clear_move_length` | 五通传感器解除后到 ACE 停放点的回抽距离 | 停放位置不准 |
| 条件 `☆☆☆☆☆` | `CUT_TIP` 坐标 | 按本机切刀位置、轴范围和机械结构填写 | 不应启用通用示例 |

## 5. 单项注释标准

需要调整或存在物理风险的参数使用：

```ini
# ☆☆☆☆☆ 参数中文名称。
#
# 作用：说明驱动在哪个流程读取它，以及影响哪一段物理动作。
# 单位：mm、mm/s、°C、秒或布尔值。
# 填写：说明测量起点、终点、推荐值和调整方法。
# 依赖：说明依赖的传感器、宏或其他配置。
# 风险：说明过大、过小或配置错误的表现。
#
parameter_name: value
```

安全默认值可以省略填写和风险，但必须保留作用和单位说明。每个参数都应有
自己的条目说明，不能只用一段大段文字代替所有参数。

## 6. `[ace]` 功能分区和参数职责

本节只维护参数职责和分组，不记录发布默认值、当前打印机值或材料温度表。
需要填写或核对数值时必须直接查看根 `ace.cfg`；需要确认解析范围和合法值时
必须同时查看 `extras/ace.py`。代码回退值只用于兼容旧配置，不代替根模板推荐值
或本机实测值；任何文档中的示例值都不能覆盖这两个来源。

### 6.1 核心连接

| 参数 | 职责 |
| --- | --- |
| `serial` | ACE USB 设备路径，必须按本机确认。 |
| `baud` | ACE 串口波特率。 |
| `enable_debug_rpc` | 原始 RPC 调试入口，日常必须关闭。 |
| `ace_config_version` | 配置结构兼容标识；缺失时按旧配置兼容路径加载。 |

### 6.2 送料和打滑补偿

| 参数 | 职责 |
| --- | --- |
| `feed_speed` | 手动送料默认速度。 |
| `feed_fast_speed` | 自动换料快速送料速度。 |
| `feed_approach_speed` | 接近上方传感器时的慢速。 |
| `feed_approach_length` | 送料末段切换慢速的距离。 |
| `intermittent_feed` | 连续与断续送料模式选择。 |
| `feed_fast_chunk_length` | 断续送料快速阶段的单次距离。 |
| `feed_slip_compensation_length` | 正常送料结束后允许的有限补偿距离。 |
| `feed_slip_compensation_chunk` | 断续补偿单次距离。 |
| `feed_slip_compensation_speed` | 打滑补偿速度。 |
| `toolchange_feed_hard_limit` | 正常送料、接近和有限补偿允许达到的绝对总上限。 |

顺序是“快速送料 -> 慢速接近 -> 上方传感器确认 -> 必要时有限补偿”。传感器
已触发时不得继续送满预设距离，补偿不能配置成无限尝试。

### 6.3 回料、停放和机器结构

| 参数 | 职责 |
| --- | --- |
| `retract_speed` | 手动回料默认速度。 |
| `retract_fast_speed` | 自动换料快速回料速度。 |
| `retract_parking_speed` | 停放前慢速收尾速度。 |
| `retract_parking_length` | 回料末段使用慢速的距离。 |
| `intermittent_retract` | 连续与断续回料模式选择。 |
| `toolchange_retract_length` | 换料时释放公共通道的总回料距离。 |
| `toolchange_load_length` | ACE 停放点到上方传感器的最大送料距离。 |
| `toolhead_sensor_to_nozzle` | 下方传感器到喷嘴的路径长度。 |
| `toolchange_retract_hard_limit` | 换料回收及相关恢复路径允许达到的绝对总上限。 |

### 6.4 五通传感器与自动探测料管长度

| 参数 | 职责 |
| --- | --- |
| `bowden_tube_length` | ACE 出料口到五通进料口的 PTFE 管长度。 |
| `five_way_parking_margin` | 无五通传感器时使用的兼容停放余量。 |
| `parking_sensor_pin` | 可选五通公共通道传感器引脚。 |
| `parking_sensor_position` | 五通传感器位于五通前或五通后的二选一位置。 |
| `parking_sensor_clear_move_length` | 传感器解除后继续向 ACE 回抽并形成停放点的距离。 |
| `parking_sensor_debounce_count` | 五通传感器连续确认次数。 |
| `calibration_max_retract_length` | 自动探测搜索传感器解除状态的回抽上限。 |
| `calibration_speed` | 自动探测送料和回抽通用速度。 |
| `calibration_feed_speed` | 可选送料方向覆盖值；注释时继承通用速度。 |
| `calibration_retract_speed` | 可选回抽方向覆盖值；注释时继承通用速度。 |
| `calibration_chunk_length` | 自动探测主体阶段每次移动距离。 |
| `calibration_final_chunk_length` | 自动探测末段每次移动距离。 |

自动探测必须经用户确认后运行。启用五通传感器时显示上方传感器到五通传感器
和停放点的距离；未启用时显示到 ACE 内部停放点的估算。`calibration_*` 只影响
自动探测，不改变普通 T0-T3 换料、手动送料或手动回料。

### 6.5 挤出机和下方传感器

| 参数 | 职责 |
| --- | --- |
| `toolhead_feed_fast_speed` | 上方传感器触发后的快速送料速度。 |
| `toolhead_feed_slow_speed` | 接近下方传感器的慢速。 |
| `toolhead_feed_fast_length` | 工具头快速送料阶段的总距离。 |
| `toolhead_feed_fast_step` | 快速阶段单次移动距离。 |
| `toolhead_feed_slow_step` | 慢速寻找下方传感器的单次距离。 |
| `toolhead_to_nozzle_speed` | 下方传感器触发后到喷嘴的送料速度。 |
| `toolhead_sensor_max_feed_length` | 下方传感器未触发时允许的继续送料上限。 |
| `extruder_sensor_timeout` | 等待工具头送料流程完成的超时时间。 |
| `extruder_sensor_debounce_count` | 上方传感器触发和解除的独立连续确认次数。 |
| `toolhead_sensor_debounce_count` | 下方传感器触发和解除的独立连续确认次数。 |

### 6.6 通信、断联和恢复

| 参数 | 职责 |
| --- | --- |
| `ace_ready_timeout` | ACE 恢复 ready 的最长等待。 |
| `ace_stop_ready_timeout` | ACE 停止送料后的 ready 等待下限。 |
| `ace_request_timeout` | 单个 ACE 请求最长等待。 |
| `sensor_trigger_grace_time` | 理论运动时间结束后的传感器额外监测时间；只延长监测，不追加移动距离。 |
| `ace_reconnect_timeout` | 断联后的重连等待上限。 |
| `ace_reconnect_stable_time` | 重连后稳定等待时间。 |
| `ace_motion_chunk_length` | 需要分段的慢速或兼容动作默认分段距离。 |
| `ace_resume_max_retries` | 单次断联恢复最大重试次数。 |
| `auto_toolchange_recovery` | 是否启用传感器协调的换料恢复。 |
| `auto_toolchange_recovery_max_retries` | 自动换料恢复最大次数。 |
| `auto_resume_after_ace_reconnect` | 安全恢复后是否继续此前暂停的打印。 |

断联后禁止盲目重放未确认的送料、回料、切刀或换料动作；无法确认位置时必须
暂停并报告原因。

### 6.7 烘干、材料档案和无限续料

| 参数 | 职责 |
| --- | --- |
| `max_dryer_temperature` | ACE 烘干安全上限。 |
| `material_N_name` | 槽位显示和材料匹配名称，不区分大小写。 |
| `material_N_drying_temperature` | 材料的 ACE 烘干目标温度。 |
| `material_N_temperature` | 推荐打印温度，不直接控制烘干。 |
| `unknown_material_drying_temperature` | 未知材料的保守烘干温度。 |
| `unknown_material_temperature` | 未知材料打印温度；零表示未知。 |
| `mixed_material_drying_temperature` | PLA 与其他材料混装时保护 PLA 的温度。 |
| `show_material_warning` | 是否显示未知或混合材料警告。 |
| `endless_spool` | 是否启用断料自动备用槽切换。 |
| `endless_spool_require_same_material` | 是否要求备用槽材料名称完全匹配。 |
| `runout_debounce_count` | 断料连续确认次数，只在打印时累计。 |

每个自定义材料的名称、烘干温度和耗材温度必须成组填写。名称不能重复，具体
组数、默认材料和值域以当前驱动解析和根 `ace.cfg` 为准，不在本规范维护副本。

## 7. 宏和首次配置流程

`TR`、`T0`、`T1`、`T2`、`T3` 只调用 `ACE_CHANGE_TOOL`，不复制送料和回料逻辑。
换料前后宏可以提示、清理和暂停，但通用模板不得默认移动 XY/Z、加热、归零
或切料。通用 `CUT_TIP` 必须保持注释，取消前必须填写本机坐标并现场确认安全。

首次配置流程：

1. 备份 `printer_data/config`，确认打印机不在打印或暂停状态。
2. 确认全局节没有重复定义。
3. 填写所有 `☆☆☆☆☆` 项；五通传感器没有安装时保持其引脚注释。
4. 执行 Klipper 配置检查，确认没有缺少传感器、重复节和无效选项。
5. 空闲状态下重启服务，确认 Klipper ready、ACE connected/ready。
6. 先只读检查传感器，再由用户现场确认并手动测试送料、回料和探测。

## 8. 配置验收标准

- `[ace]` 只出现驱动支持的参数，材料字段成组出现。
- 通用模板没有真实传感器引脚和切刀坐标，真机配置与接线一致。
- `parking_sensor_position` 只有 `before_five_way` 或 `after_five_way`。
- 自动探测参数与根 `ace.cfg` 的发布默认值、驱动回退值和界面说明一致。
- 连续/断续送料和回料的语义与界面提示一致。
- 烘干温度不超过最高限制，未知和混合材料提示可见。
- 送料失败会暂停并保留诊断，不会无限补偿或自动取消打印。
- 正常长度、补偿或恢复请求不得绕过送料/回料绝对硬上限；越界停止换料并暂停
  正在打印的任务，不执行 `CANCEL_PRINT`。
- 上下传感器各自使用独立消抖，不能回退为共用五通或断料消抖。
- 缺少新增安全参数的旧配置仍可加载，并使用驱动兼容默认或兼容推导值；模板
  中的显式值仍是新安装和主动迁移时的推荐来源。
- 断联恢复不会盲目重放未确认的物理动作。
- 修改后通过 Python、Web、Fluidd 和安装器测试。

## 9. 配置兼容与已实现安全契约

以下项目已经从保留需求转为正式配置契约：

| 参数 | 已实现行为 | 兼容规则 |
| --- | --- | --- |
| `ace_config_version` | 标识配置结构并为后续迁移提供判断依据 | 旧配置缺失时按兼容版本处理，不因缺键拒绝启动 |
| `extruder_sensor_debounce_count` | 上方传感器独立连续确认 | 旧配置缺失时使用驱动兼容默认值 |
| `toolhead_sensor_debounce_count` | 下方传感器独立连续确认 | 旧配置缺失时使用驱动兼容默认值 |
| `toolchange_feed_hard_limit` | 限制送料、接近和补偿的绝对累计距离 | 旧配置缺失时从现有送料参数采用兼容边界 |
| `toolchange_retract_hard_limit` | 限制回料和相关恢复的绝对累计距离 | 旧配置缺失时从现有回料参数采用兼容边界 |

硬上限是最后安全边界，不替代 `toolchange_load_length`、
`feed_slip_compensation_length`、`toolchange_retract_length` 或自动探测上限。达到
硬上限时驱动停止当前换料，保存失败阶段与传感器诊断；打印中执行或保持
`PAUSE`，不得执行 `CANCEL_PRINT`。旧配置兼容只保证加载和原有行为边界，不表示
旧机器已经完成新参数调校；升级后仍应按根 `ace.cfg` 注释逐项核对。

材料档案的最终决定是保留在同一个 `[ace]` 节内，不创建 `[ace_materials]`。
Klipper 没有对应模块时，新增独立配置节会导致无法加载。材料名称、烘干温度和
推荐打印温度必须三项成组，由驱动作为唯一数据来源提供给 Moonraker 和 Fluidd。

以下内容不能作为新的 `[ace]` 参数：

- 传感器电平反相：继续使用 Klipper 的 `^PIN`、`!PIN`、`^!PIN` 语法。
- 切刀坐标、清洁动作和工具头位置：只属于用户明确配置的宏。
- 用户界面语言和槽位颜色：属于 Fluidd/状态数据。
- 自动跟随烘干的当前开关：属于持久化运行状态，不复制为第二个静态来源。

## 10. 后续配置变更流程

根目录 `ace.cfg` 是唯一可安装模板；
`docs/templates/ace-config-section.template.ini` 是新增功能区和参数说明的编写模板。

任何新增、删除、重命名或改变默认值必须按顺序完成：

1. 在 `extras/ace.py` 中实现读取、类型、范围、依赖和错误提示。
2. 在 `ace.cfg` 对应功能区加入参数，按模板写完整中文说明。
3. 机械相关参数明确单位、测量方式、正常上限、绝对硬上限和失败行为。
4. 更新本规范、驱动指南、安装教程和项目记忆；重大语义变化追加 ADR。
5. 如果参数或其派生状态对外暴露，同步 Moonraker 状态/能力/参数校验、Fluidd
   类型与界面、备用页，并明确哪一层是数据权威来源。
6. 更新配置布局、驱动行为、Web/Fluidd 和安装器测试。
7. 重建 `manifest.sha256`，确认活动参数唯一、模板无真实引脚、宏无默认误动作。

禁止只在 `ace.cfg` 中加入驱动不读取的活动参数，也禁止只改代码默认值而不更新
根模板。规范和其他文档不得复制一整套当前机器值或发布默认值；确需举例时必须
标注为非权威示例。代码回退值和根模板推荐值不同时，只在根 `ace.cfg` 的对应
条目说明差异，并由测试锁定。
