# 快速开始

本页用于第一次安装 Ace Pro Control Center 第三代驱动。目标是先完成兼容性检查、安装和只读状态确认，不执行送料、回抽、切刀、烘干或自动换料。

完整参数与升级方法见[安装与升级](Installation-and-Upgrade)。准备启用任何物理动作前，必须阅读[安全与限制](Safety-and-Limitations)。

## 1. 准备工作

开始前确认：

- 打印机处于待机状态，没有正在打印、暂停或恢复中的任务。
- 已备份 `printer.cfg`、`moonraker.conf`、机器宏、Fluidd 自定义内容和可能存在的其他 ACE 配置。
- 打印机 Linux 主机可以访问 Ace Pro Control Center 源码目录。
- 已找到每台 ACE 的稳定串口路径，优先使用 `/dev/serial/by-id/`，不要使用可能随重启变化的 `/dev/ttyUSB0`。
- Klipper 实际运行 Python 为 `3.8` 或更高版本，并可导入 `pyserial 3.4` 或更高版本。
- 当前公开流程是全新安装；如果机器另有第三方 ACE 驱动，安装器发现冲突时会停止，不会覆盖现有文件。

## 2. 进入源码目录

首次安装先从正式仓库取得完整源码：

```bash
git clone https://github.com/Luomo520/ace-pro-control-center.git ~/ace-pro-control-center
cd ~/ace-pro-control-center
```

目录已存在时不要重复克隆；先确认其中没有需要保留的本地修改。

厂商固件、多 Klipper 实例或自定义目录不要依赖自动发现，参见[安装与升级](Installation-and-Upgrade#自定义目录与多实例)。

## 3. 只读兼容性检查

先检查 Klipper、运行时依赖和可选 Fluidd 源码，不写入任何文件：

```bash
./installer/install.sh --check-compatibility \
  --klipper-python ~/klippy-env/bin/python \
  --fluidd-mode auto
```

使用 Fluidd 源码集成时，可以追加：

```bash
--fluidd-source ~/fluidd-source
```

兼容性检查通过只表示所需目录、Python 运行环境和软件接口符合要求，不表示 ACE 已连接，也不表示物理动作已验证。

## 4. 先运行 dry-run

将占位路径替换为本机真实的稳定串口路径：

```bash
./installer/install.sh --dry-run --non-interactive \
  --device-count 1 \
  --device 'ace1|/dev/serial/by-id/REPLACE_WITH_STABLE_PATH'
```

`--dry-run` 会验证设备参数、配置冲突和安装计划，但不会写入目标文件。看到错误时先解决错误，不要跳过预检或手工覆盖安装器拒绝的文件。

## 5. 正式安装

使用与 dry-run 完全相同的设备顺序和参数，移除 `--dry-run`：

```bash
./installer/install.sh --non-interactive \
  --device-count 1 \
  --device 'ace1|/dev/serial/by-id/REPLACE_WITH_STABLE_PATH'
```

安装器将：

- 安装 Klipper extra、Moonraker 组件和 `/ace-v3/` 独立页面所需链接。
- 创建或升级唯一活动配置 `ace.cfg`。
- 在 `printer.cfg` 和 `moonraker.conf` 中维护 V3 托管块。
- 在兼容的 Fluidd 源码和所选模式允许时安装 Dashboard 卡片与 `#/acepro` 页面。

安装器不会重启 Klipper、Moonraker 或 Fluidd，也不会发送 G-code 或执行任何物理动作。

## 6. 检查默认安全状态

重启任何服务前，打开打印机配置目录中的 `ace.cfg`，确认至少满足：

```ini
[ace]
toolchange_mode: manual
```

```ini
[ace_device ace0]
physical_actions_enabled: False
```

同时检查：

- `serial` 是当前设备的稳定路径，不是文档占位符。
- 安装数量与实际设备数量一致。
- `printer.cfg` 只通过 `[include ace.cfg]` 加载活动 ACE 配置。
- 没有另外加载安装器生成范围之外的第二份 ACE 配置。
- 未经核对的传感器引脚、切刀坐标和移动样板仍保持未启用状态。

这里的“已配置”仅表示配置可被读取；保持上述默认值时，物理动作仍未启用。

## 7. 重启并完成只读验收

确认打印机仍处于待机状态后，使用该设备原有的服务管理方式重启 Klipper 和 Moonraker。源码方式集成 Fluidd 时，还需要按当前 Fluidd 版本自己的工具链重新构建并部署 `dist`。

重启后只检查以下项目：

1. Klipper 进入 `ready`，没有 ACE 配置错误。
2. Moonraker 正常运行，ACE 状态接口可用。
3. ACE 设备数量与实际安装数量一致。
4. ACE1 显示在线，四个槽位状态可读。
5. 传感器未配置时显示为未启用，不应造成 Klipper 启动失败。
6. Fluidd 原生集成可通过 `http://PRINTER_HOST/#/acepro` 打开；未使用原生集成时访问 `http://PRINTER_HOST/ace-v3/`。

此阶段不要点击送料、回抽、烘干、辅助送料或换料按钮。设备在线和状态可读属于只读验收，不代表物理动作已经启用或真机验证。

## 8. 认识手动模式中的 T 指令

在 `toolchange_mode: manual`、自动换料未配置或预检未通过时：

- `T0-T15` 和 `TR` 会被逐条忽略。
- 每条命令都会提示自动换料未配置或未就绪。
- 驱动不会暂停或拒绝当前打印，也不会改变当前工具和耗材路径。

因此，单色文件可以继续执行，但多色文件会在没有实际换料的情况下继续打印。自动换料完成本机验收前，不要开始多色打印。

## 9. 下一步

- 填写设备、传感器和路径参数：[配置说明](Configuration)
- 了解单 ACE 与多 ACE 路径：[多 ACE](Multi-ACE)
- 配置共享编码器：[传感器与编码器](Sensors-and-Encoder)
- 逐项完成机器动作后启用换料：[自动换料](Automatic-Toolchange)
- 出现启动、连接或界面问题：[故障排查](Troubleshooting)

不要直接把 `toolchange_mode` 改为 `automatic` 或把 `physical_actions_enabled` 改为 `True` 作为下一步。两者只是运行门禁，不会替代传感器、切刀、坐标和物理路径验收。
