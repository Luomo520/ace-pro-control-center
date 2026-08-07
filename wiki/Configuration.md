# 配置说明

本页说明 Ace Pro Control Center 的第三代配置文件关系、设备字段和首次启用顺序。硬件路径、自动换料宏、多 ACE 五通和编码器的详细操作分别见 [自动换料](Automatic-Toolchange)、[多 ACE](Multi-ACE) 与 [传感器和编码器](Sensors-and-Encoder)。

> **安全原则：** 新安装必须保持 `toolchange_mode: manual`，每台设备必须保持 `physical_actions_enabled: False`。串口、传感器、路径距离和机器宏逐项验证后，才可解除物理动作门禁；自动换料最后启用。

## 唯一运行配置链

V3 只有一条活动配置链：

```text
printer.cfg
    └── include ace.cfg
            ├── [ace_hardware]
            ├── [ace_device ace0] ... [ace_device ace3]
            ├── [ace]
            ├── [ace_machine]
            └── [gcode_macro ...]
```

`printer.cfg` 中只保留这一条 ACE include：

```ini
[include ace.cfg]
```

不要再 include `ace_hardware.cfg` 或 `ace_machine.cfg`。`ace.cfg` 既保存安装器管理的设备拓扑，也保存传感器、距离、动作策略、宏绑定和本机宏。

### 历史测试配置如何处理（新用户跳过）

首个 GitHub 公开版本的用户是全新安装，不会有 `ace_hardware.cfg` 或 `ace_machine.cfg`，无需创建或迁移它们。以下规则只服务于项目当前测试机和内部预发布环境：旧 `ace_hardware.cfg` 不是 V3 的第二个配置文件，只是升级时的一次性迁移输入。安装器会读取其中的设备身份、通信参数和安全开关，合并到 `ace.cfg` 顶部的硬件区域，然后将旧文件归档到配置目录的 `.ace-driver-v3/legacy/`。

- 归档文件只用于追溯和恢复，不能重新 include。
- 不要同时修改旧文件和 `ace.cfg`，运行时只认 `ace.cfg`。
- 如果升级后仍看到活动的旧 include，请重新运行安装器完成迁移，不要手工建立双配置链。

## 先分清三个状态

Wiki 中使用以下词语时含义不同：

| 状态 | 含义 |
| --- | --- |
| 已配置 | 参数已经写入 `ace.cfg`，Klipper 能解析它 |
| 已启用 | 对应开关已经打开，驱动允许该能力参与运行 |
| 已真机验证 | 已在本机按安全顺序完成接线、方向、距离、传感器和故障行为测试 |

“已配置”不等于“已启用”，更不等于“已真机验证”。例如 `physical_actions_enabled: True` 只解除设备动作门禁，不证明切刀坐标、耗材路径或宏已经正确。

## `ace.cfg` 的职责分区

| 区域 | 由谁维护 | 用途 |
| --- | --- | --- |
| `ACE DRIVER V3 HARDWARE TOPOLOGY BEGIN/END` | 安装器 | 设备数量、逻辑顺序、型号、串口、ACE2 总线和 UID |
| `[ace]` | 用户 | 模式、传感器引脚、共享编码器、速度、距离、材料和安全策略 |
| `[ace_machine]` | 用户 | 七个自动换料宏的名称绑定 |
| `[gcode_macro ...]` | 用户 | 与本机机构相符的实际动作实现 |
| 文件末尾用户附加区 | 用户 | 不与 V3 命令冲突的本机扩展 |

增删 ACE、改变 ACE1/ACE2 组合或更换通信身份时，应重新运行安装器。不要取消未启用设备模板的注释，也不要手工拼接不连续的 `ace_device` 节。

## 硬件拓扑区域

### 拓扑总表

```ini
[ace_hardware]
driver_version: 3
device_count: 1
topology_mode: configured
```

| 参数 | 规则 |
| --- | --- |
| `driver_version` | 固定为 `3` |
| `device_count` | `1..4`，必须等于活动 `ace_device` 节的数量 |
| `topology_mode` | 固定为 `configured`，工具编号按配置顺序保持稳定 |

活动设备必须从 `ace0` 开始连续排列。例如两台设备只能是 `ace0`、`ace1`，不能跳到 `ace2`。

### 单台 ACE1 的安全起始配置

以下示例中的串口是占位符，必须替换为本机稳定路径：

```ini
[ace_device ace0]
model: ace1
transport: serial
serial: /dev/serial/by-id/REPLACE_WITH_STABLE_PATH
enabled: True
rfid_enabled: True
physical_actions_enabled: False
```

### 设备字段

| 参数 | 可用值 | 说明 |
| --- | --- | --- |
| `model` | `ace1`、`ace2`、`auto` | 应填写已确认的真实型号；`auto` 未解析时保持离线且禁止物理动作 |
| `transport` | `serial` | 当前固定为串口传输 |
| `serial` | 绝对设备路径 | 优先使用 `/dev/serial/by-id/`，不要依赖会变动的 `/dev/ttyUSB*` 顺序 |
| `bus_id` | ACE2 必填 | 标识 ACE2 所属总线；与 `serial`、`device_uid` 放在同一设备节 |
| `device_uid` | ACE2 必填 | 同一 ACE2 总线上必须唯一；当前不接受 `auto` |
| `enabled` | `True` / `False` | 安装器生成的活动设备为 `True`；删除设备应重跑安装器 |
| `rfid_enabled` | `True` / `False` | 控制驱动是否采纳 RFID 元数据；关闭后仍保留槽位运行状态和手工库存 |
| `physical_actions_enabled` | `True` / `False` | 送料、回料、烘干、辅助送料和换料的单设备动作门禁 |

ACE1 必须独占串口。ACE2 可以在相同 `serial` 和 `bus_id` 下共享总线，但每台必须拥有明确且唯一的 `device_uid`。

> **当前能力边界：** ACE2 在 V3 中仅提供协议模拟与只读状态能力，配置解析会拒绝 ACE2 的 `physical_actions_enabled: True`。多 ACE 两级路径已经完成配置和模拟测试，但尚未完成多机物理动作真机验收。

## `[ace]` 的安全起点

首次安装建议只完成设备连接和状态读取：

```ini
[ace]
driver_version: 3
toolchange_mode: manual

extruder_sensor_pin:
toolhead_sensor_pin:
toolhead_sensor_bypass: True
toolhead_sensor_bypass_load_length: 25
toolhead_sensor_bypass_calibrated: False
upper_sensor_feed_timeout: 30
rdm_sensor_pin:
ace0_hub_sensor_pin:
ace1_hub_sensor_pin:
ace2_hub_sensor_pin:
ace3_hub_sensor_pin:

encoder_sensor_pin:
encoder_resolution: 0
encoder_detection_length: 20
encoder_min_tracking_ratio: 0.6
encoder_mode: off
encoder_print_mode: off

require_path_hooks: True
require_cut_hook: True
```

引脚留空表示未安装或停用对应传感器，不是配置错误。下方传感器不是通用必装项：`toolhead_sensor_bypass` 默认 `True` 时仅监测，用户确认稳定后可显式设为 `False` 恢复闭环。

ACE Pro 使用直流送料电机，`toolchange_load_length` 和 `feed_slip_compensation_length` 只供 ACE 固件参考，不能代表真实耗材位移。ACE 送料以上方传感器稳定触发为唯一成功终点，编码器可判断有无进展，独立最大送料时间负责最终硬停止。上方触发后由挤出机步进电机执行入口到喷嘴的标定距离；`toolhead_sensor_bypass_load_length` 表示这一距离。模板 `25 mm` 只是未校准样板；必须按本机重复测量并把 `toolhead_sensor_bypass_calibrated` 改为 `True`，自动换料才可进入就绪检查。详细流程见[传感器和编码器](Sensors-and-Encoder#上方交接点到喷嘴)。

### 运行模式

| 参数 | 含义 |
| --- | --- |
| `toolchange_mode: manual` | 连接、状态、库存和已授权的手动能力可用；`T0-T15` 与 `TR` 在自动换料未就绪时只提示并忽略，不暂停打印 |
| `toolchange_mode: automatic` | 请求启用自动换料；仍必须通过设备门禁、七宏、传感器、路径状态和多 ACE 分支预检 |

详细启用条件见 [自动换料](Automatic-Toolchange)。

ACE 完全未配置或自动换料未就绪时，每条工具指令都显示包含实际工具号的中文提示并继续打印。此状态只允许只读管理和已经授权的 ACE 内置辅助送料；不要把一般手动送料、回料或多色换料视为可用。

### 高风险速度和距离

模板中的数字只是配置起点，不是本机校准结果。以下参数会直接影响电机动作或耗材停放位置：

| 类别 | 主要参数 |
| --- | --- |
| ACE 送料与回料速度 | `feed_speed`、`retract_speed`、`feed_fast_speed`、`retract_fast_speed` |
| ACE 固件参考量与低速停车 | `feed_slip_compensation_*`、`toolchange_load_length`、`toolchange_retract_length`、`retract_parking_*`；这些值不是 ACE 的真实位移 |
| ACE 送料失效保护 | `upper_sensor_feed_timeout`，默认 `30` 秒，范围 `1..120`；不能由命令参考距离替代 |
| 挤出机接管装载 | `toolhead_sensor_bypass_load_length`、`toolhead_sensor_bypass_calibrated`、`toolhead_feed_*`、`toolhead_to_nozzle_speed`；表示上方交接点到喷嘴的本机标定运动；`protect` 下保证运动距离不得短于 `encoder_detection_length` |
| 打印头卸载 | `toolhead_unload_*`、`ace_unload_step_length` |
| 五通清空 | `rdm_clear_move_length`、`aceN_hub_retract_length`、`aceN_hub_clear_move_length` |

数值过大可能磨料、堵头、拉断耗材、使线盘缠绕，或让挤出机运动超过 `max_extrude_only_distance`。不得用增加补偿距离的方法掩盖堵塞、路径阻力或传感器接线错误。

#### 距离和速度验证顺序

1. 保持 `toolchange_mode: manual`，相关设备保持 `physical_actions_enabled: False`。
2. 断开打印任务，确认打印机待机；手动检查管路通畅、五通方向和耗材停放点。
3. 先验证传感器无料/有料状态，未确认触发电平前不执行电机动作。
4. 记录本机实际测量值，从低速度、短距离开始验证单一送料或回料动作。
5. 每次只改一类参数，检查耗材是否在预期传感器处停止，并保留机械余量。
6. 验证装载、卸载和故障停止后，再逐步提高到目标速度；不要直接使用模板快速速度。
7. 多 ACE 必须逐设备校准分支距离，不能把一个分支的数值复制给另一个分支。
8. 所有动作仍在待机状态通过后，才解除一台 ACE1 的物理动作门禁；自动模式继续保持关闭。

## 其他共享配置

| 参数 | 用途 | 初次使用建议 |
| --- | --- | --- |
| `material_types` | Fluidd 库存编辑中的材料候选列表 | 使用英文逗号分隔，可按实际材料增删 |
| `max_dryer_temperature` | 驱动允许的烘干温度上限 | 不得超过设备、线盘和材料允许范围 |
| `endless_spool` | 无限续料总开关 | 保持 `False`，完成自动换料验证后再启用 |
| `endless_spool_match_mode` | `exact` 或 `material` | `exact` 同时匹配材料和颜色，风险较低 |
| `connection_supervision` | 连接状态监管 | 建议保持 `True` |
| `require_path_hooks` | 强制检查送料、回料路径宏 | 保持 `True` |
| `require_cut_hook` | 强制检查切刀宏 | 必须保持 `True`；V3 不执行尖端成型 |

烘干温度属于高风险配置。验证顺序为：先核对 ACE 型号和材料温度范围，再用低于目标的温度短时待机测试，确认温度反馈与停止命令正常，最后才设置实际温度和时长。打印期间不要用烘干测试代替状态验证。

无限续料会触发自动换料，必须在七个宏、切刀、全部路径传感器和同设备/跨设备换料分别通过后再启用。首次验证应使用废料、空闲打印机和可随时断开的短路径测试，不得直接在长时间打印中验证。

## 修改后的验证顺序

每次修改配置都按以下顺序检查：

1. 备份当前可启动配置，并确认打印机不在打印。
2. 检查 `printer.cfg` 只 include `ace.cfg`，没有活动的旧拆分配置。
3. 检查 `device_count` 与连续的 `ace_device` 数量一致，串口和 ACE2 身份没有重复冲突。
4. 保持 `manual` 和物理动作门禁关闭，先完成 Klipper 配置解析与重启。
5. 执行 `ACE_GET_STATUS`，确认设备数量、型号、连接状态、工具范围和传感器可用性符合实际。
6. 逐个插入、抽出耗材验证传感器，不执行切刀、送料或回料。
7. 按本页及相关硬件页面的顺序验证物理动作。
8. 只有状态、路径和故障停止均符合预期后，才进入 [自动换料](Automatic-Toolchange) 的最终启用步骤。

## 常见配置错误

- 同时 include `ace.cfg` 和旧 `ace_hardware.cfg`。
- `device_count` 与活动设备节数量不同，或设备编号不连续。
- 使用 `/dev/ttyUSB0` 等临时枚举路径后，重启时设备顺序变化。
- 给 ACE2 或 `model: auto` 打开物理动作门禁。
- 把引脚留空误认为错误，进而随意填写其他机器的引脚。
- 直接采用模板距离、速度或注释样板中的机器动作。
- 仅把 `toolchange_mode` 改为 `automatic`，却没有完成七宏和路径预检。
- 通过关闭 `require_cut_hook` 或删除宏绑定绕过安全检查。

下一步：[自动换料](Automatic-Toolchange) | [多 ACE](Multi-ACE) | [传感器和编码器](Sensors-and-Encoder) | [故障排查](Troubleshooting)
