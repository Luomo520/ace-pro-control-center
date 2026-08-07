# 安装与升级

本页说明 Ace Pro Control Center 第三代驱动的全新安装、重复安装、设备增删、Fluidd 集成和卸载，并另行保留项目维护者使用的历史测试配置迁移方法。所有写入操作都应在打印机待机时进行，并在开始前备份现有配置。

第一次使用建议先按[快速开始](Quick-Start)完成无动作安装。任何物理动作的启用条件见[安全与限制](Safety-and-Limitations)。

> **公开发行前提：** GitHub 用户均按全新安装处理，不需要卸载 V2，也不需要准备 `ace_hardware.cfg` 或 `ace_machine.cfg`。历史迁移章节只服务于项目当前测试机和内部预发布环境。

## 安装器会修改什么

安装器负责：

- 链接 V3 Klipper package extra 和兼容 wrapper。
- 链接 Moonraker `ace_status` 组件。
- 安装 `/ace-v3/` 独立页面文件。
- 创建或升级打印机配置目录中的 `ace.cfg`。
- 在 `printer.cfg` 和 `moonraker.conf` 中维护带标记的 V3 配置块。
- 根据 Fluidd 模式选择原生源码集成或独立页面。

安装器不会：

- 自动升级 Klipper、Moonraker、Python、pyserial、Node 或 Fluidd。
- 自动重启任何服务。
- 发送 G-code，或执行送料、回抽、切刀、烘干、校准和换料动作。
- 静默删除 ACE V2 或覆盖无法确认归属的旧文件。

## 持久安装前快照与恢复

正式安装、升级、重装或增删设备在第一次写入前必须创建带时间戳的持久快照。快照与安装事务的临时回滚目录作用不同：

- 临时回滚目录只用于本次安装失败时自动撤销，事务结束后可以清理。
- 持久快照在安装成功后仍保留，供用户在后续发现问题时人工恢复。
- 快照应覆盖本次实际修改的 Klipper、Moonraker、Fluidd、ACE 配置、托管块、链接和安装清单，并保存来源路径与校验值。
- 安装器结束时必须打印快照路径、恢复命令、恢复范围和校验结果；没有这些信息时，不要继续重启服务或执行物理动作。

恢复前先确认打印机待机并停止相关服务，使用安装器输出的原始恢复命令，不要猜测快照目录结构。恢复后检查 `printer.cfg`、`moonraker.conf`、`ace.cfg`、Klipper extra、Moonraker component 和 Fluidd 入口是否来自同一快照，再按本机方式启动服务。恢复只应影响该次安装管理的内容，不应删除快照外的用户文件。

## 系统要求

- Klipper 实际运行 Python `>=3.8`。
- Klipper Python 环境可导入 `pyserial >=3.4`。
- Klipper 源码包含 V3 所需的配置、G-code、Reactor、对象注册和事件 API。
- Klipper `klippy/extras`、Moonraker components、配置目录和 Fluidd 静态目录可写。
- 每台 ACE1 都有稳定且独占的串口路径；ACE2 可共享稳定串口和 `bus_id`，但每台必须使用唯一 `device_uid`。

已通过能力探测的上游 Klipper 基线为 `v0.10.0`、`v0.11.0`、`v0.12.0`、`v0.13.0` 和提交 `d865997`。厂商固件即使显示相同版本号，也必须重新通过实际 API 与运行环境检查。

## 兼容性检查

首次安装先取得完整源码：

```bash
git clone https://github.com/Luomo520/ace-pro-control-center.git ~/ace-pro-control-center
cd ~/ace-pro-control-center
```

只检查，不写入：

```bash
cd ~/ace-pro-control-center
./installer/install.sh --check-compatibility \
  --klipper-python ~/klippy-env/bin/python \
  --fluidd-mode auto
```

需要检测 Fluidd 源码集成时追加：

```bash
--fluidd-source ~/fluidd-source
```

兼容性检查成功属于“软件接口已配置并符合要求”，不等于 ACE 功能已启用，更不等于物理动作已真机验证。

## 设备参数格式

安装器按 `--device` 出现顺序生成 `ace0` 至 `ace3`：

| 型号 | 格式 | 说明 |
| --- | --- | --- |
| ACE1 | `ace1|SERIAL` | `SERIAL` 使用稳定的 `/dev/serial/by-id/` 路径 |
| ACE2 | `ace2|SERIAL|BUS_ID|UID` | `BUS_ID` 和明确的 `UID` 都必须提供 |

ACE2 当前拒绝 `device_uid: auto`。自动发现结果尚不能作为安全持久身份，必须填写明确 UID。

设备顺序决定固定工具映射：

| 设备 | 工具号 |
| --- | --- |
| `ace0` | `T0-T3` |
| `ace1` | `T4-T7` |
| `ace2` | `T8-T11` |
| `ace3` | `T12-T15` |

升级或增删设备时不要随意调换已有设备顺序。稳定串口和 UID 用于保留设备身份与安全开关，工具号仍由最终配置顺序决定。

## 新安装示例

### 单台 ACE1

先 dry-run：

```bash
./installer/install.sh --dry-run --non-interactive \
  --device-count 1 \
  --device 'ace1|/dev/serial/by-id/REPLACE_WITH_ACE_ONE'
```

确认输出无误后正式安装：

```bash
./installer/install.sh --non-interactive \
  --device-count 1 \
  --device 'ace1|/dev/serial/by-id/REPLACE_WITH_ACE_ONE'
```

### 两台 ACE1

```bash
./installer/install.sh --dry-run --non-interactive \
  --device-count 2 \
  --device 'ace1|/dev/serial/by-id/REPLACE_WITH_ACE_ONE' \
  --device 'ace1|/dev/serial/by-id/REPLACE_WITH_ACE_TWO'
```

### ACE1 与 ACE2

```bash
./installer/install.sh --dry-run --non-interactive \
  --device-count 2 \
  --device 'ace1|/dev/serial/by-id/REPLACE_WITH_ACE_ONE' \
  --device 'ace2|/dev/serial/by-id/REPLACE_WITH_ACE_TWO|ace2bus0|REPLACE_WITH_EXPLICIT_UID'
```

### 两台 ACE2

```bash
./installer/install.sh --dry-run --non-interactive \
  --device-count 2 \
  --device 'ace2|/dev/serial/by-id/REPLACE_WITH_ACE_ONE|ace2bus0|REPLACE_WITH_UID_ONE' \
  --device 'ace2|/dev/serial/by-id/REPLACE_WITH_ACE_TWO|ace2bus1|REPLACE_WITH_UID_TWO'
```

最多可配置 4 台设备，继续重复 `--device`，并使 `--device-count` 与参数数量完全一致。先使用 `--dry-run`；确认后使用同一条命令移除 `--dry-run`。

ACE2 和多 ACE 的配置能力不代表物理动作已验收。ACE2 物理动作在当前版本中由协议层和管理层强制拒绝；多 ACE 两级路径尚未完成真机物理动作验收。

## 默认运行状态

全新安装会写入：

```ini
[ace]
toolchange_mode: manual
```

每台新 ACE1 默认写入：

```ini
physical_actions_enabled: False
```

`manual` 控制自动换料模式，`physical_actions_enabled` 控制单台设备能否执行物理动作。两者独立，安装器不会因为设备在线、配置存在或重复安装而自动打开它们。

## 自定义目录与多实例

安装器默认查找常见 Klipper、Moonraker、配置和 Fluidd 目录。厂商固件或多实例环境应明确指定路径：

```bash
./installer/install.sh --dry-run --non-interactive \
  --klipper-home /path/to/klipper \
  --moonraker-home /path/to/moonraker \
  --config-dir /path/to/printer_config \
  --fluidd-home /path/to/fluidd \
  --klipper-python /path/to/klipper-python \
  --device-count 1 \
  --device 'ace1|/dev/serial/by-id/REPLACE_WITH_STABLE_PATH'
```

同一个 Klipper checkout 被多个打印机实例共享时，不要让不同实例分别管理和卸载同一组 extra。先确认每个实例对应的 checkout、配置目录和 Python 环境。

## Fluidd 安装模式

| 模式 | 行为 |
| --- | --- |
| `auto` | 默认；兼容时安装原生卡片和页面，不兼容时保留 `/ace-v3/` 独立页面 |
| `source` | 强制源码集成；版本或源码能力不匹配时在写入前失败 |
| `standalone` | 不修改 Fluidd 源码，只安装 `/ace-v3/` 独立页面 |

使用源码集成：

```bash
./installer/install.sh \
  --fluidd-mode auto \
  --fluidd-source ~/fluidd-source \
  ...
```

原生源码集成目前覆盖官方 Fluidd `1.34.x-1.37.x`，并继续检查实际源码锚点。安装器完成补丁后，必须使用该 Fluidd 版本声明的 Node 和包管理器重新构建，并部署生成的 `dist`。

源码模式的完成顺序固定为：

1. 检查 Fluidd 版本、源码锚点、Node 和包管理器。
2. 应用 V3 overlay，并确认没有路由或组件冲突。
3. 使用目标 Fluidd 自带的锁文件和构建命令完成生产构建。
4. 将新生成的 `dist` 部署到实际 Web 根目录，不要只保留在源码目录。
5. 清理浏览器缓存后验证 Dashboard 卡片、`#/acepro`、侧栏入口和单 ACE 工具裁剪。
6. 保留 `/ace-v3/`，用于构建失败、缓存问题和后端独立诊断。

源码补丁成功不等于原生界面已经部署。构建或 `dist` 部署失败时，应停止并使用持久快照恢复 Fluidd 源码或产物；后端安装可继续使用 `standalone` 模式，但不得宣称原生卡片可用。

对于更旧、更新或厂商修改过的未知源码，`auto` 会回退到独立页面，不应影响 Klipper 驱动安装；`source` 会停止；`standalone` 始终不改 Fluidd 源码。

## 历史测试版本迁移（普通用户跳过）

本节不属于 GitHub 公开用户的安装步骤。只有项目当前测试机或曾参与内部预发布测试的环境才可能出现以下文件；全新安装用户直接跳到[升级、重装和增删设备](#升级重装和增删设备)。

V3 不会静默覆盖 V2。检测到以下内容时安装会停止：

- 旧 `klippy/extras/ace.py`。
- 未由 V3 管理的 Moonraker ACE 组件或 `[ace_status]` 配置节。
- 不能确认是 V3 的现有 `ace.cfg`。
- 与 V3 冲突的旧工具宏或活动 include。

正确顺序：

1. 备份完整打印机配置和现有 Fluidd 自定义内容。
2. 使用 V2 自身的卸载说明移除旧驱动链接、组件和活动 include。
3. 保留备份，不要把 V2 文件直接改名冒充 V3 配置。
4. 运行 V3 `--check-compatibility`。
5. 运行 V3 `--dry-run`，解决全部冲突后再正式安装。

V3 旧拆分配置的迁移规则与 V2 冲突处理不同：

- 旧 `ace_hardware.cfg` 只读取一次，有效设备身份、通信参数和安全开关会合并到 `ace.cfg`。
- 迁移后的 `ace_hardware.cfg` 归档到配置目录的 `.ace-driver-v3/legacy/`，不得继续 include。
- 旧 `ace_machine.cfg` 中可迁移的坐标、校准值和用户宏会并入 `ace.cfg`，随后退出运行链。
- 最终活动链应为 `printer.cfg -> ace.cfg`。

## 升级、重装和增删设备

使用新版本源码重新运行安装命令即可升级现有 V3。安装器会按稳定硬件身份保留：

- `enabled`
- `rfid_enabled`
- `physical_actions_enabled`
- 运行模式、引脚、距离、坐标和用户自定义宏

增加、删除、替换 ACE 或改变组合时，重新运行安装器并提供最终完整设备列表。先运行 `--dry-run`，检查工具映射和设备身份，再正式执行。新设备不会继承被删除设备的物理动作授权。

不要手工编辑 `ace.cfg` 中带有 V3 硬件拓扑开始和结束标记的安装器托管区域。运行参数、传感器、机器宏和校准内容应在相应用户配置区域修改，详见[配置说明](Configuration)。

## 安装后检查

安装器结束后先不要重启服务，检查：

1. `ace.cfg` 中的串口、型号、数量和顺序正确。
2. 新设备保持 `physical_actions_enabled: False`。
3. `[ace]` 保持 `toolchange_mode: manual`。
4. `printer.cfg` 只加载 `ace.cfg`，没有活动的旧拆分配置。
5. 未核对的传感器引脚和机器坐标没有被意外启用。
6. 打印机处于待机状态。
7. 安装器已经输出可读取的持久快照路径、恢复命令、恢复范围和校验结果。
8. 源码模式已经构建并部署 `dist`；只应用 overlay 时仍视为未完成。

随后使用本机原有方式重启 Klipper 和 Moonraker，只进行连接、状态、槽位和页面检查。源码集成 Fluidd 时完成构建部署。物理动作应按[安全与限制](Safety-and-Limitations)逐项验收。

## 卸载

```bash
./installer/uninstall.sh
```

卸载只移除 V3 自身管理的链接和配置块，保留用户的 `ace.cfg`、`.ace-driver-v3/legacy/` 迁移归档和其他配置。卸载器同样不会重启服务。

卸载后检查 Klipper 和 Moonraker 配置，再按设备原有方式重启服务。需要恢复旧版本时，只能使用安装前备份和对应版本的恢复说明，不要同时加载 V2 与 V3。
