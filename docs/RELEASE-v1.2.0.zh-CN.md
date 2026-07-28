# ACE Pro 管理中心 v1.2.0 重大更新

`v1.2.0` 是项目从“ACEPROSV08 的 Fluidd 卡片”升级为完整 **Ace Pro Control Center / ACE Pro 管理中心**后的首个正式版本。它同时包含增强 Klipper 驱动、Moonraker 受控 API、Fluidd 原生卡片、中文备用页面和事务式安装器。

项目仓库：[Luomo520/ace-pro-control-center](https://github.com/Luomo520/ace-pro-control-center)
完整教程：[安装、升级与恢复教程](https://github.com/Luomo520/ace-pro-control-center/blob/v1.2.0/docs/INSTALL.zh-CN.md)
驱动说明：[v1.2.0 功能与调校说明](https://github.com/Luomo520/ace-pro-control-center/blob/v1.2.0/docs/DRIVER-v1.2.0.zh-CN.md)

## 1. 重要变化

- 项目正式更名为 **Ace Pro Control Center / ACE Pro 管理中心**，默认安装目录变为 `~/ace-pro-control-center`。
- 本项目已经包含自己的 ACE 驱动，不再要求预先安装原版 `szkrisz/ACEPROSV08`。
- 安装器按全新安装处理，不扫描、迁移或删除 Kobra-S1、原版 ACEPROSV08 或其他 ACE 驱动。安装者必须自行确保 Klipper 只加载一套 `[ace]`。
- `~/printer_data/config/ace.cfg` 改为配置目录内的普通可写文件，解决 Fluidd 中带锁无法编辑的问题。
- Fluidd 所有 ACE 写操作只通过 Moonraker 白名单 API；API 不可用时停止并显示错误，不回退执行原始 G-code。
- 默认宏不会归零、移动、加热或执行切刀。`CUT_TIP` 必须根据本机结构填写。

## 2. 主要功能

- 单台 ACE Pro、T0-T3 四料槽库存、颜色、材料、喷嘴参考温度和耗材位置管理。
- 上方与下方耗材传感器独立显示，物理传感器状态优先于保存状态。
- 连续快速送料、末段慢速接近、有限打滑补偿和快速/慢速两阶段回抽。
- 换料阶段中文诊断，显示 `TA -> TB`、切刀、回抽、传感器触发和失败位置。
- USB 断联后的有界恢复，不盲目重放不确定的送料、回抽或切刀动作。
- 自动探测料管长度、可选五通传感器、预停放距离、冷态预装载和完整卸载。
- 自动跟随打印烘干：全部 PLA 45°C、PLA 混装 50°C、未知材料 45°C、高温材料 60°C，并受最高温度限制。
- Fluidd 原生卡片与 `/ace.html` 备用页面使用相同状态和受控命令。
- 完整安装、仅驱动、仅卡片、强制安装、最近回滚、首次基线恢复和卸载。

## 3. 支持范围

| 项目 | v1.2.0 支持情况 |
| --- | --- |
| 打印机 | DIY Klipper 3D 打印机 |
| ACE 数量 | 1 台 |
| 料槽 | T0-T3 四槽 |
| Fluidd | `v1.37.2` 完整构建验证 |
| 其他 Fluidd 版本 | 安装前提示风险，可取消或继续并保留回滚 |
| Moonraker | `0.9.3` 保守完整验证基线；使用包内 `ace_status` 第三方组件，不修改上游核心 |
| Kobra-S1/ACEPRO | 不兼容同时加载 |
| 原版 ACEPROSV08 | 不兼容同时加载 |

## 4. 安装前必须完成

1. 停止打印，确认没有送料、回抽、切刀、换料或烘干启动操作正在执行。
2. 备份 `~/printer_data/config`、当前 Fluidd、Moonraker 配置和现有 ACE 驱动。
3. 记录 ACE 的 `/dev/serial/by-id/...` 路径、上下传感器引脚、切刀坐标和耗材路径长度。
4. 检查 `printer.cfg` 及 include 文件，确保没有重复 `[ace]`、`[save_variables]`、`[respond]` 或同名宏。
5. 确认磁盘空间足够同时保存当前 Fluidd 和新 Fluidd 构建。

```bash
ls -l /dev/serial/by-id/
grep -Rni '^\[ace\]' ~/printer_data/config
grep -Rni '^\[save_variables\]' ~/printer_data/config
grep -Rni '^\[respond\]' ~/printer_data/config
```

## 5. 全新安装

```bash
cd ~
git clone --branch v1.2.0 --depth 1 \
  https://github.com/Luomo520/ace-pro-control-center.git \
  ace-pro-control-center-source
cd ace-pro-control-center-source
sh install.sh
```

字符安装器默认选项 `1` 同时安装驱动、配置、Moonraker 组件、Fluidd 卡片和备用页面。已有 `ace.cfg` 时会保留内容，并把新模板写入 `~/ace-pro-control-center/ace.cfg.example`。

源码目录必须与默认运行目录 `~/ace-pro-control-center` 分开。安装器会在任何归档或写入前拒绝两者相同或互相包含的危险路径，防止安装过程移动自身源码。

安装器不会自动重启服务，也不会执行送料、回抽、切刀、加热或工具切换。配置确认完成并确保打印机空闲后，再重启 Klipper 与 Moonraker。

## 6. 从旧版本升级

旧仓库地址会由 GitHub 重定向，但建议使用新目录重新克隆，避免旧安装目录、软链接和发布标签造成混淆：

```bash
cd ~
git clone --branch v1.2.0 --depth 1 \
  https://github.com/Luomo520/ace-pro-control-center.git ace-pro-control-center-v1.2.0
cd ace-pro-control-center-v1.2.0
sh install.sh
```

选择完整安装或仅驱动安装时，安装器会先解析现有 `ace.cfg` 的真实内容，再建立归档并转换成普通可写文件。不要提前手工删除旧软链接或旧配置，否则会丢失安装器自动恢复所需的来源。

如果旧系统同时加载其他 ACE 驱动，应先根据对应项目的卸载说明完成清理，并人工确认只剩一套 `[ace]`。本安装器不会代替用户卸载其他驱动。

## 7. 安装后配置

编辑：

```bash
nano ~/printer_data/config/ace.cfg
```

至少确认：

- `serial`
- `extruder_sensor_pin`
- `toolhead_sensor_pin`
- `toolchange_load_length`
- `toolchange_retract_length`
- `bowden_tube_length`
- `toolhead_sensor_to_nozzle`
- `_ACE_PRE_TOOLCHANGE`、`CUT_TIP`、`_ACE_POST_TOOLCHANGE`
- 可选五通传感器的引脚、电平、位置和停放偏移

切刀、传感器引脚和长度不能照抄其他打印机。默认切刀示例保持注释，必须按本机轴范围和机械结构填写。

## 8. 首次验证顺序

1. 检查 Klipper 和 Moonraker 能正常启动，Fluidd 基础页面可访问。
2. 打开 `http://打印机IP:7125/server/ace/status`，确认 API 返回状态而不是 404。
3. 打开 Fluidd ACE Pro 页面和 `http://打印机IP/ace.html`，确认两处状态一致。
4. 手动触发上下传感器，确认对应状态开关独立变化。
5. 在打印机空闲时进行短距离送料与回抽测试。
6. 空载检查切刀坐标和动作，不带耗材确认不会撞机。
7. 最后再执行一次完整换料，观察切刀、回抽、上方传感器、挤出机送料和下方传感器顺序。

任何阶段出现方向错误、传感器不触发、打滑或撞机风险，应立即停止，不要单纯增大距离掩盖配置错误。

## 9. 回滚与卸载

最近一次更新出现问题时：

```bash
sh ui-installer.sh --rollback-latest
```

完整卸载并恢复项目第一次写入前状态：

```bash
sh uninstall.sh
```

只恢复驱动或卡片：

```bash
sh ui-installer.sh --uninstall-driver
sh ui-installer.sh --uninstall-card
```

回滚和卸载前也会归档当前文件。归档默认位于：

```text
~/.local/share/ace-pro-control-center/old/
```

## 10. 已知边界

- 安装器通过 Git Bash 故障注入与混合安装顺序测试，并由 GitHub Actions 在 Ubuntu 上验证真实 POSIX 软链接恢复；其他发行版和文件系统仍需继续积累兼容结果。
- 非 Fluidd `v1.37.2` 或非 Moonraker `0.9.3` 只提供兼容风险提示和可回滚安装，不代表完整兼容认证。
- 自动测试不能验证切刀坐标、传感器电平、送料打滑、USB 供电或实际管路长度。
- 物理状态不确定时驱动优先暂停并报告位置，不会猜测耗材身份。

## 11. 验证记录

发布前已完成：Python 驱动与 Moonraker 测试、Web 行为测试、Fluidd 单元测试、类型检查、Lint、生产构建、安装器普通/分范围/失败恢复/事务故障/混合基线测试，以及发布清单 SHA-256 校验。标签创建前还会要求 GitHub Actions Ubuntu 原生 Linux 验证通过。

本项目按 GPL-3.0 发布，来源与修改边界见 [THIRD_PARTY_NOTICES.md](https://github.com/Luomo520/ace-pro-control-center/blob/v1.2.0/THIRD_PARTY_NOTICES.md)。
