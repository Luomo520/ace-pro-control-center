# Ace Pro Control Center | ACE Pro 管理中心

面向 DIY Klipper 打印机的单台 ACE Pro 四色管理系统。项目提供增强 Klipper 驱动、Moonraker 受控 API、Fluidd 原生卡片、备用 `/ace.html` 控制页，以及可安装、升级、回滚和卸载的一体化字符安装器。

本项目不是另一套打印机网站。日常入口是 Fluidd 中的 ACE Pro 导航页和仪表盘卡片；`/ace.html` 仅用于 Fluidd 页面不可用时的备用控制和诊断。

> [!IMPORTANT]
> v1.2.0 只支持一台 ACE Pro、T0-T3 四个料槽和 DIY Klipper 打印机。本项目不兼容 `Kobra-S1/ACEPRO`，也不能与原版 `szkrisz/ACEPROSV08` 同时加载。安装器不会扫描、迁移或删除其他 ACE 驱动，安装者必须先保证 Klipper 中只有一套 ACE 驱动和一个有效的 `[ace]`。

## 界面预览

### Fluidd ACE Pro 卡片

![ACE Pro Fluidd 卡片详细视图](docs/images/acepro-fluidd-card-detail.png)

### Fluidd 完整仪表盘

![ACE Pro 卡片在 Fluidd 仪表盘中的完整视图](docs/images/acepro-fluidd-dashboard-overview.png)

## 当前开发分支安全更新（未发布）

- `ace_config_version` 为配置结构提供兼容标识；缺少该键的旧配置按兼容模式加载，
  不要求为了升级而直接覆盖现有 `ace.cfg`。
- 上方与下方传感器分别使用 `extruder_sensor_debounce_count` 和
  `toolhead_sensor_debounce_count` 独立消抖，送料停止与工具头到达判定不再共用
  断料或五通传感器的消抖配置。
- `toolchange_feed_hard_limit` 和 `toolchange_retract_hard_limit` 为送料、补偿、回料
  与相关恢复路径提供独立绝对边界；达到硬上限会停止换料、保留失败阶段并暂停
  正在打印的任务，不会执行 `CANCEL_PRINT`。
- 本轮只记录静态部署验证，不代表已经完成送料、回抽、切刀或完整换料的真机
  动作测试。实际参数值以根目录 `ace.cfg` 为唯一来源。

## v1.2.0 重大更新

- **统一产品**：驱动、Moonraker API、Fluidd 卡片和备用页统一为 Ace Pro Control Center。
- **安全安装事务**：执行安装前归档，校验完整 `manifest.sha256`，先复制并验证旧文件，再替换目标；失败或中断时尝试恢复。
- **完整恢复路径**：支持完整安装、仅驱动、仅卡片、强制安装、最近一次回滚、首次安装基线卸载和状态检查。
- **配置可编辑**：`~/printer_data/config/ace.cfg` 安装为配置目录内的普通可写文件，修复目录外软链接导致的 Fluidd 锁图标。
- **Fluidd 原生卡片**：设备、四槽库存、双传感器、烘干、换料、无限续料、手动移动、自动探测和诊断集中在 Fluidd 内。
- **命令失败关闭**：Fluidd 和备用页只调用 Moonraker 白名单 API；API 404、网络错误、409 或 5xx 时不会退回发送原始 G-code。
- **连续送料和回料**：默认取消固定 50/100 mm 停顿，采用快速段、传感器接近段和有限打滑补偿。
- **换料安全状态机**：显示 `TA -> TB` 和失败阶段；不确定的切刀、送料或回抽不会盲目重放。
- **自动探测料管长度**：一次确认动作完成送料与回料探测，二次确认后才保存结果。
- **自动跟随打印烘干**：根据四槽材料决定安全温度，手动烘干始终保留用户所有权。
- **材料资料**：材料名称、烘干温度和喷嘴参考温度由 `ace.cfg` 成组定义，卡片与备用页读取同一来源。

完整能力和限制见 [功能与接口总览](docs/FEATURES.zh-CN.md)，参数与动作说明见 [驱动 v1.2.0 指南](docs/DRIVER-v1.2.0.zh-CN.md)，配置分区和五星必填项见 [配置文件规范](docs/ACE_CONFIG_SPECIFICATION.zh-CN.md)。

> 配置来源：仓库根目录 `ace.cfg` 是唯一可安装模板。配置规范只说明结构和
> 安全规则，`docs/templates/ace-config-section.template.ini` 只供维护者编写未来
> 功能区，二者都不能替代根模板或作为第二套机器参数来源。

## 兼容范围

| 项目 | v1.2.0 支持情况 |
| --- | --- |
| 打印机 | DIY Klipper 3D 打印机 |
| ACE Pro | 单设备 |
| 料槽 | T0-T3 四槽 |
| 驱动 | 本仓库内置 Ace Pro Control Center 驱动 |
| Moonraker | 保守完整验证基线为 `0.9.3`，本仓库内置 `ace_status` 组件 |
| Fluidd | 完整构建验证基线为 Fluidd v1.37.2 |
| 其他 Fluidd 版本 | 安装器提示风险，可取消、仅装驱动或继续并保留回滚来源 |
| 其他 ACE 驱动 | 不检测、不迁移、不可同时加载 |
| 多台 ACE Pro | 不支持 |

安装卡片会部署本项目基于 Fluidd v1.37.2 构建的完整前端。Fluidd 或 Moonraker 低于、高于或无法识别对应验证基线时，继续安装不代表已经获得完整兼容性保证。

## 新用户最短安装路径

### 1. 安装前确认

1. 停止打印，确认没有送料、回抽、切刀或工具切换正在运行。
2. 确认 Klipper、Moonraker 和 Fluidd 当前可以正常启动和访问。
3. 记录 ACE 串口、上方传感器引脚、下方传感器引脚和本机切刀坐标。
4. 确认配置中只存在一份 `[save_variables]`；需要冷态预装载时还应有一份 `[force_move] enable_force_move: True`。
5. 确认没有加载 `Kobra-S1/ACEPRO`、原版 `szkrisz/ACEPROSV08` 或其他 `[ace]` 驱动。
6. 使用安装 Klipper 的普通 Linux 用户登录；禁止执行 `sudo sh install.sh`，安装器会拒绝 root 身份。

```bash
ls -l /dev/serial/by-id/
grep -Rni --include='*.cfg' '^\[ace\]' ~/printer_data/config
grep -Rni --include='*.cfg' '^\[save_variables\]' ~/printer_data/config
grep -Rni --include='*.cfg' '^\[force_move\]' ~/printer_data/config
```

### 2. 通过 Git 下载

源码目录必须与安装后的运行目录分开。不要把仓库直接克隆到 `~/ace-pro-control-center`；该路径是安装器的默认部署目标。

安装固定的 v1.2.0：

```bash
cd ~
git clone --branch v1.2.0 --depth 1 \
  https://github.com/Luomo520/ace-pro-control-center.git \
  ace-pro-control-center-source
cd ~/ace-pro-control-center-source
sh install.sh
```

安装仓库当前 `main`：

```bash
cd ~
git clone --depth 1 \
  https://github.com/Luomo520/ace-pro-control-center.git \
  ace-pro-control-center-source
cd ~/ace-pro-control-center-source
sh install.sh
```

### 3. 选择安装范围

| 菜单 | 实际行为 |
| ---: | --- |
| 1 | 安装/更新完整组件：驱动、配置、Moonraker、Fluidd 卡片和备用页；已有 `ace.cfg` 时保留当前内容 |
| 2 | 仅安装/更新驱动和配置，并修复 `ace.cfg` 可编辑状态 |
| 3 | 仅安装/更新 Fluidd 卡片、Moonraker 组件和备用页 |
| 4 | 强制完整安装；只跳过兼容性阻断，不跳过哈希校验、归档或失败恢复 |
| 5 | 恢复最近一次安装前状态 |
| 6 | 卸载并恢复项目首次写入前状态 |
| 7 | 显示版本、路径、配置文件类型和五通传感器状态 |
| 8 | 退出 |

新用户通常选择 `1`。安装向导允许上下传感器引脚留空，但在填写它们之前不要重启 Klipper。

> [!WARNING]
> 卡片安装会整体替换 `~/fluidd`，只自动保留原 `config.json`。手工主题、插件和其他额外文件不会迁移，只能从 `~/.local/share/ace-pro-control-center/old/` 归档恢复。驱动安装可能向 Klipper Python 环境安装 `pyserial==3.5`，Python 依赖不属于文件回滚范围。

已有 `ace.cfg` 时默认使用 `preserve`：安装器会跳过传感器问答，不改写现有运行配置，并用安全空值生成新版 `ace.cfg.example`。安装后必须手动核对和编辑 `~/printer_data/config/ace.cfg`。

### 4. 填写配置

```bash
nano ~/printer_data/config/ace.cfg
```

至少实测并确认：

| 参数 | 含义 |
| --- | --- |
| `serial` | ACE 的 `/dev/serial/by-id/...` 稳定路径 |
| `extruder_sensor_pin` | 挤出机上方传感器 MCU 引脚 |
| `toolhead_sensor_pin` | 挤出机下方传感器 MCU 引脚 |
| `toolchange_load_length` | ACE 停放位置到上方传感器的最大送料距离 |
| `toolchange_retract_length` | 足以把耗材退回 ACE 并释放公共通道的回抽总距离 |
| `toolchange_feed_hard_limit` | 送料及补偿允许达到的绝对总上限，不能小于正常送料需求 |
| `toolchange_retract_hard_limit` | 回料及相关恢复路径允许达到的绝对总上限 |
| `bowden_tube_length` | ACE 出料口到五通进料口的实际 PTFE 长度 |
| `toolhead_sensor_to_nozzle` | 下方传感器到喷嘴的耗材路径长度 |
| `extruder_sensor_debounce_count` | 上方传感器到达/解除的独立连续确认次数 |
| `toolhead_sensor_debounce_count` | 下方传感器到达/解除的独立连续确认次数 |
| `sensor_trigger_grace_time` | 理论运动结束后继续监测传感器的时间，只延长监测而不追加移动距离 |
| `parking_sensor_pin` | 可选五通传感器引脚；没有传感器时保持注释 |
| `parking_sensor_clear_move_length` | 五通传感器解除后继续向 ACE 回抽的总距离 |
| `CUT_TIP` | 本机切刀坐标和动作；模板默认注释，不能照抄其他机器 |

耗材路径：

```text
送料：ACE T0-T3 -> 五通 -> 五通传感器（可选） -> 上方传感器 -> 挤出机 -> 下方传感器 -> 喷嘴
回收：喷嘴 <- 下方传感器 <- 挤出机 <- 上方传感器 <- 五通传感器（可选） <- 五通 <- ACE
```

### 5. 空闲时重启

安装器不会自动重启服务，也不会执行任何机械动作。确认打印机没有打印或暂停任务后：

```bash
sudo systemctl restart klipper
sudo systemctl restart moonraker
```

### 6. 无动作验证

```bash
sh ~/ace-pro-control-center-source/ui-installer.sh --status
test -f ~/printer_data/config/ace.cfg && \
  test ! -L ~/printer_data/config/ace.cfg && \
  test -w ~/printer_data/config/ace.cfg && echo 'ace.cfg 可编辑'
systemctl --no-pager --full status klipper moonraker
curl -fsS http://127.0.0.1:7125/server/ace/capabilities
curl -fsS http://127.0.0.1:7125/server/ace/status
```

浏览器入口：

```text
http://打印机IP/
http://打印机IP/ace.html
http://打印机IP:7125/server/ace/status
```

先确认 Fluidd、Moonraker API、ACE 连接和两个传感器状态正常，再由现场用户执行短距离送料、回抽、切刀空载检查和完整换料。安装器不会替用户触发这些动作。

当前开发分支的配置版本、独立消抖和绝对硬上限只完成静态部署验证；在现场用户
明确开始动作测试前，不应把“服务正常、配置可解析”描述为机械功能已经验证。

完整逐步教程见 [安装、配置、验证、升级、回滚、卸载与排障](docs/INSTALL.zh-CN.md)。

## 自动跟随打印烘干

- 全部 PLA：45°C。
- PLA 与其他材料混装：50°C，保护 PLA，并提示其他材料烘干效果可能受限。
- 未知材料：45°C，并提示烘干效果可能受限。
- 高温材料：60°C，包括 ABS、ABSCF、PETG、PAHTCF、PETCF 和 PEEK。
- 最终温度不会超过 `max_dryer_temperature`。
- 手动启动的烘干不会被自动停止，也不会被自动功能接管。
- 打印开始后自动启动；暂停时保持；完成、取消、错误或待机后停止自动拥有的任务。
- USB 断联或烘干命令失败不取消打印，驱动按 30 秒退避、最多三次重试。

完整状态机见 [自动跟随打印烘干流程](docs/AUTO_DRYING_FLOW.zh-CN.md)。

## 自动探测、预装载和完全卸载

普通 T0-T3 始终送入喷嘴。`ACE_PRELOAD` 是待机维护命令，只冷态送到下方传感器，不能替代正常换料。

开始自动探测前，打印机必须待机、ACE 已连接并处于就绪状态，而且上下传感器必须均无料。优先使用 Fluidd 卡片中的“自动探测料管长度”；动作开始和保存结果会分别确认。

```text
ACE_CALIBRATE INDEX=n CONFIRM=1
ACE_CALIBRATION_SAVE CONFIRM=1
ACE_CALIBRATION_CANCEL
ACE_PRELOAD INDEX=n CONFIRM=1
ACE_FULL_UNLOAD INDEX=n CONFIRM=1
```

高级诊断还可分别运行：

```text
ACE_CALIBRATE_FEED INDEX=n CONFIRM=1
ACE_CALIBRATE_RETRACT CONFIRM=1
```

有五通传感器时，界面显示“上方传感器到五通传感器”和“上方传感器到五通停放点”；没有五通传感器时显示“上方传感器到内部停放点”。状态 `preload_parked_estimated` 只表示估算的预停放位置，不是毫米级绝对位置。

修改 `bowden_tube_length`、五通传感器模式、停放偏移或标定格式后，旧结果会过期。旧版位置状态升级时只迁移当前唯一能确认的槽位，其他槽位标记为 `unknown`。

## 升级

源码目录跟随 `main`：

```bash
cd ~/ace-pro-control-center-source
git pull --ff-only
sh install.sh
```

切换到固定标签：

```bash
cd ~/ace-pro-control-center-source
git fetch --tags --force
git checkout v1.2.0
sh install.sh
```

菜单 `1` 默认保留当前 `ace.cfg`。新版模板始终写入 `~/ace-pro-control-center/ace.cfg.example`；只有明确执行以下命令，或为自动化设置 `ACE_CC_CONFIG_MODE=replace`，才会用新模板替换运行配置：

```bash
sh ui-installer.sh --install-new-config
```

`ACE_CC_CONFIG_MODE` 只允许 `preserve` 或 `replace`。`replace` 会覆盖现有运行配置，只应在已经备份并准备重新填写所有机器参数时使用。

直接使用 CLI 执行安装、替换配置、回滚或卸载时仍会要求确认；只有把 `--yes` 放在操作参数前才跳过确认。非交互普通安装遇到 Fluidd/Moonraker 版本风险会失败，只有明确使用 `--install-force` 才继续完整安装。

## 回滚与卸载

安装、回滚和卸载前都会建立归档：

```text
~/.local/share/ace-pro-control-center/old/YYYYMMDD-HHMMSS-PID/
```

最近一次回滚：

```bash
cd ~/ace-pro-control-center-source
sh ui-installer.sh --rollback-latest
```

根据提示确认，或在无人值守且已经核对归档时执行 `sh ui-installer.sh --yes --rollback-latest`。

卸载并恢复首次安装前基线：

```bash
cd ~/ace-pro-control-center-source
sh uninstall.sh
```

仅恢复驱动或卡片范围：

```bash
sh ui-installer.sh --uninstall-driver
sh ui-installer.sh --uninstall-card
```

回滚和卸载同样不会自动重启服务。完成后先确认打印机空闲，再重启 Klipper 和 Moonraker。

## 常见故障快速入口

| 症状 | 第一处理步骤 |
| --- | --- |
| Fluidd 空白 | 不执行机械动作，运行 `--rollback-latest`，再检查 Fluidd 版本、文件权限和 Service Worker 缓存 |
| Fluidd 无 ACE 卡片 | 确认安装范围包含卡片，检查 Moonraker `[ace_status]` 和浏览器缓存 |
| `/server/ace/status` 404 | 检查 `ace_status.py` 是否安装并确认 Moonraker 已重启 |
| `ace.cfg` 带锁 | 重新选择完整安装或仅驱动安装，将旧外部软链接转换为普通可写文件 |
| Klipper 无法启动 | 检查重复 `[ace]`、重复宏、串口路径和上下传感器引脚 |
| 固定距离停顿 | 检查 `intermittent_feed: False` 和 `intermittent_retract: False` |
| 换料失败 | 保持暂停，按控制台阶段检查切刀、上下传感器、实际耗材位置和 USB，不盲目重复 T 命令 |
| 保存库存后恢复旧值 | 检查 `[save_variables]` 是否唯一、`saved_variables.cfg` 是否可写以及 API 返回值 |
| 探测结果过期 | 核对管路和五通参数，确认传感器无料后重新探测并保存 |

详细命令、日志位置和分支处理见 [安装教程的排障章节](docs/INSTALL.zh-CN.md#13-排障手册)。

## 项目来源与许可证

本仓库是社区衍生项目，不是 Anycubic、Fluidd、Moonraker 或上游驱动作者的官方发布。

| 项目 | 许可证 | 用途 |
| --- | --- | --- |
| [szkrisz/ACEPROSV08](https://github.com/szkrisz/ACEPROSV08) | GPL-3.0 | 驱动、串口协议、G-code 和配置结构的上游基础 |
| [Kobra-S1/ACEPRO](https://github.com/Kobra-S1/ACEPRO) | GPL-3.0 | 参考网页交互、中文流程和料卷视觉样式 |
| [fluidd-core/fluidd](https://github.com/fluidd-core/fluidd) | GPL-3.0 | Fluidd 页面、卡片、导航、主题和构建体系 |
| [Moonraker](https://github.com/Arksine/moonraker) | GPL-3.0 | 状态与受控命令接口 |
| [Vue](https://github.com/vuejs/core) | [MIT](licenses/Vue-MIT.txt) | 备用页面运行时 |

项目以 [GNU GPL v3.0](LICENSE) 发布。分发修改版本时必须保留对应源代码、许可证和上游来源。完整声明见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。

## 文档导航

- [v1.2.0 重大更新与发布说明](docs/RELEASE-v1.2.0.zh-CN.md)
- [从零安装、升级、回滚、卸载与排障](docs/INSTALL.zh-CN.md)
- [完整功能和接口边界](docs/FEATURES.zh-CN.md)
- [驱动 v1.2.0 参数与调校](docs/DRIVER-v1.2.0.zh-CN.md)
- [ACE 配置文件规范](docs/ACE_CONFIG_SPECIFICATION.zh-CN.md)
- [ACE 配置功能区编写模板](docs/templates/ace-config-section.template.ini)
- [自动跟随打印烘干流程](docs/AUTO_DRYING_FLOW.zh-CN.md)
- [项目记忆与当前状态](docs/PROJECT_MEMORY.zh-CN.md)
- [产品决策记录](docs/DECISIONS.zh-CN.md)
- [开发、测试、构建与发布手册](docs/DEVELOPMENT.zh-CN.md)
- [文档总索引](docs/DOCUMENTATION_INDEX.zh-CN.md)
- [产品待办与优先级](docs/PRODUCT_BACKLOG.zh-CN.md)
- [多智能体工作单模板](docs/WORK_ORDER_TEMPLATE.zh-CN.md)
- [更新日志](CHANGELOG.md)
- [第三方来源声明](THIRD_PARTY_NOTICES.md)
- [GPL-3.0 许可证](LICENSE)

## 安全与责任

软件无法自动知道每台 DIY 打印机的切刀坐标、轴范围、传感器电平、管路长度和堵料状态。错误配置可能造成磨料、堵料、切刀或工具头碰撞以及打印失败。首次动作验证必须由了解机器结构、能随时断电或急停的现场用户完成。
