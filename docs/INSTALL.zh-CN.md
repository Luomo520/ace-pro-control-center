# ACE Pro 管理中心 v1.2.0 完整安装与恢复教程

本文面向第一次在 DIY Klipper 打印机上安装 Ace Pro Control Center 的用户，完整覆盖准备、下载、安装、配置、静态验证、首次动作验证、升级、回滚、卸载和故障处理。

## 1. 先确认适用范围

Ace Pro Control Center 当前只支持：

- 一台 ACE Pro。
- T0-T3 四个料槽。
- DIY Klipper 打印机。
- 本仓库内置 Klipper 驱动、Moonraker `ace_status` 组件和 Fluidd 卡片。
- Fluidd v1.37.2 完整构建验证基线。

本项目从 [szkrisz/ACEPROSV08](https://github.com/szkrisz/ACEPROSV08) 衍生，使用 GPL-3.0 发布。它不兼容与 `Kobra-S1/ACEPRO` 或原版 `szkrisz/ACEPROSV08` 同时加载。

安装器按全新安装处理，不检测、不迁移、不卸载其他 ACE 驱动。开始前必须由用户确认 Klipper 中只有一个 `[ace]` 和一套 `ace.py`。

## 2. 了解安装内容

默认完整安装会处理以下边界：

| 组件 | 默认目标 |
| --- | --- |
| 项目运行目录 | `~/ace-pro-control-center/` |
| Klipper 驱动源 | `~/ace-pro-control-center/extras/ace.py` |
| Klipper 驱动入口 | `~/klipper/klippy/extras/ace.py`，指向项目运行目录的软链接 |
| ACE 运行配置 | `~/printer_data/config/ace.cfg`，普通可写文件 |
| 配置同步副本 | `~/ace-pro-control-center/ace.cfg` |
| 新版配置模板 | `~/ace-pro-control-center/ace.cfg.example` |
| Moonraker 组件 | `~/moonraker/moonraker/components/ace_status.py` |
| Fluidd | `~/fluidd/` 完整构建 |
| 备用页面 | 部署到 Fluidd 根目录，同时保留于项目运行目录 |
| 安装状态和归档 | `~/.local/share/ace-pro-control-center/` |

> [!WARNING]
> Git 源码目录不能与默认运行目录相同，也不能互相包含。不要把仓库直接克隆到 `~/ace-pro-control-center`，也不要把源码放进该运行目录或把运行目录放进源码目录。本教程统一使用 `~/ace-pro-control-center-source` 作为源码目录。安装器会在校验编译、生成临时配置和创建归档前解析两者的绝对路径；发现危险重合时拒绝安装、回滚和卸载，且不会移动任何目标文件。

> [!CAUTION]
> 必须使用安装 Klipper 的普通 Linux 用户运行。禁止执行 `sudo sh install.sh`、`sudo sh ui-installer.sh ...` 或切换到 root 后安装；安装器会拒绝 root 身份，防止把 Klipper、Moonraker、Fluidd 和配置文件写成 root 所有。

安装器还会：

- 校验包内 `manifest.sha256` 和全部发布文件。
- 尝试编译检查驱动与 Moonraker Python 文件。
- 在缺少 `serial` Python 模块时，通过 Klipper Python 环境安装固定的 `pyserial==3.5`。该 Python 环境变更不在文件回滚或卸载范围内。
- 在 `printer.cfg` 中不存在时追加一份 `[include ace.cfg]`。
- 在 `moonraker.conf` 中不存在时追加一份 `[ace_status]`。
- 卡片范围整体替换 `~/fluidd`，只保留原来的 `config.json`。
- 把 `ace.cfg` 安装为配置目录内的普通文件，避免 Fluidd 锁图标。
- 不自动重启 Klipper 或 Moonraker。
- 不执行送料、回抽、切刀、加热或工具切换。

如果原 Fluidd 中手工放入了主题、插件、补丁或其他额外文件，安装器不会把它们合并进新构建。它们只存在于本次 `old/` 归档中，需要在确认兼容后人工选择性恢复；不要把整个旧 Fluidd 覆盖回新版本。

## 3. 安装前安全检查

### 3.1 确认打印机空闲

Fluidd 中必须没有正在打印或暂停的任务。不要在换料、送料、回抽、切刀或烘干命令仍在执行时安装。

可通过 Moonraker 只读查询：

```bash
curl -fsS 'http://127.0.0.1:7125/printer/objects/query?print_stats'
```

确认返回状态不是 `printing` 或 `paused`。

### 3.2 确认现有服务正常

```bash
systemctl --no-pager --full status klipper moonraker
test -f ~/fluidd/index.html && echo 'Fluidd 文件存在'
curl -fsS http://127.0.0.1:7125/server/info
```

先解决已有的 Klipper、Moonraker 或 Fluidd 启动问题，再安装本项目。安装器归档只能恢复安装前状态，不能修复安装前已经损坏的系统。

### 3.3 检查空间

完整安装会同时保留旧 Fluidd 和新 Fluidd。至少预留当前 Fluidd 目录两倍以上空间：

```bash
du -sh ~/fluidd
df -h ~
```

### 3.4 检查重复驱动和配置

```bash
grep -Rni --include='*.cfg' '^\[ace\]' ~/printer_data/config
grep -Rni --include='*.cfg' '^\[include[[:space:]]\+ace\.cfg\]' ~/printer_data/config
find ~/klipper ~/printer_data/config -maxdepth 5 \
  \( -name 'ace.py' -o -name 'ace.cfg' \) -ls 2>/dev/null
```

如发现 Kobra-S1、原版 ACEPROSV08 或其他 ACE 驱动，先按对应项目教程处理。Ace Pro Control Center 安装器不会替用户删除它们。

### 3.5 检查 Klipper 全局节

```bash
grep -Rni --include='*.cfg' '^\[save_variables\]' ~/printer_data/config
grep -Rni --include='*.cfg' '^\[force_move\]' ~/printer_data/config
```

- `[save_variables]` 必须存在且只能定义一次，用于保存库存、当前槽位、功能开关和标定结果。
- `ACE_PRELOAD` 冷态预装载需要一份 `[force_move]`，并设置 `enable_force_move: True`。
- 不要为了本项目重复添加已有全局节。

### 3.6 记录本机参数

安装前准备好：

- ACE Pro 的 `/dev/serial/by-id/...` 串口。
- 挤出机上方传感器 MCU 引脚。
- 挤出机下方传感器 MCU 引脚。
- 可选五通传感器引脚及其位于五通之前还是之后。
- ACE 出料口到五通进料口的 PTFE 长度。
- ACE 停放位置到上方传感器的最大送料距离。
- 足以释放公共通道的完整回抽距离。
- 下方传感器到喷嘴的耗材路径长度。
- 本机切刀的安全 X/Y 坐标、轴范围和动作顺序。

```bash
ls -l /dev/serial/by-id/
```

优先使用 `/dev/serial/by-id/...`。只有明确配置 `serial: auto` 或 `serial: detect` 时驱动才扫描设备。

## 4. 通过 Git 下载

### 4.1 安装固定 v1.2.0

```bash
cd ~
git clone --branch v1.2.0 --depth 1 \
  https://github.com/Luomo520/ace-pro-control-center.git \
  ace-pro-control-center-source
cd ~/ace-pro-control-center-source
```

### 4.2 跟随 main

```bash
cd ~
git clone --depth 1 \
  https://github.com/Luomo520/ace-pro-control-center.git \
  ace-pro-control-center-source
cd ~/ace-pro-control-center-source
```

如果源码目录已经存在：

```bash
cd ~/ace-pro-control-center-source
git status --short
git pull --ff-only
```

`git pull --ff-only` 因本地修改而失败时，不要使用 `git reset --hard`。先保存自己的修改，或重新克隆到另一个源码目录。

## 5. 运行字符安装器

```bash
cd ~/ace-pro-control-center-source
sh install.sh
```

安装器先选择语言，再显示 Fluidd、Moonraker、驱动、安装包、语言、安装状态和最近归档。

| 菜单 | 作用 | 会修改的主要范围 |
| ---: | --- | --- |
| 1 | 安装/更新完整组件 | 驱动、配置、Moonraker、Fluidd、备用页 |
| 2 | 仅安装/更新驱动 | 驱动、配置、`printer.cfg` |
| 3 | 仅安装/更新卡片 | Fluidd、Moonraker、备用页 |
| 4 | 强制完整安装 | 与 1 相同，但跳过兼容性阻断 |
| 5 | 回滚最近一次安装 | 恢复安装状态记录中的最近归档 |
| 6 | 完整卸载 | 恢复项目首次写入前基线 |
| 7 | 状态检查 | 只读，不修改文件 |
| 8 | 退出 | 不修改文件 |

新用户推荐选 `1`。已有 `ace.cfg` 时，菜单 1 和 2 都会保留其实际内容；新版模板写入 `~/ace-pro-control-center/ace.cfg.example`。

`preserve` 模式检测到已有运行配置后会跳过传感器问答，不改写现有 `ace.cfg`，并用不含真实 MCU 引脚的安全默认值生成新版示例模板。安装后仍需手动核对和编辑 `~/printer_data/config/ace.cfg`。

### 5.1 五通传感器向导

首次完整安装、首次仅驱动安装或明确替换配置模板时，向导会询问：

1. 上方传感器引脚。
2. 下方传感器引脚。
3. 是否安装五通传感器。
4. 五通传感器引脚。
5. 传感器位于五通之前还是之后。

可以留空或选择稍后配置。安装包不会预填其他用户的真实 MCU 引脚。上下传感器引脚留空时，安装器会明确警告，此时不得重启 Klipper，必须先编辑 `ace.cfg`。

如果已经存在 `ace.cfg` 且使用默认 `preserve` 模式，安装器不会显示这些问答；这是为了避免用户误以为答案已经合并到现有运行配置。

### 5.2 兼容性提示

卡片范围采用保守的精确验证基线：Fluidd `1.37.2`，Moonraker `0.9.3`。当前没有证据支持声明更宽的 Moonraker 兼容范围，因此最低和最高完整验证版本暂时都定义为 `0.9.3`。

Fluidd 或 Moonraker 低于、高于对应基线时均进入风险流程。Moonraker 版本无法解析为三段数字版本时也视为未知风险，包括只有 Git 提交哈希、空值或非标准版本文本的情况；安装器不会把“能够读取到一段文本”误判为已验证兼容。

- 完整安装遇到风险时：可选择仅安装驱动、继续完整安装或取消。
- 仅卡片安装遇到风险时：可继续或取消。
- 强制安装只跳过兼容性阻断，不跳过清单校验、安装前归档和失败恢复。
- 非交互普通安装遇到版本风险会以失败结束，不会擅自继续，也不会自动降级为其他范围。
- 只有明确执行 `--install-force` 才允许非交互完整安装越过版本风险。
- `--yes` 只跳过操作确认，不等于强制兼容；`--yes --install` 遇风险仍失败，`--yes --install-force` 才继续。

### 5.3 命令行模式

```bash
sh ui-installer.sh --install
sh ui-installer.sh --install-driver
sh ui-installer.sh --install-card
sh ui-installer.sh --install-new-config
sh ui-installer.sh --install-force
sh ui-installer.sh --rollback-latest
sh ui-installer.sh --uninstall
sh ui-installer.sh --uninstall-driver
sh ui-installer.sh --uninstall-card
sh ui-installer.sh --status
sh ui-installer.sh --help
sh ui-installer.sh -h
```

除 `--status` 和帮助外，直接 CLI 执行安装、替换配置、回滚或卸载会要求确认。`--yes` 必须放在操作参数之前，用于已经完成外部审批的自动化场景，例如：

```bash
sh ui-installer.sh --yes --install-driver
```

危险操作确认示例：

```bash
# 会要求 y/N 确认
sh ui-installer.sh --rollback-latest

# 跳过确认，但仍执行清单校验、归档和失败恢复
sh ui-installer.sh --yes --rollback-latest

# 非基线 Fluidd 的无人值守完整安装必须明确使用 force
sh ui-installer.sh --yes --install-force
```

非交互模式不会询问传感器引脚。除非通过环境变量明确提供配置，否则新模板中的引脚仍为空：

```bash
ACE_CC_LANG=zh-CN \
ACE_CC_UPPER_SENSOR_PIN='^toolhead:PA5' \
ACE_CC_LOWER_SENSOR_PIN='^toolhead:PA6' \
ACE_CC_PARKING_SENSOR=no \
sh ui-installer.sh --yes --install
```

如果机器已有 `ace.cfg`，上面的 `preserve` 安装仍保留旧配置，不会把环境变量合并进去。需要手动编辑运行配置，或在充分理解覆盖后改用 `--install-new-config`。

`ACE_CC_CONFIG_MODE` 严格只接受 `preserve` 或 `replace`。其他值会在载荷校验、临时配置生成和安装前归档之前失败，不会修改目标文件。已有 `ace.cfg` 的 `preserve` 模式会继续跳过传感器问答并保留活动配置；安装器仅使用不含真实 MCU 引脚的安全默认模板生成 `ace.cfg.example`。

上例引脚只是格式示意，不能照抄。可用五通传感器值为：

```text
ACE_CC_PARKING_SENSOR=yes
ACE_CC_PARKING_SENSOR_PIN=实际引脚
ACE_CC_PARKING_SENSOR_POSITION=after_five_way
```

### 5.4 自定义目录

标准 Klipper 安装不需要设置。自定义布局可在单次命令前覆盖：

```bash
FLUIDD_ROOT=/实际/fluidd \
KLIPPER_ROOT=/实际/klipper \
MOONRAKER_ROOT=/实际/moonraker \
PRINTER_CONFIG_DIR=/实际/printer_data/config \
sh ui-installer.sh --install
```

高级变量还包括 `PRINTER_CFG`、`MOONRAKER_CONF`、`KLIPPER_PYTHON`、`ACE_CC_ROOT`、`ACE_CC_STATE_DIR` 和 `ACE_CC_CONFIG_MODE`。`ACE_CC_CONFIG_MODE` 只允许 `preserve` 或 `replace`；`replace` 会覆盖现有运行配置，必须先备份并准备重新填写全部机器参数。所有后续回滚与卸载必须使用与安装时相同的路径变量，否则安装器会在错误位置寻找目标。

## 6. 理解归档和事务恢复

每次安装写入前，安装器会建立：

```text
~/.local/share/ace-pro-control-center/old/YYYYMMDD-HHMMSS-PID/
```

典型结构：

```text
manifest.txt
archive.complete
old/
resolved/current-ace.cfg
```

- `manifest.txt` 记录应用、版本、范围、语言和路径。
- `archive.complete` 只在归档完整后创建。
- `old/` 保存原文件、目录或软链接。
- `resolved/current-ace.cfg` 保存旧 `ace.cfg` 解析后的真实内容，用于无损转换带锁软链接。
- 安装中断或替换失败时，新目标进入隔离目录，安装器尝试恢复本次写入前状态。
- 回滚和卸载本身也会先归档当前状态，不会直接删除用户文件。
- Fluidd 归档包含完整旧目录，因此旧主题、手工插件和额外文件可以从对应 `old/fluidd/` 人工取回。
- `pyserial==3.5` 安装发生在 Klipper Python 环境中，不属于这些文件归档，回滚和卸载不会自动卸载或降级 Python 包。

安装器维护三类基线：全局首次写入前基线、驱动首次写入前基线、卡片首次写入前基线。无论先装驱动还是先装卡片，完整卸载都以项目第一次写入前状态为目标。

不要手工删除 `~/.local/share/ace-pro-control-center`，否则最近回滚和完整卸载会失去恢复来源。

## 7. 配置 `ace.cfg`

安装完成后：

```bash
nano ~/printer_data/config/ace.cfg
```

也可以在 Fluidd 配置文件编辑器中打开。正常状态应是普通可写文件：

```bash
test -f ~/printer_data/config/ace.cfg && \
  test ! -L ~/printer_data/config/ace.cfg && \
  test -w ~/printer_data/config/ace.cfg && echo 'ace.cfg 是普通可写文件'
```

### 7.1 必填参数

| 参数 | 填写方法 | 错误风险 |
| --- | --- | --- |
| `serial` | 使用 `ls -l /dev/serial/by-id/` 找到 ACE | 连接错误设备或频繁断联 |
| `extruder_sensor_pin` | 填上方传感器实际 MCU 引脚 | 到达挤出机后仍继续送料 |
| `toolhead_sensor_pin` | 填下方传感器实际 MCU 引脚 | 挤出机继续送料直到上限 |
| `toolchange_load_length` | 实测 ACE 停放位置到上方传感器并留合理打滑余量 | 太短到不了，太长可能磨料 |
| `toolchange_retract_length` | 足以把耗材退回并释放公共通道 | 下次槽位无法进入五通 |
| `bowden_tube_length` | 实测 ACE 出料口到五通进料口 | 预停放估算偏差 |
| `toolhead_sensor_to_nozzle` | 实测下方传感器到喷嘴 | 装载不足或过度挤出 |
| `max_dryer_temperature` | 不超过 ACE 和所用材料安全上限 | 低温材料软化或设备过热 |

### 7.2 可选五通传感器

没有五通传感器时保持以下行注释：

```ini
#parking_sensor_pin: ^YOUR_MCU_PIN
```

有传感器时填写实际引脚，并设置位置：

```ini
parking_sensor_pin: ^实际引脚
parking_sensor_position: after_five_way
parking_sensor_clear_move_length: 75
parking_sensor_debounce_count: 3
```

- `after_five_way`：传感器位于五通公共出口之后。
- `before_five_way`：传感器位于五通之前的检测位置。
- `parking_sensor_clear_move_length`：回抽中传感器稳定变为无料后，再向 ACE 回抽的总距离，已经包含安全余量。
- 该距离不会再叠加 `five_way_parking_margin`。

### 7.3 连续送料和回料

v1.2.0 推荐：

```ini
intermittent_feed: False
intermittent_retract: False
feed_fast_speed: 160
feed_approach_speed: 25
feed_approach_length: 100
retract_fast_speed: 120
retract_parking_speed: 25
retract_parking_length: 200
```

`False` 不是关闭送料或回料，而是关闭固定距离断续模式。连续模式仍监测传感器，并保留最后慢速段和有限打滑补偿。

### 7.4 材料资料

每种材料必须成组配置：

```ini
material_1_name: PLA
material_1_drying_temperature: 45
material_1_temperature: 210
```

- `name` 用于界面选择和无限续料匹配。
- `drying_temperature` 是 ACE 烘干目标。
- `temperature` 是喷嘴参考温度，不直接控制烘干。
- 名称匹配不区分大小写。
- 自定义材料可以继续增加连续编号组。

### 7.5 切刀宏

发布模板中的 `[gcode_macro CUT_TIP]` 默认整段注释。必须根据本机机械结构填写坐标、速度和挤出机回抽，再取消注释。

不要直接照抄示例中的 `G28`、`FORCE_MOVE` 或坐标。先确认：

- 切刀实际位于哪里。
- 轴已归零时如何到达切刀。
- 未归零时是否允许自动归零。
- 切刀动作是否会碰撞打印件、擦嘴结构或限位。
- 切断后需要多少挤出机回抽。
- 宏最终是否恢复原 G-code 状态和工具头位置。

默认 `_ACE_PRE_TOOLCHANGE` 和 `_ACE_POST_TOOLCHANGE` 只输出提示，不归零、不移动、不加热。

### 7.6 配置版本、传感器消抖和绝对硬上限

新版 `[ace]` 正式支持以下配置契约：

| 参数 | 作用 | 填写原则 |
| --- | --- | --- |
| `ace_config_version` | 标识配置结构，供驱动选择兼容解析路径 | 使用根 `ace.cfg` 中的当前值，不自行猜测或递增 |
| `extruder_sensor_debounce_count` | 上方传感器触发与解除的独立连续确认次数 | 按上方微动稳定性调整，不与下方或断料消抖共用 |
| `toolhead_sensor_debounce_count` | 下方传感器触发与解除的独立连续确认次数 | 按下方微动稳定性调整，不与上方或断料消抖共用 |
| `sensor_trigger_grace_time` | 理论运动结束后的传感器额外监测时间 | 只在确有机械或通信延迟时调整；不会追加送料或回抽距离 |
| `toolchange_feed_hard_limit` | 送料、接近和有限补偿允许达到的绝对累计上限 | 必须覆盖正常路径和合理补偿，但不能用过大值掩盖打滑或传感器故障 |
| `toolchange_retract_hard_limit` | 回料及相关恢复路径允许达到的绝对累计上限 | 必须覆盖正常回料路径，同时限制持续空转和过度回抽 |

`toolchange_load_length`、`feed_slip_compensation_length` 和
`toolchange_retract_length` 仍描述正常动作及有限补偿；两个 `*_hard_limit` 是任何正常
长度、补偿或恢复请求都不能越过的最后边界。达到硬上限时驱动停止本次换料并暂停
正在打印的任务，不执行 `CANCEL_PRINT`。

旧配置缺少这些新键时仍按驱动兼容路径加载，不要求为了升级强制覆盖现有
`ace.cfg`。建议对照根 `ace.cfg` 的当前注释逐项补齐，以便显式记录配置版本、两只
传感器的独立消抖和本机绝对边界。不要从本文复制一套默认数值；根 `ace.cfg` 是唯一
可安装模板和发布值来源。

### 7.7 检查 include 和 Moonraker 配置

```bash
grep -n '^\[include ace\.cfg\]' ~/printer_data/config/printer.cfg
grep -n '^\[ace_status\]' ~/printer_data/config/moonraker.conf
```

应该各有且只有一份。安装器默认加入：

```ini
[ace_status]
upper_sensor_name: extruder_sensor
lower_sensor_name: toolhead_sensor
```

这里填写的是 Klipper 传感器对象名，不是 MCU 引脚。

## 8. 重启前静态验证

在执行服务重启前完成：

```bash
cd ~/ace-pro-control-center-source
sh ui-installer.sh --status
test -L ~/klipper/klippy/extras/ace.py && \
  readlink ~/klipper/klippy/extras/ace.py
test -f ~/moonraker/moonraker/components/ace_status.py
grep -Rni --include='*.cfg' '^\[ace\]' ~/printer_data/config
grep -Rni --include='*.cfg' '^\[save_variables\]' ~/printer_data/config
grep -nE '^(ace_config_version|extruder_sensor_debounce_count|toolhead_sensor_debounce_count|toolchange_feed_hard_limit|toolchange_retract_hard_limit):' \
  ~/printer_data/config/ace.cfg
```

确认：

- `ace.cfg` 为普通可写文件。
- Klipper `ace.py` 链接指向 `~/ace-pro-control-center/extras/ace.py`。
- 只有一个 `[ace]`。
- 只有一份 `[save_variables]`。
- 上下传感器引脚不再是模板占位符。
- 新配置应能查到配置版本、两个独立消抖项和两个绝对硬上限；旧配置缺失时应由
  驱动兼容加载，而不是出现未知选项或缺少选项错误。
- 切刀宏仍保持注释，或已经按本机验证。

本轮对上述新契约只做配置解析、服务、API 和状态等静态部署验证。未执行送料、
回抽、切刀、自动探测或完整换料，因此静态验证通过不代表机械参数已经适合本机。

## 9. 安全重启与无动作验证

再次确认 `print_stats` 不是 `printing` 或 `paused`，然后：

```bash
sudo systemctl restart klipper
sudo systemctl restart moonraker
```

安装器本身不会执行这两个命令。

### 9.1 服务状态

```bash
systemctl --no-pager --full status klipper moonraker
journalctl -u klipper -n 80 --no-pager
journalctl -u moonraker -n 80 --no-pager
```

### 9.2 Moonraker API

```bash
curl -fsS http://127.0.0.1:7125/server/ace/capabilities
curl -fsS http://127.0.0.1:7125/server/ace/status
curl -fsS http://127.0.0.1:7125/server/ace/slots
```

预期：

- 请求不是 404。
- `capabilities` 中存在驱动身份和受控命令列表。
- `status` 能返回连接、双传感器、槽位、烘干、标定和换料状态。
- API 不提供任意 G-code 执行入口。

### 9.3 页面

```text
http://打印机IP/
http://打印机IP/ace.html
```

Fluidd 是主入口；`/ace.html` 是备用页。两者功能应一致，只允许布局尺寸不同。

若 Fluidd 仍显示旧资源，先强制刷新；仍无效时清除该站点缓存和 Service Worker，再重新打开。

## 10. 首次动作验证

以下步骤会产生机械动作，必须由现场用户确认路径畅通，并准备随时暂停或断电。

### 10.1 只验证传感器

1. 界面确认上、下传感器都显示无料。
2. 分别手动按压上方和下方微动。
3. 确认两个开关独立变化，没有互换或反相。
4. 可在控制台执行 `ACE_TEST_RUNOUT_SENSOR` 查看诊断。

传感器错误时不要增加送料长度来掩盖问题。

### 10.2 短距离手动移动

确保未打印、未暂停、料路安全，再用卡片的手动操作和较小距离测试。控制台等价命令示例：

```text
ACE_FEED INDEX=0 LENGTH=20 SPEED=10 CONFIRM=1
ACE_RETRACT INDEX=0 LENGTH=20 SPEED=10 CONFIRM=1
```

先确认 T0 实际运动方向，再检查 T1-T3。Moonraker API 对手动移动限制为 1-500 mm、1-120 mm/s。

### 10.3 空载验证切刀

不带耗材，先确认工具头当前位置和轴归零状态，再单独验证用户编写的 `CUT_TIP`。任何接近限位、碰撞或异常归零都应立即停止并修改宏。

### 10.4 自动探测料管长度

开始条件：

- 打印机处于待机状态。
- ACE 已连接并处于 `ready`。
- 上下传感器必须均无料。
- 选择的槽位确实有料，路径无堵塞。

优先点击 Fluidd 卡片“自动探测料管长度”。控制台等价命令：

```text
ACE_CALIBRATE INDEX=0 CONFIRM=1
```

驱动自动送料到上方传感器，再执行受限回料。完成后检查界面显示：

- 有五通传感器：上方传感器到五通传感器、上方传感器到五通停放点。
- 无五通传感器：上方传感器到内部停放点。

确认耗材已经回到安全位置、上下传感器均无料，再保存：

```text
ACE_CALIBRATION_SAVE CONFIRM=1
```

放弃预览：

```text
ACE_CALIBRATION_CANCEL
```

高级诊断可拆分执行：

```text
ACE_CALIBRATE_FEED INDEX=0 CONFIRM=1
ACE_CALIBRATE_RETRACT CONFIRM=1
```

### 10.5 冷态预装载与完全卸载

普通 T0-T3 始终送入喷嘴。待机维护命令：

```text
ACE_PRELOAD INDEX=0 CONFIRM=1
ACE_FULL_UNLOAD INDEX=0 CONFIRM=1
```

`ACE_PRELOAD` 不加热、不归零、不移动 XY/Z、不切刀，只送到下方传感器。开始前应确认上下传感器无料；异常时停止并检查真实耗材位置。

### 10.6 完整换料

最后才测试 `T0 -> T1`：

1. 观察控制台 `T0 -> T1` 开始提示。
2. 确认旧料按宏到达切刀并切断。
3. 确认工具头挤出机回抽。
4. 确认旧料退回并释放公共通道。
5. 确认新料快速送料、最后 100 mm 慢速接近。
6. 确认上方传感器触发后 ACE 停止额外送料。
7. 确认挤出机继续送料，直到下方传感器触发。
8. 确认按 `toolhead_sensor_to_nozzle` 送到喷嘴。

失败时保持暂停，记录失败阶段和两个传感器状态。不要连续重复 T 命令。

## 11. 升级 v1.2.0 或后续版本

### 11.1 更新 main

```bash
cd ~/ace-pro-control-center-source
git status --short
git pull --ff-only
sh install.sh
```

选择菜单 `1` 会更新完整组件并保留当前 `ace.cfg`。

### 11.2 切换发布标签

```bash
cd ~/ace-pro-control-center-source
git fetch --tags --force
git checkout v1.2.0
sh install.sh
```

### 11.3 保留配置与替换模板

默认安装模式为 `preserve`：

- 保留当前 `~/printer_data/config/ace.cfg` 的真实内容。
- 同步到项目运行目录。
- 把当前包模板写入 `~/ace-pro-control-center/ace.cfg.example`。
- 不把本次向导或环境变量答案合并到已经存在的运行配置。

只有明确希望用新模板替换运行配置时执行：

```bash
cd ~/ace-pro-control-center-source
sh ui-installer.sh --install-new-config
```

该命令仍先归档旧配置，但会覆盖运行配置。执行后必须逐项重新填写并验证，不能直接重启。

### 11.4 升级后验证

重复第 8、9 节的静态与无动作验证。除非更新日志明确要求，不需要每次升级都重新执行切刀或完整换料。

修改以下项目后，旧自动探测结果会过期，需要重新探测：

- `bowden_tube_length`
- `five_way_parking_margin`
- 五通传感器启用状态或位置
- `parking_sensor_clear_move_length`
- 标定数据格式

## 12. 回滚与卸载

### 12.1 最近一次回滚

适用于刚更新后 Fluidd 空白、Moonraker 组件不兼容或驱动行为异常：

```bash
cd ~/ace-pro-control-center-source
sh ui-installer.sh --rollback-latest
```

直接 CLI 会先要求 `y/N` 确认，`--yes` 才跳过。回滚先归档当前状态，再恢复安装状态记录中的最近一次安装前归档。它不是完整卸载。

### 12.2 完整卸载

```bash
cd ~/ace-pro-control-center-source
sh uninstall.sh
```

卸载同样要求确认；无人值守可执行 `sh ui-installer.sh --yes --uninstall`。完整卸载恢复项目第一次写入前的全局基线，包括原 Fluidd、Moonraker、Klipper 驱动入口和配置文件类型/内容，但不会卸载安装期间加入 Klipper Python 环境的 `pyserial==3.5`。

### 12.3 仅卸载驱动或卡片

```bash
sh ui-installer.sh --uninstall-driver
sh ui-installer.sh --uninstall-card
```

- `--uninstall-driver` 恢复驱动、配置和 `printer.cfg` 的驱动基线。
- `--uninstall-card` 恢复 Fluidd、Moonraker 和备用页的卡片基线。

### 12.4 恢复后重启

回滚和卸载不会自动重启服务。确认没有打印或暂停任务后：

```bash
sudo systemctl restart klipper
sudo systemctl restart moonraker
```

随后验证原 Fluidd、Klipper 和 Moonraker 状态。不要在确认恢复成功前删除 `old/` 归档。

## 13. 排障手册

### 13.1 安装前提示清单校验失败

症状：`安装文件校验失败` 或 `sha256sum is required`。

处理：

```bash
command -v sha256sum
cd ~/ace-pro-control-center-source
sha256sum -c manifest.sha256
git status --short
```

- 使用 Git 重新下载完整仓库。
- 不要手工删除清单条目或使用强制安装绕过；强制模式也不会跳过校验。
- 本地改过发布文件后清单必然不匹配，应恢复官方发布内容或由开发者重新生成清单。

### 13.2 安装器提示禁止 root

退出 root 或 sudo shell，切回安装 Klipper 的普通用户：

```bash
whoami
cd ~/ace-pro-control-center-source
sh install.sh
```

不要用 `sudo` 绕过目录权限问题。先修复文件所有者或恢复安装前状态，否则会让 Fluidd 和配置继续不可编辑。

### 13.3 安装前归档失败

安装器在新文件写入前停止。检查磁盘空间、目录权限和归档路径：

```bash
df -h ~
ls -ld ~/.local/share ~/.local/share/ace-pro-control-center
```

不要在归档失败后手工覆盖 Fluidd 或驱动。

### 13.4 安装中断或提示恢复失败

记录终端给出的 `archive=` 和 `quarantine=` 路径，停止再次安装。检查：

```bash
find ~/.local/share/ace-pro-control-center/old -maxdepth 2 \
  -name manifest.txt -o -name archive.complete
```

恢复失败表示安装器无法证明当前状态完整，不应继续重启或执行物理动作。保留归档和隔离目录，用于人工比对恢复。

### 13.5 `ace.cfg` 带锁或不可编辑

检查：

```bash
ls -l ~/printer_data/config/ace.cfg
test -L ~/printer_data/config/ace.cfg && echo '仍是软链接'
test -w ~/printer_data/config/ace.cfg && echo '所有者可写'
```

重新运行安装器，选择 `1` 或 `2`。安装器会归档旧软链接和真实内容，再写入配置目录内的普通可写文件。不要递归执行 `chmod 777 ~/printer_data/config`。

### 13.6 Klipper 启动失败

```bash
journalctl -u klipper -n 150 --no-pager
tail -n 150 ~/printer_data/logs/klippy.log
grep -Rni --include='*.cfg' '^\[ace\]' ~/printer_data/config
```

常见原因：

- 上下传感器引脚仍为空或无效。
- 串口路径不存在。
- 同时加载两套 `ace.py` 或两个 `[ace]`。
- `T0`、`T1`、`PAUSE`、`RESUME`、`CANCEL_PRINT` 等宏重复定义。
- `[save_variables]` 或 `[force_move]` 重复。
- 传感器对象名与 `[ace_status]` 不一致。

### 13.7 Moonraker 警告 `[ace_status]` 未解析

```bash
test -f ~/moonraker/moonraker/components/ace_status.py
grep -n '^\[ace_status\]' ~/printer_data/config/moonraker.conf
journalctl -u moonraker -n 150 --no-pager
```

确认组件存在、配置节唯一，并在打印机空闲时重启 Moonraker。

### 13.8 API 404

不要把 `:7125/ace.html` 当作页面地址。Moonraker 7125 端口提供 API，备用页面由 Fluidd/Nginx 提供。

```text
正确页面：http://打印机IP/ace.html
正确 API：http://打印机IP:7125/server/ace/status
```

仍为 404 时检查 Moonraker 组件日志和重启状态。

### 13.9 Fluidd 空白页

优先恢复，不要反复覆盖：

```bash
cd ~/ace-pro-control-center-source
sh ui-installer.sh --rollback-latest
```

空闲时重启 Moonraker，随后清除浏览器站点缓存和 Service Worker。再检查：

```bash
test -f ~/fluidd/index.html
find ~/fluidd/assets -maxdepth 1 -type f | wc -l
ls -ld ~/fluidd ~/fluidd/assets
```

非 Fluidd v1.37.2 属于风险安装，应把版本信息和浏览器控制台错误一起记录。

### 13.10 Fluidd 没有 ACE Pro 卡片

- 运行 `sh ui-installer.sh --status`。
- 确认之前选择了完整安装或仅卡片安装。
- 确认 `/server/ace/capabilities` 可访问。
- 强制刷新 Fluidd。
- 检查 Moonraker 日志中 `ace_status` 是否加载。

### 13.11 ACE 频繁断联

```bash
ls -l /dev/serial/by-id/
dmesg --ctime | tail -n 100
journalctl -u klipper -n 200 --no-pager | grep -i -E 'ace|usb|serial|disconnect'
```

检查固定串口路径、数据线、接头、供电、USB 口和系统日志。驱动不会把不确定物理动作直接重放；达到恢复上限后保持暂停并报告阶段。

### 13.12 送料每固定距离停顿

```ini
intermittent_feed: False
```

连续模式主送料和有限打滑补偿各使用完整请求。仍有停顿时检查 ACE 固件响应、传感器抖动、USB 重连和 `ready` 等待，而不是继续增大长度。

### 13.13 回抽每 100 mm 停顿

```ini
intermittent_retract: False
```

默认只保留快速段和最后慢速停放段。机械阻力较大时应先降低 `retract_fast_speed`，不要通过超长回抽掩盖料路问题。

### 13.14 上方传感器不触发

按顺序检查：

1. UI 中手动按压上方传感器是否变化。
2. 上方和下方传感器是否接反。
3. 耗材是否在五通、PTFE 接头或挤出机入口打滑/卡住。
4. `toolchange_load_length` 是否覆盖实测路径和合理打滑余量。
5. `feed_approach_length` 和慢速是否适合传感器附近结构。

失败应暂停打印，不应取消任务或无限补偿。

### 13.15 上方触发后下方不触发

上方触发只代表耗材到达挤出机入口。检查挤出机是否联动向下送料、齿轮是否夹住耗材、下方传感器方向和 `toolhead_sensor_max_feed_length`。不要把上方传感器当作已经到达喷嘴。

### 13.16 换料没有切刀或工具头走向错误位置

- 检查 `CUT_TIP` 是否仍被注释。
- 检查 `_ACE_PRE_TOOLCHANGE`、`CUT_TIP`、`_ACE_POST_TOOLCHANGE` 是否包含本机不需要的归零或坐标移动。
- 确认切刀坐标属于本机轴范围。
- 保持打印暂停，先手工确认真实耗材位置，再决定恢复。

驱动不会为不同 DIY 机器提供通用切刀坐标。

### 13.17 库存颜色或材料刷新后恢复

```bash
grep -Rni --include='*.cfg' '^\[save_variables\]' ~/printer_data/config
ls -l ~/printer_data/config/saved_variables.cfg
curl -fsS http://127.0.0.1:7125/server/ace/slots
```

确认只有一份 `[save_variables]`，保存文件可写，API 命令返回成功。前端编辑期间状态轮询不会覆盖正在输入的值；保存失败时应显示错误，而不是退回原始 G-code。

### 13.18 烘干状态或自动跟随状态不正确

- 检查 `/server/ace/status` 中 `auto_drying`、当前温度、目标温度和剩余时间。
- 确认材料名称能匹配 `material_N_name`。
- 检查 `max_dryer_temperature` 是否限制目标温度。
- 手动烘干不会被自动功能接管；打印中手动停止后，本次打印不会再次自动启动。
- 全部槽位为空时自动烘干不会启动。

### 13.19 自动探测不支持或结果过期

```bash
curl -fsS http://127.0.0.1:7125/server/ace/capabilities
```

确认能力列表包含 `ACE_CALIBRATE`、`ACE_CALIBRATION_SAVE`。旧 Moonraker 组件、旧驱动或只更新了前端会造成能力不一致，重新执行完整安装并重启 Klipper/Moonraker。

结果过期时核对管路、五通传感器和停放参数，确认上下传感器无料后重新探测并保存。

### 13.20 送料或回料达到绝对硬上限

先保留暂停状态并查看控制台报告的失败阶段。依次检查传感器是否触发、料路是否
堵塞、齿轮是否打滑，以及正常长度和硬上限之间是否留有合理余量。不要仅通过不断
增大硬上限继续尝试。

- 送料侧核对 `toolchange_load_length`、`feed_slip_compensation_length` 和
  `toolchange_feed_hard_limit`。
- 回料侧核对 `toolchange_retract_length`、停放/恢复路径和
  `toolchange_retract_hard_limit`。
- 上下传感器反复跳变时，分别检查对应引脚、电平和独立消抖项。
- 硬上限失败应暂停当前打印并保留恢复条件，不应出现 `CANCEL_PRINT`。

### 13.21 PolicyKit 警告

PolicyKit 警告会禁用 Moonraker 的服务重启、关机、重启或更新管理权限，但不等于 ACE 驱动本身加载失败。按 Moonraker 官方 PolicyKit 安装说明修复；在此之前使用 SSH 和 `sudo systemctl` 管理服务。

## 14. 发布来源与责任

- 主仓库：<https://github.com/Luomo520/ace-pro-control-center>
- 上游驱动：<https://github.com/szkrisz/ACEPROSV08>
- 参考项目：<https://github.com/Kobra-S1/ACEPRO>
- Fluidd：<https://github.com/fluidd-core/fluidd>
- Moonraker：<https://github.com/Arksine/moonraker>

许可证和完整修改边界见仓库根目录 `LICENSE` 与 `THIRD_PARTY_NOTICES.md`。本项目不提供跨机器通用的切刀坐标、引脚和路径长度；首次机械验证责任由安装者承担。
