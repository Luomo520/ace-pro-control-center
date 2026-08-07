# 多 ACE

Ace Pro Control Center 第三代驱动支持最多四台 ACE 共用一个打印头。设备按 `ace0..ace3` 的配置顺序固定映射到 `T0-T15`，不会因为 USB 枚举顺序变化而重新编号。

> **当前验证边界：** 多 ACE 配置解析、工具映射、共享路径锁、两级五通状态机和前端展示已经完成模拟测试。项目现有真机只有单台 ACE，因此跨设备送料、回抽和分支清空尚未完成多机物理验收。启用多机自动换料前，必须在自己的机器上逐分支验证。

## 支持范围

- 设备数量：`1..4`。
- 打印头数量：固定为一个。
- 每台 ACE：四个槽位。
- 支持组合：ACE1+ACE1、ACE1+ACE2、ACE2+ACE2，以及三台、四台混合排列。
- ACE1：可在完成本机验证后授权物理动作。
- ACE2：当前仅协议模拟与只读状态，不能设置 `physical_actions_enabled: True`，也不能参与物理自动换料。

## 固定工具映射

| 逻辑设备 | 界面槽位 | 工具号 |
| --- | --- | --- |
| `ace0` | 槽 1..4 | `T0..T3` |
| `ace1` | 槽 1..4 | `T4..T7` |
| `ace2` | 槽 1..4 | `T8..T11` |
| `ace3` | 槽 1..4 | `T12..T15` |

只有已安装设备对应的工具有效。例如 `device_count: 1` 时界面和自动换料范围只能是 `T0-T3`；未启用设备模板不会产生额外通道。

内部槽位参数使用 `0..3`，Fluidd 显示为槽 1..4。用户通常只需要使用全局工具号，不需要手工换算内部槽位。

## 增加或删除设备

设备数量、顺序、型号和通信身份由安装器管理。增删设备或改变 ACE1/ACE2 组合时：

1. 保留当前 `ace.cfg` 作为备份。
2. 重新运行安装器并选择新的设备数量与顺序。
3. 为每台设备提供稳定串口；ACE2 还需提供总线 ID 和唯一 UID。
4. 让安装器更新 `ace.cfg` 顶部的硬件托管区域。
5. 重启后执行 `ACE_GET_STATUS`，核对设备顺序和工具范围。

不要手工取消未启用设备模板的注释。安装器会按稳定硬件身份保留已有设备的 `enabled`、`rfid_enabled` 和 `physical_actions_enabled`，新设备不会继承被移除设备的动作授权。

## 通信组合规则

### ACE1 + ACE1

每台 ACE1 使用不同的稳定串口，不填写 `bus_id` 或 `device_uid`：

```ini
[ace_device ace0]
model: ace1
serial: /dev/serial/by-id/REPLACE_WITH_ACE1_A_PATH
enabled: True
physical_actions_enabled: False

[ace_device ace1]
model: ace1
serial: /dev/serial/by-id/REPLACE_WITH_ACE1_B_PATH
enabled: True
physical_actions_enabled: False
```

### ACE1 + ACE2

ACE1 独占自己的串口；ACE2 使用自己的串口或 ACE2 共享总线，并填写明确身份：

```ini
[ace_device ace0]
model: ace1
serial: /dev/serial/by-id/REPLACE_WITH_ACE1_PATH
enabled: True
physical_actions_enabled: False

[ace_device ace1]
model: ace2
serial: /dev/serial/by-id/REPLACE_WITH_ACE2_BUS_PATH
bus_id: REPLACE_WITH_BUS_ID
device_uid: REPLACE_WITH_UNIQUE_UID
enabled: True
physical_actions_enabled: False
```

### ACE2 + ACE2

可以使用不同总线，也可以共享相同的 `serial` 和 `bus_id`。共享时每台 `device_uid` 必须不同。当前两台仍然都属于只读设备，不得开启物理动作。

## 五通拓扑

ACE 自带缓冲和张力调节机构，V3 不增加外部“ACE 缓冲器”节点，也不把它套用为 Happy Hare/AFC 的外置缓冲、压缩或张力传感器。外部路径只描述五通、可选编码器、作为交接点的上方传感器和可选只读下方传感器。

### 单 ACE：一级五通不存在

```text
ACE0 四槽
    │
    ▼
总五通 -> 可选共享编码器 -> 上方传感器 -> 挤出机 -> 喷嘴
                                                     └-> 可选下方传感器（只读）
```

单 ACE 只需要一个总五通。`ace0_hub_sensor_pin` 与全部 `aceN_hub_*` 分支距离保持为空或 `0`，运行时不会创建、读取或显示一级五通。

### 2 至 4 台 ACE：两级五通

从第二台设备开始，每台 ACE 的四槽先进入本设备一级五通，再汇入一个共享总五通：

```text
ACE0 四槽 -> 一级五通 0 --\
ACE1 四槽 -> 一级五通 1 ---+
ACE2 四槽 -> 一级五通 2 ---+--> 总五通 -> 可选共享编码器 -> 上方传感器 -> 挤出机 -> 喷嘴
                                                                                       └-> 可选下方传感器（只读）
ACE3 四槽 -> 一级五通 3 --/
```

| ACE 数量 | 一级五通数量 | 总五通数量 | 五通总数 |
| --- | --- | --- | --- |
| 1 | 0 | 1 | 1 |
| 2 | 2 | 1 | 3 |
| 3 | 3 | 1 | 4 |
| 4 | 4 | 1 | 5 |

## 五通传感器方案

### 总五通传感器

总五通传感器使用兼容字段 `rdm_sensor_pin`：

```ini
[ace]
rdm_sensor_pin: <总五通传感器引脚>
rdm_sensor_debounce_count: 3
```

字段名保留 `rdm` 只是为了兼容旧配置，用户界面和文档统一称“总五通传感器”。多 ACE 自动换料必须能读取总五通传感器；引脚为空时 Klipper 仍可启动，但多机自动换料保持未就绪。

### 一级五通传感器

每台设备可以在一级五通出口安装一个传感器：

```ini
ace0_hub_sensor_pin: <ace0 一级五通传感器引脚>
ace1_hub_sensor_pin: <ace1 一级五通传感器引脚>
ace2_hub_sensor_pin: <ace2 一级五通传感器引脚>
ace3_hub_sensor_pin: <ace3 一级五通传感器引脚>
ace_hub_sensor_debounce_count: 3
```

只填写实际安装设备和实际安装传感器的引脚。留空表示该分支不使用一级传感器，不是错误。

支持三种布置：

- 每个一级五通和总五通都安装传感器，四台 ACE 共五个五通传感器。
- 只在总五通安装传感器，各分支使用实测的受限盲回退。
- 部分一级分支安装传感器，其余分支分别使用实测盲回退。

不论采用哪种布置，每个允许物理动作的 ACE1 分支都必须有独立校准数据。

## 每设备分支距离

```ini
ace0_hub_retract_length: 0
ace0_hub_clear_move_length: 0
ace1_hub_retract_length: 0
ace1_hub_clear_move_length: 0
ace2_hub_retract_length: 0
ace2_hub_clear_move_length: 0
ace3_hub_retract_length: 0
ace3_hub_clear_move_length: 0
```

| 参数 | 有一级传感器时 | 无一级传感器时 |
| --- | --- | --- |
| `aceN_hub_retract_length` | 总五通释放后，寻找该一级传感器释放的最大搜索距离 | 总五通释放后的受限盲回退主距离 |
| `aceN_hub_clear_move_length` | 一级传感器释放后继续回退的停车余量 | 与上一项相加，形成该分支盲回退总量 |

多 ACE 自动换料要求每台动作型 ACE 的 `aceN_hub_retract_length` 已校准为大于 `0`。`clear_move_length` 也必须按该分支实测；只有实际结构确认不需要额外停车余量时才保留 `0`。

分支距离属于物理管路，不能因管长看起来相近就复制。接头、弯曲半径、传感器位置和耗材阻力都会改变安全距离。

### 分支距离验证顺序

1. 保持 `toolchange_mode: manual`，所有设备物理动作门禁关闭。
2. 给每条管路贴上 `ace0..ace3` 标签，确认一级五通和总五通没有接错分支。
3. 手动插入耗材，逐个验证该分支一级传感器和总五通传感器的触发方向。
4. 从总五通传感器刚刚释放的位置开始，手动测量到一级传感器释放或安全退出一级五通所需的距离。
5. 单独记录该分支的搜索距离和停车余量，不使用其他分支的数值。
6. 只授权一台已确认的 ACE1，以低速、分段回抽验证；观察总五通先释放，随后分支按预期清空。
7. 检查停止位置仍在 ACE 可重新送料的可靠范围内，没有把耗材卷回线盘或拉出驱动机构。
8. 对每台动作型 ACE 重复以上步骤；全部完成前不进行跨设备送料。

## 跨设备换料顺序

V3 的共享路径同一时刻只允许一个动作所有者。跨设备换料应按以下顺序完成：

1. 检查目标槽位可用，避免先切断当前耗材后才发现目标为空。
2. 停用当前辅助送料；停用失败则中止换料。
3. 执行本机前处理和切刀。
4. 由挤出机受限回抽旧耗材，确认上方传感器稳定释放；编码器可验证实际后退。
5. 回抽到总五通释放。
6. 使用当前设备的一级传感器或受限盲回退清空该分支。
7. 只有旧分支和总五通都已释放，目标 ACE 才能开始送料。
8. 新耗材到达上方传感器后由挤出机接管；默认旁路时下方只监测，用户显式关闭旁路后按下方闭环完成装载。

任一阶段传感器状态矛盾、搜索超限或设备返回未知结果时，路径应转为 `unknown` 并要求人工检查，不能猜测动作成功后继续下一台送料。

## 多 ACE 真机验证顺序

1. **只读阶段**：所有设备保持 `physical_actions_enabled: False`，核对设备顺序、槽位、RFID 和工具映射。
2. **机械阶段**：确认所有一级五通、总五通、管路和接头牢固，手动推料无明显卡滞。
3. **传感器阶段**：逐路验证无料/有料状态；总五通必须覆盖唯一公共路径。
4. **分支校准阶段**：逐台测量并验证 `aceN_hub_retract_length` 与 `aceN_hub_clear_move_length`。
5. **单设备动作阶段**：一次只授权一台 ACE1，验证本设备完整装载和卸载，其他设备保持动作禁用。
6. **共享路径阶段**：确认任意设备卸载后总五通和当前分支都为空，辅助送料全局最多一个槽位启用。
7. **跨设备阶段**：待机、无打印状态下验证 `ace0 -> ace1`，再验证反向；逐组完成，不一次覆盖全部组合。
8. **错误阶段**：验证目标槽空、总五通不释放或分支未清空时不会启动目标 ACE。
9. **自动阶段**：最后才设置 `toolchange_mode: automatic`，确认 `toolchange_ready` 后进行短测试打印。

多 ACE 首次验证不得在无人值守打印中进行。模拟测试通过不代表本机软管长度、传感器位置和切刀动作已经安全。

相关页面：[配置说明](Configuration) | [自动换料](Automatic-Toolchange) | [传感器和编码器](Sensors-and-Encoder) | [安装与升级](Installation-and-Upgrade)
