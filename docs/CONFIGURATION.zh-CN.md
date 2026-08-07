# Ace Pro Control Center | ACE Pro 管理中心：第三代配置规范

两级五通配置、解析、分支状态机和界面已完成模拟测试，并随当前候选部署到单 ACE 目标打印机完成只读验证；多 ACE 分支清空和跨设备换料仍未完成真机物理动作验收。本文同时规定可选共享编码器的配置与使用方法；编码器默认关闭，未完成本机接线和人工校准前不得启用保护模式。

## 1. 文件职责

`printer.cfg` 包含：

```ini
[include ace.cfg]
```

| 文件 | 内容 |
| --- | --- |
| `ace.cfg` | 唯一活动配置；包含硬件拓扑、`ace0..ace3`、运行模式、两级五通与共享打印头路径、传感器、共享编码器、每设备分支距离、速度、安全策略、`[ace_machine]` 钩子映射和七个机器动作宏 |
| 旧 `ace_hardware.cfg` | 仅用于升级时的一次性迁移输入；有效设备身份、通信参数和安全开关合并后归档到 `.ace-driver-v3/legacy/`，不得继续 include |
| 旧 `ace_machine.cfg` | 仅用于旧版本迁移的输入文件；机器宏与校准值合并进 `ace.cfg` 后退出运行时 include，新安装不会创建或加载它 |

运行时配置链只有 `printer.cfg -> ace.cfg`，禁止从 `ace.cfg` 或 `printer.cfg` 继续 include `ace_hardware.cfg`、`ace_machine.cfg` 或其归档副本。旧 V2 驱动配置不作为 V3 运行输入。升级旧 V3 配置时，安装器读取一次旧 `ace_hardware.cfg`，将其有效值合并进 `ace.cfg` 后归档到配置目录的 `.ace-driver-v3/legacy/`；安装器也会将旧 `ace_machine.cfg` 中的机器宏和已校准变量迁移为当前七宏名称并移除旧 include。新安装只创建 `ace.cfg`。`saved_variables.cfg` 中的用户库存数据不属于驱动配置；V3 首次启动且尚无 V3 库存时，`ace0` 优先迁移当前 V2 的单机 `ace_inventory`，不存在时才回退 `ace_inventory_0`，其余设备读取 `ace_inventory_1..3`。迁移材料、颜色和温度后只使用 V3 库存。

V3 运行状态不要求配置 `[save_variables]`。存在该配置节时，驱动兼容写入 `ace_v3_*` 变量，并同步保存内部状态；不存在时，驱动使用配置目录下的 `.ace-driver-v3/runtime-state.json` 原子持久化。两种模式都会在首次迁移时安全解析旧 `saved_variables.cfg`，不执行其中的代码，也不删除或覆盖旧变量。

## 2. 硬件配置

`ace.cfg` 顶部的硬件拓扑区域使用与其他功能区相同的 Happy Hare 风格信息层级：长横线功能区、块字符大标题、区块级中文说明和参数行尾短注释。该区域由安装器生成并固定按以下顺序排列：

1. 拓扑总表：`driver_version`、`device_count`、`topology_mode`。
2. 活动设备：按 `ace0..ace3` 连续排列，每台先写型号和通信，再写 RFID 与物理动作开关。
3. ACE2 身份：`serial`、`bus_id`、`device_uid` 保持在同一设备节中并紧邻排列。
4. 设备编号标题：每台设备使用醒目的 `ACE 1..4` 块字符标题，同时标明逻辑编号 `ace0..ace3`、工具范围和启用状态。
5. 未启用设备模板：全部注释且不会被 Klipper 加载；公共字段规则只说明一次，每台占位只保留紧凑配置骨架。
6. 组合规则：明确 ACE1 独占串口、ACE2 共享总线和 UID 唯一性要求。

`hardware_config.py reformat` 只改变 `ace.cfg` 内硬件拓扑区域的排版，必须保留活动设备的逻辑顺序、型号、串口、ACE2 身份、
`enabled`、`rfid_enabled` 和 `physical_actions_enabled`。任何活动值发生变化都视为迁移失败。

重新运行安装器时，`enabled`、`rfid_enabled` 和 `physical_actions_enabled` 按稳定硬件身份继承，即使设备在 `ace0..ace3` 中换序也不能串位。新设备或替换设备使用本次安装参数，不能继承被移除设备的启用状态或物理动作授权。

```ini
[ace_hardware]
driver_version: 3
device_count: 2
topology_mode: configured

[ace_device ace0]
model: ace1
transport: serial
serial: /dev/serial/by-id/usb-ANYCUBIC_ACE_1-if00
enabled: True
physical_actions_enabled: False
rfid_enabled: True

[ace_device ace1]
model: ace2
transport: serial
serial: /dev/serial/by-id/REPLACE_ACE_2-if00
bus_id: ace2bus0
device_uid: 1:2:3
enabled: True
physical_actions_enabled: False
rfid_enabled: True
```

规则：

- `device_count` 只能是 `1..4`。
- 设备节名必须连续为 `ace0`、`ace1`、`ace2`、`ace3`。
- `model` 只能是 `ace1`、`ace2` 或 `auto`。
- `serial` 优先使用 `/dev/serial/by-id/` 稳定路径。
- ACE1 每台必须拥有独立串口；ACE2 允许同一 `bus_id` 共享串口。
- 同一串口只有在明确声明为 ACE2 共享总线时才允许重复。
- ACE2 必须填写明确的 `device_uid`；在自动发现结果能够安全持久化前，`device_uid: auto` 会在配置阶段拒绝。
- `topology_mode: configured` 为默认值，重启后不改变逻辑编号。
- USB 拓扑可用于显示和校验，但不得根据枚举顺序重排 `ace0`。
- `auto` 无法确认型号时保持离线和物理动作禁用，不得猜测协议。
- `rfid_enabled` 属于单台设备，默认为 `True`；多 ACE 可以分别开启或关闭。
- `rfid_enabled: False` 时，驱动不使用硬件返回的 RFID 材料、颜色、温度、SKU 或卷料编号覆盖手工库存。该选项控制驱动采纳和显示策略，不能阻止设备固件继续上报 RFID 状态。
- RFID 开启但槽位返回“无资料”或“识别失败”时，界面统一显示“已关闭”；只有协议明确返回“已识别”或“识别中”时才显示相应状态。

## 3. 共享驱动配置

单 ACE 使用 1 个总五通，四槽直接汇入总五通，不需要一级五通。安装第 2 台 ACE 后才启用两级汇流：2/3/4 台分别使用 2/3/4 个一级五通，再共同进入 1 个总五通，总数为 3/4/5 个。ACE 设备内部自行完成张力调节，用户不需要也不能在 V3 中配置独立缓冲器。

```ini
[ace]
driver_version: 3
toolchange_mode: manual

# 上方传感器：只填真实引脚；留空表示禁用
extruder_sensor_pin:
extruder_sensor_debounce_count: 2

# 下方传感器：非必装；默认仅监测，验证稳定后可显式恢复闭环
toolhead_sensor_pin:
toolhead_sensor_debounce_count: 2
toolhead_sensor_bypass: True
toolhead_sensor_bypass_load_length: 25
toolhead_sensor_bypass_calibrated: False
upper_sensor_feed_timeout: 30

# 总五通传感器：旧配置键前缀 rdm_* 继续兼容
rdm_sensor_pin:
rdm_sensor_debounce_count: 3

# 以下一级五通与分支距离仅供 2 至 4 台 ACE 使用；单 ACE 全部留空
# ACE0 一级五通传感器（多 ACE 可选）与分支距离
ace0_hub_sensor_pin:
# ace0_hub_retract_length: <实测毫米>
# ace0_hub_clear_move_length: <实测毫米>

# ACE1 一级五通传感器（多 ACE 可选）与分支距离
ace1_hub_sensor_pin:
# ace1_hub_retract_length: <实测毫米>
# ace1_hub_clear_move_length: <实测毫米>

# ACE2 一级五通传感器（多 ACE 可选）与分支距离
ace2_hub_sensor_pin:
# ace2_hub_retract_length: <实测毫米>
# ace2_hub_clear_move_length: <实测毫米>

# ACE3 一级五通传感器（多 ACE 可选）与分支距离
ace3_hub_sensor_pin:
# ace3_hub_retract_length: <实测毫米>
# ace3_hub_clear_move_length: <实测毫米>

# 最多四个一级五通共用，不能代替总五通去抖值
ace_hub_sensor_debounce_count: 3

# 共享编码器：只填脉冲引脚；未安装时留空并保持 off
encoder_sensor_pin:
encoder_resolution: 0
encoder_detection_length: 20
encoder_min_tracking_ratio: 0.6
encoder_mode: off
encoder_print_mode: off
encoder_print_detection_length: 20

feed_speed: 80
feed_fast_speed: 160
feed_slip_compensation_length: 400
feed_slip_compensation_speed: 25
retract_speed: 80
retract_fast_speed: 120
retract_parking_speed: 25
retract_parking_length: 200
toolchange_load_length: 630
toolchange_retract_length: 150
bowden_tube_length: 1000
material_types: PLA, PLA+, PETG, PETG-CF, PETCF, ABS, ABSCF, ASA, TPU, PA, PA-CF, PAHTCF, PET-CF, PC, PBT-CF, PEEK, PVA, HIPS
max_dryer_temperature: 55
endless_spool: False
endless_spool_match_mode: exact
connection_supervision: True
require_path_hooks: True
require_cut_hook: True
```

共享打印头距离和速度只配置一次。单 ACE 不配置一级五通；多 ACE 才按 `ace0..ace3` 分别配置实际设备的一级五通传感器和分支清空距离，不能在设备之间默认复制。

`rdm_sensor_pin` 和 `rdm_sensor_debounce_count` 共同配置总五通传感器，所有用户文本统一称“总五通传感器”。最多四个一级五通共同使用 `ace_hub_sensor_debounce_count`。两个去抖字段分别生效，不能互换，也不能用其中一个同时控制两级传感器。

旧配置中的 `extruder_sensor_name`、`toolhead_sensor_name`、`rdm_sensor_name`、`aceN_hub_sensor_name` 和 `encoder_sensor_name` 仅用于运行与升级兼容，兼容路径可以继续识别已有显式对象名。新模板、安装说明和用户填写步骤不得展示或要求这些字段；新配置的固定内部名称及去重由驱动负责。

### 3.1 上方传感器交接与可选下方传感器

ACE Pro 使用直流送料电机。不同耗材的摩擦力、卷盘阻力、压轮状态和管路阻力会改变电机转速，因此 ACE 命令中的“距离”不能代表真实耗材位移：

| 项目 | 配置语义 |
| --- | --- |
| `extruder_sensor_pin` | 上方传感器引脚；自动换料必须以它的稳定触发作为 ACE 送料成功终点 |
| `extruder_sensor_debounce_count` | 上方传感器稳定确认次数；不能用极大值掩盖抖动或接线问题 |
| `toolchange_load_length` | ACE 固件主送料请求的参考量，不是从停放点到上方传感器的实测距离 |
| `feed_slip_compensation_length` | ACE 固件附加请求的参考量，不是实际打滑毫米数，也不是成功判据 |
| `toolhead_sensor_bypass` | 默认 `True`：下方传感器仅监测；用户确认稳定后可显式设 `False`，恢复下方闭环 |
| `toolhead_sensor_bypass_load_length` | 兼容期沿用的键名；只表示上方传感器稳定触发后，由挤出机步进电机执行的入口到喷嘴标定距离；配置范围 `0..250 mm` |
| `toolhead_sensor_bypass_calibrated` | 默认 `False`；入口到喷嘴距离完成重复实测和低速复核后改为 `True`，否则自动换料保持未就绪 |
| `upper_sensor_feed_timeout` | 默认 `30` 秒，有效范围 `1..120`；达到时间仍未触发上方传感器时强制停止 |
| `toolhead_sensor_pin` | 可选下方传感器引脚；默认旁路时可留空，关闭旁路恢复闭环前必须配置并验证 |

装载顺序固定为：

1. ACE 以约两秒的受限窗口分段送料，驱动在每段前后检查上方传感器；主参考量和低速参考量耗尽后仍低速分段至总超时，达到任意命令参考距离都不代表成功。
2. 有共享编码器时检查是否仍有实际耗材运动。`monitor` 无进展只提示，`protect` 无进展中止；没有编码器时仍可依靠上方传感器和最大送料时间运行。
3. 上方传感器稳定触发后立即停止 ACE，把控制权交给挤出机步进电机。
4. 挤出机执行已标定的上方交接点到喷嘴距离；编码器存在时再次验证实际移动。只有该段完成且没有 `protect` 故障，路径才能标记为已装载。

`toolhead_sensor_bypass_load_length` 默认样板 `25 mm` 不是通用结果。打印机待机并按耗材要求加热后，让耗材停在上方传感器刚稳定触发的位置，以低速小步长送到本机定义的喷嘴目标位置；完整卸载后至少重复三次，再填写可重复值并把 `toolhead_sensor_bypass_calibrated` 改为 `True`。这里的距离由挤出机步进电机执行，因此可以用于定距；它与 ACE 固件参考量必须分开校准和显示。数值为 `0`、确认开关为 `False` 或数值超限时，自动换料保持未就绪；`250 mm` 只是解析硬上限，不是建议值。

`toolhead_sensor_bypass: True` 是默认值。此时 `toolhead_sensor_pin` 留空不创建对象；填写真实引脚时驱动和界面继续显示原始有料/无料，但装载、卸载、路径就绪、空路径确认和故障原因不要求它触发或释放。用户完成引脚、电平、去抖、搜索距离和完整装卸验证后，可显式设置 `toolhead_sensor_bypass: False` 恢复下方闭环；关闭旁路后，下方传感器及闭环距离成为该模式的就绪条件。下方传感器始终不是通用安装必需项。

卸载先由挤出机受限回抽，直到上方传感器稳定释放；编码器可以验证耗材是否真实后退。上方释放后才由 ACE 回抽，先确认总五通释放，再按多 ACE 拓扑确认当前一级五通释放并执行停车余量；没有一级传感器时只允许使用已经校准的受限盲回退方案。ACE 回抽参考距离同样不能显示为真实位移，下方传感器不参与卸载终点。

多 ACE 中每个已安装且允许物理动作的 `aceN` 都要校准两项距离；单 ACE 不读取以下字段：

- `aceN_hub_retract_length`：总五通传感器释放后，继续寻找本设备一级五通传感器释放的最大回抽距离；未安装一级传感器时，这一段改为受限盲回退。
- `aceN_hub_clear_move_length`：一级五通传感器释放后的停车余量；未安装一级传感器时，与上一项相加，形成总五通释放后的受限盲回退总量。

模板不提供通用距离，未实测前保持注释。多 ACE 自动换料要求总五通传感器有效，并且每台动作型 ACE 具备“一级五通传感器 + 两项距离”或“无一级传感器 + 两项实测盲回退距离”的分支清空方案。距离缺失、搜索超限或传感器状态矛盾只使自动换料保持“尚未就绪”或进入人工检查，不影响 Klipper 启动、设备连接和只读状态。

### 3.2 共享编码器

V3 只配置一个共享编码器。它直接安装在总五通之后、上方传感器之前的公共路径，使四台 ACE 的耗材经过同一个测量点。编码器测量“耗材是否真的移动”，上方传感器确定“ACE 与挤出机的交接位置”，两类信号互补但不能互相替代。下方传感器不是必要节点。ACE 自身的张力调节和缓冲结构不进入外部路径拓扑，也没有对应的 V3 配置项；不得把它套用为 Happy Hare/AFC 的外置缓冲或压缩传感器。

| 参数 | 默认值 | 说明 |
| --- | --- | --- |
| `encoder_sensor_pin` | 空 | 脉冲输入引脚；留空表示禁用，有值时由驱动以固定内部名称创建共享编码器 |
| `encoder_resolution` | `0` | 每个脉冲对应的毫米数；`0` 表示尚未校准，必须为有限非负数 |
| `encoder_detection_length` | `20` | ACE 每个受限窗口都检查零脉冲，达到该值的长窗口要求至少两个有效脉冲；挤出机段以它作为跟随率检测下限，`protect` 要求保证运动距离不小于该值；不能解释为 ACE 的真实位移 |
| `encoder_min_tracking_ratio` | `0.6` | 编码器最低允许跟随比例，有效范围 `0.01..1`；`monitor` 只记录，`protect` 低于阈值时中止 |
| `encoder_mode` | `off` | `off`、`monitor` 或 `protect` |
| `encoder_print_mode` | `off` | 打印中连续监测：`off`、`monitor` 或 `pause` |
| `encoder_print_detection_length` | `20` | 打印净挤出达到该值仍没有新脉冲时报告故障，必须为有限正数，单位为毫米 |

三种模式的边界如下：

- `off`：不参与动作判断，适合未安装、未接线或尚未校准的机器。
- `monitor`：在 ACE 寻找上方传感器和挤出机接管两个阶段记录脉冲、测量距离和跟随比例；无进展只提示，不改变动作结果。
- `protect`：检测窗口内没有足够脉冲时中止当前阶段并要求检查路径。挤出机接管段发生保护故障时不得把路径标记为已装载；编码器不可用或未校准时，自动换料保持“尚未就绪”。

编码器不执行无上限自动补料，不会因测量距离不足而把 ACE 命令距离当作真实欠料量，也不参与判断槽位、一级五通或总五通是否有料。没有下方传感器时，挤出机已执行送料而编码器无位移，可提示耗材可能卡在上方传感器附近、未进入挤出齿轮或齿轮打滑；这仍是排查范围，不是对具体故障的自动定论。

打印监测与 ACE 动作监测相互独立。`encoder_print_mode: monitor` 只记录故障并提示，`pause` 还会通过 `pause_on_error_macro` 请求一次暂停；同一次无脉冲故障不会重复暂停。监测只在打印状态为 `printing`、路径已有装载工具、共享路径没有换料事务且编码器不在校准时启用。驱动读取挤出机物理位置并按净挤出累计，回抽及其恢复不会被误计为新的耗材消耗。编码器出现新脉冲后重新获得完整检测余量。

未配置编码器、尚未收到计数器采样或无法读取挤出机物理位置时，打印监测显示不可用并静默停用，不阻止 Klipper 启动或普通打印。打印监测只判断是否出现新脉冲，因此不依赖毫米/脉冲分辨率；人工校准仍用于 ACE 动作距离测量和确认编码器工作是否正常。故障现场包含当前工具、设备、路径状态、打印状态与传感器快照；“可能原因”只用于人工排查，不是自动诊断结论。

人工校准使用三段会话，过程中不会驱动 ACE 或挤出机：

1. 确认打印机待机、当前耗材已经卸载、共享路径状态为 `empty` 且辅助送料关闭，执行 `ACE_ENCODER_CALIBRATE START=1`。默认共 `3` 段，每段目标 `150 mm`。
2. 手动准确移动第一段后执行 `ACE_ENCODER_CALIBRATE LENGTH=150`，随后按控制台提示重复第二、第三段。`LENGTH` 填每段真实移动值，必须是 `0.01..2000 mm` 的有限数值。
3. 三段完成后驱动比较各段 `mm/脉冲`：最大偏差 `<=5%` 通过，`>5%` 且 `<=10%` 警告后保存，`>10%` 或任一段脉冲不足拒绝保存，且不覆盖上一次有效结果。

从 `START=1` 到 `LENGTH=...` 完成之前，状态显示“校准中”。驱动在此期间拒绝新的 ACE 运动、辅助送料启用和自动换料，避免其他动作的脉冲混入校准结果；停用已经开启的辅助送料仍然允许。执行 `ACE_ENCODER_CALIBRATE CANCEL=1` 可放弃本次校准且不会驱动电机。`START`、`LENGTH`、`CANCEL` 每次必须且只能填写一项，三者在打印中全部拒绝；`NaN`、`Infinity` 及超出范围的长度不会写入运行状态。

可用 `ACE_ENCODER_STATUS` 查看脉冲、三段进度、分辨率、偏差、动作监测、打印监测和最近故障。Fluidd 完整页提供开始、逐段记录、完成与取消的向导；该向导不会移动 ACE 或挤出机。第一次安装应保持两种模式均为 `off`；确认方向、脉冲稳定性和三段校准结果后先使用 `monitor`，完成本机验证后再考虑 `protect` 或 `pause`。

`material_types` 使用英文逗号分隔，决定 Fluidd 卡片和独立控制页面的耗材候选项及排列顺序。用户可以增删或重新排序，最多 32 项；不得填写空项、大小写重复项、控制字符或超过 32 字符的单项。该列表用于提高录入效率，不会覆盖已经保存的槽位材料；库存编辑仍允许录入列表外的临时自定义材料。

机器钩子名称保存在共享配置中：

```ini
[ace_machine]
pre_toolchange_macro: _ace_prepare_toolchange                    # !!!【换料前处理｜必用】
cut_macro: _ace_cut_filament                                    # !!!【切刀｜必用】
load_to_toolhead_macro: _ace_load_filament_to_toolhead          # !!!【送料｜必用】
unload_from_toolhead_macro: _ace_unload_filament_from_toolhead  # !!!【回料｜必用】
wipe_nozzle_macro: _ace_wipe_nozzle                              # !!!【擦嘴｜必用】
post_toolchange_macro: _ace_restore_after_toolchange             # !!!【换料后处理｜必用】
pause_on_error_macro: _ace_pause_on_toolchange_error             # !!!【故障暂停｜必用】
```

V3 不使用尖端成型。自动换料固定要求换料前处理、切刀、送料、回料、擦嘴、换料后处理和故障暂停七项能力，七个名称绑定全部默认启用。缺少任一绑定或同名实现时，自动换料保持“尚未就绪”。

`ace.cfg` 中的 `!!!【必用】` 是七个必用宏的统一醒目标记，表示自动换料缺少该能力就不可用。`!!!` 本身是给用户看的注释，不代替驱动的绑定检查、宏注册检查或就绪预检。

这里的“绑定启用”只表示驱动知道要调用哪个宏名，不会执行样板里的坐标。真实动作由同名 `[gcode_macro ...]` 实现决定：默认模板中的换料前处理、切刀、擦嘴和换料后处理实现整段保持注释，用户核对本机坐标、方向、速度、归零条件和安全间隙后才能分别取消注释。任一实现仍被注释时，Klipper、手动模式和已授权的 ACE 内置辅助送料可以正常使用，但自动换料预检不会通过；不得通过关闭安全要求或删除任一绑定绕过预检。

`pre_toolchange_macro`、`wipe_nozzle_macro`、`post_toolchange_macro` 和 `pause_on_error_macro` 接收 `FROM`、`TO`；切刀、装载和卸载宏接收 `TOOL`、`DEVICE`、`SLOT`。`ace.cfg` 中的装载/卸载宏只是受控入口：上方传感器稳定确认、ACE 停止、控制权交接、挤出机定距、编码器验证和受限回抽由 V3 Python 路径控制器执行，不能改回普通 Jinja 循环。旁路为 `True` 时下方只上报原始状态；显式设为 `False` 后恢复参与闭环动作和故障结论。

默认旁路模式的目标顺序是：换料前停车与升温；执行经过本机验证的切刀；挤出机受限回抽直到上方传感器稳定释放；再由 ACE 依靠总五通、当前一级五通或已校准受限盲回退方案停车；新料由 ACE 寻找上方传感器，上方稳定触发后立即停止 ACE；挤出机按入口到喷嘴标定距离接管；最后清洁并恢复位置。编码器可在 ACE 和挤出机两个阶段验证真实移动，`monitor` 只提示，`protect` 中止。关闭旁路恢复下方闭环后，路径控制器改用闭环装卸分支。`CUT` 宏本身不再包含 `FORCE_MOVE -50`，避免与卸载阶段重复回抽。

旧 V2 `ace.cfg` 中有价值的宏按下表作为 V3 设计迁移来源；这里迁移的是行为和本机实测变量，不保留会与驱动冲突的旧入口。当前安装器不会自动解析或合并真正的 V2 `ace.cfg`：检测到非 V3 `ace.cfg` 时会失败关闭，用户必须先备份并卸载 V2，再把已经确认的本机坐标和动作逻辑人工迁入 V3：

| V2 宏 | V3 归属 | 迁移结果 |
| --- | --- | --- |
| `_ACE_PRE_TOOLCHANGE` | `_ace_prepare_toolchange` | 保留归零检查、保存位置、抬 Z、停车和最低升温；迁移后仍需核对坐标 |
| `CUT_TIP` | `_ace_cut_filament` | 保留本机切刀坐标与两次切刀往复；删除 `FORCE_MOVE -50`，避免重复卸载 |
| `_ACE_POST_TOOLCHANGE` | `_ace_wipe_nozzle`、`_ace_restore_after_toolchange` | 拆分喷嘴清理和位置恢复，按实际抬升量恢复 Z |
| `_ACE_ON_EMPTY_ERROR` | `_ace_pause_on_toolchange_error` | 使用 `print_stats` 判断，仅暂停活动打印并保留明确错误提示 |
| `T0..T3`、`TR` | V3 Klipper 命令注册器 | 不生成同名宏；固定注册 `T0..T15` 和 `TR` |

通用发布模板默认启用七个名称绑定，但换料前处理、切刀、擦嘴和换料后处理的物理实现仍是整段注释的 V2 实机样板。用户必须按本机重新验证，不能直接取消样板注释；实现缺失只使自动换料未就绪，不阻止 Klipper、手动模式或已授权的 ACE 内置辅助送料。安装器会自动合并两类早期 V3 拆分文件：旧 `ace_hardware.cfg` 只迁移设备身份、通信参数和安全开关；旧 `ace_machine.cfg` 保留已经验证的 `park_x/park_y`、切刀坐标、最低温度、喷嘴清洁开关和自定义机器宏内容。两类值都写入 `ace.cfg`，原拆分文件随后退出运行链并归档。该流程不适用于 V2 `ace.cfg`。

`require_path_hooks: True` 时缺少送料或回料宏会在 ACE 动作前失败关闭，`require_cut_hook: True` 强制切刀要求；自动换料就绪检查还必须确认换料前处理、擦嘴、换料后处理和故障暂停实现存在。七项缺少任一项都只关闭自动换料，不阻止 Klipper、手动模式、只读状态或已授权的 ACE 内置辅助送料。目标槽空、传感器顺序矛盾或路径状态未知时，旧料不会先被切断。

## 4. 工具编号

每台设备固定四槽，按配置顺序线性映射：

| 设备 | 槽位 | 工具 |
| --- | --- | --- |
| `ace0` | 槽1..槽4 | `T0..T3` |
| `ace1` | 槽1..槽4 | `T4..T7` |
| `ace2` | 槽1..槽4 | `T8..T11` |
| `ace3` | 槽1..槽4 | `T12..T15` |

界面显示“槽1..槽4”，驱动内部使用本地索引 `0..3`。设备断线、型号改变或 USB 重枚举不得改变上述映射。驱动固定注册 `T0..T15`：自动换料未就绪时全部提示后忽略；自动换料就绪后，超出 `device_count` 的目标会作为未配置工具拒绝。

主命令：

```gcode
ACE_CHANGE_TOOL TOOL=T5
```

`TR` 表示卸载当前工具。底层可以兼容 `TOOL=-1`，但界面和用户文档使用 `TR`。

## 5. 安装器生成规则

首次安装询问设备数量、型号和稳定串口，生成唯一活动配置 `ace.cfg`。该文件依次包含安装器托管的硬件拓扑、共享参数、`[ace_machine]` 映射和七宏结构；新安装不创建 `ace_hardware.cfg` 或 `ace_machine.cfg`。以后重装或增删设备时，安装器只重建 `ace.cfg` 中的硬件拓扑区域，保留路径参数、共享编码器参数、机器宏校准值、自定义材料和未知扩展项，同时补齐新版本配置项、钩子名称和 V3 内部路径桥接宏。

若检测到旧 `ace_hardware.cfg`，安装器只读取一次，按稳定硬件身份迁移设备开关和通信身份，成功后将原文件移入配置目录的 `.ace-driver-v3/legacy/`；若检测到旧 `ace_machine.cfg`，安装器将其作为迁移输入合并到 `ace.cfg`，成功后退出运行时 include。未选择的设备只在 `ace.cfg` 的安装器托管区域保留注释模板。增删 ACE、替换型号或改变 ACE1/ACE2 组合必须重新运行安装器，不支持手工复制活动设备节。安装器不得自动执行送丝、回抽、切刀、加热、换料或服务重启。

安装器会递归检查 `printer.cfg` 的有效 include，发现现有 `TR` 或 `T0..T15` 宏时中止，避免 Klipper 因重复命令无法启动。旧 V2 `ace.py`、Moonraker 组件和非 V3 `ace.cfg` 也必须先备份并卸载。

物理命令超时不会自动重发。此时设备进入 `physical_state_unknown`，后续物理动作保持禁用，直到用户检查路径后显式执行恢复。送料和回抽事务必须等待设备重新报告 ready 才释放共享路径锁。

## 6. 配置书写规范

V3 的唯一活动配置 `ace.cfg` 采用类似 Happy Hare `mmu_parameters.cfg` 的信息层级：长横线功能区、块字符大标题、区块级说明和参数行尾短注释。共享编码器、入口归位与入口到喷嘴定距参考 Happy Hare 固定提交 `73d39aab2110deebb64dfb7899c6838a706edcea`，只有入口传感器且工具端传感器可为空的职责划分参考 AFC 固定提交 `a06f14dd5b2aa5e2878f92cef7a07f1e8b1fd5a3`；只借鉴设计经验，不复制上游代码，不引入 selector、gear stepper、MMU toolhead、自动补偿、Spoolman、MMU 恢复、外置缓冲器、打印机引脚或机器动作值，也不继承 V2 的单设备硬件假设。

### 6.1 配置所有权唯一

- `ace.cfg` 是唯一正在运行的 ACE 配置，包含硬件拓扑、设备通信与安全开关、单 ACE 单级路径、多 ACE 两级路径与分支距离、可选共享编码器、`[ace_machine]` 和七个必用绑定。
- `docs/templates/` 只用于维护者编写新功能区，不是第二份可运行配置。
- `ace.cfg` 中的硬件拓扑区域由安装器管理；运行安装器时只重写该区域，不覆盖用户已经测量的共享路径参数、机器宏和未知扩展项。
- 旧 `ace_hardware.cfg` 和 `ace_machine.cfg` 都不属于新安装的运行配置，只能在升级时读取一次。旧硬件文件迁移完成后归档到 `.ace-driver-v3/legacy/`；任何迁移文件或归档都不得再次被 Klipper 加载。
- 活动参数必须只有一份；设备节不能复制共享打印头参数。

### 6.2 功能分区顺序

`ace.cfg` 按以下顺序书写和维护：

1. 文件说明、版本和安全边界。
2. 安装器托管硬件拓扑：拓扑总表、活动设备、未启用模板和组合规则。
3. 共享打印头传感器：先写作为交接依据的上方传感器，再写默认旁路、可选闭环的下方传感器和总五通；总五通紧邻 `rdm_sensor_debounce_count`。
4. 多 ACE 设备分支：按 `ace0..ace3` 连续排列一级五通引脚，再写共用去抖值；单 ACE 保持全部为空。
5. 共享编码器：引脚、分辨率、检测距离和模式。
6. 送料、回料、共享路径距离及每台 ACE 的分支搜索上限和停车余量。
7. 通信、断联和机器动作安全门禁。
8. 用户可配置的耗材种类、烘干和无限续料。
9. 机器动作宏名称与实现。
10. 驱动拥有的 `TR`、`T0-T15` 说明。

每个功能区集中说明用途、单位、填写方法、依赖、互斥关系、风险和失败行为；每个活动参数行尾必须保留
简短中文说明。这样既保留必要信息，又避免为每个参数重复四行相同结构。安装器升级现有配置时，以新版模板
重新排版并保留所有实测值、自定义材料和未知扩展项，同时恢复模板的行尾说明。

`ace.cfg` 中安装器托管硬件区域的大区顺序固定为“拓扑总表 -> 活动设备 -> 未启用模板 -> 组合规则”。每个活动设备内部
固定为“型号 -> 传输 -> 稳定串口 -> ACE2 总线/UID（仅 ACE2）-> 启用 -> RFID -> 物理动作”，便于用户在
同一区域完成一台设备的全部核对，不需要跨区查找相关字段。

### 6.3 五星必填标记

`☆☆☆☆☆` 表示必须由用户根据实际设备确认的项目，并标明执行时点：

- `安装 ☆☆☆☆☆`：重启 Klipper 前完成。
- `动作 ☆☆☆☆☆`：首次送料、回料、换料或校准前完成。
- `条件 ☆☆☆☆☆`：启用可选传感器、切刀或烘干能力前完成。

通用 V3 模板不得填入任何打印机真实引脚、坐标或路径测量值。未确认的项目保持
注释或安全禁用；示例值不能被当作已校准值。

### 6.4 V2 内容在 V3 中的处理

| V2 写法 | V3 处理 |
| --- | --- |
| `[ace]` 中的共享送料、回料、传感器和材料参数 | 保留，按通用 Klipper 名称和能力模型重写 |
| `serial`、型号、设备数量 | 移到 `ace.cfg` 的安装器托管硬件区域，按 `ace0..ace3` 分节 |
| 旧模板中的 `toolhead: S1` | 剔除；传感器可引用现有对象，也可由本机真实 pin 动态创建 |
| 已在本机验证的 `CUT_TIP`、PRE/POST/错误宏 | 迁移到 `ace.cfg` 的七个清晰名称；七个绑定统一启用，物理实现保留原校准与注释状态，固定 `FORCE_MOVE -50` 被移除 |
| V2 传感器送料与交替回抽循环 | 迁移到 V3 Python 路径控制器，宏只保留本机动作入口 |
| V2 旧驱动参数兼容读取 | V3 不作为运行输入；如需提示，只由安装器生成迁移建议 |
| `ace_inventory` / `ace_inventory_0..3` 用户库存 | 仅在没有 V3 库存时一次性导入 `ace_v3_inventory`；`ace0` 优先当前 V2 单机键，不删除旧变量，不重复覆盖用户后续修改 |
| V3 运行状态 | 有 `[save_variables]` 时兼容写入 `ace_v3_*`；无该配置节时使用 `.ace-driver-v3/runtime-state.json`，无需用户额外配置 |
| V2 单机 `T0-T3` | 保留语义并扩展为配置顺序的 `T0-T15` |

单 ACE 没有配置 `rdm_sensor_pin` 时，可以依据 `toolchange_retract_length` 完成盲回抽；该值必须按本机实测。多 ACE 两级拓扑不能用这一距离清空所有分支：每个设备分支必须使用自己的 `aceN_hub_retract_length` 和 `aceN_hub_clear_move_length`。

## 7. 手动模式与换料安全契约

本节描述当前 V3 运行契约；配置解析、安装器、升级器、Moonraker 和前端必须共同遵守。

### 7.1 手动模式与物理动作门禁

```ini
[ace]
toolchange_mode: manual
```

`toolchange_mode: manual` 是全新安装默认值。ACE 可以连接并读取状态、传感器、RFID 和库存；停车坐标、切刀坐标、擦嘴宏、路径传感器或换料距离没有填写时，Klipper 仍正常启动，界面显示“手动模式”，不显示设备故障。自动换料、无限续料和自动切刀不启动。

`toolchange_mode: automatic` 仅表示用户要求使用自动换料。驱动仍需进行就绪预检：上方传感器必须可读取，入口到喷嘴的挤出机距离必须完成本机标定，`upper_sensor_feed_timeout` 必须位于 `1..120` 秒；默认 `toolhead_sensor_bypass: True` 时下方传感器不是就绪条件，显式设为 `False` 后必须验证下方闭环配置。多 ACE 时还要逐台验证总五通和一级分支清空方案，`encoder_mode: protect` 时还必须确认共享编码器可用、已校准、`encoder_min_tracking_ratio` 有效，并保证挤出机验证距离不短于 `encoder_detection_length`。配置不完整时只把换料能力标记为“尚未就绪”，不阻止 Klipper 和 ACE 状态读取，也不得开始部分换料动作。

全新 ACE1 在 `ace.cfg` 的设备节中默认使用：

```ini
physical_actions_enabled: False
```

该值为 `False` 时只允许连接、状态、RFID 和库存功能，送料、回料、烘干、校准和 ACE 内置辅助送料全部禁用。用户完成设备检查后可以改为 `True`；即使仍处于手动模式，也可以单独使用手动送料、手动回料、烘干和 ACE 内置辅助送料。升级或重装必须按稳定硬件身份保留用户已有的 `True` 或 `False`，不得恢复为安装器默认值。单打印头拓扑全局只允许一个槽位启用辅助送料。

直接使用 G-code 时，待机状态可执行第一条；打印中启用必须显式使用第二条，停用始终不要求确认：

```gcode
ACE_ENABLE_FEED_ASSIST TOOL=T0
ACE_ENABLE_FEED_ASSIST TOOL=T0 CONFIRM=1
ACE_DISABLE_FEED_ASSIST
```

Fluidd 卡片和独立页面的确认对话框会把确认结果转换为最终 Klipper 命令中的 `CONFIRM=1`。自动换料开始装载前，驱动先停用当前活动辅助送料；若旧槽位无法安全停用，本次换料中止，不允许另一台 ACE 同时向共享路径送料。

### 7.2 机器宏名称与绑定

当前版本固定使用以下名称：

| 宏名称 | 定位 | 用途 |
| --- | --- | --- |
| `_ace_prepare_toolchange` | 换料前处理，必用 | 保存位置、抬升 Z、停车并检查换料温度 |
| `_ace_cut_filament` | 切刀，必用 | 移动到切刀位置并切断耗材 |
| `_ace_load_filament_to_toolhead` | 送料，必用 | 将耗材送入打印头路径 |
| `_ace_unload_filament_from_toolhead` | 回料，必用 | 将耗材从打印头路径回抽 |
| `_ace_wipe_nozzle` | 擦嘴，必用 | 擦嘴或调用打印机已有的喷嘴清理宏 |
| `_ace_restore_after_toolchange` | 换料后处理，必用 | 恢复 Z 高度、运动状态和打印位置 |
| `_ace_pause_on_toolchange_error` | 故障暂停，必用 | 换料失败时提示，并在活动打印中暂停 |

V3 不执行尖端成型。手动模式不调用自动换料钩子；七个名称保持绑定不会自行启动换料。自动模式的固定绑定如下：

```ini
[ace_machine]
pre_toolchange_macro: _ace_prepare_toolchange                    # !!!【换料前处理｜必用】
cut_macro: _ace_cut_filament                                    # !!!【切刀｜必用】
load_to_toolhead_macro: _ace_load_filament_to_toolhead          # !!!【送料｜必用】
unload_from_toolhead_macro: _ace_unload_filament_from_toolhead  # !!!【回料｜必用】
wipe_nozzle_macro: _ace_wipe_nozzle                              # !!!【擦嘴｜必用】
post_toolchange_macro: _ace_restore_after_toolchange             # !!!【换料后处理｜必用】
pause_on_error_macro: _ace_pause_on_toolchange_error             # !!!【故障暂停｜必用】
```

`[ace_machine]` 中的字段是“名称绑定”，同名 `[gcode_macro ...]` 段才是“宏实现”。七个绑定默认启用只建立必用关系，不会自动取消任何样板注释，也不会执行 V2 示例坐标。用户必须核对本机停车、切刀、擦嘴和恢复动作的坐标、方向、速度、归零条件和安全间隙，再分别取消 `_ace_prepare_toolchange`、`_ace_cut_filament`、`_ace_wipe_nozzle` 和 `_ace_restore_after_toolchange` 实现的注释；在此之前自动换料保持“尚未就绪”，Klipper、手动模式和已授权的 ACE 内置辅助送料仍可正常使用。

`_ace_load_filament_to_toolhead`、`_ace_unload_filament_from_toolhead` 和 `_ace_pause_on_toolchange_error` 必须有完整活动实现，不得以空宏占位。换料前处理、切刀、擦嘴和换料后处理必须提供完整样板，物理实现默认整段注释，但对应名称绑定保持启用。每个活动宏必须填写简短中文 `description`，说明它在 ACE 流程中的职责。

V2 实机样板保留以下行为来源：换料前保存状态、抬升 `Z2`、停车到 `X289 Y350` 并等待最低 `240` 摄氏度；切刀从 `X10 Y330` 移动到 `X10 Y350` 并往复两次；换料后下降实际抬升量、调用 `CLEAN_NOZZLE` 并恢复位置；料盘为空时只在活动打印中暂停。所有数值和动作整段保持注释，禁止成为通用活动默认值。旧 `CUT_TIP` 中的 `FORCE_MOVE STEPPER=extruder DISTANCE=-50` 不进入切刀样板，回抽由 V3 路径控制器负责，避免重复执行。

### 7.3 宏说明格式

每个宏上方使用一个紧凑说明块，段内不留空行，只在两个宏之间保留一行。七个宏都在名称前使用 `!!!【必用】`：

```ini
# --------------------------------------------------------------------------------------------------
# !!!【切刀｜必用】_ace_cut_filament
# 用途：移动到切刀位置并切断当前耗材。
# 调用时机：旧耗材退出打印头之前。
# 物理动作：移动 X/Y 轴，并执行切刀往复。
# 必须检查：切刀坐标、运动方向、速度和 XYZ 归零状态。
# 默认状态：物理宏实现整段注释；cut_macro 名称绑定保持启用，自动换料等待用户完成核对。
# 严重警告：示例坐标禁止直接照搬，未经低速验证不得启用，否则可能撞机或损坏切刀。
# --------------------------------------------------------------------------------------------------
```

`!!!` 只表示“自动换料必用”，不能拿来表示一般警告或风险等级。七个宏都使用该标记；其他配置说明和警告行不得使用。说明使用中文直述，不使用 ASCII 字画、星级风险评分、开发过程口吻或重复的抽象术语。危险宏必须明确写出可能造成撞机、撞打印件、误切、堵头或挤出机损坏；普通宏也要说明用途、调用时机、参数和是否允许手动执行。

### 7.4 手动模式中的工具指令

自动换料未配置或尚未就绪时，驱动忽略 `T0-T15` 和 `TR`，打印继续执行。被忽略的指令不得调用任何机器宏、获取路径锁、改变当前工具、修改耗材路径状态、拒绝命令或暂停打印。

每次遇到工具指令时，Fluidd 卡片和独立页面都弹出：

```text
ACE 自动换料未配置，已忽略工具指令。
当前无法进行多色打印，仅可使用已启用的 ACE 内置辅助送料。
```

提示不做任务内去重，只用于告知用户，不得转化为错误、拒绝或暂停。这里的“仅可使用辅助送料”不绕过 `physical_actions_enabled`；设备物理动作门禁为 `False` 时，辅助送料同样不可用。自动换料配置完成并通过就绪预检后，工具指令恢复正常换料和卸载语义。
